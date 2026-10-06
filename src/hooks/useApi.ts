import { useCallback, useEffect, useRef, useState } from 'react'

/* ═══════════════════════════════════════════════════════════
   useApi —— 取数的通用 hook
   ═══════════════════════════════════════════════════════════

   为什么不引 react-query / swr：本项目每屏一次聚合请求，没有缓存失效、
   乐观更新、窗口聚焦重取这类需求。引一个缓存库进来，答辩时被问
   "为什么数据没刷新"反而更难回答。这里只有一条规则：deps 变化就重取。

   ⚠️ `fn` **不能**进依赖数组。调用方每次渲染都会传一个新箭头函数，
   放进依赖会无限循环。所以实现存进 ref，由调用方通过 `deps` 显式声明
   "什么时候该重新拉" —— 这把控制权交回调用处，比自动追踪依赖更可预测。
   ═══════════════════════════════════════════════════════════ */

export interface AsyncState<T> {
  data: T | null
  error: string | null
  loading: boolean
  /** 手动重取（上传成功后刷新记录表、点"切换样本"等） */
  reload: () => void
  /** 拿到新数据后本地替换，不重新请求（乐观更新用） */
  set: (next: T) => void
}

export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = []): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [nonce, setNonce] = useState(0)

  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => {
    // alive 标记防止"慢请求盖掉快请求"：切换地块时先发的请求后返回，
    // 会把新地块的数据覆盖成旧地块的。卸载后 setState 也靠它挡住。
    let alive = true
    setLoading(true)

    fnRef.current()
      .then((d) => {
        if (!alive) return
        setData(d)
        setError(null)
      })
      .catch((e: unknown) => {
        if (!alive) return
        // ApiError 的 message 已经是后端给的中文文案，直接用
        setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (alive) setLoading(false)
      })

    return () => {
      alive = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  const set = useCallback((next: T) => setData(next), [])

  return { data, error, loading, reload, set }
}
