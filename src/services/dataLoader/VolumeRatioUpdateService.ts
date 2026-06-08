import { dataLayer as defaultDataLayer } from '../DataLayer'
import { VolumeHistoryService } from './VolumeHistoryService'
import { INTRADAY_VOLUME_SNAPSHOT_TYPES } from './constants'
import { calculateVolumeRatio, type VolumeRatioResult } from './VolumeRatioCalculator'
import type { StockExtData, VolumeRatioMeta } from '@/types/data-layer'

type VolumeRatioDataLayer = {
  getStocks: () => Array<{ code: string; volume?: unknown; volumeRatio?: number }>
  updateStockExtData: (updates: Array<Partial<StockExtData> & { code: string }>) => void
}

type VolumeRatioHistoryReader = {
  buildVolumeHistoryMap: (codes: string[]) => Promise<Map<string, number[]>>
  buildIntradayVolumeHistoryMap: (codes: string[], date?: Date) => Promise<Map<string, number[]>>
}

type ResolvedVolumeRatio = {
  value?: number
  meta: VolumeRatioMeta
}

export interface VolumeRatioUpdateSummary {
  requested: number
  updated: number
  unavailable: number
  suspicious: number
}

export class VolumeRatioUpdateService {
  private readonly dataLayer: VolumeRatioDataLayer
  private readonly volumeHistoryService: VolumeRatioHistoryReader
  private readonly now: () => Date

  constructor(options: {
    dataLayer?: VolumeRatioDataLayer
    volumeHistoryService?: VolumeRatioHistoryReader
    now?: () => Date
  } = {}) {
    this.dataLayer = options.dataLayer || defaultDataLayer
    this.volumeHistoryService =
      options.volumeHistoryService || new VolumeHistoryService(INTRADAY_VOLUME_SNAPSHOT_TYPES)
    this.now = options.now || (() => new Date())
  }

  async updateVolumeRatios(codes: string[]): Promise<VolumeRatioUpdateSummary> {
    const targetCodes = [...new Set(codes.filter((code) => code && code.length === 6))]
    const summary: VolumeRatioUpdateSummary = {
      requested: targetCodes.length,
      updated: 0,
      unavailable: 0,
      suspicious: 0,
    }
    if (!targetCodes.length) return summary

    const date = this.now()
    const [volumeHistoryMap, intradayVolumeHistoryMap] = await Promise.all([
      this.volumeHistoryService.buildVolumeHistoryMap(targetCodes),
      this.volumeHistoryService.buildIntradayVolumeHistoryMap(targetCodes, date),
    ])

    const stocks = this.dataLayer.getStocks()
    const stockMap = new Map(stocks.map((stock) => [stock.code, stock]))
    const updates: Array<Partial<StockExtData> & { code: string }> = []

    for (const code of targetCodes) {
      const stock = stockMap.get(code)
      if (!stock) continue

      const result = this.calculateForStock(stock, volumeHistoryMap, intradayVolumeHistoryMap, date)
      const resolved = this.resolveResult(stock, result)
      if (resolved.meta.status === 'unavailable') summary.unavailable++
      if (resolved.meta.status === 'suspicious') summary.suspicious++

      updates.push({
        code,
        volumeRatio: resolved.value,
        volumeRatioMeta: resolved.meta,
      })
    }

    if (updates.length) {
      this.dataLayer.updateStockExtData(updates)
      summary.updated = updates.length
    }

    return summary
  }

  enrichStocks<
    T extends {
      code: string
      volume?: unknown
      volumeRatio?: unknown
      volumeRatioMeta?: VolumeRatioMeta | null
    },
  >(
    stocks: T[],
    volumeHistoryMap: Map<string, number[]>,
    intradayVolumeHistoryMap: Map<string, number[]> = new Map(),
    date: Date = this.now(),
  ): Array<T & { volumeRatio?: number; volumeRatioMeta: VolumeRatioMeta }> {
    return stocks.map((stock) => {
      const result = this.calculateForStock(stock, volumeHistoryMap, intradayVolumeHistoryMap, date)
      const resolved = this.resolveResult(stock, result)
      return {
        ...stock,
        volumeRatio: resolved.value,
        volumeRatioMeta: resolved.meta,
      }
    })
  }

  private calculateForStock(
    stock: { code: string; volume?: unknown },
    volumeHistoryMap: Map<string, number[]>,
    intradayVolumeHistoryMap: Map<string, number[]>,
    date: Date,
  ) {
    return calculateVolumeRatio(stock, stock.code, volumeHistoryMap, intradayVolumeHistoryMap, date)
  }

  private toMeta(result: VolumeRatioResult): VolumeRatioMeta {
    return {
      status: result.status,
      source: result.source,
      calculatedAt: result.calculatedAt,
      currentVolume: result.currentVolume,
      expectedVolume: result.expectedVolume,
      historyVolumes: result.historyVolumes,
      rawRatio: result.rawRatio,
      capped: result.capped,
      reason: result.reason,
    }
  }

  private resolveResult(
    stock: { volumeRatio?: unknown; volumeRatioMeta?: VolumeRatioMeta | null },
    result: VolumeRatioResult,
  ): ResolvedVolumeRatio {
    const preserved = this.preserveExistingRatio(stock, result)
    if (preserved) return preserved

    return {
      value: result.value,
      meta: this.toMeta(result),
    }
  }

  private preserveExistingRatio(
    stock: { volumeRatio?: unknown; volumeRatioMeta?: VolumeRatioMeta | null },
    result: VolumeRatioResult,
  ): ResolvedVolumeRatio | null {
    if (result.status !== 'unavailable' || result.reason !== 'insufficient_history') return null

    const previousValue = Number(stock.volumeRatio)
    if (!Number.isFinite(previousValue) || previousValue <= 0) return null
    if (stock.volumeRatioMeta?.status === 'unavailable') return null

    const previousMeta = stock.volumeRatioMeta ?? null
    return {
      value: previousValue,
      meta: {
        ...(previousMeta || {}),
        status: 'stale',
        source: previousMeta?.source || 'unavailable',
        calculatedAt: result.calculatedAt,
        currentVolume: result.currentVolume,
        historyVolumes: result.historyVolumes,
        reason: 'history_unavailable_preserved_previous',
      },
    }
  }
}

export const volumeRatioUpdateService = new VolumeRatioUpdateService()
