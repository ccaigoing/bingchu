/**
 * 预警系统 —— 脚手架占位。
 *
 * 2.4 / 2.5 移植清单（对照 legacy/index.html 的 `#screen-alert`）：
 *   - 预警列表（原 warnRow + renderWarns 拼 innerHTML → <WarningList> + map）
 *   - 4 个阈值滑块（.chip / input[type=range]）→ GET/PUT /api/thresholds
 *   - 预警详情与处置（/api/warnings/:id/handle）
 * 关键约束：预警**不再由前端 35% 概率随机生成**（原 maybeWarn/7000ms 已删）。
 * 改为后端 WarningEngine 三源判定：阈值 + 检测记录 + LSTM 预测。
 */
export default function AlertPage() {
  return (
    <div className="card">
      <h3>
        预警系统 <span className="tag">Warning System</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
