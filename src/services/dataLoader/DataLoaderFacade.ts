import { debugLog } from '@/utils/logger'
// src/services/dataLoader/DataLoaderFacade.ts

import { ref, readonly } from 'vue'
import { dataLayer } from '../DataLayer'
import type { MergedStock } from '@/types'
import { themeFacade } from '../theme/ThemeFacade'
import { isTradingTime } from '@/utils/time'
import { EventManager } from '../../utils/eventManager'
import { AppEvents } from '../../types'
import {
  DEFAULT_PLATFORMS,
  INTRADAY_VOLUME_SNAPSHOT_TYPES as DEFAULT_INTRADAY_VOLUME_SNAPSHOT_TYPES,
  PLATFORM_REFRESH_INTERVAL_MS,
  QUOTE_BATCH_SIZE as DEFAULT_QUOTE_BATCH_SIZE,
  QUOTE_REFRESH_INTERVAL_MS,
} from './constants'
import { extraDataProjector } from './ExtraDataProjector'
import {
  loadLimitUpData as loadLimitUpFeedData,
  loadThsLimitUpPoolData,
} from './LimitUpFeed'
import { platformHotlistService } from './PlatformHotlistService'
import { quoteService } from './QuoteService'
import { rankTrendSignalService } from './RankTrendSignalService'
import { RealtimeQuoteCoordinator } from './RealtimeQuoteCoordinator'
import { refreshResourceLocks } from '../refresh/RefreshResourceLocks'
import { refreshScheduler } from '../refresh/RefreshTaskRuntime'
import type { RefreshRequest } from '../refresh/types'
import { startupBundleService } from './StartupBundleService'
import { stockHotnessService } from './StockHotnessService'
import { stockMergeCoordinator } from './StockMergeCoordinator'
import { VolumeHistoryService } from './VolumeHistoryService'
import { VolumeRatioUpdateService } from './VolumeRatioUpdateService'
import type {
  DataLoaderBootstrapOptions,
  DataLoaderRefreshOptions,
  DataLoaderRunSummary,
  LoaderState,
  LoadingStatus,
  MergedQuoteData,
  PlatformLoadProgress,
  QuoteBatchProgress,
  StockSignalUpdate,
} from './types'
import type { RankTrendPreparedSnapshot } from '../RankTrendAnalyzer'

export type { MergedQuoteData } from './types'

const REALTIME_VOLUME_RATIO_REFRESH_DELAY_MS = 1000
const STARTUP_VOLUME_HISTORY_TIMEOUT_MS = 5000

type SignalCalculationResult = {
  merged: any[]
  enriched: boolean
}

/**
 * 业务编排层
 * 职责：协调数据加载、合并计算、缓存策略、行情获取
 */
class DataLoaderService {
  private state = ref<LoaderState>({
    initialized: false,
    platforms: [...DEFAULT_PLATFORMS],
    data: {},
    loading: false,
    loadingProgress: 0,
    loadingMessage: '',
    lastUpdate: null,
  })

  private loadingStatus = ref<LoadingStatus>({
    active: false,
    progress: 0,
    message: '',
    startTime: null,
  })

  public readonly isLoading = readonly(this.loadingStatus)

  private isLoadingDetails = false
  private destroyed = false
  private quoteProgressCompletedCodes = 0
  private runTimings: Record<string, number> = {}
  private stockPublishVersion = 0
  private pendingVolumeRatioCodes = new Set<string>()
  private volumeRatioRefreshTimer: ReturnType<typeof setTimeout> | null = null
  private volumeRatioRefreshRunning = false

  private readonly INTRADAY_VOLUME_SNAPSHOT_TYPES = DEFAULT_INTRADAY_VOLUME_SNAPSHOT_TYPES
  private realtimeCoordinator: RealtimeQuoteCoordinator
  private volumeHistoryService: VolumeHistoryService
  private volumeRatioUpdateService: VolumeRatioUpdateService

  private readonly PLATFORM_REFRESH_INTERVAL = PLATFORM_REFRESH_INTERVAL_MS // 30分钟
  private readonly startupProgress = {
    platformStart: 5,
    platformEnd: 35,
    historyStart: 35,
    historyEnd: 45,
    quoteStart: 45,
    quoteEnd: 70,
    mergeStart: 70,
    mergeEnd: 80,
    signalStart: 80,
    signalEnd: 95,
  } as const

