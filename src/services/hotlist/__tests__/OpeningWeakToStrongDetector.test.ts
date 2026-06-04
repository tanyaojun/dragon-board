import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  OpeningAuctionStateStore,
  OpeningWeakToStrongDetector,
} from '../OpeningWeakToStrongDetector'
import type {
  OpeningWeakToStrongFixture,
  OpeningWeakToStrongQuote,
  OpeningWeakToStrongSignal,
} from '../openingWeakToStrongTypes'

function loadFixture(): OpeningWeakToStrongFixture {
  return JSON.parse(
    readFileSync(
      join(process.cwd(), 'docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json'),
      'utf8',
    ),
  ) as OpeningWeakToStrongFixture
}

function runQuotes(quotes: OpeningWeakToStrongQuote[]): OpeningWeakToStrongSignal[] {
  const rules = loadFixture().rules
  const store = new OpeningAuctionStateStore(rules)
  const detector = new OpeningWeakToStrongDetector(rules)
  const events: OpeningWeakToStrongSignal[] = []

  for (const quote of quotes) {
    store.capture(quote)
    const event = detector.evaluate(quote, store.getBaseline(quote.code, quote.at))
    if (event?.triggered) events.push(event)
  }

  return events
}

function runCheckpointAcceptance(quotes: OpeningWeakToStrongQuote[]) {
  const rules = loadFixture().rules
  const store = new OpeningAuctionStateStore(rules)
  const detector = new OpeningWeakToStrongDetector(rules)
  const byCheckpoint = new Map<string, OpeningWeakToStrongSignal>()

  for (const quote of quotes) {
    store.capture(quote)
    const event = detector.evaluate(quote, store.getBaseline(quote.code, quote.at))
    if (event?.triggered) byCheckpoint.set(quote.at.slice(11, 16), event)
  }

  return ['09:20', '09:25', '09:30', '09:35', '10:00'].map((at) => {
    const event = byCheckpoint.get(at)
    return {
      at,
      result: event?.stage === 'noGap' || event?.stage === 'trendWeak' ? 'FAIL' : 'PASS',
      stage: event?.stage || 'auctionConditionPassed',
      voiceEligible: event?.voiceEligible === true,
    }
  })
}

const baseQuote = {
  code: '002552',
  name: '宝鼎科技',
  preClose: 10,
  limitUpPrice: 11,
  openingForcedSample: true,
  requestedCount: 1,
  receivedCount: 1,
} satisfies Partial<OpeningWeakToStrongQuote>

