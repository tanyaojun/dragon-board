/**
 * L1 行情快照：与 tools/YiDongJingLing/MarketData/QuoteSnapshot.cs 对齐。
 * 由前端 WS 实时行情（QuotePatch）+ 十档盘口（Depth10Book）合成，供 L1EventEngine 消费。
 */
import type { DepthLevel } from '@/types/core'
import { normalizeHotStockCode } from './hotStockEventTypes'

export interface L1QuoteLevel {
  price: number
  volume: number
}

export interface L1QuoteSnapshot {
  code: string
  name: string
  lastPrice: number
  changePct: number
  changeAmount: number
  volume: number
  amount: number
  open: number
  high: number
  low: number
  preClose: number
  bids: L1QuoteLevel[]
  asks: L1QuoteLevel[]
  /** 行情源时间戳（毫秒）。 */
  sourceTime: number
}

function toNumber(value: unknown): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : 0
}

function normalizeSide(levels: DepthLevel[] | undefined): L1QuoteLevel[] {
  if (!Array.isArray(levels)) return []
  return levels
    .map(level => ({ price: toNumber(level?.price), volume: toNumber(level?.volume) }))
    .filter(level => level.price > 0 && level.volume > 0)
}

export function bid1Price(snapshot: L1QuoteSnapshot): number {
  return snapshot.bids[0]?.price ?? 0
}

export function bid1Volume(snapshot: L1QuoteSnapshot): number {
  return snapshot.bids[0]?.volume ?? 0
}

export function ask1Price(snapshot: L1QuoteSnapshot): number {
  return snapshot.asks[0]?.price ?? 0
}

export function ask1Volume(snapshot: L1QuoteSnapshot): number {
  return snapshot.asks[0]?.volume ?? 0
}

export function bidVolume5(snapshot: L1QuoteSnapshot): number {
  return snapshot.bids.slice(0, 5).reduce((sum, level) => sum + level.volume, 0)
}

export function askVolume5(snapshot: L1QuoteSnapshot): number {
  return snapshot.asks.slice(0, 5).reduce((sum, level) => sum + level.volume, 0)
}

export interface BuildL1QuoteSnapshotInput {
  code: string
  name?: string
  lastPrice?: number
  changePct?: number
  changeAmount?: number
  volume?: number
  amount?: number
  open?: number
  high?: number
  low?: number
  preClose?: number
  capturedAt?: string
  bridgeTs?: string
  sourceTime?: number
  bids?: DepthLevel[]
  asks?: DepthLevel[]
}

/** QuotePatch + Depth10Book → L1QuoteSnapshot；缺字段安全回退 0，不抛错。 */
export function buildL1QuoteSnapshot(input: BuildL1QuoteSnapshotInput): L1QuoteSnapshot | null {
  const code = normalizeHotStockCode(input.code)
  if (!code) return null
  return {
    code,
    name: String(input.name || ''),
    lastPrice: toNumber(input.lastPrice),
    // 行情桥 changePct 与 C# QuoteSnapshot.ChangePct 同为百分数口径，直接透传
    changePct: toNumber(input.changePct),
    changeAmount: toNumber(input.changeAmount),
    volume: toNumber(input.volume),
    amount: toNumber(input.amount),
    open: toNumber(input.open),
    high: toNumber(input.high),
    low: toNumber(input.low),
    preClose: toNumber(input.preClose),
    bids: normalizeSide(input.bids),
    asks: normalizeSide(input.asks),
    sourceTime: input.sourceTime ?? (Date.parse(input.capturedAt || input.bridgeTs || '') || Date.now()),
  }
}
