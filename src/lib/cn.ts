import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * 合并 className。clsx 处理条件表达式，tailwind-merge 消解 Tailwind 冲突
 * （后者写 `p-2 p-4` 只留 `p-4`）。
 *
 * ⚠️ 注意 tailwind-merge 不认识本项目 components.css 里的自定义类（`.card`、
 * `.nav-item`、`.tile` …）。它只认识 Tailwind 工具类，所以 `.card` 会原样保留 ——
 * 这正是我们要的。但它**不会**帮我们解决 `className="card"` 撞上 `className="p-4"`
 * 的情况：按 globals.css 的说明，未分层的 components.css 永远压过 utilities 层，
 * 真撞上了是 `card` 赢。详见 styles/globals.css 顶部注释。
 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
