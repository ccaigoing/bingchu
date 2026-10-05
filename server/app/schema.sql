-- ═══════════════════════════════════════════════════════════
--  「机」到病除 —— 数据库结构
-- ═══════════════════════════════════════════════════════════
--
--  设计原则
--  ────────
--  1. **disease_classes 是单一事实源** —— 识别结果、建议措施、预警类型、
--     喷洒方案目标全部指向它。这是"7 屏数据互相自洽"的结构保证：
--     识别页建议的农药与喷洒页方案 A 的产品，在库里是同一行 products。
--
--  2. **不用 ORM** —— 纯 sqlite3 + 显式 SQL。表不多、查询不复杂，
--     引入 ORM 只会让"这一列到底哪来的"变得难查。
--
--  3. **analysis_series / analysis_points 承接所有图表序列** ——
--     避免为每张图建一张表。sparkline、折线、柱状、饼图全走这一个模型。
--
--  4. **forecast_* 两张表建好但暂不填** —— 阶段四的 LSTM 预测写这里，
--     现在建表是为了让 API 层与前端可以先按最终形状对接。
--
--  5. 迁移自 legacy/index.html 的硬编码数据，来源逐条标注在 seed.py。
-- ═══════════════════════════════════════════════════════════


-- ── 地块 ──────────────────────────────────────────────────
-- 对应原 demo 里的「1 号田 / 2 号田 / 3 号试验田 / 4 号田」。
-- 原数据里的「东区 / 南区 / 西区 / 北区 / 全域」是同一块田内的分区，
-- 在原 demo 里只作为显示字符串出现，没有独立语义，所以这里不建模成分区表 ——
-- 需要时把分区字符串存在 alerts.area / spray_tasks 里即可。
CREATE TABLE IF NOT EXISTS fields (
  id          INTEGER PRIMARY KEY,
  code        TEXT NOT NULL UNIQUE,
  name        TEXT NOT NULL,
  area_mu     REAL NOT NULL,              -- 面积（亩）
  crop        TEXT NOT NULL DEFAULT '水稻',
  note        TEXT
);


-- ── 地块最小单元 ──────────────────────────────────────────
-- 3 号试验田的 8 列 × 6 行 = 48 格，对应原 demo 的 48 格严重度地图。
-- 标签规则「X 排 X 号」= 排自上而下第几排、号自左向右第几号（原 demo 页面上
-- 的提示文字就是这么写的），故 row_no 1..6、col_no 1..8。
CREATE TABLE IF NOT EXISTS plots (
  id        INTEGER PRIMARY KEY,
  field_id  INTEGER NOT NULL REFERENCES fields(id) ON DELETE CASCADE,
  code      TEXT NOT NULL UNIQUE,          -- 'F3-01'
  row_no    INTEGER NOT NULL CHECK(row_no BETWEEN 1 AND 6),
  col_no    INTEGER NOT NULL CHECK(col_no BETWEEN 1 AND 8),
  label     TEXT NOT NULL,                 -- '3排5号'
  UNIQUE(field_id, row_no, col_no)
);


-- ── 地块严重度 ────────────────────────────────────────────
-- 带时间戳，不是一个静态数组 —— 这样才能承接阶段二 2.5 的实时推进。
-- severity 0..5 直接对应前端 PALETTES[theme].seq[0..6] 的取色。
CREATE TABLE IF NOT EXISTS field_severity (
  id        INTEGER PRIMARY KEY,
  plot_id   INTEGER NOT NULL REFERENCES plots(id) ON DELETE CASCADE,
  ts        TEXT NOT NULL,
  severity  INTEGER NOT NULL CHECK(severity BETWEEN 0 AND 5),
  UNIQUE(plot_id, ts)
);
CREATE INDEX IF NOT EXISTS idx_field_severity_ts ON field_severity(ts);


