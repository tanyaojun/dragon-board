import { normalizeStockCode } from '@/utils/common'
import { apiService } from '../apiService'
import { dataLayer } from '../DataLayer'
import type { LimitUpItem } from './types'

type LimitUpApi = {
  getLimitUp: () => Promise<any>
  getThsLimitUpPools?: () => Promise<any>
}

type LimitUpDataLayerUpdate = {
  code: string
  reason?: string
  isNew?: boolean
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  fengdan?: number
  maxFengdan?: number
  leadStatus?: string
  leadTimes?: number
  lianbanStr?: string
  tags?: Array<{ Name: string }>
  speed?: number
  turnover?: number
  turnoverRate?: number
  maxDrawdown?: number
  poolType?: LimitUpPoolType
}

type LimitUpDataLayer = {
  updateLimitUpData?: (updates: LimitUpDataLayerUpdate[]) => void
}

export interface LimitUpUpdate {
  code: string
  reason: string
  isNew: boolean
  firstZtTime: string
  lastZtTime: string
  boardHeight: number
  highDays: number
}

export type LimitUpPoolType =
  | 'one'
  | 'two'
  | 'three'
  | 'four'
  | 'high'
  | 'failed'
  | 'rushing'
  | 'drawdown'

export interface LimitUpPoolStock extends Partial<LimitUpUpdate> {
  poolType: LimitUpPoolType
  code: string
  name: string
  change?: number
  limitUpTime?: string
  fengdan?: number
  turnover?: number
  turnoverRate?: number
  speed?: number
  currencyValue?: number
  maxDrawdown?: number
  raw: Record<string, unknown>
}

type ThsLimitUpPoolResponse = Partial<Record<LimitUpPoolType, { items?: unknown[] }>>

function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = Number(value)
  return Number.isFinite(number) ? number : null
}

function parseBoardText(value: unknown): number | null {
  const text = String(value || '').trim()
  if (!text) return null
  if (text.includes('首板')) return 1

  const daysBoardsMatch = text.match(/\d+\s*天\s*(\d+)\s*板/)
  if (daysBoardsMatch) return toFiniteNumber(daysBoardsMatch[1])

  const boardMatch = text.match(/(\d+)\s*(?:连?板|板)/)
  if (boardMatch) return toFiniteNumber(boardMatch[1])

  return toFiniteNumber(text)
}

function resolveBoardHeight(item: LimitUpItem): number {
  return toFiniteNumber(item.continue_day) ?? parseBoardText(item.high_days) ?? decodeHighDaysValue(item.high_days_value) ?? 0
}

function decodeHighDaysValue(value: unknown): number | null {
  const encoded = toFiniteNumber(value)
  if (encoded === null) return null
  if (encoded > 10_000) {
    const boards = Math.floor(encoded / 65_536)
    return boards > 0 ? boards : null
  }
  return encoded
}

function resolveHighDays(item: LimitUpItem): number {
  return parseBoardText(item.high_days) ?? decodeHighDaysValue(item.high_days_value) ?? resolveBoardHeight(item)
}

function formatLimitTime(value: unknown): string {
  const text = String(value || '').trim()
  if (!text) return ''
  if (/^\d{2}:\d{2}(?::\d{2})?$/.test(text)) return text.length === 5 ? `${text}:00` : text

  const seconds = Number(text)
  if (!Number.isFinite(seconds) || seconds <= 0) return text
  const date = new Date(seconds * 1000)
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date)
}

export function mapLimitUpItems(items: LimitUpItem[]): LimitUpUpdate[] {
  return items.map((item) => ({
    code: normalizeStockCode(item.code),
    reason: item.reason_type,
    isNew: item.is_new === 1,
    firstZtTime: formatLimitTime(item.first_limit_up_time),
    lastZtTime: formatLimitTime(item.last_limit_up_time),
    boardHeight: resolveBoardHeight(item),
    highDays: resolveHighDays(item),
  }))
}

function pickText(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key]
    const text = String(value || '').trim()
    if (text) return text
  }
  return ''
}

function pickNumber(record: Record<string, unknown>, keys: string[]): number | undefined {
  for (const key of keys) {
    const value = toFiniteNumber(record[key])
    if (value !== null) return value
  }
  return undefined
}

