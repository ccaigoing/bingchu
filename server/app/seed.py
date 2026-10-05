"""把 legacy/index.html 里全部硬编码数据迁进 SQLite。

用法（在 `server/` 目录下）：

    E:/anaconda3/python.exe -m app.seed            # 重建（先删库）
    E:/anaconda3/python.exe -m app.seed --keep     # 只往空表里补，不动已有数据

出处逐条标注在下方各 SECTION 里，对照 legacy/index.html 的行号。

────────────────────────────────────────────────────────────
三处**刻意的规范化**（与 legacy 显示不完全一致，都是有意的）
────────────────────────────────────────────────────────────

1. **害虫名称统一用规范名**。legacy 的样本与识别记录里写的是「草地贪夜蛾为害」，
   规范类别字典里是「草地贪夜蛾」。既然 disease_classes 是单一事实源，
   显示名就应当由它来定，而不是各屏各写一份。

2. **样本的建议措施改用规范措辞**。legacy 的稻瘟病样本写「立即喷洒三环唑，
   用量 40g/亩」，白叶枯病写「加强通风，观察 2 日后复检」——
   后者压根没提农药。现在一律取 class_products.advice，
   这样"识别页的建议农药 == 喷洒页方案 A 的产品"是结构性成立的
   （验收清单第 7 条），而不是靠人工比对。

3. **传感器历史是确定性生成的**。legacy 用 `Math.random()`，每次刷新曲线都不同，
   无法复现也无法测试。这里改用固定种子的随机游走，且**从锚点反向生成**，
   保证最后一个点精确等于 26.4 / 62 / 6.3 / 38.0 —— 监测页四个 tile 显示的
   就是最后一个点，必须对齐。
"""

from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import datetime, timedelta

from .db import get_conn, init_db, table_counts

# 固定种子：换这个数会得到另一套（同样合法的）传感器曲线
SEED = 20261006


def _now() -> datetime:
    return datetime.now().replace(microsecond=0)


def _iso(dt: datetime) -> str:
    return dt.isoformat(sep="T")


# ═══════════════════════════════════════════════════════════
# 类别字典 —— 必须与 services/detector.py 的 CANONICAL 逐字一致
# tools/check_consistency.py 会断言这一点
# ═══════════════════════════════════════════════════════════

# code: (中文名, 英文名, disease|pest)
CLASSES: list[tuple[str, str, str, str]] = [
    ("rice_blast", "稻瘟病", "Rice Blast", "disease"),
    ("rice_brown_spot", "稻胡麻斑病", "Rice Brown Spot", "disease"),
    ("bacterial_leaf_blight", "白叶枯病", "Bacterial Leaf Blight", "disease"),
    ("sheath_blight", "纹枯病", "Sheath Blight", "disease"),
    ("rice_false_smut", "稻曲病", "Rice False Smut", "disease"),
    ("planthopper", "稻飞虱", "Rice Planthopper", "pest"),
    ("stem_borer", "二化螟", "Rice Stem Borer", "pest"),
    ("fall_armyworm", "草地贪夜蛾", "Fall Armyworm", "pest"),
]

# 农药产品。eco_score / cost_per_mu 只填**有出处**的：
# 环保性分来自喷洒页雷达图的「环保性」维度，成本来自方案卡片的「综合成本」。
# 其余 6 个产品只用于生成建议措辞，没有分数来源，一律留 NULL —— 不编数字。
PRODUCTS: list[tuple[str, str, str, str, float | None, float | None]] = [
    # (code, 名称, 剂型, chemical|biological, eco_score, cost_per_mu)
    ("tricyclazole", "三环唑 75% 可湿粉", "可湿粉", "chemical", 72.0, 6.8),
    ("isoprothiolane", "稻瘟灵 40% 乳油", "乳油", "chemical", 66.0, 5.2),
    ("bacillus_subtilis", "枯草芽孢杆菌生物制剂", "生物制剂", "biological", 96.0, 9.5),
    ("thiazole_zinc", "噻唑锌 20% 悬浮剂", "悬浮剂", "chemical", None, None),
    ("validamycin", "井冈霉素 5% 水剂", "水剂", "biological", None, None),
    ("difenoconazole_propiconazole", "苯醚甲环唑·丙环唑", "乳油", "chemical", None, None),
    ("pymetrozine", "吡蚜酮 25% 可湿粉", "可湿粉", "chemical", None, None),
    ("chlorantraniliprole", "氯虫苯甲酰胺 20% 悬浮剂", "悬浮剂", "chemical", None, None),
    ("emamectin_benzoate", "甲维盐 1% 乳油", "乳油", "chemical", None, None),
]

