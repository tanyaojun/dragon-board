// src/services/Algorithm/AlgorithmPerformanceMonitor.ts
// 性能监控模块 - 增强版：记录情绪和权重调整

import type { IAlgorithmManager } from './AlgorithmManager'
import type {
  PerformanceMetrics,
  FactorPerformance,
  FactorHealth,
  EmotionRecord,
  AdjustmentRecord,
  PerformanceStats,
} from '@/types/algorithm'

import { FACTORS } from '@/config/factors'
import { PERFORMANCE_CONFIG } from '@/types/config'
import { EventManager } from '@/utils/eventManager'
import { stockCache } from '@/services/LRUCache' // ✅ 已正确导入
import { calculateP95, calculateStability, throttle } from '@/utils/algorithmHelpers'

export class AlgorithmPerformanceMonitor {
  private algorithmManager: IAlgorithmManager
  private metrics: PerformanceMetrics
  private calcTimes: number[] = []
  private factorStats: Map<string, FactorPerformance> = new Map()
  private timer: ReturnType<typeof setInterval> | null = null

  private emotionHistory: EmotionRecord[] = []
  private timers = {
    flushTimer: null as ReturnType<typeof setTimeout> | null,
  }

  private adjustmentHistory: AdjustmentRecord[] = []

  // 配置
  private readonly MAX_HISTORY = PERFORMANCE_CONFIG.MAX_HISTORY
  private readonly UPDATE_INTERVAL = PERFORMANCE_CONFIG.UPDATE_INTERVAL
  private readonly EMOTION_HISTORY_SIZE = PERFORMANCE_CONFIG.EMOTION_HISTORY_SIZE
  private readonly ADJUSTMENT_HISTORY_SIZE = PERFORMANCE_CONFIG.ADJUSTMENT_HISTORY_SIZE

  // ✅ 新增：缓存键前缀
  private readonly CACHE_KEYS = {
    METRICS: 'algorithm:metrics',
    EMOTION_HISTORY: 'algorithm:emotion',
    ADJUSTMENT_HISTORY: 'algorithm:adjustments',
  }

  constructor(algorithmManager: IAlgorithmManager) {
    this.algorithmManager = algorithmManager

    this.metrics = {
      avgCalcTime: 0,
      p95CalcTime: 0,
      cacheHitRate: 0,
      queueWaitTime: 0,
      factorPerformance: this.factorStats,
      timestamp: Date.now(),
    }

    // ✅ 从缓存恢复历史数据
    this.loadFromCache()

    // 监听情绪反馈和权重调整事件
    this.setupListeners()
  }

  // ✅ 新增：从缓存加载历史数据
  private loadFromCache(): void {
    try {
      // 加载情绪历史
      const cachedEmotion = stockCache.get(this.CACHE_KEYS.EMOTION_HISTORY)
      if (cachedEmotion && Array.isArray(cachedEmotion)) {
        this.emotionHistory = cachedEmotion.slice(-this.EMOTION_HISTORY_SIZE)
      }

      // 加载调整历史
      const cachedAdjustments = stockCache.get(this.CACHE_KEYS.ADJUSTMENT_HISTORY)
      if (cachedAdjustments && Array.isArray(cachedAdjustments)) {
        this.adjustmentHistory = cachedAdjustments.slice(-this.ADJUSTMENT_HISTORY_SIZE)
      }

      // 加载性能指标
      const cachedMetrics = stockCache.get(this.CACHE_KEYS.METRICS)
      if (cachedMetrics) {
        this.metrics = { ...this.metrics, ...cachedMetrics }
      }
    } catch (e) {
      console.warn('[AlgorithmPerformanceMonitor] 从缓存恢复失败:', e)
    }
  }

  // ✅ 新增：保存到缓存
  private saveToCache(): void {
    try {
      stockCache.set(
        this.CACHE_KEYS.EMOTION_HISTORY,
        this.emotionHistory.slice(-100),
        30 * 60 * 1000,
      ) // 30分钟
      stockCache.set(
        this.CACHE_KEYS.ADJUSTMENT_HISTORY,
        this.adjustmentHistory.slice(-100),
        30 * 60 * 1000,
      )
      stockCache.set(this.CACHE_KEYS.METRICS, this.metrics, 5 * 60 * 1000) // 5分钟
    } catch (e) {
      // 忽略缓存错误
    }
  }

  // ========== 设置事件监听 ==========
  private setupListeners() {
    // 监听情绪反馈
    EventManager.on('breath:feedback', (feedback: any) => {
      this.recordEmotionData({
        phase: feedback.phase,
        score: feedback.score,
        ztCount: feedback.ztCount,
        dtCount: feedback.dtCount,
        hotThemesCount: feedback.hotThemesCount || 0,
        timestamp: feedback.timestamp || Date.now(),
      })
    })

    // 监听权重调整
    EventManager.on('algorithm:weights-adjusted', (event: any) => {
      if (event?.adjustments) {
        event.adjustments.forEach((adj: any) => {
          this.recordWeightAdjustment({
            factorId: adj.factorId,
            oldWeight: adj.oldWeight,
            newWeight: adj.newWeight,
            delta: adj.newWeight - adj.oldWeight,
            reason: `情绪阶段: ${event.phase}`,
            timestamp: event.timestamp || Date.now(),
          })
        })
      }
    })
  }

