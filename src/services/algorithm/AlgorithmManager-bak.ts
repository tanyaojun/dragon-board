// src/services/Algorithm/AlgorithmManager.ts

import type { Stock, ScoreResult, PerformanceRecord, PerformanceStat } from '@/types'
import type {
  PerformanceMetrics,
  FactorHealth,
  WarmupStrategy,
  ABTest,
  AlgorithmConfig,
  HealthCheckResult,
  EmotionFeedback,
  EmotionAdjustment,
} from '@/types/algorithm'

import { FACTORS } from '@/config/factors'
import { ALGORITHMS, PHASE_MULTIPLIERS, DEFAULT_THRESHOLDS } from '@/config/algorithms'
import { STORAGE_KEYS } from '@/config/storage'

// ✅ 从 types 导入 PHASE_ADJUSTMENTS
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

    this.eventManager.cleanup()
    this.healthChecker.stop()
    this.warmupManager.stop()
    this.perfMonitor.stop()
  }

  /**
   * 强制立即发送待处理事件
   */
  flushEvents() {
    this.eventManager.flush()
  }
}

export class AlgorithmManager implements IAlgorithmManager {
  private static instance: AlgorithmManager

  // ✅ 新增：事件管理器
  private eventManager: AlgorithmEventManager

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
  private sectorAnalyzer: any = null

  private constructor() {
    // 初始化子模块
    this.perfMonitor = new AlgorithmPerformanceMonitor(this)
    this.warmupManager = new AlgorithmWarmupManager(this)
    this.healthChecker = new AlgorithmHealthChecker(this)
    this.abTestManager = new AlgorithmABTestManager(this)

    // 初始化事件管理器
    this.eventManager = new AlgorithmEventManager()

    // 监听情绪反馈
    this.setupEmotionListener()
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
  handleEmotionFeedback(feedback: EmotionFeedback) {
    if (!feedback) return

    // 记录历史
    this.emotionFeedbackHistory.push(feedback)
    if (this.emotionFeedbackHistory.length > 50) {
      this.emotionFeedbackHistory.shift()
    }

    // 根据情绪阶段调整权重
    const adjustments = this.adjustWeightsByPhase(feedback.phase)

    // ✅ 使用事件管理器触发
    this.eventManager.triggerEmotionFeedback(feedback)
  }

  // ========== 根据情绪阶段调整权重 ==========
  adjustWeightsByPhase(phase: string): boolean {
    // 从统一配置中获取调整值
    const adjustments = PHASE_ADJUSTMENTS[phase]
    if (!adjustments || Object.keys(adjustments).length === 0) {
      return false
    }

    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    const adjustedFactors: Array<{ factorId: string; oldWeight: number; newWeight: number }> = []

    // 应用调整
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

      // 确保在范围内
      if (config.min !== undefined && newWeight < config.min) {
        newWeight = config.min
      }
      if (config.max !== undefined && newWeight > config.max) {
        newWeight = config.max
      }

      // 如果新旧权重相同，跳过
      if (Math.abs(newWeight - oldWeight) < 0.001) {
        return
      }

      // 更新权重
      const success = this.updateFactorWeight(factorId, newWeight)
      if (success) {
        adjustedFactors.push({
          factorId,
          oldWeight,
          newWeight,
        })

        // 记录调整历史
        this.weightAdjustmentHistory.push({
          factorId,
          delta,
          oldWeight,
          newWeight,
          reason: `情绪阶段: ${phase}`,
          timestamp: Date.now(),
        })
      }
    })

    // 限制历史记录长度
    if (this.weightAdjustmentHistory.length > 100) {
      this.weightAdjustmentHistory = this.weightAdjustmentHistory.slice(-100)
    }

    // 触发权重调整事件
    if (adjustedFactors.length > 0) {
      const eventData: WeightAdjustmentEvent = {
        phase,
        adjustments: adjustedFactors,
        timestamp: Date.now(),
      }
      // ✅ 使用事件管理器触发
      this.eventManager.triggerWeightsAdjusted(eventData)
    }

    return adjustedFactors.length > 0
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

    // 确保在范围内
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

