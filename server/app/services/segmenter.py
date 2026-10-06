"""类无关的通用分割服务（FastSAM-s）：把画面切成一个个对象。

**它不判病害类型。** 病害类型完全由 `detector.py` 的 YOLO 负责。这里的唯一
职责是产出「哪些像素是泥水」所需的原料 —— 逐对象的掩膜，好让 `lesion.py`
把泥水从病灶候选里减掉。

为什么需要它：HSV 颜色分割单独用不成立。稻田泥水是褐色，落进褐色分支，
与植株基部的褐色病斑连成**一个占图 45.5% 的连通域**，超过面积上限被整块丢弃
—— 真病斑是它的一部分，跟着一起没了。这个 bug 用颜色/几何的启发式修不掉
（本会话实测否决了 5 种，见计划文件），必须引入"对象"这一层信息。

设计要点：

1. **先缩到 ≤640 再分割**。`routers/detect.py` 全链路不缩放，而
   `static/uploads/orig/` 里真实存在 4096×3072 的上传图。`retina_masks=True`
   会把**每一个** mask 都上采样回输入尺寸 —— 十几个 mask × 12.58 MP 就是
   几百 MB。所以在缩放后的图上跑，调用方只把**最终的并集**上采样一次。
2. **`iou=0.9` 是 FastSAM 的官方设定，不是随手写的**。FastSAM 靠大量重叠的
   候选 mask 才能把"植株"与"泥"分开；用常规的 0.45 做 NMS 会把大部分 mask
   抑制掉，泥水掩膜就没了。
3. **契约与 `Detector` 完全一致**：`load()` 绝不抛异常，失败 → `degraded`；
   推理是阻塞的，调用方必须用 `run_in_threadpool` 包一层。
4. `segments()` 返回 `None` 与 `[]` **含义不同**：`None` = 这套装置不可用
   （降级 / 本次推理失败），调用方必须回落；`[]` = 跑了但一个 mask 都没有，
   这是关于这张图的**结论**，不是故障。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import cv2
import numpy as np

from ..config import SEGMENTER_ENABLED, SEGMENTER_IMGSZ, SEGMENTER_WEIGHTS

logger = logging.getLogger(__name__)

# FastSAM 推理参数。**这两个值与 YOLO 检测用的 DEFAULT_CONF/DEFAULT_IOU
# 是两回事，别互相套** —— 那边是在"框得准不准"上权衡，这边是要"别漏对象"。
#
# ⚠️ conf 必须压到 0.15，这是实测出来的，不是随手写的。在 474x561 的出错图上：
#
#     imgsz=640  conf=0.4(官方默认) → 13 个 mask，泥水对象**根本不存在**
#     imgsz=640  conf=0.25          → 泥水掩膜只有 1.4%，仍然没切出泥水
#     imgsz=640  conf=0.15          → 一块 22.5% 面积、绿 0.4%、离红 11.3 的干净泥水 ✅
#
# 原因：泥水是低对比度的大片区域，FastSAM 给它的置信度天生偏低。用官方默认值
# 会把它连同"泥水"这个概念一起丢掉，整套装置就白装了。
#
# iou=0.9 是 FastSAM 的官方设定：它靠大量**重叠**的候选 mask 才切得开
# 植株与泥；用常规的 0.45 做 NMS 会把它们抑制掉。
SEG_CONF = 0.15
SEG_IOU = 0.9


def bound(rgb: np.ndarray, max_side: int) -> np.ndarray:
    """把最长边缩到 ≤ max_side，返回新数组（不改原图）。

    缩小用 `INTER_AREA`（下采样正确做法，避免摩尔纹）。已经够小的图原样返回
    —— 放大没有意义，只会凭空造出细节。
    """
    h, w = rgb.shape[:2]
    long_side = max(h, w)
    if long_side <= max_side:
        return rgb
    scale = max_side / long_side
    return cv2.resize(
        rgb, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
        interpolation=cv2.INTER_AREA,
    )


class Segmenter:
    """FastSAM 权重的加载与推理封装。"""

    def __init__(
        self,
        weights: Path = SEGMENTER_WEIGHTS,
        imgsz: int = SEGMENTER_IMGSZ,
        enabled: bool = SEGMENTER_ENABLED,
    ) -> None:
        self.weights = Path(weights)
        self.imgsz = imgsz
        self.enabled = enabled
        self._model = None
        self.mode = "degraded"          # 加载成功前一律视为降级
        self.error: str | None = None
        self.loaded_at: float | None = None
        self.last_latency_ms: float = 0.0

    # ── 生命周期 ──
    def load(self) -> None:
        """加载权重。失败不抛异常 —— 分割层挂了不该带崩整个服务。"""
        if not self.enabled:
            self.mode, self.error = "degraded", "分割层已被 SEGMENTER_ENABLED 关闭"
            logger.info("分割层关闭，定位走纯 HSV 路径")
            return
        if not self.weights.exists():
            self.mode, self.error = "degraded", f"权重文件不存在: {self.weights}"
            logger.warning("分割模型降级：%s", self.error)
            return
        try:
            from ultralytics import FastSAM

            t0 = time.perf_counter()
            model = FastSAM(str(self.weights))
            self._model = model

            # 预热：跑一次真实推理，把 lazy init（权重反序列化、算子图构建、
            # 线程池起池）的代价从"第一个用户上传时"挪到"服务启动时"。
            # ⚠️ detector.py 的注释声称做了这件事但代码里没有 —— 别照抄那个遗漏。
            dummy = np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8)
            model.predict(
                source=dummy, imgsz=self.imgsz, conf=SEG_CONF, iou=SEG_IOU,
                retina_masks=True, device="cpu", verbose=False,
            )

            self.mode, self.error = "normal", None
            self.loaded_at = time.time()
            logger.info(
                "分割模型就绪: %s (imgsz=%d, %.1fs)",
                self.weights.name, self.imgsz, time.perf_counter() - t0,
            )
        except Exception as exc:  # noqa: BLE001 —— 任何加载失败都必须降级而非崩溃
            self._model = None
            self.mode, self.error = "degraded", f"{type(exc).__name__}: {exc}"
            logger.exception("分割模型加载失败，定位回落纯 HSV")

    @property
    def ready(self) -> bool:
        return self._model is not None and self.mode == "normal"

    # ── 推理 ──
    def segments(self, rgb: np.ndarray) -> list[np.ndarray] | None:
        """把图切成若干对象，返回**缩放分辨率下**的逐对象布尔掩膜。

        `None` = 装置不可用（降级 / 本次推理抛错），调用方必须回落。
        `[]`   = 跑了，但没切出任何对象 —— 这是结论，不是故障。
        """
        if not self.ready:
            return None

        small = bound(rgb, self.imgsz)
        t0 = time.perf_counter()
        try:
            results = self._model.predict(
                source=small, imgsz=self.imgsz, conf=SEG_CONF, iou=SEG_IOU,
                retina_masks=True, device="cpu", verbose=False,
            )
        except Exception:  # noqa: BLE001 —— 单张图失败不该让整套装置永久降级
            logger.exception("分割推理失败，本张图回落纯 HSV")
            self.last_latency_ms = (time.perf_counter() - t0) * 1000
            return None
        self.last_latency_ms = (time.perf_counter() - t0) * 1000

        if not results or results[0].masks is None:
            return []

        # masks.data 形状 (N, h, w)；retina_masks=True 时 h/w 就是 small 的尺寸。
        data = results[0].masks.data
        if data is None or len(data) == 0:
            return []
        return [m > 0.5 for m in data.cpu().numpy()]
