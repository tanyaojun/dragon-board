import { describe, expect, it } from 'vitest'

import { resolveLiveLimitState } from '../liveLimitState'

describe('resolveLiveLimitState', () => {
  it('uses real limitUpPrice before board fallback', () => {
    const state = resolveLiveLimitState({
      code: '000970',
      price: 14.52,
      change: 10,
      limitUpPrice: 14.52,
    })

    expect(state.atLimitUp).toBe(true)
    expect(state.source).toBe('quote_limit_price')
  })

  it('falls back to main-board threshold for normal 000 stock when quote limit price is missing', () => {
    const state = resolveLiveLimitState({ code: '000970', change: 9.81 })

    expect(state.atLimitUp).toBe(true)
    expect(state.limitPct).toBe(9.8)
    expect(state.source).toBe('board_fallback')
  })

  it('falls back to north exchange threshold for 8/4/9 prefixes', () => {
    expect(resolveLiveLimitState({ code: '830000', change: 29.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '430000', change: 29.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '920000', change: 29.9 }).atLimitUp).toBe(true)
  })

  it('falls back to 20 percent threshold for GEM and STAR prefixes', () => {
    expect(resolveLiveLimitState({ code: '300001', change: 19.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '301001', change: 19.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '688001', change: 19.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '689001', change: 19.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '300001', change: 9.9 }).atLimitUp).toBe(false)
  })

  it('normalizes market-prefixed codes before board fallback', () => {
    expect(resolveLiveLimitState({ code: 'SZ300001', change: 9.9 }).atLimitUp).toBe(false)
    expect(resolveLiveLimitState({ code: 'SH688001', change: 9.9 }).atLimitUp).toBe(false)
    expect(resolveLiveLimitState({ code: 'BJ830000', change: 10.1 }).atLimitUp).toBe(false)
  })

  it('does not treat 6 percent move as limit up', () => {
    const state = resolveLiveLimitState({ code: '000970', change: 6.1 })

    expect(state.atLimitUp).toBe(false)
    expect(state.source).toBe('board_fallback')
  })
})