# 类别 → 推荐产品 + 用量 + 对策档位（A 高效 / B 低成本 / C 环保）
# advice 必须与 detector.py 的 ADVICE 逐字相同 —— 那边是"数据库还没建起来时
# 检测也能给出建议"的兜底，权威来源是这张表。
# (class_code, product_code, dosage, plan_key, advice)
CLASS_PRODUCTS: list[tuple[str, str, str, str | None, str]] = [
    ("rice_blast", "tricyclazole", "40 g/亩", "A",
     "立即喷洒三环唑 75% 可湿粉，用量 40 g/亩"),
    ("rice_brown_spot", "isoprothiolane", "100 mL/亩", "B",
     "喷洒稻瘟灵 40% 乳油，用量 100 mL/亩"),
    ("bacterial_leaf_blight", "thiazole_zinc", "100 mL/亩", "B",
     "喷洒噻唑锌 20% 悬浮剂，用量 100 mL/亩"),
    ("sheath_blight", "validamycin", "150 mL/亩", "A",
     "喷洒井冈霉素 5% 水剂，用量 150 mL/亩"),
    ("rice_false_smut", "difenoconazole_propiconazole", "30 mL/亩", "A",
     "抽穗前喷洒苯醚甲环唑·丙环唑，用量 30 mL/亩"),
    ("planthopper", "pymetrozine", "20 g/亩", "C",
     "喷洒吡蚜酮 25% 可湿粉，用量 20 g/亩"),
    ("stem_borer", "chlorantraniliprole", "10 mL/亩", "C",
     "喷洒氯虫苯甲酰胺 20% 悬浮剂，用量 10 mL/亩"),
    ("fall_armyworm", "emamectin_benzoate", "50 mL/亩", "C",
     "喷洒甲维盐 1% 乳油，用量 50 mL/亩"),
]


# ═══════════════════════════════════════════════════════════
# SECTION: 地块
# 出处：legacy 概览 tile「覆盖农田面积 320 亩」+ 各屏出现的田块名
# 四块田面积之和刻意取 320，与概览那个 tile 对齐，避免答辩时对不上数
# ═══════════════════════════════════════════════════════════

FIELDS: list[tuple[str, str, float, str, str]] = [
    ("F1", "1 号田", 68.0, "水稻", "北区 / 西区"),
    ("F2", "2 号田", 76.0, "水稻", "西区 / 南区 / 北区"),
    ("F3", "3 号试验田", 96.0, "水稻", "东区 32 亩，含 8×6 地块；系统主作业区"),
    ("F4", "4 号田", 80.0, "水稻", "全域 / 东区"),
]

# 3 号试验田的 48 格严重度，出处 legacy:946 的 sev 数组
SEV_48: list[int] = [
    0, 1, 2, 2, 1, 0, 3, 4,
    2, 3, 4, 5, 3, 2, 1, 0,
    2, 3, 3, 2, 1, 0, 1, 2,
    4, 5, 4, 3, 2, 1, 0, 0,
    1, 2, 3, 3, 2, 1, 0, 1,
    2, 3, 4, 3, 2, 1, 0, 1,
]

# 严重度中文名，出处 legacy:947
SEV_CN = ["正常", "轻微", "轻度", "中度", "重度", "严重"]


# ═══════════════════════════════════════════════════════════
# SECTION: 预警
# 出处 legacy:766-778 的 warnSeed[11]
# ═══════════════════════════════════════════════════════════

