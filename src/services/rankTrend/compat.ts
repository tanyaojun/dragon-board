import type { RankTrendAnalysisResult } from './types'
import type { JumpResult } from './jumpDetector'
import type { JumpSignalResult } from './jumpSignalService'
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

export function applyJumpSignal(target: any, signal: JumpSignalResult): void {
  if (!target?.rankTrend) return
  target.rankTrend.jump = signal.jump
  target.rankTrend._jumpEntry = signal.isEntry
  target.rankTrend._jumpExit = signal.isExit
  target.rankTrend._jumpExitReason = signal.exitReason
}

export function getJumpResult(target: any): JumpResult | null {
  return (target?.rankTrend?.jump as JumpResult | undefined) ?? null
}

export function isJumpEntry(target: any): boolean {
  return !!(target?.rankTrend?._jumpEntry)
}

export function isJumpExit(target: any): boolean {
  return !!(target?.rankTrend?._jumpExit)
}

export function getJumpExitReason(target: any): string {
  return String(target?.rankTrend?._jumpExitReason ?? '')
}
