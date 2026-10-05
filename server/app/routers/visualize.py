"""数据可视化屏。

三块内容：近 30 日三病害趋势折线、3 号试验田 8×6 严重度地图、
农药使用量前后对比柱状图。

「多系列折线」在库里是**多行** analysis_series（每行一条线），
这里按 series_key 前缀合并成一张图。合并时保留 DB 的 sort_order ——
按 key 字母序排会把图例顺序变成 白叶枯病/稻瘟病/稻曲病，与原设计不符。

━━ 写法约定：先普通函数，再薄路由 ━━

本模块的聚合端点 `/visualize` 需要复用 `/field/severity` 的逻辑。
**不能直接 `await field_severity()`** —— 路由函数的默认值是 FastAPI 的
`Query(...)` 对象，直接调用时参数拿到的是 Query 实例而不是真值，
轻则 500，重则静默走错分支。所以查询逻辑一律写成普通函数，
路由只负责把 HTTP 参数传进去。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import query
from ..services.analytics import series_for_screen, series_map
from ..services.serialize import camelize

router = APIRouter(prefix="/api", tags=["visualize"])

# 与 legacy renderFieldMap 的 SEV_CN 逐字一致
SEV_CN = ["正常", "轻微", "轻度", "中度", "重度", "严重"]

# legacy: v>=3 才在格子里显示「X排X号」文字，低于中度只留颜色
SEV_LABEL_FROM = 3


def _group(series_list: list[dict], prefix: str) -> dict:
    """把同前缀的多条序列合并成一张多系列图。"""
    items = [s for s in series_list if s["seriesKey"].startswith(prefix)]
    if not items:
        return {"labels": [], "unit": None, "series": []}
    return {
        "labels": items[0]["labels"],
        "unit": items[0]["unit"],
        "series": [
            {"key": s["seriesKey"], "name": s["title"], "values": s["values"]}
            for s in items
        ],
    }


def field_severity(field_id: int = 3) -> dict:
    """某块田最新一期的地块严重度。

    48 格按 (row_no, col_no) 排成行优先序，前端直接顺序映射进 8 列网格，
    不需要自己算坐标。
    """
    rows_field = query("SELECT * FROM fields WHERE id = ?", (field_id,))
    if not rows_field:
        return {"error": f"地块 {field_id} 不存在", "code": "FIELD_NOT_FOUND"}
    field = rows_field[0]

    rows = query(
        """
        SELECT p.code, p.row_no, p.col_no, p.label, f.severity, f.ts
        FROM field_severity f
        JOIN plots p ON p.id = f.plot_id
        WHERE p.field_id = ?
          AND f.ts = (SELECT MAX(ts) FROM field_severity)
        ORDER BY p.row_no, p.col_no
        """,
        (field_id,),
    )

    return {
        "fieldId": field_id,
        "fieldName": field["name"],
        "crop": field["crop"],
        "areaMu": field["area_mu"],
        "rows": 6,
        "cols": 8,
        "ts": rows[0]["ts"] if rows else None,
        # 图例色阶的文字标签，前端配 PALETTES[theme].seq[0..5] 取色
        "severityLabels": SEV_CN,
        "cells": [
            {
                "code": r["code"],
                "rowNo": r["row_no"],
                "colNo": r["col_no"],
                "label": r["label"],
                "severity": r["severity"],
                "severityLabel": SEV_CN[min(r["severity"], len(SEV_CN) - 1)],
                "showLabel": r["severity"] >= SEV_LABEL_FROM,
            }
            for r in rows
        ],
    }


def _screen_payload() -> dict:
    series = series_for_screen("visualize")
    return {
        "trend": _group(series, "visualize.trend30"),
        "pesticide": _group(series, "visualize.pesticide"),
        "field": field_severity(),
        "series": series_map("visualize"),
    }


@router.get("/field/severity")
async def get_field_severity(field_id: int = Query(3)) -> dict:
    return field_severity(field_id)


@router.get("/field/plots")
async def field_plots(field_id: int = Query(3)) -> list[dict]:
    rows = query(
        "SELECT * FROM plots WHERE field_id = ? ORDER BY row_no, col_no", (field_id,)
    )
    return [camelize(r) for r in rows]


@router.get("/analytics/trend")
async def analytics_trend() -> dict:
    return _group(series_for_screen("visualize"), "visualize.trend30")


@router.get("/analytics/pesticide-usage")
async def analytics_pesticide_usage() -> dict:
    return _group(series_for_screen("visualize"), "visualize.pesticide")


@router.get("/visualize")
async def visualize() -> dict:
    """首屏聚合：一次拿全，避免三个请求各自到达造成画面跳变。"""
    return _screen_payload()
