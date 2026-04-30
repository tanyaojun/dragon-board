// src/services/rotationService.ts
// 职责：基于 jxbk 真实数据的轮动分析服务（融入情绪感知）

import { dataLayer } from './DataLayer'
import { dragonBreathAnalyzer } from './DragonBreathAnalyzer'
import { UNIFIED_EMOTION } from '../types/emotion'
import { themeCorrelationAnalyzer } from './ThemeCorrelationAnalyzer'
import type {
  ThemeRotationStatus,
  RotationAnalysis,
  RotationDirection,
  RotationStrength,
  MarketPhaseType,
} from '../types/core'
import { ROTATION_CONFIG } from '../config/constants'

function normalizeEmotionPhase(value?: unknown): string {
  if (typeof value !== 'string') return '启动'
  const phase = value.trim()
  return phase.endsWith('期') ? phase.slice(0, -1) : phase
}

function getPhaseBand(phase: string): number {
  const normalized = normalizeEmotionPhase(phase)
  if (normalized === '高潮') return 88
  if (normalized === '发酵') return 66
  if (normalized === '启动') return 45
  if (normalized === '退潮') return 35
  if (normalized === '冰点') return 20
  return 50
}

interface JxbkBlockData {
  code: string
  name: string
  strength: number
  change: number
  mainNetInflow: number
  bigMoney300: number
  institutionBuy: number
  volumeRatio: number
  ztCount: number
}

type RotationStrongTheme = {
  themeId: string
  themeName: string
  strengthScore: number
  jxbkStrength: number
  ztCount: number
  volumeRatio: number
  netInflow: number
}

type RotationAnalysisCompat = Omit<RotationAnalysis, 'strongThemes'> & {
  strongThemes: RotationStrongTheme[]
}

class RotationService {
  private lastAnalysis: RotationAnalysisCompat | null = null
  private analysisTimer: ReturnType<typeof setInterval> | null = null
  private previousRanks: Record<string, number> = {}
  private previousInflows: Record<string, number> = {}

  constructor() {
    this.startAutoAnalysis()
  }

  /**
   * 启动自动分析
   */
  private startAutoAnalysis() {
    if (!ROTATION_CONFIG.ENABLED) return

    this.analysisTimer = setInterval(() => {
      this.analyzeAll()
    }, ROTATION_CONFIG.ANALYSIS_INTERVAL)
  }

  /**
   * 停止自动分析
   */
  stopAutoAnalysis() {
    if (this.analysisTimer) {
      clearInterval(this.analysisTimer)
      this.analysisTimer = null
    }
  }

  /**
   * 获取当前情绪数据
   */
  private getCurrentEmotion() {
    try {
      const sentiment = dragonBreathAnalyzer.getMarketSentiment()
      const phase = normalizeEmotionPhase(sentiment?.phaseName || sentiment?.phase || '启动')
      const phaseBand = getPhaseBand(phase)

      // 从统一配置中获取情绪乘数
      const multipliers = UNIFIED_EMOTION.IMPACT.THEME

      return {
        phase,
        phaseBand,
        heatMultiplier:
          multipliers.HEAT_MULTIPLIERS[phase as keyof typeof multipliers.HEAT_MULTIPLIERS] || 1.0,
        momentumMultiplier:
          multipliers.MOMENTUM_IMPACT[phase as keyof typeof multipliers.MOMENTUM_IMPACT] || 1.0,
        rotationSpeedMultiplier:
          multipliers.ROTATION_SPEED[phase as keyof typeof multipliers.ROTATION_SPEED] || 1.0,
        ztBonus: multipliers.ZT_BONUS,
        zhabanPenalty: multipliers.ZHABAN_PENALTY,
      }
    } catch (e) {
      return {
        phase: '启动',
        phaseBand: 45,
        heatMultiplier: 1.0,
        momentumMultiplier: 1.0,
        rotationSpeedMultiplier: 1.0,
        ztBonus: 5,
        zhabanPenalty: 0.005,
      }
    }
  }

