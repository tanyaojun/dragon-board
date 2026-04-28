// src/types/config.ts
// ========== 统一配置常量 ==========

// ========== 因子ID定义 ==========
export const THEME_FACTOR_IDS = {
  HEAT: 'themeHeat',
  LEADER_COUNT: 'themeLeaderCount',
  MOMENTUM: 'themeMomentum',
  POSITION: 'themePosition',
  CORRELATION: 'themeCorrelation',
} as const

export const BREATH_FACTOR_IDS = {
  PHASE: 'breathPhase',
  ZT_COUNT: 'breathZtCount',
  DT_COUNT: 'breathDtCount',
  ZHABAN_RATE: 'breathZhabanRate',
  FENGBAN_RATE: 'breathFengbanRate',
  PASS_RATE: 'breathPassRate',
  MAX_DAYS: 'breathMaxDays',
  UP_DOWN_RATIO: 'breathUpDownRatio',
  EMOTION_VALUE: 'breathEmotionValue',
  MARKET_SCORE: 'breathMarketScore',
} as const

// ========== 题材因子元数据 ==========
export const THEME_FACTORS_META = {
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
    name: '龙头数量',
    type: 'theme',
    category: 'sector',
    description: '题材内的龙头股数量',
    example: '3个龙头表示题材强势',
    range: [0, 20],
    unit: '个',
  },
  [THEME_FACTOR_IDS.MOMENTUM]: {
    name: '题材动量',
    type: 'theme',
    category: 'sector',
    description: '题材热度变化趋势',
    example: '30表示强势上涨，-30表示弱势下跌',
    range: [-100, 100],
    unit: '点',
  },
} as const

// ========== 龙息因子元数据 ==========
export const BREATH_FACTORS_META = {
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
    name: '涨停数',
    type: 'breath',
    category: 'market',
    description: '涨停家数反映市场热度',
    example: '50家以上为强势',
    range: [0, 200],
    unit: '家',
  },
  [BREATH_FACTOR_IDS.DT_COUNT]: {
    name: '跌停数',
    type: 'breath',
    category: 'market',
    description: '跌停家数反映风险',
    example: '10家以下为健康',
    range: [0, 200],
    unit: '家',
  },
  [BREATH_FACTOR_IDS.ZHABAN_RATE]: {
    name: '炸板率',
    type: 'breath',
    category: 'market',
    description: '炸板率越低越好',
    example: '30%以下为健康',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.FENGBAN_RATE]: {
    name: '封板率',
    type: 'breath',
    category: 'market',
    description: '封板率越高越强',
    example: '70%以上为强势',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.PASS_RATE]: {
    name: '晋级率',
    type: 'breath',
    category: 'market',
    description: '晋级率高说明持续性好',
    example: '30%以上为强势',
    range: [0, 100],
    unit: '%',
  },
  [BREATH_FACTOR_IDS.MAX_DAYS]: {
    name: '最高连板',
    type: 'breath',
    category: 'market',
    description: '市场最高连板天数反映空间高度',
    example: '5板以上为强势',
    range: [0, 20],
    unit: '天',
  },
  [BREATH_FACTOR_IDS.UP_DOWN_RATIO]: {
    name: '涨跌比',
    type: 'breath',
    category: 'market',
    description: '上涨家数/下跌家数',
    example: '2:1以上为强势',
    range: [0, 10],
    unit: '倍',
  },
  [BREATH_FACTOR_IDS.EMOTION_VALUE]: {
    name: '情绪值',
    type: 'breath',
    category: 'market',
    description: '通达信情绪指标',
    example: '>1为活跃，<-4为冰点',
    range: [-10, 10],
    unit: '点',
  },
  [BREATH_FACTOR_IDS.MARKET_SCORE]: {
    name: '市场总分',
    type: 'breath',
    category: 'market',
    description: '综合市场情绪分数',
    example: '80分以上为高潮期',
    range: [0, 100],
    unit: '分',
  },
} as const

// ========== 数据源配置 ==========
export const DATA_SOURCES = {
  EASTMONEY: 'eastmoney',
  TENCENT: 'tencent',
  SINA: 'sina',
} as const

export type DataSourceType = (typeof DATA_SOURCES)[keyof typeof DATA_SOURCES]

export interface DataSourceConfig {
  name: string
  enabled: boolean
  baseURL: string
  timeout: number
  priority: number
  weight: number
  transform: (code: string) => string
  fieldMapping: Record<string, string>
  responsePath: string[]
}

export const DATA_SOURCE_CONFIGS: Record<DataSourceType, DataSourceConfig> = {
  [DATA_SOURCES.EASTMONEY]: {
    name: '东方财富',
    enabled: true,
    baseURL: 'https://push2.eastmoney.com/api/qt/ulist.np/get',
    timeout: 10000,
    priority: 1,
    weight: 1,
    transform: (code: string) => {
      const c = code.replace(/[^0-9]/g, '').padStart(6, '0')
      return c.startsWith('6') || c.startsWith('11') || c.startsWith('51') ? `1.${c}` : `0.${c}`
    },
    fieldMapping: {
      code: 'f12',
      name: 'f14',
      price: 'f2',
      change: 'f3',
      turnover: 'f6',
      turnoverRate: 'f8',
      pe: 'f9',
      totalMV: 'f20',
      cirMV: 'f21',
      pb: 'f23',
      zlje: 'f62',
      cddje: 'f66',
      cddjzb: 'f69',
      zljzb: 'f184',
    },
    responsePath: ['data', 'diff'],
  },
  [DATA_SOURCES.TENCENT]: {
    name: '腾讯财经',
    enabled: true,
    baseURL: 'http://qt.gtimg.cn/q',
    timeout: 5000,
    priority: 2,
    weight: 0.8,
    transform: (code: string) => {
      return code.startsWith('6') ? `sh${code}` : `sz${code}`
    },
    fieldMapping: {
      code: 'f12',
      name: 'f14',
      price: 'f2',
      change: 'f3',
      turnover: 'f6',
      turnoverRate: 'f8',
      pe: 'f9',
      totalMV: 'f20',
      cirMV: 'f21',
      pb: 'f23',
      zlje: 'f62',
      cddje: 'f66',
      cddjzb: 'f69',
      zljzb: 'f184',
    },
    responsePath: ['data', 'data', 'diff'],
  },
  [DATA_SOURCES.SINA]: {
    name: '新浪财经',
    enabled: true,
    baseURL: 'https://hq.sinajs.cn/list',
    timeout: 5000,
    priority: 3,
    weight: 0.7,
    transform: (code: string) => {
      return code.startsWith('6') ? `sh${code}` : `sz${code}`
    },
    fieldMapping: {
      code: 'f12',
      name: 'f14',
      price: 'f2',
      change: 'f3',
      turnover: 'f6',
      turnoverRate: 'f8',
      pe: 'f9',
      totalMV: 'f20',
      cirMV: 'f21',
      pb: 'f23',
      zlje: 'f62',
      cddje: 'f66',
      cddjzb: 'f69',
      zljzb: 'f184',
    },
    responsePath: ['data', 'data', 'diff'],
  },
}

