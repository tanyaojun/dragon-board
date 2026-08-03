import type { RankTrendAnalysisResult } from './types'
import type { JumpSignalResult } from './jumpSignalService'
import type { JumpResult } from './types'
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
  // finalSignal/finalConfidence 由 Python decision.final（已含 resonance 融合）投影，
  // 前端只读不重算；该投影覆盖所有走 applyRankTrendAnalysis 的更新路径。
  const final = rankTrend.decision?.final
  target.finalSignal = final?.signal ?? 'hold'
  target.finalConfidence = Number(final?.confidence) || 0
}

export function getRankTrendAnalysis(target: any): RankTrendAnalysisResult | null {
  return (target?.rankTrend as RankTrendAnalysisResult | undefined) ?? null
}

export function applyJumpSignal(target: any, signal: JumpSignalResult): void {
  if (!target?.rankTrend) return
  target.rankTrend.jump = { ...signal.jump, limitUp: signal.limitUp }
  target.rankTrend._jumpEntry = signal.isEntry
  target.rankTrend._jumpExit = signal.isExit
  target.rankTrend._jumpExitReason = signal.exitReason
  target.rankTrend._jumpLimitUp = signal.limitUp
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
