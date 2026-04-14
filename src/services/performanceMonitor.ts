// src/services/performanceMonitor.ts

import { cacheManager } from './LRUCache'

interface PerformanceMetric {
  name: string
  duration: number
  timestamp: number
  success: boolean
  details?: any
  type?: 'api' | 'calculation' | 'render' | 'cache' | 'event' // 指标类型
}

interface MemoryInfo {
  usedJSHeapSize: number
  totalJSHeapSize: number
  jsHeapSizeLimit: number
  heapUsagePercent: number
}

interface CacheStats {
  size: number
  hitRate: number
  missRate: number
  avgAccessTime: number
  byType?: Record<string, { hits: number; misses: number; hitRate: number }> // 按类型统计
}

interface ApiStats {
  name: string
  count: number
  totalTime: number
  avgTime: number
  successRate: number
  p95Time: number // 95分位响应时间
  p99Time: number // 99分位响应时间
  errorCount: number
}

interface SystemHealth {
  status: 'healthy' | 'warning' | 'critical'
  issues: string[]
  suggestions: string[]
  lastCheck: number
}

interface ComponentStatus {
  name: string
  status: 'healthy' | 'warning' | 'error' | 'stopped'
  lastActive: number
  metrics: Record<string, any>
}

// ========== 数据链条类型定义 ==========

interface DataChainNode {
  name: string
  type: 'source' | 'processor' | 'calculator' | 'cache' | 'presentation'
  status: 'active' | 'degraded' | 'failed' | 'pending'
  latency: number // 处理延迟(ms)
  throughput: number // 吞吐量(条/秒)
  errorRate: number // 错误率(%)
  lastUpdate: number
  dependencies: string[] // 依赖的上游节点
  metrics: Record<string, any>
}

interface DataFlowMetrics {
  sourceId: string // 数据源ID (eastmoney, tencent, etc)
  sourceType: 'http' | 'websocket' | 'mock'
  fetchCount: number
  successCount: number
  failCount: number
  totalBytes: number
  avgResponseTime: number
  p95ResponseTime: number
  lastSuccessTime: number
  lastFailTime: number
  failReason?: string
}

interface ProcessingMetrics {
  processorId: string
  inputCount: number
  outputCount: number
  transformTime: number
  mergeCount: number
  dedupCount: number
  enrichCount: number
}

interface CalculationMetrics {
  calculatorId: string
  invokeCount: number
  cacheHitCount: number
  cacheMissCount: number
  avgCalcTime: number
  p95CalcTime: number
  resultSize: number
}

interface CacheMetrics {
  cacheId: string
  type: 'stock' | 'leader' | 'sector' | 'quote'
  size: number
  capacity: number
  hitRate: number
  missRate: number
  evictionCount: number
  avgAccessTime: number
  hotKeys: Array<{ key: string; accessCount: number }>
  coldKeys: Array<{ key: string; lastAccess: number }>
}

interface PresentationMetrics {
  panelId: string
  renderCount: number
  avgRenderTime: number
  dataFreshness: number // 数据新鲜度(ms)
  updateFrequency: number // 更新频率(次/分钟)
  userInteractionCount: number
}

// 完整数据链条
interface DataChain {
  sources: Record<string, DataFlowMetrics>
  processors: Record<string, ProcessingMetrics>
  calculators: Record<string, CalculationMetrics>
  caches: Record<string, CacheMetrics>
  presentations: Record<string, PresentationMetrics>
  timestamps: {
    start: number
    lastSourceUpdate: number
    lastProcessUpdate: number
    lastCalcUpdate: number
    lastPresentationUpdate: number
  }
  health: {
    overall: 'healthy' | 'degraded' | 'critical'
    bottlenecks: string[]
    warnings: string[]
  }
}

class PerformanceMonitorService {
  private metrics: PerformanceMetric[] = []
  private readonly MAX_METRICS = 2000 // 增加容量

  private startTime = Date.now()

  // 缓存统计
  private cacheHits = 0
  private cacheMisses = 0
  private cacheAccessTimes: number[] = []
  private cacheHitByType: Map<string, { hits: number; misses: number }> = new Map()

  // 情绪历史
  private emotionHistory: Array<{ phase: string; score: number; timestamp: number }> = []

  // API 性能统计
  private apiPerformance: Map<
    string,
    {
      times: number[]
      successes: number
      failures: number
      lastError?: string
    }
  > = new Map()

  // 组件健康状态
  private componentStatus: Map<string, ComponentStatus> = new Map()

  // 系统健康历史
  private healthHistory: SystemHealth[] = []
  private readonly MAX_HEALTH_HISTORY = 50

  // 性能阈值
  private readonly THRESHOLDS = {
    SLOW_API: 5000, // 5000ms
    VERY_SLOW_API: 10000, // 10s
    MEMORY_WARNING: 80, // 80%
    MEMORY_CRITICAL: 90, // 90%
    CACHE_HIT_RATE_LOW: 20, // 20%
    CACHE_HIT_RATE_CRITICAL: 10, // 10%
    QUEUE_SIZE_WARNING: 100,
    QUEUE_SIZE_CRITICAL: 200,
  }

