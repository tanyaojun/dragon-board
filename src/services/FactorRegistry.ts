// src/services/FactorRegistry.ts（新增文件）

import { FACTORS } from '@/data/factors'
import type { Factor } from '@/types'

/**
 * 因子注册器 - 统一管理所有因子的注册
 */
export class FactorRegistry {
  private static instance: FactorRegistry
  private factors: Map<string, Factor> = new Map()
  private dependencies: Map<string, string[]> = new Map() // 因子依赖的服务

  private constructor() {
    // 初始化时加载已有因子
    this.loadExistingFactors()
  }

  static getInstance(): FactorRegistry {
    if (!FactorRegistry.instance) {
      FactorRegistry.instance = new FactorRegistry()
    }
    return FactorRegistry.instance
  }

  /**
   * 加载已有因子
   */
  private loadExistingFactors() {
    Object.entries(FACTORS).forEach(([id, factor]) => {
      this.factors.set(id, factor)
    })
  }

  /**
   * 注册因子
   */
  register(id: string, factor: Factor, dependencies?: string[]) {
    if (this.factors.has(id)) {
      console.warn(`[FactorRegistry] ⚠️ 因子 ${id} 已存在，将被覆盖`)
    }

    this.factors.set(id, factor)
    if (dependencies) {
      this.dependencies.set(id, dependencies)
    }

    // 同步到 FACTORS 对象
    ;(FACTORS as any)[id] = factor

    return this
  }

  /**
   * 批量注册因子
   */
  registerBatch(factors: Record<string, { factor: Factor; dependencies?: string[] }>) {
    Object.entries(factors).forEach(([id, { factor, dependencies }]) => {
      this.register(id, factor, dependencies)
    })
    return this
  }

  /**
   * 获取因子
   */
  get(id: string): Factor | undefined {
    return this.factors.get(id)
  }

  /**
   * 获取所有因子
   */
  getAll(): Map<string, Factor> {
    return new Map(this.factors)
  }

  /**
   * 按类型获取因子
   */
  getByType(type: string): [string, Factor][] {
    return Array.from(this.factors.entries()).filter(([_, factor]) => factor.type === type)
  }

  /**
   * 按分类获取因子
   */
  getByCategory(category: string): [string, Factor][] {
    return Array.from(this.factors.entries()).filter(([_, factor]) => factor.category === category)
  }

  /**
   * 检查依赖是否满足
   */
  checkDependencies(id: string): { satisfied: boolean; missing: string[] } {
    const deps = this.dependencies.get(id) || []
    const missing = deps.filter((dep) => {
      // 检查依赖的服务是否存在
      if (dep.startsWith('service:')) {
        const serviceName = dep.replace('service:', '')
        return !(window as any)[serviceName]
      }
      // 检查依赖的因子是否存在
      return !this.factors.has(dep)
    })

    return {
      satisfied: missing.length === 0,
      missing,
    }
  }

  /**
   * 获取因子统计
   */
  getStats() {
    const byType: Record<string, number> = {}
    const byCategory: Record<string, number> = {}

    this.factors.forEach((factor, id) => {
      byType[factor.type] = (byType[factor.type] || 0) + 1
      byCategory[factor.category] = (byCategory[factor.category] || 0) + 1
    })

    return {
      total: this.factors.size,
      byType,
      byCategory,
      withDependencies: this.dependencies.size,
    }
  }
}

// 导出单例
export const factorRegistry = FactorRegistry.getInstance()

// ===== 挂载到 window =====
if (typeof window !== 'undefined') {
  ;(window as any).factorRegistry = factorRegistry
}
