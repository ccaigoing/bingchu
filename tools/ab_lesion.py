"""病灶定位的 A/B 验收工具：纯 HSV  vs  通用分割排除泥水。

## 为什么必须有这个工具

本次变更的前两次尝试都是"数字看着对、肉眼是错的"：面积上限不再触发、
框数从 1 涨到 4，看着像改善，实际是病斑被切碎。所以验收判据**不能**用管线
自己的量（框数、覆盖率），必须换一个与管线**解耦**的客观量。

## 判据：框内像素的颜色分类

对每个输出框，取框内的原始 HSV 像素，按**纯颜色**判据分三类：

    病斑  20 < H < 45 且 S > 105     实测真病灶 H≈32/S≈133
    泥水  H < 20 或 S < 90           实测泥水 H≈8~12/S≈70~86
    未分类  其余

⚠️ 这里刻意**不**用管线的 `lesion` 掩膜来采样 —— 那是循环论证
（用管道自己的输出证明管道对）。判据只看原始像素的颜色。

## 通过闸门

    OIP-C (474x561 稻田泥水)  top-3 无「泥水/未分类」，且 45.5% 巨块消失
    稻瘟病 599x440             首框仍是病斑色，框数不塌
    纹枯病 474x205             aR 0.166 框（H22.6/S123）存活
    R-C.jfif                   不出现泥水色框

用法：
    E:/anaconda3/python.exe tools/ab_lesion.py                # 跑全部样本
    E:/anaconda3/python.exe tools/ab_lesion.py 图片路径 ...
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.services import lesion as L                      # noqa: E402
from app.services.segmenter import Segmenter              # noqa: E402

# 默认样本：三张真实图 + 一张曾出问题的网图。
DEFAULT_SAMPLES = [
    ROOT / "OIP-C.webp",
    ROOT / "static" / "uploads" / "orig",
]

# 纯颜色分类判据（与管线无关，见模块 docstring）
CLS_LESION = "病斑"
CLS_MUD = "泥水"
CLS_OTHER = "未分类"


def classify_region(hsv: np.ndarray) -> dict[str, float]:
    """把一块 HSV 区域按纯颜色判据分类，返回三类占比。"""
    h, s, _v = cv2.split(hsv)
    is_lesion = (h > 20) & (h < 45) & (s > 105)
    is_mud = (h < 20) | (s < 90)
    n = h.size or 1
    return {
        CLS_LESION: float(np.count_nonzero(is_lesion)) / n,
        # 两类可能同时命中（H<20 且 S>105 时两边都算）—— 按"是泥水"优先归泥水
        CLS_MUD: float(np.count_nonzero(is_mud)) / n,
        CLS_OTHER: float(np.count_nonzero(~is_lesion & ~is_mud)) / n,
    }


def dominant(cls: dict[str, float]) -> str:
    return max(cls, key=lambda k: cls[k])


def describe_box(rgb: np.ndarray, hsv: np.ndarray, d: dict) -> str:
    x, y, w, h = d["x"], d["y"], d["w"], d["h"]
    region = hsv[y:y + h, x:x + w]
    if region.size == 0:
        return "空"
    c = classify_region(region)
    return (f"病斑{c[CLS_LESION]*100:4.0f}% 泥水{c[CLS_MUD]*100:4.0f}% "
            f"未分类{c[CLS_OTHER]*100:3.0f}% -> {dominant(c)}")


def segment_stats(rgb: np.ndarray, masks: list[np.ndarray]) -> list[dict]:
    """复现 build_mud_mask 的逐对象判据，把"为什么挑中/没挑中"打出来。

    刻意把判据表达式抄一遍（与 `debug_lesion.channels` 同一惯例）：
    调 `MUD_*` 常量时记得同步改这里，否则诊断输出会与实际行为脱节。
    """
    mh, mw = masks[0].shape[:2]
    small = rgb if rgb.shape[:2] == (mh, mw) else cv2.resize(rgb, (mw, mh),
                                                             interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    hue, _s, _v = cv2.split(hsv)
    green = L._green_mask(hsv) > 0
    red_dist = L._hue_red_dist(hue)
    seg_area = float(mh * mw)

    span = max(3, int(min(mh, mw) * L.MUD_RING_RATIO)) | 1
    ring_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))

    rows = []
    for i, m in enumerate(masks):
        if m.shape[:2] != (mh, mw):
            continue
        npix = int(np.count_nonzero(m))
        area_ratio = npix / seg_area
        green_frac = float(np.count_nonzero(m & green)) / max(1, npix)
        ng = m & ~green
        n_ng = int(np.count_nonzero(ng))
        mean_rd = float(red_dist[ng].mean()) if n_ng else float("nan")
        ring = cv2.dilate(m.astype(np.uint8), ring_k).astype(bool) & ~m
        ring_green = float(green[ring].mean()) if ring.any() else 1.0
        picked = (
            area_ratio >= L.MUD_MIN_SEG_AREA
            and green_frac < L.MUD_GREEN_FRAC_MAX
            and n_ng >= 32
            and mean_rd < L.MUD_RED_DIST_MAX
            and ring_green < L.MUD_RING_GREEN_MAX
        )
        rows.append({
            "i": i, "area": area_ratio, "green": green_frac,
            "red_dist": mean_rd, "ring_green": ring_green, "picked": picked,
        })
    return rows


def overlay_mask(rgb: np.ndarray, mask: np.ndarray | None, color=(255, 0, 255)) -> np.ndarray:
    out = rgb.copy()
    if mask is None:
        cv2.putText(out, "mud mask: none (fallback)", (8, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
        return out
    m = mask > 0
    out[m] = (out[m] * 0.45 + np.array(color) * 0.55).astype(np.uint8)
    cv2.putText(out, f"mud mask {np.count_nonzero(m)/m.size*100:.1f}%", (8, 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    return out


def boxed(rgb: np.ndarray, lesions: list[dict], caption: str) -> np.ndarray:
    out = rgb.copy()
    for i, d in enumerate(lesions):
        cv2.rectangle(out, (d["x"], d["y"]), (d["x"] + d["w"], d["y"] + d["h"]),
                      (255, 0, 0), 2)
        cv2.putText(out, str(i), (d["x"] + 2, max(14, d["y"] + 16)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
    cv2.putText(out, caption, (8, out.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (0, 0, 255), 2)
    return out


def run_one(path: Path, seg: Segmenter | None) -> dict:
    rgb = np.asarray(Image.open(path).convert("RGB"))
    h, w = rgb.shape[:2]
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    print(f"\n{'='*78}\n{path.name}  {w}x{h}")
    area_cap = L.AREA_MAX_RATIO

    # ── 模式 A：纯 HSV ──
    t0 = time.perf_counter()
    a = L.locate_lesions(rgb)
    a_ms = (time.perf_counter() - t0) * 1000

    # ── 分割 ──
    masks, seg_ms, mud, b = [], 0.0, None, []
    if seg is not None and seg.ready:
        t0 = time.perf_counter()
        masks = seg.segments(rgb) or []
        seg_ms = (time.perf_counter() - t0) * 1000
        if masks:
            b = segment_stats(rgb, masks)
            print(f"分割对象 {len(masks)} 个（{seg_ms:.0f}ms）；逐个过四条判据：")
            # 只打面积 ≥0.5% 的：更小的连最小面积闸门都过不了，列出来只是噪声
            for r in [x for x in b if x["area"] >= 0.005]:
                print(f"    #{r['i']:2d} 面积{r['area']*100:6.2f}% 绿{r['green']*100:5.1f}% "
                      f"离红{r['red_dist']:6.1f} 环绿{r['ring_green']*100:5.1f}% "
                      f"{'√ 判为泥水' if r['picked'] else ''}")
            print(f"    （另有 {sum(1 for x in b if x['area'] < 0.005)} 个对象面积 <0.5%，"
                  f"被面积闸门拒）")
            mud = L.build_mud_mask(rgb, masks)

    # ── 模式 B：减去泥水 ──
    t0 = time.perf_counter()
    bb = L.locate_lesions(rgb, exclude_mask=mud)
    b_ms = (time.perf_counter() - t0) * 1000

    for tag, lesions, ms in (("A 纯 HSV", a, a_ms), ("B +分割", bb, b_ms)):
        over = [d for d in lesions if d["areaRatio"] > area_cap]
        print(f"  [{tag}] {len(lesions)} 框 / {ms:.0f}ms"
              f"{f' / ⚠️ {len(over)} 个超面积上限' if over else ' / 无超限'}")
        for i, d in enumerate(lesions[:3]):
            print(f"      top{i}: aR={d['areaRatio']*100:5.2f}% 贴合={d['purity']:.2f}  "
                  f"{describe_box(rgb, hsv, d)}")

    # ── 并排出图 ──
    panels = [boxed(rgb, a, "A: pure HSV"),
              overlay_mask(rgb, mud),
              boxed(rgb, bb, "B: +FastSAM mud subtraction")]
    H = max(p.shape[0] for p in panels)
    panels = [p if p.shape[0] == H else
              cv2.resize(p, (int(p.shape[1] * H / p.shape[0]), H)) for p in panels]
    # 带上后缀：OIP-C.webp 与 OIP-C.jpeg 的 stem 相同，只用 stem 会互相覆盖
    out = ROOT / "tools" / f"_ab_{path.stem[:24]}{path.suffix.replace('.', '_')}.png"
    Image.fromarray(np.hstack(panels)).save(out)
    print(f"  并排图: {out}")

    return {
        "name": path.name, "a": a, "b": bb, "mud": mud,
        "a_over": sum(1 for d in a if d["areaRatio"] > area_cap),
        "b_over": sum(1 for d in bb if d["areaRatio"] > area_cap),
        "seg_ms": seg_ms, "a_ms": a_ms, "b_ms": b_ms, "hsv": hsv, "rgb": rgb,
        "mud_area": 0.0 if mud is None else float(np.count_nonzero(mud)) / mud.size,
    }


def main(argv: list[str]) -> int:
    paths: list[Path] = [Path(p) for p in argv] if argv else []
    if not paths:
        paths = [DEFAULT_SAMPLES[0]]
        orig = DEFAULT_SAMPLES[1]
        if orig.is_dir():
            exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
            paths += sorted(p for p in orig.iterdir() if p.suffix.lower() in exts)
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("没有可读的图片")
        return 1

    seg = Segmenter()
    seg.load()
    print(f"分割器: {seg.mode}" + (f" —— {seg.error}" if seg.error else ""))

    results = [run_one(p, seg) for p in paths]

    print(f"\n{'='*78}\n汇总")
    for r in results:
        top1_a = describe_box(r["rgb"], r["hsv"], r["a"][0]) if r["a"] else "无框"
        top1_b = describe_box(r["rgb"], r["hsv"], r["b"][0]) if r["b"] else "无框"
        print(f"  {r['name'][:30]:32s} A:{len(r['a']):3d}框 超限{r['a_over']}  "
              f"B:{len(r['b']):3d}框 超限{r['b_over']}  泥水{r['mud_area']*100:5.1f}%  "
              f"分割{r['seg_ms']:4.0f}ms")
        print(f"      A top1: {top1_a}")
        print(f"      B top1: {top1_b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
