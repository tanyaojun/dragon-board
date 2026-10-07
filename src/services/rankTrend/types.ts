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
  /** MA 均线交叉第 5 决策分量权重（2026-09-13 五因子化；0 = 显式关闭） */
  maWeight: number
  buyScoreThreshold: number
  sellScoreThreshold: number
}

export interface RankTrendSignalScore {
  signal: RankSignalDirection
  confidence: number
  score: number
}

/** 投票维观察信号离散档位（后端 Python golden 生产，前端只消费；unknown=样本不足/数据缺失） */
export type RankTrendSignalTier = 'S' | 'A' | 'B' | 'C' | 'D' | 'E' | 'unknown'

/** 档位命中规则原文（后端 tierReasons） */
export type RankTrendTierReasons = string[]

export interface RankTrendObservationScores {
  rankTrend: {
    direction: RankSignalDirection
    score: number
    signedScore: number
    signalTier?: RankTrendSignalTier
    tierReasons?: RankTrendTierReasons
  }
  // 生命周期轨可独立降级：未达可算窗口时由观察服务移除该字段并给出结构化原因
  lifecycle?: {
    stage: AttentionStage
    score: number
    veto: boolean
    reasons: string[]
    signalTier?: RankTrendSignalTier
    tierReasons?: RankTrendTierReasons
    factors: {
      stageFitness: number
      pathCommitment: number
      momentumConfirmation: number
      riskSafety: number
    }
  }
  // 量价协同轴（阶段 2）：后端生产，前端只消费
  volumePrice?: RankTrendVolumePrice
  synergy?: RankTrendSynergy
  // 横截面相对强弱（2026-08-18 阶段 11 G2，第 5 维投票默认打开；tooltip 展示）
  crossSection?: RankTrendCrossSection
}

/** 横截面相对强弱（后端 Python compute_cross_section 产出，2026-08-18） */
export interface RankTrendCrossSection {
  percentile: number | null
  percentileDelta: number | null
  relativeToMarket: number | null
  signalTier?: RankTrendSignalTier
  tierReasons?: RankTrendTierReasons
}

/** 量价评分（后端 Python compute_volume_price_score 产出，0-100） */
export interface RankTrendVolumePrice {
  score: number | null
  direction: 'up' | 'down' | 'neutral' | null
  quadrant: 'rise_volume' | 'rise_shrink' | 'fall_volume' | 'fall_shrink' | 'normal' | null
  reasons: string[]
  breakdown?: { direction: number; volume: number; fund: number }
  signalTier?: RankTrendSignalTier
  tierReasons?: RankTrendTierReasons
}

/** 四象协同状态（阶段 × 量价 为主，技术/共振协同） */
export interface RankTrendSynergy {
  state: '启动确认' | '主升确认' | '风险升级' | '退潮' | '存疑' | 'noData'
  hardWarn: boolean
  reasons: string[]
  signalTier?: RankTrendSignalTier
  tierReasons?: RankTrendTierReasons
}

export interface RankTrendThemeResonance {
  /** @deprecated 2026-08-06 题材动量不再并入共振（D2），仅迁移期兼容 */
  status: 'ok' | 'insufficient'
  themeId?: string
  themeName?: string
  role?: 'leader' | 'core' | 'follower' | 'independent' | 'noise'
  roleWeight?: number
  themeMomentumScore?: number
  themeMomentumDirection?: 'buy' | 'sell' | 'hold'
  themeLifecycle?: string
  themeContribution?: number
  adjustment?: number
  reasons: string[]
}

/** 题材动量 v2 每股只读投影（第4轨数据源，不参与 decision） */
export interface RankTrendThemeMomentum {
  status: 'ok' | 'insufficient'
  themeId?: string
  themeName?: string
  score?: number
  direction?: 'up' | 'neutral' | 'down'
  role?: string
  phaseLabel?: string
  reasons?: string[]
}

export interface RankTrendResonance {
  status: 'ok' | 'insufficient'
  direction: RankSignalDirection
  score: number
  /** 量价修正前原始排名动量分（阶段 2，后端保留，面板对比用） */
  rawScore?: number
  label: '非常强' | '强' | '中等' | '较弱' | '非常弱' | '样本不足'
  relativeMomentum: number
  acceleration: number
  persistence: number
  jumpFreshness: number
  reversalPenalty: number
  historyState: 'established' | 'new_entry'
  marketMedianShortChange: number
  marketSampleCount?: number
  marketMedianPercentile?: number
  baseScore?: number // 调节前原始共振分数（Python 融合输出，供审计与前端对比）
  theme?: RankTrendThemeResonance
  reasons: string[]
  /** 前端挂 stock.rankTrend.resonance，对应后端 analysis.resonance 顶层字段（组装下沉后生产） */
  signalTier?: RankTrendSignalTier
  tierReasons?: RankTrendTierReasons
}

export interface JumpEvent {
  index: number
  /**
   * 'surge' 上冲 / 'collapse' 下坠；'hold' = 跳动未获价格/量能确认后的同步降级
   * （后端 _confirm_jump P0-1：events 与外层 direction 口径必须一致，2026-08-19）。
   */
  direction: 'surge' | 'collapse' | 'hold'
  magnitude: number
}

