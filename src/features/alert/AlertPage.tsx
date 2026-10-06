import { useState } from 'react'

import { Card } from '@components/ui/Card'
import { Chip } from '@components/ui/Chip'
import { ErrorCard, LoadingCard } from '@components/ui/PageState'
import { StatTile } from '@components/ui/StatTile'
import { StatusBadge } from '@components/ui/StatusBadge'
import { useApi } from '@hooks/useApi'
import { api } from '@lib/api'

import type { Threshold, Warning, WarningLevel } from '@lib/types/api'

/**
 * 预警系统 —— 对照 legacy/index.html 的 `#screen-alert`。
 *
 * ⚠️ 四个 tile 的数字与 legacy 不同，这是**修正**不是回归：
 * 原版 tile 写死 3/5/9/14，而它自己的列表只有 11 条（3/5/3/4）。
 * 现在 tile 由后端现场 COUNT，与下面的表在结构上不可能再打架。
 */

/** tile 的值染色。legacy 是逐个写死的内联色，这里集中一处。 */
const TILE_COLOR: Record<string, string> = {
  critical: 'var(--critical)',
  serious: 'var(--serious)',
  warning: '#a97a00',
  done: 'var(--good)',
}

type Filter = 'all' | WarningLevel | 'undone'

const FILTERS: { key: Filter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'critical', label: '严重' },
  { key: 'serious', label: '较重' },
  { key: 'warning', label: '一般' },
  { key: 'undone', label: '未处理' },
]

/** 级别 → 中文。与原 demo 的 LEVEL_LABEL 一致。 */
const LEVEL_CN: Record<WarningLevel, string> = {
  critical: '严重',
  serious: '较重',
  warning: '一般',
}

export default function AlertPage() {
  const { data, error, reload, loading } = useApi(() => api.alert(), [])
  const [filter, setFilter] = useState<Filter>('all')
  /** 正在提交的预警 id。禁用该行的按钮，防止连点产生重复请求。 */
  const [busy, setBusy] = useState<number | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  if (error) return <ErrorCard message={error} onRetry={reload} />
  if (!data) return <LoadingCard what="预警数据" />

  const rows = data.warnings.filter((w) => {
    if (filter === 'all') return true
    if (filter === 'undone') return w.status === 'undone'
    return w.level === filter
  })

  async function onHandle(w: Warning) {
    setBusy(w.id)
    setActionError(null)
    try {
      await api.handleWarning(w.id)
      // 必须重取：tile 是 COUNT 出来的，本地改状态是改不了 tile 的。
      reload()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <>
      <div className="tiles">
        {data.tiles.map((t) => (
          <StatTile
            key={t.key}
            label={t.label}
            value={t.value}
            unit={t.unit || undefined}
            valueColor={TILE_COLOR[t.key]}
            footer={{ kind: 'status', status: t.status, text: t.note }}
          />
        ))}
      </div>

      {actionError && (
        <div className="banner" style={{ marginTop: 16 }}>
          操作失败：{actionError}
        </div>
      )}

      <div className="grid g-21" style={{ marginTop: 16 }}>
        <Card title="预警列表" tag={loading ? '刷新中…' : undefined}>
          <div style={{ display: 'flex', gap: 8, margin: '10px 0 14px', flexWrap: 'wrap' }}>
            {FILTERS.map((f) => (
              <Chip key={f.key} on={filter === f.key} onClick={() => setFilter(f.key)}>
                {f.label}
              </Chip>
            ))}
          </div>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>预警 ID</th>
                  <th>类型</th>
                  <th>级别</th>
                  <th>位置</th>
                  <th>时间</th>
                  <th>状态</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={7} style={{ textAlign: 'center', color: 'var(--muted)' }}>
                      暂无匹配预警
                    </td>
                  </tr>
                )}
                {rows.map((w) => (
                  <tr key={w.id}>
                    <td className="mono">{w.warningNo}</td>
                    <td>{w.type}</td>
                    <td>
                      <StatusBadge status={w.level}>{LEVEL_CN[w.level]}</StatusBadge>
                    </td>
                    <td>{w.area}</td>
                    <td className="mono">{w.timeText}</td>
                    <td>
                      {w.status === 'done' ? (
                        <StatusBadge status="good">已处理</StatusBadge>
                      ) : (
                        <StatusBadge status="warning">未处理</StatusBadge>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="btn"
                        style={{ padding: '4px 10px', fontSize: 12 }}
                        disabled={w.status === 'done' || busy === w.id}
                        onClick={() => onHandle(w)}
                      >
                        {w.status === 'done' ? '已闭环' : busy === w.id ? '处理中…' : '处理'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="预警阈值设置" hint="达到阈值时系统自动触发预警推送">
          <div className="kv" style={{ gridTemplateColumns: '1fr' }}>
            {data.thresholds.map((t) => (
              <ThresholdRow key={t.key} threshold={t} onError={setActionError} />
            ))}
          </div>
          <div className="banner" style={{ marginTop: 16 }}>
            预警将通过 <b>移动设备推送</b> 与 <b>电子邮件</b> 及时送达农场管理者。
          </div>
        </Card>
      </div>
    </>
  )
}

/**
 * 一个阈值滑块。
 *
 * 拖动时只改本地 state（标签要跟手，不能等网络），**松手才落库** ——
 * 每移动一像素发一次 PATCH 会把后端打满。
 * 键盘用户不会触发 pointerup，所以 keyup 也要提交。
 */
function ThresholdRow({
  threshold,
  onError,
}: {
  threshold: Threshold
  onError: (m: string | null) => void
}) {
  const [value, setValue] = useState(threshold.value)

  async function commit() {
    if (value === threshold.value) return
    try {
      await api.patchThreshold(threshold.key, value)
      onError(null)
    } catch (e) {
      // 服务端拒绝（越界等）→ 回退到服务端的值，不要让界面停在一个
      // 后端并不认可的数字上。
      setValue(threshold.value)
      onError(e instanceof Error ? e.message : String(e))
    }
  }

  // 整数阈值不显示小数位；pH 的 step 是 0.1，要保留一位
  const text = threshold.step < 1 ? value.toFixed(1) : value.toFixed(0)

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between' }}>
        <span>{threshold.label}</span>
        <span>
          {text}
          {threshold.unit ? ` ${threshold.unit}` : ''}
        </span>
      </div>
      <input
        type="range"
        min={threshold.minValue}
        max={threshold.maxValue}
        step={threshold.step}
        value={value}
        aria-label={threshold.label}
        onChange={(e) => setValue(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
      />
    </div>
  )
}
