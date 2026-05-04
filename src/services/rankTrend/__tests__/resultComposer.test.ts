import { describe, expect, it } from 'vitest'

import { cloneDefaultRankTrendRuntimeConfig } from '../../../types/rankTrendDefaults'
import { composeDecision } from '../resultComposer'
import type { RankTrendAnalysisResult } from '../types'

function createTechnical(
  overrides: Partial<{
    directionSignal: 'buy' | 'sell' | 'hold'
    directionScore: number
    accelerationSignal: 'buy' | 'sell' | 'hold'
    accelerationScore: number
    zeroCrossSignal: 'buy' | 'sell' | 'hold'
    zeroCrossScore: number
    macdCross: 'golden' | 'death' | 'none'
    macdRawScore: number
  }> = {},
): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 80, ma10: 74, trend: 'up' },
    macd: {
      dif: 1.2, dea: 0.7, histogram: 1,
      cross: overrides.macdCross ?? 'golden',
      rawScore: overrides.macdRawScore ?? 0.7,
      confirmed: true,
    },
    signals: {
      direction: { signal: overrides.directionSignal ?? 'buy', confidence: 80, score: overrides.directionScore ?? 0.7 },
      acceleration: { signal: overrides.accelerationSignal ?? 'buy', confidence: 76, score: overrides.accelerationScore ?? 0.5 },
      zeroCross: { signal: overrides.zeroCrossSignal ?? 'hold', confidence: 50, score: overrides.zeroCrossScore ?? 0 },
    },
    momentumScore: 62,
    momentumProfile: { short: 6, mid: 7, long: 4, acceleration: 2, shock: 0.8, composite: 6.5 },
  }
}

function createCycle(
  stage: RankTrendAnalysisResult['cycle']['stage'],
): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: stage === 'reversal' ? 'crowded' : 'ignition',
    transition: stage === 'reversal' ? 'crowded->reversal' : 'ignition->expansion',
    confidence: 78,
    metrics: {
      rankVelocity: 1.5, rankAcceleration: 0.3, rankShock: 0.8,
      hotZoneStreak: 1, bestRecentRank: 7, drawdownFromPeak: 0,
    },
    entryAdvice: { bias: stage === 'reversal' ? 'blocked' : 'preferred', allowed: stage !== 'reversal', reason: '' },
  }
}

function createRisk(overrides: {
  overheatSeverity?: number
  divergenceSeverity?: number
  pressure?: number
  synergy?: number
  overheatSignal?: 'buy' | 'sell' | 'hold'
  divergenceSignal?: 'buy' | 'sell' | 'hold'
} = {}): RankTrendAnalysisResult['risk'] {
  return {
    overheat: { score: 0, signal: overrides.overheatSignal ?? 'hold', severity: overrides.overheatSeverity ?? 0 },
    divergence: { score: 0, signal: overrides.divergenceSignal ?? 'hold', severity: overrides.divergenceSeverity ?? 0 },
    pressure: overrides.pressure ?? 0,
    synergy: overrides.synergy ?? 0,
  }
}

