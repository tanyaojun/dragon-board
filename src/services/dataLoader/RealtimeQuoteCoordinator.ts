import { AppEvents, type Depth10Book, type QuotePatch, type TickTrade } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from '../DataLayer'
import { isDashboardFundSource } from '../moneyFlowSourcePriority'
import { realtimeSubscriptionRegistry } from '../realtime/RealtimeSubscriptionRegistry'
import { webSocketService } from '../websocket'
import { REALTIME_FLUSH_DELAY_MS } from './constants'

const REALTIME_OWNER = 'dataLoader.hotlist'

// P0/P1 资金校准分级（2026-08-08 用户确认简化为纯 compRank 口径）：
// P0 = compRank ≤ 50（优先校准，30 秒轮转），P1 = compRank > 50（180 秒轮转）。
// 不再叠加信号/金叉/confidence/turnover 分层。
const P0_MAX_COMP_RANK = 50

function deriveMainMoneyRatio(mainNet: unknown, turnover: unknown): number | undefined {
  const net = Number(mainNet)
  const amount = Number(turnover)
  if (!Number.isFinite(net) || !Number.isFinite(amount) || amount <= 0) return undefined
  return Number(((net / amount) * 100).toFixed(2))
}

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
  private realtimeUnsubscribers: Array<() => void> = []

  constructor(options: RealtimeQuoteCoordinatorOptions) {
    this.getHotCodes = options.getHotCodes
    this.onQuoteFlushed = options.onQuoteFlushed
    this.flushDelay = options.flushDelay ?? REALTIME_FLUSH_DELAY_MS
    this.setupRealtimeFeed()
  }

  syncRealtimeSubscription() {
    const { p0Codes, allCodes } = this.buildRealtimeSubscriptionCodes()
    realtimeSubscriptionRegistry.setOwnerCodes(REALTIME_OWNER, allCodes, p0Codes)
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
      this.pendingRealtimeQuotes.set(item.code, {
        ...this.pendingRealtimeQuotes.get(item.code),
        ...item,
      })
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

    if (quoteItems.length) {
      dataLayer.applyRealtimeQuoteBatch(
        quoteItems.map((item) => {
          const hasDashboardMoneyFlow = isDashboardFundSource(item)
          const mainMoneyRatio = hasDashboardMoneyFlow
            ? item.zljzb ?? deriveMainMoneyRatio(item.zlje, dataLayer.getStock(item.code)?.turnover)
            : undefined
          return {
            code: item.code,
            name: item.name,
            price: item.lastPrice,
            change: item.changePct,
            speed: item.speed,
            volume: item.volume,
            turnover: item.amount,
            turnoverRate: item.turnoverRate,
            zlje: hasDashboardMoneyFlow ? item.zlje : undefined,
            zljzb: mainMoneyRatio,
            cddje: hasDashboardMoneyFlow ? item.cddje : undefined,
            cddjzb: hasDashboardMoneyFlow ? item.cddjzb : undefined,
            moneyFlowSource: hasDashboardMoneyFlow ? item.moneyFlowSource : undefined,
            moneyFlowEstimated: hasDashboardMoneyFlow ? item.moneyFlowEstimated : undefined,
            capitalFlowSource: hasDashboardMoneyFlow ? item.capitalFlowSource : undefined,
            capitalFlowConfidence: hasDashboardMoneyFlow ? item.capitalFlowConfidence : undefined,
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

  private buildRealtimeSubscriptionCodes(): { p0Codes: string[]; allCodes: string[] } {
    const hotCodes = Array.from(this.getHotCodes())
    if (!hotCodes.length) return { p0Codes: [], allCodes: [] }

    const hotCodeSet = new Set(hotCodes)
    const stocks = dataLayer.getStocks().filter((stock) => hotCodeSet.has(stock.code))

    const getCompRank = (stock: any) => {
      const compRank = Number(stock?.compRank)
      if (Number.isFinite(compRank) && compRank > 0) return compRank
      const fallbackRank = Number(stock?.rank)
      if (Number.isFinite(fallbackRank) && fallbackRank > 0) return fallbackRank
      return 9999
    }

    // P0/P1 只按 compRank 排序（用户确认简化为纯 compRank 口径）
    const sorted = stocks
      .slice()
      .sort((left: any, right: any) => {
        const leftRank = getCompRank(left)
        const rightRank = getCompRank(right)
        if (leftRank !== rightRank) return leftRank - rightRank
        return String(left?.code || '').localeCompare(String(right?.code || ''))
      })
      .map((stock) => stock.code)

    const missingCodes = hotCodes.filter((code) => !sorted.includes(code))
    const allCodes = [...sorted, ...missingCodes]
    const p0Codes = allCodes.filter((code) => {
      const stock = stocks.find((item) => item.code === code)
      return stock !== undefined && getCompRank(stock) <= P0_MAX_COMP_RANK
    })
    return { p0Codes, allCodes }
  }

}