function mapThsPoolItem(poolType: LimitUpPoolType, value: unknown): LimitUpPoolStock | null {
  if (!value || typeof value !== 'object') return null
  const item = value as Record<string, unknown>
  const code = normalizeStockCode(pickText(item, ['stock_code', 'code']))
  if (!code) return null

  const limitUpTime = formatLimitTime(pickText(item, ['limit_up_time', 'first_limit_up_time']))
  const boardHeight =
    toFiniteNumber(item.continue_day) ??
    parseBoardText(item.high_days) ??
    decodeHighDaysValue(item.high_days_value) ??
    undefined

  return {
    poolType,
    code,
    name: pickText(item, ['stock_name', 'name']) || code,
    reason: pickText(item, ['limit_up_reason', 'reason_type']),
    firstZtTime: limitUpTime,
    lastZtTime: formatLimitTime(pickText(item, ['last_limit_up_time'])) || limitUpTime,
    limitUpTime,
    boardHeight,
    highDays: boardHeight,
    change: pickNumber(item, ['change', 'change_rate']),
    fengdan: pickNumber(item, ['volume_money', 'order_amount']),
    turnover: pickNumber(item, ['turnover', 'volume_money']),
    turnoverRate: pickNumber(item, ['turnover_rate']),
    speed: pickNumber(item, ['rise_rate', 'speed']),
    currencyValue: pickNumber(item, ['currency_value']),
    maxDrawdown: pickNumber(item, ['max_drawdown']),
    raw: item,
  }
}

export function mapThsLimitUpPools(pools: ThsLimitUpPoolResponse): LimitUpPoolStock[] {
  return (Object.entries(pools) as Array<[LimitUpPoolType, { items?: unknown[] }]>).flatMap(([poolType, pool]) =>
    (Array.isArray(pool?.items) ? pool.items : [])
      .map((item) => mapThsPoolItem(poolType, item))
      .filter((item): item is LimitUpPoolStock => Boolean(item)),
  )
}

function toLimitUpUpdate(stock: LimitUpPoolStock): LimitUpDataLayerUpdate {
  const update: Record<string, unknown> = {
    code: stock.code,
    poolType: stock.poolType,
  }
  if (stock.reason) update.reason = stock.reason
  if (stock.isNew !== undefined) update.isNew = stock.isNew
  if (stock.firstZtTime) update.firstZtTime = stock.firstZtTime
  if (stock.lastZtTime) update.lastZtTime = stock.lastZtTime
  if (stock.boardHeight !== undefined) update.boardHeight = stock.boardHeight
  if (stock.highDays !== undefined) update.highDays = stock.highDays
  if (stock.fengdan !== undefined) update.fengdan = stock.fengdan
  if (stock.speed !== undefined) update.speed = stock.speed
  if (stock.turnover !== undefined) update.turnover = stock.turnover
  if (stock.turnoverRate !== undefined) update.turnoverRate = stock.turnoverRate
  if (stock.maxDrawdown !== undefined) update.maxDrawdown = stock.maxDrawdown
  return update as LimitUpDataLayerUpdate
}

export async function loadLimitUpData(
  dependencies: {
    api?: LimitUpApi
    dataLayer?: LimitUpDataLayer
  } = {},
): Promise<void> {
  const api = dependencies.api || apiService
  const targetDataLayer = dependencies.dataLayer || dataLayer

  try {
    const response = await api.getLimitUp()
    if (!response?.data?.info) return

    targetDataLayer.updateLimitUpData?.(mapLimitUpItems(response.data.info))
  } catch (error) {
    console.warn('[DataLoader] 加载涨停池数据失败:', error)
  }
}

export async function loadThsLimitUpPoolData(
  dependencies: {
    api?: LimitUpApi
    dataLayer?: LimitUpDataLayer
  } = {},
): Promise<void> {
  const api = dependencies.api || apiService
  const targetDataLayer = dependencies.dataLayer || dataLayer

  try {
    if (!api.getThsLimitUpPools) return
    const response = await api.getThsLimitUpPools()
    const updates = mapThsLimitUpPools(response?.pools || {}).map(toLimitUpUpdate)
    if (!updates.length) return
    targetDataLayer.updateLimitUpData?.(updates)
  } catch (error) {
    console.warn('[DataLoader] 加载同花顺细分涨停池数据失败:', error)
  }
}
