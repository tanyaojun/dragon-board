// src/services/hotlist/hotlistSentimentApi.ts
// 薄 API client：只做 fetch + 类型化，无兜底计算（口径唯一来源 = QuantBoard 后端）
import type { HotListSentimentDayDoc } from '@/types/hotlistSentiment'

export interface HotlistSentimentSeriesResponse {
  ok: boolean
  degraded?: boolean
  reason?: string
  items: Array<HotListSentimentDayDoc | { tradingDate: string; missing: true; reason: string }>
}

export interface HotlistSentimentMissingDay {
  tradingDate: string
  reason: string | null
}

export interface HotlistSentimentSeriesResult {
  items: HotListSentimentDayDoc[]
  degraded: boolean
  reason: string | null
  missingDays: HotlistSentimentMissingDay[]
}

type HotlistSentimentSeriesEntry = HotlistSentimentSeriesResponse['items'][number]

// missing 条目：后端对窗口内无快照的交易日返回 { tradingDate, missing: true, reason }
function isMissingEntry(item: HotlistSentimentSeriesEntry): item is {
  tradingDate: string
  missing: true
  reason: string
} {
  return (item as { missing?: unknown }).missing === true
}

export async function fetchHotlistSentimentSeries(
  days = 3,
  datasetId = 'dragonboard_live',
): Promise<HotlistSentimentSeriesResult> {
  const params = new URLSearchParams({ dataset_id: datasetId, days: String(days) })
  const response = await fetch(`/api/hotlist-sentiment/series?${params.toString()}`)
  if (!response.ok) {
    return { items: [], degraded: true, reason: `HTTP ${response.status}`, missingDays: [] }
  }
  const body = (await response.json()) as HotlistSentimentSeriesResponse
  if (!body.ok || body.degraded) {
    return { items: [], degraded: true, reason: body.reason || 'degraded', missingDays: [] }
  }
  // 缺失日不吞掉：从被过滤条目收集 tradingDate/reason，供面板展示「窗口缺失 N 日」标注
  const docs: HotListSentimentDayDoc[] = []
  const missingDays: HotlistSentimentMissingDay[] = []
  for (const item of body.items || []) {
    if (isMissingEntry(item)) {
      missingDays.push({ tradingDate: item.tradingDate || '', reason: item.reason ?? null })
    } else {
      docs.push(item)
    }
  }
  return { items: docs, degraded: false, reason: body.reason || null, missingDays }
}

export interface HotlistSentimentSlotsResult {
  items: HotListSentimentDayDoc[]
  /** 槽位所属交易日（缺省请求回落到后端最新交易日） */
  tradingDate: string
  degraded: boolean
  reason: string | null
}

/**
 * 当日槽位情绪序列（GET /api/hotlist-sentiment/slots）：日内 9:30→15:00 逐槽 EOD 级文档，
 * 由采集主链每槽同步写入（analyze → 槽位情绪 → EOD）。与 series（日终值）互补：
 * 回答"今天情绪怎么走到现在"。槽位缺失/降级时透传错误态，不伪造数据。
 */
export async function fetchHotlistSentimentSlots(
  datasetId = 'dragonboard_live',
): Promise<HotlistSentimentSlotsResult> {
  const params = new URLSearchParams({ dataset_id: datasetId })
  const response = await fetch(`/api/hotlist-sentiment/slots?${params.toString()}`)
  if (!response.ok) {
    return { items: [], tradingDate: '', degraded: true, reason: `HTTP ${response.status}` }
  }
  const body = (await response.json()) as {
    ok: boolean
    degraded?: boolean
    reason?: string
    tradingDate?: string
    items?: HotListSentimentDayDoc[]
  }
  if (!body.ok || body.degraded) {
    return {
      items: [],
      tradingDate: body.tradingDate || '',
      degraded: true,
      reason: body.reason || 'degraded',
    }
  }
  return {
    items: body.items || [],
    tradingDate: body.tradingDate || '',
    degraded: false,
    reason: null,
  }
}

// ---------- 涨停池成分股明细（2026-09-25，热榜概览三容器 → 明细面板） ----------

export interface HotlistPoolLimitStockRow {
  code: string
  name: string
  rank: number
  change: number
  boardHeight: number
  nearLimitUp: boolean
  zhaban: boolean
  mainNet: number
  firstLimitUpTime: string
  lastLimitUpTime: string
  statusLabel: string
}

export interface HotlistMarketLimitStockRow {
  code: string
  name: string
  change: number | null
  highDays: string
  boardHeight: number
  firstLimitUpTime: string
  lastLimitUpTime: string
  turnoverRate: number | null
  openNum: number | null
  limitUpType: string
  reasonType: string
}

export interface HotlistYesterdayLimitStockRow {
  code: string
  name: string
  rank: number
  yesterdayChange: number
  boardHeight: number
  matched: boolean
  todayChange: number | null
  todayRank: number
  retained: boolean
  positive: boolean
  weakened: boolean
  failedOrWeak: boolean
}

export type HotlistLimitStockKind = 'pool' | 'market' | 'yesterday'

export interface HotlistLimitStocksResult {
  ok: boolean
  degraded: boolean
  reason: string | null
  tradingDate: string
  prevTradingDate: string
  diagnostics: string[]
  pool: { rows: HotlistPoolLimitStockRow[] }
  market: { rows: HotlistMarketLimitStockRow[]; degraded: boolean; reason: string | null }
  yesterday: { rows: HotlistYesterdayLimitStockRow[] }
}

const EMPTY_LIMIT_STOCKS = (): HotlistLimitStocksResult => ({
  ok: false,
  degraded: true,
  reason: 'not_loaded',
  tradingDate: '',
  prevTradingDate: '',
  diagnostics: [],
  pool: { rows: [] },
  market: { rows: [], degraded: true, reason: 'not_loaded' },
  yesterday: { rows: [] },
})

/** 涨停池成分股明细（GET /api/hotlist-sentiment/limit-stocks）：一次取三份名单，各部分失败结构化标注。 */
export async function fetchHotlistLimitStocks(datasetId = 'dragonboard_live'): Promise<HotlistLimitStocksResult> {
  const params = new URLSearchParams({ dataset_id: datasetId })
  let response: Response
  try {
    response = await fetch(`/api/hotlist-sentiment/limit-stocks?${params.toString()}`)
  } catch (err) {
    return { ...EMPTY_LIMIT_STOCKS(), reason: err instanceof Error ? err.message : 'fetch failed' }
  }
  if (!response.ok) {
    return { ...EMPTY_LIMIT_STOCKS(), reason: `HTTP ${response.status}` }
  }
  const body = (await response.json()) as Partial<HotlistLimitStocksResult>
  return {
    ok: body.ok === true,
    degraded: body.degraded === true,
    reason: body.reason ?? null,
    tradingDate: body.tradingDate || '',
    prevTradingDate: body.prevTradingDate || '',
    diagnostics: body.diagnostics ?? [],
    pool: body.pool ?? { rows: [] },
    market: body.market ?? { rows: [], degraded: true, reason: 'not_loaded' },
    yesterday: body.yesterday ?? { rows: [] },
  }
}
