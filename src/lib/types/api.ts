/* ═══════════════════════════════════════════════════════════
   API 响应类型 —— 与 server/app/routers/* 一一对应
   ═══════════════════════════════════════════════════════════

   后端用 serialize.camel() 统一把 snake_case 转成 camelCase，所以这里的
   字段名就是数据库列名的驼峰形式，不再逐条列映射表。

   ⚠️ 两个刻度必须分清的字段：

     summary.confidence       诊断置信度，来自 YOLO 判型（0–1）
     detections[].localizationScore  框贴合度，来自图像分割（0–1）

     前者是"这是什么病"的把握，后者是"这个框圈得准不准"。两者量级差很远
     （实测 0.965 vs 0.373），混用会让识别页把高置信度确诊显示成 37%。

   ⚠️ detection_records.confidence 是**百分数**（96.2），与上面两个 0–1 的
     不是同一个刻度 —— 这张记录表是从 legacy 显示口径迁来的。后端在
     serialize.pct_to_ratio 里已除回 0–1 再返回，前端拿到的一律是 0–1。
   ═══════════════════════════════════════════════════════════ */

// ── 通用 ──────────────────────────────────────────────────

export type Tone = 'up' | 'down'
export type StatusKey = 'good' | 'warning' | 'serious' | 'critical'
export type ChartType = 'line' | 'bar' | 'pie' | 'spark'

/** 图表序列。多系列折线在库里是多行，同前缀靠 seriesKey 分组。 */
export interface Series {
  seriesKey: string
  title: string
  unit: string | null
  chartType: ChartType
  labels: string[]
  values: number[]
}

/** 按 seriesKey 索引的序列集合。 */
export type SeriesMap = Record<string, Series>

/** 合并好的多系列图（三病害趋势、前后对比都用这个形状）。 */
export interface MultiSeries {
  labels: string[]
  unit: string | null
  series: { key: string; name: string; values: number[] }[]
}

/** 指标卡片。valueText 是**展示文案**（'×3.2' / '-20'），不是数字。 */
export interface KpiTile {
  id: number
  screen: string
  key: string
  label: string
  valueText: string
  unit: string
  note: string
  tone: Tone
  seriesKey: string | null
  sortOrder: number
}

// ── 字典 ──────────────────────────────────────────────────

export interface ProductRef {
  code: string
  name: string
  formulation: string
  kind: 'chemical' | 'biological'
  ecoScore: number | null
  costPerMu: number | null
}

export interface Product extends ProductRef {
  id: number
  note: string | null
}

export interface DiseaseClass {
  code: string
  nameCn: string
  nameEn: string
  category: 'disease' | 'pest'
  /** 第三方权重里的原始标签名。显式映射，绝不靠字符串匹配 —— Leaf Smut ≠ 稻曲病 */
  datasetLabel: string | null
  product: ProductRef | null
  dosage: string | null
  planKey: 'A' | 'B' | 'C' | null
  advice: string | null
}

export interface ModelEntry {
  id: number
  name: string
  version: string
  task: string
  architecture: string
  classCount: number | null
  weightsFile: string | null
  sizeMb: number | null
  license: string | null
  sourceUrl: string | null
  device: string | null
  status: 'active' | 'retired' | 'planned'
  notes: string | null
  registeredAt: string
}

export interface DatasetEntry {
  id: number
  name: string
  kind: string
  source: string | null
  license: string | null
  period: string | null
  rowCount: number | null
  status: 'in-use' | 'planned'
  notes: string | null
  registeredAt: string
}

export interface KnowledgeItem {
  term: string
  detail: string
}

// ── 概览 ──────────────────────────────────────────────────

export interface Field {
  id: number
  code: string
  name: string
  areaMu: number
  crop: string
  note: string | null
}

export interface Overview {
  tiles: KpiTile[]
  series: SeriesMap
  fields: { count: number; areaMu: number; crop: string; items: Field[] }
}

// ── 监测 ──────────────────────────────────────────────────

/** 监测页 tile。value 是**已格式化好的字符串**，前端直接显示。 */
export interface MonitorTile {
  key: string
  label: string
  value: string
  unit: string
  note: string
  tone: Tone
  sparkKey: string
}

export interface SensorReading {
  id: number
  ts: string
  temp: number
  hum: number
  ph: number
  light: number
  battery: number | null
  altitude: number | null
  speed: number | null
  source: string
}

export interface Drone {
  battery: number
  altitude: number
  speed: number
  status: string
  statusTone: string
  area: string
  route: string
  telemetryTs: string
}

export interface Monitor {
  tiles: MonitorTile[]
  /** 最近 N 个采样点，**时间正序**。tile 的 sparkline、两张趋势图、
   *  「最新 8 条」数据流表全部取自这一份 —— 一个数据源，三处不会对不上。 */
  readings: SensorReading[]
  drone: Drone | null
}

// ── 识别 ──────────────────────────────────────────────────

export interface SampleSpot {
  cx: number
  cy: number
  r: number
}

/** 演示样本。**不是识别结果** —— 接入真实上传后降级为"示例图"缩略图。 */
export interface DiseaseSample {
  classCode: string | null
  nameCn: string
  confidence: number
  severity: StatusKey
  severityLabel: string
  regionDesc: string
  areaRatio: number
  advice: string
  boxX: number
  boxY: number
  boxW: number
  boxH: number
  sortOrder: number
  spots: SampleSpot[]
}

