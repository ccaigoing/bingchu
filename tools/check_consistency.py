"""断言「代码里的类别字典」与「数据库里的类别字典」完全一致。

用法（可在任意目录运行）：
    E:/anaconda3/python.exe tools/check_consistency.py

━━━ 为什么必须有这个脚本 ━━━
方案里反复强调 disease_classes 是**单一事实源**，但代码里存在两处副本：

  services/detector.py   推理时要解析模型原始标签，必须有一份内存里的字典
                         （数据库没建起来时检测也得能给出建议）
  app/seed.py            往库里灌的那一份

只要这两份漂移，就会出现最难查的一类 bug：**识别页说稻瘟病、喷洒页找不到对应产品**。
7 个屏的数据互相自洽是答辩口径的核心，靠人工比对保不住，所以用断言守住。

任何一处检查失败都退出码非 0，可以直接挂进 CI 或提交前钩子。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

from app.db import query  # noqa: E402
from app.services import detector  # noqa: E402

failures: list[str] = []
checks = 0


def check(cond: bool, label: str, detail: str = "") -> None:
    global checks
    checks += 1
    if cond:
        print(f"  ✓ {label}")
    else:
        print(f"  ✗ {label}")
        if detail:
            print(f"      {detail}")
        failures.append(label)


def main() -> int:
    print("检查 1/4 · 类别字典 (detector.CANONICAL ↔ disease_classes)")
    rows = query("SELECT code, name_cn, category FROM disease_classes")
    db_classes = {r["code"]: (r["name_cn"], r["category"]) for r in rows}
    code_classes = {c: (cn, cat) for c, (cn, cat) in detector.CANONICAL.items()}

    check(set(db_classes) == set(code_classes),
          "两边的 code 集合相同",
          f"仅代码有: {set(code_classes) - set(db_classes)}；仅库里有: {set(db_classes) - set(code_classes)}")
    for code in sorted(set(db_classes) & set(code_classes)):
        check(db_classes[code] == code_classes[code],
              f"{code} 的中文名与类别一致",
              f"库里 {db_classes[code]} vs 代码 {code_classes[code]}")

    print("\n检查 2/4 · 建议措施 (detector.ADVICE ↔ class_products.advice)")
    rows = query("SELECT class_code, advice FROM class_products")
    db_advice = {r["class_code"]: r["advice"] for r in rows}

    check(set(db_advice) == set(code_classes),
          "每个类别都有推荐产品",
          f"缺: {set(code_classes) - set(db_advice)}")
    for code in sorted(set(db_advice) & set(detector.ADVICE)):
        check(db_advice[code] == detector.ADVICE[code],
              f"{code} 的建议措辞逐字相同",
              f"库里「{db_advice[code]}」 vs 代码「{detector.ADVICE[code]}」")

    print("\n检查 3/4 · 方案档位 (detector.PLAN_KEY ↔ class_products.plan_key)")
    rows = query("SELECT class_code, plan_key FROM class_products WHERE plan_key IS NOT NULL")
    db_plan = {r["class_code"]: r["plan_key"] for r in rows}
    check(db_plan == detector.PLAN_KEY,
          "A/B/C 档位映射一致",
          f"仅库里有: {set(db_plan.items()) - set(detector.PLAN_KEY.items())}；"
          f"仅代码有: {set(detector.PLAN_KEY.items()) - set(db_plan.items())}")

    print("\n检查 4/4 · 跨屏引用完整性")
    rows = query("""
        SELECT cp.class_code, cp.plan_key, dc.name_cn,
               p.name AS product, sp.plan_key AS plan_of_that_key, sp_p.name AS plan_product
        FROM class_products cp
        JOIN disease_classes dc ON dc.code = cp.class_code
        JOIN products p        ON p.id  = cp.product_id
        LEFT JOIN spray_plans sp   ON sp.plan_key = cp.plan_key
        LEFT JOIN products sp_p    ON sp_p.id = sp.product_id
        ORDER BY cp.class_code
    """)
    check(all(r["plan_of_that_key"] for r in rows),
          "每个 plan_key 都能在 spray_plans 里找到对应方案")

    # 验收清单第 7 条：识别页建议的农药 == 喷洒页方案 A 的产品
    rows = query("""
        SELECT p.name AS product
        FROM class_products cp JOIN products p ON p.id = cp.product_id
        WHERE cp.class_code = 'rice_blast'
    """)
    advice_product = rows[0]["product"] if rows else None
    rows = query("""
        SELECT p.name AS product FROM spray_plans sp
        JOIN products p ON p.id = sp.product_id WHERE sp.plan_key = 'A'
    """)
    plan_a_product = rows[0]["product"] if rows else None
    check(advice_product is not None and advice_product == plan_a_product,
          "识别页「稻瘟病」建议的产品 == 喷洒页方案 A 的产品",
          f"建议 {advice_product} vs 方案A {plan_a_product}")

    # 识别记录 / 样本 / 图表刻度里出现的名称，必须都能对上类别字典
    for table, col in (("detection_records", "name_cn"), ("disease_samples", "name_cn")):
        rows = query(f"SELECT DISTINCT {col} AS n FROM {table}")
        known = {cn for cn, _ in code_classes.values()} | {"其他"}
        unknown = {r["n"] for r in rows} - known
        check(not unknown, f"{table}.{col} 全部能对上类别字典",
              f"对不上的: {unknown}")

    print()
    if failures:
        print(f"✗ {len(failures)}/{checks} 项不通过：")
        for f in failures:
            print(f"    · {f}")
        return 1
    print(f"✓ 全部 {checks} 项通过 —— 代码与数据库的类别字典一致。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
