import { debugLog } from '@/utils/logger'
// src/services/dataLoader/DataLoaderFacade.ts

import { ref, readonly } from 'vue'
import { dataLayer } from '../DataLayer'
import type { MergedStock } from '@/types'
import { themeFacade } from '../theme/ThemeFacade'
import { isTradingTime } from '@/utils/time'
import { useUIStore } from '../../stores/ui'
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
import { loadLimitUpData as loadLimitUpFeedData } from './LimitUpFeed'
import { platformHotlistService } from './PlatformHotlistService'
import { quoteService } from './QuoteService'
import { rankTrendSignalService } from './RankTrendSignalService'
import { RealtimeQuoteCoordinator } from './RealtimeQuoteCoordinator'
import { stockHotnessService } from './StockHotnessService'
import { stockMergeCoordinator } from './StockMergeCoordinator'
import { VolumeHistoryService } from './VolumeHistoryService'
import { calculateVolumeRatioValue } from './VolumeRatioCalculator'
import type { LoaderState, LoadingStatus, MergedQuoteData, StockSignalUpdate } from './types'

export type { MergedQuoteData } from './types'

/**
 * 业务编排层
 * 职责：协调数据加载、合并计算、缓存策略、行情获取
 */
class DataLoaderService {
  private quoteRefreshTimer: ReturnType<typeof setInterval> | null = null
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

  private readonly INTRADAY_VOLUME_SNAPSHOT_TYPES = DEFAULT_INTRADAY_VOLUME_SNAPSHOT_TYPES
  private realtimeCoordinator: RealtimeQuoteCoordinator
  private volumeHistoryService: VolumeHistoryService

  private readonly PLATFORM_REFRESH_INTERVAL = PLATFORM_REFRESH_INTERVAL_MS // 30分钟

