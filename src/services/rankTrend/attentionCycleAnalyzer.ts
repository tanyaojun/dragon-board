import type { AttentionStage, CycleEntryBias, RankTrendAnalysisResult } from './types'
import { ATTENTION_STAGE_SEQUENCE } from './types'
import { clamp } from './utils'

function calculateRankVelocity(percentiles: number[], offset = 1): number {
  if (percentiles.length < offset + 1) return 0
  return percentiles[percentiles.length - offset] - percentiles[percentiles.length - offset - 1]
}

function calculateCycleRankShock(percentiles: number[]): number {
  if (percentiles.length < 6) return 0
  const velocities: number[] = []
  for (let i = 1; i < percentiles.length; i++) {
    velocities.push(percentiles[i] - percentiles[i - 1])
  }
  const recent = velocities.slice(-5)
  const current = recent[recent.length - 1] ?? 0
  const mean = recent.reduce((sum, value) => sum + value, 0) / recent.length
  const variance =
    recent.reduce((sum, value) => sum + (value - mean) ** 2, 0) / recent.length
  const std = Math.sqrt(variance)
  if (!Number.isFinite(std) || std < 1e-6) return 0
  return (current - mean) / std
}

function calculateRankPathCommitment(percentiles: number[]): number {
  if (percentiles.length < 4) return 0.5
  const window = percentiles.slice(-8)
  const totalImprovement = Math.max(0, (window[window.length - 1] ?? 0) - (window[0] ?? 0))
  if (totalImprovement <= 0) return 0

  const steps: number[] = []
  for (let index = 1; index < window.length; index++) {
    steps.push((window[index] ?? 0) - (window[index - 1] ?? 0))
  }
  const positiveSteps = steps.filter((step) => step > 0)
  const lastStep = Math.max(0, steps[steps.length - 1] ?? 0)
  const preBreakoutImprovement = positiveSteps
    .slice(0, -1)
    .reduce((sum, step) => sum + step, 0)
  const positiveStepShare = positiveSteps.length / Math.max(1, steps.length)
  const preBreakoutShare = preBreakoutImprovement / Math.max(totalImprovement, 1)
  const lastStepDominance = lastStep / Math.max(totalImprovement, 1)

  return clamp(
    positiveStepShare * 0.45 + preBreakoutShare * 0.45 + (1 - lastStepDominance) * 0.1,
    0,
    1,
  )
}

function buildAttentionTrajectoryMetrics(
  ranks: number[],
  percentiles: number[],
  currentRank: number,
  currentPercentile: number,
): RankTrendAnalysisResult['cycle']['metrics'] {
  const recentRanks =
    ranks.length > 0 && ranks[ranks.length - 1] === currentRank ? [...ranks] : [...ranks, currentRank]
  const recentPercentiles =
    percentiles.length > 0 && Math.abs(percentiles[percentiles.length - 1] - currentPercentile) < 0.01
      ? [...percentiles]
      : [...percentiles, currentPercentile]

  const windowSize = Math.min(8, Math.max(recentRanks.length, 1))
  const rankWindow = recentRanks.slice(-windowSize)
  const percentileWindow = recentPercentiles.slice(-windowSize)

  let hotZoneStreak = 0
  for (let i = rankWindow.length - 1; i >= 0; i--) {
    const rank = rankWindow[i] ?? 999
    const percentile = percentileWindow[i] ?? 0
    if (rank <= 10 || percentile >= 88) {
      hotZoneStreak += 1
    } else {
      break
    }
  }

  const bestRecentRank =
    rankWindow.length > 0
      ? rankWindow.reduce((best, rank) => Math.min(best, rank), rankWindow[0] ?? currentRank)
      : currentRank

  return {
    rankVelocity: calculateRankVelocity(percentiles),
    rankAcceleration: calculateRankVelocity(percentiles, 1) - calculateRankVelocity(percentiles, 2),
    rankShock: calculateCycleRankShock(percentiles),
    hotZoneStreak,
    bestRecentRank,
    drawdownFromPeak: Math.max(0, currentRank - bestRecentRank),
    rankPathCommitment: calculateRankPathCommitment(recentPercentiles),
  }
}

