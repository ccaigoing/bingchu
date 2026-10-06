/* 展示层格式化。集中一处，避免各屏各写一遍 toFixed 导致小数位不一致。 */

/**
 * 0–1 的比例 → 百分数字符串。
 *
 * 三处都用它，且三处刻度已经统一成 0–1：
 * 诊断置信度、框贴合度、感染面积占比。
 * （库里 detection_records.confidence 存的是百分数，后端在
 *  serialize.pct_to_ratio 里已经除回来了，前端不需要知道这件事。）
 */
export function pct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

/** 直接就是百分数的值 → '92%'。tile 的 note 这类已经是文案的不走这里。 */
export function numPct(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return `${v.toFixed(digits)}%`
}

/** 千分位。 */
export function num(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

/** ISO 时间戳 → '09:42'。预警表的「时间」列只显示时分，与原 demo 一致。 */
export function timeHM(iso: string | null | undefined): string {
  if (!iso) return '—'
  const i = iso.indexOf('T')
  return i >= 0 ? iso.slice(i + 1, i + 6) : iso.slice(0, 5)
}

/** ISO 时间戳 → '09:42:18'。识别记录表显示到秒。 */
export function timeHMS(iso: string | null | undefined): string {
  if (!iso) return '—'
  const i = iso.indexOf('T')
  return i >= 0 ? iso.slice(i + 1, i + 9) : iso
}

/** 保留小数位，null 安全。 */
export function fixed(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  return v.toFixed(digits)
}
