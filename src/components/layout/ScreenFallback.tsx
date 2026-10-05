/**
 * 路由级 Suspense 兜底。7 个页面都是 lazy 加载，首次进入某屏时会有一次
 * 分包下载。占位刻意做得安静（不转圈、不闪白），切换时不打断讲稿节奏。
 */
export function ScreenFallback() {
  return (
    <div className="card">
      <h3>加载中</h3>
      <p className="hint">正在载入页面模块…</p>
    </div>
  )
}