function determineRawAttentionStage(input: {
  historyLength: number
  currentPercentile: number
  metrics: RankTrendAnalysisResult['cycle']['metrics']
}): AttentionStage {
  const { historyLength, currentPercentile, metrics } = input
  const {
    rankVelocity,
    rankAcceleration,
    hotZoneStreak,
    bestRecentRank,
    drawdownFromPeak,
  } = metrics

  if (historyLength < 2) return 'cooling'

  const inWarmZone = currentPercentile >= 65 || bestRecentRank <= 25
  const inHotZone = currentPercentile >= 85 || bestRecentRank <= 10
  const recoveryReady =
    rankVelocity > 0 &&
    rankAcceleration >= -1.2 &&
    (currentPercentile >= 50 || bestRecentRank <= 30 || hotZoneStreak >= 1)
  const expansionReady =
    rankVelocity > 0 &&
    currentPercentile >= 70 &&
    (rankAcceleration >= -1 || hotZoneStreak >= 1 || bestRecentRank <= 20)
  const crowdedReady =
    inHotZone &&
    (hotZoneStreak >= 3 || bestRecentRank <= 5) &&
    drawdownFromPeak <= 1 &&
    (rankVelocity <= 1 || rankAcceleration < 0)
  const reversalReady =
    inWarmZone &&
    drawdownFromPeak >= 2 &&
    (rankVelocity < 0 || rankAcceleration < -1) &&
    (hotZoneStreak >= 2 || bestRecentRank <= 10)

  if (reversalReady) return 'reversal'
  if (crowdedReady) return 'crowded'
  if (expansionReady && inWarmZone) return 'expansion'
  if (recoveryReady) return 'ignition'
  return 'cooling'
}

function normalizeAttentionStage(input: {
  previousStage: AttentionStage | null
  rawStage: AttentionStage
  currentPercentile: number
  metrics: RankTrendAnalysisResult['cycle']['metrics']
}): AttentionStage {
  const { previousStage, rawStage, currentPercentile, metrics } = input
  const { rankVelocity, rankAcceleration, hotZoneStreak, bestRecentRank, drawdownFromPeak } = metrics

  if (!previousStage) return rawStage

  const recoveryReady =
    rankVelocity > 0 &&
    rankAcceleration >= -1.2 &&
    (currentPercentile >= 50 || bestRecentRank <= 30 || hotZoneStreak >= 1)
  const weakening = rankVelocity < 0 || rankAcceleration < -1 || drawdownFromPeak >= 2
  const severeWeakening = rankVelocity < -1 || rankAcceleration < -2.5 || drawdownFromPeak >= 3
  const coolingReady = currentPercentile < 72 || hotZoneStreak <= 1
  const crowdedCarryover = currentPercentile >= 82 || bestRecentRank <= 12 || hotZoneStreak >= 2

  switch (previousStage) {
    case 'ignition':
      if (rawStage === 'expansion') return 'expansion'
      if (rawStage === 'crowded') return 'expansion'
      if (rawStage === 'reversal' || rawStage === 'cooling') {
        return weakening ? 'cooling' : 'ignition'
      }
      return 'ignition'
    case 'expansion':
      if (rawStage === 'crowded') return 'crowded'
      if (rawStage === 'reversal') {
        if (crowdedCarryover && !severeWeakening) return 'crowded'
        return severeWeakening || weakening ? 'reversal' : 'crowded'
      }
      if (rawStage === 'cooling') {
        return severeWeakening || weakening ? 'reversal' : 'expansion'
      }
      if (rawStage === 'ignition') return 'expansion'
      return 'expansion'
    case 'crowded':
      if (rawStage === 'reversal') return 'reversal'
      if (rawStage === 'cooling') return coolingReady ? 'cooling' : 'reversal'
      if (rawStage === 'expansion' || rawStage === 'ignition') {
        return weakening ? 'reversal' : 'crowded'
      }
      return 'crowded'
    case 'reversal':
      if (rawStage === 'cooling') return 'cooling'
      if (rawStage === 'reversal') return 'reversal'
      return recoveryReady ? 'cooling' : 'reversal'
    case 'cooling':
      if (rawStage === 'cooling' || rawStage === 'reversal') return 'cooling'
      if (!recoveryReady) return 'cooling'
      if (rawStage === 'expansion' && currentPercentile < 72 && hotZoneStreak === 0) return 'ignition'
      if (rawStage === 'crowded') return 'expansion'
      return rawStage
    default:
      return rawStage
  }
}

function buildTransition(previousStage: AttentionStage | null, currentStage: AttentionStage): string {
  if (!previousStage || previousStage === currentStage) return currentStage
  return `${previousStage}->${currentStage}`
}

