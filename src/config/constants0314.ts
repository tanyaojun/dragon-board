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

  // 预警阈值
  ALERT_THRESHOLDS: {
    HEAT_SURGE: 0.5, // 热度暴涨50%
    MOMENTUM_BREAK: 30, // 动量突破30
    LEADER_DROP: -0.05, // 龙头股跌幅超过5%
  },

  // 调试模式
  DEBUG: false,

  // 同步防抖时间
  SYNC_DEBOUNCE_MS: 500,
} as const

/**
 * 情绪周期定义（与 DragonBreathAnalyzer 共享）
 */
export const MARKET_PHASES = {
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
    // ✅ 添加阈值乘数
    thresholdMultiplier: {
      totalLeader: 0.9,
      continuousLeader: 0.85,
      sectorLeader: 0.8,
      middleLeader: 0.75,
      emotionLeader: 0.7,
    },
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
    thresholdMultiplier: {
      totalLeader: 0.95,
      continuousLeader: 0.9,
      sectorLeader: 0.85,
      middleLeader: 0.8,
      emotionLeader: 0.75,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.0,
      continuousLeader: 1.0,
      sectorLeader: 1.0,
      middleLeader: 1.0,
      emotionLeader: 1.0,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.05,
      continuousLeader: 1.05,
      sectorLeader: 1.05,
      middleLeader: 1.0,
      emotionLeader: 1.0,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.1,
      continuousLeader: 1.1,
      sectorLeader: 1.05,
      middleLeader: 1.05,
      emotionLeader: 1.0,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.15,
      continuousLeader: 1.15,
      sectorLeader: 1.1,
      middleLeader: 1.05,
      emotionLeader: 1.05,
    },
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
    thresholdMultiplier: {
      totalLeader: 1.2,
      continuousLeader: 1.15,
      sectorLeader: 1.1,
      middleLeader: 1.05,
      emotionLeader: 1.0,
    },
  },
} as const

/**
 * 龙头级别定义（与 DragonAnalyzer 共享）
 */
export const LEADER_LEVELS = {
  TOTAL: { name: '总龙头', icon: '👑', color: '#FFD700', order: 1, minScore: 80 },
  CONTINUOUS: { name: '连板龙头', icon: '📈', color: '#e74c3c', order: 2, minScore: 70 },
  SECTOR: { name: '板块龙头', icon: '🏆', color: '#3498db', order: 3, minScore: 65 },
  MIDDLE: { name: '中军龙头', icon: '⚔️', color: '#9b59b6', order: 4, minScore: 60 },
  EMOTION: { name: '情绪龙头', icon: '🔥', color: '#f39c12', order: 5, minScore: 55 },
} as const

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

/**
 * 题材对情绪的影响权重
 */
export const THEME_IMPACT_WEIGHTS = {
  HOT_THEME_COUNT: 0.3, // 热门题材数量
  THEME_MOMENTUM: 0.4, // 题材动量
  THEME_CORRELATION: 0.3, // 题材联动性
} as const

/**
 * 应用事件名称
 */
export const APP_EVENTS = {
  DATA: {
    MERGED: 'data:merged',
    UPDATED: 'data:updated',
    PLATFORMS_LOADED: 'platforms:loaded',
    QUOTES_UPDATED: 'quotes:updated',
  },
  SECTOR: {
    UPDATED: 'sector:updated',
    READY: 'sector:ready',
    BATCH_UPDATED: 'sector:batch:updated',
    HOT_UPDATED: 'sector:hot:updated',
    ALERT: 'sector:alert',
  },
  DRAGON: {
    UPDATED: 'dragon:updated',
    CHANGED: 'dragon:changed',
  },
  STOCK: {
    SELECTED: 'stock:selected',
    CLEARED: 'stock:cleared',
  },
  UI: {
    PANEL_OPEN: 'ui:panel:open',
    PANEL_CLOSE: 'ui:panel:close',
    TOAST: 'ui:toast',
  },
  REFRESH: {
    STARTED: 'refresh:started',
    COMPLETE: 'refresh:complete',
    FAIL: 'refresh:fail',
  },
} as const

/**
 * 默认阈值（与 AlgorithmManager 共享）
 */
export const DEFAULT_THRESHOLDS = {
  totalLeader: 80,
  sectorLeader: 65,
  continuousLeader: 70,
  middleLeader: 60,
  emotionLeader: 55,
} as const

/**
 * 阈值范围
 */
export const THRESHOLD_RANGES = {
  totalLeader: { min: 60, max: 95 },
  sectorLeader: { min: 45, max: 85 },
  continuousLeader: { min: 50, max: 90 },
  middleLeader: { min: 40, max: 80 },
  emotionLeader: { min: 35, max: 75 },
} as const

/**
 * 存储键名
 */
