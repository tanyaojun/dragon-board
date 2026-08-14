/**
 * 资金数据源标识常量（统一入口，2026-08-14：废弃种子与不可用源，只保留 L2 + akshare）。
 * 所有资金行 source / moneyFlowSource 的值一律引用本模块常量。
 * 后端对应常量见 quant-board/backend/core/fund_sources.py。
 *
 * 数据源口径（2026-08-14 用户确认，两条线）：
 * - THS_MAIN_MONITOR：同花顺 mainMonitorDetail L2 主源（权威），专供行情主页
 *   八平台热榜股票列表（约 200-230 只）资金列；
 * - AKSHARE_THS_INDIVIDUAL：akshare 同花顺网页个股资金流（估算），专供
 *   theme_fund 题材股票列表（约 4000 只）资金聚合。
 *
 * 已废弃且实测不可用的历史源一律删除、禁止恢复：ths_web_seed / eastmoney_seed
 * （种子方案从未启动）、eastmoney（东财限流）、tdx_transaction（bridge L1 分笔
 * 自算不可靠）、tdx_estimate（TDX 分笔估算兜底）、ths_l2 / qmt_l2（历史兼容）。
 */

export const FUND_SOURCE = {
  /** 同花顺 mainMonitorDetail L2 主源（权威口径，行情主页热榜资金列） */
  THS_MAIN_MONITOR: 'ths_main_monitor',
  /** akshare 同花顺网页个股资金流（估算口径，theme_fund 题材资金聚合） */
  AKSHARE_THS_INDIVIDUAL: 'akshare_ths_individual',
} as const

export type FundSource = (typeof FUND_SOURCE)[keyof typeof FUND_SOURCE]
