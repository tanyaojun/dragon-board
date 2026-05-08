import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../DataLayer'
import { RankTrendSignalService } from '../RankTrendSignalService'

let emittedEvents = 0

vi.mock('../../RankTrendAnalyzer', () => ({
  rankTrendAnalyzer: {
    getRankTrends: vi.fn(),
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