WARNS: list[tuple[str, str, str, str, str, str]] = [
    ("W-2041", "稻瘟病爆发风险", "critical", "3 号田 · 东区", "09:42", "undone"),
    ("W-2040", "草地贪夜蛾为害", "critical", "3 号田 · 南区", "09:31", "undone"),
    ("W-2039", "稻瘟病局部加重", "critical", "1 号田 · 北区", "09:18", "undone"),
    ("W-2038", "稻曲病扩散", "serious", "2 号田 · 西区", "09:05", "undone"),
    ("W-2037", "土壤 pH 偏低", "serious", "3 号田 · 东区", "08:52", "undone"),
    ("W-2036", "湿度超阈值", "serious", "4 号田 · 全域", "08:40", "undone"),
    ("W-2035", "白叶枯病初现", "serious", "2 号田 · 南区", "08:26", "undone"),
    ("W-2034", "温度接近上限", "serious", "3 号田 · 全域", "08:12", "done"),
    ("W-2033", "光谱异常提示", "warning", "1 号田 · 西区", "07:58", "done"),
    ("W-2032", "pH 轻微波动", "warning", "4 号田 · 东区", "07:44", "done"),
    ("W-2031", "湿度偏低提示", "warning", "2 号田 · 北区", "07:30", "done"),
]

# 出处 legacy:531-534 的四个滑块
THRESHOLDS: list[tuple[str, str, str, float, float, float, float]] = [
    ("temp_max", "温度上限", "℃", 35.0, 25.0, 45.0, 1.0),
    ("hum_min", "湿度下限", "%", 40.0, 20.0, 80.0, 1.0),
    ("ph_min", "pH 下限", "", 5.0, 4.0, 7.0, 0.1),
    ("conf_min", "病害置信度阈值", "%", 85.0, 50.0, 99.0, 1.0),
]


# ═══════════════════════════════════════════════════════════
# SECTION: 识别
# 出处 legacy:471-476（识别记录表）+ legacy:785-798（samples[4]）
# sample_spots 的 [cx, cy, r] 直接来自 legacy 各样本的 spots 数组
# ═══════════════════════════════════════════════════════════

# (时间, class_code, 置信度, severity, 中文级别)  —— 出处 legacy:471-476
DETECTION_ROWS: list[tuple[str, str, float, str, str]] = [
    ("09:42:18", "rice_blast", 96.2, "critical", "严重"),
    ("09:38:05", "rice_false_smut", 91.8, "serious", "较重"),
    ("09:31:47", "fall_armyworm", 93.4, "critical", "严重"),
    ("09:26:12", "bacterial_leaf_blight", 88.7, "warning", "一般"),
    ("09:19:33", "rice_blast", 95.1, "critical", "严重"),
    ("09:14:50", "rice_false_smut", 90.3, "serious", "较重"),
]

# (class_code, 置信度, severity, 级别, 感染区域, 面积占比, box, spots)
SAMPLES: list[tuple[str, float, str, str, str, float, tuple, list]] = [
    (
        "rice_blast", 96.2, "critical", "严重", "叶片中部 · 3 处病斑", 0.186,
        (0.20, 0.24, 0.70, 0.52),
        [(0.30, 0.42, 0.16), (0.44, 0.50, 0.14), (0.52, 0.40, 0.12), (0.38, 0.60, 0.12),
         (0.60, 0.58, 0.10), (0.70, 0.34, 0.12), (0.24, 0.55, 0.10), (0.65, 0.66, 0.10),
         (0.48, 0.72, 0.10), (0.82, 0.48, 0.09), (0.34, 0.30, 0.09), (0.56, 0.26, 0.09)],
    ),
    (
        "rice_false_smut", 91.8, "serious", "较重", "穗部 · 2 处病斑", 0.112,
        (0.30, 0.22, 0.46, 0.34),
        [(0.40, 0.30, 0.11), (0.55, 0.28, 0.10), (0.48, 0.38, 0.09), (0.62, 0.34, 0.09),
         (0.35, 0.40, 0.08), (0.70, 0.42, 0.08), (0.44, 0.48, 0.07), (0.58, 0.46, 0.07)],
    ),
    (
        "bacterial_leaf_blight", 88.7, "warning", "一般", "叶缘 · 1 处病斑", 0.064,
        (0.28, 0.46, 0.38, 0.34),
        [(0.34, 0.52, 0.12), (0.46, 0.56, 0.10), (0.40, 0.62, 0.09), (0.52, 0.66, 0.08),
         (0.44, 0.72, 0.07), (0.58, 0.58, 0.07)],
    ),
    (
        "fall_armyworm", 93.4, "critical", "严重", "叶片多处咬痕", 0.223,
        (0.22, 0.24, 0.64, 0.50),
        [(0.28, 0.34, 0.10), (0.42, 0.30, 0.09), (0.50, 0.44, 0.10), (0.60, 0.36, 0.09),
         (0.70, 0.52, 0.09), (0.34, 0.60, 0.08), (0.48, 0.66, 0.08), (0.78, 0.40, 0.08),
         (0.62, 0.62, 0.07), (0.40, 0.46, 0.06)],
    ),
]


