import { debugLog } from '@/utils/logger'
// src/services/sectorAnalyzer.ts
// 版本: 6.0.0

import type {
  Stock,
  ThemeInfo,
  LeaderInfo,
  JxbkBlockData,
  JxbkStockData,
  HotTheme,
  ThemeStock,
  ThemeDetail,
  ThemeHeatResult,
} from '../types'

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

import { SECTOR_CONFIG, ALERT_THRESHOLDS, ALERT_TYPES, ALERT_LEVELS } from '../config/constants'
import { dataLayer } from './DataLayer'
import { themeMapping } from './ThemeDataService'
import { apiService } from './apiService'
import { alertService } from './alertService'
import {
  buildStockThemeSignature,
  resolvePrimaryStockTheme,
  sortStockThemes,
} from './theme/stockThemeMeta'
import { themeFacade } from './theme/ThemeFacade'
import { StockUtils } from '../utils/common'

// ========== 配置常量 ==========
const CONFIG = {
  ...SECTOR_CONFIG,
  HOT_THEMES_LIMIT: 10,
  MAX_THEMES_PER_STOCK: 5,
  JXBK_BLOCK_LIMIT: 10,
  CACHE_TTL: 5 * 60 * 1000,
  PRELOAD_COUNT: 10,
}

// ========== 工具函数 ==========
const Utils = {
  normalizeStockCode(code: string): string {
    if (!code) return ''
    return String(code).replace(/[^\d]/g, '').padStart(6, '0')
  },

  getHeatLevel(score: number): { level: string; icon: string; color: string } {
    if (score >= 80) return { level: '热门', icon: '🔥', color: '#ff4757' }
    if (score >= 60) return { level: '活跃', icon: '⚡', color: '#f39c12' }
    if (score >= 40) return { level: '温', icon: '🌟', color: '#3498db' }
    if (score >= 20) return { level: '冷', icon: '❄️', color: '#7f8c8d' }
    return { level: '冰', icon: '🧊', color: '#2c3e50' }
  },

  log(...args: any[]) {
    if (CONFIG.DEBUG) debugLog('[SectorAnalyzer]', ...args)
  },

  warn(...args: any[]) {
    console.warn('[SectorAnalyzer]', ...args)
  },

  error(...args: any[]) {
    console.error('[SectorAnalyzer]', ...args)
  },

  formatMoney(value: number): string {
    const absValue = Math.abs(value)
    if (absValue >= 100000000) {
      return (value / 100000000).toFixed(2) + '亿'
    }
    if (absValue >= 10000) {
      return (value / 10000).toFixed(2) + '万'
    }
    return value.toString()
  },
}

// ========== 题材热度计算器（简化版） ==========
/**
 * @deprecated V4 fallback only. Theme heat authority lives in `src/services/theme/ThemeFactorEngine`.
 */
class ThemeHeatCalculator {
  /**
   * 计算题材热度（只使用 jxbk 强度，去掉情绪和龙头影响）
   */
  calculateThemeHeat(themeId: string, themeName?: string): ThemeHeatResult {
    const stockCodes = themeMapping.getThemeStocks(themeId)
    const stocks = stockCodes.map((code) => dataLayer.getStock(code)).filter(Boolean) as Stock[]
    const theme = themeMapping.getTheme(themeId)
    const jxbkBlock = findJxbkBlockByThemeName(theme?.name || themeName)
    const jxbkScore = this.calculateJxbkScore(jxbkBlock)

    if (stocks.length === 0 && jxbkScore === 0) {
      return this.getEmptyResult(themeId, themeName)
    }

    // 1. 基础分（板块规模）
    const baseScore = this.calculateBaseScore(stocks.length)

    // 2. 涨停贡献分
    const ztScore = this.calculateZtScore(stocks)

    // 3. 资金贡献分（从 jxbk 获取）
    const moneyScore = this.calculateMoneyScore(themeName)

    // 4. 联动性加成
    const correlation = this.calculateCorrelation(stocks)
    const correlationBonus = 1 + correlation * 0.3

    const stockScore = this.normalizeScore((baseScore + ztScore + moneyScore) * correlationBonus)

    // JXBK 是全市场板块强度，热榜成分是本地确认信号；优先用全市场强度，避免未入热榜股票导致热度全为 0。
    const normalizedScore = Math.max(jxbkScore, stockScore)

    // 确定热度等级
    const heatLevel = Utils.getHeatLevel(normalizedScore)

    const result: ThemeHeatResult = {
      themeId,
      themeName: theme?.name || themeName || '',
      heatScore: normalizedScore,
      heatLevel: heatLevel.level,
      heatIcon: heatLevel.icon,
      heatColor: heatLevel.color,
      correlation,
      stats: {
        stockCount: stocks.length,
        ztCount: stocks.filter((s) => {
          const change = s.change || 0
          const code = s.code || ''
          const name = s.name || ''
          return StockUtils.isLimitUp(change, code, name)
        }).length,
        leaderCount: 0,
      },
      components: {
        baseScore,
        ztScore,
        moneyScore: Math.max(moneyScore, jxbkScore),
        correlationBonus,
      },
    }

    return result
  }

  private normalizeScore(rawScore: number): number {
    const MAX_SCORE = 20000
    let score = Math.min(100, (rawScore / MAX_SCORE) * 100)
    score = Math.max(0, Math.min(100, score))
    return Math.round(score)
  }

  private calculateBaseScore(stockCount: number): number {
    let score = stockCount * 10
    if (stockCount < 20) score *= 1.2
    else if (stockCount > 100) score *= 0.8
    return Math.round(score)
  }

