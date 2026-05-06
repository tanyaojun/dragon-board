import { debugLog } from '@/utils/logger'
// src/services/dataLoader.ts

import { ref, readonly } from 'vue'
import { Adapters } from './adapters'
import { dataLayer } from './DataLayer'
import type { MergedStock } from '@/types'
import { rankTrendAnalyzer } from './RankTrendAnalyzer'
import { applyRankTrendAnalysis } from './rankTrend/compat'
import type { RankTrendAnalysisResult } from './rankTrend/types'
import { themeFacade } from './theme/ThemeFacade'
import { isTradingTime } from '@/utils/time'
import { DEFAULT_RANK } from '@/types/config'
import { filterValidStockCodes } from '@/utils/common'
import { useUIStore } from '../stores/ui'
import { stockCodeManager } from './StockCodeManager'
import { calculateStockHotnessUpdates, stockHotnessConfigService } from './hotness'
import { resolvePrimaryStockTheme } from './theme/stockThemeMeta'
import { clamp } from './theme/utils'
import { toLocalTradingDate } from './snapshot/identity'
import { slotTimeToMinutes } from './snapshot/schedule'
import { snapshotFacade } from './snapshot/facade'
import type { SnapshotRecord, SnapshotStockRow } from './snapshot/types'
import { EventManager } from '../utils/eventManager'
import { webSocketService } from './websocket'
import { AppEvents, type Depth10Book, type QuotePatch, type TickTrade } from '../types'
import {
  DEFAULT_PLATFORMS,
  INTRADAY_VOLUME_SNAPSHOT_TYPES as DEFAULT_INTRADAY_VOLUME_SNAPSHOT_TYPES,
  MAX_PLATFORM_CACHE_SIZE,
  PLATFORM_CACHE_TTL_MS,
  PLATFORM_REFRESH_INTERVAL_MS,
  QUOTE_BATCH_DELAY_MS,
  QUOTE_BATCH_SIZE as DEFAULT_QUOTE_BATCH_SIZE,
  QUOTE_REFRESH_INTERVAL_MS,
  REALTIME_FLUSH_DELAY_MS,
} from './dataLoader/constants'
import { getRankField, rankMergedStocks } from './dataLoader/ComprehensiveRankEngine'
import { loadLimitUpData as loadLimitUpFeedData } from './dataLoader/LimitUpFeed'
import { estimateTdxMoneyFlow, summarizeMoneyFlowTicks } from './dataLoader/MoneyFlowEstimator'
import { quoteHttpFeed } from './dataLoader/QuoteHttpFeed'
import {
  calculateVolumeRatioValue,
  getAshareVolumeClockMinute,
} from './dataLoader/VolumeRatioCalculator'
import type {
  IntradayMoneyFlowStats,
  LoaderState,
  LoadingStatus,
  MergedQuoteData,
  StockSignalUpdate,
} from './dataLoader/types'

export type { MergedQuoteData } from './dataLoader/types'

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

/**
 * 业务编排层
 * 职责：协调数据加载、合并计算、缓存策略、行情获取
 */
class DataLoaderService {
  private quoteRefreshTimer: ReturnType<typeof setInterval> | null = null
  private readonly QUOTE_REFRESH_INTERVAL = QUOTE_REFRESH_INTERVAL_MS
  private readonly QUOTE_BATCH_SIZE = DEFAULT_QUOTE_BATCH_SIZE
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

  private platformCache = new Map<string, { data: any; timestamp: number }>()
  private lastPlatformRefresh = 0
  private readonly PLATFORM_CACHE_TTL = PLATFORM_CACHE_TTL_MS
  private readonly MAX_CACHE_SIZE = MAX_PLATFORM_CACHE_SIZE
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
  private readonly BATCH_DELAY = QUOTE_BATCH_DELAY_MS
  private readonly REALTIME_FLUSH_DELAY = REALTIME_FLUSH_DELAY_MS
  private readonly INTRADAY_VOLUME_SNAPSHOT_TYPES = DEFAULT_INTRADAY_VOLUME_SNAPSHOT_TYPES
  private realtimeFlushTimer: ReturnType<typeof setTimeout> | null = null
  private pendingRealtimeQuotes = new Map<string, QuotePatch>()
  private pendingDepthBooks = new Map<string, Depth10Book>()
  private pendingTicks = new Map<string, TickTrade[]>()
  private intradayMoneyFlowStats = new Map<string, IntradayMoneyFlowStats>()
  private intradayMoneyFlowTickKeys = new Map<string, Set<string>>()
  private intradayMoneyFlowTickQueues = new Map<string, string[]>()
  private realtimeUnsubscribers: Array<() => void> = []

