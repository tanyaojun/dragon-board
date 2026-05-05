import { debugLog } from '@/utils/logger'
// src/services/Algorithm/AlgorithmWarmupManager.ts
// 预热管理模块
// 注意：已移除增量刷新相关代码

import type { IAlgorithmManager } from './AlgorithmManager'
import type { WarmupStrategy } from '@/types/algorithm'

import { EventManager } from '@/utils/eventManager'
import { getWarmupTargets, chunkArray, safeExecute } from '@/utils/algorithmHelpers'

export interface AlgorithmWarmupDependencies {
  dataLayer?: any
  themeFacade?: any
  dragonAnalyzer?: any
}

export class AlgorithmWarmupManager {
  private algorithmManager: IAlgorithmManager
  private getDependencies: () => AlgorithmWarmupDependencies
  private strategies: Map<string, WarmupStrategy> = new Map()
  private isWarmingUp: Map<string, boolean> = new Map()
  private progress: Map<string, { loaded: number; total: number; startTime: number }> = new Map()

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
      schedule: 'onStart', // 改为 onStart，不再周期性预热
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

  constructor(
    algorithmManager: IAlgorithmManager,
    getDependencies: () => AlgorithmWarmupDependencies = () => ({}),
  ) {
    this.algorithmManager = algorithmManager
    this.getDependencies = getDependencies
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
    debugLog('[AlgorithmWarmup] 🔥 启动预热管理...')

    // 执行启动预热
    this.strategies.forEach((strategy, name) => {
      if (strategy.enabled && strategy.schedule === 'onStart') {
        this.warmup(name)
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
   * 供 RefreshManager 调用的更新方法 - 全量预热
   */
  async runUpdate(): Promise<void> {
    debugLog('[AlgorithmWarmup] 收到刷新指令，执行全量预热')

    // 执行所有策略的预热
    const promises: Promise<void>[] = []
    this.strategies.forEach((strategy, name) => {
      if (strategy.enabled) {
        promises.push(this.warmup(name))
      }
    })

    await Promise.allSettled(promises)
  }

  /**
   * 按股票代码预热分数缓存，供 AlgorithmManager 增量更新调用。
   */
  async warmupStocks(codes: string[]): Promise<void> {
    if (!codes.length) return

    const deps = this.getDependencies()
    const stocks = deps.dataLayer?.getStocks?.() || []
    const codeSet = new Set(codes)
    const targets = stocks.filter((stock: any) => codeSet.has(stock.code))

    if (targets.length === 0) return

    this.progress.set('incremental', { loaded: 0, total: targets.length, startTime: Date.now() })
    await this.warmupBatch(targets, {
      enabled: true,
      schedule: 'onIdle',
      priority: 'medium',
      batchSize: targets.length,
      maxItems: targets.length,
      concurrency: 3,
      retryCount: 1,
    })
    this.progress.delete('incremental')
  }

  /**
   * 发布当前预热进度，供后台维护调用。
   */
  checkProgress(): void {
    EventManager.emit('algorithm:warmup-status', {
      progress: this.getAllProgress(),
      timestamp: Date.now(),
    })
  }

  /**
   * 停止预热管理
   */
  stop(): void {
    this.isWarmingUp.clear()
    this.progress.clear()
  }

  /**
   * 执行预热
   */
  async warmup(name: string): Promise<void> {
    const strategy = this.strategies.get(name)
    if (!strategy || !strategy.enabled) return

    if (this.isWarmingUp.get(name)) {
      debugLog(`[AlgorithmWarmup] ⏳ 预热 ${name} 正在进行中，跳过`)
      return
    }

    this.isWarmingUp.set(name, true)

    try {
      debugLog(`[AlgorithmWarmup] 🔥 开始预热: ${name}`)
      EventManager.emit('algorithm:warmup-started', {
        strategy: name,
        total: strategy.maxItems || 0,
      })

      // 获取预热目标
      const deps = this.getDependencies()
      const stocks = await getWarmupTargets(
        name,
        deps.themeFacade,
        deps.dragonAnalyzer,
        deps.dataLayer,
      )

      const targets = stocks.slice(0, strategy.maxItems)
      const batches = chunkArray(targets, strategy.batchSize)

      this.progress.set(name, { loaded: 0, total: targets.length, startTime: Date.now() })

      // 分批预热
      for (let i = 0; i < batches.length; i++) {
        const batch = batches[i]

        // 并发预热
        await this.warmupBatch(batch, strategy)

        // 更新进度
        const entry = this.progress.get(name)!
        const loaded = Math.min((i + 1) * strategy.batchSize, targets.length)
        this.progress.set(name, { ...entry, loaded })

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
      debugLog(
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

  private getWarmupDuration(name: string): number {
    const entry = this.progress.get(name)
    return entry ? Date.now() - entry.startTime : 0
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
    }
  }

  /**
   * 启用/禁用策略
   */
  setStrategyEnabled(name: string, enabled: boolean): void {
    const strategy = this.strategies.get(name)
    if (strategy) {
      strategy.enabled = enabled
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