  private calculateZtScore(stocks: Stock[]): number {
    let score = 0
    stocks.forEach((stock) => {
      const change = stock.change || 0
      const code = stock.code || ''
      const name = stock.name || ''
      if (StockUtils.isLimitUp(change, code, name)) {
        let ztPoints = 1000
        if (stock.continuousDays && stock.continuousDays > 1) {
          ztPoints += stock.continuousDays * 200
        }
        score += ztPoints
      }
    })
    return Math.round(score)
  }

  private calculateMoneyScore(themeName?: string): number {
    if (!themeName) return 0

    const jxbkBlocks = dataLayer.getJxbkBlocksSorted()
    const block = jxbkBlocks.find((b: any) => b.name === themeName)
    if (!block?.mainNetInflow) return 0

    const inflowInHundredMillion = Math.abs(block.mainNetInflow) / 100000000
    return Math.round(inflowInHundredMillion * 200)
  }

  private calculateJxbkScore(block?: JxbkBlockData | null): number {
    if (!block) return 0

    let score = 0
    const strength = Number(block.strength) || 0
    const ztCount = Number(block.ztCount) || 0
    const volumeRatio = Number(block.volumeRatio) || 0
    const netInflow = Number(block.mainNetInflow) || 0

    if (strength >= 4000) score += 40
    else if (strength >= 3000) score += 30
    else if (strength >= 2000) score += 20
    else if (strength >= 1000) score += 10
    else if (strength > 0) score += 5

    if (ztCount >= 10) score += 30
    else if (ztCount >= 5) score += 25
    else if (ztCount >= 3) score += 20
    else if (ztCount >= 1) score += 15

    if (volumeRatio >= 2.5) score += 15
    else if (volumeRatio >= 1.5) score += 10
    else if (volumeRatio >= 0.8) score += 5

    if (netInflow > 100000000) score += 15
    else if (netInflow > 50000000) score += 12
    else if (netInflow > 10000000) score += 8
    else if (netInflow > 0) score += 5

    return Math.min(100, Math.round(score))
  }

  private calculateCorrelation(stocks: Stock[]): number {
    if (stocks.length < 2) return 0

    const changes = stocks.map((s) => Math.sign(s.change || 0)).filter((c) => c !== 0)
    if (changes.length < 2) return 0

    const positive = changes.filter((c) => c > 0).length
    const negative = changes.filter((c) => c < 0).length
    const directionScore = Math.max(positive, negative) / changes.length

    const values = stocks.map((s) => Math.abs(s.change || 0)).filter((v) => v > 0)
    if (values.length < 2) return directionScore

    const avg = values.reduce((a, b) => a + b, 0) / values.length
    const variance = values.reduce((a, b) => a + Math.pow(b - avg, 2), 0) / values.length
    const cv = Math.sqrt(variance) / avg
    const magnitudeScore = Math.max(0, 1 - Math.min(cv, 1))

    return directionScore * 0.7 + magnitudeScore * 0.3
  }

  private getEmptyResult(themeId: string, themeName?: string): ThemeHeatResult {
    return {
      themeId,
      themeName: themeName || '',
      heatScore: 0,
      heatLevel: '冰',
      heatIcon: '🧊',
      heatColor: '#2c3e50',
      correlation: 0,
      stats: { stockCount: 0, ztCount: 0, leaderCount: 0 },
      components: {
        baseScore: 0,
        ztScore: 0,
        moneyScore: 0,
        correlationBonus: 1,
      },
    }
  }
}

// ========== 联动分析引擎 ==========
class CorrelationEngine {
  /**
   * 计算题材间的联动性
   * @param themeId 当前题材ID
   * @param stockCodes 题材下的股票代码列表
   * @returns 相关题材列表（按相关性降序）
   */
  findRelatedThemes(
    themeId: string,
    stockCodes: string[],
  ): Array<{ id: string; name: string; correlation: number }> {
    // 获取题材下的股票详情
    const stocks = stockCodes
      .map((code) => dataLayer.getStock(code))
      .filter((s): s is Stock => s !== null && s !== undefined)

    if (stocks.length === 0) return []

    // 统计其他题材的共现情况
    const themeStats = new Map<
      string,
      {
        count: number // 共现股票数量
        totalChange: number // 累计涨跌幅（用于强度）
        totalVolume: number // 累计成交量（用于活跃度）
        name: string
      }
    >()

    stocks.forEach((stock) => {
      const stockChange = Math.abs(stock.change || 0)
      const stockVolume = stock.volume || 0

      stock.themes?.forEach((theme: { id: string; name: string }) => {
        // 排除当前题材
        if (String(theme.id) === String(themeId)) return

        const themeKey = String(theme.id)

        if (!themeStats.has(themeKey)) {
          themeStats.set(themeKey, {
            count: 0,
            totalChange: 0,
            totalVolume: 0,
            name: theme.name,
          })
        }

        const stats = themeStats.get(themeKey)!
        stats.count++
        stats.totalChange += stockChange
        stats.totalVolume += stockVolume
      })
    })

    if (themeStats.size === 0) return []

    // 计算各题材的相关性得分
    const results = Array.from(themeStats.entries()).map(([id, stats]) => {
      // 1. 共现比例 (0-1)
      const cooccurrence = stats.count / stocks.length

      // 2. 涨跌幅强度 (归一化到 0-1，最大10%)
      const avgChange = stats.totalChange / stats.count
      const changeStrength = Math.min(1, avgChange / 10)

      // 3. 成交量活跃度 (归一化到 0-1)
      const avgVolume = stats.totalVolume / stats.count
      const volumeStrength = Math.min(1, avgVolume / 10000000) // 1000万手为基准

      // 4. 综合相关性 = 共现比例 * 0.5 + 涨跌幅强度 * 0.3 + 成交量活跃度 * 0.2
      const correlation = cooccurrence * 0.5 + changeStrength * 0.3 + volumeStrength * 0.2

      return {
        id,
        name: stats.name,
        correlation: Math.round(correlation * 100) / 100,
      }
    })

    // 过滤相关性低于0.15的，排序后取前5个
    return results
      .filter((r) => r.correlation > 0.15)
      .sort((a, b) => b.correlation - a.correlation)
      .slice(0, 5)
  }
}

