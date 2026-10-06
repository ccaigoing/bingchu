import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

import type { Fragment } from '@components/charts/chartTheme'
import type { EChartsOption } from 'echarts'

/* ═══════════════════════════════════════════════════════════
   useECharts —— 自建封装，替掉 legacy 的 charts{} 全局字典
   ═══════════════════════════════════════════════════════════

   不用 `echarts-for-react`：React 19 下类型报错未修、StrictMode 里实例
   取不到；且 2026-05 该包发生过 npm 供应链投毒（3.0.7/3.1.7/3.2.7 为
   恶意版本）。自建这个 hook 一共四十行，没有引入这个风险的必要。

   legacy 的做法是：全局 `charts{}` 字典 + `renderers[current]()` 注册表 +
   `window.resize` 里遍历所有实例 resize。三样全部去掉：
     - 每张图挂在各自路由上，切屏自动挂载/卸载，不需要手动管理生命周期
     - ResizeObserver 观察**容器**，侧栏折叠、路由切换这类布局变化也能捕获，
       `window.resize` 做不到（窗口没变但容器变了）
   ═══════════════════════════════════════════════════════════ */

export function useECharts(option: Fragment | null) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<echarts.ECharts | null>(null)

  // option 也存一份：挂载 effect 是 [] 依赖的，它需要拿到"当前"的 option。
  // 同步写在它自己的 effect 里而不是渲染期直接赋值 —— 渲染期改 ref 属于
  // 副作用，React 明确不保证这种写法在并发渲染下的时序。
  // 声明顺序很关键：这个 effect 必须排在挂载 effect **之前**，否则首次
  // 挂载时 chart 拿到的是 undefined，画面空白。
  const optionRef = useRef(option)
  useEffect(() => {
    optionRef.current = option
  }, [option])

  useEffect(() => {
    const el = ref.current
    if (!el) return

    // 判重：StrictMode 下 effect 会跑两次。不判重就会在同一容器上 init
    // 出两个实例，第二个盖住第一个，而第一个永远不 dispose（内存泄漏 +
    // 两个实例抢同一块 canvas 的渲染）。
    let chart = echarts.getInstanceByDom(el)
    if (!chart) chart = echarts.init(el)
    chartRef.current = chart

    // 挂载时若已有 option 就先画上。
    // 这一步不能省：StrictMode 重挂载时 option 没变，下面那个 [option] 的
    // effect 不会重跑，新实例就会是一张白图。
    if (optionRef.current) chart.setOption(asOption(optionRef.current), true)

    const ro = new ResizeObserver(() => chart?.resize())
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart?.dispose()
      chartRef.current = null
    }
  }, [])

  useEffect(() => {
    if (!option) return
    // notMerge=true 是**必须**的：主题切换要整体重建 option。
    // PALETTES 是 JS 对象不是 CSS 变量，改 data-theme 对已初始化的实例
    // 毫无影响，只有重建才能换色。顺带避免旧 series 残留。
    chartRef.current?.setOption(asOption(option), true)
  }, [option])

  return ref
}

/**
 * 全项目**唯一**一处 `as EChartsOption`。
 *
 * ECharts 的 `EChartsOption` 是巨型联合类型，逐字段拼装有大量
 * "可选字段 vs undefined" 的冲突，严格类型下处处报错、逼人写 `any`。
 * 与其让 7 个页面各写一个断言（等于把 `any` 撒得到处都是），
 * 不如让各屏拼松散的 `Fragment`，在这一处收口 —— 出事只有一个地方。 */
function asOption(f: Fragment): EChartsOption {
  return f as EChartsOption
}
