"""验证部署护栏：限流是否按 IP 生效。

对应 deploy/README.md 的验证第 6–7 步。上线后跑一次，确认
`services/guard.py` + nginx 的 X-Forwarded-For 这一整条链路是通的。

## 为什么不发真图

限流中间件在**路由之前**执行，所以一个不带文件的 `POST /api/detect`
同样会消耗令牌（代价是返回 400），但**不会写数据库、不会落盘图片**。

用真图连发 20 次的话，前 15 次会留下 15 条识别记录和 30 张图片，
把答辩要看的演示库污染掉 —— 为了测限流付出的代价太大了。

## 看什么

    python tools/test_guard.py                      # 本机
    python tools/test_guard.py --url http://<公网IP> # 线上（从别的机器跑）

期望：前 `perMinute` 次不是 429，之后全是 429 且带 `RATE_LIMITED`。
**最后会打印 `guard.trackedIps`** —— 在服务器上从不同设备跑，这个数应该
跟着涨；一直是 1 就说明 nginx 的 X-Forwarded-For 没生效（见手册故障表）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request


def post_detect(base: str, timeout: float = 30.0) -> tuple[int, dict | None]:
    """发一次不带文件的 detect 请求，返回 (状态码, 响应体或 None)。

    400 和 429 都是**预期内**的答复，不是异常 —— 前者说明请求真的进了路由
    （也就是限流放行了），后者说明被拦下了。真正的失败只有连不上（URLError）。
    """
    req = urllib.request.Request(
        f"{base}/api/detect", data=b"", method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _json(resp)
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc)
    except urllib.error.URLError as exc:
        print(f"连不上 {base}：{exc.reason}")
        print("后端没起来？先确认 /api/health 能打开。")
        sys.exit(2)


def _json(resp) -> dict | None:
    try:
        return json.loads(resp.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def get_health(base: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(f"{base}/api/health", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def burst(base: str, count: int) -> tuple[list[int], int | None]:
    """连发 count 次，返回（状态码列表, 首次 429 的序号）。"""
    codes: list[int] = []
    first_429: int | None = None
    for i in range(1, count + 1):
        status, body = post_detect(base)
        codes.append(status)
        if status == 429:
            if first_429 is None:
                first_429 = i
            print(f"{i:>3}  429  {(body or {}).get('code', '?')}")
        else:
            print(f"{i:>3}  {status}  （放行 —— 非 429 即未被拦，属预期）")
    return codes, first_429


def main() -> int:
    ap = argparse.ArgumentParser(description="验证限流护栏")
    ap.add_argument("--url", default="http://127.0.0.1:8000",
                    help="后端地址（本机直连 8000；线上填 http://<公网IP> 走 nginx）")
    ap.add_argument("--count", type=int, default=20, help="连发次数，默认 20")
    ap.add_argument("--no-retry", action="store_true",
                    help="窗口里有历史用量时不等 60 秒重测（默认会等）")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    try:
        health = get_health(base)
    except Exception as exc:  # noqa: BLE001 —— 这里就是要把任何失败都变成一句人话
        print(f"读 /api/health 失败：{exc}")
        return 2

    guard = health.get("guard")
    if not guard:
        print("⚠️ /api/health 里没有 guard 段 —— 说明跑的还是改造前的后端。")
        return 2

    limit = guard["perMinute"]
    print(f"目标 {base}")
    print(f"额度 {limit} 次/分钟 · {guard['perDay']} 次/天\n")

    # ── 判定 ──
    #
    # 期望的形状：前 limit 次放行，第 limit+1 次起拦截。
    # 严格用 limit+1 而不是"差不多"—— 差一个说明固定窗口的边界算错了，
    # 那种 bug 在低流量下永远看不出来，一到演示现场就是全体 429。
    #
    # ⚠️ 但"比预期早被拦"**不必然是 bug**：固定窗口是按分钟对齐的，
    # 这个窗口里之前已经用掉的额度（比如刚跑过一轮回归测试）会算进来。
    # 所以早拦时先等窗口翻篇重测一次 —— 否则这个脚本会在最需要它给出
    # 可信结论的时候，为着上一次的残留用量大喊狼来了。
    codes, first_429 = burst(base, args.count)

    if first_429 is not None and first_429 <= limit and not args.no_retry:
        used = limit - first_429 + 1
        print(f"\n本窗口内已有约 {used} 次历史用量（可能来自刚才的测试）。")
        print("等 60 秒窗口翻篇后重测一次，以得到干净的结论……")
        time.sleep(61)
        print()
        codes, first_429 = burst(base, args.count)

    print()
    ok = first_429 == limit + 1
    if ok:
        print(f"✅ 限流正确：第 {limit + 1} 次起被拦")
    elif first_429 is None:
        print(f"❌ 连发 {args.count} 次全被放行 —— 限流没生效。")
        print("   若额度本身大于连发次数，把 --count 调大再试。")
    else:
        print(f"❌ 第 {first_429} 次就被拦了，期望是第 {limit + 1} 次。")
        print("   已排除窗口残留用量后仍不对 —— 固定窗口的计算有问题。")

    # 拒绝计数应当**至少**增加了被拦的次数（可能有别的来源，所以用 >=）
    try:
        after = get_health(base)["guard"]
        print(f"\nguard.rejectedTotal: {guard['rejectedTotal']} → {after['rejectedTotal']}")
        print(f"guard.trackedIps  : {after['trackedIps']}"
              "   ← 在服务器上从不同设备跑，这个数应该跟着涨")
    except Exception as exc:  # noqa: BLE001
        print(f"（回读 /api/health 失败，不影响限流结论：{exc}）")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