// ========== 状态管理 ==========
const state = {
  themeInfo: {} as Record<string, ThemeInfo>,
  correlationEngine: new CorrelationEngine(),

  initialized: false,
  jxbkTimer: null as ReturnType<typeof setInterval> | null,
  destroyed: false,

  jxbkBlocks: [] as JxbkBlockData[],
  jxbkBlockMap: {} as Record<string, JxbkBlockData>,
  previousBlocks: {} as Record<string, JxbkBlockData>,

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

const heatCalculator = new ThemeHeatCalculator()

function findJxbkBlockByThemeName(themeName?: string): JxbkBlockData | null {
  if (!themeName || state.jxbkBlocks.length === 0) return null

  const nameToCodeMap = (state as any).jxbkNameToCodeMap || {}
  const normalizedName = themeName.trim()
  const candidateNames = [
    normalizedName,
    normalizedName.replace(/概念$/, ''),
    normalizedName.replace(/板块$/, ''),
  ].filter(Boolean)

  for (const name of candidateNames) {
    const blockCode = nameToCodeMap[name]
    if (blockCode && state.jxbkBlockMap[blockCode]) {
      return state.jxbkBlockMap[blockCode]
    }
  }

  return (
    state.jxbkBlocks.find(
      (block) =>
        block.name === normalizedName ||
        block.name.replace(/概念$/, '') === normalizedName ||
        normalizedName.replace(/概念$/, '') === block.name,
    ) || null
  )
}

// ========== 初始化 ==========
export async function init(): Promise<() => void> {
  if (state.initialized) return () => {}

  await themeMapping.waitForLoaded()
  await updateFullThemeMapping()
  initializeThemeInfo()
  state.initialized = true

  await waitForStocksReady()
  await fetchJxbkData()
  updateThemeHeat()
  await initTagsAndReasons()

  setTimeout(() => {
    if (!state.destroyed) {
      preloadTopSectors(CONFIG.PRELOAD_COUNT)
    }
  }, 2000)

  startJxbkTimer()

  return () => {
    stopTimers()
    state.destroyed = true
    state.initialized = false
  }
}

function initializeThemeInfo() {
  const allThemes = themeMapping.getAllThemes()

  allThemes.forEach((theme) => {
    const stocks = themeMapping.getThemeStocks(theme.id)
    const stockCodes = themeMapping.getThemeStocks(theme.id)
    const relatedThemes = state.correlationEngine.findRelatedThemes(theme.id, stockCodes)

    state.themeInfo[theme.id] = {
      id: theme.id,
      name: theme.name,
      heatScore: 0,
      heatLevel: '冷',
      heatIcon: '🧊',
      heatColor: '#2c3e50',
      leaders: [],
      history: [],
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
      relatedThemes,
    }
  })
}

function waitForStocksReady(timeout = 10000): Promise<void> {
  return new Promise((resolve) => {
    if (dataLayer.getStocks().length) return resolve()

    let resolved = false
    const unsub = dataLayer.subscribe('merged.stocks', () => {
      if (!resolved) {
        resolved = true
        unsub?.()
        resolve()
      }
    })

    setTimeout(() => {
      if (!resolved) {
        resolved = true
        unsub?.()
        resolve()
      }
    }, timeout)
  })
}

// ========== jxbk 数据获取 ==========
async function fetchJxbkData() {
  try {
    debugLog('[SectorAnalyzer] 开始获取 JXBK 数据...')

    const data = await apiService.getHotBlockList({ st: 20 }, { force: true })

    if (!data?.list || !Array.isArray(data.list)) {
      console.warn('[SectorAnalyzer] JXBK 数据格式异常')
      return
    }

    const blocks: JxbkBlockData[] = []
    const blockMap: Record<string, JxbkBlockData> = {}
    const nameToCodeMap: Record<string, string> = {} // ✅ 新增：名称到代码的映射

    data.list.forEach((item: any[]) => {
      const blockCode = String(item[0])
      const blockName = item[1]

      if (blockName.includes('ST') || blockName.includes('*ST')) {
        return
      }

      const block: JxbkBlockData = {
        code: blockCode,
        name: blockName,
        strength: item[2] || 0,
        change: item[3] || 0,
        mainNetInflow: item[6] || 0,
        bigMoney300: item[12] || 0,
        institutionBuy: item[14] || 0,
        volumeRatio: item[9] || 0,
        ztCount: 0,
      }
      blocks.push(block)
      blockMap[blockCode] = block

      // ✅ 建立名称映射：板块名称 → 板块代码
      nameToCodeMap[blockName] = blockCode

      // ✅ 同时建立去掉"概念"后缀的映射（如"机器人概念" → "机器人"）
      const shortName = blockName.replace(/概念$/, '')
      if (shortName !== blockName) {
        nameToCodeMap[shortName] = blockCode
      }
    })

    state.jxbkBlocks = blocks
    state.jxbkBlockMap = blockMap
    ;(state as any).jxbkNameToCodeMap = nameToCodeMap // ✅ 保存映射

    dataLayer.updateJxbkBlocks(blocks)

    debugLog(`[SectorAnalyzer] JXBK 数据加载成功: ${blocks.length} 个板块`)
    debugLog(`[SectorAnalyzer] 名称映射已建立: ${Object.keys(nameToCodeMap).length} 个条目`)
  } catch (error) {
    console.error('[SectorAnalyzer] 获取 JXBK 数据失败:', error)
    state.jxbkBlocks = []
    state.jxbkBlockMap = {}
  }
}

// ========== 懒加载板块个股数据 ==========
export async function loadSectorStocks(
  sectorCode: string,
  sectorName: string,
  forceRefresh: boolean = false,
): Promise<JxbkStockData[]> {
  const cacheKey = `${sectorCode}_${sectorName}`

  if (!forceRefresh && state.sectorStocksCache[cacheKey]?.loaded) {
    const cached = state.sectorStocksCache[cacheKey]
    if (Date.now() - cached.loadTime < CONFIG.CACHE_TTL) {
      return cached.stocks
    }
  }

  if (forceRefresh && state.sectorStocksCache[cacheKey]) {
    delete state.sectorStocksCache[cacheKey]
  }

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
        const change = parseFloat(d[2]) || 0

        return {
          code: item[1],
          name: item[2],
          leadStatus: item[6] || '',
          blocks: d[0] ? d[0].split('、') : [],
          price: parseFloat(d[1]) || 0,
          change: change,
          volumeRatio: parseFloat(d[4]) || 0,
          mainNetInflow: parseFloat(d[6]) || 0,
          mainBuy: parseFloat(d[7]) || 0,
          mainSell: parseFloat(d[8]) || 0,
          institutionBuy: parseFloat(d[14]) || 0,
          lianban: d[18] || '',
          fengdan: parseFloat(d[21]) || 0,
          maxFengdan: parseFloat(d[22]) || 0,
          totalMV: parseFloat(d[28]) || 0,
          cirMV: parseFloat(d[29]) || 0,
          leadTimes: parseInt(d[40]) || 0,
          bigMoney300: parseFloat(d[50]) || 0,
          popularity: parseInt(d[58]) || 0,
          popularityChange: parseInt(d[59]) || 0,
          speed: parseFloat(d[3]) || 0,
        }
      })

      state.sectorStocksCache[cacheKey] = {
        stocks,
        loaded: true,
        loading: false,
        loadTime: Date.now(),
      }

      updateSectorStocksToDataLayer(sectorName, stocks)
      updateBlocksZtCount()

      return stocks
    }
  } catch (error) {
    Utils.error(`加载板块 ${sectorCode} 个股数据失败:`, error)
    state.sectorStocksCache[cacheKey].loading = false
  }

  return []
}

