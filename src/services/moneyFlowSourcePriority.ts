import { FUND_SOURCE } from '@/config/fundSources'

export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

// 资金列来源优先级（rank 高者权威，低者不覆盖高者）：
// - ths_main_monitor：mainMonitorDetail L2 主源（权威）
// - akshare_ths_individual：akshare 同花顺网页个股资金流（估算）
// - eastmoney_seed / ths_web_seed：存量种子（估算，仅兼容旧缓存）
// tdx_transaction（bridge L1 分笔自算，非全日完整分笔、累计不可靠）不作为
// 资金列来源，仅 bridge /health 诊断；eastmoney / ths_l2 / qmt_l2 亦保持 rank 0。
const DASHBOARD_FUND_SOURCE_RANK: Record<string, number> = {
  [FUND_SOURCE.THS_MAIN_MONITOR]: 5,
  [FUND_SOURCE.AKSHARE_THS_INDIVIDUAL]: 1,
  [FUND_SOURCE.THS_WEB_SEED]: 1,
  [FUND_SOURCE.EASTMONEY_SEED]: 1,
}

export function getMoneyFlowSourceRank(value: MoneyFlowSourceLike | null | undefined): number {
  if (!value || typeof value.moneyFlowSource !== 'string') return 0
  return DASHBOARD_FUND_SOURCE_RANK[value.moneyFlowSource] ?? 0
}

/** 是否可作为资金列来源（rank > 0）。统一白名单入口，禁止在业务代码硬编码源字符串。 */
export function isDashboardFundSource(value: MoneyFlowSourceLike | null | undefined): boolean {
  return getMoneyFlowSourceRank(value) > 0
}

export function shouldApplyMoneyFlowUpdate(
  current: MoneyFlowSourceLike | null | undefined,
  next: MoneyFlowSourceLike | null | undefined,
): boolean {
  const nextRank = getMoneyFlowSourceRank(next)
  if (nextRank <= 0) return false

  return nextRank >= getMoneyFlowSourceRank(current)
}

export function pickHigherPriorityMoneyFlow<T extends MoneyFlowSourceLike, U extends MoneyFlowSourceLike>(
  first: T | null | undefined,
  second: U | null | undefined,
): T | U | null | undefined {
  return getMoneyFlowSourceRank(second) > getMoneyFlowSourceRank(first) ? second : first
}
