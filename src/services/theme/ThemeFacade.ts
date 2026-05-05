import { dataLayer } from '@/services/DataLayer'
import { themeMapping } from '@/services/ThemeDataService'
import type { RotationAnalysis } from '@/types/core'
import type { JxbkBlockData, JxbkStockData } from '@/types'
import { buildThemeRotationSummary } from './ThemeRotationEngine'
import { themeRuntimeStore } from './ThemeRuntimeStore'
import { jxbkThemeFeed } from './JxbkThemeFeed'
import { refreshRuntime, themeInputSignature } from './ThemeRuntimeCoordinator'
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
  const result = refreshRuntime({
    source: 'themeFacade',
    context,
    emitAlerts: false,
  } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })
  applyRuntimeResult(context, result)
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

export function refreshThemeFacadeState(options: ThemeRefreshOptions & {
  context?: ThemeSourceContext
} = {}) {
  const context =
    options.context ||
    buildCurrentThemeSourceContext({
      timestamp: options.timestamp,
      snapshotId: options.snapshotId,
    })
  const result = refreshRuntime({
    ...options,
    source: options.source || 'themeFacade',
    context,
  } as ThemeRefreshOptions & { source: string; context: ThemeSourceContext })
  applyRuntimeResult(context, result)

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
  const result = await refreshRuntime({
    ...options,
    source: options.source || 'ui',
    forceJxbk: !options.skipJxbkRefresh,
  })
  const nextContext = buildCurrentThemeSourceContext({
    timestamp: result.timestamp,
    snapshotId: options.snapshotId,
  })
  applyRuntimeResult(nextContext, result)
  return result
}

export function getJxbkBlocksCompat(limit?: number): JxbkBlockData[] {
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

export const refreshRuntimeState = refreshRuntime

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

export function getHotThemesCompat(limit: number = 10) {
  return getThemeFactors()
    .map(toHotThemeCompat)
    .sort((a, b) => b.heatScore - a.heatScore)
    .slice(0, limit)
}

export function getThemeStocksCompat(themeId: string, limit = 50) {
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
  const factor = getThemeFactors().find((item) => item.themeId === themeId)
  if (!factor) return null
  const hotTheme = toHotThemeCompat(factor)
  const stocks = getThemeStocksCompat(themeId, 50)
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
  getJxbkBlocksCompat,
  getJxbkLastUpdate,
  getThemeStockMapCompat,
  refreshJxbkAndFactors,
  getHotThemesCompat,
  getThemeDetailCompat,
  getThemeStocksCompat,
  toHotThemeCompat,
  toStockThemeCompat,
  runtimeStore: themeRuntimeStore,
}
