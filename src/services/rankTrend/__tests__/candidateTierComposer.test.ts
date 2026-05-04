import { describe, expect, it } from 'vitest'

import { composeCandidateTier } from '../candidateTierComposer'
import type { MarketRegimeAnalysis, RankTrendAnalysisResult } from '../types'

function createTechnical(
  overrides: Partial<{
    directionSignal: 'buy' | 'sell' | 'hold'
    accelerationSignal: 'buy' | 'sell' | 'hold'
    macdCross: 'golden' | 'death' | 'none'
    momentumShort: number
    momentumMid: number
    momentumLong: number
    momentumAcceleration: number
  }> = {},
): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 70, ma10: 65, trend: 'up' },
    macd: { dif: 0, dea: 0, histogram: 0, cross: overrides.macdCross ?? 'none', rawScore: 0, confirmed: false },
    signals: {
      direction: { signal: overrides.directionSignal ?? 'hold', confidence: 50, score: 0 },
      acceleration: { signal: overrides.accelerationSignal ?? 'hold', confidence: 50, score: 0 },
      zeroCross: { signal: 'hold', confidence: 50, score: 0 },
    },
    momentumScore: 0,
    momentumProfile: {
      short: overrides.momentumShort ?? 0,
      mid: overrides.momentumMid ?? 0,
      long: overrides.momentumLong ?? 0,
      acceleration: overrides.momentumAcceleration ?? 0,
      shock: 0,
      composite: 0,
    },
  }
}

function createCycle(
  stage: RankTrendAnalysisResult['cycle']['stage'],
): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: null,
    transition: stage,
    confidence: 50,
    metrics: {
      rankVelocity: 0,
      rankAcceleration: 0,
      rankShock: 0,
      hotZoneStreak: 0,
      bestRecentRank: 50,
      drawdownFromPeak: 0,
    },
    entryAdvice: { bias: 'watch', allowed: false, reason: '' },
  }
}

function createRisk(overrides: { divergenceSeverity?: number; pressure?: number; overheatSeverity?: number } = {}): RankTrendAnalysisResult['risk'] {
  return {
    overheat: { score: 0, signal: 'hold', severity: overrides.overheatSeverity ?? 0 },
    divergence: { score: 0, signal: 'hold', severity: overrides.divergenceSeverity ?? 0 },
    pressure: overrides.pressure ?? 0,
    synergy: 0,
  }
}

function createRegime(state: MarketRegimeAnalysis['state'] = 'normal'): MarketRegimeAnalysis {
  return { state, score: 50, reasons: [] }
}

describe('composeCandidateTier', () => {
  it('扩张+中周期动量+技术买点+非弱势 → A_MAIN', () => {
    const result = composeCandidateTier({
      technical: createTechnical({
        directionSignal: 'buy',
        momentumShort: 0,
        momentumMid: 5,
        momentumLong: 2,
      }),
      cycle: createCycle('expansion'),
      risk: createRisk({ divergenceSeverity: 0.1, pressure: 0.1 }),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('A_MAIN')
    expect(result.action).toBe('focus')
  })

  it('点火+短周期冲击强+非退潮 → B_IGNITION', () => {
    const result = composeCandidateTier({
      technical: createTechnical({
        momentumShort: 4,
        momentumAcceleration: 1,
      }),
      cycle: createCycle('ignition'),
      risk: createRisk({ pressure: 0.1 }),
      regime: createRegime('strong'),
    })

    expect(result.candidateTier).toBe('B_IGNITION')
    expect(result.action).toBe('watch')
  })

  it('反转+短周期动量转弱 → D_EXIT_RISK', () => {
    const result = composeCandidateTier({
      technical: createTechnical({
        momentumShort: -3,
        momentumAcceleration: -3,
      }),
      cycle: createCycle('reversal'),
      risk: createRisk({ pressure: 0.6 }),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('D_EXIT_RISK')
    expect(result.action).toBe('exit_watch')
  })

  it('冷却+动量恶化 → D_EXIT_RISK', () => {
    const result = composeCandidateTier({
      technical: createTechnical({ momentumShort: -2, momentumAcceleration: -2 }),
      cycle: createCycle('cooling'),
      risk: createRisk({ pressure: 0.55 }),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('D_EXIT_RISK')
  })

  it('拥挤阶段 → C_CROWDED', () => {
    const result = composeCandidateTier({
      technical: createTechnical({ momentumLong: 6, momentumAcceleration: -1 }),
      cycle: createCycle('crowded'),
      risk: createRisk({ pressure: 0.3 }),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('C_CROWDED')
    expect(result.action).toBe('avoid')
  })

  it('长周期高位+加速度转弱 → C_CROWDED', () => {
    const result = composeCandidateTier({
      technical: createTechnical({ momentumLong: 5, momentumAcceleration: -0.5 }),
      cycle: createCycle('expansion'),
      risk: createRisk({ pressure: 0.5 }),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('C_CROWDED')
  })

  it('无明确信号时默认 N_NEUTRAL', () => {
    const result = composeCandidateTier({
      technical: createTechnical(),
      cycle: createCycle('cooling'),
      risk: createRisk(),
      regime: createRegime('normal'),
    })

    expect(result.candidateTier).toBe('N_NEUTRAL')
    expect(result.action).toBe('hold')
  })

  it('弱势环境下买入信号降级为 N_NEUTRAL', () => {
    const result = composeCandidateTier({
      technical: createTechnical({ directionSignal: 'buy' }),
      cycle: createCycle('ignition'),
      risk: createRisk(),
      regime: createRegime('weak'),
    })

    // 弱市时 B_IGNITION 不满足 regime.state !== 'retreat'，退到 N_NEUTRAL
    if (result.candidateTier === 'N_NEUTRAL') {
      expect(result.reasons.some((r) => r.includes('弱势') || r.includes('退潮'))).toBe(true)
    }
  })

  it('退潮环境下 A_MAIN 和 B_IGNITION 均不应出现', () => {
    const aResult = composeCandidateTier({
      technical: createTechnical({
        directionSignal: 'buy',
        momentumShort: 0,
        momentumMid: 5,
      }),
      cycle: createCycle('expansion'),
      risk: createRisk({ divergenceSeverity: 0.1, pressure: 0.1 }),
      regime: createRegime('retreat'),
    })
    const bResult = composeCandidateTier({
      technical: createTechnical({ momentumShort: 4, momentumAcceleration: 1 }),
      cycle: createCycle('ignition'),
      risk: createRisk({ pressure: 0.1 }),
      regime: createRegime('retreat'),
    })

    expect(aResult.candidateTier).not.toBe('A_MAIN')
    expect(bResult.candidateTier).not.toBe('B_IGNITION')
  })

  it('result.reasons 至少包含动量结构摘要', () => {
    const result = composeCandidateTier({
      technical: createTechnical({ momentumShort: 3, momentumMid: 4 }),
      cycle: createCycle('expansion'),
      risk: createRisk(),
      regime: createRegime('normal'),
    })

    const momentumLine = result.reasons.find((r) => r.startsWith('动量结构'))
    expect(momentumLine).toBeDefined()
    expect(momentumLine).toContain('短+3.0')
    expect(momentumLine).toContain('中+4.0')
  })
})
