import { Adapters } from '../adapters'
import { apiService } from '../apiService'
import { MAX_PLATFORM_CACHE_SIZE, PLATFORM_CACHE_TTL_MS } from './constants'
import type { PlatformLoadProgress } from './types'

export interface PlatformHotlistResult {
  data: Record<string, any[]>
  timestamp: number
  fromCache: boolean
}

export class PlatformHotlistService {
  private platformCache = new Map<string, { data: Record<string, any[]>; timestamp: number }>()
  private lastPlatformRefresh = 0

  constructor(
    private readonly cacheTtl = PLATFORM_CACHE_TTL_MS,
    private readonly maxCacheSize = MAX_PLATFORM_CACHE_SIZE,
  ) {}

  async loadPlatforms(
    platforms: string[],
    force = false,
    options: { onProgress?: (progress: PlatformLoadProgress) => void } = {},
  ): Promise<PlatformHotlistResult> {
    const activeCodes = await this.loadActiveStockCodes()
    if (!activeCodes) {
      return {
        data: Object.fromEntries(platforms.map((platform) => [platform, []])),
        timestamp: Date.now(),
        fromCache: false,
      }
    }

    const cached = this.platformCache.get('platforms')
    if (!force && cached && Date.now() - cached.timestamp < this.cacheTtl) {
      return {
        data: this.filterPlatformData(cached.data, activeCodes),
        timestamp: cached.timestamp,
        fromCache: true,
      }
    }

    const results: Record<string, any[]> = {}
    let completed = 0
    const allResults = await Promise.allSettled(
      platforms.map(async (platform) => {
        try {
          const adapter = Adapters[platform as keyof typeof Adapters]
          if (!adapter) return { platform, data: [], success: false }
          const rawData = await adapter.getHotList()
          const formatted = adapter.format(rawData)
          return { platform, data: formatted, success: true }
        } catch (error) {
          console.warn(`[DataLoader] 平台 ${platform} 加载失败:`, error)
          return { platform, data: [], success: false }
        } finally {
          completed += 1
          options.onProgress?.({
            completed,
            total: platforms.length,
            platform,
          })
        }
      }),
    )

    allResults.forEach((result) => {
      if (result.status === 'fulfilled' && result.value.success) {
        results[result.value.platform] = result.value.data.filter((item) => activeCodes.has(item?.code))
        return
      }

      const failedPlatform = result.status === 'fulfilled' ? result.value.platform : undefined
      if (failedPlatform) results[failedPlatform] = []
    })

    const timestamp = Date.now()
    this.setCache('platforms', { data: results, timestamp })
    return { data: results, timestamp, fromCache: false }
  }

  getAllHotCodes(data: Record<string, any[]>): Set<string> {
    const codes = new Set<string>()
    Object.values(data || {}).forEach((platformData) => {
      if (Array.isArray(platformData)) {
        platformData.forEach((item) => {
          if (item?.code) codes.add(item.code)
        })
      }
    })
    return codes
  }

  shouldRefresh(intervalMs: number): boolean {
    return Date.now() - this.lastPlatformRefresh >= intervalMs
  }

  markRefreshed() {
    this.lastPlatformRefresh = Date.now()
  }

  hasFreshCache(): boolean {
    const cached = this.platformCache.get('platforms')
    return !!cached && Date.now() - cached.timestamp < this.cacheTtl
  }

  maintenance() {
    const now = Date.now()
    for (const [key, value] of this.platformCache.entries()) {
      if (now - value.timestamp > this.cacheTtl) {
        this.platformCache.delete(key)
      }
    }
  }

  clearCache() {
    this.platformCache.clear()
  }

  private async loadActiveStockCodes(): Promise<Set<string> | null> {
    try {
      const response = await apiService.listStockNames({ active: true })
      if (response?.ok !== true || response?.source !== 'mongodb' || !Array.isArray(response.stocks)) {
        throw new Error('stock_names API did not return an active MongoDB stock list')
      }

      return new Set(
        response.stocks
          .filter((stock: any) => stock?.active === true && stock?.code && String(stock.name || '').trim())
          .map((stock: any) => String(stock.code).trim().padStart(6, '0')),
      )
    } catch (error) {
      console.warn('[DataLoader] MongoDB stock_names 白名单不可用，拒绝加载平台热榜:', error)
      return null
    }
  }

  private filterPlatformData(
    data: Record<string, any[]>,
    activeCodes: Set<string>,
  ): Record<string, any[]> {
    return Object.fromEntries(
      Object.entries(data).map(([platform, rows]) => [
        platform,
        Array.isArray(rows) ? rows.filter((item) => activeCodes.has(item?.code)) : [],
      ]),
    )
  }

  private setCache(key: string, value: { data: Record<string, any[]>; timestamp: number }) {
    if (this.platformCache.size >= this.maxCacheSize) {
      const oldestKey = this.platformCache.keys().next().value
      oldestKey && this.platformCache.delete(oldestKey)
    }

    this.platformCache.set(key, value)
  }
}

export const platformHotlistService = new PlatformHotlistService()
