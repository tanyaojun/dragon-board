import { debugLog } from '@/utils/logger'
// src/services/DragonAnalyzer.ts

// @ts-nocheck
import type { Stock, LeaderInfo, LeaderChange, FactorDetail, LeaderLevelType } from '@/types'
import { LEADER_LEVELS } from '@/types'
import { ALERT_THRESHOLDS, ALERT_TYPES, ALERT_LEVELS } from '@/config/constants'
import { EventManager } from '@/utils/eventManager'
import { algorithmManager } from './algorithm/AlgorithmManager'
import { dragonBreathAnalyzer } from './DragonBreathAnalyzer'
import { dataLayer } from './DataLayer'
import { alertService } from './alertService'
import { getThresholdMultiplier } from '@/types/emotion'


// ========== 工具函数 ==========
const ThemeUtils = {
  getStockName(stock: Stock, code: string): string {
    return stock?.name || code || '未知'
  },
  getThemeName(theme: any): string | null {
    if (!theme) return null
    if (typeof theme === 'string') return theme !== '-' && theme !== '' ? theme : null
    if (typeof theme === 'object') {
      const name = theme?.name
      return name && name !== '-' && name !== '' ? name : null
    }
    return null
  },
}

// ========== 龙头信息类 ==========
class LeaderInfoImpl implements LeaderInfo {
  code: string
  name: string
  score: number
  level: LeaderLevelType
  levelName: string
  reasons: string[]
  factorDetails: Record<string, FactorDetail>
  price: number
  change: number
  turnover: number
  turnoverRate: number
  compRank: number
  zlje: number
  zljzb: number
  totalMV: number
  cirMV: number
  themes: any[]
  mainTheme: { name: string; heatScore?: number; heatLevel?: string } | null
  themeHeat: number
  themeLevel: string
  firstSeen: number
  lastSeen: number
  updateTime: number
  continuousDays: number

  constructor(
    stock: Stock,
    score: number,
    level: LeaderLevelType,
    reasons: string[] = [],
    factorDetails = {},
  ) {
    this.code = stock.code
    this.name = ThemeUtils.getStockName(stock, stock.code)
    this.score = score
    this.level = level
    this.levelName = LEADER_LEVELS[level]?.name || '未知'
    this.reasons = reasons
    this.factorDetails = factorDetails
    this.price = stock.price || 0
    this.change = stock.change || 0
    this.turnover = stock.turnover || 0
    this.turnoverRate = stock.turnoverRate || 0
    this.compRank = stock.compRank || 999
    this.zlje = stock.zlje || 0
    this.zljzb = stock.zljzb || 0
    this.totalMV = stock.totalMV || 0
    this.cirMV = stock.cirMV || 0
    this.themes = stock.themes || []
    this.mainTheme = stock.themes?.[0] ? { name: String(stock.themes[0]) } : null
    this.themeHeat = 80
    this.themeLevel = '热门'
    this.firstSeen = Date.now()
    this.lastSeen = Date.now()
    this.updateTime = Date.now()
    this.continuousDays = stock.continuousDays || 1
  }

  update(
    stock: Stock,
    score: number,
    reasons: string[],
    factorDetails: Record<string, FactorDetail>,
  ): void {
    this.score = score
    this.reasons = reasons
    this.factorDetails = factorDetails
    this.price = stock.price || 0
    this.change = stock.change || 0
    this.turnover = stock.turnover || 0
    this.zlje = stock.zlje || 0
    this.lastSeen = Date.now()
    this.updateTime = Date.now()
    if (stock.change && stock.change > 9.5) {
      this.continuousDays++
    } else {
      this.continuousDays = 1
    }
  }

