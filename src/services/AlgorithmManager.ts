// src/services/AlgorithmManager.ts
// 优化版：使用 stockCache 和分级TTL

import type {
  Stock,
  Factor,
  FactorConfig,
  Algorithm,
  Thresholds,
  ThresholdRanges,
  FactorDetail,
  ScoreResult,
  PerformanceStat,
  PerformanceRecord,
  ThemeFactors,
  LeaderThresholds,
} from '@/types'

import {
  THEME_FACTOR_IDS,
  BREATH_FACTOR_IDS,
  DEFAULT_THRESHOLDS,
  THRESHOLD_RANGES,
  STORAGE_KEYS,
  AppEvents,
} from '@/types'

import { ALGORITHMS } from '@/data/algorithms'
import { dataLayer } from './DataLayer'
import { factorRegistry } from './FactorRegistry'
import { EventManager } from '@/utils/eventManager'
import { stockCache } from './LRUCache'
import { dragonBreathAnalyzer } from './DragonBreathAnalyzer'

// ========== 类型定义 ==========
interface AlgorithmManagerState {
  currentAlgorithm: string
  thresholds: Thresholds
  initialized: boolean
  performance: {
    history: PerformanceRecord[]
    stats: Map<string, PerformanceStat>
  }
  customWeights: Record<string, number> | null
  trainingData: any[]
  sectorAnalyzer?: any
  initPromise: Promise<boolean> | null
}

// ========== 工具函数 ==========
const getFactors = () => {
  if (typeof window !== 'undefined' && (window as any).FACTORS) {
    return (window as any).FACTORS
  }
  console.warn('[AlgorithmManager] ⚠️ FACTORS 未加载')
  return {}
}

// ========== 算法管理器类 ==========
export class AlgorithmManager {
  private static instance: AlgorithmManager
  private state: AlgorithmManagerState
  private initPromise: Promise<boolean> | null = null

  private constructor() {
    this.state = {
      currentAlgorithm: 'balanced',
      thresholds: { ...DEFAULT_THRESHOLDS },
      initialized: false,
      performance: {
        history: [],
        stats: new Map(),
      },
      customWeights: null,
      trainingData: [],
      sectorAnalyzer: null,
      initPromise: null,
    }
  }

  static getInstance(): AlgorithmManager {
    if (!AlgorithmManager.instance) {
      AlgorithmManager.instance = new AlgorithmManager()
    }
    return AlgorithmManager.instance
  }

