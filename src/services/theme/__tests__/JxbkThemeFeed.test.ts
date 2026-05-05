import { beforeEach, describe, expect, it, vi } from 'vitest'

import { dataLayer } from '@/services/DataLayer'
import { apiService } from '@/services/apiService'
import { jxbkThemeFeed } from '../JxbkThemeFeed'
import { themeFacade } from '../ThemeFacade'

const blockStockResponse = {
  response: {
    data: [
      [
        null,
        '000001',
        '样本一',
        null,
        null,
        null,
        '龙一',
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        null,
        ['人工智能、算力', '10.5', '3.2', '1.1', '2.5', '', '1000', '600', '400', '', '', '', '', '', '200', '', '', '', '2板', '', '', '3000', '5000', '', '', '', '', '', '', '80', '', '', '', '', '', '', '', '', '', '', '4', '', '', '', '', '', '', '', '', '', '9000', '', '', '', '', '', '', '', '99', '2'],
      ],
    ],
  },
}

describe('JxbkThemeFeed sector stock loading', () => {
  beforeEach(() => {
    dataLayer.reset()
    jxbkThemeFeed.clearSectorStockCache()
    vi.restoreAllMocks()
  })

  it('loads sector stocks, writes DataLayer and refreshes runtime', async () => {
    const apiSpy = vi.spyOn(apiService, 'getBlockStockList').mockResolvedValue(blockStockResponse as any)
    const refreshSpy = vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'jxbkThemeFeed',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })

    const stocks = await jxbkThemeFeed.loadSectorStocks('BKAI', '人工智能')

    expect(apiSpy).toHaveBeenCalledWith('BKAI', { type: 6, st: 80 })
    expect(stocks).toHaveLength(1)
    expect(stocks[0]).toMatchObject({
      code: '000001',
      name: '样本一',
      blocks: ['人工智能', '算力'],
      price: 10.5,
      change: 3.2,
      leadStatus: '龙一',
    })
    expect(dataLayer.getJxbkStock('000001')?.name).toBe('样本一')
    expect(refreshSpy).toHaveBeenCalledWith({
      source: 'jxbkThemeFeed',
      context: expect.any(Object),
      emitAlerts: false,
    })
    expect(jxbkThemeFeed.getSectorStockCacheStats().cachedSectors).toBe(1)
  })

  it('reuses cache and coalesces concurrent loads', async () => {
    const apiSpy = vi.spyOn(apiService, 'getBlockStockList').mockResolvedValue(blockStockResponse as any)
    vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'jxbkThemeFeed',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })

    const [first, second] = await Promise.all([
      jxbkThemeFeed.loadSectorStocks('BKAI', '人工智能'),
      jxbkThemeFeed.loadSectorStocks('BKAI', '人工智能'),
    ])
    const cached = await jxbkThemeFeed.loadSectorStocks('BKAI', '人工智能')
    await jxbkThemeFeed.loadSectorStocks('BKAI', '人工智能', true)

    expect(first).toEqual(second)
    expect(cached).toEqual(first)
    expect(apiSpy).toHaveBeenCalledTimes(2)
  })

  it('ignores malformed detail arrays instead of parsing string characters', async () => {
    vi.spyOn(apiService, 'getBlockStockList').mockResolvedValue({
      response: {
        data: [[null, '000002', '样本二', null, null, null, '', null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, null, '人工智能、10.5']],
      },
    } as any)
    vi.spyOn(themeFacade, 'refreshRuntime').mockReturnValue({
      factors: [],
      exposures: { byCode: new Map(), byTheme: new Map() },
      rotationSummary: null,
      events: [],
      qualitySummary: { totalFlags: 0, fatalCount: 0, warningCount: 0, infoCount: 0, byCode: {} },
      changedFields: [],
      inputSignature: 'same',
      source: 'jxbkThemeFeed',
      timestamp: 1713751200000,
      syncedStockCount: 0,
    })

    const stocks = await jxbkThemeFeed.loadSectorStocks('BKBAD', '异常题材')

    expect(stocks[0]).toMatchObject({
      code: '000002',
      name: '样本二',
      blocks: [],
      price: 0,
      change: 0,
    })
  })
})
