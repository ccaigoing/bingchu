"""字典类端点：类别 / 产品 / 模型登记 / 数据溯源 / 知识条目。

这几个是**跨屏共用**的只读字典，不属于任何单一屏，所以单独成组。
`disease_classes` 是本系统的单一事实源 —— 识别页的"建议措施"、预警页的
"类型"、喷洒页的方案目标，全部指向它。这里把类别与推荐产品**连接后**返回，
前端一次拿到，避免在前端做二次 join 导致两屏显示不一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from ..db import query
from ..services.serialize import camelize_all

router = APIRouter(prefix="/api", tags=["catalog"])


@router.get("/classes")
async def list_classes() -> list[dict]:
    """规范类别字典（8 类）+ 各自的推荐产品与建议措施。

    手写组装而非 camelize：这里要把 classes / class_products / products
    三张表拼成一个嵌套对象，不是单纯的列改名。
    """
    rows = query(
        """
        SELECT d.code, d.name_cn, d.name_en, d.category, d.dataset_label,
               d.sort_order,
               cp.dosage, cp.plan_key, cp.advice,
               p.code AS p_code, p.name AS p_name, p.formulation,
               p.kind, p.eco_score, p.cost_per_mu
        FROM disease_classes d
        LEFT JOIN class_products cp ON cp.class_code = d.code
        LEFT JOIN products p ON p.id = cp.product_id
        ORDER BY d.sort_order
        """
    )
    out = []
    for r in rows:
        out.append({
            "code": r["code"],
            "nameCn": r["name_cn"],
            "nameEn": r["name_en"],
            "category": r["category"],
            # 显式映射列，绝不靠字符串匹配 —— Leaf Smut ≠ 稻曲病
            "datasetLabel": r["dataset_label"],
            "product": None if r["p_code"] is None else {
                "code": r["p_code"],
                "name": r["p_name"],
                "formulation": r["formulation"],
                "kind": r["kind"],
                "ecoScore": r["eco_score"],
                "costPerMu": r["cost_per_mu"],
            },
            "dosage": r["dosage"],
            "planKey": r["plan_key"],
            "advice": r["advice"],
        })
    return out


@router.get("/products")
async def list_products(
    kind: str | None = Query(None, pattern="^(chemical|biological)$"),
) -> list[dict]:
    sql = "SELECT * FROM products"
    params: tuple = ()
    if kind:
        sql += " WHERE kind = ?"
        params = (kind,)
    return camelize_all(query(sql + " ORDER BY id", params))


@router.get("/models")
async def list_models() -> list[dict]:
    """模型登记表 —— 答辩溯源用。前端"模型与数据"区直接渲染这张表。"""
    return camelize_all(query("SELECT * FROM model_registry ORDER BY id"))


@router.get("/datasets")
async def list_datasets() -> list[dict]:
    """数据溯源表。

    `status='planned'` 的几行是**刻意保留**的：真实气象数据（ERA5 / IMERG /
    田间气象站）尚未接入，把"计划接入但还没接"显式登记出来，
    比假装数据齐全要诚实，答辩被问到时这张表就是答案。
    """
    return camelize_all(query("SELECT * FROM datasets ORDER BY id"))


@router.get("/knowledge")
async def list_knowledge(topic: str = Query(..., min_length=1)) -> list[dict]:
    """按 topic 取键值说明条目，例如 topic=effect.methods。"""
    return camelize_all(
        query(
            "SELECT term, detail FROM knowledge_items"
            " WHERE topic = ? ORDER BY sort_order",
            (topic,),
        )
    )
