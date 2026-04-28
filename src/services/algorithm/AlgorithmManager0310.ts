// src/services/Algorithm/AlgorithmManager.ts

import type { Stock, ScoreResult, PerformanceRecord, PerformanceStat } from '@/types'
import { FACTORS } from '@/config/factors'
import { ALGORITHMS, PHASE_MULTIPLIERS, DEFAULT_THRESHOLDS } from '@/config/algorithms'
import { STORAGE_KEYS } from '@/config/storage'

import {
  AppEvents,
  PHASE_ADJUSTMENTS,
  type EmotionFactorWeights,
  type EmotionFeedback,
} from '@/types'

import { dataLayer } from '@/services/DataLayer'
import { stockCache } from '@/services/LRUCache'
import { calculationQueue } from './CalculationQueue'
import { EventManager } from '@/utils/eventManager'

import { AlgorithmPerformanceMonitor } from './AlgorithmPerformanceMonitor'
import { AlgorithmWarmupManager } from './AlgorithmWarmupManager'
import { AlgorithmHealthChecker } from './AlgorithmHealthChecker'
import { AlgorithmABTestManager } from './AlgorithmABTestManager'

import { createCacheKey, safeExecute, throttle, debounce } from '@/utils/algorithmHelpers'

export interface SectorAnalyzer {
  getHotThemes?: () => any[]
  syncLeadersToThemes?: (leaders: any[]) => void
}

// ===== 情绪反馈相关类型 =====
export interface EmotionAdjustment {
  factorId: string
  delta: number
  oldWeight: number
  newWeight: number
  reason: string
  timestamp: number
}

export interface WeightAdjustmentEvent {
  phase: string
  adjustments: Array<{ factorId: string; oldWeight: number; newWeight: number }>
  timestamp: number
}

// 主协调器接口
export interface IAlgorithmManager {
  getCurrentAlgorithm(): any
  calculateScore(stock: Stock): ScoreResult
  calculateScoresBulk(stocks: Stock[]): Map<string, ScoreResult>
  invalidateCache(): void
  getVersion(): number
  getFactorWeights(algorithmId?: string): any[]
  updateFactorWeight(factorId: string, weight: number): boolean
  getThresholds(): Record<string, number>
  updateThreshold(key: string, value: number): boolean
  getAlgorithmFactors?(algorithmId: string): any[]

  // 情绪相关接口
  handleEmotionFeedback?(feedback: EmotionFeedback): void
  adjustWeightsByPhase?(phase: string): boolean
  getWeightAdjustmentHistory?(): EmotionAdjustment[]
  getEmotionStats?(): Record<string, { count: number; avgScore: number }>
}

// ========== 事件合并管理器 ==========
class AlgorithmEventManager {
  private updateTimer: ReturnType<typeof setTimeout> | null = null
  private pendingEvents: Map<string, any> = new Map()
  private lastEmitTime = 0

  private readonly MERGE_INTERVAL = 500 // 500ms 合并间隔
  private readonly MAX_DELAY = 2000 // 最大延迟 2秒

  /**
   * 触发算法变更事件（自动合并）
   */
  triggerAlgorithmChanged(algorithm: any) {
    this.pendingEvents.set('algorithm-changed', {
      algorithm,
      timestamp: Date.now(),
    })
    this.scheduleEmit()
  }

  /**
   * 触发权重调整事件（自动合并）
   */
  triggerWeightsAdjusted(data: any) {
    const key = 'algorithm:weights-adjusted'
    const existing = this.pendingEvents.get(key)

    if (existing) {
      // 合并调整数据
      existing.adjustments = [...(existing.adjustments || []), ...(data.adjustments || [])]
      existing.count = (existing.count || 0) + 1
    } else {
      this.pendingEvents.set(key, {
        ...data,
        count: 1,
        timestamp: Date.now(),
      })
    }
    this.scheduleEmit()
  }

  /**
   * 触发情绪反馈事件（自动合并）
   */
  triggerEmotionFeedback(feedback: any) {
    const key = 'algorithm:emotion-feedback-received'
    const existing = this.pendingEvents.get(key)

    if (existing) {
      existing.count = (existing.count || 0) + 1
      existing.lastFeedback = feedback
    } else {
      this.pendingEvents.set(key, {
        feedback,
        count: 1,
        timestamp: Date.now(),
      })
    }
    this.scheduleEmit()
  }

  /**
   * 安排发送
   */
  private scheduleEmit() {
    const now = Date.now()
    const timeSinceLastEmit = now - this.lastEmitTime

    if (this.updateTimer) {
      clearTimeout(this.updateTimer)
      this.updateTimer = null
    }

    if (timeSinceLastEmit >= this.MERGE_INTERVAL) {
      this.emitNow()
      return
    }

    const delay = Math.min(this.MAX_DELAY, this.MERGE_INTERVAL - timeSinceLastEmit)
    this.updateTimer = setTimeout(() => this.emitNow(), delay)
  }

  /**
   * 立即发送所有待处理事件
   */
  private emitNow() {
    this.pendingEvents.forEach((data, eventName) => {
      if (process.env.NODE_ENV === 'development') {
        console.log(`[AlgorithmEvent] 📢 ${eventName} (合并${data.count || 1}次)`)
      }

      // 添加合并信息
      const eventData = {
        ...data,
        merged: data.count > 1,
        mergedCount: data.count || 1,
      }

      EventManager.emit(eventName, eventData)
    })

    this.pendingEvents.clear()
    this.lastEmitTime = Date.now()
    this.updateTimer = null
  }

