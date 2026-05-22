import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { OpeningRealtimeEventBridge } from '../OpeningRealtimeEventBridge'
import type { OpeningWeakToStrongFixture } from '../openingWeakToStrongTypes'

function loadFixture(): OpeningWeakToStrongFixture {
  return JSON.parse(
    readFileSync(
      join(process.cwd(), 'docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json'),
      'utf8',
    ),
  ) as OpeningWeakToStrongFixture
}

describe('OpeningRealtimeEventBridge', () => {
  it('posts realtime opening signal and injects voice-arbitrated event into monitor', async () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const postSignal = vi.fn().mockResolvedValue({
      ok: true,
      accepted: true,
      voiceOwner: 'web',
    })
    const acceptDerivedEvents = vi.fn()
    const refresh = vi.fn().mockResolvedValue({ ok: true })
    const bridge = new OpeningRealtimeEventBridge({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents, refresh } as any,
    })

    bridge.acceptQuotes(sample!.quotes.map(quote => ({
      code: quote.code,
      name: quote.name,
      lastPrice: quote.lastPrice,
      changePct: 0,
      volume: quote.volume || 0,
      amount: quote.amount || 0,
      open: quote.open,
      preClose: quote.preClose,
      capturedAt: quote.capturedAt,
      bridgeTs: quote.bridgeTs,
      lastPriceSource: 'last',
    })))
    await vi.waitFor(() => expect(postSignal).toHaveBeenCalledTimes(1))

    expect(postSignal).toHaveBeenCalledWith('web', expect.objectContaining({
      code: '002552',
      signalType: 'opening_weak_to_strong',
      tradingDate: '2026-05-22',
      variant: 'auction_gap_reversal',
    }))
    expect(acceptDerivedEvents).toHaveBeenCalledWith([
      expect.objectContaining({
        code: '002552',
        typeName: '竞价弱转强',
        raw: expect.objectContaining({
          voiceOwner: 'web',
        }),
      }),
    ])
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('keeps local monitor event when proxy post fails', async () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const postSignal = vi.fn().mockResolvedValue({
      ok: false,
      accepted: false,
      voiceOwner: 'none',
    })
    const acceptDerivedEvents = vi.fn()
    const refresh = vi.fn().mockResolvedValue({ ok: true })
    const bridge = new OpeningRealtimeEventBridge({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents, refresh } as any,
    })

    bridge.acceptQuotes(sample!.quotes.map(quote => ({
      code: quote.code,
      name: quote.name,
      lastPrice: quote.lastPrice,
      changePct: 0,
      volume: quote.volume || 0,
      amount: quote.amount || 0,
      open: quote.open,
      preClose: quote.preClose,
      capturedAt: quote.capturedAt,
      bridgeTs: quote.bridgeTs,
      lastPriceSource: 'last',
    })))
    await vi.waitFor(() => expect(postSignal).toHaveBeenCalledTimes(1))

    expect(acceptDerivedEvents).toHaveBeenCalledTimes(1)
    const [[events]] = acceptDerivedEvents.mock.calls
    expect(events[0]).toMatchObject({
      code: '002552',
      typeName: '竞价弱转强',
      raw: {
        voiceOwner: 'web',
        openingSignalPost: { ok: false },
      },
    })
    expect(refresh).toHaveBeenCalledTimes(1)
  })

  it('computes limit-up price from quote fields for strong open board attempt', async () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === 'strong-open-board-attempt-with-precondition')
    expect(sample).toBeTruthy()
    const postSignal = vi.fn().mockResolvedValue({
      ok: true,
      accepted: true,
      voiceOwner: 'web',
    })
    const bridge = new OpeningRealtimeEventBridge({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
      signalClient: { postSignal } as any,
      monitorService: { acceptDerivedEvents: vi.fn(), refresh: vi.fn().mockResolvedValue({ ok: true }) } as any,
    })

    bridge.acceptQuotes(sample!.quotes.map(quote => ({
      code: quote.code,
      name: quote.name,
      lastPrice: quote.lastPrice,
      changePct: 0,
      volume: quote.volume || 0,
      amount: quote.amount || 0,
      open: quote.open,
      preClose: quote.preClose,
      capturedAt: quote.capturedAt,
      bridgeTs: quote.bridgeTs,
      lastPriceSource: 'last',
    })))
    await vi.waitFor(() => expect(postSignal).toHaveBeenCalledTimes(1))

    expect(postSignal).toHaveBeenCalledWith('web', expect.objectContaining({
      code: '600001',
      variant: 'strong_open_board_attempt',
    }))
  })
})
