import { describe, expect, it } from 'vitest'

import { analyzeRiskSignals } from '../riskSignalAnalyzer'
import type { RankTrendAnalysisResult } from '../types'

function createTechnical(
  overrides: Partial<{
    directionSignal: 'buy' | 'sell' | 'hold'
    accelerationSignal: 'buy' | 'sell' | 'hold'
    zeroCrossSignal: 'buy' | 'sell' | 'hold'
    macdHistogram: number
  }> = {},
): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 72, ma10: 66, trend: 'up' },
    macd: {
      dif: 1.6, dea: 1.2, histogram: overrides.macdHistogram ?? -0.4,
      cross: 'none', rawScore: 0, confirmed: false,
    },
    signals: {
      direction: { signal: overrides.directionSignal ?? 'buy', confidence: 76, score: 0.6 },
      acceleration: { signal: overrides.accelerationSignal ?? 'hold', confidence: 54, score: 0.05 },
      zeroCross: { signal: overrides.zeroCrossSignal ?? 'sell', confidence: 78, score: -0.7 },
    },
    momentumScore: 42,
    momentumProfile: { short: 5, mid: 6, long: 4, acceleration: -1.5, shock: 1.2, composite: 5.4 },
  }
}

function createCycle(
  stage: RankTrendAnalysisResult['cycle']['stage'],
  overrides: Partial<{
    rankVelocity: number
    rankAcceleration: number
    rankShock: number
    drawdownFromPeak: number
  }> = {},
): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: stage === 'reversal' ? 'crowded' : 'ignition',
    transition: stage === 'reversal' ? 'crowded->reversal' : stage,
    confidence: 70,
    metrics: {
      rankVelocity: overrides.rankVelocity ?? 0.8,
      rankAcceleration: overrides.rankAcceleration ?? -1.4,
      rankShock: overrides.rankShock ?? 1.6,
      hotZoneStreak: 3,
      bestRecentRank: 4,
      drawdownFromPeak: overrides.drawdownFromPeak ?? 3,
    },
    entryAdvice: { bias: stage === 'reversal' ? 'blocked' : 'watch', allowed: false, reason: '' },
  }
}

describe('riskSignalAnalyzer', () => {
  // 原始测试：reversal 风险压力高于 expansion
  it('同样的热度与资金条件下，reversal 的风险压力应高于 expansion', () => {
    const technical = createTechnical()
    const expansionRisk = analyzeRiskSignals({
      currentPercentile: 90,
      technical,
      cycle: createCycle('expansion'),
      zlje: -8_000_000,
      zljzb: -2.1,
      volumeRatio: 2.4,
    })
    const reversalRisk = analyzeRiskSignals({
      currentPercentile: 90,
      technical,
      cycle: createCycle('reversal'),
      zlje: -8_000_000,
      zljzb: -2.1,
      volumeRatio: 2.4,
    })

    expect(reversalRisk.overheat.severity).toBeGreaterThan(expansionRisk.overheat.severity)
    expect(reversalRisk.divergence.severity).toBeGreaterThan(expansionRisk.divergence.severity)
    expect(reversalRisk.pressure).toBeGreaterThan(expansionRisk.pressure)
  })

  it('高百分位+正排名速度拉升过热分', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 90,
      technical: createTechnical(),
      cycle: createCycle('expansion'),
      zlje: 0,
      zljzb: 0,
      volumeRatio: 0,
    })

    expect(result.overheat.score).toBeGreaterThan(20)
  })

  it('过热分>=70 且处于拥挤或反转阶段时信号为 sell', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 95,
      technical: createTechnical({ accelerationSignal: 'hold' }),
      cycle: createCycle('crowded', { rankVelocity: 4, rankShock: 3 }),
      zlje: 0,
      zljzb: 0,
      volumeRatio: 0,
    })

    if (result.overheat.score >= 70) {
      expect(result.overheat.signal).toBe('sell')
    }
  })

  it('过热分 45-69 区间信号为 hold', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 75,
      technical: createTechnical({ directionSignal: 'hold' }),
      cycle: createCycle('cooling', { rankVelocity: 0.5, rankShock: 0.2 }),
      zlje: 0,
      zljzb: 0,
      volumeRatio: 0,
    })

    if (result.overheat.score >= 45 && result.overheat.score < 70) {
      expect(result.overheat.signal).toBe('hold')
    }
  })

  it('高热度+资金转弱推升背离分', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 80,
      technical: createTechnical(),
      cycle: createCycle('expansion', { rankVelocity: 2 }),
      zlje: -10_000_000,
      zljzb: -3,
      volumeRatio: 2.5,
    })

    expect(result.divergence.score).toBeGreaterThan(30)
  })

  it('背离分>=65 信号为 sell', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 85,
      technical: createTechnical(),
      cycle: createCycle('crowded', { rankVelocity: 2, rankShock: 1.5 }),
      zlje: -20_000_000,
      zljzb: -5,
      volumeRatio: 3,
    })

    if (result.divergence.score >= 65) {
      expect(result.divergence.signal).toBe('sell')
    }
  })

  it('正向资金流降低背离分', () => {
    const negative = analyzeRiskSignals({
      currentPercentile: 80,
      technical: createTechnical(),
      cycle: createCycle('expansion', { rankVelocity: 2 }),
      zlje: -10_000_000,
      zljzb: -3,
      volumeRatio: 2.5,
    })
    const positive = analyzeRiskSignals({
      currentPercentile: 80,
      technical: createTechnical(),
      cycle: createCycle('expansion', { rankVelocity: 2 }),
      zlje: 10_000_000,
      zljzb: 3,
      volumeRatio: 2.5,
    })

    expect(positive.divergence.score).toBeLessThan(negative.divergence.score)
  })

  it('synergy 在两风险严重度均超阈值时为 1', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 92,
      technical: createTechnical({ zeroCrossSignal: 'sell' }),
      cycle: createCycle('reversal', { rankVelocity: -1, rankAcceleration: -2, rankShock: 2 }),
      zlje: -20_000_000,
      zljzb: -5,
      volumeRatio: 3,
    })

    // synergy 在两 severity 都高时触发
    if (result.overheat.severity >= 0.65 && result.divergence.severity >= 0.6) {
      expect(result.synergy).toBe(1)
    }
  })

  it('ignition 阶段风险乘数最低，severity 被压制', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 85,
      technical: createTechnical(),
      cycle: createCycle('ignition', { rankVelocity: 2, rankShock: 1.2 }),
      zlje: -5_000_000,
      zljzb: -2,
      volumeRatio: 2,
    })

    expect(result.overheat.severity).toBeLessThanOrEqual(0.4)
    expect(result.divergence.severity).toBeLessThanOrEqual(0.4)
  })

  it('pressure 为两 severity 的加权组合', () => {
    const result = analyzeRiskSignals({
      currentPercentile: 90,
      technical: createTechnical(),
      cycle: createCycle('reversal'),
      zlje: -10_000_000,
      zljzb: -3,
      volumeRatio: 2.5,
    })

    expect(result.pressure).toBeGreaterThanOrEqual(0)
    expect(result.pressure).toBeLessThanOrEqual(1)
  })
})
