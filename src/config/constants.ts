// src/config/constants.ts
/**
 * 题材分析器配置常量
 * 与 sectorAnalyzer.ts 3.0.0 保持同步
 */
export const SECTOR_CONFIG = {
  // 热门题材限制（只影响展示）
  HOT_THEMES_LIMIT: 10,

  // 每只股票最多显示几个题材
  MAX_THEMES_PER_STOCK: 3,

  // 并发控制
  MAX_CONCURRENT: 3,
  MAX_RETRIES: 3,

  // 缓存配置
  CACHE_TTL: 5 * 60 * 1000, // 5分钟
  CACHE_KEYS: {
    THEME_META: 'sector:meta:all',
    THEME_DETAIL: 'sector:detail:',
    THEME_STATS: 'sector:stats:',
    THEME_HISTORY: 'sector:history',
    STOCK_THEMES: 'sector:stock:',
    THEME_LIST: 'sector:list:',
  },

  // 缓存策略
  CACHE_STRATEGY: {
    META_TTL: 7 * 24 * 60 * 60 * 1000, // 7天
    DETAIL_TTL: 3 * 24 * 60 * 60 * 1000, // 3天
    HOT_TTL: 24 * 60 * 60 * 1000, // 1天
  },

  // 加载控制
  BATCH_LOAD: {
    ENABLED: true,
    BATCH_SIZE: 10,
    DELAY_MS: 500,
    RETRY_COUNT: 2,
  },

  // 热度阈值
  HEAT_THRESHOLDS: {
    HOT: 3000, // 🔥 热门
    WARM: 1500, // 🌟 温
  },

  // 热度权重
  HEAT_WEIGHTS: {
    ZT_COUNT: 1000, // 每个涨停股 +1000
    LEADER_COUNT: 500, // 每个龙头股 +500
    CONTINUOUS_DAY: 200, // 每个连板天数 +200
    STOCK_BASE: 10, // 每只股票 +10
    HOT_SCORE: 1, // 个股热度分
    CORRELATION_BONUS: 0.2, // 联动系数加成
  },

  // 动量配置
  MOMENTUM: {
    SHORT_WINDOW: 3,
    LONG_WINDOW: 6,
    TREND_WINDOW: 5,
    PCT_WEIGHT: 0.6,
    TREND_WEIGHT: 0.3,
    ACCEL_WEIGHT: 0.1,
  },

  // 轮动状态
  ROTATION_STATES: {
    BULL_WAVE: { name: '主升浪', icon: '⚡', color: '#ff6b81', threshold: 50 },
    STRONG_ATTACK: { name: '强势进攻', icon: '🚀', color: '#ff4757', threshold: 20 },
    OSC_UP: { name: '震荡上行', icon: '⬆️', color: '#f39c12', threshold: 10 },
    OSCILLATION: { name: '震荡', icon: '🔄', color: '#95a5a6', threshold: -10 },
    OSC_DOWN: { name: '震荡下行', icon: '↘️', color: '#7f8c8d', threshold: -20 },
    WEAK_EBB: { name: '弱势退潮', icon: '⬇️', color: '#3498db', threshold: -20 },
    BEAR_WAVE: { name: '主跌浪', icon: '⚠️', color: '#2c3e50', threshold: -50 },
  },

  // 调试模式
  DEBUG: false,

  // 同步防抖时间
  SYNC_DEBOUNCE_MS: 500,
} as const

const SAME_ORIGIN_API_BASE =
  typeof window !== 'undefined' && window.location?.origin
    ? window.location.origin
    : 'http://localhost:3000'

/**
 * API 服务配置 - 与 apiService 深度整合
 */
