import type {
  AttentionStage,
  CandidateTier,
  MarketRegimeState,
  RankTrendAnalysisResult,
  StrategyAction,
} from '@/services/rankTrend/types'
import type { RankTrendSnapshotType } from '@/type/rankTrendDefaults'

export type GoldenSnapshotType = RankTrendSnapshotType

export interface GoldenReplayStock {
  code: string
  name: string
  rank: number
  price?: number
  change?: number
  volumeRatio?: number
  zlje?: number
  zljzb?: number
  turnoverRate?: number
  themes?: Array<{ id?: string; name?: string; heatScore?: number }>
  finalSignal?: string
  finalConfidence?: number
  [key: string]: any
}

export interface GoldenReplayMarketContext {
  marketStats?: Record<string, any> | null
  sentiment?: Record<string, any> | null
  moneyFlow?: Record<string, any> | null
  indices?: Record<string, any> | null
  limitSummary?: Record<string, any> | null
  rotationSummary?: Record<string, any> | null
  payload?: Record<string, any> | null
}

export interface GoldenReplayFrame {
  snapshotId: string
  timestamp: number
  tradingDate: string
  slotTime: string
  type: GoldenSnapshotType
  captureMode: 'real_time' | 'delayed' | 'restored'
  stocks: GoldenReplayStock[]
  marketContext: GoldenReplayMarketContext
}

export interface GoldenReplaySignal {
  snapshotId: string
  timestamp: number
  tradingDate: string
  slotTime: string
  code: string
  name: string
  rank: number
  price: number | null
  rankTrend: RankTrendAnalysisResult
  candidateTier: CandidateTier
  action: StrategyAction
  stage: AttentionStage
  regime: MarketRegimeState
  confidence: number
}

export interface GoldenReplayMeta {
  snapshotTypeUsed: GoldenSnapshotType | null
  requestedSnapshotTypes: GoldenSnapshotType[]
  snapshotCount: number
  tradingDateCount: number
  tradingDateRange: { start: string | null; end: string | null }
  delayedCount: number
  restoredCount: number
  emptyHotlistCount: number
  lowHotlistCount: number
  sampleQuality: 'ok' | 'degraded' | 'insufficient'
  featureCoverage: 'full' | 'partial'
  warnings: string[]
  generatedAt: number
}

export interface GoldenReplayOptions {
  warmupCount?: number
  windowSize?: number
  maxSignals?: number
  meta: GoldenReplayMeta
}
