// src/services/DataLayer.ts

import { ref, reactive } from 'vue'
import type { BreathData, Depth10Book, L2Summary, TickTrade } from '../types'
import { ALERT_CONFIG } from '../config/constants'
import { applyRankTrendAnalysis } from './rankTrend/compat'
import type { RotationAnalysis, StockAlert, AlertStats } from '../types'
import type { AlertType } from '../types/core'
import type { DragonReviewResult } from './dragon/types'
import type { ThemeCorrelationDetail } from './ThemeCorrelationAnalyzer'
import {
  applyReviewProjectionToStock,
  buildReviewLeaderProjection,
  normalizeLeaderRole,
  stripLegacyLeaderFields,
} from './dragon/reviewProjection'
import type {
  DataState,
  JxbkBlockData,
  JxbkStockData,
  LimitUpExtData,
  MergedStock,
  StockExtData,
  ThemeMetrics,
} from '../types/data-layer'
import type {
  BigOrderItem,
  BigOrderStatistics,
  DenseOrderAlert,
  PeriodStatistics,
} from '../types/big-order'
import { shouldApplyMoneyFlowUpdate } from './moneyFlowSourcePriority'

/**
 * 数据存储层
 * 职责单一：存储数据、提供访问接口、版本管理
 */
class DataLayer {
  private readonly bigOrderData = new Map<
    string,
    {
      orders: BigOrderItem[]
      statistics: BigOrderStatistics | null
      periods: PeriodStatistics[]
      lastUpdate: number
    }
  >()
  private readonly denseOrderAlerts: DenseOrderAlert[] = []

  constructor() {}

  private state: DataState = reactive({
    raw: { stocks: [], platforms: {}, themes: [], fullMarket: [] },
    realtime: {
      quotes: new Map(),
      depth10: new Map(),
      recentTicks: new Map(),
      l2Summary: new Map(),
      lastUpdate: null,
    },
    merged: { stocks: [], themes: [] },

    // 龙头数据单独存储
    leader: {
      byCode: new Map(),
      byLevel: {},
      lastUpdate: null,
    },

    review: {
      result: null,
      marketCore: null,
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      battlefields: [],
      transitions: [],
      summaryLines: [],
      lastUpdate: null,
    },

    // ========== 题材数据  ==========
    theme: {
      base: {
        byCode: new Map(),
        byId: new Map(),
        lastUpdate: null,
      },
      metrics: {
        byTheme: new Map(),
        hotList: [],
        rotation: [],
        lastUpdate: null,
      },
      jxbk: {
        blocks: [],
        blockMap: {},
        stockMap: {},
        lastUpdate: null,
      },
      correlation: {
        byTheme: new Map(),
        lastUpdate: null,
      },
    },

    // 分析结果
    analysis: {
      breath: {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      },
      algorithm: {
        config: null,
        results: new Map(),
        lastUpdate: null,
      },
      // ✅ 添加 rotation
      rotation: {
        current: null,
        history: [],
        lastUpdate: null,
      },

      // 预警存储
      alerts: {
        items: [],
        stats: {
          total: 0,
          critical: 0,
          warning: 0,
          info: 0,
          byType: {} as Record<AlertType, number>,
          lastUpdate: 0,
        },
        lastUpdate: null,
      },
    },

    // ✅ 历史排名数据初始化
    rankHistory: {
      byCode: new Map(),
      lastUpdate: null,
      snapshotDate: null,
    },

    version: {
      stocks: 0,
      themes: 0,
      leaders: 0,
      review: 0,
      quotes: 0,
      platforms: 0,
      breath: 0,
      algorithm: 0,
      rotation: 0,
    },

    meta: {
      initialized: false,
      lastMergeTime: null,
      marketMode: 'hot',
    },
  })

  private subscribers = new Map<string, Set<(data: any) => void>>()
  private notifyTimer: ReturnType<typeof setTimeout> | null = null
  private pendingNotify = new Map<string, any>()

  // ========== 复盘兼容查询（只服务旧入口读取，不再产出龙头结论） ==========

  /**
   * 获取单个龙头信息
   */
  getLeaderByCode(code: string) {
    return this.state.leader.byCode.get(code) || null
  }

  /**
   * 按级别获取龙头
   */
  getLeadersByLevel(level: string) {
    const normalizedLevel = normalizeLeaderRole(level) || level
    return this.state.leader.byLevel[normalizedLevel] || []
  }

  /**
   * 获取所有龙头
   */
  getAllLeaders() {
    return Array.from(this.state.leader.byCode.values())
  }

  updateReviewData(result: DragonReviewResult) {
    const timestamp = Date.now()
    this.state.review = {
      result,
      marketCore: result.marketCore,
      trueLeaders: result.trueLeaders || [],
      heightBoard: result.heightBoard || [],
      attentionBoard: result.attentionBoard || [],
      pseudoLeaderGraveyard: result.pseudoLeaderGraveyard || [],
      battlefields: result.battlefields || [],
      transitions: result.transitions || [],
      summaryLines: result.summaryLines || [],
      lastUpdate: timestamp,
    }

    const { byCode, byLevel } = buildReviewLeaderProjection(result, timestamp)

    this.state.leader = {
      byCode,
      byLevel,
      lastUpdate: timestamp,
    }

    if (this.state.merged.stocks.length) {
      this.state.merged.stocks = this.state.merged.stocks.map((stock) =>
        applyReviewProjectionToStock(stock, byCode.get(stock.code) || null),
      )
      this.throttledNotify('merged.stocks', this.state.merged.stocks)
    }

    this.state.version.review = (this.state.version.review || 0) + 1
    this.state.version.leaders++
    this.throttledNotify('review.result', result)
    this.throttledNotify('version.review', this.state.version.review)
    this.throttledNotify('version.leaders', this.state.version.leaders)
  }

  getDragonReview(): DragonReviewResult | null {
    return this.state.review.result
  }

  getMarketCore() {
    return this.state.review.marketCore
  }

  getTrueLeaders() {
    return this.state.review.trueLeaders
  }

  getHeightBoard() {
    return this.state.review.heightBoard
  }

  getAttentionBoard() {
    return this.state.review.attentionBoard
  }

