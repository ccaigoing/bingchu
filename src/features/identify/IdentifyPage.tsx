import { useEffect, useMemo, useRef, useState } from 'react'

import { EChart } from '@components/charts/EChart'
import { PALETTES, tip } from '@components/charts/chartTheme'
import { Card } from '@components/ui/Card'
import { Icon } from '@components/ui/Icon'
import { Meter } from '@components/ui/Meter'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatusBadge } from '@components/ui/StatusBadge'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { pct } from '@lib/format'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'
import type { DetectResult } from '@lib/types/api'

/* ═══════════════════════════════════════════════════════════
   病虫害识别 —— 全系统最重要的一屏
   ═══════════════════════════════════════════════════════════

   对照 legacy/index.html 的 `#screen-identify`，但有一处**必须的删除**：

   legacy 的叶片是 `drawLeaf()` 现场画的 SVG —— 绿色叶形 path + 按预设坐标
   打的褐色圆点 + 按预设 box 画的红框。它**不能处理任何一张真实图片**，
   用户最高优先级的诉求（"上传真图 → 真的标出类型和位置"）正是冲它来的。

   所以这里整段删掉，换成：
     选图 → POST /api/detect → 显示**后端画好框的实拍图** + 叠一层可 hover 的交互框

   同时删掉的还有"切换样本 / 点缩略图换结果"—— 那是切换**假图**的开关。
   四个示例样本降级为一行只读的参考条目（名字 + 置信度），不可点击：
   界面上任何一个数字都必须能追到一次真实推理。

   ⚠️ 两个刻度不要混（详见 lib/types/api.ts 顶部）：
     summary.confidence       诊断置信度 —— 卡片上那个"置信度"
     detections[].localizationScore  框贴合度 —— hover 框时显示的
   ═══════════════════════════════════════════════════════════ */

const RECORD_LIMIT = 6