function calculateCycleConfidence(
  stage: AttentionStage,
  currentPercentile: number,
  metrics: RankTrendAnalysisResult['cycle']['metrics'],
): number {
  const { rankVelocity, rankAcceleration, hotZoneStreak, bestRecentRank, drawdownFromPeak } = metrics

  const regionEvidence =
    stage === 'cooling'
      ? currentPercentile < 60
      : stage === 'ignition'
        ? currentPercentile >= 50 && currentPercentile < 80
        : stage === 'expansion'
          ? currentPercentile >= 60
          : stage === 'crowded'
            ? currentPercentile >= 82 || bestRecentRank <= 10
            : currentPercentile >= 70 || bestRecentRank <= 20

  const momentumEvidence =
    stage === 'cooling'
      ? rankVelocity <= 0 || currentPercentile < 60
      : stage === 'ignition'
        ? rankVelocity > 0 && rankAcceleration >= -0.8
        : stage === 'expansion'
          ? rankVelocity > 0 && rankAcceleration >= -0.2
          : stage === 'crowded'
            ? currentPercentile >= 80 && (rankVelocity <= 0 || hotZoneStreak >= 2)
            : rankVelocity <= 0 || rankAcceleration < -1

  const persistenceEvidence =
    stage === 'cooling'
      ? hotZoneStreak <= 1
      : stage === 'ignition'
        ? hotZoneStreak <= 1
        : stage === 'expansion'
          ? hotZoneStreak <= 2
          : stage === 'crowded'
            ? hotZoneStreak >= 2
            : hotZoneStreak >= 2 || bestRecentRank <= 10

  const drawdownEvidence =
    stage === 'cooling'
      ? drawdownFromPeak <= 1 || currentPercentile < 60
      : stage === 'ignition'
        ? drawdownFromPeak === 0
        : stage === 'expansion'
          ? drawdownFromPeak <= 1
          : stage === 'crowded'
            ? drawdownFromPeak <= 1
            : drawdownFromPeak >= 1

  return clamp(
    50 +
      Number(regionEvidence) * 10 +
      Number(momentumEvidence) * 10 +
      Number(persistenceEvidence) * 10 +
      Number(drawdownEvidence) * 10,
    50,
    90,
  )
}

function buildEntryAdvice(
  stage: AttentionStage,
  transition: string,
): RankTrendAnalysisResult['cycle']['entryAdvice'] {
  let bias: CycleEntryBias = 'watch'
  if (transition === 'cooling->ignition' || transition === 'ignition->expansion') {
    bias = 'preferred'
  } else if (stage === 'reversal') {
    bias = 'blocked'
  } else if (stage === 'cooling' || stage === 'crowded') {
    bias = 'avoid'
  } else if (stage === 'ignition' || stage === 'expansion') {
    bias = 'watch'
  }

  const reasonMap: Record<CycleEntryBias, string> = {
    preferred: '处于优选阶段路径，可作为情绪周期主观察对象。',
    watch: '处于可跟踪阶段，但还不是优选出手路径。',
    avoid: '处于冷却或拥挤阶段，宜观察不宜积极出手。',
    blocked: '处于反转阶段，应优先回避。',
  }

  return {
    bias,
    allowed: bias === 'preferred',
    reason: reasonMap[bias],
  }
}

