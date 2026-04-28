// src/services/Algorithm/AlgorithmWarmupManager.ts
// 预热管理模块

import type { IAlgorithmManager } from './AlgorithmManager'
import type { WarmupStrategy, WarmupTarget } from '@/types/algorithm'

import { dataLayer } from '@/services/DataLayer'
import { sectorAnalyzer } from '@/services/sectorAnalyzer'
import { dragonAnalyzer } from '@/services/DragonAnalyzer'
import { EventManager } from '@/utils/eventManager'
import { getWarmupTargets, chunkArray, safeExecute, throttle } from '@/utils/algorithmHelpers'

export class AlgorithmWarmupManager {
  private algorithmManager: IAlgorithmManager
  private strategies: Map<string, WarmupStrategy> = new Map()
  private isWarmingUp: Map<string, boolean> = new Map()
  private progress: Map<string, { loaded: number; total: number }> = new Map()

  // ✅ 合并两个 timers 定义
  private timers = {
    warmupTimer: null as ReturnType<typeof setInterval> | null,
    periodicTimers: new Map<string, ReturnType<typeof setInterval>>(),
  }

  // 默认预热策略
  private defaultStrategies: Record<string, WarmupStrategy> = {
    hotThemes: {
      enabled: true,
      schedule: 'onStart',
      priority: 'high',
      batchSize: 20,
      maxItems: 200,
      concurrency: 3,
      retryCount: 2,
    },
    leaders: {
      enabled: true,
      schedule: 'periodic',
      interval: 5 * 60 * 1000, // 5分钟
      priority: 'medium',
      batchSize: 10,
      maxItems: 50,
      concurrency: 2,
      retryCount: 2,
    },
    popularStocks: {
      enabled: true,
      schedule: 'onIdle',
      priority: 'low',
      batchSize: 50,
      maxItems: 500,
      concurrency: 3,
      retryCount: 1,
    },
  }

  constructor(algorithmManager: IAlgorithmManager) {
    this.algorithmManager = algorithmManager
    this.initStrategies()
  }

  /**
   * 初始化策略
   */
  private initStrategies(): void {
    Object.entries(this.defaultStrategies).forEach(([name, strategy]) => {
      this.strategies.set(name, { ...strategy })
    })
  }

  /**
   * 启动预热管理
   */
  start(): void {
    console.log('[AlgorithmWarmup] 🔥 启动预热管理...')

    // 执行启动预热
    this.strategies.forEach((strategy, name) => {
      if (strategy.enabled && strategy.schedule === 'onStart') {
        this.warmup(name)
      }
    })

    // 启动定时预热
    this.strategies.forEach((strategy, name) => {
      if (strategy.enabled && strategy.schedule === 'periodic' && strategy.interval) {
        this.startPeriodicWarmup(name, strategy.interval)
      }
    })

    // 空闲时预热
    if ('requestIdleCallback' in window) {
      this.strategies.forEach((strategy, name) => {
        if (strategy.enabled && strategy.schedule === 'onIdle') {
          window.requestIdleCallback(
            () => {
              this.warmup(name)
            },
            { timeout: 10000 },
          )
        }
      })
    }
  }

  /**
   * 停止预热管理
   */
  stop(): void {
    // 清理所有定时器
    if (this.timers.warmupTimer) {
      clearInterval(this.timers.warmupTimer)
      this.timers.warmupTimer = null
    }

    this.timers.periodicTimers.forEach((timer) => clearInterval(timer))
    this.timers.periodicTimers.clear()

    this.isWarmingUp.clear()
    this.progress.clear()
  }

  /**
   * 开始定时预热
   */
  private startPeriodicWarmup(name: string, interval: number): void {
    const timer = setInterval(() => {
      this.warmup(name)
    }, interval)

    this.timers.periodicTimers.set(name, timer)
  }

