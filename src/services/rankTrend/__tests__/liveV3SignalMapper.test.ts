import { describe, expect, it } from 'vitest'

import { getLiveV3SignalDecision } from '../liveV3SignalMapper'
import type { RankTrendAnalysisResult } from '../types'

function createRankTrend(overrides: Partial<RankTrendAnalysisResult> = {}): RankTrendAnalysisResult {
  return {
    meta: {
      code: '000001',
      currentRank: 1,
      currentPercentile: 99,
      change: 12,
      rawChange: 12,
      updateTime: Date.now(),
    },
    technical: {
      movingAverage: {
        ma5: 10,
        ma10: 9,
        trend: 'up',
      },
      macd: {
        dif: 1,
        dea: 0.8,
        histogram: 0.2,
        cross: 'golden',
        rawScore: 0.7,
        confirmed: true,
      },
      signals: {
        direction: { signal: 'buy', confidence: 80, score: 0.6 },
        acceleration: { signal: 'buy', confidence: 78, score: 0.5 },
        zeroCross: { signal: 'hold', confidence: 50, score: 0 },
      },
      momentumScore: 78,
      momentumProfile: {
        short: 12,
        mid: 18,
        long: 11,
        acceleration: 12,
        shock: 2,
        composite: 75,
      },
    },
    cycle: {
      rawStage: 'expansion',
      stage: 'expansion',
      previousStage: 'ignition',
      transition: 'ignition_to_expansion',
      confidence: 80,
      metrics: {
        rankVelocity: 10,
        rankAcceleration: 4,
        rankShock: 2,
        hotZoneStreak: 3,
        bestRecentRank: 1,
        drawdownFromPeak: 0,
      },
      entryAdvice: {
        bias: 'preferred',
        allowed: true,
        reason: 'ok',
      },
    },
    risk: {
      overheat: { score: 0, signal: 'hold', severity: 0 },
      divergence: { score: 0, signal: 'hold', severity: 0 },
      pressure: 0.2,
      synergy: 0.7,
    },
    decision: {
      base: {
        signal: 'buy',
        confidence: 78,
        combinedScore: 0.8,
        scoreMargin: 0.2,
      },
      final: {
        signal: 'hold',
        confidence: 72,
      },
    },
    strategy: {
      regime: { state: 'strong', score: 80, reasons: [] },
      momentum: {
        short: 12,
        mid: 18,
        long: 11,
        acceleration: 12,
        shock: 2,
        composite: 75,
      },
      candidateTier: 'A_MAIN',
      action: 'focus',
      reasons: [],
    },
    ...overrides,
  } as RankTrendAnalysisResult
}

function createStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '000001',
    name: '平安银行',
    price: 12.34,
    change: 3.2,
    rankTrend: createRankTrend(),
    ...overrides,
  }
}

describe('getLiveV3SignalDecision', () => {
  it('命中 A_MAIN V3 入场条件时返回 A主升买点', () => {
    const stock = createStock({
      rankTrend: {
        ...createRankTrend(),
        jump: { direction: 'buy', confidence: 92 },
      },
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('A主升买点')
    expect(decision.tone).toBe('buy')
    expect(decision.degraded).toBe(false)
  })

  it('命中 B_IGNITION V3 入场条件时返回 B点火买点', () => {
    const stock = createStock({
      rankTrend: createRankTrend({
        technical: {
          ...createRankTrend().technical,
          signals: {
            ...createRankTrend().technical.signals,
            zeroCross: { signal: 'buy', confidence: 82, score: 0.7 },
          },
          momentumProfile: {
            ...createRankTrend().technical.momentumProfile,
            mid: 22,
          },
        },
        strategy: {
          ...createRankTrend().strategy!,
          candidateTier: 'B_IGNITION',
          action: 'watch',
        },
        jump: { direction: 'buy', confidence: 95 },
      }),
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('B点火买点')
    expect(decision.tone).toBe('buy')
  })

  it('rawChange 大跌且 MACD 死叉时返回 转弱卖出', () => {
    const stock = createStock({
      rankTrend: createRankTrend({
        meta: {
          ...createRankTrend().meta,
          rawChange: -55,
        },
        technical: {
          ...createRankTrend().technical,
          macd: {
            ...createRankTrend().technical.macd,
            cross: 'death',
          },
        },
      }),
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('转弱卖出')
    expect(decision.tone).toBe('sell')
  })

  it('同时命中 D_EXIT_RISK 和大跌死叉时会保留两类转弱依据', () => {
    const stock = createStock({
      rankTrend: createRankTrend({
        meta: {
          ...createRankTrend().meta,
          rawChange: -55,
        },
        technical: {
          ...createRankTrend().technical,
          macd: {
            ...createRankTrend().technical.macd,
            cross: 'death',
          },
        },
        strategy: {
          ...createRankTrend().strategy!,
          candidateTier: 'D_EXIT_RISK',
          action: 'exit_watch',
        },
      }),
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('转弱卖出')
    expect(decision.reasons).toContain('candidateTier = D_EXIT_RISK')
    expect(decision.reasons).toContain('MACD 死叉')
  })

  it('样本质量不足时不会继续给出动作信号', () => {
    const stock = createStock({
      rankTrend: {
        ...createRankTrend(),
        meta: {
          ...createRankTrend().meta,
          sampleQuality: {
            snapshotType: 'half_hour',
            sampleCount: 3,
            requiredSampleCount: 10,
            status: 'insufficient',
            delayedCount: 0,
            restoredCount: 0,
          },
        },
        jump: { direction: 'buy', confidence: 92 },
      },
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('无信号')
    expect(decision.tone).toBe('neutral')
    expect(decision.degraded).toBe(true)
    expect(decision.reasons[0]).toContain('样本质量不足')
  })

  it('样本降级但仍可判定时保留信号并标记为降级判断', () => {
    const stock = createStock({
      rankTrend: {
        ...createRankTrend(),
        meta: {
          ...createRankTrend().meta,
          sampleQuality: {
            snapshotType: 'half_hour',
            sampleCount: 6,
            requiredSampleCount: 10,
            status: 'degraded',
            coverageWarning: '样本不足，已回退 half_hour',
            delayedCount: 1,
            restoredCount: 0,
          },
        },
        jump: { direction: 'buy', confidence: 92 },
      },
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('A主升买点')
    expect(decision.degraded).toBe(true)
    expect(decision.degradedReason).toContain('样本降级')
  })

  it('仍是 A_MAIN 候选但未满足 V3 入场门槛时返回 持有观察', () => {
    const stock = createStock({
      rankTrend: {
        ...createRankTrend(),
        jump: { direction: 'buy', confidence: 80 },
      },
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('持有观察')
    expect(decision.tone).toBe('watch')
  })

  it('缺少 rankTrend 数据时返回 无信号', () => {
    const stock = createStock({
      rankTrend: undefined,
    })

    const decision = getLiveV3SignalDecision(stock)

    expect(decision.label).toBe('无信号')
    expect(decision.tone).toBe('neutral')
  })
})
