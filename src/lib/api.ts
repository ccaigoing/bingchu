/* ═══════════════════════════════════════════════════════════
   API 客户端
   ═══════════════════════════════════════════════════════════

   基址是相对路径 `/api`，由 Vite 代理转到 FastAPI（见 vite.config.ts）。
   相对路径是刻意的：生产部署时前后端同源，不需要配 CORS，也不需要在
   构建期注入环境变量 —— 少一个部署时会出错的地方。

   上传不走 fetch 的默认 body：multipart 必须让浏览器自己生成 boundary，
   手写 Content-Type 会漏掉 boundary 导致后端解析失败。
   ═══════════════════════════════════════════════════════════ */

import type {
  AlertScreen,
  ClassCount,
  DatasetEntry,
  DetectResult,
  DetectionObject,
  DetectionRecord,
  DetectStats,
  DiseaseClass,
  DiseaseSample,
  EffectScreen,
  Health,
  IdentifyScreen,
  KnowledgeItem,
  ModelEntry,
  Monitor,
  Overview,
  Product,
  SensorReading,
  SprayScreen,
  Threshold,
  Visualize,
  Warning,
} from '@lib/types/api'

const BASE = '/api'

/** 后端错误统一 `{ error, code, detail? }`，这里原样带出来给调用方。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly detail?: string

  constructor(status: number, body: unknown) {
    const b = (body ?? {}) as Record<string, unknown>
    const msg = typeof b.error === 'string' ? b.error : `请求失败（HTTP ${status}）`
    super(msg)
    this.name = 'ApiError'
    this.status = status
    this.code = typeof b.code === 'string' ? b.code : 'UNKNOWN'
    this.detail = typeof b.detail === 'string' ? b.detail : undefined
  }
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init)
  const text = await res.text()
  let body: unknown = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      // 后端理论上只发 JSON；真收到非 JSON 说明是代理或网关插了一脚，
      // 把原文放进 detail 而不是丢掉 —— 这种错误靠猜是查不出来的。
      if (!res.ok) {
        throw new ApiError(res.status, { error: '服务返回了非 JSON 响应', code: 'BAD_RESPONSE', detail: text.slice(0, 200) })
      }
      throw new Error(`响应不是 JSON：${text.slice(0, 200)}`)
    }
  }
  if (!res.ok) throw new ApiError(res.status, body)
  return body as T
}

/** 把对象拼成查询串，跳过 undefined / null / 空串。 */
function qs(params: Record<string, string | number | undefined | null>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export const api = {
  health: () => req<Health>('/health'),

  // ── 字典 ──
  classes: () => req<DiseaseClass[]>('/classes'),
  products: (kind?: 'chemical' | 'biological') =>
    req<Product[]>('/products' + qs({ kind })),
  models: () => req<ModelEntry[]>('/models'),
  datasets: () => req<DatasetEntry[]>('/datasets'),
  knowledge: (topic: string) => req<KnowledgeItem[]>('/knowledge' + qs({ topic })),

  // ── 概览 ──
  overview: () => req<Overview>('/overview'),

  // ── 监测 ──
  monitor: (points?: number) => req<Monitor>('/monitor' + qs({ points })),
  sensorsLatest: () =>
    req<{ reading: SensorReading | null; tiles: Monitor['tiles']; drone: Monitor['drone'] }>(
      '/sensors/latest',
    ),
  sensorsHistory: (points?: number) =>
    req<SensorReading[]>('/sensors/history' + qs({ points })),

  // ── 识别 ──
  identify: () => req<IdentifyScreen>('/detect'),
  detectClasses: (sort?: 'count' | 'name') =>
    req<ClassCount[]>('/detect/classes' + qs({ sort })),
  detectRecords: (limit?: number, source?: 'seed' | 'upload') =>
    req<DetectionRecord[]>('/detect/records' + qs({ limit, source })),
  detectObjects: (recordId: number) =>
    req<DetectionObject[]>(`/detect/records/${recordId}/objects`),
  detectSamples: () => req<DiseaseSample[]>('/detect/samples'),
  detectStats: () => req<DetectStats>('/detect/stats'),
  /** 模型认得的 116 个原始标签。调试用，不是业务契约。 */
  detectModelClasses: () =>
    req<{ mode: string; count: number; names: Record<string, string> }>(
      '/detect/model-classes',
    ),

  /** 上传图片做识别。这是全系统最重要的一次请求。 */
  detect: (file: File, opts?: { conf?: number; iou?: number }): Promise<DetectResult> => {
    const fd = new FormData()
    fd.append('file', file)
    if (opts?.conf !== undefined) fd.append('conf', String(opts.conf))
    if (opts?.iou !== undefined) fd.append('iou', String(opts.iou))
    // 不设 Content-Type —— 交给浏览器生成带 boundary 的头
    return req<DetectResult>('/detect', { method: 'POST', body: fd })
  },

  // ── 可视化 ──
  visualize: () => req<Visualize>('/visualize'),
  fieldSeverity: (fieldId?: number) =>
    req<Visualize['field']>('/field/severity' + qs({ field_id: fieldId })),

  // ── 预警 ──
  alert: () => req<AlertScreen>('/alert'),
  warnings: (p?: { level?: string; status?: string; q?: string; limit?: number }) =>
    req<Warning[]>('/warnings' + qs({ ...p })),
  thresholds: () => req<Threshold[]>('/thresholds'),

  /** 标记一条预警为已处理。幂等 —— 连点两下不会报错。
   *  ⚠️ 调用方**必须**随后重取 `/api/alert`：tile 的计数是 COUNT 出来的，
   *  不重取就还是旧数字，于是 tile 和下面的表又对不上了。 */
  handleWarning: (id: number) =>
    req<Warning>(`/warnings/${id}/handle`, { method: 'POST' }),

  /** 改阈值。范围在**服务端**校验，越界返回 422。 */
  patchThreshold: (key: string, value: number) =>
    req<Threshold>(`/thresholds/${key}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ value }),
    }),

  // ── 喷洒 ──
  spray: () => req<SprayScreen>('/spray'),
  sprayPlans: () => req<Pick<SprayScreen, 'plans' | 'radar'>>('/spray/plans'),

  // ── 效果 ──
  effect: () => req<EffectScreen>('/effect'),
}
