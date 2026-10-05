"""只读的派生数据：图表序列组装、tile 计算。

分两类，界线很重要：

- **序列组装**（`series_for_screen`）—— 把 analysis_series / analysis_points
  两张表折成前端要的形状。纯搬运，不产生新数值。

- **tile 计算**（`monitor_tiles` / `alert_tiles`）—— 值是真的算出来的。
  监测页取最新一条 sensor_readings，预警页按级别 COUNT(warnings)。
  之所以现场算而不像概览页那样存死表：**tile 不能和底下的表打架**。
  ⚠️ 顺带修正了原 demo 的一处自相矛盾：legacy 的预警 tile 写死 3/5/9/14，
  而它自己的预警列表只有 11 条（3 严重 / 5 较重 / 3 一般 / 4 已处理）。
  现在改为从表里数，这个矛盾结构上不可能再出现。
"""

from __future__ import annotations

from typing import Any

from ..db import query

# ═══════════════════════════════════════════════════════════
# 图表序列
# ═══════════════════════════════════════════════════════════


def series_for_screen(screen: str) -> list[dict[str, Any]]:
    """某屏的全部图表序列。

    每个图是**多行** analysis_series（一张多系列折线 = 多条序列），
    这里折成前端直接可用的形状：labels 是 X 轴刻度，values 是数据点。
    """
    rows = query(
        """
        SELECT s.series_key, s.title, s.unit, s.chart_type, s.sort_order,
               p.seq, p.point_label, p.value
        FROM analysis_series s
        LEFT JOIN analysis_points p ON p.series_id = s.id
        WHERE s.screen = ?
        ORDER BY s.sort_order, p.seq
        """,
        (screen,),
    )

    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        key = r["series_key"]
        if key not in out:
            out[key] = {
                "seriesKey": key,
                "title": r["title"],
                "unit": r["unit"],
                "chartType": r["chart_type"],
                "labels": [],
                "values": [],
            }
        if r["value"] is not None:
            out[key]["labels"].append(r["point_label"])
            out[key]["values"].append(r["value"])
    return list(out.values())


def series_map(screen: str) -> dict[str, dict[str, Any]]:
    """按 series_key 索引的版本，给"我就想要某一张图"的场景。"""
    return {s["seriesKey"]: s for s in series_for_screen(screen)}


# ═══════════════════════════════════════════════════════════
# 传感器
# ═══════════════════════════════════════════════════════════


def reading_history(limit: int = 30) -> list[dict[str, Any]]:
    """最近 limit 个采样点，**按时间正序**返回（图表从左到右是时间流）。"""
    rows = query(
        "SELECT * FROM sensor_readings ORDER BY ts DESC LIMIT ?", (limit,)
    )
    return list(reversed(rows))


def latest_reading() -> dict[str, Any] | None:
    rows = query("SELECT * FROM sensor_readings ORDER BY ts DESC LIMIT 1")
    return rows[0] if rows else None


def latest_drone_state() -> dict[str, Any] | None:
    """最近一条带无人机遥测的读数。

    遥测是单点快照，不是每个采样点都有，所以要单独找 —— 直接取最新一行
    会在下一批只写环境数据的采样点上取到 NULL。
    """
    rows = query(
        "SELECT battery, altitude, speed, ts FROM sensor_readings"
        " WHERE battery IS NOT NULL ORDER BY ts DESC LIMIT 1"
    )
    return rows[0] if rows else None


# 监测页四个 tile。格式化精度对齐 legacy 的 tick（legacy:1061-1064）：
# 湿度显示 "62.0" 而不是 "62"，pH 显示 "6.30" 而不是 "6.3" ——
# 静态 HTML 里写的是后者，但每 2 秒的 tick 会覆盖成前者，以 tick 为准。
MONITOR_TILES: list[tuple[str, str, str, str, str]] = [
    # (key, 标题, 读数列, 小数位, 单位)
    ("temp", "空气温度", "temp", 1, "℃"),
    ("hum", "空气湿度", "hum", 1, "%"),
    ("ph", "土壤 pH", "ph", 2, ""),
    ("light", "光谱光照", "light", 1, "kLx"),
]

# 各读数的正常区间，用于 tile 上那句状态文字（legacy 写死"正常/适宜"）
MONITOR_BANDS: dict[str, tuple[float, float, str]] = {
    "temp": (15.0, 32.0, "正常"),
    "hum": (45.0, 85.0, "正常"),
    "ph": (5.5, 7.0, "适宜"),
    "light": (20.0, 60.0, "正常"),
}


def monitor_tiles() -> list[dict[str, Any]]:
    latest = latest_reading()
    if not latest:
        return []

    tiles = []
    for key, label, col, prec, unit in MONITOR_TILES:
        raw = latest.get(col)
        lo, hi, ok_text = MONITOR_BANDS[key]
        in_band = raw is not None and lo <= raw <= hi
        tiles.append({
            "key": key,
            "label": label,
            "value": "—" if raw is None else f"{raw:.{prec}f}",
            "unit": unit,
            "note": ok_text if in_band else "偏离",
            "tone": "up" if in_band else "down",
            "sparkKey": f"monitor.spk{key.capitalize()}",
        })
    return tiles


# ═══════════════════════════════════════════════════════════
# 预警
# ═══════════════════════════════════════════════════════════

# 预警页四个 tile。level → (标题, 状态文字, 状态样式)
ALERT_TILES: list[tuple[str, str, str]] = [
    ("critical", "严重预警", "需立即处理"),
    ("serious", "较重预警", "今日处理中"),
    ("warning", "一般预警", "持续关注"),
]

LEVEL_CN = {"critical": "严重", "serious": "较重", "warning": "一般"}


def warning_counts() -> dict[str, int]:
    rows = query("SELECT level, COUNT(*) AS c FROM warnings GROUP BY level")
    counts = {r["level"]: r["c"] for r in rows}
    done = query("SELECT COUNT(*) AS c FROM warnings WHERE status='done'")[0]["c"]
    return {
        "critical": counts.get("critical", 0),
        "serious": counts.get("serious", 0),
        "warning": counts.get("warning", 0),
        "done": done,
        "total": sum(counts.values()),
        "undone": sum(counts.values()) - done,
    }


def alert_tiles() -> list[dict[str, Any]]:
    counts = warning_counts()
    tiles = [
        {
            "key": level,
            "label": label,
            "value": str(counts[level]),
            "unit": "",
            "note": note,
            "tone": "down" if level == "critical" else "up",
            "status": level,
        }
        for level, label, note in ALERT_TILES
    ]
    tiles.append({
        "key": "done",
        "label": "今日已处理",
        "value": str(counts["done"]),
        "unit": "",
        "note": "闭环完成",
        "tone": "up",
        "status": "good",
    })
    return tiles
