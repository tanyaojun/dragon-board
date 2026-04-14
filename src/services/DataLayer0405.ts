// src/services/DataLayer.ts

import { ref, reactive } from 'vue'
import { EventManager } from '../utils/eventManager'
import { AppEvents } from '../types/config'
import type { BreathData } from '../types'
import { ALERT_CONFIG } from '../config/constants'
import { SENTIMENT_SCORE_CONFIG } from '../config/constants'
import { isTradingTime } from '../utils/time'
import type { ThemeCorrelationDetail } from './ThemeCorrelationAnalyzer'
import type { RotationAnalysis } from '../types'
import type { StockAlert, AlertStats } from '../types'
import { rankTrendAnalyzer } from './RankTrendAnalyzer'
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
  private signalUpdateTimer: ReturnType<typeof setTimeout> | null = null
  private lastSnapshotKey = {
    half: '',
    quarter: '',
    hour: '',
    daily: '',
  }

  constructor() {
    this.startTimer()
    this.loadVolumeHistoryCache()
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
  private volumeHistoryCache: Map<string, number[]> = new Map()
  private volumeHistoryCacheTime: number = 0

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

    // 触发合并，更新 merged.stocks 中的龙头标记
    this.mergeToMerged()

    this.throttledNotify('leader.updated', { count: leaders.length })
    EventManager.emit('leader.updated', { count: leaders.length, timestamp: Date.now() })
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

    // 基础映射变化需要触发合并
    this.mergeToMerged()

    // 题材基础数据更新后，触发信号重新计算
    this.triggerSignalUpdate()
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

    // 需要触发合并，因为 merged.stocks 中的题材数据需要更新
    this.mergeToMerged()

    this.throttledNotify('theme.stocks.updated', { count: updates.length })
    EventManager.emit('theme.stocks.updated', {
      count: updates.length,
      timestamp: Date.now(),
    })
    // 股票题材更新后，触发信号重新计算
    this.triggerSignalUpdate()
  }

  /**
   * 更新热门题材列表
   */
  updateHotThemes(hotThemes: any[]) {
    this.state.theme.metrics.hotList = hotThemes
    this.state.theme.metrics.lastUpdate = Date.now()
    this.state.version.themes++

    this.throttledNotify('theme.hotThemes', {
      count: hotThemes.length,
      timestamp: Date.now(),
    })
    EventManager.emit('theme.hotThemes', {
      count: hotThemes.length,
      timestamp: Date.now(),
    })

    // 热门题材更新后，触发信号重新计算
    this.triggerSignalUpdate()
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
      stats: {
        stockCount: number
        ztCount: number
        leaderCount: number
      }
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
      // ✅ 获取题材名称
      const themeName = this.getThemeById(update.themeId)?.name || update.themeId

      // ✅ 从 JXBK 股票数据中统计该题材下的股票（模糊匹配）
      const themeStocks = Object.values(this.state.theme.jxbk.stockMap).filter((stock: any) => {
        if (!stock.blocks) return false
        for (let i = 0; i < stock.blocks.length; i++) {
          const block = stock.blocks[i]
          // 模糊匹配：题材名称包含板块名称，或板块名称包含题材名称
          if (block.includes(themeName) || themeName.includes(block)) {
            return true
          }
        }
        return false
      })

      // 统计龙头数量（leadStatus 包含 "龙" 或 "领涨"）
      const actualLeaderCount = themeStocks.filter(
        (stock: any) => stock.leadStatus?.includes('龙') || stock.leadStatus?.includes('领涨'),
      ).length

      // 统计涨停数
      const actualZtCount = themeStocks.filter((stock: any) => {
        const change = stock.change || 0
        const code = stock.code || ''
        const name = stock.name || ''
        return StockUtils.isLimitUp(change, code, name)
      }).length

      // 使用实际计算的数据覆盖传入的值
      const correctedStats = {
        stockCount: themeStocks.length,
        ztCount: actualZtCount,
        leaderCount: actualLeaderCount,
      }

      this.state.theme.metrics.byTheme.set(update.themeId, {
        ...update,
        stats: correctedStats,
        lastUpdate: Date.now(),
      })
    })

    this.state.version.themes++

    this.throttledNotify('theme.metrics.updated', { count: updates.length })
    EventManager.emit('theme.metrics.updated', {
      count: updates.length,
      timestamp: Date.now(),
    })

    // 题材指标更新后，触发信号重新计算
    this.triggerSignalUpdate()
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

    // jxbk 数据更新需要触发合并，因为 merged.stocks 需要这些数据
    this.mergeToMerged()
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

    // jxbk 数据更新需要触发合并
    this.mergeToMerged()
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

    // 重新合并
    this.mergeToMerged()

    this.throttledNotify('raw.stocks', data)
    EventManager.emit(AppEvents.DATA.MERGED, {
      count: this.state.merged.stocks.length,
      timestamp: Date.now(),
    })

    EventManager.emit('data:stocks-updated', {
      count: this.state.merged.stocks.length,
      version: this.state.version.stocks,
    })

    this.triggerSignalUpdate() // 触发信号更新
  }

  /**
   * 触发信号更新（当股票数据变化时自动调用）
   */
  public async triggerSignalUpdate() {
    // 避免频繁触发，使用防抖
    if (this.signalUpdateTimer) {
      clearTimeout(this.signalUpdateTimer)
    }

    this.signalUpdateTimer = setTimeout(async () => {
      try {
        // ✅ 确保 JXBK 数据已加载
        await this.ensureJxbkDataLoaded()

        const rankMap = new Map()
        this.state.merged.stocks.forEach((s) => {
          if (s.compRank) rankMap.set(s.code, s.compRank)
        })
        if (rankMap.size > 0) {
          await rankTrendAnalyzer.getRankTrends(rankMap)
          console.log('[DataLayer] 信号已自动更新')
        }
      } catch (error) {
        console.error('[DataLayer] 信号更新失败:', error)
      }
      this.signalUpdateTimer = null
    }, 500) // 500ms 防抖
  }

  /**
   * 确保 JXBK 数据已加载
   */
  private async ensureJxbkDataLoaded(): Promise<void> {
    const jxbkData = this.state.theme.jxbk
    if (jxbkData.blocks && jxbkData.blocks.length > 0) {
      return
    }

    const { sectorAnalyzer } = await import('./sectorAnalyzer')
    sectorAnalyzer.forceRefreshJxbk().catch((err) => {
      console.error('[DataLayer] JXBK 加载失败:', err)
    })

    return new Promise((resolve) => {
      const timeout = setTimeout(() => {
        clearInterval(checkInterval)
        console.warn('[DataLayer] JXBK 加载超时')
        resolve()
      }, 30000)

      const checkInterval = setInterval(() => {
        if (this.state.theme.jxbk.blocks && this.state.theme.jxbk.blocks.length > 0) {
          clearInterval(checkInterval)
          clearTimeout(timeout)
          resolve()
        }
      }, 500)
    })
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

    this.throttledNotify('stock.ext.updated', { count: updates.length })
    EventManager.emit('stock.ext.updated', {
      count: updates.length,
      timestamp: Date.now(),
    })
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

  // ========== 历史排名数据 ==========

  /**
   * 从历史快照加载昨天的排名
   */
  async loadYesterdayRankFromSnapshot(): Promise<Map<string, number>> {
    try {
      // 获取昨天的日期
      const yesterday = new Date()
      yesterday.setDate(yesterday.getDate() - 1)
      const yesterdayStr = yesterday.toISOString().slice(0, 10)

      // 获取昨天的快照
      const yesterdaySnapshot = await this.getSnapshotFromDB(yesterdayStr)

      if (yesterdaySnapshot && yesterdaySnapshot.hotlist) {
        const rankMap = new Map<string, number>()

        // 从快照的热榜中提取排名
        yesterdaySnapshot.hotlist.forEach((item: any, index: number) => {
          if (item.code) {
            rankMap.set(item.code, index + 1)
          }
        })

        // 保存到状态中
        this.state.rankHistory.byCode = rankMap
        this.state.rankHistory.lastUpdate = Date.now()
        this.state.rankHistory.snapshotDate = yesterdayStr
        return rankMap
      }

      return new Map()
    } catch (error) {
      console.error('[DataLayer] 加载历史排名失败:', error)
      return new Map()
    }
  }

  /**
   * 获取股票的排名变化
   * @param code 股票代码
   * @param currentRank 当前排名
   * @returns 变化值（正数表示上升，负数表示下降）
   */
  async getRankChange(code: string, currentRank: number): Promise<number> {
    // 如果还没有加载历史排名，尝试加载
    if (this.state.rankHistory.byCode.size === 0 && !this.state.rankHistory.lastUpdate) {
      await this.loadYesterdayRankFromSnapshot()
    }

    const yesterdayRank = this.state.rankHistory.byCode.get(code)
    if (yesterdayRank === undefined) {
      return 0 // 新上榜的股票，没有历史排名
    }

    return yesterdayRank - currentRank // 正数表示排名上升，负数表示下降
  }

  /**
   * 批量获取排名变化
   */
  async getRankChanges(rankMap: Map<string, number>): Promise<Map<string, number>> {
    // 如果还没有加载历史排名，尝试加载
    if (this.state.rankHistory.byCode.size === 0 && !this.state.rankHistory.lastUpdate) {
      await this.loadYesterdayRankFromSnapshot()
    }

    const changes = new Map<string, number>()

    for (const [code, currentRank] of rankMap.entries()) {
      const yesterdayRank = this.state.rankHistory.byCode.get(code)
      if (yesterdayRank !== undefined) {
        changes.set(code, yesterdayRank - currentRank)
      } else {
        changes.set(code, 0)
      }
    }

    return changes
  }

  // ========== 实时行情数据 ==========
  updateQuotesBatch(changes: any[]) {
    if (!changes?.length) return

    const updateMap = new Map()
    changes.forEach((change) => {
      if (!change?.code) return
      updateMap.set(change.code, change)
    })

    changes.forEach((change) => {
      if (!change?.code) return
      const existing = this.state.realtime.quotes.get(change.code) || {}
      this.state.realtime.quotes.set(change.code, {
        ...existing,
        ...change,
        timestamp: Date.now(),
      })
    })

    // ✅ 同步更新 merged.stocks 并重新计算量比
    const updatedStocks = this.state.merged.stocks.map((stock) => {
      const update = updateMap.get(stock.code)
      if (update) {
        const newStock = {
          ...stock,
          price: update.price ?? stock.price,
          change: update.change ?? stock.change,
          volume: update.volume ?? stock.volume,
          turnover: update.turnover ?? stock.turnover,
          turnoverRate: update.turnoverRate ?? stock.turnoverRate,
          pe: update.pe ?? stock.pe,
          pb: update.pb ?? stock.pb,
          totalMV: update.totalMV ?? stock.totalMV,
          cirMV: update.cirMV ?? stock.cirMV,
          zlje: update.zlje ?? stock.zlje,
          zljzb: update.zljzb ?? stock.zljzb,
          cddje: update.cddje ?? stock.cddje,
          cddjzb: update.cddjzb ?? stock.cddjzb,
        }
        // ✅ 重新计算量比（需要历史成交量数据）
        this.recalculateVolumeRatio(newStock)
        return newStock
      }
      return stock
    })

    this.state.merged.stocks = updatedStocks
    this.state.realtime.lastUpdate = Date.now()
    this.state.version.quotes++

    this.throttledNotify('quotes:batch', { count: changes.length })
  }

  private async loadVolumeHistoryCache() {
    const now = Date.now()
    if (this.volumeHistoryCache.size > 0 && now - this.volumeHistoryCacheTime < 3600000) {
      return
    }
    const { dataLoader } = await import('./dataLoader')
    this.volumeHistoryCache = await dataLoader.buildVolumeHistoryMap()
    this.volumeHistoryCacheTime = now
  }

  /**
   * 重新计算单只股票的量比
   */
  private recalculateVolumeRatio(stock: any) {
    if (!stock.volume || stock.volume <= 0) {
      stock.volumeRatio = 1.0
      return
    }

    const volumes = this.volumeHistoryCache.get(stock.code)
    if (!volumes || volumes.length === 0) {
      stock.volumeRatio = 1.0
      return
    }

    const WEIGHTS = [5, 3, 2]
    const daysToUse = Math.min(volumes.length, WEIGHTS.length)

    let weightedSum = 0
    let totalWeight = 0

    for (let i = 0; i < daysToUse; i++) {
      weightedSum += volumes[i] * WEIGHTS[i]
      totalWeight += WEIGHTS[i]
    }

    if (totalWeight === 0) {
      stock.volumeRatio = 1.0
      return
    }

    const avgVolume = weightedSum / totalWeight
    if (avgVolume <= 0) {
      stock.volumeRatio = 1.0
      return
    }

    let ratio = stock.volume / avgVolume
    stock.volumeRatio = Math.min(10, Math.max(0.1, Number(ratio.toFixed(2))))
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

    // 情绪数据更新后，触发信号重新计算
    this.triggerSignalUpdate()
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

  // ========== 合并逻辑 ==========

  /**
   * 合并原始数据、龙头数据、题材数据、JXBK数据
   */
  private mergeToMerged() {
    const stockMap = new Map(this.state.merged.stocks.map((s) => [s.code, s]))
    this.state.raw.stocks.forEach((stock) => {
      const existing = stockMap.get(stock.code) || {}
      const merged = this.createMergedStock(stock, existing)
      this.mergeThemes(merged, stock.code)
      this.mergeJxbkData(merged, stock.code)
      this.mergeLeaderData(merged, stock.code)
      this.mergeLimitUpData(merged, stock.code)
      stockMap.set(stock.code, merged)
    })

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.meta.lastMergeTime = Date.now()
  }

  /**
   * 创建基础合并股票对象
   */
  private createMergedStock(stock: any, existing: any): MergedStock {
    return {
      ...existing,
      ...stock,
      code: stock.code,
      name: stock.name || existing.name,
      price: stock.price ?? existing.price ?? 0,
      change: stock.change ?? existing.change ?? 0,
    }
  }

  /**
   * 合并题材数据（使用静态映射）
   */
  private mergeThemes(merged: MergedStock, code: string) {
    // 直接从静态映射获取题材列表（已经是 { id, name } 格式）
    const themes = this.state.theme.base.byCode.get(code) || []
    merged.themes = themes
  }

  /**
   * 合并 JXBK 实时数据（量比、主力净额等）
   */
  private mergeJxbkData(merged: MergedStock, code: string) {
    const jxbkStock = this.state.theme.jxbk.stockMap[code]
    if (!jxbkStock) return

    merged.speed = jxbkStock.speed
    // merged.volumeRatio = jxbkStock.volumeRatio
    merged.leadTimes = jxbkStock.leadTimes
    merged.leadStatus = jxbkStock.leadStatus
    merged.lianbanStr = jxbkStock.lianban
    merged.bigMoney300 = jxbkStock.bigMoney300
    merged.popularity = jxbkStock.popularity
    merged.popularityChange = jxbkStock.popularityChange
    merged.institutionBuy = jxbkStock.institutionBuy
    merged.mainBuy = jxbkStock.mainBuy
    merged.mainSell = jxbkStock.mainSell
    merged.fengdan = jxbkStock.fengdan
    merged.maxFengdan = jxbkStock.maxFengdan
    merged.cirMV = jxbkStock.cirMV
  }

  /**
   * 合并龙头标记
   */
  private mergeLeaderData(merged: MergedStock, code: string) {
    const leaderInfo = this.state.leader.byCode.get(code)
    if (!leaderInfo) return

    merged.isSectorLeader = true
    merged.leaderLevel = leaderInfo.levelName
    merged.leaderScore = leaderInfo.score
    merged.continuousDays = leaderInfo.continuousDays
  }

  /**
   * 合并涨停扩展数据
   */
  private mergeLimitUpData(merged: MergedStock, code: string) {
    const limitUpData = this.state.tck2?.limitUpData.get(code)
    if (!limitUpData) return

    merged.fengdan = limitUpData.fengdan ?? merged.fengdan
    merged.maxFengdan = limitUpData.maxFengdan ?? merged.maxFengdan
    merged.leadStatus = limitUpData.leadStatus ?? merged.leadStatus
    merged.leadTimes = limitUpData.leadTimes ?? merged.leadTimes
    merged.lianbanStr = limitUpData.lianbanStr ?? merged.lianbanStr
    merged.firstZtTime = limitUpData.firstZtTime ?? merged.firstZtTime
    merged.lastZtTime = limitUpData.lastZtTime ?? merged.lastZtTime
    merged.reason = limitUpData.reason ?? merged.reason
    merged.tags = limitUpData.tags ?? merged.tags
    merged.isNew = limitUpData.isNew ?? merged.isNew
  }

  /**
   * 手动设置合并后的股票数据
   * 供 dataLoader 调用，更新 merged.stocks
   */
  setMergedStocks(stocks: any[]) {
    // 先合并行情数据
    const enrichedStocks = this.enrichWithQuotes(stocks)

    // 更新 merged.stocks
    this.state.merged.stocks = enrichedStocks as MergedStock[]
    this.state.version.stocks++
    this.state.meta.lastMergeTime = Date.now()

    // 触发通知
    this.throttledNotify('merged.stocks', { count: stocks.length })
    EventManager.emit(AppEvents.DATA.MERGED, {
      count: stocks.length,
      timestamp: Date.now(),
    })

    // ✅ 添加：自动触发信号更新
    this.triggerSignalUpdate()
  }

  // ========== 工具方法 ==========

  getAllStocks(): MergedStock[] {
    if (this.state.raw.fullMarket.length) {
      return this.enrichWithQuotes(this.state.raw.fullMarket) as MergedStock[]
    }
    if (this.state.raw.stocks.length) {
      return this.enrichWithQuotes(this.state.raw.stocks) as MergedStock[]
    }
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

  // ========== 行情数据合并 ==========

  private enrichWithQuotes(stocks: any[]): any[] {
    if (!stocks?.length) return []

    return stocks.map((stock) => {
      const quote = this.state.realtime.quotes.get(stock.code)
      if (!quote) return stock

      return {
        ...stock,
        price: quote.price ?? stock.price,
        change: quote.change ?? stock.change,
        volume: quote.volume ?? stock.volume,
        turnover: quote.turnover ?? stock.turnover,
        turnoverRate: quote.turnoverRate ?? stock.turnoverRate,
        pe: quote.pe ?? stock.pe,
        pb: quote.pb ?? stock.pb,
        totalMV: quote.totalMV ?? stock.totalMV,
        cirMV: quote.cirMV ?? stock.cirMV,
        zlje: quote.zlje ?? stock.zlje,
        zljzb: quote.zljzb ?? stock.zljzb,
        cddje: quote.cddje ?? stock.cddje,
        cddjzb: quote.cddjzb ?? stock.cddjzb,
      }
    })
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
   * 批量更新股票信号（4维信号）
   */
  updateStockSignals(
    updates: Array<{
      code: string
      rankChange?: number
      // MACD 技术指标字段
      macd?: number
      macdSignal?: number
      macdHistogram?: number
      ma5?: number
      ma10?: number
      maTrend?: 'up' | 'down' | 'steady'
      macdCross?: 'golden' | 'death' | 'none'
      // 3个排名趋势信号
      directionSignal?: 'buy' | 'sell' | 'hold'
      directionConfidence?: number
      accelerationSignal?: 'buy' | 'sell' | 'hold'
      accelerationConfidence?: number
      crossSignal?: 'buy' | 'sell' | 'hold'
      crossConfidence?: number
      // 综合信号
      finalSignal?: 'buy' | 'sell' | 'hold'
      finalConfidence?: number
    }>,
  ) {
    if (!updates.length) return

    const stockMap = new Map(this.state.merged.stocks.map((s) => [s.code, s]))

    updates.forEach((update) => {
      const stock = stockMap.get(update.code)
      if (stock) {
        // 排名变化（UI显示）
        if (update.rankChange !== undefined) stock.rankChange = update.rankChange

        // MACD 技术指标字段
        if (update.macd !== undefined) stock.macd = update.macd
        if (update.macdSignal !== undefined) stock.macdSignal = update.macdSignal
        if (update.macdHistogram !== undefined) stock.macdHistogram = update.macdHistogram
        if (update.ma5 !== undefined) stock.ma5 = update.ma5
        if (update.ma10 !== undefined) stock.ma10 = update.ma10
        if (update.maTrend !== undefined) stock.maTrend = update.maTrend
        if (update.macdCross !== undefined) stock.macdCross = update.macdCross

        // 3个排名趋势信号
        if (update.directionSignal !== undefined) stock.directionSignal = update.directionSignal
        if (update.directionConfidence !== undefined)
          stock.directionConfidence = update.directionConfidence
        if (update.accelerationSignal !== undefined)
          stock.accelerationSignal = update.accelerationSignal
        if (update.accelerationConfidence !== undefined)
          stock.accelerationConfidence = update.accelerationConfidence
        if (update.crossSignal !== undefined) stock.crossSignal = update.crossSignal
        if (update.crossConfidence !== undefined) stock.crossConfidence = update.crossConfidence

        // 综合信号
        if (update.finalSignal !== undefined) stock.finalSignal = update.finalSignal
        if (update.finalConfidence !== undefined) stock.finalConfidence = update.finalConfidence
      }
    })

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++

    this.throttledNotify('stock.signals.updated', { count: updates.length })
    EventManager.emit('stock.signals.updated', {
      count: updates.length,
      timestamp: Date.now(),
    })
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

        hotlist: stocks.slice(0, 200).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
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
          fundPenetration: stock.fundPenetration,

          // 题材
          mainTheme: stock.mainTheme,
          themeHeat: stock.themeHeat,
          themeLevel: stock.themeLevel,

          //信号
          signals: {
            direction: { signal: stock.directionSignal, confidence: stock.directionConfidence },
            acceleration: {
              signal: stock.accelerationSignal,
              confidence: stock.accelerationConfidence,
            },
            cross: { signal: stock.crossSignal, confidence: stock.crossConfidence },
            final: { signal: stock.finalSignal, confidence: stock.finalConfidence },
          },
          macdCross: stock.macdCross,
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
      console.log(`[DataLayer] ✅ 一刻快照已保存: ${key}`)
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

        hotlist: stocks.slice(0, 200).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
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
          themes: stock.themes?.slice(0, 3).map((t: any) => ({
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
          fundPenetration: stock.fundPenetration,

          // 题材
          mainTheme: stock.mainTheme,
          themeHeat: stock.themeHeat,
          themeLevel: stock.themeLevel,

          // 信号
          signals: {
            direction: { signal: stock.directionSignal, confidence: stock.directionConfidence },
            acceleration: {
              signal: stock.accelerationSignal,
              confidence: stock.accelerationConfidence,
            },
            cross: { signal: stock.crossSignal, confidence: stock.crossConfidence },
            final: { signal: stock.finalSignal, confidence: stock.finalConfidence },
          },
          macdCross: stock.macdCross,
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
      console.log(`[DataLayer] ✅ 半小时快照已保存: ${key}`)
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存半小时快照失败:', error)
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

        hotlist: stocks.slice(0, 100).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
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

          // 综合信号
          finalSignal: stock.finalSignal,
          finalConfidence: stock.finalConfidence,
          macdCross: stock.macdCross,
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
      return true
    } catch (error) {
      console.error('[DataLayer] ❌ 保存小时快照失败:', error)
      return false
    }
  }

  /**
   * 生成每日快照（完整版）- 包含所有回测需要的数据
   */
  generateDailySnapshot(): any {
    const now = new Date()
    const dateStr = now.toISOString().slice(0, 10)
    const breathData = this.getBreathData()
    const marketData = this.state.analysis.breath?.marketData
    const jxbkStocks = this.state.theme.jxbk.stockMap || {}
    const jxbkBlocks = this.state.theme.jxbk.blocks || []
    const stockQuotes = this.getStocks() || []
    const hotThemes = this.getHotThemes() || []
    const themeMetrics = this.getAllThemeMetrics() || new Map()
    const breathHistory = this.getBreathHistory()
    const breathFactors = this.getBreathFactors()
    const rotationAnalysis = this.state.analysis.rotation?.current || null

    // ✅ 获取 themeMapping（从 window，用于获取题材名称）
    const themeMapping = (window as any).themeMapping

    // 建立股价映射
    const priceMap = new Map()
    stockQuotes.forEach((s: any) => {
      priceMap.set(s.code, s.price)
    })

    // ========== 1. 龙头数据（来自 jxbk 领涨股） ==========
    const leadingStocks = Object.values(jxbkStocks)
      .filter((stock: any) => stock.leadStatus && stock.leadStatus.includes('龙'))
      .sort((a: any, b: any) => {
        const getRank = (status: string) => {
          if (status.includes('龙一')) return 1
          if (status.includes('龙二')) return 2
          if (status.includes('龙三')) return 3
          if (status.includes('龙')) return 4
          return 5
        }
        return getRank(a.leadStatus) - getRank(b.leadStatus)
      })

    const leaders = leadingStocks.map((stock: any) => {
      const block = jxbkBlocks.find((b: any) => stock.blocks?.includes(b.name))
      return {
        code: stock.code,
        name: stock.name,
        level: stock.leadStatus,
        score: stock.leadTimes * 100,
        continuousDays: parseInt(stock.lianban) || 1,
        change: stock.change,
        price: priceMap.get(stock.code) || 0,
        block: block?.name || '',
        blockStrength: block?.strength || 0,
        blockChange: block?.change || 0,
        mainNetInflow: stock.mainNetInflow,
        bigMoney300: stock.bigMoney300,
        institutionBuy: stock.institutionBuy,
        leadTimes: stock.leadTimes,
        leadStatus: stock.leadStatus,
        lianbanStr: stock.lianban,
        popularity: stock.popularity,
        fengdan: stock.fengdan,
        maxFengdan: stock.maxFengdan,
      }
    })

    // ========== 2. 板块数据（全部，按强度排序） ==========
    const sectors = jxbkBlocks
      .map((block: any) => ({
        code: block.code,
        name: block.name,
        strength: block.strength,
        change: block.change,
        mainNetInflow: block.mainNetInflow,
        bigMoney300: block.bigMoney300,
        institutionBuy: block.institutionBuy,
        volumeRatio: block.volumeRatio,
        ztCount: block.ztCount,
      }))
      .sort((a, b) => b.strength - a.strength)

    // ========== 3. 创建板块强度映射（供题材使用） ==========
    const sectorStrengthMap = new Map()
    sectors.forEach((sector) => {
      sectorStrengthMap.set(sector.name, sector.strength)
    })

    // ========== 4. 涨停池数据 ==========
    const allStocks = this.getStocks() || []
    const limitUpStocks = allStocks
      .filter((stock) => {
        const change = stock.change || 0
        const code = stock.code || ''
        const name = stock.name || ''
        return StockUtils.isLimitUp(change, code, name)
      })
      .map((stock) => {
        // 从 JXBK 获取实时数据
        const jxbkStock = this.state.theme.jxbk.stockMap[stock.code]

        return {
          code: stock.code,
          name: stock.name,
          change: stock.change,
          price: stock.price,
          turnover: stock.turnover,
          turnoverRate: stock.turnoverRate,
          zlje: stock.zlje,
          zljzb: stock.zljzb,
          volume: stock.volume,
          firstZtTime: stock.firstZtTime,
          lastZtTime: stock.lastZtTime,
          boardHeight: stock.boardHeight,
          fengdan: stock.fengdan,
          maxFengdan: stock.maxFengdan,
          leadStatus: stock.leadStatus,
          lianbanStr: stock.lianbanStr,
          leadTimes: stock.leadTimes,
          volumeRatio: stock.volumeRatio,
          speed: stock.speed,
          // 从 JXBK 获取
          mainNetInflow: jxbkStock?.mainNetInflow || 0,
          bigMoney300: jxbkStock?.bigMoney300 || stock.bigMoney300 || 0,
          institutionBuy: jxbkStock?.institutionBuy || stock.institutionBuy || 0,
          popularity: jxbkStock?.popularity || stock.popularity || 0,
          popularityChange: jxbkStock?.popularityChange || stock.popularityChange || 0,
        }
      })

    // ========== 5. 连板梯队统计 ==========
    const continuousBoards = {
      board1: marketData?.limitData?.yiban ?? 0,
      board2: marketData?.limitData?.erban ?? 0,
      board3: marketData?.limitData?.sanban ?? 0,
      board4plus: marketData?.limitData?.sibanPlus ?? 0,
      total:
        (marketData?.limitData?.yiban ?? 0) +
        (marketData?.limitData?.erban ?? 0) +
        (marketData?.limitData?.sanban ?? 0) +
        (marketData?.limitData?.sibanPlus ?? 0),
    }
    // ========== 6. 全部题材指标（按热度排序，只取前100） ==========
    const allThemes = Array.from(themeMetrics.entries())
      .map(([id, metrics]: [string, any]) => {
        let themeName = ''
        if (themeMapping) {
          const theme = themeMapping.getTheme(id)
          if (theme) themeName = theme.name
        }
        if (!themeName) {
          const theme = this.getThemeById(id)
          if (theme) themeName = theme.name || ''
        }

        return {
          id: id,
          name: themeName,
          heatScore: metrics.heatScore,
          heatLevel: metrics.heatLevel,
          momentum: metrics.momentum,
          trend: metrics.trend,
          acceleration: metrics.acceleration,
          correlation: metrics.correlation,
          stockCount: metrics.stats?.stockCount || 0,
          ztCount: metrics.stats?.ztCount || 0,
          leaderCount: metrics.stats?.leaderCount || 0,
          strength: sectorStrengthMap.get(themeName) || 0,
          mainNetInflow: metrics.jxbk?.mainNetInflow || 0,
          bigMoney300: metrics.jxbk?.bigMoney300 || 0,
          institutionBuy: metrics.jxbk?.institutionBuy || 0,
          volumeRatio: metrics.jxbk?.volumeRatio || 0,
        }
      })
      .sort((a, b) => b.heatScore - a.heatScore)
      .slice(0, 100)

    // ========== 7. 题材联动分析数据 ==========
    const themeCorrelations = []
    const mainLines = rotationAnalysis?.mainLines || []
    const allCorrelations = this.state.theme.correlation?.byTheme || new Map()

    for (const mainLine of mainLines) {
      const themeId = mainLine.themeId
      const themeName = mainLine.themeName
      const correlation = allCorrelations.get(themeId)

      if (correlation) {
        themeCorrelations.push({
          themeId: themeId,
          themeName: themeName,
          overallCorrelation: correlation.overallCorrelation,
          coreStocks: correlation.coreStocks || [],
          followerStocks: correlation.followerStocks || [],
          independentStocks: correlation.independentStocks || [],
          leader: correlation.leader
            ? {
                code: correlation.leader.code,
                name: correlation.leader.name,
                score: correlation.leader.score,
                confidence: correlation.leader.confidence,
                change: correlation.leader.change,
                lianban: correlation.leader.lianban,
                fengdan: correlation.leader.fengdan,
              }
            : null,
          stats: correlation.stats || {
            totalStocks: 0,
            avgChange: 0,
            totalZtCount: 0,
            avgVolumeRatio: 0,
            totalMainInflow: 0,
          },
          isMainLine: true,
          mainLineRank: mainLine.rank || 0,
          mainLineStrength: mainLine.strength || 0,
          mainLinePersistentDays: mainLine.persistentDays || 0,
        })
      }
    }

    // ========== 8. 热榜数据（完整版） ==========
    const stocks = this.getStocks() || []
    const topStocks = [...stocks]
      .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
      .slice(0, 200)

    // ========== 9. 炸板数据 ==========
    const zhabanData = {
      count: marketData?.zhaban?.count || 0,
      rate: marketData?.zhaban?.rate || 0,
      fengbanRate: marketData?.zhaban?.fengbanRate || 0,
    }

    // ========== 10. 昨日涨停表现 ==========
    const yesterdayStats = marketData?.yesterdayLimit || {}
    const yesterdayZtPerformance = {
      total: yesterdayStats.total || 0,
      dtCount: yesterdayStats.dtCount || 0,
      bigLossCount: yesterdayStats.bigLossCount || 0,
      redCount: yesterdayStats.redCount || 0,
      greenCount: yesterdayStats.greenCount || 0,
      avgChange: yesterdayStats.avgChange || 0,
      maxChange: yesterdayStats.maxChange || 0,
      minChange: yesterdayStats.minChange || 0,
    }

    const yesterdayLimit = marketData?.yesterdayLimit || {}

    // ========== 11. 资金流向 ==========
    const moneyFlow = {
      main: marketData?.moneyFlow?.main || 0,
      retail: marketData?.moneyFlow?.retail || 0,
      cddje: marketData?.cddje || 0,
      cddjzb: marketData?.cddjzb || 0,
    }

    // ========== 12. 指数表现 ==========
    const indices = {
      sh: marketData?.indices?.sh?.change || 0,
      sz: marketData?.indices?.sz?.change || 0,
      cy: marketData?.indices?.cy?.change || 0,
      hs300: marketData?.indices?.hs300?.change || 0,
      zz500: marketData?.indices?.zz500?.change || 0,
      zz1000: marketData?.indices?.zz1000?.change || 0,
    }

    // ========== 13. 市场统计 ==========
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

    // ========== 14. 返回完整快照 ==========
    return {
      date: `[日级快照] ${dateStr}`,
      timestamp: Date.now(),
      type: 'daily',

      sentiment: {
        overall: breathData?.overall || 0,
        phase: breathData?.phase || '',
        phaseName: breathData?.phaseName || '',
        riskLevel: breathData?.riskLevel || '',
        suggestion: breathData?.suggestion || '',
        factorScores: breathData?.factorScores || {},
        history: breathHistory,
        factors: breathFactors,
      },

      market: marketStats,
      leaders: leaders,
      sectors: sectors,
      limitUpStocks: limitUpStocks,
      continuousBoards: continuousBoards,
      zhaban: zhabanData,

      yesterdayZt: yesterdayZtPerformance,
      yesterdayLimitUpStats: yesterdayStats,
      yesterdayLimit: yesterdayLimit,
      moneyFlow: moneyFlow,
      indices: indices,
      allThemes: allThemes,

      limit: {
        yiban: marketData?.limitData?.yiban ?? 0,
        erban: marketData?.limitData?.erban ?? 0,
        sanban: marketData?.limitData?.sanban ?? 0,
        sibanPlus: marketData?.limitData?.sibanPlus ?? 0,
      },

      hotThemes: hotThemes.slice(0, 20).map((t: any, i: number) => ({
        rank: i + 1,
        name: t.name,
        heatScore: t.heatScore,
        heatLevel: t.heatLevel,
        ztCount: t.ztCount,
        leaderCount: t.leaderCount,
        momentum: t.momentum?.toFixed(2) || '0',
        trend: t.trend?.toFixed(2) || '0',
      })),

      hotlist: topStocks.map((s) => ({
        code: s.code,
        name: s.name,
        rank: s.compRank,
        price: s.price,
        change: s.change,
        turnover: s.turnover,
        turnoverRate: s.turnoverRate,
        zlje: s.zlje,
        zljzb: s.zljzb,
        volume: s.volume,
        pe: s.pe,
        pb: s.pb,
        totalMV: s.totalMV,
        cirMV: s.cirMV,
        volumeRatio: s.volumeRatio,
        speed: s.speed,
        leadStatus: s.leadStatus,
        lianbanStr: s.lianbanStr,
        fengdan: s.fengdan,
        maxFengdan: s.maxFengdan,
        popularity: s.popularity,
        popularityChange: s.popularityChange,
        hotness: s.hotness,
        tags: s.tags,
        reason: s.reason,
        isNew: s.isNew,
        firstZtTime: s.firstZtTime,
        lastZtTime: s.lastZtTime,
        boardHeight: s.boardHeight,
        highDays: s.highDays,
        rankChange: s.rankChange,
        fundPenetration: s.fundPenetration,
        mainTheme: s.mainTheme,
        themeHeat: s.themeHeat,
        themeLevel: s.themeLevel,
        // ✅ 3个排名趋势信号
        directionSignal: s.directionSignal,
        directionConfidence: s.directionConfidence,
        accelerationSignal: s.accelerationSignal,
        accelerationConfidence: s.accelerationConfidence,
        crossSignal: s.crossSignal,
        crossConfidence: s.crossConfidence,
        // ✅ 综合信号
        finalSignal: s.finalSignal,
        finalConfidence: s.finalConfidence,
        // ✅ MACD
        macdCross: s.macdCross,
        // 题材
        themes: [
          ...new Set(
            s.themes
              ?.slice(0, 5)
              .map((t: any) => t.name)
              .filter(Boolean) || [],
          ),
        ],
      })),

      themeCorrelations: themeCorrelations,

      rotation: rotationAnalysis
        ? {
            marketPhase: rotationAnalysis.marketPhase,
            rotationSpeed: rotationAnalysis.rotationSpeed,
            mainLines: mainLines.map((m: any) => ({
              themeId: m.themeId,
              themeName: m.themeName,
              strengthScore: m.strengthScore,
              persistentDays: m.persistentDays,
              netInflow: m.netInflow,
              ztCount: m.ztCount,
              isMainLine: m.isMainLine,
              rank: m.rank,
            })),
            strongThemes: (rotationAnalysis.strongThemes || []).slice(0, 5).map((s: any) => ({
              themeName: s.themeName,
              strengthScore: s.strengthScore,
            })),
            emotion: rotationAnalysis.emotion,
            suggestion: rotationAnalysis.summary?.suggestion || '',
          }
        : null,

      weights: {
        MARKET_LOSS: SENTIMENT_SCORE_CONFIG.WEIGHTS.MARKET_LOSS || 0,
        TDX_EMOTION: SENTIMENT_SCORE_CONFIG.WEIGHTS.TDX_EMOTION || 0,
        UP_DOWN_RATIO: SENTIMENT_SCORE_CONFIG.WEIGHTS.UP_DOWN_RATIO || 0,
        DT_COUNT: SENTIMENT_SCORE_CONFIG.WEIGHTS.DT_COUNT || 0,
        LOSS_EFFECT: SENTIMENT_SCORE_CONFIG.WEIGHTS.LOSS_EFFECT || 0,
        ZT_COUNT: SENTIMENT_SCORE_CONFIG.WEIGHTS.ZT_COUNT || 0,
        PROFIT_EFFECT: SENTIMENT_SCORE_CONFIG.WEIGHTS.PROFIT_EFFECT || 0,
        YESTERDAY_ZT: SENTIMENT_SCORE_CONFIG.WEIGHTS.YESTERDAY_ZT || 0,
        FENGBAN_RATE: SENTIMENT_SCORE_CONFIG.WEIGHTS.FENGBAN_RATE || 0,
        INDEX: SENTIMENT_SCORE_CONFIG.WEIGHTS.INDEX || 0,
        LIANBAN_HEIGHT: SENTIMENT_SCORE_CONFIG.WEIGHTS.LIANBAN_HEIGHT || 0,
        PROMOTION_RATE: SENTIMENT_SCORE_CONFIG.WEIGHTS.PROMOTION_RATE || 0,
        VOLUME: SENTIMENT_SCORE_CONFIG.WEIGHTS.VOLUME || 0,
      },

      stats: {
        totalStocks: stocks.length,
        totalLeaders: leaders.length,
        totalSectors: sectors.length,
        totalLimitUpStocks: limitUpStocks.length,
        totalThemes: allThemes.length,
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
   * 导出快照数据为 Excel（CSV格式，Excel可打开）
   * @param snapshotKey 快照的key（如 'daily_2026-03-22' 或 '一刻快照_2026-03-22_1430'）
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
        return false
      }

      // 2. 默认导出所有工作表
      const sheets = options?.sheets || ['hotlist', 'sectors', 'sentiment', 'market']
      const filename = options?.filename || `${snapshotKey}_export`

      // 3. 构建 CSV 内容
      const csvParts: string[] = []
      const sheetNames: string[] = []

      // 3.1 热榜数据工作表
      if (sheets.includes('hotlist') && snapshot.hotlist?.length) {
        sheetNames.push('热榜')
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
          'MACD金叉',
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
          stock.tags || '',
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
          stock.macdCross ? '是' : '否',
        ])

        csvParts.push(this.arrayToCSV([headers, ...rows]))
      }

      // 3.2 板块数据工作表
      if (sheets.includes('sectors') && snapshot.sectors?.length) {
        if (csvParts.length > 0) csvParts.push('---SEPARATOR---')
        sheetNames.push('板块')

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
        if (csvParts.length > 0) csvParts.push('---SEPARATOR---')
        sheetNames.push('情绪')

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
        if (csvParts.length > 0) csvParts.push('---SEPARATOR---')
        sheetNames.push('市场')

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
        if (csvParts[i] === '---SEPARATOR---') {
          finalCSV += `\n\n========== ${sheetNames[i]} ==========\n\n`
        } else {
          finalCSV += csvParts[i]
        }
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
      const filteredDates = allDates.filter((date) => date >= startDate && date <= endDate)

      if (filteredDates.length === 0) {
        console.warn('[DataLayer] 指定范围内没有快照')
        return false
      }

      const allData: any[] = []

      for (const date of filteredDates) {
        const snapshot = await this.getSnapshotFromDB(date)
        if (snapshot?.hotlist) {
          snapshot.hotlist.forEach((stock: any) => {
            allData.push({
              日期: date,
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
      if (!isTradingTime(now)) return

      const m = now.getMinutes()
      const s = now.getSeconds()
      const h = now.getHours()
      const key = `${now.getFullYear()}-${now.getMonth()}-${now.getDate()}-${h}:${m}`

      // ✅ 允许 1 秒误差
      if (s > 2) return

      // 半点
      if ((m === 0 || m === 30) && this.lastSnapshotKey.half !== key) {
        this.lastSnapshotKey.half = key
        this.saveHalfHourSnapshot()
      }
      // 一刻
      if ((m === 15 || m === 45) && this.lastSnapshotKey.quarter !== key) {
        this.lastSnapshotKey.quarter = key
        this.saveQuarterHourSnapshot()
      }
      // 整点
      if (m === 0 && [10, 11, 13, 14, 15].includes(h) && this.lastSnapshotKey.hour !== key) {
        this.lastSnapshotKey.hour = key
        this.saveHourlySnapshot()
      }
      // 日线
      if (h === 15 && m === 0 && this.lastSnapshotKey.daily !== key) {
        this.lastSnapshotKey.daily = key
        this.saveDailySnapshot()
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
