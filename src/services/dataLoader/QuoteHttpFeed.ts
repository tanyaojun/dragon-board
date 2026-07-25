import { normalizeStockCode } from '@/utils/common'
import { apiService } from '../apiService'
import type { QuoteBatchProgress } from './types'

type QuoteApi = {
  getQuotes: (codes: string[], options: Record<string, unknown>) => Promise<any>
}

type Sleep = (ms: number) => Promise<void>
type QuoteBatchProgressCallback = (progress: QuoteBatchProgress) => void

export class QuoteHttpFeed {
  private readonly api: QuoteApi
  private readonly sleep: Sleep

  constructor(options: {
    api?: QuoteApi
    sleep?: Sleep
    eastmoneyQuoteEnrichmentEnabled?: boolean
  } = {}) {
    this.api = options.api || apiService
    this.sleep = options.sleep || ((ms) => new Promise((resolve) => setTimeout(resolve, ms)))
    void options.eastmoneyQuoteEnrichmentEnabled
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
    void codes
    void force
    void options
    return new Map()
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
    }), options.onProgress)
  }


  private async fetchInBatches(
    codes: string[],
    source: 'tencent' | 'sina',
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
