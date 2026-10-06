import { useMemo } from 'react'

import { EChart } from '@components/charts/EChart'
import { axisX, axisY, barSeries, legend, lineSeries, PALETTES, tip } from '@components/charts/chartTheme'
import { Card } from '@components/ui/Card'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'
import type { Palette } from '@components/charts/chartTheme'

export default function VisualizePage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.visualize(), [])

  const p = PALETTES[theme]

  const trendOpt = useMemo<Opt | null>(() => {
    if (!data) return null
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      legend: legend(p),
      grid: { left: 44, right: 20, top: 38, bottom: 30 },
      xAxis: { ...axisX(p), boundaryGap: false, data: data.trend.labels },
      yAxis: axisY(p),
      series: data.trend.series.map((s, i) => lineSeries(p, s.name, s.values, p.cat[i])),
    }
  }, [data, p])

  const pestOpt = useMemo<Opt | null>(() => {
    if (!data) return null
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      legend: legend(p),
      grid: { left: 44, right: 20, top: 38, bottom: 30 },
      xAxis: { ...axisX(p), data: data.pesticide.labels },
      yAxis: axisY(p),
      series: data.pesticide.series.map((s, i) => barSeries(p, s.name, s.values, p.cat[i])),
    }
  }, [data, p])

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="分析序列与地块严重度" />

  const f = data.field

  return (
    <>
      <Card title="近 30 日病虫害发生率趋势" tag={`单位：${data.trend.unit ?? '%'}`}>
        <EChart option={trendOpt} style={{ height: 300 }} />
      </Card>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card
          title="农田地块病虫害严重程度分布"
          tag={`${f.fieldName} · ${f.rows}×${f.cols} 地块`}
          hint="地块标注「X排X号」：排为自上而下第几排、号为自左向右第几号；仅标注中度及以上地块。"
        >
          <div className="fieldmap">
            {f.cells.map((c) => (
              <div
                key={c.code}
                className="plot"
                style={{ background: severityColor(p, c.severity) }}
                title={`${c.label} · ${c.severityLabel}`}
              >
                {c.showLabel ? c.label : ''}
              </div>
            ))}
          </div>
          <div className="legend-ramp">
            <span>低</span>
            <div
              className="ramp"
              style={{
                background: `linear-gradient(90deg,${p.seq[0]},${p.seq[Math.floor(p.seq.length / 2)]},${p.seq[p.seq.length - 1]})`,
              }}
            />
            <span>高</span>
          </div>
        </Card>
        <Card title="农药使用量 · 使用前后对比" tag={`单位：${data.pesticide.unit ?? 'L/亩'}`}>
          <EChart option={pestOpt} style={{ height: 252 }} />
        </Card>
      </div>
    </>
  )
}

/**
 * 严重度 0–5 → 顺序色阶。越界时夹到最后一档（legacy 是 `p.seq[Math.min(v,len-1)]`），
 * 这样后端万一给出比色阶长的严重度也只是取到最深的颜色，而不是 `undefined`
 * 让地块变成透明。
 */
function severityColor(p: Palette, severity: number): string {
  return p.seq[Math.min(severity, p.seq.length - 1)]
}
