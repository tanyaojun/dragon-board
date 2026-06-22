import type { MergedStock } from '@/types'
import type { AlertLevel, AlertType, RotationAnalysis } from '@/types/core'
import type { ThemeCorrelationDetail } from '@/services/ThemeCorrelationAnalyzer'

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
}

export interface ThemePanelSummary {
  id: string
  name: string
  rank: number
  heatScore: number
  heatIcon: string
  heatColor: string
  heatLevel: string
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
  themeScore: number
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
  rotationAnalysis?: RotationAnalysis | null
  correlations?: Map<string, ThemeCorrelationDetail>
}

export interface ThemeExposureProjection {
  byCode: Map<string, ThemeStockExposure[]>
  byTheme: Map<string, ThemeStockExposure[]>
}

export type ThemeEventType =
  | 'theme_mainline_started'
  | 'theme_strength_surge'
  | 'theme_fund_inflow'
  | 'theme_crowding_high'
  | 'theme_cooling'
  | 'theme_leader_fall'
  | 'theme_mapping_quality_warning'

export interface ThemeEvent {
  id: string
  type: ThemeEventType
  level: AlertLevel
  themeId: string
  themeName: string
  timestamp: number
  source: 'theme'
  alertType?: AlertType
  factorSnapshotId?: string
  stockCodes: string[]
  metrics: Record<string, number | string | boolean | null>
  riskFlags: string[]
  reasons: string[]
}

export interface ThemeRuntimeSnapshot {
  factors: ThemeFactorSnapshot[]
  exposures: ThemeExposureProjection
  rotationSummary: RotationAnalysis | null
  events: ThemeEvent[]
  correlations: Map<string, ThemeCorrelationDetail>
  lastUpdate: number | null
  inputSignature?: string
  factorVersion?: string
  eventVersion?: string
  qualitySummary?: ThemeRuntimeQualitySummary
  refreshSource?: ThemeRefreshSource
  changedFields?: ThemeRuntimeChangedField[]
}

export type ThemeRefreshSource = 'ui' | 'dataLoader' | 'timer' | 'manual' | 'sectorAnalyzer' | 'rotationService' | 'test' | string

export type ThemeRuntimeChangedField =
  | 'factors'
  | 'exposures'
  | 'rotation'
  | 'events'
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
  rotationSummary: RotationAnalysis | null
  events: ThemeEvent[]
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
  emitAlerts?: boolean
  source?: ThemeRefreshSource
  syncStocks?: boolean
  context?: ThemeSourceContext
}

export interface ThemeRuntimeRefreshOptions extends ThemeRefreshOptions {
  source: ThemeRefreshSource
}