  getPseudoLeaderGraveyard() {
    return this.state.review.pseudoLeaderGraveyard
  }

  getReviewBattlefields() {
    return this.state.review.battlefields
  }

  getReviewTransitions() {
    return this.state.review.transitions
  }

  // ========== 题材数据管理 ==========
  /**
   * 更新基础题材映射（来自 ThemeDataService）
   */
  updateThemeBase(data: {
    byCode: Map<string, any[]>
    byId: Map<string, any>
    lastUpdate: string
  }) {
    this.state.theme.base.byCode = data.byCode
    this.state.theme.base.byId = data.byId
    this.state.theme.base.lastUpdate = data.lastUpdate
    this.state.version.themes++
  }

  /**
   * 更新股票对应的题材数据
   * @param updates  { code: string, themes: any[] }[]
   */
  updateStockThemes(
    updates: Array<{
      code: string
      themes: any[]
      mainTheme?: string
      themeHeat?: number
      themeLevel?: string
    }>,
  ) {
    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touchedMergedStocks = false

    updates.forEach(({ code, themes, mainTheme, themeHeat, themeLevel }) => {
      this.state.theme.base.byCode.set(code, themes)

      const stock = stockMap.get(code)
      if (stock) {
        stock.themes = themes
        stock.mainTheme = mainTheme || undefined
        stock.themeHeat = themeHeat ?? 0
        stock.themeLevel = themeLevel || '冷'
        stockMap.set(code, stock)
        touchedMergedStocks = true
      }
    })

    if (touchedMergedStocks) {
      this.state.merged.stocks = Array.from(stockMap.values())
      this.state.version.stocks++
    }

    this.state.version.themes++
  }

