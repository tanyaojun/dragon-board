import type { RankTrendAnalysisResult } from './types'
import { clamp } from './utils'

function calculateStageWeightedRiskSeverity(input: {
  score: number
  threshold: number
  scale: number
  stage: RankTrendAnalysisResult['cycle']['stage']
  stageMultipliers: Record<RankTrendAnalysisResult['cycle']['stage'], number>
}): number {
  const { score, threshold, scale, stage, stageMultipliers } = input
  const baseSeverity = clamp((score - threshold) / scale, 0, 1)
  return clamp(baseSeverity * (stageMultipliers[stage] ?? 1), 0, 1)
}

function calculateOverheatRiskScore(input: {
  currentPercentile: number
  metrics: RankTrendAnalysisResult['cycle']['metrics']
  technical: RankTrendAnalysisResult['technical']
}): number {
  const { currentPercentile, metrics, technical } = input
  let score = 0
  score += Math.max(0, currentPercentile - 70) * 1.2
  score += Math.max(0, metrics.rankShock) * 12

  if (metrics.rankVelocity > 0) score += Math.min(15, metrics.rankVelocity * 1.5)
  if (metrics.rankAcceleration < 0) score += Math.min(20, Math.abs(metrics.rankAcceleration) * 4)
  if (technical.macd.histogram < 0) score += Math.min(10, Math.abs(technical.macd.histogram) * 15)
  if (technical.signals.direction.signal === 'buy') score += 5
  if (technical.signals.acceleration.signal !== 'buy') score += 10
  if (technical.signals.zeroCross.signal === 'sell') score += 18

  return clamp(score, 0, 100)
}

function calculateAttentionCapitalDivergenceScore(input: {
  currentPercentile: number
  metrics: RankTrendAnalysisResult['cycle']['metrics']
  stage: RankTrendAnalysisResult['cycle']['stage']
  zlje: number
  zljzb: number
  volumeRatio: number
}): number {
  const { currentPercentile, metrics, stage, zlje, zljzb, volumeRatio } = input
  let score = 0
  const hotAttention = currentPercentile >= 70 || metrics.rankVelocity > 0
  const moneyWeak = zlje <= 0
  const ratioWeak = zljzb <= 0
  const abnormalVolume = volumeRatio >= 2

  if (hotAttention) score += 10
  if (hotAttention && moneyWeak) score += 25
  if (hotAttention && ratioWeak) score += 18
  if (abnormalVolume && moneyWeak) score += 15
  if (abnormalVolume && ratioWeak) score += 8
  if (metrics.rankShock > 0.8 && moneyWeak) score += 12
  if ((stage === 'crowded' || stage === 'reversal') && moneyWeak) score += 12

  if (zlje > 0) score -= 15
  if (zljzb > 0) score -= 10
  if (volumeRatio > 0 && volumeRatio < 1.5 && zlje > 0) score -= 6

  return clamp(score, 0, 100)
}

export function analyzeRiskSignals(input: {
  currentPercentile: number
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  zlje: number
  zljzb: number
  volumeRatio: number
}): RankTrendAnalysisResult['risk'] {
  const { currentPercentile, technical, cycle, zlje, zljzb, volumeRatio } = input
  const overheatScore = calculateOverheatRiskScore({
    currentPercentile,
    metrics: cycle.metrics,
    technical,
  })
  const divergenceScore = calculateAttentionCapitalDivergenceScore({
    currentPercentile,
    metrics: cycle.metrics,
    stage: cycle.stage,
    zlje,
    zljzb,
    volumeRatio,
  })

  const overheatSeverity = calculateStageWeightedRiskSeverity({
    score: overheatScore,
    threshold: 45,
    scale: 30,
    stage: cycle.stage,
    stageMultipliers: {
      ignition: 0.3,
      expansion: 0.55,
      crowded: 0.85,
      reversal: 1,
      cooling: 0.3,
    },
  })
  const divergenceSeverity = calculateStageWeightedRiskSeverity({
    score: divergenceScore,
    threshold: 40,
    scale: 30,
    stage: cycle.stage,
    stageMultipliers: {
      ignition: 0.35,
      expansion: 0.65,
      crowded: 0.9,
      reversal: 1,
      cooling: 0.35,
    },
  })

  const pressure = clamp(0.58 * overheatSeverity + 0.42 * divergenceSeverity, 0, 1)
  const synergy = overheatSeverity >= 0.65 && divergenceSeverity >= 0.6 ? 1 : 0

  return {
    overheat: {
      score: overheatScore,
      signal:
        overheatScore >= 70 && (cycle.stage === 'crowded' || cycle.stage === 'reversal')
          ? 'sell'
          : overheatScore >= 45
            ? 'hold'
            : 'buy',
      severity: overheatSeverity,
    },
    divergence: {
      score: divergenceScore,
      signal: divergenceScore >= 65 ? 'sell' : divergenceScore >= 40 ? 'hold' : 'buy',
      severity: divergenceSeverity,
    },
    pressure,
    synergy,
  }
}