  constructor() {}

  // ========== 情绪历史 ==========

  /**
   * ✅ 新增：供 RefreshManager 调用的维护方法
   */
  async runMaintenance(): Promise<void> {
    console.log('[PerformanceMonitor] 执行后台维护')

    // 生成报告
    const report = this.generateReport()

    // 内存警告
    if (report.memory) {
      const usage = parseFloat(report.memory.usagePercent)
      if (usage > this.THRESHOLDS.MEMORY_CRITICAL) {
        console.error('[PerformanceMonitor] 🔴 内存使用率过高:', report.memory.usagePercent)
      } else if (usage > this.THRESHOLDS.MEMORY_WARNING) {
        console.warn('[PerformanceMonitor] 🟡 内存使用率偏高:', report.memory.usagePercent)
      }
    }

    // 缓存命中率警告
    const hitRate = parseFloat(report.cache.hitRate)
    const totalAccess = this.cacheHits + this.cacheMisses
    if (totalAccess > 100) {
      if (hitRate < this.THRESHOLDS.CACHE_HIT_RATE_CRITICAL) {
        console.error('[PerformanceMonitor] 🔴 缓存命中率过低:', report.cache.hitRate)
      } else if (hitRate < this.THRESHOLDS.CACHE_HIT_RATE_LOW) {
        console.warn('[PerformanceMonitor] 🟡 缓存命中率偏低:', report.cache.hitRate)
      }
    }

    // 健康检查
    this.checkSystemHealth()
  }

  recordEmotion(phase: string, score: number) {
    this.emotionHistory.push({
      phase,
      score,
      timestamp: Date.now(),
    })

    if (this.emotionHistory.length > 100) {
      this.emotionHistory = this.emotionHistory.slice(-100)
    }
  }

  getEmotionHistory(limit: number = 50) {
    return this.emotionHistory.slice(-limit)
  }

  // ========== 指标记录 ==========

  recordMetric(
    name: string,
    duration: number,
    success: boolean = true,
    details?: any,
    type: PerformanceMetric['type'] = 'api',
  ) {
    const metric: PerformanceMetric = {
      name,
      duration,
      timestamp: Date.now(),
      success,
      details,
      type,
    }

    this.metrics.push(metric)

    // 限制数量
    if (this.metrics.length > this.MAX_METRICS) {
      this.metrics = this.metrics.slice(-this.MAX_METRICS)
    }

    // 按类型统计
    if (type === 'api') {
      this.recordApiPerformance(name, duration, success, details)
    }

    // 慢操作警告
    if (duration > this.THRESHOLDS.SLOW_API) {
      const level = duration > this.THRESHOLDS.VERY_SLOW_API ? '⚠️ 非常慢' : '⚠️ 慢'
      console.warn(`[Performance] ${level} ${type}: ${name} 耗时 ${duration}ms`, details)
    }
  }

  /**
   * 记录 API 性能
   */
  private recordApiPerformance(name: string, duration: number, success: boolean, details?: any) {
    if (!this.apiPerformance.has(name)) {
      this.apiPerformance.set(name, { times: [], successes: 0, failures: 0 })
    }

    const stat = this.apiPerformance.get(name)!
    stat.times.push(duration)

    // 只保留最近100次
    if (stat.times.length > 100) {
      stat.times = stat.times.slice(-100)
    }

    if (success) {
      stat.successes++
    } else {
      stat.failures++
      stat.lastError = details?.error || '未知错误'
    }
  }

  // ========== 缓存监控 ==========

  recordCacheAccess(hit: boolean, accessTime: number, cacheType?: string) {
    if (hit) {
      this.cacheHits++
    } else {
      this.cacheMisses++
    }
    this.cacheAccessTimes.push(accessTime)

    // 按类型统计
    if (cacheType) {
      if (!this.cacheHitByType.has(cacheType)) {
        this.cacheHitByType.set(cacheType, { hits: 0, misses: 0 })
      }
      const typeStat = this.cacheHitByType.get(cacheType)!
      if (hit) {
        typeStat.hits++
      } else {
        typeStat.misses++
      }
    }

    // 限制数量
    if (this.cacheAccessTimes.length > 1000) {
      this.cacheAccessTimes = this.cacheAccessTimes.slice(-1000)
    }
  }

