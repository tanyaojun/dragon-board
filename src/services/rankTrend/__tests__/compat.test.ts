import { describe, expect, it } from 'vitest'

import { getRankTrendDisplayStatus } from '../compat'
import type { RankTrendAnalysisResult } from '../types'

function createRankTrend(input: {
  tier?: NonNullable<RankTrendAnalysisResult['strategy']>['candidateTier']
  sampleStatus?: NonNullable<RankTrendAnalysisResult['meta']['sampleQuality']>['status']
  percentile?: number
  change?: number
}): RankTrendAnalysisResult {
  const tier = input.tier ?? 'N_NEUTRAL'
  return {
    meta: {
      code: '300001',
      currentRank: 18,
      currentPercentile: input.percentile ?? 80,
      change: input.change ?? 3,
      rawChange: 0,
      updateTime: 1,
      sampleQuality: {
        snapshotType: 'half_hour',
        sampleCount: input.sampleStatus === 'insufficient' ? 3 : 30,
        requiredSampleCount: 30,
        status: input.sampleStatus ?? 'ok',
        delayedCount: 0,
        restoredCount: 0,
      },
    },
    technical: {
      movingAverage: { ma5: 0, ma10: 0, trend: 'steady' },
      macd: { dif: 0, dea: 0, histogram: 0, cross: 'none', rawScore: 0, confirmed: false },
      signals: {
        direction: { signal: 'hold', confidence: 50, score: 0 },
        acceleration: { signal: 'hold', confidence: 50, score: 0 },
        zeroCross: { signal: 'hold', confidence: 50, score: 0 },
      },
      momentumScore: 0,
      momentumProfile: { short: 0, mid: 0, long: 0, acceleration: 0, shock: 0, composite: 0 },
    },
    cycle: {
      rawStage: 'cooling',
      stage: 'cooling',
      previousStage: null,
      transition: 'cooling',
      confidence: 50,
      metrics: {
        rankVelocity: 0,
        rankAcceleration: 0,
        rankShock: 0,
        hotZoneStreak: 0,
        bestRecentRank: 18,
        drawdownFromPeak: 0,
      },
      entryAdvice: { bias: 'watch', allowed: false, reason: '' },
    },
    risk: {
      overheat: { score: 0, signal: 'hold', severity: 0 },
      divergence: { score: 0, signal: 'hold', severity: 0 },
      pressure: 0,
      synergy: 0,
    },
    decision: {
      base: { signal: 'hold', confidence: 50, combinedScore: 0, scoreMargin: 0 },
      final: { signal: 'hold', confidence: 50 },
    },
    strategy: {
      regime: { state: 'normal', score: 55, reasons: [] },
      momentum: { short: 0, mid: 0, long: 0, acceleration: 0, shock: 0, composite: 0 },
      candidateTier: tier,
      action: 'hold',
      reasons: [],
    },
  }
}

describe('getRankTrendDisplayStatus', () => {
  it('把候选池和资金质量映射成主表状态', () => {
    expect(
      getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), { zlje: 1, zljzb: 2 }).label,
    ).toBe('主升确认')
    expect(
      getRankTrendDisplayStatus(createRankTrend({ tier: 'B_IGNITION' }), { zlje: 1, zljzb: 2 }).label,
    ).toBe('点火观察')
    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'C_CROWDED' }), {}).label).toBe('高位拥挤')
    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'D_EXIT_RISK' }), {}).label).toBe('转弱预警')
    expect(
      getRankTrendDisplayStatus(
        createRankTrend({ sampleStatus: 'insufficient' }),
        { zlje: 6.8e8, zljzb: 21, cddje: 2.3e8, cddjzb: 7 },
      ).label,
    ).toBe('强资确认')
    expect(
      getRankTrendDisplayStatus(createRankTrend({ sampleStatus: 'insufficient', change: 5 }), {
        compRank: 30,
        zlje: 0,
        zljzb: 0,
      }).label,
    ).toBe('新入观察')
    expect(
      getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), {
        compRank: 18,
        zlje: -1,
        zljzb: -5,
      }).label,
    ).toBe('资金背离')
    expect(getRankTrendDisplayStatus(null, {}).label).toBe('样本不足')
  })
})