export const API_CONFIG = {
  // ===== 代理服务器配置 =====
  PROXIES: {
    PROXY_3000: 'http://localhost:3000', // 热榜、行情代理（有源码）
    QUANT_BOARD: SAME_ORIGIN_API_BASE, // 通过 3000/Vite 同源代理访问 QuantBoard 后端
  },

  // ===== 请求默认配置 =====
  DEFAULTS: {
    TIMEOUT: 10000,
    RETRIES: 2,
    RETRY_DELAY: 1000,
    CACHE_TTL: 30000,
  },

  // ===== 各业务模块的专用配置 =====
  CONTEXTS: {
    // 平台热榜数据 - 走3000
    PLATFORM: {
      baseURL: 'http://localhost:3000',
      timeout: 8000,
      retries: 2,
      cacheTTL: 60000,
      priority: 'medium' as const,
      batchSize: 8,
    },
    // 行情数据 - 走3000
    QUOTE: {
      baseURL: 'http://localhost:3000',
      timeout: 5000,
      retries: 1,
      cacheTTL: 2000,
      priority: 'high' as const,
      batchSize: 20,
    },
    // 情绪数据 - 走3000
    BREATH: {
      baseURL: 'http://localhost:3000',
      timeout: 8000,
      retries: 2,
      cacheTTL: 30000,
      priority: 'medium' as const,
    },
    // 通达信数据 - 走3000
    TDX: {
      baseURL: 'http://localhost:3000',
      timeout: 3000,
      retries: 1,
      cacheTTL: 30000,
      priority: 'high' as const,
    },
    // 涨停数据 - 走3000
    LIMITUP: {
      baseURL: 'http://localhost:3000',
      timeout: 8000,
      retries: 2,
      cacheTTL: 10000,
      priority: 'medium' as const,
    },
    // 市场概览 - 走3000
    MARKET: {
      baseURL: 'http://localhost:3000',
      timeout: 5000,
      retries: 2,
      cacheTTL: 10000,
      priority: 'high' as const,
    },
    'big-order': {
      baseURL: 'http://localhost:3000', // 通过代理服务器
      timeout: 15000,
      retries: 3,
      cacheTTL: 30000,
      priority: 'high' as const,
    },
    QUANT_BOARD: {
      baseURL: SAME_ORIGIN_API_BASE,
      timeout: 15000,
      retries: 1,
      cacheTTL: 0,
      priority: 'high' as const,
    },
  },

  // ===== 接口端点定义 =====
  ENDPOINTS: {
    // 八平台热榜（3000）
    PLATFORMS: {
      XUEQIU: '/api/xueqiu/hot',
      CLS: '/api/cls/hot',
      EASTMONEY: '/api/eastmoney/hot',
      THS: '/api/ths/hot',
      KPL: '/api/kpl/hot',
      TDX: '/api/tdx/hot',
      TGB: '/api/tgb/hot',
      DZH: '/api/dzh/hot',
    },
    // 行情数据（3000）
    QUOTES: {
      TENCENT: '/api/quotes/tencent',
      EASTMONEY: '/api/quotes/eastmoney',
      SINA: '/api/quotes/sina',
    },
    // 涨停数据（3000）
    LIMITUP: {
      TODAY: '/api/limitup/10jqka',
      PERFORMANCE: '/api/surge-stock/performance',
    },
    // 市场数据（3000）
    MARKET: {
      OVERVIEW: '/api/market/overview',
      SENTIMENT: '/api/sentiment/composite',
    },
    // 通达信接口（3000）
    TDX: {
      MARKET_STATS: 'HQServ.PBSdstat',
      LIMIT_DATA: 'HQServ.hq_nlp_misc',
      YESTERDAY_INFO: 'CWServ.cfg_fx_dxqx_jyr',
      ZHABAN_DATA: 'HQServ.hq_nlp_dxqx',
      EMOTION_DATA: 'HQServ.hq_nlp_dxqx',
    },
  },

  // ===== 通达信接口参数 =====
  TDX_PARAMS: {
    MARKET_STATS: { Head: { Target: 0 }, Type: '4' },
    LIMIT_DATA: [
      {
        ReqId: '201054',
        Tdate: '',
        Market: '0',
        blockstyle: '3',
        modname: 'module_misc.dll',
      },
    ],
    YESTERDAY_INFO: { Params: [] },
    ZHABAN_DATA: [
      {
        ReqId: '1000',
        Market: '0',
        BkCode: '880201',
        blockstyle: 'string',
        modname: 'module_misc.dll',
      },
    ],
    EMOTION_DATA: [
      {
        ReqId: '200200',
        Code: 'DXQX_AG',
        IndexCode: '999999',
        BeginDate: '',
        EndDate: '',
        TradeDays: '1',
        Page: '0',
        PageSize: '5',
        modname: 'mod_dxqx.dll',
      },
    ],
  },

  // ===== 限流配置 =====
  RATE_LIMIT: {
    DAILY_LIMIT: 3000,
    BURST_LIMIT: 100,
    MIN_INTERVAL: 200,
    MAX_BATCH_SIZE: 100,
    BATCH_SPLIT_SIZE: 50,
  },

  // ===== 反馈配置 =====
  FEEDBACK: {
    ENABLED: true,
    COOLDOWN: 5000,
  },

  // ===== 日志配置 =====
  LOG_LEVEL: {
    DEBUG: false,
    INFO: true,
    WARN: true,
    ERROR: true,
  },

  // ===== LRU缓存配置 =====
  LRU_CACHE: {
    HISTORY_KEY: 'breath_history',
    HISTORY_TTL: 7 * 24 * 60 * 60 * 1000,
  },

  // ===== 自动刷新配置 =====
  AUTO_REFRESH: true,
  REFRESH_INTERVAL: 30000,
} as const