  // ========== 初始化 ==========
  public init(): Promise<boolean> {
    if (this.initPromise) {
      return this.initPromise
    }

    this.initPromise = new Promise((resolve) => {
      if (this.state.initialized) {
        resolve(true)
        return
      }

      console.log('[AlgorithmManager] 🧠 算法管理器初始化中...')

      try {
        this.registerThemeFactors()
        this.loadFromConfigManager()
        this.loadFromLocalStorage()
        this.loadHistory()
        this.registerBreathFactors()
        this.registerContrarianFactor()
        this.tryGetBreathAnalyzer()
        this.tryGetSectorAnalyzer()
        this.setupEventListeners()

        this.state.initialized = true

        console.log('[AlgorithmManager] 🧠 算法管理器初始化完成')
        console.log(`   ├─ 算法数量: ${Object.keys(ALGORITHMS).length}`)
        console.log(`   ├─ 因子总数: ${Object.keys(this.getFactors()).length}`)
        console.log(`   ├─ 当前算法: ${ALGORITHMS[this.state.currentAlgorithm]?.name || 'unknown'}`)
        console.log(`   └─ 阈值: 总龙头≥${this.state.thresholds.totalLeader}`)

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

  // ========== 缓存优化方法 ==========

  /**
   * 计算股票得分（优化版）- 使用 stockCache 和分级TTL
   */
  calculateScore(stock: Stock): ScoreResult {
    const version = dataLayer.getVersion()

    // 使用分级TTL，类型为 'score'（5秒）
    return stockCache.getOrCompute(
      `score:${stock.code}:${version.stocks}:${version.themes}`,
      () => {
        const algo = ALGORITHMS[this.state.currentAlgorithm]
        if (!algo) {
          return {
            score: 50,
            details: {},
            timestamp: Date.now(),
            algorithm: this.state.currentAlgorithm,
            algorithmName: '未知',
          }
        }

        let totalScore = 0
        let totalWeight = 0
        const details: Record<string, FactorDetail> = {}

        // 获取题材因子
        const themeFactors = this.getStockThemeFactors(stock)

        Object.entries(algo.factors).forEach(([factorId, config]) => {
          if (!config.enabled) return

          try {
            const factor = this.getFactors()[factorId]
            if (!factor) return

            let rawScore: number

            if (factorId.startsWith('theme')) {
              rawScore = this.calculateThemeFactor(factorId, themeFactors, stock)
            } else if (factorId.startsWith('breath')) {
              rawScore = factor.calculate()
            } else {
              rawScore = factor.calculate(stock)
            }

            const normalizedScore = this.normalizeScore(rawScore, factorId)

            let weight = config.weight
            if (weight === 'dynamic') {
              weight = config.baseWeight || 0.1
            }

            details[factorId] = {
              name: factor.name,
              score: normalizedScore,
              weight: weight as number,
              contribution: normalizedScore * (weight as number),
              description: factor.description,
              example: factor.example,
            }

            totalScore += normalizedScore * (weight as number)
            totalWeight += weight as number
          } catch (error) {
            console.warn(`[AlgorithmManager] 计算因子 ${factorId} 失败:`, error)
          }
        })

        const finalScore = totalWeight > 0 ? totalScore / totalWeight : 50

        return {
          score: finalScore,
          details,
          timestamp: Date.now(),
          algorithm: this.state.currentAlgorithm,
          algorithmName: algo.name,
          themeInfo: themeFactors,
        }
      },
      'score',
      [`score:${stock.code}`],
    )
  }

  /**
   * 批量计算股票得分（新增）- 批量操作优化
   */
  calculateScoresBulk(stocks: Stock[]): Map<string, ScoreResult> {
    const version = dataLayer.getVersion()
    const results = new Map<string, ScoreResult>()

    // 生成所有缓存键
    const keys = stocks.map((stock) => `score:${stock.code}:${version.stocks}:${version.themes}`)

    // 批量获取或计算
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

    computed.forEach((value, key) => {
      const code = key.split(':')[1]
      results.set(code, value)
    })

    return results
  }

  /**
   * 获取股票题材因子（优化版）- 使用 stockCache
   */
  private getStockThemeFactors(stock: Stock): ThemeFactors {
    const defaultFactors: ThemeFactors = {
      themeHeat: 0,
      themeLeaderCount: 0,
      themeMomentum: 0,
      themePosition: 15,
    }

    if (!this.state.sectorAnalyzer || !stock.code) {
      return defaultFactors
    }

    try {
      const version = dataLayer.getVersion()

      return stockCache.getOrCompute(
        `themeFactors:${stock.code}:${version.themes}`,
        () => {
          const factors = this.state.sectorAnalyzer.getThemeFactors?.(stock.code)
          return factors || defaultFactors
        },
        'themeFactors',
        [`themeFactors:${stock.code}`],
      )
    } catch (error) {
      console.warn(`[AlgorithmManager] 获取题材因子失败: ${stock.code}`, error)
      return defaultFactors
    }
  }

  /**
   * 获取性能统计（优化版）- 使用 stockCache
   */
  getPerformanceStats(): any {
    const version = dataLayer.getVersion()

    return stockCache.getOrCompute(
      `algorithm:stats:${version.leaders}:${version.themes}`,
      () => {
        const stats: Record<string, any> = {}
        this.state.performance.stats.forEach((stat, id) => {
          stats[id] = {
            ...stat,
            version: version.leaders,
            timestamp: Date.now(),
          }
        })
        return stats
      },
      'algorithm:stats',
      ['algorithmStats'],
    )
  }

  /**
   * 获取因子分析（优化版）- 使用 stockCache
   */
  getFactorAnalysis(stock: Stock): Record<string, any> {
    const version = dataLayer.getVersion()

    return stockCache.getOrCompute(
      `factorAnalysis:${stock.code}:${version.stocks}:${version.themes}`,
      () => {
        const analysis: Record<string, any> = {}

        Object.entries(this.getFactors()).forEach(([factorId, factor]) => {
          try {
            let score: number

            if (factorId.startsWith('theme')) {
              const themeFactors = this.getStockThemeFactors(stock)
              switch (factorId) {
                case THEME_FACTOR_IDS.HEAT:
                  score = themeFactors.themeHeat
                  break
                case THEME_FACTOR_IDS.LEADER_COUNT:
                  score = themeFactors.themeLeaderCount
                  break
                case THEME_FACTOR_IDS.MOMENTUM:
                  score = themeFactors.themeMomentum
                  break
                case THEME_FACTOR_IDS.POSITION:
                  score = themeFactors.themePosition
                  break
                default:
                  score = factor.calculate(stock)
              }
            } else {
              score = factor.calculate(stock)
            }

            const percentile = Math.min(100, Math.max(0, score))

            let level = '低'
            if (percentile >= 80) level = '高'
            else if (percentile >= 60) level = '中高'
            else if (percentile >= 40) level = '中'
            else if (percentile >= 20) level = '中低'

            analysis[factorId] = {
              name: factor.name,
              score: percentile,
              level,
              category: factor.category,
              description: factor.description,
              example: factor.example,
            }
          } catch (e) {
            // 忽略计算失败的因子
          }
        })

        return analysis
      },
      'factor:analysis',
      [`factorAnalysis:${stock.code}`],
    )
  }

  /**
   * 清除算法相关缓存
   */
  clearCache() {
    stockCache.invalidateByTag('score')
    stockCache.invalidateByTag('themeFactors')
    stockCache.invalidateByTag('algorithmStats')
    stockCache.invalidateByTag('factor:analysis')

    console.log('[AlgorithmManager] 🧹 算法缓存已清除')

    EventManager.emit(AppEvents.UI.TOAST, {
      message: '🧹 算法缓存已清除',
      duration: 1500,
      type: 'success',
    })
  }

  // ========== 原有方法（保持不变）=========

  private registerThemeFactors() {
    Object.entries(THEME_FACTORS_META).forEach(([id, meta]) => {
      const factors = this.getFactors()
      if (!factors) return
      ;(factors as any)[id] = {
        ...meta,
        calculate: (stock: Stock) => {
          if (!stock.themes || stock.themes.length === 0) return 0
          const mainTheme = stock.themes[0]
          switch (id as ThemeFactorId) {
            case THEME_FACTOR_IDS.HEAT:
              return mainTheme.heatScore || 0
            case THEME_FACTOR_IDS.LEADER_COUNT:
              return mainTheme.leaderCount || 0
            case THEME_FACTOR_IDS.MOMENTUM:
              return mainTheme.momentum || 0
            case THEME_FACTOR_IDS.POSITION:
              return (mainTheme as any).rank || 15
            default:
              return 0
          }
        },
      }
    })
    console.log('[AlgorithmManager] 📊 题材因子注册完成')
  }

  private registerBreathFactors() {
    const breath = dragonBreathAnalyzer
    if (!breath) {
      setTimeout(() => this.registerBreathFactors(), 1000)
      return
    }

    console.log('[AlgorithmManager] 🌬️ 开始注册龙息因子...')

    // 安全获取市场数据
    const safeGetMarketData = () => {
      try {
        return breath.getMarketData() || {}
      } catch {
        return {}
      }
    }

    const safeGetSentiment = () => {
      try {
        return breath.getMarketSentiment() || { phase: '启动', overall: 50 }
      } catch {
        return { phase: '启动', overall: 50 }
      }
    }

    const phaseToScore = (phase: string): number => {
      const map: Record<string, number> = {
        冰点: 20,
        启动: 45,
        发酵: 66,
        高潮: 88,
        退潮: 35,
      }
      return map[phase] || map.启动
    }

    // 注册因子
    factorRegistry.registerBatch({
      [BREATH_FACTOR_IDS.PHASE]: {
        factor: {
          name: '龙息阶段',
          type: 'breath',
          category: 'market',
          description: '当前市场情绪阶段',
          example: '高潮期=80分，冰点期=20分',
          calculate: () => phaseToScore(safeGetSentiment().phase),
        },
        dependencies: ['service:dragonBreathAnalyzer'],
      },
      [BREATH_FACTOR_IDS.ZT_COUNT]: {
        factor: {
          name: '龙息涨停数',
          type: 'breath',
          category: 'market',
          description: '当日涨停股票数量',
          example: '>60为高潮，<30为冰点',
          calculate: () => safeGetMarketData().ztCount || 0,
        },
        dependencies: ['service:dragonBreathAnalyzer'],
      },
      [BREATH_FACTOR_IDS.DT_COUNT]: {
        factor: {
          name: '龙息跌停数',
          type: 'breath',
          category: 'market',
          description: '当日跌停股票数量',
          example: '>20为高风险',
          calculate: () => safeGetMarketData().dtCount || 0,
        },
        dependencies: ['service:dragonBreathAnalyzer'],
      },
      [BREATH_FACTOR_IDS.ZHABAN_RATE]: {
        factor: {
          name: '龙息炸板率',
          type: 'breath',
          category: 'market',
          description: '炸板率越低越好',
          example: '<30%为健康',
          calculate: () => 100 - (safeGetMarketData().zhaban?.rate || 0),
        },
        dependencies: ['service:dragonBreathAnalyzer'],
      },
      [BREATH_FACTOR_IDS.FENGBAN_RATE]: {
        factor: {
          name: '龙息封板率',
          type: 'breath',
          category: 'market',
          description: '封板率越高越强',
          example: '>70%为强势',
          calculate: () => safeGetMarketData().zhaban?.fengbanRate || 0,
        },
        dependencies: ['service:dragonBreathAnalyzer'],
      },
    })

    console.log('[AlgorithmManager] 🌬️ 龙息因子注册完成')
  }

  private registerContrarianFactor() {
    if (factorRegistry.has('contrarian')) {
      console.log('[AlgorithmManager] 逆势因子已存在，跳过注册')
      return
    }

    const breath = dragonBreathAnalyzer
    if (!breath) {
      setTimeout(() => this.registerContrarianFactor(), 1000)
      return
    }

    factorRegistry.register(
      'contrarian',
      {
        name: '逆势因子',
        type: 'sentiment',
        category: 'technical',
        description: '冰点期逆势上涨的股票，反映个股独立性',
        calculate: (stock: Stock) => {
          try {
            const sentiment = breath.getMarketSentiment()
            if (!sentiment) return 50

            if (sentiment.phase === '冰点' || sentiment.phaseName === '冰点') {
              if (stock.change > 0) {
                return Math.min(100, 50 + stock.change * 5)
              }
              if (stock.change > -3) {
                return Math.max(0, 30 + stock.change * 5)
              }
              return 20
            }

            if ((sentiment.phase === '退潮' || sentiment.phaseName === '退潮') && stock.change > 0) {
              return 40
            }

            return 30
          } catch (e) {
            return 50
          }
        },
      },
      ['service:dragonBreathAnalyzer'],
    )

    console.log('[AlgorithmManager] 📈 逆势因子已注册')
  }

  private loadFromConfigManager() {
    if (typeof window === 'undefined' || !(window as any).ConfigManager) return

    try {
      const configManager = (window as any).ConfigManager
      const savedAlgorithm = configManager.get('algorithm.current', 'balanced')
      this.state.currentAlgorithm = ALGORITHMS[savedAlgorithm] ? savedAlgorithm : 'balanced'

      const savedThresholds = configManager.get('algorithm.thresholds')
      if (savedThresholds) {
        this.state.thresholds = { ...DEFAULT_THRESHOLDS, ...savedThresholds }
      }

      const savedWeights = configManager.get('algorithm.weights')
      if (savedWeights) {
        this.state.customWeights = savedWeights
      }

      console.log('[AlgorithmManager] 📊 从ConfigManager加载配置')
    } catch (e) {
      console.warn('[AlgorithmManager] 从ConfigManager加载失败:', e)
    }
  }

  private loadFromLocalStorage() {
    if (typeof window === 'undefined') return

    try {
      const savedAlgorithm = localStorage.getItem(STORAGE_KEYS.ALGORITHM)
      if (savedAlgorithm && ALGORITHMS[savedAlgorithm]) {
        this.state.currentAlgorithm = savedAlgorithm
      }

      const savedThresholds = localStorage.getItem(STORAGE_KEYS.THRESHOLDS)
      if (savedThresholds) {
        try {
          const thresholds = JSON.parse(savedThresholds)
          this.state.thresholds = { ...DEFAULT_THRESHOLDS, ...thresholds }
        } catch (e) {}
      }

      const savedWeights = localStorage.getItem(STORAGE_KEYS.WEIGHTS)
      if (savedWeights) {
        try {
          this.state.customWeights = JSON.parse(savedWeights)
        } catch (e) {}
      }
    } catch (e) {
      console.warn('[AlgorithmManager] 从localStorage加载失败:', e)
    }
  }

  private loadHistory() {
    if (typeof window === 'undefined') return

    try {
      const savedHistory = localStorage.getItem(STORAGE_KEYS.HISTORY)
      if (savedHistory) {
        const history = JSON.parse(savedHistory)
        this.state.performance.history = history.slice(-200)
        this.rebuildStats()
      }
    } catch (e) {
      console.warn('[AlgorithmManager] 加载历史数据失败:', e)
    }
  }

  private rebuildStats() {
    this.state.performance.stats.clear()
    this.state.performance.history.forEach((record) => {
      let stat = this.state.performance.stats.get(record.algorithm)
      if (!stat) {
        stat = { count: 0, successCount: 0, totalScore: 0, avgScore: 0, successRate: '0%' }
        this.state.performance.stats.set(record.algorithm, stat)
      }
      stat.count++
      stat.totalScore += record.score
      if (record.success) stat.successCount++
      stat.avgScore = stat.totalScore / stat.count
      stat.successRate = ((stat.successCount / stat.count) * 100).toFixed(1) + '%'
    })
  }

  private tryGetBreathAnalyzer() {
    if (typeof window === 'undefined') return
    if (dragonBreathAnalyzer) {
      console.log('[AlgorithmManager] 🌬️ 已连接到龙息分析器')
    }
    EventManager.on('breath:ready', () => {
      if (dragonBreathAnalyzer) {
        console.log('[AlgorithmManager] 🌬️ 龙息分析器已就绪')
        this.registerBreathFactors()
      }
    })
  }

  private tryGetSectorAnalyzer() {
    if (typeof window === 'undefined') return
    if ((window as any).sectorAnalyzer) {
      this.state.sectorAnalyzer = (window as any).sectorAnalyzer
      console.log('[AlgorithmManager] 📊 已连接到题材分析器')
    }
    EventManager.on('sector:ready', () => {
      if ((window as any).sectorAnalyzer) {
        this.state.sectorAnalyzer = (window as any).sectorAnalyzer
        console.log('[AlgorithmManager] 📊 题材分析器已就绪')
      }
    })
  }

  private setupEventListeners() {
    if (typeof window === 'undefined') return
    EventManager.on('breath:updated', () => {
      this.adjustWeightsByBreathPhase()
    })
  }

  private getFactors() {
    return getFactors()
  }

  private normalizeScore(score: number, factorId: string): number {
    const factor = this.getFactors()[factorId]
    if (factor?.range) {
      const [min, max] = factor.range
      return ((score - min) / (max - min)) * 100
    }
    return Math.min(100, Math.max(0, score))
  }

  private calculateThemeFactor(factorId: string, themeFactors: ThemeFactors, stock: Stock): number {
    switch (factorId) {
      case THEME_FACTOR_IDS.HEAT:
        return Math.min(100, themeFactors.themeHeat / 100)
      case THEME_FACTOR_IDS.LEADER_COUNT:
        return Math.min(100, themeFactors.themeLeaderCount * 20)
      case THEME_FACTOR_IDS.MOMENTUM:
        return 50 + Math.min(50, Math.max(-50, themeFactors.themeMomentum))
      case THEME_FACTOR_IDS.POSITION:
        return Math.max(0, 100 - themeFactors.themePosition * 6)
      default:
        const factor = this.getFactors()[factorId]
        return factor?.calculate?.(stock) || 0
    }
  }

  private adjustWeightsByBreathPhase() {
    const phase = dragonBreathAnalyzer?.getMarketSentiment().phase
    if (!phase) return

    const algo = ALGORITHMS[this.state.currentAlgorithm]
    if (!algo) return

    console.log(`[AlgorithmManager] 🌬️ 根据龙息阶段调整权重: ${phase}`)

    const phaseMultipliers: Record<string, Record<string, number>> = {
      冰点: { contrarian: 2.5, breathZtCount: 2.0, breathDtCount: 2.0 },
      启动: { themeHeat: 1.8, themeMomentum: 1.3, breathPassRate: 1.8 },
      发酵: { themeMomentum: 1.8, zlje: 1.5, breathMaxDays: 1.5 },
      高潮: { continuousDays: 1.8, zlje: 1.6, breathMaxDays: 1.6 },
      退潮: { continuousDays: 0.4, zlje: 0.3, themeHeat: 0.4 },
    }

    const multipliers = phaseMultipliers[phase] || {}

    Object.entries(algo.factors).forEach(([factorId, config]) => {
      const multiplier = multipliers[factorId]
      if (!multiplier) return

      let currentWeight: number
      if (config.weight === 'dynamic') {
        currentWeight = config.baseWeight || 0.1
      } else {
        currentWeight = config.weight as number
      }

      const newWeight = currentWeight * multiplier
      const minWeight = config.min || 0.03
      const maxWeight = config.max || 0.3
      const clampedWeight = Math.min(maxWeight, Math.max(minWeight, newWeight))

      if (config.weight === 'dynamic') {
        config.baseWeight = clampedWeight
      } else {
        config.weight = clampedWeight
      }
    })

    console.log(`[AlgorithmManager] ✅ 权重调整完成`)
  }

  getCurrentAlgorithm(): Algorithm & { id: string } {
    const algo = ALGORITHMS[this.state.currentAlgorithm]
    if (!algo) {
      this.state.currentAlgorithm = 'balanced'
      return this.getCurrentAlgorithm()
    }
    return { id: this.state.currentAlgorithm, ...algo }
  }

  getThresholds(): Thresholds {
    return { ...this.state.thresholds }
  }

  getLeaderThresholds(level: string, algorithmId?: string): Record<string, any> {
    const algoId = algorithmId || this.state.currentAlgorithm
    const algo = ALGORITHMS[algoId]
    const customThresholds = algo?.leaderThresholds?.[level as keyof LeaderThresholds]
    if (customThresholds) {
      return customThresholds
    }
    return this.getDefaultLeaderThresholds(level)
  }

  private getDefaultLeaderThresholds(level: string): Record<string, any> {
    const defaults: Record<string, Record<string, any>> = {
      continuous: { minChange: 9.5, minDays: 2, maxRank: 30, minScore: 70 },
      middle: { minMV: 20e8, maxChange: 8, minTurnoverRate: 0.5, maxTurnoverRate: 15 },
      sector: { maxRank: 50, minChange: 3, minScore: 70, minThemeHeat: 75 },
      total: { maxRank: 15, minDays: 3, eliteRank: 5, minScore: 95 },
      emotion: { minTurnoverRate: 8, minAbsChange: 2, minScore: 60 },
    }
    return defaults[level] || {}
  }

  getThresholdRanges(): ThresholdRanges {
    return { ...THRESHOLD_RANGES }
  }

  setThresholds(newThresholds: Partial<Thresholds>): boolean {
    const oldThresholds = { ...this.state.thresholds }
    let changed = false

    Object.entries(newThresholds).forEach(([key, value]) => {
      const k = key as keyof Thresholds
      if (k in THRESHOLD_RANGES) {
        const range = THRESHOLD_RANGES[k]
        const validValue = Math.min(range.max, Math.max(range.min, Number(value)))
        if (this.state.thresholds[k] !== validValue) {
          this.state.thresholds[k] = validValue
          changed = true
        }
      }
    })

    if (changed) {
      this.saveThresholds()
      console.log('[AlgorithmManager] 📊 阈值已更新:', this.state.thresholds)
      EventManager.emit('thresholds-changed', { old: oldThresholds, new: this.state.thresholds })
      return true
    }
    return false
  }

  updateThreshold(key: keyof Thresholds, value: number): boolean {
    if (!(key in THRESHOLD_RANGES)) return false
    const range = THRESHOLD_RANGES[key]
    const validValue = Math.min(range.max, Math.max(range.min, Number(value)))
    if (this.state.thresholds[key] === validValue) return true

    const oldValue = this.state.thresholds[key]
    this.state.thresholds[key] = validValue
    this.saveThresholds()
    console.log(`[AlgorithmManager] 📊 阈值 ${key} 已更新: ${oldValue} → ${validValue}`)
    EventManager.emit('thresholds-changed', { key, old: oldValue, new: validValue })
    return true
  }

  resetThresholds(): boolean {
    const oldThresholds = { ...this.state.thresholds }
    this.state.thresholds = { ...DEFAULT_THRESHOLDS }
    if (typeof window !== 'undefined') {
      localStorage.removeItem(STORAGE_KEYS.THRESHOLDS)
    }
    this.saveThresholds()
    console.log('[AlgorithmManager] 🔄 阈值已重置')
    EventManager.emit('thresholds-changed', { old: oldThresholds, new: this.state.thresholds })
    return true
  }

  private saveThresholds(): void {
    if (typeof window === 'undefined') return
    if ((window as any).ConfigManager) {
      ;(window as any).ConfigManager.set('algorithm.thresholds', this.state.thresholds)
    }
    localStorage.setItem(STORAGE_KEYS.THRESHOLDS, JSON.stringify(this.state.thresholds))
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
      isActive: id === this.state.currentAlgorithm,
    }))
  }

  setAlgorithm(algorithmId: string): boolean {
    if (!ALGORITHMS[algorithmId]) return false

    const oldAlgorithm = this.state.currentAlgorithm
    this.state.currentAlgorithm = algorithmId

    if (typeof window !== 'undefined') {
      if ((window as any).ConfigManager) {
        ;(window as any).ConfigManager.set('algorithm.current', algorithmId)
      }
      localStorage.setItem(STORAGE_KEYS.ALGORITHM, algorithmId)
    }

    console.log(`[AlgorithmManager] 🔄 切换算法: ${ALGORITHMS[algorithmId].name}`)
    EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())
    return true
  }

