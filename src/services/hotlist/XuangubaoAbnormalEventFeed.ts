import {
  type HotStockAbnormalEvent,
  type HotStockAbnormalEventType,
  type HotStockEventDirection,
  type HotStockEventSeverity,
  normalizeHotStockCode,
} from './hotStockEventTypes'

export const XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES: HotStockAbnormalEventType[] = [
  10001,
  10005,
  10003,
  10007,
  10002,
  10006,
  10004,
  10008,
  10012,
  10014,
  10009,
  10010,
]

export const XUANGUBAO_SECTOR_ABNORMAL_EVENT_TYPES: HotStockAbnormalEventType[] = [
  11000,
  11001,
]

const STOCK_EVENT_TYPE_SET = new Set<number>(XUANGUBAO_STOCK_ABNORMAL_EVENT_TYPES)
const SECTOR_EVENT_TYPE_SET = new Set<number>(XUANGUBAO_SECTOR_ABNORMAL_EVENT_TYPES)
const DOWN_EVENT_TYPES = new Set<number>([10002, 10006, 10004, 10008, 10010])
const SECTOR_UP_EVENT_TYPES = new Set<number>([11000])
const SECTOR_DOWN_EVENT_TYPES = new Set<number>([11001])
const DEFAULT_ENDPOINT = '/api/xuangubao/events'

const EVENT_TYPE_NAMES: Record<number, string> = {
  10001: '封涨停板',
  10005: '逼近涨停',
  10003: '打开涨停板',
  10007: '即将打开涨停',
  10002: '封跌停板',
  10006: '逼近跌停',
  10004: '打开跌停板',
  10008: '即将打开跌停',
  10012: '新股开板',
  10014: '新股开板回封',
  10009: '大幅拉升',
  10010: '快速跳水',
  11000: '板块拉升',
  11001: '板块跳水',
}

type Fetcher = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>

export interface XuangubaoAbnormalEventFeedOptions {
  endpoint?: string
  fetcher?: Fetcher
}

function toNumber(value: unknown): number | null {
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function toRatio(value: unknown): number | null {
  const number = toNumber(value)
  if (number === null) return null
  const ratio = Math.abs(number) > 1 ? number / 100 : number
  return Math.round(ratio * 1_000_000) / 1_000_000
}

function toTimestamp(value: unknown): number {
  if (typeof value === 'number') return value < 1_000_000_000_000 ? value * 1000 : value
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value)
    if (Number.isFinite(numeric)) return numeric < 1_000_000_000_000 ? numeric * 1000 : numeric
    const parsed = Date.parse(value)
    return Number.isFinite(parsed) ? parsed : Date.now()
  }
  return Date.now()
}

function getFirst(row: any, keys: string[]): unknown {
  for (const key of keys) {
    if (row?.[key] !== undefined && row[key] !== null) return row[key]
  }
  return undefined
}

function getRows(payload: any): any[] {
  const source = payload?.data ?? payload
  const nestedRows = [
    ...toArray(source?.stock_abnormal_event_data),
    ...toArray(source?.plate_abnormal_event_data),
    ...toArray(source?.stockAbnormalEventData),
    ...toArray(source?.plateAbnormalEventData),
  ]
  if (nestedRows.length) return nestedRows
  if (Array.isArray(source?.events)) return source.events
  if (Array.isArray(source)) return source
  return []
}

function toArray(value: unknown): any[] {
  return Array.isArray(value) ? value : []
}

function isNonEmptyRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value) && Object.keys(value).length > 0
}

function normalizeEventRow(row: any): any {
  const stockNested = row?.stock_abnormal_event_data || row?.stockAbnormalEventData
  const sectorNested = row?.plate_abnormal_event_data || row?.plateAbnormalEventData
  const rowType = Number(row?.event_type ?? row?.eventType ?? row?.type)
  const nested = SECTOR_EVENT_TYPE_SET.has(rowType) && isNonEmptyRecord(sectorNested)
    ? sectorNested
    : stockNested
  const source = nested || sectorNested
  if (!source || typeof source !== 'object') return row

  return {
    ...source,
    id: row.id ?? source.id,
    event_id: row.event_id ?? source.event_id,
    event_type: row.event_type ?? source.event_type,
    event_type_name: row.event_type_name ?? source.event_type_name,
    event_timestamp: row.event_timestamp ?? source.event_timestamp,
    created_at: row.created_at ?? source.created_at,
    timestamp: row.timestamp ?? source.timestamp,
    raw_event: row,
  }
}

