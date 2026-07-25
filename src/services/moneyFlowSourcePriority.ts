export type MoneyFlowSourceLike = {
  moneyFlowSource?: unknown
  capitalFlowSource?: unknown
  moneyFlowEstimated?: unknown
}

export function getMoneyFlowSourceRank(value: MoneyFlowSourceLike | null | undefined): number {
  if (!value) return 0

  // tdx_transaction: 主力数据源，基于 tdxpy 逐笔成交实时计算
  if (
    value.moneyFlowEstimated === false &&
    value.moneyFlowSource === 'tdx_transaction' &&
    value.capitalFlowSource === 'tdx_tick'
  ) {
    return 5
  }

  // ths_l2: 同花顺 L2 替代数据源
  if (value.moneyFlowEstimated === false && value.moneyFlowSource === 'ths_l2') {
    return 4
  }

  if (
    value.moneyFlowEstimated === false &&
    value.moneyFlowSource === 'qmt_l2' &&
    (value.capitalFlowSource === 'broker_l2' || value.capitalFlowSource === 'official_l2')
  ) {
    return 3
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
