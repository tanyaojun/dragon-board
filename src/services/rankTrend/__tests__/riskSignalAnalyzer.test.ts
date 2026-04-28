import { describe, expect, it } from 'vitest'

import { analyzeRiskSignals } from '../riskSignalAnalyzer'
import type { RankTrendAnalysisResult } from '../types'

function createTechnical(): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 72, ma10: 66, trend: 'up' },
    macd: { dif: 1.6, dea: 1.2, histogram: -0.4, cross: 'none', rawScore: 0, confirmed: false },
    signals: {
      direction: { signal: 'buy', confidence: 76, score: 0.6 },
      acceleration: { signal: 'hold', confidence: 54, score: 0.05 },
      zeroCross: { signal: 'sell', confidence: 78, score: -0.7 },
    },
    momentumScore: 42,
    momentumProfile: { short: 5, mid: 6, long: 4, acceleration: -1.5, shock: 1.2, composite: 5.4 },
  }
}

function createCycle(stage: RankTrendAnalysisResult['cycle']['stage']): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: stage === 'reversal' ? 'crowded' : 'ignition',
    transition: stage === 'reversal' ? 'crowded->reversal' : stage,
    confidence: 70,
    metrics: {
      rankVelocity: 0.8,
      rankAcceleration: -1.4,
      rankShock: 1.6,
      hotZoneStreak: 3,
      bestRecentRank: 4,
      drawdownFromPeak: 3,
    },
    entryAdvice: {
      bias: stage === 'reversal' ? 'blocked' : 'watch',
      allowed: false,
      reason: '',
    },
  }
}

describe('riskSignalAnalyzer', () => {
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
})
