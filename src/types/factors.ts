// src/types/factors.ts

/**
 * 因子基础接口
 */
export interface Factor {
  id?: string
  name: string
  type: string
  category: string
  description: string
  example?: string
  range?: [number, number]
  min?: number
  max?: number
  unit?: string
  invert?: boolean
  calculate: (stock: any) => number
}

/**
 * 因子配置
 */
export interface FactorConfig {
  weight: number | 'dynamic'
  enabled: boolean
  min?: number
  max?: number
  baseWeight?: number // 用于 dynamic 类型的基准权重
}

/**
 * 因子详情（计算结果）
 */
export interface FactorDetail {
  name: string
  score: number
  weight: number
  contribution: number
  description?: string
  example?: string
  source?: string
}

/**
 * 龙头阈值配置（新增）
 */
export interface LeaderThresholds {
  continuous?: {
    minChange: number // 最小涨幅
    minDays: number // 最小连板天数
    maxRank: number // 最大排名
    minScore: number // 最低得分
    useRank?: boolean // 是否使用排名
    useFactorScore?: boolean // 是否使用因子得分
    factorThreshold?: number // 因子得分阈值
  }
  middle?: {
    minMV: number // 最小市值
    maxChange: number // 最大涨幅
    minTurnoverRate: number // 最小换手率
    maxTurnoverRate: number // 最大换手率
    maxRank: number // 最大排名
    useRank?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  sector?: {
    maxRank: number // 最大排名
    minChange: number // 最小涨幅
    minScore: number // 最低得分
    minThemeHeat: number // 最小题材热度
    minTurnover: number // 最小成交额（全市场用）
    highTurnover: number // 较高成交额（全市场用）
    useRank?: boolean
    useTheme?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  total?: {
    maxRank: number // 最大排名
    minDays: number // 最小连板天数
    eliteRank: number // 精英排名
    minScore: number // 最低得分
    minTurnover: number // 最小成交额（全市场用）
    extremeChange: number // 极端涨幅（全市场用）
    useRank?: boolean
    useFactorScore?: boolean
    factorThreshold?: number
  }
  emotion?: {
    minTurnoverRate: number // 最小换手率
    minAbsChange: number // 最小绝对涨幅
    minScore: number // 最低得分
    useFactorScore?: boolean
    factorThreshold?: number
  }
}

/**
 * 算法定义
 */
export interface Algorithm {
  id?: string
  name: string
  icon: string
  description: string
  category: string
  color: string
  factors: Record<string, FactorConfig>
  leaderThresholds?: LeaderThresholds
  adaptive?: boolean
  learningRate?: number
}

/**
 * 阈值定义
 */
export interface Thresholds {
  totalLeader: number
  sectorLeader: number
  continuousLeader: number
  middleLeader: number
  emotionLeader: number
}

/**
 * 阈值范围
 */
export interface ThresholdRanges {
  totalLeader: { min: number; max: number }
  sectorLeader: { min: number; max: number }
  continuousLeader: { min: number; max: number }
  middleLeader: { min: number; max: number }
  emotionLeader: { min: number; max: number }
}

/**
 * 分数计算结果
 */
export interface ScoreResult {
  score: number
  details: Record<string, FactorDetail>
  timestamp: number
  algorithm: string
  algorithmName: string
  sentimentInfo?: {
    overall: number
    phase: string
    ztCount?: number
    dtCount?: number
  }
  themeInfo?: {
    heat: number
    leaderCount: number
    momentum: number
    position: number
  }
}

/**
 * 性能记录
 */
export interface PerformanceRecord {
  algorithm: string
  score: number
  success: boolean
  timestamp: number
}

/**
 * 性能统计
 */
export interface PerformanceStat {
  count: number
  successCount: number
  totalScore: number
  avgScore: number
  successRate: string
}

// ===== 题材因子定义（新增）=====

/**
 * 题材因子接口
 */
export interface ThemeFactors {
  themeHeat: number // 题材热度
  themeLeaderCount: number // 题材龙头数
  themeMomentum: number // 题材动量
  themePosition: number // 题材排名
  themeCorrelation?: number // 题材联动性（可选）
}

/**
 * 题材因子配置
 */
export const THEME_FACTOR_IDS = {
  HEAT: 'themeHeat',
  LEADER_COUNT: 'themeLeaderCount',
  MOMENTUM: 'themeMomentum',
  POSITION: 'themePosition',
  CORRELATION: 'themeCorrelation',
} as const

export type ThemeFactorId = (typeof THEME_FACTOR_IDS)[keyof typeof THEME_FACTOR_IDS]

/**
 * 题材因子元数据
 */
export const THEME_FACTORS_META: Record<ThemeFactorId, Omit<Factor, 'calculate'>> = {
  [THEME_FACTOR_IDS.HEAT]: {
    name: '题材热度',
    type: 'theme',
    category: 'sector',
    description: '题材整体热度分，越高代表题材越热门',
    example: '4500分表示热门题材，>3000为温，>1500为冷',
    range: [0, 10000],
    unit: '分',
  },
  [THEME_FACTOR_IDS.LEADER_COUNT]: {
    name: '题材龙头数',
    type: 'theme',
    category: 'sector',
    description: '题材内包含的龙头股数量',
    example: '3个以上表示强势题材',
    range: [0, 20],
    unit: '个',
  },
  [THEME_FACTOR_IDS.MOMENTUM]: {
    name: '题材动量',
    type: 'theme',
    category: 'sector',
    description: '题材趋势强度，正数表示上升趋势',
    example: '>30强势上行，<-30弱势下行',
    range: [-100, 100],
    unit: '',
  },
  [THEME_FACTOR_IDS.POSITION]: {
    name: '题材排名',
    type: 'theme',
    category: 'sector',
    description: '在热门题材榜中的位置',
    example: '1表示排名第一，越小越靠前',
    range: [1, 15],
    unit: '名',
  },
  [THEME_FACTOR_IDS.CORRELATION]: {
    name: '题材联动性',
    type: 'theme',
    category: 'sector',
    description: '题材内部股票的联动强度',
    example: '>0.6表示高联动',
    range: [0, 1],
    unit: '',
  },
}

// ===== 龙息因子=====

/**
 * 龙息因子ID定义
 */
export const BREATH_FACTOR_IDS = {
  PHASE: 'breathPhase', // 龙息阶段
  ZT_COUNT: 'breathZtCount', // 龙息涨停数
  DT_COUNT: 'breathDtCount', // 龙息跌停数
  ZHABAN_RATE: 'breathZhabanRate', // 龙息炸板率
  FENGBAN_RATE: 'breathFengbanRate', // 龙息封板率
  PASS_RATE: 'breathPassRate', // 龙息晋级率
  MAX_DAYS: 'breathMaxDays', // 龙息最高连板
  UP_DOWN_RATIO: 'breathUpDownRatio', // 龙息涨跌比
  EMOTION_VALUE: 'breathEmotionValue', // 龙息情绪值
  MARKET_SCORE: 'breathMarketScore', // 龙息市场总分
} as const

export type BreathFactorId = (typeof BREATH_FACTOR_IDS)[keyof typeof BREATH_FACTOR_IDS]

/**
 * 龙息因子元数据
 */
export const BREATH_FACTORS_META: Record<BreathFactorId, Omit<Factor, 'calculate'>> = {
  [BREATH_FACTOR_IDS.PHASE]: {
    name: '龙息阶段',
    type: 'breath',
    category: 'market',
    description: '当前市场情绪阶段：冰点、启动、发酵、高潮、退潮',
    example: '高潮期=80分，冰点期=20分',
    range: [0, 100],
    unit: '分',
  },
  [BREATH_FACTOR_IDS.ZT_COUNT]: {
    name: '龙息涨停数',
    type: 'breath',
    category: 'market',
    description: '当日涨停股票数量（不含ST）',
    example: '>60为高潮，<30为冰点',
    range: [0, 100],
    unit: '只',
  },
  [BREATH_FACTOR_IDS.DT_COUNT]: {
    name: '龙息跌停数',
    type: 'breath',
    category: 'market',
    description: '当日跌停股票数量',
    example: '>20为高风险',
    range: [0, 100],
    unit: '只',
  },
  [BREATH_FACTOR_IDS.ZHABAN_RATE]: {
    name: '龙息炸板率',
    type: 'breath',
    category: 'market',
    description: '炸板率越低，市场情绪越好',
    example: '<30%为健康',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.FENGBAN_RATE]: {
    name: '龙息封板率',
    type: 'breath',
    category: 'market',
    description: '封板率越高，市场越强势',
    example: '>70%为强势',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.PASS_RATE]: {
    name: '龙息晋级率',
    type: 'breath',
    category: 'market',
    description: '昨日涨停今日继续涨停的比例',
    example: '>40%为强势',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.MAX_DAYS]: {
    name: '龙息最高连板',
    type: 'breath',
    category: 'market',
    description: '市场最高连板天数',
    example: '>4板为强势',
    range: [0, 100],
    unit: '板',
  },
  [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: {
    name: '龙息涨跌比',
    type: 'breath',
    category: 'market',
    description: '上涨家数/下跌家数',
    example: '>2为强势',
    range: [0, 10],
    unit: '',
  },
  [BREATH_FACTOR_IDS.EMOTION_VALUE]: {
    name: '龙息情绪值',
    type: 'breath',
    category: 'market',
    description: '通达信情绪指标',
    example: '>1为活跃，<-4为冰点',
    range: [-10, 10],
    unit: '',
  },
  [BREATH_FACTOR_IDS.MARKET_SCORE]: {
    name: '龙息市场总分',
    type: 'breath',
    category: 'market',
    description: '综合市场情绪分数',
    example: '0-100分',
    range: [0, 100],
    unit: '分',
  },
}

// src/types/factors.ts

// ========== 算法配置常量 ==========

/**
 * 默认阈值
 */
export const DEFAULT_THRESHOLDS: Thresholds = {
  totalLeader: 80,
  sectorLeader: 65,
  continuousLeader: 70,
  middleLeader: 60,
  emotionLeader: 55,
}

/**
 * 阈值范围
 */
export const THRESHOLD_RANGES: ThresholdRanges = {
  totalLeader: { min: 60, max: 95 },
  sectorLeader: { min: 45, max: 85 },
  continuousLeader: { min: 50, max: 90 },
  middleLeader: { min: 40, max: 80 },
  emotionLeader: { min: 35, max: 75 },
}

/**
 * 存储键名
 */
export const STORAGE_KEYS = {
  ALGORITHM: 'kpl_algorithm',
  WEIGHTS: 'kpl_algorithm_weights',
  THRESHOLDS: 'kpl_algorithm_thresholds',
  HISTORY: 'kpl_algorithm_history',
}

// ========== 龙头级别常量 ==========

/**
 * 龙头级别定义
 */
export const LEADER_LEVELS = {
  TOTAL: { name: '总龙头', icon: '👑', color: '#FFD700', order: 1, minScore: 80 },
  CONTINUOUS: { name: '连板龙头', icon: '📈', color: '#e74c3c', order: 2, minScore: 70 },
  SECTOR: { name: '板块龙头', icon: '🏆', color: '#3498db', order: 3, minScore: 65 },
  MIDDLE: { name: '中军龙头', icon: '⚔️', color: '#9b59b6', order: 4, minScore: 60 },
  EMOTION: { name: '情绪龙头', icon: '🔥', color: '#f39c12', order: 5, minScore: 55 },
} as const

export type LeaderLevelType = keyof typeof LEADER_LEVELS

/**
 * 龙头变化类型
 */
export const LEADER_CHANGE_TYPES = {
  NEW: '新增',
  DISAPPEAR: '消失',
  PROMOTION: '晋级',
  DEMOTION: '降级',
  THEME_CHANGE: '题材变化',
} as const

export type LeaderChangeType = (typeof LEADER_CHANGE_TYPES)[keyof typeof LEADER_CHANGE_TYPES]

// ========== 权重配置常量 ==========

/**
 * 平台权重配置
 */
export const PLATFORM_WEIGHTS = {
  KPL: 1.0,
  TDX: 0.9,
  THS: 0.85,
  EASTMONEY: 0.75,
  DZH: 0.7,
  TGB: 0.4,
  XUEQIU: 0.35,
  CLS: 0.35,
} as const

/**
 * 综合排名权重配置
 */
export const COMPREHENSIVE_WEIGHTS = {
  HOT_RANK: 0.45,
  MONEY_RATIO: 0.25,
  FUND_PENETRATION: 0.1,
  TURNOVER_RATE: 0.12,
  VOLUME: 0.08,
} as const

/**
 * 惩罚分数（未上榜平台）
 */
export const PENALTY_SCORE = 100

/**
 * 默认排名（未上榜）
 */
export const DEFAULT_RANK = 999

/**
 * 换手率最优值
 */
export const OPTIMAL_TURNOVER = 15

/**
 * 换手率标准差
 */
export const TURNOVER_SIGMA = 10
