import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import { AppLayout } from '@components/layout/AppLayout'
import { ScreenFallback } from '@components/layout/ScreenFallback'
import { ROUTES } from './routes'

/**
 * 7 个屏各自 lazy 分包。原来的单文件是"一次性渲染所有 7 屏、再用
 * `.screen.active` 藏起 6 个"，所有 ECharts 实例在启动时就全建好了；
 * 现在按路由挂载/卸载，切屏天然销毁图表（配合 useECharts 的 dispose）。
 */
const OverviewPage = lazy(() => import('@features/overview/OverviewPage'))
const MonitorPage = lazy(() => import('@features/monitor/MonitorPage'))
const IdentifyPage = lazy(() => import('@features/identify/IdentifyPage'))
const VisualizePage = lazy(() => import('@features/visualize/VisualizePage'))
const AlertPage = lazy(() => import('@features/alert/AlertPage'))
const SprayPage = lazy(() => import('@features/spray/SprayPage'))
const EffectPage = lazy(() => import('@features/effect/EffectPage'))

function withFallback(node: ReactNode) {
  return <Suspense fallback={<ScreenFallback />}>{node}</Suspense>
}

function NotFoundPage() {
  return (
    <div className="card">
      <h3>页面不存在</h3>
      <p className="hint">请从左侧导航进入系统功能页。</p>
    </div>
  )
}

export const router = createBrowserRouter([
  {
    path: ROUTES.OVERVIEW,
    element: <AppLayout />,
    children: [
      { index: true, element: withFallback(<OverviewPage />) },
      { path: ROUTES.MONITOR, element: withFallback(<MonitorPage />) },
      { path: ROUTES.IDENTIFY, element: withFallback(<IdentifyPage />) },
      { path: ROUTES.VISUALIZE, element: withFallback(<VisualizePage />) },
      { path: ROUTES.ALERT, element: withFallback(<AlertPage />) },
      { path: ROUTES.SPRAY, element: withFallback(<SprayPage />) },
      { path: ROUTES.EFFECT, element: withFallback(<EffectPage />) },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