export interface DetectionRecord {
  id: number
  detectionId: string
  classCode: string | null
  nameCn: string
  /** 诊断置信度，0–1（后端已从库里的百分数除回来） */
  confidence: number
  severity: StatusKey
  severityLabel: string
  infectedAreaRatio: number | null
  spotCount: number | null
  regionDesc: string | null
  advice: string | null
  imageUrl: string | null
  annotatedUrl: string | null
  source: 'seed' | 'upload'
  createdAt: string
  /** 派生自 createdAt 的 HH:MM:SS，legacy 记录表就显示这个 */
  timeText: string
}

export interface DetectionObject {
  seq: number
  classCode: string | null
  nameCn: string
  category: string
  /** 框贴合度，0–1 —— 不是诊断置信度 */
  localizationScore: number
  x: number
  y: number
  w: number
  h: number
}

export interface ClassCount {
  code: string
  nameCn: string
  category: 'disease' | 'pest'
  count: number
}

export interface DetectStats {
  total: number
  uploaded: number
  seeded: number
}

export interface IdentifyScreen {
  samples: DiseaseSample[]
  records: DetectionRecord[]
  classes: ClassCount[]
  stats: DetectStats
}

/** 单个检测框。坐标归一化到 0–1，左上原点，与 legacy 的 box[] 语义一致。 */
export interface DetectBox {
  x: number
  y: number
  w: number
  h: number
}

export interface Detection {
  classId: number
  code: string | null
  nameCn: string
  category: string
  isPest: boolean
  /** 框贴合度，0–1 */
  localizationScore: number
  box: DetectBox
  boxPx: { x: number; y: number; w: number; h: number }
  areaRatio: number
  region: 'top' | 'mid' | 'bottom'
}

export interface DetectSummary {
  topClassName: string | null
  topClassCode: string | null
  category: string | null
  /** 诊断置信度，0–1 */
  confidence: number
  localizationScore: number | null
  severityLevel: StatusKey
  severityLabel: string
  infectedAreaRatio: number
  spotCount: number
  regionDesc: string
  advice: string
  recommendedPlanKey: 'A' | 'B' | 'C' | null
  counts: Record<string, number>
}

/** POST /api/detect 的响应。 */
export interface DetectResult {
  detectionId: string
  model: {
    name: string
    version: string
    device: string
    /** 降级时必须显式看到这个 —— 绝不静默回落 */
    mode: 'normal' | 'degraded'
    error: string | null
  }
  /** 分工透出：定位由图像分割完成，YOLO 只判型且它的框被丢弃 */
  localization: {
    method: string
    note: string
    yoloTopClass: string | null
    yoloTopNameCn: string | null
    yoloConfidence: number | null
    yoloBoxIgnored: string | null
  }
  latencyMs: number
  image: {
    originalUrl: string
    annotatedUrl: string
    width: number
    height: number
  }
  summary: DetectSummary
  detections: Detection[]
  counts: Record<string, number>
}

// ── 可视化 ────────────────────────────────────────────────

export interface SeverityCell {
  code: string
  rowNo: number
  colNo: number
  label: string
  severity: number
  severityLabel: string
  /** legacy: 只有中度及以上才在格子里显示文字 */
  showLabel: boolean
}

export interface FieldSeverity {
  fieldId: number
  fieldName: string
  crop: string
  areaMu: number
  rows: number
  cols: number
  ts: string | null
  severityLabels: string[]
  cells: SeverityCell[]
}

export interface Visualize {
  trend: MultiSeries
  pesticide: MultiSeries
  field: FieldSeverity
  series: SeriesMap
}

// ── 预警 ──────────────────────────────────────────────────

export type WarningLevel = 'critical' | 'serious' | 'warning'

export interface Warning {
  id: number
  warningNo: string
  type: string
  level: WarningLevel
  area: string
  /** 显示用时刻 '09:42'，与原 demo 一致（不含日期） */
  timeText: string
  status: 'done' | 'undone'
  source: string
  createdAt: string
}

/** 预警页 tile。数字是后端从 warnings 表现场 COUNT 出来的。 */
export interface AlertTile {
  key: string
  label: string
  value: string
  unit: string
  note: string
  tone: Tone
  status: StatusKey
}

export interface Threshold {
  id: number
  key: string
  label: string
  unit: string
  value: number
  minValue: number
  maxValue: number
  step: number
  sortOrder: number
}

export interface AlertScreen {
  tiles: AlertTile[]
  counts: {
    critical: number
    serious: number
    warning: number
    done: number
    total: number
    undone: number
  }
  warnings: Warning[]
  thresholds: Threshold[]
}

// ── 喷洒 ──────────────────────────────────────────────────

export interface PlanScore {
  dimension: string
  score: number
}

export interface SprayPlan {
  planKey: 'A' | 'B' | 'C'
  name: string
  tagline: string
  recommended: boolean
  product: ProductRef
  dosage: string
  timing: string
  efficacy: number
  costPerMu: number
  scores: PlanScore[]
}

export interface Radar {
  dimensions: string[]
  series: { key: string; name: string; values: number[] }[]
}

export interface SprayTask {
  id: number
  planId: number | null
  fieldId: number | null
  title: string
  progress: number
  areaDone: number
  areaTotal: number
  eta: string | null
  feedback: string | null
  status: 'pending' | 'running' | 'paused' | 'done'
  createdAt: string
  fieldName: string | null
}

export interface SprayLog {
  time: string
  event: string
}

export interface SprayScreen {
  plans: SprayPlan[]
  radar: Radar
  active: { task: SprayTask; logs: SprayLog[] } | null
}

// ── 效果 ──────────────────────────────────────────────────

export interface EffectScreen {
  tiles: KpiTile[]
  methods: KnowledgeItem[]
  comparison: MultiSeries
}

// ── 系统 ──────────────────────────────────────────────────

export interface Health {
  status: string
  model: {
    name: string
    device: string
    mode: 'normal' | 'degraded'
    error: string | null
    classCount: number
  }
}
