// src/types/index.ts

// 直接从 core 和 config 导入并导出
export * from './core'
export * from './config'
export * from './sector'

export type {
  AppConfig,
  SystemConfig,
  UserConfig,
  AlgorithmConfig,
  ModulesConfig,
  CacheConfig,
  DataLoaderConfig,
  RendererConfig,
  DragonBreathConfig,
  CacheItemConfig,
} from './core'

// 如果需要单独导出某些常量（保持现有导出）
export {
  // 算法相关
  DEFAULT_THRESHOLDS,
  THRESHOLD_RANGES,
  STORAGE_KEYS,

  // 龙头相关
  LEADER_LEVELS,
  LEADER_CHANGE_TYPES,

  // 因子相关
  THEME_FACTOR_IDS,
  THEME_FACTORS_META,
  BREATH_FACTOR_IDS,
  BREATH_FACTORS_META,

  // 龙息阶段相关
  MARKET_PHASES,
  DEFAULT_THRESHOLD_MULTIPLIERS,
  type MarketPhase,

  // 权重相关
  PLATFORM_WEIGHTS,
  COMPREHENSIVE_WEIGHTS,
  PENALTY_SCORE,
  DEFAULT_RANK,
  OPTIMAL_TURNOVER,
  TURNOVER_SIGMA,

  // 事件相关
  AppEvents,
} from './config'