// ========== 轮动分析器配置 ==========
export const ROTATION_CONFIG = {
  // 轮动分析开关
  ENABLED: true,

  // 分析间隔（毫秒）
  ANALYSIS_INTERVAL: 5000,

  // 资金阈值（万元）
  FUND_THRESHOLDS: {
    STRONG_INFLOW: 5000, // 强势流入：>5000万
    MEDIUM_INFLOW: 1000, // 中等流入：>1000万
    STRONG_OUTFLOW: -3000, // 强势流出：<-3000万
    MEDIUM_OUTFLOW: -1000, // 中等流出：<-1000万
  },

  // 涨停阈值
  ZT_THRESHOLDS: {
    STRONG: 5, // 强势：5只以上涨停
    MEDIUM: 3, // 中等：3-4只涨停
    WEAK: 1, // 弱势：1-2只涨停
  },

  // 持续性阈值（天数）
  PERSISTENCE: {
    MAIN_LINE: 3, // 主线：持续3天以上
    QUICK_ROTATION: 1, // 快速轮动：1天
    OVERHEAT: 5, // 过热：持续5天以上
  },

  // 排名变化阈值
  RANK_CHANGE: {
    SURGE: -10, // 飙升：排名上升10位以上
    UP: -5, // 上升：排名上升5-9位
    DOWN: 5, // 下降：排名下降5-9位
    PLUNGE: 10, // 暴跌：排名下降10位以上
  },

  // 轮动速度阈值（百分比）
  ROTATION_SPEED: {
    FAST: 70, // 快速轮动：>70%
    NORMAL: 40, // 正常轮动：40-70%
    SLOW: 20, // 缓慢轮动：20-40%
    STABLE: 20, // 稳定：<20%
  },

  // 市场阶段配置 - 已移至 emotion.ts，此处在注释中保留引用
  // @see {@link EMOTION_PHASES} in '@/types/emotion'
  // MARKET_PHASES: { ... }  // 已删除

  // 阶段判定阈值
  PHASE_THRESHOLDS: {
    // 上升期：主线>=3条 且 轮动速度<50%
    RISING: { MAIN_LINES: 3, MAX_SPEED: 50 },
    // 出货期：轮动速度>70%
    DISTRIBUTION: { MIN_SPEED: 70 },
    // 下降期：流出板块>流入板块*2
    FALLING: { OUTFLOW_RATIO: 2 },
  },

  // 历史数据保留数量
  HISTORY_LIMIT: 100,

  // 调试模式
  DEBUG: false,
} as const

// ========== 预警系统配置 ==========
export const ALERT_CONFIG = {
  // 预警开关
  ENABLED: true,

  // 检查间隔（毫秒）
  CHECK_INTERVAL: 10000,

  // 最大预警数量
  MAX_ALERTS: 100,

  // 预警冷却时间（毫秒，同一类型避免重复）
  COOLDOWN: 5 * 60 * 1000, // 5分钟

  // 预警过期时间（毫秒）
  EXPIRE_TIME: 30 * 60 * 1000, // 30分钟

  // 历史数据保留时间（毫秒）
  HISTORY_RETENTION: 24 * 60 * 60 * 1000, // 24小时

  // 批量处理大小
  BATCH_SIZE: 100,
} as const

// ========== 预警类型定义 ==========
export const ALERT_TYPES = {
  LEADER_FALL: 'leader_fall', // 龙头倒下
  LEADER_EMERGE: 'leader_emerge', // 龙头涌现
  BATCH_LIMIT_UP: 'batch_limit_up', // 批量涨停
  BATCH_EXPLODE: 'batch_explode', // 批量炸板
  HEAT_SURGE: 'heat_surge', // 热度飙升
  HEAT_PLUNGE: 'heat_plunge', // 热度骤降
  VOLUME_SURGE: 'volume_surge', // 放量异动
  ROTATION_SIGNAL: 'rotation_signal', // 轮动信号
  MONEY_FLOW: 'money_flow', // 资金异动
  DATA_ANOMALY: 'data_anomaly', // 数据异常
  RANK_FAST_RISE: 'rank_fast_rise', // 排名快速上升
  RANK_FAST_FALL: 'rank_fast_fall', // 排名快速下降
} as const