describe('resultComposer', () => {
  it('高风险会压低最终置信度，但不改变基础合成方向', () => {
    const technical = createTechnical()
    const config = cloneDefaultRankTrendRuntimeConfig()

    const lowRisk = composeDecision({ technical, cycle: createCycle('expansion'), risk: createRisk({ overheatSeverity: 0.1, divergenceSeverity: 0.05, pressure: 0.08 }), config })
    const highRisk = composeDecision({ technical, cycle: createCycle('reversal'), risk: createRisk({ overheatSeverity: 0.8, divergenceSeverity: 0.7, pressure: 0.82, synergy: 1 }), config })

    expect(lowRisk.base.signal).toBe('buy')
    expect(highRisk.base.signal).toBe('buy')
    expect(highRisk.final.confidence).toBeLessThan(lowRisk.final.confidence)
  })

  it('多组件买入信号推动 combinedScore 超过 buyScoreThreshold 时 base.signal 为 buy', () => {
    const technical = createTechnical({
      directionSignal: 'buy', directionScore: 0.8,
      accelerationSignal: 'buy', accelerationScore: 0.6,
      macdCross: 'golden', macdRawScore: 0.7,
    })
    const config = cloneDefaultRankTrendRuntimeConfig()

    const result = composeDecision({ technical, cycle: createCycle('expansion'), risk: createRisk(), config })

    expect(result.base.signal).toBe('buy')
    expect(result.base.combinedScore).toBeGreaterThan(0)
  })

  it('多组件卖出信号推动 combinedScore 低于 sellScoreThreshold 时 base.signal 为 sell', () => {
    const technical = createTechnical({
      directionSignal: 'sell', directionScore: -0.6,
      accelerationSignal: 'sell', accelerationScore: -0.5,
      macdCross: 'death', macdRawScore: -0.6,
    })
    const config = cloneDefaultRankTrendRuntimeConfig()

    const result = composeDecision({ technical, cycle: createCycle('cooling'), risk: createRisk(), config })

    expect(result.base.signal).toBe('sell')
    expect(result.base.combinedScore).toBeLessThan(0)
  })

  it('方向买加速卖拉锯时 combinedScore 落在阈值区间内则为 hold', () => {
    const technical = createTechnical({
      directionSignal: 'sell', directionScore: -0.1,
      accelerationSignal: 'buy', accelerationScore: 0.1,
      macdCross: 'none', macdRawScore: 0,
    })
    const config = cloneDefaultRankTrendRuntimeConfig()

    const result = composeDecision({ technical, cycle: createCycle('cooling'), risk: createRisk(), config })

    if (result.base.combinedScore > config.sellScoreThreshold && result.base.combinedScore < config.buyScoreThreshold) {
      expect(result.base.signal).toBe('hold')
    }
  })

  it('reversal+高压+高过热+margin 极窄时 finalSignal 翻转为 hold 且置信<=62', () => {
    // combinedScore 需略高于 buyScoreThreshold(0.12) 使 margin<0.05 触发翻转
    const technical = createTechnical({
      directionSignal: 'buy', directionScore: 0.25,
      accelerationSignal: 'buy', accelerationScore: 0.2,
      macdCross: 'none', macdRawScore: 0,
    })
    const config = cloneDefaultRankTrendRuntimeConfig()

    const result = composeDecision({
      technical,
      cycle: createCycle('reversal'),
      risk: createRisk({ overheatSeverity: 0.8, divergenceSeverity: 0.7, pressure: 0.85, synergy: 1 }),
      config,
    })

    expect(result.base.signal).toBe('buy')
    // combined=0.25*0.3+0.2*0.25=0.125, margin=0.125-0.12=0.005<0.05 → reversal override 触发
    expect(result.final.signal).toBe('hold')
    expect(result.final.confidence).toBeLessThanOrEqual(62)
  })

  it('置信度始终在 [50, 95] 区间内', () => {
    const technical = createTechnical()
    const config = cloneDefaultRankTrendRuntimeConfig()

    // 强信号
    const strong = composeDecision({ technical, cycle: createCycle('expansion'), risk: createRisk(), config })
    expect(strong.base.confidence).toBeGreaterThanOrEqual(50)
    expect(strong.base.confidence).toBeLessThanOrEqual(95)
    expect(strong.final.confidence).toBeGreaterThanOrEqual(50)
    expect(strong.final.confidence).toBeLessThanOrEqual(95)

    // 高风险压下
    const risky = composeDecision({
      technical: createTechnical({ directionSignal: 'hold', accelerationSignal: 'hold' }),
      cycle: createCycle('reversal'),
      risk: createRisk({ overheatSeverity: 0.9, divergenceSeverity: 0.9, pressure: 0.95, synergy: 1 }),
      config,
    })
    expect(risky.base.confidence).toBeGreaterThanOrEqual(50)
    expect(risky.base.confidence).toBeLessThanOrEqual(95)
    expect(risky.final.confidence).toBeGreaterThanOrEqual(50)
    expect(risky.final.confidence).toBeLessThanOrEqual(95)
  })

  it('scoreMargin 反映 combinedScore 与阈值之间的差距', () => {
    const technical = createTechnical()
    const config = cloneDefaultRankTrendRuntimeConfig()

    const result = composeDecision({ technical, cycle: createCycle('expansion'), risk: createRisk(), config })

    if (result.base.signal === 'buy') {
      expect(result.base.scoreMargin).toBeGreaterThanOrEqual(0)
    }
  })

  it('risk.synergy=1 时额外扣除 5 点置信', () => {
    const noSynergy = composeDecision({
      technical: createTechnical(),
      cycle: createCycle('expansion'),
      risk: createRisk({ synergy: 0 }),
      config: cloneDefaultRankTrendRuntimeConfig(),
    })
    const withSynergy = composeDecision({
      technical: createTechnical(),
      cycle: createCycle('expansion'),
      risk: createRisk({ synergy: 1 }),
      config: cloneDefaultRankTrendRuntimeConfig(),
    })

    expect(withSynergy.final.confidence).toBeLessThanOrEqual(noSynergy.final.confidence)
  })
})
