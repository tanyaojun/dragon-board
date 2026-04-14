// src/services/DragonLifecycle.ts
// 龙头生命周期追踪服务 - 专业版 v2.1 (集成刷新管理器)

import type { LeaderInfo, LeaderLifecycle, LifecycleStage, LeaderLineage } from '@/types'
import { dragonAnalyzer } from './DragonAnalyzer'
import { dataLayer } from './DataLayer'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { incrementalUpdater } from './IncrementalUpdater'
import { RefreshManager } from './RefreshManager'
import { isTradingTime } from '@/utils/time'

// ========== 专业版生命周期阶段定义 ==========
export const LIFECYCLE_STAGES = {
  // 萌芽期 - 刚露头
  SPROUT: {
    id: 'sprout',
    name: '萌芽期',
    icon: '🌱',
    color: '#86efac',
    description: '首次异动，资金试盘',
    nextStage: 'seedling',
    duration: { min: 0.5, max: 2 },
    signals: ['首次涨停', '放量突破', '板块联动初现'],
    requirements: {
      minScore: 65,
      minRank: 50,
      confirmationCount: 1,
    },
  },

  // 幼苗期 - 确认强度
  SEEDLING: {
    id: 'seedling',
    name: '幼苗期',
    icon: '🌿',
    color: '#4ade80',
    description: '确认强度，开始走独立',
    nextStage: 'growth',
    duration: { min: 1, max: 3 },
    signals: ['二连板', '缩量加速', '带动跟风'],
    requirements: {
      minScore: 70,
      minRank: 30,
      confirmationCount: 2,
    },
  },

  // 成长期 - 确立地位
  GROWTH: {
    id: 'growth',
    name: '成长期',
    icon: '📈',
    color: '#fbbf24',
    description: '确立板块龙头地位',
    nextStage: 'maturity',
    duration: { min: 2, max: 5 },
    signals: ['三连板以上', '成为板块风向标', '带动板块梯队'],
    requirements: {
      minScore: 75,
      minRank: 20,
      confirmationCount: 3,
    },
  },

  // 成熟期 - 市场总龙头
  MATURITY: {
    id: 'maturity',
    name: '成熟期',
    icon: '👑',
    color: '#f97316',
    description: '成为市场总龙头',
    nextStage: 'aging',
    duration: { min: 3, max: 7 },
    signals: ['五连板以上', '带动多个板块', '成为情绪指标'],
    requirements: {
      minScore: 85,
      minRank: 10,
      confirmationCount: 5,
    },
  },

  // 衰老期 - 开始掉队
  AGING: {
    id: 'aging',
    name: '衰老期',
    icon: '🍂',
    color: '#f87171',
    description: '高位分歧，跟风掉队',
    nextStage: 'decline',
    duration: { min: 1, max: 3 },
    signals: ['高位放量', '烂板回封', '板块内部分化'],
    requirements: {
      minScore: 70,
      minRank: 30,
      confirmationCount: 2,
    },
  },

  // 衰退期 - 正式退潮
  DECLINE: {
    id: 'decline',
    name: '衰退期',
    icon: '📉',
    color: '#ef4444',
    description: '正式退潮，A杀风险',
    nextStage: 'death',
    duration: { min: 0.5, max: 2 },
    signals: ['断板大跌', '板块集体调整', '亏钱效应扩散'],
    requirements: {
      minScore: 55,
      minRank: 80,
      confirmationCount: 1,
    },
  },

  // 死亡期 - 退出榜单
  DEATH: {
    id: 'death',
    name: '死亡期',
    icon: '💀',
    color: '#6b7280',
    description: '退出龙头榜单',
    nextStage: null,
    duration: { min: 0, max: 0 },
    signals: ['退出龙头列表', '可能反抽但无持续性', '等待下一个周期'],
    requirements: {
      minScore: 0,
      minRank: 999,
      confirmationCount: 0,
    },
  },
}

// ========== 配置化规则系统 ==========
const CONFIRM_RULES = {
  FAST_TRACK: [
    { type: '连续涨停', value: 3, desc: '3连板' },
    { type: '评分', value: 92, desc: '92分以上' },
    { type: '评级', value: 'SSS', desc: 'SSS级' },
    { type: '2连板+评级', value: 'SS', desc: '2连板+SS级' },
  ],

  SCORE_REQUIREMENTS: {
    SSS: { min: 85, time: 10, count: 2 },
    SS: { min: 80, time: 15, count: 2 },
    S: { min: 75, time: 20, count: 2 },
    A: { min: 70, time: 25, count: 2 },
    B: { min: 65, time: 30, count: 2 },
    C: { min: 999, time: 999, count: 999 },
  },

  OBSERVATION_HOURS: {
    primary: { SSS: 48, SS: 36, S: 24, A: 18, B: 12, C: 1 },
    secondary: { SSS: 36, SS: 24, S: 18, A: 12, B: 8, C: 0.5 },
    cold: { SSS: 24, SS: 18, S: 12, A: 8, B: 4, C: 0.25 },
  },

  MARKET_FACTORS: {
    高潮期: 0.8,
    活跃期: 0.9,
    震荡期: 1.0,
    退潮期: 1.2,
    冰点期: 1.5,
  },

  TREND_THRESHOLD: {
    DECLINE: -15,
    AGING: -5,
  },
}

// ========== 龙头基因评分系统 ==========
interface LeaderGenetics {
  genes: {
    money: {
      score: number
      zlje: number
      zljzb: number
      continuity: number
    }
    technical: {
      score: number
      continuousDays: number
      change: number
      turnoverRate: number
    }
    theme: {
      score: number
      heatScore: number
      leadership: number
      synergy: number
    }
    sentiment: {
      score: number
      phase: string
      crowd: number
      resistance: number
    }
  }
  totalScore: number
  rating: 'SSS' | 'SS' | 'S' | 'A' | 'B' | 'C'
  potential: {
    maxDays: number
    targetPrice: number
    confidence: number
  }
}

// ========== 生命周期配置 ==========
const LIFECYCLE_CONFIG = {
  TIME: {
    MIN_SURVIVAL: 30 * 60 * 1000,
    OBSERVATION: 60 * 60 * 1000,
    GRACE_PERIOD: 15 * 60 * 1000,
    STABLE_THRESHOLD: 2 * 60 * 60 * 1000,
  },
  SCORE: {
    MIN_QUALIFIED: 65,
    GOOD: 75,
    EXCELLENT: 85,
    ELITE: 92,
  },
  CONFIRMATION: {
    SPROUT: 1,
    SEEDLING: 2,
    GROWTH: 3,
    MATURITY: 5,
    AGING: 2,
    DECLINE: 1,
  },
  SURVIVAL_DAYS: {
    SPROUT: 0.5,
    SEEDLING: 1,
    GROWTH: 2,
    MATURITY: 3,
    AGING: 5,
    DECLINE: 7,
  },
}

const STORAGE_KEYS = {
  LIFECYCLES: 'dragon_lifecycles',
  OBSERVATION: 'dragon_observation',
  TRANSITIONS: 'dragon_transitions',
  LAST_UPDATE: 'dragon_last_update',
}

