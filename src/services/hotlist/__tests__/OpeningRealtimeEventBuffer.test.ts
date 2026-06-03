import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { OpeningRealtimeEventBuffer } from '../OpeningRealtimeEventBuffer'
import type { OpeningWeakToStrongFixture } from '../openingWeakToStrongTypes'

function loadFixture(): OpeningWeakToStrongFixture {
  return JSON.parse(
    readFileSync(
      join(process.cwd(), 'docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json'),
      'utf8',
    ),
  ) as OpeningWeakToStrongFixture
}

describe('OpeningRealtimeEventBuffer', () => {
  it('converts realtime quote samples into an opening weak-to-strong hot stock event', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })

    const events = sample!.quotes.flatMap(quote => buffer.acceptQuote(quote))

    expect(events).toHaveLength(2)
    expect(events[0]).toMatchObject({
      category: 'stock',
      code: '002552',
      name: '宝鼎科技',
      type: 12001,
      typeName: '竞价弱转强候选',
      direction: 'up',
      severity: 'important',
      matchedHotStock: false,
    })
    expect(events[0].raw).toMatchObject({
      source: 'opening_weak_to_strong_v3',
      signal: {
        signalType: 'opening_weak_to_strong',
        variant: 'auction_late_lift',
        intradayStatus: 'preopen_candidate',
      },
    })
    expect(events[1].id).toBe('opening_weak_to_strong:2026-05-22:002552:pending')
  })

  it('allows same stock to emit again on the next trading day', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })

    const firstDay = sample!.quotes.flatMap(quote => buffer.acceptQuote(quote))
    const secondDay = sample!.quotes.flatMap(quote => buffer.acceptQuote({
      ...quote,
      at: quote.at.replace('2026-05-22', '2026-05-23'),
      capturedAt: quote.capturedAt?.replace('2026-05-22', '2026-05-23'),
      bridgeTs: quote.bridgeTs?.replace('2026-05-22', '2026-05-23'),
    }))

    expect(firstDay).toHaveLength(2)
    expect(secondDay).toHaveLength(2)
    expect(secondDay[0].id).toBe('opening_weak_to_strong:2026-05-23:002552:preopen_candidate')
    expect(secondDay[1].id).toBe('opening_weak_to_strong:2026-05-23:002552:pending')
  })

  it('emits separate action events for preopen candidate and opening upgrade', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const quotes = sample!.quotes
    const finalQuote = quotes[quotes.length - 2]
    const openQuote = quotes[quotes.length - 1]

    const events = [
      ...quotes.slice(0, -1),
      {
        ...finalQuote,
        at: '2026-05-22T09:25:12+08:00',
        capturedAt: '2026-05-22T09:25:12+08:00',
        bridgeTs: '2026-05-22T09:25:12+08:00',
      },
      openQuote,
    ].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events).toHaveLength(2)
    expect(events.map(item => item.signal.intradayStatus)).toEqual(['preopen_candidate', 'pending'])
    expect(events.map(item => item.event.id)).toEqual([
      'opening_weak_to_strong:2026-05-22:002552:preopen_candidate',
      'opening_weak_to_strong:2026-05-22:002552:pending',
    ])
    expect(events.map(item => item.event.typeName)).toEqual(['竞价弱转强候选', '竞价弱转强'])
  })

  it('upgrades watch signal to stronger signal inside the same trading day', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const baselineQuotes = sample!.quotes.slice(0, -1)
    const auction = {
      ...baselineQuotes[baselineQuotes.length - 1],
      amount: 25_000_000,
      capturedAt: undefined,
      bridgeTs: undefined,
    }
    const watch = {
      ...sample!.quotes[sample!.quotes.length - 1],
      lastPrice: 37.5,
      amount: 4_000_000,
      at: '2026-05-22T09:30:10+08:00',
      capturedAt: '2026-05-22T09:29:40+08:00',
      bridgeTs: '2026-05-22T09:29:40+08:00',
    }
    const strong = {
      ...sample!.quotes[sample!.quotes.length - 1],
      lastPrice: 38.6,
      amount: 120_000_000,
      at: '2026-05-22T09:31:00+08:00',
      capturedAt: '2026-05-22T09:31:00+08:00',
      bridgeTs: '2026-05-22T09:31:00+08:00',
    }

    const events = [
      ...baselineQuotes.slice(0, -1),
      auction,
      watch,
      strong,
    ].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events).toHaveLength(3)
    expect(events[0].signal.intradayStatus).toBe('preopen_candidate')
    expect(events[1].signal.confidence).toBe('watch')
    expect(events[1].event.severity).toBe('important')
    expect(events[2].signal.confidence).toBe('critical')
  })

  it('emits a 09:25 preopen candidate for deep-water price-volume lift', () => {
    const fixture = loadFixture()
    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const base = {
      code: '002579',
      name: '中京电子',
      preClose: 17.15,
      open: 0,
      volume: 1_000_000,
    }

    const events = [
      {
        ...base,
        at: '2026-06-01T09:20:05+08:00',
        lastPrice: 14.6,
        amount: 2_000_000,
        capturedAt: '2026-06-01T09:20:05+08:00',
        bridgeTs: '2026-06-01T09:20:05+08:00',
      },
      {
        ...base,
        at: '2026-06-01T09:24:05+08:00',
        lastPrice: 15,
        amount: 12_000_000,
        capturedAt: '2026-06-01T09:24:05+08:00',
        bridgeTs: '2026-06-01T09:24:05+08:00',
      },
      {
        ...base,
        at: '2026-06-01T09:25:00+08:00',
        lastPrice: 15.46,
        amount: 20_650_000,
        capturedAt: '2026-06-01T09:25:00+08:00',
        bridgeTs: '2026-06-01T09:25:00+08:00',
      },
    ].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events).toHaveLength(1)
    expect(events[0].event.id).toBe('opening_weak_to_strong:2026-06-01:002579:preopen_candidate')
    expect(events[0].event.severity).toBe('important')
    expect(events[0].signal.priceVolumeConfirmed).toBe(true)
    expect(events[0].signal.auctionPct).toBeCloseTo(-9.85)
  })

  it('emits intraday confirmation and failure updates after the opening trigger', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const confirm = {
      ...sample!.quotes[sample!.quotes.length - 1],
      at: '2026-05-22T09:36:00+08:00',
      lastPrice: 38.6,
      amount: 88_000_000,
      capturedAt: '2026-05-22T09:36:00+08:00',
      bridgeTs: '2026-05-22T09:36:00+08:00',
    }
    const failed = {
      ...confirm,
      at: '2026-05-22T09:42:00+08:00',
      lastPrice: 36.7,
      amount: 98_000_000,
      capturedAt: '2026-05-22T09:42:00+08:00',
      bridgeTs: '2026-05-22T09:42:00+08:00',
    }

    const events = [
      ...sample!.quotes,
      confirm,
      failed,
    ].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events.map(item => item.signal.intradayStatus)).toEqual([
      'preopen_candidate',
      'pending',
      'confirmed',
      'failed',
    ])
    expect(events[2].signal.intradayOutcome).toBe('confirmed_strong')
    expect(events[3].signal.intradayOutcome).toBe('failed_open_dump')
    expect(events[3].signal.riskFlags.map(item => item.key)).toContain('intraday_open_dump')
  })

  it('lets a fresh realtime opening signal replace a dry-run pending signal', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === 'strong-open-board-attempt-with-precondition')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const quotes = sample!.quotes
    const open = quotes[quotes.length - 1]

    for (const quote of quotes.slice(0, -1)) buffer.acceptQuoteWithSignals(quote)
    const stale = buffer.acceptQuoteWithSignals({
      ...open,
      capturedAt: '2026-05-22T09:29:40+08:00',
      bridgeTs: '2026-05-22T09:29:40+08:00',
    })
    const fresh = buffer.acceptQuoteWithSignals({
      ...open,
      capturedAt: open.at,
      bridgeTs: open.at,
    })

    expect(stale).toHaveLength(1)
    expect(stale[0].signal.dryRun).toBe(true)
    expect(fresh).toHaveLength(1)
    expect(fresh[0].signal.dryRun).toBe(false)
    expect(fresh[0].signal.intradayStatus).toBe('pending')
  })

  it('lets a lower-scored fresh pending signal replace a stale dry-run pending signal', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const quotes = sample!.quotes
    const open = quotes[quotes.length - 1]

    for (const quote of quotes.slice(0, -1)) buffer.acceptQuoteWithSignals(quote)
    const stale = buffer.acceptQuoteWithSignals({
      ...open,
      lastPrice: 38.6,
      amount: 120_000_000,
      capturedAt: '2026-05-22T09:29:20+08:00',
      bridgeTs: '2026-05-22T09:29:20+08:00',
    })
    const fresh = buffer.acceptQuoteWithSignals({
      ...open,
      lastPrice: 37.5,
      amount: 4_000_000,
      capturedAt: '2026-05-22T09:31:00+08:00',
      bridgeTs: '2026-05-22T09:31:00+08:00',
    })

    expect(stale).toHaveLength(1)
    expect(stale[0].signal.dryRun).toBe(true)
    expect(fresh).toHaveLength(1)
    expect(fresh[0].signal.dryRun).toBe(false)
    expect(fresh[0].signal.intradayStatus).toBe('pending')
    expect(fresh[0].signal.score).toBeLessThan(stale[0].signal.score)
  })

  it('confirms a near-limit opening signal without requiring an impossible extra advance', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === 'strong-open-board-attempt-with-precondition')
    expect(sample).toBeTruthy()

    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const open = sample!.quotes[sample!.quotes.length - 1]
    const confirm = {
      ...open,
      at: '2026-05-22T09:36:00+08:00',
      capturedAt: '2026-05-22T09:36:00+08:00',
      bridgeTs: '2026-05-22T09:36:00+08:00',
      amount: 120_000_000,
    }

    const events = [...sample!.quotes, confirm].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events.map(item => item.signal.intradayStatus)).toEqual([
      'preopen_candidate',
      'pending',
      'confirmed',
    ])
    expect(events[2].signal.intradayOutcome).toBe('confirmed_strong')
  })

  it('emits watch and delayed confirmation events for auction gap repair boards', () => {
    const fixture = loadFixture()
    const buffer = new OpeningRealtimeEventBuffer({
      rules: fixture.rules,
      ruleVersion: fixture.ruleVersion,
    })
    const base = {
      code: '002806',
      name: '华锋股份',
      preClose: 18.48,
      open: 0,
      volume: 1_200_000,
      limitUpPrice: 20.33,
      previousWeakScore: 35,
      previousWeakSignals: ['yesterday_open_board'],
      previousWeakSource: 'manual_previous_weak',
    }
    const events = [
      {
        ...base,
        at: '2026-06-02T09:20:05+08:00',
        lastPrice: 16.3,
        amount: 2_000_000,
        capturedAt: '2026-06-02T09:20:05+08:00',
        bridgeTs: '2026-06-02T09:20:05+08:00',
      },
      {
        ...base,
        at: '2026-06-02T09:24:05+08:00',
        lastPrice: 16.7,
        amount: 8_000_000,
        capturedAt: '2026-06-02T09:24:05+08:00',
        bridgeTs: '2026-06-02T09:24:05+08:00',
      },
      {
        ...base,
        at: '2026-06-02T09:25:00+08:00',
        lastPrice: 16.95,
        amount: 13_530_000,
        capturedAt: '2026-06-02T09:25:00+08:00',
        bridgeTs: '2026-06-02T09:25:00+08:00',
      },
      {
        ...base,
        at: '2026-06-02T09:30:08+08:00',
        lastPrice: 17.72,
        open: 17.68,
        amount: 22_000_000,
        capturedAt: '2026-06-02T09:30:08+08:00',
        bridgeTs: '2026-06-02T09:30:08+08:00',
      },
      {
        ...base,
        at: '2026-06-02T09:36:00+08:00',
        lastPrice: 18.15,
        open: 17.68,
        amount: 56_000_000,
        capturedAt: '2026-06-02T09:36:00+08:00',
        bridgeTs: '2026-06-02T09:36:00+08:00',
      },
      {
        ...base,
        at: '2026-06-02T14:56:00+08:00',
        lastPrice: 20.33,
        open: 17.68,
        amount: 397_900_000,
        capturedAt: '2026-06-02T14:56:00+08:00',
        bridgeTs: '2026-06-02T14:56:00+08:00',
      },
    ].flatMap(quote => buffer.acceptQuoteWithSignals(quote))

    expect(events.map(item => item.signal.intradayStatus)).toEqual([
      'preopen_candidate',
      'pending',
      'watch',
      'confirmed',
    ])
    expect(events[1].signal.variant).toBe('auction_gap_delayed_board')
    expect(events.map(item => item.event.id)).toEqual([
      'opening_weak_to_strong:2026-06-02:002806:preopen_candidate',
      'opening_weak_to_strong:2026-06-02:002806:pending',
      'opening_weak_to_strong:2026-06-02:002806:watch',
      'opening_weak_to_strong:2026-06-02:002806:confirmed',
    ])
    expect(events[3].signal.intradayOutcome).toBe('confirmed_strong')
  })
})
