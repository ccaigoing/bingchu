import { useMemo } from 'react'

import { EChart } from '@components/charts/EChart'
import { axisX, axisY, lineSeries, PALETTES, tip } from '@components/charts/chartTheme'
import { Icon } from '@components/ui/Icon'
import type { IconName } from '@components/layout/IconSprite'
import { Card } from '@components/ui/Card'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatTile, kpiFooter } from '@components/ui/StatTile'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'
import { useThemeStore } from '@stores/themeStore'

import type { Fragment as Opt } from '@components/charts/chartTheme'

/**
 * 概览页的 sparkline 取色。
 *
 * ⚠️ 这张表是**从 legacy 抄下来的**，不是算出来的：原版 spkArea 与 spkPest
 * 用的是同一个 p.cat[2]，spkWarn 用的是最后一个 p.cat[7]。看着像笔误，
 * 但"视觉零漂移"是硬要求，改色要单独提，不能顺手改。
 */
const SPARK_COLOR: Record<string, number> = { recog: 0, warn: 7, area: 2, pest: 2 }

/** legacy 只有「农药使用量变化」这张 tile 的值染了 --good（-20% 是减排成果）。 */
const GOOD_KEYS = new Set(['pest'])

/**
 * 防治闭环的六个环节。**注意第二项的措辞与 legacy 不同**：
 * 原版写"改进 YOLOv5"，但本项目实际加载的是 YOLO11x
 * （见 `/api/models`：jktk_x / YOLO11x / 116 类）。
 * 屏幕上留一句与模型登记表对不上的话，是答辩现场最容易被抓的那种。
 * 这里改成中性且为真的说法；识别页的模型名则是从响应里读的真实值。
 */
const FLOW: { icon: IconName; t: string; d: string }[] = [
  { icon: 'activity', t: '实时监测', d: '传感器数据采集' },
  { icon: 'search', t: '病虫害识别', d: 'YOLO 目标检测' },
  { icon: 'alert', t: '预警系统', d: '阈值触发告警' },
  { icon: 'flask', t: '喷洒方案', d: 'LSTM 生成方案' },
  { icon: 'send', t: '精准喷洒', d: '无人机执行' },
  { icon: 'refresh', t: '反馈优化', d: '动态调整策略' },
]

export default function OverviewPage() {
  const theme = useThemeStore((s) => s.theme)
  const { data, error, reload } = useApi(() => api.overview(), [])

  const p = PALETTES[theme]

  const pie = useMemo<Opt | null>(() => {
    const s = data?.series['overview.composition']
    if (!s) return null
    return {
      tooltip: tip(p),
      color: p.cat,
      // 圆心两行字。legacy 把 "5 类" 写死了，这里按实际类别数算 ——
      // 后端加一个类别它就跟着变，不会变成一句对不上的话。
      graphic: [
        {
          type: 'text',
          left: 'center',
          top: '35%',
          style: { text: `${s.labels.length} 类`, fill: p.ink, fontSize: 26, fontWeight: '700', textAlign: 'center' },
        },
        {
          type: 'text',
          left: 'center',
          top: '48%',
          style: { text: '主要病害', fill: p.muted, fontSize: 11, textAlign: 'center' },
        },
      ],
      series: [
        {
          type: 'pie',
          radius: ['50%', '72%'],
          center: ['50%', '44%'],
          itemStyle: { borderColor: p.surface, borderWidth: 2 },
          label: { show: true, formatter: '{b}\n{d}%', color: p.ink2, fontSize: 11, lineHeight: 16 },
          labelLine: { show: true, length: 12, length2: 8, lineStyle: { color: p.axis } },
          emphasis: { label: { color: p.ink, fontWeight: '700' } },
          data: s.labels.map((name, i) => ({ name, value: s.values[i] })),
        },
      ],
    }
  }, [data, p])

  const trend = useMemo<Opt | null>(() => {
    const s = data?.series['overview.warnTrend']
    if (!s) return null
    return {
      tooltip: { ...tip(p), trigger: 'axis' },
      grid: { left: 44, right: 20, top: 20, bottom: 30 },
      xAxis: { ...axisX(p), data: s.labels },
      yAxis: axisY(p),
      series: [
        {
          ...lineSeries(p, s.title, s.values, p.cat[0], true),
          markPoint: {
            symbolSize: 38,
            label: { color: p.ink2, fontSize: 10, formatter: '峰值 {c}' },
            itemStyle: { color: p.cat[0], borderColor: p.surface, borderWidth: 2 },
            data: [{ type: 'max', name: '峰值' }],
          },
        },
      ],
    }
  }, [data, p])

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="概览数据" />

  return (
    <>
      <div className="tiles">
        {data.tiles.map((t) => {
          const s = t.seriesKey ? data.series[t.seriesKey] : undefined
          return (
            <StatTile
              key={t.key}
              label={t.label}
              value={t.valueText}
              unit={t.unit || undefined}
              valueColor={GOOD_KEYS.has(t.key) ? 'var(--good)' : undefined}
              footer={kpiFooter(t)}
              spark={
                s && s.values.length > 1
                  ? { data: s.values, color: p.cat[SPARK_COLOR[t.key] ?? 0] }
                  : undefined
              }
            />
          )
        })}
      </div>

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card
          title="病虫害防治闭环"
          tag="监测 → 识别 → 预警 → 方案 → 喷洒 → 反馈"
          hint="系统通过无人机与传感器实现从诊断到治理的完整闭环"
        >
          <div className="flow">
            {FLOW.map((n, i) => (
              <FlowNode key={n.t} index={i} icon={n.icon} title={n.t} desc={n.d} />
            ))}
          </div>
        </Card>
        <Card title="病虫害类型占比" tag="近 30 日">
          <EChart option={pie} style={{ height: 252 }} />
        </Card>
      </div>

      <Card title="近 7 日病虫害预警趋势" style={{ marginTop: 16 }}>
        <EChart option={trend} style={{ height: 260 }} />
      </Card>
    </>
  )
}

/** 一个环节 + 它前面的箭头。箭头夹在中间，所以从第二个开始才渲染。 */
function FlowNode({
  index,
  icon,
  title,
  desc,
}: {
  index: number
  icon: IconName
  title: string
  desc: string
}) {
  return (
    <>
      {index > 0 && <div className="arrow">→</div>}
      <div className="node">
        <span className="n-ic">
          <Icon name={icon} size={22} />
        </span>
        <div className="n-t">{title}</div>
        <div className="n-d">{desc}</div>
      </div>
    </>
  )
}
