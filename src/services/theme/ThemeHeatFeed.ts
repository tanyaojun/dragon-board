import { ApiHttpError, apiService } from '@/services/apiService'
import { cacheManager } from '@/services/LRUCache'
import type {
  ThemeFactorSnapshot,
  ThemeHeatApiFactor,
  ThemeHeatApiSnapshot,
  ThemeHeatStock,
  ThemeQualityFlag,
  ThemeQualityFlagCode,
  ThemeStockRole,
} from './types'


type ThemeHeatApiClient = Pick<typeof apiService, 'getThemeHeat' | 'getThemeHeatStocks'>
type StoredSnapshot = ThemeHeatApiSnapshot & { stale: boolean; lastError: string | null }

const STOCK_ROLES = new Set<ThemeStockRole>(['leader', 'core', 'follower', 'independent', 'noise'])

// 题材热度数据 LRU TTL 缓存（复用 src/services/LRUCache.ts；30 秒 TTL，force 可绕过）
const THEME_HEAT_TTL_MS = 30_000

export const themeHeatSnapshotCache = cacheManager.createCache('themeHeat', {
  capacity: 4,
  defaultTTL: THEME_HEAT_TTL_MS,
  maxMemory: 8 * 1024 * 1024,
  ttlConfig: { themeHeat: THEME_HEAT_TTL_MS },
})

export const themeHeatStocksCache = cacheManager.createCache('themeHeatStocks', {
  capacity: 200,
  defaultTTL: THEME_HEAT_TTL_MS,
  maxMemory: 8 * 1024 * 1024,
  ttlConfig: { themeHeatStocks: THEME_HEAT_TTL_MS },
})

function finite(value: unknown, fallback = 0): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function nullableFinite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function normalizeFlags(value: unknown): ThemeQualityFlag[] {
  if (!Array.isArray(value)) return []
  return value.flatMap((item) => {
    if (typeof item === 'string') {
      return [{ code: item as ThemeQualityFlagCode, level: 'warning' as const, message: item }]
    }
    if (!item || typeof item !== 'object') return []
    const flag = item as Partial<ThemeQualityFlag>
    if (!flag.code) return []
    return [{
      code: flag.code,
      level: flag.level || 'warning',
      message: flag.message || flag.code,
      ...(flag.count === undefined ? {} : { count: flag.count }),
    }]
  })
}

function unwrapSnapshot(response: any): ThemeHeatApiSnapshot {
  const snapshot = response?.data ?? response
  return {
    computedAt: finite(snapshot?.computedAt),
    cacheBucket: String(snapshot?.cacheBucket || ''),
    factorVersion: String(snapshot?.factorVersion || ''),
    mappingVersion: String(snapshot?.mappingVersion || ''),
    factors: Array.isArray(snapshot?.factors) ? snapshot.factors : [],
    quality: snapshot?.quality && typeof snapshot.quality === 'object' ? snapshot.quality : {},
    sources: snapshot?.sources && typeof snapshot.sources === 'object' ? snapshot.sources : {},
  }
}

function toRuntimeFactor(factor: ThemeHeatApiFactor, computedAt: number): ThemeFactorSnapshot {
  const heatScore = finite(factor.heatScore)
  const fundScore = nullableFinite(factor.fundScore)
  const netInflow = nullableFinite(factor.netInflow ?? (factor as any).mainNetInflow)
  return {
    themeId: String(factor.themeId || ''),
    themeName: String(factor.themeName || factor.themeId || ''),
    source: 'market_aggregate',
    snapshotId: factor.snapshotId,
    timestamp: finite(factor.timestamp, computedAt),
    heatScore,
    heatLevel: nullableFinite(factor.heatLevel),
    momentumScore: finite(factor.momentumScore),
    breadthScore: finite(factor.breadthScore),
    fundScore,
    leadershipScore: finite(factor.leadershipScore),
    correlationScore: finite(factor.correlationScore),
    crowdingRisk: finite(factor.crowdingRisk),
    persistenceScore: finite(factor.persistenceScore),
    rotationState: factor.rotationState || 'neutral',
    stockCount: finite(factor.stockCount),
    ztCount: finite(factor.ztCount),
    leaderCount: finite(factor.leaderCount),
    netInflow,
    strength: finite(factor.strength, heatScore),
    volumeRatio: finite(factor.volumeRatio),
    rank: finite(factor.rank),
    relatedThemeIds: Array.isArray(factor.relatedThemeIds) ? factor.relatedThemeIds : [],
    qualityFlags: normalizeFlags(factor.qualityFlags),
    components: {
      breadthScore: finite(factor.breadthScore),
      fundScore,
      leadershipScore: finite(factor.leadershipScore),
      correlationScore: finite(factor.correlationScore),
      riskPenalty: Math.min(14, finite(factor.crowdingRisk) * 0.14),
    },
  }
}