// ========== 预警级别定义 ==========
export const ALERT_LEVELS = {
  CRITICAL: 'critical', // 严重预警
  WARNING: 'warning', // 警告预警
  INFO: 'info', // 提示信息
} as const

// ========== 预警级别显示配置 ==========
export const ALERT_LEVEL_DISPLAY = {
  [ALERT_LEVELS.CRITICAL]: {
    name: '严重',
    icon: '🔴',
    color: '#ff4757',
    bgColor: 'rgba(255, 71, 87, 0.1)',
  },
  [ALERT_LEVELS.WARNING]: {
    name: '警告',
    icon: '🟡',
    color: '#f39c12',
    bgColor: 'rgba(243, 156, 18, 0.1)',
  },
  [ALERT_LEVELS.INFO]: {
    name: '提示',
    icon: '🔵',
    color: '#3498db',
    bgColor: 'rgba(52, 152, 219, 0.1)',
  },
} as const

// ========== 预警类型显示配置 ==========
export const ALERT_TYPE_DISPLAY = {
  [ALERT_TYPES.LEADER_FALL]: {
    name: '龙头倒下',
    icon: '👑',
    desc: '龙头股跌停或大跌',
    level: ALERT_LEVELS.CRITICAL,
  },
  [ALERT_TYPES.LEADER_EMERGE]: {
    name: '龙头涌现',
    icon: '🌟',
    desc: '新龙头出现',
    level: ALERT_LEVELS.WARNING,
  },
  [ALERT_TYPES.BATCH_LIMIT_UP]: {
    name: '批量涨停',
    icon: '📈',
    desc: '多只股票涨停',
    level: ALERT_LEVELS.WARNING,
  },
  [ALERT_TYPES.BATCH_EXPLODE]: {
    name: '批量炸板',
    icon: '💥',
    desc: '多只涨停股炸板',
    level: ALERT_LEVELS.CRITICAL,
  },
  [ALERT_TYPES.HEAT_SURGE]: {
    name: '热度飙升',
    icon: '🔥',
    desc: '题材热度快速上升',
    level: ALERT_LEVELS.INFO,
  },
  [ALERT_TYPES.HEAT_PLUNGE]: {
    name: '热度骤降',
    icon: '❄️',
    desc: '题材热度快速下降',
    level: ALERT_LEVELS.WARNING,
  },
  [ALERT_TYPES.VOLUME_SURGE]: {
    name: '放量异动',
    icon: '📊',
    desc: '成交额异常放大',
    level: ALERT_LEVELS.INFO,
  },
  [ALERT_TYPES.ROTATION_SIGNAL]: {
    name: '轮动信号',
    icon: '🔄',
    desc: '板块轮动加速',
    level: ALERT_LEVELS.INFO,
  },
  [ALERT_TYPES.MONEY_FLOW]: {
    name: '资金异动',
    icon: '💰',
    desc: '资金流入/流出异常',
    level: ALERT_LEVELS.WARNING,
  },
  [ALERT_TYPES.DATA_ANOMALY]: {
    name: '数据异常',
    icon: '⚠️',
    desc: '数据质量或映射异常',
    level: ALERT_LEVELS.INFO,
  },
} as const