-- ── 传感器读数 ────────────────────────────────────────────
-- 迁移自原 demo 的 sim.tempH / humH / phH / lightH（30 点滚动窗口）。
-- 也承接无人机状态（电量 / 高度 / 速度）。
CREATE TABLE IF NOT EXISTS sensor_readings (
  id        INTEGER PRIMARY KEY,
  ts        TEXT NOT NULL,
  temp      REAL NOT NULL,                 -- ℃
  hum       REAL NOT NULL,                 -- %
  ph        REAL NOT NULL,
  light     REAL NOT NULL,                 -- kLx
  battery   REAL,                          -- % 无人机
  altitude  REAL,                          -- m
  speed     REAL,                          -- m/s
  source    TEXT NOT NULL DEFAULT 'seed'   -- 'seed' | 'engine'
);
CREATE INDEX IF NOT EXISTS idx_sensor_ts ON sensor_readings(ts);


-- ── 类别字典（单一事实源）────────────────────────────────
-- code 必须与 services/detector.py 的 CANONICAL 完全一致 —— 那边是推理时
-- 解析模型原始标签的落点，两边对不上就会出现"识别页说稻瘟病、喷洒页找不到"。
-- tools/check_consistency.py 会校验这个不变量。
--
-- ⚠️ dataset_label 是显式映射，**绝不靠字符串匹配**：数据集里的
--    `Leaf Smut` 是稻叶黑粉病，不等于稻曲病（Rice False Smut），中文极易混。
CREATE TABLE IF NOT EXISTS disease_classes (
  id            INTEGER PRIMARY KEY,
  code          TEXT NOT NULL UNIQUE,
  name_cn       TEXT NOT NULL,
  name_en       TEXT NOT NULL,
  category      TEXT NOT NULL CHECK(category IN ('disease','pest')),
  dataset_label TEXT,                      -- 第三方权重里的原始标签名
  sort_order    INTEGER NOT NULL DEFAULT 0
);


-- ── 农药产品 ──────────────────────────────────────────────
-- eco_score 与 cost_per_mu 只填**有出处**的那些（喷洒页方案 A/B/C 的雷达分
-- 与卡片成本），其余留 NULL —— 不编数字。MADM 需要时再补数据源。
CREATE TABLE IF NOT EXISTS products (
  id           INTEGER PRIMARY KEY,
  code         TEXT NOT NULL UNIQUE,
  name         TEXT NOT NULL,              -- '三环唑 75% 可湿粉'
  formulation  TEXT NOT NULL,              -- '可湿粉' / '乳油' / '生物制剂'
  kind         TEXT NOT NULL CHECK(kind IN ('chemical','biological')),
  eco_score    REAL CHECK(eco_score IS NULL OR eco_score BETWEEN 0 AND 100),
  cost_per_mu  REAL,                       -- 元/亩
  note         TEXT
);


-- ── 类别 → 推荐产品 ───────────────────────────────────────
-- 这张表就是 services/detector.py 里 ADVICE 字典的数据库版本。
-- 保留那边的字典是为了"数据库还没建起来时检测也能给出建议"，
-- 但**权威来源是这张表** —— check_consistency.py 会断言两者一致。
-- 识别页的「建议措施」必须来自这里，这样它和喷洒页方案 A 的产品天然同一行。
CREATE TABLE IF NOT EXISTS class_products (
  class_code  TEXT PRIMARY KEY REFERENCES disease_classes(code) ON DELETE CASCADE,
  product_id  INTEGER NOT NULL REFERENCES products(id),
  dosage      TEXT NOT NULL,               -- '40 g/亩'
  plan_key    TEXT CHECK(plan_key IS NULL OR plan_key IN ('A','B','C')),
  advice      TEXT NOT NULL                -- 完整建议措辞，识别页直接显示
);


-- ── 预警阈值 ──────────────────────────────────────────────
-- 迁移自预警页的 4 个滑块（含各自的 min/max/step）。
CREATE TABLE IF NOT EXISTS alert_thresholds (
  id          INTEGER PRIMARY KEY,
  key         TEXT NOT NULL UNIQUE,
  label       TEXT NOT NULL,
  unit        TEXT NOT NULL DEFAULT '',
  value       REAL NOT NULL,
  min_value   REAL NOT NULL,
  max_value   REAL NOT NULL,
  step        REAL NOT NULL DEFAULT 1,
  sort_order  INTEGER NOT NULL DEFAULT 0
);