// ========== 更新板块个股数据到 DataLayer ==========
function updateSectorStocksToDataLayer(sectorName: string, stocks: JxbkStockData[]) {
  const dataLayerState = (dataLayer as any).state
  if (!dataLayerState?.theme?.jxbk?.stockMap) {
    return
  }

  const stockMap = dataLayerState.theme.jxbk.stockMap || {}

  // 更新或添加股票数据
  stocks.forEach((stock) => {
    if (!stockMap[stock.code]) {
      stockMap[stock.code] = stock
    } else {
      Object.assign(stockMap[stock.code], stock)
    }
  })

  dataLayer.updateJxbkStocks(Object.values(stockMap))

  // ✅ 更新涨停扩展数据，但保留已有的 reason 和 tags
  const limitUpUpdates = stocks
    .filter((stock) => stock.lianban)
    .map((stock) => {
      const existing = dataLayer.getLimitUpData(stock.code)
      return {
        code: stock.code,
        lianbanStr: stock.lianban,
        fengdan: stock.fengdan,
        maxFengdan: stock.maxFengdan,
        leadStatus: stock.leadStatus,
        leadTimes: stock.leadTimes,
        // ✅ 保留已有的 reason 和 tags，不覆盖
        reason: existing?.reason || '',
        tags: existing?.tags || [],
        isNew: existing?.isNew || false,
        firstZtTime: existing?.firstZtTime || '',
        lastZtTime: existing?.lastZtTime || '',
      }
    })

  if (limitUpUpdates.length > 0) {
    dataLayer.updateLimitUpData(limitUpUpdates)
  }
}

// ========== 按需触发热度计算 ==========
export async function triggerHeatCalculation() {
  if (state.destroyed) return
  const result = await themeFacade.refreshRuntime({
    source: 'sectorAnalyzer',
    forceJxbk: true,
    syncStocks: true,
  })
  dataLayer.updateHotThemes(themeFacade.getHotThemesCompat(CONFIG.HOT_THEMES_LIMIT))
  return result
}

// ========== 预加载前N个板块 ==========
export async function preloadTopSectors(limit: number = CONFIG.PRELOAD_COUNT) {
  const topBlocks = state.jxbkBlocks.slice(0, limit)
  if (topBlocks.length === 0) return

  for (const block of topBlocks) {
    const cacheKey = `${block.code}_${block.name}`
    if (!state.sectorStocksCache[cacheKey]?.loaded) {
      await loadSectorStocks(block.code, block.name)
      await new Promise((resolve) => setTimeout(resolve, 100))
    }
  }
}

