import { apiService } from '../apiService'
import { mapThsLimitUpPools, type LimitUpPoolStock, type LimitUpPoolType } from '../dataLoader/LimitUpFeed'
import {
  type HotStockAbnormalEvent,
  type HotStockAbnormalEventType,
  type HotStockEventSeverity,
  normalizeHotStockCode,
} from './hotStockEventTypes'

type ThsLimitUpEventApi = {
  getThsLimitUpPools: () => Promise<any>
}

export interface ThsLimitUpEventFeedOptions {
  api?: ThsLimitUpEventApi
  now?: () => number
}

const LIMIT_UP_POOL_TYPES = new Set<LimitUpPoolType>(['one', 'two', 'three', 'four', 'high'])

function resolveEventType(poolType: LimitUpPoolType): HotStockAbnormalEventType | null {
  if (LIMIT_UP_POOL_TYPES.has(poolType)) return 10001
  if (poolType === 'failed') return 10003
  if (poolType === 'rushing') return 10005
  return null
}

function resolveEventName(type: HotStockAbnormalEventType): string {
  if (type === 10001) return '封涨停板'
  if (type === 10003) return '打开涨停板'
  if (type === 10005) return '逼近涨停'
  return ''
}

function resolveSeverity(type: HotStockAbnormalEventType): HotStockEventSeverity {
  return type === 10001 ? 'important' : 'normal'
}

function toRatio(value: unknown): number | null {
  const number = Number(value)
  if (!Number.isFinite(number)) return null
  const ratio = Math.abs(number) > 1 ? number / 100 : number
  return Math.round(ratio * 1_000_000) / 1_000_000
}

function splitReason(reason: unknown): string[] {
  const text = String(reason || '').trim()
  if (!text) return []
  const names = text
    .split(/[+/,，、；;|]+/)
    .map(item => item.trim())
    .filter(Boolean)
  return [...new Set(names)].slice(0, 4)
}

function timeToTimestamp(time: string | undefined, now: number): number {
  if (!time) return now
  const match = time.match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/)
  if (!match) return now

  const date = new Date(now)
  date.setHours(Number(match[1]), Number(match[2]), Number(match[3] || 0), 0)
  return date.getTime()
}

function eventId(stock: LimitUpPoolStock, type: HotStockAbnormalEventType, code: string, timestamp: number): string {
  const suffix = stock.limitUpTime || stock.firstZtTime ? String(timestamp) : 'latest'
  return `ths:${stock.poolType}:${type}:${code}:${suffix}`
}

function toEvent(stock: LimitUpPoolStock, now: number): HotStockAbnormalEvent | null {
  const type = resolveEventType(stock.poolType)
  const code = normalizeHotStockCode(stock.code)
  if (!type || !code) return null

  const timestamp = timeToTimestamp(stock.limitUpTime || stock.firstZtTime, now)
  return {
    category: 'stock',
    id: eventId(stock, type, code, timestamp),
    eventType: type,
    type,
    typeName: resolveEventName(type),
    direction: 'up',
    severity: resolveSeverity(type),
    timestamp,
    code,
    name: stock.name || code,
    changePct: toRatio(stock.change),
    price: null,
    relatedPlates: splitReason(stock.reason),
    sectorName: '',
    matchedHotStock: false,
    matchedCandidate: false,
    raw: {
      source: 'ths-limitup-pools',
      poolType: stock.poolType,
      item: stock.raw,
    },
  }
}

export class ThsLimitUpEventFeed {
  private readonly api: ThsLimitUpEventApi
  private readonly now: () => number

  constructor(options: ThsLimitUpEventFeedOptions = {}) {
    this.api = options.api || apiService
    this.now = options.now || Date.now
  }

  async fetchEvents(): Promise<HotStockAbnormalEvent[]> {
    const response = await this.api.getThsLimitUpPools()
    const now = this.now()
    return mapThsLimitUpPools(response?.pools || {})
      .map(stock => toEvent(stock, now))
      .filter((event): event is HotStockAbnormalEvent => Boolean(event))
  }
}
