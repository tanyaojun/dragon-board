// src/services/dataLoader.ts

import { ref, readonly } from 'vue'
import { Adapters } from './adapters'
import { dataLayer } from './DataLayer'
import type { MergedStock } from './DataLayer'
import { apiService } from './apiService'
import { rankTrendAnalyzer } from './RankTrendAnalyzer'
import sectorAnalyzer from './sectorAnalyzer'
import {
  COMPREHENSIVE_WEIGHTS,
  PENALTY_SCORE,
  DEFAULT_RANK,
  OPTIMAL_TURNOVER,
  TURNOVER_SIGMA,
} from '@/types'
import { isTradingTime } from '@/utils/time'
import { filterValidStockCodes } from '@/utils/common'

// ========== 类型定义 ==========
interface LoaderState {
  initialized: boolean
  platforms: string[]
  data: Record<string, any[]>
  loading: boolean
  loadingProgress: number
  loadingMessage: string
  lastUpdate: number | null
}

interface LimitUpItem {
  code: string
  reason_type: string
  is_new: number
  first_limit_up_time: string
  last_limit_up_time: string
  continue_day: number
  high_days: number
}

interface LoadingStatus {
  active: boolean
  progress: number
  message: string
  startTime: number | null
}

export interface MergedQuoteData {
  price: number
  change: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  totalMV: number
  cirMV: number
  pb: number
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number
  name?: string
  sources: string[]
  confidence: number
  timestamp: number
}

/**
 * 业务编排层
 * 职责：协调数据加载、合并计算、缓存策略、行情获取
 */