  /**
   * 获取缓存统计（增强版）
   */
  getCacheStats(): CacheStats {
    const total = this.cacheHits + this.cacheMisses
    const hitRate = total > 0 ? this.cacheHits / total : 0
    const missRate = total > 0 ? this.cacheMisses / total : 0
    const avgAccessTime =
      this.cacheAccessTimes.length > 0
        ? this.cacheAccessTimes.reduce((a, b) => a + b, 0) / this.cacheAccessTimes.length
        : 0
    // 从 cacheManager 获取所有缓存的统计信息
    let totalCacheSize = 0
    const byType: Record<string, { hits: number; misses: number; hitRate: number }> = {}
    try {
      const allStats = cacheManager.getAllStats?.() || {}
      totalCacheSize = Object.values(allStats).reduce(
        (sum: number, stat: any) => sum + (stat.size || 0),
        0,
      )

      // 获取各类型命中率
      Object.entries(allStats).forEach(([name, stats]: [string, any]) => {
        const typeTotal = (stats.hits || 0) + (stats.misses || 0)
        byType[name] = {
          hits: stats.hits || 0,
          misses: stats.misses || 0,
          hitRate: typeTotal > 0 ? (stats.hits / typeTotal) * 100 : 0,
        }
      })

      // 合并自定义类型统计
      this.cacheHitByType.forEach((stat, type) => {
        if (!byType[type]) {
          const typeTotal = stat.hits + stat.misses
          byType[type] = {
            hits: stat.hits,
            misses: stat.misses,
            hitRate: typeTotal > 0 ? (stat.hits / typeTotal) * 100 : 0,
          }
        }
      })
    } catch (e) {
      console.warn('[PerformanceMonitor] 无法获取缓存统计', e)
    }

    return {
      size: totalCacheSize,
      hitRate,
      missRate,
      avgAccessTime,
      byType,
    }
  }

  // ========== 组件健康监控 ==========

  /**
   * 注册组件状态
   */
  registerComponent(name: string, initialStatus: ComponentStatus['status'] = 'healthy') {
    this.componentStatus.set(name, {
      name,
      status: initialStatus,
      lastActive: Date.now(),
      metrics: {},
    })
  }

  /**
   * 更新组件状态
   */
  updateComponentStatus(
    name: string,
    status: ComponentStatus['status'],
    metrics?: Record<string, any>,
  ) {
    if (!this.componentStatus.has(name)) {
      this.registerComponent(name, status)
    }

    const component = this.componentStatus.get(name)!
    component.status = status
    component.lastActive = Date.now()
    if (metrics) {
      component.metrics = { ...component.metrics, ...metrics }
    }
  }

  /**
   * 记录组件指标
   */
  recordComponentMetric(name: string, metric: string, value: any) {
    if (!this.componentStatus.has(name)) {
      this.registerComponent(name)
    }

    const component = this.componentStatus.get(name)!
    component.metrics[metric] = value
    component.lastActive = Date.now()
  }

  /**
   * 获取组件状态
   */
  getComponentStatus(name: string): ComponentStatus | undefined {
    return this.componentStatus.get(name)
  }

  /**
   * 获取所有组件状态
   */
  getAllComponentStatus(): ComponentStatus[] {
    return Array.from(this.componentStatus.values())
  }

  // ========== 系统健康检查 ==========

  private setupHealthCheck() {
    return
  }

  /**
   * 检查系统健康状态
   */
  checkSystemHealth(): SystemHealth {
    const issues: string[] = []
    const suggestions: string[] = []
    let status: SystemHealth['status'] = 'healthy'

    // 检查内存
    const memory = this.getMemoryInfo()
    if (memory) {
      if (memory.heapUsagePercent > this.THRESHOLDS.MEMORY_CRITICAL) {
        status = 'critical'
        issues.push(`内存使用率过高: ${memory.heapUsagePercent.toFixed(1)}%`)
        suggestions.push('考虑增加缓存清理频率或减少缓存容量')
      } else if (memory.heapUsagePercent > this.THRESHOLDS.MEMORY_WARNING) {
        if (status !== 'critical') status = 'warning'
        issues.push(`内存使用率偏高: ${memory.heapUsagePercent.toFixed(1)}%`)
        suggestions.push('建议监控内存使用趋势')
      }
    }

    // 检查缓存命中率
    const cacheStats = this.getCacheStats()
    if (cacheStats.hitRate < this.THRESHOLDS.CACHE_HIT_RATE_CRITICAL / 100) {
      if (status !== 'critical') status = 'warning'
      issues.push(`缓存命中率过低: ${(cacheStats.hitRate * 100).toFixed(1)}%`)
      suggestions.push('检查缓存策略，考虑增加缓存预热')
    }

    // 检查 API 健康
    const apiStats = this.getApiStats()
    const slowApis = apiStats.filter((api) => api.p95Time > this.THRESHOLDS.SLOW_API)
    if (slowApis.length > 0) {
      if (status !== 'critical') status = 'warning'
      issues.push(`${slowApis.length} 个 API 响应较慢`)
      suggestions.push('检查慢 API 的性能瓶颈')
    }

    // 检查组件健康
    const unhealthyComponents = Array.from(this.componentStatus.values()).filter(
      (c) => c.status !== 'healthy',
    )
    if (unhealthyComponents.length > 0) {
      status = 'warning'
      issues.push(`${unhealthyComponents.length} 个组件状态异常`)
      unhealthyComponents.forEach((c) => {
        issues.push(`  - ${c.name}: ${c.status}`)
      })
    }

    const health: SystemHealth = {
      status,
      issues,
      suggestions,
      lastCheck: Date.now(),
    }

    this.healthHistory.push(health)
    if (this.healthHistory.length > this.MAX_HEALTH_HISTORY) {
      this.healthHistory = this.healthHistory.slice(-this.MAX_HEALTH_HISTORY)
    }

    return health
  }

