import type { QuotePatch, TickTrade } from '../../types'
import {
  LARGE_ORDER_AMOUNT_THRESHOLD,
  LARGE_ORDER_VOLUME_THRESHOLD,
  MAX_ACTIVE_MONEY_FLOW_RATIO,
  MAX_ESTIMATED_MAIN_RATIO,
  MAX_ESTIMATED_SUPER_RATIO,
  SUPER_ORDER_AMOUNT_THRESHOLD,
  SUPER_ORDER_VOLUME_THRESHOLD,
} from './constants'
import { clamp } from '../theme/utils'

export interface TdxDarkMoneyFactor {
  x16: number
  amplitude: number
  closePosition: number
}

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

function roundMoney(value: number): number {
  return Number.isFinite(value) ? Math.round(value) : 0
}

function capEstimatedMoneyFlowRatio(ratio: number, maxAbsRatio: number): number {
  if (!Number.isFinite(ratio)) return 0
  return clamp(ratio, -maxAbsRatio, maxAbsRatio)
}

function safeRatio(numerator: number, denominator: number): number {
  return denominator !== 0 && Number.isFinite(numerator) && Number.isFinite(denominator)
    ? numerator / denominator
    : 0
}

export function calculateTdxDarkMoneyFactor(quote: QuotePatch): TdxDarkMoneyFactor {
  const close = Number(quote.lastPrice) || 0
  const open = Number(quote.open) || close
  const high = Number(quote.high) || Math.max(open, close)
  const low = Number(quote.low) || Math.min(open, close)
  const preClose = Number(quote.preClose) || open || close

  const x9 = safeRatio(open - preClose, preClose)
  const x10 = safeRatio(close - open, open)
  const x11 = safeRatio(high - open, open)
  const x12 = safeRatio(close - high, high)
  const x13 = safeRatio(low - open, open)
  const x14 = safeRatio(close - low, low)
  const x15 = x9 + x10 + x11 + x12 + x13 + x14
  const x16 = x15 >= 1 ? 0.8 : x15
  const amplitude = safeRatio(high - low, preClose)
  const closePosition = high > low ? clamp((close - low) / (high - low), 0, 1) : 0.5

  return {
    x16,
    amplitude,
    closePosition,
  }
}

export function classifyMoneyFlowOrder(
  amount: number,
  volume: number,
): 'super' | 'large' | 'other' {
  if (amount >= SUPER_ORDER_AMOUNT_THRESHOLD || volume >= SUPER_ORDER_VOLUME_THRESHOLD) {
    return 'super'
  }
  if (amount >= LARGE_ORDER_AMOUNT_THRESHOLD || volume >= LARGE_ORDER_VOLUME_THRESHOLD) {
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
    const bucket = classifyMoneyFlowOrder(amount, volume * 100)
    if (bucket === 'super') {
      summary.superNet += amount * direction
      summary.mainNet += amount * direction
    } else if (bucket === 'large') {
      summary.mainNet += amount * direction
    }
  })

  return summary
}

