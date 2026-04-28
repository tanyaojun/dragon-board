// src/services/dataLoader.ts

import { ref, readonly } from 'vue'
import { Adapters } from './adapters'
import { dataLayer } from './DataLayer'
import type { MergedStock } from './DataLayer'
import { apiService } from './apiService'
import { rankTrendAnalyzer } from './RankTrendAnalyzer'
import { applyRankTrendAnalysis } from './rankTrend/compat'
import type { RankTrendAnalysisResult } from './rankTrend/types'
import sectorAnalyzer from './sectorAnalyzer'
import { isTradingTime } from '../utils/time'
import {
  COMPREHENSIVE_WEIGHTS,
  PENALTY_SCORE,
  DEFAULT_RANK,
  OPTIMAL_TURNOVER,
  TURNOVER_SIGMA,
} from '../types/config'
import { filterValidStockCodes } from '../utils/common'
import { useUIStore } from '../stores/ui'
import { stockCodeManager } from './StockCodeManager'
import { calculateStockHotnessUpdates, stockHotnessConfigService } from './hotness'
import { resolvePrimaryStockTheme } from './theme/stockThemeMeta'
import { toLocalTradingDate } from './snapshot/identity'
import { EventManager } from '../utils/eventManager'
import { webSocketService } from './websocket'
import { AppEvents, type Depth10Book, type QuotePatch, type TickTrade } from '../types'

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

interface StockSignalUpdate {
  code: string
  rankTrend?: RankTrendAnalysisResult | null
  coverageWarning?: string | null
}

function isRankTrendAnalysisResult(value: unknown): value is RankTrendAnalysisResult {
  return !!(
    value &&
    typeof value === 'object' &&
    'meta' in value &&
    'technical' in value &&
    'cycle' in value &&
    'risk' in value &&
    'decision' in value
  )
}

export interface MergedQuoteData {
  price: number
  change: number
  speed?: number
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
  private readonly QUOTE_REFRESH_INTERVAL = 30000 // 30秒
  private readonly QUOTE_BATCH_SIZE = 50
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
  private lastPlatformRefresh = 0
  private readonly PLATFORM_CACHE_TTL = 1800000 // 30分钟（缓存有效期）
  private readonly MAX_CACHE_SIZE = 10
  private isLoadingDetails = false
  private destroyed = false
  private hotStockSet = new Set<string>()

  // 请求队列
  private pendingQuoteRequests: Map<
    string,
    { resolve: (value: any) => void; reject: (reason?: any) => void }
  > = new Map()
  private pendingCodes: Set<string> = new Set()
  private batchTimer: ReturnType<typeof setTimeout> | null = null
  private readonly BATCH_DELAY = 50
  private readonly REALTIME_FLUSH_DELAY = 50
  private realtimeFlushTimer: ReturnType<typeof setTimeout> | null = null
  private pendingRealtimeQuotes = new Map<string, QuotePatch>()
  private pendingDepthBooks = new Map<string, Depth10Book>()
  private pendingTicks = new Map<string, TickTrade[]>()
  private realtimeUnsubscribers: Array<() => void> = []

  private readonly PLATFORM_REFRESH_INTERVAL = 1800000 // 10分钟

  constructor() {
    console.log('[DataLoader] 初始化完成')
    this.setupRealtimeFeed()
    this.startQuoteAutoRefresh() // 自动启动行情刷新
  }

  private setupRealtimeFeed() {
    this.realtimeUnsubscribers.push(
      EventManager.on(AppEvents.WEBSOCKET.FULL_STATE, (payload: any) => {
        const quotes = Array.isArray(payload?.quotes) ? payload.quotes : []
        const depth = Array.isArray(payload?.depth) ? payload.depth : []
        this.queueRealtimeQuotes(quotes)
        this.queueDepthBooks(depth)
      }),
    )

    this.realtimeUnsubscribers.push(
      EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, (payload: any) => {
        this.queueRealtimeQuotes(Array.isArray(payload?.items) ? payload.items : [])
      }),
    )

    this.realtimeUnsubscribers.push(
      EventManager.on(AppEvents.WEBSOCKET.DEPTH_PATCH, (payload: any) => {
        this.queueDepthBooks(Array.isArray(payload?.items) ? payload.items : [])
      }),
    )

