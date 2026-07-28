import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../DataLayer'
import { RankTrendSignalService } from '../RankTrendSignalService'

let emittedEvents = 0

vi.mock('../../RankTrendAnalyzer', () => ({
  rankTrendAnalyzer: {
    getRankTrends: vi.fn(),
    getCachedPercentiles: vi.fn().mockReturnValue(null),
    getLatestAnalysisSeries: vi.fn().mockReturnValue(null),
    getLatestAnalysisFrameKeys: vi.fn().mockReturnValue([]),
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

vi.mock('../../candidate/TradingPoolAnalysisService', () => ({
  analyzeTradingPoolCandidate: vi.fn((input: any) => {
    const rows = (input.candidates || [])
      .concat(input.liveStocks || [])
      .map((stock: any) => ({
        code: stock.code,
        name: stock.name,
        status: '观察中' as const,
        decision: 'watch' as const,
        reasons: ['consensus_moderate'],
        signalSnapshot: {
          finalSignal: 'hold',
          finalConfidence: 72,
          jumpDirection: 'buy',
          directionSignal: 'buy',
          directionConfidence: 80,
          jumpConfidence: 92,
          macdCross: 'golden',
          accelerationSignal: 'buy',
          accelerationConfidence: 80,
          zeroCrossSignal: 'hold',
          zeroCrossConfidence: 50,
          buyVotes: 3,
          riskFlags: [],
          source: 'live_projection',
          limitUp: false,
          momentumSyncBroken: false,
          lifecycleAction: 'allow',
          dataQuality: 'fresh' as const,
        },
        scoringBreakdown: {
          totalScore: 20,
          discreteScore: 5,
          continuousScore: 15,
          discreteDetail: { macdCross: 3, jumpDirection: 2 },
          continuousDetail: {
            jumpConfidence: 4.6,
            finalConfidence: 3.6,
            directionConfidence: 4.0,
            accelerationConfidence: 4.0,
            zeroCrossConfidence: -1.2,
          },
        },
      }))
    return { rows, staleCount: 0, exitedCount: 0 }
  }),
  normalizeResonanceIntensity: vi.fn((totalScore: number) => {
    const pct = Math.max(0, Math.min(100, Math.round((totalScore / 30) * 100)))
    let label = '非常弱'
    if (pct >= 90) label = '非常强'
    else if (pct >= 67) label = '强'
    else if (pct >= 50) label = '中等'
    else if (pct >= 27) label = '较弱'
    return { pct, label }
  }),
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
    const result = await service.applySignalsToMerged([{ code: '000001', avgRankNum: 1 }])

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
        avgRankNum: 1,
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

  it('excludes stocks without a valid avgRankNum from the current attention ranking', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockImplementation(async (rankMap) => {
      expect(Array.from(rankMap.keys())).toEqual(['000001'])
      return new Map()
    })

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged([
      { code: '000001', name: '有效均榜', avgRankNum: 3 },
      { code: '000002', name: '零均榜', avgRankNum: 0, rankTrend: { stale: true } },
      { code: '000003', name: '缺失均榜', rankTrend: { stale: true } },
    ])

    expect(result[0].rank).toBe(1)
    expect(result[1]).toMatchObject({
      rank: undefined,
      rankTrend: undefined,
      finalSignal: 'hold',
      finalConfidence: 0,
      _resonancePct: undefined,
      _resonanceLabel: '样本不足',
    })
    expect(result[2].rankTrendCoverageWarning).toBe('均榜缺失')
  })

  it('can update stock signals without publishing UI events', () => {
    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', avgRankNum: 1 } as any])
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
    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', avgRankNum: 1 } as any])
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

  it('uses the current-frame analysis series when evaluating a jump signal', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { evaluateJumpSignal } = await import('../../rankTrend/jumpSignalService')
    const rankTrend = {
      meta: {
        code: '002298',
        currentRank: 11,
        currentPercentile: 95.2,
        change: 65.9,
        rawChange: 86,
        updateTime: 1,
      },
      technical: {},
      cycle: {},
      risk: {},
      decision: {},
    } as any

    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map([['002298', rankTrend]]))
    vi.mocked(rankTrendAnalyzer.getCachedPercentiles).mockReturnValue([58.8, 27.5, 29.3])
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisSeries).mockReturnValue({
      ranks: [97, 175, 165, 11],
      percentiles: [58.8, 27.5, 29.3, 95.2],
    })

    const service = new RankTrendSignalService()
    await service.applySignalsToMerged([{ code: '002298', name: '中电鑫龙', rank: 11, avgRankNum: 1 }])

    expect(evaluateJumpSignal).toHaveBeenCalledWith(
      expect.objectContaining({ code: '002298' }),
      rankTrend,
      [58.8, 27.5, 29.3, 95.2],
      true,
      [97, 175, 165, 11],
    )
  })

  it('writes one resonance final after the same-cycle jump pass', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const rankTrends = new Map(
      Array.from({ length: 20 }, (_, index) => {
        const code = index === 0 ? '002298' : String(600000 + index).padStart(6, '0')
        return [
          code,
          {
            meta: {
              code,
              currentRank: index + 1,
              currentPercentile: index === 0 ? 95.2 : 60,
              change: 0,
              rawChange: 0,
              updateTime: 1,
              sampleQuality: {
                snapshotType: 'half_hour',
                sampleCount: 9,
                requiredSampleCount: 9,
                status: 'ok',
                delayedCount: 0,
                restoredCount: 0,
              },
            },
            technical: {},
            cycle: {},
            risk: {},
            decision: { final: { signal: 'hold', confidence: 50 } },
          } as any,
        ]
      }),
    )
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(rankTrends as any)
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisFrameKeys).mockReturnValue([
      'H1',
      'H2',
      'H3',
      'H4',
      'H5',
      'S1',
      'S2',
      'S3',
      'CURRENT',
    ])
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisSeries).mockImplementation((code: string) => ({
      ranks: code === '002298'
        ? [150, 140, 130, 120, 110, 97, 175, 165, 11]
        : [140, 130, 120, 110, 100, 100, 90, 80, 70],
      percentiles: code === '002298'
        ? [30, 35, 40, 45, 50, 58.8, 27.5, 29.3, 95.2]
        : [25, 30, 35, 40, 45, 45, 50, 55, 60],
      frameKeys: ['H1', 'H2', 'H3', 'H4', 'H5', 'S1', 'S2', 'S3', 'CURRENT'],
    }))

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged(
      Array.from(rankTrends.keys()).map((code, index) => ({ code, name: code, avgRankNum: index + 1 })),
    )
    const target = result.find((stock) => stock.code === '002298')

    expect(target?.rankTrend.resonance).toMatchObject({ status: 'ok', direction: 'buy' })
    expect(target?.rankTrend.decision.final.signal).toBe('buy')
  })

  it('computes the market median only from stocks aligned to the same four market frames', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const rankTrends = new Map(
      Array.from({ length: 40 }, (_, index) => {
        const code = String(600000 + index).padStart(6, '0')
        return [
          code,
          {
            meta: {
              code,
              currentRank: index + 1,
              currentPercentile: 50,
              change: 0,
              rawChange: 0,
              updateTime: 1,
              sampleQuality: {
                snapshotType: 'half_hour',
                sampleCount: 4,
                requiredSampleCount: 4,
                status: 'ok',
                delayedCount: 0,
                restoredCount: 0,
              },
            },
            technical: {},
            cycle: {},
            risk: {},
            decision: { final: { signal: 'hold', confidence: 50 } },
          } as any,
        ]
      }),
    )
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(rankTrends as any)
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisFrameKeys).mockReturnValue([
      'S1',
      'S2',
      'S3',
      'CURRENT',
    ])
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisSeries).mockImplementation((code: string) => {
      const aligned = Number(code) < 600020
      return {
        ranks: [40, 35, 30, 25],
        percentiles: aligned ? [40, 45, 48, 50] : [100, 90, 80, 50],
        frameKeys: aligned ? ['S1', 'S2', 'S3', 'CURRENT'] : ['X1', 'X2', 'X3', 'CURRENT'],
      }
    })

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged(
      Array.from(rankTrends.keys()).map((code, index) => ({ code, name: code, avgRankNum: index + 1 })),
    )

    expect(result[0].rankTrend.resonance.marketMedianShortChange).toBe(10)
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

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34, avgRankNum: 1 } as any])

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
    await service.applySignalsToMerged([{ code: '002129', name: 'TCL中环', avgRankNum: 1 }])

    await vi.waitFor(() => expect(applyCandidatePoolProjections).toHaveBeenCalled())
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

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34, avgRankNum: 1 } as any])

    const service = new RankTrendSignalService()
    await service.refreshRankTrendSignals()

    expect(jumpSignalNotifier.notifyEntry).not.toHaveBeenCalled()
    expect(jumpSignalNotifier.notifyExit).not.toHaveBeenCalled()
  })

  describe('precomputeDisplayFields (via applySignalsToMerged)', () => {
    it('projects the unified resonance score instead of the trading-pool score', () => {
      const stock = {
        code: '002298',
        rankTrend: {
          meta: { change: 65.9 },
          jump: { direction: 'buy', confidence: 85 },
          resonance: { status: 'ok', direction: 'buy', score: 86, label: '非常强' },
          observation: {
            rankTrend: { direction: 'sell', score: 64, signedScore: -0.64 },
            lifecycle: {
              stage: 'expansion',
              score: 83,
              veto: false,
              reasons: [],
              factors: {
                stageFitness: 1,
                pathCommitment: 0.8,
                momentumConfirmation: 0.7,
                riskSafety: 0.75,
              },
            },
          },
        },
      }
      const service = new RankTrendSignalService()

      ;(service as any).precomputeDisplayFields([stock])

      expect(stock).toMatchObject({
        _resonancePct: 86,
        _resonanceRawScore: 86,
        _resonanceLabel: '非常强',
        _rankTrendPct: 64,
        _rankTrendDirection: 'sell',
        _lifecyclePct: 83,
        _lifecycleStage: 'expansion',
        _lifecycleVeto: false,
      })
    })

    it('sets _rankChange / _jumpConfidence / _jumpDirection when rankTrend is present', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
        new Map([
          [
            '000001',
            {
              meta: { code: '000001', currentRank: 1, currentPercentile: 99, change: 12, rawChange: 12, updateTime: 1, sampleQuality: { status: 'ok', sampleCount: 30, requiredSampleCount: 30, delayedCount: 0, restoredCount: 0 } },
              technical: {},
              cycle: {},
              risk: {},
              decision: { base: { signal: 'buy', confidence: 80 }, final: { signal: 'hold', confidence: 72 } },
              jump: { direction: 'buy', confidence: 92 },
            } as any,
          ],
        ]),
      )

      const service = new RankTrendSignalService()
      const result = await service.applySignalsToMerged([{ code: '000001', name: '平安银行', avgRankNum: 1 }])

      expect(result[0]._rankChange).toBe(12)
      expect(result[0]._jumpConfidence).toBe(92)
      expect(result[0]._jumpDirection).toBe('buy')
    })

    it('sets _rankChange to 0 and _jumpDirection to null when rankTrend is missing', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map())

      const service = new RankTrendSignalService()
      const result = await service.applySignalsToMerged([{ code: '000002', name: '测试股', avgRankNum: 1 }])

      expect(result[0]._rankChange).toBe(0)
      expect(result[0]._jumpConfidence).toBe(0)
      expect(result[0]._jumpDirection).toBeNull()
    })

    it('sets _resonancePct / _resonanceLabel when rankTrend is available for live stocks', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
        new Map([
          [
            '000001',
            {
              meta: { code: '000001', currentRank: 1, currentPercentile: 99, change: 5, rawChange: 5, updateTime: 1, sampleQuality: { status: 'ok', sampleCount: 30, requiredSampleCount: 30, delayedCount: 0, restoredCount: 0 } },
              technical: {},
              cycle: {},
              risk: {},
              decision: { final: { signal: 'buy', confidence: 78 } },
              jump: { direction: 'buy', confidence: 85 },
            } as any,
          ],
        ]),
      )

      const service = new RankTrendSignalService()
      const result = await service.applySignalsToMerged([{ code: '000001', name: '平安银行', avgRankNum: 1 }])

      expect(result[0]._resonancePct).toBeUndefined()
      expect(result[0]._resonanceLabel).toBe('样本不足')
      expect(result[0]._resonanceRawScore).toBeUndefined()
    })

    it('sets _resonancePct / _resonanceLabel for thesis candidates with candidatePoolProjection', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
        new Map([
          [
            '000003',
            {
              meta: { code: '000003', currentRank: 3, currentPercentile: 97, change: 8, rawChange: 8, updateTime: 1, sampleQuality: { status: 'ok', sampleCount: 30, requiredSampleCount: 30, delayedCount: 0, restoredCount: 0 } },
              technical: {},
              cycle: {},
              risk: {},
              decision: { final: { signal: 'buy', confidence: 82 } },
              jump: { direction: 'buy', confidence: 88 },
            } as any,
          ],
        ]),
      )

      const service = new RankTrendSignalService()
      const result = await service.applySignalsToMerged([
        {
          code: '000003',
          name: '候选股',
          avgRankNum: 1,
          candidatePoolEntryId: 'entry-3',
          candidatePoolProjection: {
            entryDecision: {
              decisionState: 'auto_add',
              label: '自动入池',
              summary: '全部门禁通过',
              checks: [],
              configSnapshot: { minJumpConfidence: 60 },
            },
          },
        },
      ])

      expect(result[0]._rankChange).toBe(8)
      expect(result[0]._jumpConfidence).toBe(88)
      expect(result[0]._resonancePct).toBeUndefined()
      expect(result[0]._resonanceLabel).toBe('样本不足')
    })

    it('handles empty stocks array without error', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map())

      const service = new RankTrendSignalService()
      // applySignalsToMerged 会调用 rankTrendAnalyzer.getRankTrends(new Map())
      // 空 map 也是合法的
      const result = await service.applySignalsToMerged([])

      expect(result).toEqual([])
    })

    it('shows an explicit insufficient resonance when no valid cross-section exists', async () => {
      const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
      vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(
        new Map([
          [
            '000004',
            {
              meta: { code: '000004', currentRank: 4, currentPercentile: 96, change: 3, rawChange: 3, updateTime: 1, sampleQuality: { status: 'ok', sampleCount: 30, requiredSampleCount: 30, delayedCount: 0, restoredCount: 0 } },
              technical: {},
              cycle: {},
              risk: {},
              decision: { final: { signal: 'hold', confidence: 60 } },
              jump: { direction: 'hold', confidence: 55 },
            } as any,
          ],
        ]),
      )
      const service = new RankTrendSignalService()
      const result = await service.applySignalsToMerged([{ code: '000004', name: '无共振股', avgRankNum: 1 }])

      expect(result[0]._rankChange).toBe(3)
      expect(result[0]._jumpConfidence).toBe(55)
      expect(result[0]._resonancePct).toBeUndefined()
      expect(result[0]._resonanceLabel).toBe('样本不足')
    })
  })

  it('returns RankTrend, Jump and resonance fields without waiting for candidate-pool sync', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { fusionCandidateNotifier } = await import('../../rankTrend/FusionCandidateNotifier')
    let releaseCandidateSync: (() => void) | undefined
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
              sampleQuality: { status: 'ok', sampleCount: 30, requiredSampleCount: 30 },
            },
            technical: {},
            cycle: {},
            risk: {},
            decision: { final: { signal: 'buy', confidence: 80 } },
            jump: { direction: 'buy', confidence: 92 },
          } as any,
        ],
      ]),
    )
    vi.mocked(fusionCandidateNotifier.process).mockImplementationOnce(
      () => new Promise<void>((resolve) => { releaseCandidateSync = resolve }),
    )

    const service = new RankTrendSignalService()
    const result = await service.applySignalsToMerged([{ code: '000001', name: '平安银行', avgRankNum: 1 }])

    expect(result[0]).toMatchObject({
      _rankChange: 12,
      _jumpConfidence: 92,
      _jumpDirection: 'buy',
    })
    expect(fusionCandidateNotifier.process).toHaveBeenCalledWith(result)

    releaseCandidateSync?.()
  })

  it('never publishes an older candidate projection after a newer frame is queued', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { fusionCandidateNotifier } = await import('../../rankTrend/FusionCandidateNotifier')
    const { applyCandidatePoolProjections } = await import('../../candidate/CandidatePoolStatusProjector')
    let releaseFirst: (() => void) | undefined
    let releaseSecond: (() => void) | undefined
    vi.mocked(rankTrendAnalyzer.getRankTrends).mockResolvedValue(new Map())
    vi.mocked(rankTrendAnalyzer.getLatestAnalysisFrameKeys).mockReturnValue([])
    vi.mocked(fusionCandidateNotifier.process)
      .mockImplementationOnce(() => new Promise<void>((resolve) => { releaseFirst = resolve }))
      .mockImplementationOnce(() => new Promise<void>((resolve) => { releaseSecond = resolve }))
    vi.mocked(applyCandidatePoolProjections).mockImplementation((stocks: any[]) => {
      for (const stock of stocks) stock.candidatePoolLabel = `projected:${stock.name}`
      return stocks
    })

    const service = new RankTrendSignalService()
    const first = [{ code: '000001', name: 'frame-a', avgRankNum: 1 }]
    const second = [{ code: '000001', name: 'frame-b', avgRankNum: 1 }]
    await service.applySignalsToMerged(first)
    dataLayer.setMergedStocks(second as any)
    await service.applySignalsToMerged(second)

    releaseFirst?.()
    await vi.waitFor(() => expect(fusionCandidateNotifier.process).toHaveBeenCalledTimes(2))
    expect(dataLayer.getStock('000001')?.candidatePoolLabel).toBeUndefined()

    releaseSecond?.()
    await vi.waitFor(() => {
      expect(dataLayer.getStock('000001')?.candidatePoolLabel).toBe('projected:frame-b')
    })
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

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行', price: 12.34, avgRankNum: 1 } as any])

    const service = new RankTrendSignalService()
    const result = await service.refreshRankTrendSignals()

    expect(result[0].rankTrend?.meta?.code).toBe('000001')
    await vi.waitFor(() => expect(buildFusionStrategyProjections).toHaveBeenCalled())
    expect(buildFusionStrategyProjections).toHaveBeenCalledWith(result, expect.any(Object))
    expect(applyCandidatePoolProjections).toHaveBeenCalledWith(result, expect.any(Array))
  })

  it('keeps unavailable observation values missing instead of projecting zero', () => {
    const service = new RankTrendSignalService()
    const stocks = [
      { code: '000001' },
      {
        code: '000002',
        rankTrend: {
          resonance: { status: 'insufficient', score: 0, label: '样本不足' },
        },
      },
    ]

    ;(service as any).precomputeDisplayFields(stocks)

    for (const stock of stocks) {
      expect(stock._resonancePct).toBeUndefined()
      expect(stock._rankTrendPct).toBeUndefined()
      expect(stock._lifecyclePct).toBeUndefined()
    }
  })
})
