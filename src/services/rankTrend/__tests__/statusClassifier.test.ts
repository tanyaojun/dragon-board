import { describe, expect, it } from 'vitest'

import { buildRankTrendStatusContext, getRankTrendDisplayStatus } from '../statusClassifier'
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
        { turnover: 100, volumeRatio: 1.6, turnoverRate: 5, zlje: 6.8e8, zljzb: 21, cddje: 2.3e8, cddjzb: 7 },
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

  it('样本不足但强资金且成交额和量比有承接时映射为强资确认', () => {
    const target = {
      turnover: 100,
      volumeRatio: 1.6,
      turnoverRate: 5,
      zlje: 6.8e8,
      zljzb: 21,
      cddje: 2.3e8,
      cddjzb: 7,
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      target,
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      { turnover: 400, volumeRatio: 3, turnoverRate: 12 },
    ])

    const status = getRankTrendDisplayStatus(
      createRankTrend({ sampleStatus: 'insufficient', percentile: 40, change: 0 }),
      target,
      context,
    )

    expect(status.label).toBe('强资确认')
    expect(status.tooltip).toContain('趋势持续性仍需后续快照确认')
  })

  it('样本不足且强资金但高涨幅爆量时仍为强资确认并提示风险', () => {
    const target = {
      change: 10,
      turnover: 400,
      volumeRatio: 3.5,
      turnoverRate: 15,
      zlje: 6.8e8,
      zljzb: 21,
      cddje: 2.3e8,
      cddjzb: 7,
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      { turnover: 100, volumeRatio: 1.4, turnoverRate: 6 },
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      target,
    ])

    const status = getRankTrendDisplayStatus(createRankTrend({ sampleStatus: 'insufficient' }), target, context)

    expect(status.label).toBe('强资确认')
    expect(status.tooltip).toContain('量能偏热')
    expect(status.tooltip).toContain('不能直接视为主升确认')
  })

  it('点火观察且量能健康时保持点火观察并提示量能配合', () => {
    const target = {
      turnover: 100,
      volumeRatio: 1.6,
      turnoverRate: 5,
      zlje: 1,
      zljzb: 2,
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      target,
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      { turnover: 400, volumeRatio: 3, turnoverRate: 12 },
    ])

    const status = getRankTrendDisplayStatus(createRankTrend({ tier: 'B_IGNITION' }), target, context)

    expect(status.label).toBe('点火观察')
    expect(status.tooltip).toContain('量能配合较好')
  })

  it('主升确认但量能过热且主力转弱时降为资金背离', () => {
    const target = {
      compRank: 10,
      change: 10,
      turnover: 400,
      volumeRatio: 3.5,
      turnoverRate: 15,
      zlje: -1,
      zljzb: -5,
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      { turnover: 100, volumeRatio: 1.4, turnoverRate: 6 },
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      target,
    ])

    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), target, context).label).toBe('资金背离')
  })

  it('TDX估算资金小幅转弱时不直接降为资金背离', () => {
    const target = {
      compRank: 10,
      turnover: 100,
      volumeRatio: 1.6,
      turnoverRate: 5,
      zlje: -1e7,
      zljzb: -5,
      cddje: 2e6,
      cddjzb: 1,
      moneyFlowEstimated: true,
      moneyFlowSource: 'tdx_estimate',
    }

    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), target).label).toBe('主升确认')
  })

  it('TDX估算资金需要主力占比和超大单同时恶化才触发资金背离', () => {
    const target = {
      compRank: 10,
      turnover: 400,
      volumeRatio: 3.5,
      turnoverRate: 15,
      zlje: -1e8,
      zljzb: -12,
      cddje: -3e7,
      cddjzb: -5,
      moneyFlowEstimated: true,
      moneyFlowSource: 'tdx_estimate',
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      { turnover: 100, volumeRatio: 1.4, turnoverRate: 6 },
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      target,
    ])

    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), target, context).label).toBe('资金背离')
  })

  it('显式无效行情优先显示样本不足，不误判为转弱预警', () => {
    const status = getRankTrendDisplayStatus(createRankTrend({ tier: 'D_EXIT_RISK' }), {
      price: 0,
      turnover: 0,
      compRank: 20,
      zlje: -1e8,
      zljzb: -20,
      cddje: -3e7,
      cddjzb: -8,
    })

    expect(status.label).toBe('样本不足')
    expect(status.tooltip).toContain('行情价格或成交额无效')
  })

  it('有效价格但成交额缺失时不参与状态分层', () => {
    expect(
      getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), {
        price: 12.3,
        turnover: 0,
        zlje: 1e8,
        zljzb: 12,
        cddje: 3e7,
        cddjzb: 4,
      }).label,
    ).toBe('样本不足')
  })

  it('主升确认但量能过热且主力不弱时降为高位拥挤', () => {
    const target = {
      change: 10,
      turnover: 400,
      volumeRatio: 3.5,
      turnoverRate: 15,
      zlje: 1,
      zljzb: 2,
    }
    const context = buildRankTrendStatusContext([
      { turnover: 10, volumeRatio: 0.6, turnoverRate: 2 },
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      { turnover: 100, volumeRatio: 1.4, turnoverRate: 6 },
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      target,
    ])

    expect(getRankTrendDisplayStatus(createRankTrend({ tier: 'A_MAIN' }), target, context).label).toBe('高位拥挤')
  })

  it('样本不足且资金不强量能偏弱时保持样本不足', () => {
    const target = {
      compRank: 120,
      turnover: 10,
      volumeRatio: 0.6,
      turnoverRate: 2,
      zlje: 0,
      zljzb: 0,
    }
    const context = buildRankTrendStatusContext([
      target,
      { turnover: 50, volumeRatio: 1, turnoverRate: 4 },
      { turnover: 100, volumeRatio: 1.4, turnoverRate: 6 },
      { turnover: 200, volumeRatio: 2, turnoverRate: 8 },
      { turnover: 400, volumeRatio: 3, turnoverRate: 12 },
    ])

    expect(
      getRankTrendDisplayStatus(
        createRankTrend({ sampleStatus: 'insufficient', percentile: 20, change: 0 }),
        target,
        context,
      ).label,
    ).toBe('样本不足')
  })

  it('没有热榜横截面 context 时使用 fallback 且不抛错', () => {
    expect(() =>
      getRankTrendDisplayStatus(createRankTrend({ sampleStatus: 'insufficient' }), {
        turnover: 100,
        volumeRatio: 1.6,
        turnoverRate: 5,
        zlje: 1,
        zljzb: 2,
      }),
    ).not.toThrow()
  })
})
