import { STORAGE_KEYS } from '@/config/storage'

import {
  DEFAULT_STOCK_HOTNESS_CONFIG,
  normalizeStockHotnessConfig,
  type StockHotnessConfig,
  type StockHotnessConfigInput,
} from './StockHotnessCalculator'

const HOTNESS_STORAGE_KEY =
  (STORAGE_KEYS as Record<string, string>).HOTNESS_CONFIG || 'stock_hotness_config'

function canUseStorage(): boolean {
  return typeof localStorage !== 'undefined'
}

/**
 * 个股热度配置服务只负责参数持久化和运行时读取，
 * 不承载任何热度计算逻辑，避免“配方”和“计算器”相互污染。
 */
class StockHotnessConfigService {
  private runtimeConfig: StockHotnessConfig = { ...DEFAULT_STOCK_HOTNESS_CONFIG }

  constructor() {
    this.runtimeConfig = this.loadConfig()
  }

  getConfig(): StockHotnessConfig {
    return {
      weights: { ...this.runtimeConfig.weights },
    }
  }

  saveConfig(config: StockHotnessConfigInput | StockHotnessConfig): StockHotnessConfig {
    const normalized = normalizeStockHotnessConfig(config)
    this.runtimeConfig = normalized

    if (canUseStorage()) {
      localStorage.setItem(HOTNESS_STORAGE_KEY, JSON.stringify(normalized))
    }

    return this.getConfig()
  }

  updateConfig(patch: StockHotnessConfigInput): StockHotnessConfig {
    return this.saveConfig({
      weights: {
        ...this.runtimeConfig.weights,
        ...(patch.weights || {}),
      },
    })
  }

  reset(): StockHotnessConfig {
    this.runtimeConfig = normalizeStockHotnessConfig(DEFAULT_STOCK_HOTNESS_CONFIG)
    if (canUseStorage()) {
      localStorage.removeItem(HOTNESS_STORAGE_KEY)
    }
    return this.getConfig()
  }

  private loadConfig(): StockHotnessConfig {
    if (!canUseStorage()) {
      return normalizeStockHotnessConfig(DEFAULT_STOCK_HOTNESS_CONFIG)
    }

    try {
      const raw = localStorage.getItem(HOTNESS_STORAGE_KEY)
      if (!raw) {
        return normalizeStockHotnessConfig(DEFAULT_STOCK_HOTNESS_CONFIG)
      }

      return normalizeStockHotnessConfig(JSON.parse(raw))
    } catch (error) {
      console.error('[StockHotnessConfigService] 加载热度配置失败，回退默认配置:', error)
      return normalizeStockHotnessConfig(DEFAULT_STOCK_HOTNESS_CONFIG)
    }
  }
}

export const stockHotnessConfigService = new StockHotnessConfigService()
