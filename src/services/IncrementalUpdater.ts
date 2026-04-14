// src/services/IncrementalUpdater.ts
// 优化版 v2.6.0 - 改为服务模式，供协调者调用

import type {
  UpdateType,
  UpdateTask,
  UpdateTaskData,
  QueueStats,
  UpdaterStats,
  SlowQueryRecord,
  UpdaterStatus,
} from '@/types'
import { EventManager } from '@/utils/eventManager'
import { dataLayer } from './DataLayer'
import {
  INCREMENTAL_UPDATER_CONFIG,
  REFRESH_STRATEGY_CONFIGS,
  REFRESH_STORAGE_KEY,
  type RefreshConfig,
} from '@/types/config'
import { apiService } from './apiService'
import { AppEvents } from '@/types'
import { quoteCache } from './LRUCache'
import { performanceMonitor } from './performanceMonitor'
import { isTradingTime } from '@/utils/time'
import { RefreshManager } from './RefreshManager'

const UPDATER_CONFIG = INCREMENTAL_UPDATER_CONFIG

/**
 * 增量更新器状态
 */
interface UpdaterState {
  initialized: boolean
  queue: Record<number, Map<string, UpdateTask>>
  queueSize: number
  processing: boolean
  stats: UpdaterStats
  _updating: boolean
  paused: boolean

  // 动态调度相关状态（用于内部优化，不影响调度频率）
  metrics: {
    lastProcessTime: number
    avgProcessTime: number
    queueGrowthRate: number
    lastQueueSize: number
    lastCheckTime: number
    priorityStats: Record<
      number,
      {
        total: number
        avgTime: number
        failRate: number
      }
    >
  }

  // 动态配置（用于内部优化）
  dynamicConfig: {
    batchSize: number
    delayBetweenBatches: number
    priorityMultipliers: Record<number, number>
  }
}

export class IncrementalUpdater {
  private static instance: IncrementalUpdater
  private state: UpdaterState
  private unsubscribeFns: (() => void)[] = []
  private destroyed = false
  private pendingQuotes: Map<string, any> = new Map()
  private pendingChanges: Set<string> = new Set()

  // 性能采样窗口
  private performanceSamples: number[] = []
  private readonly MAX_SAMPLES = 20

  // 热点股票数量
  private hotStocksLimit: number = INCREMENTAL_UPDATER_CONFIG.HOT_STOCKS_LIMIT

  // ✅ 涨停状态缓存
  private lastZTState: Map<string, { isZT: boolean; timestamp: number; change: number }> = new Map()

  // ✅ 防止并发处理行情
  private processingQuotes: Set<string> = new Set()

  // ✅ 题材更新相关
  private sectorUpdateInProgress: boolean = false
  private lastFullSectorUpdate: number = 0

  // ✅ 排名更新相关
  private lastRankUpdate: number = 0

  // ✅ 添加处理中的 Promise
  private processingPromise: Promise<void> | null = null

  private constructor() {
    this.state = {
      initialized: false,
      queue: {
        [UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE]: new Map(),
        [UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE]: new Map(),
        [UPDATER_CONFIG.PRIORITY.DRAGON_FULL]: new Map(),
        [UPDATER_CONFIG.PRIORITY.HTTP_QUOTE]: new Map(),
        [UPDATER_CONFIG.PRIORITY.SECTOR_UPDATE]: new Map(),
        [UPDATER_CONFIG.PRIORITY.BACKGROUND]: new Map(),
      },
      queueSize: 0,
      processing: false,
      stats: this.getDefaultStats(),
      _updating: false,
      paused: true,

      metrics: {
        lastProcessTime: 0,
        avgProcessTime: 100,
        queueGrowthRate: 0,
        lastQueueSize: 0,
        lastCheckTime: Date.now(),
        priorityStats: {},
      },
      dynamicConfig: {
        batchSize: UPDATER_CONFIG.BATCH_SIZE,
        delayBetweenBatches: 100,
        priorityMultipliers: {},
      },
    }

    // 只保留入队的事件监听，去掉主动触发
    this.setupEnqueueListeners()
    this.startMetricsMonitor()
  }

  static getInstance(): IncrementalUpdater {
    if (!IncrementalUpdater.instance) {
      IncrementalUpdater.instance = new IncrementalUpdater()
    }
    return IncrementalUpdater.instance
  }

  /**
   * 从 localStorage 加载热点股票数量
   */
  private loadHotStocksLimit(): number {
    try {
      const saved = localStorage.getItem(REFRESH_STORAGE_KEY)
      if (saved) {
        const config = JSON.parse(saved) as RefreshConfig
        let limit = config.hotStocksLimit

        if (limit === undefined || limit === null) {
          limit =
            REFRESH_STRATEGY_CONFIGS[config.strategy || 'balanced']?.hotStocksLimit ||
            UPDATER_CONFIG.HOT_STOCKS_LIMIT
        }

        if (limit < UPDATER_CONFIG.MIN_HOT_STOCKS_LIMIT) {
          limit = UPDATER_CONFIG.MIN_HOT_STOCKS_LIMIT
        }
        if (limit > UPDATER_CONFIG.MAX_HOT_STOCKS_LIMIT) {
          limit = UPDATER_CONFIG.MAX_HOT_STOCKS_LIMIT
        }

        this.utils.log(`从 localStorage 加载热点股票数量: ${limit}`)
        return limit
      }
    } catch (e) {
      this.utils.warn('加载热点股票数量失败:', e)
    }

    const defaultLimit = UPDATER_CONFIG.HOT_STOCKS_LIMIT
    this.utils.log(`使用默认热点股票数量: ${defaultLimit}`)
    return defaultLimit
  }

  /**
   * 检查是否可以执行更新
   */
  private canUpdate(): boolean {
    if (this.destroyed) return false
    if (this.state.paused) return false

    const status = RefreshManager.getStatus()
    if (!status.enabled) return false
    if (!status.isRunning) return false
    if (status.tradingTimeOnly && !isTradingTime()) return false

    return true
  }

  /**
   * 初始化
   */
  async init(): Promise<boolean> {
    if (this.state.initialized) return true

    this.hotStocksLimit = this.loadHotStocksLimit()
    this.utils.log('📦 初始化增量更新器...')

    const status = RefreshManager.getStatus()
    this.state.paused = !status.enabled || !status.isRunning

    this.state.initialized = true
    this.utils.log('✅ 初始化完成，暂停状态:', this.state.paused)

    return true
  }

  /**
   * 获取默认统计
   */
  private getDefaultStats(): UpdaterStats {
    return {
      totalUpdates: 0,
      totalBatches: 0,
      byType: {
        dragon_change: 0,
        dragon_full: 0,
        ws_quote: 0,
        http_quote: 0,
        sector: 0,
        rank: 0,
        platform: 0,
        algorithm: 0,
      },
      avgProcessTime: '0ms',
      lastUpdateTime: null,
      slowQueries: 0,
    }
  }

