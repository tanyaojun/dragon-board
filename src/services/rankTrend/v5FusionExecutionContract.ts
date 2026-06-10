import type { CandidateTier, RankTrendAnalysisResult } from './types'
import { getExecutionCandidateTier } from './executionTierSelector'

export const V5_FUSION_DEFAULTS = {
  strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
  snapshotType: 'half_hour',
  executionMode: 'current_bar',
  maxHoldingBars: 30,
  volumeParticipationRate: 0.1,
  stopLossPct: 0.05,
  takeProfitPct: 9.99,
  minJumpConfidence: 90,
} as const

type RankTrendLike = RankTrendAnalysisResult & {
  jump?: {
    direction?: string
    confidence?: number
  }
}

export interface V5FusionEntryResult {
  accepted: boolean
  candidateTier: CandidateTier
  jumpConfidence: number
  lifecycleAction: string
  blockedReasons: string[]
}

export interface V5FusionExitInput {
  hasOpenPosition?: boolean
  grossReturn?: number
}

export interface V5FusionExitResult {
  exitWatch: boolean
  reason?: string
}

function asNumber(value: unknown, fallback = 0): number {
  const num = Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getRankTrend(stock: any): RankTrendLike | null {
  return (stock?.rankTrend as RankTrendLike | undefined) ?? null
}

function getMomentum(rankTrend: RankTrendLike) {
  return rankTrend.technical?.momentumProfile ?? rankTrend.executionStrategy?.momentum
}

function isLimitUpBlocked(stock: any): boolean {
  const change = asNumber(stock?.change)
  const code = String(stock?.code ?? '')
  const threshold = code.startsWith('300') || code.startsWith('301') || code.startsWith('688') ? 19.8 : 9.8
  return change >= threshold
}

export function evaluateV5FusionEntry(stock: any): V5FusionEntryResult {
  const blockedReasons: string[] = []
  const rankTrend = getRankTrend(stock)
  if (!rankTrend) {
    return {
      accepted: false,
      candidateTier: 'N_NEUTRAL',
      jumpConfidence: 0,
      lifecycleAction: '',
      blockedReasons: ['缺失 rankTrend，阻断 V5 入场'],
    }
  }

  const executionTier = getExecutionCandidateTier(rankTrend)
  const candidateTier = executionTier || 'N_NEUTRAL'
  const lifecycleAction = String(rankTrend.cycle?.decision?.action ?? '')
  const jumpConfidence = asNumber(rankTrend.jump?.confidence)
  if (!executionTier) blockedReasons.push('缺失 executionStrategy，阻断 V5 入场')

  if (rankTrend.meta?.sampleQuality?.status === 'insufficient') {
    blockedReasons.push('样本不足，阻断 V5 入场')
  }

  if (lifecycleAction === 'veto') {
    blockedReasons.push('生命周期辅助决策一票否决')
  }

  const jumpDirection = String(rankTrend.jump?.direction ?? '')
  if (jumpDirection !== 'buy') blockedReasons.push('Jump 方向不是 buy')
  if (jumpConfidence < V5_FUSION_DEFAULTS.minJumpConfidence) {
    blockedReasons.push(`Jump 置信度低于 ${V5_FUSION_DEFAULTS.minJumpConfidence}`)
  }

  const momentum = getMomentum(rankTrend)
  const short = asNumber(momentum?.short)
  const mid = asNumber(momentum?.mid)
  const long = asNumber(momentum?.long)
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber(stock?.accDelta)
  const change = asNumber(stock?.change)

  if (short <= 0 || mid <= 0 || long <= 0) blockedReasons.push('多周期动量未同步为正')
  if (acceleration < 10 && accDelta < 8) blockedReasons.push('加速度未达到 V5 入场要求')
  if (change >= 6) blockedReasons.push('涨幅过高，阻断早期入场')
  if (isLimitUpBlocked(stock)) blockedReasons.push('涨停状态，阻断入场')

  if (candidateTier !== 'A_MAIN' && candidateTier !== 'B_IGNITION') {
    blockedReasons.push('executionStrategy 非 A/B 候选')
  }

  if (candidateTier === 'B_IGNITION') {
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
    if (mid < 20 || zeroCross !== 'buy') {
      blockedReasons.push('B_IGNITION 未通过中周期动量和零轴同步确认')
    }
  }

  return {
    accepted: blockedReasons.length === 0,
    candidateTier,
    jumpConfidence,
    lifecycleAction,
    blockedReasons,
  }
}

export function evaluateV5FusionExit(stock: any, input: V5FusionExitInput): V5FusionExitResult {
  const rankTrend = getRankTrend(stock)
  const lifecycleAction = String(rankTrend?.cycle?.decision?.action ?? '')
  const grossReturn = asNumber(input.grossReturn)

  if (
    input.hasOpenPosition &&
    grossReturn <= 0 &&
    (lifecycleAction === 'veto' || lifecycleAction === 'exit_watch')
  ) {
    return { exitWatch: true, reason: '生命周期B反对且未盈利' }
  }

  return { exitWatch: false }
}
