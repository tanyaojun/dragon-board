import { filterValidStockCodes } from '@/utils/common'
import { dataLayer as defaultDataLayer } from '../DataLayer'
import { webSocketService as defaultWebSocketService } from '../websocket'
import { QUOTE_BATCH_DELAY_MS } from './constants'
import { estimateTdxMoneyFlow } from './MoneyFlowEstimator'
import {
  pickHigherPriorityMoneyFlow,
  shouldApplyMoneyFlowUpdate,
} from '../moneyFlowSourcePriority'
import { quoteHttpFeed } from './QuoteHttpFeed'
import type { MergedQuoteData } from './types'
import type { QuotePatch } from '@/types'

type QuoteFeed = {
  fetchBasicData: (codes: string[]) => Promise<Map<string, any>>
  fetchFullData: (codes: string[], force?: boolean) => Promise<Map<string, any>>
}

type QuoteDataLayer = {
  getQuote: (code: string) => any
  getStock: (code: string) => any
  updateQuote: (code: string, quote: MergedQuoteData) => void
}

type QuoteWebSocketService = {
  getQuotesBatch: (codes: string[]) => Map<string, QuotePatch>
}

type PendingBatchRequest = {
  codes: string[]
  force: boolean
  resolve: (value: Map<string, any>) => void
  reject: (reason?: any) => void
}

export class QuoteService {
  private readonly feed: QuoteFeed
  private readonly dataLayer: QuoteDataLayer
  private readonly webSocketService: QuoteWebSocketService
  private readonly isRealtimePrimaryHealthy: () => boolean
  private readonly now: () => number
  private readonly batchDelay: number
  private pendingBatchRequests: PendingBatchRequest[] = []
  private pendingCodes = new Set<string>()
  private batchTimer: ReturnType<typeof setTimeout> | null = null

  constructor(options: {
    feed?: QuoteFeed
    dataLayer?: QuoteDataLayer
    webSocketService?: QuoteWebSocketService
    isRealtimePrimaryHealthy?: () => boolean
    now?: () => number
    batchDelay?: number
  } = {}) {
    this.feed = options.feed || quoteHttpFeed
    this.dataLayer = options.dataLayer || defaultDataLayer
    this.webSocketService = options.webSocketService || defaultWebSocketService
    this.isRealtimePrimaryHealthy = options.isRealtimePrimaryHealthy || (() => false)
    this.now = options.now || (() => Date.now())
    this.batchDelay = options.batchDelay ?? QUOTE_BATCH_DELAY_MS
  }

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
      const realtimeQuotes = this.webSocketService.getQuotesBatch(validCodes)
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

    const httpResult = await this.fetchHttpQuotes(httpCodes, options.force)
    httpResult.forEach((quote, code) => {
      const realtimeQuote = result.get(code)
      result.set(code, realtimeQuote ? this.mergeHttpIntoRealtimeQuote(realtimeQuote, quote) : quote)
    })