  /**
   * 工具函数
   */
  private utils = {
    log: (...args: any[]): void => {
      console.log('[IncrementalUpdater]', ...args)
    },

    warn: (...args: any[]): void => {
      console.warn('[IncrementalUpdater]', ...args)
    },

    error: (...args: any[]): void => {
      console.error('[IncrementalUpdater]', ...args)
    },

    now: (): number => Date.now(),

    delay: (ms: number): Promise<void> => {
      return new Promise((resolve) => setTimeout(resolve, ms))
    },

    measureTime: <T>(fn: () => T): { result: T; duration: number } => {
      const start = performance.now()
      const result = fn()
      const duration = performance.now() - start
      return { result, duration }
    },

    measureTimeAsync: async <T>(fn: () => Promise<T>): Promise<{ result: T; duration: number }> => {
      const start = performance.now()
      const result = await fn()
      const duration = performance.now() - start
      return { result, duration }
    },

    recordSlowQuery: (type: UpdateType, duration: number, code?: string): void => {
      if (UPDATER_CONFIG.MONITOR.ENABLED && duration > UPDATER_CONFIG.MONITOR.SLOW_THRESHOLD) {
        this.state.stats.slowQueries++
        this.utils.warn(`慢查询 [${type}] ${code || ''}: ${duration.toFixed(0)}ms`)
      }
    },

    getQueueStats: (): QueueStats => {
      const byPriority: Record<number, number> = {}
      let total = 0

      Object.entries(this.state.queue).forEach(([priority, map]) => {
        const count = map.size
        byPriority[Number(priority)] = count
        total += count
      })

      return { byPriority, total }
    },

    getPriorityName: (priority: number): string => {
      const names: Record<number, string> = {
        [UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE]: '龙头变化',
        [UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE]: 'WebSocket行情',
        [UPDATER_CONFIG.PRIORITY.DRAGON_FULL]: '龙头全量',
        [UPDATER_CONFIG.PRIORITY.HTTP_QUOTE]: 'HTTP校准',
        [UPDATER_CONFIG.PRIORITY.SECTOR_UPDATE]: '题材更新',
        [UPDATER_CONFIG.PRIORITY.BACKGROUND]: '后台任务',
      }
      return names[priority] || `优先级${priority}`
    },
  }

  // ========== 监控系统（用于内部优化） ==========

  /**
   * 启动指标监控
   */
  private startMetricsMonitor() {
    setInterval(() => {
      if (this.destroyed) return
      this.updateMetrics()
      this.adjustDynamicConfig()
    }, 5000)
  }

  /**
   * 更新性能指标
   */
  private updateMetrics() {
    const now = Date.now()
    const timeDiff = (now - this.state.metrics.lastCheckTime) / 1000

    const currentSize = this.state.queueSize
    const sizeDiff = currentSize - this.state.metrics.lastQueueSize
    this.state.metrics.queueGrowthRate = timeDiff > 0 ? sizeDiff / timeDiff : 0

    this.state.metrics.lastQueueSize = currentSize
    this.state.metrics.lastCheckTime = now
  }

  /**
   * 动态调整配置（只影响内部处理，不影响调度频率）
   */
  private adjustDynamicConfig() {
    if (this.state.queueSize > 200) {
      this.state.dynamicConfig.batchSize = Math.min(50, UPDATER_CONFIG.BATCH_SIZE * 2)
      this.state.dynamicConfig.delayBetweenBatches = 50
    } else if (this.state.queueSize < 50) {
      this.state.dynamicConfig.batchSize = Math.max(10, UPDATER_CONFIG.BATCH_SIZE / 2)
      this.state.dynamicConfig.delayBetweenBatches = 200
    } else {
      this.state.dynamicConfig.batchSize = UPDATER_CONFIG.BATCH_SIZE
      this.state.dynamicConfig.delayBetweenBatches = 100
    }

    if (this.state.metrics.avgProcessTime > 500) {
      this.state.dynamicConfig.batchSize = Math.max(5, this.state.dynamicConfig.batchSize * 0.7)
    } else if (this.state.metrics.avgProcessTime < 100) {
      this.state.dynamicConfig.batchSize = Math.min(50, this.state.dynamicConfig.batchSize * 1.2)
    }

    if (this.state.metrics.queueGrowthRate > 10) {
      this.state.dynamicConfig.priorityMultipliers = {
        [UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE]: 2.0,
        [UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE]: 1.5,
        [UPDATER_CONFIG.PRIORITY.DRAGON_FULL]: 1.2,
      }
    } else {
      this.state.dynamicConfig.priorityMultipliers = {}
    }
  }

  /**
   * 记录处理时间样本
   */
  private recordProcessTime(duration: number) {
    this.performanceSamples.push(duration)
    if (this.performanceSamples.length > this.MAX_SAMPLES) {
      this.performanceSamples.shift()
    }

    const sum = this.performanceSamples.reduce((a, b) => a + b, 0)
    this.state.metrics.avgProcessTime = sum / this.performanceSamples.length

    const alpha = 0.3
    const currentAvg = parseFloat(this.state.stats.avgProcessTime) || 0
    this.state.stats.avgProcessTime =
      (currentAvg * (1 - alpha) + duration * alpha).toFixed(0) + 'ms'
  }

  /**
   * 获取当前应该处理的优先级顺序（动态调整）
   */
  private getPriorityOrder(): number[] {
    const basePriorities = [
      UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE,
      UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE,
      UPDATER_CONFIG.PRIORITY.DRAGON_FULL,
      UPDATER_CONFIG.PRIORITY.HTTP_QUOTE,
      UPDATER_CONFIG.PRIORITY.SECTOR_UPDATE,
      UPDATER_CONFIG.PRIORITY.BACKGROUND,
    ]

    if (this.state.queueSize < 50) {
      return basePriorities
    }

    const queueSizes = basePriorities.map((p) => ({
      priority: p,
      size: this.state.queue[p]?.size || 0,
    }))

    const adjustedPriorities = [...basePriorities]

    queueSizes.forEach(({ priority, size }) => {
      if (size > 20) {
        const currentIndex = adjustedPriorities.indexOf(priority)
        if (currentIndex > 0) {
          adjustedPriorities.splice(currentIndex, 1)
          adjustedPriorities.splice(currentIndex - 1, 0, priority)
        }
      }
    })

    return adjustedPriorities
  }

  /**
   * 获取当前优先级的动态批次大小
   */
  private getBatchSizeForPriority(priority: number): number {
    const baseSize = this.state.dynamicConfig.batchSize
    const multiplier = this.state.dynamicConfig.priorityMultipliers[priority] || 1.0

    if (priority === UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE) {
      return Math.floor(baseSize * 1.5 * multiplier)
    }
    if (priority === UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE) {
      return Math.floor(baseSize * 1.2 * multiplier)
    }

    return Math.floor(baseSize * multiplier)
  }

  // ========== 只保留入队监听器 ==========

