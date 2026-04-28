import type { RankSignalDirection, RankTrendAnalysisResult, RankTrendRuntimeConfig } from './types'
import { clamp } from './utils'

function convertCrossToSignal(
  cross: RankTrendAnalysisResult['technical']['macd']['cross'],
): RankSignalDirection {
  if (cross === 'golden') return 'buy'
  if (cross === 'death') return 'sell'
  return 'hold'
}

export function composeDecision(input: {
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  risk: RankTrendAnalysisResult['risk']
  config: RankTrendRuntimeConfig
}): RankTrendAnalysisResult['decision'] {
  const { technical, cycle, risk, config } = input
  const components = [
    {
      signal: technical.signals.direction.signal,
      rawScore: clamp(technical.signals.direction.score, -1, 1),
      weight: config.directionWeight,
    },
    {
      signal: technical.signals.acceleration.signal,
      rawScore: clamp(technical.signals.acceleration.score, -1, 1),
      weight: config.accelerationWeight,
    },
    {
      signal: technical.signals.zeroCross.signal,
      rawScore: clamp(technical.signals.zeroCross.score, -1, 1),
      weight: config.crossWeight,
    },
    {
      signal: convertCrossToSignal(technical.macd.cross),
      rawScore: clamp(technical.macd.rawScore, -1, 1),
      weight: config.macdWeight,
    },
  ]

  const combinedScore = components.reduce((sum, component) => sum + component.rawScore * component.weight, 0)
  const positiveWeight = components.reduce(
    (sum, component) => sum + component.weight * Math.max(component.rawScore, 0),
    0,
  )
  const negativeWeight = components.reduce(
    (sum, component) => sum + component.weight * Math.max(-component.rawScore, 0),
    0,
  )
  const explicitBuyCount = components.filter((component) => component.signal === 'buy').length
  const explicitSellCount = components.filter((component) => component.signal === 'sell').length

  let baseSignal: RankSignalDirection = 'hold'
  if (
    combinedScore >= config.buyScoreThreshold &&
    explicitSellCount <= 1 &&
    positiveWeight >= negativeWeight
  ) {
    baseSignal = 'buy'
  } else if (
    combinedScore <= config.sellScoreThreshold &&
    explicitBuyCount <= 1 &&
    negativeWeight >= positiveWeight
  ) {
    baseSignal = 'sell'
  }

  const signedThreshold =
    baseSignal === 'buy'
      ? config.buyScoreThreshold
      : baseSignal === 'sell'
        ? config.sellScoreThreshold
        : combinedScore >= 0
          ? config.buyScoreThreshold
          : config.sellScoreThreshold
  const thresholdScale = Math.max(0.05, Math.abs(signedThreshold))
  const scoreMargin =
    combinedScore >= 0
      ? combinedScore - config.buyScoreThreshold
      : Math.abs(combinedScore) - Math.abs(config.sellScoreThreshold)
  const margin = Math.abs(combinedScore - signedThreshold)
  const opposingWeight =
    baseSignal === 'buy'
      ? negativeWeight
      : baseSignal === 'sell'
        ? positiveWeight
        : Math.min(positiveWeight, negativeWeight)
  const agreement = clamp(1 - opposingWeight, 0, 1)
  const baseConfidence = clamp(
    50 +
      25 * Math.abs(combinedScore) +
      15 * agreement +
      10 * Math.tanh(margin / thresholdScale),
    50,
    95,
  )

  let finalSignal = baseSignal
  let finalConfidence = clamp(
    baseConfidence -
      11 * risk.overheat.severity -
      9 * risk.divergence.severity -
      5 * risk.synergy,
    50,
    95,
  )

  if (
    baseSignal === 'buy' &&
    cycle.stage === 'reversal' &&
    risk.pressure >= 0.78 &&
    risk.overheat.severity >= 0.7 &&
    scoreMargin < 0.05
  ) {
    finalSignal = 'hold'
    finalConfidence = Math.min(finalConfidence, 62)
  }

  return {
    base: {
      signal: baseSignal,
      confidence: baseConfidence,
      combinedScore,
      scoreMargin,
    },
    final: {
      signal: finalSignal,
      confidence: finalConfidence,
    },
  }
}
