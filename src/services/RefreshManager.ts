import { debugLog } from '@/utils/logger'
// src/services/RefreshManager.ts

import { reactive } from 'vue'
import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types'
import { dataLayer } from './DataLayer'
import { isTradingTime } from '../utils/time'
import type { RefreshStrategy as ConfigRefreshStrategy, RefreshConfig } from '../types/config'
import { REFRESH_STRATEGY_CONFIGS, REFRESH_STORAGE_KEY } from '../types/config'
import { refreshCoordinator } from './RefreshCoordinator'
import { refreshScheduler, refreshTaskRegistry } from './refresh/RefreshTaskRuntime'
import type { RefreshRequest, RefreshRequestResult } from './refresh/types'

export type RefreshStrategy = 'conservative' | 'balanced' | 'aggressive'

interface RefreshStatus {
  initialized: boolean
  enabled: boolean
  strategy: RefreshStrategy
  tradingTimeOnly: boolean
  allowManualRefresh: boolean
  fullRefreshInterval: number
  incrementalRefreshInterval: number
  hotStocksLimit?: number
  retryOnFailure: boolean
  maxRetries?: number
  isRunning: boolean
  isRefreshing: boolean
  stats: {
    fullRefreshes: number
    incrementalRefreshes: number
    manualRefreshes: number
    failedRefreshes: number
    lastRefreshTime: number | null
    lastFullRefreshTime: number | null
    lastIncrementalRefreshTime: number | null
    totalStocksLoaded: number
    totalLeadersFound: number
  }
}

function normalizeRefreshStrategy(strategy: ConfigRefreshStrategy | undefined): RefreshStrategy {
  return strategy === 'conservative' || strategy === 'balanced' || strategy === 'aggressive'
    ? strategy
    : 'balanced'
}

// 注意：已移除 incrementalUpdater 依赖

class RefreshManagerService {
  private state = reactive<RefreshStatus>({
    initialized: false,
    enabled: true,
    strategy: 'balanced',
    tradingTimeOnly: true,
    allowManualRefresh: true,
    fullRefreshInterval: 3600000,
    incrementalRefreshInterval: 300000, // 保留但不再使用
    retryOnFailure: true,
    isRunning: false,
    isRefreshing: false,
    stats: {
      fullRefreshes: 0,
      incrementalRefreshes: 0,
      manualRefreshes: 0,
      failedRefreshes: 0,
      lastRefreshTime: null,
      lastFullRefreshTime: null,
      lastIncrementalRefreshTime: null,
      totalStocksLoaded: 0,
      totalLeadersFound: 0,
    },
  })

  private timers = {
    full: null as ReturnType<typeof setInterval> | null,
    trading: null as ReturnType<typeof setInterval> | null,
    maintenance: null as ReturnType<typeof setInterval> | null,
    rotation: null as ReturnType<typeof setInterval> | null,
  }

  private currentConfig: RefreshConfig
  private readonly taskRegistry = refreshTaskRegistry
  private unsubscribeFns: (() => void)[] = []
  private destroyed = false
  private isTradingTimeCache = false
  private refreshEventsBound = false

  constructor() {
    this.currentConfig = { ...REFRESH_STRATEGY_CONFIGS.balanced }
  }