  getAlgorithmFactors(algorithmId: string | null = null) {
    const algoId = algorithmId || this.state.currentAlgorithm
    const algo = ALGORITHMS[algoId]
    if (!algo) return []

    return Object.entries(algo.factors).map(([factorId, config]) => {
      const factor = this.getFactors()[factorId]
      return {
        id: factorId,
        name: factor?.name || factorId,
        type: factor?.type || 'unknown',
        category: factor?.category || 'other',
        description: factor?.description || '',
        example: factor?.example,
        weight: config.weight,
        enabled: config.enabled,
        min: config.min,
        max: config.max,
        baseWeight: config.baseWeight,
      }
    })
  }

  updateFactorWeight(algorithmId: string, factorId: string, weight: number): boolean {
    const algo = ALGORITHMS[algorithmId]
    if (!algo || !algo.factors[factorId]) return false
    if (weight < 0 || weight > 1) return false

    const factor = algo.factors[factorId]
    if (factor.min !== undefined && weight < factor.min) return false
    if (factor.max !== undefined && weight > factor.max) return false

    algo.factors[factorId].weight = weight

    if (algorithmId === this.state.currentAlgorithm) {
      if (!this.state.customWeights) this.state.customWeights = {}
      this.state.customWeights[factorId] = weight

      if (typeof window !== 'undefined') {
        if ((window as any).ConfigManager) {
          ;(window as any).ConfigManager.set('algorithm.weights', this.state.customWeights)
        }
        localStorage.setItem(STORAGE_KEYS.WEIGHTS, JSON.stringify(this.state.customWeights))
      }
    }

    console.log(`[AlgorithmManager] 📊 更新权重: ${algo.name} - ${factorId} = ${weight}`)
    EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())
    return true
  }

  resetWeights(algorithmId: string | null = null): boolean {
    const algoId = algorithmId || this.state.currentAlgorithm
    const algo = ALGORITHMS[algoId]
    if (!algo) return false

    const defaultAlgo = ALGORITHMS[algoId]
    algo.factors = JSON.parse(JSON.stringify(defaultAlgo.factors))

    if (algoId === this.state.currentAlgorithm) {
      this.state.customWeights = null
      if (typeof window !== 'undefined') {
        localStorage.removeItem(STORAGE_KEYS.WEIGHTS)
      }
    }

    console.log(`[AlgorithmManager] 🔄 重置权重: ${algo.name}`)
    EventManager.emit('algorithm-changed', this.getCurrentAlgorithm())
    return true
  }

  recordPerformance(algorithmId: string, score: number, success: boolean = true): void {
    const record: PerformanceRecord = {
      algorithm: algorithmId,
      score,
      success,
      timestamp: Date.now(),
    }

    this.state.performance.history.push(record)
    if (this.state.performance.history.length > 200) {
      this.state.performance.history = this.state.performance.history.slice(-200)
    }

    let stat = this.state.performance.stats.get(algorithmId)
    if (!stat) {
      stat = { count: 0, successCount: 0, totalScore: 0, avgScore: 0, successRate: '0%' }
      this.state.performance.stats.set(algorithmId, stat)
    }

    stat.count++
    stat.totalScore += score
    if (success) stat.successCount++
    stat.avgScore = stat.totalScore / stat.count
    stat.successRate = ((stat.successCount / stat.count) * 100).toFixed(1) + '%'

    if (typeof window !== 'undefined') {
      localStorage.setItem(STORAGE_KEYS.HISTORY, JSON.stringify(this.state.performance.history))
    }
  }
}

// 导出单例
export const algorithmManager = AlgorithmManager.getInstance()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).algorithmManager = algorithmManager
}
