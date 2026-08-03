import { Adapters } from '../adapters'
import { apiService } from '../apiService'
import {
  MAX_PLATFORM_CACHE_SIZE,
  PLATFORM_CACHE_TTL_MS,
  PLATFORM_FAILURE_THRESHOLD,
} from './constants'
import type { PlatformLoadProgress } from './types'

export interface PlatformHotlistResult {
  data: Record<string, any[]>
  timestamp: number
  fromCache: boolean
}

export interface PlatformReloadDiagnostic {
  rowCount: number
  success: boolean
  consecutiveFailures?: number
  error?: string
  /** 质量标记：白名单不可用时平台数据按原样展示（fail-visible，不阻断） */
  warning?: string
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
  private consecutiveFailures: Record<string, number> = {}
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
    const whitelistUnavailable = activeCodes === null

    if (whitelistUnavailable) {
      // fail-visible：stock_names 白名单不可用不再阻断平台加载，
      // 平台原始数据照常展示并打标，供下游与诊断观察（质量标记不是硬门禁）。
      console.warn(
        '[DataLoader] MongoDB stock_names 白名单不可用，平台数据按原样展示并打标（fail-visible）',
      )
    }

    const cached = this.platformCache.get('platforms')
    if (!force && cached && Date.now() - cached.timestamp < this.cacheTtl) {
      const data = this.filterPlatformData(cached.data, activeCodes)
      this.diagnostics.lastLoadFromCache = true
      this.diagnostics.platforms = this.summarizePlatforms(data, whitelistUnavailable)
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
        const rows = whitelistUnavailable
          ? result.value.data
          : result.value.data.filter((item) => activeCodes!.has(item?.code))
        results[result.value.platform] = rows
        this.consecutiveFailures[result.value.platform] = 0
        platformDiagnostics[result.value.platform] = {
          rowCount: rows.length,
          success: true,
          consecutiveFailures: 0,
          ...(whitelistUnavailable ? { warning: 'whitelist-unavailable' } : {}),
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
      const failureCount = (this.consecutiveFailures[failedPlatform] ?? 0) + 1
      this.consecutiveFailures[failedPlatform] = failureCount
      platformDiagnostics[failedPlatform] = {
        rowCount: 0,
        success: false,
        consecutiveFailures: failureCount,
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

  /**
   * 后台重试失败平台（连续失败 < 阈值）：成功即恢复，连续 3 次失败后不再自动重试。
   * 返回本次是否取回数据，供上层合并进展示层。
   */
  async retryFailedPlatforms(): Promise<{ updated: boolean; data: Record<string, any[]> }> {
    const activeCodes = await this.loadActiveStockCodes()
    const whitelistUnavailable = activeCodes === null
    if (whitelistUnavailable) {
      console.warn(
        '[DataLoader] 失败平台重试：stock_names 白名单不可用，按原样合并并打标（fail-visible）',
      )
    }
    const candidates = Object.entries(this.consecutiveFailures)
      .filter(([, count]) => count > 0 && count < PLATFORM_FAILURE_THRESHOLD)
      .map(([platform]) => platform)
    if (candidates.length === 0) {
      return { updated: false, data: {} }
    }

    const updated: Record<string, any[]> = {}
    let anyUpdated = false
    await Promise.allSettled(
      candidates.map(async (platform) => {
        try {
          const adapter = Adapters[platform as keyof typeof Adapters]
          if (!adapter) {
            throw new Error('adapter-unavailable')
          }
          const rawData = await adapter.getHotList()
          const formatted = adapter.format(rawData)
          const rows = whitelistUnavailable
            ? formatted
            : formatted.filter((item) => activeCodes!.has(item?.code))
          this.consecutiveFailures[platform] = 0
          this.diagnostics.platforms[platform] = {
            rowCount: rows.length,
            success: true,
            consecutiveFailures: 0,
            ...(whitelistUnavailable ? { warning: 'whitelist-unavailable' } : {}),
          }
          updated[platform] = rows
          anyUpdated = true
        } catch (error) {
          const count = (this.consecutiveFailures[platform] ?? 0) + 1
          this.consecutiveFailures[platform] = count
          this.diagnostics.platforms[platform] = {
            rowCount: 0,
            success: false,
            consecutiveFailures: count,
            error: error instanceof Error ? error.message : String(error),
          }
        }
      }),
    )

    if (anyUpdated) {
      const cached = this.platformCache.get('platforms')
      if (cached) {
        this.platformCache.set('platforms', {
          data: { ...cached.data, ...updated },
          timestamp: Date.now(),
        })
      }
    }
    return { updated: anyUpdated, data: updated }
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
    this.consecutiveFailures = {}
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
    activeCodes: Set<string> | null,
  ): Record<string, any[]> {
    if (!activeCodes) return data
    return Object.fromEntries(
      Object.entries(data).map(([platform, rows]) => [
        platform,
        Array.isArray(rows) ? rows.filter((item) => activeCodes.has(item?.code)) : [],
      ]),
    )
  }

  private summarizePlatforms(
    data: Record<string, any[]>,
    whitelistUnavailable = false,
  ): Record<string, PlatformReloadDiagnostic> {
    const summary: Record<string, PlatformReloadDiagnostic> = {}
    for (const [platform, rows] of Object.entries(data)) {
      this.consecutiveFailures[platform] = 0
      summary[platform] = {
        rowCount: Array.isArray(rows) ? rows.length : 0,
        success: true,
        consecutiveFailures: 0,
        ...(whitelistUnavailable ? { warning: 'whitelist-unavailable' } : {}),
      }
    }
    return summary
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
