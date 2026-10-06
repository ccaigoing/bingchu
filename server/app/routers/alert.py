"""预警屏（只读）。

⚠️ 顶部四个 tile 的数字是**从 warnings 表数出来的**，不是照抄原 demo。
原 demo 的 tile 写死 3 / 5 / 9 / 14，而它自己的预警列表只有 11 条
（3 严重 / 5 较重 / 3 一般 / 4 已处理）—— 这两组数字不可能同时成立。
现在改为现场 COUNT，tile 与下面的表在结构上不可能再打架。
因此本页「一般预警」会显示 3、「今日已处理」会显示 4，与原 demo 的 9 / 14 不同：
**这是修正，不是回归。**

写操作有两个（处理预警、调阈值），逻辑在 services/alerting.py。
它们**不在** 2.5 的实时引擎里：原 demo 的「处理」按钮只改内存数组、刷新即复原，
如果 2.4 只搬一个点了没反应的按钮，这一屏就还是个壳。所以提前把落库补上。

查询逻辑写成普通函数再套路由 —— 原因见 visualize.py 顶部说明。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from ..db import query
from ..services.alerting import BadValue, NotFound, handle_warning, update_threshold
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


# ── 写操作 ────────────────────────────────────────────────


class ThresholdPatch(BaseModel):
    """只收一个 value。范围由 min_value/max_value 在服务端定义，不由请求方声明。"""

    value: float = Field(description="目标值，必须落在该阈值的 minValue–maxValue 内")


@router.post("/warnings/{warning_id}/handle")
async def mark_handled(warning_id: int) -> dict:
    """把一条预警标记为已处理。幂等：重复调用返回同一行，不报错。

    前端点完要重取 `/api/alert` —— tile 的「严重预警」「今日已处理」是
    COUNT 出来的，不重取就还是旧数字，tile 又和表打架了。
    """
    try:
        return handle_warning(warning_id)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/thresholds/{key}")
async def patch_threshold(key: str, body: ThresholdPatch) -> dict:
    try:
        return update_threshold(key, body.value)
    except NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except BadValue as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