  /**
   * 强制立即发送
   */
  flush() {
    if (this.updateTimer) {
      clearTimeout(this.updateTimer)
      this.updateTimer = null
    }
    this.emitNow()
  }

  /**
   * 清理
   */
  cleanup() {
    if (this.updateTimer) {
      clearTimeout(this.updateTimer)
      this.updateTimer = null
    }
    this.pendingEvents.clear()
  }

  /**
   * 强制立即发送待处理事件
   */
  flushEvents() {
    if (this.updateTimer) {
      clearTimeout(this.updateTimer)
      this.updateTimer = null
    }
    this.emitNow()
  }
}

export class AlgorithmManager implements IAlgorithmManager {
  private static instance: AlgorithmManager

  // ✅ 添加存储键名
  private readonly STORAGE_KEY = 'algorithm_config'

  // ✅ 新增：统一管理取消函数
  private unsubscribeFns: (() => void)[] = []

  // ✅ 新增：统一管理销毁状态
  private destroyed = false

  // ✅ 新增：统一定时器管理
  private timers = {
    performanceFlush: null as ReturnType<typeof setTimeout> | null,
    healthCheck: null as ReturnType<typeof setTimeout> | null,
    warmupCheck: null as ReturnType<typeof setTimeout> | null,
    emotionDebounce: null as ReturnType<typeof setTimeout> | null,
  }

  // ✅ 新增：事件管理器
  private eventManager: AlgorithmEventManager

  // 添加批量更新防抖
  private batchUpdateTimer: ReturnType<typeof setTimeout> | null = null
  private pendingUpdates: Map<string, number> = new Map()

  // 核心状态
  private version = 1
  private currentAlgorithm = 'balanced'
  private customWeights: Record<string, number> | null = null
  private thresholds: Record<string, number> = { ...DEFAULT_THRESHOLDS }
  private initialized = false
  private initPromise: Promise<boolean> | null = null

  // 历史数据
  private performanceHistory: PerformanceRecord[] = []
  private performanceStats: Map<string, PerformanceStat> = new Map()

  // 情绪反馈历史
  private emotionFeedbackHistory: EmotionFeedback[] = []
  private weightAdjustmentHistory: EmotionAdjustment[] = []

  // 子模块
  private perfMonitor!: AlgorithmPerformanceMonitor
  private warmupManager!: AlgorithmWarmupManager
  private healthChecker!: AlgorithmHealthChecker
  private abTestManager!: AlgorithmABTestManager

  // 外部服务引用
  private sectorAnalyzer: SectorAnalyzer | null = null

  private constructor() {
    // 初始化子模块
    this.perfMonitor = new AlgorithmPerformanceMonitor(this)
    this.warmupManager = new AlgorithmWarmupManager(this)
    this.healthChecker = new AlgorithmHealthChecker(this)
    this.abTestManager = new AlgorithmABTestManager(this)

    // 初始化事件管理器
    this.eventManager = new AlgorithmEventManager()
  }

  async calculateScoresBulk(stocks: Stock[]): Promise<Map<string, ScoreResult>> {
    const versions = {
      algoVersion: this.version,
      stocks: dataLayer.getVersion().stocks,
      themes: dataLayer.getVersion().themes,
    }

    const keys = stocks.map((stock) => createCacheKey('score', stock.code, versions))

    // ✅ 使用异步批量缓存方法
    const computed = await stockCache.getOrComputeManyAsync(
      keys,
      async (missingKeys) => {
        const missingResults = new Map<string, ScoreResult>()

        // 并行计算缺失的股票
        await Promise.all(
          missingKeys.map(async (key) => {
            const code = key.split(':')[1]
            const stock = stocks.find((s) => s.code === code)
            if (stock) {
              const result = await this.calculateScore(stock)
              missingResults.set(key, result)
            }
          }),
        )

        return missingResults
      },
      'score',
      ['score:bulk'],
    )

    const results = new Map<string, ScoreResult>()
    computed.forEach((value, key) => {
      const code = key.split(':')[1]
      results.set(code, value)
    })

    return results
  }

  getAlgorithmFactors?(algorithmId: string): any[] {
    throw new Error('Method not implemented.')
  }

  static getInstance(): AlgorithmManager {
    if (!AlgorithmManager.instance) {
      AlgorithmManager.instance = new AlgorithmManager()
    }
    return AlgorithmManager.instance
  }

  // ========== 设置情绪监听 ==========
  private setupEmotionListener() {
    EventManager.on('breath:feedback', (feedback: EmotionFeedback) => {
      this.handleEmotionFeedback(feedback)
    })
  }

  // ========== 处理情绪反馈 ==========
  private readonly MAX_EMOTION_HISTORY = 100