// ========== 更新板块涨停数 ==========
async function updateBlocksZtCount() {
  try {
    const allStocks = dataLayer.getStocks()
    const blockZtCount: Record<string, number> = {}

    // 遍历所有股票，统计每个板块的涨停数
    allStocks.forEach((stock) => {
      const change = stock.change || 0
      const code = stock.code || ''
      const name = stock.name || ''

      if (StockUtils.isLimitUp(change, code, name)) {
        // 获取股票的板块列表
        const jxbkStock = dataLayer.getJxbkStock(code)
        const blocks = jxbkStock?.blocks || []

        blocks.forEach((blockName: string) => {
          blockZtCount[blockName] = (blockZtCount[blockName] || 0) + 1
        })

        blocks.forEach((blockName: string) => {
          checkStockZtAlerts({ ...stock, blocks }, blockName)
        })
      }
    })

    const currentBlocks = dataLayer.getJxbkBlocksSorted() || []

    const updatedBlocks = currentBlocks.map((block) => ({
      ...block,
      ztCount: blockZtCount[block.name] || 0,
    }))

    dataLayer.updateJxbkBlocks(updatedBlocks)
    state.jxbkBlocks = updatedBlocks

    checkBlockAlerts(updatedBlocks)
  } catch (error) {
    if (CONFIG.DEBUG) {
      console.warn('[SectorAnalyzer] 更新涨停数失败:', error)
    }
  }
}

// ========== 获取前N个板块的个股数据 ==========
async function fetchJxbkStocksForTopBlocks() {
  const topBlocks = state.jxbkBlocks.slice(0, CONFIG.JXBK_BLOCK_LIMIT)

  const allStocks: JxbkStockData[] = []

  for (const block of topBlocks) {
    try {
      const data = await apiService.getBlockStockList(block.code, { type: 6, st: 80 })

      if (data?.response?.data && Array.isArray(data.response.data)) {
        const stocks = data.response.data.map((item: any) => {
          const d = item[100] || []
          const change = parseFloat(d[2]) || 0

          return {
            code: item[1],
            name: item[2],
            leadStatus: item[6] || '',
            blocks: d[0] ? d[0].split('、') : [],
            price: parseFloat(d[1]) || 0,
            change: change,
            volumeRatio: parseFloat(d[4]) || 0,
            mainNetInflow: parseFloat(d[6]) || 0,
            mainBuy: parseFloat(d[7]) || 0,
            mainSell: parseFloat(d[8]) || 0,
            institutionBuy: parseFloat(d[14]) || 0,
            lianban: d[18] || '',
            fengdan: parseFloat(d[21]) || 0,
            maxFengdan: parseFloat(d[22]) || 0,
            totalMV: parseFloat(d[28]) || 0,
            cirMV: parseFloat(d[29]) || 0,
            leadTimes: parseInt(d[40]) || 0,
            bigMoney300: parseFloat(d[50]) || 0,
            popularity: parseInt(d[58]) || 0,
            popularityChange: parseInt(d[59]) || 0,
            speed: parseFloat(d[3]) || 0,
          }
        })

        allStocks.push(...stocks)
        updateSectorStocksToDataLayer(block.name, stocks)
      }
      await new Promise((resolve) => setTimeout(resolve, 100))
    } catch (error) {
      Utils.error(`获取板块 ${block.code} 个股数据失败:`, error)
    }
  }

  if (allStocks.length > 0) {
    await updateBlocksZtCount()
  } else {
    Utils.warn('⚠️ 没有获取到任何个股数据')
  }
}

// ========== 预警检查函数 ==========
function checkBlockAlerts(currentBlocks: JxbkBlockData[]) {
  if (!currentBlocks.length) return

  currentBlocks.forEach((block) => {
    const prevBlock = state.previousBlocks[block.code]

    if (prevBlock && prevBlock.strength !== undefined) {
      const strengthChange = ((block.strength - prevBlock.strength) / prevBlock.strength) * 100

      if (strengthChange >= ALERT_THRESHOLDS.HEAT_CHANGE.SURGE) {
        alertService.sendAlert({
          type: 'strength_surge',
          level: ALERT_LEVELS.INFO,
          title: `📈 ${block.name} 强度飙升`,
          message: `板块强度上升 ${strengthChange.toFixed(1)}%`,
          themeId: block.code,
          themeName: block.name,
          snapshot: {
            strength: block.strength,
            prevStrength: prevBlock.strength,
            change: strengthChange,
          },
        })
      } else if (strengthChange <= ALERT_THRESHOLDS.HEAT_CHANGE.PLUNGE) {
        alertService.sendAlert({
          type: 'strength_plunge',
          level: ALERT_LEVELS.WARNING,
          title: `📉 ${block.name} 强度骤降`,
          message: `板块强度下降 ${Math.abs(strengthChange).toFixed(1)}%`,
          themeId: block.code,
          themeName: block.name,
          snapshot: {
            strength: block.strength,
            prevStrength: prevBlock.strength,
            change: strengthChange,
          },
        })
      }
    }

    state.previousBlocks[block.code] = { ...block }
  })
}

