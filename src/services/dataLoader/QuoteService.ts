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
import type { MergedQuoteData, QuoteBatchProgress } from './types'
import type { QuotePatch } from '@/types'

type QuoteFeed = {
  fetchBasicData: (
    codes: string[],
    options?: { onProgress?: (progress: QuoteBatchProgress) => void },
  ) => Promise<Map<string, any>>
  fetchFullData: (
    codes: string[],
    force?: boolean,
    options?: { onProgress?: (progress: QuoteBatchProgress) => void },
  ) => Promise<Map<string, any>>
  fetchFromSinaMoneyFlow?: (codes: string[], force?: boolean) => Promise<Map<string, any>>
}

type QuoteDataLayer = {
  getQuote: (code: string) => any
  getStock: (code: string) => any
  updateQuote: (code: string, quote: MergedQuoteData) => void
  applyRealtimeQuoteBatch?: (changes: any[]) => void
}

type QuoteWebSocketService = {
  getQuotesBatch: (codes: string[]) => Map<string, QuotePatch>
}

const BACKGROUND_FULL_QUOTE_BATCH_SIZE = 20
const BACKGROUND_FULL_QUOTE_BATCH_DELAY_MS = 120
const BACKGROUND_FULL_QUOTE_CONCURRENCY = 3

type PendingBatchRequest = {
  codes: string[]
  force: boolean
  onProgress?: (progress: QuoteBatchProgress) => void
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
    options: { force?: boolean; onProgress?: (progress: QuoteBatchProgress) => void } = {},
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
        if (!this.hasQuoteSupplementData(mergedRealtimeQuote)) {
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

    const httpResult = await this.fetchHttpQuotes(httpCodes, options.force, options.onProgress)
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

  async getQuotes(
    codes: string[],
    force = false,
    options: { onProgress?: (progress: QuoteBatchProgress) => void } = {},
  ): Promise<Map<string, any>> {
    const quotes = await this.fetchMergedQuotes(codes, { force, onProgress: options.onProgress })
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

  async getQuoteBatch(
    codes: string[],
    force = false,
    options: { onProgress?: (progress: QuoteBatchProgress) => void } = {},
  ): Promise<Map<string, any>> {
    const uniqueCodes = [...new Set(codes)]
    if (uniqueCodes.length === 0) return new Map()

    return new Promise((resolve, reject) => {
      this.pendingBatchRequests.push({ codes: uniqueCodes, force, onProgress: options.onProgress, resolve, reject })
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
      const callbacks = new Set(requests.map((request) => request.onProgress).filter(Boolean))
      const quotes = await this.fetchMergedQuotes(batchCodes, {
        force: requests.some((request) => request.force),
        onProgress:
          callbacks.size > 0
            ? (progress) => {
                callbacks.forEach((callback) => callback?.(progress))
              }
            : undefined,
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

  private async fetchHttpQuotes(
    codes: string[],
    force?: boolean,
    onProgress?: (progress: QuoteBatchProgress) => void,
  ): Promise<Map<string, MergedQuoteData>> {
    const httpResult = new Map<string, MergedQuoteData>()
    if (!force) {
      const basicResult = onProgress
        ? await this.feed.fetchBasicData(codes, { onProgress })
        : await this.feed.fetchBasicData(codes)
      if (basicResult.size > 0) {
        basicResult.forEach((quote, code) => {
          httpResult.set(code, {
            ...quote,
            timestamp: this.now(),
            sources: [quote.source],
            confidence: quote.source === 'eastmoney' ? 95 : 70,
          } as MergedQuoteData)
        })
      }

      void this.enrichFullQuotesInBackground(codes, httpResult)
      return httpResult
    }

    const progressReporter = onProgress ? createHttpQuoteProgressReporter(codes.length, onProgress) : null
    const basicOptions = progressReporter
      ? { onProgress: (progress: QuoteBatchProgress) => progressReporter.report('basic', progress) }
      : undefined
    const fullOptions = progressReporter
      ? { onProgress: (progress: QuoteBatchProgress) => progressReporter.report('full', progress) }
      : undefined
    const [basicResult, fullResult] = await Promise.allSettled([
      (async () => {
        try {
          return basicOptions
            ? await this.feed.fetchBasicData(codes, basicOptions)
            : await this.feed.fetchBasicData(codes)
        } finally {
          progressReporter?.settle('basic')
        }
      })(),
      (async () => {
        try {
          return fullOptions
            ? await this.feed.fetchFullData(codes, force, fullOptions)
            : await this.feed.fetchFullData(codes, force)
        } finally {
          progressReporter?.settle('full')
        }
      })(),
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
          httpResult.set(code, mergeHttpQuoteSources(existing, fullQuote, this.now()))
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

  private async enrichFullQuotesInBackground(
    codes: string[],
    baseQuotes: Map<string, MergedQuoteData>,
  ): Promise<void> {
    const batches: string[][] = []
    for (let i = 0; i < codes.length; i += BACKGROUND_FULL_QUOTE_BATCH_SIZE) {
      batches.push(codes.slice(i, i + BACKGROUND_FULL_QUOTE_BATCH_SIZE))
    }

    const concurrency = Math.min(BACKGROUND_FULL_QUOTE_CONCURRENCY, batches.length)
    await Promise.all(
      Array.from({ length: concurrency }, async (_, workerIndex) => {
        await this.runBackgroundFullQuoteWorker(batches, workerIndex, concurrency, baseQuotes)
      }),
    )
  }

  private async runBackgroundFullQuoteWorker(
    batches: string[][],
    workerIndex: number,
    concurrency: number,
    baseQuotes: Map<string, MergedQuoteData>,
  ): Promise<void> {
    for (let index = workerIndex; index < batches.length; index += concurrency) {
      const batch = batches[index]
      try {
        const fullRows = await this.fetchBackgroundFullQuoteRows(batch)
        this.publishFullQuoteRows(fullRows, baseQuotes)
      } catch (error) {
        console.warn('[DataLoader] 后台资金流懒加载批次失败，继续后续批次:', error)
      }

      if (index + concurrency < batches.length) {
        await delay(BACKGROUND_FULL_QUOTE_BATCH_DELAY_MS)
      }
    }
  }

  private async fetchBackgroundFullQuoteRows(
    codes: string[],
  ): Promise<Map<string, MergedQuoteData & { source?: string }>> {
    if (this.feed.fetchFromSinaMoneyFlow) {
      return await this.feed.fetchFromSinaMoneyFlow(codes, false)
    }
    return await this.feed.fetchFullData(codes, false)
  }

  private publishFullQuoteRows(
    fullRows: Map<string, MergedQuoteData & { source?: string }>,
    baseQuotes: Map<string, MergedQuoteData>,
  ): void {
    if (fullRows.size === 0) return

    const patches: Array<MergedQuoteData & { code: string }> = []
    fullRows.forEach((fullQuote, code) => {
      const existing = baseQuotes.get(code) || this.dataLayer.getQuote(code)
      const merged = existing
        ? mergeHttpQuoteSources(existing, fullQuote, this.now())
        : ({
            ...fullQuote,
            timestamp: this.now(),
            sources: [fullQuote.source],
            confidence: 95,
          } as MergedQuoteData)
      patches.push({ code, ...merged })
    })

    if (this.dataLayer.applyRealtimeQuoteBatch) {
      this.dataLayer.applyRealtimeQuoteBatch(patches)
      return
    }

    patches.forEach(({ code, ...quote }) => {
      this.dataLayer.updateQuote(code, quote)
    })
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
      volumeRatio: pickPositiveNumber(quote.volumeRatio, stock?.volumeRatio, existingQuote?.volumeRatio),
      pe: pickNonZeroNumber(stock?.pe, existingQuote?.pe),
      totalMV: pickPositiveNumber(stock?.totalMV, existingQuote?.totalMV),
      cirMV: pickPositiveNumber(stock?.cirMV, existingQuote?.cirMV),
      pb: pickPositiveNumber(stock?.pb, existingQuote?.pb),
      zlje: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.zlje, stock?.zlje)
        : shouldUseEstimatedMoneyFlow
          ? pickMoneyFlowNumber(estimatedMoneyFlow?.zlje, stock?.zlje, existingQuote?.zlje)
          : pickNonZeroNumber(moneyFlowBase?.zlje, stock?.zlje, existingQuote?.zlje),
      zljzb: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.zljzb, stock?.zljzb)
        : shouldUseEstimatedMoneyFlow
          ? pickMoneyFlowNumber(estimatedMoneyFlow?.zljzb, stock?.zljzb, existingQuote?.zljzb)
          : pickNonZeroNumber(moneyFlowBase?.zljzb, stock?.zljzb, existingQuote?.zljzb),
      cddje: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.cddje, stock?.cddje)
        : shouldUseEstimatedMoneyFlow
          ? pickMoneyFlowNumber(estimatedMoneyFlow?.cddje, stock?.cddje, existingQuote?.cddje)
          : pickNonZeroNumber(moneyFlowBase?.cddje, stock?.cddje, existingQuote?.cddje),
      cddjzb: hasRealtimeL2MoneyFlow
        ? pickFundFlow(quote.cddjzb, stock?.cddjzb)
        : shouldUseEstimatedMoneyFlow
          ? pickMoneyFlowNumber(estimatedMoneyFlow?.cddjzb, stock?.cddjzb, existingQuote?.cddjzb)
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
    if (
      (quote.moneyFlowEstimated === true || quote.capitalFlowSource === 'estimated_l1') &&
      quote.moneyFlowSource !== 'sina'
    ) {
      return false
    }
    return ['zlje', 'zljzb', 'cddje', 'cddjzb'].some((key) => {
      const value = Number((quote as unknown as Record<string, unknown>)[key])
      return Number.isFinite(value) && value !== 0
    })
  }

  private hasQuoteSupplementData(quote: Partial<MergedQuoteData> | null | undefined): boolean {
    if (!quote) return false
    return (
      Number(quote.turnoverRate) > 0 &&
      Number(quote.totalMV) > 0 &&
      Number(quote.cirMV) > 0 &&
      Number(quote.pb) > 0 &&
      Number.isFinite(Number(quote.pe)) &&
      Number(quote.pe) !== 0
    )
  }

  private mergeHttpIntoRealtimeQuote(
    realtimeQuote: MergedQuoteData,
    httpQuote: MergedQuoteData,
  ): MergedQuoteData {
    const preferHttpSupplement = this.hasQuoteSupplementData(httpQuote)
    const preferHttpFundFlow =
      (httpQuote.moneyFlowSource === 'eastmoney' || httpQuote.moneyFlowSource === 'sina') &&
      this.hasFundFlowData(httpQuote) &&
      shouldApplyMoneyFlowUpdate(realtimeQuote, httpQuote)

    return {
      ...httpQuote,
      ...realtimeQuote,
      price: pickFinite(realtimeQuote.price, httpQuote.price, true),
      change: pickFinite(realtimeQuote.change, httpQuote.change),
      volume: pickFinite(realtimeQuote.volume, httpQuote.volume, true),
      turnover: pickFinite(realtimeQuote.turnover, httpQuote.turnover, true),
      volumeRatio: pickFinite(realtimeQuote.volumeRatio, httpQuote.volumeRatio, true),
      turnoverRate: preferHttpSupplement
        ? pickFinite(httpQuote.turnoverRate, realtimeQuote.turnoverRate, true)
        : pickFinite(realtimeQuote.turnoverRate, httpQuote.turnoverRate, true),
      pe: preferHttpSupplement
        ? pickNonZeroNumber(httpQuote.pe, realtimeQuote.pe)
        : pickNonZeroNumber(realtimeQuote.pe, httpQuote.pe),
      totalMV: preferHttpSupplement
        ? pickFinite(httpQuote.totalMV, realtimeQuote.totalMV, true)
        : pickFinite(realtimeQuote.totalMV, httpQuote.totalMV, true),
      cirMV: preferHttpSupplement
        ? pickFinite(httpQuote.cirMV, realtimeQuote.cirMV, true)
        : pickFinite(realtimeQuote.cirMV, httpQuote.cirMV, true),
      pb: preferHttpSupplement
        ? pickFinite(httpQuote.pb, realtimeQuote.pb, true)
        : pickFinite(realtimeQuote.pb, httpQuote.pb, true),
      zlje: preferHttpFundFlow ? pickMoneyFlowNumber(httpQuote.zlje, realtimeQuote.zlje) : pickFundFlow(realtimeQuote.zlje, httpQuote.zlje),
      zljzb: preferHttpFundFlow ? pickMoneyFlowNumber(httpQuote.zljzb, realtimeQuote.zljzb) : pickFundFlow(realtimeQuote.zljzb, httpQuote.zljzb),
      cddje: preferHttpFundFlow ? pickMoneyFlowNumber(httpQuote.cddje, realtimeQuote.cddje) : pickFundFlow(realtimeQuote.cddje, httpQuote.cddje),
      cddjzb: preferHttpFundFlow ? pickMoneyFlowNumber(httpQuote.cddjzb, realtimeQuote.cddjzb) : pickFundFlow(realtimeQuote.cddjzb, httpQuote.cddjzb),
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

function pickMoneyFlowNumber(...values: unknown[]): number {
  for (const value of values) {
    const number = Number(value)
    if (Number.isFinite(number)) return number
  }

  return 0
}

function mergeHttpQuoteSources(
  existing: MergedQuoteData,
  fullQuote: MergedQuoteData & { source?: string },
  timestamp: number,
): MergedQuoteData {
  const hasFullQuoteMoneyFlow = ['zlje', 'zljzb', 'cddje', 'cddjzb'].some((key) => {
    const value = Number((fullQuote as unknown as Record<string, unknown>)[key])
    return Number.isFinite(value) && value !== 0
  })
  const useFullQuoteMoneyFlow =
    Boolean(fullQuote.moneyFlowSource) &&
    hasFullQuoteMoneyFlow &&
    (fullQuote.moneyFlowEstimated === false || fullQuote.moneyFlowSource === 'sina')
  const fullQuoteMainRatio = estimateMainMoneyRatio(fullQuote.zlje, existing.turnover)

  return {
    ...existing,
    price: pickFinite(fullQuote.price, existing.price, true),
    change: pickFinite(fullQuote.change, existing.change),
    volume: pickFinite(fullQuote.volume, existing.volume, true),
    turnover: pickFinite(fullQuote.turnover, existing.turnover, true),
    volumeRatio: pickFinite(fullQuote.volumeRatio, existing.volumeRatio, true),
    turnoverRate: pickFinite(fullQuote.turnoverRate, existing.turnoverRate, true),
    pe: pickNonZeroNumber(fullQuote.pe, existing.pe),
    totalMV: pickFinite(fullQuote.totalMV, existing.totalMV, true),
    cirMV: pickFinite(fullQuote.cirMV, existing.cirMV, true),
    pb: pickFinite(fullQuote.pb, existing.pb, true),
    zlje: useFullQuoteMoneyFlow ? pickMoneyFlowNumber(fullQuote.zlje) : existing.zlje,
    zljzb: useFullQuoteMoneyFlow
      ? pickNonZeroNumber(fullQuote.zljzb, fullQuoteMainRatio)
      : existing.zljzb,
    cddje: useFullQuoteMoneyFlow ? pickMoneyFlowNumber(fullQuote.cddje) : existing.cddje,
    cddjzb: useFullQuoteMoneyFlow ? pickMoneyFlowNumber(fullQuote.cddjzb) : existing.cddjzb,
    moneyFlowSource: useFullQuoteMoneyFlow ? fullQuote.moneyFlowSource : existing.moneyFlowSource,
    moneyFlowEstimated: useFullQuoteMoneyFlow
      ? fullQuote.moneyFlowEstimated
      : existing.moneyFlowEstimated,
    capitalFlowSource: useFullQuoteMoneyFlow
      ? fullQuote.capitalFlowSource
      : existing.capitalFlowSource,
    capitalFlowConfidence: useFullQuoteMoneyFlow
      ? fullQuote.capitalFlowConfidence
      : existing.capitalFlowConfidence,
    name: fullQuote.name || existing.name,
    sources: [...existing.sources, fullQuote.source || fullQuote.sources?.[0] || 'eastmoney'],
    confidence: 95,
    timestamp,
  }
}

function estimateMainMoneyRatio(mainNet: unknown, turnover: unknown): number {
  const main = Number(mainNet)
  const amount = Number(turnover)
  if (!Number.isFinite(main) || !Number.isFinite(amount) || amount <= 0) return 0
  return Number(((main / amount) * 100).toFixed(2))
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function createHttpQuoteProgressReporter(
  totalCodes: number,
  onProgress: (progress: QuoteBatchProgress) => void,
) {
  type FeedKind = 'basic' | 'full'

  const progressByFeed = new Map<FeedKind, QuoteBatchProgress>()
  let lastCompletedCodes = -1
  let lastTotalCodes = -1

  const fallbackProgress = (feed: FeedKind): QuoteBatchProgress => ({
    source: feed === 'basic' ? 'tencent' : 'eastmoney',
    completedBatches: 0,
    totalBatches: 1,
    completedCodes: 0,
    totalCodes,
  })

  const emit = (latest: QuoteBatchProgress) => {
    const basic = progressByFeed.get('basic') || fallbackProgress('basic')
    const full = progressByFeed.get('full') || fallbackProgress('full')
    const completedCodes = Math.floor((basic.completedCodes + full.completedCodes) / 2)
    const normalizedTotalCodes = Math.max(basic.totalCodes, full.totalCodes, totalCodes)
    if (completedCodes === lastCompletedCodes && normalizedTotalCodes === lastTotalCodes) return
    lastCompletedCodes = completedCodes
    lastTotalCodes = normalizedTotalCodes
    onProgress({
      ...latest,
      completedCodes,
      totalCodes: normalizedTotalCodes,
    })
  }

  return {
    report(feed: FeedKind, progress: QuoteBatchProgress) {
      progressByFeed.set(feed, progress)
      emit(progress)
    },
    settle(feed: FeedKind) {
      const current = progressByFeed.get(feed)
      const completed: QuoteBatchProgress = {
        ...(current || fallbackProgress(feed)),
        completedBatches: current?.totalBatches || 1,
        completedCodes: totalCodes,
        totalCodes,
      }
      progressByFeed.set(feed, completed)
      emit(completed)
    },
  }
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
