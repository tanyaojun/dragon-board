import { FUND_SOURCE } from '@/config/fundSources'

export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

// 行情主页资金列来源优先级（rank 高者权威，低者不覆盖高者）。
// 2026-08-14 用户确认：行情主页热榜资金列只用 L2 主源（ths_main_monitor），
// 缺口诚实显示 --；akshare 同花顺网页估算源（akshare_ths_individual）只供
// theme_fund 题材资金聚合（走后端 /api/themes/fund-rows，不进入本资金列白名单）。
// 已废弃/不可用源（ths_web_seed / eastmoney_seed / eastmoney / tdx_transaction /
// tdx_estimate / ths_l2 / qmt_l2）一律移除，禁止恢复。
const DASHBOARD_FUND_SOURCE_RANK: Record<string, number> = {
  [FUND_SOURCE.THS_MAIN_MONITOR]: 5,
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