// ========== 数据源切换策略 ==========
export const DATA_SOURCE_STRATEGY = {
  // 当前活跃数据源
  ACTIVE: DATA_SOURCES.TENCENT,

  // 切换模式: 'sequential' | 'parallel' | 'weighted'
  MODE: 'sequential',

  // 失败切换阈值
  FAIL_THRESHOLD: 3,

  // 健康检查间隔（毫秒）
  HEALTH_CHECK_INTERVAL: 60000,
} as const

// ========== 行情数据字段映射 ==========
export interface QuoteFieldMapping {
  code: string
  name: string
  price: string
  change: string
  turnover: string
  turnoverRate: string
  pe: string
  totalMV: string
  cirMV: string
  pb: string
  zlje: string
  cddje: string
  cddjzb: string
  zljzb: string
}

// ========== 龙息阶段定义 ==========
export interface MarketPhase {
  name: string // 阶段名称
  value: string // 阶段值
  color: string // 显示颜色
  gradient: string // 渐变背景
  icon: string // 图标
  score: number // 阈值分数
  desc: string // 描述
  suggestion: string // 操作建议
  features: string[] // 阶段特征
  thresholdMultiplier: {
    // 动态阈值系数
    totalLeader: number
    continuousLeader: number
    sectorLeader: number
    middleLeader: number
    emotionLeader: number
  }
}

export const MARKET_PHASES: Record<string, MarketPhase> = {
  ICE: {
    name: '冰点期',
    value: 'ice',
    color: '#7f8c8d',
    gradient: 'linear-gradient(135deg, #1e2b3a, #2c3e50)',
    icon: '❄️',
    score: 20,
    desc: '市场极度悲观，涨停稀少，跌停泛滥',
    suggestion: '空仓观望，等待情绪反转',
    features: ['逆势抗跌', '连板高度2-3板', '关注逆势股'],
  },
  DEPRESSED: {
    name: '低迷期',
    value: 'depressed',
    color: '#7f8c8d',
    gradient: 'linear-gradient(135deg, #7f8c8d, #95a5a6)',
    icon: '🌧️',
    score: 30,
    desc: '人气低迷，量能萎缩',
    suggestion: '多看少动，等待机会',
    features: ['人气低迷', '量能萎缩', '多看少动'],
  },
  START: {
    name: '启动期',
    value: 'start',
    color: '#3498db',
    gradient: 'linear-gradient(135deg, #1e3c5a, #2980b9)',
    icon: '🌱',
    score: 40,
    desc: '情绪开始回暖，出现首板，跌停减少',
    suggestion: '轻仓试错，关注率先反弹的板块',
    features: ['首板增多', '板块龙头萌芽', '题材发酵'],
  },
  OSCILLATION: {
    name: '震荡期',
    value: 'oscillation',
    color: '#95a5a6',
    gradient: 'linear-gradient(135deg, #2c3e50, #34495e)',
    icon: '⚖️',
    score: 50,
    desc: '多空平衡，板块轮动，情绪震荡',
    suggestion: '控制仓位，低吸为主，不追高',
    features: ['板块轮动', '情绪震荡', '控制仓位'],
  },
  STABLE: {
    name: '平稳期',
    value: 'stable',
    color: '#3498db',
    gradient: 'linear-gradient(135deg, #3498db, #5dade2)',
    icon: '🌊',
    score: 55,
    desc: '情绪稳定，窄幅震荡',
    suggestion: '低吸为主，波段操作',
    features: ['情绪稳定', '窄幅震荡', '低吸为主'],
  },
  FERMENT: {
    name: '发酵期',
    value: 'ferment',
    color: '#f39c12',
    gradient: 'linear-gradient(135deg, #b45f06, #f39c12)',
    icon: '🔥',
    score: 60,
    desc: '题材扩散，连板增加，赚钱效应显现',
    suggestion: '适度加仓，紧跟主线题材',
    features: ['连板梯队', '资金涌入', '题材动量增强'],
  },
  ACTIVE: {
    name: '活跃期',
    value: 'active',
    color: '#ff7f50',
    gradient: 'linear-gradient(135deg, #ff7f50, #ffa07a)',
    icon: '🔥',
    score: 70,
    desc: '题材活跃，涨停增加，情绪升温',
    suggestion: '积极参与，紧跟热点',
    features: ['题材活跃', '涨停增加', '情绪升温'],
  },
  CLIMAX: {
    name: '高潮期',
    value: 'climax',
    color: '#e74c3c',
    gradient: 'linear-gradient(135deg, #a52613, #e74c3c)',
    icon: '⚡',
    score: 80,
    desc: '情绪亢奋，批量涨停，连板高度打开',
    suggestion: '持股为主，注意分化风险',
    features: ['总龙头4板以上', '连板高度提升', '注意分化'],
  },
  RECESSION: {
    name: '退潮期',
    value: 'recession',
    color: '#9b59b6',
    gradient: 'linear-gradient(135deg, #4a235a, #8e44ad)',
    icon: '🌊',
    score: 100,
    desc: '高位分歧，亏钱效应，炸板率高',
    suggestion: '减仓防守，规避高位股',
    features: ['高位补跌', '减仓防守', '关注穿越'],
  },
} as const

