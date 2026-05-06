import type { IntradayVolumeSnapshotType } from './types'

export const DEFAULT_PLATFORMS = [
  'eastmoney',
  'ths',
  'kpl',
  'tdx',
  'xueqiu',
  'cls',
  'tgb',
  'dzh',
] as const

export const QUOTE_REFRESH_INTERVAL_MS = 30000
export const QUOTE_BATCH_SIZE = 50
export const PLATFORM_CACHE_TTL_MS = 1800000
export const PLATFORM_REFRESH_INTERVAL_MS = 1800000
export const MAX_PLATFORM_CACHE_SIZE = 10
export const QUOTE_BATCH_DELAY_MS = 50
export const REALTIME_FLUSH_DELAY_MS = 50
export const EASTMONEY_QUOTE_ENRICHMENT_ENABLED = false

export const SUPER_ORDER_AMOUNT_THRESHOLD = 1_000_000
export const SUPER_ORDER_VOLUME_THRESHOLD = 500_000
export const LARGE_ORDER_AMOUNT_THRESHOLD = 200_000
export const LARGE_ORDER_VOLUME_THRESHOLD = 100_000

export const MAX_ESTIMATED_MAIN_RATIO = 0.28
export const MAX_ESTIMATED_SUPER_RATIO = 0.16
export const MAX_ACTIVE_MONEY_FLOW_RATIO = 0.32

export const A_SHARE_TRADING_MINUTES = 240
export const VOLUME_RATIO_HISTORY_WEIGHTS = [5, 3, 2] as const
export const INTRADAY_VOLUME_SNAPSHOT_TYPES: IntradayVolumeSnapshotType[] = [
  'quarter_hour',
  'half_hour',
  'hourly',
]
