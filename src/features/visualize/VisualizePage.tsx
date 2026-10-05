/**
 * 数据可视化 —— 脚手架占位。
 *
 * 2.4 移植清单（对照 legacy/index.html 的 `#screen-visualize`）：
 *   - 8×6 地块严重度地图（.fieldmap / .plot，48 格 + .legend-ramp 色阶）
 *   - 病害发生趋势、农药使用量对比等 ECharts 图
 * 数据来源：GET /api/field/severity（48 格 sev 数组）、/api/field/plots、
 *           /api/analytics/*
 * 注意：severity 0–5 直接映射 PALETTES[theme].seq[0..6]，主题切换要重建 option。
 */
export default function VisualizePage() {
  return (
    <div className="card">
      <h3>
        数据可视化 <span className="tag">Data Visualization</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