// ========== 龙头基因分析器 ==========
class LeaderGeneticAnalyzer {
  analyzeGenetics(leader: LeaderInfo): LeaderGenetics {
    const stockData = dataLayer.getStock(leader.code)
    const themes = dataLayer.getStockThemes(leader.code)
    const quote = dataLayer.getQuote(leader.code)

    // 合并数据
    const enhancedLeader = {
      ...leader,
      ...stockData,
      ...quote,
      themes: themes || leader.themes,
      // 确保关键字段有值
      zlje: quote.zlje || stockData?.zlje || leader.zlje || 0,
      zljzb: quote.zljzb || stockData?.zljzb || leader.zljzb || 0,
      price: quote.price || stockData?.price || leader.price || 0,
      change: quote.change || stockData?.change || leader.change || 0,
      turnover: quote.turnover || stockData?.turnover || leader.turnover || 0,
      turnoverRate: quote.turnoverRate || stockData?.turnoverRate || leader.turnoverRate || 0,
    }

    const moneyGenes = this.analyzeMoneyGenes(enhancedLeader)
    const technicalGenes = this.analyzeTechnicalGenes(enhancedLeader)
    const themeGenes = this.analyzeThemeGenes(enhancedLeader)
    const sentimentGenes = this.analyzeSentimentGenes(enhancedLeader)

    const totalScore =
      moneyGenes.score * 0.35 +
      technicalGenes.score * 0.25 +
      themeGenes.score * 0.25 +
      sentimentGenes.score * 0.15

    const rating = this.determineRating(totalScore)

    const potential = this.predictPotential(enhancedLeader, totalScore, {
      money: moneyGenes,
      technical: technicalGenes,
      theme: themeGenes,
      sentiment: sentimentGenes,
    })

    return {
      genes: {
        money: moneyGenes,
        technical: technicalGenes,
        theme: themeGenes,
        sentiment: sentimentGenes,
      },
      totalScore,
      rating,
      potential,
    }
  }

  private analyzeMoneyGenes(leader: any) {
    // 优先使用 dataLayer 的数据
    const zlje = leader.zlje || 0
    const zljzb = leader.zljzb || 0

    let moneyScore = 0
    if (zlje > 1e8) moneyScore = 100
    else if (zlje > 5e7) moneyScore = 85
    else if (zlje > 2e7) moneyScore = 70
    else if (zlje > 1e7) moneyScore = 50
    else moneyScore = 30

    let ratioScore = 0
    if (zljzb > 30) ratioScore = 100
    else if (zljzb > 20) ratioScore = 80
    else if (zljzb > 10) ratioScore = 60
    else ratioScore = 40

    const continuity = Math.min(100, moneyScore * 0.7 + ratioScore * 0.3)

    return {
      score: Math.round(moneyScore * 0.5 + ratioScore * 0.3 + continuity * 0.2),
      zlje,
      zljzb,
      continuity,
    }
  }

  private analyzeTechnicalGenes(leader: LeaderInfo) {
    const days = leader.continuousDays || 1
    const change = Math.abs(leader.change || 0)
    const turnoverRate = leader.turnoverRate || 0

    let daysScore = 0
    if (days >= 7) daysScore = 100
    else if (days >= 5) daysScore = 90
    else if (days >= 4) daysScore = 80
    else if (days >= 3) daysScore = 70
    else if (days >= 2) daysScore = 50
    else daysScore = 30

    let changeScore = 0
    if (change > 9) changeScore = 100
    else if (change > 7) changeScore = 80
    else if (change > 5) changeScore = 60
    else changeScore = 40

    let turnoverHealth = 0
    if (turnoverRate > 30) turnoverHealth = 60
    else if (turnoverRate > 20) turnoverHealth = 80
    else if (turnoverRate > 10) turnoverHealth = 90
    else if (turnoverRate > 5) turnoverHealth = 70
    else turnoverHealth = 50

    return {
      score: Math.round(daysScore * 0.5 + changeScore * 0.3 + turnoverHealth * 0.2),
      continuousDays: days,
      change,
      turnoverRate,
    }
  }

  private analyzeThemeGenes(leader: LeaderInfo) {
    const themeHeat = leader.themeHeat || 0

    let heatScore = 0
    if (themeHeat > 4000) heatScore = 100
    else if (themeHeat > 3000) heatScore = 85
    else if (themeHeat > 2000) heatScore = 70
    else if (themeHeat > 1000) heatScore = 50
    else heatScore = 30

    let leadership = 50
    if (leader.level === 'TOTAL') leadership = 100
    else if (leader.level === 'SECTOR') leadership = 85
    else if (leader.level === 'CONTINUOUS') leadership = 70
    else if (leader.level === 'MIDDLE') leadership = 60

    const synergy = this.calculateThemeSynergy(leader)

    return {
      score: Math.round(heatScore * 0.4 + leadership * 0.4 + synergy * 0.2),
      heatScore,
      leadership,
      synergy,
    }
  }

  private analyzeSentimentGenes(leader: LeaderInfo) {
    const sentiment = leader.sentimentInfo || { phase: '震荡期', overall: 50 }

    let phaseBonus = 1.0
    if (sentiment.phase === '高潮期') phaseBonus = 1.3
    else if (sentiment.phase === '活跃期') phaseBonus = 1.2
    else if (sentiment.phase === '发酵期') phaseBonus = 1.1
    else if (sentiment.phase === '退潮期') phaseBonus = 0.7
    else if (sentiment.phase === '冰点期') phaseBonus = 0.5

    const marketData = dataLayer.getStocks() || []
    const upCount = marketData.filter((s) => (s.change || 0) > 0).length
    const total = marketData.length
    const crowd = total > 0 ? (upCount / total) * 100 : 50

    const resistance = this.calculateResistance(leader)

    const baseScore = sentiment.overall * phaseBonus
    return {
      score: Math.min(100, Math.round(baseScore * 0.5 + crowd * 0.3 + resistance * 0.2)),
      phase: sentiment.phase,
      crowd,
      resistance,
    }
  }

  private calculateThemeSynergy(leader: LeaderInfo): number {
    if (!leader.themes?.length) return 50

    const themeName = leader.mainTheme?.name
    if (!themeName) return 50

    const stocks = dataLayer.getStocks()
    const sameThemeStocks = stocks.filter(
      (s) => s.themes?.some((t) => t.name === themeName) && s.code !== leader.code,
    )

    if (sameThemeStocks.length === 0) return 50

    const followChanges = sameThemeStocks.map((s) => s.change || 0)
    const avgFollowChange = followChanges.reduce((a, b) => a + b, 0) / followChanges.length

    const leaderChange = leader.change || 0
    if (leaderChange <= 0) return 50

    const synergy = Math.min(100, (avgFollowChange / leaderChange) * 100)
    return Math.round(synergy)
  }

  private calculateResistance(leader: LeaderInfo): number {
    const turnover = leader.turnover || 0
    if (turnover === 0) return 50

    const idealRatio = 2
    const actualRatio = 1.5

    return Math.min(100, Math.round((actualRatio / idealRatio) * 100))
  }

  private determineRating(score: number): 'SSS' | 'SS' | 'S' | 'A' | 'B' | 'C' {
    if (score >= 95) return 'SSS'
    if (score >= 90) return 'SS'
    if (score >= 85) return 'S'
    if (score >= 75) return 'A'
    if (score >= 65) return 'B'
    return 'C'
  }

  private predictPotential(
    leader: LeaderInfo,
    totalScore: number,
    genes: any,
  ): { maxDays: number; targetPrice: number; confidence: number } {
    const currentDays = leader.continuousDays || 1

    let maxDays = currentDays
    if (totalScore >= 90) maxDays = currentDays + 3
    else if (totalScore >= 80) maxDays = currentDays + 2
    else if (totalScore >= 70) maxDays = currentDays + 1
    else maxDays = currentDays

    const currentPrice = leader.price || 0
    const moneyStrength = genes.money.score / 100
    const targetPrice = currentPrice * (1 + moneyStrength * 0.3)

    const confidence = Math.min(
      95,
      Math.round(
        genes.money.continuity * 0.4 +
          genes.technical.score * 0.3 +
          genes.theme.score * 0.2 +
          genes.sentiment.score * 0.1,
      ),
    )

    return { maxDays, targetPrice, confidence }
  }
}

// ========== 龙头生命周期追踪器（专业版 - 集成刷新管理器） ==========
export class DragonLifecycleTracker {
  private static instance: DragonLifecycleTracker
  private geneticAnalyzer: LeaderGeneticAnalyzer

