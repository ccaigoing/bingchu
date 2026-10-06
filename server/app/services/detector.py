"""YOLO 检测服务：模型单例、推理、标注图绘制、类别映射。

对齐方案的三条硬要求：

1. **同时**产出「画好框的标注图」与「归一化坐标」—— 前者是"系统真的标注了"
   的视觉铁证，后者供前端叠加可交互的框。少任何一个都不算完成。
2. 换权重只改 `config.DEFAULT_WEIGHTS` 一行，本文件与 API 契约不动。
3. 模型不可用时**既不抛异常、也不静默回落**，而是置 `mode="degraded"`
   交由 API 层显式透出，前端必须能看到 banner。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..config import DEFAULT_CONF, DEFAULT_IOU, INFER_IMGSZ

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 类别字典
#
# 这是识别、预警、喷洒方案三处共用的**单一事实源**。第三方权重的原始标签
# 通过 RAW_LABEL_MAP（精确）→ KEYWORD_RULES（模糊）两级映射到这里。
#
# ⚠️ 绝不能只靠字符串匹配：数据集里的 `Leaf Smut` 是**稻叶黑粉病**，
#    不等于 **稻曲病（Rice False Smut）**，中文里极易混。已知的原始标签
#    必须写进 RAW_LABEL_MAP 做显式映射。
# ═══════════════════════════════════════════════════════════

# code -> (中文名, 类别)
CANONICAL: dict[str, tuple[str, str]] = {
    "rice_blast": ("稻瘟病", "disease"),
    "rice_brown_spot": ("稻胡麻斑病", "disease"),
    "bacterial_leaf_blight": ("白叶枯病", "disease"),
    "sheath_blight": ("纹枯病", "disease"),
    "rice_false_smut": ("稻曲病", "disease"),
    "planthopper": ("稻飞虱", "pest"),
    "stem_borer": ("二化螟", "pest"),
    "fall_armyworm": ("草地贪夜蛾", "pest"),
}

# 第三方权重原始标签 → 规范 code。dump 出 model.names 后按真实标签填写。
RAW_LABEL_MAP: dict[str, str] = {}

# 兜底关键词规则：按顺序匹配，**具体的必须排在笼统的前面**
# （否则 "sheath blight" 会被 "blight" 抢走）。
KEYWORD_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("rice_false_smut", ("false smut", "rice false smut")),
    ("rice_blast", ("rice blast", "leaf blast", "neck blast", "blast")),
    ("rice_brown_spot", ("brown spot", "brown_spot", "helminthosporium")),
    ("sheath_blight", ("sheath blight", "sheath_blight", "banded leaf")),
    ("bacterial_leaf_blight", ("bacterial leaf blight", "bacterial blight", "leaf blight")),
    ("planthopper", ("planthopper", "hopper")),
    ("stem_borer", ("stem borer", "stem_borer", "borer")),
    ("fall_armyworm", ("armyworm", "fall armyworm")),
]

# 建议措施 —— 与喷洒方案页方案 A 的产品保持同一套（方案要求 7 屏数据自洽）
ADVICE: dict[str, str] = {
    "rice_blast": "立即喷洒三环唑 75% 可湿粉，用量 40 g/亩",
    "rice_brown_spot": "喷洒稻瘟灵 40% 乳油，用量 100 mL/亩",
    "bacterial_leaf_blight": "喷洒噻唑锌 20% 悬浮剂，用量 100 mL/亩",
    "sheath_blight": "喷洒井冈霉素 5% 水剂，用量 150 mL/亩",
    "rice_false_smut": "抽穗前喷洒苯醚甲环唑·丙环唑，用量 30 mL/亩",
    "planthopper": "喷洒吡蚜酮 25% 可湿粉，用量 20 g/亩",
    "stem_borer": "喷洒氯虫苯甲酰胺 20% 悬浮剂，用量 10 mL/亩",
    "fall_armyworm": "喷洒甲维盐 1% 乳油，用量 50 mL/亩",
}

# 判型没给出结论时的建议措辞。**按类别分岔** —— ADVICE 的兜底那句写的是
# "确认病原"，对虫害不成立（虫不是病原）。这不是措辞讲究，是别把虫说成病。
ADVICE_FALLBACK = {
    "pest": "疑似虫害，建议田间取样确认虫种后再选用对口药剂",
    "disease": "建议进一步取样送检，确认病原后再施药",
}

# 严重度分级：感染面积占比 → (等级, 中文标签)
SEVERITY_BANDS: list[tuple[float, str, str]] = [
    (0.02, "good", "正常"),
    (0.05, "warning", "轻微"),
    (0.15, "serious", "较重"),
    (1.01, "critical", "严重"),
]


@dataclass
class Detection:
    """单个检测框。同时携带归一化与像素两套坐标。"""

    class_id: int
    code: str
    name_cn: str
    category: str
    confidence: float
    # 归一化坐标，左上原点，与原 demo 的 box:[x,y,w,h] 语义完全一致
    x: float
    y: float
    w: float
    h: float
    # 像素坐标
    x_px: int
    y_px: int
    w_px: int
    h_px: int

    @property
    def area_ratio(self) -> float:
        return self.w * self.h

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2

    def to_dict(self) -> dict:
        """显式构造驼峰键名的响应体。

        不用 asdict() 直接透出 —— 那样会留下 name_cn / class_id 这类蛇形键，
        与 API 契约（驼峰）不一致，前端拿不到 nameCn 就会崩。

        ⚠️ 这里输出的是 `localizationScore` 而**不是** `confidence`。
        病灶框上的这个数来自 build_detections 的框贴合度（L["purity"]），
        衡量的是"这个框圈得准不准"，**不是"这个病诊断得对不对"**。
        诊断置信度来自 YOLO 判型，只在 summary.confidence 上出现。
        早先两处都叫 confidence，结果一个 96.5% 确诊的稻瘟病在页面上
        显示成"置信度 37.3%"。名字分开之后这类混淆不可能再发生。
        """
        return {
            "classId": self.class_id,
            "code": self.code,
            "nameCn": self.name_cn,
            "category": self.category,
            "isPest": self.category == "pest",
            # 框贴合度 —— 定位质量，非诊断置信度
            "localizationScore": self.confidence,
            "box": {"x": round(self.x, 4), "y": round(self.y, 4),
                    "w": round(self.w, 4), "h": round(self.h, 4)},
            "boxPx": {"x": self.x_px, "y": self.y_px,
                      "w": self.w_px, "h": self.h_px},
            "areaRatio": round(self.area_ratio, 4),
            "region": _region_of(self.center_y),
        }


def _region_of(center_y: float) -> str:
    """按归一化纵向中心把框归到上/中/下三带。"""
    if center_y < 0.34:
        return "top"
    if center_y < 0.67:
        return "mid"
    return "bottom"


REGION_CN = {"top": "上方", "mid": "中部", "bottom": "下方"}


def resolve_class(raw_name: str) -> tuple[str, str, str]:
    """把模型原始标签解析为 (code, 中文名, 类别)。

    三级：显式映射 → 关键词 → 原样透出（标记为 other，绝不丢弃、绝不猜错）。
    """
    key = raw_name.strip()

    code = RAW_LABEL_MAP.get(key)
    if code and code in CANONICAL:
        cn, cat = CANONICAL[code]
        return code, cn, cat

    low = key.lower()
    for code, keys in KEYWORD_RULES:
        if any(k in low for k in keys):
            cn, cat = CANONICAL[code]
            return code, cn, cat

    # 没映射上：原样显示，归为 other。宁可显示英文原名，也不要张冠李戴。
    return f"raw:{key}", key, "other"


# ═══════════════════════════════════════════════════════════
# 模型单例
# ═══════════════════════════════════════════════════════════


class Detector:
    """YOLO 权重的加载与推理封装。

    模型只在 lifespan 里 `load()` 一次；推理本身是阻塞的，
    调用方必须用 `run_in_threadpool` 包一层，否则会堵死事件循环。
    """

    def __init__(self, weights: Path, device: str = "cpu") -> None:
        self.weights = Path(weights)
        self.device = device
        self._model = None
        self.mode = "degraded"          # 加载成功前一律视为降级
        self.error: str | None = None
        self.loaded_at: float | None = None
        self.model_names: dict[int, str] = {}

    # ── 生命周期 ──
    def load(self) -> None:
        """加载权重。失败不抛异常 —— 降级也要让服务起得来。"""
        if not self.weights.exists():
            self.mode, self.error = "degraded", f"权重文件不存在: {self.weights}"
            logger.warning("检测模型降级：%s", self.error)
            return
        try:
            from ultralytics import YOLO

            t0 = time.perf_counter()
            model = YOLO(str(self.weights))
            self._model = model
            # 触发一次空推理，把 lazy init 的代价前置到启动阶段
            self.model_names = dict(model.names)
            self.mode = "normal"
            self.error = None
            self.loaded_at = time.time()
            logger.info(
                "检测模型就绪: %s (%d 类, %.1fs)",
                self.weights.name, len(self.model_names), time.perf_counter() - t0,
            )
        except Exception as exc:  # noqa: BLE001 —— 任何加载失败都必须降级而非崩溃
            self.mode, self.error = "degraded", f"{type(exc).__name__}: {exc}"
            logger.exception("检测模型加载失败，进入降级模式")

    @property
    def ready(self) -> bool:
        return self._model is not None and self.mode == "normal"

    # ── 推理 ──
    def predict(
        self,
        image: Image.Image,
        conf: float = DEFAULT_CONF,
        iou: float = DEFAULT_IOU,
    ) -> tuple[list[Detection], float]:
        """对一张 PIL 图推理，返回 (检测列表, 耗时毫秒)。

        坐标由 ultralytics 内部换算回原图尺寸，这里直接读即可。
        """
        if not self.ready:
            return [], 0.0

        t0 = time.perf_counter()
        results = self._model.predict(
            source=image, conf=conf, iou=iou,
            imgsz=INFER_IMGSZ, device=self.device, verbose=False,
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        if not results:
            return [], latency_ms

        res = results[0]
        img_w, img_h = res.orig_shape[1], res.orig_shape[0]
        boxes = res.boxes
        dets: list[Detection] = []

        if boxes is None or len(boxes) == 0:
            return [], latency_ms

        for i in range(len(boxes)):
            xyxy = boxes.xyxy[i].tolist()
            cls_id = int(boxes.cls[i].item())
            conf_v = float(boxes.conf[i].item())

            raw_name = self.model_names.get(cls_id, f"class_{cls_id}")
            code, name_cn, category = resolve_class(raw_name)

            x1, y1, x2, y2 = xyxy
            x1, y1 = max(0.0, x1), max(0.0, y1)
            x2, y2 = min(float(img_w), x2), min(float(img_h), y2)
            w_px, h_px = x2 - x1, y2 - y1
            if w_px <= 1 or h_px <= 1:
                continue

            dets.append(Detection(
                class_id=cls_id, code=code, name_cn=name_cn, category=category,
                confidence=round(conf_v, 4),
                x=x1 / img_w, y=y1 / img_h, w=w_px / img_w, h=h_px / img_h,
                x_px=int(x1), y_px=int(y1), w_px=int(w_px), h_px=int(h_px),
            ))

        dets.sort(key=lambda d: d.confidence, reverse=True)
        return dets, latency_ms


# ═══════════════════════════════════════════════════════════
# 标注图绘制
# ═══════════════════════════════════════════════════════════

CATEGORY_COLORS = {
    "disease": (208, 59, 59),    # 红 —— 病害
    "pest": (250, 178, 25),      # 橙 —— 虫害
    "other": (120, 120, 120),    # 灰 —— 未映射类别
}


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    """取中文字体。找不到就退回 PIL 内置位图字体（英文仍可读）。"""
    for path in (
        "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",   # 黑体
        "C:/Windows/Fonts/simsun.ttc",   # 宋体
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_annotated(image: Image.Image, dets: list[Detection]) -> Image.Image:
    """把检测框画进图里，返回新图（不修改入参）。

    这是"系统真的标注出了病虫害位置"的视觉证据，必须真实绘制，
    不接受前端叠加层冒充。
    """
    canvas = image.convert("RGB").copy()
    if not dets:
        return canvas

    draw = ImageDraw.Draw(canvas)
    w, h = canvas.size
    scale = max(w, h) / 1000.0
    line_w = max(2, round(3 * scale))
    font_size = max(14, round(22 * scale))
    font = _font(font_size)
    pad = max(3, round(5 * scale))

    for d in dets:
        color = CATEGORY_COLORS.get(d.category, CATEGORY_COLORS["other"])
        x1, y1 = d.x_px, d.y_px
        x2, y2 = x1 + d.w_px, y1 + d.h_px

        draw.rectangle([x1, y1, x2, y2], outline=color, width=line_w)

        label = f"{d.name_cn} {d.confidence:.0%}"
        tb = draw.textbbox((0, 0), label, font=font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        ty = y1 - th - pad * 2
        if ty < 0:                      # 框贴顶时标签改画到框内
            ty = y1
        draw.rectangle([x1, ty, x1 + tw + pad * 2, ty + th + pad * 2], fill=color)
        draw.text((x1 + pad, ty + pad - tb[1]), label, font=font, fill=(255, 255, 255))

    return canvas


# ═══════════════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════════════


def summarize(
    dets: list[Detection],
    img_w: int,
    img_h: int,
    type_confidence: float | None = None,
    type_class: tuple[str, str, str] | None = None,
) -> dict:
    """把原始检测列表压成前端要的 summary。

    `regionDesc` 是**真算出来的**（框按 y 聚到上/中/下三带 + 计数），
    不是写死的字符串。

    `type_confidence` 是 **YOLO 判型的诊断置信度**，必须由调用方传进来。
    不能拿 `dets[0].confidence` 顶替 —— 那是病灶框的贴合度，两者量级差很远
    （实测：稻瘟病判型 0.965 / 首个病灶框贴合度 0.373），混用会让识别页
    把一次高置信度的确诊显示成"置信度 37%"。

    `type_class` 同理，是 `effective_class()` 判出的 (code, 中文名, 类别)。
    ⚠️ **不要改回从 `dets[0]` 里读**：dets 按面积降序排，取首框等于把"是什么"
    绑在"最大的那个框"上。今天所有框共用同一个类别，这么取碰巧是对的；一旦
    框可以有不同的类别（例如将来接入害虫检测权重，虫体框与病斑框混在一起），
    一个比病斑更大的虫体框就会顶掉判型结果，让一张纯病叶的图报出害虫名。
    不传时才回退到首框 —— 那是退而求其次，正常调用一律显式传。
    """
    if not dets:
        return {
            "topClassName": None, "topClassCode": None, "category": None,
            "confidence": type_confidence or 0.0,
            "localizationScore": None,
            "severityLevel": "good", "severityLabel": "正常",
            "infectedAreaRatio": 0.0, "spotCount": 0,
            "regionDesc": "未检出病虫害", "advice": "未发现明显病虫害，建议保持常规巡田",
            "recommendedPlanKey": None,
            "counts": {"disease": 0, "pest": 0, "other": 0},
        }

    # 类别取判型结果，不取首框（理由见 docstring）
    code, name_cn, category = (
        type_class if type_class is not None
        else (dets[0].code, dets[0].name_cn, dets[0].category)
    )

    # 感染面积占比：各框面积并集太大不现实，这里取"各框面积之和"再截到 1，
    # 与本项目原有的 ratio 口径一致（原 demo 的 ratio 就是各病斑面积之和）。
    total_area = sum(d.area_ratio for d in dets)
    infected = min(1.0, total_area)

    level, level_cn = _band_of(infected)

    # 主区域 = 框最多的那一带
    band_count: dict[str, int] = {}
    for d in dets:
        band_count[_region_of(d.center_y)] = band_count.get(_region_of(d.center_y), 0) + 1
    main_band = max(band_count, key=lambda k: band_count[k])

    is_pest = category == "pest"
    unit = "处虫害" if is_pest else "处病斑"
    region_desc = f"叶片{REGION_CN[main_band]} · {len(dets)} {unit}"

    counts = {"disease": 0, "pest": 0, "other": 0}
    for d in dets:
        counts[d.category] = counts.get(d.category, 0) + 1

    return {
        "topClassName": name_cn,
        "topClassCode": code,
        "category": category,
        # 诊断置信度来自 YOLO；缺省回退到最好的那个框的贴合度，但那是退而求其次
        "confidence": type_confidence if type_confidence is not None
        else max(d.confidence for d in dets),
        "localizationScore": max(d.confidence for d in dets),
        "severityLevel": level,
        "severityLabel": level_cn,
        "infectedAreaRatio": round(infected, 4),
        "spotCount": len(dets),
        "regionDesc": region_desc,
        # 兜底措辞按类别分岔：虫害不能套"确认病原"那句（见 ADVICE_FALLBACK）
        "advice": ADVICE.get(code)
        or ADVICE_FALLBACK.get(category, ADVICE_FALLBACK["disease"]),
        "recommendedPlanKey": _plan_key_of(code),
        "counts": counts,
    }


def _band_of(area_ratio: float) -> tuple[str, str]:
    for threshold, level, label in SEVERITY_BANDS:
        if area_ratio < threshold:
            return level, label
    return "critical", "严重"


PLAN_KEY = {
    "rice_blast": "A", "rice_false_smut": "A", "sheath_blight": "A",
    "rice_brown_spot": "B", "bacterial_leaf_blight": "B",
    "planthopper": "C", "stem_borer": "C", "fall_armyworm": "C",
}


def _plan_key_of(code: str) -> str | None:
    """建议对应的喷洒方案（与 spray 页 A/B/C 共用同一套字典）。"""
    return PLAN_KEY.get(code)
