"""识别相关 API。

阶段一只需要 `POST /api/detect` 这一个端点把链路打通；
记录管理（`/detect/records` 等）留到阶段二接入数据库时再加。
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import (
    ALLOWED_EXT,
    DEFAULT_CONF,
    DEFAULT_IOU,
    DEFAULT_WEIGHTS,
    MAX_UPLOAD_BYTES,
    UPLOAD_ANNOTATED_DIR,
    UPLOAD_ORIG_DIR,
)
from ..services.detector import draw_annotated, summarize
from ..services.lesion import build_detections, locate_lesions

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["detect"])


@router.get("/health")
async def health(request: Request) -> dict:
    """存活探针 + 当前模型状态。前端用它决定是否显示降级 banner。"""
    det = request.app.state.detector
    return {
        "status": "ok",
        "model": {
            "name": det.weights.stem,
            "device": det.device,
            "mode": det.mode,
            "error": det.error,
            "classCount": len(det.model_names),
        },
    }


@router.get("/detect/classes")
async def list_classes(request: Request) -> dict:
    """当前权重认得的**原始**类别清单。

    阶段一直接用第三方权重，类别体系是它的，不是我们的；
    这个端点用来核对真实类别名，据此填写 detector.RAW_LABEL_MAP。
    """
    det = request.app.state.detector
    return {
        "mode": det.mode,
        "count": len(det.model_names),
        "names": {str(k): v for k, v in sorted(det.model_names.items())},
    }


@router.post("/detect")
async def detect(
    request: Request,
    file: UploadFile = File(...),
    conf: float = Form(DEFAULT_CONF),
    iou: float = Form(DEFAULT_IOU),
) -> dict:
    """上传一张图片，返回带框标注图与结构化检测结果。"""
    det = request.app.state.detector

    # ── 上传校验：扩展名 + 大小 ──
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail={"error": f"不支持的图片格式 {suffix or '(无扩展名)'}",
                    "code": "BAD_EXTENSION",
                    "detail": f"仅支持 {'/'.join(sorted(ALLOWED_EXT))}"},
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=400,
            detail={"error": "图片过大", "code": "TOO_LARGE",
                    "detail": f"上限 {MAX_UPLOAD_BYTES // 1024 // 1024} MB"},
        )
    if not raw:
        raise HTTPException(
            status_code=400,
            detail={"error": "空文件", "code": "EMPTY_FILE"},
        )

    # ── 落盘原图 ──
    uid = uuid.uuid4().hex[:12]
    stamp = datetime.now().strftime("%Y%m%d")
    detection_id = f"det_{stamp}_{uid}"

    orig_name = f"{uid}{suffix}"
    orig_path = UPLOAD_ORIG_DIR / orig_name
    orig_path.write_bytes(raw)

    # ── 解码 + 按 EXIF 摆正（手机照片不摆正，框位置会整体偏转）──
    try:
        with Image.open(orig_path) as im:
            image = ImageOps.exif_transpose(im).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        orig_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400,
            detail={"error": "图片无法解码", "code": "DECODE_FAILED", "detail": str(exc)},
        ) from exc

    width, height = image.size

    # ── 第一步：YOLO 判型（阻塞，丢线程池，别堵事件循环）──
    yolo_dets, latency_ms = await run_in_threadpool(det.predict, image, conf, iou)
    top = yolo_dets[0] if yolo_dets else None

    # ── 第二步：图像分割定位真实病斑 ──
    # 不能用 YOLO 的框：实测该权重输出的是整图框（分类数据集导出的检测集），
    # 它只回答"是什么病"，不回答"病在哪"。定位交给 lesion 层。
    lesions = await run_in_threadpool(locate_lesions, np.asarray(image))

    dets = build_detections(
        width, height, lesions,
        top.code if top else None,
        top.name_cn if top else None,
        top.category if top else "other",
    )

    # ── 画标注图 ──
    annotated = await run_in_threadpool(draw_annotated, image, dets)
    annotated_name = f"{uid}.jpg"
    annotated.save(UPLOAD_ANNOTATED_DIR / annotated_name, quality=92)

    summary = summarize(dets, width, height)

    logger.info(
        "detect %s: YOLO=%s(%.3f) · 病灶 %d 个 / %.0fms / mode=%s",
        detection_id,
        top.code if top else "-", top.confidence if top else 0.0,
        len(dets), latency_ms, det.mode,
    )

    return {
        "detectionId": detection_id,
        "model": {
            "name": f"yaodao-{det.weights.stem}",
            "version": "pretrained-apache2.0",
            "device": det.device,
            # 降级必须显式透出 —— 绝不静默回落
            "mode": det.mode,
            "error": det.error,
        },
        # 分工必须写明白，不许让"YOLO 精准定位"变成一句虚话
        "localization": {
            "method": "lesion-cv",
            "note": "病灶框由图像分割生成，YOLO 仅用于判定病害类型",
            "yoloTopClass": top.code if top else None,
            "yoloTopNameCn": top.name_cn if top else None,
            "yoloConfidence": top.confidence if top else None,
            "yoloBoxIgnored": "whole-image" if top and top.w > 0.9 and top.h > 0.9 else None,
        },
        "latencyMs": round(latency_ms, 1),
        "image": {
            "originalUrl": f"/uploads/orig/{orig_name}",
            "annotatedUrl": f"/uploads/annotated/{annotated_name}",
            "width": width,
            "height": height,
        },
        "summary": summary,
        "detections": [d.to_dict() for d in dets],
        "counts": summary["counts"],
    }
