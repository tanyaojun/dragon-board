/**
 * 连板上下文加载器：与 tools/YiDongJingLing/MarketData/LimitUpStreakLoader.cs 语义完全一致。
 * 拉取近几个交易日的同花顺涨停池（/api/limitup/10jqka?date=），自算每只股票
 * "截至上一交易日的连续涨停天数"（0 = 昨日未涨停），盘前注入 L1 引擎用于"N连板"命名。
 * 局限可见：候选日按自然日回溯并跳过周末，法定假日会提前终止连板计数（记入 errors）。
 */

const MAX_LOOKBACK_DAYS = 8
const CACHE_KEY_PREFIX = 'yidongjingling.limitup-streaks.'

export interface LimitUpStreakResult {
  streaks: Map<string, number>
  coveredDates: string[]
  errors: string[]
  loadedAt: number
}

export interface LimitUpStreakLoaderOptions {
  endpoint?: string
  fetcher?: typeof fetch
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
  now?: () => number
  log?: (message: string) => void
}

type Fetcher = typeof fetch

export class LimitUpStreakLoader {
  private readonly endpoint: string
  private readonly fetcher: Fetcher | null
  private readonly storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
  private readonly now: () => number
  private readonly log?: (message: string) => void

  constructor(options: LimitUpStreakLoaderOptions = {}) {
    this.endpoint = options.endpoint || '/api/limitup/10jqka'
    this.fetcher = options.fetcher === undefined ? defaultFetcher() : options.fetcher
    this.storage = options.storage === undefined ? defaultStorage() : options.storage
    this.now = options.now || Date.now
    this.log = options.log
  }

  async load(): Promise<LimitUpStreakResult> {
    const today = new Date(this.now())
    const todayText = formatDate(today)
    const cached = this.loadCache(todayText)
    if (cached) return cached

    const errors: string[] = []
    const coveredDates: string[] = []
    const perDateCodes: Array<Set<string>> = []

    // 候选日：今天在前，跳过周末；today 当天数据仅用于确认交易日序列，不参与 streak 基准。
    const candidates: string[] = []
    const cursor = new Date(today.getFullYear(), today.getMonth(), today.getDate())
    while (candidates.length < MAX_LOOKBACK_DAYS) {
      const day = cursor.getDay()
      if (day !== 0 && day !== 6) candidates.push(formatDate(cursor))
      cursor.setDate(cursor.getDate() - 1)
    }

    let isToday = true
    for (const dateText of candidates) {
      let codes: string[]
      try {
        codes = await this.fetchDate(dateText)
      } catch (error) {
        errors.push(`${dateText}: ${getErrorMessage(error)}`)
        break
      }

      if (!codes.length) {
        // 盘前/早盘"今日池为空"是常态：跳过今日继续回溯昨日基准；
        // 非今日候选空池视为非交易日，序列终止并留痕。
        if (isToday) {
          isToday = false
          continue
        }
        errors.push(`${dateText}: empty_pool_treated_as_non_trading_day`)
        break
      }

      coveredDates.push(dateText)
      perDateCodes.push(new Set(codes))
      isToday = false
    }

    // streak 基准：候选[0]=今天（数据不参与计数），其前第一个有数据日为"昨日"（连板第 1 天）。
    const streaks = new Map<string, number>()
    const baseIndex = coveredDates.length > 0 && coveredDates[0] === todayText ? 1 : 0
    for (let dayIndex = baseIndex; dayIndex < perDateCodes.length; dayIndex++) {
      for (const code of perDateCodes[dayIndex]) {
        let streak = 1
        for (let back = dayIndex - 1; back >= baseIndex; back--) {
          if (perDateCodes[back].has(code)) streak++
          else break
        }
        streaks.set(code, Math.max(streaks.get(code) ?? 0, streak))
      }
    }

    const result: LimitUpStreakResult = {
      streaks,
      coveredDates,
      errors,
      loadedAt: this.now(),
    }
    // 空结果（上游异常/基准日缺失）不落缓存，避免当日固化失效数据
    if (streaks.size > 0) this.saveCache(todayText, result)
    return result
  }

  private async fetchDate(dateText: string): Promise<string[]> {
    if (!this.fetcher) throw new Error('no fetcher')
    const response = await this.fetcher(`${this.endpoint}?date=${encodeURIComponent(dateText)}`)
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const payload = await response.json()
    return parseDateResponse(payload)
  }

  private saveCache(todayText: string, result: LimitUpStreakResult) {
    if (!this.storage) return
    try {
      this.storage.setItem(
        CACHE_KEY_PREFIX + todayText,
        JSON.stringify({
          loadedAt: result.loadedAt,
          coveredDates: result.coveredDates,
          streaks: [...result.streaks.entries()],
        }),
      )
    } catch {
      // 缓存写入失败不阻塞
    }
  }

  private loadCache(todayText: string): LimitUpStreakResult | null {
    if (!this.storage) return null
    try {
      const raw = this.storage.getItem(CACHE_KEY_PREFIX + todayText)
      if (!raw) return null
      const wrapper = JSON.parse(raw) as { loadedAt?: number; coveredDates?: string[]; streaks?: [string, number][] }
      if (!wrapper?.loadedAt || !isSameLocalDate(wrapper.loadedAt, this.now())) return null
      return {
        streaks: new Map(wrapper.streaks || []),
        coveredDates: wrapper.coveredDates || [],
        errors: [],
        loadedAt: wrapper.loadedAt,
      }
    } catch {
      try {
        this.storage.removeItem(CACHE_KEY_PREFIX + todayText)
      } catch {
        // 缓存自愈失败不阻塞
      }
      return null
    }
  }
}

/** 同花顺涨停池日期响应解析：data.info[].code（6 位数字）。 */
export function parseDateResponse(payload: unknown): string[] {
  const root = payload as { data?: { info?: unknown } } | null
  const info = root?.data?.info
  if (!Array.isArray(info)) return []

  const codes: string[] = []
  for (const item of info) {
    const code = String((item as { code?: unknown })?.code || '').trim()
    if (/^\d{6}$/.test(code)) codes.push(code)
  }
  return codes
}

function formatDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${date.getFullYear()}-${month}-${day}`
}

function isSameLocalDate(left: number, right: number): boolean {
  const a = new Date(left)
  const b = new Date(right)
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
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

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}