  /**
   * 从 localStorage 加载配置
   */
  private loadFromStorage(): RefreshConfig {
    try {
      const saved = localStorage.getItem(REFRESH_STORAGE_KEY)
      if (saved) {
        const parsed = JSON.parse(saved) as RefreshConfig

        if (parsed.strategy && REFRESH_STRATEGY_CONFIGS[parsed.strategy]) {
          const preset = REFRESH_STRATEGY_CONFIGS[parsed.strategy]

          return {
            ...preset,
            ...parsed,
            strategy: parsed.strategy,
            fullRefreshInterval: parsed.fullRefreshInterval ?? preset.fullRefreshInterval,
            incrementalRefreshInterval:
              parsed.incrementalRefreshInterval ?? preset.incrementalRefreshInterval,
            hotStocksLimit: parsed.hotStocksLimit ?? preset.hotStocksLimit,
            tradingTimeOnly: parsed.tradingTimeOnly ?? preset.tradingTimeOnly,
            allowManualRefresh: parsed.allowManualRefresh ?? preset.allowManualRefresh,
          }
        }
        return parsed
      }
    } catch (e) {
      console.warn('[RefreshManager] 加载配置失败:', e)
    }

    debugLog('[RefreshManager] 使用默认配置:', REFRESH_STRATEGY_CONFIGS.balanced)
    return { ...REFRESH_STRATEGY_CONFIGS.balanced }
  }

  /**
   * 保存配置到 localStorage
   */
  private saveToStorage(config: RefreshConfig): void {
    try {
      localStorage.setItem(REFRESH_STORAGE_KEY, JSON.stringify(config))
      debugLog('[RefreshManager] 配置已保存到 localStorage:', config)
    } catch (e) {
      console.error('[RefreshManager] 保存配置失败:', e)
    }
  }

  /**
   * 初始化
   */
  async init(): Promise<boolean> {
    if (this.state.initialized) return true

    try {
      const savedConfig = this.loadFromStorage()
      this.currentConfig = { ...savedConfig }

      this.state.enabled = this.currentConfig.enabled
      this.state.strategy = normalizeRefreshStrategy(this.currentConfig.strategy)
      this.state.tradingTimeOnly = this.currentConfig.tradingTimeOnly
      this.state.allowManualRefresh = this.currentConfig.allowManualRefresh
      this.state.fullRefreshInterval = this.currentConfig.fullRefreshInterval
      this.state.incrementalRefreshInterval = this.currentConfig.incrementalRefreshInterval
      this.state.retryOnFailure = this.currentConfig.retryOnFailure
      refreshScheduler.setPolicy({ tradingTimeOnly: this.currentConfig.tradingTimeOnly })

      this.setupListeners()
      this.isTradingTimeCache = isTradingTime()
      this.state.initialized = true

      this.startTradingChecker()

      // if (this.state.enabled) {
      //   this.start()
      // }

      debugLog('[RefreshManager] ✅ 初始化完成，当前配置:', this.getStatus())
      EventManager.emit('refresh:initialized', { config: this.getStatus() })

      return true
    } catch (error) {
      console.error('[RefreshManager] ❌ 初始化失败:', error)
      return false
    }
  }

  /**
   * 启动刷新
   */
  start(): boolean {
    if (!this.state.initialized || this.destroyed) return false
    if (!this.state.enabled) return false
    if (this.state.isRunning) return true

    this.startFullTimer()

    this.state.isRunning = true
    EventManager.emit('refresh:started', { timestamp: Date.now() })
    debugLog('[RefreshManager] ▶️ 已启动')

    return true
  }

  /**
   * 停止刷新
   */
  stop(): boolean {
    this.clearRefreshTimers()
    this.state.isRunning = false
    EventManager.emit('refresh:stopped', { timestamp: Date.now() })
    debugLog('[RefreshManager] ⏸️ 已停止')
    return true
  }

  /**
   * 刷新入口
   */
  async refresh(
    type: 'full' | 'manual' = 'full',
    options: { force?: boolean; retryCount?: number } = {},
  ): Promise<boolean> {
    const result = await this.requestRefresh({
      kind: 'full',
      source: type === 'manual' ? 'manual' : 'timer',
      trigger: type === 'manual' ? 'manual' : 'timer',
      force: Boolean(options.force),
      retryCount: options.retryCount,
    })
    return result.success
  }

