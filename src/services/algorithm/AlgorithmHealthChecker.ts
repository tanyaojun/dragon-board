// src/services/Algorithm/AlgorithmHealthChecker.ts
// 健康检查模块

import type { IAlgorithmManager } from './AlgorithmManager'
import type { FactorHealth, HealthCheckResult, FactorPerformance } from '@/types/algorithm'

import { FACTORS } from '@/config/factors'
import { ALGORITHMS } from '@/config/algorithms'
import { EventManager } from '@/utils/eventManager'
import { consistencyManager } from './ConsistencyManager'
import { stockCache } from '@/services/LRUCache'
import { PHASE_MULTIPLIERS } from '@/config/algorithms'

export class AlgorithmHealthChecker {
  private algorithmManager: IAlgorithmManager
  private readonly CHECK_INTERVAL = 5 * 60 * 1000 // 5分钟
  private autoRepair = true
  private lastCheckResult: HealthCheckResult | null = null

  constructor(algorithmManager: IAlgorithmManager) {
    this.algorithmManager = algorithmManager
  }

  /**
   * 启动健康检查
   */
  start(autoRepair: boolean = true): void {
    if (this.timer) return

    this.autoRepair = autoRepair
    console.log('[AlgorithmHealth] 🏥 启动健康检查...')

    // 立即执行一次
    this.check()
  }

  /**
   * 停止健康检查
   */
  stop(): void {}

  /**
   * ✅ 新增：供 AlgorithmManager 调用的维护方法
   */
  async runMaintenance(): Promise<void> {
    console.log('[AlgorithmHealth] 执行后台维护')
    await this.check()
  }

  /**
   * 执行健康检查
   */
  async check(): Promise<HealthCheckResult> {
    const issues: string[] = []
    const warnings: string[] = []
    const suggestions: string[] = []

    // 1. 检查算法配置与因子定义的一致性
    this.checkAlgorithmFactorConsistency(issues, warnings, suggestions)

    // 2. 检查动态权重配置
    this.checkDynamicWeights(issues, warnings, suggestions)

    // 3. 检查阶段乘数与因子定义的一致性
    this.checkPhaseMultipliers(issues, warnings, suggestions)

    // 4. 检查因子健康度
    await this.checkFactorHealth(warnings, suggestions)

    // 5. 检查缓存健康度
    this.checkCacheHealth(warnings, suggestions)

    const result: HealthCheckResult = {
      valid: issues.length === 0,
      issues,
      warnings,
      suggestions,
      timestamp: Date.now(),
    }

    this.lastCheckResult = result

    // 如果有问题且开启了自动修复，尝试修复
    if (!result.valid && this.autoRepair) {
      await this.repair(result)
    }

    // 触发事件
    EventManager.emit('algorithm:health-checked', result)

    // 输出日志
    this.logHealthCheck(result)

    return result
  }

  /**
   * 检查算法因子一致性
   */
  private checkAlgorithmFactorConsistency(
    issues: string[],
    warnings: string[],
    suggestions: string[],
  ): void {
    Object.entries(ALGORITHMS).forEach(([algoId, algo]) => {
      Object.keys(algo.factors).forEach((factorId) => {
        if (!FACTORS[factorId]) {
          issues.push(`算法 ${algoId} 使用了不存在的因子: ${factorId}`)
          suggestions.push(`建议从算法 ${algoId} 中移除因子 ${factorId}`)
        }
      })
    })
  }

  /**
   * 检查动态权重配置
   */
  private checkDynamicWeights(issues: string[], warnings: string[], suggestions: string[]): void {
    Object.entries(ALGORITHMS).forEach(([algoId, algo]) => {
      Object.entries(algo.factors).forEach(([factorId, config]) => {
        if (config.weight === 'dynamic') {
          if (!config.baseWeight) {
            issues.push(`算法 ${algoId} 的动态因子 ${factorId} 缺少 baseWeight`)
            suggestions.push(`为因子 ${factorId} 设置 baseWeight 默认值 0.1`)
          }
          if (!config.min || !config.max) {
            issues.push(`算法 ${algoId} 的动态因子 ${factorId} 缺少 min/max 范围`)
            suggestions.push(`为因子 ${factorId} 设置范围 min=0.03, max=0.3`)
          }
          if (config.baseWeight && (config.baseWeight < 0.01 || config.baseWeight > 0.5)) {
            warnings.push(
              `算法 ${algoId} 的因子 ${factorId} baseWeight 可能不合理: ${config.baseWeight}`,
            )
          }
        }
      })
    })
  }

