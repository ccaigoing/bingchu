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

# 疑似病斑（YOLO 说这是健康叶、但分割确实找出了斑块）
SUSPECT_CODE = "suspected_lesion"
SUSPECT_CN = "疑似病斑"


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


def locate_lesions(rgb: np.ndarray) -> list[dict]:
    """找出病斑，返回 [{x, y, w, h, purity, areaRatio}, ...]（像素坐标）。

    `purity` = 框内被判为病灶的像素占比 —— 这是**真实算出来**的框贴合度，
    用作置信度；不是编出来的数字。
    """
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        return []

    h_img, w_img = rgb.shape[:2]
    img_area = h_img * w_img
    leaf, lesion = _masks(rgb)

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


def build_detections(
    img_w: int,
    img_h: int,
    lesions: list[dict],
    top_code: str | None,
    top_cn: str | None,
    top_category: str,
) -> list[Detection]:
    """把病灶框组装成 Detection，以便复用标注绘制与汇总逻辑。

    类别归属规则：
    - YOLO 判为病害 → 病灶框继承该病害类别（置信度 = 框贴合度，封顶 0.95）
    - YOLO 判为害虫 → 病灶归属无意义，直接沿用害虫类别
    - YOLO 没给出有效结论 → 标为「疑似病斑」，不硬塞一个病害名
    """
    is_disease = top_category == "disease" and top_code and not top_code.startswith("raw:")

    if is_disease:
        code, cn, cat = top_code, top_cn or top_code, "disease"
    elif top_category == "pest":
        code, cn, cat = top_code or SUSPECT_CODE, top_cn or SUSPECT_CN, "pest"
    else:
        code, cn, cat = SUSPECT_CODE, SUSPECT_CN, "disease"

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