// ========== 情绪反馈相关类型 ==========
export interface EmotionFactorWeights {
  breathPhase: number
  breathZtCount: number
  breathDtCount: number
  breathPassRate: number
  breathMaxDays: number
  breathUpDownRatio: number
  [key: string]: number
}

export interface EmotionFeedback {
  phase: string
  score: number
  ztCount: number
  dtCount: number
  hotThemesCount: number
  themeImpact: number
  timestamp: number
}

export interface PhaseAdjustment {
  [factorId: string]: number // 正数为增加权重，负数为减少
}

export const PHASE_ADJUSTMENTS: Record<string, PhaseAdjustment> = {
  // ===== 冰点期：防守为主，关注逆势 =====
  冰点期: {
    contrarian: 0.05, // 逆势因子大幅提高（找抗跌股）
    compRank: 0.02, // 综合排名稍提高（找强势股）
    breathDtCount: 0.03, // 跌停数权重提高（风险警示）
    themeHeat: -0.03, // 题材热度降权（题材失效）
    breathZtCount: -0.02, // 涨停数降权
    breathPassRate: -0.02, // 晋级率降权
    zlje: -0.02, // 主力净额降权
  },

  // ===== 低迷期：观望为主，轻仓试错 =====
  低迷期: {
    contrarian: 0.03, // 逆势因子保持
    breathDtCount: 0.02, // 跌停数关注
    compRank: 0.01,
    themeHeat: -0.02,
    breathZtCount: -0.01,
    breathPassRate: -0.01,
  },

  // ===== 启动期：轻仓试错，关注率先反弹 =====
  启动期: {
    themeHeat: 0.02, // 题材热度开始重要
    compRank: 0.02, // 排名重要（找领涨）
    breathPassRate: 0.03, // 晋级率提高
    breathZtCount: 0.01, // 涨停数略增
    continuousDays: 0.01, // 连板开始关注
    zlje: 0.01, // 主力开始进场
    contrarian: -0.02, // 逆势降权
  },

  // ===== 震荡期：低吸为主，控制仓位 =====
  震荡期: {
    // 保持中性，各因子均衡
    compRank: 0.01,
    themeHeat: 0.01,
    breathPassRate: 0.01,
    breathZtCount: 0.01,
  },

  // ===== 平稳期：低吸为主，波段操作 =====
  平稳期: {
    compRank: 0.02, // 排名重要
    themeHeat: 0.01,
    turnover: 0.02, // 成交额重要（量能稳定）
    zlje: 0.01, // 主力稳定
    continuousDays: 0.01, // 连板保持
  },

  // ===== 发酵期：适度加仓，紧跟主线 =====
  发酵期: {
    themeHeat: 0.03, // 题材热度最重要
    themeMomentum: 0.03, // 题材动量最重要
    continuousDays: 0.02, // 连板开始发力
    breathPassRate: 0.02, // 晋级率提高
    zlje: 0.02, // 主力开始加仓
    breathZtCount: 0.01,
    compRank: -0.01, // 排名适当降低（题材更重要）
  },

  // ===== 活跃期：积极参与，紧跟热点 =====
  活跃期: {
    themeHeat: 0.02,
    themeMomentum: 0.02,
    continuousDays: 0.03, // 连板最重要
    breathZtCount: 0.02, // 涨停数重要
    breathPassRate: 0.02,
    zlje: 0.01,
    turnover: 0.01,
    compRank: -0.02, // 排名不重要（情绪更重要）
  },

  // ===== 高潮期：持股为主，注意分化 =====
  高潮期: {
    continuousDays: 0.04, // 连板最重要（高度板）
    breathZtCount: 0.02,
    breathPhase: 0.02,
    themeHeat: -0.02, // 题材热度降权（注意分化）
    themeMomentum: -0.02,
    zlje: -0.02, // 主力降权（高潮期不看主力）
    contrarian: -0.03, // 逆势大幅降权
  },

  // ===== 退潮期：减仓防守，规避高位 =====
  退潮期: {
    breathDtCount: 0.04, // 跌停数最重要（风险警示）
    breathZhabanRate: 0.03, // 炸板率重要
    contrarian: 0.02, // 逆势回升
    continuousDays: -0.03, // 连板大幅降权（不追高）
    themeHeat: -0.02,
    themeMomentum: -0.02,
    zlje: -0.03, // 主力大幅降权
    breathPassRate: -0.02,
  },
} as const

// ========== 算法配置常量 ==========
export interface Thresholds {
  totalLeader: number
  sectorLeader: number
  continuousLeader: number
  middleLeader: number
  emotionLeader: number
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  totalLeader: 80, // 总龙头：市场绝对核心，连板高度+带动性
  continuousLeader: 68, // 连板龙头：至少3连板，且有换手
  sectorLeader: 58, // 板块龙头：板块内最强，带动板块跟风
  middleLeader: 48, // 中军龙头：大市值+高成交额+趋势
  emotionLeader: 45, // 情绪龙头：涨停+高换手+带动情绪
}

export interface ThresholdRange {
  min: number
  max: number
}

export interface ThresholdRanges {
  totalLeader: ThresholdRange
  sectorLeader: ThresholdRange
  continuousLeader: ThresholdRange
  middleLeader: ThresholdRange
  emotionLeader: ThresholdRange
}

export const THRESHOLD_RANGES: ThresholdRanges = {
  totalLeader: { min: 75, max: 95 }, // 总龙头不能低于75
  sectorLeader: { min: 60, max: 85 }, // 板块龙头不能低于60
  continuousLeader: { min: 65, max: 90 }, // 连板龙头不能低于65
  middleLeader: { min: 55, max: 80 }, // 中军龙头不能低于55
  emotionLeader: { min: 52, max: 75 }, // 情绪龙头最低52（比原来提高17分）
}
/**
 * 存储键名 - 添加阈值乘数配置
 */
