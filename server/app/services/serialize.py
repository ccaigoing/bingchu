"""数据库行 → 驼峰 JSON。

━━━ 为什么用统一的转换器，而不是逐字段手写 ━━━

本项目 25 张表约 150 个列。逐字段手写映射表有两个后果：一是冗长，
二是**会漂移** —— 加一列忘改一处就静默丢字段，而且是那种"前端某个数字
莫名不显示"的难查 bug。这里统一转换，规则只有一条：snake_case → camelCase。

⚠️ 但领域响应体**仍然手写**，不用这个转换器。例如 `/api/detect` 的返回：
那里做的不是"改个名"，而是**语义组装** —— 把 code / nameCn / category
拼成一个对象、把 areaRatio 算出来、把 `box` 与 `boxPx` 两套坐标并列。
那种地方手写才看得清契约。判断标准：**只是改名 → 用转换器；
要做组装或计算 → 手写。**

字段名对不上是前端最难查的一类 bug，所以转换规则必须唯一且可预测。
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def camel(name: str) -> str:
    """snake_case → camelCase。已经是驼峰的原样返回。"""
    head, *rest = name.split("_")
    return head + "".join(w[:1].upper() + w[1:] for w in rest if w)


def camelize(row: Mapping[str, Any]) -> dict[str, Any]:
    return {camel(k): v for k, v in row.items()}


def camelize_all(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [camelize(r) for r in rows]


def pct_to_ratio(value: float | None) -> float | None:
    """库里的百分数 → API 的 0–1 概率。

    ⚠️ 系统里**存在两个置信度刻度，这是有意的**：

    - **库表**存百分数（`96.2`）—— `detection_records` / `disease_samples`
      是从 legacy 显示口径迁来的**记录表**，同表的 `severity_label`、
      `region_desc` 也是展示型字段，百分数与它们同源。
    - **REST API** 一律 0–1 —— 与模型原生输出一致，也与阶段一已验证的
      `POST /api/detect` 契约一致（`tools/verify.html` 按 0–1 渲染）。

    转换只在这个函数里发生，所以想改口径只需要改这一处。
    """
    return None if value is None else round(value / 100.0, 4)
