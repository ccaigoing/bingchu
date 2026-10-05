"""喷洒方案屏。

方案 A/B/C 的农药产品来自 `spray_plans.product_id → products`，
**与识别页"建议措施"里的产品是同一行** —— 这就是"7 屏数据自洽"的结构保证，
不是靠文案对齐。

雷达图五维分值现在读 spray_plan_scores（seed 写入）。阶段四的 MADM 会接替
写入这张表，届时 API 与前端一行不用改。
"""

from __future__ import annotations

from fastapi import APIRouter

from ..db import query
from ..services.serialize import camelize

router = APIRouter(prefix="/api", tags=["spray"])


def plan_payload() -> dict:
    plans = query(
        """
        SELECT sp.*,
               p.code AS p_code, p.name AS p_name, p.formulation, p.kind,
               p.eco_score, p.cost_per_mu AS p_cost
        FROM spray_plans sp
        JOIN products p ON p.id = sp.product_id
        ORDER BY sp.sort_order
        """
    )

    # 五维分值。维度顺序取分值表自己的 sort_order —— 三个方案共用同一套维度，
    # 这里不假设是哪五个，维度名从数据里来。
    scores = query(
        "SELECT s.plan_id, s.dimension, s.score FROM spray_plan_scores s"
        " JOIN spray_plans p ON p.id = s.plan_id"
        " ORDER BY p.sort_order, s.sort_order"
    )
    by_plan: dict[int, list[dict]] = {}
    dimensions: list[str] = []
    for s in scores:
        by_plan.setdefault(s["plan_id"], []).append(
            {"dimension": s["dimension"], "score": s["score"]}
        )
        if s["dimension"] not in dimensions:
            dimensions.append(s["dimension"])

    out = []
    for p in plans:
        out.append({
            "planKey": p["plan_key"],
            "name": p["name"],
            "tagline": p["tagline"],
            "recommended": bool(p["recommended"]),
            "product": {
                "code": p["p_code"],
                "name": p["p_name"],
                "formulation": p["formulation"],
                "kind": p["kind"],
                "ecoScore": p["eco_score"],
                "costPerMu": p["p_cost"],
            },
            "dosage": p["dosage"],
            "timing": p["timing"],
            "efficacy": p["efficacy"],
            "costPerMu": p["cost_per_mu"],
            "scores": by_plan.get(p["id"], []),
        })

    return {
        "plans": out,
        "radar": {
            "dimensions": dimensions,
            "series": [
                {
                    "key": p["planKey"],
                    "name": p["name"],
                    "values": [s["score"] for s in p["scores"]],
                }
                for p in out
            ],
        },
    }


def active_task_payload() -> dict | None:
    task = query(
        "SELECT t.*, f.name AS field_name FROM spray_tasks t"
        " LEFT JOIN fields f ON f.id = t.field_id"
        " WHERE t.status IN ('running','paused','pending')"
        " ORDER BY t.created_at DESC LIMIT 1"
    )
    if not task:
        return None

    task = task[0]
    logs = query(
        "SELECT time_text, event FROM spray_logs WHERE task_id = ? ORDER BY sort_order",
        (task["id"],),
    )
    return {
        "task": camelize(task),
        "logs": [{"time": r["time_text"], "event": r["event"]} for r in logs],
    }


@router.get("/spray/plans")
async def spray_plans() -> dict:
    return plan_payload()


@router.get("/spray/tasks/active")
async def active_task() -> dict | None:
    return active_task_payload()


@router.get("/spray")
async def spray_screen() -> dict:
    return {**plan_payload(), "active": active_task_payload()}