  constructor() {
    debugLog('[DataLoader] 初始化完成')
    this.realtimeCoordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => this.getAllHotCodes(),
      onQuoteFlushed: (codes) => this.handleRealtimeQuoteFlushed(codes),
    })
    this.volumeHistoryService = new VolumeHistoryService(this.INTRADAY_VOLUME_SNAPSHOT_TYPES)
    this.volumeRatioUpdateService = new VolumeRatioUpdateService({
      volumeHistoryService: this.volumeHistoryService,
    })
    this.startQuoteAutoRefresh() // 自动启动行情刷新
    this.startSignalAutoRefresh()
  }

  private syncRealtimeSubscription() {
    this.realtimeCoordinator.syncRealtimeSubscription()
  }

  private isRealtimePrimaryHealthy(): boolean {
    return this.realtimeCoordinator.isRealtimePrimaryHealthy()
  }

  private handleRealtimeQuoteFlushed(codes: string[]): void {
    const validCodes = codes.filter((code) => code && code.length === 6)
    validCodes.forEach((code) => this.pendingVolumeRatioCodes.add(code))
    this.scheduleRealtimeVolumeRatioRefresh()
  }

  private scheduleRealtimeVolumeRatioRefresh(): void {
    if (this.volumeRatioRefreshTimer || this.volumeRatioRefreshRunning) return
    this.volumeRatioRefreshTimer = setTimeout(() => {
      this.volumeRatioRefreshTimer = null
      void this.flushRealtimeVolumeRatioRefresh()
    }, REALTIME_VOLUME_RATIO_REFRESH_DELAY_MS)
  }

  private async flushRealtimeVolumeRatioRefresh(): Promise<void> {
    if (this.volumeRatioRefreshRunning) return
    const codes = Array.from(this.pendingVolumeRatioCodes)
    this.pendingVolumeRatioCodes.clear()
    if (!codes.length) return

    this.volumeRatioRefreshRunning = true
    try {
      await this.updateVolumeRatios(codes)
    } finally {
      this.volumeRatioRefreshRunning = false
      if (this.pendingVolumeRatioCodes.size > 0) {
        this.scheduleRealtimeVolumeRatioRefresh()
      }
    }
  }

  private async maybeRefreshPlatformCache(): Promise<boolean> {
    if (!platformHotlistService.shouldRefresh(this.PLATFORM_REFRESH_INTERVAL)) {
      return false
    }

    if (!platformHotlistService.hasFreshCache()) {
      await this.loadAllPlatforms(true)
      await this.loadLimitUpData(true)
      await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
      platformHotlistService.markRefreshed()
      return true
    }

    platformHotlistService.markRefreshed()
    return false
  }

  // ========== 加载状态管理 ==========
  private setLoading(
    active: boolean,
    message: string = '',
    progress: number = 0,
    phase?: LoadingStatus['phase'],
  ) {
    this.loadingStatus.value = {
      active,
      progress,
      message,
      startTime: active ? Date.now() : null,
      phase,
    }
    this.state.value.loading = active
    this.state.value.loadingProgress = progress
    this.state.value.loadingMessage = message
  }

  private updateProgress(progress: number, message: string, phase?: LoadingStatus['phase']) {
    this.loadingStatus.value.progress = progress
    this.loadingStatus.value.message = message
    this.loadingStatus.value.phase = phase
    this.state.value.loadingProgress = progress
    this.state.value.loadingMessage = message
  }

  private mapProgress(start: number, end: number, completed: number, total: number): number {
    if (!Number.isFinite(total) || total <= 0) return start
    const ratio = Math.max(0, Math.min(1, completed / total))
    return Math.round(start + (end - start) * ratio)
  }

  private reportPlatformProgress(progress: PlatformLoadProgress) {
    this.updateProgress(
      this.mapProgress(
        this.startupProgress.platformStart,
        this.startupProgress.platformEnd,
        progress.completed,
        progress.total,
      ),
      `加载平台热榜 ${progress.completed}/${progress.total}...`,
      'platform',
    )
  }

  private reportQuoteProgress(progress: QuoteBatchProgress) {
    if (progress.completedCodes < this.quoteProgressCompletedCodes) return
    this.quoteProgressCompletedCodes = progress.completedCodes

    this.updateProgress(
      this.mapProgress(
        this.startupProgress.quoteStart,
        this.startupProgress.quoteEnd,
        progress.completedCodes,
        progress.totalCodes,
      ),
      `加载行情数据 ${progress.completedCodes}/${progress.totalCodes}...`,
      'quote',
    )
  }

  private publishStocks(
    stocks: any[],
    meta: {
      reason:
        | 'base-merge'
        | 'signal-enriched'
        | 'manual-signal-update'
        | 'hotness-recalculated'
      startupCache?: DataLoaderRunSummary['startupCache']
    },
  ): number {
    const publishVersion = ++this.stockPublishVersion
    dataLayer.setMergedStocks(stocks)
    EventManager.emit(AppEvents.DATA.MERGED, {
      count: stocks.length,
      timestamp: Date.now(),
      reason: meta.reason,
      startupCache: meta.startupCache,
    })
    return publishVersion
  }

  private summarizeRun(startTime: number, fromCache: boolean): DataLoaderRunSummary {
    const platformCount = Object.values(this.state.value.data || {}).filter(
      (rows) => Array.isArray(rows) && rows.length > 0,
    ).length

    return {
      stockCount: dataLayer.getStocks().length,
      platformCount,
      fromCache,
      elapsedMs: Date.now() - startTime,
      timings: { ...this.runTimings },
    }
  }

  private summarizeStartupBundleRun(startTime: number, bundle: any): DataLoaderRunSummary {
    const platformCount = Object.values(bundle.platformData || {}).filter(
      (rows) => Array.isArray(rows) && rows.length > 0,
    ).length
    const createdAt = Number(bundle.createdAt) || 0

    return {
      stockCount: dataLayer.getStocks().length,
      platformCount,
      fromCache: true,
      elapsedMs: Date.now() - startTime,
      timings: { ...this.runTimings },
      startupCache: {
        hit: true,
        stale: Boolean(bundle.cacheMeta?.stale),
        ageMs: createdAt ? Date.now() - createdAt : undefined,
        backgroundRefresh: true,
      },
    }
  }

  private async measureStartupStep<T>(name: string, task: () => Promise<T>): Promise<T> {
    const start = Date.now()
    try {
      return await task()
    } finally {
      this.runTimings[name] = Date.now() - start
    }
  }

  private async withTimeout<T>(task: Promise<T>, timeoutMs: number, label: string): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | null = null
    try {
      return await Promise.race([
        task,
        new Promise<T>((_, reject) => {
          timer = setTimeout(() => {
            reject(new Error(`${label} timeout after ${timeoutMs}ms`))
          }, timeoutMs)
        }),
      ])
    } finally {
      if (timer) clearTimeout(timer)
    }
  }

  private async loadPlatformAndMerge(
    force = false,
    options: {
      includeLimitUpData?: boolean
      allowWhileLoading?: boolean
      deferSignalEnrichment?: boolean
      deferIntradayVolumeHistory?: boolean
      preserveExistingOnEmpty?: boolean
    } = {},
  ): Promise<DataLoaderRunSummary> {
    const locked = await refreshResourceLocks.runExclusive(
      'hotlist-platform',
      () => this.doLoadPlatformAndMerge(force, options),
    )
    return locked.value!
  }

  private publishStartupBundle(bundle: any, startTime: number): DataLoaderRunSummary {
    this.state.value.data = bundle.platformData || {}
    this.state.value.lastUpdate = Number(bundle.createdAt) || Date.now()
    dataLayer.updatePlatforms(this.state.value.data)
    this.publishStocks(bundle.stocks || [], {
      reason: 'base-merge',
      startupCache: {
        hit: true,
        stale: Boolean(bundle.cacheMeta?.stale),
        ageMs: Number(bundle.createdAt) ? Date.now() - Number(bundle.createdAt) : undefined,
        backgroundRefresh: true,
      },
    })
    this.syncRealtimeSubscription()
    return this.summarizeStartupBundleRun(startTime, bundle)
  }

  private async writeStartupBundle(summary: DataLoaderRunSummary): Promise<void> {
    const stocks = dataLayer.getStocks()
    if (!stocks.length) return

    await startupBundleService.write({
      platformData: this.state.value.data || {},
      stocks,
      summary,
    })
  }

  private refreshStartupBundleInBackground(force: boolean): void {
    void this.loadPlatformAndMerge(force, {
      allowWhileLoading: true,
      deferSignalEnrichment: true,
      deferIntradayVolumeHistory: true,
      preserveExistingOnEmpty: true,
    })
      .catch((error) => {
        console.warn('[DataLoader] 后台刷新启动快照包失败:', error)
      })
  }

  private async doLoadPlatformAndMerge(
    force = false,
    options: {
      includeLimitUpData?: boolean
      allowWhileLoading?: boolean
      deferSignalEnrichment?: boolean
      deferIntradayVolumeHistory?: boolean
      preserveExistingOnEmpty?: boolean
    } = {},
  ): Promise<DataLoaderRunSummary> {
    const startTime = Date.now()
    let fromCache = false
    this.runTimings = {}

    if (this.destroyed) return this.summarizeRun(startTime, fromCache)
    if (this.state.value.loading && !force && !options.allowWhileLoading) {
      if (dataLayer.getStocks().length > 0) return this.summarizeRun(startTime, fromCache)
      this.state.value.loading = false
    }

    const platforms = this.state.value.platforms
    const result = await this.measureStartupStep('platform', () =>
      platformHotlistService
        .loadPlatforms(platforms, force, {
          onProgress: (progress) => this.reportPlatformProgress(progress),
        })
        .catch((error) => {
          console.warn('[DataLoader] 平台热榜加载失败，继续进入空数据状态:', error)
          return {
            data: {} as Record<string, any[]>,
            timestamp: Date.now(),
            fromCache: false,
          }
        }),
    )
    fromCache = result.fromCache

    if (result.fromCache) {
      const hasCachedRows = Object.values(result.data || {}).some(
        (rows) => Array.isArray(rows) && rows.length > 0,
      )
      if (!hasCachedRows && !dataLayer.getStocks().length) {
        platformHotlistService.clearCache()
        return this.doLoadPlatformAndMerge(true, options)
      }
    }

    const hasRows = this.hasPlatformRows(result.data)
    if (!hasRows && options.preserveExistingOnEmpty && dataLayer.getStocks().length > 0) {
      console.warn('[DataLoader] 后台平台刷新无有效数据，保留启动缓存数据')
      return {
        ...this.summarizeRun(startTime, fromCache),
        degraded: true,
        degradeReason: 'empty-platform-refresh',
      }
    }

    this.updateProgress(this.startupProgress.historyStart, '加载平台数据完成', 'platform')
    this.state.value.data = result.data
    this.state.value.lastUpdate = result.timestamp
    dataLayer.updatePlatforms(result.data)
    const rankTrendSnapshotPromise = options.deferSignalEnrichment
      ? this.preloadRankTrendSnapshotsInBackground(Array.from(this.getAllHotCodes()))
      : undefined
    if (options.includeLimitUpData) {
      await this.measureStartupStep('limitUp', () => this.loadLimitUpData(force))
    }
    await this.mergeData({
      deferSignalEnrichment: options.deferSignalEnrichment,
      deferIntradayVolumeHistory: options.deferIntradayVolumeHistory,
      rankTrendSnapshotPromise,
    })

    const summary = this.summarizeRun(startTime, fromCache)
    debugLog('[DataLoader] 启动加载耗时', summary)
    return summary
  }

  async bootstrapInitialData(
    options: DataLoaderBootstrapOptions = {},
  ): Promise<DataLoaderRunSummary> {
    const startTime = Date.now()
    this.quoteProgressCompletedCodes = 0
    this.setLoading(true, '加载平台热榜...', this.startupProgress.platformStart, 'platform')
    try {
      if (!options.force) {
        const bundle = await this.measureStartupStep('startupCache', () => startupBundleService.read())
        if (bundle) {
          this.updateProgress(100, '已从缓存恢复，后台刷新中...', 'cache')
          const summary = this.publishStartupBundle(bundle, startTime)
          this.refreshStartupBundleInBackground(true)
          return summary
        }
      }

      const summary = await this.loadPlatformAndMerge(options.force ?? false, {
        allowWhileLoading: true,
        deferSignalEnrichment: true,
        deferIntradayVolumeHistory: true,
      })
      this.updateProgress(100, '完成', 'done')
      return summary
    } finally {
      this.setLoading(false, '', 100, 'done')
    }
  }

  async refreshAll(options: DataLoaderRefreshOptions = {}): Promise<DataLoaderRunSummary> {
    void options.source
    this.quoteProgressCompletedCodes = 0
    this.setLoading(true, '加载平台热榜...', this.startupProgress.platformStart, 'platform')
    try {
      const summary = await this.loadPlatformAndMerge(options.force ?? false, {
        includeLimitUpData: true,
        allowWhileLoading: true,
      })
      await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
      this.updateProgress(100, '完成', 'done')
      return summary
    } finally {
      this.setLoading(false, '', 100, 'done')
    }
  }

  // ========== RefreshManager/Coordinator 接口 ==========
  async runUpdate(request?: RefreshRequest): Promise<DataLoaderRunSummary | void> {
    if (this.destroyed) return
    const source = request?.trigger === 'manual' ? 'manual' : 'timer'
    return this.refreshAll({ force: request?.force ?? true, source })
  }

  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    platformHotlistService.maintenance()
  }

  // ========== 行情服务 ==========
  /**
   * 启动行情自动刷新
   */
  startQuoteAutoRefresh(
    interval: number = QUOTE_REFRESH_INTERVAL_MS,
    batchSize: number = DEFAULT_QUOTE_BATCH_SIZE,
  ): void {
    refreshScheduler.registerRunner('dataLoader.quote', () => this.runQuoteRefresh(batchSize))
    refreshScheduler.startTask('dataLoader.quote', interval)
  }

  private async runQuoteRefresh(batchSize: number = DEFAULT_QUOTE_BATCH_SIZE): Promise<void> {
    if (!isTradingTime(new Date())) return

    const stocks = dataLayer.getStocks()
    if (!stocks.length) return

    const allStockCodes = stocks
      .map((s: any) => s.code)
      .filter((code: string) => code && code.length === 6 && code !== '000000')

    if (allStockCodes.length === 0) return

    if (this.isRealtimePrimaryHealthy()) {
      const quoteResult = await refreshResourceLocks.runExclusive(
        'quote-http',
        () => this.fetchMergedQuotes(allStockCodes, { force: false }),
        { skipIfLocked: true },
      )

      if (quoteResult.executed) {
        const quotes = quoteResult.value ?? new Map()
        if (quotes.size > 0) {
          dataLayer.applyRealtimeQuoteBatch(
            Array.from(quotes.entries()).map(([code, quote]) => ({
              code,
              ...quote,
            })),
          )
        }
      }

      await this.updateVolumeRatios(allStockCodes)
      const platformRefreshed = await this.maybeRefreshPlatformCache()
      if (!platformRefreshed) {
        await this.refreshRankTrendSignals()
      }
      return
    }

    // 缩短批次延迟
    for (let i = 0; i < allStockCodes.length; i += batchSize) {
      const batchCodes = allStockCodes.slice(i, i + batchSize)
      const quoteResult = await refreshResourceLocks.runExclusive(
        'quote-http',
        () => this.fetchMergedQuotes(batchCodes, { force: false }),
        { skipIfLocked: true },
      )
      if (!quoteResult.executed) return

      const quotes = quoteResult.value ?? new Map()

      if (quotes.size > 0) {
        dataLayer.applyRealtimeQuoteBatch(
          Array.from(quotes.entries()).map(([code, quote]) => ({
            code,
            ...quote,
          })),
        )
      }

      if (i + batchSize < allStockCodes.length) {
        await new Promise((resolve) => setTimeout(resolve, 100)) // 500 -> 100
      }
    }

    // 更新量比
    if (allStockCodes.length) {
      await this.updateVolumeRatios(allStockCodes)
    }

    const platformRefreshed = await this.maybeRefreshPlatformCache()
    if (!platformRefreshed) {
      await this.refreshRankTrendSignals()
    }

    debugLog('[DataLoader] 行情刷新完成')
  }

  /**
   * 更新指定股票的量比
   */
  private async updateVolumeRatios(codes: string[]): Promise<void> {
    try {
      const summary = await this.volumeRatioUpdateService.updateVolumeRatios(codes)
      if (summary.updated > 0) {
        debugLog(
          `[DataLoader] 更新量比: ${summary.updated} 只股票，异常 ${summary.suspicious}，不可用 ${summary.unavailable}`,
        )
        this.publishStocks(dataLayer.getStocks(), { reason: 'base-merge' })
      }
    } catch (error) {
      console.warn('[DataLoader] 更新量比失败:', error)
    }
  }

  /**
   * 停止行情自动刷新
   */
  stopQuoteAutoRefresh(): void {
    refreshScheduler.stopTask('dataLoader.quote')
  }

  startSignalAutoRefresh(interval: number = PLATFORM_REFRESH_INTERVAL_MS): void {
    refreshScheduler.registerRunner('dataLoader.ranktrendSignal', () => this.refreshRankTrendSignals())
    refreshScheduler.startTask('dataLoader.ranktrendSignal', interval)
  }

  stopSignalAutoRefresh(): void {
    refreshScheduler.stopTask('dataLoader.ranktrendSignal')
  }

  /**
   * 获取合并的行情数据
   */
  async fetchMergedQuotes(
    codes: string[],
    options: { force?: boolean } = {},
  ): Promise<Map<string, MergedQuoteData>> {
    return quoteService.fetchMergedQuotes(codes, options)
  }
  /**
   * 获取单只股票行情（带量比计算）
   */
  async getQuote(code: string, force = false): Promise<MergedQuoteData | null> {
    return quoteService.getQuote(code, force)
  }

  /**
   * 批量获取行情（带量比计算）
   */
  async getQuotes(codes: string[], force = false): Promise<Map<string, any>> {
    return quoteService.getQuotes(codes, force)
  }

  // ========== 原有初始化方法 ==========
  async init(autoLoad = true) {
    if (this.state.value.initialized) return
    if (autoLoad) await this.bootstrapInitialData()
    this.state.value.initialized = true
  }

  // ========== 手动刷新 ==========
  private async handleFullRefresh(force = false) {
    try {
      await this.refreshAll({ force, source: 'manual' })
      return true
    } catch (error) {
      console.error('[DataLoader] ❌ 刷新失败:', error)
      this.setLoading(false, '加载失败', 0, 'error')
      throw error
    }
  }

  // ========== 加载平台数据 ==========
  async loadAllPlatforms(force = false): Promise<Record<string, any[]> | void> {
    await this.loadPlatformAndMerge(force)
    return this.state.value.data
  }

  clearPlatformCache() {
    platformHotlistService.clearCache()
  }

  async loadLimitUpData(force = false): Promise<void> {
    void force
    await loadLimitUpFeedData()
    await loadThsLimitUpPoolData()
  }

  // ========== 加载行情数据 ==========
  private async getQuoteBatch(
    codes: string[],
    force = false,
    options: { onProgress?: (progress: QuoteBatchProgress) => void } = {},
  ): Promise<Map<string, any>> {
    return quoteService.getQuoteBatch(codes, force, options)
  }

  // ========== 加载行情数据 ==========
  async loadStockDetails(force = false): Promise<Map<string, any> | void> {
    if (this.destroyed || this.isLoadingDetails) return
    this.isLoadingDetails = true

    try {
      const allCodes = this.getAllHotCodes()
      if (allCodes.size === 0) return

      const codesArray = Array.from(allCodes)
      this.updateProgress(this.startupProgress.quoteStart, `加载行情数据 ${codesArray.length} 只...`, 'quote')
      const quoteResult = await refreshResourceLocks.runExclusive(
        'quote-http',
        () => this.getQuoteBatch(codesArray, force, {
          onProgress: (progress) => this.reportQuoteProgress(progress),
        }),
      )
      const quotes = quoteResult.value ?? new Map()

      return quotes
    } catch (error) {
      console.error('[DataLoader] 加载行情详情失败:', error)
      if (error instanceof Error && error.name === 'AbortError') {
        return new Map()
      }
      throw error
    } finally {
      this.isLoadingDetails = false
    }
  }

  private getAllHotCodes(): Set<string> {
    return platformHotlistService.getAllHotCodes(this.state.value.data || {})
  }

  private hasPlatformRows(data: Record<string, any[]> | null | undefined): boolean {
    return Object.values(data || {}).some((rows) => Array.isArray(rows) && rows.length > 0)
  }

  getMerged() {
    return dataLayer.getStocks()
  }

  getMergedWithVersion() {
    return dataLayer.getStocksWithVersion()
  }

  // ========== 合并计算 ==========
  /**
   * 合并数据主入口
   */
  async mergeData(
    options: {
      deferSignalEnrichment?: boolean
      deferIntradayVolumeHistory?: boolean
      rankTrendSnapshotPromise?: Promise<RankTrendPreparedSnapshot[]>
    } = {},
  ): Promise<any[]> {
    // 1. 获取历史成交量索引
    const allCodes = this.getAllHotCodes()
    const codesArray = Array.from(allCodes)
    this.updateProgress(this.startupProgress.historyStart, '加载历史成交量索引...', 'merge')
    const volumeHistoryMap = await this.measureStartupStep('history', () =>
      this.withTimeout(
        this.buildVolumeHistoryMap(codesArray),
        STARTUP_VOLUME_HISTORY_TIMEOUT_MS,
        'volume history',
      ).catch((error) => {
        console.warn('[DataLoader] 历史成交量索引加载失败，继续使用空索引:', error)
        return new Map<string, number[]>()
      }),
    )
    const intradayVolumeHistoryMap = options.deferIntradayVolumeHistory
      ? new Map<string, number[]>()
      : await this.measureStartupStep('intradayHistory', () =>
          this.buildIntradayVolumeHistoryMap(codesArray).catch((error) => {
            console.warn('[DataLoader] 分时成交量索引加载失败，继续使用空索引:', error)
            return new Map<string, number[]>()
          }),
        )
    this.updateProgress(this.startupProgress.historyEnd, '历史成交量索引完成', 'merge')

    // 2. ✅ 先加载行情数据
    let quotesMap = new Map<string, any>()
    if (allCodes.size > 0) {
      try {
        this.updateProgress(this.startupProgress.quoteStart, `加载行情数据 ${codesArray.length} 只...`, 'quote')
        const quoteResult = await this.measureStartupStep('quote', () =>
          refreshResourceLocks.runExclusive(
            'quote-http',
            () => this.getQuoteBatch(codesArray, false, {
              onProgress: (progress) => this.reportQuoteProgress(progress),
            }),
          ),
        )
        quotesMap = quoteResult.value ?? new Map()
      } catch (error) {
        console.warn('[DataLoader] 行情补全失败，保留平台热榜数据:', error)
      }
    }

    // 3. 获取现有 stocks（用于保留已有数据）
    const existingStocks = dataLayer.getMergedStocks()
    const existingMap = new Map(
      existingStocks.filter((stock) => allCodes.has(stock.code)).map((stock) => [stock.code, stock]),
    )

    // 4. 构建股票数据并计算综合排名
    this.updateProgress(this.startupProgress.mergeStart, '合并热榜与行情数据...', 'merge')
    let merged = await this.measureStartupStep('merge', () =>
      stockMergeCoordinator.merge({
        platformData: this.state.value.data || {},
        latestQuotes: quotesMap,
        volumeHistoryMap,
        intradayVolumeHistoryMap,
        existingMap,
      }),
    )

    // 5. 合并额外数据
    merged = this.mergeExtraData(merged)

    merged = this.volumeRatioUpdateService.enrichStocks(
      merged,
      volumeHistoryMap,
      intradayVolumeHistoryMap,
    )

    // 6. 计算个股热度
    this.updateStockHotness(merged)

    // 7. 先存储基础热榜，RankTrend 信号属于后置增强，不能阻塞首屏数据可见。
    const basePublishVersion = this.publishStocks(merged, { reason: 'base-merge' })
    this.syncRealtimeSubscription()
    this.updateProgress(this.startupProgress.mergeEnd, '基础榜单已就绪', 'merge')

    if (options.deferIntradayVolumeHistory) {
      this.refreshIntradayVolumeRatiosInBackground(codesArray, volumeHistoryMap)
    }

    if (options.deferSignalEnrichment) {
      void this.enrichSignalsInBackground(merged, basePublishVersion, options.rankTrendSnapshotPromise)
      return merged
    }

    // 8. 计算信号并回写增强字段
    this.updateProgress(this.startupProgress.signalStart, '计算排名趋势信号...', 'signal')
    const signalResult = await this.measureStartupStep('signal', () =>
      this.calculateSignals(merged, options.rankTrendSnapshotPromise),
    )
    merged = signalResult.merged
    if (signalResult.enriched) {
      this.publishStocks(merged, { reason: 'signal-enriched' })
      this.updateProgress(this.startupProgress.signalEnd, '排名趋势信号完成', 'signal')
    }

    return merged
  }

  private preloadRankTrendSnapshotsInBackground(
    codes: string[],
  ): Promise<RankTrendPreparedSnapshot[]> | undefined {
    const targetCodes = codes.filter((code) => code && code.length === 6)
    if (!targetCodes.length) return undefined

    return this.measureStartupStep('rankTrendSnapshot', () =>
      rankTrendSignalService.preloadSnapshots(targetCodes),
    ).catch((error) => {
      console.warn('[DataLoader] 排名趋势历史快照预取失败，将回退即时读取:', error)
      return []
    })
  }

  private refreshIntradayVolumeRatiosInBackground(
    codes: string[],
    volumeHistoryMap: Map<string, number[]>,
  ): void {
    void this.buildIntradayVolumeHistoryMap(codes)
      .then((intradayVolumeHistoryMap) => {
        if (!intradayVolumeHistoryMap.size) return

        const codeSet = new Set(codes)
        const enrichedByCode = new Map(
          this.volumeRatioUpdateService
            .enrichStocks(
              dataLayer.getStocks().filter((stock) => codeSet.has(stock.code)),
              volumeHistoryMap,
              intradayVolumeHistoryMap,
            )
            .map((stock) => [stock.code, stock]),
        )

        if (!enrichedByCode.size) return

        const nextStocks = dataLayer.getStocks().map((stock) => {
          const enriched = enrichedByCode.get(stock.code)
          if (!enriched) return stock
          return {
            ...stock,
            volumeRatio: enriched.volumeRatio,
            volumeRatioMeta: enriched.volumeRatioMeta,
          }
        })
        this.publishStocks(nextStocks, { reason: 'base-merge' })
      })
      .catch((error) => {
        console.warn('[DataLoader] 后台分时成交量索引加载失败，保留日级量比:', error)
      })
  }

  private async enrichSignalsInBackground(
    baseMerged: any[],
    basePublishVersion: number,
    snapshotPromise?: Promise<RankTrendPreparedSnapshot[]>,
  ): Promise<void> {
    try {
      const result = await this.calculateSignals(baseMerged, snapshotPromise)
      if (!result.enriched) return
      const enriched = result.merged
      if (this.stockPublishVersion !== basePublishVersion) {
        if (this.tryMergeStaleSignalEnrichment(baseMerged, enriched)) return
        debugLog('[DataLoader] 跳过过期的后台排名趋势信号增强')
        return
      }
      this.publishStocks(enriched, { reason: 'signal-enriched' })
      void this.writeStartupBundle(this.summarizeRun(Date.now(), false))
    } catch (error) {
      console.warn('[DataLoader] 后台排名趋势信号增强失败，保留基础热榜数据:', error)
    }
  }

  private tryMergeStaleSignalEnrichment(baseMerged: any[], enriched: any[]): boolean {
    const current = dataLayer.getStocks()
    const sameOrderedPool =
      current.length === baseMerged.length &&
      current.every((stock, index) => {
        const baseStock = baseMerged[index]
        return stock.code === baseStock?.code && stock.compRank === baseStock?.compRank
      })

    if (!sameOrderedPool) return false

    const enrichedByCode = new Map(enriched.map((stock) => [stock.code, stock]))
    const merged = current.map((stock) => {
      const signalStock = enrichedByCode.get(stock.code)
      if (!signalStock) return stock
      return {
        ...stock,
        rankTrend: signalStock.rankTrend,
        rankTrendCoverageWarning: signalStock.rankTrendCoverageWarning,
        candidatePoolStatus: signalStock.candidatePoolStatus,
        candidatePoolLabel: signalStock.candidatePoolLabel,
        candidatePoolProjection: signalStock.candidatePoolProjection,
        candidatePoolEntryId: signalStock.candidatePoolEntryId,
        candidatePoolSource: signalStock.candidatePoolSource,
        candidatePoolUpdatedAt: signalStock.candidatePoolUpdatedAt,
      }
    })

    this.publishStocks(merged, { reason: 'signal-enriched' })
    void this.writeStartupBundle(this.summarizeRun(Date.now(), false))
    return true
  }

  /**
   * 8. 计算个股热度
   * 热度不是 avgRank 的简单拷贝，而是“跨平台排名 + 覆盖度 + 人气 + 人气变化 + 领涨信号 + 身位 + 换手活跃度”的综合结果。
   */
  private updateStockHotness(stocks: MergedStock[]): void {
    stockHotnessService.updateStockHotness(stocks, this.state.value.platforms?.length || 8)
  }

  /**
   * 对外暴露热度重算入口，方便后续接外部研究工具或开发期手工微调。
   */
  recalculateStockHotness(): MergedStock[] {
    const stocks = stockHotnessService.recalculateStockHotness(this.state.value.platforms?.length || 8)
    if (stocks.length) {
      this.publishStocks(stocks, { reason: 'hotness-recalculated' })
    }
    return stocks
  }

  /**
   * 合并额外数据（从 DataLayer 迁移）
   * 包括：题材、JXBK、龙头、涨停扩展数据
   */
  private mergeExtraData(stocks: any[]): any[] {
    return extraDataProjector.project(stocks)
  }

  public async buildIntradayVolumeHistoryMap(
    codes: string[] = [],
    date: Date = new Date(),
  ): Promise<Map<string, number[]>> {
    return this.volumeHistoryService.buildIntradayVolumeHistoryMap(codes, date)
  }

  /**
   * 1. 构建历史成交量索引
   * 正式主链只按 code + daily + tradingDate 读取日级快照投影行，
   * 返回最近 4 个交易日成交量，供后续剔除“当前成交量与最新日级快照重复”的场景。
   */
  public async buildVolumeHistoryMap(codes: string[] = []): Promise<Map<string, number[]>> {
    return this.volumeHistoryService.buildVolumeHistoryMap(codes)
  }

  /**
   * 批量更新股票信号（从 RankTrendAnalyzer 调用）
   */
  updateStockSignals(
    updates: StockSignalUpdate[],
  ) {
    const stocks = rankTrendSignalService.updateStockSignals(updates)
    this.publishStocks(stocks, { reason: 'manual-signal-update' })
  }

  async refreshRankTrendSignals(): Promise<void> {
    const result = await refreshResourceLocks.runExclusive(
      'ranktrend-signal',
      () => rankTrendSignalService.refreshRankTrendSignals(),
    )
    const stocks = result.value ?? []
    if (stocks.length) {
      this.publishStocks(stocks, { reason: 'manual-signal-update' })
    }
  }

  /**
   * 5. 计算信号（排名变化 + 四维信号）
   */
  private async calculateSignals(
    merged: any[],
    snapshotPromise?: Promise<RankTrendPreparedSnapshot[]>,
  ): Promise<SignalCalculationResult> {
    try {
      const snapshots = snapshotPromise ? await snapshotPromise : undefined
      return {
        merged: await rankTrendSignalService.applySignalsToMerged(merged, { snapshots }),
        enriched: true,
      }
    } catch (error) {
      console.warn('[DataLoader] 排名趋势信号增强失败，保留基础热榜数据:', error)
      return { merged, enriched: false }
    }
  }
  getLoadingStatus() {
    return {
      active: this.loadingStatus.value.active,
      progress: this.loadingStatus.value.progress,
      message: this.loadingStatus.value.message,
      phase: this.loadingStatus.value.phase,
    }
  }

  destroy() {
    this.destroyed = true
    this.stopQuoteAutoRefresh()
    this.stopSignalAutoRefresh()
    if (this.volumeRatioRefreshTimer) {
      clearTimeout(this.volumeRatioRefreshTimer)
      this.volumeRatioRefreshTimer = null
    }
    this.pendingVolumeRatioCodes.clear()
    this.volumeRatioRefreshRunning = false
    platformHotlistService.clearCache()
    quoteService.clearPending()
    this.realtimeCoordinator.destroy()
  }

  clear() {
    this.destroy()
    this.state.value = {
      initialized: false,
      platforms: [...DEFAULT_PLATFORMS],
      data: {},
      loading: false,
      loadingProgress: 0,
      loadingMessage: '',
      lastUpdate: null,
    }
  }
}

export const dataLoader = new DataLoaderService()

if (typeof window !== 'undefined') {
  ;(window as any).dataLoader = dataLoader
}
