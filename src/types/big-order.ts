// src/types/big-order.ts
import type { Stock } from './core'

// ========== 核心大单类型 ==========
export interface BigOrderItem {
  // 原始数据
  id?: string
  type: 1 | 2 | 3 | 4
  volume: number // 手数
  amount: number // 金额（元）
  price: number // 均价
  time: string | Date // 时间

  // 标记数据（算法计算后填充）
  fundMarker: string // 点火/砸盘
  buyMarker: string // 买活跃/承接好

  // 计算属性（服务层填充）
  typeName?: string
  amountStr?: string
  timeStr?: string
  isBuy?: boolean
  isSell?: boolean
}

// ========== 统计数据 ==========
export interface BigOrderStatistics {
  // 买卖统计
  buyAmount: number // 买入总额（元）
  sellAmount: number // 卖出总额（元）
  netBuy: number // 净买入（元）

  // 主动买卖
  mainBuyAmount: number // 主动买入（元）
  mainSellAmount: number // 主动卖出（元）

  // 标记统计
  igniteCount: number // 点火次数
  smashCount: number // 砸盘次数
  buyActiveCount: number // 买活跃次数
  sellActiveCount: number // 承接好次数

  // 其他统计
  totalCount: number // 总笔数
  avgAmount: number // 平均金额
  maxAmount: number // 最大金额
}

// ========== 时段统计 ==========
export interface PeriodStatistics {
  name: string // 时段名称
  start: string // 开始时间
  end: string // 结束时间
  count: number // 笔数
  buyAmount: number // 买入金额
  sellAmount: number // 卖出金额
  netBuy: number // 净买入
  igniteCount: number // 点火次数
  smashCount: number // 砸盘次数
  buyActiveCount: number // 买活跃次数
  sellActiveCount: number // 承接好次数
}

// ========== 筛选条件 ==========
export interface BigOrderFilter {
  minAmount?: number // 最小金额（万元）
  fundMarker?: string // 资金标记筛选
  buyMarker?: string // 买盘标记筛选
  stockCode?: string // 股票代码
}

// ========== 密集大单检测 ==========
export interface DenseOrderAlert {
  stockCode: string
  stockName: string
  count: number // 笔数
  windowMs: number // 时间窗口（毫秒）
  totalAmount: number // 总金额
  avgAmount: number // 平均金额
  timestamp: number
}

// ========== DataLayer 存储结构 ==========
export interface BigOrderStore {
  // 按股票存储的大单数据
  byStock: Map<
    string,
    {
      orders: BigOrderItem[]
      statistics: BigOrderStatistics
      periods: PeriodStatistics[]
      lastUpdate: number
    }
  >

  // 密集大单检测
  denseAlerts: DenseOrderAlert[]

  // 最后更新时间
  lastUpdate: number | null
}

// ========== 颜色规则 ==========
export interface BigOrderColorRule {
  name: string
  priority: number
  condition: (order: BigOrderItem) => boolean
  color: string
  isBold?: boolean
}

export const BIG_ORDER_COLORS = {
  buy: '#FF5050', // 红色 - 主动买
  sell: '#50C850', // 绿色 - 主动卖
  ignite: '#FFD700', // 金色 - 点火
  smash: '#9370DB', // 紫色 - 砸盘
  superBig: '#FFFF00', // 黄色 - 超大单
  default: '#FFFFFF', // 白色 - 默认
  buyActive: '#FF4500', // 橙红 - 买活跃
  sellActive: '#00BFFF', // 深蓝 - 承接好
} as const