# ═══════════════════════════════════════════════════════════
# SECTION: 喷洒方案
# 出处 legacy:544-576（三张方案卡片）+ legacy:1021-1023（雷达图分值）
# ═══════════════════════════════════════════════════════════

# (plan_key, tagline, product_code, 用量, 时机, 防治率, 成本, 推荐)
PLANS: list[tuple[str, str, str, str, str, float, float, int]] = [
    ("A", "LSTM 综合评分最高", "tricyclazole", "40 g/亩", "今日 17:00 前", 92.0, 6.8, 1),
    ("B", "成本更低、起效稍慢", "isoprothiolane", "80 ml/亩", "明日上午", 84.0, 5.2, 0),
    ("C", "绿色环保、生物防治", "bacillus_subtilis", "60 g/亩", "连续 3 日", 78.0, 9.5, 0),
]

# 雷达图五维。顺序必须与 legacy:1008-1011 的 indicator 一致。
RADAR_DIMS = ["防治效果", "成本效益", "时效性", "环保性", "易执行"]
RADAR_VALUES: dict[str, list[float]] = {
    "A": [92, 80, 90, 72, 88],
    "B": [84, 92, 70, 66, 80],
    "C": [78, 58, 60, 96, 70],
}

# 出处 legacy:586-601
SPRAY_LOGS: list[tuple[str, str]] = [
    ("09:45", "无人机起飞，进入目标航线"),
    ("09:52", "完成东区 12 亩喷洒"),
    ("10:01", "补充药液，返回继续作业"),
    ("10:08", "覆盖第 3 处病斑区域"),
]


# ═══════════════════════════════════════════════════════════
# SECTION: 图表序列
# 出处：legacy 各 renderers 里的静态数组
# (series_key, screen, 系列名, 单位, 类型, X 轴刻度 or None, 值)
# ═══════════════════════════════════════════════════════════

