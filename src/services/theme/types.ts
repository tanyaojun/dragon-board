import type { MergedStock } from '@/types'

export type ThemeRotationState = 'mainline' | 'inflow' | 'outflow' | 'quick' | 'cooling' | 'neutral'

export type ThemeQualityFlagCode =
  | 'empty_theme'
  | 'low_sample'
  | 'mapping_missing'
  | 'invalid_number'
  | 'time_disorder'
  | 'quote_coverage_partial'
  | 'theme_quote_coverage_low'
  | 'quote_stale'
  | 'fund_flow_partial'
  | 'fund_flow_unavailable'
  | 'source_time_skew'
  | 'persistence_history_insufficient'

export interface ThemeQualityFlag {
  code: ThemeQualityFlagCode
  level: 'fatal' | 'warning' | 'info'
  message: string
  count?: number
}

export interface ThemeBaseLike {
  id: string
  name: string
  zsCode?: string
}

export interface ThemeFactorComponents {
  breadthScore: number
  fundScore: number | null
  leadershipScore: number
  correlationScore: number
  riskPenalty: number
}

export type ThemeFactorSource = 'static' | 'mixed' | 'market_aggregate'

export interface ThemeFactorSnapshot {
  themeId: string
  themeName: string
  source: ThemeFactorSource
  snapshotId?: string
  timestamp: number
  heatScore: number
  /** 0-100 rank 百分位相对分（2026-09 口径迁移）；null = 热度缺失，不伪装 0 */
  heatLevel: number | null
  momentumScore: number
  breadthScore: number
  fundScore: number | null
  leadershipScore: number
  correlationScore: number
  crowdingRisk: number
  persistenceScore: number
  rotationState: ThemeRotationState
  stockCount: number
  ztCount: number
  leaderCount: number
  netInflow: number | null
  strength: number
  volumeRatio: number
  rank: number
  relatedThemeIds: string[]
  qualityFlags: ThemeQualityFlag[]
  components: ThemeFactorComponents
}

export type ThemeStockRole = 'leader' | 'core' | 'follower' | 'independent' | 'noise'

export interface ThemeHeatApiFactor
  extends Omit<ThemeFactorSnapshot, 'heatScore' | 'fundScore' | 'netInflow'> {
  heatScore: number | null
  heatLevel: number | null
  fundScore: number | null
  netInflow?: number | null
  mainNetInflow: number | null
  rankEligible: boolean
  degraded: boolean
  metadata: Record<string, unknown>
}

export interface ThemeHeatStock {
  code: string
  name: string
  change: number
  price: number
  volumeRatio: number | null
  mainNetInflow: number | null
  turnoverRate: number | null
  rank: number
  role: ThemeStockRole
  qualityFlags: ThemeQualityFlag[]
  /** 涨停池扩展字段：由 enrichStocksWithLimitUp 从 DataLayer 涨停池数据合入，非涨停股保持缺失 */
  lianbanStr?: string
  boardHeight?: number
  firstZtTime?: string
  lastZtTime?: string
  fengdan?: number
  openNum?: number
  reason?: string
}

export interface ThemePanelSummary {
  id: string
  name: string
  rank: number
  heatScore: number
  heatIcon: string
  heatColor: string
  heatLevel: string
  /** 0-100 相对分；null = 热度缺失（12 处阈值消费点统一输入） */
  heatLevelScore: number | null
  momentumScore: number
  breadthScore: number
  fundScore: number | null
  leadershipScore: number
  correlationScore: number
  crowdingRisk: number
  stockCount: number
  ztCount: number
  leaderCount: number
  mainNetInflow: number | null
  volumeRatio: number | null
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  strength: number
  rotationState: ThemeRotationState
  lastUpdate: number
  qualityFlags: ThemeQualityFlag[]
  degraded: boolean
}

export interface ThemeHeatApiSnapshot {
  computedAt: number
  cacheBucket: string
  factorVersion: string
  mappingVersion: string
  factors: ThemeHeatApiFactor[]
  quality: Record<string, unknown>
  sources: Record<string, unknown>
}

export interface ThemeStockExposure {
  code: string
  themeId: string
  themeName: string
  exposureWeight: number
  source: 'static' | 'realtime' | 'mixed'
  /** = 主导 factor 的 heatLevel 相对分；null = 热度缺失，不伪装 0 */
  themeScore: number | null
  role: ThemeStockRole
  roleScore: number
  themeContribution: number
  riskPenalty: number
  reasons: string[]
  qualityFlags: ThemeQualityFlag[]
}

export interface ThemeSourceContext {
  timestamp?: number
  snapshotId?: string
  themes: ThemeBaseLike[]
  themeStocks: Map<string, string[]>
  stockThemes: Map<string, string[]>
  stocks: Array<Partial<MergedStock> & { code: string; name?: string }>
}

export interface ThemeExposureProjection {
  byCode: Map<string, ThemeStockExposure[]>
  byTheme: Map<string, ThemeStockExposure[]>
}

export interface ThemeRuntimeSnapshot {
  factors: ThemeFactorSnapshot[]
  exposures: ThemeExposureProjection
  lastUpdate: number | null
  inputSignature?: string
  factorVersion?: string
  qualitySummary?: ThemeRuntimeQualitySummary
  refreshSource?: ThemeRefreshSource
  changedFields?: ThemeRuntimeChangedField[]
}

export type ThemeRefreshSource = 'ui' | 'dataLoader' | 'timer' | 'manual' | 'sectorAnalyzer' | 'themeRuntime' | 'test' | string

export type ThemeRuntimeChangedField =
  | 'factors'
  | 'exposures'
  | 'quality'
  | 'stocks'

export interface ThemeRuntimeQualitySummary {
  totalFlags: number
  fatalCount: number
  warningCount: number
  infoCount: number
  byCode: Partial<Record<ThemeQualityFlagCode, number>>
}

export interface ThemeRuntimeRefreshResult {
  factors: ThemeFactorSnapshot[]
  exposures: ThemeExposureProjection
  qualitySummary: ThemeRuntimeQualitySummary
  changedFields: ThemeRuntimeChangedField[]
  inputSignature: string
  source: ThemeRefreshSource
  timestamp: number
  syncedStockCount: number
}

export interface ThemeRefreshOptions {
  timestamp?: number
  snapshotId?: string
  force?: boolean
  source?: ThemeRefreshSource
  syncStocks?: boolean
  context?: ThemeSourceContext
}

export interface ThemeRuntimeRefreshOptions extends ThemeRefreshOptions {
  source: ThemeRefreshSource
}
