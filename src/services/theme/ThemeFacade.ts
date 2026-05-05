import { dataLayer } from '@/services/DataLayer'
import type { RotationAnalysis } from '@/types/core'
import type { JxbkBlockData, JxbkStockData } from '@/types'
import { buildThemeRotationSummary } from './ThemeRotationEngine'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { jxbkThemeFeed } from './JxbkThemeFeed'
import { themeRepository } from './ThemeRepository'
import { refreshRuntime, themeInputSignature } from './ThemeRuntimeCoordinator'
import { deriveThemeHeatLevel } from './stockThemeMeta'
import type {
  ThemeExposureProjection,
  ThemeFactorSnapshot,
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
let lastSourceContext: ThemeSourceContext | null = null
let lastSourceSignature = ''
const JXBK_CONTEXT_TTL = 5 * 60 * 1000

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
    jxbkBlocks: dataLayer.getJxbkBlocksSorted?.() || [],
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

function applyRuntimeResult(context: ThemeSourceContext, result: ThemeRuntimeRefreshResult) {
  lastFactors = result.factors
  lastExposureProjection = result.exposures
  lastRotationSummary = result.rotationSummary
  lastSourceContext = context
  lastSourceSignature = result.inputSignature
}

function buildContextForRuntimeResult(options: ThemeRefreshOptions, result: ThemeRuntimeRefreshResult) {
  return buildCurrentThemeSourceContext({
    timestamp: result.timestamp || options.timestamp,
    snapshotId: options.snapshotId,
  })
}

export function refreshRuntimeState(
  options: ThemeRefreshOptions & { context: ThemeSourceContext },
): ThemeRuntimeRefreshResult
export function refreshRuntimeState(options: ThemeRefreshOptions): Promise<ThemeRuntimeRefreshResult>
export function refreshRuntimeState(
  options: ThemeRefreshOptions,
): ThemeRuntimeRefreshResult | Promise<ThemeRuntimeRefreshResult> {
  const apply = (result: ThemeRuntimeRefreshResult, context: ThemeSourceContext) => {
    applyRuntimeResult(context, result)
    return result
  }

  if (options.context) {
    const result = refreshRuntime({
      ...options,
      source: options.source || 'themeFacade',
      context: options.context,
    } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })
    return apply(result, options.context)
  }

  const result = refreshRuntime({
    ...options,
    source: options.source || 'themeFacade',
  } as ThemeRefreshOptions & { source: string })

  if (result instanceof Promise) {
    return result.then((resolved) => apply(resolved, buildContextForRuntimeResult(options, resolved)))
  }
  return apply(result, buildContextForRuntimeResult(options, result))
}

export function refreshThemeFacadeState(options: ThemeRefreshOptions & {
  context?: ThemeSourceContext
} = {}) {
  const context =
    options.context ||
    buildCurrentThemeSourceContext({
      timestamp: options.timestamp,
      snapshotId: options.snapshotId,
    })
  const result = refreshRuntimeState({
    ...options,
    source: options.source || 'themeFacade',
    context,
  } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })

  return {
    factors: lastFactors,
    exposures: lastExposureProjection,
    rotationSummary: lastRotationSummary,
    events: result.events,
    qualitySummary: result.qualitySummary,
    changedFields: result.changedFields,
    inputSignature: result.inputSignature,
  }
}

export async function refreshJxbkAndFactors(options: ThemeRefreshOptions & {
  context?: ThemeSourceContext
} = {}) {
  if (!options.skipJxbkRefresh && options.context?.jxbkBlocks?.length) {
    jxbkThemeFeed.updateBlocks(options.context.jxbkBlocks)
  }
  const context = options.context
  if (context) {
    return refreshThemeFacadeState({
      ...options,
      source: options.source || 'ui',
      context,
    })
  }
  const result = await refreshRuntimeState({
    ...options,
    source: options.source || 'ui',
    forceJxbk: !options.skipJxbkRefresh,
  })
  return result
}

export function getJxbkBlocksCompat(limit?: number): JxbkBlockData[] {
  return getJxbkBlocks(limit)
}

export function getJxbkBlocks(limit?: number): JxbkBlockData[] {
  const now = Date.now()
  const contextFresh =
    Boolean(lastSourceContext?.jxbkBlocks?.length) &&
    Boolean(lastSourceContext?.timestamp) &&
    now - Number(lastSourceContext?.timestamp) <= JXBK_CONTEXT_TTL
  const blocks = contextFresh && lastSourceContext
    ? lastSourceContext.jxbkBlocks
    : jxbkThemeFeed.getBlocks(limit)
  const ordered = [...(blocks || [])]
  return typeof limit === 'number' ? ordered.slice(0, Math.max(0, limit)) : ordered
}

export function getJxbkLastUpdate(): number | null {
  if (lastSourceContext?.timestamp) return lastSourceContext.timestamp
  const state = (dataLayer as any).state
  return state?.theme?.jxbk?.lastUpdate || null
}

export function getThemeStockMapCompat(): Record<string, JxbkStockData> {
  return getThemeStockMap()
}

export function getThemeStockMap(): Record<string, JxbkStockData> {
  const stockMap = jxbkThemeFeed.getStockMap()
  return Object.fromEntries(
    Object.entries(stockMap).map(([code, stock]) => [
      code,
      {
        ...stock,
        blocks: [...(stock.blocks || [])],
      },
    ]),
  )
}

export function getRuntimeSnapshot() {
  return themeRuntimeStore.getSnapshot()
}

export function getThemeFactors(): ThemeFactorSnapshot[] {
  if (lastFactors.length === 0) {
    refreshThemeFactors()
  }
  return lastFactors
}

export function getStockExposures(code: string): ThemeStockExposure[]
export function getStockExposures(): Map<string, ThemeStockExposure[]>
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

export function toHotThemeCompat(factor: ThemeFactorSnapshot) {
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

export function getHotThemesCompat(limit: number = 10) {
  return getHotThemes(limit)
}

export function getHotThemes(limit: number = 10) {
  return getThemeFactors()
    .map(toHotThemeCompat)
    .sort((a, b) => b.heatScore - a.heatScore)
    .slice(0, limit)
}

export function getThemeStocksCompat(themeId: string, limit = 50) {
  return getThemeStocks(themeId, limit)
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

export function getThemeDetailCompat(themeId: string) {
  return getThemeDetail(themeId)
}

export function getThemeDetail(themeId: string) {
  const factor = getThemeFactors().find((item) => item.themeId === themeId)
  if (!factor) return null
  const hotTheme = toHotThemeCompat(factor)
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
  getJxbkBlocks,
  getJxbkBlocksCompat,
  getJxbkLastUpdate,
  getThemeStockMap,
  getThemeStockMapCompat,
  refreshJxbkAndFactors,
  getHotThemes,
  getHotThemesCompat,
  getThemeDetail,
  getThemeDetailCompat,
  getThemeStocks,
  getThemeStocksCompat,
  toHotThemeCompat,
  toStockThemeCompat,
  runtimeStore: themeRuntimeStore,
}