SERIES: list[tuple[str, str, str, str | None, str, list[str] | None, list[float]]] = [
    # 概览 sparkline，出处 legacy:848-851
    ("overview.spkRecog", "overview", "今日识别次数", None, "spark", None,
     [820, 940, 1100, 1020, 1180, 1240, 1180, 1200, 1220, 1240, 1260, 1286]),
    ("overview.spkWarn", "overview", "今日预警次数", None, "spark", None,
     [38, 34, 36, 30, 32, 28, 30, 27, 26, 25, 24, 23]),
    ("overview.spkArea", "overview", "覆盖农田面积", None, "spark", None,
     [180, 200, 220, 240, 260, 270, 280, 290, 300, 305, 310, 320]),
    ("overview.spkPest", "overview", "农药使用量变化", None, "spark", None,
     [100, 95, 90, 88, 85, 84, 83, 82, 81, 80, 80, 80]),
    # 概览饼图，出处 legacy:864-867
    ("overview.composition", "overview", "病虫害类型占比", "%", "pie",
     ["稻瘟病", "稻曲病", "白叶枯病", "草地贪夜蛾", "其他"], [42, 26, 15, 11, 6]),
    # 概览近 7 日趋势，出处 legacy:872-875
    ("overview.warnTrend", "overview", "预警次数", "次", "line",
     ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
     [18, 22, 20, 26, 24, 30, 23]),
    # 识别页横向柱状，出处 legacy:909-910（注意 yAxis 的顺序是反的，保持一致）
    ("identify.classCount", "identify", "识别次数", "次", "bar",
     ["草地贪夜蛾", "白叶枯病", "稻曲病", "稻瘟病"], [138, 86, 164, 287]),
    # 可视化页近 30 日三种病害，出处 legacy:925-927
    ("visualize.trend30.rice_blast", "visualize", "稻瘟病", "%", "line",
     [f"{i}日" for i in range(1, 31)],
     [3, 4, 4, 5, 6, 5, 7, 8, 9, 10, 9, 8, 9, 10, 11, 12, 13, 12, 14, 15,
      16, 15, 14, 13, 12, 11, 10, 9, 8, 7]),
    ("visualize.trend30.rice_false_smut", "visualize", "稻曲病", "%", "line",
     [f"{i}日" for i in range(1, 31)],
     [2, 2, 3, 3, 4, 4, 5, 5, 6, 5, 6, 6, 7, 7, 8, 8, 7, 8, 9, 8,
      9, 8, 7, 7, 6, 6, 5, 5, 4, 4]),
    ("visualize.trend30.bacterial_leaf_blight", "visualize", "白叶枯病", "%", "line",
     [f"{i}日" for i in range(1, 31)],
     [1, 1, 2, 2, 2, 3, 3, 4, 4, 5, 4, 5, 5, 6, 5, 5, 6, 5, 5, 4,
      5, 4, 4, 3, 3, 3, 2, 2, 2, 2]),
    # 可视化页农药对比，出处 legacy:936-937
    ("visualize.pesticide.before", "visualize", "使用前", "L/亩", "bar",
     ["杀虫剂", "杀菌剂", "除草剂"], [2.4, 1.8, 1.2]),
    ("visualize.pesticide.after", "visualize", "使用后", "L/亩", "bar",
     ["杀虫剂", "杀菌剂", "除草剂"], [1.7, 1.3, 0.9]),
    # 效果页对比，出处 legacy:1039-1040
    ("effect.comparison.before", "effect", "使用前", None, "bar",
     ["农药用量 (L/亩)", "防治成本 (元/亩)", "产量 (kg/亩)"], [2.2, 42, 560]),
    ("effect.comparison.after", "effect", "使用后", None, "bar",
     ["农药用量 (L/亩)", "防治成本 (元/亩)", "产量 (kg/亩)"], [1.6, 31, 602]),
]

# 出处 legacy:610-613
EFFECT_METRICS: list[tuple[str, str, str, str, str, str]] = [
    ("pesticide", "农药使用量", "-20", "%", "▼ 减少 20% 以上", "down"),
    ("yield", "作物产量", "+7.5", "%", "▲ 提升 5%–10%", "up"),
    ("cost", "防治成本", "-15", "%", "▼ 显著降低", "down"),
    ("efficiency", "防治效率", "×3.2", "", "▲ 较人工巡查", "up"),
]

# 出处 legacy:625-629
EFFECT_METHODS: list[tuple[str, str]] = [
    ("产量数据", "定期收集并对比历史产量"),
    ("健康指标", "作物生长状态监测"),
    ("环境记录", "温度 / 湿度 / pH / 光谱"),
    ("农药用量监控", "确保资源优化确实实现"),
    ("反馈调整", "基于反馈优化系统配置与流程"),
]


# ═══════════════════════════════════════════════════════════
# 传感器历史
# ═══════════════════════════════════════════════════════════

# 监测页四个 tile 显示的就是最后一个采样点，必须精确等于这些值
SENSOR_ANCHOR = {"temp": 26.4, "hum": 62.0, "ph": 6.3, "light": 38.0}
# 每步最大漂移，出处 legacy:758/761 的 drift 参数
SENSOR_STEP = {"temp": 1.4, "hum": 3.0, "ph": 0.2, "light": 2.0}
SENSOR_PREC = {"temp": 1, "hum": 1, "ph": 2, "light": 1}
SENSOR_POINTS = 30


