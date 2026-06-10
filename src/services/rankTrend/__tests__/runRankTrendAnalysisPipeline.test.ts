import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { RankTrendAnalysisResult } from '../types'

const mockStocks = [
  {
    code: '600001',
    name: '测试样本',
    change: 2.4,
    turnover: 8.6e8,
    turnoverRate: 4.2,
    volumeRatio: 1.8,
    zlje: 1.2e7,
    zljzb: 3.1,
    cddje: 0,
    cddjzb: 0,
    price: 12.3,
    platforms: 4,
    avgRankNum: 12,
    compRank: 15,
  },
]

function buildReplayStocks(rank: number, overrides: Record<string, unknown> = {}, total = 100) {
  const rows = Array.from({ length: total }, (_, index) => ({
    code: `FILL${String(index + 1).padStart(3, '0')}`,
    name: `填充${index + 1}`,
    rank: index + 1,
    price: 10 + index,
  }))

  rows[rank - 1] = {
    code: '600001',
    name: '测试样本',
    rank,
    price: 12.3,
    change: 2.4,
    volumeRatio: 1.8,
    zlje: 12000000,
    zljzb: 3.1,
    ...overrides,
  }

  return rows
}

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: () => mockStocks,
    getStock: (code: string) => mockStocks.find((stock) => stock.code === code) || null,
    getBreathData: () => ({
      overall: 58,
      marketData: { ztCount: 52, dtCount: 3, upCount: 3100, downCount: 1800, totalAmo: 1.1e12 },
      passRate: { to2: 42 },
      timestamp: 1,
    }),
  },
}))

vi.mock('../../dataLoader', () => ({
  dataLoader: {
    updateStockSignals: vi.fn(),
  },
}))

vi.mock('../../apiService', () => ({
  apiService: {
    getRankTrendRankSeries: vi.fn(),
  },
}))

vi.mock('../../../utils/eventManager', () => ({
  EventManager: {
    on: vi.fn(() => vi.fn()),
  },
}))

vi.mock('@/utils/logger', () => ({
  debugLog: vi.fn(),
}))

const technicalResult: RankTrendAnalysisResult['technical'] = {
  movingAverage: { ma5: 80, ma10: 76, trend: 'up' },
  macd: {
    dif: 1.2,
    dea: 0.8,
    histogram: 0.4,
    cross: 'golden',
    rawScore: 0.7,
    confirmed: true,
  },
  signals: {
    direction: { signal: 'buy', confidence: 80, score: 0.7 },
    acceleration: { signal: 'buy', confidence: 72, score: 0.45 },
    zeroCross: { signal: 'hold', confidence: 50, score: 0 },
  },
  momentumScore: 61,
  momentumProfile: {
    short: 8,
    mid: 6,
    long: 4,
    acceleration: 2,
    shock: 1,
    composite: 6.5,
  },
}

const initialCycle: RankTrendAnalysisResult['cycle'] = {
  rawStage: 'expansion',
  stage: 'expansion',
  previousStage: 'ignition',
  transition: 'ignition->expansion',
  confidence: 76,
  metrics: {
    rankVelocity: 1.5,
    rankAcceleration: 0.3,
    rankShock: 0.5,
    hotZoneStreak: 1,
    bestRecentRank: 12,
    drawdownFromPeak: 0,
    rankPathCommitment: 0.72,
  },
  entryAdvice: {
    bias: 'preferred',
    allowed: true,
    reason: 'initial',
  },
  decision: {
    action: 'allow',
    confidence: 74,
    reasons: ['initial'],
    discovery: {
      action: 'none',
      reasons: [],
    },
    evidence: {
      rawStage: 'expansion',
      stage: 'expansion',
      transition: 'ignition->expansion',
      rankVelocity: 1.5,
      rankAcceleration: 0.3,
      drawdownFromPeak: 0,
      hotZoneStreak: 1,
      rankPathCommitment: 0.72,
      momentumShort: 8,
      momentumMid: 6,
      momentumLong: 4,
      momentumAcceleration: 2,
      riskPressure: 0,
      divergenceSeverity: 0,
      overheatSeverity: 0,
    },
  },
}

const refinedCycle: RankTrendAnalysisResult['cycle'] = {
  ...initialCycle,
  stage: 'reversal',
  transition: 'expansion->reversal',
  entryAdvice: {
    bias: 'blocked',
    allowed: false,
    reason: 'refined',
  },
  decision: {
    ...initialCycle.decision,
    action: 'veto',
    reasons: ['refined'],
    evidence: {
      ...initialCycle.decision.evidence,
      stage: 'reversal',
      transition: 'expansion->reversal',
      riskPressure: 0.81,
      divergenceSeverity: 0.67,
      overheatSeverity: 0.74,
    },
  },
}

