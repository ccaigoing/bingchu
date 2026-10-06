"""病灶定位 —— 用图像分割找出真实病斑位置。

## 为什么需要这一层

实测结论（2026-10-06，两张真实水稻病害照片）：

    jktk_x.pt 对「是什么病」判断很准（纹枯病 0.947 / 稻瘟病 0.965），
    但它给出的框是 (0.001, 0.033, 0.997, 0.934) —— 盖住整张图。

原因：它是**图像分类数据集被导出成检测格式**训练的，所谓"框"就是整图，
模型学到了"这张图里是什么病"，但从未学过"病斑在哪"。

所以这里做分层：**YOLO 负责判型，图像分割负责定位。**

## 原理

水稻叶片是绿色的；坏死病斑是褐色 / 灰白 / 黄晕。在 HSV 空间里这两类
分得很开。步骤：

1. 绿色掩膜 → 外扩 R 像素 → 得到「叶片区域」
2. 褐 / 灰白 / 黄晕掩膜 → 得到「病灶候选」
3. 形态学清理 → 连通域 → 每个连通域一个紧致外接框
4. 逐个连通域过滤：面积、长宽比、框贴合度、**落在叶片区域内的比例**

## 为什么第 4 步是「连通域级」而不是「像素级与运算」

踩过的坑：早期写法是 `lesion &= leaf`，逐像素求交。在 474x205 的纹枯病
照片（OIP-C.jpeg）上，病鞘宽约 100px，而 `leaf` 只是绿色外扩约 15px，
够不到病鞘中心 —— 63.4% 的候选被砍到 **5.35%**，真病鞘整个丢失，
只剩一堆碎渣框落在虚焦背景上。

**病得越重、病斑越宽、越不绿，就越会被这条规则删掉** —— 规则自我否定。

改成连通域级判定后：病鞘有 32% 的面积落在叶片区域内（两侧叶缘各贡献
约 16%），通过阈值；而虚焦暖色背景宽 252px，只有约 6% 落在叶片区域内，
被拒。既保住了宽病斑，又挡住了背景。

（另外验证过一个更强的判据：局部清晰度 |Laplacian| 能量。实测该图上
背景 1.23x 中位数、病鞘 2.01x —— **方向对但幅度不足以设阈值**，
故未采用，避免为一个样本过拟合。）

## 第三层：减去泥水（`build_mud_mask` + `exclude_mask`）

颜色 + 几何在这里到头了：稻田泥水是褐色，与基部褐色病斑连成**一个占图 45.5%
的连通域**，超过 `AREA_MAX_RATIO` 被整块丢弃，真病斑跟着一起没了。所以要借助
`segmenter.py` 的类无关分割，把泥水对象从病灶候选里减掉。

判据的设计过程见常量区 `MUD_*` 的注释 —— 那里记着一条重要的**否定结论**：
"绿色占比低 + 色相偏红"这两条单独用会把**稻瘟病斑当成泥水删掉**（病斑 H≈22、
泥水 H≈17，色相上只差几个单位），必须靠**"对象四周是否有绿色"**这个与颜色
无关的轴才分得开。

### 已知残留

OIP-C 那张图上，FastSAM 把**基部褐色病斑与褐色泥水合并成了一个对象**，
减泥水时病斑跟着被减掉（基部 56.9% 的病斑色像素落在泥水掩膜内），基部病灶
因此仍未出框；且首位框是一个 3.55% 的虚焦背景框。

试过一个对症修法 —— 减泥水时保护掩膜内"强病斑色"（`20<H<45 且 S>105`）的像素
—— **实测反而更糟**：虚焦背景本身就是高饱和褐色，保护后首位框从 3.55% 涨到
13.14%。已否决，勿再试。
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from .detector import Detection

logger = logging.getLogger(__name__)


# ── 分割参数（OpenCV HSV：H∈[0,179], S∈[0,255], V∈[0,255]）──

# 绿色叶片
GREEN_H = (35, 90)
GREEN_S_MIN = 50
GREEN_V_MIN = 40

# 褐色坏死（色相偏红黄两侧）
# V 下限取 70 是关键：真实病斑是**亮**的（v≈80~200），而叶片之间的
# 阴影暗缝很暗（v≈30~60）。早先把下限放到 25，暗缝就被当成了褐色病斑，
# 连成整幅图高的竖条，逼得只能靠形状硬滤 —— 结果把细长的真病斑一起砍掉。
# 在颜色上分开，比在形状上分可靠得多。
BROWN_H_MAX = 30
BROWN_S_MIN = 50
BROWN_V = (70, 245)

# 黄晕（病斑外圈的褪绿过渡带）
YELLOW_H = (20, 36)
YELLOW_S_MIN = 80
YELLOW_V_MIN = 120

# 灰白坏死中心
NECROTIC_S_MAX = 60
NECROTIC_V_MIN = 110

# 叶片区域 = 绿色掩膜外扩这么多（占图像短边比例）。
# 取 8% 是为了让"两侧叶缘的绿色"能覆盖到中等宽度病斑的内部；
# 再大就会把背景一起圈进来。
GREEN_GROW_RATIO = 0.08

# 面积过滤：占全图比例
AREA_MIN_RATIO = 0.0004      # 小于万分之四视为噪点
AREA_MAX_RATIO = 0.25        # 单个病斑不该占掉四分之一画面，超过视为背景/分割失败

# 形状过滤：水稻稻瘟病的病斑是**梭形/眼状**，长宽比天然就有 4~6，
# 这个值必须放得够宽，否则会把真病斑当噪声滤掉（踩过这个坑）。
MAX_ASPECT = 8.0

# 贴合度下限：梭形病斑的外接矩形四角是空的，贴合度天然偏低，
# 所以这里也不能设高。
MIN_PURITY = 0.28

# 连通域落在叶片区域内的比例下限（见模块 docstring 的推导过程）
MIN_PLANT_OVERLAP = 0.15

MAX_LESIONS = 30             # 单图最多输出这么多框，避免糊成一片

# ── 泥水掩膜参数（配合 segmenter.py 的通用分割使用）──
#
# 背景：稻田泥水是褐色，落进上面的褐色分支，与基部褐色病斑连成一个占图
# 45.5% 的连通域，超过 AREA_MAX_RATIO 被整块丢弃 —— 真病斑跟着一起没了。
# 颜色/几何的启发式修不掉（实测否决 5 种），所以要借用分割给出的**对象**信息：
# 逐个 mask 判断"它是不是泥水"，只减掉泥水。
#
# 判据是四条**与**关系，而不是"绿色占比低就是泥"：
#
#   ① 绿色占比低     泥水 mask 实测 0.4%；植株 mask 71.7%
#   ② 非绿像素色相偏红 泥水实测 H≈16.9
#   ③ **四周环形区域的绿色占比也低**  ← 这条才是真正管用的
#   ④ 面积够大        滤掉分割模型的碎屑
#
# ⚠️ 前两条**单独用是会出事的**，这点是实测撞出来的：稻瘟病斑 H≈22、离红≈22，
#    泥水 H≈17、离红≈17 —— 两个轴上都只差几个单位。用它跑 599x440 的稻瘟病图，
#    FastSAM 切出的病斑对象（绿 0.8~8.9%、离红 14.7~21.9）**全部通过**①②，
#    于是真病斑被当泥水减掉，9 个正确的框塌成 4 个碎框。
#    **褐色病斑与褐色泥水在"颜色"里分不开**，这条路根本走不通。
#
#    第 ③ 条换了一个与颜色无关的轴：**这个对象是不是长在绿色里**。
#    病斑长在叶片上、四周是绿的；泥水四周还是泥水。实测：
#
#        真泥水（OIP-C 那张）      环内绿色 9.6%   → 收
#        稻瘟病斑（全部）          环内绿色 84~97%  → 拒
#        R-C.jfif 被误判的对象     环内绿色 84.3%   → 拒
#
#    这个轴是不变量：无论病斑是褐色、灰白还是黄晕，周围总有绿叶。
MUD_GREEN_FRAC_MAX = 0.15    # ① 对象自身的绿色占比上限
MUD_RED_DIST_MAX = 25.0      # ② 非绿像素"离纯红的色相距离"上限，见 _hue_red_dist
MUD_RING_GREEN_MAX = 0.25    # ③ 对象四周环形区域的绿色占比上限
MUD_RING_RATIO = 0.06        # ③ 环宽度 = 掩膜短边的这个比例
MUD_MIN_SEG_AREA = 0.002     # ④ 面积下限，滤掉分割碎屑。⚠️ 别调大：提到 2% 会把基部
                             #    那些「环绿 0%」的小泥水块漏掉，剩下的褐色背景反而连成
                             #    更大的一块（实测 3.55% → 6.78%）。有第 ③ 条兜底，不需要它来挡
MUD_MAX_COVERAGE = 0.85      # 并集覆盖超过这个比例 = 分割失控，宁可不用

# 疑似病斑（YOLO 说这是健康叶、但分割确实找出了斑块）
SUSPECT_CODE = "suspected_lesion"
SUSPECT_CN = "疑似病斑"

# 虫害（未定种）—— 虫害闸门 yolo11s-pest-ip102 判出"图里有虫"，但**它定不准种**
# （实测同一张虫照换四种裁剪得到四个不同答案，见 services/pest_gate.py）。
# 与 SUSPECT 同类，是**哨兵**而不是规范类别：disease_classes 是"病种/虫种"字典，
# 而"未定种"恰恰是"没有类别"，所以它同样落库为 class_code=NULL。
PEST_UNKNOWN_CODE = "pest_unidentified"
PEST_UNKNOWN_CN = "虫害（未定种）"


def _green_mask(hsv: np.ndarray) -> np.ndarray:
    h, s, v = cv2.split(hsv)
    return (
        (h >= GREEN_H[0]) & (h <= GREEN_H[1])
        & (s >= GREEN_S_MIN) & (v >= GREEN_V_MIN)
    ).astype(np.uint8) * 255


def _lesion_color_mask(hsv: np.ndarray) -> np.ndarray:
    """褐 / 黄晕 / 灰白三路并集 —— 病灶的**颜色**候选，不含任何空间约束。"""
    h, s, v = cv2.split(hsv)

    brown = (
        ((h <= BROWN_H_MAX) | (h >= 160))
        & (s >= BROWN_S_MIN) & (v >= BROWN_V[0]) & (v <= BROWN_V[1])
    )
    yellow = ((h > YELLOW_H[0]) & (h < YELLOW_H[1])
              & (s >= YELLOW_S_MIN) & (v >= YELLOW_V_MIN))
    necrotic = (s < NECROTIC_S_MAX) & (v >= NECROTIC_V_MIN)

    return (brown | yellow | necrotic).astype(np.uint8) * 255


def _masks(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """返回 (叶片区域, 病灶候选)，均为 uint8 的 0/255 掩膜。

    注意：叶片区域**不再**用于像素级求交，只作为连通域的归属判据
    （见 `locate_lesions` 与模块 docstring）。
    """
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    min_dim = min(rgb.shape[:2])

    green = _green_mask(hsv)

    span = max(5, int(min_dim * GREEN_GROW_RATIO)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))
    leaf = cv2.dilate(green, kernel)

    return leaf, _lesion_color_mask(hsv)


def _hue_red_dist(h: np.ndarray) -> np.ndarray:
    """色相到「纯红」的**环形**距离：0 = 纯红，90 = 青绿。

    直接用色相均值判"偏不偏红"是错的 —— 褐色横跨 0 度，落在 H≤30 **和**
    H≥160 两支上（见 `_lesion_color_mask` 的 brown 分支），把 175 和 5 取平均
    会得到 90（青绿），与事实相反。取到纯红的环形距离就没有这个问题。
    """
    return np.minimum(h, 180 - h)


def build_mud_mask(rgb: np.ndarray, masks: list[np.ndarray]) -> np.ndarray | None:
    """从通用分割的逐对象掩膜里挑出「泥水」，并集上采样回原图尺寸。

    返回 `None` 表示**不可信 / 不可用**，调用方必须回落到纯 HSV 路径 ——
    宁可不减，也不能把病斑当泥水删掉。触发条件：没有 mask、并集为空、
    并集覆盖超过 `MUD_MAX_COVERAGE`。

    `masks` 是**缩放分辨率**下的布尔掩膜（见 `segmenter.segments`）。
    绿色/色相统计与掩膜同分辨率地算，避免把全分辨率图反复缩放。
    """
    if not masks:
        return None

    h_img, w_img = rgb.shape[:2]
    mh, mw = masks[0].shape[:2]
    if mh < 2 or mw < 2:
        return None

    # 缩到掩膜分辨率 —— 与分割器当时看到的图一致（INTER_AREA，与 bound() 同法）
    small = rgb if (h_img, w_img) == (mh, mw) else cv2.resize(
        rgb, (mw, mh), interpolation=cv2.INTER_AREA
    )
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    hue, _s, _v = cv2.split(hsv)
    green = _green_mask(hsv) > 0
    red_dist = _hue_red_dist(hue)

    seg_area = float(mh * mw)
    union = np.zeros((mh, mw), dtype=bool)
    picked = 0

    span = max(3, int(min(mh, mw) * MUD_RING_RATIO)) | 1
    ring_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))

    for m in masks:
        if m.shape[:2] != (mh, mw):
            continue
        area_ratio = float(np.count_nonzero(m)) / seg_area
        if area_ratio < MUD_MIN_SEG_AREA:
            continue

        n_mask = int(np.count_nonzero(m))
        green_frac = float(np.count_nonzero(m & green)) / max(1, n_mask)
        if green_frac >= MUD_GREEN_FRAC_MAX:
            continue

        non_green = m & ~green
        n_non_green = int(np.count_nonzero(non_green))
        if n_non_green < 32:      # 非绿像素太少，色相均值不可信
            continue
        mean_red_dist = float(red_dist[non_green].mean())
        if mean_red_dist >= MUD_RED_DIST_MAX:   # 不偏红 → 不是泥水
            continue

        # ③ 这个对象是不是长在绿色里。病斑四周有绿叶，泥水四周没有 ——
        # 这是唯一能把「褐色病斑」与「褐色泥水」分开的轴（见常量区的实测表）。
        ring = cv2.dilate(m.astype(np.uint8), ring_k).astype(bool) & ~m
        if not ring.any():
            continue
        ring_green = float(green[ring].mean())
        if ring_green >= MUD_RING_GREEN_MAX:
            continue

        union |= m
        picked += 1

    if picked == 0:
        return None

    coverage = float(np.count_nonzero(union)) / seg_area
    if coverage <= 0 or coverage > MUD_MAX_COVERAGE:
        logger.info("泥水掩膜不可信，放弃：覆盖 %.3f（挑中 %d 个对象）", coverage, picked)
        return None

    # 只上采样这一张并集（不是每个 mask 各来一次）—— 原图可能是 4096x3072
    if (mh, mw) != (h_img, w_img):
        union = cv2.resize(
            union.astype(np.uint8), (w_img, h_img), interpolation=cv2.INTER_NEAREST
        ).astype(bool)

    logger.info("泥水掩膜：从 %d 个对象中挑中 %d 个，覆盖 %.3f", len(masks), picked, coverage)
    return (union.astype(np.uint8)) * 255


def locate_lesions(rgb: np.ndarray, *, exclude_mask: np.ndarray | None = None) -> list[dict]:
    """找出病斑，返回 [{x, y, w, h, purity, areaRatio}, ...]（像素坐标）。

    `purity` = 框内被判为病灶的像素占比 —— 这是**真实算出来**的框贴合度，
    用作置信度；不是编出来的数字。

    `exclude_mask`（可选，0/255 的 uint8）是从病灶候选里**要减掉**的区域，
    目前用于排除泥水。它在**形态学之前**生效 —— 必须赶在连通域成型前把泥水
    去掉，否则泥水与病斑已经连成一体，事后减不干净。
    `exclude_mask=None` 时行为与不带这个参数时**逐字节相同**。
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        return []

    h_img, w_img = rgb.shape[:2]
    img_area = h_img * w_img
    leaf, lesion = _masks(rgb)

    if exclude_mask is not None:
        if exclude_mask.shape[:2] != lesion.shape[:2]:
            exclude_mask = cv2.resize(
                exclude_mask, (lesion.shape[1], lesion.shape[0]),
                interpolation=cv2.INTER_NEAREST,
            )
        lesion = lesion & ~exclude_mask

    # 开运算去孤立噪点，闭运算把碎裂的同一病斑连起来
    span = max(3, int(min(h_img, w_img) * 0.012)) | 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (span, span))
    lesion = cv2.morphologyEx(lesion, cv2.MORPH_OPEN, k)
    lesion = cv2.morphologyEx(lesion, cv2.MORPH_CLOSE, k, iterations=2)

    n, labels, stats, _centroids = cv2.connectedComponentsWithStats(lesion, 8)
    leaf_crop_all = leaf

    out: list[dict] = []
    for i in range(1, n):  # 0 是背景
        x, y, w, h, area_px = stats[i]
        ratio = area_px / img_area
        if ratio < AREA_MIN_RATIO or ratio > AREA_MAX_RATIO:
            continue

        # 形状过滤：细长条是叶间暗缝，不是病斑
        long_side, short_side = max(w, h), max(1, min(w, h))
        if long_side / short_side > MAX_ASPECT:
            continue

        sub = lesion[y:y + h, x:x + w]
        comp = (labels[y:y + h, x:x + w] == i)

        # 框贴合度：框内有病斑像素的比例
        purity = float(np.count_nonzero(sub)) / float(w * h) if w * h else 0.0
        if purity < MIN_PURITY:
            continue

        # 叶片归属：该连通域有足够比例落在「绿色外扩区」内。
        # 这一条替代了原来的像素级 `lesion &= leaf` —— 后者会腰斩宽病斑。
        plant = float(np.count_nonzero(comp & (leaf_crop_all[y:y + h, x:x + w] > 0)))
        plant_overlap = plant / float(area_px) if area_px else 0.0
        if plant_overlap < MIN_PLANT_OVERLAP:
            continue

        out.append({
            "x": int(x), "y": int(y), "w": int(w), "h": int(h),
            "purity": round(purity, 3),
            "areaRatio": round(ratio, 5),
        })

    # 大斑在前，最多 MAX_LESIONS 个
    out.sort(key=lambda d: d["areaRatio"], reverse=True)
    return out[:MAX_LESIONS]


