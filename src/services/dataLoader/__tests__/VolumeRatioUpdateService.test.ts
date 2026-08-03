import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'
import { VolumeRatioUpdateService } from '../VolumeRatioUpdateService'

vi.mock('../../apiService', () => ({
  apiService: {
    getVolumeRatios: vi.fn(),
  },
}))

describe('VolumeRatioUpdateService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('consumes backend volume ratio results and writes structured diagnostics', async () => {
    vi.mocked(apiService.getVolumeRatios).mockResolvedValue({
      ok: true,
      items: {
        '600000': {
          value: 99.99,
          status: 'suspicious',
          source: 'daily_snapshot',
          currentVolume: 100000,
          expectedVolume: 1,
          historyVolumes: [1, 1, 1],
          rawRatio: 100000,
          capped: true,
          reason: 'ratio_capped',
          calculatedAt: 123,
        },
      },
    })
    const dataLayer = {
      getStocks: vi.fn(() => [{ code: '600000', name: '浦发银行', volume: 100000 }]),
      updateStockExtData: vi.fn(),
    }
    const service = new VolumeRatioUpdateService({ dataLayer })

    const summary = await service.updateVolumeRatios(['600000'])

    expect(summary).toEqual({ requested: 1, updated: 1, unavailable: 0, suspicious: 1 })
    expect(apiService.getVolumeRatios).toHaveBeenCalledWith({
      stocks: [{ code: '600000', volume: 100000 }],
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
    vi.mocked(apiService.getVolumeRatios).mockResolvedValue({
      ok: true,
      items: {
        '600000': {
          status: 'unavailable',
          source: 'unavailable',
          currentVolume: 100000,
          historyVolumes: [],
          reason: 'insufficient_history',
          calculatedAt: 1000,
        },
      },
    })
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
    const service = new VolumeRatioUpdateService({ dataLayer })

    const summary = await service.updateVolumeRatios(['600000'])

    expect(summary).toEqual({ requested: 1, updated: 1, unavailable: 0, suspicious: 0 })
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

  it('keeps existing data when the backend volume ratio service is unavailable', async () => {
    vi.mocked(apiService.getVolumeRatios).mockRejectedValue(new Error('backend offline'))
    const updateStockExtData = vi.fn()
    const service = new VolumeRatioUpdateService({
      dataLayer: {
        getStocks: vi.fn(() => [{ code: '600000', name: '浦发银行', volume: 100 }]),
        updateStockExtData,
      },
    })

    const summary = await service.updateVolumeRatios(['600000'])

    expect(summary).toEqual({ requested: 1, updated: 0, unavailable: 0, suspicious: 0 })
    expect(updateStockExtData).not.toHaveBeenCalled()
  })
})
