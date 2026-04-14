// src/services/Algorithm/AlgorithmStorage.ts
// 算法配置本地存储服务

import { ALGORITHMS } from '@/config/algorithms'
import type { StoredAlgorithmConfig } from '@/types/algorithm'

class AlgorithmStorage {
  private readonly STORAGE_KEY = 'algorithm_config'
  private readonly VERSION = '1.0.0'

  /**
   * 保存算法配置
   */
  saveConfig(
    algorithmId: string,
    weights: Record<string, number>,
    thresholds: Record<string, number>,
  ): void {
    try {
      const data: StoredAlgorithmConfig = {
        algorithmId,
        weights,
        thresholds,
        lastUpdate: new Date().toLocaleTimeString(),
        version: this.VERSION,
      }
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(data))
      console.log('[AlgorithmStorage] ✅ 配置已保存', data)
    } catch (error) {
      console.error('[AlgorithmStorage] ❌ 保存失败:', error)
    }
  }

  /**
   * 加载算法配置
   */
  loadConfig(): StoredAlgorithmConfig | null {
    try {
      const data = localStorage.getItem(this.STORAGE_KEY)
      if (!data) return null

      const config = JSON.parse(data) as StoredAlgorithmConfig
      console.log('[AlgorithmStorage] 📦 从本地加载配置', config)
      return config
    } catch (error) {
      console.error('[AlgorithmStorage] ❌ 加载失败:', error)
      return null
    }
  }

  /**
   * 获取当前活动的算法ID
   */
  getActiveAlgorithmId(): string | null {
    const config = this.loadConfig()
    return config?.algorithmId || null
  }

  /**
   * 获取算法的权重配置
   */
  getAlgorithmWeights(algorithmId: string): Record<string, number> | null {
    const config = this.loadConfig()
    if (config?.algorithmId === algorithmId) {
      return config.weights
    }
    return null
  }

  /**
   * 获取算法的阈值配置
   */
  getAlgorithmThresholds(algorithmId: string): Record<string, number> | null {
    const config = this.loadConfig()
    if (config?.algorithmId === algorithmId) {
      return config.thresholds
    }
    return null
  }

  /**
   * 重置为默认配置
   */
  resetToDefault(algorithmId: string): void {
    localStorage.removeItem(this.STORAGE_KEY)
    console.log('[AlgorithmStorage] 🧹 已重置为默认配置')
  }

  /**
   * 获取最后更新时间
   */
  getLastUpdate(): string | null {
    const config = this.loadConfig()
    return config?.lastUpdate || null
  }
}

export const algorithmStorage = new AlgorithmStorage()
