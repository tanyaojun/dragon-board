import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '../../DataLayer'

const platformRows: Record<string, any[]> = {
  eastmoney: [{ code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' }],
}

let fromCache = false
let firstPlatformLoadEmptyCache = false
let platformLoadCount = 0
let quoteError: Error | null = null
let volumeHistoryError: Error | null = null
let platformLoadError: Error | null = null
let blockSignalCalculation = false
let releaseSignalCalculation: (() => void) | null = null
let signalCalculationError: Error | null = null
let signalApplyCount = 0

vi.mock('../PlatformHotlistService', () => ({
  platformHotlistService: {
    loadPlatforms: vi.fn(async (_platforms, force) => {
      if (platformLoadError) throw platformLoadError
      platformLoadCount++
      if (firstPlatformLoadEmptyCache && platformLoadCount === 1 && !force) {
        return {
          data: {},
          timestamp: 1000,
          fromCache: true,
        }
      }
      return {
        data: platformRows,
        timestamp: 1000,
        fromCache: force ? false : fromCache,
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

vi.mock('../LimitUpFeed', () => ({
  loadLimitUpData: vi.fn(async () => undefined),
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
    applySignalsToMerged: vi.fn(async (stocks) => {
      signalApplyCount++
      if (signalCalculationError) throw signalCalculationError
      if (blockSignalCalculation) {
        await new Promise<void>((resolve) => {
          releaseSignalCalculation = resolve
        })
      }
      return stocks
    }),
    updateStockSignals: vi.fn(),
    refreshRankTrendSignals: vi.fn(() => [
      { code: '000001', name: '平安银行', rankTrendCoverageWarning: 'refreshed' },
    ]),
  },
}))

describe('DataLoaderFacade', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    fromCache = false
    firstPlatformLoadEmptyCache = false
    platformLoadCount = 0
    quoteError = null
    volumeHistoryError = null
    platformLoadError = null
    blockSignalCalculation = false
    releaseSignalCalculation = null
    signalCalculationError = null
    signalApplyCount = 0
    EventManager.clearHistory()
    vi.clearAllMocks()
  })

  afterEach(async () => {
    const { dataLoader } = await import('../../dataLoader')
    dataLoader.stopSignalAutoRefresh()
  })

  it('bootstrapInitialData publishes base hotlist rows and returns a structured summary', async () => {
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: true })

    expect(summary).toEqual(
      expect.objectContaining({
        stockCount: 1,
        platformCount: 1,
        fromCache: false,
      }),
    )
    expect(summary.elapsedMs).toBeGreaterThanOrEqual(0)
    expect(platformLoadCount).toBe(1)
    expect(signalApplyCount).toBe(1)
    expect(dataLoader.getLoadingStatus().active).toBe(false)
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('bootstrapInitialData reloads through the startup path when old rows already exist', async () => {
    dataLayer.setMergedStocks([{ code: '000099', name: '旧数据' } as any])
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: false })

    expect(summary.stockCount).toBe(1)
    expect(platformLoadCount).toBe(1)
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('bootstrapInitialData keeps startup usable when quote enrichment fails', async () => {
    quoteError = new Error('quote unavailable')
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: true })

    expect(summary.stockCount).toBe(1)
    expect(dataLoader.getLoadingStatus().active).toBe(false)
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('refreshAll performs one platform load and one merge cycle', async () => {
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.refreshAll({ force: true, source: 'manual' })

    expect(summary).toEqual(
      expect.objectContaining({
        stockCount: 1,
        platformCount: 1,
        fromCache: false,
      }),
    )
    expect(platformLoadCount).toBe(1)
    expect(signalApplyCount).toBe(1)
    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
      expect.objectContaining({ data: expect.objectContaining({ reason: 'base-merge' }) }),
      expect.objectContaining({ data: expect.objectContaining({ reason: 'signal-enriched' }) }),
    ])
    expect(dataLoader.getLoadingStatus().active).toBe(false)
  })

  it('does not double-increment UI data version when DATA.MERGED is subscribed', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { useUIStore } = await import('../../../stores/ui')
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      await dataLoader.refreshAll({ force: true, source: 'manual' })

      expect(uiStore.dataVersion).toBe(2)
    } finally {
      dispose()
    }
  })

  it('refreshAll returns an empty structured summary after recoverable platform failure', async () => {
    platformLoadError = new Error('platform request aborted')
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.refreshAll({ force: true, source: 'manual' })

    expect(summary).toEqual(
      expect.objectContaining({
        stockCount: 0,
        platformCount: 0,
        fromCache: false,
      }),
    )
    expect(dataLoader.getLoadingStatus().active).toBe(false)
    expect(dataLayer.getStocks()).toEqual([])
  })

  it('runs scheduled RankTrend refresh from DataLoader instead of DataTable', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-08T14:44:59+08:00'))
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { rankTrendSignalService } = await import('../RankTrendSignalService')

      dataLoader.stopSignalAutoRefresh()
      ;(dataLoader as any).lastSignalRefreshDate = null
      dataLoader.startSignalAutoRefresh(1000)
      vi.advanceTimersByTime(1000)
      await Promise.resolve()

      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopSignalAutoRefresh()
      vi.useRealTimers()
    }
  })

  it('publishes scheduled RankTrend refresh through the DataLoader boundary', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')

    await dataLoader.refreshRankTrendSignals()

    expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledWith()
    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
      expect.objectContaining({
        data: expect.objectContaining({ reason: 'manual-signal-update' }),
      }),
    ])
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        rankTrendCoverageWarning: 'refreshed',
      }),
    ])
  })

  it('publishes hotness recalculation through the DataLoader boundary', async () => {
    dataLayer.setMergedStocks([
      { code: '000001', name: '平安银行', hotness: 0, sources: ['eastmoney'], rank: 1 } as any,
    ])
    EventManager.clearHistory()
    const { dataLoader } = await import('../../dataLoader')

    const stocks = dataLoader.recalculateStockHotness()

    expect(stocks).toEqual([
      expect.objectContaining({
        code: '000001',
        hotness: expect.any(Number),
      }),
    ])
    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
      expect.objectContaining({
        data: expect.objectContaining({ reason: 'hotness-recalculated' }),
      }),
    ])
  })

  it('runs scheduled RankTrend refresh once per local date', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-08T14:44:59+08:00'))
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { rankTrendSignalService } = await import('../RankTrendSignalService')

      dataLoader.stopSignalAutoRefresh()
      ;(dataLoader as any).lastSignalRefreshDate = null
      dataLoader.startSignalAutoRefresh(1000)
      vi.advanceTimersByTime(1000)
      await Promise.resolve()
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

      vi.setSystemTime(new Date('2026-05-08T14:45:30+08:00'))
      vi.advanceTimersByTime(1000)
      await Promise.resolve()
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

      vi.setSystemTime(new Date('2026-05-09T14:44:59+08:00'))
      vi.advanceTimersByTime(1000)
      await Promise.resolve()
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(2)
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopSignalAutoRefresh()
      vi.useRealTimers()
    }
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

  it('publishes base hotlist rows before RankTrend signal enrichment finishes', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    const loadPromise = dataLoader.loadAllPlatforms(true)

    await vi.waitFor(() => {
      expect(dataLayer.getStocks()).toEqual([
        expect.objectContaining({
          code: '000001',
          name: '平安银行',
        }),
      ])
    })

    blockSignalCalculation = false
    releaseSignalCalculation?.()
    await loadPromise
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

  it('recovers from a stale loading flag when startup has no stocks yet', async () => {
    const { dataLoader } = await import('../../dataLoader')
    ;(dataLoader as any).state.value.loading = true

    await dataLoader.loadAllPlatforms(false)

    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('refetches when a fresh platform cache is empty during startup', async () => {
    firstPlatformLoadEmptyCache = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.loadAllPlatforms(false)

    expect(platformLoadCount).toBe(2)
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

  it('keeps startup usable when RankTrend signal enrichment is aborted', async () => {
    const error = new Error('signal is aborted without reason')
    error.name = 'AbortError'
    signalCalculationError = error
    const { dataLoader } = await import('../../dataLoader')

    await expect(dataLoader.loadAllPlatforms(true)).resolves.toEqual(platformRows)
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
