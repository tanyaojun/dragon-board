import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { OpeningRealtimeEventBuffer } from '../OpeningRealtimeEventBuffer'
import type { OpeningWeakToStrongFixture, OpeningWeakToStrongQuote } from '../openingWeakToStrongTypes'

function loadFixture(): OpeningWeakToStrongFixture {
  return JSON.parse(
    readFileSync(
      join(process.cwd(), 'docs/yidong-jingling/fixtures/opening-weak-to-strong-cases.json'),
      'utf8',
    ),
  ) as OpeningWeakToStrongFixture
}

const base = {
  code: '002552',
  name: '宝鼎科技',
  preClose: 10,
  limitUpPrice: 11,
  openingForcedSample: true,
  requestedCount: 1,
  receivedCount: 1,
}

function buffer() {
  const fixture = loadFixture()
  return new OpeningRealtimeEventBuffer({
    rules: fixture.rules,
    ruleVersion: fixture.ruleVersion,
  })
}

describe('OpeningRealtimeEventBuffer', () => {
  it('converts the four live checkpoints into stage-specific hot stock events', () => {
    const realtime = buffer()
    const events = [
      {
        ...base,
        at: '2026-06-03T09:20:00+08:00',
        capturedAt: '2026-06-03T09:20:00+08:00',
        bridgeTs: '2026-06-03T09:20:00+08:00',
        lastPrice: 9.8,
        amount: 1_000_000,
        volume: 100_000,
      },
      {
        ...base,
        at: '2026-06-03T09:24:00+08:00',
        capturedAt: '2026-06-03T09:24:00+08:00',
        bridgeTs: '2026-06-03T09:24:00+08:00',
        lastPrice: 9.9,
        amount: 1_500_000,
        volume: 150_000,
      },
      {
        ...base,
        at: '2026-06-03T09:25:00+08:00',
        capturedAt: '2026-06-03T09:25:00+08:00',
        bridgeTs: '2026-06-03T09:25:00+08:00',
        lastPrice: 9.95,
        amount: 2_000_000,
        volume: 180_000,
      },
      {
        ...base,
        at: '2026-06-03T09:30:00+08:00',
        capturedAt: '2026-06-03T09:30:00+08:00',
        bridgeTs: '2026-06-03T09:30:00+08:00',
        lastPrice: 10.35,
        open: 10.35,
        amount: 8_000_000,
        volume: 600_000,
      },
      {
        ...base,
        at: '2026-06-03T09:35:00+08:00',
        capturedAt: '2026-06-03T09:35:00+08:00',
        bridgeTs: '2026-06-03T09:35:00+08:00',
        lastPrice: 10.65,
        open: 10.35,
        amount: 16_000_000,
        volume: 1_200_000,
      },
      {
        ...base,
        at: '2026-06-03T10:00:00+08:00',
        capturedAt: '2026-06-03T10:00:00+08:00',
        bridgeTs: '2026-06-03T10:00:00+08:00',
        lastPrice: 10.7,
        open: 10.35,
        amount: 25_000_000,
        volume: 2_000_000,
      },
    ].flatMap(quote => realtime.acceptQuoteWithSignals(quote as OpeningWeakToStrongQuote))

    expect(events.map(item => item.signal.stage)).toEqual([
      'auctionConditionPassed',
      'gapAlert',
      'trendConfirm',
      'optionalFinalStatus',
    ])
    expect(events.map(item => item.event.id)).toEqual([
      'opening_weak_to_strong:2026-06-03:002552:auctionConditionPassed',
      'opening_weak_to_strong:2026-06-03:002552:gapAlert',
      'opening_weak_to_strong:2026-06-03:002552:trendConfirm',
      'opening_weak_to_strong:2026-06-03:002552:optionalFinalStatus',
    ])
    expect(events.map(item => item.event.typeName)).toEqual([
      '竞价弱转强候选',
      '开盘承接转强',
      '开盘反攻确认',
      '竞价弱转强复盘',
    ])
    expect(events.map(item => item.signal.voiceEligible)).toEqual([false, true, true, false])
  })

  it('allows the same stock to emit the same checkpoint again on the next trading day', () => {
    const realtime = buffer()
    const quote = {
      ...base,
      at: '2026-06-03T09:20:00+08:00',
      capturedAt: '2026-06-03T09:20:00+08:00',
      bridgeTs: '2026-06-03T09:20:00+08:00',
      lastPrice: 9.8,
      amount: 1_000_000,
      volume: 100_000,
    } as OpeningWeakToStrongQuote
    realtime.acceptQuote(quote)
    realtime.acceptQuote({
      ...quote,
      at: '2026-06-03T09:24:00+08:00',
      capturedAt: '2026-06-03T09:24:00+08:00',
      bridgeTs: '2026-06-03T09:24:00+08:00',
      lastPrice: 9.9,
      amount: 1_500_000,
    })

    const firstDay = realtime.acceptQuote({
      ...quote,
      at: '2026-06-03T09:25:00+08:00',
      capturedAt: '2026-06-03T09:25:00+08:00',
      bridgeTs: '2026-06-03T09:25:00+08:00',
      lastPrice: 9.95,
      amount: 2_000_000,
    })
    realtime.acceptQuote({
      ...quote,
      at: '2026-06-04T09:20:00+08:00',
      capturedAt: '2026-06-04T09:20:00+08:00',
      bridgeTs: '2026-06-04T09:20:00+08:00',
    })
    realtime.acceptQuote({
      ...quote,
      at: '2026-06-04T09:24:00+08:00',
      capturedAt: '2026-06-04T09:24:00+08:00',
      bridgeTs: '2026-06-04T09:24:00+08:00',
      lastPrice: 9.9,
      amount: 1_500_000,
    })
    const secondDay = realtime.acceptQuote({
      ...quote,
      at: '2026-06-04T09:25:00+08:00',
      capturedAt: '2026-06-04T09:25:00+08:00',
      bridgeTs: '2026-06-04T09:25:00+08:00',
      lastPrice: 9.95,
      amount: 2_000_000,
    })

    expect(firstDay[0].id).toBe('opening_weak_to_strong:2026-06-03:002552:auctionConditionPassed')
    expect(secondDay[0].id).toBe('opening_weak_to_strong:2026-06-04:002552:auctionConditionPassed')
  })
})
