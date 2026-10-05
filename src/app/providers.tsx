import { RouterProvider } from 'react-router-dom'
import { router } from './router'

/**
 * 应用级的 Provider 层。目前只有路由（主题状态走 zustand，见 stores/themeStore，
 * 不占 Provider 位置）。保留这一层是为了之后接全局的东西时有固定落点 ——
 * 例如 useSSE 的连接生命周期、全局 Toast 容器。届时加在这里，不动 main.tsx。
 */
export function Providers() {
  return <RouterProvider router={router} />
}