  /**
   * 执行预热
   */
  async warmup(name: string): Promise<void> {
    const strategy = this.strategies.get(name)
    if (!strategy || !strategy.enabled) return

    if (this.isWarmingUp.get(name)) {
      console.log(`[AlgorithmWarmup] ⏳ 预热 ${name} 正在进行中，跳过`)
      return
    }

    this.isWarmingUp.set(name, true)

    try {
      console.log(`[AlgorithmWarmup] 🔥 开始预热: ${name}`)
      EventManager.emit('algorithm:warmup-started', {
        strategy: name,
        total: strategy.maxItems || 0,
      })

      // 获取预热目标
      const stocks = await getWarmupTargets(name, sectorAnalyzer, dragonAnalyzer, dataLayer)

      const targets = stocks.slice(0, strategy.maxItems)
      const batches = chunkArray(targets, strategy.batchSize)

      this.progress.set(name, { loaded: 0, total: targets.length })

      // 分批预热
      for (let i = 0; i < batches.length; i++) {
        const batch = batches[i]

        // 并发预热
        await this.warmupBatch(batch, strategy)

        // 更新进度
        const loaded = Math.min((i + 1) * strategy.batchSize, targets.length)
        this.progress.set(name, { loaded, total: targets.length })

        EventManager.emit('algorithm:warmup-progress', {
          strategy: name,
          loaded,
          total: targets.length,
        })

        // 控制预热速度
        if (i < batches.length - 1) {
          await new Promise((resolve) => setTimeout(resolve, 100))
        }
      }

      const duration = this.getWarmupDuration(name)
      console.log(
        `[AlgorithmWarmup] ✅ 预热完成: ${name}, ${targets.length}只股票, 耗时${duration}ms`,
      )

      EventManager.emit('algorithm:warmup-completed', {
        strategy: name,
        loaded: targets.length,
        duration,
      })
    } catch (error) {
      console.error(`[AlgorithmWarmup] ❌ 预热失败: ${name}`, error)
    } finally {
      this.isWarmingUp.set(name, false)
      this.progress.delete(name)
    }
  }

  /**
   * 预热单个批次
   */
  private async warmupBatch(stocks: any[], strategy: WarmupStrategy): Promise<void> {
    const concurrency = strategy.concurrency || 3
    const batches = chunkArray(stocks, concurrency)

    for (const batch of batches) {
      await Promise.all(
        batch.map((stock) =>
          safeExecute(
            async () => {
              // 计算得分（会触发缓存）
              await this.algorithmManager.calculateScore(stock)
            },
            null,
            (error) => {
              if (strategy.retryCount && strategy.retryCount > 0) {
                // 重试逻辑
                setTimeout(() => {
                  this.algorithmManager.calculateScore(stock)
                }, 1000)
              }
            },
          ),
        ),
      )
    }
  }

  /**
   * 获取预热时长
   */
  private getWarmupDuration(name: string): number {
    const startTime = Date.now() - 1000 // 简化实现
    return Date.now() - startTime
  }

  /**
   * 获取预热进度
   */
  getProgress(name: string): { loaded: number; total: number } | null {
    return this.progress.get(name) || null
  }

  /**
   * 获取所有预热进度
   */
  getAllProgress(): Record<string, { loaded: number; total: number }> {
    const result: Record<string, { loaded: number; total: number }> = {}
    this.progress.forEach((value, key) => {
      result[key] = value
    })
    return result
  }

  /**
   * 检查是否正在预热
   */
  isWarming(name: string): boolean {
    return this.isWarmingUp.get(name) || false
  }

  /**
   * 更新预热策略
   */
  updateStrategy(name: string, strategy: Partial<WarmupStrategy>): void {
    const existing = this.strategies.get(name)
    if (existing) {
      this.strategies.set(name, { ...existing, ...strategy })

      // 如果改变了间隔，重启定时器
      if (strategy.interval && existing.interval !== strategy.interval) {
        const timer = this.timers.periodicTimers.get(name)
        if (timer) {
          clearInterval(timer)
          this.timers.periodicTimers.delete(name)
          this.startPeriodicWarmup(name, strategy.interval)
        }
      }
    }
  }

  /**
   * 启用/禁用策略
   */
  setStrategyEnabled(name: string, enabled: boolean): void {
    const strategy = this.strategies.get(name)
    if (strategy) {
      strategy.enabled = enabled

      // 如果禁用，取消定时器
      if (!enabled) {
        const timer = this.timers.periodicTimers.get(name)
        if (timer) {
          clearInterval(timer)
          this.timers.periodicTimers.delete(name)
        }
      }
    }
  }

  /**
   * 获取所有策略
   */
  getStrategies(): Record<string, WarmupStrategy> {
    const result: Record<string, WarmupStrategy> = {}
    this.strategies.forEach((value, key) => {
      result[key] = { ...value }
    })
    return result
  }

  /**
   * 手动触发预热
   */
  async warmupNow(name: string): Promise<boolean> {
    if (!this.strategies.has(name)) return false
    await this.warmup(name)
    return true
  }

  /**
   * 预热所有
   */
  async warmupAll(): Promise<void> {
    const promises: Promise<void>[] = []
    this.strategies.forEach((_, name) => {
      promises.push(this.warmup(name))
    })
    await Promise.all(promises)
  }
}