class DataLoaderService {
  private quoteRefreshTimer: ReturnType<typeof setInterval> | null = null
  private readonly QUOTE_REFRESH_INTERVAL = 30000 // ✅ 改为30秒
  private readonly QUOTE_BATCH_SIZE = 20
  private state = ref<LoaderState>({
    initialized: false,
    platforms: ['eastmoney', 'ths', 'kpl', 'tdx', 'xueqiu', 'cls', 'tgb', 'dzh'],
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

  private platformCache = new Map<string, { data: any; timestamp: number }>()
  private readonly PLATFORM_CACHE_TTL = 3600000
  private readonly MAX_CACHE_SIZE = 10
  private isLoadingDetails = false
  private destroyed = false
  private hotStockSet = new Set<string>()

  // 行情刷新定时器
  private quoteRefreshTimer: ReturnType<typeof setInterval> | null = null

  // 请求队列
  private pendingQuoteRequests: Map<
    string,
    { resolve: (value: any) => void; reject: (reason?: any) => void }
  > = new Map()
  private pendingCodes: Set<string> = new Set()
  private batchTimer: ReturnType<typeof setTimeout> | null = null
  private readonly BATCH_DELAY = 50

  constructor() {
    console.log('[DataLoader] 初始化完成')
    this.startQuoteAutoRefresh() // 自动启动行情刷新
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
    await this.loadLimitUpData(true)
    sectorAnalyzer.syncThemesToStocks()
  }

  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    const now = Date.now()
    for (const [key, value] of this.platformCache.entries()) {
      if (now - value.timestamp > this.PLATFORM_CACHE_TTL) {
        this.platformCache.delete(key)
      }
    }
  }

  async syncData(): Promise<void> {
    if (this.destroyed) return
    const latestQuotes = dataLayer.getAllQuotes()
    const quoteMap = new Map(latestQuotes.map((q) => [q.code, q]))
    await this.mergeData(quoteMap)
  }

  // ========== 行情服务 ==========

  /**
   * 启动行情自动刷新
   */
  startQuoteAutoRefresh(
    interval: number = this.QUOTE_REFRESH_INTERVAL, // ✅ 默认30秒
    batchSize: number = this.QUOTE_BATCH_SIZE,
  ): void {
    if (!isTradingTime()) {
      console.log('[DataLoader] 非交易时间，不启动行情自动刷新')
      return
    }
    if (this.quoteRefreshTimer) return

    this.quoteRefreshTimer = setInterval(async () => {
      try {
        const stocks = dataLayer.getStocks()
        const top200 = stocks
          .filter((s: any) => s.compRank)
          .sort((a: any, b: any) => (a.compRank || 999) - (b.compRank || 999))
          .slice(0, 200)
          .map((s: any) => s.code)
          .filter(Boolean)

        if (top200.length === 0) return

        // ✅ 分批获取，每批 batchSize 只
        for (let i = 0; i < top200.length; i += batchSize) {
          const batchCodes = top200.slice(i, i + batchSize)

          // fetchMergedQuotes 内部已经使用 getQuotesBatch，会自动分批
          const quotes = await this.fetchMergedQuotes(batchCodes, { force: false })

          if (quotes.size > 0) {
            quotes.forEach((quote, code) => {
              dataLayer.updateQuote(code, quote)
            })
          }

          if (i + batchSize < top200.length) {
            await new Promise((resolve) => setTimeout(resolve, 500))
          }
        }

        // 刷新完成后重新计算信号
        await this.syncData()
      } catch (error) {
        console.error('[DataLoader] 行情刷新失败:', error)
      }
    }, interval)
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
    const validCodes = filterValidStockCodes([...new Set(codes)])
    if (validCodes.length === 0) return new Map()

    const result = new Map<string, MergedQuoteData>()

    // 并行请求基础数据和完整数据
    const [basicResult, fullResult] = await Promise.allSettled([
      this.fetchBasicData(validCodes),
      this.fetchFullData(validCodes, options.force),
    ])

    // 处理基础数据
    if (basicResult.status === 'fulfilled' && basicResult.value.size > 0) {
      basicResult.value.forEach((quote, code) => {
        result.set(code, {
          ...quote,
          timestamp: Date.now(),
          sources: [quote.source],
          confidence: quote.source === 'eastmoney' ? 95 : 70,
        } as MergedQuoteData)
      })
    }

    // 处理完整数据（东财数据覆盖基础数据）
    if (fullResult.status === 'fulfilled' && fullResult.value.size > 0) {
      fullResult.value.forEach((fullQuote, code) => {
        const existing = result.get(code)
        if (existing) {
          result.set(code, {
            ...existing,
            ...fullQuote,
            sources: [...existing.sources, fullQuote.source],
            confidence: 95,
            timestamp: Date.now(),
          })
        } else {
          result.set(code, {
            ...fullQuote,
            timestamp: Date.now(),
            sources: [fullQuote.source],
            confidence: 95,
          })
        }
      })
    }

    return result
  }
  /**
   * 获取单只股票行情
   */
  async getQuote(code: string, force = false): Promise<MergedQuoteData | null> {
    if (!force) {
      const cached = dataLayer.getQuote(code)
      if (cached && Date.now() - cached.timestamp < 5000) {
        return cached
      }
    }

    const quotes = await this.fetchMergedQuotes([code], { force })
    const quote = quotes.get(code)
    if (quote) dataLayer.updateQuote(code, quote)
    return quote || null
  }

  /**
   * 批量获取行情
   */
  async getQuotes(codes: string[], force = false): Promise<Map<string, any>> {
    const quotes = await this.fetchMergedQuotes(codes, { force })
    const result = new Map()

    quotes.forEach((quote, code) => {
      result.set(code, {
        price: quote.price,
        change: quote.change,
        volume: quote.volume || 0,
        turnover: quote.turnover || 0,
        turnoverRate: quote.turnoverRate || 0,
        pe: quote.pe || 0,
        totalMV: quote.totalMV || 0,
        cirMV: quote.cirMV || 0,
        pb: quote.pb || 0,
        zlje: quote.zlje || 0,
        cddje: quote.cddje || 0,
        cddjzb: quote.cddjzb || 0,
        zljzb: quote.zljzb || 0,
        name: quote.name || '',
      })
      dataLayer.updateQuote(code, quote)
    })

    return result
  }

  // ========== 私有行情方法 ==========
  /**
   * 获取基础数据（腾讯/新浪）
   */
  private async fetchBasicData(codes: string[]): Promise<Map<string, any>> {
    try {
      return await this.fetchFromTencent(codes)
    } catch (error) {
      console.warn('[DataLoader] 腾讯接口失败，尝试新浪:', error)
      return await this.fetchFromSina(codes)
    }
  }

  /**
   * 获取完整数据（东财）
   */
  private async fetchFullData(codes: string[], force?: boolean): Promise<Map<string, any>> {
    return await this.fetchFromEastMoney(codes, force)
  }

  /**
   * 从腾讯获取基础数据
   */
  private async fetchFromTencent(codes: string[]): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const batchSize = 20

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)

      // ✅ 使用 getQuotes，指定 source: 'tencent'
      const response = await apiService.getQuotes(batch, { source: 'tencent' })

