import { FUND_SOURCE } from '@/config/fundSources'

export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

export function getMoneyFlowSourceRank(value: MoneyFlowSourceLike | null | undefined): number {
  if (!value) return 0

  if (value.moneyFlowSource === FUND_SOURCE.THS_MAIN_MONITOR) {
    return 5
  }

  // akshare 同花顺网页个股资金流（估算口径，非 L2）——rank 1，低于 L2 主源
  if (value.moneyFlowSource === FUND_SOURCE.AKSHARE_THS_INDIVIDUAL) {
    return 1
  }

  return 0
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