function buildLifecycleDecision(input: {
  rawStage: AttentionStage
  stage: AttentionStage
  transition: string
  confidence: number
  metrics: RankTrendAnalysisResult['cycle']['metrics']
  risk?: {
    pressure?: number
    divergenceSeverity?: number
    overheatSeverity?: number
  }
}): RankTrendAnalysisResult['cycle']['decision'] {
  const { rawStage, stage, transition, confidence, metrics, risk } = input
  const reasons: string[] = []
  const discoveryReasons: string[] = []
  let action: RankTrendAnalysisResult['cycle']['decision']['action'] = 'caution'
  const riskPressure = risk?.pressure ?? 0
  const divergenceSeverity = risk?.divergenceSeverity ?? 0
  const overheatSeverity = risk?.overheatSeverity ?? 0
  const highRiskConflict =
    riskPressure >= 0.75 || (divergenceSeverity >= 0.8 && overheatSeverity >= 0.7)
  const weakPathCommitment =
    metrics.rankPathCommitment < 0.45 &&
    metrics.rankVelocity > 18 &&
    metrics.rankAcceleration > 12 &&
    (stage === 'ignition' || stage === 'expansion')

  if (stage === 'reversal' || rawStage === 'reversal') {
    action = 'veto'
    reasons.push('生命周期进入反转路径，辅助决策一票否决。')
  } else if (weakPathCommitment) {
    action = 'veto'
    reasons.push('生命周期B识别到最后一跳过强但整段承接不足，按假突破路径一票否决。')
  } else if (highRiskConflict && (stage === 'ignition' || stage === 'expansion')) {
    action = 'veto'
    reasons.push('生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。')
  } else if (stage === 'crowded') {
    action = 'exit_watch'
    reasons.push('生命周期进入拥挤路径，持仓后应进入退出观察。')
  } else if (stage === 'ignition' || stage === 'expansion') {
    action = 'allow'
    reasons.push('生命周期处于点火或扩散路径，允许 RankTrend 主结构继续进入候选评估。')
  } else {
    action = 'caution'
    reasons.push('生命周期仍在冷却路径，辅助决策保持谨慎。')
  }

  if (transition.includes('->')) {
    reasons.push(`阶段路径：${transition}。`)
  }

  if ((stage === 'ignition' || stage === 'expansion') && metrics.rankVelocity > 0) {
    discoveryReasons.push('生命周期存在漏选研究价值：点火/扩散路径仍在改善，但不得绕过 RankTrend 主结构直接制造买入。')
  }

  return {
    action,
    confidence,
    reasons,
    discovery: {
      action: discoveryReasons.length > 0 ? 'research_watch' : 'none',
      reasons: discoveryReasons,
    },
    evidence: {
      rawStage,
      stage,
      transition,
      rankVelocity: metrics.rankVelocity,
      rankAcceleration: metrics.rankAcceleration,
      drawdownFromPeak: metrics.drawdownFromPeak,
      hotZoneStreak: metrics.hotZoneStreak,
      rankPathCommitment: metrics.rankPathCommitment,
      riskPressure,
      divergenceSeverity,
      overheatSeverity,
    },
  }
}

export function analyzeAttentionCycle(input: {
  ranks: number[]
  percentiles: number[]
  risk?: {
    pressure?: number
    divergenceSeverity?: number
    overheatSeverity?: number
  }
}): RankTrendAnalysisResult['cycle'] {
  const { ranks, percentiles, risk } = input
  let previousRawStage: AttentionStage | null = null
  let previousStage: AttentionStage | null = null
  let currentRawStage: AttentionStage | null = null
  let currentStage: AttentionStage | null = null
  let currentMetrics: RankTrendAnalysisResult['cycle']['metrics'] | null = null

  // 逐前缀模拟阶段演化路径，取终态作为当前阶段判定。n≤50 时 O(n²) 开销可接受。
  for (let index = 0; index < percentiles.length; index++) {
    const prefixRanks = ranks.slice(0, index + 1)
    const prefixPercentiles = percentiles.slice(0, index + 1)
    const currentRank = prefixRanks[prefixRanks.length - 1] ?? 999
    const currentPercentile = prefixPercentiles[prefixPercentiles.length - 1] ?? 0
    const metrics = buildAttentionTrajectoryMetrics(
      prefixRanks,
      prefixPercentiles,
      currentRank,
      currentPercentile,
    )
    const rawStage = determineRawAttentionStage({
      historyLength: prefixPercentiles.length,
      currentPercentile,
      metrics,
    })
    const normalizedStage = normalizeAttentionStage({
      previousStage: currentStage,
      rawStage,
      currentPercentile,
      metrics,
    })

    previousRawStage = currentRawStage
    previousStage = currentStage
    currentRawStage = rawStage
    currentStage = normalizedStage
    currentMetrics = metrics
  }

  const fallbackStage = ATTENTION_STAGE_SEQUENCE[ATTENTION_STAGE_SEQUENCE.length - 1]
  const stage = currentStage ?? fallbackStage
  const rawStage = currentRawStage ?? fallbackStage
  const metrics =
    currentMetrics ?? {
      rankVelocity: 0,
      rankAcceleration: 0,
      rankShock: 0,
      hotZoneStreak: 0,
      bestRecentRank: ranks[ranks.length - 1] ?? 999,
      drawdownFromPeak: 0,
      rankPathCommitment: 0.5,
    }
  const currentPercentile = percentiles[percentiles.length - 1] ?? 0
  const transition = buildTransition(previousStage, stage)
  const confidence = calculateCycleConfidence(stage, currentPercentile, metrics)

  return {
    rawStage,
    stage,
    previousStage,
    transition,
    confidence,
    metrics,
    entryAdvice: buildEntryAdvice(stage, transition),
    decision: buildLifecycleDecision({ rawStage, stage, transition, confidence, metrics, risk }),
  }
}
