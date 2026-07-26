import { describe, expect, it } from 'vitest'
import { analyzeRankResonance } from '../resonanceAnalyzer'

describe('analyzeRankResonance', () => {
  const quality = {
    status: 'ok' as const,
  }

  it('uses relative momentum and persistence to keep a continuous rise as buy without a new jump', () => {
    const result = analyzeRankResonance({
      percentiles: [42, 51, 63, 76, 88],
      sampleQuality: quality,
      marketMedianShortChange: 12,
      jump: { direction: 'hold', event: 'none', events: [] },
      marketSampleCount: 20,
    })

    expect(result.status).toBe('ok')
    expect(result.direction).toBe('buy')
    expect(result.score).toBeGreaterThan(0)
    expect(result.persistence).toBe(1)
  })

  it('lets a latest opposite jump override otherwise positive momentum', () => {
    const result = analyzeRankResonance({
      percentiles: [42, 51, 63, 76, 88],
      sampleQuality: quality,
      marketMedianShortChange: 12,
      jump: { direction: 'sell', event: 'jump', events: [{ index: 4, direction: 'collapse', magnitude: 20 }] },
      marketSampleCount: 20,
    })

    expect(result.direction).toBe('sell')
  })

  it('uses the full current-frame series of 002298 to produce buy', () => {
    const result = analyzeRankResonance({
      percentiles: [58.8, 27.5, 29.3, 95.2],
      sampleQuality: quality,
      marketMedianShortChange: 5,
      jump: { direction: 'buy', event: 'jump', events: [{ index: 3, direction: 'surge', magnitude: 55.4 }] },
      marketSampleCount: 20,
    })

    expect(result.direction).toBe('buy')
    expect(result.jumpFreshness).toBe(1)
  })

  it('uses only the latest eight bars for path persistence and reversal penalty', () => {
    const latestPath = [20, 30, 40, 50, 60, 70, 80, 90]
    const result = analyzeRankResonance({
      percentiles: [100, 0, 100, 0, ...latestPath],
      sampleQuality: quality,
      marketMedianShortChange: 12,
      jump: { direction: 'hold', event: 'none', events: [] },
      marketSampleCount: 20,
    })

    expect(result.persistence).toBe(1)
    expect(result.reversalPenalty).toBe(0)
    expect(result.direction).toBe('buy')
  })

  it('keeps a strong new attention entry observable without a history-length multiplier', () => {
    const result = analyzeRankResonance({
      percentiles: [95],
      sampleQuality: { status: 'insufficient' },
      marketMedianShortChange: 0,
      marketSampleCount: 20,
      jump: { direction: 'hold', event: 'none', events: [] },
      entry: { isNew: true, currentAttentionPercentile: 95 },
    })

    expect(result).toMatchObject({
      status: 'ok',
      direction: 'buy',
      score: 70,
      historyState: 'new_entry',
    })
  })

  it('returns insufficient hold without a complete current frame or valid market cross-section', () => {
    const result = analyzeRankResonance({
      percentiles: [42, 51, 63],
      sampleQuality: { ...quality, status: 'insufficient' },
      marketMedianShortChange: 12,
      jump: { direction: 'hold', event: 'none', events: [] },
      marketSampleCount: 19,
    })

    expect(result).toMatchObject({
      status: 'insufficient',
      direction: 'hold',
      score: 0,
      label: '样本不足',
    })
  })
})
