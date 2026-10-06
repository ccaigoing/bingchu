import { useMemo } from 'react'

import { EChart } from '@components/charts/EChart'
import { axisX, axisY, lineSeries, PALETTES, tip } from '@components/charts/chartTheme'
import { Card } from '@components/ui/Card'
import { Meter } from '@components/ui/Meter'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatTile } from '@components/ui/StatTile'
import { StatusBadge } from '@components/ui/StatusBadge'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { timeHMS } from '@lib/format'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'
import type { StatusKey } from '@lib/types/api'

/** 四个传感器通道：tile 的 key 就是读数表的列名，取色沿用 legacy 的 cat[0..3]。 */
const CHANNELS = ['temp', 'hum', 'ph', 'light'] as const

/** 数据流表只显示最新 8 条（legacy `while(tb.children.length>8)`）。 */
const STREAM_ROWS = 8

export default function MonitorPage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.monitor(), [])

  const p = PALETTES[theme]

  // 依赖写 `data` 而不是 `data.readings`：后者在 data 为空时是 `?? []`，
  // 每次渲染都是**新数组**，作为 useMemo 依赖会让它每帧重算。
  const tempOpt = useMemo<Opt | null>(() => {
    const rs = data?.readings
    if (!rs?.length) return null
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      grid: { left: 44, right: 16, top: 20, bottom: 28 },
      xAxis: { ...axisX(p), boundaryGap: false, data: rs.map((_, i) => i + 1) },
      yAxis: axisY(p),
      series: [lineSeries(p, '温度 (℃)', rs.map((r) => r.temp), p.cat[0], true)],
    }
  }, [data, p])

  const humOpt = useMemo<Opt | null>(() => {
    const rs = data?.readings
    if (!rs?.length) return null
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      grid: { left: 44, right: 16, top: 20, bottom: 28 },
      xAxis: { ...axisX(p), boundaryGap: false, data: rs.map((_, i) => i + 1) },
      yAxis: axisY(p),
      series: [lineSeries(p, '湿度 (%)', rs.map((r) => r.hum), p.cat[1], true)],
    }
  }, [data, p])

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="传感器数据" />

  const d = data.drone
  const readings = data.readings
  // 最新的 N 条，倒序 —— 表头下面是"刚刚"，往下才是"更早"。
  const stream = readings.slice(-STREAM_ROWS).reverse()

  return (
    <>
      <div className="tiles">
        {data.tiles.map((t) => {
          const ch = CHANNELS.find((c) => c === t.key)
          return (
            <StatTile
              key={t.key}
              label={t.label}
              value={t.value}
              unit={t.unit || undefined}
              footer={{ kind: 'delta', tone: t.tone, text: t.note }}
              spark={
                ch && readings.length > 1
                  ? {
                      data: readings.map((r) => r[ch]),
                      color: p.cat[CHANNELS.indexOf(ch)],
                    }
                  : undefined
              }
            />
          )
        })}
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="温度实时趋势" tag="最近 30 个采样点">
          <EChart option={tempOpt} />
        </Card>
        <Card title="无人机飞行状态">
          <div className="grid g-11">
            <div
              className="stage"
              style={{ minHeight: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 12 }}
            >
              <DroneSvg />
            </div>
            <dl className="kv">
              <dt>飞行状态</dt>
              <dd>
                {d ? (
                  <StatusBadge status={(d.statusTone as StatusKey) ?? 'good'}>{d.status}</StatusBadge>
                ) : (
                  '—'
                )}
              </dd>
              <dt>当前高度</dt>
              <dd>{d ? `${d.altitude.toFixed(1)} m` : '—'}</dd>
              <dt>飞行速度</dt>
              <dd>{d ? `${d.speed.toFixed(1)} m/s` : '—'}</dd>
              <dt>剩余电量</dt>
              <dd>
                <div style={{ margin: '4px 0 0' }}>
                  <Meter value={d?.battery ?? 0} />
                </div>
              </dd>
              <dt>作业区域</dt>
              <dd>{d?.area ?? '—'}</dd>
              <dt>航线类型</dt>
              <dd>{d?.route ?? '—'}</dd>
            </dl>
          </div>
        </Card>
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="湿度实时趋势" tag="最近 30 个采样点">
          <EChart option={humOpt} />
        </Card>
        <Card title="实时数据流" tag={`最新 ${STREAM_ROWS} 条`}>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>时间</th>
                  <th>温度</th>
                  <th>湿度</th>
                  <th>pH</th>
                  <th>光照</th>
                </tr>
              </thead>
              <tbody>
                {stream.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{timeHMS(r.ts)}</td>
                    <td className="mono">{r.temp.toFixed(1)}℃</td>
                    <td className="mono">{r.hum.toFixed(1)}%</td>
                    <td className="mono">{r.ph.toFixed(2)}</td>
                    <td className="mono">{r.light.toFixed(1)}kLx</td>
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

/**
 * 无人机示意图。从 legacy 原样搬过来 —— 它是**动画示意**不是数据可视化，
 * 所以留着 SVG，不像识别页的假叶片那样删掉：假叶片冒充的是识别结果，
 * 这里没有任何数据被冒充。
 */
function DroneSvg() {
  return (
    <svg viewBox="0 0 200 140" width="180" aria-hidden="true">
      <line x1="100" y1="70" x2="100" y2="28" stroke="var(--accent)" strokeWidth="2" />
      <line x1="100" y1="70" x2="64" y2="104" stroke="var(--accent)" strokeWidth="2" />
      <line x1="100" y1="70" x2="136" y2="104" stroke="var(--accent)" strokeWidth="2" />
      <circle cx="100" cy="70" r="7" fill="var(--accent)" />
      {[
        { cx: 100, cy: 24, begin: undefined },
        { cx: 60, cy: 100, begin: '0.4s' },
        { cx: 140, cy: 100, begin: '0.8s' },
      ].map((r) => (
        <circle
          key={`${r.cx}-${r.cy}`}
          cx={r.cx}
          cy={r.cy}
          r="15"
          fill="none"
          stroke="var(--accent)"
          strokeWidth="2"
          opacity="0.5"
        >
          <animate attributeName="r" values="12;18;12" dur="1.4s" begin={r.begin} repeatCount="indefinite" />
        </circle>
      ))}
    </svg>
  )
}
