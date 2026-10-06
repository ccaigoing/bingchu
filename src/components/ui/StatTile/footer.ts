import type { KpiTile } from '@lib/types/api'
import type { TileFooter } from './StatTile'

/**
 * KpiTile（后端存的死数据）→ 概览 / 效果页的 delta 尾巴。
 *
 * 单独一个文件而不是塞进 StatTile.tsx：那个文件只导出组件才能保住
 * React Fast Refresh（改了组件文件要能热更新而不整页刷新）。
 */
export function kpiFooter(t: KpiTile): TileFooter {
  return { kind: 'delta', tone: t.tone, text: t.note }
}