  /**
   * 启动性能监控
   */
  start(): void {
    // 不再启动独立定时器
    console.log('[AlgorithmPerformanceMonitor] 已启动（由RefreshManager调度）')
    return
  }

  /**
   * 停止性能监控
   */
  stop(): void {
    if (this.timers.flushTimer) {
      clearInterval(this.timers.flushTimer)
      this.timers.flushTimer = null
    }

    this.saveToCache()
  }

  /**
   * ✅ 新增：供 RefreshManager 调用的维护方法
   */
  async runMaintenance(): Promise<void> {
    if (!this.algorithmManager) return
    console.log('[AlgorithmPerformanceMonitor] 执行后台维护')

    // 更新性能指标
    this.updateMetrics()

    // 保存到缓存
    this.saveToCache()
  }

  /**
   * 记录计算时间
   */
  recordCalculation(stockCode: string, calcTime: number): void {
    this.calcTimes.push(calcTime)
    if (this.calcTimes.length > this.MAX_HISTORY) {
      this.calcTimes.shift()
    }
  }

  /**
   * 记录因子性能
   */
  recordFactorPerformance(
    factorId: string,
    calcTime: number,
    success: boolean,
    contribution: number,
  ): void {
    let stat = this.factorStats.get(factorId)

    if (!stat) {
      const factor = FACTORS[factorId]
      stat = {
        factorId,
        factorName: factor?.name || factorId,
        avgTime: 0,
        callCount: 0,
        errorRate: 0,
        contribution: 0,
        stability: 100,
        isHealthy: true,
      }
      this.factorStats.set(factorId, stat)
    }

    // 更新统计
    stat.callCount++
    stat.avgTime = (stat.avgTime * (stat.callCount - 1) + calcTime) / stat.callCount

    if (!success) {
      const errorCount = stat.callCount * stat.errorRate
      stat.errorRate = (errorCount + 1) / stat.callCount
    }

    stat.contribution = (stat.contribution * (stat.callCount - 1) + contribution) / stat.callCount
    stat.stability = calculateStability(stat.errorRate, stat.avgTime)
    stat.isHealthy = stat.stability > 60 && stat.errorRate < 0.1

    // 如果不健康，发出警告
    if (!stat.isHealthy && stat.callCount % 100 === 0) {
      this.emitFactorWarning(factorId, stat)
    }
  }

  // ========== 新增：记录情绪数据 ==========
  recordEmotionData(record: EmotionRecord): void {
    this.emotionHistory.push(record)
    if (this.emotionHistory.length > this.EMOTION_HISTORY_SIZE) {
      this.emotionHistory.shift()
    }

    if (this.emotionHistory.length >= 2) {
      const last = this.emotionHistory[this.emotionHistory.length - 2]
      const current = this.emotionHistory[this.emotionHistory.length - 1]

      if (last.phase !== current.phase) {
        this.handlePhaseChange(last.phase, current.phase)
      }
    }

    // ✅ 每10条记录保存一次
    if (this.emotionHistory.length % 10 === 0) {
      this.saveToCache()
    }
  }

  // ========== 新增：记录权重调整 ==========
  recordWeightAdjustment(record: AdjustmentRecord): void {
    this.adjustmentHistory.push(record)
    if (this.adjustmentHistory.length > this.ADJUSTMENT_HISTORY_SIZE) {
      this.adjustmentHistory.shift()
    }

    // ✅ 每5条记录保存一次
    if (this.adjustmentHistory.length % 5 === 0) {
      this.saveToCache()
    }
  }

  // ========== 新增：处理情绪阶段变化 ==========
  private handlePhaseChange(oldPhase: string, newPhase: string): void {
    // 触发事件
    EventManager.emit('algorithm:phase-changed', {
      oldPhase,
      newPhase,
      timestamp: Date.now(),
    })
  }

  // ========== 新增：获取情绪历史 ==========
  getEmotionHistory(limit?: number): EmotionRecord[] {
    if (limit) {
      return this.emotionHistory.slice(-limit)
    }
    return [...this.emotionHistory]
  }

  // ========== 新增：获取权重调整历史 ==========
  getAdjustmentHistory(limit?: number, factorId?: string): AdjustmentRecord[] {
    let history = this.adjustmentHistory

    if (factorId) {
      history = history.filter((h) => h.factorId === factorId)
    }

    if (limit) {
      history = history.slice(-limit)
    }

    return [...history]
  }

  // ========== 新增：获取情绪统计 ==========
  getEmotionStats(): Record<string, { count: number; avgScore: number }> {
    const stats: Record<string, { count: number; avgScore: number }> = {}

    this.emotionHistory.forEach((e) => {
      if (!stats[e.phase]) {
        stats[e.phase] = { count: 0, avgScore: 0 }
      }
      stats[e.phase].count++
      stats[e.phase].avgScore =
        (stats[e.phase].avgScore * (stats[e.phase].count - 1) + e.score) / stats[e.phase].count
    })

    return stats
  }