  // ========== 初始化 ==========
  public async init(): Promise<boolean> {
    if (this.initPromise) return this.initPromise

    this.initPromise = new Promise(async (resolve) => {
      if (this.initialized) {
        resolve(true)
        return
      }

      console.log('[AlgorithmManager] 🧠 算法管理器初始化中...')

      try {
        // 1. 加载配置
        this.loadFromStorage()
        this.loadHistory()

        // 2. 连接外部服务
        this.tryConnectServices()

        // 3. 设置事件监听
        this.setupEventListeners()

        // 4. 启动子模块
        this.perfMonitor.start()
        this.warmupManager.start()
        this.healthChecker.start()

        // 5. 验证配置
        const validation = await this.healthChecker.checkNow()
        if (!validation.valid) {
          console.warn('[AlgorithmManager] ⚠️ 配置验证发现警告:', validation.warnings)
        }

        this.initialized = true
        this.version++

        console.log('[AlgorithmManager] ✅ 初始化完成')
        console.log(`   ├─ 算法数量: ${Object.keys(ALGORITHMS).length}`)
        console.log(`   ├─ 因子总数: ${Object.keys(FACTORS).length}`)
        console.log(`   ├─ 当前算法: ${this.getCurrentAlgorithm().name}`)
        console.log(`   ├─ 预热策略: ${Object.keys(this.warmupManager.getStrategies()).length}个`)
        console.log(`   └─ 版本: v${this.version}`)

        EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())
        resolve(true)
      } catch (error) {
        console.error('[AlgorithmManager] 初始化失败:', error)
        this.initPromise = null
        resolve(false)
      }
    })