      const diff = response?.data?.diff || []
      diff.forEach((item: any) => {
        const code = this.normalizeCode(item.f12)
        result.set(code, {
          price: parseFloat(item.f2) || 0,
          change: parseFloat(item.f3) || 0,
          volume: parseInt(item.f6) || 0,
          turnover: parseFloat(item.f5) || 0,
          turnoverRate: parseFloat(item.f8) || 0,
          pe: parseFloat(item.f9) || 0,
          pb: parseFloat(item.f23) || 0,
          name: item.f14 || '',
          source: 'tencent',
          totalMV: (parseFloat(item.f20) || 0) * 10000,
          cirMV: (parseFloat(item.f21) || 0) * 10000,
          zlje: parseFloat(item.f62) || 0,
          zljzb: parseFloat(item.f184) || 0,
          cddje: parseFloat(item.f66) || 0,
          cddjzb: parseFloat(item.f69) || 0,
        })
      })

      if (i + batchSize < codes.length) {
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
    }

    return result
  }

  /**
   * 从新浪获取备用数据
   */
  private async fetchFromSina(codes: string[]): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const batchSize = 20

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)

      // ✅ 使用 getQuotes，指定 source: 'sina'
      const response = await apiService.getQuotes(batch, { source: 'sina' })

      const diff = response?.data?.diff || []
      diff.forEach((item: any) => {
        const code = this.normalizeCode(item.f12)
        result.set(code, {
          price: parseFloat(item.f2) || 0,
          change: parseFloat(item.f3) || 0,
          volume: parseInt(item.f6) || 0,
          turnover: parseFloat(item.f5) || 0,
          turnoverRate: parseFloat(item.f8) || 0,
          pe: parseFloat(item.f9) || 0,
          pb: parseFloat(item.f23) || 0,
          name: item.f14 || '',
          source: 'sina',
          totalMV: (parseFloat(item.f20) || 0) * 10000,
          cirMV: (parseFloat(item.f21) || 0) * 10000,
          zlje: parseFloat(item.f62) || 0,
          zljzb: parseFloat(item.f184) || 0,
          cddje: parseFloat(item.f66) || 0,
          cddjzb: parseFloat(item.f69) || 0,
        })
      })

      if (i + batchSize < codes.length) {
        await new Promise((resolve) => setTimeout(resolve, 100))
      }
    }

    return result
  }

  /**
   * 从东财获取完整数据
   */
  private async fetchFromEastMoney(codes: string[], force?: boolean): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const batchSize = 20

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)

      // ✅ 使用 getQuotes，指定 source: 'eastmoney'
      const response = await apiService.getQuotes(batch, {
        source: 'eastmoney',
        force,
        timeout: 8000,
        retries: 2,
      })

      const diff = response?.data?.diff || []
      diff.forEach((item: any) => {
        const code = this.normalizeCode(item.f12)
        result.set(code, {
          price: parseFloat(item.f2) || 0,
          change: parseFloat(item.f3) || 0,
          volume: parseInt(item.f5) || 0,
          turnover: parseFloat(item.f6) || 0,
          turnoverRate: parseFloat(item.f8) || 0,
          pe: parseFloat(item.f9) || 0,
          pb: parseFloat(item.f23) || 0,
          name: item.f14 || '',
          source: 'eastmoney',
          totalMV: parseFloat(item.f20) || 0,
          cirMV: parseFloat(item.f21) || 0,
          zlje: parseFloat(item.f62) || 0,
          zljzb: parseFloat(item.f184) || 0,
          cddje: parseFloat(item.f66) || 0,
          cddjzb: parseFloat(item.f69) || 0,
        })
      })

      if (i + batchSize < codes.length) {
        await new Promise((resolve) => setTimeout(resolve, 200))
      }
    }

    return result
  }

  // ========== 原有初始化方法 ==========
  async init(autoLoad = true) {
    if (this.state.value.initialized) return
    if (autoLoad) await this.loadAllPlatforms()
    this.state.value.initialized = true
  }

  // ========== 全量刷新 ==========
  private async handleFullRefresh(force = false) {
    try {
      this.setLoading(true, '加载平台数据...', 0)
      await Promise.all([this.loadAllPlatforms(force), this.loadStockDetails(true)])
      this.updateProgress(80, '合并数据...')

      const latestQuotes = dataLayer.getAllQuotes()
      const quoteMap = new Map(latestQuotes.map((q) => [q.code, q]))
      await this.mergeData(quoteMap)

      const updatedCount = sectorAnalyzer.syncThemesToStocks()
      if (updatedCount > 0) console.log(`[DataLoader] 全量刷新后同步题材: ${updatedCount}只股票`)

      this.updateProgress(100, '完成')
      this.setLoading(false)
      return true
    } catch (error) {
      console.error('[DataLoader] ❌ 全量刷新失败:', error)
      this.setLoading(false, '加载失败')
      throw error
    }
  }

  // ========== 加载平台数据 ==========
  async loadAllPlatforms(force = false) {
    if (this.destroyed || this.state.value.loading) return

    const cacheKey = 'platforms'
    const cached = this.platformCache.get(cacheKey)

    if (!force && cached && Date.now() - cached.timestamp < this.PLATFORM_CACHE_TTL) {
      this.state.value.data = cached.data
      this.state.value.lastUpdate = cached.timestamp
      this.state.value.loading = false
      return
    }

    this.setLoading(true, '加载平台热榜...', 10)
    const results: Record<string, any[]> = {}
    const stockMap = new Map<string, any>()
    await this.mergeData()

    const platforms = this.state.value.platforms
    const batchSize = 2
    let completed = 0

    for (let i = 0; i < platforms.length; i += batchSize) {
      const batch = platforms.slice(i, i + batchSize)
      const batchResults = await Promise.allSettled(
        batch.map(async (platform) => {
          try {
            const adapter = Adapters[platform as keyof typeof Adapters]
            if (!adapter) return { platform, data: [] }

            const rawData = await adapter.getHotList()
            const formatted = adapter.format(rawData)

            formatted.forEach((item: any) => {
              if (item?.code) stockMap.set(item.code, true)
            })

            return { platform, data: formatted }
          } catch (error) {
            return { platform, data: [] }
          }
        }),
      )

      batchResults.forEach((result) => {
        if (result.status === 'fulfilled' && result.value) {
          results[result.value.platform] = result.value.data
          this.state.value.data = { ...this.state.value.data, ...results }
          this.mergeData()
        }
      })

      completed += batch.length
      const progress = 10 + Math.floor((completed / platforms.length) * 40)
      this.updateProgress(progress, `加载平台数据 ${completed}/${platforms.length}`)

      if (i + batchSize < platforms.length) {
        await new Promise((resolve) => setTimeout(resolve, 200))
      }
    }

    this.state.value.data = results
    this.state.value.lastUpdate = Date.now()
    this.updateHotStockSet()
    dataLayer.updatePlatforms(results)
    await this.mergeData()

    if (this.platformCache.size >= this.MAX_CACHE_SIZE) {
      const oldestKey = this.platformCache.keys().next().value
      oldestKey && this.platformCache.delete(oldestKey)
    }

    this.platformCache.set(cacheKey, { data: results, timestamp: Date.now() })
    return results
  }

  clearPlatformCache() {
    this.platformCache.clear()
  }

  async loadLimitUpData(force = false): Promise<void> {
    try {
      const response = await apiService.getLimitUp()
      if (!response?.data?.info) return

      const updates = response.data.info.map((item: LimitUpItem) => ({
        code: this.normalizeCode(item.code),
        reason: item.reason_type,
        isNew: item.is_new === 1,
        firstZtTime: item.first_limit_up_time,
        lastZtTime: item.last_limit_up_time,
        boardHeight: item.continue_day,
        highDays: item.high_days,
      }))

      dataLayer.updateLimitUpData?.(updates)
    } catch (error) {
      console.warn('[DataLoader] 加载涨停池数据失败:', error)
    }
  }

  // ========== 加载行情数据 ==========
  private async getQuoteBatch(codes: string[], force = false): Promise<Map<string, any>> {
    const uniqueCodes = [...new Set(codes)]
    const result = new Map<string, any>()
    const toFetch: string[] = []

    for (const code of uniqueCodes) {
      const pending = this.pendingQuoteRequests.get(code)
      if (pending && !force) {
        const quote = await new Promise((resolve, reject) => {
          this.pendingQuoteRequests.set(code, { resolve, reject })
        })
        if (quote) result.set(code, quote)
      } else {
        toFetch.push(code)
      }
    }

    if (toFetch.length === 0) return result

    return new Promise((resolve) => {
      for (const code of toFetch) this.pendingCodes.add(code)
      if (this.batchTimer) clearTimeout(this.batchTimer)

      this.batchTimer = setTimeout(async () => {
        const batchCodes = Array.from(this.pendingCodes)
        this.pendingCodes.clear()
        this.batchTimer = null

        if (batchCodes.length === 0) {
          resolve(result)
          return
        }

        try {
          const quotes = await this.fetchMergedQuotes(batchCodes, { force })

          quotes.forEach((quote, code) => {
            result.set(code, quote)
            dataLayer.updateQuote(code, quote)
          })

          for (const code of batchCodes) {
            const pending = this.pendingQuoteRequests.get(code)
            if (pending) {
              pending.resolve(quotes.get(code))
              this.pendingQuoteRequests.delete(code)
            }
          }
          resolve(result)
        } catch (error) {
          for (const code of batchCodes) {
            const pending = this.pendingQuoteRequests.get(code)
            if (pending) pending.reject(error)
          }
        }
      }, this.BATCH_DELAY)
    })
  }

  async loadStockDetails(force = false): Promise<Map<string, any> | void> {
    if (this.destroyed || this.isLoadingDetails) return
    this.isLoadingDetails = true

    try {
      const allCodes = this.getAllHotCodes()
      if (allCodes.size === 0) return

      const codesArray = Array.from(allCodes)
      this.updateProgress(50, `加载行情数据 ${codesArray.length} 只...`)
      const quotes = await this.getQuoteBatch(codesArray, true)
      await this.mergeData(quotes)
      return quotes
    } catch (error) {
      console.error('[DataLoader] 加载行情详情失败:', error)
      throw error
    } finally {
      this.isLoadingDetails = false
    }
  }

  private getAllHotCodes(): Set<string> {
    const codes = new Set<string>()
    Object.values(this.state.value.data || {}).forEach((platformData) => {
      if (Array.isArray(platformData)) {
        platformData.forEach((item) => {
          if (item?.code) codes.add(item.code)
        })
      }
    })
    return codes
  }

  private updateHotStockSet() {
    this.hotStockSet.clear()
    Object.values(this.state.value.data || {}).forEach((platformData) => {
      if (Array.isArray(platformData)) {
        platformData.forEach((item) => {
          if (item?.code) this.hotStockSet.add(item.code)
        })
      }
    })
  }

  getMerged() {
    return dataLayer.getStocks()
  }

  getMergedWithVersion() {
    return dataLayer.getStocksWithVersion()
  }

  // ========== 合并计算 ==========
  async mergeData(useLatestQuotes?: Map<string, any>): Promise<any[]> {
    const stockMap = new Map<string, any>()
    const platformTotals = this.getPlatformTotals()

    // 1. 合并平台排名数据
    for (const [platform, items] of Object.entries(this.state.value.data || {})) {
      for (const item of items) {
        const code = item.code
        if (!code) continue

        let stock = stockMap.get(code)
        if (!stock) {
          stock = this.createEmptyStock(code)
          stockMap.set(code, stock)
        }

        if (this.isValidName(item.name) && !stock.platformName) {
          stock.platformName = item.name
        }

        const rankField = this.getRankField(platform)
        if (rankField) {
          stock[rankField] = item.rank
        }
      }
    }

    // 2. 获取行情数据
    let quoteMap: Map<string, any>
    if (useLatestQuotes) {
      quoteMap = useLatestQuotes
    } else {
      const layerStocks = dataLayer.getRawStocks()
      quoteMap = new Map(layerStocks.map((s) => [s.code, s]))
    }

    // 3. 合并行情数据
    for (const [code, stock] of stockMap.entries()) {
      const quote = quoteMap.get(code)
      if (quote) {
        Object.assign(stock, {
          price: quote.price ?? stock.price,
          change: quote.change ?? stock.change,
          volume: quote.volume ?? stock.volume,
          turnover: quote.turnover ?? stock.turnover,
          turnoverRate: quote.turnoverRate ?? stock.turnoverRate,
          pe: quote.pe ?? stock.pe,
          pb: quote.pb ?? stock.pb,
          totalMV: quote.totalMV ?? stock.totalMV,
          cirMV: quote.cirMV ?? stock.cirMV,
          zlje: quote.zlje ?? stock.zlje,
          zljzb: quote.zljzb ?? stock.zljzb,
          cddje: quote.cddje ?? stock.cddje,
          cddjzb: quote.cddjzb ?? stock.cddjzb,
        })

        if (quote.name && quote.name !== '-' && quote.name !== '') {
          stock.name = quote.name
        }
      }

      if (!this.isValidName(stock.name) && stock.platformName) {
        stock.name = stock.platformName
      }

      if (!this.isValidName(stock.name)) {
        stock.name = '-'
      }
    }

    let merged = Array.from(stockMap.values())
    merged = merged.map((stock) => this.calculateAvgRank(stock, platformTotals))
    merged.sort((a, b) => a.avgRankNum - b.avgRankNum)
    this.calculateComprehensiveRank(merged)

    const newRankMap = new Map<string, number>()
    merged.forEach((stock, index) => {
      const newRank = index + 1
      newRankMap.set(stock.code, newRank)
      stock.rank = newRank
    })

    const rankTrends = await rankTrendAnalyzer.getRankTrends(newRankMap)

    merged.forEach((stock: any) => {
      const themes = dataLayer.getStockThemes(stock.code)
      stock.themes = themes

      const hotness = dataLayer.getStockHotness?.(stock.code)
      if (hotness !== undefined) stock.hotness = hotness

      const tags = dataLayer.getStockTags?.(stock.code)
      if (tags) stock.tags = tags

      const reason = dataLayer.getStockReason?.(stock.code)
      if (reason) stock.reason = reason

      const isNew = dataLayer.getStockIsNew?.(stock.code)
      if (isNew !== undefined) stock.isNew = isNew

      const limitUp = dataLayer.getLimitUpData?.(stock.code)
      if (limitUp) {
        stock.firstZtTime = limitUp.firstZtTime
        stock.lastZtTime = limitUp.lastZtTime
        stock.boardHeight = limitUp.boardHeight
        stock.highDays = limitUp.highDays
      }

      const trend = rankTrends.get(stock.code)
      if (trend) {
        stock.finalSignal = trend.finalSignal
        stock.finalConfidence = trend.finalConfidence
        stock.rankChange = Math.round(trend.change)
        stock.macdCross = trend.macdCross
        stock.rankTrendSignal = trend.rankTrendSignal
        stock.rankTrendConfidence = trend.rankTrendConfidence
        stock.rankSignal = trend.rankSignal
        stock.moneyFlowSignal = trend.moneyFlowSignal
        stock.technicalSignal = trend.technicalSignal
        stock.marketSentimentSignal = trend.marketSentimentSignal
        stock.sectorSignal = trend.sectorSignal
      } else {
        stock.rankTrendSignal = 'none'
        stock.rankTrendConfidence = 0
        stock.finalSignal = 'none'
        stock.finalConfidence = 0
        stock.rankChange = 0
        stock.macdCross = 'none'
        stock.rankSignal = 'none'
        stock.moneyFlowSignal = 'none'
        stock.technicalSignal = 'none'
        stock.marketSentimentSignal = 'none'
        stock.sectorSignal = 'none'
      }
    })

    dataLayer.setMergedStocks(merged)
    return merged
  }

  private createEmptyStock(code: string): MergedStock {
    return {
      // ========== 基础字段 ==========
      code, // 股票代码（6位数字）
      name: '', // 股票名称
      price: 0, // 最新价（元）
      change: 0, // 涨跌幅（%）
      volume: 0, // 成交量（手）
      turnover: 0, // 成交额（元）
      turnoverRate: 0, // 换手率（%）
      pe: 0, // 市盈率（动态）
      pb: 0, // 市净率
      totalMV: 0, // 总市值（元）
      cirMV: 0, // 流通市值（元）
      zlje: 0, // 主力净额（元）
      zljzb: 0, // 主力净占比（%）
      cddje: 0, // 超大单净额（元）
      cddjzb: 0, // 超大单净占比（%）

      // ========== 八平台排名 ==========
      emRank: DEFAULT_RANK, // 东方财富排名
      thsRank: DEFAULT_RANK, // 同花顺排名
      kplRank: DEFAULT_RANK, // 开盘啦排名
      tdxRank: DEFAULT_RANK, // 通达信排名
      xqRank: DEFAULT_RANK, // 雪球排名
      clsRank: DEFAULT_RANK, // 财联社排名
      tgbRank: DEFAULT_RANK, // 淘股吧排名
      dzhRank: DEFAULT_RANK, // 大智慧排名

      // ========== 综合指标 ==========
      platforms: 0, // 上榜平台数量
      avgRankNum: DEFAULT_RANK, // 加权平均排名（数值）
      avgRank: DEFAULT_RANK.toString(), // 加权平均排名（显示）
      compRank: null, // 综合排名（1-N）
      compScore: 0, // 综合得分（0-100）
      updatedAt: Date.now(), // 最后更新时间戳

      // ========== 题材数据 ==========
      themes: [], // 所属题材列表 [{id, name}]

      // ========== 热度数据 ==========
      hotness: 0, // 个股热度值
      tags: [], // 标签列表 [{Name}]
      reason: '', // 涨停原因
      isNew: false, // 是否新涨停
      firstZtTime: '', // 首次涨停时间（HH:MM:SS）
      lastZtTime: '', // 最后涨停时间（HH:MM:SS）
      boardHeight: 0, // 封板高度
      highDays: 0, // 近期最高连板天数
      platformName: '', // 平台名称（用于显示）

      // ========== 排名变化 ==========
      rankChange: 0, // 排名变化（百分位变化，正=上升）
      fundPenetration: 0, // 资金渗透率（主力净额/流通市值）
      mainTheme: undefined, // 主要题材
      themeHeat: 0, // 题材热度
      themeLevel: '冷', // 题材热度等级（冷/温/热/爆）

      // ========== 六维信号 ==========
      // 1. 排名趋势信号（基于排名动量、加速度、RSI）
      rankTrendSignal: 'none', // 排名趋势信号（buy/sell/hold/none）
      rankTrendConfidence: 0, // 排名趋势置信度（0-100）

      // 2. 平台排名信号（八平台综合）
      rankSignal: 'none', // 平台排名信号（buy/sell/hold/none）
      rankConfidence: 0, // 平台排名置信度（0-100）
      rankTrend: 'steady', // 排名趋势方向（up/down/steady）
      rankStrength: 'weak', // 排名趋势强度（strong/medium/weak）

      // 3. 资金流向信号（主力净额、主力占比、机构增仓）
      moneyFlowSignal: 'none', // 资金流向信号（buy/sell/hold/none）
      moneyFlowConfidence: 0, // 资金流向置信度（0-100）

      // 4. 技术指标信号（量比、换手率、涨跌幅）
      technicalSignal: 'none', // 技术指标信号（buy/sell/hold/none）
      technicalConfidence: 0, // 技术指标置信度（0-100）

      // 5. 市场情绪信号（龙息情绪分析）
      marketSentimentSignal: 'none', // 市场情绪信号（buy/sell/hold/none）
      marketSentimentConfidence: 0, // 市场情绪置信度（0-100）

      // 6. 板块强度信号（题材热度）
      sectorSignal: 'none', // 板块强度信号（buy/sell/hold/none）
      sectorConfidence: 0, // 板块强度置信度（0-100）

      // 综合信号
      finalSignal: 'none', // 最终综合信号（buy/sell/hold/none）
      finalConfidence: 0, // 最终置信度（0-100）

      // ========== MACD 技术指标（基于排名序列） ==========
      macdCross: 'none', // MACD交叉（golden金叉/death死叉/none）
    }
  }

  private getRankField(platform: string): string | null {
    const map: Record<string, string> = {
      eastmoney: 'emRank',
      ths: 'thsRank',
      kpl: 'kplRank',
      tdx: 'tdxRank',
      xueqiu: 'xqRank',
      cls: 'clsRank',
      tgb: 'tgbRank',
      dzh: 'dzhRank',
    }
    return map[platform] || null
  }

  private calculateAvgRank(stock: any, platformTotals: any): any {
    let weightedSum = 0,
      totalWeight = 0,
      platforms = 0

    const rankData = [
      { rank: stock.emRank, src: 'eastmoney' },
      { rank: stock.thsRank, src: 'ths' },
      { rank: stock.kplRank, src: 'kpl' },
      { rank: stock.tdxRank, src: 'tdx' },
      { rank: stock.xqRank, src: 'xueqiu' },
      { rank: stock.clsRank, src: 'cls' },
      { rank: stock.tgbRank, src: 'tgb' },
      { rank: stock.dzhRank, src: 'dzh' },
    ]

    for (const { rank, src } of rankData) {
      const total = platformTotals[src as keyof typeof platformTotals]
      const weight = this.getWeight(src)
      if (total > 0) {
        totalWeight += weight
        if (rank < DEFAULT_RANK) {
          platforms++
          weightedSum += (rank / total) * 100 * weight
        } else {
          weightedSum += PENALTY_SCORE * weight
        }
      }
    }

    stock.platforms = platforms
    if (totalWeight > 0) {
      stock.avgRankNum = weightedSum / totalWeight
      stock.avgRank = stock.avgRankNum.toFixed(1)
    }
    return stock
  }

  private calculateComprehensiveRank(data: any[]) {
    if (!data.length) return

    data.forEach((item) => {
      const cirMV = parseFloat(item.cirMV) || 1
      item.fundPenetration = ((parseFloat(item.zlje) || 0) / cirMV) * 100
    })

    const stats = {
      avgRankNum: { min: Infinity, max: -Infinity },
      zljzb: { min: Infinity, max: -Infinity },
      fundPenetration: { min: Infinity, max: -Infinity },
      turnover: { min: Infinity, max: -Infinity },
    }

    data.forEach((item) => {
      ;(['avgRankNum', 'zljzb', 'fundPenetration', 'turnover'] as const).forEach((key) => {
        const val = parseFloat(item[key]) || 0
        if (val < stats[key].min) stats[key].min = val
        if (val > stats[key].max) stats[key].max = val
      })
    })

    const normalize = (val: number, min: number, max: number, reverse = false) => {
      if (max === min) return 50
      const score = ((val - min) / (max - min)) * 100
      return reverse ? 100 - score : score
    }

    const getTurnoverScore = (rate: number) => {
      const r = parseFloat(rate as any) || 0
      return 100 * Math.exp(-Math.pow(r - OPTIMAL_TURNOVER, 2) / (2 * TURNOVER_SIGMA ** 2))
    }

    data.forEach((item) => {
      item.compScore =
        normalize(item.avgRankNum, stats.avgRankNum.min, stats.avgRankNum.max, true) *
          COMPREHENSIVE_WEIGHTS.HOT_RANK +
        normalize(item.zljzb, stats.zljzb.min, stats.zljzb.max) *
          COMPREHENSIVE_WEIGHTS.MONEY_RATIO +
        normalize(item.fundPenetration, stats.fundPenetration.min, stats.fundPenetration.max) *
          COMPREHENSIVE_WEIGHTS.FUND_PENETRATION +
        getTurnoverScore(item.turnoverRate) * COMPREHENSIVE_WEIGHTS.TURNOVER_RATE +
        normalize(item.turnover, stats.turnover.min, stats.turnover.max) *
          COMPREHENSIVE_WEIGHTS.VOLUME
    })

    const sorted = [...data].sort((a, b) => b.compScore - a.compScore)
    sorted.forEach((item, i) => (item.compRank = i + 1))
  }

  // ========== 工具方法 ==========
  private getPlatformTotals() {
    return {
      eastmoney: this.state.value.data?.eastmoney?.length || 0,
      ths: this.state.value.data?.ths?.length || 0,
      kpl: this.state.value.data?.kpl?.length || 0,
      tdx: this.state.value.data?.tdx?.length || 0,
      xueqiu: this.state.value.data?.xueqiu?.length || 0,
      cls: this.state.value.data?.cls?.length || 0,
      tgb: this.state.value.data?.tgb?.length || 0,
      dzh: this.state.value.data?.dzh?.length || 0,
    }
  }

  private getWeight(platform: string): number {
    const weightMap: Record<string, number> = {
      kpl: 1.0,
      tdx: 0.9,
      ths: 0.85,
      eastmoney: 0.75,
      dzh: 0.7,
      tgb: 0.4,
      xueqiu: 0.35,
      cls: 0.35,
    }
    return weightMap[platform] || 0.5
  }

  private isValidName(name: string): boolean {
    return !!(name && name !== '-' && name !== 'null' && name !== 'undefined' && name.trim() !== '')
  }

  private normalizeCode(code: string): string {
    if (!code) return ''
    return code.replace(/[^0-9]/g, '').padStart(6, '0')
  }

  getStats() {
    const debug = dataLayer.debug()
    return {
      total: debug.size.merged.stocks,
      platforms: Object.keys(this.state.value.data || {}).length,
      lastUpdate: this.state.value.lastUpdate,
      version: debug.version,
    }
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
    this.platformCache.clear()
    if (this.batchTimer) {
      clearTimeout(this.batchTimer)
      this.batchTimer = null
    }
    this.pendingCodes.clear()
    this.pendingQuoteRequests.clear()
  }

  clear() {
    this.destroy()
    this.state.value = {
      initialized: false,
      platforms: ['eastmoney', 'ths', 'kpl', 'tdx', 'xueqiu', 'cls', 'tgb', 'dzh'],
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
