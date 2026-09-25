// src/types/index.ts

// 直接从 core 和 config 导入并导出
export * from './core'
export * from './config'
export * from './sector'
export * from './board'
export * from './rankTrendDefaults'
export type {
  DataState,
  DataVersion,
  LeaderLookupRecord,
  LimitUpExtData,
  ListPoolProvenance,
  ListPoolSource,
  MergedStock,
  StockExtData,
  ThemeMetrics as DataLayerThemeMetrics,
} from './data-layer'
export type {
  Factor,
  FactorConfig,
  LeaderThresholds,
  ThemeFactors,
  ThemeFactorId,
  BreathFactorId,
  LeaderLevelType,
  LeaderChangeType,
} from './factors'

export type {
  AppConfig,
  SystemConfig,
  UserConfig,
  ModulesConfig,
  CacheConfig,
  DataLoaderConfig,
  RendererConfig,
  DragonBreathConfig,
  CacheItemConfig,
} from './core'

// 如果需要单独导出某些常量（保持现有导出）
export {
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

  // 平台权重与缺省占位
  PLATFORM_WEIGHTS,
  DEFAULT_RANK,

  // 事件相关
  AppEvents,
} from './config'
