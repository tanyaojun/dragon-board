import {
  DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
  RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'
import type { RankTrendLiveStrategyConfig } from '@/types/rankTrendLiveStrategy'

export function getRankTrendLiveStrategyConfig(): RankTrendLiveStrategyConfig {
  if (typeof localStorage === 'undefined') return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  const raw = localStorage.getItem(RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY)
  if (!raw) return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  try {
    return normalizeRankTrendLiveStrategyConfig(JSON.parse(raw))
  } catch {
    return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  }
}
