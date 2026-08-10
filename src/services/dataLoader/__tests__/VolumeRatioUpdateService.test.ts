import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'
import { VolumeRatioUpdateService } from '../VolumeRatioUpdateService'
import { clearVolumeRatioCache } from '../volumeRatioCache'

vi.mock('../../apiService', () => ({
  apiService: {
    getVolumeRatios: vi.fn(),
  },
}))

describe('VolumeRatioUpdateService', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    // 清空量比结果 LRU 缓存，避免用例间缓存残留
    clearVolumeRatioCache()
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

    expect(summary).toEqual({ requested: 1, updated: 0, unavailable: 1, suspicious: 0 })
    expect(updateStockExtData).not.toHaveBeenCalled()
  })

  it('reuses cached volume ratio within 60s TTL without calling backend again', async () => {
    vi.mocked(apiService.getVolumeRatios).mockResolvedValue({
      ok: true,
      items: {
        '600000': {
          value: 1.88,
          status: 'fresh',
          source: 'daily_snapshot',
          currentVolume: 100000,
          expectedVolume: 53191,
          historyVolumes: [50000, 52000, 48000],
          rawRatio: 1.88,
          calculatedAt: 123,
        },
      },
    })
    const updateStockExtData = vi.fn()
    const service = new VolumeRatioUpdateService({
      dataLayer: {
        getStocks: vi.fn(() => [{ code: '600000', name: '浦发银行', volume: 100000 }]),
        updateStockExtData,
      },
    })

    // 首次：miss → 调后端并写缓存
    const first = await service.updateVolumeRatios(['600000'])
    expect(first.updated).toBe(1)
    expect(apiService.getVolumeRatios).toHaveBeenCalledTimes(1)

    // 二次（60s TTL 内）：命中缓存 → 不调后端
    vi.mocked(apiService.getVolumeRatios).mockClear()
    const second = await service.updateVolumeRatios(['600000'])
    expect(second.updated).toBe(1)
    expect(apiService.getVolumeRatios).not.toHaveBeenCalled()
  })
})