def build_sensor_history(n: int = SENSOR_POINTS) -> list[dict]:
    """确定性生成 n 个采样点，**最后一个精确等于锚点**。

    做法是从锚点往回随机游走 n-1 步再反转。正向游走做不到这一点 ——
    走到哪算哪，最后一个点不可能恰好落在 26.4。
    """
    rng = random.Random(SEED)
    series: dict[str, list[float]] = {k: [v] for k, v in SENSOR_ANCHOR.items()}

    for _ in range(n - 1):
        for key, step in SENSOR_STEP.items():
            prev = series[key][-1]
            moved = max(0.0, prev + (rng.random() - 0.5) * step)
            series[key].append(round(moved, SENSOR_PREC[key]))

    for vals in series.values():
        vals.reverse()  # 锚点回到末尾

    base = _now() - timedelta(seconds=2 * (n - 1))
    rows: list[dict] = []
    for i in range(n):
        rows.append({
            "ts": _iso(base + timedelta(seconds=2 * i)),
            "temp": series["temp"][i],
            "hum": series["hum"][i],
            "ph": series["ph"][i],
            "light": series["light"][i],
            # 无人机状态是单点快照，历史点不带 —— 出处 legacy:756 的 bat/alt/spd
            "battery": None, "altitude": None, "speed": None,
        })

    # 最后一行的无人机状态，出处 legacy:405-407 的 12.4 m / 4.2 m/s / 76%
    rows[-1].update({"battery": 76.0, "altitude": 12.4, "speed": 4.2})
    return rows


# ═══════════════════════════════════════════════════════════
# 写入
# ═══════════════════════════════════════════════════════════


def _insert_classes(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO disease_classes (code, name_cn, name_en, category, dataset_label, sort_order)"
        " VALUES (?,?,?,?,NULL,?)",
        [(c, cn, en, cat, i) for i, (c, cn, en, cat) in enumerate(CLASSES)],
    )


def _insert_products(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO products (code, name, formulation, kind, eco_score, cost_per_mu, note)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            (code, name, form, kind, eco, cost,
             None if eco is not None else "暂无环保性/成本数据来源，留空不编数字")
            for code, name, form, kind, eco, cost in PRODUCTS
        ],
    )


def _insert_class_products(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO class_products (class_code, product_id, dosage, plan_key, advice)"
        " VALUES (?, (SELECT id FROM products WHERE code=?), ?, ?, ?)",
        [(cls, prod, dose, plan, advice) for cls, prod, dose, plan, advice in CLASS_PRODUCTS],
    )


def _insert_fields(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT INTO fields (code, name, area_mu, crop, note) VALUES (?,?,?,?,?)", FIELDS
    )

    # 3 号试验田的 48 格：8 列 × 6 行，标签「X 排 X 号」
    plots: list[tuple] = []
    for i in range(48):
        row_no, col_no = i // 8 + 1, i % 8 + 1
        plots.append(("F3", f"F3-{i + 1:02d}", row_no, col_no, f"{row_no}排{col_no}号"))
    conn.executemany(
        "INSERT INTO plots (field_id, code, row_no, col_no, label)"
        " VALUES ((SELECT id FROM fields WHERE code=?), ?, ?, ?, ?)",
        plots,
    )

    ts = _iso(_now())
    conn.executemany(
        "INSERT INTO field_severity (plot_id, ts, severity)"
        " VALUES ((SELECT id FROM plots WHERE code=?), ?, ?)",
        [(f"F3-{i + 1:02d}", ts, v) for i, v in enumerate(SEV_48)],
    )


def _insert_sensors(conn: sqlite3.Connection) -> None:
    rows = build_sensor_history()
    conn.executemany(
        "INSERT INTO sensor_readings (ts, temp, hum, ph, light, battery, altitude, speed, source)"
        " VALUES (:ts, :temp, :hum, :ph, :light, :battery, :altitude, :speed, 'seed')",
        rows,
    )


