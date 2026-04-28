import type {
  AttentionStage,
  CandidateTier,
  MarketRegimeState,
  RankTrendAnalysisResult,
  StrategyAction,
} from '@/services/rankTrend/types'
import type { RankTrendSnapshotType } from '@/type/rankTrendDefaults'

export type BacktestSnapshotType = RankTrendSnapshotType
export type BacktestHorizon = 1 | 3 | 5 | 10

export interface ReplayStock {
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

export interface ReplayMarketContext {
  marketStats?: Record<string, any> | null
  sentiment?: Record<string, any> | null
  moneyFlow?: Record<string, any> | null
  indices?: Record<string, any> | null
  limitSummary?: Record<string, any> | null
  rotationSummary?: Record<string, any> | null
  payload?: Record<string, any> | null
}

export interface ReplayFrame {
  snapshotId: string
  timestamp: number
  tradingDate: string
  slotTime: string
  type: BacktestSnapshotType
  captureMode: 'real_time' | 'delayed' | 'restored'
  stocks: ReplayStock[]
  marketContext: ReplayMarketContext
}

export interface ReplaySignal {
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

export interface ForwardOutcome {
  code: string
  entrySnapshotId: string
  horizon: BacktestHorizon
  found: boolean
  rankDelta: number | null
  percentileDelta: number | null
  priceReturn: number | null
  maxDrawdown: number | null
  stayedTop20: boolean
  stayedTop50: boolean
}

export interface BacktestMeta {
  snapshotTypeUsed: BacktestSnapshotType | null
  requestedSnapshotTypes: BacktestSnapshotType[]
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

export interface TierDistributionRow {
  key: string
  count: number
  share: number
}

export interface DailyTierDistribution {
  tradingDate: string
  total: number
  tiers: Record<CandidateTier, number>
  regimes: Record<MarketRegimeState, number>
}

export interface TierDistributionReport {
  totalSignals: number
  byTier: TierDistributionRow[]
  byStage: TierDistributionRow[]
  byRegime: TierDistributionRow[]
  daily: DailyTierDistribution[]
  weakRetreatABShare: number
  warnings: string[]
}

export interface OutcomeStats {
  groupKey: string
  sampleCount: number
  foundCount: number
  foundRate: number
  avgRankDelta: number | null
  avgPercentileDelta: number | null
  avgPriceReturn: number | null
  avgMaxDrawdown: number | null
  stayedTop20Rate: number
  stayedTop50Rate: number
}

export interface HorizonValidationReport {
  horizon: BacktestHorizon
  byTier: OutcomeStats[]
  byStage: OutcomeStats[]
  byRegime: OutcomeStats[]
  byTierStage: OutcomeStats[]
  byTierRegime: OutcomeStats[]
  byMomentumBucket: OutcomeStats[]
}

export interface ForwardValidationReport {
  horizons: HorizonValidationReport[]
  bToATransitionRate: number
  dDecayRate: number
  buyBaselineComparison: {
    horizon: BacktestHorizon
    aMain: OutcomeStats | null
    legacyBuy: OutcomeStats | null
  }[]
}

export interface TradeSimulationConfig {
  initialCapital: number
  maxPositions: number
  positionSize: number
  feeRate: number
  stampTaxRate: number
  slippageRate: number
  maxHoldingBars: number
  stopLoss: number
  takeProfit: number
}

export interface SimulatedTrade {
  code: string
  name: string
  entrySnapshotId: string
  exitSnapshotId: string
  entryTime: number
  exitTime: number
  entryPrice: number
  exitPrice: number
  quantity: number
  grossReturn: number
  netReturn: number
  profit: number
  reason: string
}

export interface EquityPoint {
  snapshotId: string
  timestamp: number
  equity: number
}

export interface TradeSimulationReport {
  enabled: boolean
  config: TradeSimulationConfig
  totalReturn: number
  maxDrawdown: number
  winRate: number
  tradeCount: number
  trades: SimulatedTrade[]
  equityHistory: EquityPoint[]
  notes: string[]
}

export interface StrategyBacktestReport {
  meta: BacktestMeta
  distribution: TierDistributionReport
  forwardValidation: ForwardValidationReport
  tradeSimulation?: TradeSimulationReport
}

export interface StrategyBacktestRunOptions {
  snapshotTypes?: BacktestSnapshotType[]
  startDate?: string
  endDate?: string
  warmupCount?: number
  horizons?: BacktestHorizon[]
  enableTradeSimulation?: boolean
  tradeConfig?: Partial<TradeSimulationConfig>
}

export interface ValidateLatestOptions {
  days?: number
  snapshotType?: BacktestSnapshotType
}

export interface LoadedReplayFrames {
  frames: ReplayFrame[]
  meta: BacktestMeta
}

export interface ReplayEngineOptions {
  warmupCount?: number
  windowSize?: number
  meta: BacktestMeta
}