  private lifecycles = new Map<string, LeaderLifecycle>()
  private transitions: LeaderTransition[] = []
  private families = new Map<string, LeaderFamily>()
  private pendingUpdates = new Set<string>() // ✅ 待处理的龙头更新

  private observationQueue = {
    primary: new Map<string, ObservationData>(),
    secondary: new Map<string, ObservationData>(),
    cold: new Map<string, ObservationData>(),
  }

  private history: Array<{
    timestamp: number
    lifecycles: Map<string, LeaderLifecycle>
    stats: any
  }> = []

  private stats = {
    totalTracked: 0,
    confirmedCount: 0,
    averageLifespan: 0,
    stageDistribution: {} as Record<string, number>,
    ratingDistribution: {} as Record<string, number>,
    survivalRate: {} as Record<string, number>,
    averageGenesScore: 0,
  }

  private unsubscribeFns: (() => void)[] = []
  private destroyed = false
  private paused = true // ✅ 初始暂停状态

  private constructor() {
    this.geneticAnalyzer = new LeaderGeneticAnalyzer()
    this.loadFromStorage()
    this.setupListeners()
  }

  static getInstance(): DragonLifecycleTracker {
    if (!DragonLifecycleTracker.instance) {
      DragonLifecycleTracker.instance = new DragonLifecycleTracker()
    }
    return DragonLifecycleTracker.instance
  }

  // ========== 集成刷新管理器 ==========

  /**
   * ✅ 检查是否可以处理更新
   */
  private canProcess(): boolean {
    if (this.destroyed) return false
    if (this.paused) return false

    const status = RefreshManager.getStatus()
    if (!status.enabled) return false
    if (!status.isRunning) return false
    if (status.tradingTimeOnly && !isTradingTime()) return false

    return true
  }

  /**
   * ✅ 设置监听器 - 集成刷新管理器
   */
  private setupListeners() {
    // 监听龙头更新
    const unsub = EventManager.on(AppEvents.DRAGON.UPDATED, (data: any) => {
      this.onLeadersUpdated(data)
    })
    this.unsubscribeFns.push(unsub)

    // 监听全量刷新
    const unsubFull = EventManager.on(AppEvents.REFRESH.FULL_REQUESTED, () => {
      this.fullRefresh()
    })
    this.unsubscribeFns.push(unsubFull)

    // ✅ 监听刷新管理器状态
    const unsubRefreshStarted = EventManager.on('refresh:started', () => {
      this.paused = false
      console.log('[DragonLifecycle] ▶️ 恢复处理')
    })
    this.unsubscribeFns.push(unsubRefreshStarted)

    const unsubRefreshStopped = EventManager.on('refresh:stopped', () => {
      this.paused = true
      console.log('[DragonLifecycle] ⏸️ 暂停处理')
    })
    this.unsubscribeFns.push(unsubRefreshStopped)

    const unsubConfigChanged = EventManager.on('refresh:config-changed', (data: any) => {
      const config = data?.config
      if (config) {
        this.paused = !config.enabled || !config.isRunning
      }
    })
    this.unsubscribeFns.push(unsubConfigChanged)

    // ✅ 监听增量更新完成，处理待更新
    const unsubIncrementalComplete = EventManager.on('incremental:queue-processed', (data: any) => {
      if (this.destroyed) return

      // 每次增量更新完成后，检查观察队列老化
      if (this.canProcess()) {
        this.checkObservationAging(Date.now())
      }

      // 如果有待更新，处理
      if (this.pendingUpdates.size > 0) {
        this.processPendingUpdates()
      }
    })
    this.unsubscribeFns.push(unsubIncrementalComplete)

    // ✅ 监听维护请求，执行保存
    const unsubMaintenance = EventManager.on(AppEvents.REFRESH.MAINTENANCE_REQUESTED, () => {
      if (this.destroyed) return

      // 执行后台维护任务
      this.saveToStorage() // 保存数据
      this.cleanupExpiredObservations() // 清理过期观察数据
    })
    this.unsubscribeFns.push(unsubMaintenance)

    // ✅ 监听手动刷新
    const unsubManual = EventManager.on(AppEvents.REFRESH.MANUAL_REQUESTED, () => {
      if (this.paused) {
        console.log('[DragonLifecycle] 手动刷新时强制检查')
        this.checkObservationAging(Date.now())
      }
    })
    this.unsubscribeFns.push(unsubManual)
  }

  /**
   * 清理过期观察数据
   */
  private cleanupExpiredObservations(): void {
    const now = Date.now()
    const queues = ['primary', 'secondary', 'cold'] as const

    queues.forEach((queueName) => {
      const queue = this.observationQueue[queueName]
      const entries = Array.from(queue.entries())

      entries.forEach(([code, data]) => {
        // 如果超过24小时没出现，从观察队列移除
        if (now - data.lastSeen > 24 * 60 * 60 * 1000) {
          queue.delete(code)
        }
      })
    })
  }

  /**
   * ✅ 处理待更新
   */
  private processPendingUpdates() {
    if (!this.canProcess() || this.pendingUpdates.size === 0) return

    console.log(`[DragonLifecycle] 处理 ${this.pendingUpdates.size} 个待更新龙头`)

    // 添加到增量更新队列
    this.pendingUpdates.forEach((code) => {
      incrementalUpdater.addToQueue?.(
        code,
        {
          type: 'dragon_lifecycle',
          data: { code, action: 'check' },
        },
        80, // 优先级介于龙头变化和HTTP校准之间
      )
    })

    this.pendingUpdates.clear()
  }

  /**
   * 保存到 localStorage
   */
  private saveToStorage() {
    if (typeof window === 'undefined') return

    try {
      const lifecyclesData: any[] = []
      this.lifecycles.forEach((data, code) => {
        lifecyclesData.push({
          code,
          name: data.name,
          currentStage: data.currentStage,
          birthTime: data.birthTime,
          deathTime: data.deathTime,
          peakScore: data.peakScore,
          peakTime: data.peakTime,
          totalDuration: data.totalDuration,
          stages: data.stages.map((s) => ({
            stage: s.stage,
            startTime: s.startTime,
            endTime: s.endTime,
            level: s.level,
            score: s.score,
            continuousDays: s.continuousDays,
            theme: s.theme,
          })),
          transitions: data.transitions,
          genetics: data.genetics
            ? {
                rating: data.genetics.rating,
                totalScore: data.genetics.totalScore,
                genes: data.genetics.genes,
              }
            : undefined,
          confirmationData: data.confirmationData,
        })
      })
      localStorage.setItem(STORAGE_KEYS.LIFECYCLES, JSON.stringify(lifecyclesData))

      const observationData = {
        primary: Array.from(this.observationQueue.primary.entries()).map(([code, data]) => [
          code,
          {
            ...data,
            leader: {
              code: data.leader.code,
              name: data.leader.name,
              score: data.leader.score,
              level: data.leader.level,
              continuousDays: data.leader.continuousDays,
              change: data.leader.change,
              mainTheme: data.leader.mainTheme,
            },
          },
        ]),
        secondary: Array.from(this.observationQueue.secondary.entries()).map(([code, data]) => [
          code,
          {
            ...data,
            leader: {
              code: data.leader.code,
              name: data.leader.name,
              score: data.leader.score,
              level: data.leader.level,
              continuousDays: data.leader.continuousDays,
              change: data.leader.change,
              mainTheme: data.leader.mainTheme,
            },
          },
        ]),
        cold: Array.from(this.observationQueue.cold.entries()).map(([code, data]) => [
          code,
          {
            ...data,
            leader: {
              code: data.leader.code,
              name: data.leader.name,
              score: data.leader.score,
              level: data.leader.level,
              continuousDays: data.leader.continuousDays,
              change: data.leader.change,
              mainTheme: data.leader.mainTheme,
            },
          },
        ]),
      }
      localStorage.setItem(STORAGE_KEYS.OBSERVATION, JSON.stringify(observationData))

      localStorage.setItem(STORAGE_KEYS.TRANSITIONS, JSON.stringify(this.transitions.slice(0, 100)))
      localStorage.setItem(STORAGE_KEYS.LAST_UPDATE, Date.now().toString())
    } catch (e) {
      console.warn('[DragonLifecycle] 保存失败', e)
    }
  }