def _insert_warnings(conn: sqlite3.Connection) -> None:
    base = _now().replace(hour=0, minute=0, second=0)
    rows = []
    for no, typ, level, area, time_text, status in WARNS:
        hh, mm = (int(x) for x in time_text.split(":"))
        rows.append((no, typ, level, area, time_text, status, "seed",
                     _iso(base + timedelta(hours=hh, minutes=mm))))
    conn.executemany(
        "INSERT INTO warnings (warning_no, type, level, area, time_text, status, source, created_at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )

    conn.executemany(
        "INSERT INTO alert_thresholds (key, label, unit, value, min_value, max_value, step, sort_order)"
        " VALUES (?,?,?,?,?,?,?,?)",
        [(k, lab, unit, v, lo, hi, st, i)
         for i, (k, lab, unit, v, lo, hi, st) in enumerate(THRESHOLDS)],
    )


def _insert_detections(conn: sqlite3.Connection) -> None:
    """识别记录（迁移自静态表格）+ 演示样本（含病斑坐标）。"""
    name_of = {c: cn for c, cn, _, _ in CLASSES}
    advice_of = {cls: advice for cls, _, _, _, advice in CLASS_PRODUCTS}
    base = _now().replace(hour=0, minute=0, second=0)

    for idx, (t, cls, conf, sev, sev_cn) in enumerate(DETECTION_ROWS):
        hh, mm, ss = (int(x) for x in t.split(":"))
        created = base + timedelta(hours=hh, minutes=mm, seconds=ss)
        conn.execute(
            "INSERT INTO detection_records"
            " (detection_id, class_code, name_cn, confidence, severity, severity_label,"
            "  advice, source, created_at)"
            " VALUES (?,?,?,?,?,?,?,'seed',?)",
            (f"det_seed_{idx + 1:04d}", cls, name_of[cls], conf, sev, sev_cn,
             advice_of[cls], _iso(created)),
        )

    for order, (cls, conf, sev, sev_cn, region, ratio, box, spots) in enumerate(SAMPLES):
        cur = conn.execute(
            "INSERT INTO disease_samples"
            " (class_code, name_cn, confidence, severity, severity_label, region_desc,"
            "  area_ratio, advice, box_x, box_y, box_w, box_h, sort_order)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cls, name_of[cls], conf, sev, sev_cn, region, ratio, advice_of[cls],
             box[0], box[1], box[2], box[3], order),
        )
        conn.executemany(
            "INSERT INTO sample_spots (sample_id, seq, cx, cy, radius) VALUES (?,?,?,?,?)",
            [(cur.lastrowid, i, cx, cy, r) for i, (cx, cy, r) in enumerate(spots)],
        )


def _insert_spray(conn: sqlite3.Connection) -> None:
    now = _iso(_now())
    for order, (key, tagline, prod, dose, timing, eff, cost, rec) in enumerate(PLANS):
        cur = conn.execute(
            "INSERT INTO spray_plans"
            " (plan_key, name, tagline, product_id, dosage, timing, efficacy, cost_per_mu,"
            "  recommended, sort_order)"
            " VALUES (?,?,?,(SELECT id FROM products WHERE code=?),?,?,?,?,?,?)",
            (key, f"方案 {key}", tagline, prod, dose, timing, eff, cost, rec, order),
        )
        conn.executemany(
            "INSERT INTO spray_plan_scores (plan_id, dimension, score, sort_order)"
            " VALUES (?,?,?,?)",
            [(cur.lastrowid, dim, RADAR_VALUES[key][i], i)
             for i, dim in enumerate(RADAR_DIMS)],
        )

    task = conn.execute(
        "INSERT INTO spray_tasks"
        " (plan_id, field_id, title, progress, area_done, area_total, eta, feedback, status, created_at)"
        " VALUES ((SELECT id FROM spray_plans WHERE plan_key='A'),"
        "         (SELECT id FROM fields WHERE code='F3'),"
        "         ?,?,?,?,?,?, 'running', ?)",
        ("方案 A · 3 号试验田东区", 64.0, 20.5, 32.0, "17:24",
         "喷洒均匀度良好，已覆盖 3 处病斑区域", now),
    ).lastrowid

    conn.executemany(
        "INSERT INTO spray_logs (task_id, time_text, event, sort_order) VALUES (?,?,?,?)",
        [(task, t, e, i) for i, (t, e) in enumerate(SPRAY_LOGS)],
    )


def _insert_series(conn: sqlite3.Connection) -> None:
    for order, (key, screen, title, unit, chart, labels, values) in enumerate(SERIES):
        sid = conn.execute(
            "INSERT INTO analysis_series (series_key, screen, title, unit, chart_type, sort_order)"
            " VALUES (?,?,?,?,?,?)",
            (key, screen, title, unit, chart, order),
        ).lastrowid
        conn.executemany(
            "INSERT INTO analysis_points (series_id, seq, point_label, value) VALUES (?,?,?,?)",
            [(sid, i, labels[i] if labels else None, v) for i, v in enumerate(values)],
        )

    conn.executemany(
        "INSERT INTO effect_metrics (key, label, value_text, unit, note, tone, sort_order)"
        " VALUES (?,?,?,?,?,?,?)",
        [(k, lab, val, unit, note, tone, i)
         for i, (k, lab, val, unit, note, tone) in enumerate(EFFECT_METRICS)],
    )

    conn.executemany(
        "INSERT INTO knowledge_items (topic, term, detail, sort_order) VALUES (?,?,?,?)",
        [("effect.methods", term, detail, i)
         for i, (term, detail) in enumerate(EFFECT_METHODS)],
    )


