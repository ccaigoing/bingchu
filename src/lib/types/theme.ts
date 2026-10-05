/**
 * 主题名。放在 lib/types 而不是 chartTheme 或 themeStore 里，
 * 是因为两边都要用：themeStore 管状态，chartTheme 按主题选色板。
 * 若定义在其中一侧，另一侧就得反向 import（stores → components 或反之），
 * 依赖方向会变得莫名其妙。所以提到中立位置，两边都只依赖它。
 */
export type ThemeName = 'light' | 'dark'