function resolveDirection(type: number, changePct: number | null): HotStockEventDirection {
  if (DOWN_EVENT_TYPES.has(type)) return 'down'
  if (SECTOR_UP_EVENT_TYPES.has(type)) return 'up'
  if (SECTOR_DOWN_EVENT_TYPES.has(type)) return 'down'
  if (changePct !== null && changePct < 0) return 'down'
  if (changePct !== null && changePct > 0) return 'up'
  return 'neutral'
}

function normalizeSectorName(row: any): string {
  return String(getFirst(row, [
    'plate_name',
    'plateName',
    'sector_name',
    'sectorName',
    'name',
    'title',
    'stock_name',
    'stockName',
    'stock_code',
    'code',
  ]) || '').trim()
}

function resolveSeverity(type: number): HotStockEventSeverity {
  return 'normal'
}

function normalizeRelatedPlates(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  const names: string[] = []
  for (const item of value) {
    const name = typeof item === 'string'
      ? item
      : String((item as any)?.plate_name || (item as any)?.name || (item as any)?.plateName || '').trim()
    if (name) names.push(name)
  }
  return [...new Set(names)]
}

export function parseXuangubaoAbnormalEvents(payload: unknown): HotStockAbnormalEvent[] {
  const events: HotStockAbnormalEvent[] = []

  for (const sourceRow of getRows(payload)) {
    const row = normalizeEventRow(sourceRow)
    const type = Number(getFirst(row, ['event_type', 'type', 'eventType']))
    if (!STOCK_EVENT_TYPE_SET.has(type) && !SECTOR_EVENT_TYPE_SET.has(type)) continue

    const changePct = toRatio(getFirst(row, ['change_percent', 'change_pct', 'changePct', 'change', 'pcp']))
    const price = toNumber(getFirst(row, ['price', 'current_price', 'currentPrice', 'last', 'close']))
    const timestamp = toTimestamp(getFirst(row, ['event_timestamp', 'created_at', 'timestamp', 'time', 'createdAt']))
    const isSector = SECTOR_EVENT_TYPE_SET.has(type)
    const code = isSector ? '' : normalizeHotStockCode(getFirst(row, ['stock_code', 'code', 'symbol', 'stockCode']))
    if (!isSector && !code) continue
    const sectorName = isSector ? normalizeSectorName(row) : ''
    const identity = isSector ? sectorName || 'sector' : code
    const id = String(getFirst(row, ['id', 'event_id', 'eventId']) || `${type}-${identity}-${timestamp}`)

    events.push({
      category: isSector ? 'sector' : 'stock',
      id,
      eventType: type as HotStockAbnormalEventType,
      type: type as HotStockAbnormalEventType,
      typeName: String(getFirst(row, ['event_type_name', 'type_name', 'typeName', 'title']) || EVENT_TYPE_NAMES[type] || ''),
      direction: resolveDirection(type, changePct),
      severity: resolveSeverity(type),
      timestamp,
      code,
      name: isSector ? sectorName : String(getFirst(row, ['stock_name', 'name', 'stockName']) || ''),
      changePct,
      price,
      relatedPlates: normalizeRelatedPlates(getFirst(row, ['related_plates', 'relatedPlates', 'plates'])),
      sectorName,
      matchedHotStock: false,
      matchedCandidate: false,
      raw: sourceRow,
    })
  }

  return events
}

export class XuangubaoAbnormalEventFeed {
  private readonly endpoint: string
  private readonly fetcher: Fetcher

  constructor(options: XuangubaoAbnormalEventFeedOptions = {}) {
    this.endpoint = options.endpoint || DEFAULT_ENDPOINT
    this.fetcher = options.fetcher || globalThis.fetch.bind(globalThis)
  }

  async fetchEvents(): Promise<HotStockAbnormalEvent[]> {
    const response = await this.fetcher(this.endpoint)
    if (!response.ok) throw new Error(`xuangubao events request failed: ${response.status}`)

    const payload = await response.json()
    if (payload?.ok === false || payload?.degraded === true) {
      throw new Error(
        payload?.message || payload?.errorCode || 'xuangubao events degraded',
      )
    }

    return parseXuangubaoAbnormalEvents(payload)
  }
}
