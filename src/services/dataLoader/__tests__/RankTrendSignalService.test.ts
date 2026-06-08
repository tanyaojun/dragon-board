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

vi.mock('../../candidate/CandidatePoolStatusProjector', () => ({
  applyCandidatePoolStatus: vi.fn(async (stocks: any[]) => stocks),
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

  it('refreshRankTrendSignals uses fresh rankTrend results to compute live V3 signals', async () => {
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
    const { applyCandidatePoolStatus } = await import('../../candidate/CandidatePoolStatusProjector')

    expect(fusionCandidateNotifier.process).toHaveBeenCalledWith(result)
    expect(applyCandidatePoolStatus).toHaveBeenCalledWith(result)
    expect(result[0].liveV3SignalDecision).toBeUndefined()
  })

  it('keeps RankTrend refresh usable when fusion auto-candidate creation fails', async () => {
    const { rankTrendAnalyzer } = await import('../../RankTrendAnalyzer')
    const { fusionCandidateNotifier } = await import('../../rankTrend/FusionCandidateNotifier')
    const { applyCandidatePoolStatus } = await import('../../candidate/CandidatePoolStatusProjector')

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
    expect(applyCandidatePoolStatus).toHaveBeenCalledWith(result)
  })
})
