import type { CSSProperties, ReactNode } from 'react'

import { cn } from '@lib/cn'

export interface CardProps {
  /** 标题。`.card h3::before` 那条强调色竖条由 CSS 提供，这里不要自己画。 */
  title?: ReactNode
  /** 标题右侧的灰字标签，如「最近 30 个采样点」 */
  tag?: ReactNode
  /** 标题下的说明文字 */
  hint?: ReactNode
  children?: ReactNode
  className?: string
  style?: CSSProperties
}

export function Card({ title, tag, hint, children, className, style }: CardProps) {
  return (
    <div className={cn('card', className)} style={style}>
      {title !== undefined && (
        <h3>
          {title}
          {tag !== undefined && <span className="tag">{tag}</span>}
        </h3>
      )}
      {hint !== undefined && <p className="hint">{hint}</p>}
      {children}
    </div>
  )
}
