import { describe, expect, it, vi } from 'vitest'

import { OpeningRealtimeEventBridge } from '../OpeningRealtimeEventBridge'
import { DEFAULT_OPENING_WEAK_TO_STRONG_RULES } from '../openingWeakToStrongConfig'
import type { OpeningWeakToStrongQuote } from '../openingWeakToStrongTypes'

type QuotePatchInput = Omit<OpeningWeakToStrongQuote, 'at'> & {
  capturedAt?: string
  bridgeTs?: string
  sourceTs?: number
  lastPriceSource?: 'last'
}

const baseQuote = {
  code: '002552',
  name: '宝鼎科技',
  preClose: 10,
  limitUpPrice: 11,
  openingForcedSample: true,
  requestedCount: 132,
  receivedCount: 128,
  elapsedMs: 420,
  slowBatches: 1,
  truncatedBatches: 2,
  lastPriceSource: 'last',
} satisfies Partial<QuotePatchInput>

function checkpointQuotes(overrides: Partial<QuotePatchInput> = {}): QuotePatchInput[] {
  return [
    {
      ...baseQuote,
      ...overrides,
      capturedAt: '2026-06-03T09:20:00+08:00',
      bridgeTs: '2026-06-03T09:20:00+08:00',
      lastPrice: 9.8,
      amount: 1_000_000,
      volume: 100_000,
    },
    {
      ...baseQuote,
      ...overrides,
      capturedAt: '2026-06-03T09:25:00+08:00',
      bridgeTs: '2026-06-03T09:25:00+08:00',
      lastPrice: 9.95,
      amount: 2_000_000,
      volume: 180_000,
    },
    {
      ...baseQuote,
      ...overrides,
      capturedAt: '2026-06-03T09:30:00+08:00',
      bridgeTs: '2026-06-03T09:30:00+08:00',
      lastPrice: 10.35,
      open: 10.35,
      amount: 8_000_000,
      volume: 600_000,
    },
    {
      ...baseQuote,
      ...overrides,
      capturedAt: '2026-06-03T09:35:00+08:00',
      bridgeTs: '2026-06-03T09:35:00+08:00',
      lastPrice: 10.65,
      open: 10.35,
      amount: 16_000_000,
      volume: 1_200_000,
    },
    {
      ...baseQuote,
      ...overrides,
      capturedAt: '2026-06-03T10:00:00+08:00',
      bridgeTs: '2026-06-03T10:00:00+08:00',
      lastPrice: 10.7,
      open: 10.35,
      amount: 25_000_000,
      volume: 2_000_000,
    },
  ] as QuotePatchInput[]
}

describe('OpeningRealtimeEventBridge', () => {
  it('posts the four live checkpoint signals and injects stage events into monitor', async () => {
    const postSignal = vi.fn().mockResolvedValue({
      ok: true,
      accepted: true,
      voiceOwner: 'web',
    })
    const acceptDerivedEvents = vi.fn()
    const refresh = vi.fn().mockResolvedValue({ ok: true })
    const bridge = new OpeningRealtimeEventBridge({
      rules: DEFAULT_OPENING_WEAK_TO_STRONG_RULES,
      ruleVersion: 'opening-weak-to-strong.v1',
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents, refresh } as any,
    })

    bridge.acceptQuotes(checkpointQuotes())
    await vi.waitFor(() => expect(postSignal).toHaveBeenCalledTimes(4))

    const payloads = postSignal.mock.calls.map(([, signal]) => signal)
    expect(payloads.map(signal => signal.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(payloads.map(signal => signal.voiceEligible)).toEqual([false, true, true, false])
    expect(payloads.map(signal => Object.keys(signal).sort())).toEqual([
      ['amount', 'code', 'name', 'pct', 'price', 'reason', 'stage', 'status', 'time', 'voiceEligible'],
      ['amount', 'code', 'name', 'pct', 'price', 'reason', 'stage', 'status', 'time', 'voiceEligible'],
      ['amount', 'code', 'name', 'pct', 'price', 'reason', 'stage', 'status', 'time', 'voiceEligible'],
      ['amount', 'code', 'name', 'pct', 'price', 'reason', 'stage', 'status', 'time', 'voiceEligible'],
    ])

    expect(postSignal).toHaveBeenCalledWith('web', expect.objectContaining({
      code: '002552',
      stage: 'gapAlert',
      voiceEligible: true,
    }))

    await vi.waitFor(() => expect(acceptDerivedEvents).toHaveBeenCalledTimes(4))
    const shownEvents = acceptDerivedEvents.mock.calls.map(([events]) => events[0])
    expect(shownEvents.map(event => event.typeName)).toEqual([
      '竞价弱转强候选',
      '竞价跳空高开',
      '快速上板前兆',
      '竞价弱转强复盘',
    ])
    expect(shownEvents.map(event => event.raw.voiceOwner)).toEqual(['none', 'web', 'web', 'none'])
    expect(shownEvents.map(event => event.raw.signal.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(shownEvents[1].raw.debug.signal.stage).toBe('gapAlert')
    expect(shownEvents[1].raw.debug.signal.auctionCapturedAt).toBe('2026-06-03T09:25:00+08:00')
    expect(refresh).toHaveBeenCalledTimes(4)
  })

  it('falls back to local web voice only for 09:30 gap and 09:35 trend when proxy post fails', async () => {
    const postSignal = vi.fn().mockResolvedValue({
      ok: false,
      accepted: false,
      voiceOwner: 'none',
    })
    const acceptDerivedEvents = vi.fn()
    const refresh = vi.fn().mockResolvedValue({ ok: true })
    const bridge = new OpeningRealtimeEventBridge({
      rules: DEFAULT_OPENING_WEAK_TO_STRONG_RULES,
      ruleVersion: 'opening-weak-to-strong.v1',
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents, refresh } as any,
    })

    bridge.acceptQuotes(checkpointQuotes())
    await vi.waitFor(() => expect(acceptDerivedEvents).toHaveBeenCalledTimes(4))

    const shownEvents = acceptDerivedEvents.mock.calls.map(([events]) => events[0])
    expect(shownEvents.map(event => event.raw.signal.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(shownEvents.map(event => event.raw.voiceOwner)).toEqual(['none', 'web', 'web', 'none'])
    expect(shownEvents.every(event => event.raw.openingSignalPost.ok === false)).toBe(true)
  })

  it('keeps sourceTs UTC instants in local opening checkpoints', async () => {
    const postSignal = vi.fn().mockResolvedValue({
      ok: true,
      accepted: true,
      voiceOwner: 'web',
    })
    const bridge = new OpeningRealtimeEventBridge({
      rules: DEFAULT_OPENING_WEAK_TO_STRONG_RULES,
      ruleVersion: 'opening-weak-to-strong.v1',
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents: vi.fn(), refresh: vi.fn().mockResolvedValue({ ok: true }) } as any,
    })

    bridge.acceptQuotes(checkpointQuotes().map(quote => {
      const { capturedAt, bridgeTs, ...rest } = quote
      const sourceTs = Date.parse(capturedAt || bridgeTs || '')
      return { ...rest, sourceTs }
    }))
    await vi.waitFor(() => expect(postSignal).toHaveBeenCalledTimes(4))

    const payloads = postSignal.mock.calls.map(([, signal]) => signal)
    expect(payloads.map(signal => signal.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(payloads.every(signal => signal.time.startsWith('2026-06-03T'))).toBe(true)
  })
})