  constructor() {
    debugLog('[DataLoader] 初始化完成')
    this.realtimeCoordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => this.getAllHotCodes(),
    })
    this.volumeHistoryService = new VolumeHistoryService(this.INTRADAY_VOLUME_SNAPSHOT_TYPES)
    this.startQuoteAutoRefresh() // 自动启动行情刷新
  }

  private syncRealtimeSubscription() {
    this.realtimeCoordinator.syncRealtimeSubscription()
  }

  private isRealtimePrimaryHealthy(): boolean {
    return this.realtimeCoordinator.isRealtimePrimaryHealthy()
  }

  private async maybeRefreshPlatformCache() {
    if (!platformHotlistService.shouldRefresh(this.PLATFORM_REFRESH_INTERVAL)) {
      return
    }

    if (!platformHotlistService.hasFreshCache()) {
      await this.loadAllPlatforms(true)
      await this.loadLimitUpData(true)
      await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
    }

    platformHotlistService.markRefreshed()
  }

  // ========== 加载状态管理 ==========
  private setLoading(active: boolean, message: string = '', progress: number = 0) {
    this.loadingStatus.value = { active, progress, message, startTime: active ? Date.now() : null }
    this.state.value.loading = active
    this.state.value.loadingProgress = progress
    this.state.value.loadingMessage = message
  }

  private updateProgress(progress: number, message: string) {
    this.loadingStatus.value.progress = progress
    this.loadingStatus.value.message = message
    this.state.value.loadingProgress = progress
    this.state.value.loadingMessage = message
  }

  // ========== RefreshManager/Coordinator 接口 ==========
  async runUpdate(): Promise<void> {
    if (this.destroyed) return
    await this.handleFullRefresh(true)
    await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
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
    if (this.quoteRefreshTimer) return

    this.quoteRefreshTimer = setInterval(async () => {
      try {
        if (!isTradingTime(new Date())) return

        const stocks = dataLayer.getStocks()
        if (!stocks.length) return

        const allStockCodes = stocks
          .map((s: any) => s.code)
          .filter((code: string) => code && code.length === 6 && code !== '000000')

        if (allStockCodes.length === 0) return

        if (this.isRealtimePrimaryHealthy()) {
          await this.updateVolumeRatios(allStockCodes)
          await this.maybeRefreshPlatformCache()
          return
        }

        // 缩短批次延迟
        for (let i = 0; i < allStockCodes.length; i += batchSize) {
          const batchCodes = allStockCodes.slice(i, i + batchSize)
          const quotes = await this.fetchMergedQuotes(batchCodes, { force: true })

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

        await this.maybeRefreshPlatformCache()

        debugLog('[DataLoader] 行情刷新完成')
      } catch (error) {
        console.error('[DataLoader] 行情刷新失败:', error)
      }
    }, interval)
  }

  /**
   * 更新指定股票的量比
   */
  private async updateVolumeRatios(codes: string[]): Promise<void> {
    try {
      const stocks = dataLayer.getStocks()
      const [volumeHistoryMap, intradayVolumeHistoryMap] = await Promise.all([
        this.buildVolumeHistoryMap(codes),
        this.buildIntradayVolumeHistoryMap(codes),
      ])

      const updates: Array<{ code: string; volumeRatio?: number }> = []

      for (const code of codes) {
        const stock = stocks.find((s) => s.code === code)
        if (stock && stock.volume && stock.volume > 0) {
          const volumeRatio = calculateVolumeRatioValue(
            stock,
            code,
            volumeHistoryMap,
            intradayVolumeHistoryMap,
          )
          if (volumeRatio !== stock.volumeRatio) {
            updates.push({ code, volumeRatio })
          }
        }
      }

      if (updates.length) {
        debugLog(`[DataLoader] 更新量比: ${updates.length} 只股票`)
        dataLayer.updateStockExtData(updates)
        EventManager.emit(AppEvents.DATA.MERGED, { count: dataLayer.getStocks().length, timestamp: Date.now() })
        useUIStore().updateDataVersion()
      }
    } catch (error) {
      console.warn('[DataLoader] 更新量比失败:', error)
    }
  }

  /**
   * 停止行情自动刷新
   */
  stopQuoteAutoRefresh(): void {
    if (this.quoteRefreshTimer) {
      clearInterval(this.quoteRefreshTimer)
      this.quoteRefreshTimer = null
    }
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
    if (autoLoad) await this.loadAllPlatforms()
    this.state.value.initialized = true
  }

  // ========== 手动刷新 ==========
  private async handleFullRefresh(force = false) {
    try {
      this.setLoading(true, '加载平台数据...', 0)
      // 并行加载所有数据
      await Promise.all([
        this.loadAllPlatforms(force),
        this.loadStockDetails(true),
        this.loadLimitUpData(force),
      ])
      this.updateProgress(80, '合并数据...')

      await this.mergeData()

      const result = await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
      const updatedCount = result.syncedStockCount
      if (updatedCount > 0) debugLog(`[DataLoader] 刷新后同步题材: ${updatedCount}只股票`)

      this.updateProgress(100, '完成')
      this.setLoading(false)

      const uiStore = useUIStore()
      uiStore.updateDataVersion()

      return true
    } catch (error) {
      console.error('[DataLoader] ❌ 刷新失败:', error)
      this.setLoading(false, '加载失败')
      throw error
    }
  }

  // ========== 加载平台数据 ==========
  async loadAllPlatforms(force = false) {
    if (this.destroyed || (this.state.value.loading && !force)) return

    const platforms = this.state.value.platforms
    const result = await platformHotlistService.loadPlatforms(platforms, force)

    if (result.fromCache) {
      this.state.value.data = result.data
      this.state.value.lastUpdate = result.timestamp
      this.state.value.loading = false
      dataLayer.updatePlatforms(result.data)
      if (!dataLayer.getStocks().length) {
        await this.mergeData()
      }
      return
    }

    this.setLoading(true, '加载平台热榜...', 10)

    this.updateProgress(10, `加载平台数据 0/${platforms.length}`)
    this.updateProgress(50, `加载平台数据完成`)
    this.state.value.data = result.data
    this.state.value.lastUpdate = result.timestamp
    dataLayer.updatePlatforms(result.data)
    await this.mergeData()
    this.setLoading(false)

    return result.data
  }

  clearPlatformCache() {
    platformHotlistService.clearCache()
  }

  async loadLimitUpData(force = false): Promise<void> {
    void force
    await loadLimitUpFeedData()
  }

  // ========== 加载行情数据 ==========
  private async getQuoteBatch(codes: string[], force = false): Promise<Map<string, any>> {
    return quoteService.getQuoteBatch(codes, force)
  }

  // ========== 加载行情数据 ==========
  async loadStockDetails(force = false): Promise<Map<string, any> | void> {
    if (this.destroyed || this.isLoadingDetails) return
    this.isLoadingDetails = true

    try {
      const allCodes = this.getAllHotCodes()
      if (allCodes.size === 0) return

      const codesArray = Array.from(allCodes)
      this.updateProgress(60, `加载行情数据 ${codesArray.length} 只...`)
      const quotes = await this.getQuoteBatch(codesArray, true)

      return quotes
    } catch (error) {
      console.error('[DataLoader] 加载行情详情失败:', error)
      throw error
    } finally {
      this.isLoadingDetails = false
    }
  }

  private getAllHotCodes(): Set<string> {
    return platformHotlistService.getAllHotCodes(this.state.value.data || {})
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
  async mergeData(): Promise<any[]> {
    // 1. 获取历史成交量索引
    const allCodes = this.getAllHotCodes()
    const codesArray = Array.from(allCodes)
    const [volumeHistoryMap, intradayVolumeHistoryMap] = await Promise.all([
      this.buildVolumeHistoryMap(codesArray),
      this.buildIntradayVolumeHistoryMap(codesArray),
    ])

    // 2. ✅ 先加载行情数据
    let quotesMap = new Map<string, any>()
    if (allCodes.size > 0) {
      quotesMap = await this.getQuoteBatch(codesArray, true)
    }

    // 3. 获取现有 stocks（用于保留已有数据）
    const existingStocks = dataLayer.getMergedStocks()
    const existingMap = new Map(existingStocks.map((s) => [s.code, s]))

    // 4. 构建股票数据并计算综合排名
    let merged = await stockMergeCoordinator.merge({
      platformData: this.state.value.data || {},
      latestQuotes: quotesMap,
      volumeHistoryMap,
      intradayVolumeHistoryMap,
      existingMap,
    })

    // 5. 合并额外数据
    merged = this.mergeExtraData(merged)

    // 6. 计算个股热度
    this.updateStockHotness(merged)

    // 7. 计算信号
    merged = await this.calculateSignals(merged)

    // 8. 存储到 DataLayer
    dataLayer.setMergedStocks(merged)
    EventManager.emit(AppEvents.DATA.MERGED, { count: merged.length, timestamp: Date.now() })
    useUIStore().updateDataVersion()
    this.syncRealtimeSubscription()

    return merged
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
    return stockHotnessService.recalculateStockHotness(this.state.value.platforms?.length || 8)
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
    rankTrendSignalService.updateStockSignals(updates)
  }

  async refreshRankTrendSignals(): Promise<void> {
    await rankTrendSignalService.refreshRankTrendSignals()
  }

  /**
   * 5. 计算信号（排名变化 + 四维信号）
   */
  private async calculateSignals(merged: any[]): Promise<any[]> {
    return rankTrendSignalService.applySignalsToMerged(merged)
  }
  getLoadingStatus() {
    return {
      active: this.loadingStatus.value.active,
      progress: this.loadingStatus.value.progress,
      message: this.loadingStatus.value.message,
    }
  }

  destroy() {
    this.destroyed = true
    this.stopQuoteAutoRefresh()
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