  toJSON(): LeaderInfo {
    return {
      code: this.code,
      name: this.name,
      score: this.score,
      level: this.level,
      levelName: this.levelName,
      reasons: this.reasons,
      factorDetails: this.factorDetails,
      price: this.price,
      change: this.change,
      turnover: this.turnover,
      turnoverRate: this.turnoverRate,
      compRank: this.compRank,
      zlje: this.zlje,
      zljzb: this.zljzb,
      totalMV: this.totalMV,
      cirMV: this.cirMV,
      themes: this.themes,
      mainTheme: this.mainTheme,
      themeHeat: this.themeHeat,
      themeLevel: this.themeLevel,
      firstSeen: this.firstSeen,
      lastSeen: this.lastSeen,
      updateTime: this.updateTime,
      continuousDays: this.continuousDays,
    }
  }
}

// ========== 龙头分析器主类 ==========
export class DragonAnalyzer {
  private static instance: DragonAnalyzer
  private state = {
    initialized: false,
    algorithm: null as any,
    thresholds: null as any,
    leaders: new Map<string, LeaderInfoImpl>(), // 只保留 leaders，其他从 DataLayer 获取
    changes: [] as LeaderChange[],
    stats: {
      totalLeaders: 0,
      totalLeadersCount: 0,
      sectorLeaders: 0,
      continuousLeaders: 0,
      middleLeaders: 0,
      emotionLeaders: 0,
      themeLeaders: 0,
      lastUpdate: null as number | null,
    },
    _recalculating: false,
  }

  private unsubscribeFns: (() => void)[] = []
  private destroyed = false
  private updateTimeout: ReturnType<typeof setTimeout> | null = null
  private pendingUpdates: Set<string> = new Set()

  // 用于记录前一状态的龙头数据，用于预警对比
  private previousLeaders: Map<string, { level: string; price: number; change: number }> = new Map()

  private constructor() {}

  static getInstance(): DragonAnalyzer {
    if (!DragonAnalyzer.instance) {
      DragonAnalyzer.instance = new DragonAnalyzer()
    }
    return DragonAnalyzer.instance
  }

  // ========== 初始化 ==========
  async init(): Promise<boolean> {
    if (this.destroyed || this.state.initialized) return false
    debugLog('[DragonAnalyzer] 📊 初始化龙头分析器...')
    this.updateAlgorithm()
    this.state.initialized = true
    debugLog('[DragonAnalyzer] ✅ 初始化完成')
    return true
  }

  // ========== 供协调者调用的方法 ==========
  async runFullUpdate(): Promise<void> {
    if (this.destroyed || this.state._recalculating) return
    debugLog('[DragonAnalyzer] 执行全量更新')
    await this.recalculateAll()
  }

  async syncData(): Promise<void> {
    if (this.destroyed) return
    debugLog('[DragonAnalyzer] 同步龙头数据到 DataLayer')
    const leaders = Array.from(this.state.leaders.values()).map((l) => l.toJSON())
    if (typeof (dataLayer as any).updateLeaderData === 'function') {
      ;(dataLayer as any).updateLeaderData(leaders)
    }
    dataLayer.bumpLeadersVersion?.()
  }

  async runMaintenance(): Promise<void> {
    if (this.destroyed) return
    // 简单维护，不需要复杂的一致性检查
    if (this.state.changes.length > 100) {
      this.state.changes = this.state.changes.slice(0, 100)
    }
  }

  // ========== 预警检查函数 ==========