export const STORAGE_KEYS = {
  ALGORITHM: 'algorithm',
  WEIGHTS: 'lgorithm_weights',
  THRESHOLDS: 'algorithm_thresholds',
  HISTORY: 'algorithm_history',
  THRESHOLD_MULTIPLIERS: 'threshold_multipliers', //情绪计算阈值乘数配置
}

/**
 * 阈值乘数配置
 */
export interface ThresholdMultiplier {
  totalLeader: number
  continuousLeader: number
  sectorLeader: number
  middleLeader: number
  emotionLeader: number
}

/**
 * 默认阈值乘数
 */
export const DEFAULT_THRESHOLD_MULTIPLIERS: ThresholdMultiplier = {
  totalLeader: 1.0,
  continuousLeader: 1.0,
  sectorLeader: 1.0,
  middleLeader: 1.0,
  emotionLeader: 1.0,
}

/**
 * 情绪阶段配置（包含可调整的阈值乘数）
 */
export interface MarketPhase {
  name: string
  value: string
  color: string
  gradient: string
  icon: string
  score: number
  desc: string
  suggestion: string
  features: string[]
  thresholdMultiplier: ThresholdMultiplier // 改为可配置
}

// ========== 龙头级别常量 ==========
export interface LeaderLevel {
  name: string
  icon: string
  color: string
  order: number
  minScore: number
}

export const LEADER_LEVELS: Record<string, LeaderLevel> = {
  TOTAL: { name: '总龙头', icon: '👑', color: '#FFD700', order: 1, minScore: 80 },
  CONTINUOUS: { name: '连板龙头', icon: '📈', color: '#e74c3c', order: 2, minScore: 70 },
  SECTOR: { name: '板块龙头', icon: '🏆', color: '#3498db', order: 3, minScore: 65 },
  MIDDLE: { name: '中军龙头', icon: '⚔️', color: '#9b59b6', order: 4, minScore: 60 },
  EMOTION: { name: '情绪龙头', icon: '🔥', color: '#f39c12', order: 5, minScore: 55 },
} as const

export const LEADER_CHANGE_TYPES = {
  NEW: '新增',
  DISAPPEAR: '消失',
  PROMOTION: '晋级',
  DEMOTION: '降级',
  THEME_CHANGE: '题材变化',
} as const

// ========== 权重配置常量 ==========
export const PLATFORM_WEIGHTS = {
  kpl: 1.0,
  tdx: 0.9,
  ths: 0.85,
  eastmoney: 0.75,
  dzh: 0.7,
  tgb: 0.4,
  xueqiu: 0.35,
  cls: 0.35,
} as const

export const COMPREHENSIVE_WEIGHTS = {
  HOT_RANK: 0.45,
  MONEY_RATIO: 0.25,
  FUND_PENETRATION: 0.1,
  TURNOVER_RATE: 0.12,
  VOLUME: 0.08,
} as const

export const PENALTY_SCORE = 100
export const DEFAULT_RANK = 999
export const OPTIMAL_TURNOVER = 15
export const TURNOVER_SIGMA = 10

// ========== 性能监控配置 ==========
export const PERFORMANCE_CONFIG = {
  MAX_HISTORY: 1000,
  UPDATE_INTERVAL: 60 * 1000, // 1分钟
  EMOTION_HISTORY_SIZE: 100,
  ADJUSTMENT_HISTORY_SIZE: 200,
} as const

// ========== 情绪监控相关类型 ==========
export interface EmotionRecord {
  phase: string
  score: number
  ztCount: number
  dtCount: number
  hotThemesCount: number
  timestamp: number
}

export interface AdjustmentRecord {
  factorId: string
  oldWeight: number
  newWeight: number
  delta: number
  reason: string
  timestamp: number
}

export interface PerformanceStats {
  avgCalcTime: number
  p95CalcTime: number
  cacheHitRate: number
  emotionStats: Record<string, { count: number; avgScore: number }>
  adjustmentStats: Record<string, { count: number; totalDelta: number }>
}

// ========== 统一题材情绪影响配置 ==========
export const THEME_EMOTION_IMPACT = {
  // 1. 情绪阶段对题材热度的乘数（与龙息分析器保持一致）
  PHASE_MULTIPLIERS: {
    冰点期: 0.5,
    低迷期: 0.7,
    启动期: 0.9,
    震荡期: 1.0,
    平稳期: 1.0,
    发酵期: 1.2,
    活跃期: 1.3,
    高潮期: 1.4,
    退潮期: 0.9, // 将 0.6 改为 0.9
  },

  // 2. 涨停数对题材热度的加成（每涨停加多少分）
  ZT_BONUS: 5, // 每个涨停加5分

  // 3. 炸板率惩罚系数（炸板率越高，题材热度越低）
  ZHABAN_PENALTY: 0.005, // 炸板率每1%扣0.5%的热度

  // 4. 情绪阶段对题材动量的影响（动量变化速度）
  MOMENTUM_IMPACT: {
    冰点期: 0.6, // 动量增长缓慢
    低迷期: 0.8,
    启动期: 1.0,
    震荡期: 1.0,
    平稳期: 1.0,
    发酵期: 1.2, // 动量加速
    活跃期: 1.3,
    高潮期: 1.4,
    退潮期: 0.7, // 动量衰减
  },

  // 5. 情绪分数阈值（定义各阶段的分数范围）- 与 DragonBreathAnalyzer 共享
  PHASE_SCORE_THRESHOLDS: {
    冰点期: { min: 0, max: 25 },
    低迷期: { min: 25, max: 35 },
    启动期: { min: 35, max: 45 },
    震荡期: { min: 45, max: 55 },
    平稳期: { min: 55, max: 60 },
    发酵期: { min: 60, max: 70 },
    活跃期: { min: 70, max: 78 },
    高潮期: { min: 78, max: 85 },
    退潮期: { min: 85, max: 100 },
  },

  // 6. 因子贡献权重（各因子对题材热度的贡献比例）
  FACTOR_WEIGHTS: {
    ztCount: 0.4, // 涨停数贡献40%
    leaderCount: 0.3, // 龙头数贡献30%
    momentum: 0.2, // 动量贡献20%
    correlation: 0.1, // 联动性贡献10%
  },

  // 7. 情绪对题材轮动的影响（轮动速度）
  ROTATION_SPEED: {
    冰点期: 0.8,
    低迷期: 0.9,
    启动期: 1.0,
    震荡期: 1.0,
    平稳期: 1.0,
    发酵期: 1.2,
    活跃期: 1.3,
    高潮期: 1.4,
    退潮期: 0.9,
  },
} as const