function normalizeStock(item: any): ThemeHeatStock {
  const role = STOCK_ROLES.has(item?.role) ? item.role : 'follower'
  return {
    code: String(item?.code || ''),
    name: String(item?.name || item?.code || ''),
    change: finite(item?.change),
    price: finite(item?.price),
    volumeRatio: nullableFinite(item?.volumeRatio),
    mainNetInflow: nullableFinite(item?.mainNetInflow),
    turnoverRate: nullableFinite(item?.turnoverRate),
    rank: finite(item?.rank),
    role,
    qualityFlags: normalizeFlags(item?.qualityFlags),
  }
}

export class ThemeHeatFeed {
  private snapshot: StoredSnapshot | null = null
  private refreshPromise: Promise<ThemeHeatApiSnapshot> | null = null
  private stockPromises = new Map<string, Promise<ThemeHeatStock[]>>()

  // 2026-08-14 用户确认：题材资金统一用 akshare 估算口径（走 HTTP 5 分钟全量刷新），
  // 不再订阅 fund-stream 的 L2 资金补丁（否则 L2 会覆盖题材热榜股票的估算值，口径混杂）。
  constructor(private readonly api: ThemeHeatApiClient = apiService) {}

  refresh(options: { force?: boolean } = {}): Promise<ThemeHeatApiSnapshot> {
    const cacheKey = 'theme-heat-snapshot'
    if (!options.force) {
      const cached = themeHeatSnapshotCache.get(cacheKey) as ThemeHeatApiSnapshot | null
      if (cached) {
        this.snapshot = { ...cached, stale: false, lastError: null }
        return Promise.resolve(cached)
      }
    }
    if (this.refreshPromise) return this.refreshPromise
    this.refreshPromise = (async () => {
      try {
        const next = unwrapSnapshot(await this.api.getThemeHeat({ force: options.force }))
        this.snapshot = { ...next, stale: false, lastError: null }
        themeHeatSnapshotCache.setWithType(cacheKey, next, 'themeHeat')
        return next
      } catch (error) {
        const body = error instanceof ApiHttpError ? error.body as any : null
        const stale = body?.staleData ? unwrapSnapshot(body.staleData) : this.snapshot
        if (stale) {
          this.snapshot = {
            ...stale,
            stale: true,
            lastError: error instanceof Error ? error.message : String(error),
          }
        }
        throw error
      } finally {
        this.refreshPromise = null
      }
    })()
    return this.refreshPromise
  }

  getSnapshot(): StoredSnapshot | null {
    return this.snapshot
  }

  getRuntimeFactors(): ThemeFactorSnapshot[] {
    if (!this.snapshot) return []
    return this.snapshot.factors
      .filter((factor) => factor.rankEligible && Number.isFinite(factor.heatScore))
      .map((factor) => toRuntimeFactor(factor, this.snapshot!.computedAt))
  }

  async loadThemeStocks(
    themeId: string,
    options: { force?: boolean; limit?: number } = {},
  ): Promise<ThemeHeatStock[]> {
    const cacheKey = `theme:${themeId}:${options.limit || 80}`
    if (!options.force) {
      const cached = themeHeatStocksCache.get(cacheKey) as ThemeHeatStock[] | null
      if (cached) return cached
    }
    if (!options.force && this.stockPromises.has(cacheKey)) return this.stockPromises.get(cacheKey)!
    const promise = (async () => {
      try {
        const response = await this.api.getThemeHeatStocks(themeId, { limit: options.limit || 80 })
        const rows = Array.isArray(response?.data?.stocks) ? response.data.stocks : []
        const stocks = rows.map(normalizeStock).filter((stock: ThemeHeatStock) => stock.code)
        themeHeatStocksCache.setWithType(cacheKey, stocks, 'themeHeatStocks')
        return stocks
      } finally {
        this.stockPromises.delete(cacheKey)
      }
    })()
    this.stockPromises.set(cacheKey, promise)
    return promise
  }

  clear(): void {
    this.snapshot = null
    this.refreshPromise = null
    this.stockPromises.clear()
    themeHeatSnapshotCache.clear()
    themeHeatStocksCache.clear()
  }

  destroy(): void {
    this.clear()
  }
}

export const themeHeatFeed = new ThemeHeatFeed()
