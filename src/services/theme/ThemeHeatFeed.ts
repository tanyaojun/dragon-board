import { ApiHttpError, apiService } from '@/services/apiService'
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
  private stockCache = new Map<string, ThemeHeatStock[]>()
  private stockPromises = new Map<string, Promise<ThemeHeatStock[]>>()

  constructor(private readonly api: ThemeHeatApiClient = apiService) {}

  refresh(options: { force?: boolean } = {}): Promise<ThemeHeatApiSnapshot> {
    if (this.refreshPromise) return this.refreshPromise
    this.refreshPromise = (async () => {
      try {
        const next = unwrapSnapshot(await this.api.getThemeHeat({ force: options.force }))
        this.snapshot = { ...next, stale: false, lastError: null }
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
    const key = `${themeId}:${options.limit || 80}`
    if (!options.force && this.stockCache.has(key)) return this.stockCache.get(key)!
    if (!options.force && this.stockPromises.has(key)) return this.stockPromises.get(key)!
    const promise = (async () => {
      try {
        const response = await this.api.getThemeHeatStocks(themeId, { limit: options.limit || 80 })
        const rows = Array.isArray(response?.data?.stocks) ? response.data.stocks : []
        const stocks = rows.map(normalizeStock).filter((stock: ThemeHeatStock) => stock.code)
        this.stockCache.set(key, stocks)
        return stocks
      } finally {
        this.stockPromises.delete(key)
      }
    })()
    this.stockPromises.set(key, promise)
    return promise
  }

  clear(): void {
    this.snapshot = null
    this.refreshPromise = null
    this.stockCache.clear()
    this.stockPromises.clear()
  }
}

export const themeHeatFeed = new ThemeHeatFeed()
