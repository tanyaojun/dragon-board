import { normalizeStockCode } from '@/utils/common'
import { apiService } from '../apiService'
import { EASTMONEY_QUOTE_ENRICHMENT_ENABLED } from './constants'
import type { QuoteBatchProgress } from './types'

type QuoteApi = {
  getQuotes: (codes: string[], options: Record<string, unknown>) => Promise<any>
}

type Sleep = (ms: number) => Promise<void>
type QuoteBatchProgressCallback = (progress: QuoteBatchProgress) => void

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

    return await this.fetchFromEastMoney(codes, force, options)
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
          name: item.f14 || '',
          source: 'eastmoney',
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
          totalMV: parseFloat(item.f20) || 0,
          cirMV: parseFloat(item.f21) || 0,
          zlje: parseFloat(item.f62) || 0,
          zljzb: parseFloat(item.f184) || 0,
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

  private async fetchInBatches(
    codes: string[],
    source: 'tencent' | 'sina',
    delayMs: number,
    mapItem: (item: any) => Record<string, unknown>,
    onProgress?: QuoteBatchProgressCallback,
  ): Promise<Map<string, any>> {
    const result = new Map<string, any>()
    const batchSize = 50
    const totalBatches = Math.ceil(codes.length / batchSize) || 1

    for (let i = 0; i < codes.length; i += batchSize) {
      const batch = codes.slice(i, i + batchSize)
      const response = await this.api.getQuotes(batch, { source })
      const diff = response?.data?.diff || []
      diff.forEach((item: any) => {
        const code = normalizeStockCode(item.f12)
        result.set(code, mapItem(item))
      })
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
