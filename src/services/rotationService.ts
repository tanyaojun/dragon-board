// src/services/rotationService.ts
// Legacy adapter: 轮动事实来源统一为 ThemeRuntimeCoordinator/themeFacade。

import { dataLayer } from './DataLayer'
import { themeCorrelationAnalyzer } from './ThemeCorrelationAnalyzer'
import { themeFacade } from './theme/ThemeFacade'
import type { RotationAnalysis, ThemeRotationStatus } from '../types/core'
import { ROTATION_CONFIG } from '../config/constants'
import { refreshScheduler } from './refresh/RefreshTaskRuntime'

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

function emptyAnalysis(): RotationAnalysisCompat {
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

class RotationService {
  private lastAnalysis: RotationAnalysisCompat | null = null

  constructor() {
    this.startAutoAnalysis()
  }

  startAutoAnalysis(interval: number = ROTATION_CONFIG.ANALYSIS_INTERVAL) {
    if (!ROTATION_CONFIG.ENABLED) return
    refreshScheduler.registerRunner('theme.runtime', () => {
      this.analyzeAll()
    })
    refreshScheduler.startTask('theme.runtime', interval)
  }

  stopAutoAnalysis() {
    refreshScheduler.stopTask('theme.runtime')
  }

  analyzeAll(): RotationAnalysisCompat {
    const result = themeFacade.refreshRuntime({
      source: 'rotationService',
      context: themeFacade.buildCurrentThemeSourceContext(),
      emitAlerts: false,
    })
    const analysis = (result.rotationSummary as RotationAnalysisCompat | null) || emptyAnalysis()
    dataLayer.updateRotationAnalysis?.(analysis)
    this.lastAnalysis = analysis
    this.saveHotThemesToLocalStorage([
      ...analysis.mainLines,
      ...analysis.inflowThemes,
      ...analysis.outflowThemes,
    ])
    this.scheduleCorrelationForMainLines(analysis.mainLines)
    return analysis
  }

  private scheduleCorrelationForMainLines(mainLines: ThemeRotationStatus[]) {
    if (!mainLines.length) return
    setTimeout(() => {
      for (const mainLine of mainLines.slice(0, 3)) {
        themeCorrelationAnalyzer
          .analyzeThemeCorrelation(mainLine.themeId, mainLine.themeName, { force: false })
          .catch((error) => console.warn('联动分析失败:', error))
      }
    }, 100)
  }

  private saveHotThemesToLocalStorage(flows: ThemeRotationStatus[]) {
    if (typeof localStorage === 'undefined') return
    try {
      const today = new Date().toISOString().split('T')[0]
      const historyDates = JSON.parse(localStorage.getItem('hot_themes_history') || '[]')
      const top10Themes = flows.slice(0, 10).map((flow) => ({
        themeId: flow.themeId,
        themeName: flow.themeName,
        rank: flow.rank,
        strength: flow.strengthScore,
        netInflow: flow.netInflow,
        ztCount: flow.ztCount,
        persistentDays: flow.persistentDays || 1,
        timestamp: Date.now(),
      }))

      localStorage.setItem(`hot_themes_${today}`, JSON.stringify(top10Themes))
      if (!historyDates.includes(today)) {
        historyDates.push(today)
        if (historyDates.length > 30) {
          const oldestDate = historyDates.shift()
          if (oldestDate) localStorage.removeItem(`hot_themes_${oldestDate}`)
        }
        localStorage.setItem('hot_themes_history', JSON.stringify(historyDates))
      }
      localStorage.setItem('hot_themes_last_saved', today)
    } catch (error) {
      console.warn('[RotationService] 保存到 localStorage 失败:', error)
    }
  }

  forceAnalyze(): RotationAnalysisCompat {
    return this.analyzeAll()
  }

  getLastAnalysis(): RotationAnalysisCompat | null {
    return this.lastAnalysis
  }

  destroy() {
    this.stopAutoAnalysis()
    this.lastAnalysis = null
  }
}

export const rotationService = new RotationService()

if (typeof window !== 'undefined') {
  ;(window as any).rotationService = rotationService
}

export default rotationService
