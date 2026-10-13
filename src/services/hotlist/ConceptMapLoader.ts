/**
 * 全市场概念映射加载器：与 tools/YiDongJingLing/Concepts/ConceptMapLoader.cs 行为一致。
 * - 拉取 quant-board /api/concepts/map（服务端后台刷新：首刷返回 refreshing:true 快照，需轮询）；
 * - refreshing/invalid_payload 时重试（默认 13 次 × 15s，可注入加速测试）；
 * - 失败回退 localStorage 缓存（stale 标记）， degraded 错误全程可见；
 * - 合并逻辑：本工具只用服务器概念（.blk 自选股池由 TdxBlockPoolService 承担，同名覆盖语义与 C# 一致地不在 Web 端重复）。
 */

const DEFAULT_ENDPOINT = '/api/concepts/map'
const CACHE_STORAGE_KEY = 'yidongjingling.concept-map-cache.v1'

export interface ConceptSector {
  code: string
  name: string
  changePct: number | null
  stocks: string[]
}

export interface ConceptMapResult {
  sectorToStocks: Map<string, string[]>
  stockToSectors: Map<string, string[]>
  fetchedAt: number | null
  stale: boolean
  errors: string[]
  conceptCount: number
}

export interface ConceptMapLoadOutcome extends ConceptMapResult {
  /** true = 本次成功并已写入缓存。 */
  refreshed: boolean
}

export interface ConceptMapLoaderOptions {
  endpoint?: string
  fetcher?: typeof fetch
  log?: (message: string) => void
  maxAttempts?: number
  retryDelayMs?: number
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
  now?: () => number
}

interface MapPayload {
  ok?: boolean
  refreshing?: boolean
  stale?: boolean
  fetchedAt?: string
  conceptCount?: number
  stockCount?: number
  data?: Array<{ code?: string; name?: string; changePct?: number; stocks?: unknown }>
  errors?: unknown
}

type Fetcher = typeof fetch

export class ConceptMapLoader {
  private readonly endpoint: string
  private readonly fetcher: Fetcher | null
  private readonly log?: (message: string) => void
  private readonly maxAttempts: number
  private readonly retryDelayMs: number
  private readonly storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
  private readonly now: () => number
  private loading: Promise<ConceptMapLoadOutcome> | null = null
  private lastResult: ConceptMapResult = emptyResult()

  constructor(options: ConceptMapLoaderOptions = {}) {
    this.endpoint = options.endpoint || DEFAULT_ENDPOINT
    this.fetcher = options.fetcher === undefined ? defaultFetcher() : options.fetcher
    this.log = options.log
    this.maxAttempts = Math.max(1, options.maxAttempts ?? 13)
    this.retryDelayMs = Math.max(0, options.retryDelayMs ?? 15_000)
    this.storage = options.storage === undefined ? defaultStorage() : options.storage
    this.now = options.now || Date.now
  }

  /** 当前可用映射（可能是旧值）；加载中再次调用会复用同一趟轮询。 */
  getMap(): ConceptMapResult {
    return this.lastResult
  }

  isLoading(): boolean {
    return this.loading !== null
  }

  async load(forceRefresh = false): Promise<ConceptMapLoadOutcome> {
    if (!forceRefresh && this.loading) return this.loading
    const promise = this.loadInternal()
    if (!forceRefresh && !this.lastResult.stale) {
      // 常规路径：记住在途任务供并发调用复用
    }
    this.loading = promise.finally(() => {
      if (this.loading === promise) this.loading = null
    })
    return promise
  }

  private async loadInternal(): Promise<ConceptMapLoadOutcome> {
    const errors: string[] = []
    if (!this.fetcher) {
      return this.serveCache(['concept_map_no_fetcher'], false)
    }

    for (let attempt = 1; attempt <= this.maxAttempts; attempt++) {
      try {
        const response = await this.fetcher(this.endpoint)
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const payload = await response.json() as MapPayload
        const parsed = parseConceptMapPayload(payload)
        if (parsed) {
          const retryable = payload.refreshing === true ||
            parsed.errors.some(item => item.startsWith('invalid_payload'))
          if (!retryable) {
            this.saveCache(payload)
            const result: ConceptMapLoadOutcome = {
              ...parsed,
              refreshed: true,
            }
            this.lastResult = result
            return result
          }
          this.log?.(`概念映射后台刷新中（查询 ${attempt}/${this.maxAttempts}）…`)
          errors.length = 0
          errors.push(...parsed.errors)
        }
      } catch (error) {
        errors.length = 0
        errors.push(`server_unavailable: ${getErrorMessage(error)}`)
        this.log?.(`概念映射请求失败（${attempt}/${this.maxAttempts}）: ${getErrorMessage(error)}`)
      }
      if (attempt < this.maxAttempts && this.retryDelayMs > 0) {
        await delay(this.retryDelayMs)
      }
    }

    return this.serveCache(errors, false)
  }

