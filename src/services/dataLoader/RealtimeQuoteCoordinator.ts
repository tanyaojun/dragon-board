import { AppEvents, type Depth10Book, type QuotePatch, type TickTrade } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '../DataLayer'
import { realtimeSubscriptionRegistry } from '../realtime/RealtimeSubscriptionRegistry'
import { webSocketService } from '../websocket'
import { toLocalTradingDate } from '../snapshot/identity'
import { summarizeMoneyFlowTicks } from './MoneyFlowEstimator'
import { REALTIME_FLUSH_DELAY_MS } from './constants'
import type { IntradayMoneyFlowStats } from './types'

const REALTIME_OWNER = 'dataLoader.hotlist'

export interface RealtimeQuoteCoordinatorOptions {
  getHotCodes: () => Set<string>
  onQuoteFlushed?: (codes: string[]) => void | Promise<void>
  flushDelay?: number
}

export class RealtimeQuoteCoordinator {
  private readonly getHotCodes: () => Set<string>
  private readonly onQuoteFlushed?: (codes: string[]) => void | Promise<void>
  private readonly flushDelay: number
  private realtimeFlushTimer: ReturnType<typeof setTimeout> | null = null
  private pendingRealtimeQuotes = new Map<string, QuotePatch>()
  private pendingDepthBooks = new Map<string, Depth10Book>()
  private pendingTicks = new Map<string, TickTrade[]>()
  private intradayMoneyFlowStats = new Map<string, IntradayMoneyFlowStats>()
  private intradayMoneyFlowTickKeys = new Map<string, Set<string>>()
  private intradayMoneyFlowTickQueues = new Map<string, string[]>()
  private realtimeUnsubscribers: Array<() => void> = []

  constructor(options: RealtimeQuoteCoordinatorOptions) {
    this.getHotCodes = options.getHotCodes
    this.onQuoteFlushed = options.onQuoteFlushed
    this.flushDelay = options.flushDelay ?? REALTIME_FLUSH_DELAY_MS
    this.setupRealtimeFeed()
  }

  syncRealtimeSubscription() {
    realtimeSubscriptionRegistry.setOwnerCodes(REALTIME_OWNER, this.buildRealtimeSubscriptionCodes())
  }

  isRealtimePrimaryHealthy(): boolean {
    const status = webSocketService.getStatus()
    return status.subscribedCount > 0 && webSocketService.isTdxRealtimeHealthy()
  }

  destroy() {
    if (this.realtimeFlushTimer) {
      clearTimeout(this.realtimeFlushTimer)
      this.realtimeFlushTimer = null
    }
    this.realtimeUnsubscribers.forEach((unsubscribe) => unsubscribe())
    this.realtimeUnsubscribers = []
    this.pendingRealtimeQuotes.clear()
    this.pendingDepthBooks.clear()
    this.pendingTicks.clear()
    this.intradayMoneyFlowStats.clear()
    this.intradayMoneyFlowTickKeys.clear()
    this.intradayMoneyFlowTickQueues.clear()
    realtimeSubscriptionRegistry.clearOwner(REALTIME_OWNER)
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
    }, this.flushDelay)
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
          const hasRealtimeL2MoneyFlow =
            item.moneyFlowEstimated === false &&
            (item.moneyFlowSource === 'ths_l2' ||
             item.moneyFlowSource === 'tdx_transaction' ||
             item.moneyFlowSource === 'qmt_l2')
          return {
            code: item.code,
            name: item.name,
            price: item.lastPrice,
            change: item.changePct,
            speed: item.speed,
            volume: item.volume,
            turnover: item.amount,
            turnoverRate: item.turnoverRate,
            zlje: hasRealtimeL2MoneyFlow ? item.zlje : undefined,
            zljzb: hasRealtimeL2MoneyFlow ? item.zljzb : undefined,
            cddje: hasRealtimeL2MoneyFlow ? item.cddje : undefined,
            cddjzb: hasRealtimeL2MoneyFlow ? item.cddjzb : undefined,
            moneyFlowSource: hasRealtimeL2MoneyFlow ? item.moneyFlowSource : undefined,
            moneyFlowEstimated: hasRealtimeL2MoneyFlow ? false : undefined,
            capitalFlowSource: hasRealtimeL2MoneyFlow ? item.capitalFlowSource : undefined,
            capitalFlowConfidence: hasRealtimeL2MoneyFlow ? item.capitalFlowConfidence : undefined,
            tdxBuyVolume: item.tdxBuyVolume,
            tdxSellVolume: item.tdxSellVolume,
            tdxCurrentVolume: item.tdxCurrentVolume,
            capturedAt: item.capturedAt,
            bridgeTs: item.bridgeTs,
            lastPriceSource: item.lastPriceSource,
            sampleKind: item.sampleKind,
            openingForcedSample: item.openingForcedSample,
            requestedCount: item.requestedCount,
            receivedCount: item.receivedCount,
            elapsedMs: item.elapsedMs,
            slowBatches: item.slowBatches,
            truncatedBatches: item.truncatedBatches,
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

    if (quoteItems.length && this.onQuoteFlushed) {
      const changedCodes = quoteItems.map((item) => item.code).filter(Boolean)
      void Promise.resolve(this.onQuoteFlushed([...new Set(changedCodes)])).catch((error) => {
        console.warn('[RealtimeQuoteCoordinator] 量比刷新回调失败:', error)
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

  private buildRealtimeSubscriptionCodes(): string[] {
    const hotCodes = Array.from(this.getHotCodes())
    if (!hotCodes.length) return []

    const hotCodeSet = new Set(hotCodes)
    const stocks = dataLayer.getStocks().filter((stock) => hotCodeSet.has(stock.code))

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
}
