// src/services/websocket.ts
// AllTick WebSocket 服务（带可配置密钥）

import { ref } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { apiService } from './apiService'
import { dataLayer } from './DataLayer'

// 从环境变量或配置文件读取 token
const ALLTICK_CONFIG = {
  // 优先从环境变量读取，其次是 localStorage，最后是默认值（仅用于开发）
  get token(): string {
    // 尝试从环境变量读取（需要在构建时注入）
    if (typeof process !== 'undefined' && process.env?.VITE_ALLTICK_TOKEN) {
      return process.env.VITE_ALLTICK_TOKEN
    }

    // 尝试从 localStorage 读取（可用于动态更新）
    try {
      const saved = localStorage.getItem('alltick_token')
      if (saved) return saved
    } catch (e) {}

    // 默认值（当前过期的，仅用于开发测试）
    return 'ebe0ff3be9e7ffc4635ac975b5c34dfa-c-app'
  },

  // 更新 token 的方法（可用于界面配置）
  setToken(newToken: string) {
    try {
      localStorage.setItem('alltick_token', newToken)
    } catch (e) {}
  },
}

const ENABLE_WEBSOCKET = false

class WebSocketService {
  private ws: WebSocket | null = null
  private state = ref({
    status: 'disconnected',
    subscribedCount: 0,
  })

  private subscribedCodes = new Set<string>()
  private pendingUpdates = new Map<string, any>()
  private batchTimer: ReturnType<typeof setTimeout> | null = null
  private lastQuotes = new Map<string, any>() // 用于差异比较

  // AllTick 相关属性
  private currentAllTickBatch: string[] = [] // 当前订阅的5只股票
  private currentSubscriptionIndex: number = 0

  // 保存所有事件取消函数
  private unsubscribeFns: (() => void)[] = []

  // 保存所有定时器
  private timers: {
    rotation: ReturnType<typeof setInterval> | null
    batch: ReturnType<typeof setTimeout> | null
    cleanup: ReturnType<typeof setInterval> | null
    storage: ReturnType<typeof setInterval> | null
  } = {
    rotation: null,
    batch: null,
    cleanup: null,
    storage: null,
  }

  // 销毁标志
  private destroyed = false

  // AllTick 重试限制
  private alltickRetryCount = 0
  private readonly ALLTICK_MAX_RETRIES = 3
  private alltickWs: WebSocket | null = null

  // 统计
  private stats = {
    totalPolls: 0,
    successfulPolls: 0,
    failedPolls: 0,
    lastPollTime: 0,
  }

  private lastUpdateTime: number = Date.now()

  // 缓存配置
  private readonly STORAGE_KEY = 'stock_quotes_cache'
  private readonly CACHE_DURATION = 5 * 60 * 1000 // 5分钟
  private readonly MAX_CACHE_SIZE = 1000
  private readonly CLEANUP_INTERVAL = 5 * 60 * 1000 // 5分钟

  // AllTick 配置
  private readonly ALLTICK_WS_URL = 'wss://quote.alltick.co/quote-stock-b-ws-api'
  private alltickSeqId = 1000
  private readonly ALLTICK_MAX_SUBSCRIPTION = 5

  constructor() {
    if (ENABLE_WEBSOCKET) {
      this.init()
      this.startCleanupTimer()
    }
  }

  /**
   * 初始化
   */
  async init(): Promise<void> {
    if (this.destroyed) return

    // 加载缓存
    this.loadFromStorage()

    // 监听数据合并事件，更新订阅列表
    const unsub1 = EventManager.on(AppEvents.DATA.MERGED, () => {
      if (this.destroyed) return
      this.updateSubscriptions()
    })
    this.unsubscribeFns.push(unsub1)

    // 监听增量刷新事件，执行HTTP轮询
    const unsub2 = EventManager.on(AppEvents.REFRESH.INCREMENTAL_REQUESTED, async () => {
      if (this.destroyed) return
      await this.httpPolling()
    })
    this.unsubscribeFns.push(unsub2)

    // 尝试连接 AllTick（带重试限制）
    setTimeout(() => {
      if (this.destroyed) return
      this.tryAllTickConnection()
    }, 1000)

    // 启动定时器
    this.startTimers()
  }

  /**
   * ✅ 新增：供 RefreshManager 调用的维护方法
   */
  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    console.log('[WebSocketService] 执行后台维护')