  // ========== 统计信息 ==========

  /**
   * 获取 API 统计（增强版）
   */
  getApiStats(limit: number = 20): ApiStats[] {
    const stats: ApiStats[] = []

    this.apiPerformance.forEach((data, name) => {
      const total = data.times.length
      if (total === 0) return

      const avgTime = data.times.reduce((a, b) => a + b, 0) / total
      const sortedTimes = [...data.times].sort((a, b) => a - b)
      const p95Index = Math.floor(total * 0.95)
      const p99Index = Math.floor(total * 0.99)

      stats.push({
        name,
        count: total,
        totalTime: data.times.reduce((a, b) => a + b, 0),
        avgTime,
        successRate: (data.successes / (data.successes + data.failures)) * 100,
        p95Time: sortedTimes[p95Index] || avgTime,
        p99Time: sortedTimes[p99Index] || avgTime,
        errorCount: data.failures,
      })
    })

    return stats.sort((a, b) => b.avgTime - a.avgTime).slice(0, limit)
  }

  getAverageResponseTime(api: string): number {
    const apiMetrics = this.metrics.filter((m) => m.name === api && m.type === 'api')
    if (apiMetrics.length === 0) return 0

    const sum = apiMetrics.reduce((acc, m) => acc + m.duration, 0)
    return sum / apiMetrics.length
  }

  getSuccessRate(api: string): number {
    const apiMetrics = this.metrics.filter((m) => m.name === api && m.type === 'api')
    if (apiMetrics.length === 0) return 1

    const successes = apiMetrics.filter((m) => m.success).length
    return successes / apiMetrics.length
  }

  getSystemUptime(): number {
    return Date.now() - this.startTime
  }

  getMemoryInfo(): MemoryInfo | null {
    if ('memory' in performance) {
      const memory = (performance as any).memory
      const usagePercent = (memory.usedJSHeapSize / memory.jsHeapSizeLimit) * 100
      return {
        usedJSHeapSize: memory.usedJSHeapSize,
        totalJSHeapSize: memory.totalJSHeapSize,
        jsHeapSizeLimit: memory.jsHeapSizeLimit,
        heapUsagePercent: usagePercent,
      }
    }
    return null
  }

  getRecentMetrics(limit: number = 100, type?: PerformanceMetric['type']): PerformanceMetric[] {
    let filtered = this.metrics
    if (type) {
      filtered = filtered.filter((m) => m.type === type)
    }
    return filtered.slice(-limit)
  }

  getSlowestOperations(limit: number = 10, minDuration: number = 100): PerformanceMetric[] {
    return [...this.metrics]
      .filter((m) => m.duration > minDuration)
      .sort((a, b) => b.duration - a.duration)
      .slice(0, limit)
  }

  /**
   * 获取系统摘要
   */
  getSystemSummary() {
    const memory = this.getMemoryInfo()
    const cache = this.getCacheStats()
    const uptime = this.getSystemUptime()
    const health = this.checkSystemHealth()
    const apiStats = this.getApiStats(5)

    return {
      uptime: this.formatUptime(uptime),
      health: health.status,
      issues: health.issues.length,
      memory: memory
        ? {
            used: this.formatBytes(memory.usedJSHeapSize),
            percent: memory.heapUsagePercent.toFixed(1) + '%',
          }
        : null,
      cache: {
        size: cache.size,
        hitRate: (cache.hitRate * 100).toFixed(1) + '%',
        avgAccessTime: cache.avgAccessTime.toFixed(2) + 'ms',
      },
      slowApis: apiStats.filter((api) => api.p95Time > this.THRESHOLDS.SLOW_API).length,
      components: {
        total: this.componentStatus.size,
        unhealthy: Array.from(this.componentStatus.values()).filter((c) => c.status !== 'healthy')
          .length,
      },
      timestamp: Date.now(),
    }
  }

  // ========== 性能报告 ==========