function checkStockZtAlerts(stock: any, blockName: string) {
  if (!stock || stock.change <= 9.5) return

  if (stock.leadStatus?.includes('龙')) {
    alertService.sendAlert({
      type: ALERT_TYPES.LEADER_EMERGE,
      level: ALERT_LEVELS.INFO,
      title: `👑 ${stock.name} 龙头涨停`,
      message: `${stock.leadStatus} 涨停 ${stock.change.toFixed(2)}%`,
      code: stock.code,
      name: stock.name,
      themeName: blockName,
      snapshot: {
        change: stock.change,
        lianban: stock.lianban,
        fengdan: stock.fengdan,
      },
    })
  }

  if (stock.lianban && (stock.lianban.includes('2板') || stock.lianban.includes('3板'))) {
    alertService.sendAlert({
      type: ALERT_TYPES.LEADER_EMERGE,
      level: ALERT_LEVELS.INFO,
      title: `📈 ${stock.name} ${stock.lianban}`,
      message: `${stock.name} 成功晋级 ${stock.lianban}`,
      code: stock.code,
      name: stock.name,
      themeName: blockName,
      snapshot: {
        change: stock.change,
        lianban: stock.lianban,
        fengdan: stock.fengdan,
      },
    })
  }
}

// ========== 实时热度和强度计算 ==========
function startJxbkTimer() {
  state.jxbkTimer = setInterval(
    async () => {
      await fetchJxbkData()
      updateThemeHeat()
      // ✅ jxbk 数据更新后，同步题材到股票
      const updatedCount = syncThemesToStocks()
      if (CONFIG.DEBUG && updatedCount > 0) {
        debugLog(`[SectorAnalyzer] jxbk定时同步题材: ${updatedCount}只股票更新`)
      }
    },
    10 * 60 * 1000,
  )
}

function stopTimers() {
  if (state.jxbkTimer) {
    clearInterval(state.jxbkTimer)
    state.jxbkTimer = null
  }
}

function updateThemeHeat() {
  const allThemes = themeMapping.getAllThemes()
  const { factors } = themeFacade.refreshThemeFactors()

  const metricsUpdates: ReturnType<typeof calculateThemeMetrics>[] = []

  allThemes.forEach((theme) => {
    const metrics = calculateThemeMetrics(theme.id)
    if (metrics) {
      metricsUpdates.push(metrics)
    }
  })

  const hotThemes = generateHotThemes(metricsUpdates, factors)

  if (metricsUpdates.length > 0) {
    dataLayer.updateThemeMetrics(metricsUpdates)
  }

  dataLayer.updateHotThemes(hotThemes)

  const currentBlocks = dataLayer.getJxbkBlocksSorted() || []
  checkBlockAlerts(currentBlocks)
}

function calculateThemeMetrics(themeId: string) {
  const theme = themeMapping.getTheme(themeId)
  const factor = themeFacade.getThemeFactors().find((item) => item.themeId === themeId)
  if (factor) {
    return {
      themeId,
      heatScore: factor.heatScore,
      heatLevel:
        factor.heatScore >= 80
          ? '热门'
          : factor.heatScore >= 60
            ? '活跃'
            : factor.heatScore >= 40
              ? '温'
              : factor.heatScore >= 20
                ? '冷'
                : '冰',
      momentum: factor.momentumScore,
      trend: factor.persistenceScore,
      acceleration: Math.max(0, factor.momentumScore - factor.crowdingRisk),
      correlation: factor.correlationScore / 100,
      relatedThemes: state.correlationEngine.findRelatedThemes(
        themeId,
        themeMapping.getThemeStocks(themeId),
      ),
      stats: {
        stockCount: factor.stockCount,
        ztCount: factor.ztCount,
        leaderCount: factor.leaderCount,
      },
      jxbk: {
        strength: factor.strength,
        mainNetInflow: factor.netInflow,
        bigMoney300: 0,
        institutionBuy: 0,
        volumeRatio: factor.volumeRatio,
      },
      components: factor.components,
      qualityFlags: factor.qualityFlags,
      rotationState: factor.rotationState,
      lastUpdate: factor.timestamp,
    }
  }

  // Compatibility fallback for callers that read metrics before the theme facade has produced factors.
  const result = heatCalculator.calculateThemeHeat(themeId, theme?.name)

  const jxbkBlock = findJxbkBlockByThemeName(theme?.name)

  return {
    themeId,
    heatScore: result.heatScore,
    heatLevel: result.heatLevel,
    momentum: 0,
    trend: 0,
    acceleration: 0,
    correlation: result.correlation,
    relatedThemes: state.correlationEngine.findRelatedThemes(
      themeId,
      themeMapping.getThemeStocks(themeId),
    ),
    stats: result.stats,
    jxbk: jxbkBlock
      ? {
          strength: jxbkBlock.strength,
          mainNetInflow: jxbkBlock.mainNetInflow,
          bigMoney300: jxbkBlock.bigMoney300,
          institutionBuy: jxbkBlock.institutionBuy,
          volumeRatio: jxbkBlock.volumeRatio,
        }
      : {
          strength: 0,
          mainNetInflow: 0,
          bigMoney300: 0,
          institutionBuy: 0,
          volumeRatio: 0,
        },
    components: result.components,
    lastUpdate: Date.now(),
  }
}

/**
 * @deprecated V4 fallback only. New callers should use `themeFacade.getHotThemesCompat()`.
 */