// ========== 事件常量 ==========
export const AppEvents = {
  // ===== 股票相关事件 =====
  STOCK: {
    SELECTED: 'stock:selected',
    FAVORITE_ADDED: 'stock:favorite-added',
    FAVORITE_REMOVED: 'stock:favorite-removed',
    DETAILS_LOADED: 'stock:details-loaded',
    UPDATED: 'stocks-updated',
    QUOTES_UPDATED: 'quotes-updated',
    FAVORITES_UPDATED: 'favorites-updated',
  },

  // ===== 数据相关事件 =====
  DATA: {
    STOCKS_LOADED: 'data:stocks-loaded',
    PLATFORMS_LOADED: 'data:platforms-loaded',
    THEMES_LOADED: 'data:themes-loaded',
    MERGED: 'data:merged',
    QUOTES_UPDATED: 'data:quotes-updated',
    UPDATED: 'data:updated',
  },

  // ===== 题材相关事件 =====
  SECTOR: {
    UPDATED: 'sector:updated',
    READY: 'sector:ready',
    ALERT: 'sector-alert',
    HOT_THEMES_UPDATED: 'sector:hot-themes-updated',
    ROTATION_UPDATED: 'sector:rotation-updated',
    THEME_DETAIL_UPDATED: 'sector:theme-detail-updated',
    LEADERS_SYNCED: 'sector:leaders-synced',
  },

  // ===== 龙头相关事件 =====
  DRAGON: {
    UPDATED: 'dragon:updated',
    CHANGED: 'dragon:changed',
    LEVEL_CHANGED: 'dragon:level-changed',
    THEME_CHANGED: 'dragon:theme-changed',
    PERFORMANCE: 'dragon:performance',
    TASK_FAILED: 'dragon:task-failed',
    CACHE_CLEARED: 'dragon:cache-cleared',
    RECALCULATED: 'dragon:recalculated',
  },

  // ===== 龙息相关事件 =====
  BREATH: {
    UPDATED: 'breath:updated',
    PHASE_CHANGED: 'breath:phase-changed',
    METRICS_UPDATED: 'breath:metrics-updated',
    FEEDBACK: 'breath:feedback',
    THRESHOLD_MULTIPLIERS_UPDATED: 'threshold-multipliers-updated',
  },

  // ===== 算法相关事件 =====
  ALGORITHM: {
    CHANGED: 'algorithm-changed',
    WEIGHTS_ADJUSTED: 'algorithm:weights-adjusted',
    THRESHOLDS_CHANGED: 'thresholds-changed',
    CONFIG_CHANGED: 'algorithm:config-changed',
    INITIALIZED: 'algorithm:initialized',
    CONFIG_SAVED: 'algorithm:config-saved',
    WEIGHTS_NORMALIZED: 'algorithm:weights-normalized',
  },

  // ===== WebSocket相关事件 =====
  WEBSOCKET: {
    STATUS_CHANGED: 'tdxl2:status-changed',
    SUBSCRIPTION_UPDATED: 'tdxl2:subscription-updated',
    FULL_STATE: 'tdxl2:full-state',
    QUOTE_PATCH: 'tdxl2:quote-patch',
    DEPTH_PATCH: 'tdxl2:depth-patch',
    TICKS_BATCH: 'tdxl2:ticks-batch',
    HEARTBEAT: 'tdxl2:heartbeat',
    TICK: 'tdxl2:tick',
  },

  // ===== 行情服务相关事件 =====
  QUOTE: {
    FETCH_FAILED: 'quote:fetch-failed',
    CACHE_INVALIDATED: 'quote:cache-invalidated',
    CACHE_CLEARED: 'quote:cache-cleared',
    DESTROYED: 'quote:destroyed',
    UPDATED: 'quotes:updated',
  },

  // ===== 配置相关事件 =====
  CONFIG: {
    REFRESH_CHANGED: 'config:refresh-changed',
  },

  // ===== UI 相关事件 =====
  UI: {
    TOAST: 'ui:toast',
    PANEL_OPEN: 'ui:panel-open',
    PANEL_CLOSE: 'ui:panel-close',
    REFRESH_REQUESTED: 'ui:refresh-requested',
  },

  // ===== 增量更新相关事件 =====
  INCREMENTAL: {
    QUEUE_PROCESSED: 'incremental:queue-processed',
    BATCH_COMPLETED: 'incremental:batch-completed',
    SLOW_QUERY: 'incremental:slow-query',
    TASK_FAILED: 'incremental:task-failed',
  },

  // ===== 刷新管理相关事件 =====
  REFRESH: {
    FULL_REQUESTED: 'refresh:full-requested',
    INCREMENTAL_REQUESTED: 'refresh:incremental-requested',
    MANUAL_REQUESTED: 'refresh:manual-requested',
    MAINTENANCE_REQUESTED: 'refresh:maintenance-requested',
    COMPLETE: 'refresh:complete',
    FULL_COMPLETE: 'refresh:full-complete', // ✅ 新增
    INCREMENTAL_COMPLETE: 'refresh:incremental-complete', // ✅ 新增
    FAILED: 'refresh:failed',
    STARTED: 'refresh:started',
    STOPPED: 'refresh:stopped',
    CHANGED: 'refresh:config-changed',
    RESET: 'refresh:config-reset',
    INITIALIZED: 'refresh:initialized',
  },

  // ===== 缓存相关事件 =====
  CACHE: {
    ANALYZE_KEYS: 'cache:analyze-keys',
    ANALYZE_COMPLETE: 'cache:analyze-complete',
    CLEAR_REQUESTED: 'cache:clear-requested',
    CLEARED: 'cache:cleared',
    CLEAR_FAILED: 'cache:clear-failed',
  },

  // ===== 统计导出相关事件 =====
  STATS: {
    EXPORT_START: 'stats:export-start',
    EXPORT_COMPLETE: 'stats:export-complete',
    EXPORT_FAILED: 'stats:export-failed',
  },
} as const