  /**
   * 从 localStorage 加载
   */
  private loadFromStorage() {
    if (typeof window === 'undefined') return

    try {
      const savedLifecycles = localStorage.getItem(STORAGE_KEYS.LIFECYCLES)
      if (savedLifecycles) {
        const lifecycles = JSON.parse(savedLifecycles)
        lifecycles.forEach((item: any) => {
          const stages = item.stages.map((s: any) => ({
            ...s,
            startTime: s.startTime,
            endTime: s.endTime,
          }))

          this.lifecycles.set(item.code, {
            ...item,
            stages,
            birthTime: item.birthTime,
            deathTime: item.deathTime,
          })
        })
      }

      const savedObservation = localStorage.getItem(STORAGE_KEYS.OBSERVATION)
      if (savedObservation) {
        const obs = JSON.parse(savedObservation)

        obs.primary?.forEach(([code, data]: [string, any]) => {
          this.observationQueue.primary.set(code, data)
        })
        obs.secondary?.forEach(([code, data]: [string, any]) => {
          this.observationQueue.secondary.set(code, data)
        })
        obs.cold?.forEach(([code, data]: [string, any]) => {
          this.observationQueue.cold.set(code, data)
        })
      }

      const savedTransitions = localStorage.getItem(STORAGE_KEYS.TRANSITIONS)
      if (savedTransitions) {
        this.transitions = JSON.parse(savedTransitions)
      }

      this.buildFamilies()
      this.updateStats()

      // 从刷新管理器获取初始暂停状态
      const status = RefreshManager.getStatus()
      this.paused = !status.enabled || !status.isRunning

      console.log('[DragonLifecycle] ✅ 数据恢复完成，暂停状态:', this.paused)
    } catch (e) {
      console.warn('[DragonLifecycle] 加载失败', e)
    }
  }

  /**
   * 手动清除保存的数据
   */
  clearStorage() {
    if (typeof window === 'undefined') return

    localStorage.removeItem(STORAGE_KEYS.LIFECYCLES)
    localStorage.removeItem(STORAGE_KEYS.OBSERVATION)
    localStorage.removeItem(STORAGE_KEYS.TRANSITIONS)
    localStorage.removeItem(STORAGE_KEYS.LAST_UPDATE)

    console.log('[DragonLifecycle] 🧹 已清除本地存储')
  }

  private safelyExecute<T>(fn: () => T, fallback: T, context: string): T {
    try {
      return fn()
    } catch (error) {
      console.error(`[${context}] 执行失败:`, error)
      return fallback
    }
  }

  // ========== 核心追踪逻辑 ==========
  private onLeadersUpdated(data: any) {
    this.safelyExecute(
      () => {
        if (this.destroyed) return

        const now = Date.now()
        const currentLeaders = dragonAnalyzer.getAllLeaders({ useCache: false })
        const currentCodes = new Set(currentLeaders.map((l) => l.code))

        // 1. 先处理观察队列（老化检查）- 只有可处理时才执行
        if (this.canProcess()) {
          this.checkObservationAging(now)
        }

        // 2. 处理新增和更新
        currentLeaders.forEach((leader) => {
          if (!this.lifecycles.has(leader.code)) {
            this.processNewLeader(leader, now)
          } else {
            this.updateExistingLeader(leader, now)
          }
        })

        // 3. 检查消失的龙头
        this.lifecycles.forEach((lifecycle, code) => {
          if (!currentCodes.has(code) && lifecycle.currentStage !== 'death') {
            this.processLeaderDisappearance(code, now)
          }
        })

        // 4. 更新家族关系
        if (this.lifecycles.size % 10 === 0) {
          this.buildFamilies()
        }

        this.updateStats()
        this.emitLifecycleUpdate()

        // 自动保存（但不频繁）
        if (Math.random() < 0.1) {
          this.saveToStorage()
        }
      },
      undefined,
      'onLeadersUpdated',
    )
  }

  /**
   * 处理新龙头
   */
  private processNewLeader(leader: LeaderInfo, timestamp: number) {
    const genetics = this.geneticAnalyzer.analyzeGenetics(leader)

    if (genetics.rating === 'SSS' || genetics.rating === 'SS') {
      this.addToObservation(leader, genetics, 'primary', timestamp)
    } else if (genetics.rating === 'S' || genetics.rating === 'A') {
      this.addToObservation(leader, genetics, 'secondary', timestamp)
    } else if (genetics.rating === 'B') {
      this.addToObservation(leader, genetics, 'cold', timestamp)
    } else {
      return
    }

    // 标记待更新
    this.pendingUpdates.add(leader.code)

    // 如果可以处理，立即检查确认条件
    if (this.canProcess()) {
      const observed = this.observationQueue[
        genetics.rating === 'SSS' || genetics.rating === 'SS'
          ? 'primary'
          : genetics.rating === 'S' || genetics.rating === 'A'
            ? 'secondary'
            : 'cold'
      ].get(leader.code)

      if (observed && this.shouldConfirmLeader(observed)) {
        this.confirmLeader(observed, timestamp)
        this.observationQueue[observed.queue].delete(leader.code)
      }
    }
  }

  /**
   * 添加到观察队列
   */
  private addToObservation(
    leader: LeaderInfo,
    genetics: LeaderGenetics,
    queue: 'primary' | 'secondary' | 'cold',
    timestamp: number,
  ) {
    const observationData: ObservationData = {
      leader,
      genetics,
      firstSeen: timestamp,
      lastSeen: timestamp,
      appearances: [timestamp],
      scores: [leader.score],
      geneticsHistory: [genetics],
      queue,
      peakScore: leader.score,
      peakTime: timestamp,
    }

    this.observationQueue[queue].set(leader.code, observationData)

    console.log(
      `[DragonLifecycle] 🔍 龙头 ${leader.name} 进入${this.getQueueName(queue)} ` +
        `(评级: ${genetics.rating}, 得分: ${genetics.totalScore.toFixed(1)})`,
    )
  }

  /**
   * 确认龙头
   */
  private confirmLeader(observed: ObservationData, timestamp: number) {
    const leader = observed.leader
    const genetics = observed.genetics || {
      rating: 'C',
      totalScore: 60,
      genes: {
        money: { score: 50, zlje: 0, zljzb: 0, continuity: 50 },
        technical: { score: 50, continuousDays: 1, change: 0, turnoverRate: 0 },
        theme: { score: 50, heatScore: 0, leadership: 50, synergy: 50 },
        sentiment: { score: 50, phase: '震荡期', crowd: 50, resistance: 50 },
      },
    }

    let initialStage = 'sprout'
    if (genetics.rating === 'SSS' || genetics.rating === 'SS') {
      initialStage = 'seedling'
    }

    const lifecycle: LeaderLifecycle = {
      code: leader.code,
      name: leader.name,
      stages: [
        {
          stage: initialStage,
          startTime: observed.firstSeen,
          endTime: null,
          level: leader.level,
          score: leader.score,
          continuousDays: leader.continuousDays,
          theme: leader.mainTheme?.name,
        },
      ],
      currentStage: initialStage,
      birthTime: observed.firstSeen,
      deathTime: null,
      peakScore: observed.peakScore,
      peakTime: observed.peakTime,
      totalDuration: 0,
      transitions: [],
      genetics,
      confirmationData: {
        observationStart: observed.firstSeen,
        confirmationTime: timestamp,
        queue: observed.queue,
        appearances: observed.appearances.length,
        avgScore: observed.scores.reduce((a, b) => a + b, 0) / observed.scores.length,
        rating: genetics.rating,
      },
    }

    this.lifecycles.set(leader.code, lifecycle)

    const queueName = this.getQueueName(observed.queue)
    console.log(
      `[DragonLifecycle] ✅ 龙头 ${leader.name} 确认诞生 ` +
        `(评级: ${genetics.rating}, 观察: ${queueName})`,
    )

    // ✅ 触发龙头确认事件
    EventManager.emit('dragon:confirmed', {
      code: leader.code,
      name: leader.name,
      rating: genetics.rating,
      stage: initialStage,
      timestamp,
    })
  }

