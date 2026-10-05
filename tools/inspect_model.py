"""查权重底细：类别表、任务类型、参数量、能否加载。

阶段一的第一个真实验证点 —— 在写任何映射之前，先看清这个第三方权重
到底认哪些类别，据此判断它能不能满足"识别水稻病虫害"的需求。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "models" / "jktk_x.pt"

sys.path.insert(0, str(ROOT / "server"))


def main() -> int:
    import torch
    print(f"torch      : {torch.__version__}")
    print(f"cuda 可用   : {torch.cuda.is_available()}")

    import ultralytics
    print(f"ultralytics: {ultralytics.__version__}")
    print(f"权重文件    : {WEIGHTS}  ({WEIGHTS.stat().st_size / 1024 / 1024:.1f} MB)")
    print()

    from ultralytics import YOLO

    print("加载中…")
    model = YOLO(str(WEIGHTS))

    print(f"task       : {model.task}")
    names = model.names
    print(f"类别数      : {len(names)}")
    print()

    # 只看跟水稻/作物病害相关的，116 类全打印太长
    KW = ("rice", "blast", "blight", "smut", "spot", "borer", "hopper",
          "armyworm", "sheath", "bacterial", "fungal", "rust", "rot",
          "mildew", "mosaic", "leaf", "pest", "insect", "wilt")
    hits = [(i, n) for i, n in sorted(names.items()) if any(k in str(n).lower() for k in KW)]

    print(f"── 与作物病虫害相关的类别（{len(hits)}/{len(names)}）──")
    for i, n in hits:
        print(f"  {i:3d}  {n}")

    print()
    print("── 全部类别 ──")
    for i, n in sorted(names.items()):
        print(f"  {i:3d}  {n}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
