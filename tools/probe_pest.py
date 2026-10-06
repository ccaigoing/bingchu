"""隔离验证：候选害虫检测权重在**现有图片**上的行为。

它不改 detect.py、不改任何现有输出，只回答一个问题：

    **把这个害虫权重接进来，会不会把现有的病害识别结果搞坏？**

判据不是"它在害虫图上框得准不准"（那是收益），而是"**它在病害图上安不安静**"
（那是风险）。一个见什么框什么的检测器，接进来就会往 detections[] 里塞虫框，
污染 infectedAreaRatio / severityLevel / counts，所以先量出这个数。

用法：
    E:/anaconda3/python.exe tools/probe_pest.py
    E:/anaconda3/python.exe tools/probe_pest.py 图片1 图片2 ...
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.services.detector import CANONICAL, resolve_class  # noqa: E402

# 权重可覆盖：候选不止一个，同一套判据要能横向比（同 test_detect.py 的 YAODAO_API 惯例）
WEIGHTS = Path(os.environ.get(
    "YAODAO_PEST_WEIGHTS", ROOT / "models" / "yolo11s-pest-ip102.pt"))

# 病害图（**风险面**：它该安静）+ 害虫图（**收益面**：它该出声）
DISEASE_SAMPLES = [
    ROOT / "samples" / "v2-ba4a63f67ac673a177fbe4ecec68c30e_1440w.jpg",
    ROOT / "samples" / "OIP-C.jpeg",
    ROOT / "OIP-C.webp",
]
PEST_SAMPLE = Path(r"C:\Users\wub\Desktop\63_178223_361b8636a0bfff3.jpg")

CONFS = (0.25, 0.5)


def report_class_mapping(names: dict) -> None:
    """先做纯字符串检查：这个权重的标签会被现有规则**映射成什么**。

    不需要推理就能算，而且这是接权重前必须解决的硬问题 —— 现有 KEYWORD_RULES
    里 "borer" / "hopper" 这种笼统词会把不相关的虫吞进水稻害虫类。

    ⚠️ 这里刻意**不**自动判断"某个名字算不算水稻害虫" —— 那是领域知识，用子串
    启发式判会判错（实测把 `stem_borer` 误分到非水稻桶）。只客观分成三桶，
    剩下由人看。
    """
    print(f"\n{'='*80}\n① 类别名映射风险（纯字符串，现有 resolve_class 直接跑）\n")
    to_pest, to_disease, raw = [], [], []
    for idx in sorted(names):
        name = names[idx]
        code, cn, cat = resolve_class(name)
        if code.startswith("raw:"):
            raw.append((name, code))
        elif cat == "pest":
            to_pest.append((name, code, cn))
        else:
            to_disease.append((name, code, cn))

    print(f"  ① 会被现有规则判为**规范害虫**的（{len(to_pest)} 个）"
          f"—— 逐个核对是不是真水稻害虫：")
    for name, code, cn in to_pest:
        print(f"      {name:34} -> {code:14} ({cn})")

    if to_disease:
        print(f"\n  ⚠️ 会被判为**病害**的（{len(to_disease)} 个）—— 虫模型报病名，一定是错的：")
        for name, code, cn in to_disease:
            print(f"      {name:34} -> {code:14} ({cn})")

    print(f"\n  ② 映射不上、只能原样透出英文名的（{len(raw)} 个）：")
    for name, code in raw:
        print(f"      {name:34} -> {code}")

    print(f"\n  小结：{len(names)} 类里 {len(to_pest)} 类会得到规范害虫名、"
          f"{len(raw)} 类透出原名。")
    print("  => 接权重前必须把 RAW_LABEL_MAP 按这些**真实标签**填实（它现在是空的），"
          "否则 KEYWORD_RULES 的宽词会把不相干的虫也报成水稻害虫。")


def probe(models, path: Path) -> dict:
    """在一张图上跑两档 conf，返回结果。"""
    if not path.exists():
        print(f"\n{'='*80}\n{path.name}  ← 不存在，跳过")
        return {}
    image = Image.open(path).convert("RGB")

    print(f"\n{'='*80}\n{path.name}  {image.width}x{image.height}")
    out = {}
    for conf in CONFS:
        t0 = time.perf_counter()
        res = models.predict(source=image, imgsz=640, conf=conf, iou=0.45,
                             device="cpu", verbose=False)[0]
        ms = (time.perf_counter() - t0) * 1000
        boxes = res.boxes
        n = 0 if boxes is None else len(boxes)
        print(f"  conf={conf:<5} → {n:3d} 框 / {ms:6.0f}ms")
        rows = []
        if n:
            names = res.names
            for b in boxes:
                cls_id = int(b.cls.item())
                c = float(b.conf.item())
                x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
                area = (x2 - x1) * (y2 - y1) / (image.width * image.height)
                rows.append((names[cls_id], c, area))
            rows.sort(key=lambda r: -r[2])
            for name, c, area in rows[:8]:
                code, cn, _ = resolve_class(name)
                flag = "" if code.startswith("raw:") else f"  ← 现有规则判为 {cn}({code})"
                print(f"        {name:32} conf={c:.3f} 面积={area*100:5.2f}%{flag}")
            if len(rows) > 8:
                print(f"        …另有 {len(rows) - 8} 个更小的框")
        out[conf] = rows
    return out


def main(argv: list[str]) -> int:
    if not WEIGHTS.exists():
        print(f"权重不存在: {WEIGHTS}")
        return 1

    from ultralytics import YOLO

    print(f"加载 {WEIGHTS.name} …")
    t0 = time.perf_counter()
    models = YOLO(str(WEIGHTS))
    print(f"就绪 {time.perf_counter() - t0:.1f}s · {len(models.names)} 类")

    report_class_mapping(models.names)

    if argv:
        paths = [Path(p) if Path(p).is_absolute() else ROOT / p for p in argv]
    else:
        paths = list(DISEASE_SAMPLES) + [PEST_SAMPLE]
    results = {p.name: probe(models, p) for p in paths}

    print(f"\n{'='*80}\n③ 结论\n")
    print(f"  {'图':38} {'conf=0.25':>10} {'conf=0.5':>10}")
    for name, r in results.items():
        a = len(r.get(0.25, [])) if r else 0
        b = len(r.get(0.5, [])) if r else 0
        print(f"  {name[:36]:38} {a:>10} {b:>10}")
    print("""
  读法：病害图那一行必须接近 0 —— 那是「接进来会不会污染现有结果」的直接答案。
  害虫图那一行是收益：有几框、落在虫体上没有（出图看，不要只看数字）。""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