  private confirmCache = new Map<string, { result: boolean; timestamp: number }>()

  /**
   * 是否应该确认为龙头
   */
  private shouldConfirmLeader(observed: ObservationData): boolean {
    const now = Date.now()
    const rating = observed.genetics?.rating || 'C'
    const days = observed.leader.continuousDays || 1
    const score = observed.leader.score || 0
    const marketPhase =
      (observed.leader.sentimentInfo?.phase as keyof typeof CONFIRM_RULES.MARKET_FACTORS) ||
      '震荡期'

    // 快速通道
    if (days >= 3) {
      return true
    }
    if (score >= 92) {
      return true
    }
    if (rating === 'SSS') {
      return true
    }
    if (days >= 2 && rating === 'SS') {
      return true
    }

    const requirement = CONFIRM_RULES.SCORE_REQUIREMENTS[rating]
    if (!requirement) return false

    const factor = CONFIRM_RULES.MARKET_FACTORS[marketPhase] || 1.0
    const requiredScore = requirement.min * factor
    const requiredTime = requirement.time * 60 * 1000
    const requiredCount = requirement.count

    const timeOk = now - observed.firstSeen >= requiredTime
    const scoreOk = observed.peakScore >= requiredScore
    const countOk = observed.appearances.length >= requiredCount

    return timeOk && scoreOk && countOk
  }

  /**
   * 检查观察队列老化
   */
  private checkObservationAging(now: number) {
    const queues = ['primary', 'secondary', 'cold'] as const

    queues.forEach((queueName) => {
      const queue = this.observationQueue[queueName]
      const entries = Array.from(queue.entries())

      entries.forEach(([code, data]) => {
        const rating = data.genetics?.rating || 'C'
        const hoursInQueue = (now - data.firstSeen) / (60 * 60 * 1000)

        const maxHours = CONFIRM_RULES.OBSERVATION_HOURS[queueName]?.[rating] || 4

        if (this.shouldConfirmLeader(data)) {
          this.confirmLeader(data, now)
          queue.delete(code)
          return
        }

        if (hoursInQueue > maxHours) {
          if (queueName === 'primary' && (rating === 'SSS' || rating === 'SS' || rating === 'S')) {
            this.moveToQueue(data, 'secondary')
          } else if (
            queueName === 'secondary' &&
            (rating === 'SSS' || rating === 'SS' || rating === 'S' || rating === 'A')
          ) {
            this.moveToQueue(data, 'cold')
          } else {
            queue.delete(code)
          }
        }
      })
    })
  }

  /**
   * 移动到指定队列
   */
  private moveToQueue(data: ObservationData, targetQueue: 'primary' | 'secondary' | 'cold') {
    this.observationQueue[data.queue].delete(data.leader.code)
    data.queue = targetQueue
    data.firstSeen = Date.now()
    this.observationQueue[targetQueue].set(data.leader.code, data)
  }

  /**
   * 获取队列名称
   */
  private getQueueName(queue: 'primary' | 'secondary' | 'cold'): string {
    const names = {
      primary: '主队列',
      secondary: '次队列',
      cold: '冷备',
    }
    return names[queue]
  }

  /**
   * 更新现有龙头
   */
  private updateExistingLeader(leader: LeaderInfo, timestamp: number) {
    // 先检查是否在观察队列中
    for (const queue of ['primary', 'secondary', 'cold'] as const) {
      const observed = this.observationQueue[queue].get(leader.code)
      if (observed) {
        observed.appearances.push(timestamp)
        observed.scores.push(leader.score)
        observed.lastSeen = timestamp

        if (leader.score > observed.peakScore) {
          observed.peakScore = leader.score
          observed.peakTime = timestamp
        }

        // 标记待更新
        this.pendingUpdates.add(leader.code)

        if (this.canProcess() && this.shouldConfirmLeader(observed)) {
          this.confirmLeader(observed, timestamp)
          this.observationQueue[queue].delete(leader.code)
        }
        return
      }
    }

    const lifecycle = this.lifecycles.get(leader.code)
    if (!lifecycle) return

    const lastStage = lifecycle.stages[lifecycle.stages.length - 1]
    if (!lastStage) return

    const newStage = this.determineStageAdvanced(leader, lifecycle, timestamp)

    if (leader.score > lifecycle.peakScore) {
      lifecycle.peakScore = leader.score
      lifecycle.peakTime = timestamp
    }

    if (lastStage.stage !== newStage) {
      this.recordHistorySnapshot(lifecycle, lastStage, newStage, timestamp)

      lastStage.endTime = timestamp

      lifecycle.stages.push({
        stage: newStage,
        startTime: timestamp,
        endTime: null,
        level: leader.level,
        score: leader.score,
        continuousDays: leader.continuousDays,
        theme: leader.mainTheme?.name,
      })

      lifecycle.currentStage = newStage
      lifecycle.transitions.push({
        from: lastStage.stage,
        to: newStage,
        time: timestamp,
        reason: this.getTransitionReasonAdvanced(leader, lastStage.stage, newStage),
      })

      this.recordTransition({
        code: leader.code,
        name: leader.name,
        fromStage: lastStage.stage,
        toStage: newStage,
        timestamp,
        reason: this.getTransitionReasonAdvanced(leader, lastStage.stage, newStage),
      })

      // ✅ 标记待更新
      this.pendingUpdates.add(leader.code)
    }

    const currentStage = lifecycle.stages[lifecycle.stages.length - 1]
    currentStage.score = leader.score
    currentStage.continuousDays = leader.continuousDays
    currentStage.level = leader.level
  }

  /**
   * 记录历史快照
   */
  private recordHistorySnapshot(
    lifecycle: LeaderLifecycle,
    oldStage: any,
    newStage: string,
    timestamp: number,
  ) {
    const snapshot = {
      timestamp,
      code: lifecycle.code,
      name: lifecycle.name,
      fromStage: oldStage.stage,
      toStage: newStage,
      fromScore: oldStage.score,
      toScore: lifecycle.peakScore,
      duration: timestamp - (oldStage.startTime || lifecycle.birthTime),
      theme: lifecycle.genetics?.genes?.theme?.name,
    }

    this.history.push({
      timestamp,
      lifecycles: new Map([[lifecycle.code, lifecycle]]),
      stats: { ...this.stats },
    })

    if (this.history.length > 100) {
      this.history = this.history.slice(-100)
    }

    try {
      const historyKey = 'dragon_history_snapshots'
      const saved = localStorage.getItem(historyKey)
      let history = saved ? JSON.parse(saved) : []
      history.push(snapshot)
      if (history.length > 50) history = history.slice(-50)
      localStorage.setItem(historyKey, JSON.stringify(history))
    } catch (e) {
      // 忽略错误
    }
  }

  /**
   * 获取历史快照
   */
  getHistorySnapshots(limit: number = 20): any[] {
    if (this.history.length > 0) {
      return this.history.slice(-limit).map((h) => ({
        timestamp: h.timestamp,
        ...h.stats,
        leaders: Array.from(h.lifecycles.values()).map((l) => ({
          code: l.code,
          name: l.name,
          stage: l.currentStage,
          score: l.peakScore,
        })),
      }))
    }

    try {
      const historyKey = 'dragon_history_snapshots'
      const saved = localStorage.getItem(historyKey)
      return saved ? JSON.parse(saved).slice(-limit) : []
    } catch (e) {
      return []
    }
  }

