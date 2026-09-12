// src/types/hotlistSentiment.ts
// 热榜情绪类型契约：仅类型契约，计算在 QuantBoard 后端（GET /api/hotlist-sentiment/series）。
// 类型区与后端 backend/analysis/hotlist/sentiment.py 输出契约保持一致，字段不加不减。
import type { EmotionCycleStage, UnifiedEmotionStage } from './emotion'
import type { ThsLimitUpPoolEvidence } from './index'

/**
 * 全池状态结构键：生命周期 5 态 + 阶段缺失（无阶段）。
 *
 * 2026-09-10 口径统一（spec §10）：8 类展示分类层已删除，分布锚定 `cycle.stage` 黄金真值。
 * 不再使用 8 类 label（主升确认/点火观察/强资确认/新入观察/高位拥挤/资金背离/转弱预警/样本不足）。
 */
export type HotListStageKey = 'ignition' | 'expansion' | 'crowded' | 'reversal' | 'cooling' | 'unknown'

/** 5 态 + 无阶段的展示词（与后端 `STAGE_LABELS` / `STAGE_UNKNOWN_LABEL` 逐字一致）。 */
export const HOT_LIST_STAGE_LABELS: Record<HotListStageKey, string> = {
  ignition: '点火',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '冷却',
  unknown: '无阶段',
}

export interface HotListDayMetrics {
  tradingDate?: string
  total: number
  topN: number
  upCount: number
  downCount: number
  flatCount: number
  upRatio: number
  downRatio: number
  hotTrin: number | null
  totalTurnover: number
  upTurnover: number
  downTurnover: number
  mainNetAmount: number
  superNetAmount: number
  avgChange: number
  nearLimitUpCount: number
  highGainCount: number
  highTurnoverCount: number
  /** 全池状态分布：生命周期 5 态 + 无阶段（2026-09-10 替代原 8 类 statusCounts，spec §4）。 */
  stageCounts: Record<HotListStageKey, number>
  stageShares: Record<HotListStageKey, number>
}

export type HotListLayerKey = 'top20' | 'top50' | 'top100' | 'all'

export type HotListLayerSet = Record<HotListLayerKey, HotListDayMetrics>

export interface TurnoverEntryDetail {
  code: string
  name: string
  rank: number
  changePct: number
  entryReason: 'limit_up' | 'strong_money' | 'rank_surge' | 'new_high_volume'
}

export interface TurnoverExitDetail {
  code: string
  name: string
  rank: number
  changePct: number
  exitReason: 'rank_out_of_range' | 'weakening' | 'limit_down'
}

export interface TurnoverResult {
  previousPoolSize: number
  currentPoolSize: number
  retainedFromYesterday: number
  newEntries: string[]
  eliminated: string[]
  newEntryDetails: TurnoverEntryDetail[]
  eliminatedDetails: TurnoverExitDetail[]
}

export interface HotListYesterdayStrongPerformance {
  count: number
  matchedCount: number
  retainedTop100Count: number
  avgChange: number | null
  positiveCount: number
  positiveRate: number | null
  weakeningCount: number
  weakeningRate: number | null
}

export interface HotListThreeDayComparison {
  today: HotListDayMetrics
  yesterday?: HotListDayMetrics
  dayBefore?: HotListDayMetrics
  totalChange1d: number | null
  totalChange2d: number | null
  top100RetainFromYesterday: number
  top100RetainFromDayBefore: number
  top100RetainRateFromYesterday: number
  top100RetainRateFromDayBefore: number
  newTop100Count: number
  newTop100StrongMoneyCount: number
  yesterdayStrongRetainRate: number | null
  yesterdayCrowdedRiskCount: number
  yesterdayStrongPerformance: HotListYesterdayStrongPerformance
}

export interface HotListLimitMarketEvidence {
  ztCount: number
  zhabanCount: number
  fengbanRate: number
  board1: number
  board2: number
  board3: number
  board4Plus: number
  maxContinuousDays: number
  thsPools: ThsLimitUpPoolEvidence
}

export interface HotListLimitIntersectionEvidence {
  top20LimitUpCount: number
  top50LimitUpCount: number
  top100LimitUpCount: number
  top100LimitUpShare: number
  top100NearLimitUpCount: number
  top100Board2PlusCount: number
  top100MaxBoardHeight: number
  top100ZhabanCount: number
  top100ZhabanShare: number
}

export interface HotListYesterdayHotLimitEvidence {
  count: number
  retainedTop100Count: number
  avgChange: number | null
  positiveRate: number | null
  weakeningRate: number | null
  failedOrWeakRate: number | null
}

export interface HotListLimitEvidence {
  market: HotListLimitMarketEvidence
  intersection: HotListLimitIntersectionEvidence
  yesterdayHotLimit: HotListYesterdayHotLimitEvidence
}

export interface HotListSentimentMetrics {
  topN: number
  layers: HotListLayerSet
  comparison: HotListThreeDayComparison
  limitEvidence: HotListLimitEvidence
}

export type HotListSentimentRiskLevel = '低' | '中' | '高'

export interface HotListSentimentResult {
  stage: EmotionCycleStage
  riskLevel: HotListSentimentRiskLevel
  confidence: number
  summary: string
  metrics: HotListSentimentMetrics
  turnover: TurnoverResult
  signals: string[]
  warnings: string[]
}

export interface HotListSentimentDayDoc {
  datasetId: string
  snapshotType: string
  tradingDate: string
  snapshotId?: string
  slotTime?: string
  timestamp?: number
  stage: UnifiedEmotionStage
  riskLevel: HotListSentimentRiskLevel
  confidence: number
  summary: string
  metrics: HotListSentimentMetrics & {
    poolSize?: number
    allPoolUpRatio?: number
    retentionRate1d?: number | null
    retentionRate2d?: number | null
    limitIntersectionRate?: number
    newEntryCount?: number
    eliminatedCount?: number
    /** 状态来源：金标投影命中 / fallback 接管（阶段缺失已并入「无阶段」格，无独立计数） */
    statusSourceCounts?: { displayStatus: number; fallback: number }
    missingEvidence?: string[]
  }
  turnover: TurnoverResult
  signals: string[]
  warnings: string[]
  missing?: boolean
  reason?: string
}
