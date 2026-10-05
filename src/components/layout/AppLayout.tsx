import { Outlet } from 'react-router-dom'
import { IconSprite } from './IconSprite'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

/**
 * 应用外壳。对应 legacy/index.html 的 body 结构：
 *   body(display:flex) > aside.sidebar + div.main > header.topbar + main.content
 *
 * 两处对应关系：
 * - 原 `body{display:flex;overflow:hidden}` 移到了 `.app`（见 components.css 说明）
 * - `<IconSprite/>` 必须在这里渲染一次：sprite 里的 <symbol> 是
 *   `<use href="#i-xxx">` 的**同文档**目标，放这里保证全部路由页面都能引用到。
 */
export function AppLayout() {
  return (
    <div className="app">
      <IconSprite />
      <Sidebar />
      <div className="main">
        <Topbar />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