    return result
  }

  async getQuote(code: string, force = false): Promise<MergedQuoteData | null> {
    if (!force) {
      const cached = this.dataLayer.getQuote(code)
      if (cached && this.now() - cached.timestamp < 5000) {
        return cached
      }
    }

    const quotes = await this.fetchMergedQuotes([code], { force })
    const quote = quotes.get(code)
    if (!quote) return null

    this.dataLayer.updateQuote(code, quote)
    return quote
  }

  async getQuotes(codes: string[], force = false): Promise<Map<string, any>> {
    const quotes = await this.fetchMergedQuotes(codes, { force })
    const result = new Map()

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
      this.dataLayer.updateQuote(code, quote)
    })

    return result
  }

  async getQuoteBatch(codes: string[], force = false): Promise<Map<string, any>> {
    const uniqueCodes = [...new Set(codes)]
    if (uniqueCodes.length === 0) return new Map()

    return new Promise((resolve, reject) => {
      this.pendingBatchRequests.push({ codes: uniqueCodes, force, resolve, reject })
      for (const code of uniqueCodes) this.pendingCodes.add(code)

      if (!this.batchTimer) {
        this.batchTimer = setTimeout(() => {
          void this.flushQuoteBatch()
        }, this.batchDelay)
      }
    })
  }

  clearPending(): void {
    if (this.batchTimer) {
      clearTimeout(this.batchTimer)
      this.batchTimer = null
    }
    this.pendingCodes.clear()
    const error = new Error('Quote batch request cleared')
    for (const request of this.pendingBatchRequests) request.reject(error)
    this.pendingBatchRequests = []
  }

  private async flushQuoteBatch(): Promise<void> {
    const batchCodes = Array.from(this.pendingCodes)
    const requests = this.pendingBatchRequests.splice(0)
    this.pendingCodes.clear()
    this.batchTimer = null

    if (batchCodes.length === 0) {
      for (const request of requests) request.resolve(new Map())
      return
    }

    try {
      const quotes = await this.fetchMergedQuotes(batchCodes, {
        force: requests.some((request) => request.force),
      })
      quotes.forEach((quote, code) => {
        this.dataLayer.updateQuote(code, quote)
      })

      for (const request of requests) {
        const result = new Map<string, any>()
        for (const code of request.codes) {
          const quote = quotes.get(code)
          if (quote) result.set(code, quote)
        }
        request.resolve(result)
      }
    } catch (error) {
      for (const request of requests) request.reject(error)
    }
  }

  private async fetchHttpQuotes(codes: string[], force?: boolean): Promise<Map<string, MergedQuoteData>> {
    const httpResult = new Map<string, MergedQuoteData>()
    const [basicResult, fullResult] = await Promise.allSettled([
      this.feed.fetchBasicData(codes),
      this.feed.fetchFullData(codes, force),
    ])

    if (basicResult.status === 'fulfilled' && basicResult.value.size > 0) {
      basicResult.value.forEach((quote, code) => {
        httpResult.set(code, {
          ...quote,
          timestamp: this.now(),
          sources: [quote.source],
          confidence: quote.source === 'eastmoney' ? 95 : 70,
        } as MergedQuoteData)
      })
    }

    if (fullResult.status === 'fulfilled' && fullResult.value.size > 0) {
      fullResult.value.forEach((fullQuote, code) => {
        const existing = httpResult.get(code)
        if (existing) {
          httpResult.set(code, {
            ...existing,
            ...fullQuote,
            sources: [...existing.sources, fullQuote.source],
            confidence: 95,
            timestamp: this.now(),
          })
        } else {
          httpResult.set(code, {
            ...fullQuote,
            timestamp: this.now(),
            sources: [fullQuote.source],
            confidence: 95,
          })
        }
      })
    }

    return httpResult
  }

  private buildRealtimeMergedQuoteData(code: string, quote: QuotePatch): MergedQuoteData {
    const existingQuote = this.dataLayer.getQuote(code) || {}
    const stock = this.dataLayer.getStock(code)
    const speedCandidate = quote.speed ?? existingQuote?.speed
    const speed = typeof speedCandidate === 'number' && Number.isFinite(speedCandidate) ? speedCandidate : undefined
    const hasRealtimeL2MoneyFlow = isReliableL2MoneyFlow(quote)
    const estimatedMoneyFlow = hasRealtimeL2MoneyFlow ? null : estimateTdxMoneyFlow(code, quote)
    const fallbackMoneyFlow = pickHigherPriorityMoneyFlow(stock, existingQuote)
    const shouldUseEstimatedMoneyFlow = shouldApplyMoneyFlowUpdate(fallbackMoneyFlow, estimatedMoneyFlow)
    const shouldUseRealtimeL2MoneyFlow = shouldApplyMoneyFlowUpdate(fallbackMoneyFlow, quote)
    const moneyFlowBase = hasRealtimeL2MoneyFlow && shouldUseRealtimeL2MoneyFlow ? quote : fallbackMoneyFlow

    return {
      price: Number(quote.lastPrice) || 0,
      change: Number(quote.changePct) || 0,
      speed,
      volume: Number(quote.volume ?? stock?.volume ?? existingQuote?.volume) || 0,
      turnover: Number(quote.amount ?? stock?.turnover ?? existingQuote?.turnover) || 0,
      turnoverRate: pickPositiveNumber(quote.turnoverRate, stock?.turnoverRate, existingQuote?.turnoverRate),
      pe: Number(stock?.pe ?? existingQuote?.pe) || 0,
      totalMV: Number(stock?.totalMV ?? existingQuote?.totalMV) || 0,
      cirMV: Number(stock?.cirMV ?? existingQuote?.cirMV) || 0,
      pb: Number(stock?.pb ?? existingQuote?.pb) || 0,
      zlje: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.zlje, stock?.zlje)
        : shouldUseEstimatedMoneyFlow
          ? pickNonZeroNumber(estimatedMoneyFlow?.zlje, stock?.zlje, existingQuote?.zlje)
          : pickNonZeroNumber(moneyFlowBase?.zlje, stock?.zlje, existingQuote?.zlje),
      zljzb: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.zljzb, stock?.zljzb)
        : shouldUseEstimatedMoneyFlow
          ? pickNonZeroNumber(estimatedMoneyFlow?.zljzb, stock?.zljzb, existingQuote?.zljzb)
          : pickNonZeroNumber(moneyFlowBase?.zljzb, stock?.zljzb, existingQuote?.zljzb),
      cddje: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.cddje, stock?.cddje)
        : shouldUseEstimatedMoneyFlow
          ? pickNonZeroNumber(estimatedMoneyFlow?.cddje, stock?.cddje, existingQuote?.cddje)
          : pickNonZeroNumber(moneyFlowBase?.cddje, stock?.cddje, existingQuote?.cddje),
      cddjzb: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.cddjzb, stock?.cddjzb)
        : shouldUseEstimatedMoneyFlow
          ? pickNonZeroNumber(estimatedMoneyFlow?.cddjzb, stock?.cddjzb, existingQuote?.cddjzb)
          : pickNonZeroNumber(moneyFlowBase?.cddjzb, stock?.cddjzb, existingQuote?.cddjzb),
      moneyFlowSource: shouldUseEstimatedMoneyFlow
        ? estimatedMoneyFlow?.moneyFlowSource
        : moneyFlowBase?.moneyFlowSource,
      moneyFlowEstimated: shouldUseEstimatedMoneyFlow
        ? estimatedMoneyFlow?.moneyFlowEstimated
        : moneyFlowBase?.moneyFlowEstimated,
      capitalFlowSource: shouldUseEstimatedMoneyFlow ? 'estimated_l1' : moneyFlowBase?.capitalFlowSource,
      capitalFlowConfidence: shouldUseEstimatedMoneyFlow ? 'low' : moneyFlowBase?.capitalFlowConfidence,
      tdxBuyVolume: Number(quote.tdxBuyVolume ?? stock?.tdxBuyVolume ?? existingQuote?.tdxBuyVolume) || 0,
      tdxSellVolume: Number(quote.tdxSellVolume ?? stock?.tdxSellVolume ?? existingQuote?.tdxSellVolume) || 0,
      tdxCurrentVolume: Number(quote.tdxCurrentVolume ?? stock?.tdxCurrentVolume ?? existingQuote?.tdxCurrentVolume) || 0,
      name: quote.name || stock?.name || existingQuote?.name,
      sources: hasRealtimeL2MoneyFlow
        ? [String(quote.moneyFlowSource)]
        : estimatedMoneyFlow
          ? ['tdx_l2', 'tdx_money_estimate']
          : ['tdx_l2'],
      confidence: 99,
      timestamp: this.now(),
    }
  }

  private hasFundFlowData(quote: Partial<MergedQuoteData> | null | undefined): boolean {
    if (!quote) return false
    return ['zlje', 'zljzb', 'cddje', 'cddjzb'].some((key) => {
      const value = Number((quote as unknown as Record<string, unknown>)[key])
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
      capitalFlowSource: preferHttpFundFlow
        ? httpQuote.capitalFlowSource
        : realtimeQuote.capitalFlowSource || httpQuote.capitalFlowSource,
      capitalFlowConfidence: preferHttpFundFlow
        ? httpQuote.capitalFlowConfidence
        : realtimeQuote.capitalFlowConfidence || httpQuote.capitalFlowConfidence,
      tdxBuyVolume: pickFinite(realtimeQuote.tdxBuyVolume, httpQuote.tdxBuyVolume),
      tdxSellVolume: pickFinite(realtimeQuote.tdxSellVolume, httpQuote.tdxSellVolume),
      tdxCurrentVolume: pickFinite(realtimeQuote.tdxCurrentVolume, httpQuote.tdxCurrentVolume),
      name: realtimeQuote.name || httpQuote.name,
      sources: Array.from(new Set([...(realtimeQuote.sources || []), ...(httpQuote.sources || [])])),
      confidence: Math.max(Number(realtimeQuote.confidence) || 0, Number(httpQuote.confidence) || 0),
      timestamp: this.now(),
    }
  }
}

