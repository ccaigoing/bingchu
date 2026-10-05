"""预期效果屏。

4 个 tile 读 kpi_tiles（value_text 是**展示文案**，'×3.2' / '-20' 这种
带符号带乘号的字符串原样存原样出，不在后端转成浮点在前后端之间来回漂）。
评估方法 5 条读 knowledge_items。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..db import query
from ..services.analytics import series_for_screen
from ..services.serialize import camelize_all

router = APIRouter(prefix="/api", tags=["effect"])


def metrics_payload() -> dict:
    return {
        "tiles": camelize_all(
            query("SELECT * FROM kpi_tiles WHERE screen='effect' ORDER BY sort_order")
        ),
        "methods": camelize_all(
            query(
                "SELECT term, detail FROM knowledge_items"
                " WHERE topic='effect.methods' ORDER BY sort_order"
            )
        ),
    }


def comparison_payload() -> dict:
    """使用前后对比。库里是两条序列（before / after），各 3 个指标。"""
    items = [
        s for s in series_for_screen("effect")
        if s["seriesKey"].startswith("effect.comparison")
    ]
    if not items:
        return {"labels": [], "series": []}
    return {
        "labels": items[0]["labels"],
        "series": [
            {"key": s["seriesKey"], "name": s["title"], "values": s["values"]}
            for s in items
        ],
    }


@router.get("/effect/metrics")
async def effect_metrics() -> dict:
    return metrics_payload()


@router.get("/effect/comparison")
async def effect_comparison() -> dict:
    return comparison_payload()


@router.get("/effect")
async def effect_screen() -> dict:
    return {**metrics_payload(), "comparison": comparison_payload()}
