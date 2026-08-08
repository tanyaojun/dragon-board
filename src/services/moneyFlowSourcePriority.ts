export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

// 资金列来源优先级（rank 高者权威，低者不覆盖高者）：
// - ths_main_monitor：mainMonitorDetail L2 主源（权威）
// - eastmoney_seed：东财排行接口全市场种子（估算），与 L2 口径近似，盘中由 L2 校准覆盖
// - ths_web_seed：存量同花顺网页口径种子（估算，接口已切换为东财，仅兼容旧缓存）
// tdx_transaction（bridge L1 分笔自算，非全日完整分笔、累计不可靠）不作为
// 资金列来源，仅 bridge /health 诊断；eastmoney / ths_l2 / qmt_l2 亦保持 rank 0。
const DASHBOARD_FUND_SOURCE_RANK: Record<string, number> = {
  ths_web_seed: 1,
  eastmoney_seed: 1,
  ths_main_monitor: 5,
}

export function getMoneyFlowSourceRank(value: MoneyFlowSourceLike | null | undefined): number {
  if (!value || typeof value.moneyFlowSource !== 'string') return 0
  return DASHBOARD_FUND_SOURCE_RANK[value.moneyFlowSource] ?? 0
}

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
