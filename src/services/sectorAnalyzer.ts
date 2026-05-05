import { debugLog } from '@/utils/logger'
// src/services/sectorAnalyzer.ts
// Legacy adapter: 题材事实来源统一为 src/services/theme/ThemeFacade。

import type {
  HotTheme,
  JxbkBlockData,
  JxbkStockData,
  LeaderInfo,
  ThemeDetail,
  ThemeInfo,
  ThemeStock,
} from '../types'
import { SECTOR_CONFIG } from '../config/constants'
import { dataLayer } from './DataLayer'
import { themeFacade } from './theme/ThemeFacade'
import { jxbkThemeFeed } from './theme/JxbkThemeFeed'
import { themeRepository } from './theme/ThemeRepository'
import { deriveThemeHeatMeta } from './theme/stockThemeMeta'

type SortableThemeStockKey = keyof Pick<
  ThemeStock,
  | 'change'
  | 'price'
  | 'turnover'
  | 'turnoverRate'
  | 'continuousDays'
  | 'fengdan'
  | 'maxFengdan'
  | 'volumeRatio'
  | 'popularity'
  | 'leadTimes'
  | 'bigMoney300'
  | 'speed'
  | 'mainNetInflow'
  | 'institutionBuy'
>

const CONFIG = {
  ...SECTOR_CONFIG,
  HOT_THEMES_LIMIT: 10,
  MAX_THEMES_PER_STOCK: 5,
  CACHE_TTL: 5 * 60 * 1000,
  PRELOAD_COUNT: 10,
}

const state = {
  themeInfo: {} as Record<string, ThemeInfo>,
  initialized: false,
  destroyed: false,
  topBlocksLoaded: false,
}

function buildThemeBase() {
  const byCode = new Map<string, any[]>()
  const byId = new Map<string, any>()
  themeRepository.getThemes().forEach((theme) => {
    byId.set(theme.id, {
      id: theme.id,
      name: theme.name,
      zsCode: theme.zsCode || '',
      aliases: [],
    })
    themeRepository.getThemeStocks(theme.id).forEach((code) => {
      if (!byCode.has(code)) byCode.set(code, [])
      byCode.get(code)!.push({
        id: theme.id,
        name: theme.name,
        zsCode: theme.zsCode || '',
      })
    })
  })
  return { byCode, byId }
}

function initializeThemeInfo() {
  themeRepository.getThemes().forEach((theme) => {
    const stocks = themeRepository.getThemeStocks(theme.id)
    const level = deriveThemeHeatMeta(0)
    state.themeInfo[theme.id] = {
      id: theme.id,
      name: theme.name,
      heatScore: 0,
      heatLevel: level.level,
      heatIcon: level.icon,
      heatColor: level.color,
      leaders: state.themeInfo[theme.id]?.leaders || [],
      history: state.themeInfo[theme.id]?.history || [],
      momentum: 0,
      trend: 0,
      acceleration: 0,
      lastUpdate: null,
      stats: {
        ztCount: 0,
        leaderCount: 0,
        stockCount: stocks.length,
      },
      correlation: 0,
      relatedThemes: [],
    }
  })
}

async function syncTagsAndReasonsToDataLayer(): Promise<void> {
  const stockTagsUpdates: Array<{ code: string; tags: Array<{ Name: string }> }> = []
  const limitUpUpdates: Array<{
    code: string
    reason?: string
    tags?: Array<{ Name: string }>
  }> = []
  for (const theme of themeRepository.getThemes()) {
    for (const code of themeRepository.getThemeStocks(theme.id)) {
      const tags = themeRepository.getStockTags(code)
      const reason = themeRepository.getStockReason(code)
      if (tags.length > 0) {
        stockTagsUpdates.push({
          code,
          tags: tags.map((tag: { Name: string }) => ({ Name: tag.Name })),
        })
      }
      if (reason) {
        limitUpUpdates.push({
          code,
          reason,
          tags: tags.length > 0 ? tags.map((tag: { Name: string }) => ({ Name: tag.Name })) : undefined,
        })
      }
    }
  }

  if (stockTagsUpdates.length > 0) dataLayer.updateStockTags(stockTagsUpdates)
  if (limitUpUpdates.length > 0) dataLayer.updateLimitUpData(limitUpUpdates)
  if (stockTagsUpdates.length > 0 || limitUpUpdates.length > 0) {
    dataLayer.updateStocks(dataLayer.getStocks())
  }
}

async function initTagsAndReasons(): Promise<void> {
  try {
    await themeRepository.loadThemeBase()
    await syncTagsAndReasonsToDataLayer()
  } catch (error) {
    console.warn('[SectorAnalyzer] 初始化标签数据失败:', error)
  }
}

