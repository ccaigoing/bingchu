"""公网护栏：按 IP 限流 + 推理并发闸门。

本机开发时这个模块整个可以不存在。一旦挂到公网上、并且**允许任何人上传**，
它就是必需品 —— 因为这台机器是 2 核 CPU 跑一个 436MB 的模型。

## 两个不同的问题，别混为一谈

    限流（RateLimiter）      防的是**单个人刷太多**。是配额问题。
    并发闸门（inference_slot）防的是**多人同时刷**。是资源争抢问题。

只做限流不做闸门，10 个不同 IP 各发 1 个请求照样把 CPU 打满；
只做闸门不做限流，一个人慢慢发也能把磁盘和数据库写爆。两个都要。

## ⚠️ 单进程假设

限流计数和信号量都是**进程内**的。uvicorn 开多 worker 时每个进程各有一份，
实际额度会翻成 worker 数倍。当前部署刻意用单进程（2 核机器上多进程没意义，
每个进程都要把 436MB 权重载进内存，反而更容易 OOM），所以这里的实现成立。
**要改成多进程，必须先把这两样换成 Redis 之类的共享存储。**
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from fastapi import Request

from ..config import INFER_CONCURRENCY, RATE_PER_DAY, RATE_PER_MIN

logger = logging.getLogger(__name__)

# 固定窗口的长度（秒）
_MINUTE = 60.0
_DAY = 86400.0

# 多久做一次过期清理（秒）。不清的话，被刷时字典会随 IP 数无限增长 ——
# 那本身就是一种内存耗尽攻击。
_SWEEP_INTERVAL = 60.0

# 字典条数的硬上限。超过就**整表清空**而不是逐条淘汰 ——
# 走到这一步说明正在被大规模刷，此时"少拦几个人"远不如"别把内存吃光"重要。
_MAX_TRACKED_IPS = 10_000


def client_ip(request: Request) -> str:
    """访客真实 IP。

    ⚠️ 这是整条链路上最容易做错的一处。反代之后 `request.client.host`
    是 **nginx 的地址**（127.0.0.1），**对所有访客都一样** ——
    直接拿它当限流键，第 15 个请求开始就是**全部访客一起被拒**，
    而且现场表现是"用着用着就 429 了"，极难联想到是取错了 IP。

    所以优先读 `X-Forwarded-For` 的**第一跳**。

    前提是 nginx 用 `proxy_set_header X-Forwarded-For $remote_addr;`
    **覆盖**而不是追加。若写成 nginx 默认的 `$proxy_add_x_forwarded_for`，
    它会把访客自带的 XFF 头原样接在前面 —— 访客随手伪造一个，
    就能每次换一个"IP"，限流形同虚设。见 deploy/nginx.conf 里的同名注释。
    """
    xff = request.headers.get("x-forwarded-for")
    if xff:
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


@dataclass
class _Window:
    """一个固定窗口的计数。"""

    start: float
    count: int = 0


@dataclass
class RateLimiter:
    """按 IP 的固定窗口限流。

    两个窗口各自独立判定，**任一超限即拒绝** ——
    「1 分钟 15 次」挡瞬间并发，「1 天 300 次」挡慢速刷。
    """

    per_min: int = RATE_PER_MIN
    per_day: int = RATE_PER_DAY
    _minute: dict[str, _Window] = field(default_factory=dict)
    _day: dict[str, _Window] = field(default_factory=dict)
    _last_sweep: float = 0.0
    rejected_total: int = 0

    def _sweep(self, now: float) -> None:
        """丢掉过期的窗口。隔一段时间做一次，不是每次请求都做。"""
        if now - self._last_sweep < _SWEEP_INTERVAL:
            return
        self._last_sweep = now
        if len(self._minute) > _MAX_TRACKED_IPS or len(self._day) > _MAX_TRACKED_IPS:
            self._minute.clear()
            self._day.clear()
            return
        self._minute = {
            ip: w for ip, w in self._minute.items() if now - w.start < _MINUTE
        }
        self._day = {ip: w for ip, w in self._day.items() if now - w.start < _DAY}

    def check(self, ip: str, now: float | None = None) -> tuple[bool, int]:
        """记一次并判定。返回 `(是否放行, 拒绝时还需等待的秒数)`。

        放行时也会计数 —— 配额是按"请求数"算的，不是按"被拒次数"。
        """
        now = time.time() if now is None else now
        self._sweep(now)

        m = self._minute.get(ip)
        if m is None or now - m.start >= _MINUTE:
            m = _Window(start=now)
            self._minute[ip] = m
        d = self._day.get(ip)
        if d is None or now - d.start >= _DAY:
            d = _Window(start=now)
            self._day[ip] = d

        m.count += 1
        d.count += 1

        if self.per_min > 0 and m.count > self.per_min:
            self.rejected_total += 1
            return False, max(1, int(_MINUTE - (now - m.start)) + 1)
        if self.per_day > 0 and d.count > self.per_day:
            self.rejected_total += 1
            return False, max(1, int(_DAY - (now - d.start)) + 1)
        return True, 0

    def snapshot(self) -> dict:
        """给 /api/health 看的可观测状态。答辩时能直接展示"护栏在工作"。"""
        return {
            "perMinute": self.per_min,
            "perDay": self.per_day,
            "trackedIps": len(self._day),
            "rejectedTotal": self.rejected_total,
        }


# 模块级单例：只作用于 POST /api/detect 这一条**昂贵**路径。
# 其余 /api/* 是读数据库的轻请求（毫秒级），给它们上同样的配额只会
# 让正常浏览被误伤，而它们本身不构成资源风险。真正要保护的只有推理。
limiter = RateLimiter()


# ── 推理并发闸门 ─────────────────────────────────────────────
#
# 同一时刻最多 INFER_CONCURRENCY 个推理在跑，多出来的在门口**排队**。
#
# 为什么排队比直接放行好：排队的时间是**有上限**的（并发数 × 单次耗时），
# 而让它们一起抢 CPU 是**没有上限**的 —— 每个请求都变慢，然后互相拖到超时，
# 最后全部失败。访客看到的现象是"服务器挂了"，而不是"有点慢"。
#
# asyncio 原语在 3.10+ 是惰性绑定事件循环的，模块导入时创建不需要已有 loop。
inference_slot = asyncio.Semaphore(INFER_CONCURRENCY)


@asynccontextmanager
async def inference_turn(label: str = "") -> AsyncIterator[None]:
    """占一个推理位，用完自动释放（含抛异常时）。

    排队超过 1 秒记一条日志。**不是噪音**：没有这条日志，"排队"是隐形的 ——
    出问题时只能看到"变慢了"，看不到"因为有人在排队"，会往错的方向查。
    """
    t0 = time.perf_counter()
    async with inference_slot:
        waited = time.perf_counter() - t0
        if waited > 1.0:
            logger.info(
                "推理排队 %.1fs（并发上限 %d）%s",
                waited, INFER_CONCURRENCY, f" · {label}" if label else "",
            )
        yield