function generateHotThemes(metricsUpdates: any[], factors: ReturnType<typeof themeFacade.getThemeFactors> = []) {
  if (factors.length > 0) {
    return factors
      .filter((factor) => !factor.themeName.includes('ST') && !factor.themeName.includes('*ST'))
      .slice(0, CONFIG.HOT_THEMES_LIMIT)
      .map((factor, index) => ({
        ...themeFacade.toHotThemeCompat(factor),
        rank: index + 1,
      }))
  }

  const candidates = metricsUpdates
    .map((metrics) => {
      const theme = themeMapping.getTheme(metrics.themeId)
      if (!theme) return null

      if (theme.name.includes('ST') || theme.name.includes('*ST')) {
        return null
      }

      const heatLevel = Utils.getHeatLevel(metrics.heatScore)

      return {
        id: metrics.themeId,
        name: theme.name,
        heatScore: metrics.heatScore,
        heatIcon: heatLevel.icon,
        heatColor: heatLevel.color,
        heatLevel: heatLevel.level,
        stockCount: metrics.stats.stockCount,
        ztCount: metrics.stats.ztCount,
        leaderCount: metrics.stats.leaderCount,
        momentum: 0,
        trend: 0,
        acceleration: 0,
        correlation: metrics.correlation,
        strength: metrics.jxbk?.strength || 0,
        lastUpdate: metrics.lastUpdate,
      }
    })
    .filter((item): item is NonNullable<typeof item> => item !== null)
    .sort((a, b) => b.heatScore - a.heatScore)

  return candidates.slice(0, CONFIG.HOT_THEMES_LIMIT).map((t, i) => ({ ...t, rank: i + 1 }))
}

// ========== 全量更新 ==========
export async function updateFullThemeMapping(): Promise<{ success: boolean; message: string }> {
  if (state.destroyed) {
    return { success: false, message: '题材分析器已销毁' }
  }

  try {
    await fetchJxbkStocksForTopBlocks()
    updateThemeHeat()

    const allThemes = themeMapping.getAllThemes()
    const byCode = new Map<string, any[]>()
    const byId = new Map<string, any>()

    allThemes.forEach((theme) => {
      byId.set(theme.id, {
        id: theme.id,
        name: theme.name,
        zsCode: '',
        aliases: [],
      })

      const stocks = themeMapping.getThemeStocks(theme.id)
      stocks.forEach((code) => {
        if (!byCode.has(code)) {
          byCode.set(code, [])
        }
        byCode.get(code)!.push({
          id: theme.id,
          name: theme.name,
          zsCode: '',
        })
      })
    })

    dataLayer.updateThemeBase({
      byCode,
      byId,
      lastUpdate: themeMapping.getLastUpdateTime() || new Date().toISOString(),
    })

    const updatedCount = syncThemesToStocks()
    if (updatedCount > 0) {
      debugLog(`[SectorAnalyzer] 全量更新后同步题材: ${updatedCount}只股票更新`)
    }

    return { success: true, message: `${byId.size}个题材, ${byCode.size}只股票` }
  } catch (error) {
    const message = error instanceof Error ? error.message : '未知错误'
    Utils.error('❌ 全量更新失败:', error)
    return { success: false, message }
  }
}

// ========== 同步到股票 ==========
export function syncThemesToStocks(): number {
  const result = themeFacade.refreshRuntime({
    source: 'sectorAnalyzer',
    context: themeFacade.buildCurrentThemeSourceContext(),
    syncStocks: true,
    emitAlerts: false,
  })
  return result.syncedStockCount
}

/**
 * 同步标签和原因数据到 DataLayer
 */
async function syncTagsAndReasonsToDataLayer(): Promise<void> {
  const allThemes = themeMapping.getAllThemes()
  let totalTags = 0
  let totalReasons = 0

  const stockTagsUpdates: Array<{ code: string; tags: Array<{ Name: string }> }> = []
  const limitUpUpdates: Array<{
    code: string
    reason?: string
    tags?: Array<{ Name: string }>
  }> = []

  for (const theme of allThemes) {
    // 从 ThemeDataService 获取该题材下的股票标签和原因
    const stockTags = (themeMapping as any).stockTagsMap || new Map()
    const stockReasons = (themeMapping as any).stockReasonsMap || new Map()

    const stocks = themeMapping.getThemeStocks(theme.id)

    for (const code of stocks) {
      const tags = stockTags.get(code) || []
      const reason = stockReasons.get(code) || ''

      if (tags.length > 0) {
        stockTagsUpdates.push({
          code,
          tags: tags.map((t: { Name: string }) => ({ Name: t.Name })),
        })
        totalTags += tags.length
      }

      if (reason) {
        limitUpUpdates.push({
          code,
          reason: reason,
          tags: tags.length > 0 ? tags.map((t: { Name: string }) => ({ Name: t.Name })) : undefined,
        })
        totalReasons++
      }
    }
  }

  // 批量更新到 DataLayer
  if (stockTagsUpdates.length > 0) {
    dataLayer.updateStockTags(stockTagsUpdates)
  }

  if (limitUpUpdates.length > 0) {
    dataLayer.updateLimitUpData(limitUpUpdates)
  }

  // 触发合并
  dataLayer.updateStocks(dataLayer.getStocks())
}

/**
 * 初始化标签和原因数据（从已保存的题材数据中读取）
 */
async function initTagsAndReasons(): Promise<void> {
  try {
    // 确保题材数据已加载
    await themeMapping.waitForLoaded()

    // 从 ThemeDataService 同步到 DataLayer
    await syncTagsAndReasonsToDataLayer()
  } catch (error) {
    console.warn('[SectorAnalyzer] 初始化标签数据失败:', error)
  }
}

// ========== 公共API ==========
/**
 * 获取热门题材列表
 * @param limit 返回数量限制，默认10
 */
export function getHotThemes(limit: number = 10): HotTheme[] {
  const compat = themeFacade.getHotThemesCompat(limit) as HotTheme[]
  if (compat.length > 0) return compat
  const hotThemes = dataLayer.getHotThemes()
  return hotThemes.slice(0, limit) as HotTheme[]
}

/**
 * 获取题材详情
 * @param themeName 题材名称
 * @param options 选项，force 是否强制刷新
 */
