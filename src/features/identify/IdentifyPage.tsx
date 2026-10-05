/**
 * 病虫害识别 —— 脚手架占位。**本页是全案最高优先级的落点。**
 *
 * 2.4 移植清单（对照 legacy/index.html 的 `#screen-identify`）：
 *   - 上传区（把阶段一 tools/verify.html 的临时表单换成正式组件，接 POST /api/detect）
 *   - <DetectCanvas>：显示后端返回的 annotatedUrl（**后端画好框的图**），
 *     叠加层用归一化 box 映射为 left/top/width/height 百分比
 *   - 识别结果：类别名 / 置信度 / 严重度 / 感染面积占比 / 建议措施
 *   - 样例缩略图（.thumbs）→ 来自 DB 的 disease_samples，不再是硬编码数组
 *
 * ⚠️ **原版的 drawLeaf() 整段删除**：那是用 SVG <path> 现画的假叶片 +
 * 预设坐标的假病斑 + 预设 box[] 的假检测框。改造后页面上不允许出现任何
 * SVG 假叶片 —— 这是验收清单第 1 条。
 */
export default function IdentifyPage() {
  return (
    <div className="card">
      <h3>
        病虫害识别 <span className="tag">Pest &amp; Disease Identification</span>
      </h3>
      <p className="hint">脚手架已就位，页面内容将在 2.4 从 legacy 移植。</p>
    </div>
  )
}
