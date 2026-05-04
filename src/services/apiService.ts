import { debugLog } from '@/utils/logger'
// src/services/apiService.ts
import { API_CONFIG } from '../config/constants'
import type {
  CloudBackupHealth,
  CloudDayBundleUploadResult,
  CloudManifestWindow,
  SnapshotFrameQueryOptions,
  SnapshotQueryOptions,
  SnapshotSectorRowQueryOptions,
  SnapshotStockRowQueryOptions,
  SnapshotDayBundle,
} from './snapshot/types'
// ========== 类型定义 ==========

/** HTTP 方法 */
export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

/** 请求优先级 */
export type RequestPriority = 'high' | 'medium' | 'low'

/** 请求上下文（用于区分不同业务） */
export type RequestContext =
  | 'platform' // 八平台热榜
  | 'quote' // 行情数据
  | 'theme' // 题材数据
  | 'breath' // 情绪数据
  | 'tdx' // 通达信数据
  | 'limitup' // 涨停数据
  | 'market' // 市场概览
  | 'quant-board' // QuantBoard 数据后端
  | 'unknown'

/** 请求配置 */
export interface RequestConfig {
  /** 重试次数，默认2次 */
  retries?: number
  /** 重试延迟（毫秒），默认1000ms */
  retryDelay?: number
  /** 超时时间（毫秒），默认10000ms */
  timeout?: number
  /** 请求优先级 */
  priority?: RequestPriority
  /** 请求上下文（用于监控） */
  context?: RequestContext
  /** 请求ID（用于追踪） */
  requestId?: string
  /** 取消信号 */
  signal?: AbortSignal
  /** 自定义请求头 */
  headers?: Record<string, string>
  /** 是否使用缓存（仅对GET请求有效） */
  cache?: boolean
  /** 缓存过期时间（毫秒） */
  cacheTTL?: number
  /** 响应类型 */
  responseType?: 'json' | 'text' | 'arraybuffer'
  /** 是否静默失败（不打印错误日志） */
  silent?: boolean
  /** 强制刷新（跳过缓存） */
  force?: boolean
  /** HTTP 非 2xx 是否按异常处理 */
  throwOnHttpError?: boolean
}

/** 请求指标 */
interface RequestMetrics {
  url: string
  method: HttpMethod
  context: RequestContext
  startTime: number
  endTime?: number
  duration?: number
  status?: number
  success: boolean
  retryCount: number
  error?: string
  responseSize?: number
}

/** 缓存项 */
interface CacheItem<T> {
  data: T
  timestamp: number
  ttl: number
  etag?: string
}

export interface ApiEnvelope<T> {
  ok: boolean
  requestId?: string
  message?: string
  errorCode?: string
  data: T
  details?: unknown
}

type SqliteSnapshotDatasetOptions = {
  datasetId?: string
  allowedCaptureModes?: SnapshotQueryOptions['allowedCaptureModes']
  excludeRestored?: boolean
}

type SqliteSnapshotRecordQueryOptions = SnapshotQueryOptions & SqliteSnapshotDatasetOptions
type SqliteSnapshotFrameQueryOptions = SnapshotFrameQueryOptions & SqliteSnapshotDatasetOptions
type SqliteSnapshotStockRowQueryOptions = SnapshotStockRowQueryOptions & SqliteSnapshotDatasetOptions
type SqliteSnapshotSectorRowQueryOptions = SnapshotSectorRowQueryOptions & SqliteSnapshotDatasetOptions

export class ApiHttpError extends Error {
  readonly status: number
  readonly statusText: string
  readonly url: string
  readonly method: HttpMethod
  readonly body: unknown
  readonly errorCode?: string
  readonly details?: unknown
  readonly retryable: boolean