const riskResult: RankTrendAnalysisResult['risk'] = {
  overheat: { score: 0.74, signal: 'sell', severity: 0.74 },
  divergence: { score: 0.67, signal: 'sell', severity: 0.67 },
  pressure: 0.81,
  synergy: 1,
}

const decisionResult: RankTrendAnalysisResult['decision'] = {
  base: {
    signal: 'buy',
    confidence: 71,
    combinedScore: 0.21,
    scoreMargin: 0.09,
  },
  final: {
    signal: 'hold',
    confidence: 58,
  },
}

const strategyResult = {
  regime: {
    state: 'normal',
    score: 0.4,
    reasons: ['stable'],
  },
  momentum: technicalResult.momentumProfile,
  candidateTier: 'D_EXIT_RISK' as const,
  action: 'avoid' as const,
  reasons: ['refined-cycle'],
}

const hotlistSentiment = {
  phaseName: '发酵',
  riskLevel: '中',
  confidence: 82,
}

const executionStrategyResult = {
  ...strategyResult,
  hotlist: {
    state: 'present' as const,
    stage: '发酵',
    riskLevel: '中',
    confidence: 82,
  },
  candidateTier: 'A_MAIN' as const,
  action: 'focus' as const,
  reasons: ['execution-tier'],
}

const technicalCalls = vi.fn()
const fallbackTechnicalCalls = vi.fn()
const cycleCalls = vi.fn()
const riskCalls = vi.fn()
const decisionCalls = vi.fn()
const strategyCalls = vi.fn()
const executionStrategyCalls = vi.fn()
const minSamplesCalls = vi.fn()
const marketRegimeCalls = vi.fn()

vi.mock('@/services/rankTrend/technicalSignalAnalyzer', () => ({
  analyzeTechnicalSignals: vi.fn((percentiles: number[]) => {
    technicalCalls(percentiles)
    return technicalResult
  }),
  analyzeFallbackTechnicalSignals: vi.fn((input: unknown) => {
    fallbackTechnicalCalls(input)
    return technicalResult
  }),
}))

vi.mock('@/services/rankTrend/attentionCycleAnalyzer', () => ({
  analyzeAttentionCycle: vi.fn((input: { risk?: unknown }) => {
    cycleCalls(input)
    return input.risk ? refinedCycle : initialCycle
  }),
}))

vi.mock('@/services/rankTrend/riskSignalAnalyzer', () => ({
  analyzeRiskSignals: vi.fn((input: unknown) => {
    riskCalls(input)
    return riskResult
  }),
}))

vi.mock('@/services/rankTrend/resultComposer', () => ({
  composeDecision: vi.fn((input: unknown) => {
    decisionCalls(input)
    return decisionResult
  }),
}))

vi.mock('@/services/rankTrend/candidateTierComposer', () => ({
  composeCandidateTier: vi.fn((input: unknown) => {
    strategyCalls(input)
    return strategyResult
  }),
}))

vi.mock('@/services/rankTrend/executionCandidateTierComposer', () => ({
  composeExecutionCandidateTier: vi.fn((input: unknown) => {
    executionStrategyCalls(input)
    return executionStrategyResult
  }),
}))

vi.mock('@/services/rankTrend/marketRegimeAnalyzer', () => ({
  analyzeMarketRegime: vi.fn((input: unknown) => {
    marketRegimeCalls(input)
    return strategyResult.regime
  }),
}))

vi.mock('@/services/rankTrend/utils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../utils')>()
  return {
    ...actual,
    getTechnicalMinSamples: vi.fn(() => {
      minSamplesCalls()
      return 5
    }),
  }
})

