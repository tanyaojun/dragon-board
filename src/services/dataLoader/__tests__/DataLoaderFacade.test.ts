import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '../../DataLayer'

const platformRows: Record<string, any[]> = {
  eastmoney: [{ code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' }],
}

let platformRowsByLoad: Array<Record<string, any[]>> = []
let fromCache = false
let firstPlatformLoadEmptyCache = false
let platformLoadCount = 0
let quoteError: Error | null = null
let volumeHistoryError: Error | null = null
let platformLoadError: Error | null = null
let quoteBatchResult = new Map<string, any>()
let blockPlatformLoad = false
let releasePlatformLoad: (() => void) | null = null
let blockSignalCalculation = false
let releaseSignalCalculation: (() => void) | null = null
let signalCalculationError: Error | null = null
let signalApplyCount = 0
let signalCompletionCount = 0
let signalPreloadCount = 0
let blockQuoteBatch = false
let releaseQuoteBatch: (() => void) | null = null
let realtimePrimaryHealthy = false
let blockIntradayVolumeHistory = false
let releaseIntradayVolumeHistory: (() => void) | null = null
let blockVolumeHistory = false
let releaseVolumeHistory: (() => void) | null = null
let startupBundle: any = null
let startupBundleGetCount = 0
let startupBundleSaveCount = 0
let realtimeOptions: any = null
let volumeHistoryMapResult = new Map<string, number[]>()
let intradayVolumeHistoryMapResult = new Map<string, number[]>()
let volumeHistoryRequestCount = 0
let intradayVolumeHistoryRequestCount = 0

const timeState = vi.hoisted(() => ({
  tradingTime: true,
}))

vi.mock('@/utils/time', () => ({
  isTradingTime: vi.fn(() => timeState.tradingTime),
}))

vi.mock('../PlatformHotlistService', () => ({
  platformHotlistService: {
    loadPlatforms: vi.fn(async (_platforms, force, options) => {
      if (platformLoadError) throw platformLoadError
      platformLoadCount++
      if (blockPlatformLoad) {
        options?.onProgress?.({ completed: 2, total: 8, platform: 'ths' })
        await new Promise<void>((resolve) => {
          releasePlatformLoad = resolve
        })
      }
      if (firstPlatformLoadEmptyCache && platformLoadCount === 1 && !force) {
        return {
          data: {},
          timestamp: 1000,
          fromCache: true,
        }
      }
      const rows = platformRowsByLoad[platformLoadCount - 1] || platformRows
      return {
        data: rows,
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
    getQuoteBatch: vi.fn(async (_codes, _force, options) => {
      if (quoteError) throw quoteError
      if (blockQuoteBatch) {
        options?.onProgress?.({
          source: 'tencent',
          completedBatches: 1,
          totalBatches: 4,
          completedCodes: 50,
          totalCodes: 200,
        })
        await new Promise<void>((resolve) => {
          releaseQuoteBatch = resolve
        })
      }
      return quoteBatchResult
    }),
    getQuotes: vi.fn(async () => new Map()),
    fetchMergedQuotes: vi.fn(async () => new Map()),
    getQuote: vi.fn(async () => null),
  },
}))

vi.mock('../LimitUpFeed', () => ({
  loadLimitUpData: vi.fn(async () => undefined),
  loadThsLimitUpPoolData: vi.fn(async () => undefined),
}))

vi.mock('../../theme/ThemeFacade', () => ({
  themeFacade: {
    refreshRuntime: vi.fn(async () => ({ syncedStockCount: 0 })),
  },
}))

vi.mock('../RealtimeQuoteCoordinator', () => ({
    RealtimeQuoteCoordinator: class {
      constructor(options: any) {
        realtimeOptions = options
      }
      syncRealtimeSubscription() {}
      isRealtimePrimaryHealthy() {
        return realtimePrimaryHealthy
      }
    },
  }))

vi.mock('../VolumeHistoryService', () => ({
  VolumeHistoryService: class {
    async buildVolumeHistoryMap() {
      volumeHistoryRequestCount++
      if (volumeHistoryError) throw volumeHistoryError
      if (blockVolumeHistory) {
        await new Promise<void>((resolve) => {
          releaseVolumeHistory = resolve
        })
      }
      return volumeHistoryMapResult
    }
    async buildIntradayVolumeHistoryMap() {
      intradayVolumeHistoryRequestCount++
      if (volumeHistoryError) throw volumeHistoryError
      if (blockIntradayVolumeHistory) {
        await new Promise<void>((resolve) => {
          releaseIntradayVolumeHistory = resolve
        })
      }
      return intradayVolumeHistoryMapResult
    }
  },
}))

vi.mock('../RankTrendSignalService', () => ({
  rankTrendSignalService: {
    preloadSnapshots: vi.fn(async () => {
      signalPreloadCount++
      return [
        {
          date: '2026-05-18 10:00',
          timestamp: 1,
          snapshot: {
            type: 'half_hour',
            hotlist: [{ code: '000001', rank: 30 }],
            totalCount: 100,
          },
        },
      ]
    }),
    applySignalsToMerged: vi.fn(async (stocks) => {
      signalApplyCount++
      if (signalCalculationError) throw signalCalculationError
      if (blockSignalCalculation) {
        await new Promise<void>((resolve) => {
          releaseSignalCalculation = resolve
        })
      }
      signalCompletionCount++
      return stocks.map((stock: any) => ({
        ...stock,
        rankTrend: {
          meta: { change: 12 },
          technical: {},
          cycle: {},
          risk: {},
          decision: {},
        },
        candidatePoolStatus: 'triggered',
        candidatePoolLabel: '已触发',
        candidatePoolEntryId: 'entry-1',
        candidatePoolSource: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        candidatePoolUpdatedAt: '2026-06-08T10:00:00.000Z',
      }))
    }),
    updateStockSignals: vi.fn(),
    refreshRankTrendSignals: vi.fn(async () => {
      if (blockSignalCalculation) {
        await new Promise<void>((resolve) => {
          releaseSignalCalculation = resolve
        })
      }
      const currentStocks = dataLayer.getStocks()
      if (!currentStocks.length) {
        return [{ code: '000001', name: '平安银行', rankTrendCoverageWarning: 'refreshed' }]
      }
      return currentStocks.map((stock: any) => ({
        ...stock,
        rankTrendCoverageWarning: 'refreshed',
      }))
    }),
  },
}))

vi.mock('../StartupBundleService', () => ({
  startupBundleService: {
    read: vi.fn(async () => {
      startupBundleGetCount++
      return startupBundle
    }),
    write: vi.fn(async (_bundle) => {
      startupBundleSaveCount++
    }),
  },
}))

describe('DataLoaderFacade', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    timeState.tradingTime = true
    platformRowsByLoad = []
    fromCache = false
    firstPlatformLoadEmptyCache = false
    platformLoadCount = 0
    quoteError = null
    volumeHistoryError = null
    platformLoadError = null
    quoteBatchResult = new Map()
    blockPlatformLoad = false
    releasePlatformLoad = null
    blockSignalCalculation = false
    releaseSignalCalculation = null
    signalCalculationError = null
    signalApplyCount = 0
    signalCompletionCount = 0
    signalPreloadCount = 0
    blockQuoteBatch = false
    releaseQuoteBatch = null
    realtimePrimaryHealthy = false
    blockIntradayVolumeHistory = false
    releaseIntradayVolumeHistory = null
    blockVolumeHistory = false
    releaseVolumeHistory = null
    startupBundle = null
    startupBundleGetCount = 0
    startupBundleSaveCount = 0
    volumeHistoryMapResult = new Map()
    intradayVolumeHistoryMapResult = new Map()
    volumeHistoryRequestCount = 0
    intradayVolumeHistoryRequestCount = 0
    EventManager.clearHistory()
    vi.clearAllMocks()
  })

  afterEach(async () => {
    const { dataLoader } = await import('../../dataLoader')
    dataLoader.stopQuoteAutoRefresh()
    dataLoader.stopSignalAutoRefresh()
    const runtime = await import('../../refresh/RefreshTaskRuntime').catch(() => null)
    runtime?.refreshTaskRegistry.resetRuntimeState()
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

  it('publishes EastMoney money-flow quote fields into merged stocks during startup', async () => {
    platformRowsByLoad = [
      {
        eastmoney: [{ code: '600584', name: '长电科技', rank: 1, source: 'eastmoney' }],
      },
    ]
    quoteBatchResult = new Map([
      [
        '600584',
        {
          price: 66.84,
          change: 0.94,
          volume: 3_125_058,
          turnover: 21_324_471_319,
          turnoverRate: 17.46,
          pe: 72.39,
          pb: 4.16,
          totalMV: 119_604_000_000,
          cirMV: 119_604_000_000,
          zlje: -970_465_792,
          zljzb: -4.55,
          cddje: -1_080_225_280,
          cddjzb: -5.07,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
          sources: ['tencent', 'eastmoney'],
          confidence: 95,
          timestamp: 1,
        },
      ],
    ])
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(dataLayer.getStock('600584')).toMatchObject({
      code: '600584',
      name: '长电科技',
      zlje: -970_465_792,
      zljzb: -4.55,
      cddje: -1_080_225_280,
      cddjzb: -5.07,
      moneyFlowSource: 'eastmoney',
      moneyFlowEstimated: false,
      capitalFlowSource: 'official_l2',
      turnoverRate: 17.46,
      totalMV: 119_604_000_000,
      cirMV: 119_604_000_000,
      pe: 72.39,
      pb: 4.16,
    })
  })

  it('refreshes EastMoney fund flow back into merged stocks when realtime is healthy', async () => {
    realtimePrimaryHealthy = true
    dataLayer.setMergedStocks([
      {
        code: '600584',
        name: '长电科技',
        zlje: 5_460,
        zljzb: 2.56,
        cddje: 0,
        cddjzb: 0,
        moneyFlowSource: 'tdx_estimate',
        moneyFlowEstimated: true,
        capitalFlowSource: 'estimated_l1',
        capitalFlowConfidence: 'low',
      } as any,
    ])
    quoteBatchResult = new Map([
      [
        '600584',
        {
          price: 66.84,
          change: 0.94,
          volume: 3_125_058,
          turnover: 21_324_471_319,
          turnoverRate: 17.46,
          pe: 72.39,
          pb: 4.16,
          totalMV: 119_604_000_000,
          cirMV: 119_604_000_000,
          zlje: -970_465_792,
          zljzb: -4.55,
          cddje: -1_080_225_280,
          cddjzb: -5.07,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
          sources: ['tencent', 'eastmoney'],
          confidence: 95,
          timestamp: 1,
        },
      ],
    ])
    const { dataLoader } = await import('../../dataLoader')
    const { quoteService } = await import('../QuoteService')
    const mockedFetchMergedQuotes = vi.mocked(quoteService.fetchMergedQuotes)
    const originalFetchMergedQuotes = mockedFetchMergedQuotes.getMockImplementation()
    mockedFetchMergedQuotes.mockResolvedValue(quoteBatchResult)

    try {
      await (dataLoader as any).runQuoteRefresh(50)

      expect(quoteService.fetchMergedQuotes).toHaveBeenCalledWith(['600584'], { force: false })
      expect(dataLayer.getStock('600584')).toMatchObject({
        code: '600584',
        zlje: -970_465_792,
        zljzb: -4.55,
        cddje: -1_080_225_280,
        cddjzb: -5.07,
        moneyFlowSource: 'eastmoney',
        moneyFlowEstimated: false,
        capitalFlowSource: 'official_l2',
        capitalFlowConfidence: 'medium',
        turnoverRate: 17.46,
        totalMV: 119_604_000_000,
        cirMV: 119_604_000_000,
        pe: 72.39,
        pb: 4.16,
      })
    } finally {
      if (originalFetchMergedQuotes) {
        mockedFetchMergedQuotes.mockImplementation(originalFetchMergedQuotes)
      }
    }
  })

  it('hydrates startup data from Redis bundle before running a background refresh', async () => {
    platformRowsByLoad = [
      {
        eastmoney: [{ code: '000002', name: '刷新数据', rank: 1, source: 'eastmoney' }],
      },
    ]
    blockPlatformLoad = true
    startupBundle = {
      schemaVersion: 1,
      tradingDate: '2026-05-18',
      createdAt: Date.now(),
      platformData: {
        eastmoney: [{ code: '000001', name: '缓存数据', rank: 1, source: 'eastmoney' }],
      },
      stocks: [
        {
          code: '000001',
          name: '缓存数据',
          rank: 1,
          compRank: 1,
          source: 'eastmoney',
          rankTrend: { meta: { change: 8 } },
        },
      ],
      cacheMeta: { stale: true },
    }
    const { dataLoader } = await import('../../dataLoader')

    const summaryPromise = dataLoader.bootstrapInitialData({ force: false })

    try {
      const summary = await Promise.race([
        summaryPromise,
        new Promise((resolve) => setTimeout(() => resolve('blocked-on-refresh'), 25)),
      ])

      expect(summary).toEqual(
        expect.objectContaining({
          stockCount: 1,
          fromCache: true,
          startupCache: expect.objectContaining({
            hit: true,
            stale: true,
            backgroundRefresh: true,
          }),
        }),
      )
      expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000001' })])
      expect(platformLoadCount).toBe(1)
      expect(startupBundleGetCount).toBe(1)
      expect(dataLoader.getLoadingStatus()).toMatchObject({
        active: false,
        phase: 'done',
        progress: 100,
      })
    } finally {
      blockPlatformLoad = false
      releasePlatformLoad?.()
      await summaryPromise.catch(() => undefined)
    }

    await vi.waitFor(() => {
      expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000002' })])
    })
    expect(startupBundleSaveCount).toBeGreaterThanOrEqual(1)
  })

  it('keeps hydrated startup data when background platform refresh returns no rows', async () => {
    platformRowsByLoad = [{ eastmoney: [] }]
    startupBundle = {
      schemaVersion: 1,
      tradingDate: '2026-05-18',
      createdAt: Date.now(),
      platformData: {
        eastmoney: [{ code: '000001', name: '缓存数据', rank: 1, source: 'eastmoney' }],
      },
      stocks: [
        {
          code: '000001',
          name: '缓存数据',
          rank: 1,
          compRank: 1,
          source: 'eastmoney',
          rankTrend: { meta: { change: 8 } },
        },
      ],
    }
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: false })

    expect(summary.fromCache).toBe(true)
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000001' })])
    await vi.waitFor(() => {
      expect(platformLoadCount).toBe(1)
    })
    await new Promise((resolve) => setTimeout(resolve, 10))
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000001' })])
    expect(startupBundleSaveCount).toBe(0)
  })

  it('reports platform item progress during startup loading', async () => {
    blockPlatformLoad = true
    const { dataLoader } = await import('../../dataLoader')

    const loadingPromise = dataLoader.bootstrapInitialData({ force: true })

    await vi.waitFor(() => {
      expect(releasePlatformLoad).toEqual(expect.any(Function))
    })
    expect(dataLoader.getLoadingStatus()).toMatchObject({
      active: true,
      phase: 'platform',
      progress: 13,
      message: '加载平台热榜 2/8...',
    })

    blockPlatformLoad = false
    releasePlatformLoad?.()
    await loadingPromise
  })

  it('reports quote batch progress during startup loading', async () => {
    blockQuoteBatch = true
    const { dataLoader } = await import('../../dataLoader')

    const loadingPromise = dataLoader.bootstrapInitialData({ force: true })

    await vi.waitFor(() => {
      expect(releaseQuoteBatch).toEqual(expect.any(Function))
    })
    expect(dataLoader.getLoadingStatus()).toMatchObject({
      active: true,
      phase: 'quote',
      progress: 51,
      message: '加载行情数据 50/200...',
    })

    blockQuoteBatch = false
    releaseQuoteBatch?.()
    await loadingPromise
  })

  it('preloads RankTrend snapshots while startup quote loading is still in flight', async () => {
    blockQuoteBatch = true
    const { dataLoader } = await import('../../dataLoader')

    const loadingPromise = dataLoader.bootstrapInitialData({ force: true })

    await vi.waitFor(() => {
      expect(releaseQuoteBatch).toEqual(expect.any(Function))
    })
    expect(signalPreloadCount).toBe(1)
    expect(signalApplyCount).toBe(0)

    blockQuoteBatch = false
    releaseQuoteBatch?.()
    await loadingPromise
  })

  it('does not block startup completion on RankTrend signal enrichment', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: true })

    expect(summary.stockCount).toBe(1)
    expect(dataLoader.getLoadingStatus()).toMatchObject({
      active: false,
      phase: 'done',
      progress: 100,
    })
    expect(signalApplyCount).toBe(1)

    blockSignalCalculation = false
    releaseSignalCalculation?.()
    await vi.waitFor(() => {
      expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
        expect.objectContaining({ data: expect.objectContaining({ reason: 'base-merge' }) }),
        expect.objectContaining({ data: expect.objectContaining({ reason: 'signal-enriched' }) }),
      ])
    })
  })

  it('does not block initial startup on intraday volume history loading', async () => {
    blockIntradayVolumeHistory = true
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: true })

    expect(summary.stockCount).toBe(1)
    expect(intradayVolumeHistoryRequestCount).toBe(1)
    expect(dataLoader.getLoadingStatus()).toMatchObject({
      active: false,
      phase: 'done',
      progress: 100,
    })

    blockIntradayVolumeHistory = false
    releaseIntradayVolumeHistory?.()
  })

  it('does not block initial startup on daily volume history loading', async () => {
    vi.useFakeTimers()
    blockVolumeHistory = true
    try {
      const { dataLoader } = await import('../../dataLoader')

      const summaryPromise = dataLoader.bootstrapInitialData({ force: true })
      await vi.advanceTimersByTimeAsync(6000)
      const summary = await summaryPromise

      expect(summary.stockCount).toBe(1)
      expect(volumeHistoryRequestCount).toBe(1)
      expect(dataLoader.getLoadingStatus()).toMatchObject({
        active: false,
        phase: 'done',
        progress: 100,
      })
      expect(dataLayer.getStocks()).toEqual([
        expect.objectContaining({
          code: '000001',
          name: '平安银行',
        }),
      ])
    } finally {
      blockVolumeHistory = false
      releaseVolumeHistory?.()
      vi.useRealTimers()
    }
  })

  it('does not write half-enriched startup bundles before RankTrend signals finish', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(startupBundleSaveCount).toBe(0)

    blockSignalCalculation = false
    releaseSignalCalculation?.()

    await vi.waitFor(() => {
      expect(startupBundleSaveCount).toBe(1)
    })
  })

  it('does not publish signal-enriched when background RankTrend enhancement falls back to base data', async () => {
    signalCalculationError = new Error('signal is aborted without reason')
    signalCalculationError.name = 'AbortError'
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
      expect.objectContaining({
        data: expect.objectContaining({ reason: 'base-merge' }),
      }),
    ])
    expect(dataLayer.getStock('000001')?.rankTrend).toBeUndefined()
  })

  it('merges deferred RankTrend signals after realtime volume-ratio publish changes the loader version', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(dataLayer.getStock('000001')?.rankTrend).toBeUndefined()
    dataLayer.updateStockExtData([
      {
        code: '000001',
        volumeRatio: 1.5,
        volumeRatioMeta: {
          status: 'fresh',
          source: 'daily_snapshot',
          calculatedAt: 1,
          currentVolume: 100,
          historyVolumes: [80, 90],
          capped: false,
        },
      } as any,
    ])
    ;(dataLoader as any).publishStocks(dataLayer.getStocks(), { reason: 'base-merge' })

    blockSignalCalculation = false
    releaseSignalCalculation?.()

    await vi.waitFor(() => {
      expect(dataLayer.getStock('000001')?.rankTrend?.meta?.change).toBe(12)
    })
    expect(dataLayer.getStock('000001')).toMatchObject({
      candidatePoolStatus: 'triggered',
      candidatePoolLabel: '已触发',
      candidatePoolEntryId: 'entry-1',
      candidatePoolSource: 'ranktrend_early_big_move_v3_lifecycle_fusion',
      candidatePoolUpdatedAt: '2026-06-08T10:00:00.000Z',
    })
    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual([
      expect.objectContaining({ data: expect.objectContaining({ reason: 'base-merge' }) }),
      expect.objectContaining({ data: expect.objectContaining({ reason: 'base-merge' }) }),
      expect.objectContaining({ data: expect.objectContaining({ reason: 'signal-enriched' }) }),
    ])
  })

  it('does not let stale background signal enrichment overwrite newer hotlist data', async () => {
    platformRowsByLoad = [
      {
        eastmoney: [{ code: '000001', name: '第一轮', rank: 1, source: 'eastmoney' }],
      },
      {
        eastmoney: [{ code: '000002', name: '第二轮', rank: 1, source: 'eastmoney' }],
      },
    ]
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000001' })])

    blockSignalCalculation = false
    await dataLoader.refreshAll({ force: true, source: 'manual' })
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000002' })])

    releaseSignalCalculation?.()
    await vi.waitFor(() => {
      expect(signalCompletionCount).toBe(2)
    })

    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toHaveLength(3)
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000002' })])
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
    const { loadLimitUpData, loadThsLimitUpPoolData } = await import('../LimitUpFeed')

    const summary = await dataLoader.refreshAll({ force: true, source: 'manual' })

    expect(summary).toEqual(
      expect.objectContaining({
        stockCount: 1,
        platformCount: 1,
        fromCache: false,
      }),
    )
    expect(loadLimitUpData).toHaveBeenCalledTimes(1)
    expect(loadThsLimitUpPoolData).toHaveBeenCalledTimes(1)
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
      await vi.advanceTimersByTimeAsync(1000)

      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopSignalAutoRefresh()
      vi.useRealTimers()
    }
  })

  it('records quote fallback refresh through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { refreshTaskRegistry } = await import('../../refresh/RefreshTaskRuntime')

      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])
      dataLoader.stopQuoteAutoRefresh()
      dataLoader.startQuoteAutoRefresh(1000)

      await vi.advanceTimersByTimeAsync(1000)

      expect(refreshTaskRegistry.getTask('dataLoader.quote')).toMatchObject({
        running: false,
        lastRunAt: expect.any(Number),
        lastSuccessAt: expect.any(Number),
        lastError: null,
        successCount: 1,
        source: 'scheduler',
      })
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopQuoteAutoRefresh()
      vi.useRealTimers()
    }
  })

  it('recalculates RankTrend signals during trading-time quote refresh', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])

    await (dataLoader as any).runQuoteRefresh(50)

    expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)
  })

  it('does not recalculate RankTrend signals outside trading time quote refresh', async () => {
    timeState.tradingTime = false
    const { dataLoader } = await import('../../dataLoader')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])

    await (dataLoader as any).runQuoteRefresh(50)

    expect(rankTrendSignalService.refreshRankTrendSignals).not.toHaveBeenCalled()
  })

  it('skips quote fallback while a full refresh owns the quote HTTP resource', async () => {
    vi.useFakeTimers()
    blockQuoteBatch = true
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { quoteService } = await import('../QuoteService')

      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])
      const refreshPromise = dataLoader.refreshAll({ force: true, source: 'manual' })

      await vi.waitFor(() => {
        expect(releaseQuoteBatch).toEqual(expect.any(Function))
      })

      vi.mocked(quoteService.fetchMergedQuotes).mockClear()
      dataLoader.stopQuoteAutoRefresh()
      dataLoader.startQuoteAutoRefresh(1000)
      await vi.advanceTimersByTimeAsync(1000)

      expect(quoteService.fetchMergedQuotes).not.toHaveBeenCalled()

      blockQuoteBatch = false
      releaseQuoteBatch?.()
      await refreshPromise
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopQuoteAutoRefresh()
      vi.useRealTimers()
    }
  })

  it('records scheduled RankTrend checks through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-08T14:44:59+08:00'))
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { refreshTaskRegistry } = await import('../../refresh/RefreshTaskRuntime')

      dataLoader.stopSignalAutoRefresh()
      ;(dataLoader as any).lastSignalRefreshDate = null
      dataLoader.startSignalAutoRefresh(1000)

      await vi.advanceTimersByTimeAsync(1000)

      expect(refreshTaskRegistry.getTask('dataLoader.ranktrendSignal')).toMatchObject({
        running: false,
        lastRunAt: expect.any(Number),
        lastSuccessAt: expect.any(Number),
        lastError: null,
        successCount: 1,
        source: 'scheduler',
      })
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

  it('serializes manual RankTrend signal refreshes through the ranktrend resource', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')

    const first = dataLoader.refreshRankTrendSignals()

    await vi.waitFor(() => {
      expect(releaseSignalCalculation).toEqual(expect.any(Function))
    })

    const second = dataLoader.refreshRankTrendSignals()
    await Promise.resolve()

    expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

    blockSignalCalculation = false
    releaseSignalCalculation?.()
    await Promise.all([first, second])

    expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(2)
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
      await vi.advanceTimersByTimeAsync(1000)
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

      vi.setSystemTime(new Date('2026-05-08T14:45:30+08:00'))
      await vi.advanceTimersByTimeAsync(1000)
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

      vi.setSystemTime(new Date('2026-05-09T14:44:59+08:00'))
      await vi.advanceTimersByTimeAsync(1000)
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

  it('refreshes volume ratios for realtime quote changed codes', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          volume: 100,
          volumeRatio: 1,
        } as any,
      ])

      realtimeOptions.onQuoteFlushed(['000001'])
      await vi.advanceTimersByTimeAsync(1000)

      expect(dataLayer.getStock('000001')).toMatchObject({
        volumeRatioMeta: expect.objectContaining({
          status: 'unavailable',
          reason: 'insufficient_history',
        }),
      })
      expect(dataLoader.getMerged()).toEqual([expect.objectContaining({ code: '000001' })])
    } finally {
      vi.useRealTimers()
    }
  })

  it('coalesces realtime volume ratio refreshes instead of reading history on every flush', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      dataLayer.setMergedStocks([
        { code: '000001', name: '平安银行', volume: 100, volumeRatio: 1 } as any,
        { code: '000002', name: '万科A', volume: 200, volumeRatio: 1 } as any,
      ])

      void realtimeOptions.onQuoteFlushed(['000001'])
      void realtimeOptions.onQuoteFlushed(['000001', '000002'])
      await Promise.resolve()

      expect(volumeHistoryRequestCount).toBe(0)
      expect(intradayVolumeHistoryRequestCount).toBe(0)

      await vi.advanceTimersByTimeAsync(1000)

      expect(volumeHistoryRequestCount).toBe(1)
      expect(intradayVolumeHistoryRequestCount).toBe(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('writes structured volume ratio metadata during startup merge', async () => {
    quoteBatchResult = new Map([
      [
        '000001',
        {
          price: 10,
          change: 1,
          volume: 200,
          turnover: 2000,
          turnoverRate: 2,
        },
      ],
    ])
    volumeHistoryMapResult = new Map([['000001', [100, 100, 100]]])
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.loadAllPlatforms(true)

    expect(dataLayer.getStock('000001')).toMatchObject({
      volume: 200,
      volumeRatio: 2,
      volumeRatioMeta: expect.objectContaining({
        status: 'fresh',
        source: 'daily_snapshot',
        currentVolume: 200,
      }),
    })
  })
})
