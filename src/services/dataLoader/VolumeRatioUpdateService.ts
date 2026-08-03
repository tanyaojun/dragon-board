import { apiService } from '../apiService'
import { dataLayer as defaultDataLayer } from '../DataLayer'
import type { StockExtData, VolumeRatioMeta } from '@/types/data-layer'

type VolumeRatioDataLayer = {
  getStocks: () => Array<{
    code: string
    volume?: unknown
    volumeRatio?: number
    volumeRatioMeta?: VolumeRatioMeta | null
  }>
  updateStockExtData: (updates: Array<Partial<StockExtData> & { code: string }>) => void
}

export interface VolumeRatioUpdateSummary {
  requested: number
  updated: number
  unavailable: number
  suspicious: number
}

type BackendVolumeRatioItem = {
  value?: number
  status?: string
  source?: string
  currentVolume?: number
  expectedVolume?: number
  historyVolumes?: number[]
  rawRatio?: number
  capped?: boolean
  reason?: string
  calculatedAt?: number
}

/**
 * 量比更新服务：只消费后端量比结果（Python golden + Redis TTL），
 * 不再在前端读取快照历史或运行量比算法（原 VolumeHistoryService/VolumeRatioCalculator 已迁移后端）。
 */
export class VolumeRatioUpdateService {
  private readonly dataLayer: VolumeRatioDataLayer
  private readonly now: () => Date

  constructor(
    options: {
      dataLayer?: VolumeRatioDataLayer
      now?: () => Date
    } = {},
  ) {
    this.dataLayer = options.dataLayer || defaultDataLayer
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

    const stockByCode = new Map(this.dataLayer.getStocks().map((stock) => [stock.code, stock]))
    const stocks = targetCodes
      .map((code) => {
        const volume = Number(stockByCode.get(code)?.volume)
        return { code, volume }
      })
      .filter((item) => Number.isFinite(item.volume) && item.volume > 0)
    if (!stocks.length) return summary

    try {
      const response = await apiService.getVolumeRatios({ stocks })
      const items = response?.items && typeof response.items === 'object' ? response.items : {}
      const updates: Array<Partial<StockExtData> & { code: string }> = []

      for (const code of targetCodes) {
        const stock = stockByCode.get(code)
        const item = items[code]
        if (!item) {
          summary.unavailable++
          continue
        }
        const meta = this.toMeta(item)
        const preserved = this.preserveExistingRatio(stock, meta, item)
        if (preserved) {
          updates.push(preserved)
          continue
        }
        if (meta.status === 'unavailable') summary.unavailable++
        else if (meta.status === 'suspicious') summary.suspicious++
        updates.push({
          code,
          volumeRatio: typeof item.value === 'number' ? item.value : undefined,
          volumeRatioMeta: meta,
        })
      }

      if (updates.length) {
        this.dataLayer.updateStockExtData(updates)
        summary.updated = updates.length
      }
      return summary
    } catch (error) {
      // 后端量比不可用：保留现有量比，结构化失败原因由日志暴露（fail-visible，不伪装 0）
      console.warn('[VolumeRatio] 后端量比服务不可用，保留现有量比:', error)
      return summary
    }
  }

  private toMeta(item: BackendVolumeRatioItem): VolumeRatioMeta {
    const status =
      item.status === 'fresh' || item.status === 'suspicious' ? item.status : 'unavailable'
    const source =
      item.source === 'intraday_snapshot' || item.source === 'daily_snapshot'
        ? item.source
        : 'unavailable'
    const currentVolume = Number(item.currentVolume)
    const expectedVolume = Number(item.expectedVolume)
    const rawRatio = Number(item.rawRatio)
    return {
      status,
      source,
      calculatedAt: Number(item.calculatedAt) || this.now().getTime(),
      currentVolume: Number.isFinite(currentVolume) ? currentVolume : 0,
      expectedVolume: Number.isFinite(expectedVolume) ? expectedVolume : undefined,
      historyVolumes: Array.isArray(item.historyVolumes) ? item.historyVolumes.map(Number) : [],
      rawRatio: Number.isFinite(rawRatio) ? rawRatio : undefined,
      capped: item.capped === true,
      reason: typeof item.reason === 'string' ? item.reason : undefined,
    }
  }

  private preserveExistingRatio(
    stock: ReturnType<VolumeRatioDataLayer['getStocks']>[number] | undefined,
    meta: VolumeRatioMeta,
    item: BackendVolumeRatioItem,
  ): (Partial<StockExtData> & { code: string }) | null {
    if (!stock) return null
    if (meta.status !== 'unavailable' || item.reason !== 'insufficient_history') return null

    const previousValue = Number(stock.volumeRatio)
    if (!Number.isFinite(previousValue) || previousValue <= 0) return null
    if (stock.volumeRatioMeta?.status === 'unavailable') return null

    const previousMeta = stock.volumeRatioMeta ?? null
    return {
      code: stock.code,
      volumeRatio: previousValue,
      volumeRatioMeta: {
        ...(previousMeta || {}),
        status: 'stale',
        source: previousMeta?.source || 'unavailable',
        calculatedAt: meta.calculatedAt,
        currentVolume: meta.currentVolume,
        historyVolumes: meta.historyVolumes,
        reason: 'history_unavailable_preserved_previous',
      },
    }
  }
}

export const volumeRatioUpdateService = new VolumeRatioUpdateService()
