// src/services/rankTrend/jumpHistory.ts
// 排名跳动历史视图（2026-09-16 P2-1）：把 analyze 产物的 jump 字段组装为面板可渲染的
// 摘要 + 事件列表。事件为最近 N 次排名跳动明细（index=排名序列位置，direction=surge/collapse，
// magnitude=幅度）。无事件（event='none' / events 空 / 缺字段）返回 null，区块整段隐藏
// （fail-visible：无跳动历史 ≠ 0 次跳动被抹平，是不存在该数据）。
export interface JumpHistoryItem {
  key: string
  /** direction === 'surge'；'collapse' 为下坠；其它值视为未知方向（中性、无符号） */
  isSurge: boolean
  /** direction === 'collapse' */
  isCollapse: boolean
  label: string
  magnitudeText: string
}

export interface JumpHistoryView {
  eventCount: number
  surgeCount: number
  collapseCount: number
  magnitudeText: string
  directionText: string
  confirmed: boolean
  items: JumpHistoryItem[]
}

interface JumpEventLike {
  index?: number
  direction?: string
  magnitude?: number
}

interface JumpLike {
  event?: string
  direction?: string
  magnitude?: number
  eventCount?: number
  surgeCount?: number
  collapseCount?: number
  confirmed?: boolean
  events?: JumpEventLike[]
}

function directionText(direction?: string): string {
  if (direction === 'buy') return '买入'
  if (direction === 'sell') return '卖出'
  return '持有'
}

function magnitudeText(value: number | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`
}

export function buildJumpHistoryView(jump: JumpLike | null | undefined): JumpHistoryView | null {
  if (!jump || jump.event !== 'jump') return null
  const events = Array.isArray(jump.events) ? jump.events : []
  if (!events.length) return null
  return {
    eventCount: Number(jump.eventCount ?? 0),
    surgeCount: Number(jump.surgeCount ?? 0),
    collapseCount: Number(jump.collapseCount ?? 0),
    magnitudeText: magnitudeText(jump.magnitude),
    directionText: directionText(jump.direction),
    confirmed: jump.confirmed === true,
    items: events.map((event) => {
      const isSurge = event.direction === 'surge'
      const isCollapse = event.direction === 'collapse'
      const index = event.index ?? 0
      // magnitude 存正值，符号由 direction 表达（surge=+ / collapse=-）；
      // 未知方向（如部分链路出现 'hold'）fail-visible：中性无符号，不猜测涨跌
      const magnitude = typeof event.magnitude === 'number' ? Math.abs(event.magnitude) : undefined
      const hasKnownDirection = isSurge || isCollapse
      const signed =
        magnitude === undefined
          ? undefined
          : hasKnownDirection
            ? isSurge
              ? magnitude
              : -magnitude
            : magnitude
      return {
        key: `e${index}`,
        isSurge,
        isCollapse,
        label: `#${index}`,
        magnitudeText: hasKnownDirection || signed === undefined ? magnitudeText(signed) : `${signed.toFixed(1)}%`,
      }
    }),
  }
}
