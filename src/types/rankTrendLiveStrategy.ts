import type { CandidateTier } from '@/services/rankTrend/types'

export type RankTrendLiveStrategyMode = 'recall_first' | 'balanced' | 'strict_execution'

export type RankTrendLiveGateMode = 'off' | 'warn' | 'block'

export type RankTrendLiveGateStatus = 'pass' | 'warn' | 'fail' | 'disabled'

export type RankTrendLiveDecisionState =
  | 'auto_add'
  | 'watch_candidate'
  | 'blocked_candidate'
  | 'not_candidate'

export interface RankTrendLiveChangeGateConfig {
  mode: RankTrendLiveGateMode
  maxEntryChangePct: number | null
}

export interface TradingPoolThresholds {
  recallJumpMin: number
  readyJumpMin: number
  observeFinalMin: number
  readyFinalMin: number
  buyVotesMin: number
  downgradeJumpMin: number
  downgradeFinalMin: number
  exitFinalSell: number
  /** Jump 方向为 hold 时，替代 jumpDirection=buy 的最低置信度补偿阈值 */
  jumpHoldMinConfidence: number
}

export interface RankTrendLiveStrategyConfig {
  version: string
  mode: RankTrendLiveStrategyMode
  minJumpConfidence: number
  allowDegradedSample: boolean
  requireCandidateTier: boolean
  allowedCandidateTiers: CandidateTier[]
  requireTierBMidAndZeroCross: boolean
  tierBMidMin: number
  accelerationMin: number
  accDeltaMin: number
  changeGate: RankTrendLiveChangeGateConfig
  limitUpPolicy: 'quote_first'
  tradingPool: TradingPoolThresholds
}

export interface RankTrendLiveGateCheck {
  key: string
  label: string
  status: RankTrendLiveGateStatus
  hardBlock: boolean
  actual: string | number | boolean | null
  expected: string
  message: string
}

export interface RankTrendLiveEntryDecision {
  decisionState: RankTrendLiveDecisionState
  accepted: boolean
  label: string
  summary: string
  firstBlockingCheck?: RankTrendLiveGateCheck
  checks: RankTrendLiveGateCheck[]
  configSnapshot: RankTrendLiveStrategyConfig
}
