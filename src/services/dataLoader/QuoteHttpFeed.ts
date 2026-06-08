import { normalizeStockCode } from '@/utils/common'
import { apiService } from '../apiService'
import { EASTMONEY_QUOTE_ENRICHMENT_ENABLED } from './constants'
import type { QuoteBatchProgress } from './types'

type QuoteApi = {
  getQuotes: (codes: string[], options: Record<string, unknown>) => Promise<any>
}

type Sleep = (ms: number) => Promise<void>
type QuoteBatchProgressCallback = (progress: QuoteBatchProgress) => void
const SINA_MONEY_FLOW_BATCH_SIZE = 20
const SINA_MONEY_FLOW_TIMEOUT_MS = 20000

export class QuoteHttpFeed {
  private readonly api: QuoteApi
  private readonly sleep: Sleep
  private readonly eastmoneyQuoteEnrichmentEnabled: boolean

  constructor(options: {
    api?: QuoteApi
    sleep?: Sleep
    eastmoneyQuoteEnrichmentEnabled?: boolean
  } = {}) {
    this.api = options.api || apiService
    this.sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)))
    this.eastmoneyQuoteEnrichmentEnabled =
      options.eastmoneyQuoteEnrichmentEnabled ?? EASTMONEY_QUOTE_ENRICHMENT_ENABLED
  }

  async fetchBasicData(
    codes: string[],
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    try {
      return await this.fetchFromTencent(codes, options)
    } catch (error) {
      console.warn('[DataLoader] 腾讯接口失败，尝试新浪:', error)
      return await this.fetchFromSina(codes, options)
    }
  }

  async fetchFullData(
    codes: string[],
    force?: boolean,
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    if (!this.eastmoneyQuoteEnrichmentEnabled) {
      return new Map()
    }

    let eastmoneyRows = new Map<string, any>()
    try {
      eastmoneyRows = await this.fetchFromEastMoney(codes, force, options)
    } catch (error) {
      console.warn('[DataLoader] 东财资金流补全失败，尝试新浪资金流:', error)
    }
    const missingMoneyCodes = codes.filter((code) => {
      const row = eastmoneyRows.get(normalizeStockCode(code))
      return !hasMoneyFlow(row?.zlje)
    })

    if (!missingMoneyCodes.length) {
      return eastmoneyRows
    }

    try {
      const sinaRows = await this.fetchFromSinaMoneyFlow(missingMoneyCodes, force, options)
      for (const [code, sinaRow] of sinaRows) {
        const existing = eastmoneyRows.get(code)
        if (!existing) {
          eastmoneyRows.set(code, sinaRow)
          continue
        }
        if (hasMoneyFlow(sinaRow.zlje)) {
          existing.zlje = sinaRow.zlje
          existing.moneyFlowSource = 'sina'
          existing.moneyFlowEstimated = true
          existing.capitalFlowSource = 'sina_money_flow'
          existing.capitalFlowConfidence = 'low'
          existing.zljzb = estimateMainMoneyRatio(existing.zlje, existing.turnover) || existing.zljzb || 0
        }
      }
    } catch (error) {
      console.warn('[DataLoader] 新浪资金流补全失败，保留东财行情数据:', error)
    }

    return eastmoneyRows
  }

  async fetchFromTencent(
    codes: string[],
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    return this.fetchInBatches(codes, 'tencent', 100, (item) => ({
      price: parseFloat(item.f2) || 0,
      change: parseFloat(item.f3) || 0,
      volume: parseInt(item.f6) || 0,
      turnover: parseFloat(item.f5) || 0,
      turnoverRate: parseFloat(item.f8) || 0,
      pe: parseFloat(item.f9) || 0,
      pb: parseFloat(item.f23) || 0,
      volumeRatio: parseFloat(item.f10) || 0,
      name: item.f14 || '',
      source: 'tencent',
      totalMV: (parseFloat(item.f20) || 0) * 10000,
      cirMV: (parseFloat(item.f21) || 0) * 10000,
      zlje: parseFloat(item.f62) || 0,
      zljzb: parseFloat(item.f184) || 0,
      cddje: parseFloat(item.f66) || 0,
      cddjzb: parseFloat(item.f69) || 0,
    }), options.onProgress)
  }

  async fetchFromSina(
    codes: string[],
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    return this.fetchInBatches(codes, 'sina', 100, (item) => ({
      price: parseFloat(item.f2) || 0,
      change: parseFloat(item.f3) || 0,
      volume: parseInt(item.f6) || 0,
      turnover: parseFloat(item.f5) || 0,
      turnoverRate: parseFloat(item.f8) || 0,
      pe: parseFloat(item.f9) || 0,
      pb: parseFloat(item.f23) || 0,
      volumeRatio: parseFloat(item.f10) || 0,
      name: item.f14 || '',
      source: 'sina',
      totalMV: (parseFloat(item.f20) || 0) * 10000,
      cirMV: (parseFloat(item.f21) || 0) * 10000,
      zlje: parseFloat(item.f62) || 0,
      zljzb: parseFloat(item.f184) || 0,
      cddje: parseFloat(item.f66) || 0,
      cddjzb: parseFloat(item.f69) || 0,
    }), options.onProgress)
  }

  async fetchFromEastMoney(
    codes: string[],
    force?: boolean,
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const batchSize = 50
    const totalBatches = Math.ceil(codes.length / batchSize) || 1

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)
      const response = await this.api.getQuotes(batch, {
        source: 'eastmoney',
        force,
        refresh: force ? '1' : undefined,
        timeout: 8000,
        retries: 2,
      })

      const diff = response?.data?.diff || []
      diff.forEach((item: any) => {
        const code = normalizeStockCode(item.f12)
        result.set(code, {
          price: parseFloat(item.f2) || 0,
          change: parseFloat(item.f3) || 0,
          volume: parseInt(item.f5) || 0,
          turnover: parseFloat(item.f6) || 0,
          turnoverRate: parseFloat(item.f8) || 0,
          pe: parseFloat(item.f9) || 0,
          pb: parseFloat(item.f23) || 0,
          volumeRatio: parseFloat(item.f10) || 0,
          name: item.f14 || '',
          source: 'eastmoney',
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
          totalMV: parseFloat(item.f20) || 0,
          cirMV: parseFloat(item.f21) || 0,
          zlje: parseFloat(item.f62) || 0,
          zljzb:
            parseFloat(item.f184) ||
            estimateMainMoneyRatio(parseFloat(item.f62), parseFloat(item.f6)) ||
            0,
          cddje: parseFloat(item.f66) || 0,
          cddjzb: parseFloat(item.f69) || 0,
        })
      })
      options.onProgress?.({
        source: 'eastmoney',
        completedBatches: Math.floor(i / batchSize) + 1,
        totalBatches,
        completedCodes: Math.min(i + batch.length, codes.length),
        totalCodes: codes.length,
      })

      if (i + batchSize < codes.length) {
        await this.sleep(200)
      }
    }

    return result
  }

  async fetchFromSinaMoneyFlow(
    codes: string[],
    force?: boolean,
    options: { onProgress?: QuoteBatchProgressCallback } = {},
  ): Promise<Map<string, any>> {
    return this.fetchInBatches(
      codes,
      'sinaMoneyFlow',
      120,
      (item) => ({
        price: parseFloat(item.f2) || 0,
        name: item.f14 || '',
        source: 'sina',
        moneyFlowSource: 'sina',
        moneyFlowEstimated: true,
        capitalFlowSource: 'sina_money_flow',
        capitalFlowConfidence: 'low',
        zlje: parseFloat(item.f62) || 0,
        zljzb: 0,
      }),
      options.onProgress,
      force,
      SINA_MONEY_FLOW_BATCH_SIZE,
      { timeout: SINA_MONEY_FLOW_TIMEOUT_MS, retries: 0 },
    )
  }

  private async fetchInBatches(
    codes: string[],
    source: 'tencent' | 'sina' | 'sinaMoneyFlow',
    delayMs: number,
    mapItem: (item: any) => Record<string, unknown>,
    onProgress?: QuoteBatchProgressCallback,
    force?: boolean,
    batchSize = 50,
    extraRequestOptions: Record<string, unknown> = {},
  ): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const totalBatches = Math.ceil(codes.length / batchSize) || 1

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)
      const requestOptions =
        force === undefined
          ? { source, ...extraRequestOptions }
          : { source, force, ...extraRequestOptions }
      const response = await this.api.getQuotes(batch, requestOptions)
      const diff = response?.data?.diff || []
      const returnedCodes = new Set<string>()
      diff.forEach((item: any) => {
        const code = normalizeStockCode(item.f12)
        returnedCodes.add(code)
        result.set(code, mapItem(item))
      })
      if (source === 'sinaMoneyFlow' && batch.length > 1 && Number(response?.dragonMeta?.failed) > 0) {
        const missingCodes = batch.filter((code) => !returnedCodes.has(normalizeStockCode(code)))
        for (const code of missingCodes) {
          try {
            const singleResponse = await this.api.getQuotes([code], requestOptions)
            const singleDiff = singleResponse?.data?.diff || []
            singleDiff.forEach((item: any) => {
              const normalizedCode = normalizeStockCode(item.f12)
              result.set(normalizedCode, mapItem(item))
            })
          } catch (error) {
            console.warn('[DataLoader] 新浪资金流单只重试失败:', code, error)
          }
        }
      }
      onProgress?.({
        source,
        completedBatches: Math.floor(i / batchSize) + 1,
        totalBatches,
        completedCodes: Math.min(i + batch.length, codes.length),
        totalCodes: codes.length,
      })

      if (i + batchSize < codes.length) {
        await this.sleep(delayMs)
      }
    }

    return result
  }
}

export const quoteHttpFeed = new QuoteHttpFeed()

function hasMoneyFlow(value: unknown): boolean {
  const amount = Number(value)
  return Number.isFinite(amount) && amount !== 0
}

function estimateMainMoneyRatio(mainNet: unknown, turnover: unknown): number {
  const main = Number(mainNet)
  const amount = Number(turnover)
  if (!Number.isFinite(main) || !Number.isFinite(amount) || amount <= 0) return 0
  return Number(((main / amount) * 100).toFixed(2))
}
