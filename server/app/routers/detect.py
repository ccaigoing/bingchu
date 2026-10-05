"""识别相关 API。

两类端点：
  - **推理** `POST /api/detect` —— 阶段一打通的链路，现在额外落库
  - **记录** `/detect/records` `/detect/samples` `/detect/stats` —— 识别屏的
    下半部分，全部来自数据库

`/detect/classes` 给的是**规范 8 类字典**（来自 disease_classes）；
模型认得的 116 个原始标签挪到了 `/detect/model-classes` —— 那是核对权重用的
调试端点，不是业务契约。两个都留着，但名字必须分清，否则前端会拿原始标签去
匹配喷洒方案，静默匹配不上。
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
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
from ..db import query
from ..services.analytics import series_for_screen
from ..services.detector import draw_annotated, summarize
from ..services.lesion import build_detections, locate_lesions
from ..services.records import list_records, record_objects, save_detection
from ..services.serialize import camelize_all, pct_to_ratio

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


def class_counts(sort: str = "count") -> list[dict]:
    """规范类别字典 + 各自的识别次数。识别屏右上那张柱状图的数据源。

    `count` 来自 analysis_series 的 identify.classCount（近 30 日）；
    字典里有但没被识别过的类别补 0 —— 不能因为没数据就从图里消失，
    否则答辩时"为什么只有四种病"会被问。
    """
    dict_rows = query(
        "SELECT code, name_cn, category FROM disease_classes ORDER BY sort_order"
    )
    counts = {
        s["labels"][i]: int(s["values"][i])
        for s in series_for_screen("identify")
        if s["seriesKey"] == "identify.classCount"
        for i in range(len(s["labels"]))
    }

    out = [
        {
            "code": r["code"],
            "nameCn": r["name_cn"],
            "category": r["category"],
            "count": counts.get(r["name_cn"], 0),
        }
        for r in dict_rows
    ]
    if sort == "count":
        out.sort(key=lambda x: x["count"], reverse=True)
    return out


def sample_rows() -> list[dict]:
    """演示样本。

    ⚠️ 这是**演示素材**，不是识别结果。识别屏接入真实上传后，左侧叶片区改为
    显示后端标注图；这些样本降级为下方的"示例图"缩略图。
    """
    samples = camelize_all(
        query("SELECT * FROM disease_samples ORDER BY sort_order")
    )
    spots = query(
        "SELECT sample_id, cx, cy, radius FROM sample_spots ORDER BY sample_id, seq"
    )
    by_sample: dict[int, list] = {}
    for s in spots:
        by_sample.setdefault(s["sample_id"], []).append(
            {"cx": s["cx"], "cy": s["cy"], "r": s["radius"]}
        )

    for s in samples:
        s["confidence"] = pct_to_ratio(s.get("confidence"))
        s["spots"] = by_sample.get(s.pop("id"), [])
    return samples


def detection_stats() -> dict:
    total = query("SELECT COUNT(*) AS c FROM detection_records")[0]["c"]
    uploaded = query(
        "SELECT COUNT(*) AS c FROM detection_records WHERE source='upload'"
    )[0]["c"]
    return {"total": total, "uploaded": uploaded, "seeded": total - uploaded}


@router.get("/detect/classes")
async def list_classes(sort: str = Query("count", pattern="^(count|name)$")) -> list[dict]:
    return class_counts(sort)


@router.get("/detect/model-classes")
async def list_model_classes(request: Request) -> dict:
    """当前权重认得的**原始** 116 个标签。

    调试端点，不是业务契约 —— 用来核对权重真实类别名、据此维护
    detector.RAW_LABEL_MAP / KEYWORD_RULES。业务侧一律走 /detect/classes。
    """
    det = request.app.state.detector
    return {
        "mode": det.mode,
        "count": len(det.model_names),
        "names": {str(k): v for k, v in sorted(det.model_names.items())},
    }


@router.get("/detect/records")
async def detect_records(
    limit: int = Query(6, ge=1, le=100),
    source: str | None = Query(None, pattern="^(seed|upload)$"),
) -> list[dict]:
    """识别记录，最新在前。默认 6 条，对齐识别屏那张表。"""
    return list_records(limit=limit, source=source)


@router.get("/detect/records/{record_id}/objects")
async def detect_record_objects(record_id: int) -> list[dict]:
    """某条记录里的检测框（归一化坐标），用于在图上叠加可交互框。"""
    return record_objects(record_id)


@router.get("/detect/samples")
async def detect_samples() -> list[dict]:
    return sample_rows()


@router.get("/detect/stats")
async def detect_stats() -> dict:
    return detection_stats()


@router.get("/detect")
async def identify_screen() -> dict:
    """识别屏首屏聚合。左栏样本 / 右栏记录 / 下方柱状图一次取全。

    调的是普通函数不是路由函数 —— 路由函数的默认值是 Query 对象，
    直接调会静默传错值（详见 visualize.py 顶部说明）。
    """
    return {
        "samples": sample_rows(),
        "records": list_records(limit=6),
        "classes": class_counts("count"),
        "stats": detection_stats(),
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

    # 诊断置信度传 YOLO 的判型结果，不是病灶框的贴合度 —— 见 summarize 的说明
    summary = summarize(
        dets, width, height,
        type_confidence=top.confidence if top else None,
    )

    # ── 落库（验收标准 6：记录表新增一行，来自 DB 而非前端数组）──
    # 放在返回之前，但**失败不吞异常**：写不进去就该 500，
    # 不能让用户看到"识别成功"而记录表里没有。
    orig_url = f"/uploads/orig/{orig_name}"
    annotated_url = f"/uploads/annotated/{annotated_name}"
    await run_in_threadpool(
        save_detection,
        detection_id, summary, [d.to_dict() for d in dets],
        orig_url, annotated_url,
    )

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
            "originalUrl": orig_url,
            "annotatedUrl": annotated_url,
            "width": width,
            "height": height,
        },
        "summary": summary,
        "detections": [d.to_dict() for d in dets],
        "counts": summary["counts"],
    }
