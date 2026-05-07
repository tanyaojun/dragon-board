import type { RankTrendAnalysisResult } from './types'
export {
  buildRankTrendStatusContext,
  classifyVolumeConfirmation,
  getRankTrendDisplayBreakdown,
  getRankTrendDisplayStatus,
  type RankTrendDisplayBreakdown,
  type RankTrendDisplayStatus,
  type RankTrendStatusContext,
  type VolumeConfirmation,
} from './statusClassifier'

export function applyRankTrendAnalysis(target: any, rankTrend?: RankTrendAnalysisResult | null): void {
  if (!target) return

  if (!rankTrend) {
    target.rankTrend = undefined
    return
  }

  target.rankTrend = rankTrend
}

export function getRankTrendAnalysis(target: any): RankTrendAnalysisResult | null {
  return (target?.rankTrend as RankTrendAnalysisResult | undefined) ?? null
}
