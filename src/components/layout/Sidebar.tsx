import { NavLink } from 'react-router-dom'
import { Icon } from '@components/ui/Icon'
import { NAV_GROUPS, ROUTES } from '@/app/routes'
import { cn } from '@lib/cn'

/**
 * 侧栏。原版是 7 个 `<button data-screen>` + 手写 classList.toggle('active')，
 * 这里换成 NavLink —— `.nav-item.active` 的样式类名不变，但"谁高亮"交给路由。
 *
 * `end` 只给首页：NavLink 默认前缀匹配，`/` 会匹配上所有路由，
 * 导致"系统概览"在任何页面都高亮。
 */
export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="logo">
          <div className="mark">
            <Icon name="leaf" size={20} />
          </div>
          <div>
            <h1>“机”到病除</h1>
            <p>AI 病虫害诊断系统</p>
          </div>
        </div>
      </div>

      <nav className="nav">
        {NAV_GROUPS.map(({ group, items }) => (
          <div key={group}>
            <div className="grp">{group}</div>
            {items.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === ROUTES.OVERVIEW}
                className={({ isActive }) => cn('nav-item', isActive && 'active')}
              >
                <span className="ic">
                  <Icon name={item.icon} size={18} />
                </span>
                {item.label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>

      <div className="foot">乡村振兴 · 农业农村现代化赛道</div>
    </aside>
  )
}
