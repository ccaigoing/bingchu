/**
 * 内联 SVG 图标 sprite —— 从 legacy/index.html 原样迁移。
 *
 * ⚠️ **必须内联在文档里，不要改成外链 `/icons.svg#id`。**
 * 原版把 <symbol> 内联在 body，`<use href="#i-home">` 是同文档引用。
 * 外链 `use` 会遇到跨域与缓存问题（尤其经 Vite dev server 与生产
 * 静态托管时行为不一致）。整个应用只在 AppLayout 里渲染这一个实例。
 *
 * 18 个 symbol 全部保留，包括当前界面没直接用的
 * （layers / map / monitor / wifi / cpu）—— 它们是架构图与后续屏
 * 要用的，删掉会在移植后面几屏时才发现缺图。
 */
export function IconSprite() {
  return (
    <svg xmlns="http://www.w3.org/2000/svg" style={{ display: 'none' }} aria-hidden="true">
      <symbol id="i-home" viewBox="0 0 24 24">
        <path d="M3 9.5 12 3l9 6.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z" />
      </symbol>
      <symbol id="i-activity" viewBox="0 0 24 24">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
      </symbol>
      <symbol id="i-search" viewBox="0 0 24 24">
        <circle cx="11" cy="11" r="7" />
        <path d="m21 21-4.3-4.3" />
      </symbol>
      <symbol id="i-bar" viewBox="0 0 24 24">
        <path d="M18 20V10" />
        <path d="M12 20V4" />
        <path d="M6 20v-6" />
      </symbol>
      <symbol id="i-alert" viewBox="0 0 24 24">
        <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
        <path d="M12 9v4" />
        <path d="M12 17h.01" />
      </symbol>
      <symbol id="i-droplet" viewBox="0 0 24 24">
        <path d="M12 2.7 6.3 8.4a8 8 0 1 0 11.4 0z" />
      </symbol>
      <symbol id="i-layers" viewBox="0 0 24 24">
        <path d="m12 2 10 5-10 5L2 7z" />
        <path d="m2 12 10 5 10-5" />
        <path d="M2 17l10 5 10-5" />
      </symbol>
      <symbol id="i-map" viewBox="0 0 24 24">
        <path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4z" />
        <path d="M8 2v16" />
        <path d="M16 6v16" />
      </symbol>
      <symbol id="i-trend" viewBox="0 0 24 24">
        <path d="M23 6l-9.5 9.5-5-5L1 18" />
        <path d="M17 6h6v6" />
      </symbol>
      <symbol id="i-flask" viewBox="0 0 24 24">
        <path d="M10 2v6L4.5 20a2 2 0 0 0 1.8 3h11.4a2 2 0 0 0 1.8-3L14 8V2" />
        <path d="M8.5 2h7" />
        <path d="M7 16h10" />
      </symbol>
      <symbol id="i-send" viewBox="0 0 24 24">
        <path d="M22 2 11 13" />
        <path d="M22 2 15 22l-4-9-9-4z" />
      </symbol>
      <symbol id="i-refresh" viewBox="0 0 24 24">
        <path d="M23 4v6h-6" />
        <path d="M1 20v-6h6" />
        <path d="M3.5 9a9 9 0 0 1 14.8-3.4L23 10" />
        <path d="M1 14l4.7 4.4A9 9 0 0 0 20.5 15" />
      </symbol>
      <symbol id="i-monitor" viewBox="0 0 24 24">
        <rect x="2" y="3" width="20" height="14" rx="2" />
        <path d="M8 21h8" />
        <path d="M12 17v4" />
      </symbol>
      <symbol id="i-wifi" viewBox="0 0 24 24">
        <path d="M5 12.5a10 10 0 0 1 14 0" />
        <path d="M1.5 8.5a16 16 0 0 1 21 0" />
        <path d="M8.5 16a5 5 0 0 1 7 0" />
        <path d="M12 20h.01" />
      </symbol>
      <symbol id="i-cpu" viewBox="0 0 24 24">
        <rect x="5" y="5" width="14" height="14" rx="2" />
        <rect x="9.5" y="9.5" width="5" height="5" />
        <path d="M9 2v3" />
        <path d="M15 2v3" />
        <path d="M9 19v3" />
        <path d="M15 19v3" />
        <path d="M2 9h3" />
        <path d="M2 15h3" />
        <path d="M19 9h3" />
        <path d="M19 15h3" />
      </symbol>
      <symbol id="i-leaf" viewBox="0 0 24 24">
        <path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.5 19 2c1 2 2 4.2 2 8 0 5.5-4.8 10-10 10z" />
        <path d="M2 21c0-3 1.9-5.4 5.1-6C9.5 14.5 12 13 13 12" />
      </symbol>
      <symbol id="i-sun" viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2" />
        <path d="M12 20v2" />
        <path d="M4.9 4.9l1.4 1.4" />
        <path d="M17.7 17.7l1.4 1.4" />
        <path d="M2 12h2" />
        <path d="M20 12h2" />
        <path d="M4.9 19.1l1.4-1.4" />
        <path d="M17.7 6.3l1.4-1.4" />
      </symbol>
      <symbol id="i-moon" viewBox="0 0 24 24">
        <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9z" />
      </symbol>
    </svg>
  )
}

/** sprite 里已定义的图标名。给 Icon 组件的 name 用，写错在编译期就能发现。 */
export type IconName =
  | 'home'
  | 'activity'
  | 'search'
  | 'bar'
  | 'alert'
  | 'droplet'
  | 'layers'
  | 'map'
  | 'trend'
  | 'flask'
  | 'send'
  | 'refresh'
  | 'monitor'
  | 'wifi'
  | 'cpu'
  | 'leaf'
  | 'sun'
  | 'moon'
