import { describe, expect, it, vi } from 'vitest'

import { VolumeRatioUpdateService } from '../VolumeRatioUpdateService'

describe('VolumeRatioUpdateService', () => {
  it('writes structured volume ratio diagnostics to the data layer', async () => {
    const dataLayer = {
      getStocks: vi.fn(() => [{ code: '600000', name: '浦发银行', volume: 100000 }]),
      updateStockExtData: vi.fn(),
    }
    const volumeHistoryService = {
      buildVolumeHistoryMap: vi.fn(async () => new Map([['600000', [1, 1, 1]]])),
      buildIntradayVolumeHistoryMap: vi.fn(async () => new Map()),
    }
    const service = new VolumeRatioUpdateService({
      dataLayer,
      volumeHistoryService,
      now: () => new Date('2026-05-06T15:30:00+08:00'),
    })

    const summary = await service.updateVolumeRatios(['600000'])

    expect(summary).toEqual({
      requested: 1,
      updated: 1,
      unavailable: 0,
      suspicious: 1,
    })
    expect(dataLayer.updateStockExtData).toHaveBeenCalledWith([
      expect.objectContaining({
        code: '600000',
        volumeRatio: 99.99,
        volumeRatioMeta: expect.objectContaining({
          status: 'suspicious',
          source: 'daily_snapshot',
          currentVolume: 100000,
          expectedVolume: 1,
          rawRatio: 100000,
          capped: true,
          reason: 'ratio_capped',
        }),
      }),
    ])
  })

  it('preserves an existing positive volume ratio when history is insufficient', async () => {
    const dataLayer = {
      getStocks: vi.fn(() => [
        {
          code: '600000',
          name: '浦发银行',
          volume: 100000,
          volumeRatio: 1.88,
          volumeRatioMeta: {
            status: 'fresh',
            source: 'daily_snapshot',
            calculatedAt: 1000,
            currentVolume: 90000,
          },
        },
      ]),
      updateStockExtData: vi.fn(),
    }
    const volumeHistoryService = {
      buildVolumeHistoryMap: vi.fn(async () => new Map()),
      buildIntradayVolumeHistoryMap: vi.fn(async () => new Map()),
    }
    const service = new VolumeRatioUpdateService({
      dataLayer,
      volumeHistoryService,
      now: () => new Date('2026-05-06T15:30:00+08:00'),
    })

    const summary = await service.updateVolumeRatios(['600000'])

    expect(summary).toEqual({
      requested: 1,
      updated: 1,
      unavailable: 0,
      suspicious: 0,
    })
    expect(dataLayer.updateStockExtData).toHaveBeenCalledWith([
      expect.objectContaining({
        code: '600000',
        volumeRatio: 1.88,
        volumeRatioMeta: expect.objectContaining({
          status: 'stale',
          source: 'daily_snapshot',
          currentVolume: 100000,
          reason: 'history_unavailable_preserved_previous',
        }),
      }),
    ])
  })
})