  generateReport(): any {
    const memory = this.getMemoryInfo()
    const cache = this.getCacheStats()
    const uptime = this.getSystemUptime()
    const health = this.checkSystemHealth()
    const apiStats = this.getApiStats()
    const components = this.getAllComponentStatus()

    // 按类型分组统计
    const metricsByType = {
      api: this.metrics.filter((m) => m.type === 'api').length,
      calculation: this.metrics.filter((m) => m.type === 'calculation').length,
      render: this.metrics.filter((m) => m.type === 'render').length,
      cache: this.metrics.filter((m) => m.type === 'cache').length,
      event: this.metrics.filter((m) => m.type === 'event').length,
    }

    return {
      timestamp: Date.now(),
      summary: {
        uptime: this.formatUptime(uptime),
        totalMetrics: this.metrics.length,
        metricsByType,
        health: health.status,
        issues: health.issues.length,
      },

      health: {
        status: health.status,
        issues: health.issues,
        suggestions: health.suggestions,
        lastCheck: health.lastCheck,
      },

      memory: memory
        ? {
            used: this.formatBytes(memory.usedJSHeapSize),
            total: this.formatBytes(memory.totalJSHeapSize),
            limit: this.formatBytes(memory.jsHeapSizeLimit),
            usagePercent: memory.heapUsagePercent.toFixed(1) + '%',
            status:
              memory.heapUsagePercent > this.THRESHOLDS.MEMORY_CRITICAL
                ? 'critical'
                : memory.heapUsagePercent > this.THRESHOLDS.MEMORY_WARNING
                  ? 'warning'
                  : 'good',
          }
        : null,

      cache: {
        size: cache.size,
        hitRate: (cache.hitRate * 100).toFixed(1) + '%',
        missRate: (cache.missRate * 100).toFixed(1) + '%',
        avgAccessTime: cache.avgAccessTime.toFixed(2) + 'ms',
        byType: cache.byType
          ? Object.fromEntries(
              Object.entries(cache.byType).map(([k, v]) => [
                k,
                {
                  ...v,
                  hitRate: v.hitRate.toFixed(1) + '%',
                },
              ]),
            )
          : undefined,
      },

      api: {
        total: apiStats.length,
        slowApis: apiStats.filter((api) => api.p95Time > this.THRESHOLDS.SLOW_API).length,
        verySlowApis: apiStats.filter((api) => api.p95Time > this.THRESHOLDS.VERY_SLOW_API).length,
        withErrors: apiStats.filter((api) => api.errorCount > 0).length,
        details: apiStats.slice(0, 10).map((stat) => ({
          name: stat.name,
          count: stat.count,
          avgTime: stat.avgTime.toFixed(2) + 'ms',
          p95Time: stat.p95Time.toFixed(2) + 'ms',
          p99Time: stat.p99Time.toFixed(2) + 'ms',
          successRate: stat.successRate.toFixed(1) + '%',
          errorCount: stat.errorCount,
        })),
      },

      components: components.map((c) => ({
        name: c.name,
        status: c.status,
        lastActive: new Date(c.lastActive).toLocaleTimeString(),
        metrics: c.metrics,
      })),

      slowOperations: this.getSlowestOperations(5).map((m) => ({
        name: m.name,
        duration: m.duration + 'ms',
        type: m.type,
        time: new Date(m.timestamp).toLocaleTimeString(),
        success: m.success,
      })),

      emotion: {
        count: this.emotionHistory.length,
        latest: this.emotionHistory.slice(-5),
      },
    }
  }

  // ========== 工具函数 ==========

  private formatUptime(ms: number): string {
    const seconds = Math.floor(ms / 1000)
    const minutes = Math.floor(seconds / 60)
    const hours = Math.floor(minutes / 60)
    const days = Math.floor(hours / 24)

    if (days > 0) return `${days}天 ${hours % 24}小时`
    if (hours > 0) return `${hours}小时 ${minutes % 60}分钟`
    if (minutes > 0) return `${minutes}分钟 ${seconds % 60}秒`
    return `${seconds}秒`
  }

  private formatBytes(bytes: number): string {
    if (bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i]
  }

  // ========== 定时报告 ==========

  private setupPeriodicReporting() {
    return
  }

  // ========== 新增：数据链条监控 ==========

  private dataChain: DataChain = {
    sources: {},
    processors: {},
    calculators: {},
    caches: {},
    presentations: {},
    timestamps: {
      start: Date.now(),
      lastSourceUpdate: 0,
      lastProcessUpdate: 0,
      lastCalcUpdate: 0,
      lastPresentationUpdate: 0,
    },
    health: {
      overall: 'healthy',
      bottlenecks: [],
      warnings: [],
    },
  }

  // ========== 1. 原始数据层监控 ==========

  /**
   * 记录数据源获取
   */
  recordDataSource(
    sourceId: string,
    sourceType: DataFlowMetrics['sourceType'],
    success: boolean,
    responseTime: number,
    bytes?: number,
    error?: string,
  ) {
    if (!this.dataChain.sources[sourceId]) {
      this.dataChain.sources[sourceId] = {
        sourceId,
        sourceType,
        fetchCount: 0,
        successCount: 0,
        failCount: 0,
        totalBytes: 0,
        avgResponseTime: 0,
        p95ResponseTime: 0,
        lastSuccessTime: 0,
        lastFailTime: 0,
      }
    }

    const source = this.dataChain.sources[sourceId]
    source.fetchCount++

    if (success) {
      source.successCount++
      source.lastSuccessTime = Date.now()
      if (bytes) source.totalBytes += bytes
    } else {
      source.failCount++
      source.lastFailTime = Date.now()
      source.failReason = error
    }

    // 更新平均响应时间
    source.avgResponseTime =
      (source.avgResponseTime * (source.fetchCount - 1) + responseTime) / source.fetchCount

    // 更新P95（简化版）
    const responseTimes = this.getResponseTimesForSource(sourceId)
    if (responseTimes.length > 0) {
      const sorted = [...responseTimes].sort((a, b) => a - b)
      const p95Index = Math.floor(sorted.length * 0.95)
      source.p95ResponseTime = sorted[p95Index] || responseTime
    }

    this.dataChain.timestamps.lastSourceUpdate = Date.now()
    this.updateDataChainHealth()
  }