describe('runRankTrendAnalysisPipeline', () => {
  beforeEach(() => {
    technicalCalls.mockClear()
    fallbackTechnicalCalls.mockClear()
    cycleCalls.mockClear()
    riskCalls.mockClear()
    decisionCalls.mockClear()
    strategyCalls.mockClear()
    executionStrategyCalls.mockClear()
    minSamplesCalls.mockClear()
    marketRegimeCalls.mockClear()
  })

  it('按 shared pipeline 顺序执行并把 risk 回灌给第二次 cycle', async () => {
    const { runRankTrendAnalysisPipeline } = await import('../runRankTrendAnalysisPipeline')

    const result = runRankTrendAnalysisPipeline({
      ranks: [35, 21, 12],
      percentiles: [65, 79, 88],
      currentPercentile: 88,
      displayChange: 9,
      stockChange: 5.2,
      volumeRatio: 2.1,
      zlje: 12000000,
      zljzb: 14.2,
      regime: strategyResult.regime,
      hotlistSentiment,
      config: {
        momentumPeriods: [5, 10, 20],
        momentumWeights: [0.5, 0.3, 0.2],
        buyThresholds: [70, 80, 90],
        sellThresholds: [30, 20, 10],
        macdFast: 12,
        macdSlow: 26,
        macdSignal: 9,
        directionWeight: 0.3,
        accelerationWeight: 0.25,
        crossWeight: 0.2,
        macdWeight: 0.25,
        buyScoreThreshold: 0.12,
        sellScoreThreshold: -0.12,
      },
      requiredSamples: 3,
    })

    expect(technicalCalls).toHaveBeenCalledTimes(1)
    expect(fallbackTechnicalCalls).not.toHaveBeenCalled()
    expect(cycleCalls).toHaveBeenCalledTimes(2)
    expect(riskCalls).toHaveBeenCalledTimes(1)
    expect(decisionCalls).toHaveBeenCalledTimes(1)
    expect(strategyCalls).toHaveBeenCalledTimes(1)
    expect(executionStrategyCalls).toHaveBeenCalledTimes(1)

    expect(cycleCalls.mock.calls[0]?.[0]).toMatchObject({
      ranks: [35, 21, 12],
      percentiles: [65, 79, 88],
      momentumProfile: technicalResult.momentumProfile,
    })
    expect(cycleCalls.mock.calls[1]?.[0]).toMatchObject({
      ranks: [35, 21, 12],
      percentiles: [65, 79, 88],
      momentumProfile: technicalResult.momentumProfile,
      risk: {
        pressure: riskResult.pressure,
        divergenceSeverity: riskResult.divergence.severity,
        overheatSeverity: riskResult.overheat.severity,
      },
    })
    expect(riskCalls.mock.calls[0]?.[0]).toMatchObject({
      currentPercentile: 88,
      technical: technicalResult,
      cycle: initialCycle,
      zlje: 12000000,
      zljzb: 14.2,
      volumeRatio: 2.1,
    })
    expect(decisionCalls.mock.calls[0]?.[0]).toMatchObject({
      technical: technicalResult,
      cycle: refinedCycle,
      risk: riskResult,
    })
    expect(strategyCalls.mock.calls[0]?.[0]).toMatchObject({
      technical: technicalResult,
      cycle: refinedCycle,
      risk: riskResult,
      regime: strategyResult.regime,
    })
    expect(executionStrategyCalls.mock.calls[0]?.[0]).toMatchObject({
      technical: technicalResult,
      cycle: refinedCycle,
      risk: riskResult,
      regime: strategyResult.regime,
      hotlistSentiment,
    })

    expect(result).toEqual({
      technical: technicalResult,
      cycle: refinedCycle,
      risk: riskResult,
      decision: decisionResult,
      strategy: strategyResult,
      executionStrategy: executionStrategyResult,
    })
  })

  it('样本不足时走 fallback technical 但仍保持共享顺序', async () => {
    const { runRankTrendAnalysisPipeline } = await import('../runRankTrendAnalysisPipeline')

    runRankTrendAnalysisPipeline({
      ranks: [28, 18, 11],
      percentiles: [71, 82, 91],
      currentPercentile: 91,
      displayChange: 7,
      stockChange: 3.6,
      volumeRatio: 1.8,
      zlje: 8000000,
      zljzb: 10.5,
      regime: strategyResult.regime,
      config: {
        momentumPeriods: [5, 10, 20],
        momentumWeights: [0.5, 0.3, 0.2],
        buyThresholds: [70, 80, 90],
        sellThresholds: [30, 20, 10],
        macdFast: 12,
        macdSlow: 26,
        macdSignal: 9,
        directionWeight: 0.3,
        accelerationWeight: 0.25,
        crossWeight: 0.2,
        macdWeight: 0.25,
        buyScoreThreshold: 0.12,
        sellScoreThreshold: -0.12,
      },
      requiredSamples: 6,
    })

    expect(technicalCalls).not.toHaveBeenCalled()
    expect(fallbackTechnicalCalls).toHaveBeenCalledTimes(1)
    expect(cycleCalls).toHaveBeenCalledTimes(2)
    expect(riskCalls).toHaveBeenCalledTimes(1)
    expect(decisionCalls).toHaveBeenCalledTimes(1)
    expect(strategyCalls).toHaveBeenCalledTimes(1)
    expect(minSamplesCalls).not.toHaveBeenCalled()
  })

  it('未显式传 requiredSamples 时会回退到 getTechnicalMinSamples(config)', async () => {
    const { runRankTrendAnalysisPipeline } = await import('../runRankTrendAnalysisPipeline')

    runRankTrendAnalysisPipeline({
      ranks: [31, 18, 9],
      percentiles: [69, 82, 91],
      currentPercentile: 91,
      displayChange: 6,
      stockChange: 2.8,
      volumeRatio: 1.6,
      zlje: 6000000,
      zljzb: 8.4,
      regime: strategyResult.regime,
      config: {
        momentumPeriods: [5, 10, 20],
        momentumWeights: [0.5, 0.3, 0.2],
        buyThresholds: [70, 80, 90],
        sellThresholds: [30, 20, 10],
        macdFast: 12,
        macdSlow: 26,
        macdSignal: 9,
        directionWeight: 0.3,
        accelerationWeight: 0.25,
        crossWeight: 0.2,
        macdWeight: 0.25,
        buyScoreThreshold: 0.12,
        sellScoreThreshold: -0.12,
      },
    })

    expect(minSamplesCalls).toHaveBeenCalledTimes(1)
    expect(technicalCalls).not.toHaveBeenCalled()
    expect(fallbackTechnicalCalls).toHaveBeenCalledTimes(1)
    expect(cycleCalls).toHaveBeenCalledTimes(2)
  })
})

