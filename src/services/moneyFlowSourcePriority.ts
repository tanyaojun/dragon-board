export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

export function getMoneyFlowSourceRank(value: MoneyFlowSourceLike | null | undefined): number {
  if (!value) return 0

  if (
    value.moneyFlowEstimated === false &&
    value.moneyFlowSource === 'qmt_l2' &&
    (value.capitalFlowSource === 'broker_l2' || value.capitalFlowSource === 'official_l2')
  ) {
    return 3
  }

  if (value.moneyFlowEstimated === false && value.moneyFlowSource === 'eastmoney') {
    return 2
  }

  if (value.moneyFlowEstimated === true || value.capitalFlowSource === 'estimated_l1') {
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
