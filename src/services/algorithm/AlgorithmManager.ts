import { debugLog } from '@/utils/logger'
// src/services/Algorithm/AlgorithmManager.ts
// 优化版 - 改为服务模式，供协调者调用

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
import { consistencyManager } from './ConsistencyManager'
import { themeSyncAdapter } from '@/services/theme/ThemeSyncAdapter'

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
  adjustments: Array<{ factorId: string; delta?: number; oldWeight: number; newWeight: number }>
  timestamp: number
}

const THRESHOLD_RANGES: Record<string, { min: number; max: number }> = {
  totalLeader: { min: 60, max: 95 },
  sectorLeader: { min: 50, max: 90 },
  continuousLeader: { min: 50, max: 90 },
  middleLeader: { min: 40, max: 85 },
  emotionLeader: { min: 40, max: 85 },
}

// 主协调器接口
export interface IAlgorithmManager {
  getCurrentAlgorithm(): any
  calculateScore(stock: Stock): Promise<ScoreResult>
  calculateScoresBulk(stocks: Stock[]): Promise<Map<string, ScoreResult>>
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
  private pendingEvents: Map<string, any> = new Map()
  private lastEmitTime = 0

  triggerAlgorithmChanged(algorithm: any) {
    this.pendingEvents.set('algorithm-changed', {
      algorithm,
      timestamp: Date.now(),
    })
    EventManager.emit('algorithm:has-pending-events', {
      type: 'changed',
      timestamp: Date.now(),
    })
  }

  triggerWeightsAdjusted(data: any) {
    const key = 'algorithm:weights-adjusted'
    const existing = this.pendingEvents.get(key)

    if (existing) {
      existing.adjustments = [...(existing.adjustments || []), ...(data.adjustments || [])]
      existing.count = (existing.count || 0) + 1
    } else {
      this.pendingEvents.set(key, {
        ...data,
        count: 1,
        timestamp: Date.now(),
      })
    }
    EventManager.emit('algorithm:has-pending-events', {
      type: 'weights',
      timestamp: Date.now(),
    })
  }

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
    EventManager.emit('algorithm:has-pending-events', {
      type: 'emotion',
      timestamp: Date.now(),
    })
  }

  /**
   * 由协调者调用，处理待发送事件
   */
  flush(): void {
    this.pendingEvents.forEach((data, eventName) => {
      if (process.env.NODE_ENV === 'development') {
        debugLog(`[AlgorithmEvent] 📢 ${eventName} (合并${data.count || 1}次)`)
      }

      const eventData = {
        ...data,
        merged: data.count > 1,
        mergedCount: data.count || 1,
      }

      EventManager.emit(eventName, eventData)
    })

    this.pendingEvents.clear()
    this.lastEmitTime = Date.now()
  }

  cleanup() {
    this.pendingEvents.clear()
  }
}

export class AlgorithmManager implements IAlgorithmManager {
  private static instance: AlgorithmManager

  private readonly STORAGE_KEY = 'algorithm_config'

  private unsubscribeFns: (() => void)[] = []

  private destroyed = false

  private timers = {
    performanceFlush: null as ReturnType<typeof setTimeout> | null,
    healthCheck: null as ReturnType<typeof setTimeout> | null,
    warmupCheck: null as ReturnType<typeof setTimeout> | null,
    emotionDebounce: null as ReturnType<typeof setTimeout> | null,
  }

  private eventManager: AlgorithmEventManager

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
    this.perfMonitor = new AlgorithmPerformanceMonitor(this)
    this.warmupManager = new AlgorithmWarmupManager(this, () => ({
      dataLayer,
      sectorAnalyzer: (window as any).sectorAnalyzer,
      dragonAnalyzer: (window as any).dragonAnalyzer,
    }))
    this.healthChecker = new AlgorithmHealthChecker(this, consistencyManager)
    this.abTestManager = new AlgorithmABTestManager(this)