    return this.initPromise
  }

  // ========== 核心计算逻辑 ==========

  calculateScore(stock: Stock): ScoreResult {
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

      const result = stockCache.getOrCompute(
        cacheKey,
        () => this.calculateScoreInternal(stock, algo, algorithmId),
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

  private calculateScoreInternal(stock: Stock, algo: any, algorithmId: string): ScoreResult {
    const phase = this.getCurrentMarketPhase()
    const multipliers = phase ? PHASE_MULTIPLIERS[phase] || {} : {}

    let totalScore = 0
    let totalWeight = 0
    const details: Record<string, any> = {}

    Object.entries(algo.factors).forEach(([factorId, config]: [string, any]) => {
      if (!config.enabled) return

      const factor = FACTORS[factorId]
      if (!factor) return

      const startTime = performance.now()
      let success = true

      try {
        const rawScore = safeExecute(
          () => Promise.resolve(factor.calculate(stock)),
          50,
          (error) => {
            success = false
            console.warn(`[AlgorithmManager] 因子 ${factorId} 计算失败:`, error)
          },
        )

        let weight = config.weight
        if (weight === 'dynamic') {
          weight = config.baseWeight || 0.1
          const multiplier = multipliers[factorId] || 1
          weight = Math.min(config.max || 0.3, Math.max(config.min || 0.03, weight * multiplier))
        }

        const contribution = rawScore * weight

        details[factorId] = {
          name: factor.name,
          score: rawScore,
          weight,
          contribution,
        }

        totalScore += contribution
        totalWeight += weight

        const calcTime = performance.now() - startTime
        this.perfMonitor.recordFactorPerformance(factorId, calcTime, success, contribution)
      } catch (error) {
        console.warn(`[AlgorithmManager] 因子 ${factorId} 处理失败:`, error)
      }
    })

    const finalScore = totalWeight > 0 ? totalScore / totalWeight : 50

    return {
      score: finalScore,
      details,
      timestamp: Date.now(),
      algorithm: algorithmId,
      algorithmName: algo.name,
    }
  }

  calculateScoresBulk(stocks: Stock[]): Map<string, ScoreResult> {
    const versions = {
      algoVersion: this.version,
      stocks: dataLayer.getVersion().stocks,
      themes: dataLayer.getVersion().themes,
    }

    const keys = stocks.map((stock) => createCacheKey('score', stock.code, versions))

    const computed = stockCache.getOrComputeMany(
      keys,
      (missingKeys) => {
        const missingResults = new Map<string, ScoreResult>()

        missingKeys.forEach((key) => {
          const code = key.split(':')[1]
          const stock = stocks.find((s) => s.code === code)
          if (stock) {
            missingResults.set(key, this.calculateScore(stock))
          }
        })

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

  private loadFromStorage(): void {
    if (typeof window === 'undefined') return

    try {
      const savedAlgorithm = localStorage.getItem(STORAGE_KEYS.ALGORITHM)
      if (savedAlgorithm && ALGORITHMS[savedAlgorithm]) {
        this.currentAlgorithm = savedAlgorithm
      }

      const savedWeights = localStorage.getItem(STORAGE_KEYS.WEIGHTS)
      if (savedWeights) {
        try {
          this.customWeights = JSON.parse(savedWeights)
          this.applyCustomWeights()
        } catch (e) {}
      }

      const savedThresholds = localStorage.getItem(STORAGE_KEYS.THRESHOLDS)
      if (savedThresholds) {
        try {
          this.thresholds = { ...this.thresholds, ...JSON.parse(savedThresholds) }
        } catch (e) {}
      }
    } catch (e) {
      console.warn('[AlgorithmManager] 从localStorage加载失败:', e)
    }
  }

  private saveToStorage(): void {
    if (typeof window === 'undefined') return

    localStorage.setItem(STORAGE_KEYS.ALGORITHM, this.currentAlgorithm)
    if (this.customWeights) {
      localStorage.setItem(STORAGE_KEYS.WEIGHTS, JSON.stringify(this.customWeights))
    }
    localStorage.setItem(STORAGE_KEYS.THRESHOLDS, JSON.stringify(this.thresholds))
  }

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

  private setupEventListeners(): void {
    EventManager.on(AppEvents.DATA.MERGED, () => {
      this.invalidateCache()
    })

    EventManager.on('algorithm-changed', () => {
      this.invalidateCache()
    })
  }

  // ========== 公共API ==========

  getCurrentAlgorithm(): any {
    return ALGORITHMS[this.currentAlgorithm] || ALGORITHMS.balanced
  }

  getAlgorithmList() {
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
    if (!ALGORITHMS[algorithmId]) return false

    this.currentAlgorithm = algorithmId
    this.saveToStorage()
    this.invalidateCache()

    // ✅ 使用事件管理器触发
    this.eventManager.triggerAlgorithmChanged(this.getCurrentAlgorithm())
    return true
  }

  getFactorWeights(algorithmId?: string): any[] {
    const algoId = algorithmId || this.currentAlgorithm
    const algo = ALGORITHMS[algoId]
    if (!algo) return []

    return Object.entries(algo.factors).map(([factorId, config]: [string, any]) => {
      const factor = FACTORS[factorId]
      return {
        id: factorId,
        name: factor?.name || factorId,
        type: factor?.type || 'unknown',
        description: factor?.description || '',
        weight: config.weight,
        enabled: config.enabled,
        min: config.min,
        max: config.max,
        baseWeight: config.baseWeight,
      }
    })
  }

  updateFactorWeight(factorId: string, weight: number): boolean {
    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo || !algo.factors[factorId]) return false

    const config = algo.factors[factorId]
    if (config.min !== undefined && weight < config.min) return false
    if (config.max !== undefined && weight > config.max) return false

    algo.factors[factorId].weight = weight

    if (!this.customWeights) this.customWeights = {}
    this.customWeights[factorId] = weight
    this.saveToStorage()
    this.invalidateCache()

    // ✅ 使用事件管理器触发
    this.eventManager.triggerAlgorithmChanged(this.getCurrentAlgorithm())
    return true
  }

  resetWeights(): boolean {
    const algo = ALGORITHMS[this.currentAlgorithm]
    if (!algo) return false

    const defaultAlgo = ALGORITHMS[this.currentAlgorithm]
    algo.factors = JSON.parse(JSON.stringify(defaultAlgo.factors))

    this.customWeights = null
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEYS.WEIGHTS)
    }
    this.invalidateCache()

    // ✅ 使用事件管理器触发
    this.eventManager.triggerAlgorithmChanged(this.getCurrentAlgorithm())
    return true
  }

  getThresholds(): Record<string, number> {
    return { ...this.thresholds }
  }

  updateThreshold(key: string, value: number): boolean {
    if (!(key in this.thresholds)) return false
    this.thresholds[key] = value
    localStorage.setItem(STORAGE_KEYS.THRESHOLDS, JSON.stringify(this.thresholds))
    this.invalidateCache()
    return true
  }

  getPerformanceStats(): Record<string, PerformanceStat> {
    const stats: Record<string, PerformanceStat> = {}
    this.performanceStats.forEach((stat, id) => {
      stats[id] = { ...stat }
    })
    return stats
  }

  getVersion(): number {
    return this.version
  }

  getFullStatus() {
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
      // 情绪相关状态
      emotion: {
        feedbackCount: this.emotionFeedbackHistory.length,
        adjustmentsCount: this.weightAdjustmentHistory.length,
        stats: this.getEmotionStats(),
      },
    }
  }

  getLeaderThresholds(): Record<string, number> {
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
    return this.perfMonitor
  }

  getABTestManager(): AlgorithmABTestManager {
    return this.abTestManager
  }

  getWarmupManager(): AlgorithmWarmupManager {
    return this.warmupManager
  }

  getHealthChecker(): AlgorithmHealthChecker {
    return this.healthChecker
  }
}

// 导出单例
export const algorithmManager = AlgorithmManager.getInstance()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).algorithmManager = algorithmManager
}
