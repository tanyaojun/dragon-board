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
})