  /**
   * 分析单个板块（融入情绪因子）
   */
  private analyzeThemeFlow(block: JxbkBlockData, emotion: any): ThemeRotationStatus | null {
    if (!block) return null

    const netInflow = block.mainNetInflow || 0
    const ztCount = block.ztCount || 0
    const strength = block.strength || 0
    const volumeRatio = block.volumeRatio || 1
    const change = block.change || 0
    const bigMoney300 = block.bigMoney300 || 0
    const institutionBuy = block.institutionBuy || 0

    // 判断方向
    let direction: RotationDirection = 'neutral'
    if (netInflow > ROTATION_CONFIG.FUND_THRESHOLDS.MEDIUM_INFLOW) {
      direction = 'inflow'
    } else if (netInflow < ROTATION_CONFIG.FUND_THRESHOLDS.MEDIUM_OUTFLOW) {
      direction = 'outflow'
    }

    // 计算强度分数（融入情绪因子）
    const strengthScore = this.calculateStrengthScore(
      strength,
      ztCount,
      volumeRatio,
      netInflow,
      emotion,
    )

    // 判断强度等级
    let strengthLevel: RotationStrength = 'weak'
    if (strengthScore >= 80) {
      strengthLevel = 'strong'
    } else if (strengthScore >= 50) {
      strengthLevel = 'medium'
    }

    // 计算持续天数
    const persistentDays = this.calculatePersistentDays(block.code)

    // 判断是否为主线（融入情绪）
    const isMainLine = this.isMainLine(block, strengthScore, persistentDays, emotion)

    // 计算资金变化率
    const inflowChange = this.calculateInflowChange(block.code, netInflow)

    return {
      themeId: block.code,
      themeName: block.name,
      inflow: netInflow > 0 ? netInflow : 0,
      outflow: netInflow < 0 ? Math.abs(netInflow) : 0,
      netInflow: netInflow,
      avgChange: change,
      totalTurnover: 0,
      ztCount: ztCount,
      totalBoardHeight: 0,
      avgBoardHeight: 0,
      highDays: 0,
      topReasons: [],
      stockCount: 0,
      rank: 0,
      rankChange: 0,
      direction,
      strength: strengthLevel,
      strengthScore,
      persistentDays,
      isMainLine,
      relatedThemes: [],
      volumeRatio,
      bigMoney300,
      institutionBuy,
      inflowChange,
    }
  }

  /**
   * 计算强度分数（融入情绪）
   */
  private calculateStrengthScore(
    strength: number,
    ztCount: number,
    volumeRatio: number,
    netInflow: number,
    emotion: any,
  ): number {
    let score = 0

    // 强度贡献 (0-40分) - 融入情绪乘数
    if (strength >= 4000) score += 40 * emotion.heatMultiplier
    else if (strength >= 3000) score += 30 * emotion.heatMultiplier
    else if (strength >= 2000) score += 20 * emotion.heatMultiplier
    else if (strength >= 1000) score += 10 * emotion.heatMultiplier
    else score += 5 * emotion.heatMultiplier

    // 涨停贡献 (0-30分) - 情绪好时涨停加成
    if (ztCount >= 10) score += 30 + emotion.ztBonus
    else if (ztCount >= 5) score += 25 + emotion.ztBonus
    else if (ztCount >= 3) score += 20 + emotion.ztBonus
    else if (ztCount >= 1) score += 15

    // 量比贡献 (0-15分)
    if (volumeRatio >= 2.5) score += 15
    else if (volumeRatio >= 1.5) score += 10
    else if (volumeRatio >= 0.8) score += 5

    // 资金贡献 (0-15分)
    if (netInflow > 100000000) score += 15
    else if (netInflow > 50000000) score += 12
    else if (netInflow > 10000000) score += 8
    else if (netInflow > 0) score += 5

    return Math.min(100, Math.round(score))
  }

  /**
   * 判断是否为主线（融入情绪）
   */
  private isMainLine(
    block: JxbkBlockData,
    strengthScore: number,
    persistentDays: number,
    emotion: any,
  ): boolean {
    // 基础主线判断
    const baseCondition = persistentDays >= 3 && block.mainNetInflow > 0 && strengthScore >= 60

    // 情绪加成条件
    const emotionBonus =
      ['发酵', '高潮'].includes(normalizeEmotionPhase(emotion.phase)) &&
      block.ztCount >= 3 &&
      block.mainNetInflow > 0

    // 爆发力条件（不受持续天数限制）
    const explosiveCondition =
      block.ztCount >= 5 && block.mainNetInflow > 100000000 && strengthScore >= 80

    return baseCondition || emotionBonus || explosiveCondition
  }

