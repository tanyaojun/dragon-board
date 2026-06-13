import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../DataLayer'
import { RankTrendSignalService } from '../RankTrendSignalService'

let emittedEvents = 0

vi.mock('../../RankTrendAnalyzer', () => ({
  rankTrendAnalyzer: {
    getRankTrends: vi.fn(),
    getCachedPercentiles: vi.fn().mockReturnValue(null),
  },
}))

vi.mock('../../rankTrend/FusionCandidateNotifier', () => ({
  fusionCandidateNotifier: {
    process: vi.fn(),
  },
}))

vi.mock('../../rankTrend/FusionStrategyProjector', () => ({
  buildFusionStrategyProjection: vi.fn((input: any) => ({
    stockCode: input.stock.code,
    stockName: input.stock.name || input.stock.code,
    strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
    snapshotType: input.snapshotType,
    tradingDate: input.tradingDate,
    snapshotId: input.snapshotId,
    frameTime: input.frameTime,
    projectionSource: 'live',
    strategyState: input.strategyLifecycle?.hasOpenPosition ? 'active_holding' : 'idle',
    candidateTier: 'A_MAIN',
    lifecycleAction: 'allow',
    executionOverlay: input.executionOverlay || null,
    entryDecision: {
      decisionState: 'blocked_candidate',
      label: '被阻断',
      summary: '当前实时门禁阻断',
      checks: [],
      configSnapshot: {},
    },
  })),
  buildFusionStrategyProjections: vi.fn(() => []),
}))

vi.mock('../../candidate/CandidateJournalService', () => ({
  candidateJournalService: {
    getExecutionOverlayMap: vi.fn(async () => ({})),
    getOpenCandidateMap: vi.fn(async () => ({})),
    toExecutionOverlay: vi.fn((entry: any) =>
      entry
        ? {
            executed: !!entry.entryTime,
            entryId: entry.id,
            entryTime: entry.entryTime || undefined,
          }
        : null,
    ),
  },
}))

vi.mock('../../rankTrend/JumpSignalNotifier', () => ({
  jumpSignalNotifier: {
    notifyEntry: vi.fn(),
    notifyExit: vi.fn(),
  },
}))

vi.mock('../../rankTrend/jumpSignalService', async () => {
  const actual = await vi.importActual<any>('../../rankTrend/jumpSignalService')
  return {
    ...actual,
    evaluateJumpSignal: vi.fn(() => ({
      jump: { event: 'jump', direction: 'buy', confidence: 92, sustained: true, magnitude: 20 },
      isEntry: true,
      isExit: false,
      exitReason: '',
    })),
  }
})

vi.mock('../../candidate/CandidatePoolStatusProjector', () => ({
  applyCandidatePoolProjections: vi.fn((stocks: any[], _projections: any[]) => stocks),
}))

vi.mock('@/utils/eventManager', () => ({
  EventManager: {
    emit: vi.fn(() => {
      emittedEvents++
    }),
  },
}))

