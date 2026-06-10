import type { CandidateTier, RankTrendAnalysisResult, RankTrendStrategyResult } from './types'

export function getExecutionStrategy(
  rankTrend: Pick<RankTrendAnalysisResult, 'strategy' | 'executionStrategy'> | null | undefined,
): RankTrendStrategyResult | undefined {
  return rankTrend?.executionStrategy
}

export function getExecutionCandidateTier(
  rankTrend: Pick<RankTrendAnalysisResult, 'strategy' | 'executionStrategy'> | null | undefined,
): CandidateTier | '' {
  return (getExecutionStrategy(rankTrend)?.candidateTier as CandidateTier | undefined) ?? ''
}