export async function init(): Promise<() => void> {
  if (state.initialized) return () => {}

  await themeRepository.loadThemeBase()
  initializeThemeInfo()
  const base = buildThemeBase()
  dataLayer.updateThemeBase({
    ...base,
    lastUpdate: themeRepository.getThemeBaseStatus()?.lastUpdate || new Date().toISOString(),
  })
  await themeFacade.refreshRuntime({
    source: 'sectorAnalyzer',
    forceJxbk: true,
    syncStocks: true,
    emitAlerts: false,
  })
  await initTagsAndReasons()
  state.initialized = true

  setTimeout(() => {
    if (!state.destroyed) preloadTopSectors(CONFIG.PRELOAD_COUNT)
  }, 2000)

  return () => {
    state.destroyed = true
    state.initialized = false
  }
}

export async function triggerHeatCalculation() {
  if (state.destroyed) return
  const result = await themeFacade.refreshRuntime({
    source: 'sectorAnalyzer',
    forceJxbk: true,
    syncStocks: true,
    emitAlerts: false,
  })
  dataLayer.updateHotThemes(themeFacade.getHotThemes(CONFIG.HOT_THEMES_LIMIT))
  return result
}

export async function loadSectorStocks(
  sectorCode: string,
  sectorName: string,
  forceRefresh: boolean = false,
): Promise<JxbkStockData[]> {
  return jxbkThemeFeed.loadSectorStocks(sectorCode, sectorName, forceRefresh)
}

export async function preloadTopSectors(limit: number = CONFIG.PRELOAD_COUNT) {
  const blocks = themeFacade.getJxbkBlocks(limit)
  for (const block of blocks.slice(0, limit)) {
    await loadSectorStocks(block.code, block.name)
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  state.topBlocksLoaded = blocks.length > 0
}

export async function updateFullThemeMapping(): Promise<{ success: boolean; message: string }> {
  if (state.destroyed) return { success: false, message: '题材分析器已销毁' }

  try {
    const base = buildThemeBase()
    dataLayer.updateThemeBase({
      ...base,
      lastUpdate: themeRepository.getThemeBaseStatus()?.lastUpdate || new Date().toISOString(),
    })
    await themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      forceJxbk: true,
      syncStocks: true,
      emitAlerts: false,
    })
    return { success: true, message: `${base.byId.size}个题材, ${base.byCode.size}只股票` }
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    console.error('❌ 全量更新失败:', error)
    return { success: false, message }
  }
}

export function syncThemesToStocks(): number {
  const result = themeFacade.refreshRuntime({
    source: 'sectorAnalyzer',
    context: themeFacade.buildCurrentThemeSourceContext(),
    syncStocks: true,
    emitAlerts: false,
  })
  return result.syncedStockCount
}

export function getHotThemes(limit: number = 10): HotTheme[] {
  const compat = themeFacade.getHotThemes(limit) as HotTheme[]
  if (compat.length > 0) return compat
  return (dataLayer.getHotThemes() as HotTheme[]).slice(0, limit)
}

export async function getThemeDetail(
  themeName: string,
  options?: { force?: boolean },
): Promise<ThemeDetail | null> {
  const theme = themeRepository.getThemes().find((item) => item.name === themeName || item.id === themeName)
  if (options?.force && theme) {
    await loadSectorStocks(theme.id, theme.name)
  }
  const compat = themeFacade.getThemeDetail(theme?.id || themeName) as ThemeDetail | null
  if (compat) return compat

  const level = deriveThemeHeatMeta(0)
  return theme
    ? {
        id: theme.id,
        name: theme.name,
        zsCode: theme.zsCode || '',
        aliases: [],
        heatScore: 0,
        heatLevel: level.level,
        heatIcon: level.icon,
        heatColor: level.color,
        momentum: 0,
        trend: 0,
        acceleration: 0,
        correlation: 0,
        relatedThemes: [],
        stats: {
          stockCount: themeRepository.getThemeStocks(theme.id).length,
          ztCount: 0,
          leaderCount: state.themeInfo[theme.id]?.leaders?.length || 0,
        },
        stocks: getThemeStocks(theme.id, { limit: 50 }).stocks,
        history: state.themeInfo[theme.id]?.history || [],
        lastUpdate: null,
        leaders: state.themeInfo[theme.id]?.leaders || [],
      }
    : null
}

