import type { RankTrendAnalysisResult } from '../rankTrend/types'

export interface LoaderState {
  initialized: boolean
  platforms: string[]
  data: Record<string, any[]>
  loading: boolean
  loadingProgress: number
  loadingMessage: string
  lastUpdate: number | null
}

export interface LimitUpItem {
  code: string
  reason_type: string
  is_new: number
  first_limit_up_time: string
  last_limit_up_time: string
  continue_day: number | null
  high_days: number | string | null
  high_days_value?: number | string | null
}

export interface LoadingStatus {
  active: boolean
  progress: number
  message: string
  startTime: number | null
  phase?: 'cache' | 'platform' | 'quote' | 'merge' | 'signal' | 'done' | 'error'
}

export interface PlatformLoadProgress {
  completed: number
  total: number
  platform: string
}

export interface QuoteBatchProgress {
  source: 'tencent' | 'sina' | 'eastmoney'
  completedBatches: number
  totalBatches: number
  completedCodes: number
  totalCodes: number
}

export interface DataLoaderRunSummary {
  stockCount: number
  platformCount: number
  fromCache: boolean
  elapsedMs: number
  timings?: Record<string, number>
  startupCache?: {
    hit: boolean
    stale?: boolean
    ageMs?: number
    backgroundRefresh?: boolean
  }
}

export interface DataLoaderBootstrapOptions {
  force?: boolean
}

export interface DataLoaderRefreshOptions {
  force?: boolean
  source?: 'manual' | 'timer' | 'startup'
}

export interface StockSignalUpdate {
  code: string
  rankTrend?: RankTrendAnalysisResult | null
  coverageWarning?: string | null
}

export type IntradayVolumeSnapshotType = 'quarter_hour' | 'half_hour' | 'hourly'

export interface IntradayMoneyFlowStats {
  tradingDate: string
  activeAmount: number
  mainNet: number
  superNet: number
}

export interface MergedQuoteData {
  price: number
  change: number
  speed?: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  totalMV: number
  cirMV: number
  pb: number
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  capitalFlowSource?: 'broker_l2' | 'official_l2' | 'estimated_l1' | string
  capitalFlowConfidence?: 'high' | 'medium' | 'low' | string
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  name?: string
  sources: string[]
  confidence: number
  timestamp: number
}