  constructor(params: {
    method: HttpMethod
    url: string
    status: number
    statusText: string
    body: unknown
  }) {
    const body = params.body as Record<string, unknown> | null
    const errorCode = typeof body?.errorCode === 'string' ? body.errorCode : undefined
    const message =
      (typeof body?.message === 'string' && body.message) ||
      errorCode ||
      `${params.method} ${params.url} failed with HTTP ${params.status}`
    super(message)
    this.name = 'ApiHttpError'
    this.status = params.status
    this.statusText = params.statusText
    this.url = params.url
    this.method = params.method
    this.body = params.body
    this.errorCode = errorCode
    this.details = body?.details
    this.retryable = params.status === 503 || params.status >= 500
  }
}

// ========== 请求队列（优先级控制） ==========
class RequestQueue {
  private queues: Record<RequestPriority, Array<() => Promise<any>>> = {
    high: [],
    medium: [],
    low: [],
  }
  private processing = false
  private concurrentCount = 0
  private readonly MAX_CONCURRENT = 3

  async add<T>(priority: RequestPriority, task: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      this.queues[priority].push(async () => {
        try {
          const result = await task()
          resolve(result)
        } catch (error) {
          reject(error)
        }
      })
      this.process()
    })
  }

  private async process() {
    if (this.processing) return
    this.processing = true

    while (this.concurrentCount < this.MAX_CONCURRENT && this.hasTasks()) {
      this.concurrentCount++
      this.processNext()
    }
    this.processing = false
  }

  private async processNext() {
    const task = this.getNextTask()
    if (!task) {
      this.concurrentCount--
      return
    }

    try {
      await task()
    } catch (error) {
      console.error('[RequestQueue] 任务执行失败:', error)
    } finally {
      this.concurrentCount--
      this.process()
    }
  }

  private getNextTask(): (() => Promise<any>) | null {
    for (const priority of ['high', 'medium', 'low'] as RequestPriority[]) {
      if (this.queues[priority].length > 0) {
        return this.queues[priority].shift()!
      }
    }
    return null
  }

  private hasTasks(): boolean {
    return Object.values(this.queues).some((q) => q.length > 0)
  }

  clear() {
    this.queues = { high: [], medium: [], low: [] }
  }
}

// ========== 主服务类 ==========
export class ApiService {
  private readonly defaultConfig = API_CONFIG.DEFAULTS
  private readonly contextConfig = API_CONFIG.CONTEXTS
  private readonly proxies = API_CONFIG.PROXIES

  private cache = new Map<string, CacheItem<any>>()
  private queue = new RequestQueue()
  private metrics: RequestMetrics[] = []
  private abortControllers = new Map<string, AbortController>()
  private readonly MAX_METRICS = 1000

  constructor() {
    // 不需要 baseURL 参数，直接从配置读取
  }

  // 根据上下文获取配置
  private getContextConfig(context: RequestContext) {
    switch (context) {
      case 'platform':
        return this.contextConfig.PLATFORM
      case 'quote':
        return this.contextConfig.QUOTE
      case 'theme':
        return this.contextConfig.THEME
      case 'breath':
        return this.contextConfig.BREATH
      case 'tdx':
        return this.contextConfig.TDX
      case 'limitup':
        return this.contextConfig.LIMITUP
      case 'market':
        return this.contextConfig.MARKET
      case 'quant-board':
        return this.contextConfig.QUANT_BOARD
      default:
        return {
          baseURL: this.proxies.PROXY_3000, // 默认用3000
          timeout: API_CONFIG.DEFAULTS.TIMEOUT,
          retries: API_CONFIG.DEFAULTS.RETRIES,
          cacheTTL: API_CONFIG.DEFAULTS.CACHE_TTL,
          priority: 'medium' as const,
        }
    }
  }

  // 合并配置
  private mergeConfig(url: string, options: RequestConfig): RequestConfig & { baseURL: string } {
    const context = options.context || this.inferContext(url)
    const contextConfig = this.getContextConfig(context)

    return {
      baseURL: contextConfig.baseURL || this.proxies.PROXY_3000,
      timeout: options.timeout ?? contextConfig.timeout ?? API_CONFIG.DEFAULTS.TIMEOUT,
      retries: options.retries ?? contextConfig.retries ?? API_CONFIG.DEFAULTS.RETRIES,
      retryDelay: options.retryDelay ?? API_CONFIG.DEFAULTS.RETRY_DELAY,
      cacheTTL: options.cacheTTL ?? contextConfig.cacheTTL ?? API_CONFIG.DEFAULTS.CACHE_TTL,
      priority: options.priority ?? contextConfig.priority ?? 'medium',
      context,
      cache: options.cache ?? true,
      ...options,
    }
  }