  /**
   * 高级阶段判断
   */
  private determineStageAdvanced(
    leader: LeaderInfo,
    lifecycle: LeaderLifecycle,
    now: number,
  ): string {
    const days = leader.continuousDays || 1
    const age = (now - lifecycle.birthTime) / (24 * 60 * 60 * 1000)
    const score = leader.score || 0

    if (lifecycle.currentStage === 'death') return 'death'

    if (days >= 7) return 'maturity'
    if (days >= 5) return 'growth'
    if (days >= 3) return 'seedling'
    if (days === 2) return 'sprout'

    if (age < 0.5) return 'sprout'
    if (age < 1) return 'seedling'
    if (age < 2) return 'growth'
    if (age < 5) return 'maturity'
    if (age < 7) return 'aging'

    const scoreTrend = this.calculateScoreTrend(leader.code)

    if (scoreTrend < CONFIRM_RULES.TREND_THRESHOLD.DECLINE) return 'decline'
    if (scoreTrend < CONFIRM_RULES.TREND_THRESHOLD.AGING) return 'aging'

    return lifecycle.currentStage || 'sprout'
  }

  /**
   * 更新确认规则
   */
  updateConfirmRules(newRules: Partial<typeof CONFIRM_RULES>) {
    Object.assign(CONFIRM_RULES, newRules)
    console.log('[⚙️配置更新] 确认规则已更新', newRules)

    if (this.canProcess()) {
      this.checkObservationAging(Date.now())
    }
  }

  /**
   * 获取当前规则配置
   */
  getConfirmRules() {
    return { ...CONFIRM_RULES }
  }

  /**
   * 高级阶段变化原因
   */
  private getTransitionReasonAdvanced(leader: LeaderInfo, from: string, to: string): string {
    const reasons: Record<string, Record<string, string>> = {
      sprout: {
        seedling: `二连板确认，进入幼苗期`,
        death: `首板后无溢价，夭折`,
      },
      seedling: {
        growth: `三连板确立地位，进入成长期`,
        decline: `断板掉队，进入衰退`,
      },
      growth: {
        maturity: `五连板成为总龙头，进入成熟期`,
        aging: `高位分歧，进入衰老期`,
      },
      maturity: {
        aging: `高位放量，开始衰老`,
        decline: `见顶回落，进入衰退`,
      },
      aging: {
        decline: `跟风股大面积回调，正式衰退`,
        death: `退出龙头榜单`,
      },
      decline: {
        death: `亏钱效应扩散，退出榜单`,
      },
    }

    let reason = reasons[from]?.[to] || '阶段自然过渡'
    if (to === 'growth' || to === 'maturity') {
      reason += ` (连板${leader.continuousDays})`
    }
    return reason
  }

  /**
   * 处理龙头消失
   */
  private processLeaderDisappearance(code: string, timestamp: number) {
    for (const [queueName, queue] of Object.entries(this.observationQueue)) {
      if (queue.has(code)) {
        const data = queue.get(code)!
        const timeInQueue = timestamp - data.firstSeen

        if (timeInQueue < LIFECYCLE_CONFIG.TIME.OBSERVATION / 2) {
          queue.delete(code)
        } else {
          data.lastSeen = timestamp
        }
        return
      }
    }

    const lifecycle = this.lifecycles.get(code)
    if (!lifecycle) return

    const lastSeen = lifecycle.stages[lifecycle.stages.length - 1].startTime
    const timeSinceLastSeen = timestamp - lastSeen

    if (timeSinceLastSeen < LIFECYCLE_CONFIG.TIME.GRACE_PERIOD) {
      return
    }

    this.markLeaderDeath(code, timestamp)
  }

  /**
   * 标记龙头死亡
   */
  private markLeaderDeath(code: string, timestamp: number) {
    const lifecycle = this.lifecycles.get(code)
    if (!lifecycle) return

    const lastStage = lifecycle.stages[lifecycle.stages.length - 1]
    const totalLife = timestamp - lifecycle.birthTime

    let lifeRating = ''
    if (totalLife > 7 * 24 * 60 * 60 * 1000) lifeRating = '长命'
    else if (totalLife > 3 * 24 * 60 * 60 * 1000) lifeRating = '中寿'
    else lifeRating = '短命'

    lastStage.endTime = timestamp
    lifecycle.deathTime = timestamp
    lifecycle.currentStage = 'death'
    lifecycle.totalDuration = totalLife

    lifecycle.stages.push({
      stage: 'death',
      startTime: timestamp,
      endTime: null,
      level: 'DEATH',
      score: 0,
      continuousDays: 0,
    })

    lifecycle.transitions.push({
      from: lastStage.stage,
      to: 'death',
      time: timestamp,
      reason: '退出龙头榜单',
    })

    this.recordTransition({
      code,
      name: lifecycle.name,
      fromStage: lastStage.stage,
      toStage: 'death',
      timestamp,
      reason: `龙头陨落 (${lifeRating})`,
    })

    // ✅ 标记待更新
    this.pendingUpdates.add(code)

    console.log(
      `[DragonLifecycle] 💀 龙头陨落: ${lifecycle.name} ` +
        `(寿命: ${Math.round(totalLife / (1000 * 60 * 60))}小时)`,
    )
  }

  // ========== 家族关系构建 ==========
  private buildFamilies() {
    const leaders = Array.from(this.lifecycles.values()).filter((l) => l.currentStage !== 'death')
    const sorted = leaders.sort((a, b) => a.birthTime - b.birthTime)

    for (let i = 0; i < sorted.length; i++) {
      const current = sorted[i]
      const family: LeaderFamily = {
        code: current.code,
        name: current.name,
        parents: [],
        children: [],
        siblings: [],
        rivals: [],
        genetics: current.genetics?.rating,
      }

      const predecessors = sorted
        .slice(0, i)
        .filter((p) => current.birthTime - p.birthTime < 5 * 24 * 60 * 60 * 1000)
      family.parents = predecessors.map((p) => p.code)

      const successors = sorted
        .slice(i + 1)
        .filter((s) => s.birthTime - current.birthTime < 5 * 24 * 60 * 60 * 1000)
      family.children = successors.map((s) => s.code)

      const currentTheme = this.getLeaderTheme(current.code)
      if (currentTheme) {
        const sameTheme = sorted.filter((l) => {
          const lTheme = this.getLeaderTheme(l.code)
          return lTheme === currentTheme && l.code !== current.code
        })
        family.siblings = sameTheme.map((s) => s.code)
      }

      const rivals = sorted.filter((l) => {
        const timeDiff = Math.abs(l.birthTime - current.birthTime)
        return (
          timeDiff < 2 * 24 * 60 * 60 * 1000 &&
          l.code !== current.code &&
          !family.siblings.includes(l.code)
        )
      })
      family.rivals = rivals.map((r) => r.code).slice(0, 5)

      this.families.set(current.code, family)
    }
  }

  // ========== 公共API ==========

  /**
   * ✅ 暂停处理
   */
  pause(): void {
    this.paused = true
    console.log('[DragonLifecycle] ⏸️ 手动暂停')
  }

  /**
   * ✅ 恢复处理
   */
  resume(): void {
    this.paused = false
    console.log('[DragonLifecycle] ▶️ 手动恢复')

    // 恢复时立即检查
    if (this.canProcess()) {
      this.checkObservationAging(Date.now())
      this.processPendingUpdates()
    }
  }

  /**
   * 获取生命周期
   */
  getLifecycle(code: string): LeaderLifecycle | null {
    return this.lifecycles.get(code) || null
  }

  /**
   * 获取所有生命周期
   */
  getAllLifecycles(): LeaderLifecycle[] {
    return Array.from(this.lifecycles.values())
  }

  /**
   * 获取当前活跃龙头
   */
  getActiveLeaders(): LeaderLifecycle[] {
    return Array.from(this.lifecycles.values()).filter((l) => l.currentStage !== 'death')
  }

