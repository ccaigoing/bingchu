"""虫害闸门（yolo11s-pest-ip102）：只回答"这张图里有没有虫"。

## 为什么需要它

`jktk_x.pt` 的 116 类里**没有任何水稻害虫类**，而 `lesion.py` 的 HSV 定位找的是
褐/黄/坏死斑 —— 虫子不是斑。所以一张害虫照片走完全链路只会得到「疑似病斑 ·
建议取样送检」，类型和位置都给不出来。

## ⚠️ 为什么只取布尔结论，不取虫种

这个权重**"看得见虫、但定不准种"**。实测（`tools/probe_pest.py`，同机 CPU）：

    剖茎幼虫照 2791x2091   conf=0.25 → 1 框 `flax budworm` 0.658
                           conf=0.02 → `asiatic rice borer` 仍然没出现

`flax budworm` 是亚麻害虫，**是错的**；框还圈住整段受损茎、不贴虫体。

级联（裁到检出框再跑一次）能得到 `asiatic rice borer` 0.519（对），但换四种
裁剪得到**四个不同答案** —— 这说明它定种的头不稳，属于"数字看着对"的形态，
本项目对此的一贯处理是**不做能力交付**（见 models/README.md 的同名章节）。

所以这里把它降级成一个**闸门**：`fired` 是唯一的输出，虫种名只作诊断字段
透出、绝不进入业务结论。

## 顺带避开的一个坑

`detector.resolve_class` 现在靠 `KEYWORD_RULES` 的宽词做模糊匹配，而
`RAW_LABEL_MAP` 是空的。拿这个权重的真实标签去跑，`corn borer` / `peach borer`
会被 `"borer"` 吞成二化螟、`yellow rice borer`（三化螟）也会变成二化螟。

**本模块从设计上就不调用 `resolve_class`** —— 不产出的字段就不会被写错。
这比"把 RAW_LABEL_MAP 填对"更可靠：前者是结构保证，后者要靠人不出错。

## 契约

与 `Detector` / `Segmenter` 完全一致：`load()` 绝不抛异常，失败 → `degraded`；
推理阻塞，调用方必须 `run_in_threadpool` 包一层。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..config import (
    DEFAULT_IOU,
    INFER_IMGSZ,
    PEST_GATE_CONF,
    PEST_GATE_ENABLED,
    PEST_WEIGHTS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateResult:
    """闸门的一次判定。

    `raw_label` 是**诊断信息，不是结论** —— 它只在 `/api/detect` 响应的
    `localization.pestGate` 里透出，供答辩与排查使用。业务侧（写库、展示、
    算建议）只许读 `fired` 与 `boxes`，**绝不许读 `raw_label`**。

    `boxes` 是**像素坐标**的 `(x1, y1, x2, y2, conf)`，与 `raw_label` 不同，
    它是可以进业务结论的 —— 虫种认不准，但"这一片里有虫"是可信的。
    为什么虫害图不用 HSV 病灶框定位：同一张幼虫照上 HSV 出的 5 个框全是茎上的
    坏死/黄化区，**没有一个压在虫体上**，还有 1 个落在虚焦背景上；闸门的框虽然
    松（圈住整段受损茎、不贴虫体），但确实把虫体圈在里面。
    """

    fired: bool
    raw_label: str | None
    confidence: float | None
    boxes: tuple[tuple[float, float, float, float, float], ...] = ()


class PestGate:
    """虫害闸门权重的加载与推理封装。"""

    def __init__(
        self,
        weights: Path = PEST_WEIGHTS,
        imgsz: int = INFER_IMGSZ,
        conf: float = PEST_GATE_CONF,
        enabled: bool = PEST_GATE_ENABLED,
    ) -> None:
        self.weights = Path(weights)
        self.imgsz = imgsz
        self.conf = conf
        self.enabled = enabled
        self._model = None
        self.model_names: dict[int, str] = {}
        self.mode = "degraded"          # 加载成功前一律视为降级
        self.error: str | None = None
        self.loaded_at: float | None = None
        self.last_latency_ms: float = 0.0

    # ── 生命周期 ──
    def load(self) -> None:
        """加载权重。失败不抛异常 —— 闸门挂了不该带崩整个服务。"""
        if not self.enabled:
            self.mode, self.error = "degraded", "虫害闸门已被 PEST_GATE_ENABLED 关闭"
            logger.info("虫害闸门关闭，判型回落原有路径")
            return
        if not self.weights.exists():
            self.mode, self.error = "degraded", f"权重文件不存在: {self.weights}"
            logger.warning("虫害闸门降级：%s", self.error)
            return
        try:
            from ultralytics import YOLO

            t0 = time.perf_counter()
            model = YOLO(str(self.weights))
            self._model = model
            self.model_names = dict(model.names)

            # 预热：把 lazy init（权重反序列化、算子图构建、线程池起池）的代价
            # 从"第一张害虫照片上传时"挪到"服务启动时"。
            # ⚠️ detector.py 的注释声称做了这件事但代码里没有 —— 别照抄那个遗漏。
            model.predict(
                source=Image.new("RGB", (self.imgsz, self.imgsz)),
                imgsz=self.imgsz, conf=self.conf, iou=DEFAULT_IOU,
                device="cpu", verbose=False,
            )

            self.mode, self.error = "normal", None
            self.loaded_at = time.time()
            logger.info(
                "虫害闸门就绪: %s (%d 类, conf>=%.2f, %.1fs)",
                self.weights.name, len(self.model_names), self.conf,
                time.perf_counter() - t0,
            )
        except Exception as exc:  # noqa: BLE001 —— 任何加载失败都必须降级而非崩溃
            self._model = None
            self.mode, self.error = "degraded", f"{type(exc).__name__}: {exc}"
            logger.exception("虫害闸门加载失败，判型回落原有路径")

    @property
    def ready(self) -> bool:
        return self._model is not None and self.mode == "normal"

    # ── 推理 ──
    def fires(self, image: Image.Image) -> GateResult | None:
        """这张图里有没有虫。

        `None` = 装置不可用（降级 / 本次推理抛错），调用方按"闸门沉默"处理 ——
        与 `Segmenter.segments` 的 `None` 语义一致：不可用，必须回落。
        """
        if not self.ready:
            return None

        t0 = time.perf_counter()
        try:
            results = self._model.predict(
                source=image, imgsz=self.imgsz, conf=self.conf,
                iou=DEFAULT_IOU, device="cpu", verbose=False,
            )
        except Exception:  # noqa: BLE001 —— 单张图失败不该让整套装置永久降级
            logger.exception("虫害闸门推理失败，本张图按沉默处理")
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            return None
        self.last_latency_ms = (time.perf_counter() - t0) * 1000

        # conf 已在 predict 里过滤，所以"有框"就等于"过了阈值"
        boxes = results[0].boxes if results else None
        if boxes is None or len(boxes) == 0:
            return GateResult(fired=False, raw_label=None, confidence=None)

        # xyxy 由 ultralytics 换算回**原图**像素坐标（与 Detector.predict 同一套）
        rows = []
        for i in range(len(boxes)):
            x1, y1, x2, y2 = (float(v) for v in boxes.xyxy[i])
            rows.append((x1, y1, x2, y2, float(boxes.conf[i].item())))
        rows.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)

        best = max(range(len(boxes)), key=lambda i: float(boxes.conf[i].item()))
        cls_id = int(boxes.cls[best].item())
        return GateResult(
            fired=True,
            raw_label=self.model_names.get(cls_id, f"class_{cls_id}"),
            confidence=round(float(boxes.conf[best].item()), 4),
            boxes=tuple(rows),
        )
