// src/utils/apiClient.ts
// API客户端工具 - 修复重复导入问题

import { API_ENDPOINTS, API_TIMEOUT, API_RETRY, API_CACHE } from '@/config/api'

import type {
  RequestOptions,
  QuotesParams,
  TdxParams,
  SectorParams,
  ApiResponse,
} from '@/config/api'

/**
 * 简单的内存缓存
 */
class ApiCache {
  private cache = new Map<string, { data: any; timestamp: number; ttl: number }>()

  get(key: string): any | null {
    const item = this.cache.get(key)
    if (!item) return null

    if (Date.now() - item.timestamp > item.ttl) {
      this.cache.delete(key)
      return null
    }

    return item.data
  }

  set(key: string, data: any, ttl: number) {
    // 限制缓存大小
    if (this.cache.size >= API_CACHE.MAX_SIZE) {
      const oldestKey = this.cache.keys().next().value
      if (oldestKey !== undefined) {
        this.cache.delete(oldestKey)
      }
    }

    this.cache.set(key, {
      data,
      timestamp: Date.now(),
      ttl,
    })
  }

  clear() {
    this.cache.clear()
  }

  invalidate(pattern?: RegExp) {
    if (!pattern) {
      this.clear()
      return
    }

    for (const key of this.cache.keys()) {
      if (pattern.test(key)) {
        this.cache.delete(key)
      }
    }
  }
}

const cache = new ApiCache()

/**
 * 延迟函数
 */
const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 生成缓存键
 */
const getCacheKey = (url: string, params?: any): string => {
  if (!params) return url
  return `${url}:${JSON.stringify(params)}`
}

/**
 * 带重试的请求
 */
async function requestWithRetry<T>(
  url: string,
  options: RequestOptions & { method?: string; body?: any } = {},
): Promise<T> {
  const {
    method = 'GET',
    body,
    timeout = API_TIMEOUT.DEFAULT,
    retries = API_RETRY.COUNT,
    signal,
    headers = {},
  } = options

  let lastError: Error
  let waitTime = API_RETRY.DELAY

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeout)

      const fetchOptions: RequestInit = {
        method,
        headers: {
          'Content-Type': 'application/json',
          ...headers,
        },
        signal: signal || controller.signal,
      }

      if (body) {
        fetchOptions.body = JSON.stringify(body)
      }

      const response = await fetch(url, fetchOptions)
      clearTimeout(timeoutId)

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()
      return data as T
    } catch (error) {
      lastError = error as Error

      // 如果是取消请求，不重试
      if (error instanceof Error && error.name === 'AbortError') {
        throw error
      }

      // 最后一次尝试失败，抛出错误
      if (attempt === retries) {
        throw lastError
      }

      // 等待后重试
      await delay(waitTime)
      waitTime *= API_RETRY.BACKOFF
    }
  }

  throw lastError!
}

/**
 * API客户端
 */
