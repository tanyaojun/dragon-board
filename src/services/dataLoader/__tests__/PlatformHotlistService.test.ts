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
})