    this.realtimeUnsubscribers.push(
      EventManager.on(AppEvents.WEBSOCKET.TICKS_BATCH, (payload: any) => {
        const groups = Array.isArray(payload?.items) ? payload.items : []
        groups.forEach((group: { code?: string; items?: TickTrade[] }) => {
          const code = String(group?.code || '')
          if (!code) return
          const items = Array.isArray(group?.items) ? group.items : []
          if (!items.length) return

          const existing = this.pendingTicks.get(code) || []
          this.pendingTicks.set(code, existing.concat(items))
        })
        this.scheduleRealtimeFlush()
      }),
    )
  }

  private queueRealtimeQuotes(items: QuotePatch[]) {
    items.forEach((item) => {
      if (!item?.code) return
      this.pendingRealtimeQuotes.set(item.code, item)
    })
    this.scheduleRealtimeFlush()
  }

  private queueDepthBooks(items: Depth10Book[]) {
    items.forEach((item) => {
      if (!item?.code) return
      this.pendingDepthBooks.set(item.code, item)
    })
    this.scheduleRealtimeFlush()
  }

  private scheduleRealtimeFlush() {
    if (this.realtimeFlushTimer) return

    this.realtimeFlushTimer = setTimeout(() => {
      this.realtimeFlushTimer = null
      this.flushRealtimeUpdates()
    }, this.REALTIME_FLUSH_DELAY)
  }

  private flushRealtimeUpdates() {
    const quoteItems = Array.from(this.pendingRealtimeQuotes.values())
    const depthItems = Array.from(this.pendingDepthBooks.values())
    const tickGroups = Array.from(this.pendingTicks.entries()).map(([code, items]) => ({ code, items }))

    this.pendingRealtimeQuotes.clear()
    this.pendingDepthBooks.clear()
    this.pendingTicks.clear()

    if (quoteItems.length) {
      dataLayer.applyRealtimeQuoteBatch(
        quoteItems.map((item) => ({
          code: item.code,
          name: item.name,
          price: item.lastPrice,
          change: item.changePct,
          speed: item.speed,
          volume: item.volume,
          turnover: item.amount,
          turnoverRate: item.turnoverRate,
          sourceTs: item.sourceTs,
          seq: item.seq,
          timestamp: Date.now(),
        })),
      )
    }

    if (depthItems.length) {
      dataLayer.updateDepth10Batch(depthItems)
      dataLayer.updateL2SummaryBatch(depthItems.map((item) => this.buildDepthSummary(item)))
    }

    if (tickGroups.length) {
      dataLayer.updateRecentTicksBatch(tickGroups)
      dataLayer.updateL2SummaryBatch(
        tickGroups.map((group) => this.buildTickSummary(group.code, dataLayer.getRecentTicks(group.code))),
      )
    }

    if (quoteItems.length || depthItems.length || tickGroups.length) {
      EventManager.emit(AppEvents.DATA.UPDATED, {
        quotes: quoteItems.length,
        depth: depthItems.length,
        ticks: tickGroups.length,
        source: 'tdx_l2',
      })
    }
  }

  private buildDepthSummary(book: Depth10Book) {
    const bid1 = book.bids[0] || { price: 0, volume: 0 }
    const ask1 = book.asks[0] || { price: 0, volume: 0 }
    const bid10Total = book.bids.reduce((sum, level) => sum + (Number(level.volume) || 0), 0)
    const ask10Total = book.asks.reduce((sum, level) => sum + (Number(level.volume) || 0), 0)
    const total = bid10Total + ask10Total

    return {
      code: book.code,
      bid1Price: Number(bid1.price) || 0,
      bid1Volume: Number(bid1.volume) || 0,
      ask1Price: Number(ask1.price) || 0,
      ask1Volume: Number(ask1.volume) || 0,
      spread: Number(ask1.price) > 0 && Number(bid1.price) > 0 ? Number(ask1.price) - Number(bid1.price) : 0,
      bid10Total,
      ask10Total,
      depthImbalance: total > 0 ? Number(((bid10Total - ask10Total) / total).toFixed(4)) : 0,
      timestamp: Date.now(),
    }
  }

  private buildTickSummary(code: string, items: TickTrade[]) {
    const buyTrades = items.filter((item) => item.side === 'buy')
    const sellTrades = items.filter((item) => item.side === 'sell')
    const lastTrade = items[items.length - 1]

    return {
      code,
      tickBuyVolume: buyTrades.reduce((sum, item) => sum + (Number(item.volume) || 0), 0),
      tickSellVolume: sellTrades.reduce((sum, item) => sum + (Number(item.volume) || 0), 0),
      tickBuyCount: buyTrades.length,
      tickSellCount: sellTrades.length,
      lastTradePrice: Number(lastTrade?.price) || 0,
      lastTradeVolume: Number(lastTrade?.volume) || 0,
      timestamp: Date.now(),
    }
  }

  private syncRealtimeSubscription() {
    const codes = this.buildRealtimeSubscriptionCodes()
    webSocketService.setHotPool(codes)
  }

  private buildRealtimeSubscriptionCodes(): string[] {
    const hotCodes = Array.from(this.getAllHotCodes())
    if (!hotCodes.length) return []

    const hotCodeSet = new Set(hotCodes)
    const stocks = dataLayer
      .getStocks()
      .filter((stock) => hotCodeSet.has(stock.code))

    const getCompRank = (stock: any) => {
      const compRank = Number(stock?.compRank)
      if (Number.isFinite(compRank) && compRank > 0) return compRank
      const fallbackRank = Number(stock?.rank)
      if (Number.isFinite(fallbackRank) && fallbackRank > 0) return fallbackRank
      return 9999
    }

    const getFinalSignal = (stock: any) => stock?.rankTrend?.decision?.final?.signal ?? 'none'
    const getFinalConfidence = (stock: any) =>
      Number(stock?.rankTrend?.decision?.final?.confidence) || 0
    const getMacdCross = (stock: any) => stock?.rankTrend?.technical?.macd?.cross ?? 'none'

    const priorityOf = (stock: any) => {
      const withinTop50 = getCompRank(stock) <= 50
      const finalSignal = getFinalSignal(stock)
      const macdCross = getMacdCross(stock)

      if (withinTop50 && finalSignal === 'buy' && macdCross === 'golden') return 3
      if (withinTop50 && finalSignal === 'buy') return 2
      if (withinTop50) return 1
      return 0
    }

    const prioritizedCodes = stocks
      .slice()
      .sort((left: any, right: any) => {
        const rightPriority = priorityOf(right)
        const leftPriority = priorityOf(left)
        if (rightPriority !== leftPriority) return rightPriority - leftPriority

        const leftCompRank = getCompRank(left)
        const rightCompRank = getCompRank(right)
        if (leftCompRank !== rightCompRank) return leftCompRank - rightCompRank

        const rightConfidence = getFinalConfidence(right)
        const leftConfidence = getFinalConfidence(left)
        if (rightConfidence !== leftConfidence) return rightConfidence - leftConfidence

        const rightTurnover = Number(right?.turnover) || 0
        const leftTurnover = Number(left?.turnover) || 0
        if (rightTurnover !== leftTurnover) return rightTurnover - leftTurnover

        return String(left?.code || '').localeCompare(String(right?.code || ''))
      })
      .map((stock) => stock.code)

    const missingCodes = hotCodes.filter((code) => !prioritizedCodes.includes(code))
    return [...prioritizedCodes, ...missingCodes]
  }

  private isRealtimePrimaryHealthy(): boolean {
    const status = webSocketService.getStatus()
    return status.subscribedCount > 0 && webSocketService.isTdxRealtimeHealthy()
  }

  private buildRealtimeMergedQuoteData(code: string, quote: QuotePatch): MergedQuoteData {
    const existingQuote = dataLayer.getQuote(code) || {}
    const stock = dataLayer.getStock(code)
    const speedCandidate = quote.speed ?? existingQuote?.speed
    const speed = typeof speedCandidate === 'number' && Number.isFinite(speedCandidate) ? speedCandidate : undefined

    return {
      price: Number(quote.lastPrice) || 0,
      change: Number(quote.changePct) || 0,
      speed,
      volume: Number(quote.volume ?? stock?.volume ?? existingQuote?.volume) || 0,
      turnover: Number(quote.amount ?? stock?.turnover ?? existingQuote?.turnover) || 0,
      turnoverRate: Number(quote.turnoverRate ?? stock?.turnoverRate ?? existingQuote?.turnoverRate) || 0,
      pe: Number(stock?.pe ?? existingQuote?.pe) || 0,
      totalMV: Number(stock?.totalMV ?? existingQuote?.totalMV) || 0,
      cirMV: Number(stock?.cirMV ?? existingQuote?.cirMV) || 0,
      pb: Number(stock?.pb ?? existingQuote?.pb) || 0,
      zlje: Number(stock?.zlje ?? existingQuote?.zlje) || 0,
      zljzb: Number(stock?.zljzb ?? existingQuote?.zljzb) || 0,
      cddje: Number(stock?.cddje ?? existingQuote?.cddje) || 0,
      cddjzb: Number(stock?.cddjzb ?? existingQuote?.cddjzb) || 0,
      name: quote.name || stock?.name || existingQuote?.name,
      sources: ['tdx_l2'],
      confidence: 99,
      timestamp: Date.now(),
    }
  }

  private mergeHttpIntoRealtimeQuote(
    realtimeQuote: MergedQuoteData,
    httpQuote: MergedQuoteData,
  ): MergedQuoteData {
    const pickFinite = (primary: unknown, fallback: unknown, preferPositive = false) => {
      const primaryNumber = Number(primary)
      if (Number.isFinite(primaryNumber) && (!preferPositive || primaryNumber > 0)) {
        return primaryNumber
      }

      const fallbackNumber = Number(fallback)
      if (Number.isFinite(fallbackNumber) && (!preferPositive || fallbackNumber > 0)) {
        return fallbackNumber
      }

      return 0
    }

    return {
      ...httpQuote,
      ...realtimeQuote,
      price: pickFinite(realtimeQuote.price, httpQuote.price, true),
      change: pickFinite(realtimeQuote.change, httpQuote.change),
      volume: pickFinite(realtimeQuote.volume, httpQuote.volume, true),
      turnover: pickFinite(realtimeQuote.turnover, httpQuote.turnover, true),
      turnoverRate: pickFinite(realtimeQuote.turnoverRate, httpQuote.turnoverRate, true),
      pe: pickFinite(realtimeQuote.pe, httpQuote.pe),
      totalMV: pickFinite(realtimeQuote.totalMV, httpQuote.totalMV, true),
      cirMV: pickFinite(realtimeQuote.cirMV, httpQuote.cirMV, true),
      pb: pickFinite(realtimeQuote.pb, httpQuote.pb),
      zlje: pickFinite(realtimeQuote.zlje, httpQuote.zlje),
      zljzb: pickFinite(realtimeQuote.zljzb, httpQuote.zljzb),
      cddje: pickFinite(realtimeQuote.cddje, httpQuote.cddje),
      cddjzb: pickFinite(realtimeQuote.cddjzb, httpQuote.cddjzb),
      name: realtimeQuote.name || httpQuote.name,
      sources: Array.from(new Set([...(realtimeQuote.sources || []), ...(httpQuote.sources || [])])),
      confidence: Math.max(Number(realtimeQuote.confidence) || 0, Number(httpQuote.confidence) || 0),
      timestamp: Date.now(),
    }
  }

  private async maybeRefreshPlatformCache() {
    const currentTs = Date.now()
    if (currentTs - this.lastPlatformRefresh < this.PLATFORM_REFRESH_INTERVAL) {
      return
    }

    const cacheKey = 'platforms'
    const cached = this.platformCache.get(cacheKey)
    if (!cached || currentTs - cached.timestamp >= this.PLATFORM_CACHE_TTL) {
      await this.loadAllPlatforms(true)
      await this.loadLimitUpData(true)
      sectorAnalyzer.syncThemesToStocks()
    }

    this.lastPlatformRefresh = currentTs
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

  // ========== 行情服务 ==========
  /**
   * 启动行情自动刷新
   */
  startQuoteAutoRefresh(
    interval: number = this.QUOTE_REFRESH_INTERVAL,
    batchSize: number = this.QUOTE_BATCH_SIZE,
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

        console.log('[DataLoader] 行情刷新完成')
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
      const volumeHistoryMap = await this.buildVolumeHistoryMap(codes)

      const updates: Array<{ code: string; volumeRatio?: number }> = []

      for (const code of codes) {
        const stock = stocks.find((s) => s.code === code)
        if (stock && stock.volume && stock.volume > 0) {
          const volumeRatio = this.calculateVolumeRatioValue(stock, code, volumeHistoryMap)
          if (volumeRatio !== stock.volumeRatio) {
            updates.push({ code, volumeRatio })
          }
        }
      }

      if (updates.length) {
        console.log(`[DataLoader] 更新量比: ${updates.length} 只股票`)
        dataLayer.updateStockExtData(updates)
        EventManager.emit(AppEvents.DATA.MERGED, { count: dataLayer.getStocks().length, timestamp: Date.now() })
        useUIStore().updateDataVersion()
      }
    } catch (error) {
      console.warn('[DataLoader] 更新量比失败:', error)
    }
  }

  /**
   * 计算量比值（不修改 stock 对象）
   */
  private calculateVolumeRatioValue(
    stock: any,
    code: string,
    volumeHistoryMap: Map<string, number[]>,
  ): number | undefined {
    const currentVolume = Number(stock.volume)
    if (!Number.isFinite(currentVolume) || currentVolume <= 0) return undefined

    const volumes = this.resolveVolumeRatioHistory(currentVolume, volumeHistoryMap.get(code))
    if (volumes.length === 0) return undefined

    const WEIGHTS = [5, 3, 2]
    const daysToUse = Math.min(volumes.length, WEIGHTS.length)

    let weightedSum = 0
    let totalWeight = 0

    for (let i = 0; i < daysToUse; i++) {
      weightedSum += volumes[i] * WEIGHTS[i]
      totalWeight += WEIGHTS[i]
    }

    if (totalWeight === 0) return undefined

    const avgVolume = weightedSum / totalWeight
    if (avgVolume <= 0) return undefined

    let ratio = currentVolume / avgVolume
    ratio = Math.min(10, Math.max(0.1, Number(ratio.toFixed(2))))
    return ratio
  }

  private resolveVolumeRatioHistory(currentVolume: number, volumes?: number[]): number[] {
    if (!volumes?.length) return []

    const normalized = volumes
      .map((volume) => Number(volume))
      .filter((volume) => Number.isFinite(volume) && volume > 0)

    if (!normalized.length) return []

    const latestVolume = normalized[0]
    const relativeDiff = Math.abs(latestVolume - currentVolume) / currentVolume

    // 收盘后或凌晨刷新时，当前行情仍可能属于上一交易日。
    // 如果最新日级快照成交量等于当前成交量，先剔除它，再用前三个历史交易日计算。
    if (normalized.length > 1 && relativeDiff <= 0.001) {
      return normalized.slice(1, 4)
    }

    return normalized.slice(0, 3)
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
    const realtimePrimary = this.isRealtimePrimaryHealthy()
    const enrichmentCodes = new Set<string>()

    if (realtimePrimary) {
      const realtimeQuotes = webSocketService.getQuotesBatch(validCodes)
      realtimeQuotes.forEach((quote, code) => {
        const mergedRealtimeQuote = this.buildRealtimeMergedQuoteData(code, quote)
        result.set(code, mergedRealtimeQuote)
        if (
          (quote.turnoverRate === undefined || quote.turnoverRate === null) &&
          !(Number(mergedRealtimeQuote.turnoverRate) > 0)
        ) {
          enrichmentCodes.add(code)
        }
      })
    }

    const missingCodes = validCodes.filter((code) => !result.has(code))
    const httpCodes = [...new Set([...missingCodes, ...Array.from(enrichmentCodes)])]
    if (httpCodes.length === 0) {
      return result
    }

    const httpResult = new Map<string, MergedQuoteData>()

    // 并行请求基础数据和完整数据
    const [basicResult, fullResult] = await Promise.allSettled([
      this.fetchBasicData(httpCodes),
      this.fetchFullData(httpCodes, options.force),
    ])

    // 处理基础数据
    if (basicResult.status === 'fulfilled' && basicResult.value.size > 0) {
      basicResult.value.forEach((quote, code) => {
        httpResult.set(code, {
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
        const existing = httpResult.get(code)
        if (existing) {
          httpResult.set(code, {
            ...existing,
            ...fullQuote,
            sources: [...existing.sources, fullQuote.source],
            confidence: 95,
            timestamp: Date.now(),
          })
        } else {
          httpResult.set(code, {
            ...fullQuote,
            timestamp: Date.now(),
            sources: [fullQuote.source],
            confidence: 95,
          })
        }
      })
    }

    httpResult.forEach((quote, code) => {
      const realtimeQuote = result.get(code)
      if (realtimeQuote) {
        result.set(code, this.mergeHttpIntoRealtimeQuote(realtimeQuote, quote))
        return
      }

      result.set(code, quote)
    })

    return result
  }
  /**
   * 获取单只股票行情（带量比计算）
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
    if (!quote) return null

    // 更新行情
    dataLayer.updateQuote(code, quote)

    return quote || null
  }

  /**
   * 批量获取行情（带量比计算）
   */
  async getQuotes(codes: string[], force = false): Promise<Map<string, any>> {
    const quotes = await this.fetchMergedQuotes(codes, { force })
    const result = new Map()

    // 收集需要计算量比的股票数据
    const stocksToCalc: Array<{ code: string; name: string; volume: number }> = []

    quotes.forEach((quote, code) => {
      const stockData = {
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
      }
      result.set(code, stockData)
      dataLayer.updateQuote(code, quote)

      // 收集有成交量的股票
      if (stockData.volume > 0) {
        stocksToCalc.push({
          code,
          name: stockData.name,
          volume: stockData.volume,
        })
      }
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
    const batchSize = 50

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
    const batchSize = 50

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
    const batchSize = 50

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

      const updatedCount = sectorAnalyzer.syncThemesToStocks()
      if (updatedCount > 0) console.log(`[DataLoader] 刷新后同步题材: ${updatedCount}只股票`)

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
    if (this.destroyed || this.state.value.loading) return

    const cacheKey = 'platforms'
    const cached = this.platformCache.get('platforms')

    if (!force && cached && Date.now() - cached.timestamp < this.PLATFORM_CACHE_TTL) {
      this.state.value.data = cached.data
      this.state.value.lastUpdate = cached.timestamp
      this.state.value.loading = false
      return
    }

    this.setLoading(true, '加载平台热榜...', 10)
    const results: Record<string, any[]> = {}
    const stockMap = new Map<string, any>()
    const platforms = this.state.value.platforms

    this.updateProgress(10, `加载平台数据 0/${platforms.length}`)

    const allResults = await Promise.allSettled(
      platforms.map(async (platform) => {
        try {
          const adapter = Adapters[platform as keyof typeof Adapters]
          if (!adapter) return { platform, data: [], success: false }
          const rawData = await adapter.getHotList()
          const formatted = adapter.format(rawData)
          return { platform, data: formatted, success: true }
        } catch (error) {
          console.warn(`[DataLoader] 平台 ${platform} 加载失败:`, error)
          return { platform, data: [], success: false }
        }
      }),
    )

    // 处理结果
    allResults.forEach((result) => {
      if (result.status === 'fulfilled' && result.value.success) {
        const { platform, data } = result.value
        results[platform] = data
        data.forEach((item: any) => {
          if (item?.code) stockMap.set(item.code, true)
        })
      } else {
        const failedPlatform = (result as any).value?.platform
        if (failedPlatform) results[failedPlatform] = []
      }
    })

    this.updateProgress(50, `加载平台数据完成`)
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

  // ========== 加载行情数据 ==========
  async loadStockDetails(force = false): Promise<Map<string, any> | void> {
    if (this.destroyed || this.isLoadingDetails) return
    this.isLoadingDetails = true

    try {
      const allCodes = this.getAllHotCodes()
      if (allCodes.size === 0) return

      const codesArray = Array.from(allCodes)
      this.updateProgress(200, `加载行情数据 ${codesArray.length} 只...`)
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
  /**
   * 合并数据主入口
   */
  async mergeData(): Promise<any[]> {
    // 1. 获取历史成交量索引
    const allCodes = this.getAllHotCodes()
    const codesArray = Array.from(allCodes)
    const volumeHistoryMap = await this.buildVolumeHistoryMap(codesArray)

    // 2. ✅ 先加载行情数据
    let quotesMap = new Map<string, any>()
    if (allCodes.size > 0) {
      quotesMap = await this.getQuoteBatch(codesArray, true)
    }

    // 3. 获取现有 stocks（用于保留已有数据）
    const existingStocks = dataLayer.getMergedStocks()
    const existingMap = new Map(existingStocks.map((s) => [s.code, s]))

    // 4. 构建股票数据（传入行情数据）
    const stockMap = await this.buildStockMap(quotesMap, volumeHistoryMap, existingMap)

    // 5. 名称兜底
    this.StockNames(stockMap)

    // 6. 计算综合排名
    let merged = await this.calculateRanks(stockMap)

    // 7. 合并额外数据
    merged = this.mergeExtraData(merged)

    // 8. 计算个股热度
    this.updateStockHotness(merged)

    // 9. 计算信号
    merged = await this.calculateSignals(merged)

    // 10. 存储到 DataLayer
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
    const updates = calculateStockHotnessUpdates(
      stocks,
      this.state.value.platforms?.length || 8,
      stockHotnessConfigService.getConfig(),
    )

    const hotnessMap = new Map(updates.map((item) => [item.code, item.hotness]))
    stocks.forEach((stock) => {
      stock.hotness = hotnessMap.get(stock.code) ?? 0
    })

    dataLayer.updateStockHotness(updates)
  }

  /**
   * 对外暴露热度重算入口，方便后续接参数优化器或开发期手工微调。
   */
  recalculateStockHotness(): MergedStock[] {
    const stocks = dataLayer.getStocks().map((stock) => ({ ...stock }))
    if (!stocks.length) return []

    this.updateStockHotness(stocks)
    dataLayer.setMergedStocks(stocks)
    EventManager.emit(AppEvents.DATA.MERGED, { count: stocks.length, timestamp: Date.now() })
    useUIStore().updateDataVersion()
    return stocks
  }

  /**
   * 合并额外数据（从 DataLayer 迁移）
   * 包括：题材、JXBK、龙头、涨停扩展数据
   */
  private mergeExtraData(stocks: any[]): any[] {
    return stocks.map((stock) => {
      const {
        reviewAuthority: _reviewAuthority,
        reviewRole: _reviewRole,
        tradeability: _tradeability,
        chaseRisk: _chaseRisk,
        ...merged
      } = stock

      // 合并题材数据
      const themes = dataLayer.getStockThemes(stock.code) || []
      merged.themes = themes
      const primaryTheme = resolvePrimaryStockTheme(themes)
      merged.mainTheme = primaryTheme.mainTheme
      merged.themeHeat = primaryTheme.themeHeat
      merged.themeLevel = primaryTheme.themeLevel

      const realtimeQuote = dataLayer.getQuote(stock.code)
      const realtimeSpeed = Number(realtimeQuote?.speed)
      const hasRealtimeSpeed = Number.isFinite(realtimeSpeed)
      if (hasRealtimeSpeed) {
        merged.speed = realtimeSpeed
      }

      // 合并 JXBK 数据
      const jxbkStock = dataLayer.getJxbkStock(stock.code)
      if (jxbkStock) {
        if (!hasRealtimeSpeed) {
          merged.speed = jxbkStock.speed
        }
        merged.leadTimes = jxbkStock.leadTimes
        merged.leadStatus = jxbkStock.leadStatus
        merged.lianbanStr = jxbkStock.lianban
        merged.bigMoney300 = jxbkStock.bigMoney300
        merged.popularity = jxbkStock.popularity
        merged.popularityChange = jxbkStock.popularityChange
        merged.institutionBuy = jxbkStock.institutionBuy
        merged.mainBuy = jxbkStock.mainBuy
        merged.mainSell = jxbkStock.mainSell
        merged.fengdan = jxbkStock.fengdan
        merged.maxFengdan = jxbkStock.maxFengdan
        merged.cirMV = jxbkStock.cirMV
      }

      const leaderRecord = dataLayer.getLeaderByCode(stock.code)
      if (leaderRecord) {
        merged.reviewAuthority = leaderRecord.authority
        merged.reviewRole = leaderRecord.primaryRole
        merged.tradeability = leaderRecord.tradeability
        merged.chaseRisk = leaderRecord.chaseRisk
      }

      // 合并涨停扩展数据
      const limitUpData = dataLayer.getLimitUpData(stock.code)
      if (limitUpData) {
        merged.fengdan = limitUpData.fengdan ?? merged.fengdan
        merged.maxFengdan = limitUpData.maxFengdan ?? merged.maxFengdan
        merged.leadStatus = limitUpData.leadStatus ?? merged.leadStatus
        merged.leadTimes = limitUpData.leadTimes ?? merged.leadTimes
        merged.lianbanStr = limitUpData.lianbanStr ?? merged.lianbanStr
        merged.firstZtTime = limitUpData.firstZtTime ?? merged.firstZtTime
        merged.lastZtTime = limitUpData.lastZtTime ?? merged.lastZtTime
        merged.reason = limitUpData.reason ?? merged.reason
        merged.tags = limitUpData.tags ?? merged.tags
        merged.isNew = limitUpData.isNew ?? merged.isNew
      }

      merged.continuousDays = this.resolveContinuousDays(merged, jxbkStock, limitUpData, leaderRecord)

      return merged
    })
  }

  private parseContinuousDays(value?: string | number | null): number | null {
    if (typeof value === 'number' && Number.isFinite(value) && value > 0) return value
    if (!value) return null

    const text = String(value)
    if (text.includes('首板')) return 1

    const match = text.match(/(\d+)/)
    if (!match) return null

    const parsed = Number(match[1])
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null
  }

  private resolveContinuousDays(
    stock: any,
    jxbkStock: any,
    limitUpData: any,
    leaderRecord: ReturnType<typeof dataLayer.getLeaderByCode>,
  ): number {
    const candidates = [
      leaderRecord?.continuousDays,
      limitUpData?.highDays,
      this.parseContinuousDays(limitUpData?.lianbanStr),
      this.parseContinuousDays(stock.lianbanStr),
      this.parseContinuousDays(jxbkStock?.lianban),
      this.parseContinuousDays(stock.highDays),
      this.parseContinuousDays(stock.continuousDays),
    ]

    const resolved = candidates.find(
      (value) => typeof value === 'number' && Number.isFinite(value) && value > 0,
    )

    return resolved ?? 1
  }

  /**
   * 1. 构建历史成交量索引
   * 正式主链只按 code + daily + tradingDate 读取日级快照投影行，
   * 返回最近 4 个交易日成交量，供后续剔除“当前成交量与最新日级快照重复”的场景。
   */
  public async buildVolumeHistoryMap(codes: string[] = []): Promise<Map<string, number[]>> {
    const targetCodes = filterValidStockCodes([...new Set(codes)])
    if (targetCodes.length === 0) return new Map()
    return dataLayer.getStockVolumeHistory(targetCodes, {
      anchorTradingDate: toLocalTradingDate(new Date()),
      lookbackDays: 4,
    })
  }

  /**
   * 2. 构建股票数据（合并平台排名 + 行情数据 + 量比计算）
   */
  private async buildStockMap(
    useLatestQuotes: Map<string, any> | undefined,
    volumeHistoryMap: Map<string, number[]>,
    existingMap: Map<string, any>,
  ): Promise<Map<string, any>> {
    const quoteMap = useLatestQuotes ?? new Map()
    const stockMap = new Map<string, any>()
    const quoteProcessedCodes = new Set<string>()
    const volumeRatioCalculatedCodes = new Set<string>()

    for (const [platform, items] of Object.entries(this.state.value.data || {})) {
      for (const item of items) {
        const code = item.code
        if (!code) continue

        // 直接从 existingMap 获取现有数据，保留行情
        let stock = stockMap.get(code)
        if (!stock) {
          const existing = existingMap.get(code)
          stock = existing ? { ...existing } : this.createEmptyStock(code)
          stockMap.set(code, stock)
        }

        // 平台排名 - 直接覆盖
        const rankField = this.getRankField(platform)
        if (rankField) {
          stock[rankField] = item.rank
        }

        // 名称
        if (this.isValidName(item.name) && !stock.platformName) {
          stock.platformName = item.name
        }

        // 行情数据（本轮合并只处理一次，避免把临时标记写进股票对象）
        if (quoteMap.has(code) && !quoteProcessedCodes.has(code)) {
          this.mergeQuoteData(stock, code, quoteMap)
          quoteProcessedCodes.add(code)
        }

        // 量比不依赖行情请求是否命中；只要当前 stock 有成交量，就按日级投影表历史量重算。
        if (!volumeRatioCalculatedCodes.has(code)) {
          this.calculateVolumeRatio(stock, code, volumeHistoryMap)
          volumeRatioCalculatedCodes.add(code)
        }
      }
    }

    // 添加没有平台排名的股票（保留原有数据）
    for (const [code, existing] of existingMap.entries()) {
      if (!stockMap.has(code)) {
        const stock = { ...existing }
        if (quoteMap.has(code) && !quoteProcessedCodes.has(code)) {
          this.mergeQuoteData(stock, code, quoteMap)
          quoteProcessedCodes.add(code)
        }
        if (!volumeRatioCalculatedCodes.has(code)) {
          this.calculateVolumeRatio(stock, code, volumeHistoryMap)
          volumeRatioCalculatedCodes.add(code)
        }
        stockMap.set(code, stock)
      }
    }

    return stockMap
  }

  /**
   * 合并行情数据到股票对象
   */
  private mergeQuoteData(stock: any, code: string, quoteMap: Map<string, any>): void {
    const quote = quoteMap.get(code)
    if (!quote) return

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

    let stockName = ''

    if (quote.name && quote.name !== '-' && quote.name !== '') {
      stockName = quote.name
    } else if (stock.platformName && stock.platformName !== '-' && stock.platformName !== '') {
      stockName = stock.platformName
    }

    // 如果还是没有有效名称，从 StockCodeManager 获取
    if (!stockName || stockName === '' || stockName === '-') {
      const codeInfo = stockCodeManager.getStockInfo(code)
      if (codeInfo && codeInfo.name && codeInfo.name !== '未知') {
        stockName = codeInfo.name
        console.log(`[DataLoader] 从 StockCodeManager 获取名称: ${code} -> ${stockName}`)
      }
    }

    if (stockName) {
      stock.name = stockName
    }
  }

  /**
   * 计算量比（使用三日移动加权平均，权重 5:3:2）
   * 量比 = 当前成交量 / 加权平均成交量
   * 权重说明：昨日(最新)权重5，前日权重3，大前日权重2
   */
  private calculateVolumeRatio(
    stock: any,
    code: string,
    volumeHistoryMap: Map<string, number[]>,
  ): void {
    stock.volumeRatio = this.calculateVolumeRatioValue(stock, code, volumeHistoryMap)
  }

  /**
   * 批量更新股票信号（从 RankTrendAnalyzer 调用）
   */
  updateStockSignals(
    updates: StockSignalUpdate[],
  ) {
    // 获取当前 merged.stocks
    const stocks = dataLayer.getStocks()
    const stockMap = new Map(stocks.map((s) => [s.code, s]))

    // 应用更新
    for (const update of updates) {
      const stock = stockMap.get(update.code)
      if (stock) {
        applyRankTrendAnalysis(
          stock,
          isRankTrendAnalysisResult(update.rankTrend) ? update.rankTrend : null,
        )
        stock.rankTrendCoverageWarning = update.coverageWarning || undefined
      }
    }

    // 存回 DataLayer
    const mergedStocks = Array.from(stockMap.values())
    dataLayer.setMergedStocks(mergedStocks)
    EventManager.emit(AppEvents.DATA.MERGED, { count: mergedStocks.length, timestamp: Date.now() })
    useUIStore().updateDataVersion()
  }

  async refreshRankTrendSignals(): Promise<void> {
    const stocks = dataLayer.getStocks()
    if (!stocks.length) return

    const rankMap = new Map<string, number>()
    stocks.forEach((stock, index) => {
      rankMap.set(stock.code, index + 1)
    })

    const results = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
    })
    const coverageWarning = this.extractRankTrendCoverageWarning(results)

    const updates: StockSignalUpdate[] = []
    for (const [code, rankTrend] of results.entries()) {
      updates.push({ code, rankTrend, coverageWarning })
    }

    if (coverageWarning) {
      console.warn('[DataLoader] 排名趋势信号使用了不完整快照样本:', coverageWarning)
    }

    this.updateStockSignals(updates)
  }

  /**
   * 3. 名称兜底（如果行情没有名称，用平台名称）
   */
  private StockNames(stockMap: Map<string, any>): void {
    for (const stock of stockMap.values()) {
      // 检查名称是否有效
      const hasValidName = this.isValidName(stock.name)

      if (!hasValidName && stock.platformName) {
        stock.name = stock.platformName
      }

      if (!this.isValidName(stock.name)) {
        const codeInfo = stockCodeManager.getStockInfo(stock.code)
        if (codeInfo && this.isValidName(codeInfo.name)) {
          stock.name = codeInfo.name
        }
      }

      // 最终兜底
      if (!this.isValidName(stock.name)) {
        stock.name = '-'
      }

      delete stock._quoteProcessed
    }
  }

  /**
   * 4. 计算综合排名
   */
  private async calculateRanks(stockMap: Map<string, any>): Promise<any[]> {
    const platformTotals = this.getPlatformTotals()

    let merged = Array.from(stockMap.values())
    merged = merged.map((s) => this.calculateAvgRank(s, platformTotals))

    // ✅ 计算综合排名（会设置 fundPenetration 和 compScore）
    this.calculateComprehensiveRank(merged)

    // ✅ 关键修复：按综合得分重新排序
    merged.sort((a, b) => (b.compScore || 0) - (a.compScore || 0))

    // 重新设置显示排名
    merged.forEach((item, index) => {
      item.rank = index + 1
    })

    return merged
  }

  /**
   * 5. 计算信号（排名变化 + 四维信号）
   */
  private async calculateSignals(merged: any[]): Promise<any[]> {
    const newRankMap = new Map(merged.map((s, i) => [s.code, i + 1]))
    const rankTrends = await rankTrendAnalyzer.getRankTrends(newRankMap)
    const coverageWarning = this.extractRankTrendCoverageWarning(rankTrends)

    for (const stock of merged) {
      stock.rank = newRankMap.get(stock.code)

      // 题材数据
      const themes = dataLayer.getStockThemes(stock.code)
      stock.themes = themes
      const primaryTheme = resolvePrimaryStockTheme(themes || [])
      stock.mainTheme = primaryTheme.mainTheme
      stock.themeHeat = primaryTheme.themeHeat
      stock.themeLevel = primaryTheme.themeLevel

      // 扩展数据
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

      // 应用信号
      const trend = rankTrends.get(stock.code)
      applyRankTrendAnalysis(stock, isRankTrendAnalysisResult(trend) ? trend : null)
      stock.rankTrendCoverageWarning = coverageWarning || undefined
    }

    if (coverageWarning) {
      console.warn('[DataLoader] 综合榜单信号基于不完整快照样本:', coverageWarning)
    }
    return merged
  }

  private extractRankTrendCoverageWarning(
    results: Map<string, RankTrendAnalysisResult>,
  ): string | null {
    for (const result of results.values()) {
      const warning = result?.meta?.sampleQuality?.coverageWarning
      if (warning) return warning
    }
    return null
  }
  /**
   * 创建空股票对象（修改版）
   */
  private createEmptyStock(code: string): MergedStock {
    // ✅ 尝试从 StockCodeManager 获取名称
    let defaultName = ''
    const codeInfo = stockCodeManager.getStockInfo(code)
    if (codeInfo && this.isValidName(codeInfo.name)) {
      defaultName = codeInfo.name
    }

    return {
      code,
      name: defaultName,
      price: 0,
      change: 0,
      volume: 0,
      turnover: 0,
      turnoverRate: 0,
      pe: 0,
      pb: 0,
      totalMV: 0,
      cirMV: 0,
      zlje: 0,
      zljzb: 0,
      cddje: 0,
      cddjzb: 0,
      emRank: DEFAULT_RANK,
      thsRank: DEFAULT_RANK,
      kplRank: DEFAULT_RANK,
      tdxRank: DEFAULT_RANK,
      xqRank: DEFAULT_RANK,
      clsRank: DEFAULT_RANK,
      tgbRank: DEFAULT_RANK,
      dzhRank: DEFAULT_RANK,
      platforms: 0,
      avgRankNum: DEFAULT_RANK,
      avgRank: DEFAULT_RANK.toString(),
      compRank: undefined,
      compScore: 0,
      updatedAt: Date.now(),
      continuousDays: 1,
      themes: [],
      hotness: 0,
      tags: [],
      reason: '',
      isNew: false,
      firstZtTime: '',
      lastZtTime: '',
      boardHeight: 0,
      highDays: 0,
      platformName: '',
      fundPenetration: 0,
      firstSeen: undefined,
      lastSeen: undefined,
      mainTheme: undefined,
      themeHeat: 0,
      themeLevel: '冷',
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

    // ✅ 第一步：正确计算资金渗透率（只计算一次）
    data.forEach((item) => {
      const cirMV = parseFloat(item.cirMV) || 0
      const zlje = parseFloat(item.zlje) || 0
      if (cirMV > 0 && zlje !== 0) {
        // cirMV 已经是元为单位，不需要转换
        item.fundPenetration = (zlje / cirMV) * 100
      } else {
        item.fundPenetration = 0
      }
    })

    // ✅ 第二步：计算各指标的最大最小值
    const stats = {
      avgRankNum: { min: Infinity, max: -Infinity },
      zljzb: { min: Infinity, max: -Infinity },
      fundPenetration: { min: Infinity, max: -Infinity },
      turnover: { min: Infinity, max: -Infinity },
    }

    data.forEach((item) => {
      const avgRankNum = parseFloat(item.avgRankNum) || 0
      const zljzb = parseFloat(item.zljzb) || 0
      const fundPenetration = parseFloat(item.fundPenetration) || 0
      const turnover = parseFloat(item.turnover) || 0

      if (avgRankNum < stats.avgRankNum.min) stats.avgRankNum.min = avgRankNum
      if (avgRankNum > stats.avgRankNum.max) stats.avgRankNum.max = avgRankNum
      if (zljzb < stats.zljzb.min) stats.zljzb.min = zljzb
      if (zljzb > stats.zljzb.max) stats.zljzb.max = zljzb
      if (fundPenetration < stats.fundPenetration.min) stats.fundPenetration.min = fundPenetration
      if (fundPenetration > stats.fundPenetration.max) stats.fundPenetration.max = fundPenetration
      if (turnover < stats.turnover.min) stats.turnover.min = turnover
      if (turnover > stats.turnover.max) stats.turnover.max = turnover
    })

    // ✅ 调试：输出统计范围
    console.log('[DEBUG] 统计范围:', {
      zljzb: { min: stats.zljzb.min, max: stats.zljzb.max },
      fundPenetration: { min: stats.fundPenetration.min, max: stats.fundPenetration.max },
      turnover: { min: stats.turnover.min, max: stats.turnover.max },
    })

    // ✅ 第三步：标准化函数
    const normalize = (val: number, min: number, max: number, reverse = false) => {
      if (isNaN(val) || val === null || val === undefined) return reverse ? 100 : 0
      if (max === min || isNaN(min) || isNaN(max) || min === Infinity || max === -Infinity) {
        // 如果范围无效，根据 val 的正负返回合理值
        if (val > 0) return reverse ? 0 : 100
        if (val < 0) return reverse ? 100 : 0
        return 50
      }
      const score = ((val - min) / (max - min)) * 100
      const clampedScore = Math.min(100, Math.max(0, score))
      return reverse ? 100 - clampedScore : clampedScore
    }

    // ✅ 第四步：换手率评分
    const getTurnoverScore = (rate: number) => {
      const r = parseFloat(rate as any) || 0
      return 100 * Math.exp(-Math.pow(r - OPTIMAL_TURNOVER, 2) / (2 * TURNOVER_SIGMA ** 2))
    }

    // ✅ 第五步：计算综合得分
    data.forEach((item) => {
      const avgRankNum = parseFloat(item.avgRankNum) || 0
      const zljzb = parseFloat(item.zljzb) || 0
      const fundPenetration = parseFloat(item.fundPenetration) || 0
      const turnover = parseFloat(item.turnover) || 0

      item.compScore =
        normalize(avgRankNum, stats.avgRankNum.min, stats.avgRankNum.max, true) *
          COMPREHENSIVE_WEIGHTS.HOT_RANK +
        normalize(zljzb, stats.zljzb.min, stats.zljzb.max, false) *
          COMPREHENSIVE_WEIGHTS.MONEY_RATIO +
        normalize(fundPenetration, stats.fundPenetration.min, stats.fundPenetration.max, false) *
          COMPREHENSIVE_WEIGHTS.FUND_PENETRATION +
        getTurnoverScore(item.turnoverRate) * COMPREHENSIVE_WEIGHTS.TURNOVER_RATE +
        normalize(turnover, stats.turnover.min, stats.turnover.max, false) *
          COMPREHENSIVE_WEIGHTS.VOLUME
    })

    // ✅ 第六步：按综合得分排序
    const sorted = [...data].sort((a, b) => (b.compScore || 0) - (a.compScore || 0))
    sorted.forEach((item, i) => {
      item.compRank = i + 1
    })
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
    if (this.realtimeFlushTimer) {
      clearTimeout(this.realtimeFlushTimer)
      this.realtimeFlushTimer = null
    }
    this.realtimeUnsubscribers.forEach((unsubscribe) => unsubscribe())
    this.realtimeUnsubscribers = []
    this.pendingRealtimeQuotes.clear()
    this.pendingDepthBooks.clear()
    this.pendingTicks.clear()
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