  /**
   * 检查龙头倒下预警
   */
  private checkLeaderFallAlert(leader: LeaderInfoImpl, oldLeader: { change: number } | null) {
    if (!leader) return

    const change = leader.change || 0

    // 龙头大跌预警
    if (change <= ALERT_THRESHOLDS.LEADER_FALL.WARNING) {
      const level =
        change <= ALERT_THRESHOLDS.LEADER_FALL.CRITICAL
          ? ALERT_LEVELS.CRITICAL
          : ALERT_LEVELS.WARNING

      alertService.sendAlert({
        type: ALERT_TYPES.LEADER_FALL,
        level,
        title: `👑 ${leader.name} 龙头倒下`,
        message: `${leader.levelName}跌幅 ${change.toFixed(2)}%`,
        code: leader.code,
        name: leader.name,
        themeName: leader.mainTheme?.name,
        snapshot: {
          change,
          price: leader.price,
          level: leader.level,
        },
      })
    }

    // 龙头连续大跌（需要对比历史）
    if (oldLeader && oldLeader.change < -5 && change < -5) {
      alertService.sendAlert({
        type: ALERT_TYPES.LEADER_FALL,
        level: ALERT_LEVELS.WARNING,
        title: `📉 ${leader.name} 连续大跌`,
        message: `连续两日跌幅超过5%`,
        code: leader.code,
        name: leader.name,
        themeName: leader.mainTheme?.name,
        snapshot: {
          change,
          prevChange: oldLeader.change,
        },
      })
    }
  }

  /**
   * 检查新龙头涌现预警
   */
  private checkLeaderEmergeAlert(leader: LeaderInfoImpl, isNew: boolean) {
    if (!leader) return

    // 新龙头出现
    if (isNew) {
      alertService.sendAlert({
        type: ALERT_TYPES.LEADER_EMERGE,
        level: ALERT_LEVELS.INFO,
        title: `🌟 新龙头诞生: ${leader.name}`,
        message: `晋级${leader.levelName}，得分 ${leader.score}`,
        code: leader.code,
        name: leader.name,
        themeName: leader.mainTheme?.name,
        snapshot: {
          level: leader.level,
          score: leader.score,
          change: leader.change,
        },
      })
    }
  }

  /**
   * 检查龙头晋级/降级预警
   */
  private checkLeaderLevelChangeAlert(leader: LeaderInfoImpl, oldLevel: string, newLevel: string) {
    if (!leader || oldLevel === newLevel) return

    const isPromotion = LEADER_LEVELS[oldLevel]?.order > LEADER_LEVELS[newLevel]?.order

    alertService.sendAlert({
      type: ALERT_TYPES.LEADER_EMERGE,
      level: ALERT_LEVELS.INFO,
      title: isPromotion ? `📈 ${leader.name} 晋级` : `📉 ${leader.name} 降级`,
      message: isPromotion
        ? `从${LEADER_LEVELS[oldLevel]?.name}晋升为${LEADER_LEVELS[newLevel]?.name}`
        : `从${LEADER_LEVELS[oldLevel]?.name}降级为${LEADER_LEVELS[newLevel]?.name}`,
      code: leader.code,
      name: leader.name,
      themeName: leader.mainTheme?.name,
      snapshot: {
        oldLevel,
        newLevel,
        score: leader.score,
        change: leader.change,
      },
    })
  }

  /**
   * 检查连板高度预警
   */
  private checkContinuousDaysAlert(leader: LeaderInfoImpl) {
    if (!leader || !leader.continuousDays) return

    const days = leader.continuousDays

    // 高度连板预警
    if (days >= 5) {
      alertService.sendAlert({
        type: ALERT_TYPES.LEADER_EMERGE,
        level: ALERT_LEVELS.WARNING,
        title: `⚡ ${leader.name} ${days}连板`,
        message: `晋级${days}连板，成为市场高标`,
        code: leader.code,
        name: leader.name,
        themeName: leader.mainTheme?.name,
        snapshot: {
          continuousDays: days,
          change: leader.change,
        },
      })
    } else if (days >= 3) {
      alertService.sendAlert({
        type: ALERT_TYPES.LEADER_EMERGE,
        level: ALERT_LEVELS.INFO,
        title: `📈 ${leader.name} ${days}连板`,
        message: `成功晋级${days}连板`,
        code: leader.code,
        name: leader.name,
        themeName: leader.mainTheme?.name,
        snapshot: {
          continuousDays: days,
          change: leader.change,
        },
      })
    }
  }