export async function getThemeDetail(
  themeName: string,
  options?: { force?: boolean },
): Promise<ThemeDetail | null> {
  const allThemes = themeMapping.getAllThemes()
  const theme = allThemes.find((t) => t.name === themeName)
  if (!theme) return null

  if (options?.force) {
    await loadSectorStocks(theme.id, theme.name)
    themeFacade.refreshRuntime({
      source: 'sectorAnalyzer',
      context: themeFacade.buildCurrentThemeSourceContext(),
      emitAlerts: false,
    })
  }

  const compat = themeFacade.getThemeDetailCompat(theme.id) as ThemeDetail | null
  if (compat) return compat

  const metrics = dataLayer.getThemeMetrics(theme.id)
  const stocksResult = getThemeStocks(theme.id, { limit: 50 })

  // 获取题材下的龙头股
  const themeLeaders = state.themeInfo[theme.id]?.leaders || []

  // 使用现有的 getHeatLevel 方法
  const heatScore = metrics?.heatScore || 0
  const heatLevelInfo = Utils.getHeatLevel(heatScore)

  return {
    id: theme.id,
    name: theme.name,
    zsCode: theme.zsCode || '',
    aliases: [],
    heatScore: heatScore,
    heatLevel: heatLevelInfo.level,
    heatIcon: heatLevelInfo.icon,
    heatColor: heatLevelInfo.color,
    momentum: metrics?.momentum || 0,
    trend: metrics?.trend || 0,
    acceleration: metrics?.acceleration || 0,
    correlation: metrics?.correlation || 0,
    relatedThemes: metrics?.relatedThemes || [],
    stats: metrics?.stats || {
      stockCount: 0,
      ztCount: 0,
      leaderCount: 0,
    },
    stocks: stocksResult.stocks,
    history: state.themeInfo[theme.id]?.history || [],
    lastUpdate: metrics?.lastUpdate || null,
    leaders: themeLeaders,
  }
}

/**
 * 获取题材下的股票列表
 * @param themeId 题材ID
 * @param options 分页和排序选项
 */
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

  if (!stockCodes.length) {
    return { total: 0, page, limit, totalPages: 0, stocks: [] }
  }

  // ✅ 使用 reduce 代替 map + filter，避免类型问题
  const stocks: ThemeStock[] = stockCodes.reduce<ThemeStock[]>((acc, code) => {
    const stock = dataLayer.getStock(code)
    const jxbkStock = dataLayer.getJxbkStock(code)
    if (!stock) return acc

    const tags = dataLayer.getStockTags?.(code) || []
    const reason = dataLayer.getStockReason?.(code) || ''
    const isNew = dataLayer.getStockIsNew?.(code) || false
    const limitUpData = dataLayer.getLimitUpData?.(code)
    const legacyLeaderStock = stock as Stock & {
      isSectorLeader?: boolean
      leaderLevel?: string
    }

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
      isSectorLeader: legacyLeaderStock.isSectorLeader || false,
      leaderLevel: legacyLeaderStock.leaderLevel,
      tags: tags,
      reason: reason || stock.reason || '',
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

  // ✅ 排序
  stocks.sort((a, b) => {
    const aVal = (a[sortBy] as number) || 0
    const bVal = (b[sortBy] as number) || 0
    return sortDesc ? bVal - aVal : aVal - bVal
  })

  const total = stocks.length
  const totalPages = Math.ceil(total / limit)
  const start = (page - 1) * limit
  const paginated = stocks
    .slice(start, start + limit)
    .map((s, i) => ({ ...s, rank: start + i + 1 }))

  return { total, page, limit, totalPages, stocks: paginated }
}

export function syncLeadersToThemes(leaders: LeaderInfo[]) {
  if (!leaders?.length) return

  const themeLeaders: Record<string, LeaderInfo[]> = {}

  leaders.forEach((leader) => {
    const themeIds = themeMapping.getStockThemes(leader.code)
    themeIds.forEach((id) => {
      if (!themeLeaders[id]) themeLeaders[id] = []
      if (!themeLeaders[id].find((l) => l.code === leader.code)) {
        themeLeaders[id].push(leader)
      }
    })
  })

  Object.entries(themeLeaders).forEach(([id, ls]) => {
    if (state.themeInfo[id]) {
      state.themeInfo[id].leaders = ls.map((l) => ({
        code: l.code,
        name: l.name,
        level: l.levelName,
        change: l.change || 0,
        continuousDays: l.continuousDays || 0,
        score: l.score || 0,
      }))
    }
  })
}

// ========== 服务接口 ==========
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
    // Deprecated compatibility entrypoint. UI callers should prefer themeFacade.refreshJxbkAndFactors().
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
    stopTimers()
    state.destroyed = true
    state.initialized = false
  },

  getStats: () => {
    const mappingStats = themeMapping.getStats()
    return {
      totalThemes: themeMapping.getAllThemes().length,
      mappedStocks: themeMapping.getStats().stockCount,
      hotThemes: dataLayer.getHotThemes().length,
      cachedSectors: Object.keys(state.sectorStocksCache).length,
      lastUpdate: mappingStats.lastUpdate,
      version: '6.0.0',
    }
  },

  clearCache: () => {
    state.sectorStocksCache = {}
    state.topBlocksLoaded = false
    state.jxbkBlocks = []
    state.jxbkBlockMap = {}
  },

  debug: {
    getState: () => ({ ...state }),
    getJxbkBlocks: () => state.jxbkBlocks,
  },

  VERSION: '6.0.0',
}

if (typeof window !== 'undefined') {
  ;(window as any).sectorAnalyzer = sectorAnalyzer
}

export default sectorAnalyzer
