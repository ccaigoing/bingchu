import type { IconName } from '@components/layout/IconSprite'

interface IconProps {
  name: IconName
  size?: number
  className?: string
}

/**
 * 图标。`<use href="#i-xxx">` 是**同文档引用**，指向 <IconSprite/> 内联的
 * <symbol>。因此 IconSprite 必须在同一棵 DOM 里渲染一次（AppLayout 里做了）。
 *
 * 不要改成外链 `/icons.svg#i-xxx` —— 外链 use 有跨域与缓存问题，
 * 且 sprite 里 symbol 的样式（stroke: currentColor）要靠同文档继承。
 *
 * 类名默认 `ico`：components.css 里定义了 fill:none / stroke:currentColor /
 * stroke-width:1.6 等，与原演示页的 <svg class="ico"> 完全一致。传 className
 * 可覆盖（例如 `<Icon name="leaf" size={20} className="ico"/>` 与默认等价）。
 */
export function Icon({ name, size = 18, className = 'ico' }: IconProps) {
  return (
    <svg className={className} viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
      <use href={`#i-${name}`} />
    </svg>
  )
}