describe('shared pipeline consumers', () => {
  beforeEach(() => {
    marketRegimeCalls.mockClear()
  })

  it('RankTrendAnalyzer 通过共享 helper 产出结果', async () => {
    vi.resetModules()

    const pipelineSpy = vi.fn(() => ({
      technical: {
        ...technicalResult,
        movingAverage: {
          ...technicalResult.movingAverage,
          ma5: 123.45,
        },
      },
      cycle: {
        ...refinedCycle,
        stage: 'reversal' as const,
      },
      risk: riskResult,
      decision: {
        ...decisionResult,
        final: {
          signal: 'hold' as const,
          confidence: 57,
        },
      },
      strategy: {
        ...strategyResult,
        candidateTier: 'D_EXIT_RISK' as const,
        action: 'avoid' as const,
      },
      executionStrategy: {
        ...executionStrategyResult,
        candidateTier: 'A_MAIN' as const,
        action: 'focus' as const,
      },
    }))

    vi.doMock('@/services/rankTrend/runRankTrendAnalysisPipeline', () => ({
      runRankTrendAnalysisPipeline: pipelineSpy,
    }))

    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const rankMap = new Map<string, number>(
      Array.from({ length: 100 }, (_, index) => [
        index === 32 ? '600001' : `FILL${String(index + 1).padStart(3, '0')}`,
        index + 1,
      ]),
    )
    const snapshots = [
      { date: '2026-04-27 09:30', timestamp: Date.parse('2026-04-27T09:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '09:30', hotlist: [{ code: '600001', rank: 78 }], totalCount: 100 } },
      { date: '2026-04-27 10:00', timestamp: Date.parse('2026-04-27T10:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:00', hotlist: [{ code: '600001', rank: 66 }], totalCount: 100 } },
      { date: '2026-04-27 10:30', timestamp: Date.parse('2026-04-27T10:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:30', hotlist: [{ code: '600001', rank: 58 }], totalCount: 100 } },
      { date: '2026-04-27 11:00', timestamp: Date.parse('2026-04-27T11:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '11:00', hotlist: [{ code: '600001', rank: 49 }], totalCount: 100 } },
      { date: '2026-04-27 13:30', timestamp: Date.parse('2026-04-27T13:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '13:30', hotlist: [{ code: '600001', rank: 42 }], totalCount: 100 } },
      { date: '2026-04-27 14:00', timestamp: Date.parse('2026-04-27T14:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '14:00', hotlist: [{ code: '600001', rank: 36 }], totalCount: 100 } },
    ]

    const results = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
      preferredSnapshotType: 'half_hour',
      snapshots,
    })

    expect(pipelineSpy).toHaveBeenCalledTimes(1)
    expect(pipelineSpy.mock.calls[0]?.[0]).toMatchObject({
      ranks: [78, 66, 58, 49, 42, 36, 33],
      percentiles: [23, 35, 43, 52, 59, 65, 68],
      currentPercentile: 68,
      requiredSamples: 5,
      regime: strategyResult.regime,
      hotlistSentiment: {
        overall: 58,
        marketData: { ztCount: 52, dtCount: 3, upCount: 3100, downCount: 1800, totalAmo: 1.1e12 },
        passRate: { to2: 42 },
        timestamp: 1,
      },
    })
    expect(marketRegimeCalls).toHaveBeenCalled()
    expect(results.get('600001')).toMatchObject({
      ma5: 123.45,
      finalSignal: 'hold',
      finalConfidence: 57,
      cycle: {
        stage: 'reversal',
      },
      strategy: {
        candidateTier: 'D_EXIT_RISK',
        action: 'avoid',
      },
      executionStrategy: {
        candidateTier: 'A_MAIN',
        action: 'focus',
      },
    })

    rankTrendAnalyzer.stop()
  })

  it('RankTrendGoldenReplayEngine 通过共享 helper 产出信号', async () => {
    vi.resetModules()

    const pipelineSpy = vi.fn(() => ({
      technical: technicalResult,
      cycle: {
        ...refinedCycle,
        stage: 'reversal' as const,
      },
      risk: riskResult,
      decision: {
        ...decisionResult,
        final: {
          signal: 'hold' as const,
          confidence: 61,
        },
      },
      strategy: {
        ...strategyResult,
        candidateTier: 'C_CROWDED' as const,
        action: 'hold' as const,
      },
      executionStrategy: {
        ...executionStrategyResult,
        candidateTier: 'A_MAIN' as const,
        action: 'focus' as const,
      },
    }))

    vi.doMock('@/services/rankTrend/runRankTrendAnalysisPipeline', () => ({
      runRankTrendAnalysisPipeline: pipelineSpy,
    }))

    const { RankTrendGoldenReplayEngine } = await import('../../quantBoardGolden/RankTrendGoldenReplayEngine')
    const engine = new RankTrendGoldenReplayEngine()
    const frames = [
      {
        snapshotId: 'snap-1',
        timestamp: Date.parse('2026-04-27T09:30:00'),
        tradingDate: '2026-04-27',
        slotTime: '09:30',
        type: 'half_hour',
        stocks: buildReplayStocks(78, { change: 2.1, volumeRatio: 1.6, zlje: 10000000, zljzb: 2.8 }),
        marketContext: {
          payload: {},
          marketStats: {},
          limitSummary: {},
          sentiment: { phaseName: '发酵', riskLevel: '中', confidence: 82 },
          moneyFlow: {},
          indices: {},
          rotationSummary: {},
        },
      },
      {
        snapshotId: 'snap-2',
        timestamp: Date.parse('2026-04-27T10:00:00'),
        tradingDate: '2026-04-27',
        slotTime: '10:00',
        type: 'half_hour',
        stocks: buildReplayStocks(33, { price: 13.1, change: 3.4, volumeRatio: 2.2, zlje: 12000000, zljzb: 3.6 }),
        marketContext: {
          payload: {},
          marketStats: {},
          limitSummary: {},
          sentiment: { phaseName: '高潮', riskLevel: '中', confidence: 88 },
          moneyFlow: {},
          indices: {},
          rotationSummary: {},
        },
      },
    ]

    const signals = engine.replayFrameAt(frames as any, 1, {
      meta: {
        sampleQuality: 'ok',
        warnings: [],
        delayedCount: 0,
        restoredCount: 0,
      },
    })

    expect(pipelineSpy).toHaveBeenCalledTimes(100)
    const targetCall = pipelineSpy.mock.calls
      .map((args) => args[0])
      .find((input) => input.stockChange === 3.4)
    expect(targetCall).toMatchObject({
      ranks: [78, 33],
      percentiles: [23, 68],
      currentPercentile: 68,
      regime: strategyResult.regime,
      hotlistSentiment: { phaseName: '高潮', riskLevel: '中', confidence: 88 },
    })
    expect(marketRegimeCalls).toHaveBeenCalled()
    const targetSignal = signals.find((signal) => signal.code === '600001')
    expect(targetSignal).toMatchObject({
      candidateTier: 'C_CROWDED',
      action: 'hold',
      stage: 'reversal',
      confidence: 61,
      rankTrend: {
        strategy: {
          candidateTier: 'C_CROWDED',
        },
        executionStrategy: {
          candidateTier: 'A_MAIN',
        },
        decision: {
          final: {
            confidence: 61,
          },
        },
      },
    })
  })
})