  /**
   * 检查阶段乘数
   */
  private checkPhaseMultipliers(issues: string[], warnings: string[], suggestions: string[]): void {
    // 直接使用导入的 PHASE_MULTIPLIERS
    Object.entries(PHASE_MULTIPLIERS).forEach(([phase, multipliers]) => {
      Object.keys(multipliers).forEach((factorId) => {
        if (!FACTORS[factorId]) {
          warnings.push(`阶段 ${phase} 使用了不存在的因子: ${factorId}`)
          suggestions.push(`考虑从阶段 ${phase} 的配置中移除因子 ${factorId}`)
        }
      })
    })
  }

  /**
   * 检查因子健康度
   */
  private async checkFactorHealth(warnings: string[], suggestions: string[]): Promise<void> {
    // 这里需要从性能监控模块获取因子性能数据
    // 暂时跳过，等待集成
  }

  /**
   * 检查缓存健康度
   */
  private checkCacheHealth(warnings: string[], suggestions: string[]): void {
    const cacheStats = stockCache.getStats()

    if (cacheStats.hitRate < 50) {
      warnings.push(`缓存命中率过低: ${cacheStats.hitRate.toFixed(2)}%`)
      suggestions.push('考虑增加缓存TTL或优化缓存策略')
    }

    if (cacheStats.evictions > 1000) {
      warnings.push(`缓存淘汰次数过高: ${cacheStats.evictions}`)
      suggestions.push('考虑增加缓存容量')
    }

    if (cacheStats.memoryUsage > 10 * 1024 * 1024) {
      warnings.push(`缓存内存使用过高: ${(cacheStats.memoryUsage / 1024 / 1024).toFixed(2)}MB`)
      suggestions.push('考虑减少缓存容量或优化数据结构')
    }
  }

  /**
   * 尝试修复问题
   */
  private async repair(result: HealthCheckResult): Promise<void> {
    console.log('[AlgorithmHealth] 🔧 尝试自动修复...')

    // 使用一致性管理器修复
    const repairResult = await consistencyManager.repair({
      type: 'algorithm',
      issues: result.issues,
    })

    if (repairResult.success) {
      console.log(`[AlgorithmHealth] ✅ 修复成功: ${repairResult.fixedCount}个问题`)

      // 使缓存失效
      this.algorithmManager.invalidateCache()
    } else {
      console.warn(`[AlgorithmHealth] ⚠️ 修复失败: ${repairResult.error}`)
    }
  }

  /**
   * 输出健康检查日志
   */
  private logHealthCheck(result: HealthCheckResult): void {
    if (result.valid) {
      console.log('[AlgorithmHealth] ✅ 健康检查通过')
      return
    }

    console.warn('[AlgorithmHealth] ⚠️ 健康检查发现问题:')

    if (result.issues.length > 0) {
      console.warn('   ├─ 严重问题:')
      result.issues.slice(0, 3).forEach((issue) => {
        console.warn(`   │  └─ ${issue}`)
      })
    }

    if (result.warnings.length > 0) {
      console.warn('   ├─ 警告:')
      result.warnings.slice(0, 3).forEach((warning) => {
        console.warn(`   │  └─ ${warning}`)
      })
    }

    if (result.suggestions.length > 0) {
      console.log('   └─ 建议:')
      result.suggestions.slice(0, 3).forEach((suggestion) => {
        console.log(`      └─ ${suggestion}`)
      })
    }
  }

  /**
   * 获取上次检查结果
   */
  getLastCheckResult(): HealthCheckResult | null {
    return this.lastCheckResult
  }

  /**
   * 手动触发检查
   */
  async checkNow(): Promise<HealthCheckResult> {
    return this.check()
  }

  /**
   * 切换自动修复模式
   */
  setAutoRepair(enabled: boolean): void {
    this.autoRepair = enabled
    console.log(`[AlgorithmHealth] 🔧 自动修复已${enabled ? '开启' : '关闭'}`)
  }

  stop() {
    if (this.timers.checkTimer) {
      clearInterval(this.timers.checkTimer)
      this.timers.checkTimer = null
    }
  }
}