  /**
   * 更新热门题材列表
   */
  updateHotThemes(hotThemes: any[]) {
    this.state.theme.metrics.hotList = hotThemes
    this.state.theme.metrics.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新轮动数据
   */
  updateRotation(rotation: any[]) {
    this.state.theme.metrics.rotation = rotation
    this.state.theme.metrics.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新题材指标（包含 jxbk 数据）
   */
  updateThemeMetrics(
    updates: Array<{
      themeId: string
      heatScore: number
      heatLevel: string
      momentum: number
      trend: number
      acceleration: number
      correlation: number
      relatedThemes: any[]
      stats: { stockCount: number; ztCount: number; leaderCount: number }
      jxbk: {
        strength: number
        mainNetInflow: number
        bigMoney300: number
        institutionBuy: number
        volumeRatio: number
      }
    }>,
  ) {
    updates.forEach((update) => {
      this.state.theme.metrics.byTheme.set(update.themeId, {
        ...update,
        lastUpdate: Date.now(),
      })
    })

    this.state.version.themes++
  }

  /**
   * 获取题材指标
   */
  getThemeMetrics(themeId: string): ThemeMetrics | undefined {
    return this.state.theme.metrics.byTheme.get(themeId)
  }

  /**
   * 获取所有题材指标
   */
  getAllThemeMetrics(): Map<string, ThemeMetrics> {
    return this.state.theme.metrics.byTheme
  }

  /**
   * 获取股票的题材数据（从基础映射）
   */
  getStockThemes(code: string) {
    return this.state.theme.base.byCode.get(code) || []
  }

  /**
   * 获取题材详情（从基础映射）
   */
  getThemeById(id: string) {
    return this.state.theme.base.byId.get(id)
  }

  /**
   * 获取热门题材列表
   */
  getHotThemes() {
    return this.state.theme.metrics.hotList
  }

  /**
   * 获取题材轮动数据
   */
  getThemeRotation() {
    return this.state.theme.metrics.rotation
  }

  // ========== jxbk 数据管理 ==========

  /**
   * 更新 jxbk 板块数据
   */
  updateJxbkBlocks(blocks: JxbkBlockData[]) {
    const blockMap: Record<string, JxbkBlockData> = {}
    blocks.forEach((block) => {
      blockMap[block.code] = block
    })

    this.state.theme.jxbk.blocks = blocks
    this.state.theme.jxbk.blockMap = blockMap
    this.state.theme.jxbk.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新 jxbk 股票数据
   */
  updateJxbkStocks(stocks: JxbkStockData[]) {
    const stockMap: Record<string, JxbkStockData> = { ...this.state.theme.jxbk.stockMap }
    stocks.forEach((stock) => {
      stockMap[stock.code] = stock
    })

    this.state.theme.jxbk.stockMap = stockMap
    this.state.theme.jxbk.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 获取 jxbk 板块数据
   */
  getJxbkBlock(blockCode: string): JxbkBlockData | undefined {
    return this.state.theme.jxbk.blockMap[blockCode]
  }

  /**
   * 获取 jxbk 股票数据
   */
  getJxbkStock(stockCode: string): JxbkStockData | undefined {
    return this.state.theme.jxbk.stockMap[stockCode]
  }

  getJxbkStockMap(): Record<string, JxbkStockData> {
    return this.state.theme.jxbk.stockMap
  }

  /**
   * 获取所有 jxbk 板块（按强度排序）
   */
  getJxbkBlocksSorted(limit?: number): JxbkBlockData[] {
    const blocks = [...this.state.theme.jxbk.blocks]
    blocks.sort((a, b) => b.strength - a.strength)
    return limit ? blocks.slice(0, limit) : blocks
  }

  // ========== 题材个股联动管理 ==========
  updateThemeCorrelation(themeId: string, correlation: ThemeCorrelationDetail) {
    if (!this.state.theme.correlation) {
      this.state.theme.correlation = { byTheme: new Map(), lastUpdate: null }
    }
    this.state.theme.correlation.byTheme.set(themeId, correlation)
    this.state.theme.correlation.lastUpdate = Date.now()
    this.state.version.themes++
  }

  // 获取方法
  getThemeCorrelation(themeId: string): ThemeCorrelationDetail | undefined {
    return this.state.theme.correlation?.byTheme.get(themeId)
  }

  // ========== 股票数据管理 ==========
  /**
   * 更新股票数据 - 供 dataLoader 调用
   */
  updateStocks(data: any[]) {
    // 保存原始数据
    this.state.raw.stocks = data.map((s) => ({
      ...stripLegacyLeaderFields(s),
      timestamp: Date.now(),
    }))

    this.state.version.stocks++
  }

  /**
   * 获取合并后的股票数据（供UI使用）
   */
  getStocks(): MergedStock[] {
    return this.state.merged.stocks
  }

  getMergedStocks(): MergedStock[] {
    return this.getStocks()
  }

  /**
   * 获取单个股票
   */
  getStock(code: string): MergedStock | null {
    return this.state.merged.stocks.find((s) => s.code === code) || null
  }

  /**
   * 获取股票带版本信息
   */
  getStocksWithVersion() {
    return {
      stocks: this.state.merged.stocks,
      version: this.state.version.stocks,
    }
  }

  /**
   * 批量获取股票
   */
  getStocksByCodes(codes: string[]): MergedStock[] {
    return this.state.merged.stocks.filter((s) => codes.includes(s.code))
  }

  // ========== 批量更新股票扩展数据 ==========
  /**
   * 批量更新股票的扩展数据（涨速、量比、人气等）
   */
  updateStockExtData(updates: Array<Partial<StockExtData> & { code: string }>) {
    if (!updates.length) return

    const stockMap = new Map(this.state.merged.stocks.map((s) => [s.code, s]))

    updates.forEach((update) => {
      const stock = stockMap.get(update.code)
      if (stock) {
        Object.assign(stock, update)
        stockMap.set(update.code, stock)
      }
    })

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
  }

  // ========== 获取股票扩展字段方法 ==========

  getStockSpeed(code: string): number | undefined {
    return this.getStock(code)?.speed
  }

  getStockVolumeRatio(code: string): number | undefined {
    return this.getStock(code)?.volumeRatio
  }

  getStockLeadStatus(code: string): string | undefined {
    return this.getStock(code)?.leadStatus
  }

  getStockPopularity(code: string): number | undefined {
    return this.getStock(code)?.popularity
  }

  getStockFengdan(code: string): number | undefined {
    return this.getStock(code)?.fengdan
  }

  getStockInstitutionBuy(code: string): number | undefined {
    return this.getStock(code)?.institutionBuy
  }

  // ========== 平台数据管理 ==========

  updatePlatforms(data: Record<string, any>) {
    this.state.raw.platforms = data
    this.state.version.platforms++
    this.throttledNotify('raw.platforms', data)
  }

  getRawPlatforms() {
    return this.state.raw.platforms
  }

  getPlatformData(platform: string) {
    return this.state.raw.platforms[platform] || []
  }

  // ========== 原始题材数据 ==========

  updateRawThemes(data: any[]) {
    this.state.raw.themes = data
    this.state.version.themes++
    this.throttledNotify('raw.themes', data)
  }

  getRawThemes() {
    return this.state.raw.themes
  }

  // ========== 实时行情数据 ==========
  updateQuotesBatch(changes: any[]) {
    if (!changes?.length) return

    changes.forEach((change) => {
      if (!change?.code) return
      const existing = this.state.realtime.quotes.get(change.code) || {}
      const shouldApplyMoneyFlow = shouldApplyMoneyFlowUpdate(existing, change)
      const moneyFlowPatch = shouldApplyMoneyFlow
        ? {}
        : {
            zlje: existing.zlje,
            zljzb: existing.zljzb,
            cddje: existing.cddje,
            cddjzb: existing.cddjzb,
            moneyFlowSource: existing.moneyFlowSource,
            moneyFlowEstimated: existing.moneyFlowEstimated,
            capitalFlowSource: existing.capitalFlowSource,
            capitalFlowConfidence: existing.capitalFlowConfidence,
          }
      this.state.realtime.quotes.set(change.code, {
        ...existing,
        ...change,
        ...moneyFlowPatch,
        timestamp: Date.now(),
      })
    })

    this.state.realtime.lastUpdate = Date.now()
    this.state.version.quotes++

    this.throttledNotify('quotes:batch', { count: changes.length })
  }

  applyRealtimeQuoteBatch(changes: any[]) {
    if (!changes?.length) return

    this.updateQuotesBatch(changes)

    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touched = false

    changes.forEach((change) => {
      const code = String(change?.code || '')
      if (!code) return

      const stock = stockMap.get(code)
      if (!stock) return

      stock.price = Number(change.price ?? change.lastPrice ?? stock.price) || 0
      stock.change = Number(change.change ?? change.changePct ?? stock.change) || 0
      const nextSpeed = Number(change.speed)
      if (Number.isFinite(nextSpeed)) {
        stock.speed = nextSpeed
      }
      const previousVolume = Number(stock.volume) || 0
      stock.volume = Number(change.volume ?? stock.volume) || 0
      this.markVolumeRatioStaleIfVolumeChanged(stock, previousVolume)
      this.applyQuoteVolumeRatio(stock, change)
      stock.turnover = Number(change.turnover ?? change.amount ?? stock.turnover) || 0
      stock.turnoverRate = Number(change.turnoverRate ?? stock.turnoverRate) || 0
      stock.pe = this.pickQuoteNumber(change.pe, stock.pe)
      stock.pb = this.pickQuoteNumber(change.pb, stock.pb)
      stock.totalMV = this.pickPositiveQuoteNumber(change.totalMV, stock.totalMV)
      stock.cirMV = this.pickPositiveQuoteNumber(change.cirMV, stock.cirMV)
      const shouldApplyMoneyFlow = shouldApplyMoneyFlowUpdate(stock, change)
      if (shouldApplyMoneyFlow) {
        stock.zlje = this.pickMoneyFlowNumber(change.zlje, stock.zlje)
        stock.zljzb = this.pickMoneyFlowNumber(change.zljzb, stock.zljzb)
        stock.cddje = this.pickMoneyFlowNumber(change.cddje, stock.cddje)
        stock.cddjzb = this.pickMoneyFlowNumber(change.cddjzb, stock.cddjzb)
      }
      stock.tdxBuyVolume = this.pickQuoteNumber(change.tdxBuyVolume, stock.tdxBuyVolume)
      stock.tdxSellVolume = this.pickQuoteNumber(change.tdxSellVolume, stock.tdxSellVolume)
      stock.tdxCurrentVolume = this.pickQuoteNumber(change.tdxCurrentVolume, stock.tdxCurrentVolume)
      if (
        shouldApplyMoneyFlow &&
        typeof change.moneyFlowSource === 'string' &&
        change.moneyFlowSource.trim()
      ) {
        stock.moneyFlowSource = change.moneyFlowSource
      }
      if (shouldApplyMoneyFlow && typeof change.moneyFlowEstimated === 'boolean') {
        stock.moneyFlowEstimated = change.moneyFlowEstimated
      }
      if (
        shouldApplyMoneyFlow &&
        typeof change.capitalFlowSource === 'string' &&
        change.capitalFlowSource.trim()
      ) {
        stock.capitalFlowSource = change.capitalFlowSource
      }
      if (
        shouldApplyMoneyFlow &&
        typeof change.capitalFlowConfidence === 'string' &&
        change.capitalFlowConfidence.trim()
      ) {
        stock.capitalFlowConfidence = change.capitalFlowConfidence
      }
      stock.updatedAt = Date.now()
      if (typeof change.name === 'string' && change.name.trim()) {
        stock.name = change.name.trim()
      }

      stockMap.set(code, stock)
      touched = true
    })

    if (!touched) return

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  private pickQuoteNumber(nextValue: unknown, currentValue: unknown): number {
    const nextNumber = Number(nextValue)
    const currentNumber = Number(currentValue)

    if (Number.isFinite(nextNumber) && nextNumber !== 0) return nextNumber
    if (Number.isFinite(currentNumber)) return currentNumber
    if (Number.isFinite(nextNumber)) return nextNumber
    return 0
  }

  private pickMoneyFlowNumber(nextValue: unknown, currentValue: unknown): number {
    const nextNumber = Number(nextValue)
    const currentNumber = Number(currentValue)

    if (Number.isFinite(nextNumber)) return nextNumber
    if (Number.isFinite(currentNumber)) return currentNumber
    return 0
  }

  private pickPositiveQuoteNumber(nextValue: unknown, currentValue: unknown): number {
    const nextNumber = Number(nextValue)
    const currentNumber = Number(currentValue)

    if (Number.isFinite(nextNumber) && nextNumber > 0) return nextNumber
    if (Number.isFinite(currentNumber) && currentNumber > 0) return currentNumber
    if (Number.isFinite(nextNumber)) return nextNumber
    return 0
  }

  updateQuote(code: string, data: any) {
    this.updateQuotesBatch([{ code, ...data }])
  }

  getQuote(code: string) {
    return this.state.realtime.quotes.get(code)
  }

  getQuotes(codes: string[]) {
    const result = new Map()
    codes.forEach((c) => {
      const q = this.state.realtime.quotes.get(c)
      if (q) result.set(c, q)
    })
    return result
  }

  getAllQuotes() {
    return Array.from(this.state.realtime.quotes.values())
  }

  getQuotesCount() {
    return this.state.realtime.quotes.size
  }

  getQuotesLastUpdate() {
    return this.state.realtime.lastUpdate
  }

  updateDepth10Batch(changes: Depth10Book[]) {
    if (!changes?.length) return

    changes.forEach((change) => {
      if (!change?.code) return
      this.state.realtime.depth10.set(change.code, {
        ...change,
        bids: [...(change.bids || [])].slice(0, 10),
        asks: [...(change.asks || [])].slice(0, 10),
        timestamp: Date.now(),
      })
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.depth10', { count: changes.length })
  }

  getDepth10(code: string): Depth10Book | null {
    return this.state.realtime.depth10.get(code) || null
  }

  getDepth10Map(): Map<string, Depth10Book> {
    return this.state.realtime.depth10
  }

  updateRecentTicksBatch(changes: Array<{ code: string; items: TickTrade[] }>) {
    if (!changes?.length) return

    const now = Date.now()
    changes.forEach((change) => {
      const code = String(change?.code || '')
      if (!code) return

      const existing = this.state.realtime.recentTicks.get(code) || []
      const next = existing
        .filter((item) => now - Number(item?.timestamp || 0) <= 60_000)
        .concat(Array.isArray(change.items) ? change.items : [])
        .slice(-300)

      this.state.realtime.recentTicks.set(code, next)
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.ticks', { count: changes.length })
  }

  getRecentTicks(code: string): TickTrade[] {
    return [...(this.state.realtime.recentTicks.get(code) || [])]
  }

  getRecentTicksMap(): Map<string, TickTrade[]> {
    return this.state.realtime.recentTicks
  }

  updateL2SummaryBatch(changes: Array<Partial<L2Summary> & { code: string }>) {
    if (!changes?.length) return

    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touched = false

    changes.forEach((change) => {
      if (!change?.code) return

      const existing = this.state.realtime.l2Summary.get(change.code)
      const nextSummary: L2Summary = {
        code: change.code,
        bid1Price: Number(change.bid1Price ?? existing?.bid1Price) || 0,
        bid1Volume: Number(change.bid1Volume ?? existing?.bid1Volume) || 0,
        ask1Price: Number(change.ask1Price ?? existing?.ask1Price) || 0,
        ask1Volume: Number(change.ask1Volume ?? existing?.ask1Volume) || 0,
        spread: Number(change.spread ?? existing?.spread) || 0,
        bid10Total: Number(change.bid10Total ?? existing?.bid10Total) || 0,
        ask10Total: Number(change.ask10Total ?? existing?.ask10Total) || 0,
        depthImbalance: Number(change.depthImbalance ?? existing?.depthImbalance) || 0,
        tickBuyVolume: Number(change.tickBuyVolume ?? existing?.tickBuyVolume) || 0,
        tickSellVolume: Number(change.tickSellVolume ?? existing?.tickSellVolume) || 0,
        tickBuyCount: Number(change.tickBuyCount ?? existing?.tickBuyCount) || 0,
        tickSellCount: Number(change.tickSellCount ?? existing?.tickSellCount) || 0,
        lastTradePrice: Number(change.lastTradePrice ?? existing?.lastTradePrice) || 0,
        lastTradeVolume: Number(change.lastTradeVolume ?? existing?.lastTradeVolume) || 0,
        timestamp: Number(change.timestamp ?? existing?.timestamp) || Date.now(),
      }

      this.state.realtime.l2Summary.set(change.code, nextSummary)

      const stock = stockMap.get(change.code)
      if (!stock) return

      Object.assign(stock, nextSummary)
      stock.updatedAt = Date.now()
      stockMap.set(change.code, stock)
      touched = true
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.l2Summary', { count: changes.length })

    if (!touched) return

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  getL2Summary(code: string): L2Summary | null {
    return this.state.realtime.l2Summary.get(code) || null
  }

  getL2SummaryMap(): Map<string, L2Summary> {
    return this.state.realtime.l2Summary
  }

  //=======龙息分析服务=========
  updateBreathData(data: any) {
    if (!this.state.analysis) this.state.analysis = {} as any

    if (!this.state.analysis.breath) {
      this.state.analysis.breath = {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      }
    }

    // 更新情绪数据
    this.state.analysis.breath.sentiment = {
      overall: data.sentiment.overall,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
      riskLevel: data.sentiment.riskLevel,
      suggestion: data.sentiment.suggestion,
      phaseInfo: data.sentiment.phaseInfo,
    }

    // 更新市场数据 - 确保包含所有字段
    this.state.analysis.breath.marketData = {
      upCount: data.marketData.upCount || 0,
      downCount: data.marketData.downCount || 0,
      ztCount: data.marketData.ztCount || 0,
      dtCount: data.marketData.dtCount || 0,
      zhaban: data.marketData.zhaban || {},
      totalAmo: data.marketData.totalAmo || 0,
      amoDiff: data.marketData.amoDiff || 0,
      volumeRatio: data.marketData.volumeRatio || 0,
      limitData: data.marketData.limitData || { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
      yesterdayLimit: data.marketData.yesterdayLimit || {},
      previousMarketStats: data.marketData.previousMarketStats ?? null,
      indices: data.marketData.indices || {},
      moneyFlow: data.marketData.moneyFlow || { main: 0, retail: 0 },
      cddje: data.marketData.cddje || 0,
      cddjzb: data.marketData.cddjzb || 0,
      yesterdayZtPerformance: data.marketData.yesterdayZtPerformance || 0,
      emotionValue: data.marketData.emotionValue || 0,
      emotionStatus: data.marketData.emotionStatus || '震荡',
      timestamp: data.marketData.timestamp || Date.now(),
      maxContinuousDays: data.marketData.maxContinuousDays,  // 连板高度（保持 undefined 以支持回退链）
      largeCapChange: data.marketData.largeCapChange || 0,  // 大票
      microCapChange: data.marketData.microCapChange || 0,   // 微盘
      passRate: data.marketData.passRate || { to2: 0, to3: 0, to4: 0 }, // 晋级率
      thsLimitUpPools: data.marketData.thsLimitUpPools ?? null,
    }

    // 更新因子数据
    if (data.factors) {
      this.state.analysis.breath.factors = data.factors
    }

    this.state.analysis.breath.lastUpdate = data.timestamp

    // 保存历史
    if (!this.state.analysis.breath.history) {
      this.state.analysis.breath.history = []
    }
    this.state.analysis.breath.history.push({
      timestamp: data.timestamp,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
      riskLevel: data.sentiment.riskLevel,
    })
    if (this.state.analysis.breath.history.length > 100) {
      this.state.analysis.breath.history.shift()
    }
  }

  getBreathFactors() {
    return this.state.analysis.breath?.factors || []
  }

  getBreathData(): BreathData['sentiment'] | null {
    return this.state.analysis.breath.sentiment
  }

  getBreathMarketData() {
    return this.state.analysis.breath.marketData
  }

  getBreathHistory() {
    return this.state.analysis.breath.history
  }

  // ========== 算法结果管理 ==========
  updateAlgorithmResult(code: string, result: any) {
    if (!this.state.analysis.algorithm) {
      this.state.analysis.algorithm = {
        config: null, // ✅ 添加 config 属性
        results: new Map(),
        lastUpdate: null,
      }
    }

    this.state.analysis.algorithm.results.set(code, result)
    this.state.analysis.algorithm.lastUpdate = Date.now()
    this.state.version.algorithm = (this.state.version.algorithm || 0) + 1
  }

  getAlgorithmResult(code: string) {
    return this.state.analysis?.algorithm?.results?.get(code)
  }

  updateAlgorithmConfig(config: any) {
    this.state.analysis.algorithm.config = {
      ...config,
      timestamp: Date.now(),
    }
    this.state.version.algorithm = (this.state.version.algorithm || 0) + 1
    this.throttledNotify('analysis.algorithm.config', config)
  }

  getAlgorithmConfig() {
    return this.state.analysis.algorithm.config
  }

  // ========== 题材库数据管理 ==========

  private initTck2Store() {
    this.state.tck2 = {
      stockHotness: new Map(),
      stockTags: new Map(),
      stockReasons: new Map(),
      stockIsNew: new Map(),
      limitUpData: new Map<string, LimitUpExtData>(),
      lastUpdate: Date.now(),
    }
  }

  updateStockHotness(updates: Array<{ code: string; hotness: number }>) {
    if (!this.state.tck2) this.initTck2Store()
    updates.forEach(({ code, hotness }) => {
      this.state.tck2!.stockHotness.set(code, hotness)
    })
    this.throttledNotify('tck2.hotness', { count: updates.length })
  }

  updateStockTags(updates: Array<{ code: string; tags: Array<{ Name: string }> }>) {
    if (!this.state.tck2) this.initTck2Store()
    updates.forEach(({ code, tags }) => {
      this.state.tck2!.stockTags.set(code, tags)
    })
    this.throttledNotify('tck2.tags', { count: updates.length })
  }

  updateLimitUpData(
    updates: Array<{
      code: string
      reason?: string
      isNew?: boolean
      firstZtTime?: string
      lastZtTime?: string
      boardHeight?: number
      highDays?: number
      fengdan?: number
      maxFengdan?: number
      leadStatus?: string
      leadTimes?: number
      lianbanStr?: string
      tags?: Array<{ Name: string }>
    }>,
  ) {
    if (!this.state.tck2) this.initTck2Store()

    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touchedStocks = false

    updates.forEach(({ code, reason, isNew, tags, ...rest }) => {
      // 更新 reason
      if (reason !== undefined) this.state.tck2!.stockReasons.set(code, reason)

      // 更新 isNew
      if (isNew !== undefined) this.state.tck2!.stockIsNew.set(code, isNew)

      // ✅ 更新 tags
      if (tags !== undefined) {
        this.state.tck2!.stockTags.set(code, tags)
      }

      // 构建 limitUpData 数据
      const limitData: any = { ...rest }
      if (tags !== undefined) {
        limitData.tags = tags
      }
      if (reason !== undefined) {
        limitData.reason = reason
      }
      if (isNew !== undefined) {
        limitData.isNew = isNew
      }

      // 更新 limitUpData
      const existing = this.state.tck2!.limitUpData.get(code) || {}
      this.state.tck2!.limitUpData.set(code, {
        ...existing,
        ...limitData,
      })

      const stock = stockMap.get(code)
      if (stock) {
        this.applyLimitUpProjectionToStock(stock, limitData)
        stockMap.set(code, stock)
        touchedStocks = true
      }
    })

    if (touchedStocks) {
      this.state.merged.stocks = Array.from(stockMap.values())
      this.state.version.stocks++
      this.throttledNotify('merged.stocks', this.state.merged.stocks)
      this.throttledNotify('version.stocks', this.state.version.stocks)
    }

    this.throttledNotify('tck2.limitup', { count: updates.length })
  }

  private applyLimitUpProjectionToStock(stock: MergedStock, limitData: LimitUpExtData) {
    stock.firstZtTime = limitData.firstZtTime ?? stock.firstZtTime
    stock.lastZtTime = limitData.lastZtTime ?? stock.lastZtTime
    stock.boardHeight = limitData.boardHeight ?? stock.boardHeight
    stock.highDays = limitData.highDays ?? stock.highDays
    stock.fengdan = limitData.fengdan ?? stock.fengdan
    stock.maxFengdan = limitData.maxFengdan ?? stock.maxFengdan
    stock.leadStatus = limitData.leadStatus ?? stock.leadStatus
    stock.leadTimes = limitData.leadTimes ?? stock.leadTimes
    stock.lianbanStr = limitData.lianbanStr ?? stock.lianbanStr
    stock.reason = limitData.reason ?? stock.reason
    stock.tags = limitData.tags ?? stock.tags
    stock.isNew = limitData.isNew ?? stock.isNew
  }

  getStockHotness(code: string): number | undefined {
    const stored = this.state.tck2?.stockHotness.get(code)
    if (stored !== undefined) return stored
    return this.state.merged.stocks.find((stock) => stock.code === code)?.hotness
  }

  getStockTags(code: string): Array<{ Name: string }> | undefined {
    return this.state.tck2?.stockTags.get(code)
  }

  getStockReason(code: string): string | undefined {
    return this.state.tck2?.stockReasons.get(code)
  }

  getStockIsNew(code: string): boolean | undefined {
    return this.state.tck2?.stockIsNew.get(code)
  }

  getLimitUpData(code: string): LimitUpExtData | undefined {
    return this.state.tck2?.limitUpData.get(code)
  }

  /**
   * 手动设置合并后的股票数据
   * 供 dataLoader 调用，更新 merged.stocks
   */
  setMergedStocks(stocks: any[]) {
    const normalizedStocks = (stocks as MergedStock[]).map((stock) => {
      const normalized = this.applyRealtimeProjection(stripLegacyLeaderFields(stock))
      if ('rankTrend' in normalized) {
        applyRankTrendAnalysis(normalized, normalized.rankTrend ?? null)
      }
      return applyReviewProjectionToStock(
        normalized,
        this.state.leader.byCode.get(normalized.code) || null,
      )
    })

    this.state.merged.stocks = normalizedStocks
    this.state.version.stocks++
    this.state.meta.lastMergeTime = Date.now()
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  private applyRealtimeProjection(stock: MergedStock): MergedStock {
    const quote = this.state.realtime.quotes.get(stock.code)
    const l2Summary = this.state.realtime.l2Summary.get(stock.code)
    const next = { ...stock }

    if (quote) {
      next.price = this.pickQuoteNumber(quote.price ?? quote.lastPrice, next.price)
      next.change = this.pickQuoteNumber(quote.change ?? quote.changePct, next.change)
      const previousVolume = Number(next.volume) || 0
      next.volume = this.pickQuoteNumber(quote.volume, next.volume)
      this.markVolumeRatioStaleIfVolumeChanged(next, previousVolume)
      this.applyQuoteVolumeRatio(next, quote)
      next.turnover = this.pickQuoteNumber(quote.turnover ?? quote.amount, next.turnover)
      next.turnoverRate = this.pickQuoteNumber(quote.turnoverRate, next.turnoverRate)
      next.pe = this.pickQuoteNumber(quote.pe, next.pe)
      next.pb = this.pickQuoteNumber(quote.pb, next.pb)
      next.totalMV = this.pickPositiveQuoteNumber(quote.totalMV, next.totalMV)
      next.cirMV = this.pickPositiveQuoteNumber(quote.cirMV, next.cirMV)
      next.speed = this.pickOptionalQuoteNumber(quote.speed, next.speed)

      const shouldApplyMoneyFlow = shouldApplyMoneyFlowUpdate(next, quote)
      if (shouldApplyMoneyFlow) {
        next.zlje = this.pickMoneyFlowNumber(quote.zlje, next.zlje)
        next.zljzb = this.pickMoneyFlowNumber(quote.zljzb, next.zljzb)
        next.cddje = this.pickMoneyFlowNumber(quote.cddje, next.cddje)
        next.cddjzb = this.pickMoneyFlowNumber(quote.cddjzb, next.cddjzb)
      }
      next.tdxBuyVolume = this.pickOptionalQuoteNumber(quote.tdxBuyVolume, next.tdxBuyVolume)
      next.tdxSellVolume = this.pickOptionalQuoteNumber(quote.tdxSellVolume, next.tdxSellVolume)
      next.tdxCurrentVolume = this.pickOptionalQuoteNumber(
        quote.tdxCurrentVolume,
        next.tdxCurrentVolume,
      )
      if (shouldApplyMoneyFlow && typeof quote.moneyFlowSource === 'string') {
        next.moneyFlowSource = quote.moneyFlowSource
      }
      if (shouldApplyMoneyFlow && typeof quote.moneyFlowEstimated === 'boolean') {
        next.moneyFlowEstimated = quote.moneyFlowEstimated
      }
      if (shouldApplyMoneyFlow && typeof quote.capitalFlowSource === 'string') {
        next.capitalFlowSource = quote.capitalFlowSource
      }
      if (shouldApplyMoneyFlow && typeof quote.capitalFlowConfidence === 'string') {
        next.capitalFlowConfidence = quote.capitalFlowConfidence
      }
    }

    if (l2Summary) {
      Object.assign(next, l2Summary)
    }

    return next
  }

  private markVolumeRatioStaleIfVolumeChanged(stock: MergedStock, previousVolume: number): void {
    const nextVolume = Number(stock.volume) || 0
    if (!stock.volumeRatioMeta || stock.volumeRatioMeta.status !== 'fresh') return
    if (!Number.isFinite(previousVolume) || !Number.isFinite(nextVolume)) return
    if (previousVolume <= 0 || nextVolume <= 0 || previousVolume === nextVolume) return

    stock.volumeRatioMeta = {
      ...stock.volumeRatioMeta,
      status: 'stale',
      currentVolume: nextVolume,
      reason: 'volume_changed_after_ratio_calculated',
    }
  }

  private applyQuoteVolumeRatio(stock: MergedStock, quote: any): void {
    const volumeRatio = Number(quote?.volumeRatio)
    if (!Number.isFinite(volumeRatio) || volumeRatio <= 0) return

    stock.volumeRatio = Number(volumeRatio.toFixed(2))
    stock.volumeRatioMeta = {
      status: 'fresh',
      source: 'daily_snapshot',
      calculatedAt: Date.now(),
      currentVolume: Number(stock.volume) || 0,
      rawRatio: stock.volumeRatio,
      capped: false,
      reason: 'quote_feed',
    }
  }

  private pickOptionalQuoteNumber(nextValue: unknown, currentValue: unknown): number | undefined {
    const nextNumber = Number(nextValue)
    const currentNumber = Number(currentValue)

    if (Number.isFinite(nextNumber) && nextNumber !== 0) return nextNumber
    if (Number.isFinite(currentNumber)) return currentNumber
    if (Number.isFinite(nextNumber)) return nextNumber
    return undefined
  }

  // ========== 工具方法 ==========

  hasStock(code: string) {
    return this.state.merged.stocks.some((s) => s.code === code)
  }

  getVersion() {
    return { ...this.state.version }
  }

  getLastMergeTime() {
    return this.state.meta.lastMergeTime
  }

  getMarketMode(): 'hot' | 'full' {
    return this.state.meta.marketMode
  }

  refreshStocksVersion() {
    this.state.version.stocks++
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  bumpLeadersVersion() {
    this.state.version.leaders++
    this.throttledNotify('version.leaders', this.state.version.leaders)
  }

  // ========== 初始化状态 ==========

  isInitialized() {
    return this.state.meta.initialized
  }

  setInitialized(init = true) {
    this.state.meta.initialized = init
  }

  // ========== 订阅机制 ==========

  subscribe(path: string, callback: (data: any) => void) {
    if (!this.subscribers.has(path)) {
      this.subscribers.set(path, new Set())
    }
    this.subscribers.get(path)!.add(callback)
    return () => this.subscribers.get(path)?.delete(callback)
  }

  once(path: string, callback: (data: any) => void) {
    const unsubscribe = this.subscribe(path, (data) => {
      unsubscribe()
      callback(data)
    })
  }

  async waitFor(path: string, timeout = 10000): Promise<any> {
    const data = this.getPathData(path)
    if (data) return data

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        unsubscribe()
        reject(new Error(`等待 ${path} 超时`))
      }, timeout)

      const unsubscribe = this.subscribe(path, (data) => {
        clearTimeout(timer)
        unsubscribe()
        resolve(data)
      })
    })
  }

  private getPathData(path: string): any {
    return path.split('.').reduce((obj: any, key: string) => obj?.[key], this.state)
  }

  private throttledNotify(path: string, data: any) {
    this.pendingNotify.set(path, data)
    if (this.notifyTimer) return

    this.notifyTimer = setTimeout(() => {
      this.pendingNotify.forEach((pendingData, pendingPath) => {
        this.subscribers.get(pendingPath)?.forEach((cb) => {
          try {
            cb(pendingData)
          } catch (error) {
            // ✅ 添加 error 参数
            console.warn('[DataLayer] 通知回调失败:', error)
          }
        })
      })
      this.pendingNotify.clear()
      this.notifyTimer = null
    }, 50)
  }

  // ========== 轮动数据管理 ==========

  updateRotationAnalysis(analysis: RotationAnalysis) {
    this.state.analysis.rotation.current = analysis
    this.state.analysis.rotation.history.push(analysis)
    if (this.state.analysis.rotation.history.length > 100) {
      this.state.analysis.rotation.history.shift()
    }
    this.state.analysis.rotation.lastUpdate = Date.now()
    this.state.version.rotation = (this.state.version.rotation || 0) + 1
    this.throttledNotify('analysis.rotation', analysis)
  }

  getCurrentRotation(): RotationAnalysis | null {
    return this.state.analysis.rotation.current
  }

  getRotationHistory(limit?: number): RotationAnalysis[] {
    const history = this.state.analysis.rotation.history
    return limit ? history.slice(-limit) : [...history]
  }

  // ========== 大单数据管理 ==========
  updateBigOrderData(
    stockCode: string,
    orders: BigOrderItem[],
    statistics: BigOrderStatistics,
    periods: PeriodStatistics[] = [],
  ) {
    this.bigOrderData.set(stockCode, {
      orders: [...orders],
      statistics,
      periods: [...periods],
      lastUpdate: Date.now(),
    })
    this.throttledNotify(`bigOrder.${stockCode}`, this.bigOrderData.get(stockCode))
  }

  getBigOrderData(stockCode: string) {
    return this.bigOrderData.get(stockCode) || null
  }

  getBigOrders(stockCode?: string): BigOrderItem[] {
    if (stockCode) {
      return [...(this.bigOrderData.get(stockCode)?.orders || [])]
    }
    return Array.from(this.bigOrderData.values()).flatMap((entry) => entry.orders)
  }

  getBigOrderStatistics(stockCode: string): BigOrderStatistics | null {
    return this.bigOrderData.get(stockCode)?.statistics || null
  }

  getBigOrderPeriods(stockCode: string): PeriodStatistics[] {
    return [...(this.bigOrderData.get(stockCode)?.periods || [])]
  }

  addDenseOrderAlert(alert: DenseOrderAlert) {
    this.denseOrderAlerts.unshift(alert)
    if (this.denseOrderAlerts.length > 200) {
      this.denseOrderAlerts.pop()
    }
    this.throttledNotify('bigOrder.denseAlerts', this.denseOrderAlerts)
  }

  getDenseOrderAlerts(limit?: number): DenseOrderAlert[] {
    return limit ? this.denseOrderAlerts.slice(0, limit) : [...this.denseOrderAlerts]
  }

  // ========== 预警数据管理 ==========
  addAlert(alert: StockAlert) {
    this.state.analysis.alerts.items.unshift(alert)
    if (this.state.analysis.alerts.items.length > ALERT_CONFIG.MAX_ALERTS) {
      this.state.analysis.alerts.items.pop()
    }
    this.updateAlertStats()
    this.state.analysis.alerts.lastUpdate = Date.now()
    this.throttledNotify('analysis.alerts', alert)
  }

  getAlerts(limit?: number): StockAlert[] {
    const items = this.state.analysis.alerts.items
    return limit ? items.slice(0, limit) : [...items]
  }

  getUnreadAlerts(): StockAlert[] {
    return this.state.analysis.alerts.items.filter((a) => a.status === 'pending')
  }

  markAlertAsRead(alertId: string) {
    const alert = this.state.analysis.alerts.items.find((a) => a.id === alertId)
    if (alert && alert.status === 'pending') {
      alert.status = 'read'
      alert.readTime = Date.now()
      this.updateAlertStats()
    }
  }

  private updateAlertStats() {
    const items = this.state.analysis.alerts.items
    const stats = {
      total: items.length,
      critical: items.filter((a) => a.level === 'critical').length,
      warning: items.filter((a) => a.level === 'warning').length,
      info: items.filter((a) => a.level === 'info').length,
      byType: {} as Record<string, number>,
      lastUpdate: Date.now(),
    }
    items.forEach((alert) => {
      stats.byType[alert.type] = (stats.byType[alert.type] || 0) + 1
    })
    this.state.analysis.alerts.stats = stats
  }

  getStats() {
    const now = Date.now()
    return {
      quotes: {
        count: this.state.realtime.quotes.size,
        age: this.state.realtime.lastUpdate
          ? ((now - this.state.realtime.lastUpdate) / 1000).toFixed(1) + 's'
          : 'N/A',
        lastUpdate: this.state.realtime.lastUpdate,
      },
      depth10: {
        count: this.state.realtime.depth10.size,
      },
      recentTicks: {
        codes: this.state.realtime.recentTicks.size,
      },
      versions: { ...this.state.version },
    }
  }

  // ========== 重置 ==========

  reset() {
    this.state.raw = { stocks: [], platforms: {}, themes: [], fullMarket: [] }
    this.state.realtime = {
      quotes: new Map(),
      depth10: new Map(),
      recentTicks: new Map(),
      l2Summary: new Map(),
      lastUpdate: null,
    }
    this.state.merged = { stocks: [], themes: [] }
    this.state.leader = {
      byCode: new Map(),
      byLevel: {},
      lastUpdate: null,
    }
    this.state.review = {
      result: null,
      marketCore: null,
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      battlefields: [],
      transitions: [],
      summaryLines: [],
      lastUpdate: null,
    }
    this.state.theme = {
      base: {
        byCode: new Map(),
        byId: new Map(),
        lastUpdate: null,
      },
      metrics: {
        byTheme: new Map(),
        hotList: [],
        rotation: [],
        lastUpdate: null,
      },
      jxbk: {
        blocks: [],
        blockMap: {},
        stockMap: {},
        lastUpdate: null,
      },
      correlation: {
        byTheme: new Map(),
        lastUpdate: null,
      },
    }
    this.state.analysis = {
      breath: {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      },
      algorithm: {
        config: null,
        results: new Map(),
        lastUpdate: null,
      },
      rotation: {
        current: null,
        history: [],
        lastUpdate: null,
      },
      alerts: {
        items: [],
        stats: {
          total: 0,
          critical: 0,
          warning: 0,
          info: 0,
          byType: {
            leader_fall: 0,
            leader_emerge: 0,
            batch_limit_up: 0,
            batch_explode: 0,
            strength_surge: 0,
            strength_plunge: 0,
            money_flow: 0,
            data_anomaly: 0,
            volume_surge: 0,
            rocket_launch: 0,
            waterfall_dive: 0,
            fengdan_drop: 0,
          },
          lastUpdate: 0,
        },
        lastUpdate: null,
      },
    }

    this.state.rankHistory = {
      byCode: new Map(),
      lastUpdate: null,
      snapshotDate: null,
    }

    this.state.version = {
      stocks: 0,
      themes: 0,
      leaders: 0,
      review: 0,
      quotes: 0,
      platforms: 0,
      breath: 0,
      algorithm: 0,
      rotation: 0,
    }
    this.state.meta = {
      initialized: false,
      lastMergeTime: null,
      marketMode: 'hot',
    }
    this.state.tck2 = undefined
  }


}

// 在文件末尾更新导出
export const dataLayer = new DataLayer()

if (typeof window !== 'undefined') {
  ;(window as any).dataLayer = dataLayer
}