  /**
   * 计算资金变化率
   */
  private calculateInflowChange(blockCode: string, currentInflow: number): number {
    const previous = this.previousInflows[blockCode]
    if (previous === undefined) return 0
    if (previous === 0) return currentInflow > 0 ? 100 : 0
    const change = ((currentInflow - previous) / Math.abs(previous)) * 100
    return Math.round(change)
  }

  /**
   * 计算持续天数
   */
  private calculatePersistentDays(themeId: string): number {
    const historyDates = JSON.parse(localStorage.getItem('hot_themes_history') || '[]')
    let days = 0

    for (let i = historyDates.length - 1; i >= 0; i--) {
      const date = historyDates[i]
      const dayData = JSON.parse(localStorage.getItem(`hot_themes_${date}`) || '[]')
      const found = dayData.find((item: any) => item.themeId === themeId)

      if (found) {
        days = found.persistentDays || days + 1
      } else {
        break
      }
    }
    return days
  }

  /**
   * 判断市场阶段（融入情绪数据）
   */
  private determineMarketPhase(
    inflowThemes: ThemeRotationStatus[],
    outflowThemes: ThemeRotationStatus[],
    rotationSpeed: number,
    strongThemes: ThemeRotationStatus[],
    emotion: any,
  ): MarketPhaseType {
    const mainLines = inflowThemes.filter((t) => t.isMainLine)
    const strongCount = strongThemes.length
    const inflowCount = inflowThemes.length
    const outflowCount = outflowThemes.length
    const emotionPhase = normalizeEmotionPhase(emotion.phase)

    // 冰点期：阶段低迷 + 流入少
    if (emotionPhase === '冰点' || (inflowCount < 3 && strongCount < 2 && emotionPhase === '冰点')) {
      return 'ice'
    }

    // 筑底期：情绪开始回暖，但轮动慢
    if (
      emotionPhase === '启动' ||
      (inflowCount > 0 && rotationSpeed < 30 && mainLines.length < 2)
    ) {
      return 'accumulation'
    }

    // 上升期：情绪活跃 + 主线明确 + 轮动适中
    if (
      emotionPhase === '发酵' ||
      (mainLines.length >= 2 && strongCount >= 3 && rotationSpeed < 50)
    ) {
      return 'rising'
    }

    // 高潮期：情绪亢奋 + 轮动快
    if (
      emotionPhase === '高潮' ||
      (mainLines.length >= 4 && rotationSpeed > 60) ||
      (emotionPhase === '高潮' && rotationSpeed > 50)
    ) {
      return 'climax'
    }

    // 出货期：情绪高位 + 轮动极快
    if (
      (emotionPhase === '发酵' && rotationSpeed > 60) ||
      (inflowCount > 0 && outflowCount > 0 && Math.abs(inflowCount - outflowCount) < 3)
    ) {
      return 'distribution'
    }

    // 退潮期：情绪下降 + 流出多
    if (emotionPhase === '退潮' || outflowCount > inflowCount * 1.5) {
      return 'falling'
    }

    return 'accumulation'
  }

