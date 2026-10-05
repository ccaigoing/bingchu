/**
 * 实时监测 —— 脚手架占位。
 *
 * 2.4 / 2.5 移植清单（对照 legacy/index.html 的 `#screen-monitor`）：
 *   - 温/湿/pH/光照 四路实时读数 + 时序曲线
 *   - 数据流表格（原 streamTable 的 insertAdjacentHTML → store 数组 + map）
 *   - 设备状态（无人机、虫情测报灯、气象站）
 *   - 实时推送：后端 SensorEngine 每 2s 写库 → SSE `/api/stream` 的 sensor.tick
 * 关键约束：**前端不再有 setInterval 造数据**。原来的 tick(2000) 整段搬后端。
 */
export default function MonitorPage() {
  return (
    <div className="card">
      <h3>
        实时监测 <span className="tag">Real-time Monitoring</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