  /**
   * 获取数据源的响应时间历史
   */
  private getResponseTimesForSource(sourceId: string): number[] {
    return this.metrics
      .filter((m) => m.name === sourceId && m.type === 'api')
      .map((m) => m.duration)
      .slice(-100)
  }

  // ========== 2. 数据处理层监控 ==========

  /**
   * 记录数据处理
   */
  recordDataProcessor(
    processorId: string,
    inputCount: number,
    outputCount: number,
    transformTime: number,
    options?: {
      mergeCount?: number
      dedupCount?: number
      enrichCount?: number
    },
  ) {
    if (!this.dataChain.processors[processorId]) {
      this.dataChain.processors[processorId] = {
        processorId,
        inputCount: 0,
        outputCount: 0,
        transformTime: 0,
        mergeCount: 0,
        dedupCount: 0,
        enrichCount: 0,
      }
    }

    const processor = this.dataChain.processors[processorId]
    processor.inputCount += inputCount
    processor.outputCount += outputCount
    processor.transformTime =
      (processor.transformTime * (processor.inputCount - inputCount) + transformTime) /
        processor.inputCount || transformTime

    if (options) {
      processor.mergeCount += options.mergeCount || 0
      processor.dedupCount += options.dedupCount || 0
      processor.enrichCount += options.enrichCount || 0
    }

    this.dataChain.timestamps.lastProcessUpdate = Date.now()
  }

  // ========== 3. 业务计算层监控 ==========

  /**
   * 记录计算器性能
   */
  recordCalculator(calculatorId: string, calcTime: number, cacheHit: boolean, resultSize?: number) {
    if (!this.dataChain.calculators[calculatorId]) {
      this.dataChain.calculators[calculatorId] = {
        calculatorId,
        invokeCount: 0,
        cacheHitCount: 0,
        cacheMissCount: 0,
        avgCalcTime: 0,
        p95CalcTime: 0,
        resultSize: 0,
      }
    }

    const calculator = this.dataChain.calculators[calculatorId]
    calculator.invokeCount++

    if (cacheHit) {
      calculator.cacheHitCount++
    } else {
      calculator.cacheMissCount++
    }

    // 更新平均计算时间
    calculator.avgCalcTime =
      (calculator.avgCalcTime * (calculator.invokeCount - 1) + calcTime) / calculator.invokeCount

    // 更新P95
    const calcTimes = this.getCalculatorTimes(calculatorId)
    if (calcTimes.length > 0) {
      const sorted = [...calcTimes].sort((a, b) => a - b)
      const p95Index = Math.floor(sorted.length * 0.95)
      calculator.p95CalcTime = sorted[p95Index] || calcTime
    }

    if (resultSize) {
      calculator.resultSize = resultSize
    }

    this.dataChain.timestamps.lastCalcUpdate = Date.now()
  }

  /**
   * 获取计算器的耗时历史
   */
  private getCalculatorTimes(calculatorId: string): number[] {
    return this.metrics
      .filter((m) => m.name === calculatorId && m.type === 'calculation')
      .map((m) => m.duration)
      .slice(-100)
  }

  // ========== 4. 缓存层监控 ==========

  /**
   * 更新缓存统计
   */
  updateCacheMetrics(cacheId: string, cacheType: CacheMetrics['type']) {
    try {
      const allStats = cacheManager.getAllStats?.() || {}
      const cacheStat = allStats[cacheType]

      if (cacheStat) {
        this.dataChain.caches[cacheId] = {
          cacheId,
          type: cacheType,
          size: cacheStat.size || 0,
          capacity: this.getCacheCapacity(cacheType),
          hitRate: cacheStat.hitRate || 0,
          missRate: cacheStat.misses ? cacheStat.misses / (cacheStat.hits + cacheStat.misses) : 0,
          evictionCount: cacheStat.evictions || 0,
          avgAccessTime: cacheStat.avgAccessTime || 0,
          hotKeys: (cacheStat.hotKeys || []).slice(0, 5),
          coldKeys: (cacheStat.coldKeys || []).slice(0, 5),
        }
      }
    } catch (e) {
      console.warn('[PerformanceMonitor] 更新缓存统计失败', e)
    }
  }

  /**
   * 获取缓存容量
   */
  private getCacheCapacity(type: string): number {
    const capacities: Record<string, number> = {
      stock: 800,
      leader: 300,
      sector: 600,
      quote: 500,
    }
    return capacities[type] || 0
  }

  // ========== 5. 展示层监控 ==========