  // 推断上下文
  private inferContext(url: string): RequestContext {
    if (
      url.includes('/api/xueqiu') ||
      url.includes('/api/cls') ||
      url.includes('/api/eastmoney') ||
      url.includes('/api/ths') ||
      url.includes('/api/kpl') ||
      url.includes('/api/tgb') ||
      url.includes('/api/dzh')
    ) {
      return 'platform'
    }
    if (url.includes('/api/quotes')) return 'quote'
    if (
      url.includes('/api/theme') ||
      url.includes('/api/get_hot_block') ||
      url.includes('/api/get_block_stock') ||
      url.includes('/api/get_tradeday_list')
    ) {
      return 'theme' // 题材数据统一用 theme 上下文
    }
    if (url.includes('/api/tdx')) return 'tdx'
    if (url.includes('/api/limitup') || url.includes('/api/surge-stock')) return 'limitup'
    if (url.includes('/api/market')) return 'market'
    if (url.includes('/api/snapshots/ingest')) return 'quant-board'
    return 'unknown'
  }

  // ========== 核心请求方法 ==========

  async request<T = any>(
    url: string,
    method: HttpMethod = 'GET',
    data?: any,
    options: RequestConfig = {},
  ): Promise<T> {
    const config = this.mergeConfig(url, options)
    const requestId = config.requestId || this.generateRequestId(url, method)
    const fullUrl = this.buildUrl(url, config.baseURL)
    const startTime = Date.now()
    let retryCount = 0
    let lastError: Error | null = null

    // ✅ 如果 force=true，跳过缓存
    const force = options.force || false
    let finalUrl = fullUrl
    if (force && method === 'GET') {
      const separator = fullUrl.includes('?') ? '&' : '?'
      finalUrl = `${fullUrl}${separator}_t=${Date.now()}`
    }

    // 创建取消控制器
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), config.timeout)
    this.abortControllers.set(requestId, controller)

    // 合并信号
    const signal = config.signal
      ? this.mergeSignals(config.signal, controller.signal)
      : controller.signal

    // 检查缓存（仅对GET请求）
    if (method === 'GET' && config.cache && !force) {
      const cached = this.getFromCache<T>(url, config)
      if (cached) {
        clearTimeout(timeoutId)
        this.abortControllers.delete(requestId)
        return cached
      }
    }

    // 重试循环
    while (retryCount <= (config.retries ?? 2)) {
      try {
        // 通过队列执行（根据优先级）
        const response = await this.queue.add(config.priority ?? 'medium', async () => {
          const fetchOptions: RequestInit = {
            method,
            headers: {
              'Content-Type': 'application/json',
              'X-Request-ID': requestId,
              ...config.headers,
            },
            signal,
          }

          let requestUrl = finalUrl
          if (data) {
            if (method === 'GET') {
              // GET请求将数据转为查询参数
              const params = new URLSearchParams(data).toString()
              requestUrl += (requestUrl.includes('?') ? '&' : '?') + params
            } else {
              fetchOptions.body = JSON.stringify(data)
            }
          }

          const response = await fetch(requestUrl, fetchOptions)
          return response
        })

        clearTimeout(timeoutId)
        const duration = Date.now() - startTime

        // 获取响应大小
        const contentLength = response.headers.get('content-length')
        const responseSize = contentLength ? parseInt(contentLength, 10) : 0

        // 处理响应
        let responseData: T
        if (config.responseType === 'text') {
          responseData = (await response.text()) as T
        } else if (config.responseType === 'arraybuffer') {
          responseData = (await response.arrayBuffer()) as T
        } else {
          responseData = await this.parseJsonResponse<T>(response)
        }

        if (config.throwOnHttpError && !response.ok) {
          throw new ApiHttpError({
            method,
            url,
            status: response.status,
            statusText: response.statusText,
            body: responseData,
          })
        }

        // 记录成功指标
        this.recordMetrics({
          url,
          method,
          context: config.context ?? 'unknown',
          startTime,
          endTime: Date.now(),
          duration,
          status: response.status,
          success: true,
          retryCount,
          responseSize,
        })

        // 存入缓存
        if (method === 'GET' && config.cache) {
          const etag = response.headers.get('etag') || undefined
          this.setCache(url, responseData, config, etag)
        }

        this.abortControllers.delete(requestId)
        return responseData
      } catch (error) {
        lastError = error instanceof Error ? error : new Error(String(error))

        // 如果是取消请求，不重试
        if (error instanceof Error && error.name === 'AbortError') {
          debugLog(`[ApiService] 请求被取消: ${url}`)
          break
        }

        retryCount++

        // 如果还有重试次数，等待后继续
        if (retryCount <= (config.retries ?? 2) && this.shouldRetryRequest(error)) {
          const delay = (config.retryDelay ?? 1000) * Math.pow(2, retryCount - 1)
          debugLog(
            `[ApiService] 请求失败，${delay}ms后重试 (${retryCount}/${config.retries ?? 2}): ${url}`,
          )
          await this.delay(delay)
          continue
        }

        // 最后一次尝试也失败，记录指标
        const duration = Date.now() - startTime
        this.recordMetrics({
          url,
          method,
          context: config.context ?? 'unknown',
          startTime,
          endTime: Date.now(),
          duration,
          success: false,
          retryCount: retryCount - 1,
          error: error instanceof Error ? error.message : String(error),
        })

        if (!config.silent) {
          console.error(`[ApiService] ${method} ${url} 失败:`, error)
        }

        this.abortControllers.delete(requestId)
        throw error
      }
    }

    throw lastError || new Error('请求失败')
  }

  // ========== 便捷方法 ==========

  get<T = any>(url: string, options?: RequestConfig): Promise<T> {
    return this.request<T>(url, 'GET', undefined, options)
  }

  post<T = any>(url: string, data?: any, options?: RequestConfig): Promise<T> {
    return this.request<T>(url, 'POST', data, options)
  }

  put<T = any>(url: string, data?: any, options?: RequestConfig): Promise<T> {
    return this.request<T>(url, 'PUT', data, options)
  }

  delete<T = any>(url: string, options?: RequestConfig): Promise<T> {
    return this.request<T>(url, 'DELETE', undefined, options)
  }

  patch<T = any>(url: string, data?: any, options?: RequestConfig): Promise<T> {
    return this.request<T>(url, 'PATCH', data, options)
  }

  // ========== 业务专用方法 ==========

  /** 获取八平台热榜数据 */
  async getPlatformHot(platform: string, options?: RequestConfig) {
    return this.get(`/api/${platform}/hot`, {
      context: 'platform',
      cache: true,
      cacheTTL: 60000,
      ...options,
    })
  }

  /** 批量获取热榜数据 */
  async getPlatformsHot(platforms: string[], options?: RequestConfig) {
    return Promise.allSettled(platforms.map((p) => this.getPlatformHot(p, options)))
  }

  /**
   * 获取行情数据
   * @param codes 股票代码数组
   * @param options 请求配置，可通过 source 指定数据源
   */
  async getQuotes(
    codes: string[],
    options?: RequestConfig & { source?: 'tencent' | 'eastmoney' | 'sina' },
  ): Promise<any> {
    const source = options?.source || 'tencent'

    // 根据数据源选择不同的 URL
    let url: string
    switch (source) {
      case 'eastmoney':
        url = `/api/quotes/eastmoney?codes=${codes.join(',')}`
        break
      case 'sina':
        url = `/api/quotes/sina?codes=${codes.join(',')}`
        break
      case 'tencent':
      default:
        url = `/api/quotes/tencent?codes=${codes.join(',')}`
        break
    }

    return this.get(url, {
      context: 'quote',
      cache: false,
      priority: 'high',
      ...options,
    })
  }

  /**
   * 批量获取行情数据（自动分组合并）
   * @param codes 股票代码数组
   * @param batchSize 每批数量，默认20
   * @param options 请求配置
   * @param parse 可选的解析函数，用于转换每个item
   */
  async getQuotesBatch(
    codes: string[],
    batchSize = 20,
    options?: RequestConfig,
    parse?: (item: any) => any,
  ): Promise<Map<string, any>> {
    const batches = []
    for (let i = 0; i < codes.length; i += batchSize) {
      batches.push(codes.slice(i, i + batchSize))
    }

    const results = await Promise.allSettled(batches.map((batch) => this.getQuotes(batch, options)))

    const merged = new Map<string, any>()

    results.forEach((result) => {
      if (result.status === 'fulfilled' && result.value?.data?.diff) {
        result.value.data.diff.forEach((item: any) => {
          const parsed = parse ? parse(item) : item
          const code = this.normalizeCode(item.f12 || item.code)
          merged.set(code, parsed)
        })
      } else if (result.status === 'rejected') {
        console.warn('[ApiService] 批量请求失败:', result.reason)
      }
    })

    return merged
  }

  private normalizeCode(code: string): string {
    if (!code) return ''
    return code
      .toString()
      .replace(/[^0-9]/g, '')
      .padStart(6, '0')
  }

  // ========== 🔥 新增：KPL题材数据接口（走5000） ==========

  /** 获取热门板块列表 */
  async getHotBlockList(params: { st?: number; date?: string } = {}, options?: RequestConfig) {
    const query = new URLSearchParams()
    if (params.st) query.append('st', params.st.toString())
    if (params.date) query.append('Date', params.date)

    const endpoint = params.date ? '/api/get_hot_block_list_his' : '/api/get_hot_block_list'

    return this.get(`${endpoint}?${query.toString()}`, {
      context: 'theme',
      cache: !params.date, // 历史数据不缓存
      cacheTTL: 300000,
      ...options,
    })
  }

  /** 获取板块个股列表 */
  async getBlockStockList(
    blockCode: string,
    params: {
      type?: number
      order?: number
      st?: number
      old?: number
      date?: string
    } = {},
    options?: RequestConfig,
  ) {
    const query = new URLSearchParams()
    query.append('bk_code', blockCode)
    if (params.type) query.append('Type', params.type.toString())
    if (params.order) query.append('Order', params.order.toString())
    if (params.st) query.append('st', params.st.toString())
    if (params.old) query.append('old', params.old.toString())
    if (params.date) query.append('Date', params.date)

    const endpoint = params.date ? '/api/get_block_stock_list_his' : '/api/get_block_stock_list'

    return this.get(`${endpoint}?${query.toString()}`, {
      context: 'theme',
      cache: !params.date,
      cacheTTL: 300000,
      ...options,
    })
  }

  /** 获取交易日列表 */
  async getTradeDayList(options?: RequestConfig) {
    return this.get('/api/get_tradeday_list', {
      context: 'theme',
      cache: true,
      cacheTTL: 24 * 60 * 60 * 1000, // 缓存1天
      ...options,
    })
  }

  // ========== 原有接口保留 ==========

  /** 获取题材详情 */
  async getThemeDetail(themeId: string, options?: RequestConfig) {
    return this.get(`/api/theme/${themeId}`, {
      context: 'theme',
      cache: true,
      cacheTTL: 300000,
      ...options,
    })
  }

  /** 批量获取题材数据 */
  async getThemesBatch(themeIds: string[], options?: RequestConfig) {
    return this.post(
      '/api/themes/batch',
      { ids: themeIds },
      {
        context: 'theme',
        cache: true,
        cacheTTL: 300000,
        ...options,
      },
    )
  }

  /** 获取涨停板数据 */
  async getLimitUp(options?: RequestConfig) {
    return this.get('/api/limitup/10jqka', {
      context: 'limitup',
      cache: true,
      cacheTTL: 30000,
      ...options,
    })
  }

  /** 获取昨日涨停表现 */
  async getYesterdayZtPerformance(options?: RequestConfig) {
    return this.get('/api/surge-stock/performance', {
      context: 'breath',
      cache: true,
      cacheTTL: 30000,
      ...options,
    })
  }

  /** 获取市场概览 */
  async getMarketOverview(options?: RequestConfig) {
    return this.get('/api/market/overview', {
      context: 'market',
      cache: true,
      cacheTTL: 10000,
      ...options,
    })
  }

  /** 获取综合情绪数据 */
  async getSentimentComposite(options?: RequestConfig) {
    return this.get('/api/sentiment/composite', {
      context: 'breath',
      cache: true,
      cacheTTL: 30000,
      ...options,
    })
  }

  /** 快照远端健康检查 */
  async getSnapshotRemoteHealth(options?: RequestConfig) {
    return this.get<ApiEnvelope<CloudBackupHealth>>('/api/snapshots/remote/health', {
      context: 'unknown',
      priority: 'low',
      retries: 0,
      timeout: 8000,
      cache: false,
      silent: true,
      ...options,
    })
  }

  /** 快照远端 manifest */
  async listSnapshotRemoteManifest(
    params?: {
      startDate?: string
      endDate?: string
      type?: string
      limit?: number
      cursor?: string
    },
    options?: RequestConfig,
  ) {
    const query = new URLSearchParams()
    if (params?.startDate) query.set('startDate', params.startDate)
    if (params?.endDate) query.set('endDate', params.endDate)
    if (params?.type) query.set('type', params.type)
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.cursor) query.set('cursor', params.cursor)

    return this.get<ApiEnvelope<CloudManifestWindow>>(
      `/api/snapshots/remote/manifest${query.size > 0 ? `?${query.toString()}` : ''}`,
      {
        context: 'unknown',
        priority: 'low',
        retries: 1,
        timeout: 15000,
        cache: false,
        throwOnHttpError: true,
        ...options,
      },
    )
  }

  /** 上传按交易日聚合的远端 bundle */
  async uploadSnapshotRemoteDayBundle(bundle: SnapshotDayBundle, options?: RequestConfig) {
    return this.post<ApiEnvelope<CloudDayBundleUploadResult>>(
      '/api/snapshots/remote/upload-day-bundle',
      bundle,
      {
        context: 'unknown',
        priority: 'low',
        retries: 1,
        timeout: 60000,
        cache: false,
        ...options,
      },
    )
  }

  /** 发送正式快照 bundle 到 QuantBoard 后端 */
  async ingestSnapshotBundle(
    bundle: SnapshotDayBundle,
    options?: RequestConfig & { datasetId?: string; idempotencyKey?: string },
  ) {
    return this.post<any>(
      '/api/snapshots/ingest',
      {
        datasetId: options?.datasetId,
        idempotencyKey: options?.idempotencyKey,
        tradingDate: bundle.tradingDate,
        bundle,
        source: 'dragon_board_runtime',
      },
      {
        context: 'quant-board',
        priority: 'high',
        retries: 1,
        timeout: 15000,
        cache: false,
        throwOnHttpError: true,
        ...options,
      },
    )
  }

  /** 从 QuantBoard SQLite 主库读取正式快照聚合帧 */
  async listSqliteSnapshotFrames(params: SqliteSnapshotFrameQueryOptions = {}, options?: RequestConfig) {
    return this.get<any>(`/api/snapshots/frames${this.buildSqliteSnapshotQuery(params, true)}`, {
      context: 'quant-board',
      priority: 'high',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 从 QuantBoard SQLite 主库读取正式快照记录 */
  async listSqliteSnapshotRecords(params: SqliteSnapshotRecordQueryOptions = {}, options?: RequestConfig) {
    return this.get<any>(`/api/snapshots/records${this.buildSqliteSnapshotQuery(params)}`, {
      context: 'quant-board',
      priority: 'high',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 从 QuantBoard SQLite 主库按 id 读取正式快照记录 */
  async getSqliteSnapshotRecord(
    snapshotId: string,
    params: SqliteSnapshotDatasetOptions = {},
    options?: RequestConfig,
  ) {
    const query = this.buildSqliteSnapshotQuery(params)
    return this.get<any>(`/api/snapshots/records/${encodeURIComponent(snapshotId)}${query}`, {
      context: 'quant-board',
      priority: 'high',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 从 QuantBoard SQLite 主库读取正式股票投影行 */
  async listSqliteSnapshotStockRows(params: SqliteSnapshotStockRowQueryOptions = {}, options?: RequestConfig) {
    return this.get<any>(`/api/snapshots/stock-rows${this.buildSqliteSnapshotQuery(params)}`, {
      context: 'quant-board',
      priority: 'high',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 从 QuantBoard SQLite 主库读取正式题材投影行 */
  async listSqliteSnapshotSectorRows(params: SqliteSnapshotSectorRowQueryOptions = {}, options?: RequestConfig) {
    return this.get<any>(`/api/snapshots/sector-rows${this.buildSqliteSnapshotQuery(params)}`, {
      context: 'quant-board',
      priority: 'high',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 从 QuantBoard SQLite 主库读取快照事实表行数 */
  async getSqliteSnapshotCounts(datasetId?: string, options?: RequestConfig) {
    const query = this.buildSqliteSnapshotQuery({ datasetId })
    return this.get<any>(`/api/snapshots/counts${query}`, {
      context: 'quant-board',
      priority: 'medium',
      retries: 1,
      timeout: 15000,
      cache: false,
      throwOnHttpError: true,
      ...options,
    })
  }

  /** 下载远端交易日 bundle */
  async downloadSnapshotRemoteDayBundle(tradingDate: string, options?: RequestConfig) {
    return this.get<ApiEnvelope<SnapshotDayBundle | null>>(
      `/api/snapshots/remote/download-day-bundle/${encodeURIComponent(tradingDate)}`,
      {
        context: 'unknown',
        priority: 'low',
        retries: 1,
        timeout: 15000,
        cache: false,
        ...options,
      },
    )
  }

  /** 调用TDX接口 */
  async callTDX(entry: string, params: any, options?: RequestConfig) {
    return this.post(`/api/tdx/${entry}`, params, {
      context: 'tdx',
      cache: true,
      cacheTTL: 30000,
      ...options,
    })
  }

  // ========== 私有方法 ==========
  private buildUrl(url: string, baseURL: string): string {
    if (url.startsWith('http')) return url
    if (url.startsWith('/')) return `${baseURL}${url}`
    return `${baseURL}/${url}`
  }

  private buildSqliteSnapshotQuery(
    params: (SqliteSnapshotRecordQueryOptions | SqliteSnapshotFrameQueryOptions | SqliteSnapshotStockRowQueryOptions | SqliteSnapshotSectorRowQueryOptions) = {},
    frameEndpoint = false,
  ): string {
    const query = new URLSearchParams()
    const append = (key: string, value: unknown) => {
      if (value === undefined || value === null || value === '') return
      if (Array.isArray(value)) {
        if (value.length > 0) query.set(key, value.join(','))
        return
      }
      query.set(key, String(value))
    }

    append('dataset_id', params.datasetId)
    append(frameEndpoint ? 'snapshot_type' : 'snapshot_type', params.type)
    append('types', params.types)
    append('trading_date', params.tradingDate)
    append('start_date', params.startDate)
    append('end_date', params.endDate)
    append('before_trading_date', params.beforeTradingDate)
    append('allowed_capture_modes', params.allowedCaptureModes)
    append('exclude_restored', params.excludeRestored)
    append('sort', params.sort)
    append('limit', params.limit)

    const stockParams = params as SqliteSnapshotStockRowQueryOptions
    append('snapshot_id', stockParams.snapshotId)
    append('code', stockParams.code)
    append('codes', stockParams.codes)
    append('slot_time', stockParams.slotTime)

    const sectorParams = params as SqliteSnapshotSectorRowQueryOptions
    append('entity_type', sectorParams.entityType)
    append('entity_types', sectorParams.entityTypes)
    append('entity_key', sectorParams.entityKey)
    append('entity_keys', sectorParams.entityKeys)

    return query.size > 0 ? `?${query.toString()}` : ''
  }

  private async parseJsonResponse<T>(response: Response): Promise<T> {
    const text = await response.text()
    if (!text) return null as T
    try {
      return JSON.parse(text) as T
    } catch (error) {
      if (response.ok) throw error
      return {
        ok: false,
        errorCode: 'invalid_json_response',
        message: text,
      } as T
    }
  }

  private shouldRetryRequest(error: unknown): boolean {
    if (error instanceof ApiHttpError) return error.retryable
    return true
  }

  private generateRequestId(url: string, method: HttpMethod): string {
    return `${method}_${url}_${Date.now()}_${Math.random().toString(36).substring(2, 11)}`
  }

  private mergeSignals(signal1: AbortSignal, signal2: AbortSignal): AbortSignal {
    const controller = new AbortController()

    const onAbort = () => {
      controller.abort()
      signal1.removeEventListener('abort', onAbort)
      signal2.removeEventListener('abort', onAbort)
    }

    signal1.addEventListener('abort', onAbort)
    signal2.addEventListener('abort', onAbort)

    return controller.signal
  }

  private getFromCache<T>(key: string, config: RequestConfig): T | null {
    const cached = this.cache.get(key)
    if (!cached) return null

    // 检查过期
    if (Date.now() - cached.timestamp > cached.ttl) {
      this.cache.delete(key)
      return null
    }

    return cached.data as T
  }

  private setCache(key: string, data: any, config: RequestConfig, etag?: string) {
    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl: config.cacheTTL ?? 300000,
      etag,
    })

    // 限制缓存大小
    if (this.cache.size > 100) {
      const oldestKey = this.cache.keys().next().value
      if (oldestKey) {
        this.cache.delete(oldestKey)
      }
    }
  }

  private recordMetrics(metrics: RequestMetrics) {
    this.metrics.push(metrics)
    if (this.metrics.length > this.MAX_METRICS) {
      this.metrics.shift()
    }

  }

  private delay(ms: number): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, ms))
  }

  // ========== 公共方法 ==========

  /** 取消请求 */
  cancelRequest(requestId: string) {
    const controller = this.abortControllers.get(requestId)
    if (controller) {
      controller.abort()
      this.abortControllers.delete(requestId)
    }
  }

  /** 取消所有请求 */
  cancelAllRequests() {
    this.abortControllers.forEach((controller) => controller.abort())
    this.abortControllers.clear()
  }

  /** 清除缓存 */
  clearCache(pattern?: string) {
    if (pattern) {
      const keys = Array.from(this.cache.keys())
      keys.forEach((key) => {
        if (key.includes(pattern)) {
          this.cache.delete(key)
        }
      })
    } else {
      this.cache.clear()
    }
  }

  /** 获取性能指标 */
  getMetrics(limit = 100): RequestMetrics[] {
    return this.metrics.slice(-limit)
  }

  /** 获取缓存统计 */
  getCacheStats() {
    return {
      size: this.cache.size,
      keys: Array.from(this.cache.keys()),
    }
  }

  /** 获取队列状态 */
  getQueueStatus() {
    return {
      queues: {
        high: this.queue['queues'].high.length,
        medium: this.queue['queues'].medium.length,
        low: this.queue['queues'].low.length,
      },
      concurrentCount: this.queue['concurrentCount'],
    }
  }
}

// ========== 导出单例 ==========
export const apiService = new ApiService()
export const api = apiService

// 挂载到window（用于调试）
if (typeof window !== 'undefined') {
  ;(window as any).apiService = apiService
}
