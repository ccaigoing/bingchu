import { useState } from 'react'
import { useLocation } from 'react-router-dom'
import { Icon } from '@components/ui/Icon'
import { useInterval } from '@hooks/useInterval'
import { NAV } from '@/app/routes'
import { useThemeStore } from '@stores/themeStore'

const pad2 = (n: number) => String(n).padStart(2, '0')

function now(): string {
  const d = new Date()
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`
}

/**
 * 顶栏。标题由路由推导（不再需要原版的 `TITLES` 映射表 + setTitle 调用），
 * 时钟是**纯 UI 定时器，刻意留在前端** —— 它没有任何业务含义，
 * 搬到后端只增加一次往返。这与计划书 (d) 节一致：传感器漂移、预警生成
 * 这类有业务含义的节奏才必须进后端。
 */
export function Topbar() {
  const { pathname } = useLocation()
  const [clock, setClock] = useState(now)
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggle)

  useInterval(() => setClock(now()), 1000)

  const entry = NAV.find((n) => n.path === pathname)

  return (
    <header className="topbar">
      <div>
        <span className="title">{entry?.label ?? '未知页面'}</span>
        <span className="sub">{entry?.sub ?? '—'}</span>
      </div>
      <div className="spacer" />
      <span className="pill">
        <span className="dot pulse" />
        系统运行中
      </span>
      <span className="pill">{clock}</span>
      <button
        type="button"
        className="iconbtn"
        title="切换主题"
        onClick={toggleTheme}
        /* 图标表示"点下去会切到哪"：亮色时显示月亮 → 切到暗色。
           与原版 `themeBtn.innerHTML = theme==="light" ? MOON_SVG : SUN_SVG` 一致。 */
      >
        <Icon name={theme === 'light' ? 'moon' : 'sun'} size={16} />
      </button>
    </header>
  )
}
