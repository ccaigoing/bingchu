"""实时监测屏。

四个 tile 的值是**算出来的**（最新一条 sensor_readings），不是存死的 ——
见 services/analytics.py 的说明。同一份 `readings` 同时喂三处：
tile 上的 sparkline、两张 30 点趋势折线、右下角"最新 8 条"数据流表。
前端各取所需，后端只出一个数据源，避免三处数字对不上。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import query
from ..services.analytics import (
    latest_drone_state,
    latest_reading,
    monitor_tiles,
    reading_history,
)
from ..services.serialize import camelize

router = APIRouter(prefix="/api", tags=["monitor"])

# 无人机卡片里的展示型常量。作业区域与飞行状态**不在这里** ——
# 那两项由正在执行的喷洒任务推出来（见下），能反映真实作业状态。
DRONE_ROUTE = "卡尔曼滤波 + PID 航迹"


def _drone() -> dict | None:
    state = latest_drone_state()
    if not state:
        return None

    task = query(
        "SELECT t.*, f.name AS field_name FROM spray_tasks t"
        " LEFT JOIN fields f ON f.id = t.field_id"
        " WHERE t.status IN ('running','paused') ORDER BY t.created_at DESC LIMIT 1"
    )
    task = task[0] if task else None

    status_cn = {"running": "喷洒作业中", "paused": "作业暂停", "pending": "待起飞"}
    return {
        "battery": state["battery"],
        "altitude": state["altitude"],
        "speed": state["speed"],
        # 飞行状态由任务状态推导，不是写死的字符串
        "status": status_cn.get(task["status"], "待命") if task else "待命",
        "statusTone": "good" if task and task["status"] == "running" else "warn",
        "area": task["title"] if task else "未分配作业区",
        "route": DRONE_ROUTE,
        "telemetryTs": state["ts"],
    }


@router.get("/monitor")
async def monitor(points: int = Query(30, ge=2, le=240)) -> dict:
    return {
        "tiles": monitor_tiles(),
        "readings": [camelize(r) for r in reading_history(points)],
        "drone": _drone(),
    }


@router.get("/sensors/latest")
async def sensors_latest() -> dict:
    """单点最新读数。

    这是 SSE 的**降级轮询**落点（见前端 useSSE）：网络或代理出问题时，
    前端退回到定时打这个端点，页面上的数字依然在动，不会僵住。
    """
    latest = latest_reading()
    return {
        "reading": camelize(latest) if latest else None,
        "tiles": monitor_tiles(),
        "drone": _drone(),
    }


@router.get("/sensors/history")
async def sensors_history(points: int = Query(30, ge=2, le=1440)) -> list[dict]:
    return [camelize(r) for r in reading_history(points)]
