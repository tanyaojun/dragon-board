// src/services/Algorithm/ConsistencyManager.ts
// 通用数据一致性管理器 - 可被任何模块使用

import type { RepairTask, RepairResult, RepairHandler } from '@/types/algorithm'
import { stockCache, sectorCache, leaderCache } from '@/services/LRUCache'
import { EventManager } from '@/utils/eventManager'

export class ConsistencyManager {
  private repairHistory: RepairTask[] = []
  private readonly MAX_HISTORY = 100
  private repairHandlers: Map<string, RepairHandler> = new Map()

  private destroyed = false

  private unsubscribeFns: (() => void)[] = []

  private readonly CACHE_KEY = 'consistency:history'

  constructor() {
    this.registerDefaultHandlers()
    this.loadFromCache()
  }

  // ========== 供协调者调用的方法 ==========

  /**
   * 后台维护 - 供协调者调用
   */
  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    console.log('[ConsistencyManager] 执行后台维护')

    await this.autoRepairAll()
    this.cleanupHistory()
    this.saveToCache()
  }

  /**
   * 初始化
   */
  init(): () => void {
    if (this.destroyed) {
      console.warn('[ConsistencyManager] 实例已销毁，无法初始化')
      return () => {}
    }

    console.log('[ConsistencyManager] 📊 初始化...')
    console.log('[ConsistencyManager] ✅ 初始化完成')

    return () => this.destroy()
  }

  /**
   * 获取状态
   */
  getStatus(): any {
    if (this.destroyed) return null

    return {
      destroyed: this.destroyed,
      handlerCount: this.repairHandlers.size,
      historyCount: this.repairHistory.length,
      moduleStats: this.getModuleStats(),
    }
  }

  // ========== 私有方法 ==========

  private loadFromCache(): void {
    try {
      const cached = stockCache.get(this.CACHE_KEY)
      if (cached && Array.isArray(cached)) {
        this.repairHistory = cached.slice(-this.MAX_HISTORY)
      }
    } catch (e) {}
  }

  private saveToCache(): void {
    try {
      stockCache.set(this.CACHE_KEY, this.repairHistory.slice(-50), 60 * 60 * 1000)
    } catch (e) {}
  }

  /**
   * 自动修复所有模块
   */
  private async autoRepairAll(): Promise<void> {
    if (this.destroyed) return

    console.log('[ConsistencyManager] 🔧 开始自动修复所有模块...')

    for (const [module, handler] of this.repairHandlers) {
      try {
        const issues = await this.detectModuleIssues(module)
        if (issues.length > 0) {
          await handler(issues)
        }
      } catch (error) {
        console.warn(`[ConsistencyManager] 模块 ${module} 修复失败:`, error)
      }
    }
  }

  /**
   * 检测模块问题
   */
  private async detectModuleIssues(module: string): Promise<string[]> {
    // 可以扩展为调用各模块的检测方法
    return []
  }

  /**
   * 清理过期历史
   */
  private cleanupHistory(): void {
    if (this.destroyed) return

    const now = Date.now()
    const oneWeekAgo = now - 7 * 24 * 60 * 60 * 1000

    this.repairHistory = this.repairHistory.filter((task) => task.timestamp > oneWeekAgo)
    console.log(`[ConsistencyManager] 🧹 已清理历史记录，剩余 ${this.repairHistory.length} 条`)

    this.saveToCache()
  }

  /**
   * 注册修复处理器
   */
  registerHandler(module: string, handler: RepairHandler): void {
    if (this.destroyed) return
    this.repairHandlers.set(module, handler)
    console.log(`[ConsistencyManager] 📝 已注册修复处理器: ${module}`)
  }

  /**
   * 注册默认处理器
   */
  private registerDefaultHandlers(): void {
    this.registerHandler('algorithm', async (issues) => {
      let fixedCount = 0
      const details: any = {}

      for (const issue of issues) {
        if (issue.includes('使用了不存在的因子')) {
          details[issue] = '无法自动修复，需要手动配置'
        } else if (issue.includes('缺少 baseWeight')) {
          const match = issue.match(/算法 (.*?) 的动态因子 (.*?) 缺少 baseWeight/)
          if (match) {
            const [_, algoId, factorId] = match
            console.log(`[ConsistencyManager] 需要为 ${algoId}.${factorId} 设置 baseWeight`)
            fixedCount++
          }
        } else if (issue.includes('缺少 min/max 范围')) {
          const match = issue.match(/算法 (.*?) 的动态因子 (.*?) 缺少 min\/max 范围/)
          if (match) {
            const [_, algoId, factorId] = match
            console.log(
              `[ConsistencyManager] 需要为 ${algoId}.${factorId} 设置范围 min=0.03, max=0.3`,
            )
            fixedCount++
          }
        }
      }

      return {
        success: true,
        fixedCount,
        details,
        module: 'algorithm',
      }
    })

    this.registerHandler('sector', async (issues) => {
      let fixedCount = 0
      const details: any = {}

      for (const issue of issues) {
        if (issue.includes('题材映射不一致')) {
          try {
            const { sectorAnalyzer } = await import('@/services/sectorAnalyzer')
            sectorAnalyzer.syncThemesToStocks?.()
            fixedCount++
            details[issue] = '已触发题材重新同步'
          } catch (error) {
            console.error('[ConsistencyManager] 导入 sectorAnalyzer 失败:', error)
          }
        } else if (issue.includes('股票计数不一致')) {
          const match = issue.match(/题材 (.*?) 的股票计数不一致/)
          if (match) {
            const themeName = match[1]
            console.log(`[ConsistencyManager] 题材 ${themeName} 计数不一致，等待下次计算修复`)
            fixedCount++
          }
        }
      }

      return {
        success: true,
        fixedCount,
        details,
        module: 'sector',
      }
    })

    this.registerHandler('dragon', async (issues) => {
      let fixedCount = 0
      const details: any = {}

      for (const issue of issues) {
        if (issue.includes('龙头级别不匹配')) {
          try {
            const { dragonAnalyzer } = await import('@/services/DragonAnalyzer')
            dragonAnalyzer.recalculateAll?.()
            fixedCount++
            details[issue] = '已触发龙头重新计算'
          } catch (error) {
            console.error('[ConsistencyManager] 导入 dragonAnalyzer 失败:', error)
          }
        } else if (issue.includes('题材热度偏低')) {
          const match = issue.match(/板块龙头 (.*?) 的题材热度/)
          if (match) {
            const code = match[1]
            console.log(`[ConsistencyManager] 龙头 ${code} 题材热度偏低，等待下次计算修复`)
            fixedCount++
          }
        }
      }

      return {
        success: true,
        fixedCount,
        details,
        module: 'dragon',
      }
    })

    this.registerHandler('cache', async (issues) => {
      let fixedCount = 0
      const details: any = {}

      for (const issue of issues) {
        if (issue.includes('缓存命中率过低')) {
          details[issue] = '需要调整缓存策略'
        } else if (issue.includes('缓存淘汰次数过高')) {
          try {
            stockCache.cleanup?.()
            sectorCache.cleanup?.()
            leaderCache.cleanup?.()
            fixedCount++
            details[issue] = '已执行缓存清理'
          } catch (error) {
            console.error('[ConsistencyManager] 清理缓存失败:', error)
          }
        }
      }

      return {
        success: true,
        fixedCount,
        details,
        module: 'cache',
      }
    })
  }

  /**
   * 修复问题
   */
  async repair(options: { module: string; type: string; issues: string[] }): Promise<RepairResult> {
    if (this.destroyed) {
      return {
        success: false,
        fixedCount: 0,
        error: '实例已销毁',
        module: options.module,
      }
    }

    console.log(`[ConsistencyManager] 🔧 开始修复 [${options.module}]: ${options.type}`)

    const task: RepairTask = {
      module: options.module,
      type: options.type,
      issues: options.issues,
      timestamp: Date.now(),
    }

    this.repairHistory.push(task)
    if (this.repairHistory.length > this.MAX_HISTORY) {
      this.repairHistory.shift()
    }

    this.saveToCache()

    const handler = this.repairHandlers.get(options.module)
    if (!handler) {
      return {
        success: false,
        fixedCount: 0,
        error: `未找到模块 ${options.module} 的修复处理器`,
        module: options.module,
      }
    }

    try {
      const result = await handler(options.issues)

      console.log(
        `[ConsistencyManager] ✅ 修复完成 [${options.module}]: 修复了 ${result.fixedCount} 个问题`,
      )

      return result
    } catch (error) {
      console.error('[ConsistencyManager] 修复失败:', error)
      return {
        success: false,
        fixedCount: 0,
        error: error instanceof Error ? error.message : String(error),
        module: options.module,
      }
    }
  }

  /**
   * 批量修复多个模块的问题
   */
  async repairBatch(
    repairs: Array<{
      module: string
      type: string
      issues: string[]
    }>,
  ): Promise<RepairResult[]> {
    if (this.destroyed) return []

    const results: RepairResult[] = []

    for (const repair of repairs) {
      const result = await this.repair(repair)
      results.push(result)
    }

    return results
  }

  /**
   * 获取修复历史
   */
  getRepairHistory(module?: string): RepairTask[] {
    if (this.destroyed) return []

    if (module) {
      return this.repairHistory.filter((t) => t.module === module)
    }
    return [...this.repairHistory]
  }

  /**
   * 获取最后一次修复
   */
  getLastRepair(module?: string): RepairTask | null {
    if (this.destroyed) return null

    if (module) {
      const tasks = this.repairHistory.filter((t) => t.module === module)
      return tasks[tasks.length - 1] || null
    }
    return this.repairHistory[this.repairHistory.length - 1] || null
  }

  /**
   * 获取模块统计
   */
  getModuleStats(): Record<string, { total: number; lastRepair: number }> {
    if (this.destroyed) return {}

    const stats: Record<string, { total: number; lastRepair: number }> = {}

    this.repairHistory.forEach((task) => {
      if (!stats[task.module]) {
        stats[task.module] = { total: 0, lastRepair: 0 }
      }
      stats[task.module].total++
      stats[task.module].lastRepair = Math.max(stats[task.module].lastRepair, task.timestamp)
    })

    return stats
  }

  /**
   * 清除修复历史
   */
  clearHistory(module?: string): void {
    if (this.destroyed) return

    if (module) {
      this.repairHistory = this.repairHistory.filter((t) => t.module !== module)
    } else {
      this.repairHistory = []
    }

    this.saveToCache()
  }

  /**
   * 销毁方法
   */
  destroy(): void {
    if (this.destroyed) return

    console.log('[ConsistencyManager] 💥 开始销毁...')
    this.destroyed = true

    this.unsubscribeFns.forEach((fn) => {
      try {
        fn()
      } catch (e) {}
    })
    this.unsubscribeFns = []

    this.repairHistory = []
    this.repairHandlers.clear()

    try {
      stockCache.delete(this.CACHE_KEY)
    } catch (e) {}

    console.log('[ConsistencyManager] ✅ 已销毁')
  }
}

// 导出单例
export const consistencyManager = new ConsistencyManager()