  /**
   * 批量检查所有龙头预警
   */
  private checkLeaderAlerts(
    newLeaders: Map<string, LeaderInfoImpl>,
    oldLeaders: Map<string, LeaderInfoImpl>,
  ) {
    // 检查新龙头
    newLeaders.forEach((leader, code) => {
      const oldLeader = oldLeaders.get(code)
      const isNew = !oldLeader

      // 新龙头涌现
      if (isNew) {
        this.checkLeaderEmergeAlert(leader, true)
      }

      // 龙头状态变化
      if (oldLeader) {
        // 级别变化
        if (oldLeader.level !== leader.level) {
          this.checkLeaderLevelChangeAlert(leader, oldLeader.level, leader.level)
        }

        // 连板高度变化
        if (leader.continuousDays > (oldLeader.continuousDays || 1)) {
          this.checkContinuousDaysAlert(leader)
        }
      }

      // 龙头倒下（始终检查）
      this.checkLeaderFallAlert(leader, oldLeader ? { change: oldLeader.change } : null)
    })

    // 检查消失的龙头（从旧列表中有，新列表中没有）
    oldLeaders.forEach((oldLeader, code) => {
      if (!newLeaders.has(code)) {
        alertService.sendAlert({
          type: ALERT_TYPES.LEADER_FALL,
          level: ALERT_LEVELS.WARNING,
          title: `👑 ${oldLeader.name} 退出龙头榜`,
          message: `从龙头榜单中消失`,
          code: oldLeader.code,
          name: oldLeader.name,
          themeName: oldLeader.mainTheme?.name,
          snapshot: {
            lastChange: oldLeader.change,
            lastScore: oldLeader.score,
          },
        })
      }
    })
  }

  // ========== 核心计算 ==========
  async calculateScore(
    stock: Stock,
  ): Promise<{ score: number; details: Record<string, FactorDetail> }> {
    if (!stock) return { score: 50, details: {} }

    if (algorithmManager?.calculateScore) {
      try {
        const result = await algorithmManager.calculateScore(stock)
        if (result && typeof result.score === 'number') {
          return result
        }
      } catch (error) {
        console.warn(`[DragonAnalyzer] ${stock.code} 算法计算失败`, error)
      }
    }

    // 后备算法
    const rank = stock.compRank || 999
    const score = Math.max(0, 100 - rank)
    return { score, details: {} }
  }

  determineLevel(stock: Stock, score: number): LeaderLevelType | null {
    const baseThresholds = algorithmManager?.getLeaderThresholds?.() || this.getThresholds()

    // ✅ 获取当前情绪阶段和阈值乘数
    const sentiment = dragonBreathAnalyzer?.getMarketSentiment?.()
    let phaseName = sentiment?.phaseName || '震荡期'
    let multiplier = getThresholdMultiplier(phaseName)

    // 应用阈值乘数
    const thresholds = {
      totalLeader: Math.min(95, Math.round(baseThresholds.totalLeader * multiplier.totalLeader)),
      continuousLeader: Math.min(
        90,
        Math.round(baseThresholds.continuousLeader * multiplier.continuousLeader),
      ),
      sectorLeader: Math.min(85, Math.round(baseThresholds.sectorLeader * multiplier.sectorLeader)),
      middleLeader: Math.min(80, Math.round(baseThresholds.middleLeader * multiplier.middleLeader)),
      emotionLeader: Math.min(
        75,
        Math.round(baseThresholds.emotionLeader * multiplier.emotionLeader),
      ),
    }

    if (score >= thresholds.totalLeader) return 'TOTAL'
    if (score >= thresholds.continuousLeader) return 'CONTINUOUS'
    if (score >= thresholds.sectorLeader) return 'SECTOR'
    if (score >= thresholds.middleLeader) return 'MIDDLE'
    if (score >= thresholds.emotionLeader) return 'EMOTION'
    return null
  }

  /**
   * ✅ 删除旧的 getDynamicThresholds 方法，改用上面直接计算的方式
   */

