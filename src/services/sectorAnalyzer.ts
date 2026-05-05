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
import { themeMapping } from './ThemeDataService'
import { apiService } from './apiService'
import { themeFacade } from './theme/ThemeFacade'

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
  sectorStocksCache: {} as Record<
    string,
    {
      stocks: JxbkStockData[]
      loaded: boolean
      loading: boolean
      loadTime: number
    }
  >,
  topBlocksLoaded: false,
}

function heatLevel(score: number) {
  if (score >= 80) return { level: '热门', icon: '🔥', color: '#ff4757' }
  if (score >= 60) return { level: '活跃', icon: '⚡', color: '#f39c12' }
  if (score >= 40) return { level: '温', icon: '🌟', color: '#3498db' }
  if (score >= 20) return { level: '冷', icon: '❄️', color: '#7f8c8d' }
  return { level: '冰', icon: '🧊', color: '#2c3e50' }
}

function buildThemeBase() {
  const byCode = new Map<string, any[]>()
  const byId = new Map<string, any>()
  themeMapping.getAllThemes().forEach((theme) => {
    byId.set(theme.id, {
      id: theme.id,
      name: theme.name,
      zsCode: theme.zsCode || '',
      aliases: [],
    })
    themeMapping.getThemeStocks(theme.id).forEach((code) => {
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
  themeMapping.getAllThemes().forEach((theme) => {
    const stocks = themeMapping.getThemeStocks(theme.id)
    const level = heatLevel(0)
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
  const stockTags = (themeMapping as any).stockTagsMap || new Map()
  const stockReasons = (themeMapping as any).stockReasonsMap || new Map()

  for (const theme of themeMapping.getAllThemes()) {
    for (const code of themeMapping.getThemeStocks(theme.id)) {
      const tags = stockTags.get(code) || []
      const reason = stockReasons.get(code) || ''
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
    await themeMapping.waitForLoaded()
    await syncTagsAndReasonsToDataLayer()
  } catch (error) {
    console.warn('[SectorAnalyzer] 初始化标签数据失败:', error)
  }
}

export async function init(): Promise<() => void> {
  if (state.initialized) return () => {}

  await themeMapping.waitForLoaded()
  initializeThemeInfo()
  const base = buildThemeBase()
  dataLayer.updateThemeBase({
    ...base,
    lastUpdate: themeMapping.getLastUpdateTime() || new Date().toISOString(),
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
  dataLayer.updateHotThemes(themeFacade.getHotThemesCompat(CONFIG.HOT_THEMES_LIMIT))
  return result
}

export async function loadSectorStocks(
  sectorCode: string,
  sectorName: string,
  forceRefresh: boolean = false,
): Promise<JxbkStockData[]> {
  const cacheKey = `${sectorCode}_${sectorName}`

  if (!forceRefresh && state.sectorStocksCache[cacheKey]?.loaded) {
    const cached = state.sectorStocksCache[cacheKey]
    if (Date.now() - cached.loadTime < CONFIG.CACHE_TTL) return cached.stocks
  }

  if (forceRefresh && state.sectorStocksCache[cacheKey]) delete state.sectorStocksCache[cacheKey]

  if (state.sectorStocksCache[cacheKey]?.loading) {
    return new Promise((resolve) => {
      const check = setInterval(() => {
        if (state.sectorStocksCache[cacheKey]?.loaded) {
          clearInterval(check)
          resolve(state.sectorStocksCache[cacheKey].stocks)
        }
      }, 100)
    })
  }

  state.sectorStocksCache[cacheKey] = {
    stocks: [],
    loaded: false,
    loading: true,
    loadTime: Date.now(),
  }

  try {
    const data = await apiService.getBlockStockList(sectorCode, { type: 6, st: 80 })
    if (data?.response?.data && Array.isArray(data.response.data)) {
      const stocks = data.response.data.map((item: any) => {
        const d = item[100] || []
        return {
          code: item[1],
          name: item[2],
          leadStatus: item[6] || '',
          blocks: d[0] ? d[0].split('、') : [],
          price: parseFloat(d[1]) || 0,
          change: parseFloat(d[2]) || 0,
          speed: parseFloat(d[3]) || 0,
          volumeRatio: parseFloat(d[4]) || 0,
          mainNetInflow: parseFloat(d[6]) || 0,
          mainBuy: parseFloat(d[7]) || 0,
          mainSell: parseFloat(d[8]) || 0,
          institutionBuy: parseFloat(d[14]) || 0,
          lianban: d[18] || '',
          fengdan: parseFloat(d[21]) || 0,
          maxFengdan: parseFloat(d[22]) || 0,
          cirMV: parseFloat(d[29]) || 0,
          leadTimes: parseInt(d[40]) || 0,
          bigMoney300: parseFloat(d[50]) || 0,
          popularity: parseInt(d[58]) || 0,
          popularityChange: parseInt(d[59]) || 0,
        } as JxbkStockData
      })
      state.sectorStocksCache[cacheKey] = {
        stocks,
        loaded: true,
        loading: false,
        loadTime: Date.now(),
      }
      dataLayer.updateJxbkStocks(stocks)
      await themeFacade.refreshRuntime({
        source: 'sectorAnalyzer',
        context: themeFacade.buildCurrentThemeSourceContext(),
        emitAlerts: false,
      })
      return stocks
    }
  } catch (error) {
    console.error(`[SectorAnalyzer] 加载板块 ${sectorCode} 个股数据失败:`, error)
  }

  state.sectorStocksCache[cacheKey].loading = false
  return []
}

export async function preloadTopSectors(limit: number = CONFIG.PRELOAD_COUNT) {
  const blocks = themeFacade.getJxbkBlocksCompat(limit)
  for (const block of blocks.slice(0, limit)) {
    const cacheKey = `${block.code}_${block.name}`
    if (!state.sectorStocksCache[cacheKey]?.loaded) {
      await loadSectorStocks(block.code, block.name)
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
  }
  state.topBlocksLoaded = blocks.length > 0
}

export async function updateFullThemeMapping(): Promise<{ success: boolean; message: string }> {
  if (state.destroyed) return { success: false, message: '题材分析器已销毁' }

  try {
    const base = buildThemeBase()
    dataLayer.updateThemeBase({
      ...base,
      lastUpdate: themeMapping.getLastUpdateTime() || new Date().toISOString(),
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
  const compat = themeFacade.getHotThemesCompat(limit) as HotTheme[]
  if (compat.length > 0) return compat
  return (dataLayer.getHotThemes() as HotTheme[]).slice(0, limit)
}

export async function getThemeDetail(
  themeName: string,
  options?: { force?: boolean },
): Promise<ThemeDetail | null> {
  const theme = themeMapping.getAllThemes().find((item) => item.name === themeName || item.id === themeName)
  if (options?.force && theme) {
    await loadSectorStocks(theme.id, theme.name)
  }
  const compat = themeFacade.getThemeDetailCompat(theme?.id || themeName) as ThemeDetail | null
  if (compat) return compat

  const level = heatLevel(0)
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
          stockCount: themeMapping.getThemeStocks(theme.id).length,
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
  const stockCodes = themeMapping.getThemeStocks(themeId)
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
    themeMapping.getStockThemes(leader.code).forEach((id) => {
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

  async forceRefresh(): Promise<void> {
    if (state.destroyed) return
    await themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      forceJxbk: true,
      syncStocks: true,
      emitAlerts: false,
    })
  },

  async forceRefreshJxbk(): Promise<void> {
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

  destroy: () => {
    state.destroyed = true
    state.initialized = false
  },

  getStats: () => {
    const mappingStats = themeMapping.getStats()
    return {
      totalThemes: themeMapping.getAllThemes().length,
      mappedStocks: mappingStats.stockCount,
      hotThemes: dataLayer.getHotThemes().length,
      cachedSectors: Object.keys(state.sectorStocksCache).length,
      lastUpdate: mappingStats.lastUpdate,
      version: '7.0.0',
    }
  },

  clearCache: () => {
    state.sectorStocksCache = {}
    state.topBlocksLoaded = false
  },

  debug: {
    getState: () => ({ ...state }),
    getJxbkBlocks: () => themeFacade.getJxbkBlocksCompat(),
  },

  VERSION: '7.0.0',
}

if (typeof window !== 'undefined') {
  ;(window as any).sectorAnalyzer = sectorAnalyzer
}

export default sectorAnalyzer