export function estimateTdxMoneyFlow(
  code: string,
  quote: QuotePatch,
): EstimatedTdxMoneyFlow | null {
  void code

  const price = Number(quote.lastPrice) || 0
  const changePct = Number(quote.changePct) || 0
  const buyVolume = Number(quote.tdxBuyVolume) || 0
  const sellVolume = Number(quote.tdxSellVolume) || 0
  const activeVolume = buyVolume + sellVolume

  if (price <= 0 || activeVolume <= 0) return null

  const activeAmount = activeVolume * price * 100
  const turnover = Number(quote.amount) > 0 ? Number(quote.amount) : activeAmount
  if (turnover <= 0) return null

  const activeNet = (buyVolume - sellVolume) * price * 100
  const activeRatio = capEstimatedMoneyFlowRatio(
    activeNet / Math.max(activeAmount, 1),
    MAX_ACTIVE_MONEY_FLOW_RATIO,
  )
  const { x16, amplitude, closePosition } = calculateTdxDarkMoneyFactor(quote)
  const turnoverScale = clamp(Math.log10(Math.max(turnover, 1) / 500_000_000), 0, 1)
  const smallActiveImbalance = clamp((0.035 - Math.abs(activeRatio)) / 0.035, 0, 1)
  const churnScore = clamp((amplitude - 0.06) / 0.1, 0, 1)
  const weakCloseScore = clamp((0.68 - closePosition) / 0.25, 0, 1)
  const hiddenMainMultiplier = 1 + smallActiveImbalance * churnScore * weakCloseScore * turnoverScale * 14
  const closeBias = clamp((closePosition - 0.5) * 2, -1, 1)
  const pathDirection = Math.abs(x16) >= 0.025 ? Math.sign(x16) : Math.sign(closeBias)
  const pathStrength =
    pathDirection >= 0
      ? clamp((closePosition - 0.55) / 0.45, 0, 1)
      : clamp((0.55 - closePosition) / 0.55, 0, 1)
  const x16Strength = clamp(Math.abs(x16) / 0.16, 0, 1)
  const priceMoveStrength = clamp(Math.abs(changePct) / 7, 0, 1)
  const amplitudeStrength = clamp(amplitude / 0.08, 0, 1)
  const pathConflictStrength =
    pathDirection !== 0 && activeRatio !== 0 && Math.sign(activeRatio) !== pathDirection
      ? clamp(Math.max(x16Strength * priceMoveStrength, pathStrength * amplitudeStrength), 0, 1)
      : 0
  const activeDamping = 1 - pathConflictStrength * 0.97
  const activeVisibleRatio = activeRatio * hiddenMainMultiplier * activeDamping
  const pathVisibleBase =
    pathDirection >= 0
      ? clamp(0.12 + amplitude * 0.55 + turnoverScale * 0.018, 0.12, 0.28)
      : clamp(0.16 + amplitude * 0.8 + turnoverScale * 0.025, 0.16, 0.42)
  const pathVisibleRatio = x16 * pathStrength * pathVisibleBase
  const closePressureBase =
    pathDirection >= 0
      ? clamp(0.018 + turnoverScale * 0.025 + amplitude * 0.06, 0.018, 0.075)
      : clamp(0.035 + turnoverScale * 0.035 + amplitude * 0.12, 0.035, 0.12)
  const closePressureRatio =
    Math.sign(closeBias) * Math.pow(Math.abs(closeBias), 1.25) * amplitudeStrength * closePressureBase
  const conflictPressureBase =
    pathDirection >= 0
      ? clamp(0.006 + amplitude * 0.04 + turnoverScale * 0.006, 0.006, 0.035)
      : clamp(0.023 + amplitude * 0.12 + turnoverScale * 0.012, 0.023, 0.063)
  const conflictPressureRatio = pathDirection * pathConflictStrength * conflictPressureBase
  const visibleMainRatio = capEstimatedMoneyFlowRatio(
    activeVisibleRatio + pathVisibleRatio + closePressureRatio + conflictPressureRatio,
    0.2,
  )

  const neutralBaseRatio =
    x16 >= 0
      ? clamp(0.13 + amplitude * 0.72 + turnoverScale * 0.018, 0.13, 0.28)
      : clamp(0.18 + amplitude * 0.75 + turnoverScale * 0.03, 0.18, 0.32)
  const darkRatio = capEstimatedMoneyFlowRatio(neutralBaseRatio * x16, 0.12)

  const mainRatio = capEstimatedMoneyFlowRatio(
    visibleMainRatio + darkRatio,
    MAX_ESTIMATED_MAIN_RATIO,
  )

  const currentVolume = Number(quote.tdxCurrentVolume) || 0
  const currentPulse = turnover > 0 ? clamp((currentVolume * price * 100) / turnover, 0, 0.03) : 0
  const superShare = clamp(0.35 + currentPulse * 6 + Math.abs(visibleMainRatio) * 0.8, 0.35, 0.75)
  let superRatio = visibleMainRatio * superShare + darkRatio * 0.35
  superRatio = capEstimatedMoneyFlowRatio(superRatio, MAX_ESTIMATED_SUPER_RATIO)
  if (Math.abs(superRatio) > Math.abs(mainRatio)) {
    superRatio = Math.sign(superRatio) * Math.abs(mainRatio)
  }

  const mainNet = turnover * mainRatio
  const estimatedSuperNet = turnover * superRatio

  return {
    zlje: roundMoney(mainNet),
    zljzb: Number((mainRatio * 100).toFixed(2)),
    cddje: roundMoney(estimatedSuperNet),
    cddjzb: Number((superRatio * 100).toFixed(2)),
    tdxBuyVolume: buyVolume,
    tdxSellVolume: sellVolume,
    tdxCurrentVolume: currentVolume,
    moneyFlowSource: 'tdx_estimate',
    moneyFlowEstimated: true,
  }
}
