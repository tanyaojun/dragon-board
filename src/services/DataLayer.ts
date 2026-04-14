// src/services/DataLayer.ts

import { ref, reactive } from 'vue'
import type { BreathData } from '../types'
import { ALERT_CONFIG } from '../config/constants'
import { isTradingTime } from '../utils/time'
import type { ThemeCorrelationDetail } from './ThemeCorrelationAnalyzer'
import type { RotationAnalysis } from '../types'
import type { StockAlert, AlertStats } from '../types'
import { StockUtils } from '../utils/common'
import type { AlertType } from '../types/core'

interface DataVersion {
  stocks: number
  themes: number
  leaders: number
  quotes: number
  platforms: number
  breath: number
  algorithm: number
  rotation?: number
}
// ========== 题材指标类型 ==========
interface ThemeMetrics {
  // 基础热度（原有计算）
  heatScore: number
  heatLevel: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: any[]

  // 统计
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }

  // jxbk 指标（新增）
  jxbk: {
    strength: number // 强度分数
    mainNetInflow: number // 主力净额
    bigMoney300: number // 300W大单
    institutionBuy: number // 机构增仓
    volumeRatio: number // 量比
  }

  lastUpdate: number
}

// ========== 涨停数据扩展类型 ==========
interface LimitUpExtData {
  firstZtTime?: string // 首次涨停时间
  lastZtTime?: string // 最后涨停时间
  boardHeight?: number // 封板高度
  highDays?: number // 连板天数
  fengdan?: number // 封单额（万元）
  maxFengdan?: number // 最大封单（万元）
  leadStatus?: string // 领涨状态（"破板"/"领涨"等）
  leadTimes?: number // 领涨次数
  lianbanStr?: string // 连板描述（"首板"、"2板"等）
  reason?: string // 涨停原因/关联原因
  tags?: Array<{ Name: string }> // 股票标签
  isNew?: boolean // 是否新股/新涨停
}

// ========== 股票扩展数据类型 ==========
interface StockExtData {
  speed?: number // 涨速（%）
  volumeRatio?: number // 量比
  leadTimes?: number // 领涨次数
  leadStatus?: string // 领涨状态（"破板"、"领涨"等）
  lianbanStr?: string // 连板描述（"首板"、"2板"、"3板"等）
  bigMoney300?: number // 300万以上大单（万元）
  popularity?: number // 人气排名
  popularityChange?: number // 人气排名变动
  institutionBuy?: number // 机构增仓（万元）
  mainBuy?: number // 主力买入（万元）
  mainSell?: number // 主力卖出（万元）
  fengdan?: number // 封单额（万元）
  maxFengdan?: number // 最大封单（万元）
}

// ========== jxbk 数据类型 ==========

/** jxbk 板块数据（直接从API获取） */
interface JxbkBlockData {
  code: string // 板块代码
  name: string // 板块名称
  strength: number // 强度分数（原始值）
  change: number // 涨幅
  mainNetInflow: number // 主力净额
  bigMoney300: number // 300W大单
  institutionBuy: number // 机构增仓
  volumeRatio: number // 量比
  ztCount: number // 涨停数
}

/** jxbk 股票数据（直接从API获取） */
interface JxbkStockData {
  code: string
  name: string
  change: number // 涨幅
  speed: number // 涨速
  volumeRatio: number // 量比
  mainNetInflow: number // 主力净额
  leadTimes: number // 领次
  leadStatus: string // 领涨状态
  lianban: string // 连板
  bigMoney300: number // 300W大单
  popularity: number // 人气
  popularityChange: number // 变动
  blocks: string[] // 板块列表
  institutionBuy: number // 机构增仓
  mainBuy: number // 主力买入
  mainSell: number // 主力卖出
  fengdan: number // 封单额
  maxFengdan: number // 最大封单
  cirMV: number // 流通市值
}

// ========== 合并后的股票类型（包含所有字段） ==========
export interface MergedStock {
  // ========== 基础字段 ==========
  code: string
  name: string
  price: number
  change: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  pb: number
  totalMV: number
  cirMV: number
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number

  // ========== 平台排名 ==========
  emRank?: number
  thsRank?: number
  kplRank?: number
  tdxRank?: number
  xqRank?: number
  clsRank?: number
  tgbRank?: number
  dzhRank?: number
  platforms?: number
  avgRankNum?: number
  avgRank?: string

  // ========== 综合排名 ==========
  compRank?: number
  compScore?: number
  rankChange?: number

  // ========== 时间戳 ==========
  updatedAt?: number
  firstSeen?: number
  lastSeen?: number

  // ========== 平台名称 ==========
  platformName?: string

  // ========== 龙头标记 ==========
  isSectorLeader?: boolean
  leaderLevel?: string
  leaderScore?: number
  continuousDays?: number

  // ========== 题材数据 ==========
  themes?: any[]

  // ========== 个股扩展字段 ==========
  speed?: number
  volumeRatio?: number
  leadTimes?: number
  leadStatus?: string
  lianbanStr?: string
  bigMoney300?: number
  popularity?: number
  popularityChange?: number
  institutionBuy?: number
  mainBuy?: number
  mainSell?: number
  fengdan?: number
  maxFengdan?: number

  hotness?: number
  tags?: any[]
  reason?: string
  isNew?: boolean
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  fundPenetration?: number
  mainTheme?: string
  themeHeat?: number
  themeLevel?: string

  // ========== 3个排名趋势信号 ==========
  directionSignal?: 'buy' | 'sell' | 'hold' | 'none'
  directionConfidence?: number
  accelerationSignal?: 'buy' | 'sell' | 'hold' | 'none'
  accelerationConfidence?: number
  crossSignal?: 'buy' | 'sell' | 'hold' | 'none'
  crossConfidence?: number

  // ========== MACD 技术指标 ==========
  macd?: number
  macdSignal?: number
  macdHistogram?: number
  ma5?: number
  ma10?: number
  maTrend?: 'up' | 'down' | 'steady'
  macdCross?: 'golden' | 'death' | 'none'

  // ========== 综合信号 ==========
  finalSignal?: 'buy' | 'sell' | 'hold' | 'none'
  finalConfidence?: number
}

interface DataState {
  // 原始数据
  raw: {
    stocks: any[]
    platforms: Record<string, any>
    themes: any[]
    fullMarket: any[]
  }

  // 实时数据
  realtime: {
    quotes: Map<string, any>
    lastUpdate: number | null
  }

  // 合并后的展示数据（供UI直接使用）
  merged: {
    stocks: MergedStock[] // 使用扩展后的股票类型
    themes: any[]
  }

  // 龙头数据
  leader: {
    byCode: Map<
      string,
      {
        level: string
        levelName: string
        score: number
        continuousDays: number
        lastUpdate: number
      }
    >
    byLevel: Record<string, any[]>
    lastUpdate: number | null
  }

  // ========== 题材数据 ==========
  theme: {
    // 基础映射（来自 ThemeDataService，只读）
    base: {
      byCode: Map<string, any[]> // 股票 -> 题材列表（静态映射）
      byId: Map<string, any> // 题材ID -> 题材基础信息
      lastUpdate: string | null // 映射文件更新时间
    }

    // 实时指标（由 sectorAnalyzer 计算）
    metrics: {
      byTheme: Map<string, ThemeMetrics> // 题材ID -> 实时指标
      hotList: any[] // 热门题材列表
      rotation: any[] // 轮动数据
      lastUpdate: number | null
    }

    // jxbk 实时数据（来自5000接口）
    jxbk: {
      blocks: JxbkBlockData[] // 板块列表（带强度）
      blockMap: Record<string, JxbkBlockData> // 板块代码映射
      stockMap: Record<string, JxbkStockData> // 股票数据映射
      lastUpdate: number | null
    }

    // 个股联动分析
    correlation: {
      byTheme: Map<string, ThemeCorrelationDetail>
      lastUpdate: number | null
    }
  }

