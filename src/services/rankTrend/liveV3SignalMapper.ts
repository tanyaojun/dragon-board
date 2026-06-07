import type { RankTrendAnalysisResult, CandidateTier } from './types'

export type V3LiveSignalLabel =
  | 'A主升买点'
  | 'B点火买点'
  | '止损卖出'
  | '转弱卖出'
  | '离榜卖出'
  | '持有观察'
  | '无信号'

export type V3LiveSignalTone = 'buy' | 'sell' | 'watch' | 'neutral'

export interface V3LiveSignalDecision {
  label: V3LiveSignalLabel
  tone: V3LiveSignalTone
  reasons: string[]
  degraded: boolean
  degradedReason?: string
}

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

function getSampleQualityStatus(rankTrend: RankTrendLike): 'ok' | 'degraded' | 'insufficient' | '' {
  return rankTrend.meta?.sampleQuality?.status ?? ''
}

function getDegradedMetadata(rankTrend: RankTrendLike): { degraded: boolean; degradedReason?: string } {
  const sampleQuality = rankTrend.meta?.sampleQuality
  if (sampleQuality?.status === 'degraded') {
    const detail = sampleQuality.coverageWarning
      ? `：${sampleQuality.coverageWarning}`
      : '，当前信号仅供盘中辅助判断'
    return {
      degraded: true,
      degradedReason: `样本降级${detail}`,
    }
  }
  return { degraded: false }
}

function isLimitUpBlocked(stock: any): boolean {
  const change = asNumber(stock?.change)
  const code = String(stock?.code ?? '')
  const threshold = code.startsWith('300') || code.startsWith('301') || code.startsWith('688') ? 19.8 : 9.8
  return change >= threshold
}

function hasBaseV3EntryGate(stock: any, rankTrend: RankTrendLike): { ok: boolean; reasons: string[] } {
  const jumpDirection = String(rankTrend.jump?.direction ?? '')
  const jumpConfidence = asNumber(rankTrend.jump?.confidence)
  const momentum = getMomentum(rankTrend)
  const short = asNumber(momentum?.short)
  const mid = asNumber(momentum?.mid)
  const long = asNumber(momentum?.long)
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber((stock as any)?.accDelta)
  const change = asNumber(stock?.change)

  const checks = [
    jumpDirection === 'buy' ? '' : 'jump.direction 不是 buy',
    jumpConfidence >= 90 ? '' : `jump.confidence=${jumpConfidence.toFixed(1)} < 90`,
    short > 0 ? '' : `short=${short.toFixed(1)} <= 0`,
    mid > 0 ? '' : `mid=${mid.toFixed(1)} <= 0`,
    long > 0 ? '' : `long=${long.toFixed(1)} <= 0`,
    acceleration >= 10 || accDelta >= 8
      ? ''
      : `acceleration=${acceleration.toFixed(1)} 且 accDelta=${accDelta.toFixed(1)} 未达阈值`,
    change < 6 ? '' : `change=${change.toFixed(2)} >= 6`,
    !isLimitUpBlocked(stock) ? '' : '涨停附近不可买',
  ].filter(Boolean)

  return {
    ok: checks.length === 0,
    reasons: checks.length ? checks : ['满足 V3 共同入场门槛'],
  }
}

function buildDecision(
  label: V3LiveSignalLabel,
  tone: V3LiveSignalTone,
  reasons: string[],
  degraded = false,
  degradedReason?: string,
): V3LiveSignalDecision {
  return { label, tone, reasons, degraded, degradedReason }
}

export function getLiveV3SignalDecision(stock: any): V3LiveSignalDecision {
  const rankTrend = getRankTrend(stock)
  if (!rankTrend) {
    return buildDecision('无信号', 'neutral', ['缺少 rankTrend 数据'], true, '缺少 rankTrend 数据')
  }

  if (getSampleQualityStatus(rankTrend) === 'insufficient') {
    const sampleQuality = rankTrend.meta?.sampleQuality
    return buildDecision(
      '无信号',
      'neutral',
      [
        `样本质量不足(${sampleQuality?.sampleCount ?? 0}/${sampleQuality?.requiredSampleCount ?? 0})`,
        sampleQuality?.coverageWarning || '当前快照不足以支持 V3 动作判断',
      ].filter(Boolean),
      true,
      '样本质量不足',
    )
  }

  const degradedMeta = getDegradedMetadata(rankTrend)
  const tier = getCandidateTier(rankTrend)
  const macdCross = String(rankTrend.technical?.macd?.cross ?? 'none')
  const rawChange = asNumber(rankTrend.meta?.rawChange)
  const weakeningReasons: string[] = []

  if (tier === 'D_EXIT_RISK') {
    weakeningReasons.push('candidateTier = D_EXIT_RISK')
  }

  if (rawChange < -50 && macdCross === 'death') {
    weakeningReasons.push(
      `rawChange=${rawChange.toFixed(1)} < -50`,
      'MACD 死叉',
    )
  }

  if (weakeningReasons.length > 0) {
    return buildDecision('转弱卖出', 'sell', weakeningReasons, degradedMeta.degraded, degradedMeta.degradedReason)
  }

  const baseGate = hasBaseV3EntryGate(stock, rankTrend)
  if (tier === 'A_MAIN' && baseGate.ok) {
    return buildDecision('A主升买点', 'buy', [
      'candidateTier = A_MAIN',
      ...baseGate.reasons,
    ], degradedMeta.degraded, degradedMeta.degradedReason)
  }

  if (tier === 'B_IGNITION' && baseGate.ok) {
    const momentum = getMomentum(rankTrend)
    const mid = asNumber(momentum?.mid)
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
      if (mid >= 20 && zeroCross === 'buy') {
        return buildDecision('B点火买点', 'buy', [
          'candidateTier = B_IGNITION',
          ...baseGate.reasons,
          `mid=${mid.toFixed(1)} >= 20`,
          'zeroCross = buy',
        ], degradedMeta.degraded, degradedMeta.degradedReason)
      }
  }

  if (tier === 'A_MAIN' || tier === 'B_IGNITION' || tier === 'C_CROWDED' || tier === 'N_NEUTRAL') {
    return buildDecision('持有观察', 'watch', [
      tier ? `candidateTier = ${tier}` : '存在候选但未达动作阈值',
      ...(baseGate.ok ? ['未命中当前层级专属确认条件'] : baseGate.reasons.slice(0, 2)),
    ], degradedMeta.degraded, degradedMeta.degradedReason)
  }

  return buildDecision('无信号', 'neutral', ['当前数据未命中 V3 动作规则'], true, '当前数据未命中 V3 动作规则')
}