def has_type_verdict(top_code: str | None, top_category: str) -> bool:
    """主判型（YOLO）是否给出了**可用结论** —— 即 `effective_class` 不会走到兜底。

    抽出来只为一件事：让调用方能在**跑虫害闸门之前**先问一句。闸门是一次完整的
    模型推理，只有在主判型说不出话时才有必要付这个代价；也因此，现有三张识别得出
    结论的病害图**连闸门都不会被调用**，输出与接闸门之前逐字节相同。

    ⚠️ 判断条件与 `effective_class` 的分支条件**必须是同一份**，所以那个函数直接
    调这个函数，而不是再抄一遍。两边各写一遍，就会出现"这里说有结论、那里说没有"
    的静默分叉。
    """
    return (
        (top_category == "disease" and bool(top_code)
         and not top_code.startswith("raw:"))
        or top_category == "pest"
    )


def effective_class(
    top_code: str | None,
    top_cn: str | None,
    top_category: str,
    *,
    pest_gate: bool = False,
) -> tuple[str, str, str]:
    """决定本次识别**用哪个类别**，返回 (code, 中文名, 类别)。

    ⚠️ 这是全链路**唯一**的类别归属判断。`build_detections` 用它给每个框贴类别，
    `summarize` 用它填汇总里的 topClassName / topClassCode。判断只写一次，
    两处就不可能分叉。

    规则：
    - 主判型有结论（见 `has_type_verdict`）→ 用它。
        判为病害 → 该病害类别（置信度另有来源，见 build_detections）
        判为害虫 → 沿用害虫类别（jktk_x 无虫类，此路今天走不到，但要留着）
    - 主判型没有有效结论（None / 原始标签 raw:）→ 再看 `pest_gate`：
        闸门说有虫 → 「虫害（未定种）」，**不给具体虫名**
        闸门沉默   → 「疑似病斑」，不硬塞一个病害名

    `pest_gate` 只在最后那条兜底分支上起作用。主判型有结论时它被**刻意忽略** ——
    一张已经确诊稻瘟病的图，不该因为闸门多看了一眼就被改判成虫害。
    """
    if has_type_verdict(top_code, top_category):
        if top_category == "pest":
            return top_code or SUSPECT_CODE, top_cn or SUSPECT_CN, "pest"
        return top_code, top_cn or top_code, "disease"

    if pest_gate:
        return PEST_UNKNOWN_CODE, PEST_UNKNOWN_CN, "pest"
    return SUSPECT_CODE, SUSPECT_CN, "disease"