  handleEmotionFeedback(feedback: EmotionFeedback) {
    if (this.destroyed || !feedback) return

    if (this.timers.emotionDebounce) {
      clearTimeout(this.timers.emotionDebounce)
    }

    this.timers.emotionDebounce = setTimeout(() => {
      if (this.destroyed) return

      this.emotionFeedbackHistory.push(feedback)
      // 统一使用 MAX_EMOTION_HISTORY
      if (this.emotionFeedbackHistory.length > this.MAX_EMOTION_HISTORY) {
        this.emotionFeedbackHistory = this.emotionFeedbackHistory.slice(-this.MAX_EMOTION_HISTORY)
      }

      const adjustments = this.adjustWeightsByPhase(feedback.phase)
      this.eventManager.triggerEmotionFeedback(feedback)

      this.timers.emotionDebounce = null
    }, 500)
  }

  /**
   * ✅ 获取状态（供外部调用）
   */
  getStatus(): any {
    if (this.destroyed) return null

    return {
      initialized: this.initialized,
      version: this.version,
      currentAlgorithm: this.currentAlgorithm,
      thresholds: this.thresholds,
      hasCustomWeights: !!this.customWeights,
      timers: {
        performanceFlush: !!this.timers.performanceFlush,
        healthCheck: !!this.timers.healthCheck,
        warmupCheck: !!this.timers.warmupCheck,
      },
      listeners: this.unsubscribeFns.length,
      performance: {
        historySize: this.performanceHistory.length,
        stats: this.getPerformanceStats(),
      },
      emotion: {
        feedbackCount: this.emotionFeedbackHistory.length,
        adjustmentsCount: this.weightAdjustmentHistory.length,
      },
    }
  }

  // ========== 根据情绪阶段调整权重 ==========
  adjustWeightsByPhase(phase: string): boolean {
    const adjustments = PHASE_ADJUSTMENTS[phase]
    if (!adjustments || Object.keys(adjustments).length === 0) {
      return false
    }

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    const adjustedFactors: Array<{ factorId: string; oldWeight: number; newWeight: number }> = []
    let hasChanges = false

    Object.entries(adjustments).forEach(([factorId, delta]) => {
      if (!algo.factors[factorId]) return

      const config = algo.factors[factorId]
      let oldWeight: number
      let newWeight: number

      if (typeof config.weight === 'number') {
        oldWeight = config.weight
        newWeight = oldWeight + delta
      } else if (config.baseWeight) {
        oldWeight = config.baseWeight
        newWeight = oldWeight + delta
      } else {
        return
      }

      if (config.min !== undefined && newWeight < config.min) {
        newWeight = config.min
      }
      if (config.max !== undefined && newWeight > config.max) {
        newWeight = config.max
      }

      if (Math.abs(newWeight - oldWeight) < 0.001) {
        return
      }

      // ✅ 直接更新权重，不调用 updateFactorWeight
      if (!this.customWeights) this.customWeights = {}
      this.customWeights[factorId] = newWeight
      hasChanges = true

      adjustedFactors.push({
        factorId,
        oldWeight,
        newWeight,
      })

      this.weightAdjustmentHistory.push({
        factorId,
        delta,
        oldWeight,
        newWeight,
        reason: `情绪阶段: ${phase}`,
        timestamp: Date.now(),
      })
    })

    if (this.weightAdjustmentHistory.length > 100) {
      this.weightAdjustmentHistory = this.weightAdjustmentHistory.slice(-100)
    }

    if (hasChanges) {
      // ✅ 保存到 localStorage
      this.saveToStorage()

      // ✅ 增加版本号并清除缓存
      this.version++
      stockCache.invalidateByTag('score')
      stockCache.invalidateByTag('algorithmStats')

      // ✅ 发送权重调整事件
      const eventData: WeightAdjustmentEvent = {
        phase,
        adjustments: adjustedFactors,
        timestamp: Date.now(),
      }
      this.eventManager.triggerWeightsAdjusted(eventData)
    }

    return adjustedFactors.length > 0
  }

  /**
   * 简单归一化 - 忽略边界限制
   */
  simpleNormalize(): boolean {
    if (this.destroyed) return false

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    // 获取所有启用的因子
    const enabledFactors: Array<{ id: string; weight: number }> = []
    let totalWeight = 0

    Object.entries(algo.factors).forEach(([factorId, config]: [string, any]) => {
      if (!config.enabled) return

      const weight =
        this.customWeights?.[factorId] ??
        (typeof config.weight === 'number' ? config.weight : config.baseWeight || 0)

      enabledFactors.push({ id: factorId, weight })
      totalWeight += weight
    })

    if (enabledFactors.length === 0) return false
    if (Math.abs(totalWeight - 1) < 0.001) return false

    // 简单归一化：直接按比例调整
    const factor = 1 / totalWeight
    let success = false

    enabledFactors.forEach(({ id, weight }) => {
      const newWeight = weight * factor
      // 直接更新，忽略边界
      const updated = this.updateFactorWeight(id, newWeight)
      if (updated) success = true
    })

    if (success) {
      console.log(`[AlgorithmManager] ✅ 简单归一化完成: ${(totalWeight * 100).toFixed(1)}% → 100%`)
      EventManager.emit('algorithm:weights-normalized', {
        timestamp: Date.now(),
        oldTotal: totalWeight,
        newTotal: 1,
      })
    }

    return success
  }

  /**
   * 获取权重总和
   */
  getTotalWeight(): number {
    if (this.destroyed) return 0

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return 0

    let total = 0
    Object.entries(algo.factors).forEach(([factorId, config]: [string, any]) => {
      if (!config.enabled) return

      const weight =
        this.customWeights?.[factorId] ??
        (typeof config.weight === 'number' ? config.weight : config.baseWeight || 0)
      total += weight
    })

    return total
  }