export const STORAGE_KEYS = {
  // 算法相关
  ALGORITHM: 'algorithm',
  WEIGHTS: 'algorithm_weights',
  THRESHOLDS: 'algorithm_thresholds',
  HISTORY: 'algorithm_history',

  // 配置相关
  APP_CONFIG: 'app_config',
  USER_THEME: 'kpl_theme',
  REFRESH_STRATEGY: 'refresh_strategy',

  // 阈值乘数配置
  THRESHOLD_MULTIPLIERS: 'threshold_multipliers',

  // 缓存相关
  SECTOR_CACHE: 'sector_cache',
  DRAGON_CACHE: 'dragon_cache',
  BREATH_CACHE: 'breath_cache',
} as const

/**
 * API 服务配置 - 与 apiService 深度整合
 */
export const API_CONFIG = {
  // 基础配置
  BASE_URL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:3000',
  PROXY_URL: import.meta.env.VITE_PROXY_URL || 'http://localhost:3000',

  // ===== 请求默认配置 =====
  DEFAULTS: {
    TIMEOUT: 10000,
    RETRIES: 2,
    RETRY_DELAY: 1000,
    CACHE_TTL: 30000,
  },

  // ===== 各业务模块的专用配置 =====
  CONTEXTS: {
    // 平台热榜数据
    PLATFORM: {
      timeout: 8000,
      retries: 2,
      cacheTTL: 60000,
      priority: 'medium' as const,
      batchSize: 8, // 8个平台同时请求
    },
    // 行情数据
    QUOTE: {
      timeout: 5000,
      retries: 1,
      cacheTTL: 2000,
      priority: 'high' as const,
      batchSize: 20, // 每批20只股票
    },
    // 题材数据
    THEME: {
      timeout: 10000,
      retries: 3,
      cacheTTL: 300000, // 5分钟
      priority: 'low' as const,
      batchSize: 10,
    },
    // 情绪数据
    BREATH: {
      timeout: 8000,
      retries: 2,
      cacheTTL: 30000,
      priority: 'medium' as const,
    },
    // 通达信数据
    TDX: {
      timeout: 3000,
      retries: 1,
      cacheTTL: 30000,
      priority: 'high' as const,
    },
    // 涨停数据
    LIMITUP: {
      timeout: 8000,
      retries: 2,
      cacheTTL: 10000,
      priority: 'medium' as const,
    },
    // 市场概览
    MARKET: {
      timeout: 5000,
      retries: 2,
      cacheTTL: 10000,
      priority: 'high' as const,
    },
  },

  // ===== 接口端点定义 =====
  ENDPOINTS: {
    // 八平台热榜
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
    // 行情数据
    QUOTES: {
      TENCENT: '/api/quotes/tencent',
      EASTMONEY: '/api/quotes/eastmoney',
      SINA: '/api/quotes/sina',
      SPK: '/api/quotes/tencent/spk', // 盘口数据
    },
    // 题材数据
    THEMES: {
      DETAIL: (id: string) => `/api/theme/${id}`,
      BATCH: '/api/themes/batch',
    },
    // 涨停数据
    LIMITUP: {
      TODAY: '/api/limitup/10jqka',
      DETAIL: '/api/limitup/detail',
      PERFORMANCE: '/api/surge-stock/performance',
    },
    // 市场数据
    MARKET: {
      OVERVIEW: '/api/market/overview',
      SENTIMENT: '/api/sentiment/composite',
    },
    // 通达信接口
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

  // 市场阶段配置
  MARKET_PHASES: {
    ACCUMULATION: {
      name: '筑底期',
      value: 'accumulation',
      icon: '🏗️',
      color: '#7f8c8d',
      desc: '资金缓慢流入，主线初步形成',
      suggestion: '轻仓试错，关注率先企稳板块',
    },
    RISING: {
      name: '上升期',
      value: 'rising',
      icon: '📈',
      color: '#e74c3c',
      desc: '主线明确，资金持续流入',
      suggestion: '积极参与，紧跟主线',
    },
    DISTRIBUTION: {
      name: '出货期',
      value: 'distribution',
      icon: '📊',
      color: '#f39c12',
      desc: '轮动加快，资金分歧加大',
      suggestion: '控制仓位，快进快出',
    },
    FALLING: {
      name: '下降期',
      value: 'falling',
      icon: '📉',
      color: '#3498db',
      desc: '资金持续流出，主线退潮',
      suggestion: '空仓观望，等待企稳',
    },
  },

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
} as const

// ========== 扩展存储键名 ==========
export const EXTENDED_STORAGE_KEYS = {
  ROTATION_CACHE: 'rotation_cache',
  ROTATION_HISTORY: 'rotation_history',
  ALERT_CACHE: 'alert_cache',
  ALERT_HISTORY: 'alert_history',
} as const

// ========== 扩展API端点 ==========
export const EXTENDED_API_ENDPOINTS = {
  ROTATION: {
    ANALYSIS: '/api/rotation/analysis',
    HISTORY: '/api/rotation/history',
  },
  ALERT: {
    LIST: '/api/alert/list',
    STATS: '/api/alert/stats',
    MARK_READ: '/api/alert/read',
    CLEAR: '/api/alert/clear',
  },
} as const
