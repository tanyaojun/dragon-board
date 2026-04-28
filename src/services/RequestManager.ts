import { debugLog } from '@/utils/logger'
// src/services/requestManager.ts
// 修复版：修正 fetchWithRetry 方法签名

// ========== 限流配置 ==========
const RATE_LIMIT = {
  DAILY_LIMIT: 3000,
  BURST_LIMIT: 100,
  MIN_INTERVAL: 200,
  MAX_BATCH_SIZE: 100,
  BATCH_SPLIT_SIZE: 50,
}

// ========== 令牌桶 ==========
class TokenBucket {
  private tokens: number
  private lastFill: number
  private capacity: number
  private fillRate: number

  constructor(capacity: number, fillRate: number) {
    this.capacity = capacity
    this.fillRate = fillRate
    this.tokens = capacity
    this.lastFill = Date.now()
  }

  private fill() {
    const now = Date.now()
    const delta = (now - this.lastFill) / 1000
    const newTokens = Math.floor(delta * this.fillRate)
    if (newTokens > 0) {
      this.tokens = Math.min(this.capacity, this.tokens + newTokens)
      this.lastFill = now
    }
  }

  tryTake(amount = 1): boolean {
    this.fill()
    if (this.tokens >= amount) {
      this.tokens -= amount
      return true
    }
    return false
  }

  async take(amount = 1, timeout = 5000): Promise<boolean> {
    this.fill()
    if (this.tokens >= amount) {
      this.tokens -= amount
      return true
    }

    const needed = amount - this.tokens
    const waitTime = (needed / this.fillRate) * 1000

    if (waitTime > timeout) {
      throw new Error('等待令牌超时')
    }

    await new Promise((resolve) => setTimeout(resolve, waitTime))
    this.tokens = 0
    this.lastFill = Date.now()
    return true
  }
}

// ========== 请求管理器 ==========
class RequestManager {
  private requestCount = 0
  private minuteCount = 0
  private minuteStart = Date.now()
  private lastResetDate: string | null = null
  private rejectedCount = 0
  private throttledCount = 0
  private cacheHits = 0

  private cache = new Map<string, { data: any; timestamp: number }>()
  private pendingRequests = new Map<string, Promise<any>>()
  private readonly CACHE_TTL = 3000 // 3秒

  private concurrency = {
    max: 3,
    current: 0,
  }
  private queue: (() => void)[] = []

  // AbortController 管理
  private abortControllers: Map<string, AbortController> = new Map()
  private requestKeys: Map<string, string> = new Map() // code -> requestKey

  // 令牌桶
  buckets = {
    high: new TokenBucket(100, 20),
    medium: new TokenBucket(50, 10),
    low: new TokenBucket(20, 5),
  }

  private getPriority(context: string): 'high' | 'medium' | 'low' {
    const priorityMap: Record<string, 'high' | 'medium' | 'low'> = {
      leaderboard: 'high',
      smart_update: 'high',
      batch_analysis: 'medium',
      theme_panel: 'low',
      stock_quotes: 'medium',
      sector_high: 'high',
      sector_medium: 'medium',
      sector_low: 'low',
      api: 'medium', // 添加默认优先级
    }
    return priorityMap[context] || 'medium'
  }

  private resetDaily() {
    const today = new Date().toDateString()
    if (this.lastResetDate !== today) {
      this.requestCount = 0
      this.minuteCount = 0
      this.minuteStart = Date.now()
      this.lastResetDate = today
      this.rejectedCount = 0
      this.throttledCount = 0
    }
  }

  private async acquireSlot(): Promise<void> {
    if (this.concurrency.current >= this.concurrency.max) {
      await new Promise<void>((resolve) => this.queue.push(resolve))
    }
    this.concurrency.current++
  }

  private releaseSlot(): void {
    this.concurrency.current--
    if (this.queue.length > 0) {
      const next = this.queue.shift()
      setTimeout(next!, 100)
    }
  }

  private updateMinuteStats(): void {
    const now = Date.now()
    if (now - this.minuteStart > 60000) {
      this.minuteCount = 1
      this.minuteStart = now
    } else {
      this.minuteCount++
      if (this.minuteCount > RATE_LIMIT.BURST_LIMIT) {
        console.warn('[RequestManager] 分钟请求数超限')
      }
    }
  }

  // ===== 支持取消的请求方法 =====
  async fetchWithCancel(
    url: string,
    options: any = {},
    retryCount = 3,
    fetchOptions?: RequestInit, // 新增：外部传入的 fetch 选项
  ): Promise<any> {
    const {
      context = 'batch_analysis',
      skipQuota = false,
      requestId, // 请求ID，用于取消
      ...fetchOptionsFromOptions
    } = options

    const requestKey = `${url}_${JSON.stringify(fetchOptionsFromOptions)}_${requestId || ''}`

    // 检查缓存
    const cached = this.cache.get(requestKey)
    if (cached && Date.now() - cached.timestamp < this.CACHE_TTL) {
      this.cacheHits++
      return cached.data
    }

    // 请求去重
    if (this.pendingRequests.has(requestKey)) {
      return this.pendingRequests.get(requestKey)
    }

    // 检查每日限额
    this.resetDaily()
    if (this.requestCount >= RATE_LIMIT.DAILY_LIMIT) {
      this.rejectedCount++
      throw new Error('每日请求限额已用完')
    }

    /**
    const isEastMoney = url.includes('eastmoney.com') || url.includes('push2')

    // 获取令牌
    if (isEastMoney) {
      const priority = this.getPriority(context)
      const bucket = this.buckets[priority]
      await bucket.take(1, 5000)
    }
    */

    // 执行请求（支持取消）
    const request = this.executeWithCancel(
      url,
      fetchOptionsFromOptions,
      retryCount,
      fetchOptions?.signal ?? undefined, // 传递外部 signal
      requestId,
    )
    this.pendingRequests.set(requestKey, request)

    try {
      const result = await request

      // 更新统计
      this.requestCount++
      this.updateMinuteStats()

      // 写入缓存
      if (result) {
        this.cache.set(requestKey, { data: result, timestamp: Date.now() })

        // 清理过期缓存
        if (this.cache.size > 500) {
          const keys = Array.from(this.cache.keys())
          for (let i = 0; i < keys.length - 400; i++) {
            this.cache.delete(keys[i])
          }
        }
      }

      return result
    } finally {
      this.pendingRequests.delete(requestKey)
      // 清理 AbortController
      if (requestId) {
        this.abortControllers.delete(requestId)
        this.requestKeys.delete(requestId)
      }
    }
  }