  // ========== 动态调整单个因子权重 =====
  adjustFactorWeight(factorId: string, delta: number): boolean {
    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo || !algo.factors[factorId]) return false

    const config = algo.factors[factorId]
    let newWeight: number

    if (typeof config.weight === 'number') {
      newWeight = config.weight + delta
    } else if (config.baseWeight) {
      newWeight = config.baseWeight + delta
    } else {
      return false
    }

    if (config.min !== undefined && newWeight < config.min) newWeight = config.min
    if (config.max !== undefined && newWeight > config.max) newWeight = config.max

    return this.updateFactorWeight(factorId, newWeight)
  }

  // ========== 获取情绪反馈历史 ==========
  getEmotionFeedbackHistory(limit: number = 10): EmotionFeedback[] {
    return this.emotionFeedbackHistory.slice(-limit)
  }

  // ========== 获取权重调整历史 ==========
  getWeightAdjustmentHistory(limit: number = 20): EmotionAdjustment[] {
    return this.weightAdjustmentHistory.slice(-limit)
  }

  // ========== 获取情绪阶段统计 ==========
  getEmotionStats() {
    const stats: Record<string, { count: number; avgScore: number }> = {}

    this.emotionFeedbackHistory.forEach((f) => {
      if (!stats[f.phase]) {
        stats[f.phase] = { count: 0, avgScore: 0 }
      }
      stats[f.phase].count++
      stats[f.phase].avgScore =
        (stats[f.phase].avgScore * (stats[f.phase].count - 1) + f.score) / stats[f.phase].count
    })

    return stats
  }

  // ✅ 从 localStorage 加载配置
  private loadFromStorage(): void {
    try {
      // 1. 加载上次使用的算法
      const saved = localStorage.getItem(this.STORAGE_KEY)
      if (saved) {
        const config = JSON.parse(saved)
        console.log('[AlgorithmManager] 从 localStorage 加载配置:', config)

        // 恢复上次使用的算法
        if (config.currentAlgorithm && ALGORITHMS[config.currentAlgorithm]) {
          this.currentAlgorithm = config.currentAlgorithm
        }

        // 恢复阈值
        if (config.thresholds) {
          this.thresholds = { ...this.thresholds, ...config.thresholds }
        }

        // 恢复当前算法的自定义权重
        if (config.customWeights) {
          this.customWeights = config.customWeights
        }
      }

      // 2. 确保加载当前算法的特定配置（覆盖）
      this.loadCustomWeightsForAlgorithm(this.currentAlgorithm)
    } catch (e) {
      console.warn('[AlgorithmManager] 加载配置失败:', e)
    }
  }

  // ✅ 保存配置到 localStorage
  private saveToStorage(): void {
    try {
      // 保存当前算法的配置
      const config = {
        currentAlgorithm: this.currentAlgorithm,
        customWeights: this.customWeights,
        thresholds: this.thresholds,
        version: this.version,
        timestamp: Date.now(),
      }

      // 保存当前算法配置到专用key
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(config))

      // 同时保存到算法特定的key，便于切换时恢复
      if (this.customWeights) {
        localStorage.setItem(
          `${this.STORAGE_KEY}_${this.currentAlgorithm}`,
          JSON.stringify({ customWeights: this.customWeights }),
        )
      }

      console.log('[AlgorithmManager] 配置已保存:', config)
    } catch (e) {
      console.error('[AlgorithmManager] 保存配置失败:', e)
    }
  }

  // ========== 初始化 ==========
  public async init(): Promise<() => void> {
    if (this.destroyed) {
      console.warn('[AlgorithmManager] 实例已销毁，无法初始化')
      return () => {}
    }

    if (this.initialized) {
      return () => this.destroy()
    }

    if (this.initPromise) {
      await this.initPromise
      return () => this.destroy()
    }

    this.initPromise = new Promise(async (resolve) => {
      console.log('[AlgorithmManager] 🧠 算法管理器初始化中...')

      try {
        // 1. 从 localStorage 加载配置
        this.loadFromStorage()

        // 2. 如果有自定义权重，应用到算法
        if (this.customWeights) {
          this.applyCustomWeights()
        }

        // 3. 加载历史数据
        this.loadHistory()

        // 4. 连接外部服务
        this.tryConnectServices()

        // 5. 设置所有事件监听
        this.setupListeners()

        // 6. 启动定时器
        this.startTimers()

        // 7. 启动子模块
        this.perfMonitor.start()
        this.warmupManager.start()
        this.healthChecker.start()

        // 8. 验证配置
        const validation = await this.healthChecker.checkNow()
        if (!validation.valid) {
          console.warn('[AlgorithmManager] ⚠️ 配置验证发现警告:', validation.warnings)
        }

        this.initialized = true
        this.version++

        console.log('[AlgorithmManager] ✅ 初始化完成，当前配置:', this.getStatus())

        // ✅ 发送初始化完成事件
        EventManager.emit('algorithm:initialized', this.getStatus())
        EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())

        resolve(true)
      } catch (error) {
        console.error('[AlgorithmManager] 初始化失败:', error)
        this.initPromise = null
        resolve(false)
      }
    })

    await this.initPromise
    return () => this.destroy()
  }

  /**
   * 设置所有事件监听（保存取消函数）
   */
  private setupListeners(): void {
    const unsubDataMerged = EventManager.on(AppEvents.DATA.MERGED, () => {
      if (this.destroyed) return
      this.invalidateCache()
    })
    this.unsubscribeFns.push(unsubDataMerged)

    const unsubAlgorithmChanged = EventManager.on(AppEvents.ALGORITHM.CHANGED, () => {
      if (this.destroyed) return
      this.invalidateCache()
    })
    this.unsubscribeFns.push(unsubAlgorithmChanged)

    const unsubBreath = EventManager.on(AppEvents.BREATH.FEEDBACK, (feedback: EmotionFeedback) => {
      if (this.destroyed) return
      this.handleEmotionFeedback(feedback)
    })
    this.unsubscribeFns.push(unsubBreath)

    // ✅ 新增：监听权重调整事件
    const unsubWeightsAdjusted = EventManager.on(AppEvents.ALGORITHM.WEIGHTS_ADJUSTED, () => {
      if (this.destroyed) return
      // 权重调整后重新计算缓存
      this.invalidateCache()
    })
    this.unsubscribeFns.push(unsubWeightsAdjusted)

    const unsubFull = EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, () => {
      if (this.destroyed) return
      console.log('[AlgorithmManager] 🔄 收到全量刷新请求')
      this.handleFullRefresh()
    })
    this.unsubscribeFns.push(unsubFull)

    const unsubBatch = EventManager.on(AppEvents.INCREMENTAL.BATCH_COMPLETED, (data: any) => {
      if (this.destroyed) return
      if (data?.updatedCodes?.length) {
        this.warmupManager.warmupStocks?.(data.updatedCodes)
      }
    })
    this.unsubscribeFns.push(unsubBatch)
  }

  /**
   * ✅ 启动所有定时器
   */
  private startTimers(): void {
    if (this.timers.performanceFlush) {
      clearTimeout(this.timers.performanceFlush)
    }
    this.timers.performanceFlush = setInterval(() => {
      if (this.destroyed) return
      this.perfMonitor.flushStats?.()
    }, 60000)

    if (this.timers.healthCheck) {
      clearTimeout(this.timers.healthCheck)
    }
    this.timers.healthCheck = setInterval(
      () => {
        if (this.destroyed) return
        this.healthChecker.checkNow()
      },
      5 * 60 * 1000,
    )

    if (this.timers.warmupCheck) {
      clearTimeout(this.timers.warmupCheck)
    }
    this.timers.warmupCheck = setInterval(() => {
      if (this.destroyed) return
      this.warmupManager.checkProgress?.()
    }, 30000)
  }

  /**
   * ✅ 停止所有定时器
   */
  private stopTimers(): void {
    Object.values(this.timers).forEach((timer) => {
      if (timer) {
        clearInterval(timer)
        clearTimeout(timer)
      }
    })
    this.timers = {
      performanceFlush: null,
      healthCheck: null,
      warmupCheck: null,
      emotionDebounce: null,
    }
  }

  /**
   * ✅ 处理全量刷新
   */
  private handleFullRefresh(): void {
    this.invalidateCache()
    this.perfMonitor.resetStats?.()
    this.healthChecker.checkNow()
  }

  // ========== 核心计算逻辑 ==========
  // 找到 calculateScore 方法（约第530行）
  async calculateScore(stock: Stock): Promise<ScoreResult> {
    const startTime = performance.now()

    try {
      const algorithmId = this.abTestManager.getAlgorithmForStock(stock.code)
      const algo = ALGORITHMS[algorithmId] || ALGORITHMS[this.currentAlgorithm]

      if (!algo) {
        return this.getDefaultScore()
      }

      const versions = {
        algoVersion: this.version,
        stocks: dataLayer.getVersion().stocks,
        themes: dataLayer.getVersion().themes,
      }

      const cacheKey = createCacheKey('score', stock.code, versions)

      // 使用异步缓存方法
      const result = await stockCache.getOrComputeAsync(
        cacheKey,
        async () => {
          const internalResult = await this.calculateScoreInternal(stock, algo, algorithmId)

          // ===== 关键修复：确保分数是有效数字 =====
          let safeScore = 50 // 默认值

          if (internalResult && typeof internalResult.score === 'number') {
            safeScore = internalResult.score
          } else if (internalResult && typeof internalResult.score === 'string') {
            safeScore = parseFloat(internalResult.score) || 50
          }

          // 确保在0-100范围内
          safeScore = Math.min(100, Math.max(0, safeScore))

          return {
            ...internalResult,
            score: safeScore,
          }
        },
        'score',
        [`score:${stock.code}`],
      )

      const calcTime = performance.now() - startTime
      this.perfMonitor.recordCalculation(stock.code, calcTime)

      if (algorithmId !== this.currentAlgorithm) {
        this.abTestManager.recordResult(algorithmId, {
          algorithmId,
          stockCode: stock.code,
          score: result.score,
          success: result.score > 60,
        })
      }

      return result
    } catch (error) {
      console.error(`[AlgorithmManager] 计算失败: ${stock.code}`, error)
      return this.getDefaultScore()
    }
  }

  private async calculateScoreInternal(
    stock: Stock,
    algo: any,
    algorithmId: string,
  ): Promise<ScoreResult> {
    const phase = this.getCurrentMarketPhase()
    const multipliers = phase ? PHASE_MULTIPLIERS[phase] || {} : {}

    let totalScore = 0
    let totalWeight = 0
    const details: Record<string, any> = {}

    // 使用 Promise.all 并行计算所有因子
    const factorPromises = Object.entries(algo.factors).map(
      async ([factorId, config]: [string, any]) => {
        if (!config.enabled) return null

        const factor = FACTORS[factorId]
        if (!factor) return null

        const startTime = performance.now()
        let success = true

        try {
          // 确保因子计算返回数字
          let rawScore = 50 // 默认值
          try {
            const calculated = await factor.calculate(stock)
            // ===== 关键修复：确保 rawScore 是数字 =====
            if (typeof calculated === 'number' && !isNaN(calculated)) {
              rawScore = calculated
            } else if (typeof calculated === 'string') {
              rawScore = parseFloat(calculated) || 50
            } else {
              rawScore = 50
            }
          } catch (e) {
            console.warn(`[AlgorithmManager] 因子 ${factorId} 计算失败，使用默认值:`, e)
            rawScore = 50
            success = false
          }

          // 确保 rawScore 在 0-100 之间
          rawScore = Math.min(100, Math.max(0, rawScore))

          let weight = config.weight
          if (weight === 'dynamic') {
            weight = config.baseWeight || 0.1
            const multiplier = multipliers[factorId] || 1
            weight = Math.min(config.max || 0.3, Math.max(config.min || 0.03, weight * multiplier))
          }

          // 确保 weight 是数字
          weight = typeof weight === 'number' ? weight : 0.1

          const contribution = rawScore * weight

          const calcTime = performance.now() - startTime
          this.perfMonitor.recordFactorPerformance(factorId, calcTime, success, contribution)

          return {
            factorId,
            detail: {
              name: factor.name || factorId,
              score: rawScore,
              weight,
              contribution,
            },
            contribution,
            weight,
          }
        } catch (error) {
          console.warn(`[AlgorithmManager] 因子 ${factorId} 处理失败:`, error)
          return null
        }
      },
    )

    // 等待所有因子计算完成
    const results = await Promise.all(factorPromises)

    // 汇总结果
    results.forEach((result) => {
      if (result) {
        details[result.factorId] = result.detail
        totalScore += result.contribution || 0
        totalWeight += result.weight || 0
      }
    })

    // 计算最终分数
    let finalScore = totalWeight > 0 ? totalScore / totalWeight : 50

    // ===== 关键修复：确保 finalScore 是有效数字 =====
    if (typeof finalScore !== 'number' || isNaN(finalScore)) {
      finalScore = 50
    }

    // 确保分数在0-100之间
    finalScore = Math.min(100, Math.max(0, Number(finalScore.toFixed(2))))

    return {
      score: finalScore,
      details,
      timestamp: Date.now(),
      algorithm: algorithmId,
      algorithmName: algo.name || '未知',
    }
  }

  private getDefaultScore(): ScoreResult {
    return {
      score: 50,
      details: {},
      timestamp: Date.now(),
      algorithm: this.currentAlgorithm,
      algorithmName: ALGORITHMS[this.currentAlgorithm]?.name || '未知',
    }
  }

  // ========== 缓存管理 ==========

  invalidateCache(): void {
    this.version++
    stockCache.invalidateByTag('score')
    stockCache.invalidateByTag('algorithmStats')
  }

  clearCache(): void {
    this.version++
    stockCache.invalidateByTag('score')
    stockCache.invalidateByTag('algorithmStats')
    stockCache.invalidateByTag('factor:analysis')
  }

  // ========== 配置管理 ==========

  private applyCustomWeights(): void {
    if (!this.customWeights) return

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return

    Object.entries(this.customWeights).forEach(([factorId, weight]) => {
      if (algo.factors[factorId]) {
        algo.factors[factorId].weight = weight
      }
    })

    this.version++
  }

  // ========== 历史数据管理 ==========

  private loadHistory(): void {
    if (typeof window === 'undefined') return

    try {
      const savedHistory = localStorage.getItem(STORAGE_KEYS.HISTORY)
      if (savedHistory) {
        const history = JSON.parse(savedHistory)
        this.performanceHistory = history.slice(-200)
        this.rebuildStats()
      }
    } catch (e) {
      console.warn('[AlgorithmManager] 加载历史数据失败:', e)
    }
  }

  private rebuildStats(): void {
    this.performanceStats.clear()
    this.performanceHistory.forEach((record) => {
      let stat = this.performanceStats.get(record.algorithm)
      if (!stat) {
        stat = { count: 0, successCount: 0, totalScore: 0, avgScore: 0, successRate: '0%' }
        this.performanceStats.set(record.algorithm, stat)
      }
      stat.count++
      stat.totalScore += record.score
      if (record.success) stat.successCount++
      stat.avgScore = stat.totalScore / stat.count
      stat.successRate = ((stat.successCount / stat.count) * 100).toFixed(1) + '%'
    })
  }

  recordPerformance(algorithmId: string, score: number, success: boolean = true): void {
    const record: PerformanceRecord = {
      algorithm: algorithmId,
      score,
      success,
      timestamp: Date.now(),
    }

    this.performanceHistory.push(record)
    if (this.performanceHistory.length > 200) {
      this.performanceHistory = this.performanceHistory.slice(-200)
    }

    let stat = this.performanceStats.get(algorithmId)
    if (!stat) {
      stat = { count: 0, successCount: 0, totalScore: 0, avgScore: 0, successRate: '0%' }
      this.performanceStats.set(algorithmId, stat)
    }

    stat.count++
    stat.totalScore += score
    if (success) stat.successCount++
    stat.avgScore = stat.totalScore / stat.count
    stat.successRate = ((stat.successCount / stat.count) * 100).toFixed(1) + '%'

    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEYS.HISTORY, JSON.stringify(this.performanceHistory))
    }
  }

  // ========== 服务连接 ==========

  private tryConnectServices(): void {
    if (typeof window === 'undefined') return

    if ((window as any).sectorAnalyzer) {
      this.sectorAnalyzer = (window as any).sectorAnalyzer
    }

    EventManager.on('sector:ready', () => {
      if ((window as any).sectorAnalyzer) {
        this.sectorAnalyzer = (window as any).sectorAnalyzer
      }
    })
  }

  private getCurrentMarketPhase(): string | undefined {
    try {
      return (window as any).dragonBreathAnalyzer?.getMarketSentiment?.().phase
    } catch {
      return undefined
    }
  }

  // ========== 公共API ==========
  getCurrentAlgorithm(): any {
    if (this.destroyed) {
      console.warn('[AlgorithmManager] 尝试在已销毁实例上调用 getCurrentAlgorithm')
      return null
    }
    return ALGORITHMS[this.currentAlgorithm] || ALGORITHMS.balanced
  }

  getAlgorithmList() {
    if (this.destroyed) return
    return Object.entries(ALGORITHMS).map(([id, algo]) => ({
      id,
      name: algo.name,
      icon: algo.icon,
      description: algo.description,
      category: algo.category,
      color: algo.color,
      factorCount: Object.keys(algo.factors).length,
      isActive: id === this.currentAlgorithm,
    }))
  }

  setAlgorithm(algorithmId: string): boolean {
    if (this.destroyed) return false
    if (!ALGORITHMS[algorithmId]) return false

    // 1. 切换算法
    this.currentAlgorithm = algorithmId

    // 2. 重要：切换算法时，从 localStorage 加载该算法的自定义权重
    this.loadCustomWeightsForAlgorithm(algorithmId)

    // 3. 保存当前配置到 localStorage
    this.saveToStorage()

    // 4. 清除缓存
    this.invalidateCache()

    // 5. 发送事件
    EventManager.emit('algorithm:config-changed', this.getStatus())
    EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())

    return true
  }

  // 新增：加载特定算法的自定义权重
  private loadCustomWeightsForAlgorithm(algorithmId: string): void {
    try {
      // 从 localStorage 读取该算法的保存的权重
      const saved = localStorage.getItem(`${this.STORAGE_KEY}_${algorithmId}`)
      if (saved) {
        const config = JSON.parse(saved)
        this.customWeights = config.customWeights || null
        console.log(`[AlgorithmManager] 加载算法 ${algorithmId} 的自定义权重:`, this.customWeights)
      } else {
        // 没有保存的自定义权重，清空
        this.customWeights = null
      }
    } catch (e) {
      console.warn(`[AlgorithmManager] 加载算法 ${algorithmId} 配置失败:`, e)
      this.customWeights = null
    }
  }

  getFactorWeights(algorithmId?: string): any[] {
    if (this.destroyed) {
      console.warn('[AlgorithmManager] 实例已销毁，返回空数组')
      return []
    }

    const algoId = algorithmId || this.currentAlgorithm
    const algo = ALGORITHMS[algoId]

    if (!algo) {
      console.warn(`[AlgorithmManager] 未找到算法: ${algoId}`)
      return []
    }

    return Object.entries(algo.factors).map(([factorId, config]: [string, any]) => {
      const factor = FACTORS[factorId]
      if (!factor) {
        console.warn(`[AlgorithmManager] 未找到因子: ${factorId}`)
      }

      const weight =
        this.customWeights?.[factorId] ??
        (typeof config.weight === 'number' ? config.weight : config.baseWeight || 0)

      return {
        id: factorId,
        name: factor?.name || factorId,
        type: factor?.type || 'unknown',
        description: factor?.description || '',
        weight,
        enabled: config.enabled,
        min: config.min,
        max: config.max,
        baseWeight: config.baseWeight,
      }
    })
  }

  updateFactorWeight(factorId: string, weight: number): boolean {
    if (this.destroyed) return false
    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo || !algo.factors[factorId]) return false

    const config = algo.factors[factorId]
    if (config.min !== undefined && weight < config.min) return false
    if (config.max !== undefined && weight > config.max) return false

    // 更新内存中的权重
    if (!this.customWeights) this.customWeights = {}
    this.customWeights[factorId] = weight

    // 立即保存到 localStorage
    this.saveToStorage()

    // 清除缓存
    this.invalidateCache()

    // 发送事件
    EventManager.emit('algorithm:config-saved', {
      factorId,
      weight,
      timestamp: Date.now(),
    })

    return true
  }

  resetWeights(): boolean {
    if (this.destroyed) return false
    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    const defaultAlgo = ALGORITHMS[this.currentAlgorithm]
    algo.factors = JSON.parse(JSON.stringify(defaultAlgo.factors))

    this.customWeights = null
    this.saveToStorage()
    this.invalidateCache()

    // ✅ 发送配置变更事件（完整变更）
    EventManager.emit('algorithm:config-changed', this.getStatus())

    return true
  }

  normalizeWeights(): boolean {
    if (this.destroyed) return false

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    // 获取当前所有因子的权重
    const weights: Record<string, number> = {}
    let totalWeight = 0

    Object.entries(algo.factors).forEach(([factorId, config]: [string, any]) => {
      if (!config.enabled) return

      const weight =
        this.customWeights?.[factorId] ??
        (typeof config.weight === 'number' ? config.weight : config.baseWeight || 0)

      weights[factorId] = weight
      totalWeight += weight
    })

    if (Math.abs(totalWeight - 1) < 0.001) return false

    // 计算归一化因子
    const normalizeFactor = 1 / totalWeight

    // 应用归一化
    Object.entries(weights).forEach(([factorId, weight]) => {
      const normalizedWeight = weight * normalizeFactor
      const config = algo.factors[factorId]
      let finalWeight = normalizedWeight

      if (config.min !== undefined && finalWeight < config.min) {
        finalWeight = config.min
      }
      if (config.max !== undefined && finalWeight > config.max) {
        finalWeight = config.max
      }

      // 直接更新，会触发 saveToStorage
      this.updateFactorWeight(factorId, finalWeight)
    })

    console.log('[AlgorithmManager] ✅ 权重归一化完成')

    // 发送归一化事件
    EventManager.emit('algorithm:weights-normalized', {
      timestamp: Date.now(),
      oldTotal: totalWeight,
      newTotal: 1,
    })

    return true
  }

  getThresholds(): Record<string, number> {
    if (this.destroyed) return {}
    return { ...this.thresholds }
  }

  updateThreshold(key: string, value: number): boolean {
    if (this.destroyed) return false
    if (!(key in this.thresholds)) return false

    this.thresholds[key] = value
    this.saveToStorage()
    this.invalidateCache()

    // ✅ 发送配置变更事件（完整变更）
    EventManager.emit('algorithm:config-changed', this.getStatus())
    return true
  }

  getPerformanceStats(): Record<string, PerformanceStat> {
    if (this.destroyed) return {}
    const stats: Record<string, PerformanceStat> = {}
    this.performanceStats.forEach((stat, id) => {
      stats[id] = { ...stat }
    })
    return stats
  }

  getVersion(): number {
    if (this.destroyed) return 0
    return this.version
  }

  getFullStatus() {
    if (this.destroyed) return null
    return {
      version: this.version,
      currentAlgorithm: this.currentAlgorithm,
      thresholds: this.thresholds,
      customWeights: this.customWeights,
      performance: {
        historySize: this.performanceHistory.length,
        stats: this.getPerformanceStats(),
      },
      cacheStats: stockCache.getStats(),
      warmupProgress: this.warmupManager.getAllProgress(),
      healthCheck: this.healthChecker.getLastCheckResult(),
      abTests: this.abTestManager.getAllTests().length,
      emotion: {
        feedbackCount: this.emotionFeedbackHistory.length,
        adjustmentsCount: this.weightAdjustmentHistory.length,
        stats: this.getEmotionStats(),
      },
    }
  }

  getLeaderThresholds(): Record<string, number> {
    if (this.destroyed) return {}
    return {
      totalLeader: this.thresholds.totalLeader || 80,
      continuousLeader: this.thresholds.continuousLeader || 70,
      sectorLeader: this.thresholds.sectorLeader || 65,
      middleLeader: this.thresholds.middleLeader || 60,
      emotionLeader: this.thresholds.emotionLeader || 55,
    }
  }

  // 子模块获取方法
  getPerfMonitor(): AlgorithmPerformanceMonitor {
    if (this.destroyed) return null as any
    return this.perfMonitor
  }

  getABTestManager(): AlgorithmABTestManager {
    if (this.destroyed) return null as any
    return this.abTestManager
  }

  getWarmupManager(): AlgorithmWarmupManager {
    if (this.destroyed) return null as any
    return this.warmupManager
  }

  getHealthChecker(): AlgorithmHealthChecker {
    if (this.destroyed) return null as any
    return this.healthChecker
  }

  /**
   * 销毁实例
   */
  public destroy(): void {
    if (this.destroyed) return

    console.log('[AlgorithmManager] 💥 开始销毁...')
    this.destroyed = true
    this.initialized = false

    this.stopTimers()

    this.unsubscribeFns.forEach((fn) => {
      try {
        fn()
      } catch (e) {
        console.warn('[AlgorithmManager] 清理监听失败:', e)
      }
    })
    this.unsubscribeFns = []

    if (this.eventManager) {
      this.eventManager.cleanup()
    }

    this.perfMonitor.stop?.()
    this.warmupManager.stop?.()
    this.healthChecker.stop?.()
    this.abTestManager.stop?.()

    this.clearCache()
    this.performanceHistory = []
    this.performanceStats.clear()
    this.emotionFeedbackHistory = []
    this.weightAdjustmentHistory = []

    this.initPromise = null

    console.log('[AlgorithmManager] ✅ 已销毁')
  }
}

// 导出单例
export const algorithmManager = AlgorithmManager.getInstance()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).algorithmManager = algorithmManager
}
