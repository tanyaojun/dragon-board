import type { QuotePatch, TickTrade } from '../../types'
import {
  EASTMONEY_LARGE_ORDER_AMOUNT_THRESHOLD,
  EASTMONEY_LARGE_ORDER_VOLUME_THRESHOLD,
  EASTMONEY_SUPER_ORDER_AMOUNT_THRESHOLD,
  EASTMONEY_SUPER_ORDER_VOLUME_THRESHOLD,
} from './constants'

export interface MoneyFlowTickSummary {
  activeAmount: number
  mainNet: number
  superNet: number
}

export interface EstimatedTdxMoneyFlow {
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number
  tdxBuyVolume: number
  tdxSellVolume: number
  tdxCurrentVolume: number
  moneyFlowSource: 'tdx_estimate'
  moneyFlowEstimated: true
}

// 东方财富资金流页面以超大单/大单/中单/小单分档展示资金，主力口径对应超大单+大单。
// L1 主买/主卖量差不是主力资金口径，不能用来填充 zlje/zljzb/cddje/cddjzb。
const PERCENT_SCALE = 100
const SHARE_UNIT_PER_LOT = 100

function roundMoney(value: number): number {
  return Number.isFinite(value) ? Math.round(value) : 0
}

function safeRatio(numerator: number, denominator: number): number {
  return denominator !== 0 && Number.isFinite(numerator) && Number.isFinite(denominator)
    ? numerator / denominator
    : 0
}

export function classifyMoneyFlowOrder(
  amount: number,
  volume: number,
): 'super' | 'large' | 'other' {
  if (
    amount >= EASTMONEY_SUPER_ORDER_AMOUNT_THRESHOLD ||
    volume >= EASTMONEY_SUPER_ORDER_VOLUME_THRESHOLD
  ) {
    return 'super'
  }
  if (
    amount >= EASTMONEY_LARGE_ORDER_AMOUNT_THRESHOLD ||
    volume >= EASTMONEY_LARGE_ORDER_VOLUME_THRESHOLD
  ) {
    return 'large'
  }
  return 'other'
}

export function summarizeMoneyFlowTicks(ticks: TickTrade[]): MoneyFlowTickSummary {
  const summary = {
    activeAmount: 0,
    mainNet: 0,
    superNet: 0,
  }

  ticks.forEach((tick) => {
    if (tick.side !== 'buy' && tick.side !== 'sell') return
    const amount = Number(tick.amount) || 0
    const volume = Number(tick.volume) || 0
    if (amount <= 0 || volume <= 0) return

    summary.activeAmount += amount
    const direction = tick.side === 'buy' ? 1 : -1
    const bucket = classifyMoneyFlowOrder(amount, volume * SHARE_UNIT_PER_LOT)
    if (bucket === 'super') {
      summary.superNet += amount * direction
      summary.mainNet += amount * direction
    } else if (bucket === 'large') {
      summary.mainNet += amount * direction
    }
  })

  return summary
}

export function buildOfficialStyleMoneyFlow(
  summary: MoneyFlowTickSummary,
  turnover: number,
): EstimatedTdxMoneyFlow | null {
  const denominator = Number(turnover) > 0 ? Number(turnover) : summary.activeAmount
  if (denominator <= 0) return null

  const mainRatio = safeRatio(summary.mainNet, denominator)
  const superRatio = safeRatio(summary.superNet, denominator)

  return {
    zlje: roundMoney(summary.mainNet),
    zljzb: Number((mainRatio * PERCENT_SCALE).toFixed(2)),
    cddje: roundMoney(summary.superNet),
    cddjzb: Number((superRatio * PERCENT_SCALE).toFixed(2)),
    tdxBuyVolume: 0,
    tdxSellVolume: 0,
    tdxCurrentVolume: 0,
    moneyFlowSource: 'tdx_estimate',
    moneyFlowEstimated: true,
  }
}

export function estimateTdxMoneyFlow(
  code: string,
  quote: QuotePatch,
  tickSummary?: MoneyFlowTickSummary | null,
): EstimatedTdxMoneyFlow | null {
  void code

  const buyVolume = Number(quote.tdxBuyVolume) || 0
  const sellVolume = Number(quote.tdxSellVolume) || 0
  const quoteTurnover = Number(quote.amount) > 0 ? Number(quote.amount) : 0
  const currentVolume = Number(quote.tdxCurrentVolume) || 0

  const officialStyleMoneyFlow =
    tickSummary && tickSummary.activeAmount > 0
      ? buildOfficialStyleMoneyFlow(tickSummary, quoteTurnover)
      : null
  if (officialStyleMoneyFlow) {
    return {
      ...officialStyleMoneyFlow,
      tdxBuyVolume: buyVolume,
      tdxSellVolume: sellVolume,
      tdxCurrentVolume: currentVolume,
    }
  }

  return null
}