  /**
   * 记录面板渲染
   */
  recordPresentation(
    panelId: string,
    renderTime: number,
    dataFreshness: number,
    userInteraction?: boolean,
  ) {
    if (!this.dataChain.presentations[panelId]) {
      this.dataChain.presentations[panelId] = {
        panelId,
        renderCount: 0,
        avgRenderTime: 0,
        dataFreshness: 0,
        updateFrequency: 0,
        userInteractionCount: 0,
      }
    }

    const panel = this.dataChain.presentations[panelId]
    panel.renderCount++
    panel.avgRenderTime =
      (panel.avgRenderTime * (panel.renderCount - 1) + renderTime) / panel.renderCount
    panel.dataFreshness = dataFreshness

    if (userInteraction) {
      panel.userInteractionCount++
    }

    // 计算更新频率（次/分钟）
    const timeWindow = 5 * 60 * 1000 // 5分钟窗口
    const recentRenders = this.metrics.filter(
      (m) => m.type === 'render' && m.name === panelId && Date.now() - m.timestamp < timeWindow,
    ).length
    panel.updateFrequency = recentRenders / (timeWindow / 60000)

    this.dataChain.timestamps.lastPresentationUpdate = Date.now()
  }

  // ========== 数据链条健康分析 ==========

  /**
   * 更新数据链条健康状态
   */
  private updateDataChainHealth() {
    const bottlenecks: string[] = []
    const warnings: string[] = []
    let overall: 'healthy' | 'degraded' | 'critical' = 'healthy'

    // 检查数据源健康
    Object.entries(this.dataChain.sources).forEach(([id, source]) => {
      if (source.fetchCount > 10) {
        const successRate = (source.successCount / source.fetchCount) * 100
        if (successRate < 80) {
          overall = 'degraded'
          warnings.push(`数据源 ${id} 成功率偏低: ${successRate.toFixed(1)}%`)
        }
        if (successRate < 50) {
          overall = 'critical'
          bottlenecks.push(`数据源 ${id} 成功率过低: ${successRate.toFixed(1)}%`)
        }
      }

      if (source.p95ResponseTime > 1000) {
        if (overall !== 'critical') overall = 'degraded'
        warnings.push(`数据源 ${id} P95响应时间过长: ${source.p95ResponseTime.toFixed(0)}ms`)
      }
    })

    // 检查计算器性能
    Object.entries(this.dataChain.calculators).forEach(([id, calc]) => {
      if (calc.p95CalcTime > 200) {
        warnings.push(`计算器 ${id} P95耗时过长: ${calc.p95CalcTime.toFixed(0)}ms`)
      }
      if (calc.p95CalcTime > 500) {
        bottlenecks.push(`计算器 ${id} 性能瓶颈: ${calc.p95CalcTime.toFixed(0)}ms`)
      }

      const cacheHitRate =
        (calc.cacheHitCount / (calc.cacheHitCount + calc.cacheMissCount)) * 100 || 0
      if (calc.invokeCount > 50 && cacheHitRate < 30) {
        warnings.push(`计算器 ${id} 缓存命中率偏低: ${cacheHitRate.toFixed(1)}%`)
      }
    })

    // 检查缓存健康
    Object.entries(this.dataChain.caches).forEach(([id, cache]) => {
      if (cache.hitRate < 20 && cache.size > 0) {
        warnings.push(`缓存 ${id} 命中率过低: ${cache.hitRate.toFixed(1)}%`)
      }
      if (cache.evictionCount > 1000) {
        warnings.push(`缓存 ${id} 淘汰频繁: ${cache.evictionCount}次`)
      }
      if (cache.size / cache.capacity > 0.95) {
        warnings.push(`缓存 ${id} 容量即将耗尽: ${cache.size}/${cache.capacity}`)
      }
    })

    // 检查数据新鲜度
    Object.entries(this.dataChain.presentations).forEach(([id, panel]) => {
      if (panel.dataFreshness > 30000) {
        // 30秒
        warnings.push(`面板 ${id} 数据陈旧: ${(panel.dataFreshness / 1000).toFixed(0)}秒前`)
      }
    })

    this.dataChain.health = {
      overall,
      bottlenecks,
      warnings,
    }
  }

  // ========== 获取完整数据链条 ==========

  /**
   * 获取完整数据链条报告
   */
  getDataChainReport(): DataChain & { summary: string } {
    this.updateDataChainHealth()

    // 生成摘要
    let summary = ''
    const { overall, bottlenecks, warnings } = this.dataChain.health

    if (overall === 'healthy') {
      summary = '✅ 数据链条健康'
    } else if (overall === 'degraded') {
      summary = `⚠️ 数据链条降级 (${warnings.length}个警告)`
    } else {
      summary = `🔴 数据链条严重问题 (${bottlenecks.length}个瓶颈)`
    }

    return {
      ...this.dataChain,
      summary,
    }
  }

