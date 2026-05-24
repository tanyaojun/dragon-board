import type { MergedStock } from '@/types/data-layer'
import type { DragonReviewResult } from '../dragon/types'

export type HotStockEventDirection = 'up' | 'down' | 'neutral'
export type HotStockEventSeverity = 'normal' | 'important'
export type HotStockEventCategory = 'stock' | 'sector'

export const OPENING_WEAK_TO_STRONG_EVENT_TYPE = 12001

export interface TdxBlockFileSummary {
  name: string
  path?: string
  stockCount: number
  issueCount: number
  selected?: boolean
}

export type HotStockAbnormalEventType =
  | 10001
  | 10005
  | 10003
  | 10007
  | 10002
  | 10006
  | 10004
  | 10008
  | 10012
  | 10014
  | 10009
  | 10010
  | 12001
  | 11000
  | 11001

export interface HotStockAbnormalEvent {
  category: HotStockEventCategory
  id: string
  eventType: HotStockAbnormalEventType
  type: HotStockAbnormalEventType
  typeName: string
  direction: HotStockEventDirection
  severity: HotStockEventSeverity
  timestamp: number
  code: string
  name: string
  changePct: number | null
  price: number | null
  relatedPlates: string[]
  sectorName: string
  matchedHotStock: boolean
  matchedCandidate: boolean
  raw: unknown
}

export interface HotStockEventFetcher {
  fetchEvents: () => Promise<HotStockAbnormalEvent[]>
}

export interface HotStockEventDataLayer {
  getStocks: () => MergedStock[]
  getDragonReview: () => (DragonReviewResult & { candidates?: Array<{ code?: string }> }) | null
}

export interface HotStockEventRefreshResult {
  ok: boolean
  added: number
  events: HotStockAbnormalEvent[]
  hotStockEvents: HotStockAbnormalEvent[]
  otherStockEvents: HotStockAbnormalEvent[]
  sectorEvents: HotStockAbnormalEvent[]
  watchedCodes: string[]
  tdxBlockCodes: string[]
  tdxBlockFiles: TdxBlockFileSummary[]
  selectedTdxBlockFiles: string[]
  error?: string
}

export interface HotStockEventMonitorState {
  events: HotStockAbnormalEvent[]
  hotStockEvents: HotStockAbnormalEvent[]
  otherStockEvents: HotStockAbnormalEvent[]
  sectorEvents: HotStockAbnormalEvent[]
  latestAdded: HotStockAbnormalEvent[]
  latestHotStockAdded: HotStockAbnormalEvent[]
  watchedCodes: string[]
  tdxBlockCodes: string[]
  tdxBlockFiles: TdxBlockFileSummary[]
  selectedTdxBlockFiles: string[]
  lastUpdate: number | null
  loading: boolean
  running: boolean
  error: string | null
}

export function normalizeHotStockCode(code: unknown): string {
  const raw = String(code || '').trim().toUpperCase()
  if (!raw) return ''

  const withoutSuffix = raw.replace(/\.(?:SZ|SS|SH|BJ)$/i, '')
  const withoutPrefix = withoutSuffix.replace(/^(?:SZ|SS|SH|BJ)/i, '')
  if (/^\d{6}$/.test(withoutPrefix)) return withoutPrefix

  const digits = withoutPrefix.replace(/\D/g, '')
  return /^\d{6}$/.test(digits) ? digits : ''
}
