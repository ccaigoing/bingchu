import type { CSSProperties } from 'react'

import type { Fragment } from '@components/charts/chartTheme'
import { useECharts } from '@hooks/useECharts'

export interface EChartProps {
  /** 松散片段，断言收口在 useECharts —— 各屏不必写 `as EChartsOption`。 */
  option: Fragment | null
  /** 默认 `chart`（width:100%; height:280px）。legacy 里带自定义高度的图
   *  是靠内联 style 覆盖的，这里也一样 —— 不再为每种高度定义一个新类。 */
  className?: string
  style?: CSSProperties
}

export function EChart({ option, className = 'chart', style }: EChartProps) {
  const ref = useECharts(option)
  return <div ref={ref} className={className} style={style} />
}