  tck2?: {
    stockHotness: Map<string, number> // 热度值 HotNum
    stockTags: Map<string, Array<{ Name: string }>> // 标签 Tag
    stockReasons: Map<string, string> // 涨停原因
    stockIsNew: Map<string, boolean> // 是否新涨停
    limitUpData: Map<string, LimitUpExtData> // 涨停池扩展数据
    lastUpdate: number | null
  }

  // 分析结果存储
  analysis: {
    breath: {
      sentiment: {
        overall: number
        phase: string // 英文值
        phaseName: string // 中文名
        riskLevel: string
        suggestion: string
        phaseInfo?: any // 阶段完整信息
        factorScores?: Record<string, number>
      } | null
      marketData?: {
        // 添加 marketData 字段定义
        upCount: number
        downCount: number
        ztCount: number
        dtCount: number
        zhaban?: {
          count: number
          rate: number
          fengbanRate: number
          ztCount?: number
        }
        totalAmo: number
        amoDiff?: number
        volumeRatio?: number
        limitData: {
          yiban: number
          erban: number
          sanban: number
          sibanPlus: number
        }
        yesterdayLimit?: {
          total?: number
          ztCount?: number
          dtCount?: number
          bigLossCount?: number
          redCount?: number
          greenCount?: number
          avgChange?: number
          maxChange?: number
          minChange?: number
        }
        indices?: Record<string, { change: number }>
        moneyFlow?: {
          main: number
          retail: number
        }
        cddje?: number
        cddjzb?: number
        yesterdayZtPerformance?: number
        emotionValue?: number
        emotionStatus?: string
        timestamp?: number
      }
      factors?: Array<{
        id: string // 因子ID，如 'breathPhase'
        name: string // 因子名称，如 '龙息阶段'
        value: number // 因子值 (0-100)
        weight: number // 权重 (0-1)
        description?: string // 描述
        unit?: string // 单位，如 '分', '%'
        category?: string // 分类，如 'market', 'emotion'
      }>
      history: any[]
      lastUpdate: number | null
    }
    algorithm: {
      config: any
      results: Map<string, any>
      lastUpdate: number | null
    }

    rotation: {
      current: RotationAnalysis | null
      history: RotationAnalysis[]
      lastUpdate: number | null
    }
    alerts: {
      items: StockAlert[]
      stats: AlertStats
      lastUpdate: number | null
    }
  }

  // ✅ 历史排名数据
  rankHistory: {
    byCode: Map<string, number>
    lastUpdate: number | null
    snapshotDate: string | null
  }

  // 版本控制
  version: DataVersion

  // 元数据
  meta: {
    initialized: boolean
    lastMergeTime: number | null
    marketMode: 'hot' | 'full'
  }
}

/**
 * 数据存储层
 * 职责单一：存储数据、提供访问接口、版本管理
 */
class DataLayer {
  private timer: ReturnType<typeof setInterval> | null = null
  private lastSnapshotKey = {
    half: '',
    quarter: '',
    hour: '',
    daily: '',
  }

  constructor() {
    this.startTimer()
  }