    // 保存缓存
    this.saveToStorage(this.lastQuotes)

    // 清理过期数据
    this.cleanupOldData()

    // 检查 AllTick 连接状态
    if (!this.alltickWs || this.alltickWs.readyState !== WebSocket.OPEN) {
      if (this.alltickRetryCount < this.ALLTICK_MAX_RETRIES) {
        this.tryAllTickConnection()
      }
    }
  }

  /**
   * ✅ 新增：供 RefreshManager 调用的轮换订阅方法
   */
  async runRotation(): Promise<void> {
    if (this.destroyed) return
    if (!this.alltickWs || this.alltickWs.readyState !== WebSocket.OPEN) return

    console.log('[WebSocketService] 执行AllTick轮换')
    this.rotateAllTickSubscription()
  }

  /**
   * ✅ 修改：移除所有独立定时器
   */
  private startTimers(): void {
    // ❌ 不再启动独立定时器
    return
  }

  private startAllTickRotation() {
    // ❌ 不再启动独立定时器
    return
  }

  private startCleanupTimer() {
    // ❌ 不再启动独立定时器
    return
  }

  // ========== AllTick 方法 ==========

  /**
   * 更新 AllTick Token
   */
  setToken(newToken: string): void {
    ALLTICK_CONFIG.setToken(newToken)
    // 如果当前已连接，重新连接
    if (this.alltickWs) {
      this.alltickWs.close()
      this.alltickWs = null
      this.tryAllTickConnection()
    }
  }

  /**
   * 尝试连接AllTick WebSocket（带重试限制）
   */
  private async tryAllTickConnection(): Promise<boolean> {
    if (this.alltickRetryCount >= this.ALLTICK_MAX_RETRIES) {
      console.log('[AllTick] 达到最大重试次数，停止连接')
      return false
    }

    if (this.alltickWs) return true

    try {
      const token = ALLTICK_CONFIG.token
      const wsUrl = `${this.ALLTICK_WS_URL}?token=${token}`

      this.alltickWs = new WebSocket(wsUrl)

      return new Promise((resolve) => {
        const timeout = setTimeout(() => {
          this.alltickRetryCount++
          this.alltickWs = null
          resolve(false)
        }, 5000)

        this.alltickWs!.onopen = () => {
          clearTimeout(timeout)
          this.alltickRetryCount = 0
          this.sendAllTickSubscription()
          this.startAllTickRotation()
          EventManager.emit('alltick:status-changed', { connected: true })
          resolve(true)
        }

        this.alltickWs!.onerror = () => {
          clearTimeout(timeout)
          this.alltickRetryCount++
          this.alltickWs = null
          resolve(false)
        }

        this.alltickWs!.onmessage = (event) => {
          this.handleAllTickMessage(event)
        }

        this.alltickWs!.onclose = () => {
          this.alltickWs = null
          EventManager.emit('alltick:status-changed', { connected: false })

          // 重试（如果没达到上限）
          if (this.alltickRetryCount < this.ALLTICK_MAX_RETRIES) {
            setTimeout(() => {
              if (!this.destroyed) {
                this.tryAllTickConnection()
              }
            }, 10000)
          }
        }
      })
    } catch (error) {
      this.alltickRetryCount++
      return false
    }
  }

  /**
   * 发送订阅
   */
  private async sendAllTickSubscription() {
    if (!this.alltickWs || this.alltickWs.readyState !== WebSocket.OPEN) return

    const stocks = (window as any).dataLayer?.getStocks() || []

    const hotStocks = stocks
      .map((stock: any) => {
        let score = 0
        if (stock.compRank) score += (100 - stock.compRank) * 2
        if (stock.change > 9.5) score += 100
        if (stock.continuousDays > 1) score += stock.continuousDays * 30
        if (stock.isSectorLeader) score += 80
        if (stock.turnover > 1e8) score += 20
        return { code: stock.code, score }
      })
      .sort((a: any, b: any) => b.score - a.score)
      .slice(0, 5)
      .map((item: any) => item.code)

    if (hotStocks.length === 0) return

    const subscribeMsg = {
      cmd_id: 22004,
      seq_id: ++this.alltickSeqId,
      trace: `trace_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      data: {
        symbol_list: hotStocks.map((code) => ({
          code: code.startsWith('6') ? `${code}.SH` : `${code}.SZ`,
        })),
      },
    }

    try {
      this.alltickWs.send(JSON.stringify(subscribeMsg))
      this.currentAllTickBatch = hotStocks
      EventManager.emit('alltick:subscription-updated', this.currentAllTickBatch)
    } catch (error) {}
  }

  /**
   * 轮换订阅
   */
  private rotateAllTickSubscription() {
    const stocks = (window as any).dataLayer?.getStocks() || []

    const hotStocks = stocks
      .map((stock: any) => {
        let score = 0
        if (stock.compRank) score += (100 - stock.compRank) * 2
        if (stock.change > 9.5) score += 100
        if (stock.continuousDays > 1) score += stock.continuousDays * 30
        if (stock.isSectorLeader) score += 80
        return { code: stock.code, score }
      })
      .sort((a: any, b: any) => b.score - a.score)
      .map((item: any) => item.code)

    const BATCH_SIZE = 5
    const start = this.currentSubscriptionIndex * BATCH_SIZE
    let batchCodes = hotStocks.slice(start, start + BATCH_SIZE)

    if (batchCodes.length === 0) {
      this.currentSubscriptionIndex = 0
      batchCodes = hotStocks.slice(0, BATCH_SIZE)
    }

    this.sendSpecificSubscription(batchCodes)
    this.currentSubscriptionIndex++
    this.currentAllTickBatch = batchCodes
    EventManager.emit('alltick:subscription-updated', this.currentAllTickBatch)
  }

  /**
   * 发送指定代码的订阅
   */
  private sendSpecificSubscription(codes: string[]) {
    if (!this.alltickWs || this.alltickWs.readyState !== WebSocket.OPEN) return
    if (codes.length === 0) return

    const subscribeMsg = {
      cmd_id: 22004,
      seq_id: ++this.alltickSeqId,
      trace: `trace_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`,
      data: {
        symbol_list: codes.map((code) => ({
          code: code.startsWith('6') ? `${code}.SH` : `${code}.SZ`,
        })),
      },
    }

    try {
      this.alltickWs.send(JSON.stringify(subscribeMsg))
    } catch (error) {}
  }

  /**
   * 处理AllTick消息
   */
  private handleAllTickMessage(event: MessageEvent) {
    try {
      const data = JSON.parse(event.data)

      if (data.cmd_id === 22998 && data.data) {
        const tick = data.data
        const fullCode = tick.code || ''
        const code = fullCode.replace(/\..*$/, '').padStart(6, '0')

        this.pendingUpdates.set(code, {
          price: parseFloat(tick.price) || 0,
          volume: parseInt(tick.volume) || 0,
          turnover: parseFloat(tick.turnover) || 0,
          trade_direction: tick.trade_direction,
          tick_time: tick.tick_time,
          source: 'alltick_tick',
          timestamp: Date.now(),
        })

        EventManager.emit('alltick:tick', {
          code,
          name: tick.name,
          price: tick.price,
          volume: tick.volume,
        })

        this.scheduleBatchUpdate()
      }
    } catch (error) {}
  }

  // ========== HTTP 轮询 ==========

  /**
   * 更新订阅列表
   */
  private updateSubscriptions() {
    const stocks = (window as any).dataLayer?.getStocks() || []
    const newCodes = new Set(
      stocks
        .map((s: any) => s.code)
        .filter(Boolean)
        .slice(0, 200),
    )

    this.subscribedCodes = newCodes
    this.state.value.subscribedCount = this.subscribedCodes.size
  }

  /**
   * HTTP轮询执行
   */
  private async httpPolling() {
    try {
      const codes = Array.from(this.subscribedCodes)
      if (codes.length === 0) return

      const BATCH_SIZE = 20
      const batches = []

      for (let i = 0; i < codes.length; i += BATCH_SIZE) {
        batches.push(codes.slice(i, i + BATCH_SIZE))
      }

      for (const batch of batches) {
        try {
          const [quoteRes, spkRes] = await Promise.allSettled([
            apiService.get(`/api/quotes/tencent?codes=${batch.join(',')}`),
            apiService.get(`/api/quotes/tencent/spk?codes=${batch.join(',')}`),
          ])

          const spkMap = new Map()
          if (spkRes.status === 'fulfilled' && spkRes.value?.data?.diff) {
            spkRes.value.data.diff.forEach((item: any) => {
              spkMap.set(item.code, item)
            })
          }

          if (quoteRes.status === 'fulfilled' && quoteRes.value?.data?.diff) {
            quoteRes.value.data.diff.forEach((item: any) => {
              const code = item.f12?.replace(/[^0-9]/g, '').padStart(6, '0')
              if (!code) return

              const spk = spkMap.get(code)

              const price = item.f2 || 0
              const change = item.f3 || 0
              const volume = item.f6 || 0
              const turnover = item.f5 || price * volume * 100 || 0

              let zlje = 0,
                zljzb = 0,
                cddje = 0,
                cddjzb = 0

              if (spk) {
                const netBigRatio = spk.buy_big - spk.sell_big
                zlje = Math.round(turnover * netBigRatio)
                zljzb = Math.round(Math.abs(netBigRatio) * 1000) / 10
                cddje = Math.round(zlje * 0.6)
                cddjzb = Math.round(zljzb * 0.6 * 10) / 10
              }

              this.pendingUpdates.set(code, {
                code,
                name: item.f14 || '',
                price,
                change,
                volume,
                turnover,
                turnoverRate: item.f8 || 0,
                pe: item.f9 || 0,
                pb: item.f23 || 0,
                totalMV: item.f20 || 0,
                cirMV: item.f21 || 0,
                zlje,
                zljzb,
                cddje,
                cddjzb,
                timestamp: Date.now(),
                source: 'http',
              })
            })
          }

          if (batches.length > 1) {
            await new Promise((resolve) => setTimeout(resolve, 200))
          }
        } catch (batchError) {}
      }

      this.stats.successfulPolls++
      this.stats.totalPolls++
      this.stats.lastPollTime = Date.now()

      this.scheduleBatchUpdate()
    } catch (error) {
      this.stats.failedPolls++
      this.stats.totalPolls++
    }
  }

  /**
   * 调度批量更新
   */
  private scheduleBatchUpdate() {
    if (this.destroyed) return

    if (this.timers.batch) {
      clearTimeout(this.timers.batch)
    }

    this.timers.batch = setTimeout(() => {
      if (this.destroyed) return
      this.applyBatchUpdates()
      this.timers.batch = null
    }, 500)
  }

  /**
   * 比较数据变化
   */
  private compareAndGetChanges(newQuotes: Map<string, any>): Map<string, any> {
    const changes = new Map<string, any>()

    newQuotes.forEach((newQuote, code) => {
      const oldQuote = this.lastQuotes.get(code)

      if (!oldQuote) {
        changes.set(code, newQuote)
        this.lastQuotes.set(code, newQuote)
        return
      }

      const changedFields: any = { code, timestamp: Date.now() }
      let hasChanges = false

      const fields = [
        'price',
        'change',
        'turnover',
        'turnoverRate',
        'pe',
        'pb',
        'totalMV',
        'cirMV',
        'zlje',
        'zljzb',
        'cddje',
        'cddjzb',
      ]

      fields.forEach((field) => {
        if (newQuote[field] !== oldQuote[field]) {
          changedFields[field] = newQuote[field]
          hasChanges = true
        }
      })

      if (hasChanges) {
        changes.set(code, changedFields)
        this.lastQuotes.set(code, { ...oldQuote, ...changedFields })
      }
    })
    return changes
  }

  /**
   * 应用批量更新
   */
  private applyBatchUpdates() {
    const changes = this.compareAndGetChanges(this.pendingUpdates)
    if (changes.size === 0) return

    const alltickUpdates: any[] = []
    const httpUpdates: any[] = []

    changes.forEach((update) => {
      if (update.source === 'alltick_tick') {
        alltickUpdates.push(update)
      } else if (update.source === 'http') {
        httpUpdates.push(update)
      }
    })

    if (alltickUpdates.length > 0) {
      dataLayer.updateQuotesBatch(alltickUpdates)
    }

    if (httpUpdates.length > 0) {
      setTimeout(() => {
        if (this.destroyed) return
        dataLayer.updateQuotesBatch(httpUpdates)
        this.saveToStorage(this.lastQuotes)
      }, 2000)
    }

    this.pendingUpdates.clear()
    this.lastUpdateTime = Date.now()
  }

  // ========== 缓存管理 ==========

  private saveToStorage(quotes: Map<string, any>) {
    try {
      const quotesArray = Array.from(quotes.entries()).map(([code, quote]) => [
        code,
        {
          price: quote.price,
          change: quote.change,
          volume: quote.volume,
          turnover: quote.turnover,
          turnoverRate: quote.turnoverRate,
          pe: quote.pe,
          pb: quote.pb,
          totalMV: quote.totalMV,
          cirMV: quote.cirMV,
          zlje: quote.zlje,
          zljzb: quote.zljzb,
          cddje: quote.cddje,
          cddjzb: quote.cddjzb,
          timestamp: quote.timestamp,
        },
      ])

      localStorage.setItem(
        this.STORAGE_KEY,
        JSON.stringify({
          timestamp: Date.now(),
          quotes: quotesArray,
        }),
      )
    } catch (error) {}
  }

  private loadFromStorage() {
    try {
      const cached = localStorage.getItem(this.STORAGE_KEY)
      if (!cached) return

      const data = JSON.parse(cached)
      if (Date.now() - data.timestamp > this.CACHE_DURATION) {
        localStorage.removeItem(this.STORAGE_KEY)
        return
      }

      data.quotes.forEach(([code, quote]: [string, any]) => {
        this.lastQuotes.set(code, quote)
      })
    } catch (error) {}
  }

  private cleanupOldData() {
    const now = Date.now()
    const FIVE_MINUTES = 5 * 60 * 1000

    this.lastQuotes.forEach((quote, code) => {
      if (now - quote.timestamp > FIVE_MINUTES) {
        this.lastQuotes.delete(code)
      }
    })

    if (this.lastQuotes.size > this.MAX_CACHE_SIZE) {
      const entries = Array.from(this.lastQuotes.entries())
      entries.sort((a, b) => a[1].timestamp - b[1].timestamp)
      entries
        .slice(0, entries.length - this.MAX_CACHE_SIZE)
        .forEach(([code]) => this.lastQuotes.delete(code))
    }
  }

  // ========== 公共方法 ==========

  getAllTickSubscribedStocks(): string[] {
    return this.currentAllTickBatch
  }

  isAllTickConnected(): boolean {
    return this.alltickWs?.readyState === WebSocket.OPEN
  }

  getStatus() {
    return {
      status: this.state.value.status,
      subscribedCount: this.state.value.subscribedCount,
    }
  }

  getStats() {
    return {
      subscribedCount: this.subscribedCodes.size,
      pendingUpdates: this.pendingUpdates.size,
    }
  }

  getDetailedStats() {
    return {
      totalPolls: this.stats.totalPolls,
      successfulPolls: this.stats.successfulPolls,
      failedPolls: this.stats.failedPolls,
      successRate:
        this.stats.totalPolls > 0
          ? ((this.stats.successfulPolls / this.stats.totalPolls) * 100).toFixed(1) + '%'
          : '0%',
      subscribedCount: this.subscribedCodes.size,
      pendingUpdates: this.pendingUpdates.size,
      lastPollTime: this.stats.lastPollTime
        ? new Date(this.stats.lastPollTime).toLocaleTimeString()
        : '从未',
      cacheSize: this.lastQuotes.size,
    }
  }

  async pollNow() {
    await this.httpPolling()
  }

  /**
   * 统一销毁方法
   */
  destroy(): void {
    this.destroyed = true

    Object.keys(this.timers).forEach((key) => {
      const timer = this.timers[key as keyof typeof this.timers]
      if (timer) {
        if (key === 'batch') {
          clearTimeout(timer as ReturnType<typeof setTimeout>)
        } else {
          clearInterval(timer as ReturnType<typeof setInterval>)
        }
        this.timers[key as keyof typeof this.timers] = null
      }
    })

    if (this.alltickWs) {
      this.alltickWs.close()
      this.alltickWs = null
    }

    this.unsubscribeFns.forEach((fn) => fn())
    this.unsubscribeFns = []

    this.pendingUpdates.clear()
    this.lastQuotes.clear()
    this.subscribedCodes.clear()
    this.currentAllTickBatch = []
  }
}

export const webSocketService = new WebSocketService()

// 挂载到 window 方便调试
if (typeof window !== 'undefined') {
  ;(window as any).webSocketService = webSocketService
}
