/**
 * 资金数据源标识常量（统一入口，2026-08-12：消除各处硬编码字符串）。
 * 所有资金行 source / moneyFlowSource 的值一律引用本模块常量。
 * 后端对应常量见 quant-board/backend/core/fund_sources.py。
 */

export const FUND_SOURCE = {
  /** 同花顺 mainMonitorDetail L2 主源（权威口径） */
  THS_MAIN_MONITOR: 'ths_main_monitor',
  /** akshare 同花顺网页个股资金流（估算口径） */
  AKSHARE_THS_INDIVIDUAL: 'akshare_ths_individual',
  /** 同花顺 L2 主力监控（历史/兼容） */
  THS_L2: 'ths_l2',
  /** QMT L2 实时资金流（历史/兼容） */
  QMT_L2: 'qmt_l2',
  /** 东方财富资金流（历史/兼容） */
  EASTMONEY: 'eastmoney',
  /** 前端 TDX 分笔估算兜底 */
  TDX_ESTIMATE: 'tdx_estimate',
} as const

export type FundSource = (typeof FUND_SOURCE)[keyof typeof FUND_SOURCE]

/** 资金列（theme-fund 缓存）当前接受的数据源 */
export const SUPPORTED_FUND_SOURCES: ReadonlySet<string> = new Set([
  FUND_SOURCE.THS_MAIN_MONITOR,
  FUND_SOURCE.AKSHARE_THS_INDIVIDUAL,
])
