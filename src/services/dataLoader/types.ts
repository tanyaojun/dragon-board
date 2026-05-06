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
  continue_day: number
  high_days: number
}

export interface LoadingStatus {
  active: boolean
  progress: number
  message: string
  startTime: number | null
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
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  name?: string
  sources: string[]
  confidence: number
  timestamp: number
}
