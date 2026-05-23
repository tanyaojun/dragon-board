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
} from '../openingWeakToStrongTypes'

function loadFixture(): OpeningWeakToStrongFixture {
  return JSON.parse(
    readFileSync(
      join(process.cwd(), 'docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json'),
      'utf8',
    ),
  ) as OpeningWeakToStrongFixture
}

describe('OpeningWeakToStrongDetector', () => {
  it('matches the shared golden fixture cases', () => {
    const fixture = loadFixture()

    for (const sample of fixture.cases) {
      const store = new OpeningAuctionStateStore(fixture.rules)
      const detector = new OpeningWeakToStrongDetector(fixture.rules)
      let result = null

      for (const quote of sample.quotes as OpeningWeakToStrongQuote[]) {
        store.capture(quote)
        result = detector.evaluate(quote, store.getBaseline(quote.code, quote.at))
      }

      if (sample.expected.triggered) {
        expect(result, sample.caseId).not.toBeNull()
        expect(result?.triggered, sample.caseId).toBe(true)
        expect(result?.variant, sample.caseId).toBe(sample.expected.variant)
        expect(result?.confidence, sample.caseId).toBe(sample.expected.confidence)
        expect(result?.configHash, sample.caseId).toMatch(/^owts-[0-9a-f]{8}$/)
        expect(result?.score, sample.caseId).toBeGreaterThanOrEqual(sample.expected.scoreRange?.[0] ?? 0)
        expect(result?.score, sample.caseId).toBeLessThanOrEqual(sample.expected.scoreRange?.[1] ?? 100)
      } else {
        expect(result?.triggered ?? false, sample.caseId).toBe(false)
        expect(result?.invalidReason, sample.caseId).toBe(sample.expected.invalidReason)
      }

      for (const riskFlag of sample.expected.riskFlags || []) {
        expect(result?.riskFlags.map(item => item.key) || [], sample.caseId).toContain(riskFlag)
      }
    }
  })

  it('does not reuse a previous trading day auction baseline', () => {
    const fixture = loadFixture()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)

    const auction = {
      code: '002552',
      name: '宝鼎科技',
      at: '2026-05-21T09:25:00+08:00',
      lastPrice: 35.68,
      preClose: 36.2,
      amount: 6_000_000,
      capturedAt: '2026-05-21T09:25:00+08:00',
      bridgeTs: '2026-05-21T09:25:00+08:00',
    }
    const nextDayOpen = {
      code: '002552',
      name: '宝鼎科技',
      at: '2026-05-22T09:30:06+08:00',
      lastPrice: 37.48,
      preClose: 36.2,
      open: 36.92,
      amount: 56_000_000,
      capturedAt: '2026-05-22T09:30:06+08:00',
      bridgeTs: '2026-05-22T09:30:06+08:00',
    }

    store.capture(auction)
    const result = detector.evaluate(nextDayOpen, store.getBaseline(nextDayOpen.code, nextDayOpen.at))

    expect(result.triggered).toBe(false)
    expect(result.invalidReason).toBe('baseline_missing')
  })

  it('uses delayed auction quotes for profile without rolling back the locked baseline', () => {
    const fixture = loadFixture()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const quote = {
      code: '002559',
      name: '乱序基线',
      preClose: 10,
      open: 0,
      volume: 1_000_000,
      capturedAt: '2026-05-22T09:25:00+08:00',
      bridgeTs: '2026-05-22T09:25:00+08:00',
    }

    store.capture({
      ...quote,
      at: '2026-05-22T09:25:05+08:00',
      lastPrice: 10.1,
      amount: 20_000_000,
      capturedAt: '2026-05-22T09:25:05+08:00',
      bridgeTs: '2026-05-22T09:25:05+08:00',
    })
    store.capture({
      ...quote,
      at: '2026-05-22T09:24:55+08:00',
      lastPrice: 9.8,
      amount: 5_000_000,
      capturedAt: '2026-05-22T09:24:55+08:00',
      bridgeTs: '2026-05-22T09:24:55+08:00',
    })

    const open = {
      ...quote,
      at: '2026-05-22T09:30:06+08:00',
      lastPrice: 10.31,
      open: 10.1,
      amount: 55_000_000,
      capturedAt: '2026-05-22T09:30:06+08:00',
      bridgeTs: '2026-05-22T09:30:06+08:00',
    }
    const baseline = store.getBaseline(open.code, open.at)
    const result = detector.evaluate(open, baseline)

    expect(baseline?.auctionPct).toBeCloseTo(1)
    expect(result.triggered).toBe(true)
    expect(result.variant).toBe('auction_late_lift')
    expect(result.auctionPct).toBeCloseTo(1)
    expect(result.auctionSampleCount).toBe(2)
  })

  it('downgrades signals when current amount regresses below auction amount', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const [auction, open] = sample!.quotes as OpeningWeakToStrongQuote[]

    store.capture({
      ...auction,
      amount: 80_000_000,
    })
    const result = detector.evaluate({
      ...open,
      amount: 60_000_000,
    }, store.getBaseline(open.code, open.at))

    expect(result.triggered).toBe(true)
    expect(result.confidence).toBe('watch')
    expect(result.riskFlags.map(item => item.key)).toContain('amount_regressed')
  })
})