  // ===== 支持取消的执行方法 =====
  private async executeWithCancel(
    url: string,
    options: any,
    retryCount: number,
    externalSignal?: AbortSignal,
    requestId?: string,
  ): Promise<any> {
    let lastError: Error

    for (let i = 0; i <= retryCount; i++) {
      // 检查是否已被取消
      if (externalSignal?.aborted) {
        throw new DOMException('请求已被取消', 'AbortError')
      }

      try {
        await this.acquireSlot()

        // 创建 AbortController
        const controller = new AbortController()
        const timeoutId = setTimeout(() => controller.abort(), 10000)

        // 如果传入了 requestId，保存 controller
        if (requestId) {
          this.abortControllers.set(requestId, controller)
          this.requestKeys.set(requestId, url)
        }

        // 组合信号：外部信号 + 内部超时信号
        const signals: AbortSignal[] = [controller.signal]
        if (externalSignal) {
          signals.push(externalSignal)
        }

        // 创建复合信号
        const combinedController = new AbortController()
        const onAbort = () => combinedController.abort()

        signals.forEach((signal) => {
          if (signal.aborted) {
            combinedController.abort()
          } else {
            signal.addEventListener('abort', onAbort, { once: true })
          }
        })

        const response = await fetch(url, {
          ...options,
          signal: combinedController.signal,
          headers: {
            Accept: 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            Referer: 'https://quote.eastmoney.com/',
            ...options.headers,
          },
        })

        clearTimeout(timeoutId)

        // 清理事件监听
        signals.forEach((signal) => {
          signal.removeEventListener('abort', onAbort)
        })

        this.releaseSlot()

        // 检查是否已被取消
        if (externalSignal?.aborted) {
          throw new DOMException('请求已被取消', 'AbortError')
        }

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        return await response.json()
      } catch (error: any) {
        this.releaseSlot()

        // 如果是取消错误，直接抛出
        if (error.name === 'AbortError') {
          throw error
        }

        if (i < retryCount) {
          const delay = Math.min(Math.pow(2, i) * 1000, 10000)
          await new Promise((resolve) => setTimeout(resolve, delay))
        } else {
          throw error
        }
      }
    }
  }

  // ===== 兼容旧代码的 fetchWithRetry 方法 =====
  async fetchWithRetry(
    url: string,
    options: any = {},
    retryCount = 3,
    fetchOptions?: RequestInit, // ✅ 新增 fetchOptions 参数
  ): Promise<any> {
    return this.fetchWithCancel(url, options, retryCount, fetchOptions)
  }

  // ===== 取消指定请求 =====
  cancelRequest(requestId: string): boolean {
    const controller = this.abortControllers.get(requestId)
    if (controller) {
      controller.abort()
      this.abortControllers.delete(requestId)
      this.requestKeys.delete(requestId)
      debugLog(`[RequestManager] 已取消请求: ${requestId}`)
      return true
    }
    return false
  }

  // ===== 按代码取消请求 =====
  cancelByCode(code: string): boolean {
    for (const [requestId, url] of this.requestKeys.entries()) {
      if (url.includes(code)) {
        return this.cancelRequest(requestId)
      }
    }
    return false
  }

  // ===== 取消所有请求 =====
  cancelAll(): void {
    this.abortControllers.forEach((controller) => controller.abort())
    this.abortControllers.clear()
    this.requestKeys.clear()
    debugLog('[RequestManager] 已取消所有请求')
  }

  // ===== 按上下文取消 =====
  cancelByContext(context: string): number {
    let count = 0
    const prefix = `sector_${context}`

    for (const [requestId, controller] of this.abortControllers.entries()) {
      if (requestId.startsWith(prefix)) {
        controller.abort()
        this.abortControllers.delete(requestId)
        this.requestKeys.delete(requestId)
        count++
      }
    }

    if (count > 0) {
      debugLog(`[RequestManager] 已取消 ${count} 个 ${context} 请求`)
    }
    return count
  }

  getStats() {
    this.resetDaily()
    return {
      requestCount: this.requestCount,
      dailyLimit: RATE_LIMIT.DAILY_LIMIT,
      remaining: RATE_LIMIT.DAILY_LIMIT - this.requestCount,
      minuteCount: this.minuteCount,
      minuteLimit: RATE_LIMIT.BURST_LIMIT,
      rejectedCount: this.rejectedCount,
      throttledCount: this.throttledCount,
      cacheHits: this.cacheHits,
      cacheSize: this.cache.size,
      pendingRequests: this.pendingRequests.size,
      concurrency: this.concurrency.current,
      queueLength: this.queue.length,
      activeCancellable: this.abortControllers.size,
    }
  }

  clearCache() {
    this.cache.clear()
    debugLog('[RequestManager] 🧹 缓存已清除')
  }

  abortAll() {
    this.queue.length = 0
    this.concurrency.current = 0
    this.pendingRequests.clear()
    this.cancelAll()
  }
}

export const requestManager = new RequestManager()
