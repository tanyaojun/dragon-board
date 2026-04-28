import { describe, expect, it } from 'vitest'

import { cloneDefaultRankTrendRuntimeConfig } from '../../../type/rankTrendDefaults'
import { composeDecision } from '../resultComposer'
import type { RankTrendAnalysisResult } from '../types'

function createTechnical(): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 80, ma10: 74, trend: 'up' },
    macd: { dif: 1.2, dea: 0.7, histogram: 1, cross: 'golden', rawScore: 0.7, confirmed: true },
    signals: {
      direction: { signal: 'buy', confidence: 80, score: 0.7 },
      acceleration: { signal: 'buy', confidence: 76, score: 0.5 },
      zeroCross: { signal: 'hold', confidence: 50, score: 0 },
    },
    momentumScore: 62,
    momentumProfile: { short: 6, mid: 7, long: 4, acceleration: 2, shock: 0.8, composite: 6.5 },
  }
}

function createCycle(stage: RankTrendAnalysisResult['cycle']['stage']): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: stage === 'reversal' ? 'crowded' : 'ignition',
    transition: stage === 'reversal' ? 'crowded->reversal' : 'ignition->expansion',
    confidence: 78,
    metrics: {
      rankVelocity: 1.5,
      rankAcceleration: 0.3,
      rankShock: 0.8,
      hotZoneStreak: 1,
      bestRecentRank: 7,
      drawdownFromPeak: 0,
    },
    entryAdvice: {
      bias: stage === 'reversal' ? 'blocked' : 'preferred',
      allowed: stage !== 'reversal',
      reason: '',
    },
  }
}

describe('resultComposer', () => {
  it('高风险会压低最终置信度，但不改变基础合成方向', () => {
    const technical = createTechnical()
    const config = cloneDefaultRankTrendRuntimeConfig()

    const lowRisk = composeDecision({
      technical,
      cycle: createCycle('expansion'),
      risk: {
        overheat: { score: 30, signal: 'buy', severity: 0.1 },
        divergence: { score: 20, signal: 'buy', severity: 0.05 },
        pressure: 0.08,
        synergy: 0,
      },
      config,
    })

    const highRisk = composeDecision({
      technical,
      cycle: createCycle('reversal'),
      risk: {
        overheat: { score: 82, signal: 'sell', severity: 0.8 },
        divergence: { score: 75, signal: 'sell', severity: 0.7 },
        pressure: 0.82,
        synergy: 1,
      },
      config,
    })

    expect(lowRisk.base.signal).toBe('buy')
    expect(highRisk.base.signal).toBe('buy')
    expect(highRisk.final.confidence).toBeLessThan(lowRisk.final.confidence)
  })
})
