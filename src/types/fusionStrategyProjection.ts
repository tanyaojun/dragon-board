import type { CandidateTier, LifecycleDecisionAction } from '@/services/rankTrend/types'

export type FusionSnapshotType = 'half_hour' | 'quarter_hour'

export type FusionStrategyState =
  | 'idle'
  | 'triggered_wait_entry'
  | 'active_holding'
  | 'exit_signaled'
  | 'closed'

export interface FusionExecutionOverlay {
  executed: boolean
  entryId?: string
  entryPrice?: number
  entryTime?: string
  exitPrice?: number
  exitTime?: string
  stopLossPrice?: number
  takeProfitPrice?: number
  positionPct?: number
  reviewOutcome?: string
  executionResult?: string
  reviewNotes?: string
}

export interface FusionStrategyProjection {
  stockCode: string
  stockName: string
  strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion'
  snapshotType: FusionSnapshotType
  tradingDate: string
  snapshotId: string
  frameTime: string
  projectionSource: 'live' | 'backtest'
  strategyState: FusionStrategyState
  candidateTier: CandidateTier
  lifecycleAction: LifecycleDecisionAction
  triggerAt?: string
  strategyEntryAt?: string
  strategyExitAt?: string
  holdingBars?: number
  slotIndex?: number
  maxPositions?: number
  tPlusOneUnlocked?: boolean
  entryReason?: string
  exitReason?: string
  strategyEntryPrice?: number
  strategyExitPrice?: number
  strategyReturnPct?: number
  executionOverlay?: FusionExecutionOverlay | null
}
