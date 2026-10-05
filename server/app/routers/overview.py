"""概览屏。

顶部 4 个 tile **来自 kpi_tiles 死表**（今日识别总次数、减排比例这类
"算不出来"的头部数字）；中间与底部的三张图来自 analysis_series。
农田规模从 fields 现算，不写死 —— 加一块田，这里的数字自己就变。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..db import query
from ..services.analytics import series_map
from ..services.serialize import camelize_all

router = APIRouter(prefix="/api", tags=["overview"])


@router.get("/overview")
async def overview() -> dict:
    fields = query("SELECT * FROM fields ORDER BY id")
    return {
        "tiles": camelize_all(
            query(
                "SELECT * FROM kpi_tiles WHERE screen='overview' ORDER BY sort_order"
            )
        ),
        # 按 seriesKey 索引：spkRecog / spkWarn / spkArea / spkPest /
        # composition（饼图）/ warnTrend（折线）
        "series": series_map("overview"),
        "fields": {
            "count": len(fields),
            "areaMu": round(sum(f["area_mu"] for f in fields), 1),
            "crop": fields[0]["crop"] if fields else "水稻",
            "items": camelize_all(fields),
        },
    }
