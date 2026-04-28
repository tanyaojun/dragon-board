import { debugLog } from '@/utils/logger'
// src/services/AlgorithmConfigManager.ts
// 重构版：直接使用 FACTORS 和 ALGORITHMS，移除 FactorRegistry 依赖

import { ALGORITHMS } from '@/config/algorithms'
import { FACTORS } from '@/config/factors'
import type { Algorithm } from '@/types/algorithm'

/**
 * 算法配置管理器
 * 负责算法的创建、查询、导入导出
 */
export class AlgorithmConfigManager {
  private static instance: AlgorithmConfigManager
  private algorithms: Map<string, Algorithm> = new Map()
  private customAlgorithms: Map<string, Algorithm> = new Map()

  private constructor() {
    this.loadDefaultAlgorithms()
    debugLog('[AlgorithmConfigManager] 📋 初始化完成')
  }

  static getInstance(): AlgorithmConfigManager {
    if (!AlgorithmConfigManager.instance) {
      AlgorithmConfigManager.instance = new AlgorithmConfigManager()
    }
    return AlgorithmConfigManager.instance
  }

  /**
   * 加载默认算法
   */
  private loadDefaultAlgorithms() {
    Object.entries(ALGORITHMS).forEach(([id, algo]) => {
      this.algorithms.set(id, algo)
    })
    debugLog(`[AlgorithmConfigManager] 📦 加载默认算法: ${this.algorithms.size}个`)
  }

  /**
   * 获取所有可用因子（供算法配置使用）
   * 直接从 FACTORS 读取
   */
  getAvailableFactors() {
    return Object.entries(FACTORS).map(([id, factor]) => ({
      id,
      name: factor.name,
      type: factor.type,
      category: factor.category,
      description: factor.description,
      enabled: false,
      recommendedWeight: this.getRecommendedWeight(id, factor.type)
    }))
  }

  /**
   * 获取推荐权重
   * 根据因子类型和历史经验给出默认权重建议
   */
  private getRecommendedWeight(factorId: string, type: string): number {
    // 基于因子类型的默认权重
    const typeDefaults: Record<string, number> = {
      rank: 0.2,        // 排名类
      percent: 0.15,     // 百分比类
      money: 0.15,       // 资金类
      scale: 0.1,        // 规模类
      count: 0.15,       // 计数类
      theme: 0.2,        // 题材类
      momentum: 0.15,    // 动量类
      breath: 0.15,      // 龙息类
      sentiment: 0.1,    // 情绪类
    }

    // 特定因子的推荐权重（从现有算法中提取经验值）
    const factorRecommendations: Record<string, number> = {
      // 基础因子 - 从 balanced 算法中参考
      compRank: 0.15,
      change: 0.08,
      turnover: 0.08,
      turnoverRate: 0.06,
      zlje: 0.1,
      zljzb: 0.08,
      marketCap: 0.1,
      continuousDays: 0.1,
      
      // 题材因子
      themeHeat: 0.08,
      themeLeaderCount: 0.08,
      themeMomentum: 0.06,
      
      // 龙息因子 - 使用 BREATH_FACTOR_IDS 对应的值
      breathPhase: 0.08,
      breathZtCount: 0.06,
      breathDtCount: 0.05,
      breathZhabanRate: 0.05,
      breathFengbanRate: 0.05,
      breathPassRate: 0.07,
      breathMaxDays: 0.08,
      breathUpDownRatio: 0.04,
      breathEmotionValue: 0.03,
      breathMarketScore: 0.03,
      
      // 逆势因子
      contrarian: 0.06,
    }

    // 优先返回特定因子的推荐值，否则使用类型默认值
    return factorRecommendations[factorId] || typeDefaults[type] || 0.1
  }

  /**
   * 创建自定义算法
   */
  createCustomAlgorithm(
    name: string, 
    description: string, 
    factorConfigs: Record<string, {
      weight: number
      enabled?: boolean
      min?: number
      max?: number
    }>
  ) {
    const id = `custom_${Date.now()}`
    
    // 验证因子是否存在并构建配置
    const factors: Record<string, any> = {}
    let totalWeight = 0

    Object.entries(factorConfigs).forEach(([factorId, config]) => {
      // 检查因子是否存在
      if (!FACTORS[factorId]) {
        throw new Error(`因子不存在: ${factorId}`)
      }

      factors[factorId] = {
        weight: config.weight,
        enabled: config.enabled !== false,
        min: config.min,
        max: config.max
      }
      totalWeight += config.weight
    })

    // 权重总和应该接近1，给出警告但继续
    if (Math.abs(totalWeight - 1) > 0.1) {
      console.warn(`[AlgorithmConfigManager] ⚠️ 权重总和为 ${totalWeight.toFixed(2)}，建议调整到接近1`)
    }

    const algorithm: Algorithm = {
      id,
      name,
      icon: '⚙️',
      description,
      category: 'custom',
      color: '#95a5a6',
      factors,
      phaseMultipliers: {}, // 自定义算法默认没有阶段乘数
      leaderThresholds: {   // 使用默认阈值
        total: { minScore: 70 },
        sector: { minScore: 60 },
        continuous: { minScore: 65 },
        middle: { minScore: 55 },
        emotion: { minScore: 50 },
      }
    }

    this.customAlgorithms.set(id, algorithm)
    debugLog(`[AlgorithmConfigManager] ✅ 创建自定义算法: ${name} (${id})`)
    
    return { id, algorithm }
  }