  /**
   * 设置只入队的监听器 - 不主动触发处理
   */
  private setupEnqueueListeners() {
    // 监听配置变化
    const unsubConfig = EventManager.on(AppEvents.REFRESH.CHANGED, () => {
      if (this.destroyed) return
      this.hotStocksLimit = this.loadHotStocksLimit()
    })

    // 监听刷新管理器状态变化
    const unsubRefreshStarted = EventManager.on('refresh:started', () => {
      if (this.destroyed) return
      this.state.paused = false
      this.utils.log('▶️ 恢复更新')
    })

    const unsubRefreshStopped = EventManager.on('refresh:stopped', () => {
      if (this.destroyed) return
      this.state.paused = true
      this.utils.log('⏸️ 暂停更新')
    })

    const unsubConfigChanged = EventManager.on('refresh:config-changed', (data: any) => {
      if (this.destroyed) return
      const config = data?.config
      if (config) {
        this.state.paused = !config.enabled || !config.isRunning
        this.utils.log(`配置更新，暂停状态: ${this.state.paused}`)
      }
    })

    // ✅ 以下事件只入队，绝不触发处理
    const unsub1 = EventManager.on(AppEvents.STOCK.QUOTES_UPDATED, (data: any) => {
      if (this.destroyed) return
      if (data?.source === 'websocket' && data?.changes) {
        this.handleWebSocketQuotes(data.changes)
      }
      if (data?.source === 'http' && data?.changes) {
        this.handleHttpQuotes(data.changes)
      }
    })

    const unsub2 = EventManager.on(AppEvents.DRAGON.UPDATED, (data: any) => {
      if (this.destroyed) return
      if (data?.changes) this.handleDragonChanges(data.changes)
      if (data?.leaders) this.handleDragonFullUpdate()
    })

    const unsub3 = EventManager.on(AppEvents.SECTOR.UPDATED, (data: any) => {
      if (this.destroyed) return
      this.handleSectorUpdate(data)
    })

    const unsub4 = EventManager.on(AppEvents.BREATH.UPDATED, (data: any) => {
      if (this.destroyed) return
      this.handleBreathUpdate(data)
    })

    const unsub5 = EventManager.on('favorites-updated', (data: any) => {
      if (this.destroyed) return
      this.handleFavoritesUpdate(data)
    })

    const unsub6 = EventManager.on(AppEvents.ALGORITHM.WEIGHTS_ADJUSTED, (data: any) => {
      if (this.destroyed) return
      this.handleAlgorithmUpdate(data)
    })

    const unsubBigOrder = EventManager.on('big-order:updated', (data: any) => {
      if (this.destroyed) return
      if (data?.code) {
        this.addToQueue(
          data.code,
          {
            type: UPDATER_CONFIG.UPDATE_TYPES.BIG_ORDER,
            data: { code: data.code, timestamp: Date.now() },
          },
          UPDATER_CONFIG.PRIORITY.BIG_ORDER,
        )
      }
    })

    const unsubBigOrderFull = EventManager.on('big-order:full-update', () => {
      if (this.destroyed) return
      this.addToQueue(
        'FULL_BIG_ORDER_UPDATE',
        { type: UPDATER_CONFIG.UPDATE_TYPES.BIG_ORDER_FULL },
        UPDATER_CONFIG.PRIORITY.BIG_ORDER_FULL,
      )
    })

    this.unsubscribeFns.push(
      unsubConfig,
      unsubRefreshStarted,
      unsubRefreshStopped,
      unsubConfigChanged,
      unsub1,
      unsub2,
      unsub3,
      unsub4,
      unsub5,
      unsub6,
      unsubBigOrder,
      unsubBigOrderFull,
    )
  }

  // ========== 供协调者调用的方法 ==========

  /**
   * 运行增量更新 - 供协调者调用
   */
  async runIncrementalUpdate(): Promise<void> {
    if (this.processingPromise) {
      this.utils.log('增量更新正在进行中，等待完成...')
      await this.processingPromise
      return
    }

    this.processingPromise = this.performIncrementalUpdate()
    await this.processingPromise
    this.processingPromise = null
  }

  /**
   * 运行全量更新 - 供协调者调用
   */
  async runFullUpdate(): Promise<void> {
    if (this.processingPromise) {
      this.utils.log('全量更新正在进行中，等待完成...')
      await this.processingPromise
      return
    }

    this.processingPromise = this.performFullUpdate()
    await this.processingPromise
    this.processingPromise = null
  }

  /**
   * 等待处理完成 - 供协调者调用
   */
  async waitForIdle(timeout: number = 10000): Promise<boolean> {
    // 如果已经在处理中，等待处理完成
    if (this.processingPromise) {
      try {
        await Promise.race([
          this.processingPromise,
          new Promise((_, reject) => setTimeout(() => reject(new Error('超时')), timeout)),
        ])
        return true
      } catch {
        return false
      }
    }

    // 检查队列是否为空
    if (this.state.queueSize === 0 && !this.state.processing && !this.state._updating) {
      return true
    }

    // 等待队列处理完成
    return new Promise((resolve) => {
      const startTime = Date.now()
      const checkInterval = setInterval(() => {
        const isIdle = this.state.queueSize === 0 && !this.state.processing && !this.state._updating

        if (isIdle) {
          clearInterval(checkInterval)
          resolve(true)
        } else if (Date.now() - startTime > timeout) {
          clearInterval(checkInterval)
          console.warn('[IncrementalUpdater] waitForIdle 超时')
          resolve(false)
        }
      }, 50)
    })
  }

  /**
   * 设置热点股票数量（兼容 RefreshManager 调用）
   */
  setHotStocksLimit(limit: number): void {
    const oldLimit = this.hotStocksLimit

    if (limit < UPDATER_CONFIG.MIN_HOT_STOCKS_LIMIT) {
      limit = UPDATER_CONFIG.MIN_HOT_STOCKS_LIMIT
    }
    if (limit > UPDATER_CONFIG.MAX_HOT_STOCKS_LIMIT) {
      limit = UPDATER_CONFIG.MAX_HOT_STOCKS_LIMIT
    }

    this.hotStocksLimit = limit

    if (oldLimit !== limit) {
      this.utils.log(`热点股票数量已设置为: ${limit}`)
    }
  }

  /**
   * 同步数据到 DataLayer - 供协调者调用
   */
  async syncData(): Promise<void> {
    this.utils.log('同步数据到 DataLayer')
    // 确保所有待处理的变更都应用到 DataLayer
    if (this.pendingChanges.size > 0) {
      const stocks = dataLayer.getStocks()
      dataLayer.updateStocks([...stocks]) // 触发一次更新
      this.pendingChanges.clear()
    }
  }

  // ========== 核心更新逻辑 ==========

  /**
   * 执行全量更新
   */
  private async performFullUpdate(): Promise<void> {
    if (this.state._updating) return
    if (!this.canUpdate()) {
      this.utils.log('⏸️ 无法执行全量更新：已暂停或不在交易时间')
      return
    }

    this.utils.log('开始执行全量更新')
    this.state._updating = true
    const startTime = performance.now()

    try {
      // 清空队列
      Object.values(this.state.queue).forEach((map) => map.clear())
      this.state.queueSize = 0

      // 重新处理热点股票
      await this.processHotStocks()

      // 处理队列
      await this.processQueue()

      const duration = performance.now() - startTime
      this.utils.log(`全量更新完成，耗时 ${duration.toFixed(0)}ms`)
    } catch (error) {
      this.utils.error('全量更新失败:', error)
      throw error
    } finally {
      this.state._updating = false
    }
  }