  private serveCache(errors: string[], refreshed: boolean): ConceptMapLoadOutcome {
    const cached = this.loadCache()
    if (cached) {
      const result: ConceptMapLoadOutcome = {
        ...cached,
        stale: true,
        errors: ['serving_local_cache', ...errors, ...cached.errors],
        refreshed,
      }
      this.lastResult = result
      this.log?.('概念映射服务不可用，已回退本地缓存。')
      return result
    }
    const result: ConceptMapLoadOutcome = {
      ...emptyResult(),
      errors: [...errors],
      refreshed,
    }
    this.lastResult = result
    return result
  }

  private saveCache(payload: MapPayload) {
    if (!this.storage) return
    try {
      this.storage.setItem(CACHE_STORAGE_KEY, JSON.stringify({ savedAt: this.now(), payload }))
    } catch (error) {
      this.log?.(`概念映射缓存写入失败: ${getErrorMessage(error)}`)
    }
  }

  private loadCache(): ConceptMapResult | null {
    if (!this.storage) return null
    try {
      const raw = this.storage.getItem(CACHE_STORAGE_KEY)
      if (!raw) return null
      const wrapper = JSON.parse(raw) as { payload?: MapPayload }
      if (!wrapper?.payload) return null
      const parsed = parseConceptMapPayload(wrapper.payload)
      return parsed ?? null
    } catch {
      try {
        this.storage.removeItem(CACHE_STORAGE_KEY)
      } catch {
        // 缓存自愈失败不阻塞主流程
      }
      return null
    }
  }
}

export function parseConceptMapPayload(payload: MapPayload | null | undefined): ConceptMapResult | null {
  if (!payload || typeof payload !== 'object') return null
  if (payload.ok === false) return null

  const rows = Array.isArray(payload.data) ? payload.data : []
  const sectorToStocks = new Map<string, string[]>()
  const stockToSectors = new Map<string, string[]>()
  const errors: string[] = []

  for (const row of rows) {
    const name = String(row?.name || '').trim()
    const code = String(row?.code || '').trim()
    const stocks = Array.isArray(row?.stocks)
      ? row.stocks
        .map(stock => {
          if (typeof stock === 'string') return stock
          const record = stock as { code?: unknown }
          return String(record?.code || '')
        })
        .map(code => code.trim())
        .filter(Boolean)
      : []
    const key = name || code
    if (!key) continue
    if (!stocks.length) {
      errors.push(`${code || key}: no_valid_members`)
      continue
    }
    sectorToStocks.set(key, stocks)
    for (const stock of stocks) {
      const list = stockToSectors.get(stock)
      if (list) {
        if (!list.includes(key)) list.push(key)
      } else {
        stockToSectors.set(stock, [key])
      }
    }
  }

  if (!sectorToStocks.size) return null

  const fetchedAtMs = payload.fetchedAt ? Date.parse(payload.fetchedAt) : Number.NaN
  return {
    sectorToStocks,
    stockToSectors,
    fetchedAt: Number.isFinite(fetchedAtMs) ? fetchedAtMs : null,
    stale: payload.stale === true,
    errors,
    conceptCount: payload.conceptCount ?? sectorToStocks.size,
  }
}

export function sectorsOf(map: ConceptMapResult, code: string): string[] {
  return map.stockToSectors.get(code) || []
}

function emptyResult(): ConceptMapResult {
  return {
    sectorToStocks: new Map(),
    stockToSectors: new Map(),
    fetchedAt: null,
    stale: false,
    errors: [],
    conceptCount: 0,
  }
}

function defaultFetcher(): Fetcher | null {
  if (typeof globalThis.fetch !== 'function') return null
  return globalThis.fetch.bind(globalThis)
}

function defaultStorage(): Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null {
  try {
    if (typeof localStorage !== 'undefined') return localStorage
  } catch {
    // SSR/隐私模式无 localStorage
  }
  return null
}

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
