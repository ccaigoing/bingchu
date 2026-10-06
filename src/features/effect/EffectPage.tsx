import { Fragment, useMemo } from 'react'

import { EChart } from '@components/charts/EChart'
import { axisX, axisY, barSeries, legend, PALETTES, tip } from '@components/charts/chartTheme'
import { Card } from '@components/ui/Card'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatTile, kpiFooter } from '@components/ui/StatTile'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'

/**
 * 预期效果与评估 —— 对照 legacy/index.html 的 `#screen-effect`。
 *
 * 4 个 tile 全是正向指标，所以值一律染 --good（legacy 是逐个写死的内联色，
 * 这里收敛成一处常量，避免四个地方各写一遍写歪一个）。
 */
const GOOD = 'var(--good)'

export default function EffectPage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.effect(), [])

  const p = PALETTES[theme]

  const option = useMemo<Opt | null>(() => {
    if (!data) return null
    const c = data.comparison
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      legend: legend(p),
      grid: { left: 54, right: 20, top: 38, bottom: 30 },
      xAxis: { ...axisX(p), data: c.labels },
      yAxis: axisY(p),
      series: c.series.map((s, i) => barSeries(p, s.name, s.values, p.cat[i])),
    }
  }, [data, p])

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="效果评估数据" />

  return (
    <>
      <div className="tiles">
        {data.tiles.map((t) => (
          <StatTile
            key={t.key}
            label={t.label}
            value={t.valueText}
            unit={t.unit || undefined}
            valueColor={GOOD}
            footer={kpiFooter(t)}
          />
        ))}
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="使用前后关键指标对比">
          <EChart option={option} style={{ height: 300 }} />
        </Card>
        <Card title="评估方法" hint="持续收集与分析数据，验证系统实际效果">
          <dl className="kv">
            {data.methods.map((m) => (
              <Fragment key={m.term}>
                <dt>{m.term}</dt>
                <dd>{m.detail}</dd>
              </Fragment>
            ))}
          </dl>
        </Card>
      </div>
    </>
  )
}
