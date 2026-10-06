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
from ..services.guard import inference_turn, limiter
from ..services.lesion import (
    build_detections,
    build_mud_mask,
    build_pest_detections,
    effective_class,
    has_type_verdict,
    locate_lesions,
)
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
        # 公网护栏的实时状态。透出来有两个用处：一是排查"怎么被限流了"时
        # 能直接看到计数；二是答辩现场可以当场展示"护栏在工作"，
        # 而不是只在代码里声称有。rejectedTotal 是进程启动以来的累计拒绝数。
        "guard": limiter.snapshot(),
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
    # 外面这层是**推理并发闸门**（见 services/guard.py）。注意是**逐个昂贵调用**
    # 占位，不是"整段推理占一个位"：解码、画标注图、写库这些廉价步骤不该占着
    # 位子不让别人用。效果一样 —— 任一时刻最多 INFER_CONCURRENCY 个重活在跑，
    # CPU 不会被抢崩；但排队粒度更细，一个请求不会因为别人在画图而空等。
    async with inference_turn("YOLO 判型"):
        yolo_dets, latency_ms = await run_in_threadpool(det.predict, image, conf, iou)
    top = yolo_dets[0] if yolo_dets else None
    top_code = top.code if top else None
    top_cn = top.name_cn if top else None
    top_cat = top.category if top else "other"

    # ── 第一步（补充）：虫害闸门 ──
    # **只在主判型说不出话时**才跑。闸门是一次完整的模型推理（CPU 上百毫秒），
    # 而识别得出结论的图根本不需要它 —— 现有三张病害图主判型都有结论，所以
    # 这条支路不会被触发，它们的输出与接闸门之前逐字节相同。
    #
    # ⚠️ 只读 `gate.fired`，**绝不读它的虫种名**。这个权重"看得见虫、定不准种"
    #    （同一张虫照换四种裁剪得到四个不同答案），虫种名只作诊断字段透出。
    #    顺带绕开一个坑：detector.resolve_class 现在靠 KEYWORD_RULES 宽词匹配，
    #    拿它的真实标签去跑，"corn borer" 会被 "borer" 吞成二化螟。本模块不调用
    #    resolve_class，所以那些标签永远不会变成业务结论。
    gate = None
    pg = getattr(request.app.state, "pest_gate", None)
    if pg is not None and pg.ready and not has_type_verdict(top_code, top_cat):
        async with inference_turn("虫害闸门"):
            gate = await run_in_threadpool(pg.fires, image)

    # ── 第二步：定位 ──
    # 类别归属只判一次，框与汇总共用同一个结果 —— 见 effective_class 的说明。
    # 以前 summarize 是从 dets[0]（面积最大的框）里读类别的，加害虫权重后
    # 会变成"最大的框是哪类就报哪类"，所以在这里就把它固定成判型结果。
    #
    # 放在定位之前，是因为"定位走哪条路"取决于判型结果（虫害/病害用不同的框）。
    cls = effective_class(
        top_code, top_cn, top_cat,
        pest_gate=bool(gate and gate.fired),
    )

    rgb = np.asarray(image)
    mud_mask = None

    if gate is not None and gate.fired and gate.boxes:
        # ── 2A. 虫害图：用**闸门自己的框** ──
        # 不用 HSV 病灶框：实测那张幼虫照上 HSV 出的 5 个框全是茎上的坏死/黄化区，
        # **没有一个压在虫体上**，还有 1 个落在虚焦背景上。闸门的框虽然松
        # （圈住整段受损茎、不贴虫体），但确实把虫体圈在里面 ——
        # 对"虫害"这个断言来说，框里有虫比框得紧更重要。
        dets = build_pest_detections(width, height, gate.boxes, cls)
        localization_method = "pest-gate"
    else:
        # ── 2B. 病害图：图像分割定位真实病斑 ──
        # 不能用 YOLO 的框：实测该权重输出的是整图框（分类数据集导出的检测集），
        # 它只回答"是什么病"，不回答"病在哪"。定位交给 lesion 层。
        #
        # 2b-1. 类无关分割 → 挑出「泥水」掩膜
        # 稻田泥水是褐色，落进 HSV 褐色分支，会和基部褐色病斑连成一个占图 45.5%
        # 的连通域，超过面积上限被整块丢弃 —— 真病斑跟着一起没了。
        # 分割器不可用 / 掩膜不可信时返回 None，下面就走纯 HSV 路径。
        seg = getattr(request.app.state, "segmenter", None)
        if seg is not None and seg.ready:
            async with inference_turn("FastSAM 分割"):
                masks = await run_in_threadpool(seg.segments, rgb)
            if masks:
                async with inference_turn("泥水掩膜"):
                    mud_mask = await run_in_threadpool(build_mud_mask, rgb, masks)

        # 2b-2. 病灶连通域（减去泥水后再连通，顺序不能反）
        # 全分辨率的 HSV + 形态学，同样吃 CPU，同样要占位
        async with inference_turn("病灶定位"):
            lesions = await run_in_threadpool(locate_lesions, rgb, exclude_mask=mud_mask)
        dets = build_detections(width, height, lesions, cls)
        localization_method = "lesion-cv+fastsam" if mud_mask is not None else "lesion-cv"

    # ── 画标注图 ──
    annotated = await run_in_threadpool(draw_annotated, image, dets)
    annotated_name = f"{uid}.jpg"
    annotated.save(UPLOAD_ANNOTATED_DIR / annotated_name, quality=92)

    # 诊断置信度传 YOLO 的判型结果，不是病灶框的贴合度 —— 见 summarize 的说明
    summary = summarize(
        dets, width, height,
        type_confidence=top.confidence if top else None,
        type_class=cls,
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
        "detect %s: YOLO=%s(%.3f) · 闸门=%s · 判为=%s · 病灶 %d 个 / %.0fms"
        " / mode=%s / 定位=%s",
        detection_id,
        top_code or "-", top.confidence if top else 0.0,
        ("未跑" if gate is None
         else f"{'响' if gate.fired else '默'}({gate.raw_label} {gate.confidence})"),
        cls[1],
        len(dets), latency_ms, det.mode, localization_method,
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
        # 分工必须写明白，不许让"YOLO 精准定位"变成一句虚话。
        # method 反映**本次实际生效**的引擎：减掉了泥水才是 +fastsam，
        # 降级时老老实实退回 lesion-cv，不冒领。
        "localization": {
            "method": localization_method,
            "note": (
                # method 反映**本次实际生效**的引擎，note 跟着它走，不各说各话。
                # 后半句是把话说全：这个框是**检测框**，比病灶框松得多，所以
                # infectedAreaRatio 是"框的面积"、不是实测受害面积 —— 不写这句，
                # 页面上那个占比会被当成量出来的感染率。
                "虫害框由虫害闸门权重给出（未定种，不给具体虫名）；"
                "该框为检测框、偏松，其面积不等于实测受害面积"
                if localization_method == "pest-gate"
                else "病灶框由图像分割生成，YOLO 仅用于判定病害类型"
                     + ("（已用通用分割排除泥水）" if mud_mask is not None else "")
            ),
            "yoloTopClass": top_code,
            "yoloTopNameCn": top_cn,
            "yoloConfidence": top.confidence if top else None,
            "yoloBoxIgnored": "whole-image" if top and top.w > 0.9 and top.h > 0.9 else None,
            # 闸门的完整交代 —— 读了它就能复盘"这次为什么报虫害/为什么没报"。
            # consulted=false 有两种情形，靠 mode 区分：主判型有结论（压根没跑）
            # vs 闸门降级不可用（mode="degraded"/"absent"）。
            # rawLabel / confidence 是**诊断字段，不是结论** —— 定种不可靠，
            # 业务侧（写库、展示、算建议）只许读 fired。
            "pestGate": {
                "consulted": gate is not None,
                "fired": bool(gate and gate.fired),
                "rawLabel": gate.raw_label if gate else None,
                "confidence": gate.confidence if gate else None,
                "threshold": pg.conf if pg is not None else None,
                "mode": pg.mode if pg is not None else "absent",
            },
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
