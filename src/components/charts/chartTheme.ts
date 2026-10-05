/* ═══════════════════════════════════════════════════════════
   图表主题 —— 从 legacy/index.html 的 <script> 原样迁移
   ═══════════════════════════════════════════════════════════

   全是**纯函数、零 DOM 依赖**。原版把它们内联在 IIFE 里，这里原样搬出，
   值一个都不要改（视觉零漂移是硬要求；原版锁定 echarts@5.5.0）。

   ⚠️ 主题切换必须**重建 option**：
   `PALETTES` 是 JS 对象，不是 CSS 变量 —— 改 `data-theme` 只会切换
   CSS 变量的值，对已经初始化过的 ECharts 实例毫无影响。所以 theme
   变化时要重新构造 option 并 `setOption(option, true)`。
   ═══════════════════════════════════════════════════════════ */

import type { ThemeName } from '@lib/types/theme'

// 再导出，这样图表侧只需 import chartTheme 一处
export type { ThemeName }

export interface Palette {
  surface: string
  ink: string
  ink2: string
  muted: string
  grid: string
  axis: string
  border: string
  cat: string[]
  seq: string[]
}

export const PALETTES: Record<ThemeName, Palette> = {
  light: {
    surface: '#fcfcfb',
    ink: '#0b0b0b',
    ink2: '#52514e',
    muted: '#898781',
    grid: '#e1e0d9',
    axis: '#c3c2b7',
    border: 'rgba(11,11,11,0.10)',
    cat: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
    seq: ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#2a78d6', '#1c5cab', '#0d366b'],
  },
  dark: {
    surface: '#1a1a19',
    ink: '#ffffff',
    ink2: '#c3c2b7',
    muted: '#898781',
    grid: '#2c2c2a',
    axis: '#383835',
    border: 'rgba(255,255,255,0.10)',
    cat: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
    seq: ['#184f95', '#256abf', '#3987e5', '#6da7ec', '#86b6ef', '#b7d3f6', '#cde2fb'],
  },
}

/** 状态色 —— 与 tokens.css 的 --good/--warning/--serious/--critical 同值。
 *  CSS 变量给不了 ECharts，这里必须有一份 JS 副本，改一处要改两处。 */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

export type StatusKey = keyof typeof STATUS

/**
 * ECharts 选项的松散片段。
 *
 * ECharts 的 `EChartsOption` 是巨型联合类型，逐字段拼装时有大量
 * 可选字段与 `undefined` 冲突，严格类型反而处处报错、逼人写 `any`。
 * 这里统一用松散片段，最终在 page 层用 `as EChartsOption` 收口
 * —— 全项目仅此一处断言，且写明了理由。
 */
export type Fragment = Record<string, unknown>

/** Canvas 不认 #rgb / #rrggbbaa 之外的写法，透明度统一走 rgba()。 */
export function hexRgba(hex: string, a: number): string {
  let h = hex.replace('#', '')
  if (h.length === 3) {
    h = h
      .split('')
      .map((c) => c + c)
      .join('')
  }
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `rgba(${r},${g},${b},${a})`
}

/** 千分位。原版用正则负向前瞻，兼容 IE 的写法，这里保留同样的输出。 */
export function fmt(n: number): string {
  return n.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',')
}

export function axisX(p: Palette): Fragment {
  return {
    type: 'category',
    boundaryGap: true,
    axisLine: { lineStyle: { color: p.axis } },
    axisTick: { show: false },
    axisLabel: { color: p.muted, fontSize: 11 },
    splitLine: { show: false },
  }
}

export function axisY(p: Palette): Fragment {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: p.muted, fontSize: 11 },
    splitLine: { lineStyle: { color: p.grid, width: 1 } },
  }
}

export function tip(p: Palette): Fragment {
  return {
    backgroundColor: p.surface,
    borderColor: p.axis,
    borderWidth: 1,
    textStyle: { color: p.ink, fontSize: 12 },
    padding: [8, 12],
  }
}

export function legend(p: Palette): Fragment {
  return {
    textStyle: { color: p.ink2, fontSize: 11 },
    icon: 'roundRect',
    itemWidth: 10,
    itemHeight: 10,
    itemGap: 16,
  }
}

export function lineSeries(
  p: Palette,
  name: string,
  data: number[],
  color: string,
  area = false,
): Fragment {
  const s: Fragment = {
    name,
    type: 'line',
    data,
    smooth: 0.25,
    symbol: 'circle',
    symbolSize: 5,
    showSymbol: false,
    lineStyle: { width: 2, color },
    itemStyle: { color, borderColor: p.surface, borderWidth: 2 },
    emphasis: { focus: 'series' },
  }
  if (area) s.areaStyle = { color: hexRgba(color, 0.1) }
  return s
}

export function barSeries(p: Palette, name: string, data: number[], color: string): Fragment {
  return {
    name,
    type: 'bar',
    data,
    barMaxWidth: 22,
    itemStyle: { color, borderRadius: [4, 4, 0, 0] },
    label: { show: true, position: 'top', color: p.ink2, fontSize: 11, fontWeight: '600' },
    emphasis: { focus: 'series' },
  }
}
