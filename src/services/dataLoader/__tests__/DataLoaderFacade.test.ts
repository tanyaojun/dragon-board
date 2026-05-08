import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../DataLayer'

const platformRows: Record<string, any[]> = {
  eastmoney: [{ code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' }],
}

let fromCache = false
let quoteError: Error | null = null
let volumeHistoryError: Error | null = null
let platformLoadError: Error | null = null

vi.mock('../PlatformHotlistService', () => ({
  platformHotlistService: {
    loadPlatforms: vi.fn(async () => {
      if (platformLoadError) throw platformLoadError
      return {
        data: platformRows,
        timestamp: 1000,
        fromCache,
      }
    }),
    getAllHotCodes: (data: Record<string, any[]>) =>
      new Set(Object.values(data || {}).flatMap((rows) => rows.map((row) => row.code))),
    shouldRefresh: () => false,
    hasFreshCache: () => true,
    markRefreshed: vi.fn(),
    maintenance: vi.fn(),
    clearCache: vi.fn(),
  },
}))

vi.mock('../QuoteService', () => ({
  quoteService: {
    getQuoteBatch: vi.fn(async () => {
      if (quoteError) throw quoteError
      return new Map()
    }),
    getQuotes: vi.fn(async () => new Map()),
    fetchMergedQuotes: vi.fn(async () => new Map()),
    getQuote: vi.fn(async () => null),
  },
}))

vi.mock('../../theme/ThemeFacade', () => ({
  themeFacade: {
    refreshRuntime: vi.fn(async () => ({ syncedStockCount: 0 })),
  },
}))

vi.mock('../RealtimeQuoteCoordinator', () => ({
  RealtimeQuoteCoordinator: class {
    syncRealtimeSubscription() {}
    isRealtimePrimaryHealthy() {
      return false
    }
  },
}))

vi.mock('../VolumeHistoryService', () => ({
  VolumeHistoryService: class {
    async buildVolumeHistoryMap() {
      if (volumeHistoryError) throw volumeHistoryError
      return new Map()
    }
    async buildIntradayVolumeHistoryMap() {
      if (volumeHistoryError) throw volumeHistoryError
      return new Map()
    }
  },
}))

vi.mock('../RankTrendSignalService', () => ({
  rankTrendSignalService: {
    applySignalsToMerged: vi.fn(async (stocks) => stocks),
    updateStockSignals: vi.fn(),
    refreshRankTrendSignals: vi.fn(),
  },
}))

describe('DataLoaderFacade', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    fromCache = false
    quoteError = null
    volumeHistoryError = null
    platformLoadError = null
  })

  it('keeps hotlist stocks visible even when quote enrichment returns empty', async () => {
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.loadAllPlatforms(true)

    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('hydrates DataLayer from hotlist cache when the UI data pool is empty', async () => {
    fromCache = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.loadAllPlatforms(false)

    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('keeps startup usable when quote enrichment is aborted', async () => {
    const error = new Error('signal is aborted without reason')
    error.name = 'AbortError'
    quoteError = error
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.loadAllPlatforms(true)

    await expect(dataLoader.loadStockDetails(false)).resolves.toEqual(new Map())
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('keeps startup usable when volume history snapshots are unavailable', async () => {
    volumeHistoryError = new Error('snapshot unavailable')
    const { dataLoader } = await import('../../dataLoader')

    await expect(dataLoader.loadAllPlatforms(true)).resolves.toBeTruthy()
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('keeps startup usable when platform loading fails before returning data', async () => {
    platformLoadError = new Error('platform request aborted')
    const { dataLoader } = await import('../../dataLoader')

    await expect(dataLoader.loadAllPlatforms(true)).resolves.toEqual({})
    expect(dataLayer.getStocks()).toEqual([])
  })
})