// ========== 预警阈值配置 ==========
export const ALERT_THRESHOLDS = {
  // 龙头倒下
  LEADER_FALL: {
    CRITICAL: -9.5, // 跌停
    WARNING: -7, // 大跌7%
  },

  // 批量涨停
  BATCH_LIMIT_UP: {
    CRITICAL: 5, // 5只以上涨停
    WARNING: 3, // 3-4只涨停
  },

  // 批量炸板
  BATCH_EXPLODE: {
    CRITICAL: 5, // 5只以上炸板
    WARNING: 3, // 3-4只炸板
  },

  // 热度变化（百分比）
  HEAT_CHANGE: {
    SURGE: 30, // 飙升30%
    PLUNGE: -30, // 骤降30%
  },

  // 放量倍数
  VOLUME_SURGE: {
    CRITICAL: 5, // 5倍以上
    WARNING: 3, // 3-5倍
    INFO: 2, // 2-3倍
  },

  // 资金异动（万元）
  MONEY_FLOW: {
    STRONG_INFLOW: 10000, // 1亿以上流入
    STRONG_OUTFLOW: -10000, // 1亿以上流出
    WARNING_INFLOW: 5000, // 5000万以上流入
    WARNING_OUTFLOW: -5000, // 5000万以上流出
  },

  // 轮动速度
  ROTATION_SPEED: {
    FAST: 70, // 快速轮动
    SLOW: 30, // 缓慢轮动
  },

  // 排名变化预警
  RANK_CHANGE: {
    FAST_RISE: 5, // 快速上升阈值（上升超过5名）
    FAST_FALL: 5, // 快速下降阈值（下降超过5名）
    CRITICAL_RISE: 10, // 剧烈上升阈值
    CRITICAL_FALL: 10, // 剧烈下降阈值
  },
} as const

// ========== 标记算法阈值 ==========
export const MARKER_THRESHOLDS = {
  IGNITE: {
    MIN_AMOUNT: 300, // 最小金额（万元）
    RATIO: 2.0, // 倍数阈值
  },
  SMASH: {
    MIN_AMOUNT: 300, // 最小金额（万元）
    RATIO: 2.0, // 倍数阈值
  },
  BUY_ACTIVE: {
    MIN_AVG: 100, // 最小平均金额（万元）
  },
  GOOD_SUPPORT: {
    MIN_AVG: 300, // 最小平均金额（万元）
  },
  SUPER_BIG: 1000, // 超大单阈值（万元）
  DENSE_COUNT: 5, // 密集大单阈值（5笔/分钟）
  DENSE_WINDOW: 60000, // 密集窗口（60秒）
} as const

// ========== 时间窗口常量 ==========
export const TIME_WINDOWS = {
  PAST_6S: 6, // 6秒
  PAST_50S: 50, // 50秒
  FUTURE_6S: 6, // 6秒
} as const

// ========== 交易时间段常量 ==========
export const PERIODS = [
  { name: '09:30-10:00', start: '09:30', end: '10:00' },
  { name: '10:00-10:30', start: '10:00', end: '10:30' },
  { name: '10:30-11:00', start: '10:30', end: '11:00' },
  { name: '11:00-11:30', start: '11:00', end: '11:30' },
  { name: '13:00-13:30', start: '13:00', end: '13:30' },
  { name: '13:30-14:00', start: '13:30', end: '14:00' },
  { name: '14:00-14:30', start: '14:00', end: '14:30' },
  { name: '14:30-15:00', start: '14:30', end: '15:00' },
] as const

// ========== 涨停判断配置 ==========
export const LIMIT_UP_CONFIG = {
  // 各板块涨停阈值
  THRESHOLDS: {
    MAIN: 9.8, // 主板（±10%）
    GEM: 19.8, // 创业板（±20%）
    STAR: 19.8, // 科创板（±20%）
    NORTH: 29.8, // 北交所（±30%）
    ST: 4.95, // ST股（±5%）
  },

  // 涨停判断规则
  RULES: {
    // 是否要求有封单
    REQUIRE_FENGDAN: true,
    // 最小封单额（万元）
    MIN_FENGDAN: 1000,
    // 是否考虑板块效应（板块内有多个涨停才算强势）
    CONSIDER_SECTOR_EFFECT: true,
    // 新股保护天数（上市不足此天数不判断涨停）
    NEW_STOCK_PROTECTION_DAYS: 20,
    // 涨幅容差范围（涨停价±容差）
    CHANGE_TOLERANCE: 0.5,
  },

  // 连板判断
  CONTINUOUS: {
    // 连板天数字段名
    DAYS_FIELD: 'continuousDays',
    // 是否从涨停时间判断（早盘涨停加分）
    USE_TIME_CHECK: true,
    // 早盘涨停时间阈值（10:30之前）
    EARLY_LIMIT_TIME: '10:30',
  },
} as const

// ========== 预警情绪乘数配置 ==========
export const ALERT_EMOTION_MULTIPLIERS = {
  BY_PHASE: {
    冰点: 0.7,
    启动: 0.9,
    发酵: 1.1,
    高潮: 1.3,
    退潮: 1.1,
  },
  BY_ALERT_TYPE: {
    rocket_launch: {
      冰点: 0.6,
      高潮: 1.5,
    },
    waterfall_dive: {
      冰点: 0.6,
      高潮: 1.5,
    },
    leader_fall: {
      冰点: 0.5,
      高潮: 1.2,
    },
    fengdan_drop: {
      冰点: 0.8,
      高潮: 1.2,
    },
  },
} as const

