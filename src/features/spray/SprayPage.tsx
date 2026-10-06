import { useMemo } from 'react'

import { EChart } from '@components/charts/EChart'
import { hexRgba, legend, PALETTES, tip } from '@components/charts/chartTheme'
import { Card } from '@components/ui/Card'
import { Meter } from '@components/ui/Meter'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatusBadge } from '@components/ui/StatusBadge'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { fixed } from '@lib/format'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'
import type { SprayPlan } from '@lib/types/api'

export default function SprayPage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.spray(), [])

  const p = PALETTES[theme]

  const radar = useMemo<Opt | null>(() => {
    if (!data) return null
    return {
      tooltip: tip(p),
      legend: { ...legend(p), bottom: 0, left: 'center' },
      radar: {
        indicator: data.radar.dimensions.map((name) => ({ name, max: 100 })),
        radius: '62%',
        axisName: { color: p.ink2, fontSize: 12 },
        splitLine: { lineStyle: { color: p.grid } },
        splitArea: { areaStyle: { color: [p.surface, hexRgba(p.grid, 0.4)] } },
        axisLine: { lineStyle: { color: p.grid } },
      },
      series: [
        {
          type: 'radar',
          data: data.radar.series.map((s, i) => ({
            name: s.name,
            value: s.values,
            itemStyle: { color: p.cat[i] },
            areaStyle: { color: hexRgba(p.cat[i], 0.12) },
            lineStyle: { width: 2, color: p.cat[i] },
          })),
          symbol: 'circle',
          symbolSize: 5,
        },
      ],
    }
  }, [data, p])

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="喷洒方案" />

  const active = data.active

  return (
    <>
      <div className="grid g-3">
        {data.plans.map((plan) => (
          <PlanCard key={plan.planKey} plan={plan} />
        ))}
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="三方案综合对比" tag="雷达图 · 分值越高越好">
          <EChart option={radar} style={{ height: 320 }} />
        </Card>
        <Card title="无人机执行进度" hint={active ? `当前任务：${active.task.title}` : '当前没有执行中的任务'}>
          {active ? (
            <>
              <dl className="kv">
                <dt>任务进度</dt>
                <dd>
                  <Meter value={active.task.progress} />
                </dd>
                <dt>已喷洒面积</dt>
                <dd>
                  {fixed(active.task.areaDone, 1)} / {fixed(active.task.areaTotal, 0)} 亩
                </dd>
                <dt>预计完成</dt>
                <dd>{active.task.eta ?? '—'}</dd>
                <dt>实时反馈</dt>
                <dd>{active.task.feedback ?? '—'}</dd>
              </dl>
              <h3 style={{ marginTop: 16 }}>执行日志</h3>
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>时间</th>
                      <th>事件</th>
                    </tr>
                  </thead>
                  <tbody>
                    {active.logs.map((l) => (
                      <tr key={`${l.time}-${l.event}`}>
                        <td className="mono">{l.time}</td>
                        <td>{l.event}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          ) : (
            <p className="hint">无人机空闲中。方案下发后这里显示作业进度与执行日志。</p>
          )}
        </Card>
      </div>
    </>
  )
}

/** 一张方案卡。推荐方案（后端算出的最高综合分）加强调色描边 —— legacy 是用内联 style 做的。 */
function PlanCard({ plan }: { plan: SprayPlan }) {
  return (
    <div className="card" style={plan.recommended ? { borderColor: 'var(--accent)' } : undefined}>
      <h3>
        {plan.name} {plan.recommended && <StatusBadge status="good">推荐</StatusBadge>}
      </h3>
      <p className="hint">{plan.tagline}</p>
      <dl className="kv">
        <dt>农药种类</dt>
        <dd>{plan.product.name}</dd>
        <dt>用量</dt>
        <dd>{plan.dosage}</dd>
        <dt>喷洒时机</dt>
        <dd>{plan.timing}</dd>
        <dt>预计防治率</dt>
        <dd>{plan.efficacy.toFixed(0)}%</dd>
        <dt>综合成本</dt>
        <dd>¥{plan.costPerMu.toFixed(1)} / 亩</dd>
      </dl>
    </div>
  )
}