// ========== 增量更新配置 ==========

export const INCREMENTAL_UPDATER_CONFIG = {
  UPDATE_DELAY: 500,
  BATCH_SIZE: 30,

  PRIORITY: {
    DRAGON_CHANGE: 1,
    WEBSOCKET_QUOTE: 2,
    DRAGON_FULL: 3,
    HTTP_QUOTE: 4,
    SECTOR_UPDATE: 5,
    BACKGROUND: 6,
    BIG_ORDER: 7,
    BIG_ORDER_FULL: 8,
  } as const,

  // 涨停相关配置
  LIMIT_UP: {
    MAIN_THRESHOLD: 9.8, // 主板涨停阈值
    MAIN_MAX: 10.5, // 主板涨停上限（考虑新股）
    GEM_THRESHOLD: 19.5, // 创业板涨停阈值
    GEM_MAX: 20.5, // 创业板涨停上限
    STAR_THRESHOLD: 19.5, // 科创板涨停阈值
    STAR_MAX: 20.5, // 科创板涨停上限
    NORTH_THRESHOLD: 29.8, // 北交所涨停阈值
    NORTH_MAX: 30.5, // 北交所涨停上限
    MIN_CHANGE: 0.5, // 最小变化阈值（避免微小波动触发）
    DEBOUNCE_TIME: 10000, // 防抖时间（毫秒）
  },

  // 任务去重配置
  TASK_DEDUP: {
    DRAGON_CHANGE_TTL: 10000, // 龙头变化任务去重时间
    QUOTE_UPDATE_TTL: 5000, // 行情更新去重时间
  },

  UPDATE_TYPES: {
    DRAGON_CHANGE: 'dragon_change',
    DRAGON_FULL: 'dragon_full',
    WEBSOCKET_QUOTE: 'ws_quote',
    HTTP_QUOTE: 'http_quote',
    SECTOR: 'sector',
    RANK: 'rank',
    PLATFORM: 'platform',
    ALGORITHM: 'algorithm',
    LIFECYCLE: 'dragon_lifecycle',
    BIG_ORDER: 'big_order', // 大单更新
    BIG_ORDER_FULL: 'big_order_full',
  } as const,

  RETRY: {
    MAX_ATTEMPTS: 3,
    DELAY: 1000,
    BACKOFF: 2,
  },

  MONITOR: {
    ENABLED: true,
    SLOW_THRESHOLD: 100,
    QUEUE_HISTORY: 20,
  },

  // ✅ 热点股票数量配置（可自定义）
  HOT_STOCKS_LIMIT: 50, // 默认50只
  MAX_HOT_STOCKS_LIMIT: 200, // 最大限制
  MIN_HOT_STOCKS_LIMIT: 10, // 最小限制
} as const

export interface StockData {
  // 基础信息
  code: string
  name: string

  // 行情数据
  price: number
  change: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  pb: number
  totalMV: number
  cirMV: number

  // 资金数据
  zlje: number // 主力净额
  zljzb: number // 主力占比
  cddje: number // 超大单净额
  cddjzb: number // 超大单占比

  // 八平台排名（重要！）
  emRank: number // 东方财富排名
  thsRank: number // 同花顺排名
  kplRank: number // 开盘啦排名
  tdxRank: number // 通达信排名
  xqRank: number // 雪球排名
  clsRank: number // 财联社排名
  tgbRank: number // 淘股吧排名
  dzhRank: number // 大智慧排名

  // 综合数据
  platforms: number // 上榜平台数
  avgRankNum: number // 平均排名数值
  avgRank: string // 平均排名显示
  compRank: number // 综合排名
  compScore: number // 综合得分

  // 龙头数据
  isSectorLeader: boolean
  leaderLevel: string
  leaderScore: number
  continuousDays: number

  // 题材数据
  themes: any[]

  // 时间戳
  updatedAt: number
}

// ========== 刷新策略预设 ==========
export const REFRESH_STRATEGY_PRESETS = {
  AGGRESSIVE: 'aggressive',
  BALANCED: 'balanced',
  CONSERVATIVE: 'conservative',
  RECOVERY: 'recovery',
} as const

export type RefreshStrategy =
  (typeof REFRESH_STRATEGY_PRESETS)[keyof typeof REFRESH_STRATEGY_PRESETS]

// ========== 刷新配置接口 ==========
export interface RefreshConfig {
  // 基本设置
  enabled: boolean
  strategy: RefreshStrategy
  tradingTimeOnly: boolean
  allowManualRefresh: boolean

  // 刷新间隔
  fullRefreshInterval: number // 单位：毫秒
  incrementalRefreshInterval: number // 单位：毫秒

  // 热点股票配置
  hotStocksLimit: number // HTTP校准的股票数量

  // 重试配置
  retryOnFailure: boolean
  maxRetries: number
}