  async requestRefresh(request: RefreshRequest): Promise<RefreshRequestResult> {
    const normalizedRequest: RefreshRequest = {
      kind: 'full',
      source: request.source || 'unknown',
      trigger: request.trigger || 'external',
      force: Boolean(request.force),
      retryCount: request.retryCount,
      timestamp: request.timestamp || Date.now(),
    }

    const skipped = (reason: string): RefreshRequestResult => ({
      kind: normalizedRequest.kind,
      source: normalizedRequest.source,
      success: false,
      skipped: true,
      busy: false,
      duration: 0,
      executedTasks: [],
      errors: {},
      reason,
      timestamp: Date.now(),
    })

    const busy = (reason: string): RefreshRequestResult => ({
      kind: normalizedRequest.kind,
      source: normalizedRequest.source,
      success: false,
      skipped: false,
      busy: true,
      duration: 0,
      executedTasks: [],
      errors: {},
      reason,
      timestamp: Date.now(),
    })

    if (this.destroyed) return skipped('manager-destroyed')

    const isManual = normalizedRequest.trigger === 'manual'
    if (isManual && !this.state.allowManualRefresh) return skipped('manual-disabled')
    if (!isManual && !normalizedRequest.force) {
      if (!this.state.isRunning) return skipped('manager-stopped')
      if (this.state.tradingTimeOnly && !isTradingTime()) return skipped('outside-trading-time')
    }

    if (this.state.isRefreshing) return busy('manager-busy')
    if (refreshCoordinator.getStatus().isRefreshing) return busy('coordinator-busy')

    const startTime = Date.now()
    this.state.isRefreshing = true

    const timeoutId = setTimeout(() => {
      if (this.state.isRefreshing) {
        console.warn('[RefreshManager] 刷新超时，强制重置刷新状态')
        this.state.isRefreshing = false
      }
    }, 30000)

    try {
      const result = await refreshCoordinator.executeRequest(normalizedRequest)
      const finishedAt = Date.now()

      if (isManual) {
        this.state.stats.manualRefreshes++
      } else {
        this.state.stats.fullRefreshes++
      }
      this.state.stats.lastRefreshTime = finishedAt
      this.state.stats.lastFullRefreshTime = finishedAt
      if (!result.success && !result.skipped && !result.busy) {
        this.state.stats.failedRefreshes++
      }

      return {
        ...result,
        duration: result.duration || finishedAt - startTime,
      }
    } catch (error) {
      this.state.stats.failedRefreshes++
      const message = error instanceof Error ? error.message : String(error)
      const result: RefreshRequestResult = {
        kind: normalizedRequest.kind,
        source: normalizedRequest.source,
        success: false,
        skipped: false,
        busy: false,
        duration: Date.now() - startTime,
        executedTasks: [],
        errors: { refresh: message },
        timestamp: Date.now(),
      }

      EventManager.emit(AppEvents.REFRESH.FAILED, {
        ...result,
        type: result.kind,
        error: message,
      })

      return result
    } finally {
      clearTimeout(timeoutId)
      this.state.isRefreshing = false
    }
  }

