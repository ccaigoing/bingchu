import type { ReactNode } from 'react'

import { cn } from '@lib/cn'

export interface ChipProps {
  /** 选中态。`aria-pressed` 一并给上 —— 纯视觉的选中态对读屏用户不存在。 */
  on?: boolean
  onClick?: () => void
  children: ReactNode
}

export function Chip({ on, onClick, children }: ChipProps) {
  return (
    <button type="button" className={cn('chip', on && 'on')} aria-pressed={on} onClick={onClick}>
      {children}
    </button>
  )
}
