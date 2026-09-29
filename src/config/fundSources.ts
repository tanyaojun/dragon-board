/**
 * 资金数据源标识常量（统一入口）。
 * 所有资金行 source / moneyFlowSource 的值一律引用本模块常量。
 * 后端对应常量见 quant-board/backend/core/fund_sources.py。
 *
 * 数据源口径（两条线）：
 * - THS_MAIN_MONITOR：同花顺 mainMonitorDetail L2 主源（权威），专供行情主页
 *   八平台热榜股票列表（约 200-230 只）资金列；
 * - EASTMONEY_MAIN：东财 push2 主力资金（ulist.np 批量，后端 httpx 独立 URL
 *   直连、不走 akshare，估算口径），专供 theme_fund 题材股票列表（约 4000 只）
 *   资金聚合（默认源；akshare 同花顺网页口径数据不准，2026-09-29 用户确认切换）；
 * - AKSHARE_THS_INDIVIDUAL：akshare 同花顺网页个股资金流（估算），题材资金
 *   回退源（后端 QUANT_BOARD_THEME_FUND_SOURCE=akshare 时启用）。
 *
 * 已废弃且实测不可用的历史源一律删除、禁止恢复：ths_web_seed / eastmoney_seed
 * （种子方案从未启动）、tdx_transaction（bridge L1 分笔自算不可靠）、
 * tdx_estimate（TDX 分笔估算兜底）、ths_l2 / qmt_l2（历史兼容）。
 */

export const FUND_SOURCE = {
  /** 同花顺 mainMonitorDetail L2 主源（权威口径，行情主页热榜资金列） */
  THS_MAIN_MONITOR: 'ths_main_monitor',
  /** 东财 push2 主力资金（估算口径，theme_fund 题材资金聚合，默认源） */
  EASTMONEY_MAIN: 'eastmoney_main',
  /** akshare 同花顺网页个股资金流（估算口径，theme_fund 题材资金回退源） */
  AKSHARE_THS_INDIVIDUAL: 'akshare_ths_individual',
} as const

export type FundSource = (typeof FUND_SOURCE)[keyof typeof FUND_SOURCE]
