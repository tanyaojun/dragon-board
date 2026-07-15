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

// 行情刷新间隔（含基础行情 + 资金流补全）。资金流侧 Redis 缓存 60s，10s 刷新绝大部分命中缓存。
export const QUOTE_REFRESH_INTERVAL_MS = 10000
export const QUOTE_BATCH_SIZE = 50
export const PLATFORM_CACHE_TTL_MS = 1800000
export const PLATFORM_REFRESH_INTERVAL_MS = 1800000
export const MAX_PLATFORM_CACHE_SIZE = 10
export const QUOTE_BATCH_DELAY_MS = 50
export const REALTIME_FLUSH_DELAY_MS = 50
export const EASTMONEY_QUOTE_ENRICHMENT_ENABLED = true

// 东方财富/Choice 公开资金流向口径：主力 = 超大单 + 大单。
// 超大单：单笔 >= 50 万股或 >= 100 万元；大单：单笔 >= 10 万股或 >= 20 万元。
export const EASTMONEY_SUPER_ORDER_AMOUNT_THRESHOLD = 1_000_000
export const EASTMONEY_SUPER_ORDER_VOLUME_THRESHOLD = 500_000
export const EASTMONEY_LARGE_ORDER_AMOUNT_THRESHOLD = 200_000
export const EASTMONEY_LARGE_ORDER_VOLUME_THRESHOLD = 100_000

export const A_SHARE_TRADING_MINUTES = 240
export const VOLUME_RATIO_HISTORY_WEIGHTS = [5, 3, 2] as const
export const INTRADAY_VOLUME_SNAPSHOT_TYPES: IntradayVolumeSnapshotType[] = [
  'quarter_hour',
  'half_hour',
  'hourly',
]