  /**
   * 执行增量更新
   */
  private async performIncrementalUpdate(): Promise<void> {
    if (this.state._updating) return
    if (!this.canUpdate()) {
      this.utils.log('⏸️ 无法执行增量更新：已暂停或不在交易时间')
      return
    }

    this.state._updating = true
    const startTime = performance.now()

    try {
      // 处理待处理的实时行情
      await this.processPendingQuotes()

      // 处理热点股票
      await this.processHotStocks()

      // 处理队列
      await this.processQueue()

      const duration = performance.now() - startTime
      this.utils.log(`增量更新完成，耗时 ${duration.toFixed(0)}ms`)
    } catch (error) {
      this.utils.error('增量更新失败:', error)
      throw error
    } finally {
      this.state._updating = false
    }
  }

  // ========== 处理待处理的实时行情 ==========
  private async processPendingQuotes(): Promise<void> {
    const ws = (window as any).webSocketService
    if (!ws?.pendingUpdates?.size) return

    const updates: any[] = []
    ws.pendingUpdates.forEach((value, code) => {
      if (value.source === 'alltick_tick') {
        updates.push({ code, ...value })
        this.pendingChanges.add(code)
      }
    })

    if (updates.length === 0) return

    dataLayer.updateQuotesBatch(updates)

    updates.forEach((update) => {
      this.addToQueue(
        update.code,
        {
          type: UPDATER_CONFIG.UPDATE_TYPES.WEBSOCKET_QUOTE,
          data: {
            code: update.code,
            price: update.price,
            change: update.change,
            volume: update.volume,
            timestamp: update.timestamp,
          },
        },
        UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE,
      )
    })

    ws.pendingUpdates.clear()
  }

  // ========== 处理热点股票（HTTP 校准） ==========
  private async processHotStocks(): Promise<void> {
    const stocks = dataLayer.getStocks()
    if (stocks.length === 0) return

    const hotCodes = stocks
      .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
      .slice(0, this.hotStocksLimit)
      .map((s) => s.code)

    const results = new Map()
    const version = dataLayer.getVersion?.() || { stocks: 0 }
    const versionStr = `${version.stocks || 0}`

    for (let i = 0; i < hotCodes.length; i += 20) {
      const batch = hotCodes.slice(i, i + 20)
      try {
        const cachedResults = new Map()
        const needFetchCodes: string[] = []

        batch.forEach((code) => {
          const cacheKey = `quote:${code}:${versionStr}`
          const cached = quoteCache.get(cacheKey)
          if (cached) {
            cachedResults.set(code, cached)
            if (performanceMonitor) {
              performanceMonitor.recordCacheAccess(true, 0)
            }
          } else {
            needFetchCodes.push(code)
          }
        })

        if (needFetchCodes.length > 0) {
          const response = await apiService
            .get(`/api/quotes/tencent?codes=${needFetchCodes.join(',')}`)
            .catch((err) => {
              this.utils.warn(`HTTP批次失败: ${err.message}`)
              return null
            })

          if (response?.data?.diff) {
            response.data.diff.forEach((item: any) => {
              const code = item.f12?.replace(/[^0-9]/g, '').padStart(6, '0')
              if (code) {
                const quoteData = {
                  price: item.f2 || 0,
                  change: item.f3 || 0,
                  volume: item.f6 || 0,
                  turnover: item.f5 || item.f2 * item.f6 * 100 || 0,
                  turnoverRate: item.f8 || 0,
                  timestamp: Date.now(),
                }
                const cacheKey = `quote:${code}:${versionStr}`
                quoteCache.set(cacheKey, quoteData, 30 * 1000, ['quote', `quote:${code}`])
                cachedResults.set(code, quoteData)
                if (performanceMonitor) {
                  performanceMonitor.recordCacheAccess(false, 0)
                }
              }
            })
          }
        }

        cachedResults.forEach((data, code) => {
          results.set(code, data)
          this.pendingChanges.add(code)
        })
      } catch (error) {
        this.utils.error('HTTP批次失败:', error)
      }

      if (i + 20 < hotCodes.length) {
        await new Promise((r) => setTimeout(r, 200))
      }
    }

    if (results.size > 0) {
      const changes = Array.from(results.entries()).map(([code, data]) => ({
        code,
        ...data,
      }))

      dataLayer.updateQuotesBatch(changes)

      changes.forEach((change) => {
        this.addToQueue(
          change.code,
          {
            type: UPDATER_CONFIG.UPDATE_TYPES.HTTP_QUOTE,
            data: change,
          },
          UPDATER_CONFIG.PRIORITY.HTTP_QUOTE,
        )
      })
    }
  }

  /**
   * 添加任务到队列 - 只入队，绝不触发处理
   */
  private addToQueue(code: string, data: UpdateTaskData, priority: number): void {
    if (this.destroyed || !code) return

    const queue = this.state.queue[priority]
    if (!queue) {
      this.utils.warn(`未知优先级: ${priority}`)
      return
    }

    // 对于涨停变化任务，添加额外检查
    if (data.type === UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE) {
      // 检查是否已经有相同code的任务在队列中
      if (queue.has(code)) {
        const existing = queue.get(code)!
        const existingData = existing.data as any
        const newData = data as any

        // 如果已有任务且时间相近（10秒内），则忽略新任务
        if (existingData.data?.timestamp && newData.data?.timestamp) {
          const timeDiff = Math.abs(newData.data.timestamp - existingData.data.timestamp)
          if (timeDiff < 10000) {
            if (UPDATER_CONFIG.DEBUG) {
              this.utils.log(`⏱️ 忽略重复的涨停变化任务: ${code} (时间差: ${timeDiff}ms)`)
            }
            return
          }
        }
      }

      // 检查所有优先级队列中是否已有相同的任务
      for (const [p, q] of Object.entries(this.state.queue)) {
        if (Number(p) === priority) continue // 已经检查过当前队列

        if (q.has(code)) {
          const existing = q.get(code)!
          if (existing.data.type === UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE) {
            this.utils.log(`⏱️ 在其他优先级队列中发现相同任务: ${code} (优先级: ${p})`)
            return
          }
        }
      }
    }

    // 限制队列最大长度
    const MAX_QUEUE_SIZE = 1000
    if (this.state.queueSize > MAX_QUEUE_SIZE) {
      if (priority >= UPDATER_CONFIG.PRIORITY.SECTOR_UPDATE) {
        if (UPDATER_CONFIG.DEBUG) {
          this.utils.log(`队列已满，丢弃低优先级任务: ${code}`)
        }
        return
      }
    }

    // 合并或添加任务
    if (queue.has(code)) {
      const existing = queue.get(code)!

      // 对于涨停变化任务，不合并，直接更新
      if (data.type === UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE) {
        queue.set(code, {
          code,
          data,
          priority,
          timestamp: this.utils.now(),
          retryCount: 0,
          mergeCount: 0,
        })
      } else {
        existing.data = { ...existing.data, ...data }
        existing.timestamp = this.utils.now()
        existing.mergeCount = (existing.mergeCount || 0) + 1
      }
    } else {
      queue.set(code, {
        code,
        data,
        priority,
        timestamp: this.utils.now(),
        retryCount: 0,
        mergeCount: 0,
      })

      this.state.queueSize++
    }
  }