-- ── 预警记录 ──────────────────────────────────────────────
-- 迁移自 warnSeed[11]。time_text 保留 '09:42' 这种原样字符串（原 demo 就是
-- 只显示时分，不显示日期）；同时给一个完整 created_at 供排序与真实引擎使用。
CREATE TABLE IF NOT EXISTS warnings (
  id          INTEGER PRIMARY KEY,
  warning_no  TEXT NOT NULL UNIQUE,        -- 'W-2041'
  type        TEXT NOT NULL,
  level       TEXT NOT NULL CHECK(level IN ('critical','serious','warning')),
  area        TEXT NOT NULL,               -- '3 号田 · 东区'
  time_text   TEXT NOT NULL,               -- '09:42'
  status      TEXT NOT NULL CHECK(status IN ('done','undone')),
  source      TEXT NOT NULL DEFAULT 'seed',-- 'seed'|'threshold'|'detection'|'forecast'
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_warnings_level ON warnings(level);
CREATE INDEX IF NOT EXISTS idx_warnings_status ON warnings(status, created_at DESC);


-- ── 识别记录 ──────────────────────────────────────────────
-- detection_id 形如 'det_20261006_0001'，与 /api/detect 的响应字段同名。
-- source='seed' 表示迁移自原 demo 的静态表格，'upload' 表示真实上传产生。
CREATE TABLE IF NOT EXISTS detection_records (
  id                  INTEGER PRIMARY KEY,
  detection_id        TEXT NOT NULL UNIQUE,
  class_code          TEXT REFERENCES disease_classes(code),
  name_cn             TEXT NOT NULL,
  confidence          REAL NOT NULL,
  severity            TEXT NOT NULL,
  severity_label      TEXT NOT NULL,
  infected_area_ratio REAL,
  spot_count          INTEGER,
  region_desc         TEXT,
  advice              TEXT,
  image_url           TEXT,
  annotated_url       TEXT,
  source              TEXT NOT NULL DEFAULT 'seed',
  created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detection_created ON detection_records(created_at DESC);


-- ── 识别记录里的单个框 ────────────────────────────────────
-- 归一化坐标（左上原点），与原 demo 的 box:[x,y,w,h] 语义完全一致。
--
-- ⚠️ 这里的 localization_score 与 detection_records.confidence 是**两个量**：
--      confidence          = 诊断置信度，来自 YOLO 判型（这张图是什么病）
--      localization_score  = 框贴合度，来自图像分割（这个框圈得准不准）
--    实测两者量级差很远（0.965 vs 0.373）。早先两处都叫 confidence，
--    导致识别页把一次高置信度确诊显示成"置信度 37%"。列名分开杜绝复发。
CREATE TABLE IF NOT EXISTS detection_objects (
  id                 INTEGER PRIMARY KEY,
  record_id          INTEGER NOT NULL REFERENCES detection_records(id) ON DELETE CASCADE,
  seq                INTEGER NOT NULL,
  class_code         TEXT,
  name_cn            TEXT NOT NULL,
  category           TEXT NOT NULL,
  localization_score REAL NOT NULL,
  x           REAL NOT NULL,
  y           REAL NOT NULL,
  w           REAL NOT NULL,
  h           REAL NOT NULL,
  UNIQUE(record_id, seq)
);


-- ── 演示样本 ──────────────────────────────────────────────
-- 迁移自 samples[4]（稻瘟病 / 稻曲病 / 白叶枯病 / 草地贪夜蛾为害）。
-- ⚠️ 这张表存的是**演示素材**，不是识别结果。识别页接入真实上传后，
--    左侧叶片区改为显示后端标注图，这些样本降级为"示例图"缩略图。
CREATE TABLE IF NOT EXISTS disease_samples (
  id              INTEGER PRIMARY KEY,
  class_code      TEXT REFERENCES disease_classes(code),
  name_cn         TEXT NOT NULL,
  confidence      REAL NOT NULL,
  severity        TEXT NOT NULL,
  severity_label  TEXT NOT NULL,
  region_desc     TEXT NOT NULL,
  area_ratio      REAL NOT NULL,
  advice          TEXT NOT NULL,
  box_x           REAL NOT NULL,
  box_y           REAL NOT NULL,
  box_w           REAL NOT NULL,
  box_h           REAL NOT NULL,
  sort_order      INTEGER NOT NULL DEFAULT 0
);


-- ── 样本上的病斑点 ────────────────────────────────────────
-- 迁移自 samples[i].spots（每项 [cx, cy, r]，归一化到 0..1）。
CREATE TABLE IF NOT EXISTS sample_spots (
  id        INTEGER PRIMARY KEY,
  sample_id INTEGER NOT NULL REFERENCES disease_samples(id) ON DELETE CASCADE,
  seq       INTEGER NOT NULL,
  cx        REAL NOT NULL,
  cy        REAL NOT NULL,
  radius    REAL NOT NULL,
  UNIQUE(sample_id, seq)
);


-- ── 喷洒方案 ──────────────────────────────────────────────
-- 迁移自喷洒页的 A/B/C 三张卡片。product_id 指向 products ——
-- 这就是"识别页的建议措施与方案 A 是同一行产品"的结构保证。
CREATE TABLE IF NOT EXISTS spray_plans (
  id           INTEGER PRIMARY KEY,
  plan_key     TEXT NOT NULL UNIQUE CHECK(plan_key IN ('A','B','C')),
  name         TEXT NOT NULL,              -- '方案 A'
  tagline      TEXT NOT NULL,              -- 'LSTM 综合评分最高'
  product_id   INTEGER NOT NULL REFERENCES products(id),
  dosage       TEXT NOT NULL,
  timing       TEXT NOT NULL,
  efficacy     REAL NOT NULL,              -- 预计防治率 %
  cost_per_mu  REAL NOT NULL,              -- 综合成本 元/亩
  recommended  INTEGER NOT NULL DEFAULT 0 CHECK(recommended IN (0,1)),
  generated_at TEXT,
  sort_order   INTEGER NOT NULL DEFAULT 0
);


-- ── 方案五维评分 ──────────────────────────────────────────
-- 迁移自雷达图的 3 组 value。维度名单独存 —— 阶段四的 MADM 会真算这些分值，
-- 届时这张表由算法写入，而不是 seed 写死。
CREATE TABLE IF NOT EXISTS spray_plan_scores (
  id         INTEGER PRIMARY KEY,
  plan_id    INTEGER NOT NULL REFERENCES spray_plans(id) ON DELETE CASCADE,
  dimension  TEXT NOT NULL,
  score      REAL NOT NULL CHECK(score BETWEEN 0 AND 100),
  sort_order INTEGER NOT NULL DEFAULT 0,
  UNIQUE(plan_id, dimension)
);


-- ── 喷洒任务 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spray_tasks (
  id          INTEGER PRIMARY KEY,
  plan_id     INTEGER REFERENCES spray_plans(id),
  field_id    INTEGER REFERENCES fields(id),
  title       TEXT NOT NULL,               -- '方案 A · 3 号试验田东区'
  progress    REAL NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
  area_done   REAL NOT NULL DEFAULT 0,
  area_total  REAL NOT NULL,
  eta         TEXT,
  feedback    TEXT,
  status      TEXT NOT NULL CHECK(status IN ('pending','running','paused','done')),
  created_at  TEXT NOT NULL
);


-- ── 喷洒日志 ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS spray_logs (
  id         INTEGER PRIMARY KEY,
  task_id    INTEGER NOT NULL REFERENCES spray_tasks(id) ON DELETE CASCADE,
  time_text  TEXT NOT NULL,
  event      TEXT NOT NULL,
  sort_order INTEGER NOT NULL DEFAULT 0
);


-- ── 图表序列（元信息）────────────────────────────────────
-- series_key 形如 'overview.spkRecog' / 'visualize.trend30'。
-- 同一张多系列图（如近 30 日三种病害）是**多行** analysis_series，
-- 它们靠 series_key 的前缀分组，title 就是系列名。
CREATE TABLE IF NOT EXISTS analysis_series (
  id          INTEGER PRIMARY KEY,
  series_key  TEXT NOT NULL UNIQUE,
  screen      TEXT NOT NULL,               -- 归属屏，便于按屏一次取全
  title       TEXT NOT NULL,               -- 系列名，进 legend
  unit        TEXT,
  chart_type  TEXT NOT NULL DEFAULT 'line',
  sort_order  INTEGER NOT NULL DEFAULT 0
);


-- ── 图表序列（数据点）────────────────────────────────────
-- point_label 是 X 轴刻度（'周一' / '1日' / '杀虫剂'），
-- sparkline 这类无刻度的图留 NULL。
CREATE TABLE IF NOT EXISTS analysis_points (
  id           INTEGER PRIMARY KEY,
  series_id    INTEGER NOT NULL REFERENCES analysis_series(id) ON DELETE CASCADE,
  seq          INTEGER NOT NULL,
  point_label  TEXT,
  value        REAL NOT NULL,
  UNIQUE(series_id, seq)
);


-- ── 指标卡片（tile）──────────────────────────────────────
-- 概览页与效果页的 tile 共用这一张表。value_text 存**展示文案**而不是数字：
-- '×3.2' 和 '-20' 要带着千分位、正负号、乘号一起显示，硬转成浮点再转回来
-- 只会多一层格式信息。让后端存的就等于前端要显示的。
--
-- ⚠️ 监测页与预警页的 tile **不在这张表里** —— 它们的值是真能算出来的：
--    监测页 = 最新一条 sensor_readings，预警页 = warnings 按级别计数。
--    那两处由 API 现场算，这样 tile 永远不可能和底下的表打架。
--    这里只放"算不出来"的头部数字（今日识别总次数、减排比例等）。
CREATE TABLE IF NOT EXISTS kpi_tiles (
  id          INTEGER PRIMARY KEY,
  screen      TEXT NOT NULL,
  key         TEXT NOT NULL,
  label       TEXT NOT NULL,
  value_text  TEXT NOT NULL,
  unit        TEXT NOT NULL DEFAULT '',
  note        TEXT NOT NULL,
  tone        TEXT NOT NULL CHECK(tone IN ('up','down')),
  series_key  TEXT,                        -- 关联的 sparkline，可空
  sort_order  INTEGER NOT NULL DEFAULT 0,
  UNIQUE(screen, key)
);


-- ── 通用键值条目 ──────────────────────────────────────────
-- 承接各屏的 kv 说明型内容（如效果页的「评估方法」5 条）。
-- topic 分组，例如 'effect.methods'。
CREATE TABLE IF NOT EXISTS knowledge_items (
  id          INTEGER PRIMARY KEY,
  topic       TEXT NOT NULL,
  term        TEXT NOT NULL,
  detail      TEXT NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0,
  UNIQUE(topic, term)
);


-- ── 模型登记（答辩溯源刚需）──────────────────────────────
CREATE TABLE IF NOT EXISTS model_registry (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  version       TEXT NOT NULL,
  task          TEXT NOT NULL,
  architecture  TEXT NOT NULL,
  class_count   INTEGER,
  weights_file  TEXT,
  size_mb       REAL,
  license       TEXT,
  source_url    TEXT,
  device        TEXT,
  status        TEXT NOT NULL CHECK(status IN ('active','retired','planned')),
  notes         TEXT,
  registered_at TEXT NOT NULL
);


-- ── 数据溯源（答辩溯源刚需）──────────────────────────────
CREATE TABLE IF NOT EXISTS datasets (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  kind          TEXT NOT NULL,             -- 'weights'|'simulation'|'planned'
  source        TEXT,
  license       TEXT,
  period        TEXT,
  row_count     INTEGER,
  status        TEXT NOT NULL CHECK(status IN ('in-use','planned')),
  notes         TEXT,
  registered_at TEXT NOT NULL
);


-- ── 预测批次（阶段四写入，现在建空表）────────────────────
CREATE TABLE IF NOT EXISTS forecast_runs (
  id           INTEGER PRIMARY KEY,
  run_id       TEXT NOT NULL UNIQUE,
  model_name   TEXT NOT NULL,
  horizon_days INTEGER NOT NULL,
  input_days   INTEGER NOT NULL,
  mae          REAL,
  created_at   TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS forecast_points (
  id         INTEGER PRIMARY KEY,
  run_id     INTEGER NOT NULL REFERENCES forecast_runs(id) ON DELETE CASCADE,
  day_offset INTEGER NOT NULL,             -- 1..horizon
  class_code TEXT NOT NULL,
  prob       REAL NOT NULL,                -- 发生率 %  →  趋势图
  level      TEXT NOT NULL,                -- 风险等级 → 预警与状态色
  UNIQUE(run_id, day_offset, class_code)
);