describe('OpeningWeakToStrongDetector', () => {
  it('emits the required live checkpoints and only voices 09:30 / 09:35 alerts', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.35,
        open: 10.35,
        amount: 8_000_000,
        volume: 600_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 10.65,
        open: 10.35,
        amount: 16_000_000,
        volume: 1_200_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T10:00:00+08:00',
        capturedAt: '2026-06-03T10:00:00+08:00',
        bridgeTs: '2026-06-03T10:00:00+08:00',
        lastPrice: 10.7,
        open: 10.35,
        amount: 25_000_000,
        volume: 2_000_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(event => event.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(events.map(event => event.voiceEligible)).toEqual([false, true, true, false])
    expect(events.map(event => event.time)).toEqual([
      '2026-06-03T09:25:00+08:00',
      '2026-06-03T09:30:00+08:00',
      '2026-06-03T09:35:00+08:00',
      '2026-06-03T10:00:00+08:00',
    ])
  })

  it('confirms 09:35 trend from the 09:30 gap signal when the quote lacks open price', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.35,
        open: 10.35,
        amount: 8_000_000,
        volume: 600_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 10.65,
        open: 0,
        amount: 16_000_000,
        volume: 1_200_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(event => event.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
    ])
    expect(events[2].voiceEligible).toBe(true)
  })

  it('uses only the 09:20 and 09:25 auction baselines without requiring a 09:24 quote', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.7,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.92,
        amount: 2_000_000,
        volume: 180_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events).toHaveLength(1)
    expect(events[0].stage).toBe('auctionConditionPassed')
    expect(events[0].voiceEligible).toBe(false)
  })

  it('emits noGap and trendWeak as non-voice status updates', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.05,
        open: 10.05,
        amount: 6_000_000,
        volume: 500_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 9.98,
        open: 10.05,
        amount: 8_000_000,
        volume: 700_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(event => event.stage)).toEqual([
      'auctionConditionPassed',
      'noGap',
      'trendWeak',
    ])
    expect(events.every(event => event.voiceEligible === false)).toBe(true)
  })

  it('does not emit a 09:30 gap alert without the same-day 09:25 confirmation baseline', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-04T09:30:00+08:00',
        capturedAt: '2026-06-04T09:30:00+08:00',
        bridgeTs: '2026-06-04T09:30:00+08:00',
        lastPrice: 10.35,
        open: 10.35,
        amount: 8_000_000,
        volume: 600_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events).toHaveLength(0)
  })

  it('does not run any delayed board confirmation after the 10:00 final status update', () => {
    const rules = loadFixture().rules
    const store = new OpeningAuctionStateStore(rules)
    const detector = new OpeningWeakToStrongDetector(rules)
    const quotes = [
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.35,
        open: 10.35,
        amount: 8_000_000,
        volume: 600_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T10:00:00+08:00',
        capturedAt: '2026-06-03T10:00:00+08:00',
        bridgeTs: '2026-06-03T10:00:00+08:00',
        lastPrice: 10.4,
        open: 10.35,
        amount: 18_000_000,
        volume: 1_500_000,
      },
    ] as OpeningWeakToStrongQuote[]

    let finalStatus: OpeningWeakToStrongSignal | null = null
    for (const quote of quotes) {
      store.capture(quote)
      finalStatus = detector.evaluate(quote, store.getBaseline(quote.code, quote.at))
    }
    const afterTen = detector.evaluate({
      ...quotes[3],
      at: '2026-06-03T14:56:00+08:00',
      capturedAt: '2026-06-03T14:56:00+08:00',
      bridgeTs: '2026-06-03T14:56:00+08:00',
      lastPrice: 11,
      amount: 60_000_000,
      volume: 4_000_000,
    }, store.getBaseline(baseQuote.code!, '2026-06-03T14:56:00+08:00'))

    expect(finalStatus?.stage).toBe('optionalFinalStatus')
    expect(finalStatus?.voiceEligible).toBe(false)
    expect(afterTen?.triggered ?? false).toBe(false)
  })

  it('ignores non-checkpoint quotes instead of emitting scored strategy signals', () => {
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:31:00+08:00',
        capturedAt: '2026-06-03T09:31:00+08:00',
        bridgeTs: '2026-06-03T09:31:00+08:00',
        lastPrice: 10.45,
        open: 10.35,
        amount: 12_000_000,
        volume: 900_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(event => event.stage)).toEqual(['auctionConditionPassed'])
  })

  it('keeps the shared fixture narrowed to the five checkpoint acceptance contract', () => {
    const fixture = loadFixture()
    const serialized = JSON.stringify(fixture)

    expect(serialized).not.toContain('09:24')
    expect(fixture.cases.every(testCase => Array.isArray(testCase.expected?.checkpoints))).toBe(true)
    expect(fixture.cases.map(testCase => testCase.expected.checkpoints.map(item => item.at))).toEqual(
      fixture.cases.map(() => ['09:20', '09:25', '09:30', '09:35', '10:00']),
    )
    expect(serialized).not.toContain('score')
    expect(serialized).not.toContain('confidence')
    expect(serialized).not.toContain('factors')
    expect(serialized).not.toContain('riskFlags')
    for (const testCase of fixture.cases) {
      expect(runCheckpointAcceptance(testCase.quotes)).toEqual(testCase.expected.checkpoints)
    }
  })
})