  /**
   * 处理 WebSocket 实时行情
   */
  private handleWebSocketQuotes(changes: any[]): void {
    if (!changes || changes.length === 0) return

    changes.forEach((change) => {
      this.addToQueue(
        change.code,
        { type: UPDATER_CONFIG.UPDATE_TYPES.WEBSOCKET_QUOTE, data: change },
        UPDATER_CONFIG.PRIORITY.WEBSOCKET_QUOTE,
      )
    })

    this.state.stats.byType.ws_quote += changes.length
    this.state.stats.totalUpdates += changes.length
  }

  /**
   * 处理 HTTP 行情校准
   */
  private handleHttpQuotes(changes: any[]): void {
    if (!changes || changes.length === 0) return

    this.utils.log(`🌐 HTTP行情校准: ${changes.length}只`)

    changes.forEach((change) => {
      this.addToQueue(
        change.code,
        { type: UPDATER_CONFIG.UPDATE_TYPES.HTTP_QUOTE, data: change },
        UPDATER_CONFIG.PRIORITY.HTTP_QUOTE,
      )
    })

    this.state.stats.byType.http_quote += changes.length
    this.state.stats.totalUpdates += changes.length
  }

  /**
   * 处理龙头变化
   */
  private handleDragonChanges(changes: any[]): void {
    if (!changes || changes.length === 0) return

    this.utils.log(`🐲 龙头变化: ${changes.length}个`)

    changes.forEach((change) => {
      if (!change.code) {
        this.utils.warn('龙头变化缺少 code 字段', change)
        return
      }

      this.addToQueue(
        change.code,
        {
          type: UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE,
          data: {
            code: change.code,
            name: change.name,
            type: change.type,
            fromLevel: change.fromLevel,
            toLevel: change.toLevel,
          },
        },
        UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE,
      )
    })

    this.state.stats.byType.dragon_change += changes.length
    this.state.stats.totalUpdates += changes.length
  }

  /**
   * 处理龙头全量更新
   */
  private handleDragonFullUpdate(): void {
    this.utils.log('🐉 龙头全量更新')

    this.addToQueue(
      'FULL_DRAGON_UPDATE',
      { type: UPDATER_CONFIG.UPDATE_TYPES.DRAGON_FULL },
      UPDATER_CONFIG.PRIORITY.DRAGON_FULL,
    )

    this.state.stats.byType.dragon_full++
    this.state.stats.totalUpdates++
  }

  /**
   * 处理题材更新
   */
  private handleSectorUpdate(detail: any): void {
    this.utils.log('📊 题材更新')

    const themeIds = detail?.themeIds || []

    this.addToQueue(
      'SECTOR_UPDATE',
      {
        type: UPDATER_CONFIG.UPDATE_TYPES.SECTOR,
        data: { themeIds, ...detail },
      },
      UPDATER_CONFIG.PRIORITY.SECTOR_UPDATE,
    )

    this.state.stats.byType.sector++
    this.state.stats.totalUpdates++
  }

  /**
   * 调度排名更新
   */
  private scheduleRankUpdate(): void {
    this.utils.log('🏆 排名更新')

    this.addToQueue(
      'FULL_RANK_UPDATE',
      { type: UPDATER_CONFIG.UPDATE_TYPES.RANK },
      UPDATER_CONFIG.PRIORITY.BACKGROUND,
    )

    this.state.stats.byType.rank++
    this.state.stats.totalUpdates++
  }

  private schedulePlatformUpdate(): void {
    this.utils.log('📊 平台排名更新')

    this.addToQueue(
      'FULL_PLATFORM_UPDATE',
      { type: UPDATER_CONFIG.UPDATE_TYPES.PLATFORM },
      UPDATER_CONFIG.PRIORITY.BACKGROUND,
    )

    this.state.stats.byType.platform = (this.state.stats.byType.platform || 0) + 1
    this.state.stats.totalUpdates++
  }

  /**
   * 处理情绪更新
   */
  private handleBreathUpdate(data: any): void {
    if (this.destroyed) return

    // ✅ 添加标志，避免触发新的刷新
    if (this._updating) {
      this.utils.log('⏱️ 正在更新中，跳过情绪更新')
      return
    }

    this.utils.log('🌬️ 情绪更新')

    const stocks = dataLayer.getStocks()
    stocks.forEach((stock) => {
      this.pendingChanges.add(stock.code)
    })

    this.scheduleRankUpdate()
  }

  /**
   * 处理自选股更新
   */
  private handleFavoritesUpdate(data: any): void {
    if (this.destroyed) return
    this.utils.log('⭐ 自选股更新')

    this.triggerRender()
  }

  /**
   * 处理算法权重更新
   */
  private handleAlgorithmUpdate(data: any): void {
    if (this.destroyed) return
    this.utils.log('🧠 算法权重更新')

    this.addToQueue(
      'FULL_DRAGON_UPDATE',
      { type: UPDATER_CONFIG.UPDATE_TYPES.DRAGON_FULL },
      UPDATER_CONFIG.PRIORITY.DRAGON_FULL,
    )
  }

  /**
   * 处理队列 - 只处理，不调度
   */
  private async processQueue(): Promise<void> {
    if (this.destroyed || this.state.processing) return
    if (this.state.paused) {
      this.utils.log('⏸️ 处理队列时发现已暂停')
      return
    }

    this.state.processing = true
    const startTime = performance.now()
    let processedCount = 0
    let totalProcessed = 0

    try {
      const priorities = this.getPriorityOrder()

      for (const priority of priorities) {
        if (this.destroyed) break
        if (this.state.paused) {
          this.utils.log('⏸️ 处理过程中被暂停，停止处理')
          break
        }

        const queue = this.state.queue[priority]
        if (queue.size === 0) continue

        const batchSize = this.getBatchSizeForPriority(priority)
        const actualBatchSize = queue.size > 100 ? batchSize * 2 : batchSize
        const tasks = Array.from(queue.entries()).slice(0, actualBatchSize)

        if (UPDATER_CONFIG.DEBUG && tasks.length > 0) {
          this.utils.log(`处理优先级 ${priority} (批次: ${tasks.length}/${queue.size})`)
        }

        for (const [code, task] of tasks) {
          if (this.destroyed) break
          if (this.state.paused) break

          try {
            const taskStart = performance.now()
            await this.processTask(code, task)
            const taskDuration = performance.now() - taskStart

            if (!this.state.metrics.priorityStats[priority]) {
              this.state.metrics.priorityStats[priority] = { total: 0, avgTime: 0, failRate: 0 }
            }
            const stat = this.state.metrics.priorityStats[priority]
            stat.total++
            stat.avgTime = (stat.avgTime * (stat.total - 1) + taskDuration) / stat.total

            queue.delete(code)
            this.state.queueSize--
            processedCount++
            totalProcessed++
          } catch (error) {
            await this.handleTaskError(code, task, error as Error)

            const stat = this.state.metrics.priorityStats[priority]
            if (stat) {
              stat.failRate = (stat.failRate * stat.total + 1) / (stat.total + 1)
            }
          }

          if (processedCount >= 10) {
            await this.utils.delay(0)
            processedCount = 0
          }
        }

        if (totalProcessed > 0) {
          await this.utils.delay(this.state.dynamicConfig.delayBetweenBatches)
        }
      }
    } catch (error) {
      this.utils.error('处理队列失败:', error)
    } finally {
      this.state.processing = false

      const duration = performance.now() - startTime

      if (totalProcessed > 0) {
        this.recordProcessTime(duration / totalProcessed)

        this.state.stats.totalBatches++
        this.state.metrics.lastProcessTime = duration

        this.utils.log(
          `✅ 批量处理完成: ${totalProcessed}个任务, ` +
            `耗时${duration.toFixed(0)}ms, ` +
            `平均${(duration / totalProcessed).toFixed(0)}ms/任务`,
        )

        EventManager.emit('incremental:queue-processed', {
          taskCount: totalProcessed,
          duration: duration,
          timestamp: Date.now(),
        })
      }
    }
  }

