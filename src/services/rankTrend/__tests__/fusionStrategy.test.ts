import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

import { isFusionEntryCandidate } from '../fusionStrategy'
import type { RankTrendAnalysisResult } from '../types'
import { V5_FUSION_DEFAULTS } from '../v5FusionExecutionContract'

const contractFixture = JSON.parse(
  readFileSync(
    resolve(process.cwd(), 'quant-board/tests/fixtures/ranktrend_v5_live_execution_contract.json'),
    'utf-8',
  ),
) as {
  defaultMinJumpConfidence: number
  cases: Array<{
    name: string
    expectedEntry: boolean
    signal: Record<string, unknown>
  }>
}

function createRankTrend(overrides: Partial<RankTrendAnalysisResult> = {}): RankTrendAnalysisResult {
  return {
    meta: {
      code: '000001',
      currentRank: 1,
      currentPercentile: 99,
      change: 3.2,
      rawChange: 3.2,
      updateTime: Date.now(),
      sampleQuality: {
        snapshotType: 'half_hour',
        sampleCount: 30,
        requiredSampleCount: 30,
        status: 'ok',
        delayedCount: 0,
        restoredCount: 0,
      },
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
        rankPathCommitment: 4,
      },
      entryAdvice: {
        bias: 'preferred',
        allowed: true,
        reason: 'ok',
      },
      decision: {
        action: 'allow',
        confidence: 85,
        reasons: [],
        discovery: {
          action: 'none',
          reasons: [],
        },
        evidence: {
          rawStage: 'expansion',
          stage: 'expansion',
          transition: 'ignition_to_expansion',
          rankVelocity: 10,
          rankAcceleration: 4,
          drawdownFromPeak: 0,
          hotZoneStreak: 3,
          rankPathCommitment: 4,
          momentumShort: 12,
          momentumMid: 18,
          momentumLong: 11,
          momentumAcceleration: 12,
          riskPressure: 0.2,
          divergenceSeverity: 0,
          overheatSeverity: 0,
        },
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
    executionStrategy: {
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
    accDelta: 8,
    rankTrend: {
      ...createRankTrend(),
      jump: { direction: 'buy', confidence: 92 },
    },
    ...overrides,
  }
}

describe('isFusionEntryCandidate', () => {
  it('使用 rankTrendDefaults 中的 fusion jump 默认阈值', () => {
    expect(V5_FUSION_DEFAULTS.minJumpConfidence).toBe(90)
  })

  it('A_MAIN 满足基础门槛且 lifecycle 未 veto 时返回 true', () => {
    const stock = createStock()

    expect(isFusionEntryCandidate(stock)).toBe(true)
  })

  it('jump confidence 为 79.8 时低于 V5 默认门槛，不允许自动入池', () => {
    const stock = createStock({
      rankTrend: {
        ...createRankTrend(),
        jump: { direction: 'buy', confidence: 79.8 },
      },
    })

    expect(isFusionEntryCandidate(stock)).toBe(false)
  })

  it('lifecycle action = veto 时直接返回 false', () => {
    const stock = createStock({
      rankTrend: createRankTrend({
        strategy: {
          ...createRankTrend().strategy!,
          candidateTier: 'A_MAIN',
        },
        cycle: {
          ...createRankTrend().cycle,
          decision: {
            ...createRankTrend().cycle.decision,
            action: 'veto',
          },
        },
        jump: { direction: 'buy', confidence: 95 },
      }),
    })

    expect(isFusionEntryCandidate(stock)).toBe(false)
  })

  it('sampleQuality insufficient 时不会自动入池', () => {
    const stock = createStock({
      rankTrend: createRankTrend({
        meta: {
          ...createRankTrend().meta,
          sampleQuality: {
            snapshotType: 'half_hour',
            sampleCount: 6,
            requiredSampleCount: 10,
            status: 'insufficient',
            coverageWarning: '样本不足，已回退 half_hour',
            delayedCount: 1,
            restoredCount: 0,
          },
        },
        jump: { direction: 'buy', confidence: 95 },
      }),
    })

    expect(isFusionEntryCandidate(stock)).toBe(false)
  })

  it('live gate 优先使用 executionStrategy 分层，不被展示分层 N_NEUTRAL 错杀', () => {
    const displayStrategy = createRankTrend().strategy!
    const stock = createStock({
      rankTrend: {
        ...createRankTrend({
          strategy: {
            ...displayStrategy,
            candidateTier: 'N_NEUTRAL',
            action: 'hold',
          },
        }),
        executionStrategy: {
          ...displayStrategy,
          candidateTier: 'A_MAIN',
          action: 'focus',
        },
        jump: { direction: 'buy', confidence: 92 },
      },
    })

    expect(isFusionEntryCandidate(stock)).toBe(true)
  })

  it('live gate 优先使用 executionStrategy 分层，execution 非 A/B 时即使展示分层 A_MAIN 也不入池', () => {
    const displayStrategy = createRankTrend().strategy!
    const stock = createStock({
      rankTrend: {
        ...createRankTrend({
          strategy: {
            ...displayStrategy,
            candidateTier: 'A_MAIN',
            action: 'focus',
          },
        }),
        executionStrategy: {
          ...displayStrategy,
          candidateTier: 'N_NEUTRAL',
          action: 'hold',
        },
        jump: { direction: 'buy', confidence: 92 },
      },
    })

    expect(isFusionEntryCandidate(stock)).toBe(false)
  })

  it('V5 live gate 缺少 executionStrategy 时不会回退使用展示分层入池', () => {
    const rankTrend = createRankTrend({
      strategy: {
        ...createRankTrend().strategy!,
        candidateTier: 'A_MAIN',
        action: 'focus',
      },
      executionStrategy: undefined,
      jump: { direction: 'buy', confidence: 92 },
    })
    const stock = createStock({ rankTrend })

    expect(isFusionEntryCandidate(stock)).toBe(false)
  })
})

describe('V5 live execution contract fixture', () => {
  it('与 QuantBoard Python V5 fixture 使用同一默认 JumpConfidence', () => {
    expect(V5_FUSION_DEFAULTS.minJumpConfidence).toBe(contractFixture.defaultMinJumpConfidence)
  })

  it.each(contractFixture.cases)('$name', ({ signal, expectedEntry }) => {
    expect(isFusionEntryCandidate(signal)).toBe(expectedEntry)
  })
})