export function getThemeStocks(
  themeId: string,
  options: {
    limit?: number
    page?: number
    sortBy?: SortableThemeStockKey
    sortDesc?: boolean
  } = {},
): { total: number; page: number; limit: number; totalPages: number; stocks: ThemeStock[] } {
  const { limit = 200, page = 1, sortBy = 'change', sortDesc = true } = options
  const stockCodes = themeRepository.getThemeStocks(themeId)
  if (!stockCodes.length) return { total: 0, page, limit, totalPages: 0, stocks: [] }

  const stocks = stockCodes.reduce<ThemeStock[]>((acc, code) => {
    const stock = dataLayer.getStock(code)
    const jxbkStock = dataLayer.getJxbkStock(code)
    if (!stock) return acc
    const limitUpData = dataLayer.getLimitUpData?.(code)
    acc.push({
      code: stock.code,
      name: stock.name || '-',
      price: stock.price || 0,
      change: stock.change || 0,
      turnover: stock.turnover || 0,
      turnoverRate: stock.turnoverRate || 0,
      continuousDays: stock.continuousDays || 0,
      isZT: (stock.change || 0) > 9.5,
      lianbanStr: limitUpData?.lianbanStr || stock.lianbanStr || jxbkStock?.lianban || '',
      firstZtTime: limitUpData?.firstZtTime || stock.firstZtTime || '',
      lastZtTime: limitUpData?.lastZtTime || stock.lastZtTime || '',
      fengdan: limitUpData?.fengdan || stock.fengdan || jxbkStock?.fengdan || 0,
      maxFengdan: limitUpData?.maxFengdan || stock.maxFengdan || jxbkStock?.maxFengdan || 0,
      isSectorLeader: Boolean((stock as any).isSectorLeader),
      leaderLevel: (stock as any).leaderLevel,
      tags: dataLayer.getStockTags?.(code) || [],
      reason: dataLayer.getStockReason?.(code) || stock.reason || '',
      speed: jxbkStock?.speed || stock.speed || 0,
      volumeRatio: jxbkStock?.volumeRatio || stock.volumeRatio || 0,
      mainNetInflow: jxbkStock?.mainNetInflow || 0,
      leadTimes: jxbkStock?.leadTimes || stock.leadTimes || 0,
      leadStatus: jxbkStock?.leadStatus || stock.leadStatus || '',
      bigMoney300: jxbkStock?.bigMoney300 || stock.bigMoney300 || 0,
      popularity: jxbkStock?.popularity || stock.popularity || 0,
      popularityChange: jxbkStock?.popularityChange || stock.popularityChange || 0,
      institutionBuy: jxbkStock?.institutionBuy || stock.institutionBuy || 0,
      mainBuy: jxbkStock?.mainBuy || stock.mainBuy || 0,
      mainSell: jxbkStock?.mainSell || stock.mainSell || 0,
      cirMV: jxbkStock?.cirMV || stock.cirMV || 0,
    })
    return acc
  }, [])

  stocks.sort((a, b) => {
    const aVal = (a[sortBy] as number) || 0
    const bVal = (b[sortBy] as number) || 0
    return sortDesc ? bVal - aVal : aVal - bVal
  })

  const total = stocks.length
  const totalPages = Math.ceil(total / limit)
  const start = (page - 1) * limit
  return {
    total,
    page,
    limit,
    totalPages,
    stocks: stocks.slice(start, start + limit).map((stock, index) => ({
      ...stock,
      rank: start + index + 1,
    })),
  }
}

export function syncLeadersToThemes(leaders: LeaderInfo[]) {
  if (!leaders?.length) return
  const themeLeaders: Record<string, LeaderInfo[]> = {}
  leaders.forEach((leader) => {
    themeRepository.getStockThemes(leader.code).forEach((id) => {
      if (!themeLeaders[id]) themeLeaders[id] = []
      if (!themeLeaders[id].find((item) => item.code === leader.code)) themeLeaders[id].push(leader)
    })
  })

  Object.entries(themeLeaders).forEach(([id, items]) => {
    if (!state.themeInfo[id]) return
    state.themeInfo[id].leaders = items.map((leader) => ({
      code: leader.code,
      name: leader.name,
      level: leader.levelName,
      change: leader.change || 0,
      continuousDays: leader.continuousDays || 0,
      score: leader.score || 0,
    }))
  })
}

export const sectorAnalyzer = {
  init,
  syncThemesToStocks,
  getHotThemes,
  getThemeDetail,
  getThemeStocks,
  syncLeadersToThemes,
  updateFullThemeMapping,
  loadSectorStocks,
  preloadTopSectors,
  triggerHeatCalculation,

  async runUpdate(): Promise<void> {
    if (state.destroyed) return
    await themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      forceJxbk: true,
      syncStocks: true,
      emitAlerts: false,
    })
  },

  async syncData(): Promise<void> {
    if (state.destroyed) return
    await themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      syncStocks: true,
      emitAlerts: false,
    })
  },

  forceRefreshJxbk: async function () {
    if (state.destroyed) return
    await themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      forceJxbk: true,
      syncStocks: true,
      emitAlerts: false,
    })
  } as () => Promise<void>,

  destroy: () => {
    state.destroyed = true
    state.initialized = false
  },

  getStats: () => {
    const mappingStats = themeRepository.getThemeBaseStatus()
    return {
      totalThemes: themeRepository.getThemes().length,
      mappedStocks: mappingStats?.mappingCount || 0,
      hotThemes: dataLayer.getHotThemes().length,
      cachedSectors: jxbkThemeFeed.getSectorStockCacheStats().cachedSectors,
      lastUpdate: mappingStats?.lastUpdate || null,
      version: '11.0.0',
      themeBaseSource: 'sqlite',
    }
  },

  clearCache: () => {
    jxbkThemeFeed.clearSectorStockCache()
    state.topBlocksLoaded = false
  },

  debug: {
    getState: () => ({ ...state }),
    getJxbkBlocks: () => themeFacade.getJxbkBlocks(),
  },

  VERSION: '11.0.0',
}

if (typeof window !== 'undefined') {
  ;(window as any).sectorAnalyzer = sectorAnalyzer
}

export default sectorAnalyzer
