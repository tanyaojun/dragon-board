import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { AppEvents } from '@/types'
import { FRAME_POOL_PROBE_INTERVAL_MS } from '@/config/listPool'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '../../DataLayer'
import { clearVolumeRatioCache } from '../volumeRatioCache'

const platformRows: Record<string, any[]> = {
  eastmoney: [{ code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' }],
}

let platformRowsByLoad: Array<Record<string, any[]>> = []
let fromCache = false
let firstPlatformLoadEmptyCache = false
let platformLoadCount = 0
let quoteError: Error | null = null
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
let startupBundle: any = null
let startupBundleGetCount = 0
let startupBundleSaveCount = 0
let startupBundleWrites: any[] = []
let realtimeOptions: any = null
let realtimeSyncCallCount = 0
let volumeRatioItems: Record<string, any> = {}
let volumeRatioError: Error | null = null
let shouldRefreshPlatformCache = false
let hasFreshPlatformCache = true

const completeSnapshotContext = {
  breathData: { overall: 72 },
  marketData: { upCount: 3200, downCount: 1800 },
  hotThemes: [],
  themeHeatFactors: [],
  rotationAnalysis: null,
  breathHistory: [],
  breathFactors: [],
  marketMode: 'full',
  stocksVersion: 1,
}

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
    shouldRefresh: () => shouldRefreshPlatformCache,
    hasFreshCache: () => hasFreshPlatformCache,
    markRefreshChecked: vi.fn(),
    markRefreshed: vi.fn(),
    retryFailedPlatforms: vi.fn(async () => ({ updated: false, data: {} })),
    getCacheDiagnostics: vi.fn(() => ({
      lastCheckAt: 1000,
      lastReloadAt: 1000,
      lastLoadFromCache: false,
      cacheTimestamp: 1000,
      platforms: { eastmoney: { rowCount: 1, success: true, consecutiveFailures: 0 } },
    })),
    maintenance: vi.fn(),
    clearCache: vi.fn(),
  },
}))

const framePoolState = vi.hoisted(() => ({
  result: { pool: null, reason: 'http-error' } as any,
}))

// 默认降级（pool: null）：既有用例全部走热榜合并池回退路径，断言不受帧池切换影响
vi.mock('../framePoolSource', () => ({
  fetchLatestFramePool: vi.fn(async () => framePoolState.result),
  buildFrameSeedStock: vi.fn((row: any) => ({
    code: String(row.code),
    name: String(row.name || ''),
    platformName: String(row.name || ''),
    price: Number(row.price) || 0,
    change: Number(row.change) || 0,
    volume: Number(row.volume) || 0,
    turnoverRate: Number(row.turnoverRate) || 0,
    platforms: 0,
  })),
  filterPlatformDataToCodes: vi.fn(
    (platformData: Record<string, any[]>, codes: Set<string>) => {
      const filtered: Record<string, any[]> = {}
      for (const [platform, rows] of Object.entries(platformData || {})) {
        if (!Array.isArray(rows)) {
          filtered[platform] = rows
          continue
        }
        const kept = rows.filter((row) => codes.has(String(row?.code || '')))
        if (kept.length) filtered[platform] = kept
      }
      return filtered
    },
  ),
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
      syncRealtimeSubscription() {
        realtimeSyncCallCount++
      }
      isRealtimePrimaryHealthy() {
        return realtimePrimaryHealthy
      }
    },
  }))