// ========== 策略预设值 ==========
export const REFRESH_STRATEGY_CONFIGS: Record<RefreshStrategy, RefreshConfig> = {
  [REFRESH_STRATEGY_PRESETS.AGGRESSIVE]: {
    enabled: true,
    strategy: REFRESH_STRATEGY_PRESETS.AGGRESSIVE,
    tradingTimeOnly: true,
    allowManualRefresh: true,
    fullRefreshInterval: 5 * 60 * 1000, // 5分钟
    incrementalRefreshInterval: 500, // 0.5秒
    hotStocksLimit: 200, // 200只
    retryOnFailure: true,
    maxRetries: 3,
  },
  [REFRESH_STRATEGY_PRESETS.BALANCED]: {
    enabled: true,
    strategy: REFRESH_STRATEGY_PRESETS.BALANCED,
    tradingTimeOnly: true,
    allowManualRefresh: true,
    fullRefreshInterval: 15 * 60 * 1000, // 15分钟
    incrementalRefreshInterval: 2000, // 2秒
    hotStocksLimit: 100, // 100只
    retryOnFailure: true,
    maxRetries: 2,
  },
  [REFRESH_STRATEGY_PRESETS.CONSERVATIVE]: {
    enabled: true,
    strategy: REFRESH_STRATEGY_PRESETS.CONSERVATIVE,
    tradingTimeOnly: true,
    allowManualRefresh: true,
    fullRefreshInterval: 2 * 60 * 60 * 1000, // 2小时
    incrementalRefreshInterval: 10 * 60 * 1000, // 10分钟
    hotStocksLimit: 50, // 50只
    retryOnFailure: true,
    maxRetries: 1,
  },
  [REFRESH_STRATEGY_PRESETS.RECOVERY]: {
    enabled: true,
    strategy: REFRESH_STRATEGY_PRESETS.RECOVERY,
    tradingTimeOnly: false,
    allowManualRefresh: true,
    fullRefreshInterval: 15 * 60 * 1000, // 15分钟
    incrementalRefreshInterval: 60 * 1000, // 1分钟
    hotStocksLimit: 100, // 100只
    retryOnFailure: true,
    maxRetries: 5,
  },
}

// ========== 策略显示配置 ==========
export const REFRESH_STRATEGY_DISPLAY = {
  [REFRESH_STRATEGY_PRESETS.AGGRESSIVE]: {
    name: '激进型',
    icon: '⚡',
    desc: '高频刷新，适合短线交易 (增量0.5秒)',
    color: '#e74c3c',
  },
  [REFRESH_STRATEGY_PRESETS.BALANCED]: {
    name: '平衡型',
    icon: '⚖️',
    desc: '默认配置，兼顾性能和实时性 (增量2秒)',
    color: '#3498db',
  },
  [REFRESH_STRATEGY_PRESETS.CONSERVATIVE]: {
    name: '保守型',
    icon: '🐢',
    desc: '低频刷新，节省资源 (增量10分钟)',
    color: '#2ecc71',
  },
  [REFRESH_STRATEGY_PRESETS.RECOVERY]: {
    name: '恢复模式',
    icon: '🔄',
    desc: '失败后快速恢复，全天可用',
    color: '#f39c12',
  },
} as const

// ========== 刷新配置存储键 ==========
export const REFRESH_STORAGE_KEY = 'refresh-config'

// ========== 刷新间隔选项（供面板使用）==========
export const FULL_REFRESH_OPTIONS = [
  { value: 5 * 60 * 1000, label: '5分钟', strategy: REFRESH_STRATEGY_PRESETS.AGGRESSIVE },
  { value: 15 * 60 * 1000, label: '15分钟', strategy: REFRESH_STRATEGY_PRESETS.BALANCED },
  { value: 30 * 60 * 1000, label: '30分钟' },
  { value: 60 * 60 * 1000, label: '60分钟' },
  { value: 2 * 60 * 60 * 1000, label: '2小时', strategy: REFRESH_STRATEGY_PRESETS.CONSERVATIVE },
  { value: 4 * 60 * 60 * 1000, label: '4小时' },
] as const

export const INCREMENTAL_REFRESH_OPTIONS = [
  { value: 500, label: '0.5秒', strategy: REFRESH_STRATEGY_PRESETS.AGGRESSIVE },
  { value: 1000, label: '1秒' },
  { value: 2000, label: '2秒', strategy: REFRESH_STRATEGY_PRESETS.BALANCED },
  { value: 5000, label: '5秒' },
  { value: 10000, label: '10秒' },
  { value: 30000, label: '30秒' },
  { value: 60000, label: '1分钟', strategy: REFRESH_STRATEGY_PRESETS.RECOVERY },
  { value: 300000, label: '5分钟' },
  { value: 600000, label: '10分钟', strategy: REFRESH_STRATEGY_PRESETS.CONSERVATIVE },
] as const

export const HOT_STOCKS_OPTIONS = [
  { value: 10, label: '10只', min: true },
  { value: 20, label: '20只' },
  { value: 30, label: '30只' },
  { value: 50, label: '50只', strategy: REFRESH_STRATEGY_PRESETS.CONSERVATIVE },
  { value: 80, label: '80只' },
  { value: 100, label: '100只', strategy: REFRESH_STRATEGY_PRESETS.BALANCED },
  { value: 150, label: '150只' },
  { value: 200, label: '200只', strategy: REFRESH_STRATEGY_PRESETS.AGGRESSIVE },
  { value: 300, label: '300只' },
  { value: 500, label: '500只', max: true },
] as const

// ========== 轮动系统配置接口 ==========

/** 资金阈值配置 */
export interface FundThresholds {
  STRONG_INFLOW: number // 强势流入阈值（万元）
  MEDIUM_INFLOW: number // 中等流入阈值（万元）
  STRONG_OUTFLOW: number // 强势流出阈值（万元）
  MEDIUM_OUTFLOW: number // 中等流出阈值（万元）
}

/** 涨停阈值配置 */
export interface ZtThresholds {
  STRONG: number // 强势涨停数
  MEDIUM: number // 中等涨停数
  WEAK: number // 弱势涨停数
}

/** 持续性阈值配置 */
export interface PersistenceThresholds {
  MAIN_LINE: number // 主线判定天数
  QUICK_ROTATION: number // 快速轮动天数
  OVERHEAT: number // 过热预警天数
}

/** 排名变化阈值配置 */
export interface RankChangeThresholds {
  SURGE: number // 飙升阈值
  UP: number // 上升阈值
  DOWN: number // 下降阈值
  PLUNGE: number // 暴跌阈值
}

