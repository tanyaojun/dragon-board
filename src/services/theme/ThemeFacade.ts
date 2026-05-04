import { dataLayer } from '@/services/DataLayer'
import { themeMapping } from '@/services/ThemeDataService'
import { buildThemeFactors } from './ThemeFactorEngine'
import { projectThemeStockExposures } from './ThemeStockProjector'
import type {
  ThemeExposureProjection,
  ThemeFactorSnapshot,
  ThemeSourceContext,
  ThemeStockExposure,
} from './types'

let lastFactors: ThemeFactorSnapshot[] = []
let lastExposureProjection: ThemeExposureProjection = {
  byCode: new Map(),
  byTheme: new Map(),
}

function buildStockThemesMap(): Map<string, string[]> {
  const result = new Map<string, string[]>()
  themeMapping.getAllThemes().forEach((theme) => {
    themeMapping.getThemeStocks(theme.id).forEach((code) => {
      if (!result.has(code)) result.set(code, [])
      result.get(code)!.push(theme.id)
    })
  })
  return result
}

export function buildCurrentThemeSourceContext(options?: {
  timestamp?: number
  snapshotId?: string
}): ThemeSourceContext {
  const themes = themeMapping.getAllThemes().map((theme) => ({
    id: theme.id,
    name: theme.name,
    zsCode: theme.zsCode,
  }))
  const themeStocks = new Map<string, string[]>()
  themes.forEach((theme) => {
    themeStocks.set(theme.id, themeMapping.getThemeStocks(theme.id))
  })

  const correlations = new Map<string, any>()
  themes.forEach((theme) => {
    const detail = dataLayer.getThemeCorrelation?.(theme.id)
    if (detail) correlations.set(theme.id, detail)
  })

  return {
    timestamp: options?.timestamp || Date.now(),
    snapshotId: options?.snapshotId,
    themes,
    themeStocks,
    stockThemes: buildStockThemesMap(),
    stocks: dataLayer.getStocks(),
    jxbkBlocks: dataLayer.getJxbkBlocksSorted?.() || [],
    rotationAnalysis: dataLayer.getCurrentRotation?.() || null,
    correlations,
  }
}

export function refreshThemeFactors(context: ThemeSourceContext = buildCurrentThemeSourceContext()): {
  factors: ThemeFactorSnapshot[]
  exposures: ThemeExposureProjection
} {
  lastFactors = buildThemeFactors(context)
  lastExposureProjection = projectThemeStockExposures(context, lastFactors)
  return {
    factors: lastFactors,
    exposures: lastExposureProjection,
  }
}

export function getThemeFactors(): ThemeFactorSnapshot[] {
  if (lastFactors.length === 0) {
    refreshThemeFactors()
  }
  return lastFactors
}

export function getStockExposures(code?: string): ThemeStockExposure[] | Map<string, ThemeStockExposure[]> {
  if (lastFactors.length === 0) {
    refreshThemeFactors()
  }
  if (code) return lastExposureProjection.byCode.get(code) || []
  return lastExposureProjection.byCode
}

export function getThemeExposureProjection(): ThemeExposureProjection {
  if (lastFactors.length === 0) {
    refreshThemeFactors()
  }
  return lastExposureProjection
}

export function toHotThemeCompat(factor: ThemeFactorSnapshot) {
  const heatLevel =
    factor.heatScore >= 80 ? '热门' : factor.heatScore >= 60 ? '活跃' : factor.heatScore >= 40 ? '温' : factor.heatScore >= 20 ? '冷' : '冰'
  return {
    id: factor.themeId,
    name: factor.themeName,
    rank: factor.rank,
    heatScore: factor.heatScore,
    heatIcon: factor.heatScore >= 80 ? '🔥' : factor.heatScore >= 60 ? '⚡' : factor.heatScore >= 40 ? '🌟' : '❄️',
    heatColor: factor.heatScore >= 80 ? '#ff4757' : factor.heatScore >= 60 ? '#f39c12' : '#3498db',
    heatLevel,
    stockCount: factor.stockCount,
    ztCount: factor.ztCount,
    leaderCount: factor.leaderCount,
    momentum: factor.momentumScore,
    trend: factor.persistenceScore,
    acceleration: Math.max(0, factor.momentumScore - factor.crowdingRisk),
    correlation: factor.correlationScore / 100,
    strength: factor.strength || factor.heatScore,
    mainNetInflow: factor.netInflow,
    rotationState: factor.rotationState,
    qualityFlags: factor.qualityFlags,
    lastUpdate: factor.timestamp,
  }
}

export function toStockThemeCompat(exposure: ThemeStockExposure) {
  return {
    id: exposure.themeId,
    name: exposure.themeName,
    source: exposure.source,
    heatScore: exposure.themeScore,
    heatLevel:
      exposure.themeScore >= 80 ? '热门' : exposure.themeScore >= 60 ? '活跃' : exposure.themeScore >= 40 ? '温' : exposure.themeScore >= 20 ? '冷' : '冰',
    correlation: exposure.roleScore / 100,
    exposureWeight: exposure.exposureWeight,
    role: exposure.role,
    roleScore: exposure.roleScore,
    themeContribution: exposure.themeContribution,
    riskPenalty: exposure.riskPenalty,
    reasons: exposure.reasons,
  }
}

export const themeFacade = {
  buildCurrentThemeSourceContext,
  refreshThemeFactors,
  getThemeFactors,
  getStockExposures,
  getThemeExposureProjection,
  toHotThemeCompat,
  toStockThemeCompat,
}
