import type { RankTrendSnapshotType } from '../../types/rankTrendDefaults'

export type RankSignalDirection = 'buy' | 'sell' | 'hold'
export type RankSignalDirectionWithNone = RankSignalDirection | 'none'
export type MacdCross = 'golden' | 'death' | 'none'

export type AttentionStage =
  | 'ignition'
  | 'expansion'
  | 'crowded'
  | 'reversal'
  | 'cooling'

export type CycleEntryBias = 'preferred' | 'watch' | 'avoid' | 'blocked'
export type LifecycleDecisionAction = 'allow' | 'caution' | 'veto' | 'exit_watch'
export type LifecycleDiscoveryAction = 'none' | 'research_watch'
export type MarketRegimeState = 'strong' | 'normal' | 'weak' | 'retreat'
export type CandidateTier = 'A_MAIN' | 'B_IGNITION' | 'C_CROWDED' | 'D_EXIT_RISK' | 'N_NEUTRAL'
export type StrategyAction = 'focus' | 'watch' | 'hold' | 'avoid' | 'exit_watch'

export interface RankTrendMomentumProfile {
  short: number
  mid: number
  long: number
  acceleration: number
  shock: number
  composite: number
}

export interface MarketRegimeAnalysis {
  state: MarketRegimeState
  score: number
  reasons: string[]
}

export interface RankTrendStrategyResult {
  regime: MarketRegimeAnalysis
  hotlist?: {
    state: 'missing' | 'present'
    stage?: string | null
    riskLevel?: string | null
    confidence?: unknown
  }
  momentum: RankTrendMomentumProfile
  candidateTier: CandidateTier
  action: StrategyAction
  reasons: string[]
}

export interface RankTrendRuntimeConfig {
  momentumPeriods: number[]
  momentumWeights: number[]
  buyThresholds: number[]
  sellThresholds: number[]
  macdFast: number
  macdSlow: number
  macdSignal: number
  directionWeight: number
  accelerationWeight: number
  crossWeight: number
  macdWeight: number
  buyScoreThreshold: number
  sellScoreThreshold: number
}

export interface RankTrendSignalScore {
  signal: RankSignalDirection
  confidence: number
  score: number
}

export interface RankTrendResonance {
  status: 'ok' | 'insufficient'
  direction: RankSignalDirection
  score: number
  label: '非常强' | '强' | '中等' | '较弱' | '非常弱' | '样本不足'
  relativeMomentum: number
  acceleration: number
  persistence: number
  jumpFreshness: number
  reversalPenalty: number
  historyState: 'established' | 'new_entry'
  marketMedianShortChange: number
  reasons: string[]
}

export interface RankTrendAnalysisResult {
  meta: {
    code: string
    currentRank: number
    currentPercentile: number
    change: number
    rawChange: number
    updateTime: number
    sampleQuality?: {
      snapshotType: RankTrendSnapshotType
      sampleCount: number
      requiredSampleCount: number
      status: 'ok' | 'degraded' | 'insufficient'
      coverageWarning?: string
      latestTradingDate?: string
      latestSlotTime?: string
      delayedCount: number
      restoredCount: number
    }
  }
  technical: {
    movingAverage: {
      ma5: number
      ma10: number
      trend: 'up' | 'down' | 'steady'
    }
    macd: {
      dif: number
      dea: number
      histogram: number
      cross: MacdCross
      rawScore: number
      confirmed: boolean
    }
    signals: {
      direction: RankTrendSignalScore
      acceleration: RankTrendSignalScore
      zeroCross: RankTrendSignalScore
    }
    momentumScore: number
    momentumProfile: RankTrendMomentumProfile
  }
  cycle: {
    rawStage: AttentionStage
    stage: AttentionStage
    previousStage: AttentionStage | null
    transition: string
    confidence: number
    metrics: {
      rankVelocity: number
      rankAcceleration: number
      rankShock: number
      hotZoneStreak: number
      bestRecentRank: number
      drawdownFromPeak: number
      rankPathCommitment: number
    }
    entryAdvice: {
      bias: CycleEntryBias
      allowed: boolean
      reason: string
    }
    decision: {
      action: LifecycleDecisionAction
      confidence: number
      reasons: string[]
      discovery: {
        action: LifecycleDiscoveryAction
        reasons: string[]
      }
      evidence: {
        rawStage: AttentionStage
        stage: AttentionStage
        transition: string
        rankVelocity: number
        rankAcceleration: number
        drawdownFromPeak: number
        hotZoneStreak: number
        rankPathCommitment: number
        momentumShort: number
        momentumMid: number
        momentumLong: number
        momentumAcceleration: number
        riskPressure: number
        divergenceSeverity: number
        overheatSeverity: number
      }
    }
  }
  risk: {
    overheat: {
      score: number
      signal: RankSignalDirection
      severity: number
    }
    divergence: {
      score: number
      signal: RankSignalDirection
      severity: number
    }
    pressure: number
    synergy: number
  }
  decision: {
    base: {
      signal: RankSignalDirection
      confidence: number
      combinedScore: number
      scoreMargin: number
    }
    final: {
      signal: RankSignalDirection
      confidence: number
    }
  }
  jump?: {
    event?: 'jump' | 'none'
    direction: 'buy' | 'sell' | 'hold'
    confidence: number
    limitUp?: boolean
    events?: Array<{
      index: number
      direction: 'surge' | 'collapse'
      magnitude: number
    }>
  }
  resonance?: RankTrendResonance
  // 策略层结果是消费侧扩展，不属于 rankTrend 核心分析合同。
  strategy?: RankTrendStrategyResult
  // V5 执行层分层，镜像 Python candidateTierMode=execution 的热榜情绪融合语义。
  executionStrategy?: RankTrendStrategyResult
}

export const ATTENTION_STAGE_SEQUENCE: AttentionStage[] = [
  'ignition',
  'expansion',
  'crowded',
  'reversal',
  'cooling',
]