  private generateReasons(stock: Stock, level: LeaderLevelType, scoreResult: any): string[] {
    const reasons = []
    switch (level) {
      case 'TOTAL':
        reasons.push('市场总龙头 👑')
        break
      case 'CONTINUOUS':
        reasons.push(`${stock.continuousDays || 1}连板 📈`)
        break
      case 'SECTOR':
        reasons.push('板块龙头 🏆')
        break
      case 'MIDDLE':
        reasons.push('中军龙头 ⚔️')
        break
      case 'EMOTION':
        reasons.push('情绪龙头 🔥')
        break
    }
    const sentiment = dragonBreathAnalyzer?.getMarketSentiment?.()
    if (sentiment?.phaseName) reasons.push(`市场情绪: ${sentiment.phaseName}`)
    return reasons
  }

  private async calculateLeader(stock: Stock): Promise<LeaderInfo | null> {
    if (!stock) return null
    const scoreResult = await this.calculateScore(stock)
    if (!scoreResult || typeof scoreResult.score !== 'number') return null
    const finalLevel = this.determineLevel(stock, scoreResult.score)
    if (!finalLevel) return null
    const reasons = this.generateReasons(stock, finalLevel, scoreResult)
    return new LeaderInfoImpl(stock, scoreResult.score, finalLevel, reasons, scoreResult.details)
  }

  // ========== 全量更新 ==========
  async recalculateAll(): Promise<number> {
    if (this.destroyed || this.state._recalculating) return 0
    this.state._recalculating = true

    const stocks = dataLayer.getStocks()
    if (!stocks?.length) {
      this.state._recalculating = false
      return 0
    }

    const newLeaders = new Map<string, LeaderInfoImpl>()
    const batchSize = 50

    for (let i = 0; i < stocks.length; i += batchSize) {
      const batch = stocks.slice(i, i + batchSize)
      const promises = batch.map(async (stock) => {
          const leader = await this.calculateLeader(stock)
          if (leader) newLeaders.set(stock.code, leader)
      })
      await Promise.all(promises)
      await new Promise((resolve) => setTimeout(resolve, 0))
    }

    const oldLeaders = this.state.leaders

    this.checkLeaderAlerts(newLeaders, oldLeaders)

    this.state.leaders = newLeaders
    this.detectChanges(oldLeaders, this.state.leaders)
    this.updateStats()

    debugLog(`[DragonAnalyzer] 全量更新完成: ${this.state.leaders.size} 个龙头`)
    this.state._recalculating = false
    return this.state.leaders.size
  }

  // ========== 变化检测 ==========
  private detectChanges(
    oldLeaders: Map<string, LeaderInfoImpl>,
    newLeaders: Map<string, LeaderInfoImpl>,
  ): void {
    const changes: LeaderChange[] = []
    newLeaders.forEach((leader, code) => {
      if (!oldLeaders.has(code)) {
        changes.push({
          type: '新增',
          code,
          name: leader.name,
          level: leader.levelName,
          time: Date.now(),
        })
      }
    })
    oldLeaders.forEach((leader, code) => {
      if (!newLeaders.has(code)) {
        changes.push({
          type: '消失',
          code,
          name: leader.name,
          level: leader.levelName,
          time: Date.now(),
        })
      }
    })
    newLeaders.forEach((newLeader, code) => {
      const oldLeader = oldLeaders.get(code)
      if (oldLeader && oldLeader.level !== newLeader.level) {
        changes.push({
          type: oldLeader.level === 'TOTAL' ? '降级' : '晋级',
          code,
          name: newLeader.name,
          fromLevel: oldLeader.levelName,
          toLevel: newLeader.levelName,
          time: Date.now(),
        })
      }
    })
    if (changes.length > 0) {
      this.state.changes = [...changes, ...this.state.changes].slice(0, 20)
      // 同时触发事件，供其他组件使用
      changes.forEach((change) => {
        EventManager.emit('dragon:change', change)
      })
    }
  }

