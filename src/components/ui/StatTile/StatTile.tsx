import type { ReactNode } from 'react'

import { Sparkline } from '@components/charts/Sparkline'
import { cn } from '@lib/cn'
import type { StatusKey, Tone } from '@lib/types/api'

/* ═══════════════════════════════════════════════════════════
   StatTile —— `.tile` 指标卡
   ═══════════════════════════════════════════════════════════

   legacy 的 tile 有三种尾巴，靠不同的标签实现：

     概览/效果  <span class="delta up">▲ +12.4%</span>   带颜色，正负向
     监测       <span class="delta up">正常</span>        借 delta 的样式说状态
     预警       <span class="st critical">需立即处理</span> 状态徽标 + 值染色

   三种形态用一个联合类型表达，而不是一堆可选的 boolean ——
   调用方必须明确选一种，不会出现"两个都传了谁生效"的歧义。
   ═══════════════════════════════════════════════════════════ */

export type TileFooter =
  | { kind: 'delta'; tone: Tone; text: ReactNode }
  | { kind: 'status'; status: StatusKey; text: ReactNode }
  | { kind: 'plain'; text: ReactNode }

export interface StatTileProps {
  label: ReactNode
  value: ReactNode
  unit?: ReactNode
  /** 值本身的颜色，如预警页按级别染色（--critical / --serious …） */
  valueColor?: string
  footer?: TileFooter
  /** 右下角的迷你趋势图。没数据就不传 —— 不画空图占位。 */
  spark?: { data: number[]; color: string }
}

export function StatTile({ label, value, unit, valueColor, footer, spark }: StatTileProps) {
  return (
    <div className="tile">
      <div className="lab">{label}</div>
      <div className="val" style={valueColor ? { color: valueColor } : undefined}>
        {value}
        {unit !== undefined && <span className="unit">{unit}</span>}
      </div>
      {footer && <Footer f={footer} />}
      {spark && spark.data.length > 1 && (
        <div className="spark">
          <Sparkline data={spark.data} color={spark.color} />
        </div>
      )}
    </div>
  )
}

function Footer({ f }: { f: TileFooter }) {
  if (f.kind === 'delta') {
    return <span className={cn('delta', f.tone)}>{f.text}</span>
  }
  if (f.kind === 'status') {
    return <span className={cn('st', f.status)}>{f.text}</span>
  }
  return <span className="delta">{f.text}</span>
}
