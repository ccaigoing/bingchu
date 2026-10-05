"""对若干张真实照片跑一遍 /api/detect，打印可核对的结果摘要。

用法：E:/anaconda3/python.exe tools/test_detect.py 图片1 [图片2 ...]
     不给参数则跑 samples/ 下已知的两张真实病害照片
     （稻瘟病 —— 9 框落在梭形病斑；纹枯病 —— 1 框圈住褐变病鞘）。
"""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = "http://127.0.0.1:8000/api/detect"

DEFAULT = ["samples/v2-ba4a63f67ac673a177fbe4ecec68c30e_1440w.jpg", "samples/OIP-C.jpeg"]


def post_image(p: Path) -> dict:
    boundary = "----yaodao" + uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{p.name}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = head + p.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        API, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def show(p: Path) -> None:
    print(f"════ {p.name} ════")
    try:
        d = post_image(p)
    except Exception as exc:  # noqa: BLE001
        print(f"  失败: {type(exc).__name__}: {exc}\n")
        return

    m, s, loc = d["model"], d["summary"], d["localization"]
    print(f"  模型   : {m['name']} · {m['mode']} · {m['device']} · {d['latencyMs']}ms")
    print(f"  YOLO   : {loc['yoloTopNameCn']} ({loc['yoloTopClass']}) "
          f"conf={loc['yoloConfidence']}  框被忽略={loc['yoloBoxIgnored']}")
    print(f"  汇总   : {s['topClassName']} · 感染 {s['infectedAreaRatio']*100:.1f}% · "
          f"{s['spotCount']} 处 · {s['severityLabel']} · {s['regionDesc']}")
    print(f"  建议   : {s['advice']}")
    print(f"  标注图 : {d['image']['annotatedUrl']}")
    for i, o in enumerate(d["detections"]):
        b, bx = o["box"], o["boxPx"]
        print(f"    [{i:2d}] {o['nameCn']:<6} conf={o['confidence']:.2f} "
              f"box=({b['x']:.3f},{b['y']:.3f},{b['w']:.3f},{b['h']:.3f}) "
              f"px={bx['w']}x{bx['h']} 面积={o['areaRatio']*100:.2f}% {o['region']}")
    print()


def main() -> int:
    names = sys.argv[1:] or DEFAULT
    for n in names:
        p = Path(n)
        if not p.is_absolute():
            p = ROOT / n
        if not p.exists():
            print(f"跳过（不存在）: {p}")
            continue
        show(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