def _insert_provenance(conn: sqlite3.Connection) -> None:
    """模型与数据溯源 —— 答辩被问"数据哪来的"时的直接答案。"""
    now = _iso(_now())
    conn.execute(
        "INSERT INTO model_registry"
        " (name, version, task, architecture, class_count, weights_file, size_mb,"
        "  license, source_url, device, status, notes, registered_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("jktk_x", "pretrained-2026.10", "detect", "YOLO11x", 116,
         "models/jktk_x.pt", 436.0, "apache-2.0",
         "hf-mirror.com/hodoly163/krishibondhu-jktk", "cpu", "active",
         "判型准（稻瘟病 0.965 / 纹枯病 0.947），但定位为假：输出框恒为整图约 93%。"
         "该权重由图像分类数据集导出为检测格式训练而来，116 类中无水稻害虫类。"
         "因此系统只取其 top-1 判型结果，定位改由图像分割承担。",
         now),
    )
    conn.executemany(
        "INSERT INTO datasets (name, kind, source, license, period, row_count, status, notes, registered_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("krishibondhu-jktk 预训练权重", "weights",
             "hf-mirror.com/hodoly163/krishibondhu-jktk", "apache-2.0", None, 116, "in-use",
             "第三方预训练权重，经 tools/scan_checkpoint.py 反汇编核查无危险调用。仅用于判型。",
             now),
            ("病害流行学机理仿真数据", "simulation", "本系统生成（阶段四）", None, "3–5 年日频", None,
             "planned",
             "无真实历史数据。按天气层（年/日周期 + AR(1) + 泊松降雨）、病害层（Logistic 增长，"
             "增长率受基数温度响应控制）、虫害层（有效积温 + 迁入事件）三层机理生成。"
             "按时间切分 train/val/test，绝不随机切。",
             now),
            ("ERA5 再分析气象数据", "planned", "ECMWF", "Copernicus 许可", None, None, "planned",
             "已预留接入接口，替换仿真数据的气象层。", now),
            ("IMERG 降水数据", "planned", "NASA GPM", "公开", None, None, "planned",
             "已预留接入接口，替换仿真数据的降雨项。", now),
            ("田间气象站实测数据", "planned", "部署后接入", None, None, None, "planned",
             "已预留接入接口，替换仿真数据的传感器读数。", now),
        ],
    )


def _is_empty(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(f'SELECT COUNT(*) AS c FROM "{table}"').fetchone()["c"] == 0


def seed(*, fresh: bool = True, verbose: bool = True) -> dict[str, int]:
    """灌数据。`fresh=True` 重建库，`False` 只往空表里补。"""
    init_db(drop=fresh)

    # 每张表配一个写入函数。--keep 模式下只跑空表。
    steps: list[tuple[str, object]] = [
        ("disease_classes", _insert_classes),
        ("products", _insert_products),
        ("class_products", _insert_class_products),
        ("fields", _insert_fields),
        ("sensor_readings", _insert_sensors),
        ("warnings", _insert_warnings),
        ("detection_records", _insert_detections),
        ("spray_plans", _insert_spray),
        ("analysis_series", _insert_series),
        ("model_registry", _insert_provenance),
    ]

    with get_conn() as conn:
        for table, fn in steps:
            if not fresh and not _is_empty(conn, table):
                if verbose:
                    print(f"  跳过 {table}（已有数据）")
                continue
            fn(conn)  # type: ignore[operator]

    counts = table_counts()
    if verbose:
        print("\n各表行数：")
        for name, n in counts.items():
            print(f"  {name:<22} {n:>6}")
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="灌入演示数据")
    ap.add_argument("--keep", action="store_true",
                    help="保留已有数据，只往空表里补（默认会先删库重建）")
    args = ap.parse_args()

    print("重建数据库…" if not args.keep else "增量补齐…")
    seed(fresh=not args.keep)
    print("\n完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
