/**
 * 预期效果与评估 —— 脚手架占位。
 *
 * 2.4 / 阶段五 移植清单（对照 legacy/index.html 的 `#screen-effect`）：
 *   - 4 个效果 tile（防治率、减损、成本、用时）
 *   - 喷施 vs 不喷施对比图（反事实推演，来自 LSTM 的对照预测）
 *   - 模型与数据溯源区（model_registry / datasets 两张表）
 * 数据来源：GET /api/effect/metrics、/api/effect/comparison、
 *           /api/effect/counterfactual、/api/models、/api/datasets
 */
export default function EffectPage() {
  return (
    <div className="card">
      <h3>
        预期效果与评估 <span className="tag">Expected Effects</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
