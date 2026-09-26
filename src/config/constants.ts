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
      timeout: 15000,
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

  // 分析间隔（毫秒）：题材轮动分析是前端同步重计算，5s 会持续占用主线程。
  // 后端 theme_heat 已有独立刷新周期，前端降频到 30s 即可保证展示新鲜度。
  ANALYSIS_INTERVAL: 30000,

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
  { name: '15:00-15:30', start: '15:00', end: '15:30' },
] as const

// ========== 涨停判断配置 ==========
export const LIMIT_UP_CONFIG = {
  // 各板块涨停阈值（2026-09 起主板 ST 涨跌幅 ±10%，与主板一致，不再单列 ST 阈值）
  THRESHOLDS: {
    MAIN: 9.8, // 主板（±10%，含主板 ST）
    GEM: 19.8, // 创业板（±20%）
    STAR: 19.8, // 科创板（±20%）
    NORTH: 29.8, // 北交所（±30%）
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

