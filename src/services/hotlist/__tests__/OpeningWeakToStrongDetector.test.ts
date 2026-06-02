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
    const expectedHash = new OpeningWeakToStrongDetector(fixture.rules)
      .evaluate(fixture.cases[0].quotes[0] as OpeningWeakToStrongQuote, null)
      .configHash
    expect(expectedHash).toBe('owts-3dc612c2')

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
        expect(result?.configHash, sample.caseId).toBe(expectedHash)
        expect(result?.score, sample.caseId).toBeGreaterThanOrEqual(sample.expected.scoreRange?.[0] ?? 0)
        expect(result?.score, sample.caseId).toBeLessThanOrEqual(sample.expected.scoreRange?.[1] ?? 100)
      } else {
        expect(result?.triggered ?? false, sample.caseId).toBe(false)
        expect(result?.invalidReason, sample.caseId).toBe(sample.expected.invalidReason)
      }

      for (const riskFlag of sample.expected.riskFlags || []) {
        expect(result?.riskFlags.map(item => item.key) || [], sample.caseId).toContain(riskFlag)
      }
      if (sample.expected.dryRun !== undefined) {
        expect(result?.dryRun ?? false, sample.caseId).toBe(sample.expected.dryRun)
      }
      if (sample.expected.auctionCoverageRatio !== undefined) {
        expect(result?.auctionCoverageRatio, sample.caseId).toBeCloseTo(sample.expected.auctionCoverageRatio)
      }
      if (sample.expected.liquidityTier !== undefined) {
        expect(result?.liquidityTier, sample.caseId).toBe(sample.expected.liquidityTier)
      }
      if (sample.expected.liquidityTierMode !== undefined) {
        expect(result?.liquidityTierMode, sample.caseId).toBe(sample.expected.liquidityTierMode)
      }
      if (sample.expected.liquidityTierBasis !== undefined) {
        expect(result?.liquidityTierBasis, sample.caseId).toBe(sample.expected.liquidityTierBasis)
      }
      if (sample.expected.liquidityTierThresholds !== undefined) {
        expect(result?.liquidityTierThresholds, sample.caseId).toBe(
          sample.expected.liquidityTierThresholds,
        )
      }
      if (sample.expected.liquidityTierVersion !== undefined) {
        expect(result?.liquidityTierVersion, sample.caseId).toBe(sample.expected.liquidityTierVersion)
      }
      if (sample.expected.initialBaselineAt !== undefined) {
        expect(result?.initialBaselineAt, sample.caseId).toBe(sample.expected.initialBaselineAt)
      }
      if (sample.expected.initialBaselinePrice !== undefined) {
        expect(result?.initialBaselinePrice, sample.caseId).toBe(sample.expected.initialBaselinePrice)
      }
      if (sample.expected.initialBaselinePct !== undefined) {
        expect(result?.initialBaselinePct, sample.caseId).toBeCloseTo(sample.expected.initialBaselinePct)
      }
      if (sample.expected.initialBaselineAmount !== undefined) {
        expect(result?.initialBaselineAmount, sample.caseId).toBe(sample.expected.initialBaselineAmount)
      }
      if (sample.expected.lateBaselineAt !== undefined) {
        expect(result?.lateBaselineAt, sample.caseId).toBe(sample.expected.lateBaselineAt)
      }
      if (sample.expected.lateBaselinePrice !== undefined) {
        expect(result?.lateBaselinePrice, sample.caseId).toBe(sample.expected.lateBaselinePrice)
      }
      if (sample.expected.lateBaselinePct !== undefined) {
        expect(result?.lateBaselinePct, sample.caseId).toBeCloseTo(sample.expected.lateBaselinePct)
      }
      if (sample.expected.lateBaselineAmount !== undefined) {
        expect(result?.lateBaselineAmount, sample.caseId).toBe(sample.expected.lateBaselineAmount)
      }
      if (sample.expected.finalBaselineAt !== undefined) {
        expect(result?.finalBaselineAt, sample.caseId).toBe(sample.expected.finalBaselineAt)
      }
      if (sample.expected.finalBaselinePrice !== undefined) {
        expect(result?.finalBaselinePrice, sample.caseId).toBe(sample.expected.finalBaselinePrice)
      }
      if (sample.expected.finalBaselinePct !== undefined) {
        expect(result?.finalBaselinePct, sample.caseId).toBeCloseTo(sample.expected.finalBaselinePct)
      }
      if (sample.expected.finalBaselineAmount !== undefined) {
        expect(result?.finalBaselineAmount, sample.caseId).toBe(sample.expected.finalBaselineAmount)
      }
      if (sample.expected.auctionPriceLiftPctPoint !== undefined) {
        expect(result?.auctionPriceLiftPctPoint, sample.caseId).toBeCloseTo(
          sample.expected.auctionPriceLiftPctPoint,
        )
      }
      if (sample.expected.latePriceLiftPctPoint !== undefined) {
        expect(result?.latePriceLiftPctPoint, sample.caseId).toBeCloseTo(
          sample.expected.latePriceLiftPctPoint,
        )
      }
      if (sample.expected.auctionAmountDelta !== undefined) {
        expect(result?.auctionAmountDelta, sample.caseId).toBe(sample.expected.auctionAmountDelta)
      }
      if (sample.expected.lateAmountDelta !== undefined) {
        expect(result?.lateAmountDelta, sample.caseId).toBe(sample.expected.lateAmountDelta)
      }
      if (sample.expected.auctionAmountLiftRatio !== undefined) {
        expect(result?.auctionAmountLiftRatio, sample.caseId).toBeCloseTo(
          sample.expected.auctionAmountLiftRatio,
        )
      }
      if (sample.expected.lateAmountLiftRatio !== undefined) {
        expect(result?.lateAmountLiftRatio, sample.caseId).toBeCloseTo(
          sample.expected.lateAmountLiftRatio,
        )
      }
      if (sample.expected.priceVolumeConfirmed !== undefined) {
        expect(result?.priceVolumeConfirmed, sample.caseId).toBe(sample.expected.priceVolumeConfirmed)
      }
      if (sample.expected.intradayStatus !== undefined) {
        expect(result?.intradayStatus, sample.caseId).toBe(sample.expected.intradayStatus)
      }
      if (sample.expected.intradayOutcome !== undefined) {
        expect(result?.intradayOutcome, sample.caseId).toBe(sample.expected.intradayOutcome)
      }
      if (sample.expected.intradayStatusAt !== undefined) {
        expect(result?.intradayStatusAt, sample.caseId).toBe(sample.expected.intradayStatusAt)
      }
      if (sample.expected.intradayPrice !== undefined) {
        expect(result?.intradayPrice, sample.caseId).toBe(sample.expected.intradayPrice)
      }
      if (sample.expected.intradayPct !== undefined) {
        expect(result?.intradayPct, sample.caseId).toBeCloseTo(sample.expected.intradayPct)
      }
      if (sample.expected.intradayAmount !== undefined) {
        expect(result?.intradayAmount, sample.caseId).toBe(sample.expected.intradayAmount)
      }
      if (sample.expected.intradayNote !== undefined) {
        expect(result?.intradayNote, sample.caseId).toBe(sample.expected.intradayNote)
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

  it('emits a strict preopen candidate after the 09:25 final baseline is locked', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const quotes = sample!.quotes as OpeningWeakToStrongQuote[]

    for (const quote of quotes.slice(0, -1)) {
      store.capture(quote)
    }

    const finalQuote = quotes[quotes.length - 2]
    const candidate = detector.evaluate({
      ...finalQuote,
      at: '2026-05-22T09:25:12+08:00',
      capturedAt: '2026-05-22T09:25:12+08:00',
      bridgeTs: '2026-05-22T09:25:12+08:00',
    }, store.getBaseline(finalQuote.code, '2026-05-22T09:25:12+08:00'))

    expect(candidate.triggered).toBe(true)
    expect(candidate.variant).toBe('auction_late_lift')
    expect(candidate.confidence).toBe('strong')
    expect(candidate.intradayStatus).toBe('preopen_candidate')
    expect(candidate.intradayOutcome).toBe('preopen_candidate')
    expect(candidate.intradayNote).toBe('竞价量价齐升，等待开盘承接验证')
    expect(candidate.triggerAt).toBe('2026-05-22T09:25:12+08:00')
    expect(candidate.priceVolumeConfirmed).toBe(true)
    expect(candidate.riskFlags).toEqual([])
  })

  it('includes the 09:25:10 boundary in the strict preopen candidate window', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const quotes = sample!.quotes as OpeningWeakToStrongQuote[]

    for (const quote of quotes.slice(0, -1)) {
      store.capture(quote)
    }

    const finalQuote = quotes[quotes.length - 2]
    const candidate = detector.evaluate({
      ...finalQuote,
      at: '2026-05-22T09:25:10+08:00',
      capturedAt: '2026-05-22T09:25:10+08:00',
      bridgeTs: '2026-05-22T09:25:10+08:00',
    }, store.getBaseline(finalQuote.code, '2026-05-22T09:25:10+08:00'))

    expect(candidate.triggered).toBe(true)
    expect(candidate.intradayStatus).toBe('preopen_candidate')
    expect(candidate.intradayOutcome).toBe('preopen_candidate')
  })

  it('emits a preopen candidate from the 09:25 final auction quote', () => {
    const fixture = loadFixture()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const base = {
      code: '002579',
      name: '中京电子',
      preClose: 17.15,
      open: 0,
      volume: 1_000_000,
    }

    const quotes = [
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
    ] satisfies OpeningWeakToStrongQuote[]

    for (const quote of quotes) store.capture(quote)
    const finalQuote = quotes[quotes.length - 1]
    const candidate = detector.evaluate(finalQuote, store.getBaseline(finalQuote.code, finalQuote.at))

    expect(candidate.triggered).toBe(true)
    expect(candidate.variant).toBe('auction_late_lift')
    expect(candidate.intradayStatus).toBe('preopen_candidate')
    expect(candidate.priceVolumeConfirmed).toBe(true)
    expect(candidate.auctionPct).toBeCloseTo(-9.85)
    expect(candidate.auctionPriceLiftPctPoint).toBeCloseTo(5.01)
    expect(candidate.latePriceLiftPctPoint).toBeCloseTo(2.68)
    expect(candidate.riskFlags.map(item => item.key)).not.toContain('auction_late_high_retreated')
  })

  it('keeps a weak 09:25 baseline as a silent preopen candidate without auction price-volume confirmation', () => {
    const fixture = loadFixture()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const base = {
      code: '002580',
      name: '弱基准候选',
      preClose: 10,
      open: 0,
      volume: 800_000,
    }
    const quotes = [
      {
        ...base,
        at: '2026-06-01T09:20:05+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        capturedAt: '2026-06-01T09:20:05+08:00',
        bridgeTs: '2026-06-01T09:20:05+08:00',
      },
      {
        ...base,
        at: '2026-06-01T09:24:05+08:00',
        lastPrice: 9.94,
        amount: 4_000_000,
        capturedAt: '2026-06-01T09:24:05+08:00',
        bridgeTs: '2026-06-01T09:24:05+08:00',
      },
      {
        ...base,
        at: '2026-06-01T09:25:00+08:00',
        lastPrice: 9.9,
        amount: 6_000_000,
        capturedAt: '2026-06-01T09:25:00+08:00',
        bridgeTs: '2026-06-01T09:25:00+08:00',
      },
    ] satisfies OpeningWeakToStrongQuote[]

    for (const quote of quotes) store.capture(quote)
    const finalQuote = quotes[quotes.length - 1]
    const candidate = detector.evaluate(finalQuote, store.getBaseline(finalQuote.code, finalQuote.at))

    expect(candidate.triggered).toBe(true)
    expect(candidate.variant).toBe('auction_gap_reversal')
    expect(candidate.intradayStatus).toBe('preopen_candidate')
    expect(candidate.priceVolumeConfirmed).toBe(false)
    expect(candidate.riskFlags.map(item => item.key)).toContain('auction_price_volume_unverified')
    expect(candidate.intradayNote).toBe('09:25基准偏弱，等待09:30强跳变验证')
  })

  it('does not confirm a preopen candidate without the 09:30 pending opening check', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const quotes = sample!.quotes as OpeningWeakToStrongQuote[]

    for (const quote of quotes.slice(0, -1)) {
      store.capture(quote)
    }

    const finalQuote = quotes[quotes.length - 2]
    const candidate = detector.evaluate({
      ...finalQuote,
      at: '2026-05-22T09:25:12+08:00',
      capturedAt: '2026-05-22T09:25:12+08:00',
      bridgeTs: '2026-05-22T09:25:12+08:00',
    }, store.getBaseline(finalQuote.code, '2026-05-22T09:25:12+08:00'))
    const intraday = detector.evaluate({
      ...quotes[quotes.length - 1],
      at: '2026-05-22T09:36:00+08:00',
      capturedAt: '2026-05-22T09:36:00+08:00',
      bridgeTs: '2026-05-22T09:36:00+08:00',
      lastPrice: 38.5,
      amount: 90_000_000,
    }, store.getBaseline(finalQuote.code, '2026-05-22T09:36:00+08:00'))

    expect(candidate.intradayStatus).toBe('preopen_candidate')
    expect(intraday?.intradayStatus).not.toBe('confirmed')
    expect(intraday?.intradayOutcome).not.toBe('confirmed_strong')
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
      at: '2026-05-22T09:20:05+08:00',
      lastPrice: 9.7,
      amount: 3_000_000,
      capturedAt: '2026-05-22T09:20:05+08:00',
      bridgeTs: '2026-05-22T09:20:05+08:00',
    })
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
    expect(result.initialBaselineAt).toContain('09:20:05')
  })

  it('downgrades signals when current amount regresses below auction amount', () => {
    const fixture = loadFixture()
    const sample = fixture.cases.find(item => item.caseId === '002552-auction-gap-reversal')
    expect(sample).toBeTruthy()
    const store = new OpeningAuctionStateStore(fixture.rules)
    const detector = new OpeningWeakToStrongDetector(fixture.rules)
    const quotes = sample!.quotes as OpeningWeakToStrongQuote[]
    const open = quotes[quotes.length - 1]

    for (const quote of quotes.slice(0, -1)) {
      store.capture({
        ...quote,
        amount: isAuctionFinalQuote(quote) ? 80_000_000 : quote.amount,
      })
    }
    const result = detector.evaluate({
      ...open,
      amount: 60_000_000,
    }, store.getBaseline(open.code, open.at))

    expect(result.triggered).toBe(true)
    expect(result.confidence).toBe('critical')
    expect(result.riskFlags.map(item => item.key)).toContain('amount_regressed')
  })
})

function isAuctionFinalQuote(quote: OpeningWeakToStrongQuote): boolean {
  return quote.at.includes('09:25:')
}