export default function IdentifyPage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.identify(), [])

  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [result, setResult] = useState<DetectResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [detectError, setDetectError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const p = PALETTES[theme]

  // 释放上一张预览的 object URL。演示时反复选图很常见，不释放就是稳定泄漏
  // （每张图都留在内存里直到刷新）。cleanup 时 preview 还是**旧值**，
  // 所以撤销的正是要被替换掉的那一个。
  useEffect(() => {
    return () => {
      if (preview) URL.revokeObjectURL(preview)
    }
  }, [preview])

  const chartOpt = useMemo<Opt | null>(() => {
    if (!data) return null
    // 升序排 —— ECharts 类目轴的第一个值画在**最下面**，
    // 升序进来才会变成"最大的那条在最上面"。后端给什么顺序都不影响。
    const rows = [...data.classes].sort((a, b) => a.count - b.count)
    return {
      tooltip: tip(p),
      grid: { left: 90, right: 30, top: 10, bottom: 30 },
      xAxis: {
        type: 'value',
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: p.muted, fontSize: 11 },
        splitLine: { lineStyle: { color: p.grid, width: 1 } },
      },
      yAxis: {
        type: 'category',
        data: rows.map((c) => c.nameCn),
        axisLine: { lineStyle: { color: p.axis } },
        axisTick: { show: false },
        axisLabel: { color: p.muted, fontSize: 11 },
      },
      series: [
        {
          type: 'bar',
          data: rows.map((c) => c.count),
          barMaxWidth: 16,
          itemStyle: { color: p.cat[0], borderRadius: [0, 4, 4, 0] },
          label: { show: true, position: 'right', color: p.ink2, fontSize: 11 },
        },
      ],
    }
  }, [data, p])

  function choose(f: File | null | undefined) {
    if (!f) return
    setResult(null)
    setDetectError(null)
    setFile(f)
    setPreview(URL.createObjectURL(f))
  }

  function clear() {
    setFile(null)
    setPreview(null)
    setResult(null)
    setDetectError(null)
  }

  async function runDetect() {
    if (!file || busy) return
    setBusy(true)
    setDetectError(null)
    try {
      const r = await api.detect(file)
      setResult(r)
      // 记录表与"各类识别次数"都来自 DB，不重取就还是上传前的样子 ——
      // 验收标准第 6 条（记录表新增一行）靠的就是这一句。
      reload()
    } catch (e) {
      setDetectError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="识别记录与类别统计" />

  const degraded = result?.model.mode === 'degraded'
  const s = result?.summary

  return (
    <>
      {degraded && (
        <div className="banner" style={{ borderColor: 'var(--critical)' }}>
          <b>模型处于降级模式</b> —— {result?.model.error ?? '权重未加载'}。
          识别结果不可用，请检查 models/ 目录后重启后端。
        </div>
      )}

      <div className="grid g-12">
        <Card title="作物图像" tag="无人机高清摄像头采集">
          <div
            className="stage"
            style={{ minHeight: 360, cursor: file ? 'default' : 'pointer' }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault()
              choose(e.dataTransfer.files?.[0])
            }}
            onClick={() => {
              if (!file) inputRef.current?.click()
            }}
          >
            {result ? (
              <>
                <img className="shot" src={result.image.annotatedUrl} alt="带检测框的识别结果" />
                {result.detections.map((d, i) => (
                  <div
                    key={`${d.code ?? 'x'}-${i}`}
                    className="detbox"
                    tabIndex={0}
                    style={{
                      left: `${d.box.x * 100}%`,
                      top: `${d.box.y * 100}%`,
                      width: `${d.box.w * 100}%`,
                      height: `${d.box.h * 100}%`,
                    }}
                    title={`${d.nameCn} · 框贴合度 ${pct(d.localizationScore)} · 占图 ${pct(d.areaRatio)}`}
                  >
                    <span className="detbox-lab">
                      {d.nameCn} {pct(d.localizationScore, 0)}
                    </span>
                  </div>
                ))}
              </>
            ) : preview ? (
              <img className="shot" src={preview} alt="待识别的原图" />
            ) : (
              <div className="placeholder">
                <Icon name="leaf" size={26} />
                <span>
                  尚未选择图片
                  <br />
                  点击此处或将水稻叶片照片拖进来
                </span>
              </div>
            )}
          </div>

          <input
            ref={inputRef}
            type="file"
            accept="image/*"
            hidden
            onChange={(e) => {
              choose(e.target.files?.[0])
              // 清空 value：否则连续选同一张图不会再触发 change
              e.target.value = ''
            }}
          />

          <div style={{ marginTop: 14, display: 'flex', gap: 10 }}>
            <button type="button" className="btn primary" disabled={!file || busy} onClick={runDetect}>
              <Icon name="search" size={15} />
              {busy ? '识别中…' : '开始识别'}
            </button>
            <button type="button" className="btn" onClick={() => inputRef.current?.click()}>
              <Icon name="refresh" size={15} />
              选择图片
            </button>
            {file && (
              <button type="button" className="btn" onClick={clear}>
                清除
              </button>
            )}
          </div>

          {detectError && (
            <div className="banner" style={{ marginTop: 12, marginBottom: 0, borderColor: 'var(--critical)' }}>
              识别失败：{detectError}
            </div>
          )}

          <p className="hint" style={{ marginTop: 14 }}>
            示例病害（只读参考，不可点选 —— 界面上每个数字都来自一次真实推理）
          </p>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 6 }}>
            {data.samples.map((sp) => (
              <span key={sp.nameCn} className="chip" style={{ cursor: 'default' }}>
                {sp.nameCn} · {pct(sp.confidence)}
              </span>
            ))}
          </div>
        </Card>

        <Card
          title="识别结果"
          tag={result ? `${result.detections.length} 个检测框` : '待上传'}
        >
          <div style={{ marginTop: 6 }}>
            <div className="lab muted">诊断结果</div>
            <div className="hero">{s?.topClassName ?? '—'}</div>

            <div style={{ margin: '8px 0 2px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span className="muted">置信度</span>
              <span style={{ fontWeight: 700 }}>{pct(s?.confidence ?? null)}</span>
            </div>
            <Meter value={(s?.confidence ?? 0) * 100} high={(s?.confidence ?? 0) * 100 > 90} />

            <dl className="kv" style={{ marginTop: 14 }}>
              <dt>严重程度</dt>
              <dd>{s ? <StatusBadge status={s.severityLevel}>{s.severityLabel}</StatusBadge> : '—'}</dd>
              <dt>感染区域</dt>
              <dd>{s?.regionDesc ?? '—'}</dd>
              <dt>感染面积占比</dt>
              <dd>{pct(s?.infectedAreaRatio ?? null)}</dd>
              <dt>病斑数量</dt>
              <dd>{s ? `${s.spotCount} 处` : '—'}</dd>
              <dt>建议措施</dt>
              <dd>{s?.advice ?? '—'}</dd>
            </dl>
          </div>

          {result && (
            <p className="hint" style={{ marginTop: 14 }}>
              模型 {result.model.name} {result.model.version} · {result.model.device} ·{' '}
              {result.latencyMs} ms
            </p>
          )}
        </Card>
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="各类病虫害识别次数" tag="近 30 日">
          <EChart option={chartOpt} />
        </Card>
        <Card
          title="识别记录"
          tag={`最近 ${Math.min(RECORD_LIMIT, data.records.length)} 条 · 累计 ${data.stats.total}`}
        >
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>病害类型</th>
                  <th>置信度</th>
                  <th>级别</th>
                </tr>
              </thead>
              <tbody>
                {data.records.slice(0, RECORD_LIMIT).map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.timeText}</td>
                    <td>
                      {r.nameCn}
                      {/* 上传来的记录给个标记 —— 答辩时一眼能看出
                          "这一行是我刚才传的那张图" */}
                      {r.source === 'upload' && (
                        <span className="st good" style={{ marginLeft: 6 }}>
                          实拍
                        </span>
                      )}
                    </td>
                    <td className="mono">{pct(r.confidence)}</td>
                    <td>
                      <StatusBadge status={r.severity}>{r.severityLabel}</StatusBadge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>
    </>
  )
}