  /**
   * 获取特定阶段的龙头
   */
  getLeadersByStage(stage: string): LeaderLifecycle[] {
    return Array.from(this.lifecycles.values()).filter((l) => l.currentStage === stage)
  }

  /**
   * 获取已确认的龙头列表
   */
  getConfirmedLeaders(): LeaderLifecycle[] {
    return Array.from(this.lifecycles.values())
      .filter((l) => l.confirmationData !== undefined)
      .sort((a, b) => b.peakScore - a.peakScore)
  }

  /**
   * 获取某个时间段内确认的龙头
   */
  getConfirmedLeadersInTimeRange(startTime: number, endTime: number): LeaderLifecycle[] {
    return Array.from(this.lifecycles.values())
      .filter(
        (l) =>
          l.confirmationData &&
          l.confirmationData.confirmationTime >= startTime &&
          l.confirmationData.confirmationTime <= endTime,
      )
      .sort((a, b) => b.peakScore - a.peakScore)
  }

  /**
   * 获取龙头确认统计
   */
  getConfirmationStats() {
    const confirmed = this.getConfirmedLeaders()

    return {
      total: confirmed.length,
      byRating: {
        SSS: confirmed.filter((l) => l.genetics?.rating === 'SSS').length,
        SS: confirmed.filter((l) => l.genetics?.rating === 'SS').length,
        S: confirmed.filter((l) => l.genetics?.rating === 'S').length,
        A: confirmed.filter((l) => l.genetics?.rating === 'A').length,
        B: confirmed.filter((l) => l.genetics?.rating === 'B').length,
        C: confirmed.filter((l) => l.genetics?.rating === 'C').length,
      },
      byStage: confirmed.reduce(
        (acc, l) => {
          const stage = l.currentStage
          acc[stage] = (acc[stage] || 0) + 1
          return acc
        },
        {} as Record<string, number>,
      ),
      averageConfirmTime:
        confirmed.length > 0
          ? confirmed.reduce(
              (sum, l) => sum + (l.confirmationData!.confirmationTime - l.birthTime),
              0,
            ) / confirmed.length
          : 0,
    }
  }

  /**
   * 获取各阶段龙头统计
   */
  getStageDistribution(): Record<string, number> {
    const dist: Record<string, number> = {}
    this.lifecycles.forEach((l) => {
      if (l.currentStage !== 'death') {
        dist[l.currentStage] = (dist[l.currentStage] || 0) + 1
      }
    })
    return dist
  }

  /**
   * 获取评级分布
   */
  getRatingDistribution(): Record<string, number> {
    const dist: Record<string, number> = {}
    this.lifecycles.forEach((l) => {
      if (l.genetics?.rating) {
        dist[l.genetics.rating] = (dist[l.genetics.rating] || 0) + 1
      }
    })
    return dist
  }

  /**
   * 获取平均基因得分
   */
  getAverageGenesScore(): number {
    const scores = Array.from(this.lifecycles.values())
      .map((l) => l.genetics?.totalScore || 0)
      .filter((s) => s > 0)

    if (scores.length === 0) return 0
    return scores.reduce((a, b) => a + b, 0) / scores.length
  }

  /**
   * 获取龙头家族关系
   */
  getFamily(code: string): LeaderFamily | null {
    return this.families.get(code) || null
  }

  /**
   * 获取龙头族谱
   */
  getLineage(code: string): LeaderLineage {
    const family = this.families.get(code)
    if (!family) {
      return { ancestors: [], descendants: [], siblings: [], rivals: [] }
    }

    return {
      ancestors: family.parents.map((p) => this.lifecycles.get(p)).filter(Boolean),
      descendants: family.children.map((c) => this.lifecycles.get(c)).filter(Boolean),
      siblings: family.siblings.map((s) => this.lifecycles.get(s)).filter(Boolean),
      rivals: family.rivals.map((r) => this.lifecycles.get(r)).filter(Boolean),
    }
  }

  /**
   * 获取传承链
   */
  getSuccessionChain(theme?: string): Array<{
    predecessor: LeaderLifecycle
    successor: LeaderLifecycle
    gap: number
    smooth: boolean
    quality: string
  }> {
    const chains: any[] = []

    this.families.forEach((family, code) => {
      family.children.forEach((childCode) => {
        const predecessor = this.lifecycles.get(code)
        const successor = this.lifecycles.get(childCode)

        if (predecessor && successor) {
          if (theme) {
            const predTheme = this.getLeaderTheme(predecessor.code)
            const succTheme = this.getLeaderTheme(successor.code)
            if (predTheme !== theme || succTheme !== theme) return
          }

          const gap = successor.birthTime - (predecessor.deathTime || successor.birthTime)
          const smooth = Math.abs(gap) < 24 * 60 * 60 * 1000

          let quality = '普通'
          if (predecessor.genetics?.rating === 'SSS' && successor.genetics?.rating === 'SSS') {
            quality = '王者传承'
          } else if (predecessor.genetics?.rating === 'SS' && successor.genetics?.rating === 'SS') {
            quality = '优质传承'
          }

          chains.push({ predecessor, successor, gap, smooth, quality })
        }
      })
    })

    return chains.sort((a, b) => Math.abs(a.gap) - Math.abs(b.gap))
  }

  /**
   * 获取统计信息
   */
  getStats() {
    return {
      ...this.stats,
      activeCount: this.getActiveLeaders().length,
      confirmedCount: this.getConfirmedLeaders().length,
      deadCount: this.lifecycles.size - this.getActiveLeaders().length,
      transitions: this.transitions.length,
      families: this.families.size,
      averageGenesScore: this.getAverageGenesScore(),
      stageDistribution: this.getStageDistribution(),
      ratingDistribution: this.getRatingDistribution(),
    }
  }

  /**
   * 获取存活率曲线
   */
  getSurvivalCurve(): Array<{ day: number; rate: number }> {
    const curve = []
    const now = Date.now()

    for (let day = 1; day <= 10; day++) {
      const survived = Array.from(this.lifecycles.values()).filter((l) => {
        const age = (now - l.birthTime) / (1000 * 60 * 60 * 24)
        return age >= day
      }).length

      const rate = this.lifecycles.size > 0 ? (survived / this.lifecycles.size) * 100 : 0
      curve.push({ day, rate: Math.round(rate * 10) / 10 })
    }

    return curve
  }

  /**
   * 获取平均寿命（小时）
   */
  getAverageLifespan(): number {
    const deadLeaders = Array.from(this.lifecycles.values()).filter((l) => l.deathTime)

    if (deadLeaders.length === 0) return 0

    const total = deadLeaders.reduce((sum, l) => {
      return sum + (l.deathTime! - l.birthTime)
    }, 0)

    return Math.round((total / deadLeaders.length / (1000 * 60 * 60)) * 10) / 10
  }

  /**
   * 获取观察队列统计
   */
  getObservationStats() {
    return {
      primary: this.observationQueue.primary.size,
      secondary: this.observationQueue.secondary.size,
      cold: this.observationQueue.cold.size,
      total:
        this.observationQueue.primary.size +
        this.observationQueue.secondary.size +
        this.observationQueue.cold.size,
    }
  }