describe('RankTrendSignalService', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    emittedEvents = 0
    vi.restoreAllMocks()
  })

  it('does not warn in console when the only sample quality issue is delayed snapshots', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
      new Map([
        [
          '000001',
          {
            meta: {
              sampleQuality: {
                coverageWarning: '包含 18 个 delayed 快照',
              },
            },
          } as any,
        ],
      ]),
    )
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged([{ code: '000001' }])

    expect(result[0].rankTrendCoverageWarning).toBe('包含 18 个 delayed 快照')
    expect(warnSpy).not.toHaveBeenCalled()
  })

  it('keeps existing RankTrend display fields when the analyzer returns no fresh result', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map())

    const existingRankTrend = {
      meta: {
        code: '000001',
        currentRank: 1,
        currentPercentile: 99,
        change: 12,
        rawChange: 12,
        updateTime: 1000,
      },
      technical: {},
      cycle: {},
      risk: {},
      decision: {
        final: {
          signal: 'buy',
          confidence: 78,
        },
      },
    } as any

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged([
      {
        code: '000001',
        rank: 1,
        rankTrend: existingRankTrend,
        rankChange: 12,
        finalSignal: 'buy',
        finalConfidence: 78,
      },
    ])

    expect(result[0].rankTrend).toStrictEqual(existingRankTrend)
    expect(result[0].rankChange).toBe(12)
    expect(result[0].finalSignal).toBe('buy')
    expect(result[0].finalConfidence).toBe(78)
  })

  it('can update stock signals without publishing UI events', () => {
    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])
    emittedEvents = 0

    const service = new RankTrendSignalService()
    const result = service.updateStockSignals(
      [{ code: '000001', rankTrend: null, coverageWarning: '样本不足' }],
      { publish: false },
    )

    expect(result).toEqual([
      expect.objectContaining({
        code: '000001',
        rankTrendCoverageWarning: '样本不足',
      }),
    ])
    expect(emittedEvents).toBe(0)
  })

  it('keeps existing RankTrend when a signal update has no fresh result', () => {
    const existingRankTrend = {
      meta: {
        code: '000001',
        change: 9,
      },
      technical: {},
      cycle: {},
      risk: {},
      decision: {
        final: {
          signal: 'buy',
          confidence: 81,
        },
      },
    } as any
    dataLayer.setMergedStocks([
      {
        code: '000001',
        name: '平安银行',
        rankTrend: existingRankTrend,
        rankChange: 9,
        finalSignal: 'buy',
        finalConfidence: 81,
      } as any,
    ])

    const service = new RankTrendSignalService()
    const result = service.updateStockSignals([
      { code: '000001', rankTrend: null, coverageWarning: '信号未刷新' },
    ])

    expect(result[0].rankTrend).toStrictEqual(existingRankTrend)
    expect(result[0].rankChange).toBe(9)
    expect(result[0].finalSignal).toBe('buy')
    expect(result[0].finalConfidence).toBe(81)
    expect(result[0].rankTrendCoverageWarning).toBe('信号未刷新')
  })

  it('keeps stock signal updates as calculation-only by default', () => {
    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])
    emittedEvents = 0

    const service = new RankTrendSignalService()
    service.updateStockSignals([{ code: '000001', rankTrend: null, coverageWarning: '样本不足' }])

    expect(emittedEvents).toBe(0)
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        rankTrendCoverageWarning: '样本不足',
      }),
    ])
  })

  it('refreshRankTrendSignals builds fusion projections after auto candidate processing', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
      new Map([
        [
          '000001',
          {
            meta: {
              code: '000001',
              currentRank: 1,
              currentPercentile: 99,
              change: 12,
              rawChange: 12,
              updateTime: 1,
              sampleQuality: {
                snapshotType: 'half_hour',
                sampleCount: 30,
                requiredSampleCount: 30,
                status: 'ok',
                delayedCount: 0,
                restoredCount: 0,
                latestTradingDate: '2026-06-08',
                latestSlotTime: '10:00',
              },
            },
            technical: {
              movingAverage: { ma5: 1, ma10: 1, trend: 'up' },
              macd: { dif: 1, dea: 1, histogram: 1, cross: 'golden', rawScore: 0.8, confirmed: true },
              signals: {
                direction: { signal: 'buy', confidence: 80, score: 0.6 },
                acceleration: { signal: 'buy', confidence: 80, score: 0.6 },
                zeroCross: { signal: 'hold', confidence: 50, score: 0 },
              },
              momentumScore: 80,
              momentumProfile: {
                short: 12,
                mid: 18,
                long: 11,
                acceleration: 12,
                shock: 2,
                composite: 70,
              },
            },
            cycle: {
              rawStage: 'expansion',
              stage: 'expansion',
              previousStage: 'ignition',
              transition: 'ignition->expansion',
              confidence: 80,
              metrics: {
                rankVelocity: 10,
                rankAcceleration: 4,
                rankShock: 2,
                hotZoneStreak: 2,
                bestRecentRank: 1,
                drawdownFromPeak: 0,
                rankPathCommitment: 0.8,
              },
              entryAdvice: { bias: 'preferred', allowed: true, reason: 'ok' },
              decision: {
                action: 'allow',
                confidence: 80,
                reasons: [],
                discovery: { action: 'none', reasons: [] },
                evidence: {
                  rawStage: 'expansion',
                  stage: 'expansion',
                  transition: 'ignition->expansion',
                  rankVelocity: 10,
                  rankAcceleration: 4,
                  drawdownFromPeak: 0,
                  hotZoneStreak: 2,
                  rankPathCommitment: 0.8,
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
              synergy: 0.6,
            },
            decision: {
              base: { signal: 'buy', confidence: 80, combinedScore: 0.8, scoreMargin: 0.2 },
              final: { signal: 'hold', confidence: 72 },
            },
            strategy: {
              regime: { state: 'strong', score: 80, reasons: [] },
              momentum: {
                short: 12,
                mid: 18,
                long: 11,
                acceleration: 12,
                shock: 2,
                composite: 70,
              },
              candidateTier: 'A_MAIN',
              action: 'focus',
              reasons: [],
            },
            jump: {
              direction: 'buy',
              confidence: 92,
            },
          } as any,
        ],
      ]),
    )

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34 } as any])

    const service = new RankTrendSignalService()
    const result = await service.refreshRankTrendSignals()

    const { fusionCandidateNotifier } = await import('../../rankTrend/FusionCandidateNotifier')
    const { buildFusionStrategyProjections } = await import('../../rankTrend/FusionStrategyProjector')
    const { applyCandidatePoolProjections } = await import('../../candidate/CandidatePoolStatusProjector')

    expect(fusionCandidateNotifier.process).toHaveBeenCalledWith(result)
    expect(buildFusionStrategyProjections).toHaveBeenCalledWith(result, expect.any(Object))
    expect(applyCandidatePoolProjections).toHaveBeenCalledWith(result, expect.any(Array))
    expect(result[0].liveV3SignalDecision).toBeUndefined()
  })

  it('syncs quote table candidate pool state from the persisted open candidate lifecycle', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { buildFusionStrategyProjections } = await import('../../rankTrend/FusionStrategyProjector')
    const { candidateJournalService } = await import('../../candidate/CandidateJournalService')
    const { applyCandidatePoolProjections } = await import('../../candidate/CandidatePoolStatusProjector')

    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map())
    vi.mocked(buildFusionStrategyProjections).mockReturnValue([
      {
        stockCode: '002129',
        stockName: 'TCL中环',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'half_hour',
        tradingDate: '2026-06-13',
        snapshotId: 'live:002129',
        frameTime: '2026-06-13T16:30:00+08:00',
        projectionSource: 'live',
        strategyState: 'idle',
        candidateTier: 'D_EXIT_RISK',
        lifecycleAction: 'veto',
        executionOverlay: null,
        entryDecision: {
          accepted: false,
          decisionState: 'blocked_candidate',
          label: '被阻断',
          summary: '当前实时门禁阻断',
          checks: [],
          configSnapshot: {} as any,
        },
      },
    ])
    vi.mocked(candidateJournalService.getOpenCandidateMap).mockResolvedValue({
      '002129': {
        id: 'tj_002129',
        stockCode: '002129',
        stockName: 'TCL中环',
        status: 'tracking',
        tradeType: 'thesis',
        entryReason: '',
        tradeHypothesis: '',
        entryPrerequisites: '',
        invalidationRules: '',
        humanDecision: 'watch',
        skipReason: '',
        reviewOutcome: 'pending',
        modelResult: 'unknown',
        executionResult: 'unknown',
        reviewNotes: '',
        reviewTags: [],
        signalsSnapshot: {
          rankTrend: {
            strategyLifecycle: {
              triggered: true,
              hasOpenPosition: true,
              triggerAt: '2026-06-12T15:00:00+08:00',
              entryAt: '2026-06-13T09:30:00+08:00',
            },
          },
        },
        entryTime: '2026-06-13T09:30:00+08:00',
        createdAt: '2026-06-12T15:00:00+08:00',
        updatedAt: '2026-06-13T09:30:00+08:00',
      },
    } as any)

    const service = new RankTrendSignalService()
    await service.applySignalsToMerged([{ code: '002129', name: 'TCL中环' }])

    expect(applyCandidatePoolProjections).toHaveBeenCalledWith(
      expect.any(Array),
      expect.arrayContaining([
        expect.objectContaining({
          stockCode: '002129',
          strategyState: 'active_holding',
        }),
      ]),
    )
  })

  it('refreshRankTrendSignals no longer invokes legacy jump notifier side effects', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { jumpSignalNotifier } = await import('../../rankTrend/JumpSignalNotifier')

    vi.mocked(rankTrendAnalyzer.getCachedPercentiles).mockReturnValueOnce({ latest: 1 } as any)
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
      new Map([
        [
          '000001',
          {
            meta: {
              code: '000001',
              currentRank: 1,
              currentPercentile: 99,
              change: 12,
              rawChange: 12,
              updateTime: 1,
              sampleQuality: {
                snapshotType: 'half_hour',
                sampleCount: 30,
                requiredSampleCount: 30,
                status: 'ok',
                delayedCount: 0,
                restoredCount: 0,
                latestTradingDate: '2026-06-08',
                latestSlotTime: '10:00',
              },
            },
            technical: {},
            cycle: {},
            risk: {},
            decision: {},
          } as any,
        ],
      ]),
    )

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34 } as any])

    const service = new RankTrendSignalService()
    await service.refreshRankTrendSignals()

    expect(jumpSignalNotifier.notifyEntry).not.toHaveBeenCalled()
    expect(jumpSignalNotifier.notifyExit).not.toHaveBeenCalled()
  })

  it('keeps RankTrend refresh usable when fusion auto-candidate creation fails', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { fusionCandidateNotifier } = await import('../../rankTrend/FusionCandidateNotifier')
    const { buildFusionStrategyProjections } = await import('../../rankTrend/FusionStrategyProjector')
    const { applyCandidatePoolProjections } = await import('../../candidate/CandidatePoolStatusProjector')

    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
      new Map([
        [
          '000001',
          {
            meta: {
              code: '000001',
              currentRank: 1,
              currentPercentile: 99,
              change: 12,
              rawChange: 12,
              updateTime: 1,
              sampleQuality: {
                snapshotType: 'half_hour',
                sampleCount: 30,
                requiredSampleCount: 30,
                status: 'ok',
                delayedCount: 0,
                restoredCount: 0,
                latestTradingDate: '2026-06-08',
                latestSlotTime: '10:00',
              },
            },
            technical: {},
            cycle: {},
            risk: {},
            decision: {},
          } as any,
        ],
      ]),
    )
    vi.mocked(fusionCandidateNotifier.process).mockRejectedValueOnce(new Error('journal down'))

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34 } as any])

    const service = new RankTrendSignalService()
    const result = await service.refreshRankTrendSignals()

    expect(result[0].rankTrend?.meta?.code).toBe('000001')
    expect(buildFusionStrategyProjections).toHaveBeenCalledWith(result, expect.any(Object))
    expect(applyCandidatePoolProjections).toHaveBeenCalledWith(result, expect.any(Array))
  })
})