  private readonly PLATFORM_REFRESH_INTERVAL = PLATFORM_REFRESH_INTERVAL_MS // 30分钟

  constructor() {
    debugLog('[DataLoader] 初始化完成')
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

    if (tickGroups.length) {
      this.updateIntradayMoneyFlowStats(tickGroups)
    }

    if (quoteItems.length) {
      dataLayer.applyRealtimeQuoteBatch(
        quoteItems.map((item) => {
          const estimatedMoneyFlow = estimateTdxMoneyFlow(item.code, item)
          return {
            code: item.code,
            name: item.name,
            price: item.lastPrice,
            change: item.changePct,
            speed: item.speed,
            volume: item.volume,
            turnover: item.amount,
            turnoverRate: item.turnoverRate,
            zlje: estimatedMoneyFlow?.zlje,
            zljzb: estimatedMoneyFlow?.zljzb,
            cddje: estimatedMoneyFlow?.cddje,
            cddjzb: estimatedMoneyFlow?.cddjzb,
            moneyFlowSource: estimatedMoneyFlow?.moneyFlowSource,
            moneyFlowEstimated: estimatedMoneyFlow?.moneyFlowEstimated,
            tdxBuyVolume: item.tdxBuyVolume,
            tdxSellVolume: item.tdxSellVolume,
            tdxCurrentVolume: item.tdxCurrentVolume,
            sourceTs: item.sourceTs,
            seq: item.seq,
            timestamp: Date.now(),
          }
        }),
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

  private updateIntradayMoneyFlowStats(groups: Array<{ code: string; items: TickTrade[] }>) {
    const tradingDate = toLocalTradingDate(new Date())

    groups.forEach((group) => {
      const code = String(group.code || '')
      if (!code || !Array.isArray(group.items) || !group.items.length) return
      const freshItems = this.filterFreshMoneyFlowTicks(code, tradingDate, group.items)
      if (!freshItems.length) return

      const current = this.intradayMoneyFlowStats.get(code)
      const next: IntradayMoneyFlowStats =
        current?.tradingDate === tradingDate
          ? { ...current }
          : { tradingDate, activeAmount: 0, mainNet: 0, superNet: 0 }

      const delta = summarizeMoneyFlowTicks(freshItems)
      next.activeAmount += delta.activeAmount
      next.mainNet += delta.mainNet
      next.superNet += delta.superNet
      this.intradayMoneyFlowStats.set(code, next)
    })
  }

  private filterFreshMoneyFlowTicks(code: string, tradingDate: string, items: TickTrade[]): TickTrade[] {
    let seen = this.intradayMoneyFlowTickKeys.get(code)
    let queue = this.intradayMoneyFlowTickQueues.get(code)

    if (!seen) {
      seen = new Set<string>()
      this.intradayMoneyFlowTickKeys.set(code, seen)
    }
    if (!queue) {
      queue = []
      this.intradayMoneyFlowTickQueues.set(code, queue)
    }

    const fresh: TickTrade[] = []
    items.forEach((item) => {
      const key = [
        tradingDate,
        item.tradeTime || '',
        Number(item.price) || 0,
        Number(item.volume) || 0,
        item.side || 'neutral',
      ].join('|')
      if (seen.has(key)) return

      seen.add(key)
      queue.push(key)
      fresh.push(item)
    })

    while (queue.length > 800) {
      const expired = queue.shift()
      if (expired) seen.delete(expired)
    }

    return fresh
  }

  private pickNonZeroNumber(...values: unknown[]): number {
    for (const value of values) {
      const number = Number(value)
      if (Number.isFinite(number) && number !== 0) return number
    }

    for (const value of values) {
      const number = Number(value)
      if (Number.isFinite(number)) return number
    }

    return 0
  }

  private pickPositiveNumber(...values: unknown[]): number {
    for (const value of values) {
      const number = Number(value)
      if (Number.isFinite(number) && number > 0) return number
    }

    return 0
  }

  private buildRealtimeMergedQuoteData(code: string, quote: QuotePatch): MergedQuoteData {
    const existingQuote = dataLayer.getQuote(code) || {}
    const stock = dataLayer.getStock(code)
    const speedCandidate = quote.speed ?? existingQuote?.speed
    const speed = typeof speedCandidate === 'number' && Number.isFinite(speedCandidate) ? speedCandidate : undefined
    const estimatedMoneyFlow = estimateTdxMoneyFlow(code, quote)

    return {
      price: Number(quote.lastPrice) || 0,
      change: Number(quote.changePct) || 0,
      speed,
      volume: Number(quote.volume ?? stock?.volume ?? existingQuote?.volume) || 0,
      turnover: Number(quote.amount ?? stock?.turnover ?? existingQuote?.turnover) || 0,
      turnoverRate: this.pickPositiveNumber(quote.turnoverRate, stock?.turnoverRate, existingQuote?.turnoverRate),
      pe: Number(stock?.pe ?? existingQuote?.pe) || 0,
      totalMV: Number(stock?.totalMV ?? existingQuote?.totalMV) || 0,
      cirMV: Number(stock?.cirMV ?? existingQuote?.cirMV) || 0,
      pb: Number(stock?.pb ?? existingQuote?.pb) || 0,
      zlje: this.pickNonZeroNumber(estimatedMoneyFlow?.zlje, stock?.zlje, existingQuote?.zlje),
      zljzb: this.pickNonZeroNumber(estimatedMoneyFlow?.zljzb, stock?.zljzb, existingQuote?.zljzb),
      cddje: this.pickNonZeroNumber(estimatedMoneyFlow?.cddje, stock?.cddje, existingQuote?.cddje),
      cddjzb: this.pickNonZeroNumber(estimatedMoneyFlow?.cddjzb, stock?.cddjzb, existingQuote?.cddjzb),
      moneyFlowSource: estimatedMoneyFlow?.moneyFlowSource ?? stock?.moneyFlowSource ?? existingQuote?.moneyFlowSource,
      moneyFlowEstimated: estimatedMoneyFlow?.moneyFlowEstimated ?? stock?.moneyFlowEstimated ?? existingQuote?.moneyFlowEstimated,
      tdxBuyVolume: Number(quote.tdxBuyVolume ?? stock?.tdxBuyVolume ?? existingQuote?.tdxBuyVolume) || 0,
      tdxSellVolume: Number(quote.tdxSellVolume ?? stock?.tdxSellVolume ?? existingQuote?.tdxSellVolume) || 0,
      tdxCurrentVolume: Number(quote.tdxCurrentVolume ?? stock?.tdxCurrentVolume ?? existingQuote?.tdxCurrentVolume) || 0,
      name: quote.name || stock?.name || existingQuote?.name,
      sources: estimatedMoneyFlow ? ['tdx_l2', 'tdx_money_estimate'] : ['tdx_l2'],
      confidence: 99,
      timestamp: Date.now(),
    }
  }

  private hasFundFlowData(quote: Partial<MergedQuoteData> | null | undefined): boolean {
    if (!quote) return false
    return ['zlje', 'zljzb', 'cddje', 'cddjzb'].some((key) => {
      const value = Number((quote as Record<string, unknown>)[key])
      return Number.isFinite(value) && value !== 0
    })
  }

  private mergeHttpIntoRealtimeQuote(
    realtimeQuote: MergedQuoteData,
    httpQuote: MergedQuoteData,
  ): MergedQuoteData {
    const preferHttpFundFlow =
      realtimeQuote.moneyFlowEstimated === true &&
      httpQuote.moneyFlowEstimated !== true &&
      httpQuote.moneyFlowSource === 'eastmoney' &&
      this.hasFundFlowData(httpQuote)
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
    const pickFundFlow = (primary: unknown, fallback: unknown) => {
      const primaryNumber = Number(primary)
      const fallbackNumber = Number(fallback)

      if (Number.isFinite(primaryNumber) && primaryNumber !== 0) return primaryNumber
      if (Number.isFinite(fallbackNumber) && fallbackNumber !== 0) return fallbackNumber
      if (Number.isFinite(primaryNumber)) return primaryNumber
      if (Number.isFinite(fallbackNumber)) return fallbackNumber
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
      zlje: preferHttpFundFlow ? pickFundFlow(httpQuote.zlje, realtimeQuote.zlje) : pickFundFlow(realtimeQuote.zlje, httpQuote.zlje),
      zljzb: preferHttpFundFlow ? pickFundFlow(httpQuote.zljzb, realtimeQuote.zljzb) : pickFundFlow(realtimeQuote.zljzb, httpQuote.zljzb),
      cddje: preferHttpFundFlow ? pickFundFlow(httpQuote.cddje, realtimeQuote.cddje) : pickFundFlow(realtimeQuote.cddje, httpQuote.cddje),
      cddjzb: preferHttpFundFlow ? pickFundFlow(httpQuote.cddjzb, realtimeQuote.cddjzb) : pickFundFlow(realtimeQuote.cddjzb, httpQuote.cddjzb),
      moneyFlowSource: preferHttpFundFlow ? httpQuote.moneyFlowSource : realtimeQuote.moneyFlowSource || httpQuote.moneyFlowSource,
      moneyFlowEstimated: preferHttpFundFlow ? httpQuote.moneyFlowEstimated : realtimeQuote.moneyFlowEstimated ?? httpQuote.moneyFlowEstimated,
      tdxBuyVolume: pickFinite(realtimeQuote.tdxBuyVolume, httpQuote.tdxBuyVolume),
      tdxSellVolume: pickFinite(realtimeQuote.tdxSellVolume, httpQuote.tdxSellVolume),
      tdxCurrentVolume: pickFinite(realtimeQuote.tdxCurrentVolume, httpQuote.tdxCurrentVolume),
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
      await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
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
    await themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })
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
        const quoteTurnoverRate = Number(quote.turnoverRate)
        if (
          (!Number.isFinite(quoteTurnoverRate) || quoteTurnoverRate <= 0) &&
          !(Number(mergedRealtimeQuote.turnoverRate) > 0)
        ) {
          enrichmentCodes.add(code)
        }
        if (!this.hasFundFlowData(mergedRealtimeQuote)) {
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
    return quoteHttpFeed.fetchBasicData(codes)
  }

  /**
   * 获取完整数据（东财）
   */
  private async fetchFullData(codes: string[], force?: boolean): Promise<Map<string, any>> {
    return quoteHttpFeed.fetchFullData(codes, force)
  }

  /**
   * 从腾讯获取基础数据
   */
  private async fetchFromTencent(codes: string[]): Promise<Map<string, any>> {
    return quoteHttpFeed.fetchFromTencent(codes)
  }

  /**
   * 从新浪获取备用数据
   */
  private async fetchFromSina(codes: string[]): Promise<Map<string, any>> {
    return quoteHttpFeed.fetchFromSina(codes)
  }

  /**
   * 从东财获取完整数据
   */
  private async fetchFromEastMoney(codes: string[], force?: boolean): Promise<Map<string, any>> {
    return quoteHttpFeed.fetchFromEastMoney(codes, force)
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
    void force
    await loadLimitUpFeedData()
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

    // 4. 构建股票数据（传入行情数据）
    const stockMap = await this.buildStockMap(
      quotesMap,
      volumeHistoryMap,
      existingMap,
      intradayVolumeHistoryMap,
    )

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
   * 对外暴露热度重算入口，方便后续接外部研究工具或开发期手工微调。
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

  public async buildIntradayVolumeHistoryMap(
    codes: string[] = [],
    date: Date = new Date(),
  ): Promise<Map<string, number[]>> {
    const targetCodes = filterValidStockCodes([...new Set(codes)])
    const targetClockMinute = getAshareVolumeClockMinute(date)
    if (targetCodes.length === 0 || targetClockMinute === undefined) return new Map()

    const anchorTradingDate = toLocalTradingDate(date)
    const allowedCaptureModes: Array<'real_time' | 'delayed'> = ['real_time', 'delayed']
    const snapshotGroups = await Promise.all(
      this.INTRADAY_VOLUME_SNAPSHOT_TYPES.map((type) =>
        snapshotFacade.listSnapshots({
          type,
          beforeTradingDate: anchorTradingDate,
          allowedCaptureModes,
          excludeRestored: true,
          sort: 'desc',
          limit: 120,
        }),
      ),
    )

    const recordsByDate = new Map<string, SnapshotRecord[]>()
    snapshotGroups.flat().forEach((record) => {
      const slotMinute = slotTimeToMinutes(record.slotTime)
      if (!record.tradingDate || slotMinute < 0) return
      const records = recordsByDate.get(record.tradingDate) || []
      records.push(record)
      recordsByDate.set(record.tradingDate, records)
    })

    const tradingDates = Array.from(recordsByDate.keys()).sort((left, right) => right.localeCompare(left)).slice(0, 3)
    if (!tradingDates.length) return new Map()

    const result = new Map<string, number[]>()

    for (const tradingDate of tradingDates) {
      const selected = this.selectIntradayVolumeSnapshots(
        recordsByDate.get(tradingDate) || [],
        targetClockMinute,
      )
      if (!selected) continue

      const rowsBySnapshotId = await this.loadSnapshotRowsById(
        [selected.previous.id, selected.next?.id].filter((id): id is string => Boolean(id)),
        targetCodes,
      )

      targetCodes.forEach((code) => {
        const volume = this.interpolateSnapshotVolume(
          code,
          selected,
          rowsBySnapshotId,
          targetClockMinute,
        )
        const volumeValue = Number(volume)
        if (!Number.isFinite(volumeValue) || volumeValue <= 0) return
        const volumes = result.get(code) || []
        volumes.push(volumeValue)
        result.set(code, volumes)
      })
    }

    return result
  }

  private selectIntradayVolumeSnapshots(
    records: SnapshotRecord[],
    targetClockMinute: number,
  ): { previous: SnapshotRecord; next?: SnapshotRecord } | null {
    for (const type of this.INTRADAY_VOLUME_SNAPSHOT_TYPES) {
      const typeRecords = records
        .filter((record) => record.type === type && slotTimeToMinutes(record.slotTime) >= 0)
        .sort((left, right) => slotTimeToMinutes(left.slotTime) - slotTimeToMinutes(right.slotTime))

      let previous: SnapshotRecord | null = null
      let next: SnapshotRecord | undefined

      for (const record of typeRecords) {
        const slotMinute = slotTimeToMinutes(record.slotTime)
        if (slotMinute <= targetClockMinute) previous = record
        if (slotMinute >= targetClockMinute) {
          next = record
          break
        }
      }

      if (previous) {
        return {
          previous,
          next: next && next.id !== previous.id ? next : undefined,
        }
      }
    }

    return null
  }

  private async loadSnapshotRowsById(
    snapshotIds: string[],
    codes: string[],
  ): Promise<Map<string, Map<string, SnapshotStockRow>>> {
    const rowsBySnapshotId = new Map<string, Map<string, SnapshotStockRow>>()
    const uniqueSnapshotIds = [...new Set(snapshotIds)]

    await Promise.all(
      uniqueSnapshotIds.map(async (snapshotId) => {
        const rows = await snapshotFacade.listSnapshotStockRows({ snapshotId, codes })
        const rowsByCode = new Map<string, SnapshotStockRow>()
        rows.forEach((row) => {
          if (row.code) rowsByCode.set(row.code, row)
        })
        rowsBySnapshotId.set(snapshotId, rowsByCode)
      }),
    )

    return rowsBySnapshotId
  }

  private interpolateSnapshotVolume(
    code: string,
    selected: { previous: SnapshotRecord; next?: SnapshotRecord },
    rowsBySnapshotId: Map<string, Map<string, SnapshotStockRow>>,
    targetClockMinute: number,
  ): number | undefined {
    const previousRow = rowsBySnapshotId.get(selected.previous.id)?.get(code)
    const previousVolume = Number(previousRow?.volume)
    if (!Number.isFinite(previousVolume) || previousVolume <= 0) return undefined

    if (!selected.next) return previousVolume

    const previousMinute = slotTimeToMinutes(selected.previous.slotTime)
    const nextMinute = slotTimeToMinutes(selected.next.slotTime)
    if (previousMinute < 0 || nextMinute <= previousMinute) return previousVolume

    const nextRow = rowsBySnapshotId.get(selected.next.id)?.get(code)
    const nextVolume = Number(nextRow?.volume)
    if (!Number.isFinite(nextVolume) || nextVolume < previousVolume) return previousVolume

    const progress = clamp(
      (targetClockMinute - previousMinute) / (nextMinute - previousMinute),
      0,
      1,
    )
    return previousVolume + (nextVolume - previousVolume) * progress
  }

  /**
   * 1. 构建历史成交量索引
   * 正式主链只按 code + daily + tradingDate 读取日级快照投影行，
   * 返回最近 4 个交易日成交量，供后续剔除“当前成交量与最新日级快照重复”的场景。
   */
  public async buildVolumeHistoryMap(codes: string[] = []): Promise<Map<string, number[]>> {
    const targetCodes = filterValidStockCodes([...new Set(codes)])
    if (targetCodes.length === 0) return new Map()
    return snapshotFacade.getStockVolumeHistory(targetCodes, {
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
    intradayVolumeHistoryMap: Map<string, number[]> = new Map(),
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
        const rankField = getRankField(platform)
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

        // 量比不依赖行情请求是否命中；优先按同时间盘中快照重算，缺失时降级到日级成交量进度。
        if (!volumeRatioCalculatedCodes.has(code)) {
          this.calculateVolumeRatio(stock, code, volumeHistoryMap, intradayVolumeHistoryMap)
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
          this.calculateVolumeRatio(stock, code, volumeHistoryMap, intradayVolumeHistoryMap)
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

    const pickFundFlowValue = (nextValue: unknown, currentValue: unknown) => {
      const nextNumber = Number(nextValue)
      const currentNumber = Number(currentValue)

      if (Number.isFinite(nextNumber) && nextNumber !== 0) return nextNumber
      if (Number.isFinite(currentNumber)) return currentNumber
      if (Number.isFinite(nextNumber)) return nextNumber
      return 0
    }
    const pickPositiveValue = (nextValue: unknown, currentValue: unknown) => {
      const nextNumber = Number(nextValue)
      const currentNumber = Number(currentValue)

      if (Number.isFinite(nextNumber) && nextNumber > 0) return nextNumber
      if (Number.isFinite(currentNumber) && currentNumber > 0) return currentNumber
      if (Number.isFinite(nextNumber)) return nextNumber
      return 0
    }

    Object.assign(stock, {
      price: pickPositiveValue(quote.price, stock.price),
      change: quote.change ?? stock.change,
      volume: pickPositiveValue(quote.volume, stock.volume),
      turnover: pickPositiveValue(quote.turnover, stock.turnover),
      turnoverRate: pickPositiveValue(quote.turnoverRate, stock.turnoverRate),
      pe: pickPositiveValue(quote.pe, stock.pe),
      pb: pickPositiveValue(quote.pb, stock.pb),
      totalMV: pickPositiveValue(quote.totalMV, stock.totalMV),
      cirMV: pickPositiveValue(quote.cirMV, stock.cirMV),
      zlje: pickFundFlowValue(quote.zlje, stock.zlje),
      zljzb: pickFundFlowValue(quote.zljzb, stock.zljzb),
      cddje: pickFundFlowValue(quote.cddje, stock.cddje),
      cddjzb: pickFundFlowValue(quote.cddjzb, stock.cddjzb),
      moneyFlowSource: quote.moneyFlowSource ?? stock.moneyFlowSource,
      moneyFlowEstimated: quote.moneyFlowEstimated ?? stock.moneyFlowEstimated,
      tdxBuyVolume: quote.tdxBuyVolume ?? stock.tdxBuyVolume,
      tdxSellVolume: quote.tdxSellVolume ?? stock.tdxSellVolume,
      tdxCurrentVolume: quote.tdxCurrentVolume ?? stock.tdxCurrentVolume,
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
        debugLog(`[DataLoader] 从 StockCodeManager 获取名称: ${code} -> ${stockName}`)
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
    intradayVolumeHistoryMap: Map<string, number[]> = new Map(),
  ): void {
    stock.volumeRatio = calculateVolumeRatioValue(
      stock,
      code,
      volumeHistoryMap,
      intradayVolumeHistoryMap,
    )
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
    return rankMergedStocks(stockMap, this.state.value.data)
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

  private isValidName(name: string): boolean {
    return !!(name && name !== '-' && name !== 'null' && name !== 'undefined' && name.trim() !== '')
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
