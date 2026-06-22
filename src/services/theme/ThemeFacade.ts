import { dataLayer } from '@/services/DataLayer'
import type { RotationAnalysis } from '@/types/core'
import { buildThemeRotationSummary } from './ThemeRotationEngine'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { themeRepository } from './ThemeRepository'
import { refreshRuntime } from './ThemeRuntimeCoordinator'
import { refreshResourceLocks } from '../refresh/RefreshResourceLocks'
import { deriveThemeHeatLevel } from './stockThemeMeta'
import { themeHeatFeed } from './ThemeHeatFeed'
import type {
  ThemeExposureProjection,
  ThemeFactorSnapshot,
  ThemeHeatApiFactor,
  ThemePanelSummary,
  ThemeRuntimeRefreshResult,
  ThemeRefreshOptions,
  ThemeSourceContext,
  ThemeStockExposure,
} from './types'

let lastFactors: ThemeFactorSnapshot[] = []
let lastExposureProjection: ThemeExposureProjection = {
  byCode: new Map(),
  byTheme: new Map(),
}
let lastRotationSummary: RotationAnalysis | null = null

function buildStockThemesMap(): Map<string, string[]> {
  const result = new Map<string, string[]>()
  themeRepository.getThemes().forEach((theme) => {
    themeRepository.getThemeStocks(theme.id).forEach((code) => {
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
  const themes = themeRepository.getThemes().map((theme) => ({
    id: theme.id,
    name: theme.name,
    zsCode: theme.zsCode,
  }))
  const themeStocks = new Map<string, string[]>()
  themes.forEach((theme) => {
    themeStocks.set(theme.id, themeRepository.getThemeStocks(theme.id))
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
    rotationAnalysis: dataLayer.getCurrentRotation?.() || null,
    correlations,
  }
}

export function refreshThemeFactors(context: ThemeSourceContext = buildCurrentThemeSourceContext()): {
  factors: ThemeFactorSnapshot[]
  exposures: ThemeExposureProjection
} {
  refreshRuntimeState({
    source: 'themeFacade',
    context,
    emitAlerts: false,
  } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })
  return {
    factors: lastFactors,
    exposures: lastExposureProjection,
  }
}

function applyRuntimeResult(result: ThemeRuntimeRefreshResult) {
  lastFactors = result.factors
  lastExposureProjection = result.exposures
  lastRotationSummary = result.rotationSummary
  const apiFactors = themeHeatFeed.getSnapshot()?.factors || []
  const apiById = new Map(apiFactors.map((item) => [item.themeId, item]))
  dataLayer.updateHotThemes(
    result.factors.map((factor) => toHotThemeSummary(factor, apiById.get(factor.themeId))),
  )
}

export function refreshRuntimeState(
  options: ThemeRefreshOptions & { context: ThemeSourceContext },
): ThemeRuntimeRefreshResult
export function refreshRuntimeState(options: ThemeRefreshOptions): Promise<ThemeRuntimeRefreshResult>
export function refreshRuntimeState(
  options: ThemeRefreshOptions,
): ThemeRuntimeRefreshResult | Promise<ThemeRuntimeRefreshResult> {
  const apply = (result: ThemeRuntimeRefreshResult) => {
    applyRuntimeResult(result)
    return result
  }

  if (options.context) {
    const result = refreshRuntime({
      ...options,
      source: options.source || 'themeFacade',
      context: options.context,
    } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })
    return apply(result)
  }

  return refreshResourceLocks
    .runExclusive('theme-runtime', () =>
      refreshRuntime({
        ...options,
        source: options.source || 'themeFacade',
      } as ThemeRefreshOptions & { source: string }),
    )
    .then((locked) => {
      const result = locked.value!
      return apply(result)
    })
}

export function refreshThemeFacadeState(options: ThemeRefreshOptions & {
  context?: ThemeSourceContext
} = {}) {
  const project = (result: ThemeRuntimeRefreshResult) => ({
    factors: lastFactors,
    exposures: lastExposureProjection,
    rotationSummary: lastRotationSummary,
    events: result.events,
    qualitySummary: result.qualitySummary,
    changedFields: result.changedFields,
    inputSignature: result.inputSignature,
  })
  if (options.context) {
    return project(refreshRuntimeState({
      ...options,
      source: options.source || 'themeFacade',
      context: options.context,
    } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext }))
  }
  return refreshRuntimeState({
    ...options,
    source: options.source || 'themeFacade',
  }).then(project)
}

export function getRuntimeSnapshot() {
  return themeRuntimeStore.getSnapshot()
}

export function getThemeFactors(): ThemeFactorSnapshot[] {
  return lastFactors
}

export function getStockExposures(code: string): ThemeStockExposure[]
export function getStockExposures(): Map<string, ThemeStockExposure[]>
export function getStockExposures(code?: string): ThemeStockExposure[] | Map<string, ThemeStockExposure[]> {
  if (code) return lastExposureProjection.byCode.get(code) || []
  return lastExposureProjection.byCode
}

export function getThemeExposureProjection(): ThemeExposureProjection {
  return lastExposureProjection
}

export function getRotationSummary(): RotationAnalysis | null {
  if (!lastRotationSummary && lastFactors.length > 0) {
    lastRotationSummary = buildThemeRotationSummary(lastFactors, {
      previous: dataLayer.getCurrentRotation?.() || null,
    })
  }
  return lastRotationSummary
}

export function getThemeEvents() {
  return themeRuntimeStore.getSnapshot().events
}

export function toHotThemeSummary(
  factor: ThemeFactorSnapshot,
  apiFactor?: ThemeHeatApiFactor,
): ThemePanelSummary & Record<string, unknown> {
  const heatLevel = deriveThemeHeatLevel(factor.heatScore)
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
    momentumScore: factor.momentumScore,
    breadthScore: factor.breadthScore,
    fundScore: apiFactor ? apiFactor.fundScore : factor.fundScore,
    leadershipScore: factor.leadershipScore,
    correlationScore: factor.correlationScore,
    crowdingRisk: factor.crowdingRisk,
    trend: factor.persistenceScore,
    acceleration: Math.max(0, factor.momentumScore - factor.crowdingRisk),
    correlation: factor.correlationScore / 100,
    strength: factor.strength || factor.heatScore,
    mainNetInflow: apiFactor ? apiFactor.netInflow : factor.netInflow,
    volumeRatio: Number.isFinite(factor.volumeRatio) ? factor.volumeRatio : null,
    degraded: apiFactor?.degraded ?? factor.qualityFlags.length > 0,
    rotationState: factor.rotationState,
    qualityFlags: factor.qualityFlags,
    lastUpdate: factor.timestamp,
  }
}

export function toStockTheme(exposure: ThemeStockExposure) {
  return {
    id: exposure.themeId,
    name: exposure.themeName,
    source: exposure.source,
    heatScore: exposure.themeScore,
    heatLevel: deriveThemeHeatLevel(exposure.themeScore),
    correlation: exposure.roleScore / 100,
    exposureWeight: exposure.exposureWeight,
    role: exposure.role,
    roleScore: exposure.roleScore,
    themeContribution: exposure.themeContribution,
    riskPenalty: exposure.riskPenalty,
    reasons: exposure.reasons,
  }
}

export function getHotThemes(limit: number = 10) {
  const apiById = new Map((themeHeatFeed.getSnapshot()?.factors || []).map((item) => [item.themeId, item]))
  return getThemeFactors()
    .map((factor) => toHotThemeSummary(factor, apiById.get(factor.themeId)))
    .sort((a, b) => b.heatScore - a.heatScore)
    .slice(0, limit)
}

export function getThemeSummaries(limit: number = 20): ThemePanelSummary[] {
  return getHotThemes(limit)
}

export function getThemeSummary(themeId: string): ThemePanelSummary | null {
  return getThemeSummaries(Number.MAX_SAFE_INTEGER).find((theme) => theme.id === themeId) || null
}

export function getThemeLastUpdate(): number | null {
  return themeHeatFeed.getSnapshot()?.computedAt || lastFactors[0]?.timestamp || null
}

export function getThemeFeedState(): {
  stale: boolean
  lastError: string | null
  factorVersion: string | null
} {
  const snapshot = themeHeatFeed.getSnapshot()
  return {
    stale: snapshot?.stale || false,
    lastError: snapshot?.lastError || null,
    factorVersion: snapshot?.factorVersion || null,
  }
}

export function getThemeStocks(themeId: string, limit = 50) {
  const exposures = getThemeExposureProjection().byTheme.get(themeId) || []
  return {
    total: exposures.length,
    page: 1,
    limit,
    totalPages: Math.max(1, Math.ceil(exposures.length / limit)),
    stocks: exposures.slice(0, limit).map((exposure) => {
      const stock = dataLayer.getStock(exposure.code) as any
      return {
        code: exposure.code,
        name: stock?.name || '',
        price: stock?.price || 0,
        change: stock?.change || 0,
        turnover: stock?.turnover || 0,
        turnoverRate: stock?.turnoverRate || 0,
        continuousDays: stock?.continuousDays || 0,
        isZT: Boolean(stock?.isZT),
        lianbanStr: stock?.lianban || '',
        fengdan: stock?.fengdan || 0,
        maxFengdan: stock?.maxFengdan || 0,
        isSectorLeader: exposure.role === 'leader',
        speed: stock?.speed || 0,
        volumeRatio: stock?.volumeRatio || 0,
        mainNetInflow: stock?.mainNetInflow || 0,
        leadTimes: stock?.leadTimes || 0,
        leadStatus: stock?.leadStatus || '',
        bigMoney300: stock?.bigMoney300 || 0,
        popularity: stock?.popularity || 0,
        popularityChange: stock?.popularityChange || 0,
        institutionBuy: stock?.institutionBuy || 0,
        mainBuy: stock?.mainBuy || 0,
        mainSell: stock?.mainSell || 0,
        cirMV: stock?.cirMV || 0,
      }
    }),
  }
}

export function loadThemeStocks(themeId: string, options: { force?: boolean; limit?: number } = {}) {
  return themeHeatFeed.loadThemeStocks(themeId, options)
}

export function getThemeDetail(themeId: string) {
  const factor = getThemeFactors().find((item) => item.themeId === themeId)
  if (!factor) return null
  const hotTheme = toHotThemeSummary(factor)
  const stocks = getThemeStocks(themeId, 50)
  return {
    id: factor.themeId,
    name: factor.themeName,
    zsCode: '',
    aliases: [],
    heatScore: factor.heatScore,
    heatLevel: hotTheme.heatLevel,
    heatIcon: hotTheme.heatIcon,
    heatColor: hotTheme.heatColor,
    momentum: factor.momentumScore,
    trend: factor.persistenceScore,
    acceleration: hotTheme.acceleration,
    correlation: factor.correlationScore / 100,
    relatedThemes: factor.relatedThemeIds.map((id) => ({ id, name: id, correlation: 0 })),
    stats: {
      stockCount: factor.stockCount,
      ztCount: factor.ztCount,
      leaderCount: factor.leaderCount,
    },
    stocks: stocks.stocks,
    history: [],
    lastUpdate: factor.timestamp,
    leaders: stocks.stocks
      .filter((stock: any) => stock.isSectorLeader)
      .map((stock: any) => ({
        code: stock.code,
        name: stock.name,
        level: stock.leadStatus,
        change: stock.change,
        continuousDays: stock.continuousDays,
        score: factor.leadershipScore,
      })),
  }
}

export const themeFacade = {
  buildCurrentThemeSourceContext,
  refresh: refreshThemeFacadeState,
  refreshThemeFacadeState,
  refreshThemeFactors,
  refreshRuntime: refreshRuntimeState,
  getThemeFactors,
  getStockExposures,
  getThemeExposureProjection,
  getRotationSummary,
  getThemeEvents,
  getRuntimeSnapshot,
  getHotThemes,
  getThemeSummaries,
  getThemeSummary,
  getThemeLastUpdate,
  getThemeFeedState,
  getThemeDetail,
  getThemeStocks,
  loadThemeStocks,
  toHotThemeSummary,
  toStockTheme,
  runtimeStore: themeRuntimeStore,
}
