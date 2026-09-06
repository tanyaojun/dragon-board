// src/types/hotlistSentiment.ts
// 热榜情绪类型契约：仅类型契约，计算在 QuantBoard 后端（GET /api/hotlist-sentiment/series）。
// 类型区从 src/services/hotlist/HotListSentimentAnalyzer.ts 原样迁移，字段不加不减。
import type { EmotionCycleStage, UnifiedEmotionStage } from './emotion'
import type { ThsLimitUpPoolEvidence } from './index'

export type HotListStatusLabel =
  | '主升确认'
  | '点火观察'
  | '强资确认'
  | '新入观察'
  | '高位拥挤'
  | '资金背离'
  | '转弱预警'
  | '样本不足'

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
  statusCounts: Record<HotListStatusLabel, number>
  statusShares: Record<HotListStatusLabel, number>
  activeOpportunityCount: number
  activeOpportunityShare: number
  opportunityCount: number
  opportunityShare: number
  riskCount: number
  riskShare: number
  crowdedCount: number
  crowdedShare: number
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
    statusSourceCounts?: { displayStatus: number; fallback: number }
    missingEvidence?: string[]
  }
  turnover: TurnoverResult
  signals: string[]
  warnings: string[]
  missing?: boolean
  reason?: string
}