  private state: DataState = reactive({
    raw: { stocks: [], platforms: {}, themes: [], fullMarket: [] },
    realtime: { quotes: new Map(), lastUpdate: null },
    merged: { stocks: [], themes: [] },

    // 龙头数据单独存储
    leader: {
      byCode: new Map(),
      byLevel: {},
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
  private pendingNotify: { path: string; data: any } | null = null

  // ========== 龙头数据管理（唯一入口） ==========

  /**
   * 更新龙头数据 - 供 DragonAnalyzer 调用
   */
  updateLeaderData(leaders: any[]) {
    const byCode = new Map()
    const byLevel: Record<string, any[]> = {}

    leaders.forEach((leader) => {
      // 存储精简的龙头信息
      byCode.set(leader.code, {
        level: leader.level,
        levelName: leader.levelName,
        score: leader.score,
        continuousDays: leader.continuousDays,
        lastUpdate: Date.now(),
      })

      const level = leader.level || 'unknown'
      if (!byLevel[level]) byLevel[level] = []
      byLevel[level].push(leader)
    })

    this.state.leader = {
      byCode,
      byLevel,
      lastUpdate: Date.now(),
    }

    this.state.version.leaders++
  }

  /**
   * 获取单个龙头信息
   */
  getLeaderByCode(code: string) {
    return this.state.leader.byCode.get(code)
  }

  /**
   * 按级别获取龙头
   */
  getLeadersByLevel(level: string) {
    return this.state.leader.byLevel[level] || []
  }

  /**
   * 获取所有龙头
   */
  getAllLeaders() {
    return Array.from(this.state.leader.byCode.values())
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
  updateStockThemes(updates: Array<{ code: string; themes: any[] }>) {
    updates.forEach(({ code, themes }) => {
      this.state.theme.base.byCode.set(code, themes)
    })

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
      ...s,
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

  /**
   * 更新单个股票的扩展数据
   */
  updateSingleStockExtData(code: string, data: Partial<StockExtData>) {
    this.updateStockExtData([{ code, ...data }])
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
      this.state.realtime.quotes.set(change.code, {
        ...existing,
        ...change,
        timestamp: Date.now(),
      })
    })

    this.state.realtime.lastUpdate = Date.now()
    this.state.version.quotes++

    this.throttledNotify('quotes:batch', { count: changes.length })
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

  getMergedStocks(): MergedStock[] {
    return this.state.merged.stocks
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

    this.state.analysis.breath.sentiment = {
      overall: data.sentiment.overall,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
      riskLevel: data.sentiment.riskLevel,
      suggestion: data.sentiment.suggestion,
      phaseInfo: data.sentiment.phaseInfo,
      factorScores: data.sentiment.factorScores,
    }
    this.state.analysis.breath.marketData = data.marketData

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
      sentiment: data.sentiment.overall,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
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

      // 更新 limitUpData
      const existing = this.state.tck2!.limitUpData.get(code) || {}
      this.state.tck2!.limitUpData.set(code, {
        ...existing,
        ...limitData,
      })
    })

    this.throttledNotify('tck2.limitup', { count: updates.length })
  }

  getStockHotness(code: string): number | undefined {
    return this.state.tck2?.stockHotness.get(code)
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
    this.state.merged.stocks = stocks as MergedStock[]
    this.state.version.stocks++
    this.state.meta.lastMergeTime = Date.now()
  }

  // ========== 工具方法 ==========

  getAllStocks(): MergedStock[] {
    return this.state.merged.stocks
  }

  getAllCodes() {
    return this.state.merged.stocks.map((s) => s.code)
  }

  hasStock(code: string) {
    return this.state.merged.stocks.some((s) => s.code === code)
  }

  getTotalCount() {
    return this.state.merged.stocks.length
  }

  getRawStocks() {
    return this.state.raw.stocks
  }

  getVersion() {
    return { ...this.state.version }
  }

  getLastMergeTime() {
    return this.state.meta.lastMergeTime
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
    this.pendingNotify = { path, data }
    if (this.notifyTimer) return

    this.notifyTimer = setTimeout(() => {
      if (this.pendingNotify) {
        this.subscribers.get(this.pendingNotify.path)?.forEach((cb) => {
          try {
            cb(this.pendingNotify!.data)
          } catch (error) {
            // ✅ 添加 error 参数
            console.warn('[DataLayer] 通知回调失败:', error)
          }
        })
        this.pendingNotify = null
      }
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
      versions: { ...this.state.version },
    }
  }

  // ========== 重置 ==========

  reset() {
    this.state.raw = { stocks: [], platforms: {}, themes: [], fullMarket: [] }
    this.state.realtime = { quotes: new Map(), lastUpdate: null }
    this.state.merged = { stocks: [], themes: [] }
    this.state.leader = {
      byCode: new Map(),
      byLevel: {},
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

  clear() {
    this.reset()
  }

  private formatSnapshotKey(type: string, date: Date, dateOnly: boolean = false): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    const dateStr = `${year}-${month}-${day}`

    if (dateOnly) {
      return `[${type}] ${dateStr}`
    }

    const hour = String(date.getHours()).padStart(2, '0')
    const minute = String(date.getMinutes()).padStart(2, '0')
    return `[${type}] ${dateStr} ${hour}:${minute}`
  }

  /**
   * 保存15分钟快照（一刻钟）
   */
  async saveQuarterHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const now = snapshotTime || new Date()
      const key = this.formatSnapshotKey('一刻快照', now)

      const stocks = this.getStocks()
      const breathData = this.getBreathData()
      const jxbkBlocks = this.getJxbkBlocksSorted(50)
      const marketData = this.state.analysis.breath?.marketData

      const snapshot = {
        date: key,
        timestamp: now.getTime(),
        type: 'quarter_hour',

        // ========== 元数据（用于回测） ==========
        metadata: {
          version: '2.0', // 数据版本号，便于后续数据迁移
          totalStocks: stocks.length, // 总股票数量，用于计算百分位
          marketMode: this.state.meta.marketMode,
          dataVersion: this.state.version.stocks,
          timestamp: now.getTime(),
        },

        hotlist: stocks.map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          avgRank: stock.avgRank,
          rank: index + 1,

          // ========== 价格和成交量数据 ==========
          price: stock.price,
          change: stock.change,
          volume: stock.volume,
          turnover: stock.turnover,
          turnoverRate: stock.turnoverRate,
          totalMV: stock.totalMV,
          cirMV: stock.cirMV,
          zlje: stock.zlje,
          zljzb: stock.zljzb,
          cddje: stock.cddje,
          cddjzb: stock.cddjzb,
          pe: stock.pe,
          pb: stock.pb,

          // ========== 技术指标（用于回测验证） ==========
          technicalIndicators: {
            // 移动平均
            ma5: stock.ma5 || 0,
            ma10: stock.ma10 || 0,
            maTrend: stock.maTrend || 'steady',

            // MACD完整数据
            macd: stock.macd || 0,
            macdSignal: stock.macdSignal || 0,
            macdHistogram: stock.macdHistogram || 0,
            macdCross: stock.macdCross || 'none',

            // 排名百分位（实时计算）
            percentile: ((stocks.length - (index + 1) + 1) / stocks.length) * 100,

            // 资金相关
            fundPenetration: stock.fundPenetration || 0,
          },

          // JXBK数据
          volumeRatio: stock.volumeRatio,
          speed: stock.speed,
          leadStatus: stock.leadStatus,
          lianbanStr: stock.lianbanStr,
          fengdan: stock.fengdan,
          popularity: stock.popularity,
          popularityChange: stock.popularityChange,

          // 涨停数据
          isNew: stock.isNew,
          firstZtTime: stock.firstZtTime,
          lastZtTime: stock.lastZtTime,
          boardHeight: stock.boardHeight,
          highDays: stock.highDays,

          // 热度数据
          hotness: stock.hotness,
          tags: stock.tags,
          reason: stock.reason,

          // 排名变化
          rankChange: stock.rankChange,

          // 题材
          mainTheme: stock.mainTheme,
          themeHeat: stock.themeHeat,
          themeLevel: stock.themeLevel,

          // ========== 排名趋势信号 ==========
          signals: {
            direction: {
              signal: stock.directionSignal || 'none',
              confidence: stock.directionConfidence || 0,
            },
            acceleration: {
              signal: stock.accelerationSignal || 'none',
              confidence: stock.accelerationConfidence || 0,
            },
            cross: {
              signal: stock.crossSignal || 'none',
              confidence: stock.crossConfidence || 0,
            },
            final: {
              signal: stock.finalSignal || 'none',
              confidence: stock.finalConfidence || 0,
            },
          },
        })),

        sectors: jxbkBlocks.map((block: any) => ({
          code: block.code,
          name: block.name,
          strength: block.strength,
          change: block.change,
          mainNetInflow: block.mainNetInflow,
          bigMoney300: block.bigMoney300,
          institutionBuy: block.institutionBuy,
          volumeRatio: block.volumeRatio,
          ztCount: block.ztCount,
        })),

        sentiment: {
          overall: breathData?.overall || 50,
          phase: breathData?.phase || '震荡期',
          phaseName: breathData?.phaseName || '平稳期',
          emotionValue: marketData?.emotionValue || 50,
        },

        moneyFlow: {
          main: marketData?.moneyFlow?.main || 0,
          retail: marketData?.moneyFlow?.retail || 0,
        },

        marketStats: {
          upCount: marketData?.upCount || 0,
          downCount: marketData?.downCount || 0,
          ztCount: marketData?.ztCount || 0,
          dtCount: marketData?.dtCount || 0,
          totalAmo: marketData?.totalAmo || 0,
        },
      }

      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      await this.saveToIndexedDB(cleanSnapshot)
      console.log(`[DataLayer] ✅ 一刻快照已保存 (v2.0): ${key}, 股票数: ${stocks.length}`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存一刻快照失败:', error)
      return false
    }
  }

  /**
   * 保存30分钟快照
   */
  async saveHalfHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const now = snapshotTime || new Date()
      const key = this.formatSnapshotKey('半点快照', now)

      const stocks = this.getStocks()
      const breathData = this.getBreathData()
      const marketData = this.state.analysis.breath?.marketData
      const jxbkBlocks = this.getJxbkBlocksSorted(50)