  /**
   * 获取算法列表（含自定义）
   */
  getAlgorithmList() {
    const list: Array<{
      id: string
      name: string
      icon: string
      description: string
      category: string
      color: string
      factorCount: number
      isCustom: boolean
    }> = []

    // 默认算法
    this.algorithms.forEach((algo, id) => {
      list.push({
        id,
        name: algo.name,
        icon: algo.icon,
        description: algo.description,
        category: algo.category,
        color: algo.color,
        factorCount: Object.keys(algo.factors).length,
        isCustom: false
      })
    })

    // 自定义算法
    this.customAlgorithms.forEach((algo, id) => {
      list.push({
        id,
        name: algo.name,
        icon: algo.icon,
        description: algo.description,
        category: 'custom',
        color: algo.color,
        factorCount: Object.keys(algo.factors).length,
        isCustom: true
      })
    })

    return list
  }

  /**
   * 获取算法详情
   */
  getAlgorithm(id: string): Algorithm | undefined {
    return this.algorithms.get(id) || this.customAlgorithms.get(id)
  }

  /**
   * 获取算法详情（包含因子详细信息）
   */
  getAlgorithmDetail(id: string) {
    const algorithm = this.getAlgorithm(id)
    if (!algorithm) return null

    // 增强因子信息，添加因子名称和描述
    const enhancedFactors = Object.entries(algorithm.factors).map(([factorId, config]) => {
      const factor = FACTORS[factorId]
      return {
        id: factorId,
        name: factor?.name || factorId,
        description: factor?.description || '',
        type: factor?.type || 'unknown',
        category: factor?.category || 'unknown',
        ...config
      }
    })

    return {
      ...algorithm,
      factors: enhancedFactors
    }
  }

  /**
   * 删除自定义算法
   */
  deleteCustomAlgorithm(id: string): boolean {
    if (!id.startsWith('custom_')) {
      console.warn(`[AlgorithmConfigManager] ⚠️ 只能删除自定义算法: ${id}`)
      return false
    }
    
    const deleted = this.customAlgorithms.delete(id)
    if (deleted) {
      debugLog(`[AlgorithmConfigManager] 🗑️ 删除自定义算法: ${id}`)
    }
    return deleted
  }

  /**
   * 更新自定义算法
   */
  updateCustomAlgorithm(
    id: string,
    updates: Partial<{
      name: string
      description: string
      color: string
      factors: Record<string, any>
    }>
  ): boolean {
    if (!id.startsWith('custom_')) {
      console.warn(`[AlgorithmConfigManager] ⚠️ 只能更新自定义算法: ${id}`)
      return false
    }

    const algorithm = this.customAlgorithms.get(id)
    if (!algorithm) return false

    // 更新字段
    if (updates.name) algorithm.name = updates.name
    if (updates.description) algorithm.description = updates.description
    if (updates.color) algorithm.color = updates.color
    
    // 更新因子配置
    if (updates.factors) {
      // 验证因子
      Object.keys(updates.factors).forEach(factorId => {
        if (!FACTORS[factorId]) {
          throw new Error(`因子不存在: ${factorId}`)
        }
      })
      algorithm.factors = updates.factors
    }

    debugLog(`[AlgorithmConfigManager] 📝 更新自定义算法: ${id}`)
    return true
  }

  /**
   * 导出算法配置
   */
  exportConfig() {
    return {
      defaultAlgorithms: Object.fromEntries(this.algorithms),
      customAlgorithms: Object.fromEntries(this.customAlgorithms),
      exportTime: Date.now()
    }
  }

  /**
   * 导入算法配置
   */
  importConfig(config: any): { success: boolean; importedCount: number; errors: string[] } {
    const errors: string[] = []
    let importedCount = 0

    if (config.customAlgorithms) {
      Object.entries(config.customAlgorithms).forEach(([id, algo]: [string, any]) => {
        try {
          // 验证算法格式
          if (!algo.name || !algo.factors) {
            errors.push(`算法 ${id} 格式错误`)
            return
          }

          // 验证因子是否存在
          Object.keys(algo.factors).forEach(factorId => {
            if (!FACTORS[factorId]) {
              throw new Error(`因子 ${factorId} 不存在`)
            }
          })

          this.customAlgorithms.set(id, algo as Algorithm)
          importedCount++
        } catch (error) {
          errors.push(`算法 ${id} 导入失败: ${error.message}`)
        }
      })
    }

    debugLog(`[AlgorithmConfigManager] 📥 导入完成: ${importedCount}个算法, ${errors.length}个错误`)
    
    return {
      success: errors.length === 0,
      importedCount,
      errors
    }
  }

  /**
   * 获取算法统计信息
   */
  getStats() {
    return {
      totalDefault: this.algorithms.size,
      totalCustom: this.customAlgorithms.size,
      total: this.algorithms.size + this.customAlgorithms.size,
      categories: {
        comprehensive: Array.from(this.algorithms.values()).filter(a => a.category === 'comprehensive').length,
        leader: Array.from(this.algorithms.values()).filter(a => a.category === 'leader').length,
        money: Array.from(this.algorithms.values()).filter(a => a.category === 'money').length,
        sentiment: Array.from(this.algorithms.values()).filter(a => a.category === 'sentiment').length,
        ml: Array.from(this.algorithms.values()).filter(a => a.category === 'ml').length,
        custom: this.customAlgorithms.size
      }
    }
  }

  /**
   * 重置所有自定义算法
   */
  resetCustomAlgorithms() {
    const count = this.customAlgorithms.size
    this.customAlgorithms.clear()
    debugLog(`[AlgorithmConfigManager] 🔄 重置所有自定义算法: 共 ${count} 个`)
    return count
  }
}

// 导出单例
export const algorithmConfigManager = AlgorithmConfigManager.getInstance()

// 开发环境挂载到window
if (typeof window !== 'undefined' && process.env.NODE_ENV === 'development') {
  ;(window as any).algorithmConfigManager = algorithmConfigManager
}