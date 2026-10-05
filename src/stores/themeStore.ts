import { create } from 'zustand'
import type { ThemeName } from '@lib/types/theme'

interface ThemeState {
  theme: ThemeName
  setTheme: (theme: ThemeName) => void
  toggle: () => void
}

/**
 * 主题写在 <html data-theme>，与 legacy/index.html 的做法一致 ——
 * tokens.css 里 `:root` 是亮色默认值，`[data-theme='dark']` 覆盖它。
 * 亮色时也显式写 data-theme="light"（而非删属性），这样 CSS 与
 * ECharts 两边读到的状态永远一致，不会出现"属性没写但看着是亮色"的歧义。
 */
function apply(theme: ThemeName): void {
  document.documentElement.setAttribute('data-theme', theme)
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  // 初值固定 light。不做 localStorage 持久化：原演示页也不持久化，
  // 且答辩时每次刷新都从亮色开始，讲稿节奏稳定。
  theme: 'light',
  setTheme: (theme) => {
    apply(theme)
    set({ theme })
  },
  toggle: () => {
    get().setTheme(get().theme === 'light' ? 'dark' : 'light')
  },
}))

// 模块加载即应用一次，避免首帧闪亮色再跳暗色。
// （将来若要读 localStorage 恢复偏好，恢复逻辑也放这里。）
apply(useThemeStore.getState().theme)
