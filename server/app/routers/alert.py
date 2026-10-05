"""预警屏（只读）。

⚠️ 顶部四个 tile 的数字是**从 warnings 表数出来的**，不是照抄原 demo。
原 demo 的 tile 写死 3 / 5 / 9 / 14，而它自己的预警列表只有 11 条
（3 严重 / 5 较重 / 3 一般 / 4 已处理）—— 这两组数字不可能同时成立。
现在改为现场 COUNT，tile 与下面的表在结构上不可能再打架。
因此本页「一般预警」会显示 3、「今日已处理」会显示 4，与原 demo 的 9 / 14 不同：
**这是修正，不是回归。**

写操作（处理预警、调阈值）留给阶段二 2.5：
阈值滑块目前只读显示，拖动后的持久化端点在那里加。

查询逻辑写成普通函数再套路由 —— 原因见 visualize.py 顶部说明。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import query
from ..services.analytics import alert_tiles, warning_counts
from ..services.serialize import camelize_all

router = APIRouter(prefix="/api", tags=["alert"])


def fetch_warnings(
    level: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """预警列表。筛选条件与页面上那排 chip（全部/严重/较重/一般/未处理）一一对应。"""
    sql = "SELECT * FROM warnings WHERE 1=1"
    params: list = []

    if level:
        sql += " AND level = ?"
        params.append(level)
    if status:
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (type LIKE ? OR area LIKE ? OR warning_no LIKE ?)"
        params.extend([f"%{q}%"] * 3)

    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    return camelize_all(query(sql, tuple(params)))


def fetch_thresholds() -> list[dict]:
    return camelize_all(query("SELECT * FROM alert_thresholds ORDER BY sort_order"))


@router.get("/warnings")
async def list_warnings(
    level: str | None = Query(None, pattern="^(critical|serious|warning)$"),
    status: str | None = Query(None, pattern="^(done|undone)$"),
    q: str | None = Query(None, description="按类型 / 位置 / 编号模糊匹配"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[dict]:
    return fetch_warnings(level, status, q, limit)


@router.get("/thresholds")
async def list_thresholds() -> list[dict]:
    return fetch_thresholds()


@router.get("/alert")
async def alert_screen() -> dict:
    return {
        "tiles": alert_tiles(),
        "counts": warning_counts(),
        "warnings": fetch_warnings(),
        "thresholds": fetch_thresholds(),
    }
