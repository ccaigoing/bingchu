import type { ReactNode } from 'react'

/* ═══════════════════════════════════════════════════════════
   PageState —— 屏级加载中 / 加载失败
   ═══════════════════════════════════════════════════════════

   7 个页面都要「拿数据 → 判空 → 渲染」这一段，各自写一遍必然写歪
   （有的屏失败时报错，有的屏静默白屏）。这里统一成两个组件。

   ⚠️ 判断加载用的是 `!data` 而不是 `loading`：
   `useApi` 在 reload 时会把 loading 置回 true，如果拿 loading 判空，
   上传完刷新记录表会把整屏闪成"加载中"。有旧数据就先接着显示旧的。
   ═══════════════════════════════════════════════════════════ */

export function LoadingCard({ what }: { what: string }) {
  return (
    <div className="card">
      <h3>加载中</h3>
      <p className="hint">正在读取{what}…</p>
    </div>
  )
}

export interface ErrorCardProps {
  message: string
  onRetry?: () => void
  children?: ReactNode
}

/**
 * 加载失败。**必须显示后端给的原因**，不能只写"出错了" ——
 * 答辩现场这条信息就是唯一能定位问题的线索。
 */
export function ErrorCard({ message, onRetry, children }: ErrorCardProps) {
  return (
    <div className="card">
      <h3>
        加载失败 <span className="tag">后端未就绪</span>
      </h3>
      <p className="hint">{message}</p>
      {children}
      {onRetry && (
        <div style={{ marginTop: 14 }}>
          <button type="button" className="btn" onClick={onRetry}>
            重试
          </button>
        </div>
      )}
    </div>
  )
}
