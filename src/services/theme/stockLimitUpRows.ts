// 题材成分股涨停池字段合入与排序比较器。
// 数据源是 DataLayer 内的涨停池扩展数据（/api/limitup/10jqka 主池 + /api/limitup/ths/pools 细分池）。
// fail-visible 约定：非涨停股/未覆盖股保持字段缺失（UI 显示 '--'），不伪造 0 或空文本；
// 真实零值（封单 0、开板 0）原样保留。
import type { LimitUpExtData } from '@/types'

export type ThemeLimitUpFields = Pick<
  LimitUpExtData,
  'lianbanStr' | 'boardHeight' | 'firstZtTime' | 'lastZtTime' | 'fengdan' | 'openNum' | 'reason'
> & {
  // 派生字段：题材内按 连板数降序 + 首次涨停时间升序 编位（1=龙一），非涨停股不编号
  leaderRank?: number
  // 关联原因（题材映射静态文本，主营业务口径）：从静态行 reason 键转移到此，
  // reason 键只承载涨停原因（同花顺涨停池 reason_type，仅涨停股有值），两字段语义不同不得混用
  relatedReason?: string
}

export type ThemeStockWithLimitUp<T> = T & ThemeLimitUpFields

// 从涨停池 ext 合入的键（relatedReason 是静态文本转移的派生字段、leaderRank 是编位派生字段，不从 ext 合入）
const LIMIT_UP_FIELD_KEYS: Array<
  Exclude<keyof ThemeLimitUpFields, 'leaderRank' | 'relatedReason'>
> = [
  'lianbanStr',
  'boardHeight',
  'firstZtTime',
  'lastZtTime',
  'fengdan',
  'openNum',
  'reason',
]

// 排序语义分组：涨停类字段缺失时永远排在最后（不看升降序方向）；
// 其余数值字段沿用组件原有 `|| 0` 行为；code/name 走字符串比较。
const MISSING_LAST_SORT_FIELDS = new Set(['leader', 'lianban', 'firstZtTime', 'lastZtTime', 'fengdan'])
// rank 语义字段：数值小=强（1=龙一），desc（默认）时强在前，与普通数值字段方向相反
const RANK_ASC_SORT_FIELDS = new Set(['leader'])
const STRING_SORT_FIELDS = new Set(['code', 'name'])

export function enrichStocksWithLimitUp<T extends { code: string }>(
  stocks: T[],
  getLimitUpData: (code: string) => LimitUpExtData | undefined,
): ThemeStockWithLimitUp<T>[] {
  const merged = stocks.map((stock) => {
    // 统一浅拷贝：leaderRank 编位只写副本，绝不变异输入行
    const row = { ...stock } as ThemeStockWithLimitUp<T> & Record<string, unknown>
    // 两字段口径（2026-09-02）：静态行的 reason 是题材映射关联原因（主营业务文本），
    // 转移到 relatedReason 保存；reason 键清空，只留给涨停原因（ext.reason，仅涨停股有值）
    const relatedReason = (stock as { reason?: string }).reason
    if (relatedReason) row.relatedReason = relatedReason
    delete row.reason
    const ext = getLimitUpData(stock.code)
    if (!ext) return row
    LIMIT_UP_FIELD_KEYS.forEach((key) => {
      const value = ext[key]
      if (value !== undefined && value !== null && value !== '') {
        ;(row as Record<string, unknown>)[key] = value
      }
    })
    return row
  })

  // 龙一/龙二/……：题材内按 连板数降序 + 首次涨停时间升序 编位；
  // 并列按代码稳定排序；未涨停（无首次涨停时间）不编号
  const ranked = merged
    .map((row, index) => ({
      row: row as Record<string, unknown>,
      index,
      boardHeight: toFinite((row as { boardHeight?: number }).boardHeight) ?? 0,
      seconds: timeToSeconds((row as { firstZtTime?: string }).firstZtTime),
    }))
    .filter(
      (entry): entry is {
        row: Record<string, unknown>
        index: number
        boardHeight: number
        seconds: number
      } => entry.seconds !== null,
    )
    .sort(
      (a, b) =>
        b.boardHeight - a.boardHeight ||
        a.seconds - b.seconds ||
        String(a.row.code).localeCompare(String(b.row.code)) ||
        a.index - b.index,
    )
  ranked.forEach((entry, order) => {
    entry.row.leaderRank = order + 1
  })

  return merged
}

export function timeToSeconds(value: string | undefined | null): number | null {
  const match = String(value || '')
    .trim()
    .match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return null
  return Number(match[1]) * 3600 + Number(match[2]) * 60 + Number(match[3] || 0)
}

function toFinite(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function numericValue(row: Record<string, unknown>, sortBy: string): number | null {
  switch (sortBy) {
    case 'leader':
      return toFinite(row.leaderRank)
    case 'lianban':
      return toFinite(row.boardHeight)
    case 'firstZtTime':
      return timeToSeconds(row.firstZtTime as string | undefined)
    case 'lastZtTime':
      return timeToSeconds(row.lastZtTime as string | undefined)
    case 'fengdan':
      return toFinite(row.fengdan)
    default:
      return toFinite(row[sortBy])
  }
}

export function compareThemeStockRows(
  a: Record<string, unknown>,
  b: Record<string, unknown>,
  sortBy: string,
  sortDesc: boolean,
): number {
  if (STRING_SORT_FIELDS.has(sortBy)) {
    const cmp = String(a[sortBy] ?? '').localeCompare(String(b[sortBy] ?? ''))
    return sortDesc ? -cmp : cmp
  }

  const aVal = numericValue(a, sortBy)
  const bVal = numericValue(b, sortBy)
  if (MISSING_LAST_SORT_FIELDS.has(sortBy)) {
    if (aVal === null && bVal === null) return 0
    if (aVal === null) return 1
    if (bVal === null) return -1
  }
  const av = aVal ?? 0
  const bv = bVal ?? 0
  if (RANK_ASC_SORT_FIELDS.has(sortBy)) {
    // rank 小=强（1=龙一）：desc（默认）龙一在前，asc 反转
    return sortDesc ? av - bv : bv - av
  }
  return sortDesc ? bv - av : av - bv
}

export function formatLianbanText(
  row: Pick<ThemeLimitUpFields, 'lianbanStr' | 'boardHeight'> | undefined | null,
): string {
  if (!row) return '--'
  if (row.lianbanStr) return row.lianbanStr
  if (row.boardHeight === 1) return '首板'
  if (row.boardHeight && row.boardHeight > 1) return `${row.boardHeight}板`
  return '--'
}

export function formatFengdanYi(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  return `${(value / 1e8).toFixed(2)}亿`
}

export function formatOpenNum(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  return String(value)
}

const LEADER_RANK_ZH = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十'] as const

export function formatLeaderRank(value: number | null | undefined): string {
  if (value === null || value === undefined) return '--'
  if (value >= 1 && value <= LEADER_RANK_ZH.length) return `龙${LEADER_RANK_ZH[value - 1]}`
  return `龙${value}`
}
