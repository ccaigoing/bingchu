import type { ReactNode } from 'react'

import { cn } from '@lib/cn'
import type { StatusKey } from '@lib/types/api'

export interface StatusBadgeProps {
  status: StatusKey
  children: ReactNode
}

/**
 * `.st` 状态徽标。圆点由 `.st::before` 画，颜色由 `.st.{status}` 决定。
 *
 * 严重度/预警级别只有这四档，全系统共用 —— 加第五档要先加 CSS 变量，
 * 不要在这里塞内联颜色。
 */
export function StatusBadge({ status, children }: StatusBadgeProps) {
  return <span className={cn('st', status)}>{children}</span>
}