  /**
   * 获取数据流图
   */
  getDataFlowGraph() {
    const nodes: Array<{ id: string; type: string; status: string }> = []
    const edges: Array<{ from: string; to: string; latency: number }> = []

    // 添加数据源节点
    Object.keys(this.dataChain.sources).forEach((id) => {
      nodes.push({
        id,
        type: 'source',
        status: this.getNodeStatus(id, 'source'),
      })
    })

    // 添加处理器节点
    Object.keys(this.dataChain.processors).forEach((id) => {
      nodes.push({
        id,
        type: 'processor',
        status: this.getNodeStatus(id, 'processor'),
      })
    })

    // 添加计算器节点
    Object.keys(this.dataChain.calculators).forEach((id) => {
      nodes.push({
        id,
        type: 'calculator',
        status: this.getNodeStatus(id, 'calculator'),
      })
    })

    // 添加缓存节点
    Object.keys(this.dataChain.caches).forEach((id) => {
      nodes.push({
        id,
        type: 'cache',
        status: this.getNodeStatus(id, 'cache'),
      })
    })

    // 添加展示节点
    Object.keys(this.dataChain.presentations).forEach((id) => {
      nodes.push({
        id,
        type: 'presentation',
        status: this.getNodeStatus(id, 'presentation'),
      })
    })

    // 构建边（数据流向）
    // 数据源 → 处理器
    Object.keys(this.dataChain.sources).forEach((sourceId) => {
      Object.keys(this.dataChain.processors).forEach((procId) => {
        edges.push({
          from: sourceId,
          to: procId,
          latency: this.dataChain.sources[sourceId].avgResponseTime || 0,
        })
      })
    })

    // 处理器 → 计算器
    Object.keys(this.dataChain.processors).forEach((procId) => {
      Object.keys(this.dataChain.calculators).forEach((calcId) => {
        edges.push({
          from: procId,
          to: calcId,
          latency: this.dataChain.processors[procId]?.transformTime || 0,
        })
      })
    })

    // 计算器 → 缓存
    Object.keys(this.dataChain.calculators).forEach((calcId) => {
      Object.keys(this.dataChain.caches).forEach((cacheId) => {
        edges.push({
          from: calcId,
          to: cacheId,
          latency: this.dataChain.calculators[calcId]?.avgCalcTime || 0,
        })
      })
    })

    // 缓存 → 展示
    Object.keys(this.dataChain.caches).forEach((cacheId) => {
      Object.keys(this.dataChain.presentations).forEach((presId) => {
        edges.push({
          from: cacheId,
          to: presId,
          latency: this.dataChain.caches[cacheId]?.avgAccessTime || 0,
        })
      })
    })

    return { nodes, edges }
  }

  /**
   * 获取节点状态
   */
  private getNodeStatus(id: string, type: string): string {
    try {
      if (type === 'source') {
        const source = this.dataChain.sources[id]
        if (!source) return 'unknown'
        const successRate = (source.successCount / source.fetchCount) * 100 || 0
        if (successRate < 50) return 'failed'
        if (successRate < 80) return 'degraded'
        if (source.p95ResponseTime > 1000) return 'degraded'
        return 'active'
      }

      if (type === 'cache') {
        const cache = this.dataChain.caches[id]
        if (!cache) return 'unknown'
        if (cache.hitRate < 20) return 'degraded'
        if (cache.hitRate < 10) return 'failed'
        if (cache.size / cache.capacity > 0.95) return 'degraded'
        return 'active'
      }

      return 'active'
    } catch {
      return 'unknown'
    }
  }

  // ========== 数据链条可视化数据 ==========

  /**
   * 获取数据链条统计
   */
  getDataChainStats() {
    const sources = Object.values(this.dataChain.sources)
    const processors = Object.values(this.dataChain.processors)
    const calculators = Object.values(this.dataChain.calculators)
    const caches = Object.values(this.dataChain.caches)
    const presentations = Object.values(this.dataChain.presentations)

    const totalDataIn = sources.reduce((sum, s) => sum + s.fetchCount, 0)
    const totalDataOut = presentations.reduce((sum, p) => sum + p.renderCount, 0)

    const avgLatency = [
      ...sources.map((s) => s.avgResponseTime),
      ...processors.map((p) => p.transformTime),
      ...calculators.map((c) => c.avgCalcTime),
      ...caches.map((c) => c.avgAccessTime),
      ...presentations.map((p) => p.avgRenderTime),
    ]
      .filter((t) => t > 0)
      .reduce((a, b) => a + b, 0)

    const bottleneckCount = this.dataChain.health.bottlenecks.length
    const warningCount = this.dataChain.health.warnings.length

    return {
      totalNodes:
        sources.length +
        processors.length +
        calculators.length +
        caches.length +
        presentations.length,
      totalEdges: this.getDataFlowGraph().edges.length,
      totalDataIn,
      totalDataOut,
      avgLatency: avgLatency.toFixed(0) + 'ms',
      health: this.dataChain.health.overall,
      bottleneckCount,
      warningCount,
      dataFreshness: Math.max(...presentations.map((p) => p.dataFreshness)) || 0,
      cacheHitRateAvg: caches.reduce((sum, c) => sum + c.hitRate, 0) / (caches.length || 1),
    }
  }

  // ========== 重置 ==========

  reset() {
    this.metrics = []
    this.cacheHits = 0
    this.cacheMisses = 0
    this.cacheAccessTimes = []
    this.cacheHitByType.clear()
    this.apiPerformance.clear()
    this.componentStatus.clear()
    this.healthHistory = []
    this.startTime = Date.now()
    console.log('[PerformanceMonitor] 🔄 已重置')
  }
}

export const performanceMonitor = new PerformanceMonitorService()
