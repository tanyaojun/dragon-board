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

    expect(events).toHaveLength(1)
    expect(events[0]).toMatchObject({
      category: 'stock',
      code: '002552',
      name: '宝鼎科技',
      type: 12001,
      typeName: '竞价弱转强',
      direction: 'up',
      severity: 'important',
      matchedHotStock: false,
    })
    expect(events[0].raw).toMatchObject({
      source: 'opening_weak_to_strong_v3',
      signal: {
        signalType: 'opening_weak_to_strong',
        variant: 'auction_gap_reversal',
      },
    })
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

    expect(firstDay).toHaveLength(1)
    expect(secondDay).toHaveLength(1)
    expect(secondDay[0].id).toBe('opening_weak_to_strong:2026-05-23:002552:pending')
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
    const sample = fixture.cases.find(item => item.caseId === 'low-open-red-reversal')
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
      amount: 31_000_000,
      at: '2026-05-22T09:30:10+08:00',
      capturedAt: '2026-05-22T09:29:40+08:00',
      bridgeTs: '2026-05-22T09:29:40+08:00',
    }
    const strong = {
      ...sample!.quotes[sample!.quotes.length - 1],
      lastPrice: 37,
      amount: 60_000_000,
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

    expect(events).toHaveLength(2)
    expect(events[0].signal.confidence).toBe('watch')
    expect(events[1].signal.confidence).toBe('strong')
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
      'pending',
      'confirmed',
      'failed',
    ])
    expect(events[1].signal.intradayOutcome).toBe('confirmed_strong')
    expect(events[2].signal.intradayOutcome).toBe('failed_open_dump')
    expect(events[2].signal.riskFlags.map(item => item.key)).toContain('intraday_open_dump')
  })
})