vi.mock('../../apiService', () => ({
  apiService: {
    getVolumeRatios: vi.fn(async () => {
      if (volumeRatioError) throw volumeRatioError
      return { ok: true, items: volumeRatioItems }
    }),
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
      signalCompletionCount++
      return stocks.map((stock: any) => ({
        ...stock,
        // 模拟 analyze 后的 enriched 股票：compRank 权威回填；avgRankNum 由前端合并时实时计算
        // （StockMergeCoordinator），analyze 不回填，随 ...stock 原样保留、merge 合并时不得丢失
        compRank: 7,
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
  hasCompleteSnapshotContext: (context: any) =>
    Boolean(
      context?.breathData &&
        Object.keys(context.breathData).length &&
        context?.marketData &&
        Object.keys(context.marketData).length,
    ),
  startupBundleService: {
    read: vi.fn(async () => {
      startupBundleGetCount++
      return startupBundle
    }),
    write: vi.fn(async (bundle) => {
      startupBundleSaveCount++
      startupBundleWrites.push(bundle)
      return true
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
    realtimeSyncCallCount = 0
    startupBundle = null
    startupBundleGetCount = 0
    startupBundleSaveCount = 0
    startupBundleWrites = []
    volumeRatioItems = {}
    volumeRatioError = null
    shouldRefreshPlatformCache = false
    hasFreshPlatformCache = true
    EventManager.clearHistory()
    vi.clearAllMocks()
    clearVolumeRatioCache()
  })

  afterEach(async () => {
    const { dataLoader } = await import('../../dataLoader')
    dataLoader.stopQuoteAutoRefresh()
    dataLoader.stopSignalAutoRefresh()
    dataLoader.stopFailedPlatformRetry()
    const runtime = await import('../../refresh/RefreshTaskRuntime').catch(() => null)
    runtime?.refreshTaskRegistry.resetRuntimeState()
  })

  it('bootstrapInitialData publishes base hotlist rows and returns a structured summary', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { quoteService } = await import('../QuoteService')

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
    expect(quoteService.getQuoteBatch).toHaveBeenCalledWith(
      ['000001'],
      false,
      expect.objectContaining({ onProgress: expect.any(Function) }),
    )
    expect(signalApplyCount).toBe(1)
    expect(dataLoader.getLoadingStatus().active).toBe(false)
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        name: '平安银行',
      }),
    ])
  })

  it('publishes THS L2 money-flow quote fields into merged stocks during startup', async () => {
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
          cddje: 0,
          cddjzb: 0,
          moneyFlowSource: 'ths_l2',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'high',
          sources: ['tencent'],
          confidence: 95,
          timestamp: 1,
        },
      ],
    ])
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    const stock = dataLayer.getStock('600584')
    expect(stock?.code).toBe('600584')
    expect(stock?.turnoverRate).toBe(17.46)
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
      snapshotContext: completeSnapshotContext,
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
    expect(startupBundleWrites.at(-1)?.snapshotContext).toEqual(completeSnapshotContext)
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

  it('startup no longer preloads RankTrend snapshots (后端 analyze 按需提供)', async () => {
    blockQuoteBatch = true
    const { dataLoader } = await import('../../dataLoader')

    const loadingPromise = dataLoader.bootstrapInitialData({ force: true })

    await vi.waitFor(() => {
      expect(releaseQuoteBatch).toEqual(expect.any(Function))
    })
    expect(signalPreloadCount).toBe(0)
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

  it('startup no longer reads volume history locally (后端量比统一计算)', async () => {
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.bootstrapInitialData({ force: true })

    expect(summary.stockCount).toBe(1)
    expect(dataLoader.getLoadingStatus()).toMatchObject({
      active: false,
      phase: 'done',
      progress: 100,
    })
  })

  it('does not write half-enriched startup bundles before RankTrend signals finish', async () => {
    blockSignalCalculation = true
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(startupBundleSaveCount).toBe(0)

    blockSignalCalculation = false
    releaseSignalCalculation?.()

    await vi.waitFor(() => {
      expect(signalCompletionCount).toBe(1)
    })
    expect(startupBundleSaveCount).toBe(0)

    dataLayer.updateBreathData({
      sentiment: { overall: 72, phase: 'rise' },
      marketData: { upCount: 3200, downCount: 1800 },
      timestamp: Date.now(),
    })
    EventManager.emit(AppEvents.BREATH.UPDATED, { timestamp: Date.now() })

    await vi.waitFor(() => {
      expect(startupBundleSaveCount).toBe(1)
    })
    expect(startupBundleWrites[0]?.snapshotContext).toEqual(
      expect.objectContaining({
        breathData: expect.objectContaining({ overall: 72 }),
        marketData: expect.objectContaining({ upCount: 3200, downCount: 1800 }),
      }),
    )
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
      // 根治：mergeSignalEnrichmentByCode 合并时保留权威 compRank（此前漏复制导致综合列 "--"）
      // 与前端合并时实时计算的 avgRankNum（仅东财 rank1/total1 → 100）
      compRank: 7,
      avgRankNum: 100,
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

    // 旧信号增强按 code 合并时不应覆盖已刷新的新数据
    expect(dataLayer.getStocks()).toEqual([expect.objectContaining({ code: '000002' })])
    // 事件历史至少包含 2 次 base-merge + 至少 1 次 signal-enriched
    const mergedEvents = EventManager.getHistory(AppEvents.DATA.MERGED)
    expect(mergedEvents.filter((e: any) => e.data?.reason === 'base-merge')).toHaveLength(2)
    expect(mergedEvents.filter((e: any) => e.data?.reason === 'signal-enriched').length).toBeGreaterThanOrEqual(1)
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

  it('bootstrapInitialData loads limit-up data during startup', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { loadLimitUpData, loadThsLimitUpPoolData } = await import('../LimitUpFeed')

    await dataLoader.bootstrapInitialData({ force: true })

    // 题材面板成分股依赖涨停池扩展数据（连板/涨停时间/封单/开板），
    // 启动直连路径也必须加载涨停池，不能只等定时刷新
    expect(loadLimitUpData).toHaveBeenCalledTimes(1)
    expect(loadThsLimitUpPoolData).toHaveBeenCalledTimes(1)
  })

  it('background startup bundle refresh loads limit-up data', async () => {
    startupBundle = { ...completeSnapshotContext }
    const { dataLoader } = await import('../../dataLoader')
    const { loadLimitUpData, loadThsLimitUpPoolData } = await import('../LimitUpFeed')

    await dataLoader.bootstrapInitialData({ force: false })
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(loadLimitUpData).toHaveBeenCalled()
    expect(loadThsLimitUpPoolData).toHaveBeenCalled()
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

  it('refreshMarketList refreshes the table data scope and syncs themes', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { loadLimitUpData, loadThsLimitUpPoolData } = await import('../LimitUpFeed')
    const { themeFacade } = await import('../../theme/ThemeFacade')

    const summary = await dataLoader.refreshMarketList({ force: true, source: 'manual' })

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
    expect(themeFacade.refreshRuntime).toHaveBeenCalledWith({
      source: 'market-list',
      syncStocks: true,
    })
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        code: '000001',
        candidatePoolStatus: 'triggered',
        candidatePoolLabel: '已触发',
      }),
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

  it('runs scheduled RankTrend refresh every 30 minutes from DataLoader instead of DataTable', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { rankTrendSignalService } = await import('../RankTrendSignalService')

      dataLoader.stopSignalAutoRefresh()
      dataLoader.startSignalAutoRefresh()
      await vi.advanceTimersByTimeAsync(29 * 60 * 1000)

      expect(rankTrendSignalService.refreshRankTrendSignals).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(60 * 1000)

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

  it('does not trigger full-market RankTrend analysis during trading-time quote refresh', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')

    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])

    await (dataLoader as any).runQuoteRefresh(50)

    expect(rankTrendSignalService.refreshRankTrendSignals).not.toHaveBeenCalled()
  })

  it('force reloads expired platform data and recalculates RankTrend during quote refresh', async () => {
    shouldRefreshPlatformCache = true
    hasFreshPlatformCache = false
    const { dataLoader } = await import('../../dataLoader')
    const { platformHotlistService } = await import('../PlatformHotlistService')
    const { rankTrendSignalService } = await import('../RankTrendSignalService')
    const { themeFacade } = await import('../../theme/ThemeFacade')
    dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' } as any])

    await (dataLoader as any).runQuoteRefresh(50)

    expect(platformHotlistService.markRefreshChecked).toHaveBeenCalledTimes(1)
    expect(platformHotlistService.loadPlatforms).toHaveBeenCalledWith(
      expect.any(Array),
      true,
      expect.any(Object),
    )
    expect(platformHotlistService.markRefreshed).toHaveBeenCalledTimes(1)
    // 平台热榜刷新完成后必须重新上报订阅：新进榜股票立即进入调度器刷新范围
    expect(realtimeSyncCallCount).toBeGreaterThan(0)
    expect(themeFacade.refreshRuntime).toHaveBeenCalledWith({
      source: 'dataLoader',
      syncStocks: true,
    })
    expect(rankTrendSignalService.applySignalsToMerged).toHaveBeenCalled()
    expect(rankTrendSignalService.refreshRankTrendSignals).not.toHaveBeenCalled()
  })

  it('exposes platform cache diagnostics through the DataLoader facade', async () => {
    const { dataLoader } = await import('../../dataLoader')

    expect(dataLoader.getPlatformCacheDiagnostics()).toEqual(
      expect.objectContaining({
        lastCheckAt: 1000,
        lastReloadAt: 1000,
        lastLoadFromCache: false,
        platforms: { eastmoney: { rowCount: 1, success: true, consecutiveFailures: 0 } },
      }),
    )
  })

  it('publishes platform status from diagnostics into DataLayer after loading', async () => {
    const { dataLoader } = await import('../../dataLoader')

    await dataLoader.bootstrapInitialData({ force: true })

    expect(dataLayer.getPlatformStatus()).toEqual({
      eastmoney: { rowCount: 1, success: true, consecutiveFailures: 0 },
    })
  })

  it('publishes recovered platform data and status after the one-minute retry tick', async () => {
    const { dataLoader } = await import('../../dataLoader')
    const { platformHotlistService } = await import('../PlatformHotlistService')
    vi.mocked(platformHotlistService.retryFailedPlatforms).mockResolvedValue({
      updated: true,
      data: {
        eastmoney: [{ code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' }],
      },
    })
    vi.mocked(platformHotlistService.getCacheDiagnostics).mockReturnValue({
      lastCheckAt: 1000,
      lastReloadAt: 1000,
      lastLoadFromCache: false,
      cacheTimestamp: 1000,
      platforms: {
        eastmoney: { rowCount: 1, success: true, consecutiveFailures: 0 },
      },
    })

    await (dataLoader as any).retryFailedPlatformsTick()

    expect(dataLayer.getPlatformStatus()).toEqual({
      eastmoney: { rowCount: 1, success: true, consecutiveFailures: 0 },
    })
    expect(dataLayer.getRawPlatforms().eastmoney).toEqual([
      { code: '000001', name: '平安银行', rank: 1, source: 'eastmoney' },
    ])
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

  it('records scheduled RankTrend refreshes through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { refreshTaskRegistry } = await import('../../refresh/RefreshTaskRuntime')

      dataLoader.stopSignalAutoRefresh()
      dataLoader.startSignalAutoRefresh()

      await vi.advanceTimersByTimeAsync(30 * 60 * 1000)

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

  it('keeps scheduled RankTrend refresh running on every 30 minute slot', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { rankTrendSignalService } = await import('../RankTrendSignalService')

      dataLoader.stopSignalAutoRefresh()
      dataLoader.startSignalAutoRefresh()
      await vi.advanceTimersByTimeAsync(30 * 60 * 1000)
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(1)

      await vi.advanceTimersByTimeAsync(30 * 60 * 1000)
      expect(rankTrendSignalService.refreshRankTrendSignals).toHaveBeenCalledTimes(2)
    } finally {
      const { dataLoader } = await import('../../dataLoader')
      dataLoader.stopSignalAutoRefresh()
      vi.useRealTimers()
    }
  })

  it('uses the refresh request trigger when running DataLoader through the unified refresh path', async () => {
    const { dataLoader } = await import('../../dataLoader')

    const summary = await dataLoader.runUpdate({
      kind: 'full',
      source: 'app',
      trigger: 'manual',
      force: true,
    } as any)

    expect(summary).toEqual(expect.objectContaining({ stockCount: 1 }))
    expect(signalApplyCount).toBe(1)
    expect(EventManager.getHistory(AppEvents.DATA.MERGED)).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          data: expect.objectContaining({ reason: 'signal-enriched' }),
        }),
      ]),
    )
    expect(dataLayer.getStocks()).toEqual([
      expect.objectContaining({
        candidatePoolStatus: 'triggered',
        candidatePoolLabel: '已触发',
      }),
    ])
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

  it('keeps startup usable when backend volume ratio is unavailable', async () => {
    volumeRatioError = new Error('volume ratio service unavailable')
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
      const { apiService } = await import('../../apiService')
      volumeRatioItems = {
        '000001': {
          status: 'unavailable',
          source: 'unavailable',
          currentVolume: 100,
          historyVolumes: [],
          reason: 'insufficient_history',
          calculatedAt: 1,
        },
      }
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          volume: 100,
          volumeRatio: 1,
        } as any,
      ])

      ;(dataLoader as any).resetRealtimeVolumeRatioRefreshGate?.()
      realtimeOptions.onQuoteFlushed(['000001'])
      await vi.advanceTimersByTimeAsync(1000)

      expect(apiService.getVolumeRatios).toHaveBeenCalledWith(
        expect.objectContaining({
          stocks: expect.arrayContaining([
            expect.objectContaining({ code: '000001', volume: 100 }),
          ]),
        }),
      )
      expect(dataLayer.getStock('000001')).toMatchObject({
        volumeRatio: 1,
        volumeRatioMeta: expect.objectContaining({
          status: 'stale',
          reason: 'history_unavailable_preserved_previous',
        }),
      })
      expect(dataLoader.getMerged()).toEqual([expect.objectContaining({ code: '000001' })])
    } finally {
      vi.useRealTimers()
    }
  })

  it('coalesces realtime volume ratio refreshes into a single backend call', async () => {
    vi.useFakeTimers()
    try {
      const { dataLoader } = await import('../../dataLoader')
      const { apiService } = await import('../../apiService')
      volumeRatioItems = {
        '000001': { status: 'unavailable', reason: 'insufficient_history', currentVolume: 100, calculatedAt: 1 },
        '000002': { status: 'unavailable', reason: 'insufficient_history', currentVolume: 200, calculatedAt: 1 },
      }
      dataLayer.setMergedStocks([
        { code: '000001', name: '平安银行', volume: 100, volumeRatio: 1 } as any,
        { code: '000002', name: '万科A', volume: 200, volumeRatio: 1 } as any,
      ])

      ;(dataLoader as any).resetRealtimeVolumeRatioRefreshGate?.()
      void realtimeOptions.onQuoteFlushed(['000001'])
      void realtimeOptions.onQuoteFlushed(['000001', '000002'])
      await Promise.resolve()

      expect(apiService.getVolumeRatios).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(1000)

      expect(apiService.getVolumeRatios).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('writes structured volume ratio metadata during startup merge', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-05-08T15:01:00+08:00'))
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
    volumeRatioItems = {
      '000001': {
        value: 2,
        status: 'fresh',
        source: 'daily_snapshot',
        currentVolume: 200,
        expectedVolume: 100,
        historyVolumes: [100, 100, 100],
        rawRatio: 2,
        capped: false,
        calculatedAt: 1,
      },
    }
    try {
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
    } finally {
      vi.useRealTimers()
    }
  })

  describe('mergeData frame-pool membership', () => {
    beforeEach(() => {
      // dataLayer.reset() 不清 provenance（任务 1 语义：跨测试显式归零，避免上一用例残留）
      dataLayer.setListPoolProvenance(null)
      // platformRows 夹具含 000001；帧池另有 600000/300750 无平台行（验证种子补齐）
      framePoolState.result = {
        pool: {
          codes: new Set(['600000', '300750', '000001']),
          slotTime: '10:30',
          tradingDate: '2026-09-21',
          rowsByCode: new Map([
            ['600000', { code: '600000', name: '浦发银行', price: 12.34 }],
            ['300750', { code: '300750', name: '宁德时代', price: 300 }],
            ['000001', { code: '000001', name: '平安银行', price: 15 }],
          ]),
        },
      }
    })

    afterEach(() => {
      framePoolState.result = { pool: null, reason: 'http-error' }
    })

    it('membership 等于帧池 codes：平台行被过滤、帧行种子补齐', async () => {
      quoteBatchResult = new Map([['600000', { price: 12.5, change: 0.16 }]])
      const { dataLoader } = await import('../../dataLoader')

      await dataLoader.loadAllPlatforms(true)

      const stocks = dataLayer.getStocks()
      const codes = new Set(stocks.map((s: any) => s.code))
      expect(codes).toEqual(new Set(['600000', '300750', '000001']))
      // 600000 无平台行 → 来自帧行种子，名称取帧行
      const seedStock = stocks.find((s: any) => s.code === '600000')
      expect(seedStock?.name).toBe('浦发银行')
    })

    it('帧池模式打 provenance frame-pool + slotTime', async () => {
      const { dataLoader } = await import('../../dataLoader')

      await dataLoader.loadAllPlatforms(true)

      const provenance = dataLayer.getListPoolProvenance()
      expect(provenance?.source).toBe('frame-pool')
      expect(provenance?.slotTime).toBe('10:30')
    })

    it('帧池不可用回退热榜合并池并打 provenance', async () => {
      framePoolState.result = { pool: null, reason: 'http-error', message: 'boom' }
      const { dataLoader } = await import('../../dataLoader')

      await dataLoader.loadAllPlatforms(true)

      const provenance = dataLayer.getListPoolProvenance()
      expect(provenance?.source).toBe('hotlist-merged')
      expect(provenance?.degradeReason).toBe('http-error')
      // membership 回到热榜合并池（现有夹具 platformRows 的 000001）
      const codes = new Set(dataLayer.getStocks().map((s: any) => s.code))
      expect(codes.has('000001')).toBe(true)
    })
  })

  describe('maybeRefreshFramePool slot probe', () => {
    // 帧池夹具：codes/rowsByCode 由同一 rows 派生，保证 membership 与种子行一致
    const framePoolAt = (slotTime: string, rows: Array<{ code: string; name: string }>) => ({
      pool: {
        codes: new Set(rows.map((row) => row.code)),
        slotTime,
        tradingDate: '2026-09-21',
        rowsByCode: new Map(
          rows.map((row) => [row.code, { code: row.code, name: row.name, price: 12 }]),
        ),
      },
    })

    beforeEach(async () => {
      // dataLayer.reset() 不清 provenance（沿用 Task 3 用例模式：涉 provenance 显式归零）
      dataLayer.setListPoolProvenance(null)
      // 单例探测门限跨用例残留：显式归零保证每用例首次探测必过门限；
      // 门限行为本身由「间隔门限」用例经 fake timers 推进时钟单独锁定
      const { dataLoader } = await import('../../dataLoader')
      ;(dataLoader as any).lastFramePoolProbeAt = 0
      ;(dataLoader as any).framePoolProbeRunning = false
      vi.useFakeTimers()
      vi.setSystemTime(new Date('2027-01-04T09:30:00+08:00'))
    })

    afterEach(async () => {
      vi.useRealTimers()
      framePoolState.result = { pool: null, reason: 'http-error' }
    })

    it('同槽不重复重建；新槽出现则重建并更新 provenance', async () => {
      framePoolState.result = framePoolAt('10:30', [{ code: '600000', name: '浦发银行' }])
      const { dataLoader } = await import('../../dataLoader')
      const { fetchLatestFramePool } = await import('../framePoolSource')

      // 1. 先驱动一次帧池 merge，进入 frame-pool provenance 状态
      await dataLoader.loadAllPlatforms(true)
      expect(dataLayer.getListPoolProvenance()).toMatchObject({
        source: 'frame-pool',
        slotTime: '10:30',
      })
      const platformLoadsAfterSeed = platformLoadCount
      vi.mocked(fetchLatestFramePool).mockClear()

      // 2. 行情刷新 tick：探测到同槽 → 不触发重建（platformLoad 不变、provenance 不变）
      await (dataLoader as any).runQuoteRefresh(50)
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(1)
      expect(platformLoadCount).toBe(platformLoadsAfterSeed)
      expect(dataLayer.getListPoolProvenance()?.slotTime).toBe('10:30')

      // 3. 后端切到新帧槽 + 推进门限 → 以帧池重建列表并更新 provenance/membership
      framePoolState.result = framePoolAt('11:00', [
        { code: '600000', name: '浦发银行' },
        { code: '000001', name: '平安银行' },
      ])
      await vi.advanceTimersByTimeAsync(FRAME_POOL_PROBE_INTERVAL_MS + 1)
      await (dataLoader as any).runQuoteRefresh(50)
      expect(dataLayer.getListPoolProvenance()).toMatchObject({
        source: 'frame-pool',
        slotTime: '11:00',
      })
      const codes = new Set(dataLayer.getStocks().map((s: any) => s.code))
      expect(codes).toEqual(new Set(['600000', '000001']))
      expect(platformLoadCount).toBe(platformLoadsAfterSeed + 1)
    })

    it('探测失败（http-error）静默跳过，不影响当前列表与 provenance，且下一间隔仍会再探', async () => {
      framePoolState.result = framePoolAt('10:30', [{ code: '600000', name: '浦发银行' }])
      const { dataLoader } = await import('../../dataLoader')
      const { fetchLatestFramePool } = await import('../framePoolSource')

      await dataLoader.loadAllPlatforms(true)
      const stocksBefore = dataLayer.getStocks()
      const provenanceBefore = dataLayer.getListPoolProvenance()

      framePoolState.result = { pool: null, reason: 'http-error', message: 'boom' }
      vi.mocked(fetchLatestFramePool).mockClear()

      // 探测失败返回结构化 null：不抛异常、不改列表与 provenance，行情链正常完成
      await expect((dataLoader as any).runQuoteRefresh(50)).resolves.toBeUndefined()
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(1)
      expect(dataLayer.getListPoolProvenance()).toEqual(provenanceBefore)
      expect(dataLayer.getStocks()).toEqual(stocksBefore)

      // 失败不卡死门限：推进一个间隔后仍会再探（下次再探）
      await vi.advanceTimersByTimeAsync(FRAME_POOL_PROBE_INTERVAL_MS + 1)
      await (dataLoader as any).runQuoteRefresh(50)
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(2)
    })

    it('探测间隔门限内不重复探测（1min 低频跟随 30min 帧槽）', async () => {
      framePoolState.result = framePoolAt('10:30', [{ code: '600000', name: '浦发银行' }])
      const { dataLoader } = await import('../../dataLoader')
      const { fetchLatestFramePool } = await import('../framePoolSource')

      await dataLoader.loadAllPlatforms(true)
      vi.mocked(fetchLatestFramePool).mockClear()

      // 门限内连续两跳只探测一次，避免 10s 行情刷新链反复打后端
      await (dataLoader as any).runQuoteRefresh(50)
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(1)
      await (dataLoader as any).runQuoteRefresh(50)
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(1)

      // 推进门限后恢复探测；同槽仍不重建（platformLoad 保持 seed merge 那一次）
      await vi.advanceTimersByTimeAsync(FRAME_POOL_PROBE_INTERVAL_MS + 1)
      await (dataLoader as any).runQuoteRefresh(50)
      expect(fetchLatestFramePool).toHaveBeenCalledTimes(2)
      expect(platformLoadCount).toBe(1)
    })
  })

  describe('publishStartupBundle provenance', () => {
    it('启动缓存发布打 startup-bundle provenance', async () => {
      blockPlatformLoad = true
      startupBundle = {
        schemaVersion: 1,
        tradingDate: '2026-05-18',
        createdAt: Date.now(),
        snapshotContext: completeSnapshotContext,
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
        // 缓存快发布必须立即可观测 startup-bundle 来源（平台加载被 block，后台刷新不会先覆盖）
        await vi.waitFor(() => {
          expect(dataLayer.getListPoolProvenance()?.source).toBe('startup-bundle')
        })
      } finally {
        blockPlatformLoad = false
        releasePlatformLoad?.()
        await summaryPromise.catch(() => undefined)
      }
    })
  })
})
