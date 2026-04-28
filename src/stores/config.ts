import { debugLog } from '@/utils/logger'
// src/stores/config.ts

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AppConfig, SystemConfig, UserConfig, AlgorithmConfig } from '../types'
import { ErrorHandler } from '../utils/errorHandler'

// 默认配置
const DEFAULT_CONFIG: AppConfig = {
  system: {
    version: '6.0.0',
    debug: true,
    env: 'development',
    proxyUrl: 'http://localhost:3000/api/',
    timeout: 10000,
    retryCount: 2,
    useMockWebSocket: false,
  },
  modules: {
    dataLoader: {
      platforms: ['eastmoney', 'ths', 'kpl', 'tdx', 'xueqiu', 'cls', 'tgb', 'dzh'],
      platformWeights: {
        kpl: 1.0,
        tdx: 0.9,
        ths: 0.85,
        eastmoney: 0.75,
        dzh: 0.7,
        xueqiu: 0.35,
        cls: 0.35,
        tgb: 0.4,
      },
      quoteBatchSize: 30,
      quoteBatchDelay: 50,
    },
    renderer: {
      fontSize: 12,
      rowHeight: 32,
      showLeaderBadge: true,
      showSectorTags: true,
    },
    dragonBreath: {
      autoRefresh: true,
      refreshInterval: 30000,
    },
  },
  cache: {
    stock: {
      enabled: true,
      capacity: 500,
      ttl: 30 * 60 * 1000,
      maxMemory: 5 * 1024 * 1024,
      persist: true,
    },
    leader: {
      enabled: true,
      capacity: 100,
      ttl: 60 * 60 * 1000,
      maxMemory: 2 * 1024 * 1024,
      persist: true,
    },
    sector: {
      enabled: true,
      capacity: 500,
      ttl: 4 * 60 * 60 * 1000,
      maxMemory: 5 * 1024 * 1024,
      persist: true,
    },
    quote: {
      enabled: true,
      capacity: 1000,
      ttl: 30 * 1000,
      maxMemory: 2 * 1024 * 1024,
      persist: false,
    },
  },
  user: {
    theme: 'dark',
    followSystemTheme: false,
    refreshStrategy: 'balanced',
    refreshEnabled: true,
    tradingTimeOnly: true,
    fullRefreshInterval: 60 * 60 * 1000,
    incrementalRefreshInterval: 5 * 60 * 1000,
    favoriteGroups: ['默认'],
  },
  algorithm: {
    current: 'balanced',
    thresholds: {
      totalLeader: 80,
      sectorLeader: 65,
      continuousLeader: 70,
      middleLeader: 60,
      emotionLeader: 55,
    },
  },
}

export const useConfigStore = defineStore('config', () => {
  // ========== State ==========
  const config = ref<AppConfig>({ ...DEFAULT_CONFIG })
  const loaded = ref(false)

  // ========== Getters ==========
  const system = computed(() => config.value.system)
  const user = computed(() => config.value.user)
  const algorithm = computed(() => config.value.algorithm)
  const fullConfig = computed(() => config.value)

  // ========== Actions ==========
  function loadConfig() {
    try {
      // 从 localStorage 加载
      const saved = localStorage.getItem('app_config')
      if (saved) {
        const parsed = JSON.parse(saved)
        config.value = mergeConfig(DEFAULT_CONFIG, parsed)
      }

      // 向后兼容：读取旧的 localStorage 值
      migrateOldConfig()

      loaded.value = true
      debugLog('[ConfigStore] 📋 配置加载完成', config.value)
    } catch (error) {
      ErrorHandler.handle(error, 'ConfigStore.loadConfig')
    }
  }

  function migrateOldConfig() {
    const oldTheme = localStorage.getItem('kpl_theme')
    if (oldTheme && ['dark', 'light', 'matrix', 'cream'].includes(oldTheme)) {
      config.value.user.theme = oldTheme as UserConfig['theme']
    }

    const oldStrategy = localStorage.getItem('refresh_strategy')
    const validStrategies = ['balanced', 'aggressive', 'conservative', 'recovery']
    if (oldStrategy && validStrategies.includes(oldStrategy)) {
      config.value.user.refreshStrategy = oldStrategy as UserConfig['refreshStrategy']
    }

    const oldAlgorithm = localStorage.getItem('algorithm')
    const validAlgorithms = [
      'balanced',
      'dragonFirst',
      'moneyDriven',
      'techDriven',
      'sentimentDriven',
      'ml',
    ]
    if (oldAlgorithm && validAlgorithms.includes(oldAlgorithm)) {
      config.value.algorithm.current = oldAlgorithm
    }
  }

  function saveConfig() {
    try {
      localStorage.setItem('app_config', JSON.stringify(config.value))

      // 向后兼容
      localStorage.setItem('kpl_theme', config.value.user.theme)
      localStorage.setItem('refresh_strategy', config.value.user.refreshStrategy)
      localStorage.setItem('algorithm', config.value.algorithm.current)

      debugLog('[ConfigStore] 💾 配置已保存')
    } catch (error) {
      ErrorHandler.handle(error, 'ConfigStore.saveConfig')
    }
  }

  function setUserConfig<K extends keyof UserConfig>(key: K, value: UserConfig[K]) {
    config.value.user[key] = value
    saveConfig()

    // 触发自定义事件（用于兼容旧代码）
    window.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { path: `user.${key}`, newValue: value },
      }),
    )
  }

  function setSystemConfig<K extends keyof SystemConfig>(key: K, value: SystemConfig[K]) {
    config.value.system[key] = value
    saveConfig()

    window.dispatchEvent(
      new CustomEvent('config-changed', {
        detail: { path: `system.${key}`, newValue: value },
      }),
    )
  }

  function setAlgorithm(algorithmId: AlgorithmConfig['current']) {
    config.value.algorithm.current = algorithmId
    saveConfig()

    window.dispatchEvent(
      new CustomEvent('algorithm-changed', {
        detail: { algorithm: algorithmId },
      }),
    )
  }

  function setThreshold(threshold: keyof AlgorithmConfig['thresholds'], value: number) {
    config.value.algorithm.thresholds[threshold] = value
    saveConfig()

    window.dispatchEvent(
      new CustomEvent('thresholds-changed', {
        detail: { threshold, value },
      }),
    )
  }

  function resetToDefaults() {
    config.value = { ...DEFAULT_CONFIG }
    saveConfig()
  }

  // ========== 工具函数 ==========
  function mergeConfig(target: any, source: any): any {
    const output = { ...target }
    for (const key in source) {
      if (source[key] instanceof Object && !Array.isArray(source[key])) {
        output[key] = mergeConfig(target[key] || {}, source[key])
      } else {
        output[key] = source[key]
      }
    }
    return output
  }

  // 初始化
  loadConfig()

  return {
    // state
    config,
    loaded,
    // getters
    system,
    user,
    algorithm,
    fullConfig,
    // actions
    setUserConfig,
    setSystemConfig,
    setAlgorithm,
    setThreshold,
    resetToDefaults,
    saveConfig,
  }
})
