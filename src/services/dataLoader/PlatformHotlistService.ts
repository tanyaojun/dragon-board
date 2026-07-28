import { Adapters } from '../adapters'
import { apiService } from '../apiService'
import { MAX_PLATFORM_CACHE_SIZE, PLATFORM_CACHE_TTL_MS } from './constants'
import type { PlatformLoadProgress } from './types'

export interface PlatformHotlistResult {
  data: Record<string, any[]>
  timestamp: number
  fromCache: boolean
}

export interface PlatformReloadDiagnostic {
  rowCount: number
  success: boolean
  error?: string
}

export interface PlatformCacheDiagnostics {
  lastCheckAt: number | null
  lastReloadAt: number | null
  lastLoadFromCache: boolean | null
  cacheTimestamp: number | null
  platforms: Record<string, PlatformReloadDiagnostic>
}

export class PlatformHotlistService {
  private platformCache = new Map<string, { data: Record<string, any[]>; timestamp: number }>()
  private lastPlatformRefresh = 0
  private diagnostics: Omit<PlatformCacheDiagnostics, 'cacheTimestamp'> = {
    lastCheckAt: null,
    lastReloadAt: null,
    lastLoadFromCache: null,
    platforms: {},
  }

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
      this.diagnostics.lastLoadFromCache = false
      this.diagnostics.platforms = Object.fromEntries(
        platforms.map((platform) => [
          platform,
          { rowCount: 0, success: false, error: 'active-stock-codes-unavailable' },
        ]),
      )
      return {
        data: Object.fromEntries(platforms.map((platform) => [platform, []])),
        timestamp: Date.now(),
        fromCache: false,
      }
    }

    const cached = this.platformCache.get('platforms')
    if (!force && cached && Date.now() - cached.timestamp < this.cacheTtl) {
      const data = this.filterPlatformData(cached.data, activeCodes)
      this.diagnostics.lastLoadFromCache = true
      this.diagnostics.platforms = this.summarizePlatforms(data)
      return {
        data,
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
          if (!adapter) {
            return { platform, data: [], success: false, error: 'adapter-unavailable' }
          }
          const rawData = await adapter.getHotList()
          const formatted = adapter.format(rawData)
          return { platform, data: formatted, success: true }
        } catch (error) {
          console.warn(`[DataLoader] 平台 ${platform} 加载失败:`, error)
          return {
            platform,
            data: [],
            success: false,
            error: error instanceof Error ? error.message : String(error),
          }
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

    const platformDiagnostics: Record<string, PlatformReloadDiagnostic> = {}
    allResults.forEach((result, index) => {
      if (result.status === 'fulfilled' && result.value.success) {
        const rows = result.value.data.filter((item) => activeCodes.has(item?.code))
        results[result.value.platform] = rows
        platformDiagnostics[result.value.platform] = {
          rowCount: rows.length,
          success: true,
        }
        return
      }

      const failedPlatform = platforms[index]
      const error =
        result.status === 'fulfilled'
          ? result.value.error || 'platform-load-failed'
          : result.reason instanceof Error
            ? result.reason.message
            : String(result.reason)
      results[failedPlatform] = []
      platformDiagnostics[failedPlatform] = {
        rowCount: 0,
        success: false,
        error,
      }
    })

    const timestamp = Date.now()
    this.setCache('platforms', { data: results, timestamp })
    this.diagnostics.lastReloadAt = timestamp
    this.diagnostics.lastLoadFromCache = false
    this.diagnostics.platforms = platformDiagnostics
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

  markRefreshChecked(): void {
    this.diagnostics.lastCheckAt = Date.now()
  }

  markRefreshed() {
    this.lastPlatformRefresh = Date.now()
  }

  hasFreshCache(): boolean {
    const cached = this.platformCache.get('platforms')
    return !!cached && Date.now() - cached.timestamp < this.cacheTtl
  }

  getCacheDiagnostics(): PlatformCacheDiagnostics {
    return {
      ...this.diagnostics,
      cacheTimestamp: this.platformCache.get('platforms')?.timestamp ?? null,
      platforms: { ...this.diagnostics.platforms },
    }
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

  private summarizePlatforms(data: Record<string, any[]>): Record<string, PlatformReloadDiagnostic> {
    return Object.fromEntries(
      Object.entries(data).map(([platform, rows]) => [
        platform,
        { rowCount: Array.isArray(rows) ? rows.length : 0, success: true },
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
