/**
 * 喷洒方案与执行 —— 脚手架占位。
 *
 * 2.4 移植清单（对照 legacy/index.html 的 `#screen-spray`）：
 *   - A/B/C 三方案对比表（高效 / 低成本 / 环保）
 *   - 五维雷达图（防治效果 / 成本效益 / 时效性 / 环保性 / 易执行）
 *   - 可作业窗口（由预报天气算出：无雨、风速<3m/s、15–30℃）
 *   - 执行时间线（.timeline）与进度（.meter），由后端 SprayEngine 推进 → SSE
 * 数据来源：GET /api/spray/plans、/api/spray/plans/generate、
 *           /api/spray/tasks/active、/api/spray/products
 * 一致性硬约束：方案 A 的农药必须与识别页"建议措施"里的农药是 products 表的同一行。
 */
export default function SprayPage() {
  return (
    <div className="card">
      <h3>
        喷洒方案与执行 <span className="tag">Spraying Plan &amp; Execution</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
