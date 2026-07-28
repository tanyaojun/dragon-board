import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'
import { PlatformHotlistService } from '../PlatformHotlistService'

const adapterMocks = vi.hoisted(() => ({
  getHotList: vi.fn(),
  format: vi.fn(),
}))

vi.mock('../../apiService', () => ({
  apiService: {
    listStockNames: vi.fn(),
  },
}))

vi.mock('../../adapters', () => ({
  Adapters: {
    eastmoney: adapterMocks,
  },
}))

describe('PlatformHotlistService', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    adapterMocks.getHotList.mockResolvedValue([])
    adapterMocks.format.mockReturnValue([
      { code: '000001', name: '平安银行', rank: 1 },
      { code: '00700', name: '腾讯控股', rank: 2 },
      { code: '005930', name: '三星电子', rank: 3 },
    ])
  })

  it('only keeps codes returned as active by the MongoDB stock_names API', async () => {
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [
        { code: '000001', name: '平安银行', active: true },
        { code: '000002', name: '', active: true },
        { code: '00700', active: false },
      ],
    })

    const result = await new PlatformHotlistService().loadPlatforms(['eastmoney'], true)

    expect(result.data.eastmoney).toEqual([{ code: '000001', name: '平安银行', rank: 1 }])
    expect(apiService.listStockNames).toHaveBeenCalledWith({ active: true })
  })

  it('does not fall back to platform rows when the MongoDB stock_names API is unavailable', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.mocked(apiService.listStockNames).mockRejectedValue(new Error('MongoDB unavailable'))

    const result = await new PlatformHotlistService().loadPlatforms(['eastmoney'], true)

    expect(result.data.eastmoney).toEqual([])
    expect(adapterMocks.getHotList).not.toHaveBeenCalled()
    warn.mockRestore()
  })

  it('keeps the platform cache valid before the 30 minute TTL expires', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-27T09:30:00+08:00'))
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [{ code: '000001', name: '平安银行', active: true }],
    })

    try {
      const service = new PlatformHotlistService(30 * 60 * 1000)
      await service.loadPlatforms(['eastmoney'])
      vi.setSystemTime(new Date('2026-07-27T09:59:59.999+08:00'))

      const result = await service.loadPlatforms(['eastmoney'])

      expect(result.fromCache).toBe(true)
      expect(adapterMocks.getHotList).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('reloads platform data when the 30 minute TTL boundary is reached', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-27T09:30:00+08:00'))
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [{ code: '000001', name: '平安银行', active: true }],
    })

    try {
      const service = new PlatformHotlistService(30 * 60 * 1000)
      await service.loadPlatforms(['eastmoney'])
      vi.setSystemTime(new Date('2026-07-27T10:00:00+08:00'))

      const result = await service.loadPlatforms(['eastmoney'])

      expect(result.fromCache).toBe(false)
      expect(adapterMocks.getHotList).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('force reload bypasses a fresh platform cache', async () => {
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [{ code: '000001', name: '平安银行', active: true }],
    })
    const service = new PlatformHotlistService(30 * 60 * 1000)

    await service.loadPlatforms(['eastmoney'])
    const result = await service.loadPlatforms(['eastmoney'], true)

    expect(result.fromCache).toBe(false)
    expect(adapterMocks.getHotList).toHaveBeenCalledTimes(2)
  })

  it('exposes the latest cache check and real reload details', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-27T10:00:00+08:00'))
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [{ code: '000001', name: '平安银行', active: true }],
    })

    try {
      const service = new PlatformHotlistService(30 * 60 * 1000)
      service.markRefreshChecked()
      await service.loadPlatforms(['eastmoney'], true)

      expect(service.getCacheDiagnostics()).toEqual({
        lastCheckAt: new Date('2026-07-27T10:00:00+08:00').getTime(),
        lastReloadAt: new Date('2026-07-27T10:00:00+08:00').getTime(),
        lastLoadFromCache: false,
        cacheTimestamp: new Date('2026-07-27T10:00:00+08:00').getTime(),
        platforms: {
          eastmoney: { rowCount: 1, success: true },
        },
      })
    } finally {
      vi.useRealTimers()
    }
  })

  it('records the failure reason for each failed platform reload', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      stocks: [{ code: '000001', name: '平安银行', active: true }],
    })
    adapterMocks.getHotList.mockRejectedValue(new Error('upstream timeout'))
    const service = new PlatformHotlistService()

    await service.loadPlatforms(['eastmoney'], true)

    expect(service.getCacheDiagnostics().platforms.eastmoney).toEqual({
      rowCount: 0,
      success: false,
      error: 'upstream timeout',
    })
    warn.mockRestore()
  })
})
