import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../apiService'
import { StockCodeManagerService } from '../StockCodeManager'

vi.mock('../apiService', () => ({
  apiService: {
    listStockNames: vi.fn(),
  },
}))

class MemoryStorage {
  private store = new Map<string, string>()

  getItem(key: string): string | null {
    return this.store.get(key) ?? null
  }

  setItem(key: string, value: string): void {
    this.store.set(key, value)
  }

  removeItem(key: string): void {
    this.store.delete(key)
  }

  clear(): void {
    this.store.clear()
  }
}

describe('StockCodeManagerService', () => {
  let storage: MemoryStorage

  beforeEach(() => {
    vi.resetAllMocks()
    ;(StockCodeManagerService as any).instance = undefined
    storage = new MemoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.stubGlobal('fetch', vi.fn())
  })

  it('initializes from QuantBoard stock_names API and keeps sync lookup methods in memory', async () => {
    vi.mocked(apiService.listStockNames).mockResolvedValue({
      ok: true,
      source: 'mongodb',
      version: 'stock_names.v1',
      stocks: [
        {
          code: '600001',
          name: '浦发银行',
          market: 'SH',
          type: 'stock',
          pinyinInitials: 'pfyh',
          pinyinFull: 'pufayinhang',
        },
        {
          code: '000001',
          name: '平安银行',
          market: 'SZ',
          type: 'stock',
          pinyinInitials: 'payh',
          pinyinFull: 'pinganyinhang',
        },
      ],
    })

    const manager = StockCodeManagerService.getInstance()
    const stocks = await manager.getAllStocks(true)

    expect(apiService.listStockNames).toHaveBeenCalledWith()
    expect(fetch).not.toHaveBeenCalled()
    expect(stocks.map((item) => item.code)).toEqual(['600001', '000001'])
    expect(manager.getStockName('600001')).toBe('浦发银行')
    expect(manager.getStockInfo('000001')?.market).toBe('SZ')
    expect(manager.search('pf')[0].code).toBe('600001')

    const cached = JSON.parse(storage.getItem('stock_codes_cache') || '{}')
    expect(cached.source).toBe('mongodb')
    expect(cached.stale).toBe(false)
    expect(cached.version).toBe('stock_names.v1')
  })

  it('marks Mongo-sourced localStorage fallback as stale when API loading fails', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => undefined)
    storage.setItem(
      'stock_codes_cache',
      JSON.stringify({
        version: 'stock_names.v1',
        source: 'mongodb',
        stale: false,
        timestamp: Date.now(),
        codes: [
          {
            code: '600001',
            name: '浦发银行',
            market: 'SH',
            type: 'stock',
            pinyinInitials: 'pfyh',
          },
        ],
      }),
    )
    vi.mocked(apiService.listStockNames).mockRejectedValue(new Error('backend unavailable'))

    const manager = StockCodeManagerService.getInstance()
    const stocks = await manager.getAllStocks()

    expect(stocks).toHaveLength(1)
    expect(manager.getStatus()).toMatchObject({
      state: 'success',
      source: 'cache',
      stale: true,
      version: 'stock_names.v1',
      error: 'backend unavailable',
    })
  })
})