/** 轮动速度阈值配置 */
export interface RotationSpeedThresholds {
  FAST: number // 快速轮动阈值
  NORMAL: number // 正常轮动阈值
  SLOW: number // 缓慢轮动阈值
  STABLE: number // 稳定轮动阈值
}

/** 市场阶段配置项 */
export interface MarketPhaseConfig {
  name: string
  value: string
  icon: string
  color: string
  desc: string
  suggestion: string
}

/** 阶段判定阈值配置 */
export interface PhaseThresholds {
  RISING: { MAIN_LINES: number; MAX_SPEED: number }
  DISTRIBUTION: { MIN_SPEED: number }
  FALLING: { OUTFLOW_RATIO: number }
}

/** 轮动系统完整配置 */
export interface RotationConfig {
  ENABLED: boolean
  ANALYSIS_INTERVAL: number
  FUND_THRESHOLDS: FundThresholds
  ZT_THRESHOLDS: ZtThresholds
  PERSISTENCE: PersistenceThresholds
  RANK_CHANGE: RankChangeThresholds
  ROTATION_SPEED: RotationSpeedThresholds
  MARKET_PHASES: Record<string, MarketPhaseConfig>
  PHASE_THRESHOLDS: PhaseThresholds
  HISTORY_LIMIT: number
  DEBUG: boolean
}

// ========== 预警系统配置接口 ==========

/** 预警级别显示配置 */
export interface AlertLevelDisplay {
  name: string
  icon: string
  color: string
  bgColor: string
}

/** 预警类型显示配置 */
export interface AlertTypeDisplay {
  name: string
  icon: string
  desc: string
  level: string // 默认预警级别
}

/** 龙头倒下阈值配置 */
export interface LeaderFallThresholds {
  CRITICAL: number // 严重阈值（跌停）
  WARNING: number // 警告阈值（大跌）
}

/** 批量涨停阈值配置 */
export interface BatchLimitUpThresholds {
  CRITICAL: number // 严重阈值
  WARNING: number // 警告阈值
}

/** 批量炸板阈值配置 */
export interface BatchExplodeThresholds {
  CRITICAL: number // 严重阈值
  WARNING: number // 警告阈值
}

/** 热度变化阈值配置 */
export interface HeatChangeThresholds {
  SURGE: number // 飙升阈值
  PLUNGE: number // 骤降阈值
}

/** 放量倍数阈值配置 */
export interface VolumeSurgeThresholds {
  CRITICAL: number // 严重阈值
  WARNING: number // 警告阈值
  INFO: number // 提示阈值
}

/** 资金异动阈值配置 */
export interface MoneyFlowThresholds {
  STRONG_INFLOW: number // 强势流入
  STRONG_OUTFLOW: number // 强势流出
  WARNING_INFLOW: number // 警告流入
  WARNING_OUTFLOW: number // 警告流出
}

/** 轮动速度阈值配置 */
export interface RotationSpeedAlertThresholds {
  FAST: number // 快速轮动阈值
  SLOW: number // 缓慢轮动阈值
}

/** 预警阈值完整配置 */
export interface AlertThresholds {
  LEADER_FALL: LeaderFallThresholds
  BATCH_LIMIT_UP: BatchLimitUpThresholds
  BATCH_EXPLODE: BatchExplodeThresholds
  HEAT_CHANGE: HeatChangeThresholds
  VOLUME_SURGE: VolumeSurgeThresholds
  MONEY_FLOW: MoneyFlowThresholds
  ROTATION_SPEED: RotationSpeedAlertThresholds
}

/** 预警系统完整配置 */
export interface AlertConfig {
  ENABLED: boolean
  CHECK_INTERVAL: number
  MAX_ALERTS: number
  COOLDOWN: number
  EXPIRE_TIME: number
  HISTORY_RETENTION: number
  BATCH_SIZE: number
}

// ========== 预警类型和级别常量类型 ==========

/** 预警类型常量 */
export type AlertTypeConstant = {
  LEADER_FALL: 'leader_fall'
  LEADER_EMERGE: 'leader_emerge'
  BATCH_LIMIT_UP: 'batch_limit_up'
  BATCH_EXPLODE: 'batch_explode'
  HEAT_SURGE: 'heat_surge'
  HEAT_PLUNGE: 'heat_plunge'
  VOLUME_SURGE: 'volume_surge'
  ROTATION_SIGNAL: 'rotation_signal'
  MONEY_FLOW: 'money_flow'
}

/** 预警级别常量 */
export type AlertLevelConstant = {
  CRITICAL: 'critical'
  WARNING: 'warning'
  INFO: 'info'
}

// ========== 扩展的事件常量类型 ==========

/** 轮动事件类型 */
export interface RotationEvents {
  UPDATED: 'rotation:updated'
  PHASE_CHANGED: 'rotation:phase-changed'
  MAIN_LINE_UPDATED: 'rotation:main-line-updated'
}

/** 预警事件类型 */
export interface AlertEvents {
  NEW: 'alert:new'
  UPDATED: 'alert:updated'
  READ: 'alert:read'
  RESOLVED: 'alert:resolved'
  CLEARED: 'alert:cleared'
}

// ========== 扩展的存储键名类型 ==========

/** 扩展的存储键名 */
export interface ExtendedStorageKeys {
  ROTATION_CACHE: 'rotation_cache'
  ROTATION_HISTORY: 'rotation_history'
  ALERT_CACHE: 'alert_cache'
  ALERT_HISTORY: 'alert_history'
}

// ========== 扩展的API端点类型 ==========

/** 轮动API端点 */
export interface RotationEndpoints {
  ANALYSIS: '/api/rotation/analysis'
  HISTORY: '/api/rotation/history'
}

/** 预警API端点 */
export interface AlertEndpoints {
  LIST: '/api/alert/list'
  STATS: '/api/alert/stats'
  MARK_READ: '/api/alert/read'
  CLEAR: '/api/alert/clear'
}

/** 扩展的API端点 */
export interface ExtendedApiEndpoints {
  ROTATION: RotationEndpoints
  ALERT: AlertEndpoints
}