function pickNonZeroNumber(...values: unknown[]): number {
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

function pickPositiveNumber(...values: unknown[]): number {
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number) && number > 0) return number
  }

  return 0
}

function pickFinite(primary: unknown, fallback: unknown, preferPositive = false): number {
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

function isReliableL2MoneyFlow(quote: QuotePatch): boolean {
  return (
    quote.moneyFlowEstimated === false &&
    quote.moneyFlowSource === 'qmt_l2' &&
    (quote.capitalFlowSource === 'broker_l2' || quote.capitalFlowSource === 'official_l2') &&
    ['zlje', 'zljzb', 'cddje', 'cddjzb'].some((key) => {
      const value = Number((quote as unknown as Record<string, unknown>)[key])
      return Number.isFinite(value) && value !== 0
    })
  )
}

function pickFundFlow(primary: unknown, fallback: unknown): number {
  const primaryNumber = Number(primary)
  const fallbackNumber = Number(fallback)

  if (Number.isFinite(primaryNumber) && primaryNumber !== 0) return primaryNumber
  if (Number.isFinite(fallbackNumber) && fallbackNumber !== 0) return fallbackNumber
  if (Number.isFinite(primaryNumber)) return primaryNumber
  if (Number.isFinite(fallbackNumber)) return fallbackNumber
  return 0
}

export const quoteService = new QuoteService({
  isRealtimePrimaryHealthy: () => {
    const status = defaultWebSocketService.getStatus()
    return status.subscribedCount > 0 && defaultWebSocketService.isTdxRealtimeHealthy()
  },
})
