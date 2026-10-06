"""识别记录的落库与读取。

这一步是验收标准 6 的落点：「识别页记录表新增一行，来自 DB 而非前端数组」。
阶段一只有内存里的一次性响应，没有记录；到这里每次上传都写真库。

⚠️ 写入时 confidence **乘 100 存**（库表是百分数刻度，见 serialize.pct_to_ratio
的说明）；读出来给 API 时再除回 0–1。两个刻度之间只有这一进一出两个转换点。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..db import get_conn, query
from .serialize import camelize_all, pct_to_ratio


def save_detection(
    detection_id: str,
    summary: dict[str, Any],
    detections: list[dict[str, Any]],
    original_url: str,
    annotated_url: str,
) -> None:
    """把一次识别落库：1 条记录 + N 个检测框。

    整段在一个事务里 —— 记录写进去但框没写，会让详情页打开是空图。
    """
    now = datetime.now().isoformat(timespec="seconds")

    with get_conn() as conn:
        # class_code 有外键指向 disease_classes，而「疑似病斑」(SUSPECT_CODE) 和
        # 「虫害（未定种）」(PEST_UNKNOWN_CODE) 都是**哨兵**，不是规范类别 ——
        # 那张字典是"病种/虫种"字典，"没结论"和"未定种"恰恰是"没有类别"。
        # 硬写进去就是 FK 失败 → 整张上传 500（实测：任何一张 116 类映射不上的
        # 照片都会触发，包括用户那张害虫照）。落库为 NULL 才是哨兵真实的语义。
        # name_cn 照常写「疑似病斑」/「虫害（未定种）」，前端照常显示。
        class_code = summary.get("topClassCode")
        if class_code is not None and conn.execute(
            "SELECT 1 FROM disease_classes WHERE code = ?", (class_code,)
        ).fetchone() is None:
            class_code = None

        cur = conn.execute(
            "INSERT INTO detection_records"
            " (detection_id, class_code, name_cn, confidence, severity,"
            "  severity_label, infected_area_ratio, spot_count, region_desc,"
            "  advice, image_url, annotated_url, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'upload',?)",
            (
                detection_id,
                class_code,
                summary.get("topClassName") or "未识别",
                # 百分数刻度落库
                round(float(summary.get("confidence") or 0.0) * 100, 1),
                summary.get("severityLevel") or "good",
                summary.get("severityLabel") or "正常",
                summary.get("infectedAreaRatio"),
                summary.get("spotCount"),
                summary.get("regionDesc"),
                summary.get("advice"),
                original_url,
                annotated_url,
                now,
            ),
        )
        record_id = cur.lastrowid

        conn.executemany(
            "INSERT INTO detection_objects"
            " (record_id, seq, class_code, name_cn, category, localization_score,"
            "  x, y, w, h) VALUES (?,?,?,?,?,?,?,?,?,?)",
            [
                (
                    record_id, i,
                    d.get("code"), d.get("nameCn") or "未识别",
                    d.get("category") or "other",
                    # 框贴合度，不是诊断置信度 —— 两者量级不同，别拿错字段
                    d.get("localizationScore"),
                    d["box"]["x"], d["box"]["y"], d["box"]["w"], d["box"]["h"],
                )
                for i, d in enumerate(detections)
            ],
        )


def list_records(limit: int = 6, source: str | None = None) -> list[dict[str, Any]]:
    """识别记录列表，最新在前。

    只做列改名 + 置信度刻度归一，所以走 camelize。
    """
    sql = "SELECT * FROM detection_records"
    params: list = []
    if source:
        sql += " WHERE source = ?"
        params.append(source)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = camelize_all(query(sql, tuple(params)))
    for r in rows:
        r["confidence"] = pct_to_ratio(r.get("confidence"))
        # 展示用的时间戳：legacy 记录表只显示 HH:MM:SS，顺手给出来
        r["timeText"] = (r.get("createdAt") or "")[11:19]
    return rows


def record_objects(record_id: int) -> list[dict[str, Any]]:
    """某条记录的检测框。

    注意这里**不做** pct_to_ratio —— localization_score 本来就是 0–1 的
    贴合度，不是百分数刻度的诊断置信度。
    """
    return camelize_all(
        query(
            "SELECT * FROM detection_objects WHERE record_id = ? ORDER BY seq",
            (record_id,),
        )
    )
