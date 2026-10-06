"""上传图的过期清理。

公网开放上传之后，`server/static/uploads/` 只会涨不会跌 —— 每张图 10MB 封顶，
有人刷几天就能把磁盘吃满，而磁盘满了 SQLite 会写不进去，整个系统跟着挂。
这个模块就是那条底线。

## 只删图片，不删记录

`detection_records` 是答辩要根据"识别记录表"看的东西，让它随时间凭空消失，
比图片 404 严重得多。所以这里只做两件事：

    1. 删掉超过保留期的图片文件
    2. 把**确实被删掉的那几张图**对应的 `image_url` / `annotated_url` 置 NULL

## ⚠️ 第 2 步为什么不用"文件不存在就置 NULL"

那样写更简单，但会误伤：种子记录的 URL 指向的图**本来就不在 uploads 里**
（它们来自 `disease_samples`），一律扫一遍会把 6 条演示记录全清空 ——
部署完第一次跑清理，概览和识别屏的图就全没了，而且看起来像是"清理的锅"。

所以这里只处理**本次真正 unlink 成功的文件**，逐条精确匹配。宁可漏（下次再扫），
不可错杀。
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..config import (
    CLEANUP_INTERVAL_HOURS,
    UPLOAD_ANNOTATED_DIR,
    UPLOAD_ORIG_DIR,
    UPLOAD_RETENTION_DAYS,
)
from ..db import get_conn

logger = logging.getLogger(__name__)


def sweep(
    retention_days: int = UPLOAD_RETENTION_DAYS,
    *,
    now: float | None = None,
) -> dict:
    """删一轮过期图片。同步函数，调用方负责丢线程池（会做磁盘 IO）。

    返回统计字典，给日志和 /api/health 用。
    """
    if retention_days <= 0:
        # 0 / 负数 = 显式关闭。**必须返回 enabled=False 而不是静默跳过** ——
        # 否则关掉清理之后，"怎么没清理"要靠读代码才能回答。
        return {"enabled": False, "scanned": 0, "deleted": 0, "retentionDays": retention_days}

    now = time.time() if now is None else now
    cutoff = now - retention_days * 86400.0

    scanned = 0
    deleted_urls: list[str] = []

    for directory, kind in ((UPLOAD_ORIG_DIR, "orig"), (UPLOAD_ANNOTATED_DIR, "annotated")):
        if not directory.exists():
            continue
        for path in directory.iterdir():
            if not path.is_file():
                continue
            scanned += 1
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                path.unlink()
            except OSError as exc:
                # 单个文件删不掉（被占用 / 权限）不该中断整轮清理，下轮再来
                logger.warning("删除过期图片失败 %s：%s", path.name, exc)
                continue
            deleted_urls.append(f"/uploads/{kind}/{path.name}")

    if deleted_urls:
        # 精确匹配本次删掉的那些 URL，逐条置 NULL —— 见模块 docstring
        with get_conn() as conn:
            conn.executemany(
                "UPDATE detection_records SET image_url = NULL WHERE image_url = ?",
                [(u,) for u in deleted_urls],
            )
            conn.executemany(
                "UPDATE detection_records SET annotated_url = NULL WHERE annotated_url = ?",
                [(u,) for u in deleted_urls],
            )

    stats = {
        "enabled": True,
        "scanned": scanned,
        "deleted": len(deleted_urls),
        "retentionDays": retention_days,
    }
    if deleted_urls:
        # 只在真删了东西时打日志 —— 每 6 小时一条"删了 0 个"会把日志淹掉
        logger.info(
            "清理过期上传图：扫 %d 个，删 %d 个（保留 %d 天）",
            scanned, len(deleted_urls), retention_days,
        )
    return stats


async def cleanup_loop(interval_hours: int = CLEANUP_INTERVAL_HOURS) -> None:
    """后台协程：立刻扫一次，之后每 interval_hours 小时扫一次。

    为什么**先扫再睡**而不是先睡：服务停机几周再启动时，磁盘上积压的过期图
    应该马上被清掉，而不是再等一个周期。停机越久越需要立刻清理，
    这个顺序恰好对上。

    由 lifespan 用 asyncio.create_task 起，取消即退出。
    """
    interval = max(1, interval_hours) * 3600.0
    while True:
        try:
            # 同步磁盘 IO + SQLite 写，丢线程池，别堵事件循环
            await asyncio.to_thread(sweep)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 清理失败不该让服务挂掉，下一轮再来
            logger.exception("上传图清理出错，跳过本轮")
        await asyncio.sleep(interval)
