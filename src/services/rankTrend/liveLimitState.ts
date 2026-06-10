function asNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const num = asNumber(value)
    if (num !== null && num > 0) return num
  }
  return null
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function fallbackLimitPct(code: unknown): number {
  const value = normalizeCode(code)
  if (
    value.startsWith('300') ||
    value.startsWith('301') ||
    value.startsWith('688') ||
    value.startsWith('689')
  ) {
    return 19.8
  }
  if (value.startsWith('8') || value.startsWith('4') || value.startsWith('9')) {
    return 29.8
  }
  return 9.8
}

export interface LiveLimitState {
  atLimitUp: boolean
  atLimitDown: boolean
  source: 'quote_limit_price' | 'board_fallback' | 'missing_quote'
  limitPct: number | null
  limitUpPrice: number | null
  limitDownPrice: number | null
}

export function resolveLiveLimitState(
  stock: Record<string, unknown> | null | undefined,
): LiveLimitState {
  const lastPrice = firstNumber(stock?.price, stock?.latestPrice, stock?.lastPrice, stock?.lastTradePrice)
  const limitUpPrice = firstNumber(
    stock?.limitUpPrice,
    stock?.ztPrice,
    stock?.upLimitPrice,
    stock?.['涨停价'],
  )
  const limitDownPrice = firstNumber(
    stock?.limitDownPrice,
    stock?.dtPrice,
    stock?.downLimitPrice,
    stock?.['跌停价'],
  )

  if (lastPrice && limitUpPrice) {
    return {
      atLimitUp: lastPrice >= limitUpPrice * 0.999,
      atLimitDown: !!limitDownPrice && lastPrice <= limitDownPrice * 1.001,
      source: 'quote_limit_price',
      limitPct: null,
      limitUpPrice,
      limitDownPrice,
    }
  }

  const change = asNumber(stock?.change ?? stock?.pctChange ?? stock?.changePct)
  if (change === null) {
    return {
      atLimitUp: false,
      atLimitDown: false,
      source: 'missing_quote',
      limitPct: null,
      limitUpPrice,
      limitDownPrice,
    }
  }

  const limitPct = fallbackLimitPct(stock?.code)
  return {
    atLimitUp: change >= limitPct,
    atLimitDown: change <= -limitPct,
    source: 'board_fallback',
    limitPct,
    limitUpPrice,
    limitDownPrice,
  }
}