  /**
   * 处理单个任务
   */
  private async processTask(code: string, task: UpdateTask): Promise<void> {
    const startTime = performance.now()

    switch (task.data.type) {
      case UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE:
        await this.processDragonChange(task)
        break

      case UPDATER_CONFIG.UPDATE_TYPES.DRAGON_FULL:
        await this.processDragonFull()
        break

      case UPDATER_CONFIG.UPDATE_TYPES.WEBSOCKET_QUOTE:
      case UPDATER_CONFIG.UPDATE_TYPES.HTTP_QUOTE:
        await this.processQuoteUpdate(task)
        break

      case UPDATER_CONFIG.UPDATE_TYPES.SECTOR:
        await this.processSectorUpdate(task)
        break

      case UPDATER_CONFIG.UPDATE_TYPES.RANK:
        await this.processRankUpdate()
        break

      case UPDATER_CONFIG.UPDATE_TYPES.PLATFORM:
        await this.processPlatformUpdate()
        break

      case UPDATER_CONFIG.UPDATE_TYPES.ALGORITHM:
        await this.processAlgorithmUpdate(task)
        break

      case UPDATER_CONFIG.UPDATE_TYPES.LIFECYCLE:
        if (UPDATER_CONFIG.DEBUG) {
          this.utils.log(`⏱️ 生命周期检查任务: ${code}`)
        }
        break

      case UPDATER_CONFIG.UPDATE_TYPES.BIG_ORDER:
        await this.processBigOrderUpdate(task)
        break

      case UPDATER_CONFIG.UPDATE_TYPES.BIG_ORDER_FULL:
        await this.processBigOrderFullUpdate()
        break

      default:
        this.utils.warn(`未知任务类型: ${(task.data as any).type}`)
    }

    const duration = performance.now() - startTime
    this.utils.recordSlowQuery(task.data.type, duration, code)
  }
  /**
   * 处理平台排名更新
   */
  private async processPlatformUpdate(): Promise<void> {
    this.utils.log('📊 执行平台排名更新')

    const stocks = dataLayer.getStocks()
    if (stocks.length === 0) return

    const dataLoader = (window as any).dataLoader
    if (!dataLoader) return

    const platformData = dataLoader.getPlatformData?.()
    if (!platformData) return

    let updatedCount = 0
    stocks.forEach((stock) => {
      const oldRanks = {
        emRank: stock.emRank,
        thsRank: stock.thsRank,
        kplRank: stock.kplRank,
        tdxRank: stock.tdxRank,
        xqRank: stock.xqRank,
        clsRank: stock.clsRank,
        tgbRank: stock.tgbRank,
        dzhRank: stock.dzhRank,
      }

      const newRanks = dataLoader.getStockRanks?.(stock.code) || {}

      if (JSON.stringify(oldRanks) !== JSON.stringify(newRanks)) {
        Object.assign(stock, newRanks)
        updatedCount++
      }
    })

    this.utils.log(`   └─ 更新 ${updatedCount} 只股票的排名`)
  }

  /**
   * 处理算法更新
   */
  private async processAlgorithmUpdate(task: UpdateTask): Promise<void> {
    this.utils.log('🧠 执行算法更新')

    if (typeof window !== 'undefined' && (window as any).algorithmManager) {
      const algorithmManager = (window as any).algorithmManager

      const stocks = dataLayer.getStocks()
      let updatedCount = 0

      for (const stock of stocks) {
        const oldScore = stock.leaderScore
        const result = algorithmManager.calculateScore?.(stock)

        if (result && Math.abs(result.score - oldScore) > 0.1) {
          stock.leaderScore = result.score
          updatedCount++
        }
      }

      this.utils.log(`   └─ 更新 ${updatedCount} 只股票的得分`)
    }
  }

  /**
   * 处理龙头变化
   */
  private async processDragonChange(task: UpdateTask): Promise<void> {
    const change = (task.data as any).data
    if (!change) return

    if (change.source === 'quote_update') {
      this.utils.log(`🐲 处理来自行情更新的龙头变化: ${change.code}`)
    } else {
      this.utils.log(`🐲 更新龙头变化: ${change.code}`)
    }

    if (typeof window !== 'undefined' && (window as any).dragonAnalyzer) {
      const dragonAnalyzer = (window as any).dragonAnalyzer

      const processingKey = `dragon_change_${change.code}_${change.timestamp || Date.now()}`
      if ((window as any).__processingDragonChanges?.has(processingKey)) {
        this.utils.log(`⏱️ 正在处理中，忽略重复请求: ${change.code}`)
        return
      }

      if (!(window as any).__processingDragonChanges) {
        ;(window as any).__processingDragonChanges = new Set()
      }
      ;(window as any).__processingDragonChanges.add(processingKey)

      try {
        const result = await dragonAnalyzer.updateLeadersIncremental([change.code])

        if (result > 0) {
          // ✅ 不再需要手动更新股票数据，因为 dragonAnalyzer 会调用 updateLeaderData
          // 只需要触发渲染
          this.triggerRender()
        }
      } finally {
        setTimeout(() => {
          ;(window as any).__processingDragonChanges?.delete(processingKey)
        }, 5000)
      }
    }
  }

  /**
   * 处理龙头全量更新
   */
  private async processDragonFull(): Promise<void> {
    this.utils.log('🐉 执行龙头全量更新')

    if (typeof window !== 'undefined' && (window as any).dragonAnalyzer) {
      const dragonAnalyzer = (window as any).dragonAnalyzer
      if (typeof dragonAnalyzer.recalculateAll === 'function') {
        const result = await dragonAnalyzer.recalculateAll()
        this.utils.log(`   └─ 全量更新结果: ${result}个龙头`)
      }
    }

    this.triggerRender()
  }

