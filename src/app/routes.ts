import type { IconName } from '@components/layout/IconSprite'

/**
 * 7 个屏的路径常量。取自 legacy/index.html 的 `<nav>` data-screen 顺序
 * （overview → monitor → identify → visualize → alert → spray → effect），
 * 一个不多一个不少。
 *
 * 这里**只放路径与导航元数据**，不放组件 —— 组件映射在 router.tsx。
 * 拆开是为了让 Sidebar/Topbar 能 import 导航表而不把 7 个页面组件
 * 一并拖进首屏 bundle（页面在 router 里 lazy 加载）。
 */
export const ROUTES = {
  OVERVIEW: '/',
  MONITOR: '/monitor',
  IDENTIFY: '/identify',
  VISUALIZE: '/visualize',
  ALERT: '/alert',
  SPRAY: '/spray',
  EFFECT: '/effect',
} as const

export interface NavEntry {
  path: string
  /** 中文标签，显示在侧栏与顶栏标题 */
  label: string
  /** 英文副标题，侧栏小字 */
  sub: string
  icon: IconName
  /** 侧栏分组名。相邻同组会被渲染在同一段里 */
  group: string
}

/** 顺序即侧栏顺序。group 只写一次，侧栏按相邻关系自动分段。 */
export const NAV: readonly NavEntry[] = [
  { path: ROUTES.OVERVIEW, label: '系统概览', sub: 'Overview', icon: 'home', group: '系统' },
  {
    path: ROUTES.MONITOR,
    label: '实时监测',
    sub: 'Real-time Monitoring',
    icon: 'activity',
    group: '核心功能',
  },
  {
    path: ROUTES.IDENTIFY,
    label: '病虫害识别',
    sub: 'Pest & Disease ID',
    icon: 'search',
    group: '核心功能',
  },
  {
    path: ROUTES.VISUALIZE,
    label: '数据可视化',
    sub: 'Data Visualization',
    icon: 'bar',
    group: '核心功能',
  },
  { path: ROUTES.ALERT, label: '预警系统', sub: 'Warning System', icon: 'alert', group: '核心功能' },
  {
    path: ROUTES.SPRAY,
    label: '喷洒方案与执行',
    sub: 'Spraying Plan',
    icon: 'droplet',
    group: '核心功能',
  },
  {
    path: ROUTES.EFFECT,
    label: '预期效果与评估',
    sub: 'Expected Effects',
    icon: 'trend',
    group: '核心功能',
  },
]

/** 按相邻 group 折成侧栏分段。模块级算一次。 */
export const NAV_GROUPS: readonly { group: string; items: NavEntry[] }[] = NAV.reduce<
  { group: string; items: NavEntry[] }[]
>((acc, entry) => {
  const tail = acc[acc.length - 1]
  if (tail && tail.group === entry.group) tail.items.push(entry)
  else acc.push({ group: entry.group, items: [entry] })
  return acc
}, [])
