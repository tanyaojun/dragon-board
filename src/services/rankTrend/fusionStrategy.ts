import type { CandidateTier, RankTrendAnalysisResult } from './types'

type RankTrendLike = RankTrendAnalysisResult & {
  jump?: {
    direction?: string
    confidence?: number
  }
}

function asNumber(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getRankTrend(stock: any): RankTrendLike | null {
  return (stock?.rankTrend as RankTrendLike | undefined) ?? null
}

function getCandidateTier(rankTrend: RankTrendLike): CandidateTier | '' {
  return (rankTrend.strategy?.candidateTier as CandidateTier | undefined) ?? ''
}

function getMomentum(rankTrend: RankTrendLike) {
  return rankTrend.technical?.momentumProfile ?? rankTrend.strategy?.momentum
}

function hasReadySampleQuality(rankTrend: RankTrendLike): boolean {
  return rankTrend.meta?.sampleQuality?.status === 'ok'
}

function isLimitUpBlocked(stock: any): boolean {
  const change = asNumber(stock?.change)
  const code = String(stock?.code ?? '')
  const threshold = code.startsWith('300') || code.startsWith('301') || code.startsWith('688') ? 19.8 : 9.8
  return change >= threshold
}

function hasBaseFusionGate(stock: any, rankTrend: RankTrendLike): boolean {
  const jumpDirection = String(rankTrend.jump?.direction ?? '')
  const jumpConfidence = asNumber(rankTrend.jump?.confidence)
  const momentum = getMomentum(rankTrend)
  const short = asNumber(momentum?.short)
  const mid = asNumber(momentum?.mid)
  const long = asNumber(momentum?.long)
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber(stock?.accDelta)
  const change = asNumber(stock?.change)

  return (
    jumpDirection === 'buy' &&
    jumpConfidence >= 90 &&
    short > 0 &&
    mid > 0 &&
    long > 0 &&
    (acceleration >= 10 || accDelta >= 8) &&
    change < 6 &&
    !isLimitUpBlocked(stock)
  )
}

export function isFusionEntryCandidate(stock: any): boolean {
  const rankTrend = getRankTrend(stock)
  if (!rankTrend) return false
  if (!hasReadySampleQuality(rankTrend)) return false

  if (String(rankTrend.cycle?.decision?.action ?? '') === 'veto') {
    return false
  }

  if (!hasBaseFusionGate(stock, rankTrend)) {
    return false
  }

  const tier = getCandidateTier(rankTrend)
  if (tier === 'A_MAIN') {
    return true
  }

  if (tier === 'B_IGNITION') {
    const momentum = getMomentum(rankTrend)
    const mid = asNumber(momentum?.mid)
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
    return mid >= 20 && zeroCross === 'buy'
  }

  return false
}