  /**
   * 分析所有板块
   */
  analyzeAll(): RotationAnalysisCompat {
    // 1. 获取当前情绪
    const emotion = this.getCurrentEmotion()

    // 2. 获取 jxbk 板块数据
    const jxbkBlocks = dataLayer.getJxbkBlocksSorted() || []

    if (jxbkBlocks.length === 0) {
      return this.getEmptyAnalysis()
    }

    // 3. 分析每个板块（传入情绪数据）
    const flows: ThemeRotationStatus[] = []

    jxbkBlocks.forEach((block) => {
      const flow = this.analyzeThemeFlow(block, emotion)
      if (flow) {
        flows.push(flow)
      }
    })

    if (flows.length === 0) {
      return this.getEmptyAnalysis()
    }

    // 4. 按强度分数排序
    flows.sort((a, b) => (b.strengthScore || 0) - (a.strengthScore || 0))

    // 判断是否是首次运行
    const isFirstRun = Object.keys(this.previousRanks).length === 0

    // 5. 设置排名并计算排名变化
    flows.forEach((flow, index) => {
      const newRank = index + 1
      if (!isFirstRun) {
        const oldRank = this.previousRanks[flow.themeId]
        flow.rankChange = oldRank !== undefined ? oldRank - newRank : 0
      } else {
        flow.rankChange = 0
      }
      flow.rank = newRank
      this.previousRanks[flow.themeId] = newRank
      this.previousInflows[flow.themeId] = flow.netInflow
    })

    // 6. 分类
    const inflowThemes = flows.filter((f) => f.netInflow > 0)
    const outflowThemes = flows.filter((f) => f.netInflow < 0)

    // 主线板块（融入情绪）
    let mainLines = flows.filter((f) => f.isMainLine)

    if (mainLines.length < 3) {
      const candidates = flows.filter((f) => f.persistentDays >= 2 && (f.strengthScore || 0) >= 75)
      mainLines = [...mainLines, ...candidates].slice(0, 5)
    }

    const strongThemes = flows.filter((f) => (f.strengthScore || 0) >= 70)
    const quickRotation = flows.filter((f) => Math.abs(f.rankChange) >= 5)

    // 7. 计算轮动速度（融入情绪乘数）
    let rotationSpeed = 0
    if (isFirstRun) {
      const ztBlocks = flows.filter((f) => f.ztCount > 0).length
      rotationSpeed = Math.min(
        100,
        Math.round((ztBlocks / flows.length) * 70 * emotion.rotationSpeedMultiplier),
      )
    } else {
      const avgRankChange = flows.reduce((sum, f) => sum + Math.abs(f.rankChange), 0) / flows.length
      rotationSpeed = Math.min(
        100,
        Math.round(avgRankChange * 10 * emotion.rotationSpeedMultiplier),
      )
    }

    // 8. 判断市场阶段（融入情绪）
    const marketPhase = this.determineMarketPhase(
      inflowThemes,
      outflowThemes,
      rotationSpeed,
      strongThemes,
      emotion,
    )

    // 9. 生成阶段建议（融入情绪）
    const suggestion = this.generateMarketSuggestion(marketPhase, mainLines, strongThemes, emotion)

    // 10. 构建分析结果
    const analysis: RotationAnalysisCompat = {
      timestamp: Date.now(),
      inflowThemes: inflowThemes.slice(0, 10),
      outflowThemes: outflowThemes.slice(0, 10),
      mainLines: mainLines.slice(0, 5),
      strongThemes: strongThemes.slice(0, 5).map((t) => ({
        themeId: t.themeId,
        themeName: t.themeName,
        strengthScore: t.strengthScore || 0,
        jxbkStrength: t.strengthScore || 0,
        ztCount: t.ztCount || 0,
        volumeRatio: t.volumeRatio || 0,
        netInflow: t.netInflow || 0,
      })),
      quickRotation: quickRotation.slice(0, 5),
      rotationSpeed,
      marketPhase,
      emotion: {
        value: emotion.phaseBand,
        status: emotion.phase,
        phase: emotion.phase,
      },
      summary: {
        mainLineCount: mainLines.length,
        inflowCount: inflowThemes.length,
        outflowCount: outflowThemes.length,
        topInflow: inflowThemes[0]?.themeName || '无',
        topOutflow: outflowThemes[0]?.themeName || '无',
        suggestion,
        strongCount: strongThemes.length,
        topStrength: strongThemes[0]?.themeName || '无',
      },
    }

    // 11. 保存到 dataLayer
    dataLayer.updateRotationAnalysis?.(analysis)
    this.lastAnalysis = analysis

    // 12. 保存热门板块到 localStorage（每天一次）
    this.saveHotThemesToLocalStorage(flows)

    // 13. 分析完主线后，触发联动分析（异步，不阻塞）
    if (mainLines.length > 0) {
      // 异步分析主线题材的联动性
      setTimeout(() => {
        for (const mainLine of mainLines.slice(0, 3)) {
          // 最多分析3个主线
          themeCorrelationAnalyzer
            .analyzeThemeCorrelation(mainLine.themeId, mainLine.themeName, { force: false })
            .catch((e) => console.warn('联动分析失败:', e))
        }
      }, 100)
    }

    return analysis
  }

