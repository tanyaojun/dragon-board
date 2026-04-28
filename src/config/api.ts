// src/config/api.ts
// API统一管理配置文件 - 客户端版本

/**
 * API 端点配置
 * 所有请求都通过本地代理服务器
 */
export const API_ENDPOINTS = {
  // 基础URL
  BASE_URL: 'http://localhost:3000',

  // ===== 行情数据 =====
  QUOTES: {
    // 智能路由（自动选择最佳数据源）
    SMART: '/api/quotes/smart',

    // 各数据源（可直接指定）
    TENCENT: '/api/quotes/tencent',
    EASTMONEY: '/api/quotes/eastmoney',
    SINA: '/api/quotes/sina',
  },

  // ===== 热门股票数据（各平台） =====
  HOT_STOCKS: {
    XUEQIU: '/api/xueqiu/hot', // 雪球
    CLS: '/api/cls/hot', // 财联社
    EASTMONEY: '/api/eastmoney/hot', // 东方财富
    THS: '/api/ths/hot', // 同花顺
    KPL: '/api/kpl/hot', // 开盘啦
    TDX: '/api/tdx/hot', // 通达信
    TGB: '/api/tgb/hot', // 淘股吧
    DZH: '/api/dzh/hot', // 大智慧
  },

  // ===== 题材数据 =====
  SECTOR: {
    // 题材详情
    DETAIL: (id: string) => `/api/theme/${id}`,
  },

  // ===== 通达信数据（情绪面板） =====
  TDX: {
    // 通用代理入口
    PROXY: (entry: string) => `/api/tdx/${entry}`,

    // 预定义的接口入口
    ENTRIES: {
      MARKET_STATS: 'HQServ.PBSdstat', // 市场统计
      LIMIT_DATA: 'HQServ.hq_nlp_misc', // 涨停数据
      YESTERDAY_INFO: 'CWServ.cfg_fx_dxqx_jyr', // 昨日信息
      ZHABAN_DATA: 'HQServ.hq_nlp_dxqx', // 炸板数据
      EMOTION_DATA: 'HQServ.hq_nlp_dxqx', // 情绪数据
    },
  },

  // ===== 数据源管理 =====
  DATA_SOURCE: {
    STATUS: '/api/data-source/status',
    SWITCH: '/api/data-source/switch',
  },

  // ===== 测试 =====
  TEST: '/api/test',
  HEALTH: '/health',
} as const

/**
 * 请求超时配置（毫秒）
 */
export const API_TIMEOUT = {
  QUOTE: 5000, // 行情数据（需快速响应）
  HOT: 8000, // 热门数据
  SECTOR: 10000, // 题材数据
  TDX: 8000, // 通达信数据
  DEFAULT: 10000, // 默认
} as const

/**
 * 重试配置
 */
export const API_RETRY = {
  COUNT: 2, // 重试次数
  DELAY: 1000, // 初始延迟
  BACKOFF: 1.5, // 退避系数
} as const

/**
 * 缓存配置（客户端缓存）
 */
export const API_CACHE = {
  // 各类型数据缓存时间（毫秒）
  TTL: {
    QUOTE: 3000, // 行情数据缓存3秒
    HOT: 10000, // 热门数据缓存10秒
    SECTOR: 300000, // 题材数据缓存5分钟
    TDX: 5000, // 通达信数据缓存5秒
  },

  // 最大缓存数量
  MAX_SIZE: 1000,
} as const

/**
 * 请求优先级
 */
export type RequestPriority = 'high' | 'medium' | 'low'

/**
 * 请求选项
 */
export interface RequestOptions {
  priority?: RequestPriority
  timeout?: number
  retries?: number
  cache?: boolean
  cacheTTL?: number
  signal?: AbortSignal
  headers?: Record<string, string>
  method?: string
  body?: any
}

/**
 * 批量获取行情的参数
 */
export interface QuotesParams {
  codes: string[] | string
  source?: 'smart' | 'tencent' | 'eastmoney' | 'sina'
}

/**
 * 通达信请求参数
 */
export interface TdxParams {
  entry: string
  data: any[]
}

/**
 * 题材请求参数
 */
export interface SectorParams {
  id: string
}

/**
 * 响应格式（兼容原有格式）
 */
export interface ApiResponse<T = any> {
  rc?: number
  data?: {
    diff?: T[]
    [key: string]: any
  }
  List?: any[]
  list?: any[]
  error?: string
  message?: string
  [key: string]: any
}

// ========== 腾讯财经字段映射 ==========
export const TENCENT_FIELDS = {
  CODE: 2, // 股票代码
  NAME: 1, // 股票名称
  PRICE: 3, // 当前价
  PREV_CLOSE: 4, // 昨收
  CHANGE: 32, // 涨跌幅
  VOLUME: 6, // 成交量(手)
  TURNOVER_RATE: 38, // 换手率
  PE: 39, // 市盈率
  CIR_MV: 44, // 流通市值(万)
  TOTAL_MV: 45, // 总市值(万)
  PB: 46, // 市净率
} as const

// ========== 东方财富字段映射 ==========
export const EASTMONEY_FIELDS = {
  CODE: 'f12',
  NAME: 'f14',
  PRICE: 'f2',
  CHANGE: 'f3',
  TURNOVER: 'f5', // 成交额
  VOLUME: 'f6', // 成交量
  TURNOVER_RATE: 'f8',
  PE: 'f9',
  TOTAL_MV: 'f20',
  CIR_MV: 'f21',
  PB: 'f23',
  MAIN_INFLOW: 'f62', // 主力净额
  SUPER_INFLOW: 'f66', // 超大单净额
  SUPER_RATIO: 'f69', // 超大单占比
  MAIN_RATIO: 'f184', // 主力占比
} as const