// ========== 批量涨停细化配置 ==========
export const BATCH_LIMIT_UP_CONFIG = {
  // 按板块规模的不同阈值
  BY_SECTOR_SIZE: {
    SMALL: {
      // 小板块：20只以下
      WARNING: { RATIO: 0.2, COUNT: 2 }, // 20%或2只触发警告
      CRITICAL: { RATIO: 0.4, COUNT: 4 }, // 40%或4只触发严重
    },
    MEDIUM: {
      // 中板块：20-50只
      WARNING: { RATIO: 0.15, COUNT: 4 }, // 15%或4只触发警告
      CRITICAL: { RATIO: 0.3, COUNT: 8 }, // 30%或8只触发严重
    },
    LARGE: {
      // 大板块：50只以上
      WARNING: { RATIO: 0.1, COUNT: 5 }, // 10%或5只触发警告
      CRITICAL: { RATIO: 0.2, COUNT: 10 }, // 20%或10只触发严重
    },
  },

  // 是否启用比例判断
  USE_RATIO: true,
  // 是否启用数量判断
  USE_COUNT: true,
} as const

// ========== 补充预警阈值配置 ==========
export const ALERT_THRESHOLDS_EXTENDED = {
  // 涨速阈值（%）
  SPEED: {
    ROCKET: 3, // 火箭发射阈值
    DIVE: -3, // 瀑布跳水阈值
    MAX_LIMIT: 20, // 最大限制（过滤异常值）
  },

  // 封单减少阈值（%）
  FENGDAN_DROP: 50,

  // 强度变化阈值（%）
  STRENGTH_CHANGE: {
    SURGE: 30, // 飙升阈值
    PLUNGE: -30, // 骤降阈值
  },

  // 个股资金异动阈值（万元）
  STOCK_MONEY_FLOW: {
    STRONG_INFLOW: 5000, // 强势流入
    STRONG_OUTFLOW: -5000, // 强势流出
    WARNING_INFLOW: 2000, // 警告流入
    WARNING_OUTFLOW: -2000, // 警告流出
  },
} as const

// ========== 个股异动配置 ==========
export const STOCK_ALERT_CONFIG = {
  // 火箭发射
  ROCKET_LAUNCH: {
    // 最小涨速阈值
    MIN_SPEED: 3,
    // 最大涨幅限制（避免高位异常）
    MAX_CHANGE: 15,
    // 是否要求放量
    REQUIRE_VOLUME: true,
    // 最小量比
    MIN_VOLUME_RATIO: 1.5,
  },

  // 瀑布跳水
  WATERFALL_DIVE: {
    // 最大跌速阈值
    MAX_SPEED: -3,
    // 最小跌幅限制
    MIN_CHANGE: -15,
    // 是否要求放量
    REQUIRE_VOLUME: true,
    // 最小量比
    MIN_VOLUME_RATIO: 1.5,
  },

  // 封单减少
  FENGDAN_DROP: {
    // 最小减少百分比
    MIN_DROP_PERCENT: 50,
    // 最小原始封单（万元）
    MIN_ORIGINAL_FENGDAN: 2000,
    // 检查时间窗口（毫秒）
    CHECK_WINDOW: 5 * 60 * 1000,
  },
} as const

// ========== 板块预警配置 ==========
export const SECTOR_ALERT_CONFIG = {
  // 批量涨停
  BATCH_LIMIT_UP: BATCH_LIMIT_UP_CONFIG,

  // 资金异动
  MONEY_FLOW: {
    // 最小净额（万元）
    MIN_NET_INFLOW: 5000,
    // 最小变化百分比（对比前值）
    MIN_CHANGE_PERCENT: 50,
  },

  // 强度变化
  STRENGTH_CHANGE: {
    SURGE: 30,
    PLUNGE: -30,
    // 最小强度值（低于此值不预警）
    MIN_STRENGTH: 500,
  },

  // 放量异动
  VOLUME_SURGE: {
    CRITICAL: 5, // 5倍以上
    WARNING: 3, // 3-5倍
    INFO: 2, // 2-3倍
    // 最小基础量比（低于此值不预警）
    MIN_BASE_VOLUME_RATIO: 0.5,
  },
} as const