  /**
   * 手动刷新（对外接口）
   */
  async manualRefresh(type: 'full' = 'full'): Promise<boolean> {
    if (!this.state.allowManualRefresh) {
      console.warn('[RefreshManager] 手动刷新被禁用')

      EventManager.emit(AppEvents.UI.TOAST, {
        message: '手动刷新已被禁用',
        type: 'warning',
        duration: 2000,
      })

      return false
    }

    try {
      const result = await this.requestRefresh({
        kind: 'full',
        source: 'manual',
        trigger: 'manual',
        force: true,
      })

      if (result.success) {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '✅ 数据已更新',
          type: 'success',
          duration: 2000,
        })
      } else if (result.busy) {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '⏳ 刷新进行中',
          type: 'info',
          duration: 1500,
        })
      } else if (result.skipped) {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '刷新已跳过',
          type: 'info',
          duration: 1500,
        })
      } else {
        EventManager.emit(AppEvents.UI.TOAST, {
          message: '❌ 刷新失败，请稍后重试',
          type: 'error',
          duration: 2000,
        })
      }

      return result.success
    } catch (error) {
      console.error('[RefreshManager] 手动刷新异常:', error)

      EventManager.emit(AppEvents.UI.TOAST, {
        message: `刷新异常: ${error instanceof Error ? error.message : '未知错误'}`,
        type: 'error',
        duration: 3000,
      })
    }

    return false
  }

  // ========== 定时器管理 ==========

  private startFullTimer(): void {
    if (this.timers.full) clearInterval(this.timers.full)

    this.timers.full = setInterval(() => {
      if (this.shouldAutoRefresh('full')) {
        void this.requestRefresh({
          kind: 'full',
          source: 'timer',
          trigger: 'timer',
          force: false,
        })
      }
    }, this.currentConfig.fullRefreshInterval)
  }

  private startTradingChecker(): void {
    if (this.timers.trading) clearInterval(this.timers.trading)

    this.timers.trading = setInterval(() => {
      const isTrading = isTradingTime()

      if (isTrading !== this.isTradingTimeCache) {
        this.isTradingTimeCache = isTrading

        if (isTrading && this.currentConfig.enabled && !this.state.isRunning) {
          this.start()
        } else if (!isTrading && this.state.isRunning && this.currentConfig.tradingTimeOnly) {
          this.stop()
        }
      }
    }, 60000)
  }

  private shouldAutoRefresh(type: 'full'): boolean {
    if (!this.currentConfig.enabled) return false
    if (!this.state.isRunning) return false
    if (this.state.isRefreshing) return false
    if (this.currentConfig.tradingTimeOnly && !isTradingTime()) return false
    return true
  }

  private clearAllTimers(): void {
    this.clearRefreshTimers()
    if (this.timers.trading) {
      clearInterval(this.timers.trading)
      this.timers.trading = null
    }
  }

  private clearRefreshTimers(): void {
    if (this.timers.full) {
      clearInterval(this.timers.full)
      this.timers.full = null
    }
    if (this.timers.maintenance) {
      clearInterval(this.timers.maintenance)
      this.timers.maintenance = null
    }
    if (this.timers.rotation) {
      clearInterval(this.timers.rotation)
      this.timers.rotation = null
    }
  }

  // ========== 配置管理 ==========

  updateConfig(config: Partial<RefreshConfig>): void {
    const oldConfig = { ...this.currentConfig }

    Object.assign(this.currentConfig, config)
    this.saveToStorage(this.currentConfig)

    this.state.enabled = this.currentConfig.enabled
    this.state.strategy = normalizeRefreshStrategy(this.currentConfig.strategy)
    this.state.tradingTimeOnly = this.currentConfig.tradingTimeOnly
    this.state.allowManualRefresh = this.currentConfig.allowManualRefresh
    this.state.fullRefreshInterval = this.currentConfig.fullRefreshInterval
    this.state.incrementalRefreshInterval = this.currentConfig.incrementalRefreshInterval
    this.state.retryOnFailure = this.currentConfig.retryOnFailure
    refreshScheduler.setPolicy({ tradingTimeOnly: this.currentConfig.tradingTimeOnly })

    if (
      oldConfig.fullRefreshInterval !== this.currentConfig.fullRefreshInterval ||
      oldConfig.enabled !== this.currentConfig.enabled ||
      oldConfig.tradingTimeOnly !== this.currentConfig.tradingTimeOnly
    ) {
      const canRunNow =
        this.currentConfig.enabled &&
        (!this.currentConfig.tradingTimeOnly || isTradingTime())

      if (this.state.isRunning && !canRunNow) {
        this.stop()
      } else if (!this.state.isRunning && canRunNow) {
        this.start()
      } else if (this.state.isRunning && canRunNow) {
        this.stop()
        this.start()
      }
    }

    EventManager.emit('refresh:config-changed', { config: this.getStatus() })
  }

  /**
   * 设置策略
   */
  setStrategy(strategy: ConfigRefreshStrategy, applyPreset: boolean = true): void {
    const normalizedStrategy = normalizeRefreshStrategy(strategy)
    if (applyPreset) {
      const preset = REFRESH_STRATEGY_CONFIGS[normalizedStrategy]
      this.updateConfig({ ...preset })
    } else {
      this.updateConfig({ strategy: normalizedStrategy })
    }
  }

  // ========== 开关控制 ==========

  toggleEnabled(enabled: boolean): void {
    this.updateConfig({ enabled })
  }

  toggleTradingTimeOnly(enabled: boolean): void {
    this.updateConfig({ tradingTimeOnly: enabled })
  }

  toggleAllowManualRefresh(enabled: boolean): void {
    this.updateConfig({ allowManualRefresh: enabled })
  }

  // ========== 事件监听 ==========
  private setupListeners(): void {
    if (!this.refreshEventsBound) {
      this.refreshEventsBound = true

      const unsubFull = EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, (data: any) => {
        if (this.destroyed) return
        void this.requestRefresh({
          kind: 'full',
          source: data?.source || 'event',
          trigger: data?.trigger || 'event',
          force: Boolean(data?.force),
          retryCount: data?.retryCount,
          timestamp: data?.timestamp,
        })
      })
      this.unsubscribeFns.push(unsubFull)

      const unsubManual = EventManager.on(AppEvents.REFRESH.MANUAL_REQUESTED, (data: any) => {
        if (this.destroyed) return
        void this.requestRefresh({
          kind: 'full',
          source: data?.source || 'manual',
          trigger: 'manual',
          force: data?.force !== false,
          retryCount: data?.retryCount,
          timestamp: data?.timestamp,
        })
      })
      this.unsubscribeFns.push(unsubManual)
    }

    // 监听数据合并完成，更新统计
    const unsub1 = EventManager.on(AppEvents.DATA.MERGED, (data: any) => {
      if (this.destroyed) return
      this.state.stats.totalStocksLoaded = data?.count || dataLayer.getStocks().length
    })
    this.unsubscribeFns.push(unsub1)

    // 监听龙头更新完成
    const unsub2 = EventManager.on('leader.updated', (data: any) => {
      if (this.destroyed) return
      if (data?.count) {
        this.state.stats.totalLeadersFound = data.count
      }
    })
    this.unsubscribeFns.push(unsub2)

    // 同时保留对 DRAGON.UPDATED 的监听（向后兼容）
    const unsub2b = EventManager.on(AppEvents.DRAGON.UPDATED, (data: any) => {
      if (this.destroyed) return
      if (data?.totalLeaders) {
        this.state.stats.totalLeadersFound = data.totalLeaders
      }
    })
    this.unsubscribeFns.push(unsub2b)

    // 监听题材更新
    const unsubThemes = EventManager.on('theme.updated', () => {
      if (this.destroyed) return
    })
    this.unsubscribeFns.push(unsubThemes)

    // 监听配置变化
    const unsub3 = EventManager.on('config:refresh-changed', (config: Partial<RefreshConfig>) => {
      if (this.destroyed) return
      this.updateConfig(config)
    })
    this.unsubscribeFns.push(unsub3)

    // 监听 localStorage 变化（跨标签页同步）
    if (typeof window !== 'undefined') {
      const storageHandler = (e: StorageEvent) => {
        if (e.key === REFRESH_STORAGE_KEY && !this.destroyed) {
          const newConfig = this.loadFromStorage()
          this.currentConfig = { ...newConfig }
          this.state.enabled = this.currentConfig.enabled
          this.state.strategy = normalizeRefreshStrategy(this.currentConfig.strategy)
          this.state.tradingTimeOnly = this.currentConfig.tradingTimeOnly
          this.state.allowManualRefresh = this.currentConfig.allowManualRefresh
          this.state.fullRefreshInterval = this.currentConfig.fullRefreshInterval
          this.state.incrementalRefreshInterval = this.currentConfig.incrementalRefreshInterval
          this.state.retryOnFailure = this.currentConfig.retryOnFailure
          refreshScheduler.setPolicy({ tradingTimeOnly: this.currentConfig.tradingTimeOnly })

          debugLog('[RefreshManager] 检测到 localStorage 变化，配置已同步')
        }
      }
      window.addEventListener('storage', storageHandler)
      this.unsubscribeFns.push(() => window.removeEventListener('storage', storageHandler))
    }

    // AllTick 轮换定时器（纳入统一清理，避免泄漏）
    if (this.timers.rotation) clearInterval(this.timers.rotation)
    this.timers.rotation = setInterval(() => {
      if (typeof window !== 'undefined' && this.state.isRunning && !this.destroyed) {
        ;(window as any).webSocketService?.runRotation?.()
      }
    }, 45000)
  }

  // ========== 状态查询 ==========

  getStatus() {
    return {
      initialized: this.state.initialized,
      enabled: this.state.enabled,
      strategy: this.state.strategy,
      tradingTimeOnly: this.state.tradingTimeOnly,
      allowManualRefresh: this.state.allowManualRefresh,
      fullRefreshInterval: this.state.fullRefreshInterval,
      incrementalRefreshInterval: this.state.incrementalRefreshInterval,
      retryOnFailure: this.state.retryOnFailure,
      isRunning: this.state.isRunning,
      isRefreshing: this.state.isRefreshing,
      isTradingTime: isTradingTime(),
      stats: { ...this.state.stats },
      policy: refreshScheduler.getPolicy(),
      tasks: this.taskRegistry.listTasks(),
      lastError: null,
      hotStocksLimit: this.currentConfig.hotStocksLimit,
    }
  }

  getStats() {
    return { ...this.state.stats }
  }

  // ========== 重置 ==========

  reset(): void {
    if (this.destroyed) return

    this.stop()
    this.clearAllTimers()

    this.currentConfig = { ...REFRESH_STRATEGY_CONFIGS.balanced }
    this.saveToStorage(this.currentConfig)

    this.state.enabled = this.currentConfig.enabled
    this.state.strategy = normalizeRefreshStrategy(this.currentConfig.strategy)
    this.state.tradingTimeOnly = this.currentConfig.tradingTimeOnly
    this.state.allowManualRefresh = this.currentConfig.allowManualRefresh
    this.state.fullRefreshInterval = this.currentConfig.fullRefreshInterval
    this.state.incrementalRefreshInterval = this.currentConfig.incrementalRefreshInterval
    this.state.retryOnFailure = this.currentConfig.retryOnFailure
    refreshScheduler.setPolicy({ tradingTimeOnly: this.currentConfig.tradingTimeOnly })

    this.state.stats = {
      fullRefreshes: 0,
      incrementalRefreshes: 0,
      manualRefreshes: 0,
      failedRefreshes: 0,
      lastRefreshTime: null,
      lastFullRefreshTime: null,
      lastIncrementalRefreshTime: null,
      totalStocksLoaded: 0,
      totalLeadersFound: 0,
    }
    if (this.state.enabled && !this.destroyed) {
      this.start()
    }

    EventManager.emit('refresh:config-reset', { config: this.getStatus() })
  }

  // ========== 销毁 ==========
  destroy(): void {
    if (this.destroyed) return

    this.destroyed = true
    this.stop()

    this.unsubscribeFns.forEach((fn) => {
      try {
        fn()
      } catch (e) {
        console.warn('[RefreshManager] 清理监听失败:', e)
      }
    })
    this.unsubscribeFns = []
    this.refreshEventsBound = false

    this.clearAllTimers()

    debugLog('[RefreshManager] 💥 已销毁')
  }
}

export const RefreshManager = new RefreshManagerService()

if (typeof window !== 'undefined') {
  ;(window as any).RefreshManager = RefreshManager
}
