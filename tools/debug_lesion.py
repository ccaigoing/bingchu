"""把病灶分割的中间掩膜导成图片，肉眼核对每一步在做什么。

调参不能靠猜。这个脚本把每一步拆成独立面板并排输出：

    1 original      原图
    2 plant         叶片区域（绿色外扩，**只作连通域归属判据，不做像素级求交**）
    3 brown         褐色掩膜（色相接近红黄两侧）
    4 yellow        黄晕掩膜
    5 necrotic      灰白坏死掩膜（低饱和 + 高亮度）
    6 raw lesion    3|4|5 的并集
    7 cleaned&plant 形态学清理后 ∩ 叶片区域（**仅供参考**，非最终判据）
    8 final boxes   原图 + locate_lesions() 最终检出的框（带序号）

看 Panel 8 就知道框落在哪；若框位置不对，往前找是哪一个通道污染了掩膜。
注意 Panel 7 只是示意：真正的最终判据是**逐连通域**看落在叶片区域内的
比例（MIN_PLANT_OVERLAP），不要按 Panel 7 的直观覆盖率去理解结果。

用法：E:/anaconda3/python.exe tools/debug_lesion.py 图片路径
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.services import lesion as L  # noqa: E402


def label(img: np.ndarray, text: str) -> np.ndarray:
    out = img.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2RGB)
    cv2.putText(out, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 0, 0), 2)
    return out


def pct(m: np.ndarray) -> float:
    return float(np.count_nonzero(m)) / m.size * 100


def channels(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """单独复现 _masks 里的三个通道，便于定位是哪一个在误收。

    这里刻意把 `_masks` 的三条表达式抄一遍 —— 诊断工具要能看见
    "合并前"的分量，调 _masks 时记得同步改这里。
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = cv2.split(hsv)

    brown = (
        ((h <= L.BROWN_H_MAX) | (h >= 160))
        & (s >= L.BROWN_S_MIN) & (v >= L.BROWN_V[0]) & (v <= L.BROWN_V[1])
    ).astype(np.uint8) * 255
    yellow = (
        (h > L.YELLOW_H[0]) & (h < L.YELLOW_H[1])
        & (s >= L.YELLOW_S_MIN) & (v >= L.YELLOW_V_MIN)
    ).astype(np.uint8) * 255
    necrotic = ((s < L.NECROTIC_S_MAX) & (v >= L.NECROTIC_V_MIN)).astype(np.uint8) * 255
    return brown, yellow, necrotic


def main(path: str) -> int:
    src = Path(path)
    rgb = np.asarray(Image.open(src).convert("RGB"))
    h, w = rgb.shape[:2]
    print(f"图像 {w}x{h}  ({src.name})")

    leaf, raw = L._masks(rgb)
    brown, yellow, necrotic = channels(rgb)

    # 复现 locate_lesions 里的形态学步骤
    span = max(3, int(min(h, w) * 0.012)) | 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))
    cleaned = cv2.morphologyEx(raw, cv2.MORPH_OPEN, k)
    cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, k, iterations=2)
    final_mask = cv2.bitwise_and(cleaned, leaf)

    lesions = L.locate_lesions(rgb)
    boxed = rgb.copy()
    for i, d in enumerate(lesions):
        cv2.rectangle(boxed, (d["x"], d["y"]),
                      (d["x"] + d["w"], d["y"] + d["h"]), (255, 0, 0), 2)
        cv2.putText(boxed, str(i), (d["x"] + 2, d["y"] + 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)

    panels = [
        label(rgb, "1 original"),
        label(leaf, f"2 plant ({pct(leaf):.1f}%)"),
        label(brown, f"3 brown ({pct(brown):.1f}%)"),
        label(yellow, f"4 yellow ({pct(yellow):.1f}%)"),
        label(necrotic, f"5 necrotic ({pct(necrotic):.1f}%)"),
        label(raw, f"6 raw lesion ({pct(raw):.1f}%)"),
        label(final_mask, f"7 cleaned&plant ({pct(final_mask):.2f}%) ref-only"),
        label(boxed, f"8 final boxes ({len(lesions)})"),
    ]

    H = max(p.shape[0] for p in panels)
    scaled = []
    for p in panels:
        if p.shape[0] != H:
            s = H / p.shape[0]
            p = cv2.resize(p, (int(p.shape[1] * s), H))
        scaled.append(p)

    out = ROOT / "tools" / f"_debug_{src.stem[:28]}.png"
    Image.fromarray(np.hstack(scaled)).save(out)
    print(f"已输出: {out}")
    print()
    print(f"  褐色通道占比      : {pct(brown):6.2f}%")
    print(f"  黄晕通道占比      : {pct(yellow):6.2f}%")
    print(f"  灰白通道占比      : {pct(necrotic):6.2f}%   <- 虚焦/灰背景会在这里虚高")
    print(f"  原始病灶候选占比  : {pct(raw):6.2f}%")
    print(f"  清理∩叶片后占比   : {pct(final_mask):6.2f}%")
    print(f"  最终检出框        : {len(lesions)} 个")
    for i, d in enumerate(lesions[:12]):
        print(f"    [{i:2d}] x={d['x']:5d} y={d['y']:5d} {d['w']:4d}x{d['h']:<4d} "
              f"面积={d['areaRatio']*100:5.2f}% 贴合={d['purity']:.3f}")
    if len(lesions) > 12:
        print(f"    ... 另有 {len(lesions)-12} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "OIP-C.jpeg"))
