import { apiService } from '../apiService'
import type { DataLoaderRunSummary } from './types'

const STARTUP_BUNDLE_SCHEMA_VERSION = 1
const STARTUP_BUNDLE_KEY = 'default'
const MAX_BUNDLE_AGE_MS = 30 * 60 * 1000

export interface StartupBundle {
  schemaVersion: number
  tradingDate: string
  createdAt: number
  platformData: Record<string, any[]>
  stocks: any[]
  summary?: DataLoaderRunSummary
  cacheMeta?: {
    stale?: boolean
  }
}

function getLocalTradingDate(date = new Date()): string {
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function buildCacheKey(date = new Date()): string {
  return `${STARTUP_BUNDLE_KEY}:${getLocalTradingDate(date)}`
}

function isValidBundle(bundle: unknown, now = Date.now()): bundle is StartupBundle {
  const candidate = bundle as StartupBundle
  if (!candidate || typeof candidate !== 'object') return false
  if (Number(candidate.schemaVersion) !== STARTUP_BUNDLE_SCHEMA_VERSION) return false
  if (candidate.tradingDate !== getLocalTradingDate(new Date(now))) return false
  if (!Array.isArray(candidate.stocks) || !candidate.stocks.length) return false
  if (!candidate.platformData || typeof candidate.platformData !== 'object') return false
  if (Array.isArray(candidate.platformData)) return false
  const ageMs = now - Number(candidate.createdAt || 0)
  return Number.isFinite(ageMs) && ageMs >= 0 && ageMs <= MAX_BUNDLE_AGE_MS
}

class StartupBundleService {
  async read(): Promise<StartupBundle | null> {
    try {
      const response = await apiService.get<any>(
        `/api/cache/startup-bundle?key=${encodeURIComponent(buildCacheKey())}`,
        {
          context: 'platform',
          cache: false,
          retries: 0,
          timeout: 1000,
          silent: true,
        },
      )
      const bundle = response?.data
      if (!isValidBundle(bundle)) return null
      return {
        ...bundle,
        cacheMeta: {
          stale: Boolean(response?.dragonMeta?.cache?.stale),
        },
      }
    } catch {
      return null
    }
  }

  async write(bundle: Omit<StartupBundle, 'schemaVersion' | 'tradingDate' | 'createdAt'>): Promise<void> {
    const payload: StartupBundle = {
      ...bundle,
      schemaVersion: STARTUP_BUNDLE_SCHEMA_VERSION,
      tradingDate: getLocalTradingDate(),
      createdAt: Date.now(),
      cacheMeta: undefined,
    }

    if (!isValidBundle(payload, payload.createdAt)) return

    try {
      await apiService.post(
        '/api/cache/startup-bundle',
        {
          key: buildCacheKey(),
          bundle: payload,
        },
        {
          context: 'platform',
          cache: false,
          retries: 0,
          timeout: 1000,
          silent: true,
        },
      )
    } catch {
      return
    }
  }
}

export const startupBundleService = new StartupBundleService()
