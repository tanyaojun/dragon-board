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

function lateBaselineQuote(overrides: Partial<OpeningWeakToStrongQuote> = {}): OpeningWeakToStrongQuote {
  return {
    ...baseQuote,
    at: '2026-06-03T09:24:00+08:00',
    capturedAt: '2026-06-03T09:24:00+08:00',
    bridgeTs: '2026-06-03T09:24:00+08:00',
    lastPrice: 9.9,
    amount: 1_500_000,
    volume: 150_000,
    ...overrides,
  } as OpeningWeakToStrongQuote
}

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
      lateBaselineQuote(),
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
      lateBaselineQuote(),
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

  it('rejects a 09:25 candidate when neither total nor late lift meets thresholds', () => {
    // preClose=10, 09:20 pct=-3.0%, 09:24 pct=-2.8%, 09:25 pct=-2.6%
    // totalLift=0.4 < 0.8 ✗, amountRatio=0.15 < 0.35 ✗  → 全段推失败
    // lateLift=0.2 < 0.3 ✗,   lateAmount=0.127 < 0.2 ✗    → 临门突袭也失败
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.70,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.72,
        amount: 1_020_000,
        volume: 102_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.74,
        amount: 1_150_000,
        volume: 115_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events).toHaveLength(1)
    expect(events[0].stage).toBe('auctionConditionFailed')
    expect(events[0].reason).toContain('09:24')
    expect(events[0].voiceEligible).toBe(false)
  })

  it('passes a 09:25 candidate when both 09:20 total and 09:24 late lifts confirm', () => {
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
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.86,
        amount: 1_500_000,
        volume: 150_000,
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
      lateBaselineQuote(),
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

  it('gapAlert at 09:30 then trendWeak at 09:35 when price retreats below open', () => {
    // 全段推竞价通过 → gapAlert → 09:35 跌破开盘价转弱（路径三）
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.70,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.90,
        amount: 1_900_000,
        volume: 190_000,
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
        lastPrice: 9.98,
        open: 10.35,
        amount: 10_000_000,
        volume: 800_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(e => e.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendWeak',
    ])
    expect(events[2].voiceEligible).toBe(false)
    expect(events[2].firstWindowPrice!).toBeLessThan(events[2].officialOpen!)
  })

  it('late lift passes, gapAlert fires, then trendWeak at 09:35 when price retreats', () => {
    // 临门突袭竞价通过 → gapAlert → 09:35 回落转弱（路径四）
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.70,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.70,
        amount: 1_050_000,
        volume: 105_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.76,
        amount: 1_350_000,
        volume: 135_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.15,
        open: 10.15,
        amount: 5_000_000,
        volume: 400_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 9.90,
        open: 10.15,
        amount: 6_000_000,
        volume: 500_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(e => e.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendWeak',
    ])
    expect(events[2].voiceEligible).toBe(false)
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
      lateBaselineQuote(),
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
      ...quotes[4],
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

  // ── 形态专项：gapAlert & trendConfirm ──

  it('emits standalone gapAlert at 09:30 when all four opening support conditions are met', () => {
    // 竞价通过 → 09:30 改善达标 → gapAlert，无 09:35 后续行情
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.70,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.90,
        amount: 1_900_000,
        volume: 190_000,
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
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(e => e.stage)).toEqual(['auctionConditionPassed', 'gapAlert'])
    expect(events[1].voiceEligible).toBe(true)
    // 四个 gap 条件逐项验证
    expect(events[1].jumpPctPoint!).toBeGreaterThanOrEqual(1.2)       // 改善幅度 ≥ 1.2%
    expect(events[1].firstWindowPrice!).toBeGreaterThanOrEqual(events[1].auctionFinalPrice!)  // 现价 ≥ 竞价价
    expect(events[1].officialOpen!).toBeGreaterThanOrEqual(events[1].auctionFinalPrice!)      // 开盘价 ≥ 竞价价
  })

  it('verifies trendConfirm fires when price stays above open and improvement is sustained', () => {
    // 竞价通过 → gapAlert → 09:35 高开高走，四个条件全部满足
    const events = runQuotes([
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.70,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.70,
        amount: 1_050_000,
        volume: 105_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.76,
        amount: 1_350_000,
        volume: 135_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.15,
        open: 10.15,
        amount: 5_000_000,
        volume: 400_000,
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 10.20,
        open: 10.15,
        amount: 10_000_000,
        volume: 800_000,
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(e => e.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
    ])
    const trend = events[2]
    expect(trend.voiceEligible).toBe(true)
    // 四个 trendConfirm 条件逐项验证
    expect(trend.firstWindowPrice!).toBeGreaterThanOrEqual(trend.officialOpen!)  // 现价 ≥ 开盘价
    expect(trend.firstWindowPct!).toBeGreaterThanOrEqual(trend.auctionPct!)      // 涨幅 ≥ 竞价涨幅
    expect(trend.firstWindowPct! - trend.auctionPct!).toBeGreaterThanOrEqual(1.2) // 改善幅度维持
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
      lateBaselineQuote(),
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

describe('OpeningWeakToStrongDetector - checkpoint window threshold', () => {
  it('600703 delayed quotes within checkpoint window trigger gapAlert and trendConfirm', () => {
    const events = runQuotes([
      {
        code: '600703', name: '\u4e09\u5b89\u5149\u7535',
        at: '2026-06-04T09:20:00+08:00', lastPrice: 15.32, preClose: 15.51,
        amount: 12_000_000, volume: 783_000,
        capturedAt: '2026-06-04T09:20:00+08:00',
      },
      {
        code: '600703', name: '\u4e09\u5b89\u5149\u7535',
        at: '2026-06-04T09:24:48+08:00', lastPrice: 15.30, preClose: 15.51,
        amount: 27_450_000, volume: 1_794_000,
        capturedAt: '2026-06-04T09:24:48+08:00',
      },
      {
        code: '600703', name: '\u4e09\u5b89\u5149\u7535',
        at: '2026-06-04T09:25:01+08:00', lastPrice: 15.47, preClose: 15.51,
        amount: 43_032_900, volume: 2_781_000,
        capturedAt: '2026-06-04T09:25:01+08:00',
      },
      {
        code: '600703', name: '\u4e09\u5b89\u5149\u7535',
        at: '2026-06-04T09:30:18+08:00', lastPrice: 15.79, preClose: 15.51,
        open: 15.47, amount: 125_000_000, volume: 7_900_000,
        capturedAt: '2026-06-04T09:30:18+08:00',
      },
      {
        code: '600703', name: '\u4e09\u5b89\u5149\u7535',
        at: '2026-06-04T09:35:22+08:00', lastPrice: 16.01, preClose: 15.51,
        open: 15.47, amount: 630_600_000, volume: 39_400_000,
        capturedAt: '2026-06-04T09:35:22+08:00',
      },
    ] as OpeningWeakToStrongQuote[])

    expect(events.map(e => e.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
    ])
  })

  it('noGap upgrades to gapAlert when later quote in same window improves', () => {
    const events = runQuotes([
      {
        code: '002560', name: '\u5347\u7ea7\u6d4b\u8bd5',
        at: '2026-06-04T09:20:00+08:00', lastPrice: 9.8, preClose: 10,
        amount: 1_000_000, volume: 100_000,
        capturedAt: '2026-06-04T09:20:00+08:00',
      },
      {
        code: '002560', name: '\u5347\u7ea7\u6d4b\u8bd5',
        at: '2026-06-04T09:24:00+08:00', lastPrice: 9.9, preClose: 10,
        amount: 1_500_000, volume: 150_000,
        capturedAt: '2026-06-04T09:24:00+08:00',
      },
      {
        code: '002560', name: '\u5347\u7ea7\u6d4b\u8bd5',
        at: '2026-06-04T09:25:00+08:00', lastPrice: 9.95, preClose: 10,
        amount: 2_000_000, volume: 180_000,
        capturedAt: '2026-06-04T09:25:00+08:00',
      },
      {
        code: '002560', name: '\u5347\u7ea7\u6d4b\u8bd5',
        at: '2026-06-04T09:30:05+08:00', lastPrice: 10.05, preClose: 10,
        open: 9.95, amount: 5_000_000, volume: 400_000,
        capturedAt: '2026-06-04T09:30:05+08:00',
      },
      {
        code: '002560', name: '\u5347\u7ea7\u6d4b\u8bd5',
        at: '2026-06-04T09:30:18+08:00', lastPrice: 10.35, preClose: 10,
        open: 9.95, amount: 12_000_000, volume: 900_000,
        capturedAt: '2026-06-04T09:30:18+08:00',
      },
    ] as OpeningWeakToStrongQuote[])

    // noGap fires first at 09:30:05, then gapAlert upgrades at 09:30:18
    // both get emitted, but the last gapAlert is the final active state
    expect(events.filter(e => e.stage === 'gapAlert').length).toBe(1)
    expect(events.map(e => e.stage)).toContain('auctionConditionPassed')
    expect(events.map(e => e.stage)).toContain('gapAlert')
  })

  it('quote at 09:30:45 outside checkpoint window does not trigger gapAlert', () => {
    const quotes = [
      {
        ...baseQuote,
        at: '2026-06-03T09:20:00+08:00', lastPrice: 9.8, amount: 1_000_000, volume: 100_000,
        capturedAt: '2026-06-03T09:20:00+08:00', bridgeTs: '2026-06-03T09:20:00+08:00',
      },
      lateBaselineQuote({ at: '2026-06-03T09:24:00+08:00', capturedAt: '2026-06-03T09:24:00+08:00', bridgeTs: '2026-06-03T09:24:00+08:00' }),
      {
        ...baseQuote,
        at: '2026-06-03T09:25:00+08:00', lastPrice: 9.95, amount: 2_000_000, volume: 180_000,
        capturedAt: '2026-06-03T09:25:00+08:00', bridgeTs: '2026-06-03T09:25:00+08:00',
      },
      {
        ...baseQuote,
        at: '2026-06-03T09:30:45+08:00', lastPrice: 10.35, open: 9.95,
        amount: 8_000_000, volume: 600_000,
        capturedAt: '2026-06-03T09:30:45+08:00', bridgeTs: '2026-06-03T09:30:45+08:00',
      },
    ] as OpeningWeakToStrongQuote[]
    const events = runQuotes(quotes)
    // only candidate, 09:30:45 outside window
    expect(events.length).toBe(1)
    expect(events[0].stage).toBe('auctionConditionPassed')
  })
})