export interface JumpResult {
  event: 'jump' | 'none'
  direction: 'buy' | 'sell' | 'hold'
  signal: 'buy' | 'sell' | 'hold'
  magnitude: number
  overshoot: number
  delta: number
  sustained: boolean
  confidence: number
  eventCount: number
  surgeCount: number
  collapseCount: number
  rankMagnitude: number
  cumulativeChange?: number
  events: JumpEvent[]
}

export interface RankTrendAnalysisResult {
  meta: {
    code: string
    currentRank: number
    currentPercentile: number
    change: number
    rawChange: number
    updateTime: number
    analysisSource?: 'py_golden' | 'analysis_unavailable'
    analysisUnavailableReason?: string
    /**
     * G3（2026-08-23 前后端分离）：后端 golden 生产的全市场量能分位
     * （turnover/volumeRatio/turnoverRate 的 P50/70/85），供 statusClassifier 量能判定。
     * 后端未提供（旧缓存/离线）时缺省，前端回退自算/兜底。
     */
    marketPercentiles?: Record<string, number>
    /**
     * current_frame 实时综合排名（2026-09-22 用户裁决：列表均榜/综合实时口径）。
     * 后端 analyze 对 current 帧行实时算五维综合评分与均榜（与采集入库同公式）；
     * 帧池 golden（快照行 compRank/avgRankNum）降级为历史回溯兜底。
     * 仅实时 analyze 响应携带；snapshot_analysis 落库产物与历史帧查询不含。
     */
    liveRanking?: {
      compScore?: number | null
      compRank?: number | null
      avgRankNum?: number | null
      platforms?: number | null
    }
    sampleQuality?: {
      snapshotType: RankTrendSnapshotType
      sampleCount: number
      requiredSampleCount: number
      status: 'ok' | 'degraded' | 'insufficient'
      timelineValid?: boolean
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
    /** MA10×MA20 排名百分位金死叉（2026-09-13 五因子化 additive 字段；py golden 生产）
     *  fast/slow=null 表示样本不足；rawScore 仅在交叉帧取 ±1，其余帧 0 */
    maCross?: {
      fast: number | null
      slow: number | null
      state: 'bull' | 'bear' | 'flat' | 'unknown'
      cross: 'golden' | 'death' | 'none'
      rawScore: number
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
      rankVelocity: number | null
      rankAcceleration: number | null
      rankShock: number | null
      hotZoneStreak: number
      bestRecentRank: number
      drawdownFromPeak: number
      rankPathCommitment: number
      /** P3 时间正规化（2026-10-07 G1 落默认）：跨日缺口帧动量证据缺失标记 */
      temporalGap?: boolean
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
        rankVelocity: number | null
        rankAcceleration: number | null
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
    magnitude?: number
    confidence: number
    limitUp?: boolean
    events?: Array<{
      index: number
      /** 同 JumpEvent.direction：'hold' 为未确认降级态 */
      direction: 'surge' | 'collapse' | 'hold'
      magnitude: number
    }>
  }
  resonance?: RankTrendResonance
  /** 题材动量 v2 每股只读投影（第4轨数据源，不参与 decision） */
  themeMomentum?: RankTrendThemeMomentum
  observation?: RankTrendObservationScores
  // 策略层结果是消费侧扩展，不属于 rankTrend 核心分析合同。
  strategy?: RankTrendStrategyResult
  // V5 执行层分层，镜像 Python candidateTierMode=execution 的热榜情绪融合语义。
  executionStrategy?: RankTrendStrategyResult
  /**
   * 展示状态（2026-09-10 口径统一）：后端 Python `compute_display_status` 生产
   * （lifecycle.stage 主轴），前端只消费不分类；缺失（旧缓存/离线）时 statusClassifier
   * 返回结构化未知态。
   *
   * 注意：与 `apiService.SnapshotAnalysisEntry.displayStatus` 是同形状的**两处定义**
   * （后者三字段全可选，供 `/api/snapshots/analysis` 读口）。将来把
   * `loadSnapshotAnalysis` 接进 `stock.rankTrend` 时必须复用同一类型，避免丢字段。
   */
  displayStatus?: RankTrendDisplayStatus
}

/**
 * 后端 displayStatus 三字段投影（单一来源：`compute_display_status`，2026-09-10 spec §3）。
 * 前端只消费，不自维护词表（历史教训：本目录曾有自己的 CYCLE_LABELS 用"降温"，
 * 而 DataTable 用"冷却"，同一状态两套词）。
 */
export interface RankTrendDisplayStatus {
  /** 生命周期 5 态之一；缺失/非法为 `null`（此时 label 为"无阶段"）。 */
  stage: string | null
  /** `stage` 的展示词（后端 `STAGE_LABELS`）；`stage` 为 `null` 时为"无阶段"。 */
  label: string
  tooltip: string
}

export const ATTENTION_STAGE_SEQUENCE: AttentionStage[] = [
  'ignition',
  'expansion',
  'crowded',
  'reversal',
  'cooling',
]