  /**
   * 获取观察队列详情（用于显示）
   */
  getObservationQueues() {
    const primary = Array.from(this.observationQueue.primary.entries()).map(([code, data]) => ({
      code,
      name: data.leader.name,
      rating: data.genetics?.rating || 'C',
      genes: {
        total: data.genetics?.totalScore || 0,
        money: data.genetics?.genes.money.score || 0,
        technical: data.genetics?.genes.technical.score || 0,
        theme: data.genetics?.genes.theme.score || 0,
        sentiment: data.genetics?.genes.sentiment.score || 0,
      },
      firstSeen: data.firstSeen,
      appearances: data.appearances.length,
      score: data.genetics?.totalScore || 0,
    }))

    const secondary = Array.from(this.observationQueue.secondary.entries()).map(([code, data]) => ({
      code,
      name: data.leader.name,
      rating: data.genetics?.rating || 'C',
      genes: {
        total: data.genetics?.totalScore || 0,
        money: data.genetics?.genes.money.score || 0,
        technical: data.genetics?.genes.technical.score || 0,
        theme: data.genetics?.genes.theme.score || 0,
        sentiment: data.genetics?.genes.sentiment.score || 0,
      },
      firstSeen: data.firstSeen,
      appearances: data.appearances.length,
      score: data.genetics?.totalScore || 0,
    }))

    const cold = Array.from(this.observationQueue.cold.entries()).map(([code, data]) => ({
      code,
      name: data.leader.name,
      rating: data.genetics?.rating || 'C',
      genes: {
        total: data.genetics?.totalScore || 0,
        money: data.genetics?.genes.money.score || 0,
        technical: data.genetics?.genes.technical.score || 0,
        theme: data.genetics?.genes.theme.score || 0,
        sentiment: data.genetics?.genes.sentiment.score || 0,
      },
      firstSeen: data.firstSeen,
      appearances: data.appearances.length,
      score: data.genetics?.totalScore || 0,
    }))

    return { primary, secondary, cold }
  }

  /**
   * 记录阶段变化
   */
  private recordTransition(transition: LeaderTransition) {
    this.transitions.unshift(transition)
    if (this.transitions.length > 200) {
      this.transitions.pop()
    }
  }

  /**
   * 获取最近变化
   */
  getRecentTransitions(limit: number = 20): LeaderTransition[] {
    return this.transitions.slice(0, limit)
  }

  /**
   * 获取题材
   */
  private getLeaderTheme(code: string): string | null {
    const leader = dragonAnalyzer.getLeaderByCode(code)
    return leader?.mainTheme?.name || null
  }

  /**
   * 计算分数趋势
   */
  private calculateScoreTrend(code: string): number {
    const lifecycle = this.lifecycles.get(code)
    if (!lifecycle || lifecycle.stages.length < 2) return 0

    const recent = lifecycle.stages.slice(-3)
    if (recent.length < 2) return 0

    const firstScore = recent[0].score
    const lastScore = recent[recent.length - 1].score

    return ((lastScore - firstScore) / (firstScore || 1)) * 100
  }

  /**
   * 触发更新事件
   */
  private emitLifecycleUpdate() {
    EventManager.emit('dragon:lifecycle-updated', {
      timestamp: Date.now(),
      stats: this.getStats(),
      observationStats: this.getObservationStats(),
      transitions: this.transitions.slice(0, 5),
      pendingCount: this.pendingUpdates.size,
    })
  }

  /**
   * 全量刷新
   */
  fullRefresh() {
    this.lifecycles.clear()
    this.transitions = []
    this.families.clear()
    this.observationQueue.primary.clear()
    this.observationQueue.secondary.clear()
    this.observationQueue.cold.clear()
    this.pendingUpdates.clear()

    const leaders = dragonAnalyzer.getAllLeaders({ useCache: false })
    const now = Date.now()

    leaders.forEach((leader) => {
      this.processNewLeader(leader, now)
    })

    this.buildFamilies()
    this.updateStats()

    console.log('[DragonLifecycle] 🔄 全量刷新完成')
  }

  /**
   * 清理缓存
   */
  clearCache() {
    this.lifecycles.clear()
    this.transitions = []
    this.families.clear()
    this.observationQueue.primary.clear()
    this.observationQueue.secondary.clear()
    this.observationQueue.cold.clear()
    this.pendingUpdates.clear()
    this.stats = {
      totalTracked: 0,
      confirmedCount: 0,
      averageLifespan: 0,
      stageDistribution: {},
      ratingDistribution: {},
      survivalRate: {},
      averageGenesScore: 0,
    }
  }

  /**
   * 销毁
   */
  destroy() {
    this.destroyed = true

    this.unsubscribeFns.forEach((fn) => fn())
    this.unsubscribeFns = []
    this.clearCache()
  }

  // ✅ 新增：供刷新管理器调用的维护方法
  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    console.log('[DragonLifecycle] 执行后台维护')

    // 保存数据
    this.saveToStorage()

    // 清理过期观察数据
    this.cleanupExpiredObservations()

    // 检查观察队列老化
    if (this.canProcess()) {
      this.checkObservationAging(Date.now())
    }
  }

  /**
   * 更新统计
   */
  private updateStats() {
    const active = this.getActiveLeaders()

    this.stats = {
      totalTracked: this.lifecycles.size,
      confirmedCount: this.getConfirmedLeaders().length,
      averageLifespan: this.getAverageLifespan(),
      stageDistribution: this.getStageDistribution(),
      ratingDistribution: this.getRatingDistribution(),
      survivalRate: this.stats.survivalRate,
      averageGenesScore: this.getAverageGenesScore(),
    }

    Object.keys(LIFECYCLE_STAGES).forEach((stageId) => {
      const entered = this.transitions.filter((t) => t.toStage === stageId).length
      const exited = this.transitions.filter((t) => t.fromStage === stageId).length
      this.stats.survivalRate[stageId] =
        entered > 0 ? Math.round(((entered - exited) / entered) * 100 * 10) / 10 : 0
    })
  }

  /**
   * 获取状态
   */
  getStatus() {
    return {
      initialized: true,
      trackedCount: this.lifecycles.size,
      confirmedCount: this.getConfirmedLeaders().length,
      activeCount: this.getActiveLeaders().length,
      observationCount: this.getObservationStats().total,
      transitionsCount: this.transitions.length,
      familiesCount: this.families.size,
      pendingCount: this.pendingUpdates.size,
      paused: this.paused,
      stats: this.getStats(),
    }
  }
}

// ========== 类型定义 ==========
interface ObservationData {
  leader: LeaderInfo
  genetics: LeaderGenetics
  firstSeen: number
  lastSeen: number
  appearances: number[]
  scores: number[]
  geneticsHistory: LeaderGenetics[]
  queue: 'primary' | 'secondary' | 'cold'
  peakScore: number
  peakTime: number
}

interface LeaderTransition {
  code: string
  name: string
  fromStage: string
  toStage: string
  timestamp: number
  reason: string
}

interface LeaderFamily {
  code: string
  name: string
  parents: string[]
  children: string[]
  siblings: string[]
  rivals: string[]
  genetics?: string
}

// ========== 导出单例 ==========
export const dragonLifecycle = DragonLifecycleTracker.getInstance()

// ✅ 新增：在后台静默启动，不阻塞主线程
if (typeof window !== 'undefined') {
  // 使用 setTimeout 延迟执行，避免影响启动速度
  setTimeout(() => {
    console.log('[DragonLifecycle] 🔄 后台自动启动...')

    // 1. 如果有 resume 方法，调用它
    if (typeof dragonLifecycle.resume === 'function') {
      dragonLifecycle.resume()
    }

    // 2. 触发一次龙头更新事件，让服务开始处理现有数据
    import('./DragonAnalyzer')
      .then(({ dragonAnalyzer }) => {
        const leaders = dragonAnalyzer.getAllLeaders?.({ useCache: false }) || []
        if (leaders.length > 0) {
          console.log(`[DragonLifecycle] 发现 ${leaders.length} 个现有龙头，开始处理`)
          EventManager.emit(AppEvents.DRAGON.UPDATED, {
            timestamp: Date.now(),
            source: 'auto-start',
          })
        }
      })
      .catch((err) => {
        console.warn('[DragonLifecycle] 无法获取龙头分析器:', err)
      })
  }, 2000) // 延迟2秒，等主流程跑完
}

// 挂在 window 方便调试
if (typeof window !== 'undefined') {
  ;(window as any).dragonLifecycle = dragonLifecycle
}