  // 添加数组比较方法
  private arraysEqual(arr1: any[], arr2: any[]): boolean {
    if (arr1.length !== arr2.length) return false
    // 可以进一步优化，比如只比较关键字段
    return JSON.stringify(arr1) === JSON.stringify(arr2)
  }

  /**
   * 处理行情更新
   */
  private async processQuoteUpdate(task: UpdateTask): Promise<void> {
    const quoteData = (task.data as any).data
    if (!quoteData) return

    // 防止同一个股票并发处理
    if (this.processingQuotes.has(task.code)) {
      return
    }

    try {
      this.processingQuotes.add(task.code)

      const stock = dataLayer.getStock(task.code)
      if (!stock) return

      // 修复1: 统一转换为数字进行比较
      const currentChange =
        typeof stock.change === 'string' ? parseFloat(stock.change) : stock.change || 0

      const newChange =
        typeof quoteData.change === 'string' ? parseFloat(quoteData.change) : quoteData.change || 0

      // 修复2: 精确的涨停判断 - 使用涨停阈值配置
      const ZT_CONFIG = {
        MAIN: { threshold: 9.8, max: 10.5 }, // 主板 10%涨停
        GEM: { threshold: 19.5, max: 20.5 }, // 创业板 20%涨停
        STAR: { threshold: 19.5, max: 20.5 }, // 科创板 20%涨停
        NORTH: { threshold: 29.8, max: 30.5 }, // 北交所 30%涨停
      }

      const isLimitUp = (code: string, change: number): boolean => {
        // 科创板(688开头)
        if (code.startsWith('688')) {
          return change >= ZT_CONFIG.STAR.threshold && change <= ZT_CONFIG.STAR.max
        }
        // 创业板(300开头)
        if (code.startsWith('300')) {
          return change >= ZT_CONFIG.GEM.threshold && change <= ZT_CONFIG.GEM.max
        }
        // 北交所(8开头)
        if (code.startsWith('8')) {
          return change >= ZT_CONFIG.NORTH.threshold && change <= ZT_CONFIG.NORTH.max
        }
        // 主板(00、60开头)
        return change >= ZT_CONFIG.MAIN.threshold && change <= ZT_CONFIG.MAIN.max
      }

      const wasZT = isLimitUp(task.code, currentChange)
      const isZT = isLimitUp(task.code, newChange)

      // 修复3: 添加防抖和状态缓存
      const lastState = this.lastZTState.get(task.code)
      const now = Date.now()

      // 计算变化幅度，避免微小的波动触发
      const changeDiff = Math.abs(newChange - currentChange)
      const MIN_CHANGE_THRESHOLD = 0.5 // 至少变化0.5%才认为是有效变化

      // 只有当状态真正改变时才处理，并添加防抖
      if (wasZT !== isZT && changeDiff >= MIN_CHANGE_THRESHOLD) {
        // 如果状态变化，且距离上次变化超过最小间隔（10秒），才处理
        if (!lastState || now - lastState.timestamp > 10000) {
          this.utils.log(
            `⚡ 涨停状态变化: ${task.code} ${wasZT ? '开板' : '涨停'} (${currentChange.toFixed(2)}% -> ${newChange.toFixed(2)}%)`,
          )

          // 更新状态缓存
          this.lastZTState.set(task.code, {
            isZT,
            timestamp: now,
            change: newChange,
          })

          // 添加龙头变化任务，但带上更多上下文信息
          this.addToQueue(
            task.code,
            {
              type: UPDATER_CONFIG.UPDATE_TYPES.DRAGON_CHANGE,
              data: {
                code: task.code,
                name: stock.name,
                type: isZT ? '涨停' : '开板',
                fromChange: currentChange,
                toChange: newChange,
                timestamp: now,
                source: 'quote_update',
              },
            },
            UPDATER_CONFIG.PRIORITY.DRAGON_CHANGE,
          )
        } else {
          this.utils.log(`⏱️ 忽略重复的涨停状态变化: ${task.code} (距离上次变化不足10秒)`)
        }
      }
    } finally {
      this.processingQuotes.delete(task.code)
    }
  }

  /**
   * 处理题材更新
   */
  private async processSectorUpdate(task: UpdateTask): Promise<void> {
    const detail = (task.data as any).data
    this.utils.log('📊 执行题材更新')

    // 添加去重标记，避免并发执行
    if (this.sectorUpdateInProgress) {
      this.utils.log('⏱️ 题材更新正在进行中，跳过')
      return
    }

    this.sectorUpdateInProgress = true

    try {
      const themeIds = detail?.themeIds || []

      // 判断是否为全量更新
      const isFullUpdate = themeIds.length === 0
      if (isFullUpdate) {
        this.utils.log('📊 全量题材更新')
        // 检查距离上次全量更新的时间
        const now = Date.now()
        if (this.lastFullSectorUpdate && now - this.lastFullSectorUpdate < 60000) {
          this.utils.log('⏱️ 全量题材更新太频繁，跳过')
          return
        }
        this.lastFullSectorUpdate = now
      }

      EventManager.emit(AppEvents.REFRESH.INCREMENTAL_REQUESTED, {
        source: 'sector-update',
        themeIds,
        timestamp: Date.now(),
      })

      // 记录待处理的变更
      themeIds.forEach((id: string) => {
        this.pendingChanges.add(id)
      })

      this.utils.log(`   └─ 题材更新请求已发送: ${themeIds.length}个题材`)
    } catch (error) {
      this.utils.error('题材更新失败:', error)
    } finally {
      // 延迟清除处理标记，避免短时间内重复执行
      setTimeout(() => {
        this.sectorUpdateInProgress = false
      }, 5000)
    }
  }

  /**
   * 处理排名更新
   */
  private async processRankUpdate(): Promise<void> {
    const now = Date.now()
    if (this.lastRankUpdate && now - this.lastRankUpdate < 5000) {
      this.utils.log('⏱️ 排名更新太频繁，跳过')
      return
    }

    this.lastRankUpdate = now
    this.utils.log('🏆 执行排名更新')

    const stocks = dataLayer.getStocks()
    if (stocks.length === 0) return

    const changedStocks = stocks.filter((s) => this.pendingChanges.has(s.code))
    if (changedStocks.length === 0 && this.pendingChanges.size === 0) return

    const dataLoader = (window as any).dataLoader
    if (!dataLoader) return

    const updatedStocks = dataLoader.calculateComprehensiveRank?.(stocks)

    if (updatedStocks) {
      // ✅ 使用 updateStocks 更新基础数据
      dataLayer.updateStocks(updatedStocks)

      this.utils.log(`   └─ 排名更新完成，影响 ${changedStocks.length} 只股票`)

      EventManager.emit('rank:updated', {
        timestamp: Date.now(),
        changedCount: changedStocks.length,
      })
    }

    this.pendingChanges.clear()
  }

