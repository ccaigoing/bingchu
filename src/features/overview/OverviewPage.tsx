/**
 * 系统概览 —— 脚手架占位。
 *
 * 2.4 移植清单（对照 legacy/index.html 的 `#screen-overview`）：
 *   - 4 个统计 tile（.tiles / .tile + Sparkline）
 *   - 防治闭环流程图（.flow / .node / .arrow）
 *   - 病虫害类型占比饼图 + 近 7 日趋势折线（ECharts）
 *   - 系统架构分层图（.layer / .boxes / .box / .conn）
 * 数据来源：GET /api/overview/kpis、/api/analytics/composition、/api/analytics/trend
 */
export default function OverviewPage() {
  return (
    <div className="card">
      <h3>
        系统概览 <span className="tag">Overview</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
