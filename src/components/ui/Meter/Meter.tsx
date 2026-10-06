import { cn } from '@lib/cn'

export interface MeterProps {
  /** 0–100 */
  value: number
  /**
   * legacy 里 `resConfBar` 是按 conf>90 手动加 `.high` 类的。
   * 这里保留这个语义但**不自动判断**：阈值是业务规则，该由调用方决定，
   * 藏在组件里会出现"为什么这条是绿的、那条不是"的困惑。
   */
  high?: boolean
  className?: string
}

export function Meter({ value, high, className }: MeterProps) {
  const v = Math.max(0, Math.min(100, value))
  return (
    <div className={cn('meter', className)}>
      <div className={cn('fill', high && 'high')} style={{ width: `${v}%` }} />
    </div>
  )
}