    this.eventManager = new AlgorithmEventManager()
  }

  async calculateScoresBulk(stocks: Stock[]): Promise<Map<string, ScoreResult>> {
    const versions = {
      algoVersion: this.version,
      stocks: dataLayer.getVersion().stocks,
      themes: dataLayer.getVersion().themes,
    }

    const keys = stocks.map((stock) => createCacheKey('score', stock.code, versions))

    const computed = await stockCache.getOrComputeManyAsync(
      keys,
      async (missingKeys) => {
        const missingResults = new Map<string, ScoreResult>()

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

  getAlgorithmFactors(algorithmId: string): any[] {
    return this.getFactorWeights(algorithmId)
  }

  static getInstance(): AlgorithmManager {
    if (!AlgorithmManager.instance) {
      AlgorithmManager.instance = new AlgorithmManager()
    }
    return AlgorithmManager.instance
  }

  // ========== 处理情绪反馈 ==========
  private readonly MAX_EMOTION_HISTORY = 100

  handleEmotionFeedback(feedback: EmotionFeedback) {
    if (this.destroyed || !feedback) return

    this.emotionFeedbackHistory.push(feedback)
    if (this.emotionFeedbackHistory.length > this.MAX_EMOTION_HISTORY) {
      this.emotionFeedbackHistory = this.emotionFeedbackHistory.slice(-this.MAX_EMOTION_HISTORY)
    }

    const adjustments = this.adjustWeightsByPhase(feedback.phase)

    EventManager.emit('algorithm:has-pending-feedback', {
      feedback,
      adjustments,
      timestamp: Date.now(),
    })
  }

  // ========== 供协调者调用的方法 ==========

  /**
   * 全量更新 - 供协调者调用
   */
  async runFullUpdate(): Promise<void> {
    if (this.destroyed) return
    debugLog('[AlgorithmManager] 执行全量更新')

    this.invalidateCache()
    this.perfMonitor.flushStats?.()
    this.healthChecker.checkNow()
    this.eventManager.flush()
  }

  /**
   * 增量更新 - 供协调者调用
   */
  async runIncrementalUpdate(codes?: string[]): Promise<void> {
    if (this.destroyed) return
    debugLog('[AlgorithmManager] 执行增量更新')

    if (codes?.length) {
      this.warmupManager.warmupStocks?.(codes)
    }
  }

  /**
   * 同步数据 - 供协调者调用
   */
  async syncData(): Promise<void> {
    if (this.destroyed) return
    debugLog('[AlgorithmManager] 同步数据')
    // 算法管理器主要是计算，不需要同步数据到 DataLayer
  }

  /**
   * 后台维护 - 供协调者调用
   */
  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    debugLog('[AlgorithmManager] 执行后台维护')

    this.eventManager.flush()
    stockCache.cleanup?.()
    this.warmupManager.checkProgress?.()
    this.healthChecker.checkNow()
  }

  /**
   * 处理待处理的情绪反馈
   */
  async processPendingFeedback(): Promise<void> {
    // 如果有需要处理的情绪反馈，可以在这里处理
  }

  /**
   * 获取状态
   */
  getStatus(): any {
    if (this.destroyed) return null

    return {
      initialized: this.initialized,
      version: this.version,
      currentAlgorithm: this.currentAlgorithm,
      thresholds: this.thresholds,
      hasCustomWeights: !!this.customWeights,
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
    const adjustments = (PHASE_ADJUSTMENTS as Record<string, Record<string, number>>)[phase]
    if (!adjustments || Object.keys(adjustments).length === 0) {
      return false
    }

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    const adjustedFactors: Array<{
      factorId: string
      delta: number
      oldWeight: number
      newWeight: number
    }> = []
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

      if (!this.customWeights) this.customWeights = {}
      this.customWeights[factorId] = newWeight
      hasChanges = true

      adjustedFactors.push({
        factorId,
        delta,
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
      this.saveToStorage()
      this.version++
      stockCache.invalidateByTag('score')
      stockCache.invalidateByTag('algorithmStats')

      const eventData: WeightAdjustmentEvent = {
        phase,
        adjustments: adjustedFactors,
        timestamp: Date.now(),
      }
      this.eventManager.triggerWeightsAdjusted(eventData)
    }

    return adjustedFactors.length > 0
  }

  // ========== 从 localStorage 加载配置 ==========
  private loadFromStorage(): void {
    try {
      const saved = localStorage.getItem(this.STORAGE_KEY)
      if (saved) {
        const config = JSON.parse(saved)
        debugLog('[AlgorithmManager] 从 localStorage 加载配置:', config)

        if (config.currentAlgorithm && ALGORITHMS[config.currentAlgorithm]) {
          this.currentAlgorithm = config.currentAlgorithm
        }

        if (config.thresholds) {
          this.thresholds = { ...this.thresholds, ...config.thresholds }
        }

        if (config.customWeights) {
          this.customWeights = config.customWeights
        }
      }

      this.loadCustomWeightsForAlgorithm(this.currentAlgorithm)
    } catch (e) {
      console.warn('[AlgorithmManager] 加载配置失败:', e)
    }
  }

  private saveToStorage(): void {
    try {
      const config = {
        currentAlgorithm: this.currentAlgorithm,
        customWeights: this.customWeights,
        thresholds: this.thresholds,
        version: this.version,
        timestamp: Date.now(),
      }

      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(config))

      if (this.customWeights) {
        localStorage.setItem(
          `${this.STORAGE_KEY}_${this.currentAlgorithm}`,
          JSON.stringify({ customWeights: this.customWeights }),
        )
      }

      debugLog('[AlgorithmManager] 配置已保存:', config)
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
      debugLog('[AlgorithmManager] 🧠 算法管理器初始化中...')

      try {
        this.loadFromStorage()

        if (this.customWeights) {
          this.applyCustomWeights()
        }

        this.loadHistory()
        this.tryConnectServices()
        this.setupEssentialListeners() // 只保留必要的监听器

        // 启动子模块
        this.perfMonitor.start()
        this.warmupManager.start()
        this.healthChecker.start()

        const validation = await this.healthChecker.checkNow()
        if (!validation.valid) {
          console.warn('[AlgorithmManager] ⚠️ 配置验证发现警告:', validation.warnings)
        }

        this.initialized = true
        this.version++

        debugLog('[AlgorithmManager] ✅ 初始化完成，当前配置:', this.getStatus())

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
   * 设置必要的监听器 - 只保留最基本的
   */
  private setupEssentialListeners(): void {
    const listeners = [
      // 监听数据合并，清除缓存
      EventManager.on(AppEvents.DATA.MERGED, () => {
        if (this.destroyed) return
        this.invalidateCache()
      }),

      // 监听算法变化
      EventManager.on(AppEvents.ALGORITHM.CHANGED, () => {
        if (this.destroyed) return
        this.invalidateCache()
      }),

      // 监听情绪反馈
      EventManager.on(AppEvents.BREATH.FEEDBACK, (feedback: EmotionFeedback) => {
        if (this.destroyed) return
        this.handleEmotionFeedback(feedback)
      }),

      // 监听权重调整
      EventManager.on(AppEvents.ALGORITHM.WEIGHTS_ADJUSTED, () => {
        if (this.destroyed) return
        this.invalidateCache()
      }),

      // ✅ 新增：监听算法分数更新事件，批量更新到 DataLayer
      EventManager.on('algorithm:score-updated', (data: any) => {
        if (this.destroyed) return
        this.batchUpdateScores(data)
      }),
    ]

    this.unsubscribeFns.push(...listeners)
  }

  // ✅ 批量更新分数到 DataLayer
  private batchUpdateScores(data: { code: string; score: number; algorithmId: string }) {
    // 收集待更新的股票
    this.pendingUpdates.set(data.code, data.score)

    // 使用防抖，避免频繁更新
    if (this.batchUpdateTimer) {
      clearTimeout(this.batchUpdateTimer)
    }

    this.batchUpdateTimer = setTimeout(() => {
      if (this.pendingUpdates.size === 0) return

      const stocks = dataLayer.getStocks()
      const updatedStocks: any[] = []

      stocks.forEach((stock) => {
        const newScore = this.pendingUpdates.get(stock.code)
        if (newScore !== undefined) {
          const stockAny = stock as any
          const oldScore = stockAny.leaderScore || 0
          // 只有当分数变化超过阈值时才更新
          if (Math.abs(oldScore - newScore) > 0.1) {
            updatedStocks.push({
              ...stock,
              leaderScore: newScore,
              algorithmVersion: this.version,
              algorithmId: data.algorithmId,
              lastCalculated: Date.now(),
            })
          }
        }
      })

      if (updatedStocks.length > 0) {
        // 批量更新到 DataLayer
        dataLayer.updateStocks(updatedStocks)
        debugLog(`[AlgorithmManager] 批量更新 ${updatedStocks.length} 只股票的分数到 DataLayer`)
      }

      this.pendingUpdates.clear()
      this.batchUpdateTimer = null
    }, 500) // 500ms 防抖
  }

  // ========== 核心计算逻辑 ==========
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

      const result = await stockCache.getOrComputeAsync(
        cacheKey,
        async () => {
          const internalResult = await this.calculateScoreInternal(stock, algo, algorithmId)

          let safeScore = 50

          if (internalResult && typeof internalResult.score === 'number') {
            safeScore = internalResult.score
          } else if (internalResult && typeof internalResult.score === 'string') {
            safeScore = parseFloat(internalResult.score) || 50
          }

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

      // 将计算结果存入 DataLayer
      try {
        // 通过事件机制更新，避免直接操作 DataLayer 导致的循环
        EventManager.emit('algorithm:score-updated', {
          code: stock.code,
          score: result.score,
          algorithmId,
          timestamp: Date.now(),
        })

        // 同时将结果存入 analysis 缓存
        if (typeof (dataLayer as any).updateAlgorithmResult === 'function') {
          ;(dataLayer as any).updateAlgorithmResult(stock.code, {
            score: result.score,
            algorithm: algorithmId,
            details: result.details,
            timestamp: Date.now(),
            version: this.version,
          })
        }
      } catch (error) {
        console.warn(`[AlgorithmManager] 保存结果到 DataLayer 失败: ${stock.code}`, error)
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
    const multipliers = phase
      ? ((PHASE_MULTIPLIERS as Record<string, Record<string, number>>)[phase] || {})
      : {}

    let totalScore = 0
    let totalWeight = 0
    const details: Record<string, any> = {}

    const factorPromises = Object.entries(algo.factors).map(
      async ([factorId, config]: [string, any]) => {
        if (!config.enabled) return null

        const factor = FACTORS[factorId]
        if (!factor) return null

        const startTime = performance.now()
        let success = true

        try {
          let rawScore = 50
          try {
            const calculated = await factor.calculate(stock)
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

          rawScore = Math.min(100, Math.max(0, rawScore))

          let weight = config.weight
          if (weight === 'dynamic') {
            weight = config.baseWeight || 0.1
            const multiplier = multipliers[factorId] || 1
            weight = Math.min(config.max || 0.3, Math.max(config.min || 0.03, weight * multiplier))
          }

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

    const results = await Promise.all(factorPromises)

    results.forEach((result) => {
      if (result) {
        details[result.factorId] = result.detail
        totalScore += result.contribution || 0
        totalWeight += result.weight || 0
      }
    })

    let finalScore = totalWeight > 0 ? totalScore / totalWeight : 50

    if (typeof finalScore !== 'number' || isNaN(finalScore)) {
      finalScore = 50
    }

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

    consistencyManager.registerRepairServices({
      syncThemesToStocks: () => themeSyncAdapter.syncThemesToStocks(),
      recalculateDragons: () => (window as any).dragonAnalyzer?.recalculateAll?.(),
    })

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
    if (this.destroyed) return []
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

    this.currentAlgorithm = algorithmId
    this.loadCustomWeightsForAlgorithm(algorithmId)
    this.saveToStorage()
    this.invalidateCache()

    EventManager.emit('algorithm:config-changed', this.getStatus())
    EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())

    return true
  }

  private loadCustomWeightsForAlgorithm(algorithmId: string): void {
    try {
      const saved = localStorage.getItem(`${this.STORAGE_KEY}_${algorithmId}`)
      if (saved) {
        const config = JSON.parse(saved)
        this.customWeights = config.customWeights || null
        debugLog(`[AlgorithmManager] 加载算法 ${algorithmId} 的自定义权重:`, this.customWeights)
      } else {
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

    if (!this.customWeights) this.customWeights = {}
    this.customWeights[factorId] = weight

    this.saveToStorage()
    this.invalidateCache()

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

    EventManager.emit('algorithm:config-changed', this.getStatus())

    return true
  }

  normalizeWeights(): boolean {
    if (this.destroyed) return false

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

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

    const normalizeFactor = 1 / totalWeight

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

      this.updateFactorWeight(factorId, finalWeight)
    })

    debugLog('[AlgorithmManager] ✅ 权重归一化完成')

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

  getThresholdRanges(): Record<string, { min: number; max: number }> {
    return { ...THRESHOLD_RANGES }
  }

  setThresholds(thresholds: Record<string, number>): boolean {
    if (this.destroyed) return false

    let changed = false
    Object.entries(thresholds).forEach(([key, value]) => {
      if (typeof value !== 'number' || Number.isNaN(value)) return
      if (!(key in this.thresholds)) return

      const range = THRESHOLD_RANGES[key]
      const nextValue = range ? Math.min(range.max, Math.max(range.min, value)) : value
      if (this.thresholds[key] !== nextValue) {
        this.thresholds[key] = nextValue
        changed = true
      }
    })

    if (!changed) return false

    this.saveToStorage()
    this.invalidateCache()
    EventManager.emit('algorithm:config-changed', this.getStatus())
    return true
  }

  resetThresholds(): boolean {
    if (this.destroyed) return false
    this.thresholds = { ...DEFAULT_THRESHOLDS }
    this.saveToStorage()
    this.invalidateCache()
    EventManager.emit('algorithm:config-changed', this.getStatus())
    return true
  }

  updateThreshold(key: string, value: number): boolean {
    if (this.destroyed) return false
    if (!(key in this.thresholds)) return false

    this.thresholds[key] = value
    this.saveToStorage()
    this.invalidateCache()

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

  getEmotionStats(): Record<string, { count: number; avgScore: number }> {
    const stats: Record<string, { count: number; avgScore: number }> = {}

    this.emotionFeedbackHistory.forEach((feedback) => {
      if (!stats[feedback.phase]) {
        stats[feedback.phase] = { count: 0, avgScore: 0 }
      }
      const phaseStats = stats[feedback.phase]
      phaseStats.count++
      phaseStats.avgScore =
        (phaseStats.avgScore * (phaseStats.count - 1) + feedback.score) / phaseStats.count
    })

    const monitorStats = this.perfMonitor?.getEmotionStats?.() || {}
    Object.entries(monitorStats).forEach(([phase, value]) => {
      if (!stats[phase]) {
        stats[phase] = { ...value }
      }
    })

    return stats
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
  destroy(): void {
    if (this.destroyed) return

    debugLog('[AlgorithmManager] 💥 开始销毁...')
    this.destroyed = true
    this.initialized = false

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

    debugLog('[AlgorithmManager] ✅ 已销毁')
  }
}

// 导出单例
export const algorithmManager = AlgorithmManager.getInstance()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).algorithmManager = algorithmManager
}