def build_detections(
    img_w: int,
    img_h: int,
    lesions: list[dict],
    cls: tuple[str, str, str],
) -> list[Detection]:
    """把病灶框组装成 Detection，以便复用标注绘制与汇总逻辑。

    `cls` **必须**是 `effective_class()` 的返回值。这里刻意不再自己判断类别 ——
    调用方判断一次、框和汇总共用同一个结果，是"框上写的类别"与"汇总里写的类别"
    永不打架的唯一保证。
    """
    code, cn, cat = cls

    dets: list[Detection] = []
    for idx, L in enumerate(lesions):
        w_px, h_px = L["w"], L["h"]
        if w_px <= 1 or h_px <= 1:
            continue
        # 贴合度作置信度，但封顶 0.95 —— 分割不是概率模型，不该报 99%
        conf = min(0.95, max(0.35, L["purity"]))
        dets.append(Detection(
            class_id=idx,
            code=code,
            name_cn=cn,
            category=cat,
            confidence=round(conf, 4),
            x=L["x"] / img_w,
            y=L["y"] / img_h,
            w=w_px / img_w,
            h=h_px / img_h,
            x_px=L["x"], y_px=L["y"], w_px=w_px, h_px=h_px,
        ))
    return dets


def build_pest_detections(
    img_w: int,
    img_h: int,
    boxes: tuple[tuple[float, float, float, float, float], ...] | list,
    cls: tuple[str, str, str],
) -> list[Detection]:
    """把虫害闸门的检测框组装成 Detection。

    与 `build_detections` **刻意分成两个函数**，因为框的来源和置信度的含义都不同：

        build_detections        框来自图像分割，confidence 是**框贴合度**（purity）
        build_pest_detections   框来自检测器，  confidence 是**检测器对"这里有虫"的把握**

    两者都落在 `Detection.confidence` → API 的 `localizationScore` 上，但 provenance
    不同。合成一个函数就得把"贴合度"这个词硬套到检测置信度上，那是名不副实的开始。

    `boxes` 是像素坐标的 (x1, y1, x2, y2, conf)，由 `PestGate.fires` 换算好。
    `cls` 必须是 `effective_class()` 的返回值 —— 与 `build_detections` 同一条规矩。
    """
    code, cn, cat = cls

    dets: list[Detection] = []
    for idx, (x1, y1, x2, y2, conf) in enumerate(boxes):
        # 裁剪到图内 —— 闸门的框本来就该在图内，但别让越界值毁掉归一化坐标
        x1 = max(0.0, min(float(x1), float(img_w)))
        y1 = max(0.0, min(float(y1), float(img_h)))
        x2 = max(0.0, min(float(x2), float(img_w)))
        y2 = max(0.0, min(float(y2), float(img_h)))
        w_px, h_px = x2 - x1, y2 - y1
        if w_px <= 1 or h_px <= 1:
            continue

        dets.append(Detection(
            class_id=idx,
            code=code,
            name_cn=cn,
            category=cat,
            confidence=round(max(0.0, min(1.0, float(conf))), 4),
            x=x1 / img_w, y=y1 / img_h,
            w=w_px / img_w, h=h_px / img_h,
            x_px=int(x1), y_px=int(y1), w_px=int(w_px), h_px=int(h_px),
        ))
    return dets