  /**
   * 处理任务错误
   */
  private async handleTaskError(code: string, task: UpdateTask, error: Error): Promise<void> {
    if (this.destroyed) return

    this.utils.error(`任务失败 [${code}]:`, error)

    if (task.retryCount < UPDATER_CONFIG.RETRY.MAX_ATTEMPTS) {
      task.retryCount++

      const delay =
        UPDATER_CONFIG.RETRY.DELAY * Math.pow(UPDATER_CONFIG.RETRY.BACKOFF, task.retryCount - 1)

      this.utils.log(
        `🔄 计划重试 (${task.retryCount}/${UPDATER_CONFIG.RETRY.MAX_ATTEMPTS}), ${delay}ms后`,
      )

      setTimeout(() => {
        if (!this.destroyed) {
          this.addToQueue(code, task.data, task.priority)
        }
      }, delay)
    } else {
      this.utils.error(`❌ 任务失败超过最大重试次数: ${code}`)

      EventManager.emit('incremental:task-failed', {
        code,
        type: task.data.type,
        error: error.message,
        timestamp: Date.now(),
      })
    }
  }

  /**
   * 触发渲染
   */
  private triggerRender(): void {
    if (typeof window !== 'undefined' && (window as any).Renderer) {
      requestAnimationFrame(() => {
        ;(window as any).Renderer.renderTable?.()
      })
    }
  }

  // ========== 大单数据处理 ==========

  /**
   * 处理大单更新
   */
  private async processBigOrderUpdate(task: UpdateTask): Promise<void> {
    const data = (task.data as any).data
    if (!data || !data.code) return

    this.utils.log(`📊 处理大单更新: ${data.code}`)

    if (typeof window !== 'undefined' && (window as any).bigOrderService) {
      const bigOrderService = (window as any).bigOrderService
      try {
        // ✅ 正确：只调用 fetchLatest，内部已处理一切
        const result = await bigOrderService.fetchLatest(
          data.code,
          dataLayer.getStock(data.code)?.name, // 传入股票名称
          30,
        )

        if (result.orders.length > 0) {
          this.pendingChanges.add(data.code)
          this.utils.log(`✅ 大单更新完成: ${data.code}, 新增${result.newCount}条`)
        }
      } catch (error) {
        this.utils.error(`大单更新失败: ${data.code}`, error)
      }
    }
  }

  /**
   * 处理大单全量更新
   */
  private async processBigOrderFullUpdate(): Promise<void> {
    this.utils.log('📊 执行大单全量更新')

    // 获取热门股票
    const stocks = dataLayer
      .getStocks()
      .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
      .slice(0, 10)

    if (typeof window !== 'undefined' && (window as any).bigOrderService) {
      const bigOrderService = (window as any).bigOrderService

      for (const stock of stocks) {
        try {
          // ✅ 全量更新用 fetchAllDay + processAndStore
          const result = await bigOrderService.fetchAllDay(stock.code)
          await bigOrderService.processAndStore(stock.code, stock.name, result.allOrders)
          this.pendingChanges.add(stock.code)
        } catch (error) {
          this.utils.error(`大单全量更新失败: ${stock.code}`, error)
        }
        // 避免请求过快
        await this.utils.delay(100)
      }
    }
  }

  // ========== 公共 API ==========

  /**
   * 暂停处理
   */
  pause(): void {
    if (this.state.paused) return
    this.state.paused = true
    this.utils.log('⏸️ 已手动暂停')
  }

  /**
   * 恢复处理
   */
  resume(): void {
    if (!this.state.paused) return
    this.state.paused = false
    this.utils.log('▶️ 已手动恢复')
  }

  /**
   * 手动触发全量更新
   */
  forceFullUpdate(): void {
    this.utils.log('⚠️ 手动触发全量更新')
    this.runFullUpdate()
  }

  /**
   * 获取队列详情
   */
  getQueueDetails() {
    const details: any = {}

    Object.entries(this.state.queue).forEach(([priority, map]) => {
      const tasks = Array.from(map.entries()).map(([code, task]) => ({
        code,
        priority: task.priority,
        type: task.data.type,
        age: Date.now() - task.timestamp,
        retryCount: task.retryCount,
      }))

      details[priority] = {
        size: map.size,
        oldest: tasks.length > 0 ? Math.max(...tasks.map((t) => t.age)) : 0,
        tasks: tasks.slice(0, 5),
      }
    })

    return details
  }

  /**
   * 获取性能指标
   */
  getPerformanceMetrics() {
    return {
      avgProcessTime: this.state.metrics.avgProcessTime.toFixed(0) + 'ms',
      queueGrowthRate: this.state.metrics.queueGrowthRate.toFixed(2) + '/秒',
      batchSize: this.state.dynamicConfig.batchSize,
      delayBetweenBatches: this.state.dynamicConfig.delayBetweenBatches + 'ms',
      priorityStats: this.state.metrics.priorityStats,
      samples: this.performanceSamples.length,
    }
  }

  /**
   * 获取状态
   */
  getStatus(): UpdaterStatus {
    const queueStats = this.utils.getQueueStats()

    return {
      initialized: this.state.initialized,
      queueSize: this.state.queueSize,
      queueStats: queueStats.byPriority,
      processing: this.state.processing,
      paused: this.state.paused,
      stats: {
        totalUpdates: this.state.stats.totalUpdates,
        totalBatches: this.state.stats.totalBatches,
        byType: { ...this.state.stats.byType },
        avgProcessTime: this.state.stats.avgProcessTime,
        lastUpdateTime: this.state.stats.lastUpdateTime,
        slowQueries: this.state.stats.slowQueries,
      },
      queueHistory: [],
      hotStocksLimit: this.hotStocksLimit,

      dynamic: {
        batchSize: this.state.dynamicConfig.batchSize,
        delay: this.state.dynamicConfig.delayBetweenBatches,
        metrics: this.getPerformanceMetrics(),
        details: this.getQueueDetails(),
      },
    }
  }

  /**
   * 获取慢查询记录
   */
  getSlowQueries(limit: number = 10): SlowQueryRecord[] {
    return []
  }

  /**
   * 重置
   */
  reset(): void {
    if (this.destroyed) return

    Object.values(this.state.queue).forEach((map) => map.clear())
    this.state.queueSize = 0
    this.state.processing = false
    this.state.paused = true

    this.state.stats = this.getDefaultStats()

    this.hotStocksLimit = this.loadHotStocksLimit()
    this.lastZTState.clear()
    this.processingQuotes.clear()
    this.sectorUpdateInProgress = false
    this.lastFullSectorUpdate = 0
    this.lastRankUpdate = 0

    this.utils.log('🔄 已重置')
  }

  /**
   * 销毁实例
   */
  destroy(): void {
    this.destroyed = true

    this.unsubscribeFns.forEach((fn) => {
      try {
        fn()
      } catch (e) {
        console.warn('[IncrementalUpdater] 清理订阅失败:', e)
      }
    })
    this.unsubscribeFns = []

    Object.values(this.state.queue).forEach((map) => map.clear())
    this.state.queueSize = 0
    this.state.processing = false

    this.state.stats = this.getDefaultStats()

    this.lastZTState.clear()
    this.processingQuotes.clear()
  }

  static readonly VERSION = '2.6.0'
}

// 导出单例
export const incrementalUpdater = IncrementalUpdater.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).incrementalUpdater = incrementalUpdater
}
