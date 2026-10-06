import { useId } from 'react'

/* ═══════════════════════════════════════════════════════════
   Sparkline —— 纯 SVG，不初始化 ECharts 实例
   ═══════════════════════════════════════════════════════════

   legacy 用 `echarts.init()` 画这 12 个小图（每屏 tile 上都有一个），
   每个实例都有自己的生命周期、resize 监听、定时重绘。为了 96×36 像素的
   一条曲线付这个代价不划算 —— 纯 SVG 是声明式的，跟着 React 重渲染即可，
   切屏自动消失，没有实例要 dispose。

   视觉对齐 legacy 的 spark()：线宽 1.5、面积填充 0.12 透明度、平滑曲线。
   ═══════════════════════════════════════════════════════════ */

export interface SparklineProps {
  data: number[]
  color: string
  /** 默认填满 .tile .spark 的 96×36 */
  width?: number
  height?: number
}

/** 透明度用 rgba()，Canvas/SVG 都不认 #rrggbbaa 之外的花样。 */
function rgba(hex: string, a: number): string {
  let h = hex.replace('#', '')
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('')
  }
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}

export function Sparkline({ data, color, width = 96, height = 36 }: SparklineProps) {
  // 面积填充要用 <linearGradient>，id 在整页里必须唯一 ——
  // 用 useId 而不是数组下标：同屏多个 sparkline 用下标做 id 会互相覆盖填充色。
  const gid = useId()

  if (data.length < 2) {
    // 一个点连不成线，两个点才够。宁可空着也不画一条假的水平线。
    return <svg className="spark-svg" width={width} height={height} aria-hidden />
  }

  const min = Math.min(...data)
  const max = Math.max(...data)
  // 全平的数据（max === min）会让除零得到 NaN，整条线消失。
  // 退化成中线，视觉上是一条水平线 —— 那本来就是「没有波动」的正确表达。
  const span = max - min || 1
  const stepX = width / (data.length - 1)
  const pad = 3 // 上下留白，否则峰值会贴边被裁掉

  const pts = data.map((v, i) => {
    const x = i * stepX
    const y = pad + (1 - (v - min) / span) * (height - pad * 2)
    return [x, y] as const
  })

  // 中点二次贝塞尔平滑：比 Catmull-Rom 简单，且不会过冲出数据范围
  // （过冲会让 0 值画到负半轴，被 SVG 视口裁掉，看起来像数据缺了一块）
  let d = `M ${pts[0][0]} ${pts[0][1]}`
  for (let i = 1; i < pts.length; i++) {
    const [px, py] = pts[i - 1]
    const [cx, cy] = pts[i]
    d += ` Q ${px} ${py} ${(px + cx) / 2} ${(py + cy) / 2}`
  }
  const [lx, ly] = pts[pts.length - 1]
  d += ` L ${lx} ${ly}`

  const area = `${d} L ${width} ${height} L 0 ${height} Z`

  return (
    <svg
      className="spark-svg"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={rgba(color, 0.18)} />
          <stop offset="100%" stopColor={rgba(color, 0.02)} />
        </linearGradient>
      </defs>
      <path d={area} fill={`url(#${gid})`} />
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