export const apiClient = {
  /**
   * GET请求
   */
  async get<T = any>(endpoint: string, options: RequestOptions = {}): Promise<T> {
    const url = endpoint.startsWith('http') ? endpoint : `${API_ENDPOINTS.BASE_URL}${endpoint}`

    // 缓存处理
    if (options.cache !== false) {
      const cacheKey = getCacheKey(url)
      const cached = cache.get(cacheKey)
      if (cached) {
        return cached as T
      }
    }

    const data = await requestWithRetry<T>(url, { ...options, method: 'GET' })

    // 存入缓存
    if (options.cache !== false && options.cacheTTL) {
      const cacheKey = getCacheKey(url)
      cache.set(cacheKey, data, options.cacheTTL)
    }

    return data
  },

  /**
   * POST请求
   */
  async post<T = any>(endpoint: string, body: any, options: RequestOptions = {}): Promise<T> {
    const url = endpoint.startsWith('http') ? endpoint : `${API_ENDPOINTS.BASE_URL}${endpoint}`
    return requestWithRetry<T>(url, { ...options, method: 'POST', body })
  },

  /**
   * 批量获取行情
   */
  async getQuotes(codes: string[], source: 'smart' | 'tencent' | 'eastmoney' | 'sina' = 'smart') {
    const codeStr = Array.isArray(codes) ? codes.join(',') : codes

    let endpoint: string
    switch (source) {
      case 'tencent':
        endpoint = `${API_ENDPOINTS.QUOTES.TENCENT}?codes=${codeStr}`
        break
      case 'eastmoney':
        endpoint = `${API_ENDPOINTS.QUOTES.EASTMONEY}?codes=${codeStr}`
        break
      case 'sina':
        endpoint = `${API_ENDPOINTS.QUOTES.SINA}?codes=${codeStr}`
        break
      case 'smart':
      default:
        endpoint = `${API_ENDPOINTS.QUOTES.SMART}?codes=${codeStr}`
    }

    return this.get(endpoint, {
      timeout: API_TIMEOUT.QUOTE,
      cacheTTL: API_CACHE.TTL.QUOTE,
    })
  },

  /**
   * 获取热门股票
   */
  async getHotStocks(platform: keyof typeof API_ENDPOINTS.HOT_STOCKS) {
    const endpoint = API_ENDPOINTS.HOT_STOCKS[platform]
    return this.get(endpoint, {
      timeout: API_TIMEOUT.HOT,
      cacheTTL: API_CACHE.TTL.HOT,
    })
  },

  /**
   * 获取所有平台热门股票
   */
  async getAllHotStocks() {
    const platforms = Object.keys(API_ENDPOINTS.HOT_STOCKS) as Array<
      keyof typeof API_ENDPOINTS.HOT_STOCKS
    >

    const results = await Promise.allSettled(
      platforms.map(async (platform) => {
        try {
          const data = await this.getHotStocks(platform)
          return { platform, data }
        } catch (error) {
          return { platform, error: error instanceof Error ? error.message : String(error) }
        }
      }),
    )

    return results
      .filter((r): r is PromiseFulfilledResult<any> => r.status === 'fulfilled')
      .map((r) => r.value)
  },

  /**
   * 获取题材详情
   */
  async getThemeDetail(id: string) {
    const endpoint = API_ENDPOINTS.SECTOR.DETAIL(id)
    return this.get(endpoint, {
      timeout: API_TIMEOUT.SECTOR,
      cacheTTL: API_CACHE.TTL.SECTOR,
    })
  },

  /**
   * 调用通达信接口
   */
  async callTdx(entry: string, data: any) {
    const endpoint = API_ENDPOINTS.TDX.PROXY(entry)

    // 根据接口类型决定发送格式
    if (entry === 'HQServ.PBSdstat' || entry === 'CWServ.cfg_fx_dxqx_jyr') {
      // 市场统计和昨日信息用对象格式
      return this.post(endpoint, data, {
        timeout: API_TIMEOUT.TDX,
        cacheTTL: API_CACHE.TTL.TDX,
      })
    } else {
      // 其他接口用数组格式
      return this.post(endpoint, [data], {
        timeout: API_TIMEOUT.TDX,
        cacheTTL: API_CACHE.TTL.TDX,
      })
    }
  },

  /**
   * 获取涨停数据
   */
  async getLimitData(date?: string) {
    const today = date || new Date().toISOString().slice(0, 10).replace(/-/g, '')
    return this.callTdx(API_ENDPOINTS.TDX.ENTRIES.LIMIT_DATA, [
      { PageSize: 1000, Tdate: today, Sort: '2' },
    ])
  },

  /**
   * 获取昨日信息
   */
  async getYesterdayInfo() {
    return this.callTdx(API_ENDPOINTS.TDX.ENTRIES.YESTERDAY_INFO, [{ Sort: '1', PageSize: '1' }])
  },

  /**
   * 获取炸板数据
   */
  async getZhabanData() {
    return this.callTdx(API_ENDPOINTS.TDX.ENTRIES.ZHABAN_DATA, [{ Sort: '3', PageSize: 1000 }])
  },

  /**
   * 获取情绪数据
   */
  async getEmotionData() {
    const today = new Date().toISOString().slice(0, 10).replace(/-/g, '')
    return this.callTdx(API_ENDPOINTS.TDX.ENTRIES.EMOTION_DATA, [
      { StartDate: '20200101', EndDate: today, IsOld: '0' },
    ])
  },

  /**
   * 获取数据源状态
   */
  async getDataSourceStatus() {
    return this.get(API_ENDPOINTS.DATA_SOURCE.STATUS)
  },

  /**
   * 切换数据源
   */
  async switchDataSource(source: string) {
    return this.post(API_ENDPOINTS.DATA_SOURCE.SWITCH, { source })
  },

  /**
   * 健康检查
   */
  async healthCheck() {
    return this.get(API_ENDPOINTS.HEALTH, { cache: false })
  },

  /**
   * 清空缓存
   */
  clearCache() {
    cache.clear()
  },

  /**
   * 按模式失效缓存
   */
  invalidateCache(pattern?: RegExp) {
    cache.invalidate(pattern)
  },
}