  // ========== 新增：获取调整统计 ==========
  getAdjustmentStats(): Record<string, { count: number; totalDelta: number }> {
    const stats: Record<string, { count: number; totalDelta: number }> = {}

    this.adjustmentHistory.forEach((a) => {
      if (!stats[a.factorId]) {
        stats[a.factorId] = { count: 0, totalDelta: 0 }
      }
      stats[a.factorId].count++
      stats[a.factorId].totalDelta += a.delta
    })

    return stats
  }

  // ========== 新增：获取完整性能统计 ==========
  getPerformanceStats(): PerformanceStats {
    return {
      avgCalcTime: this.metrics.avgCalcTime,
      p95CalcTime: this.metrics.p95CalcTime,
      cacheHitRate: this.metrics.cacheHitRate,
      emotionStats: this.getEmotionStats(),
      adjustmentStats: this.getAdjustmentStats(),
    }
  }

  /**
   * 更新性能指标
   */
  private updateMetrics(): void {
    // 更新计算时间
    if (this.calcTimes.length > 0) {
      this.metrics.avgCalcTime = this.calcTimes.reduce((a, b) => a + b, 0) / this.calcTimes.length
      this.metrics.p95CalcTime = calculateP95(this.calcTimes)
    }

    // 更新缓存命中率
    this.metrics.cacheHitRate = stockCache.getHitRate()

    // 更新时间戳
    this.metrics.timestamp = Date.now()

    // ✅ 定期保存到缓存
    this.saveToCache()

    // 触发事件
    EventManager.emit('algorithm:performance-updated', {
      metrics: this.metrics,
      emotionStats: this.getEmotionStats(),
      adjustmentStats: this.getAdjustmentStats(),
      timestamp: Date.now(),
    })

    // 开发环境下输出日志
    if (process.env.NODE_ENV === 'development') {
      console.log('[AlgorithmPerf] 📊 性能指标:', {
        avgCalcTime: this.metrics.avgCalcTime.toFixed(2) + 'ms',
        p95CalcTime: this.metrics.p95CalcTime.toFixed(2) + 'ms',
        cacheHitRate: this.metrics.cacheHitRate.toFixed(2) + '%',
        emotionPhases: Object.keys(this.getEmotionStats()).length,
        adjustments: this.adjustmentHistory.length,
      })
    }
  }

  /**
   * 发出因子警告
   */
  private emitFactorWarning(factorId: string, stat: FactorPerformance): void {
    const warnings: string[] = []

    if (stat.errorRate > 0.1) {
      warnings.push(`错误率过高: ${(stat.errorRate * 100).toFixed(1)}%`)
    }
    if (stat.avgTime > 50) {
      warnings.push(`计算耗时过长: ${stat.avgTime.toFixed(0)}ms`)
    }
    if (stat.contribution < 5) {
      warnings.push(`贡献度偏低: ${stat.contribution.toFixed(1)}%`)
    }

    EventManager.emit('algorithm:factor-health-warning', {
      factorId,
      health: {
        id: factorId,
        name: stat.factorName,
        callCount: stat.callCount,
        avgTime: stat.avgTime,
        errorRate: stat.errorRate,
        contribution: stat.contribution,
        stability: stat.stability,
        lastCheck: Date.now(),
        isHealthy: stat.isHealthy,
        suggestions: warnings,
      },
    })
  }

  /**
   * 获取当前指标
   */
  getMetrics(): PerformanceMetrics {
    return { ...this.metrics }
  }

  /**
   * 获取因子性能报告
   */
  getFactorReport(): FactorPerformance[] {
    return Array.from(this.factorStats.values()).sort((a, b) => b.contribution - a.contribution)
  }

  /**
   * 重置监控数据
   */
  reset(): void {
    this.calcTimes = []
    this.factorStats.clear()
    this.emotionHistory = []
    this.adjustmentHistory = []
    this.metrics = {
      avgCalcTime: 0,
      p95CalcTime: 0,
      cacheHitRate: 0,
      queueWaitTime: 0,
      factorPerformance: this.factorStats,
      timestamp: Date.now(),
    }

    // ✅ 清除缓存
    try {
      stockCache.delete(this.CACHE_KEYS.METRICS)
      stockCache.delete(this.CACHE_KEYS.EMOTION_HISTORY)
      stockCache.delete(this.CACHE_KEYS.ADJUSTMENT_HISTORY)
    } catch (e) {}
  }

  /**
   * 获取调试信息
   */
  debug(): any {
    return {
      metrics: { ...this.metrics },
      emotionHistory: this.emotionHistory.slice(-10),
      adjustmentHistory: this.adjustmentHistory.slice(-10),
      factorStats: Array.from(this.factorStats.entries()).map(([id, stat]) => ({
        id,
        name: stat.factorName,
        calls: stat.callCount,
        avgTime: stat.avgTime.toFixed(2),
        contribution: stat.contribution.toFixed(2),
        healthy: stat.isHealthy,
      })),
    }
  }

}