  private updateStats(): void {
    const stats = {
      totalLeaders: 0,
      totalLeadersCount: 0,
      sectorLeaders: 0,
      continuousLeaders: 0,
      middleLeaders: 0,
      emotionLeaders: 0,
      themeLeaders: 0,
      lastUpdate: Date.now(),
    }
    this.state.leaders.forEach((leader) => {
      stats.totalLeaders++
      switch (leader.level) {
        case 'TOTAL':
          stats.totalLeadersCount++
          break
        case 'SECTOR':
          stats.sectorLeaders++
          break
        case 'CONTINUOUS':
          stats.continuousLeaders++
          break
        case 'MIDDLE':
          stats.middleLeaders++
          break
        case 'EMOTION':
          stats.emotionLeaders++
          break
      }
    })
    this.state.stats = stats
  }

  // ========== 算法配置 ==========
  private updateAlgorithm(): void {
    this.state.algorithm = algorithmManager?.getCurrentAlgorithm?.() || null
    this.state.thresholds = algorithmManager?.getThresholds?.() || null
  }

  getThresholds(): Record<string, number> {
    return (
      this.state.thresholds || {
        totalLeader: 80,
        sectorLeader: 65,
        continuousLeader: 70,
        middleLeader: 60,
        emotionLeader: 55,
      }
    )
  }

  // ========== 公共API ==========
  getAllLeaders(options?: {
    level?: LeaderLevelType
    theme?: string
    limit?: number
  }): LeaderInfo[] {
    let leaders = Array.from(this.state.leaders.values())

    // 按级别过滤
    if (options?.level) {
      leaders = leaders.filter((l) => l.level === options.level)
    }

    // 按题材过滤
    if (options?.theme) {
      leaders = leaders.filter((l) => l.themes.some((t) => t.name === options.theme))
    }

    // 排序
    leaders.sort((a, b) => b.score - a.score)

    // 限制数量
    if (options?.limit) {
      leaders = leaders.slice(0, options.limit)
    }

    return leaders.map((l) => l.toJSON())
  }

  getLeadersByLevel(level: LeaderLevelType, limit: number = 10): LeaderInfo[] {
    return Array.from(this.state.leaders.values())
      .filter((l) => l.level === level)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((l) => l.toJSON())
  }

  getLeadersByTheme(theme: string, limit?: number) {
    return this.getAllLeaders({ theme, limit })
  }

  getLeaderByCode(code: string): LeaderInfo | null {
    const leader = this.state.leaders.get(code)
    return leader ? leader.toJSON() : null
  }

  getLeaderChanges(limit: number = 10): LeaderChange[] {
    return this.state.changes.slice(0, limit)
  }

  getStats(): LeaderStats {
    return { ...this.state.stats }
  }

  getLeaderDistribution(): { byLevel: Record<string, number>; total: number } {
    const byLevel: Record<string, number> = {}
    this.state.leaders.forEach((leader) => {
      byLevel[leader.level] = (byLevel[leader.level] || 0) + 1
    })
    return { byLevel, total: this.state.leaders.size }
  }

  getStatus() {
    return {
      initialized: this.state.initialized,
      leadersCount: this.state.leaders.size,
      changesCount: this.state.changes.length,
      stats: this.state.stats,
    }
  }

  // ========== 销毁 ==========
  destroy(): void {
    if (this.destroyed) return
    this.destroyed = true
    this.state.initialized = false
    if (this.updateTimeout) clearTimeout(this.updateTimeout)
    this.unsubscribeFns.forEach((fn) => fn())
    this.unsubscribeFns = []
    this.state.leaders.clear()
    this.state.changes = []
  }

  debug() {
    return {
      leadersCount: this.state.leaders.size,
      changesCount: this.state.changes.length,
      stats: this.state.stats,
    }
  }
}

export const dragonAnalyzer = DragonAnalyzer.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).dragonAnalyzer = dragonAnalyzer
}