      const snapshot = {
        date: key,
        timestamp: now.getTime(),
        type: 'half_hour',

        // ========== 元数据（用于回测） ==========
        metadata: {
          version: '2.0', // 数据版本号，便于后续数据迁移
          totalStocks: stocks.length, // 总股票数量，用于计算百分位
          marketMode: this.state.meta.marketMode,
          dataVersion: this.state.version.stocks,
          timestamp: now.getTime(),
        },

        hotlist: stocks.map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          avgRank: stock.avgRank,
          rank: index + 1,

          // ========== 价格和成交量数据 ==========
          price: stock.price,
          change: stock.change,
          volume: stock.volume,
          turnover: stock.turnover,
          turnoverRate: stock.turnoverRate,
          totalMV: stock.totalMV,
          cirMV: stock.cirMV,
          zlje: stock.zlje,
          zljzb: stock.zljzb,
          cddje: stock.cddje,
          cddjzb: stock.cddjzb,
          pe: stock.pe,
          pb: stock.pb,

          // ========== 技术指标（用于回测验证） ==========
          technicalIndicators: {
            // 移动平均
            ma5: stock.ma5 || 0,
            ma10: stock.ma10 || 0,
            maTrend: stock.maTrend || 'steady',

            // MACD完整数据
            macd: stock.macd || 0,
            macdSignal: stock.macdSignal || 0,
            macdHistogram: stock.macdHistogram || 0,
            macdCross: stock.macdCross || 'none',

            // 排名百分位（实时计算）
            percentile: ((stocks.length - (index + 1) + 1) / stocks.length) * 100,

            // 资金相关
            fundPenetration: stock.fundPenetration || 0,
          },

          // JXBK数据
          volumeRatio: stock.volumeRatio,
          speed: stock.speed,
          leadStatus: stock.leadStatus,
          lianbanStr: stock.lianbanStr,
          fengdan: stock.fengdan,
          popularity: stock.popularity,
          popularityChange: stock.popularityChange,
          institutionBuy: stock.institutionBuy,
          bigMoney300: stock.bigMoney300,
          themes: stock.themes?.slice(0, 10).map((t: any) => ({
            id: t.id,
            name: t.name,
            heatScore: t.heatScore,
          })),

          // 涨停数据
          isNew: stock.isNew,
          firstZtTime: stock.firstZtTime,
          lastZtTime: stock.lastZtTime,
          boardHeight: stock.boardHeight,
          highDays: stock.highDays,

          // 热度数据
          hotness: stock.hotness,
          tags: stock.tags,
          reason: stock.reason,

          // 排名变化
          rankChange: stock.rankChange,

          // 题材
          mainTheme: stock.mainTheme,
          themeHeat: stock.themeHeat,
          themeLevel: stock.themeLevel,

          // ========== 排名趋势信号 ==========
          signals: {
            direction: {
              signal: stock.directionSignal || 'none',
              confidence: stock.directionConfidence || 0,
            },
            acceleration: {
              signal: stock.accelerationSignal || 'none',
              confidence: stock.accelerationConfidence || 0,
            },
            cross: {
              signal: stock.crossSignal || 'none',
              confidence: stock.crossConfidence || 0,
            },
            final: {
              signal: stock.finalSignal || 'none',
              confidence: stock.finalConfidence || 0,
            },
          },
        })),

        sectors: jxbkBlocks.map((block: any) => ({
          code: block.code,
          name: block.name,
          strength: block.strength,
          change: block.change,
          mainNetInflow: block.mainNetInflow,
          bigMoney300: block.bigMoney300,
          institutionBuy: block.institutionBuy,
          volumeRatio: block.volumeRatio,
          ztCount: block.ztCount,
        })),

        sentiment: {
          overall: breathData?.overall || 50,
          phase: breathData?.phase || '震荡期',
          phaseName: breathData?.phaseName || '平稳期',
          emotionValue: marketData?.emotionValue || 50,
        },

        moneyFlow: {
          main: marketData?.moneyFlow?.main || 0,
          retail: marketData?.moneyFlow?.retail || 0,
        },

        marketStats: {
          upCount: marketData?.upCount || 0,
          downCount: marketData?.downCount || 0,
          ztCount: marketData?.ztCount || 0,
          dtCount: marketData?.dtCount || 0,
          totalAmo: marketData?.totalAmo || 0,
        },
      }

      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      await this.saveToIndexedDB(cleanSnapshot)
      console.log(`[DataLayer] ✅ 半点快照已保存 (v2.0): ${key}, 股票数: ${stocks.length}`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存半点快照失败:', error)
      return false
    }
  }

  /**
   * 保存60分钟快照（整点快照）
   */
  async saveHourlySnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const now = snapshotTime || new Date()

      const key = this.formatSnapshotKey('整点快照', now)

      const stocks = this.getStocks()
      const breathData = this.getBreathData()
      const marketData = this.state.analysis.breath?.marketData
      const jxbkBlocks = this.getJxbkBlocksSorted(100)
      const jxbkStocks = this.state.theme.jxbk.stockMap || {}

      const limitUpStocks = Object.values(jxbkStocks)
        .filter((s: any) => {
          const change = s.change || 0
          const code = s.code || ''
          const name = s.name || ''
          return StockUtils.isLimitUp(change, code, name)
        })
        .slice(0, 50)
        .map((s: any) => ({
          code: s.code,
          name: s.name,
          change: s.change,
          lianbanStr: s.lianban,
          leadStatus: s.leadStatus,
          fengdan: s.fengdan,
        }))

      const snapshot = {
        date: key,
        timestamp: now.getTime(),
        type: 'hourly',

        // ========== 元数据（用于回测） ==========
        metadata: {
          version: '2.0', // 数据版本号，便于后续数据迁移
          totalStocks: stocks.length, // 总股票数量，用于计算百分位
          marketMode: this.state.meta.marketMode,
          dataVersion: this.state.version.stocks,
          timestamp: now.getTime(),
        },

        hotlist: stocks.slice(0, 100).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
          avgRank: stock.avgRank,

          // ========== 价格和成交量数据 ==========
          price: stock.price,
          change: stock.change,
          volume: stock.volume,
          turnover: stock.turnover,
          turnoverRate: stock.turnoverRate,
          totalMV: stock.totalMV,
          cirMV: stock.cirMV,
          zlje: stock.zlje,
          zljzb: stock.zljzb,
          cddje: stock.cddje,
          cddjzb: stock.cddjzb,
          pe: stock.pe,
          pb: stock.pb,

          // ========== 技术指标（用于回测验证） ==========
          technicalIndicators: {
            // 移动平均
            ma5: stock.ma5 || 0,
            ma10: stock.ma10 || 0,
            maTrend: stock.maTrend || 'steady',

            // MACD完整数据
            macd: stock.macd || 0,
            macdSignal: stock.macdSignal || 0,
            macdHistogram: stock.macdHistogram || 0,
            macdCross: stock.macdCross || 'none',

            // 排名百分位（实时计算）
            percentile: ((stocks.length - (index + 1) + 1) / stocks.length) * 100,

            // 资金相关
            fundPenetration: stock.fundPenetration || 0,
          },

          // 核心JXBK数据
          volumeRatio: stock.volumeRatio,
          leadStatus: stock.leadStatus,
          lianbanStr: stock.lianbanStr,
          fengdan: stock.fengdan,

          // 涨停数据
          isNew: stock.isNew,
          firstZtTime: stock.firstZtTime,
          lastZtTime: stock.lastZtTime,
          boardHeight: stock.boardHeight,
          highDays: stock.highDays,

          // 排名变化
          rankChange: stock.rankChange,

          // 题材
          mainTheme: stock.mainTheme,
          themeHeat: stock.themeHeat,

          // ========== 排名趋势信号（整点快照也保存完整信号） ==========
          signals: {
            direction: {
              signal: stock.directionSignal || 'none',
              confidence: stock.directionConfidence || 0,
            },
            acceleration: {
              signal: stock.accelerationSignal || 'none',
              confidence: stock.accelerationConfidence || 0,
            },
            cross: {
              signal: stock.crossSignal || 'none',
              confidence: stock.crossConfidence || 0,
            },
            final: {
              signal: stock.finalSignal || 'none',
              confidence: stock.finalConfidence || 0,
            },
          },
        })),

        sectors: jxbkBlocks.map((block: any) => ({
          code: block.code,
          name: block.name,
          strength: block.strength,
          change: block.change,
          mainNetInflow: block.mainNetInflow,
          bigMoney300: block.bigMoney300,
          institutionBuy: block.institutionBuy,
          volumeRatio: block.volumeRatio,
          ztCount: block.ztCount,
        })),

        limitUpStocks,

        sentiment: {
          overall: breathData?.overall || 50,
          phase: breathData?.phase || '震荡期',
          phaseName: breathData?.phaseName || '平稳期',
          emotionValue: marketData?.emotionValue || 50,
        },

        marketStats: {
          upCount: marketData?.upCount || 0,
          downCount: marketData?.downCount || 0,
          ztCount: marketData?.ztCount || 0,
          dtCount: marketData?.dtCount || 0,
          totalAmo: marketData?.totalAmo || 0,
          zhabanRate: marketData?.zhaban?.rate || 0,
        },

        zhaban: {
          count: marketData?.zhaban?.count || 0,
          rate: marketData?.zhaban?.rate || 0,
          fengbanRate: marketData?.zhaban?.fengbanRate || 0,
        },

        moneyFlow: {
          main: marketData?.moneyFlow?.main || 0,
          retail: marketData?.moneyFlow?.retail || 0,
          cddje: marketData?.cddje || 0,
        },

        continuousBoards: {
          board1: marketData?.limitData?.yiban || 0,
          board2: marketData?.limitData?.erban || 0,
          board3: marketData?.limitData?.sanban || 0,
          board4plus: marketData?.limitData?.sibanPlus || 0,
        },
      }

      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      await this.saveToIndexedDB(cleanSnapshot)
      console.log(
        `[DataLayer] ✅ 整点快照已保存 (v2.0): ${key}, 股票数: ${Math.min(stocks.length, 100)}`,
      )
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存小时快照失败:', error)
      return false
    }
  }

  /**
   * 生成每日快照 - 按功能模块分类
   */
  generateDailySnapshot(): any {
    const now = new Date()
    const dateStr = now.toISOString().slice(0, 10)

    // ========== 1. 获取基础数据 ==========
    const breathData = this.getBreathData()
    const marketData = this.state.analysis.breath?.marketData
    const jxbkStocks = this.state.theme.jxbk.stockMap || {}
    const jxbkBlocks = this.state.theme.jxbk.blocks || []
    const allStocks = this.getStocks() || []
    const hotThemes = this.getHotThemes() || []
    const rotationAnalysis = this.state.analysis.rotation?.current || null
    const themeCorrelations = this.state.theme.correlation?.byTheme || new Map()

    // 辅助：股价映射
    const priceMap = new Map(allStocks.map((s) => [s.code, s.price]))

    // ========== 2. 市场情绪数据 ==========
    const sentiment = {
      overall: breathData?.overall || 0,
      phase: breathData?.phase || '',
      phaseName: breathData?.phaseName || '',
      riskLevel: breathData?.riskLevel || '',
      suggestion: breathData?.suggestion || '',
      factorScores: breathData?.factorScores || {},
      history: this.getBreathHistory(),
      factors: this.getBreathFactors(),
    }

    // ========== 3. 市场统计 ==========
    const marketStats = {
      upCount: marketData?.upCount || 0,
      downCount: marketData?.downCount || 0,
      ztCount: marketData?.ztCount || 0,
      dtCount: marketData?.dtCount || 0,
      totalAmo: marketData?.totalAmo || 0,
      volumeRatio: marketData?.volumeRatio || 0,
      emotionValue: marketData?.emotionValue || 0,
      emotionStatus: marketData?.emotionStatus || '震荡',
    }

    // ========== 4. 涨停相关数据 ==========
    const limitData = {
      // 连板梯队
      continuousBoards: {
        board1: marketData?.limitData?.yiban ?? 0,
        board2: marketData?.limitData?.erban ?? 0,
        board3: marketData?.limitData?.sanban ?? 0,
        board4plus: marketData?.limitData?.sibanPlus ?? 0,
      },
      // 炸板数据
      zhaban: {
        count: marketData?.zhaban?.count || 0,
        rate: marketData?.zhaban?.rate || 0,
        fengbanRate: marketData?.zhaban?.fengbanRate || 0,
      },
      // 昨日涨停表现
      yesterdayZt: {
        total: marketData?.yesterdayLimit?.total || 0,
        dtCount: marketData?.yesterdayLimit?.dtCount || 0,
        bigLossCount: marketData?.yesterdayLimit?.bigLossCount || 0,
        redCount: marketData?.yesterdayLimit?.redCount || 0,
        greenCount: marketData?.yesterdayLimit?.greenCount || 0,
        avgChange: marketData?.yesterdayLimit?.avgChange || 0,
        maxChange: marketData?.yesterdayLimit?.maxChange || 0,
        minChange: marketData?.yesterdayLimit?.minChange || 0,
      },
    }

    // ========== 5. 资金流向 ==========
    const moneyFlow = {
      main: marketData?.moneyFlow?.main || 0,
      retail: marketData?.moneyFlow?.retail || 0,
      cddje: marketData?.cddje || 0,
      cddjzb: marketData?.cddjzb || 0,
    }

    // ========== 6. 指数表现 ==========
    const indices = {
      sh: marketData?.indices?.sh?.change || 0,
      sz: marketData?.indices?.sz?.change || 0,
      cy: marketData?.indices?.cy?.change || 0,
      hs300: marketData?.indices?.hs300?.change || 0,
      zz500: marketData?.indices?.zz500?.change || 0,
      zz1000: marketData?.indices?.zz1000?.change || 0,
    }

    // ========== 7. 龙头股数据（来自 JXBK 领涨股） ==========
    const leaders = Object.values(jxbkStocks)
      .filter((s: any) => s.leadStatus?.includes('龙'))
      .sort((a: any, b: any) => {
        const rankMap: Record<string, number> = { 龙一: 1, 龙二: 2, 龙三: 3 }
        const aRank = rankMap[a.leadStatus] || 4
        const bRank = rankMap[b.leadStatus] || 4
        return aRank - bRank
      })
      .map((stock: any) => {
        const block = jxbkBlocks.find((b: any) => stock.blocks?.includes(b.name))
        return {
          code: stock.code,
          name: stock.name,
          level: stock.leadStatus,
          change: stock.change,
          price: priceMap.get(stock.code) || 0,
          lianbanStr: stock.lianban,
          block: block?.name || '',
          blockStrength: block?.strength || 0,
          mainNetInflow: stock.mainNetInflow,
          fengdan: stock.fengdan,
        }
      })

    // ========== 8. 板块数据（按强度排序） ==========
    const sectors = [...jxbkBlocks]
      .sort((a, b) => b.strength - a.strength)
      .map((block) => ({
        code: block.code,
        name: block.name,
        strength: block.strength,
        change: block.change,
        mainNetInflow: block.mainNetInflow,
        ztCount: block.ztCount,
      }))

    // ========== 9. 涨停股列表 ==========
    const limitUpStocks = allStocks
      .filter((s) => StockUtils.isLimitUp(s.change || 0, s.code, s.name))
      .map((stock) => ({
        code: stock.code,
        name: stock.name,
        change: stock.change,
        price: stock.price,
        lianbanStr: stock.lianbanStr,
        leadStatus: stock.leadStatus,
        fengdan: stock.fengdan,
        firstZtTime: stock.firstZtTime,
      }))

    // ========== 10. 热门题材（前20） ==========
    const topThemes = hotThemes.slice(0, 20).map((t: any, i: number) => ({
      rank: i + 1,
      name: t.name,
      heatScore: t.heatScore,
      heatLevel: t.heatLevel,
      ztCount: t.ztCount,
      leaderCount: t.leaderCount,
    }))

    // ========== 11. 热榜股票 ==========
    const hotlist = [...allStocks]
      .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
      .map((s) => ({
        code: s.code,
        name: s.name,
        rank: s.compRank,
        avgRank: s.avgRank,
        price: s.price,
        change: s.change,
        turnover: s.turnover,
        turnoverRate: s.turnoverRate,
        zlje: s.zlje,
        volume: s.volume,
        volumeRatio: s.volumeRatio,
        leadStatus: s.leadStatus,
        lianbanStr: s.lianbanStr,
        fengdan: s.fengdan,
        finalSignal: s.finalSignal,
        finalConfidence: s.finalConfidence,
        macdCross: s.macdCross,
        themes:
          s.themes
            ?.slice(0, 10)
            .map((t: any) => t.name)
            .filter(Boolean) || [],
      }))

    // ========== 12. 轮动分析 ==========
    const rotation = rotationAnalysis
      ? {
          marketPhase: rotationAnalysis.marketPhase,
          rotationSpeed: rotationAnalysis.rotationSpeed,
          mainLines: rotationAnalysis.mainLines?.map((m: any) => ({
            themeName: m.themeName,
            persistentDays: m.persistentDays,
            netInflow: m.netInflow,
            ztCount: m.ztCount,
          })),
          suggestion: rotationAnalysis.summary?.suggestion || '',
        }
      : null

    // ========== 13. 返回完整快照 ==========
    return {
      // 元数据
      date: `[日级快照] ${dateStr}`,
      timestamp: Date.now(),
      type: 'daily',

      // 情绪数据
      sentiment,

      // 市场数据
      market: marketStats,
      indices,
      moneyFlow,

      // 涨停数据
      limit: limitData.continuousBoards,
      zhaban: limitData.zhaban,
      yesterdayZt: limitData.yesterdayZt,
      limitUpStocks,

      // 板块和题材
      sectors,
      hotThemes: topThemes,

      // 龙头和热榜
      leaders,
      hotlist,

      // 轮动分析
      rotation,

      // 统计
      stats: {
        totalStocks: allStocks.length,
        totalLeaders: leaders.length,
        totalSectors: sectors.length,
        totalLimitUpStocks: limitUpStocks.length,
        timestamp: Date.now(),
      },
    }
  }

  /**
   * 导出每日快照（JSON格式）
   */
  exportDailySnapshot(): string {
    const snapshot = this.generateDailySnapshot()
    return JSON.stringify(snapshot, null, 2)
  }

  /**
   * 导出指定股票的一刻快照数据
   * @param stockCode 股票代码
   * @param stockName 股票名称（可选，用于文件名）
   * @returns 是否成功
   */
  async exportStockQuarterSnapshots(stockCode: string, stockName: string = ''): Promise<boolean> {
    try {
      // 1. 获取所有快照的 key 列表
      const allKeys = await this.getSnapshotDates()
      const quarterSnapshots = allKeys.filter((key) => key.includes('一刻快照'))

      if (quarterSnapshots.length === 0) {
        console.warn('[DataLayer] 没有一刻快照数据')
        return false
      }

      const stockData: any[] = []

      // 2. 遍历所有一刻快照，提取该股票的数据
      for (const snapKey of quarterSnapshots) {
        const snapshot = await this.getSnapshotFromDB(snapKey)
        if (snapshot && snapshot.hotlist) {
          const stock = snapshot.hotlist.find((s: any) => s.code === stockCode)
          if (stock) {
            stockData.push({
              快照时间: snapKey.replace('[一刻快照] ', ''),
              代码: stock.code,
              名称: stock.name || stockName,
              价格: stock.price,
              '涨幅%': stock.change,
              热度: stock.avgRank,
              排名: stock.rank,
              变化: stock.rankChange,
              成交量: stock.volume,
              成交额: stock.turnover,
              '换手率%': stock.turnoverRate,
              主力净额: stock.zlje,
              量比: stock.volumeRatio,
              领涨状态: stock.leadStatus,
              连板: stock.lianbanStr,
              封单额: stock.fengdan,
              方向一致性: stock.signals?.direction?.signal || '',
              动量加速度: stock.signals?.acceleration?.signal || '',
              零线交叉: stock.signals?.cross?.signal || '',
              最终信号: stock.signals?.final?.signal,
              最终置信度: stock.signals?.final?.confidence,
              MACD金叉: stock.macdCross,
            })
          }
        }
      }

      if (stockData.length === 0) {
        console.warn(`[DataLayer] 未找到股票 ${stockCode} 的一刻快照数据`)
        return false
      }

      // 3. 导出为 CSV 文件
      const headers = Object.keys(stockData[0])
      const csvRows: string[] = [headers.join(',')]

      for (const row of stockData) {
        const escapedRow = headers
          .map((header) => {
            let val = row[header]
            if (val === undefined || val === null) return ''
            const str = String(val)
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
              return `"${str.replace(/"/g, '""')}"`
            }
            return str
          })
          .join(',')
        csvRows.push(escapedRow)
      }

      const csv = csvRows.join('\n')
      const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${stockCode}_${stockName || 'stock'}_quarter_snapshots.csv`
      link.click()
      URL.revokeObjectURL(url)

      console.log(`[DataLayer] ✅ 已导出 ${stockData.length} 条记录`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 导出股票一刻快照失败:', error)
      return false
    }
  }

  /**
   * 导出快照数据为 Excel（CSV格式，Excel可打开）
   * @param snapshotKey 快照的key（如 '[日级快照] 2026-03-22' 或 '[一刻快照] 2026-03-22 14:30'）
   * @param options 导出选项
   */
  async exportSnapshotToExcel(
    snapshotKey: string,
    options?: {
      sheets?: ('hotlist' | 'sectors' | 'sentiment' | 'market')[]
      filename?: string
    },
  ): Promise<boolean> {
    try {
      // 1. 获取快照数据
      const snapshot = await this.getSnapshotFromDB(snapshotKey)
      if (!snapshot) {
        console.error(`[DataLayer] ❌ 未找到快照: ${snapshotKey}`)
        console.log(
          '提示：快照key格式应为 "[日级快照] 2026-03-22" 或 "[一刻快照] 2026-03-22 14:30"',
        )
        return false
      }

      // 2. 默认导出所有工作表
      const sheets = options?.sheets || ['hotlist', 'sectors', 'sentiment', 'market']
      const filename = options?.filename || `${snapshotKey.replace(/[\[\] :]/g, '_')}_export`

      // 3. 构建 CSV 内容
      const csvParts: string[] = []
      const sheetTitles: string[] = []

      // 3.1 热榜数据工作表
      if (sheets.includes('hotlist') && snapshot.hotlist?.length) {
        sheetTitles.push('热榜')
        const headers = [
          '排名',
          '代码',
          '名称',
          '价格',
          '涨幅%',
          '成交额',
          '换手率%',
          '总市值',
          '流通市值',
          '主力净额',
          '主力占比',
          '超大单净额',
          '超大单占比',
          '市盈率',
          '市净率',
          '量比',
          '涨速',
          '领涨状态',
          '连板',
          '封单额',
          '人气排名',
          '人气变化',
          '首次涨停',
          '最后涨停',
          '连板天数',
          '热度值',
          '标签',
          '涨停原因',
          '排名变化',
          '资金穿透',
          '主要题材',
          '题材热度',
          '题材等级',
          '方向信号',
          '方向置信度',
          '加速信号',
          '加速置信度',
          '交叉信号',
          '交叉置信度',
          '最终信号',
          '最终置信度',
          'MACD信号',
        ]

        const rows = snapshot.hotlist.map((stock: any, idx: number) => [
          stock.rank || idx + 1,
          stock.code || '',
          stock.name || '',
          stock.price || 0,
          stock.change || 0,
          stock.turnover || 0,
          stock.turnoverRate || 0,
          stock.totalMV || 0,
          stock.cirMV || 0,
          stock.zlje || 0,
          stock.zljzb || 0,
          stock.cddje || 0,
          stock.cddjzb || 0,
          stock.pe || 0,
          stock.pb || 0,
          stock.volumeRatio || 0,
          stock.speed || 0,
          stock.leadStatus || '',
          stock.lianbanStr || '',
          stock.fengdan || 0,
          stock.popularity || 0,
          stock.popularityChange || 0,
          stock.firstZtTime || '',
          stock.lastZtTime || '',
          stock.highDays || 0,
          stock.hotness || 0,
          Array.isArray(stock.tags)
            ? stock.tags.map((t: any) => t.Name || t).join(';')
            : stock.tags || '',
          stock.reason || '',
          stock.rankChange || 0,
          stock.fundPenetration || 0,
          stock.mainTheme || '',
          stock.themeHeat || 0,
          stock.themeLevel || '',
          stock.signals?.direction?.signal || '',
          stock.signals?.direction?.confidence || 0,
          stock.signals?.acceleration?.signal || '',
          stock.signals?.acceleration?.confidence || 0,
          stock.signals?.cross?.signal || '',
          stock.signals?.cross?.confidence || 0,
          stock.signals?.final?.signal || '',
          stock.signals?.final?.confidence || 0,
          stock.macdCross,
        ])

        csvParts.push(this.arrayToCSV([headers, ...rows]))
      }

      // 3.2 板块数据工作表
      if (sheets.includes('sectors') && snapshot.sectors?.length) {
        sheetTitles.push('板块')
        const headers = [
          '代码',
          '名称',
          '强度',
          '涨幅%',
          '主力净额',
          '300W大单',
          '机构增仓',
          '量比',
          '涨停数',
        ]
        const rows = snapshot.sectors.map((sector: any) => [
          sector.code || '',
          sector.name || '',
          sector.strength || 0,
          sector.change || 0,
          sector.mainNetInflow || 0,
          sector.bigMoney300 || 0,
          sector.institutionBuy || 0,
          sector.volumeRatio || 0,
          sector.ztCount || 0,
        ])
        csvParts.push(this.arrayToCSV([headers, ...rows]))
      }

      // 3.3 情绪数据工作表
      if (sheets.includes('sentiment') && snapshot.sentiment) {
        sheetTitles.push('情绪')
        const headers = ['字段', '值']
        const rows = [
          ['情绪得分', snapshot.sentiment.overall || 50],
          ['情绪阶段', snapshot.sentiment.phaseName || '平稳期'],
          ['情绪代码', snapshot.sentiment.phase || 'stable'],
          ['情绪值', snapshot.sentiment.emotionValue || 50],
        ]
        csvParts.push(this.arrayToCSV([headers, ...rows]))
      }

      // 3.4 市场数据工作表
      if (sheets.includes('market') && snapshot.marketStats) {
        sheetTitles.push('市场')
        const headers = ['字段', '值']
        const rows = [
          ['上涨家数', snapshot.marketStats.upCount || 0],
          ['下跌家数', snapshot.marketStats.downCount || 0],
          ['涨停家数', snapshot.marketStats.ztCount || 0],
          ['跌停家数', snapshot.marketStats.dtCount || 0],
          ['成交额(亿)', ((snapshot.marketStats.totalAmo || 0) / 1e8).toFixed(0)],
          ['主力净额', snapshot.moneyFlow?.main || 0],
          ['散户净额', snapshot.moneyFlow?.retail || 0],
        ]
        csvParts.push(this.arrayToCSV([headers, ...rows]))
      }

      // 4. 合并多个工作表（用分隔符区分）
      let finalCSV = ''
      for (let i = 0; i < csvParts.length; i++) {
        if (i > 0) {
          finalCSV += `\n\n========== ${sheetTitles[i]} ==========\n\n`
        }
        finalCSV += csvParts[i]
      }

      // 5. 下载文件
      const blob = new Blob(['\uFEFF' + finalCSV], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `${filename}.csv`
      link.click()
      URL.revokeObjectURL(url)

      console.log(`[DataLayer] ✅ 已导出 Excel: ${filename}.csv`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 导出失败:', error)
      return false
    }
  }

  /**
   * 导出指定日期范围的所有快照为 Excel
   * @param startDate 开始日期 (YYYY-MM-DD)
   * @param endDate 结束日期 (YYYY-MM-DD)
   */
  async exportSnapshotsRangeToExcel(startDate: string, endDate: string): Promise<boolean> {
    try {
      const allDates = await this.getSnapshotDates()
      // 过滤日期范围内的快照（快照key格式为 "[日级快照] 2026-03-22"）
      const filteredDates = allDates.filter((date) => {
        const match = date.match(/\[\w+\]\s+(\d{4}-\d{2}-\d{2})/)
        if (!match) return false
        const dateStr = match[1]
        return dateStr >= startDate && dateStr <= endDate
      })

      if (filteredDates.length === 0) {
        console.warn('[DataLayer] 指定范围内没有快照')
        return false
      }

      const allData: any[] = []

      for (const dateKey of filteredDates) {
        const snapshot = await this.getSnapshotFromDB(dateKey)
        if (snapshot?.hotlist) {
          snapshot.hotlist.forEach((stock: any) => {
            allData.push({
              快照时间: dateKey,
              排名: stock.rank,
              代码: stock.code,
              名称: stock.name,
              价格: stock.price,
              '涨幅%': stock.change,
              成交额: stock.turnover,
              '换手率%': stock.turnoverRate,
              主力净额: stock.zlje,
              量比: stock.volumeRatio,
              领涨状态: stock.leadStatus,
              连板: stock.lianbanStr,
              最终信号: stock.signals?.final?.signal,
              最终置信度: stock.signals?.final?.confidence,
            })
          })
        }
      }

      if (allData.length === 0) {
        console.warn('[DataLayer] 没有数据可导出')
        return false
      }

      // 转换为 CSV
      const headers = Object.keys(allData[0])
      const rows = allData.map((row) => headers.map((h) => row[h]))
      const csv = this.arrayToCSV([headers, ...rows])

      const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `snapshots_${startDate}_to_${endDate}.csv`
      link.click()
      URL.revokeObjectURL(url)

      console.log(`[DataLayer] ✅ 已导出 ${allData.length} 条记录`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 导出失败:', error)
      return false
    }
  }

  /**
   * 数组转 CSV
   */
  private arrayToCSV(data: any[][]): string {
    return data
      .map((row) =>
        row
          .map((cell) => {
            if (cell === undefined || cell === null) return ''
            const str = String(cell)
            if (str.includes(',') || str.includes('"') || str.includes('\n')) {
              return `"${str.replace(/"/g, '""')}"`
            }
            return str
          })
          .join(','),
      )
      .join('\n')
  }

  /**
   * 保存每日快照到 IndexedDB
   */
  async saveDailySnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const now = snapshotTime || new Date()
      const key = this.formatSnapshotKey('日级快照', now, true)

      const snapshot = this.generateDailySnapshot()
      snapshot.date = key
      snapshot.type = 'daily'

      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      await this.saveToIndexedDB(cleanSnapshot)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存失败:', error)
      return false
    }
  }

  // ========== IndexedDB 操作 ==========
  private async openSnapshotDB(): Promise<IDBDatabase> {
    const DB_NAME = 'DragonBoardData'
    const DB_VERSION = 2
    const STORE_NAME = 'daily_snapshots'

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(DB_NAME, DB_VERSION)

      request.onerror = () => {
        console.error('[DataLayer] 打开数据库失败:', request.error)
        reject(request.error)
      }

      request.onsuccess = () => {
        resolve(request.result)
      }

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result
        if (!db.objectStoreNames.contains(STORE_NAME)) {
          const store = db.createObjectStore(STORE_NAME, { keyPath: 'date' })
          store.createIndex('date', 'date', { unique: true })
          store.createIndex('timestamp', 'timestamp')
        } else {
          // ✅ 版本升级但表已存在，不需要操作
          console.log('[DataLayer] IndexedDB 表已存在，版本升级')
        }
      }
    })
  }

  private async saveToIndexedDB(snapshot: any): Promise<void> {
    const db = await this.openSnapshotDB()
    const STORE_NAME = 'daily_snapshots'

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([STORE_NAME], 'readwrite')
      const store = transaction.objectStore(STORE_NAME)
      const request = store.put(snapshot)

      request.onerror = () => {
        console.error('[DataLayer] 保存失败:', request.error)
        reject(request.error)
      }

      request.onsuccess = () => {
        resolve()
      }

      transaction.oncomplete = () => {
        db.close()
      }

      transaction.onerror = () => {
        console.error('[DataLayer] 事务失败:', transaction.error)
        reject(transaction.error)
      }
    })
  }

  async getSnapshotFromDB(date: string): Promise<any | null> {
    try {
      const db = await this.openSnapshotDB()
      const STORE_NAME = 'daily_snapshots'

      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly')
        const store = transaction.objectStore(STORE_NAME)
        const request = store.get(date)

        request.onerror = () => {
          console.error('[DataLayer] 读取失败:', request.error)
          reject(request.error)
        }

        request.onsuccess = () => {
          db.close()
          resolve(request.result || null)
        }
      })
    } catch (error) {
      console.error('[DataLayer] 打开数据库失败:', error)
      return null
    }
  }

  async getSnapshotDates(): Promise<string[]> {
    try {
      const db = await this.openSnapshotDB()
      const STORE_NAME = 'daily_snapshots'

      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readonly')
        const store = transaction.objectStore(STORE_NAME)
        const request = store.getAllKeys()

        request.onerror = () => {
          console.error('[DataLayer] 获取日期列表失败:', request.error)
          reject(request.error)
        }

        request.onsuccess = () => {
          db.close()
          const dates = request.result as string[]
          resolve(dates.sort().reverse())
        }
      })
    } catch (error) {
      console.error('[DataLayer] 打开数据库失败:', error)
      return []
    }
  }

  async getLatestSnapshot(): Promise<any | null> {
    const dates = await this.getSnapshotDates()
    if (dates.length === 0) return null
    return this.getSnapshotFromDB(dates[0])
  }

  async exportSnapshotAsFile(date: string): Promise<void> {
    const snapshot = await this.getSnapshotFromDB(date)
    if (!snapshot) {
      console.warn(`[DataLayer] 未找到 ${date} 的快照`)
      return
    }

    const jsonData = JSON.stringify(snapshot, null, 2)
    const blob = new Blob([jsonData], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `daily_${date}.json`
    link.click()
    URL.revokeObjectURL(url)
  }

  async exportAllSnapshots(): Promise<void> {
    const dates = await this.getSnapshotDates()
    if (dates.length === 0) {
      console.warn('[DataLayer] 没有快照可导出')
      return
    }
    for (const date of dates) {
      await this.exportSnapshotAsFile(date)
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }

  async deleteSnapshot(date: string): Promise<boolean> {
    try {
      const db = await this.openSnapshotDB()
      const STORE_NAME = 'daily_snapshots'

      return new Promise((resolve, reject) => {
        const transaction = db.transaction([STORE_NAME], 'readwrite')
        const store = transaction.objectStore(STORE_NAME)
        const request = store.delete(date)

        request.onerror = () => {
          console.error('[DataLayer] 删除失败:', request.error)
          reject(request.error)
        }

        request.onsuccess = () => {
          db.close()
          resolve(true)
        }
      })
    } catch (error) {
      console.error('[DataLayer] 删除失败:', error)
      return false
    }
  }

  async getSnapshotStorageStats(): Promise<{
    totalSnapshots: number
    dates: string[]
    estimatedSize: number
  }> {
    const dates = await this.getSnapshotDates()
    let estimatedSize = 0

    for (const date of dates) {
      const snapshot = await this.getSnapshotFromDB(date)
      if (snapshot) {
        estimatedSize += JSON.stringify(snapshot).length
      }
    }

    return {
      totalSnapshots: dates.length,
      dates,
      estimatedSize,
    }
  }

  // 5分钟快照
  async saveFiveMinuteSnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const now = snapshotTime || new Date()
      const key = this.formatSnapshotKey('5分钟快照', now)

      const existing = await this.getSnapshotFromDB(key)
      if (existing) return false

      const stocks = this.getStocks()
      const snapshot = {
        date: key,
        timestamp: now.getTime(),
        type: 'five_minute',
        hotlist: stocks.slice(0, 100).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
          price: stock.price,
          change: stock.change,
        })),
      }

      await this.saveToIndexedDB(snapshot)
      return true
    } catch (error) {
      console.error('[DataLayer] 保存5分钟快照失败:', error)
      return false
    }
  }

  startTimer() {
    this.timer = setInterval(() => {
      const now = new Date()
      const m = now.getMinutes()
      const s = now.getSeconds()
      const h = now.getHours()
      const key = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${h}:${m}`

      // ✅ 放宽时间窗口到30秒，避免错过整点
      if (s > 30) return

      // 检查是否在交易时间内（除了日级快照）
      const isTrading = isTradingTime(now)

      // 日级快照（15:00，无论是否在交易时间）
      if (h === 15 && m === 0 && this.lastSnapshotKey.daily !== key) {
        this.lastSnapshotKey.daily = key
        this.saveDailySnapshot()
        return // 日级快照优先级最高
      }

      // 如果不是交易时间，只保存日级快照
      if (!isTrading) return

      // 整点快照（所有交易时间的整点，不只是特定小时）
      if (m === 0 && this.lastSnapshotKey.hour !== key) {
        this.lastSnapshotKey.hour = key
        this.saveHourlySnapshot()
        return // 整点优先级高于半点
      }

      // 半点快照
      if (m === 30 && this.lastSnapshotKey.half !== key) {
        this.lastSnapshotKey.half = key
        this.saveHalfHourSnapshot()
        return // 半点优先级高于一刻
      }

      // 一刻快照
      if ((m === 15 || m === 45) && this.lastSnapshotKey.quarter !== key) {
        this.lastSnapshotKey.quarter = key
        this.saveQuarterHourSnapshot()
      }
    }, 1000)
  }

  stopTimer() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
  }
}

// 在文件末尾更新导出
export const dataLayer = new DataLayer()

if (typeof window !== 'undefined') {
  ;(window as any).dataLayer = dataLayer
}
