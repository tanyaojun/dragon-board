// src/services/rankTrend/observationFactors.ts
// 观察因子全景（2026-09-16 P3）：把 observation 深层子字段（价格动量 / ATR均值回归 /
// 量比异动 / 价格排名背离）与 meta.marketPercentiles（市场百分位参考）组装为
// RankTrendObservationPanel「因子全景」track 的行视图。
// fail-visible：单轴缺数据 → 行仍存在、primary='缺数据'（不伪造、不隐藏轴的存在）；
// marketPercentiles 整体缺失 → null 由调用方整块隐藏。
export interface ObservationFactorRow {
  key: string
  label: string
  /** 后端 signalTier（S/A/B/C/D/E）；缺档位为 null */
  tier: string | null
  /** 核心读数（单行摘要） */
  primary: string
  /** 首条原因（tierReasons/reasons），可空 */
  reason: string | null
}

type ObservationLike = Record<string, any> | null | undefined
type FactorLike = Record<string, any> | null | undefined

const DIR_TEXT: Record<string, string> = {
  up: '上行',
  down: '下行',
  flat: '走平',
}

function dirText(value: unknown, fallback = '--'): string {
  return typeof value === 'string' ? DIR_TEXT[value] ?? value : fallback
}

function num(value: unknown, digits = 2): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--'
}

function signedNum(value: unknown, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '--'
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}`
}

function firstReason(factor: FactorLike): string | null {
  const reasons = [
    ...((factor?.tierReasons as string[] | undefined) ?? []),
    ...((factor?.reasons as string[] | undefined) ?? []),
  ]
  return typeof reasons[0] === 'string' && reasons[0] ? reasons[0] : null
}

function tierOf(factor: FactorLike): string | null {
  return typeof factor?.signalTier === 'string' && factor.signalTier ? factor.signalTier : null
}

function priceMomentumPrimary(factor: Record<string, any>): string {
  const trend = dirText(factor.maTrend, '未确认')
  const signal = typeof factor.momentumSignal === 'string' ? `（${factor.momentumSignal}）` : ''
  return `动量 ${signedNum(factor.momentumScore)} · 均线${trend}${signal}`
}

function atrPrimary(factor: Record<string, any>): string {
  if (factor.status === 'insufficient') {
    const bars = typeof factor.missingBars === 'number' ? factor.missingBars : null
    return bars !== null ? `样本不足（缺 ${bars} 帧）` : '样本不足'
  }
  if (factor.status !== 'ok') return `状态 ${String(factor.status ?? '--')}`
  return `偏差 ${signedNum(factor.deviation, 1)}% · ATR ${num(factor.atr)}`
}

function amountRatioPrimary(factor: Record<string, any>): string {
  if (typeof factor.score === 'number') {
    return `异动分 ${signedNum(factor.score)}${typeof factor.direction === 'string' ? ` · ${dirText(factor.direction)}` : ''}`
  }
  return '状态未知'
}

function divergencePrimary(factor: Record<string, any>): string {
  return `价格 ${dirText(factor.priceDir)} / 排名 ${dirText(factor.rankDir)}`
}

const FACTOR_DEFS: Array<{
  key: string
  label: string
  primary: (factor: Record<string, any>) => string
}> = [
  { key: 'priceMomentum', label: '价格动量', primary: priceMomentumPrimary },
  { key: 'atrMeanReversion', label: 'ATR均值回归', primary: atrPrimary },
  { key: 'amountRatio', label: '量比异动', primary: amountRatioPrimary },
  { key: 'priceRankDivergence', label: '价/排名背离', primary: divergencePrimary },
]

export function buildObservationFactorRows(observation: ObservationLike): ObservationFactorRow[] {
  return FACTOR_DEFS.map(({ key, label, primary }) => {
    const factor = observation?.[key]
    if (!factor || typeof factor !== 'object') {
      return { key, label, tier: null, primary: '缺数据', reason: null }
    }
    return {
      key,
      label,
      tier: tierOf(factor),
      primary: primary(factor),
      reason: firstReason(factor),
    }
  })
}

export interface MarketPercentileRow {
  label: string
  unit: string
  p50: string
  p70: string
  p85: string
}

export function buildMarketPercentileRows(
  percentiles: Record<string, any> | null | undefined,
): MarketPercentileRow[] | null {
  if (!percentiles || typeof percentiles !== 'object') return null
  const rows: MarketPercentileRow[] = []
  const push = (
    label: string,
    unit: string,
    fmt: (value: unknown) => string,
    keys: [string, string, string],
  ) => {
    const [k50, k70, k85] = keys
    const values = [percentiles[k50], percentiles[k70], percentiles[k85]]
    if (values.every((value) => typeof value !== 'number')) return
    rows.push({ label, unit, p50: fmt(values[0]), p70: fmt(values[1]), p85: fmt(values[2]) })
  }
  const toYi = (value: unknown) =>
    typeof value === 'number' && Number.isFinite(value) ? (value / 1e8).toFixed(2) : '--'
  const toFixed2 = (value: unknown) => num(value)
  push('成交额', '亿', toYi, ['turnoverP50', 'turnoverP70', 'turnoverP85'])
  push('量比', '', toFixed2, ['volumeRatioP50', 'volumeRatioP70', 'volumeRatioP85'])
  push('换手率', '%', toFixed2, ['turnoverRateP50', 'turnoverRateP70', 'turnoverRateP85'])
  return rows.length ? rows : null
}
