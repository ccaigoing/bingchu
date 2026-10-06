"""预警与阈值的**写操作**。读操作（列表、统计、tile）在 analytics.py。

为什么单独一个模块而不是并进 analytics：那个模块有一句自我约束 ——
「series_for_screen 只搬运、不产生新数字」。写操作混进去会让那条约束失效，
下一个人就不知道该往哪加东西了。读写分家。

原 demo 的「处理」按钮只改内存数组（`w.status="done"`），刷新即复原 ——
是演示壳。这里落库，所以刷新后还在，tile 计数也跟着变。
"""

from __future__ import annotations

from ..db import get_conn
from .serialize import camelize

# ⚠️ 这里必须 `dict(row)`：`sqlite3.Row` 支持按键取值和 `keys()`，
# 但**没有 `.items()`** —— camelize 收到 Row 会报 AttributeError。
# db.query() 内部已经转好 dict，所以只读路径上碰不到这个坑；
# 写路径上手写 conn.execute 时每条都要自己转。


class NotFound(Exception):
    """找不到目标行。路由层翻成 404。"""


class BadValue(Exception):
    """阈值越界或类型不对。路由层翻成 422。"""


def handle_warning(warning_id: int) -> dict:
    """把一条预警标记为已处理，返回更新后的整行。

    **幂等**：已经是 done 的直接返回当前行，不报错 —— 演示时连点两下
    （或者断网重试）不应该弹出错误。
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM warnings WHERE id = ?", (warning_id,)).fetchone()
        if row is None:
            raise NotFound(f"预警 {warning_id} 不存在")

        if row["status"] != "done":
            conn.execute("UPDATE warnings SET status = 'done' WHERE id = ?", (warning_id,))
            row = conn.execute("SELECT * FROM warnings WHERE id = ?", (warning_id,)).fetchone()
        return camelize(dict(row))


def update_threshold(key: str, value: float) -> dict:
    """改一个阈值，返回更新后的整行。

    ⚠️ **在服务端校验范围**，不能只靠前端的 `min`/`max`：
    滑块属性只是 UI 提示，一个手写的请求可以传 9999，之后预警引擎
    就会用这个值去判，产生一堆莫名其妙的预警。
    """
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM alert_thresholds WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise NotFound(f"阈值 {key} 不存在")

        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise BadValue("value 必须是数字")
        lo, hi = float(row["min_value"]), float(row["max_value"])
        if not (lo <= float(value) <= hi):
            raise BadValue(f"{row['label']} 的取值范围是 {lo:g}–{hi:g}{row['unit'] or ''}")

        conn.execute("UPDATE alert_thresholds SET value = ? WHERE key = ?", (float(value), key))
        updated = conn.execute(
            "SELECT * FROM alert_thresholds WHERE key = ?", (key,)
        ).fetchone()
        return camelize(dict(updated))
