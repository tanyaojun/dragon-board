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
      if (result.status === 'unavailable') summary.unavailable++
      if (result.status === 'suspicious') summary.suspicious++

      updates.push({
        code,
        volumeRatio: result.value,
        volumeRatioMeta: this.toMeta(result),
      })
    }

    if (updates.length) {
      this.dataLayer.updateStockExtData(updates)
      summary.updated = updates.length
    }

    return summary
  }

  enrichStocks<T extends { code: string; volume?: unknown }>(
    stocks: T[],
    volumeHistoryMap: Map<string, number[]>,
    intradayVolumeHistoryMap: Map<string, number[]> = new Map(),
    date: Date = this.now(),
  ): Array<T & { volumeRatio?: number; volumeRatioMeta: VolumeRatioMeta }> {
    return stocks.map((stock) => {
      const result = this.calculateForStock(stock, volumeHistoryMap, intradayVolumeHistoryMap, date)
      return {
        ...stock,
        volumeRatio: result.value,
        volumeRatioMeta: this.toMeta(result),
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
}

export const volumeRatioUpdateService = new VolumeRatioUpdateService()