  /**
   * 保存热门板块到 localStorage
   */
  private saveHotThemesToLocalStorage(flows: ThemeRotationStatus[]) {
    try {
      const today = new Date().toISOString().split('T')[0]
      const lastSavedDate = localStorage.getItem('hot_themes_last_saved')
      const historyDates = JSON.parse(localStorage.getItem('hot_themes_history') || '[]')

      // ✅ 计算正确的 persistentDays
      const top10Themes = flows.slice(0, 10).map((f) => {
        // 查找历史数据中该板块是否出现过
        let persistentDays = 1 // 今天算第一天

        // 如果有昨天及之前的数据，计算连续出现天数
        if (historyDates.length > 0) {
          // 从最新的历史往前查
          for (let i = historyDates.length - 1; i >= 0; i--) {
            const date = historyDates[i]
            if (date === today) continue // 跳过今天

            const dayData = JSON.parse(localStorage.getItem(`hot_themes_${date}`) || '[]')
            const found = dayData.find((item: any) => item.themeId === f.themeId)

            if (found) {
              persistentDays++
            } else {
              break
            }
          }
        }

        return {
          themeId: f.themeId,
          themeName: f.themeName,
          rank: f.rank,
          strength: f.strengthScore,
          netInflow: f.netInflow,
          ztCount: f.ztCount,
          persistentDays, // ✅ 正确计算持续天数
          timestamp: Date.now(),
        }
      })

      localStorage.setItem(`hot_themes_${today}`, JSON.stringify(top10Themes))

      // 维护历史索引
      if (!historyDates.includes(today)) {
        historyDates.push(today)
        if (historyDates.length > 30) {
          const oldestDate = historyDates.shift()
          localStorage.removeItem(`hot_themes_${oldestDate}`)
        }
        localStorage.setItem('hot_themes_history', JSON.stringify(historyDates))
      }

      localStorage.setItem('hot_themes_last_saved', today)
    } catch (e) {
      console.warn('[RotationService] 保存到 localStorage 失败:', e)
    }
  }

  /**
   * 生成市场阶段建议（融入情绪）
   */
  private generateMarketSuggestion(
    phase: MarketPhaseType,
    mainLines: ThemeRotationStatus[],
    strongThemes: ThemeRotationStatus[],
    emotion: any,
  ): string {
    const suggestions: Record<MarketPhaseType, string> = {
      ice: '❄️ 冰点期：空仓观望，等待情绪反转',
      accumulation: '🏗️ 筑底期：轻仓试错，关注率先企稳板块',
      rising: '📈 上升期：积极参与，紧跟主线',
      climax: '⚡ 高潮期：持股为主，注意分化风险',
      distribution: '📊 出货期：控制仓位，快进快出',
      falling: '📉 退潮期：减仓防守，规避高位股',
    }

    let suggestion = suggestions[phase] || suggestions.accumulation

    // 添加情绪提示
    const emotionPhase = normalizeEmotionPhase(emotion.phase)
    if (emotionPhase === '冰点') {
      suggestion += ' ⚠️ 情绪冰点，谨慎操作'
    } else if (emotionPhase === '高潮') {
      suggestion += ' 🔥 情绪亢奋，注意风险'
    }

    // 添加主线建议
    if (mainLines.length > 0) {
      suggestion += ` 主线：${mainLines
        .slice(0, 3)
        .map((t) => t.themeName)
        .join('、')}`
    }

    // 添加强势板块
    if (strongThemes.length > 0 && phase === 'rising') {
      suggestion += `，关注强势板块：${strongThemes[0].themeName}`
    }

    return suggestion
  }

  private getEmptyAnalysis(): RotationAnalysisCompat {
    return {
      timestamp: Date.now(),
      inflowThemes: [],
      outflowThemes: [],
      mainLines: [],
      strongThemes: [],
      quickRotation: [],
      rotationSpeed: 0,
      marketPhase: 'accumulation',
      summary: {
        mainLineCount: 0,
        inflowCount: 0,
        outflowCount: 0,
        strongCount: 0,
        topInflow: '无',
        topOutflow: '无',
        topStrength: '无',
        suggestion: '暂无数据',
      },
    }
  }

  /**
   * 强制分析（用于手动刷新）
   */
  forceAnalyze(): RotationAnalysisCompat {
    return this.analyzeAll()
  }

  /**
   * 获取最新分析
   */
  getLastAnalysis(): RotationAnalysisCompat | null {
    return this.lastAnalysis
  }

  /**
   * 销毁服务
   */
  destroy() {
    this.stopAutoAnalysis()
    this.lastAnalysis = null
  }
}

// 导出单例
export const rotationService = new RotationService()

if (typeof window !== 'undefined') {
  ;(window as any).rotationService = rotationService
}
