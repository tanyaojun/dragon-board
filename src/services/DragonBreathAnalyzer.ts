import { debugLog } from '@/utils/logger'
// src/services/DragonBreathAnalyzer.ts
// 优化版 - 从 emotion.ts 读取情绪阶段配置

import type {
  MarketData,
  Sentiment,
  LimitData,
  ZhabanData,
  BreathHistorySnapshot,
  EmotionFeedback,
} from '../types'

import { AppEvents } from '../types'
import {
  EMOTION_PHASES,
  EMOTION_PHASE_BY_NAME,
  type EmotionPhase, // ← 确保这行存在
} from '../types/emotion'
import { apiService } from './apiService'
import { EventManager } from '../utils/eventManager'
import { API_CONFIG } from '../config/constants'
import { dataLayer } from './DataLayer'
import { FORMAL_SNAPSHOT_READ_POLICY } from './snapshot/readPolicy'
import { snapshotFacade } from './snapshot/facade'
import { refreshScheduler } from './refresh/RefreshTaskRuntime'
import { StockUtils } from '../utils/common'

import { EMOTION_FACTOR_CONFIG, type EmotionFactor } from '../types/emotion'

/**
 * 龙息分析器状态
 */
interface DragonBreathState {
  initialized: boolean
  marketData: MarketData
  sentiment: Sentiment
  history: BreathHistorySnapshot[]
  _analyzing: boolean
  _fetching: boolean

  // 题材关联
  themeImpact: number
  hotThemesCount: number

  // 反馈状态
  lastFeedback: {
    phase: string
    timestamp: number
  } | null

  // 缓存
  cache: {
    marketStats: any
    limitStats: any
    lastFetch: number
  }

  destroyed: boolean
}

export class DragonBreathAnalyzer {
  private static instance: DragonBreathAnalyzer
  private state: DragonBreathState

  // 保存事件取消函数
  private unsubscribeFns: (() => void)[] = []

  // 防抖/节流控制
  private analysisTimeout: ReturnType<typeof setTimeout> | null = null
  private lastAnalysisTime = 0
  private readonly ANALYSIS_COOLDOWN = 2000 // 2秒内不重复分析

  //统一管理销毁状态
  private destroyed = false

  private constructor() {
    this.state = {
      initialized: false,
      marketData: this.getDefaultMarketData(),
      sentiment: this.getDefaultSentiment(),
      history: [],
      _analyzing: false,
      _fetching: false,
      themeImpact: 0,
      hotThemesCount: 0,
      lastFeedback: null,
      cache: {
        marketStats: null,
        limitStats: null,
        lastFetch: 0,
      },
      destroyed: false,
    }
  }

  static getInstance(): DragonBreathAnalyzer {
    if (!DragonBreathAnalyzer.instance) {
      DragonBreathAnalyzer.instance = new DragonBreathAnalyzer()
    }
    return DragonBreathAnalyzer.instance
  }

  /**
   * 初始化 - 由外部调用
   */
  async init(): Promise<boolean> {
    if (this.destroyed) {
      console.warn('[DragonBreathAnalyzer] 实例已销毁')
      return false
    }
    if (this.state.initialized) return true

    debugLog('[DragonBreathAnalyzer] 📊 初始化龙息分析器...')

    // 设置必要的监听器
    this.setupEssentialListeners()

    // 执行首次分析
    await this.analyzeMarketBreath()

    // ✅ 启动定时刷新（只在交易时间执行）
    this.startAutoRefresh()

    this.state.initialized = true

    debugLog('[DragonBreathAnalyzer] ✅ 初始化完成')

    return true
  }

  /**
   * 启动定时刷新
   */
  startAutoRefresh(interval: number = 300000): void {
    refreshScheduler.registerRunner('dragon.breath', async () => {
      await this.analyzeMarketBreath(false)
    })
    refreshScheduler.startTask('dragon.breath', interval)
  }

  /**
   * 设置必要的监听器（只保留最基本的）
   */
  private setupEssentialListeners(): void {
    const listeners = [
      // 监听数据合并，触发分析
      EventManager.on(AppEvents.DATA.MERGED, () => {
        this.scheduleAnalysis()
      }),
    ]

    this.unsubscribeFns.push(...listeners)
  }

  // ========== 供协调者调用的方法 ==========

  /**
   * 全量更新 - 供协调者调用
   */
  async runFullUpdate(): Promise<void> {
    if (this.destroyed) return
    await this.analyzeMarketBreath(true)
  }

  /**
   * 获取默认市场数据
   */
  private getDefaultMarketData(): MarketData {
    return {
      timestamp: null,
      upCount: 0,
      downCount: 0,
      ztCount: 0,
      dtCount: 0,
      totalAmo: 0,
      amoDiff: 0,
      limitData: { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
      yesterdayLimit: { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
      zhaban: { count: 0, rate: 0, fengbanRate: 0 },
      indices: {
        sh: { change: 0 },
        hs300: { change: 0 },
        zz500: { change: 0 },
        zz1000: { change: 0 },
      },
      moneyFlow: { main: 0, retail: 0 },
      emotionValue: 0,
      emotionStatus: '震荡',
      volumeRatio: 0,
      yesterdayZtPerformance: 0,
      yesterdayZtAvgLoss: 0,
      maxContinuousDays: 0,
      limitStocks: [],
      bigLossCount: 0,
      largeCapChange: 0,
      microCapChange: 0,
      fengbanAmount: 0,
      fengbanRate: 0,
      passRate: {
        to2: 0,
        to3: 0,
        to4: 0,
      },
      repairRate: 0,
      cddje: 0,
      cddjzb: 0,
    }
  }

  /**
   * 获取默认情绪
   */
  private getDefaultSentiment(): Sentiment {
    const defaultPhase = EMOTION_PHASES.START
    return {
      overall: 50,
      phase: defaultPhase.value,
      phaseName: defaultPhase.name,
      riskLevel: '中',
      suggestion: defaultPhase.suggestion,
      timestamp: Date.now(),
      phaseInfo: defaultPhase,
      hotThemesCount: 0,
      phaseIcon: defaultPhase.icon,
      phaseColor: defaultPhase.color,
      phaseGradient: defaultPhase.gradient,
      phaseFeatures: defaultPhase.features,
      metrics: {
        yesterdayZtPerformance: 0,
        maxContinuousDays: 0,
        ztCount: 0,
        dtCount: 0,
        zhabanRate: 0,
        upDownRatio: 0,
      },
    }
  }

  // ===== 反馈情绪给算法管理器 =====
  private feedbackToAlgorithm() {
    if (!API_CONFIG.FEEDBACK.ENABLED) return

    try {
      const sentiment = this.state.sentiment
      const marketData = this.state.marketData

      if (
        this.state.lastFeedback &&
        sentiment.phase === this.state.lastFeedback.phase &&
        Date.now() - this.state.lastFeedback.timestamp < API_CONFIG.FEEDBACK.COOLDOWN
      ) {
        return
      }

      const feedback: EmotionFeedback = {
        phase: sentiment.phase,
        score: 0,
        ztCount: marketData.ztCount,
        dtCount: marketData.dtCount,
        hotThemesCount: this.state.hotThemesCount,
        themeImpact: this.state.themeImpact,
        timestamp: Date.now(),
      }

      EventManager.emit(AppEvents.BREATH.FEEDBACK, feedback)

      this.state.lastFeedback = {
        phase: sentiment.phase,
        timestamp: Date.now(),
      }
    } catch (error) {}
  }

  /**
   * 工具函数
   */
  private utils = {
    fmtNumber: (num: number | undefined, defaultValue: string = '--'): string => {
      if (num === undefined || num === null || isNaN(num)) return defaultValue
      return num.toString()
    },

    fmtPercent: (num: number | undefined): string => {
      if (num === undefined || num === null || isNaN(num)) return '--'
      return num.toFixed(2) + '%'
    },

    fmtAmount: (num: number | undefined): string => {
      if (!num) return '--'
      const yi = num / 100000000
      if (yi >= 10000) {
        return (yi / 10000).toFixed(2) + '万亿'
      }
      return yi.toFixed(0) + '亿'
    },

    getTodayDate: (): string => {
      const today = new Date()
      return (
        today.getFullYear() +
        String(today.getMonth() + 1).padStart(2, '0') +
        String(today.getDate()).padStart(2, '0')
      )
    },

    parseNewFormat: (text: any): any => {
      try {
        if (typeof text === 'object' && text !== null) {
          return text
        }
        if (typeof text === 'string') {
          return JSON.parse(text)
        }
        return text
      } catch (e) {
        return null
      }
    },

    safeGet: (value: any, defaultValue: number = 0): number => {
      return value !== undefined && value !== null ? value : defaultValue
    },
  }

  private formatLocalTradingDate(date: Date): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  private isSnapshotLimitUpStock(stock: any): boolean {
    if (!stock || !stock.code) return false
    if ((Number(stock.boardHeight) || 0) > 0) return true
    if ((Number(stock.highDays) || 0) > 0) return true
    if (String(stock.firstZtTime || '').trim()) return true
    if (String(stock.lastZtTime || '').trim()) return true
    return false
  }

  /**
   * 发送请求（使用增强版 apiService）
   */
  private async request(entry: string, params: any): Promise<any> {
    try {
      const data = await apiService.post(`/api/tdx/${entry}`, params, {
        context: 'tdx',
        ...API_CONFIG.CONTEXTS.TDX,
      })
      return data
    } catch (error) {
      return { error: true }
    }
  }

  /**
   * 获取市场统计数据
   */
  private async fetchMarketStats(): Promise<Partial<MarketData> | null> {
    try {
      const endpoint = API_CONFIG.ENDPOINTS.TDX.MARKET_STATS
      const result = await this.request(
        API_CONFIG.ENDPOINTS.TDX.MARKET_STATS,
        API_CONFIG.TDX_PARAMS.MARKET_STATS,
      )

      if (result?.scglobaldata && result.scglobaldata.length > 0) {
        const m = result.scglobaldata[0]

        const totalAmo =
          this.utils.safeGet(m.a999999amo) +
          this.utils.safeGet(m.a399001amo) +
          this.utils.safeGet(m.bjsamo)
        const lastAmo =
          this.utils.safeGet(m.a999999lastcuramo) +
          this.utils.safeGet(m.a399001lastcuramo) +
          this.utils.safeGet(m.a899050lastcuramo)

        return {
          upCount: this.utils.safeGet(m.upnum),
          downCount: this.utils.safeGet(m.downnum),
          ztCount: this.utils.safeGet(m.ztnum),
          dtCount: this.utils.safeGet(m.dtnum),
          totalAmo,
          amoDiff: totalAmo - lastAmo,

          indices: {
            sh: { change: this.utils.safeGet(m.a999999zaf) },
            hs300: { change: this.utils.safeGet(m.a300zaf) },
            zz500: { change: this.utils.safeGet(m.a500zaf) },
            zz1000: { change: this.utils.safeGet(m.a1000zaf) },
          },

          // 风格指数
          largeCapChange: this.utils.safeGet(m.bigzaf),    // 大票
          microCapChange: this.utils.safeGet(m.microzaf),  // 微盘

          moneyFlow: {
            main: this.utils.safeGet(m.zjlxmain),
            retail: this.utils.safeGet(m.zjlxls),
          },

          cddje: this.utils.safeGet(m.cddje),
          cddjzb: this.utils.safeGet(m.cddjzb),
          yesterdayZtPerformance: this.utils.safeGet(m.zrztzaf),
          volumeRatio: this.utils.safeGet(m.a880001lb),
        }
      }
    } catch (error) {}
    return null
  }

  /**
   * 获取涨停数据
   */
  private async fetchLimitData(date: string = ''): Promise<LimitData | null> {
    try {
      debugLog(`[fetchLimitData] 获取涨停数据，日期: ${date || '今日'}`)

      const params = [{
        ReqId: "201054",
        Tdate: date,
        Market: "0",
        blockstyle: "3",
        modname: "module_misc.dll"
      }]

      const result = await this.request('HQServ.hq_nlp_misc', params)

      // 直接解析 ResultSets
      if (result?.ResultSets && result.ResultSets.length >= 2) {
        const rows = result.ResultSets[1].Content || []
        const limitStats: LimitData = { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 }
        let maxBoard = 0

        rows.forEach((row: any[]) => {
          const n002 = parseInt(row[1]) || 0  // N002 是第2个字段（索引1）
          const n003 = parseInt(row[2]) || 0  // N003 是第3个字段（索引2）

          if (n002 === 1) limitStats.yiban = n003
          else if (n002 === 2) limitStats.erban = n003
          else if (n002 === 3) limitStats.sanban = n003
          else if (n002 >= 4) limitStats.sibanPlus += n003

          if (n002 > maxBoard) maxBoard = n002
        })
        limitStats.maxBoard = maxBoard || undefined

        return limitStats
      }
    } catch (error) {
      console.error('[fetchLimitData] 失败:', error)
    }
    return null
  }


  /**
   * 获取昨日信息
   */
  private async fetchYesterdayInfo(): Promise<{
    yesterdayDate: string | null
    yesterdayFengban: number | null
  }> {
    try {
      debugLog('[fetchYesterdayInfo] 获取昨日信息...')

      const result = await this.request('CWServ.cfg_fx_dxqx_jyr', { Params: [] })

      if (result?.ResultSets && result.ResultSets.length >= 2) {
        const rs0 = result.ResultSets[0]
        const rs1 = result.ResultSets[1]

        let yesterdayDate = null
        let yesterdayFengban = null

        if (rs0.Content && rs0.Content[0]) {
          let dateStr = rs0.Content[0][0]
          debugLog('[fetchYesterdayInfo] 原始日期:', dateStr)

          if (dateStr && dateStr.includes('-')) {
            dateStr = dateStr.split(' ')[0].replace(/-/g, '')
          }
          yesterdayDate = dateStr
          debugLog('[fetchYesterdayInfo] 格式化日期:', yesterdayDate)
        }

        if (rs1.Content && rs1.Content[0]) {
          yesterdayFengban = parseFloat(rs1.Content[0][2]) || null
          debugLog('[fetchYesterdayInfo] 昨日封板率:', yesterdayFengban)
        }

        return { yesterdayDate, yesterdayFengban }
      }
    } catch (error) {
      console.error('[fetchYesterdayInfo] 失败:', error)
    }
    return { yesterdayDate: null, yesterdayFengban: null }
  }


  /**
   * 获取炸板数据
   */
  private async fetchZhaban(): Promise<ZhabanData | null> {
    try {
      const params = [{
        ReqId: "1000",
        Market: "0",
        BkCode: "880201",
        blockstyle: "string",
        modname: "module_misc.dll"
      }]

      const result = await this.request('HQServ.hq_nlp_misc', params)
      if (result?.ResultSets && result.ResultSets.length >= 2) {
        const row = result.ResultSets[1].Content[0] || []

        // 注意：数组索引从0开始
        // row[6] 对应 N007（炸板数）
        // row[17] 对应 N018（涨停数）
        const zhabanNum = parseFloat(row[6]) || 0
        const ztNum = parseFloat(row[17]) || 0
        const total = zhabanNum + ztNum


        return {
          count: zhabanNum,
          rate: total > 0 ? (zhabanNum / total * 100) : 0,
          fengbanRate: total > 0 ? ((1 - zhabanNum / total) * 100) : 0,
          ztCount: ztNum
        }
      }
    } catch (error) {
      console.error('[fetchZhaban] 失败:', error)
    }
    return null
  }

  /**
   * 获取情绪数据
   */
  private async fetchEmotionData(): Promise<{ value: number; status: string }> {
    try {
      debugLog('[fetchEmotionData] 获取情绪数据...')

      const today = new Date()
      const dateStr = today.getFullYear() +
        String(today.getMonth() + 1).padStart(2, '0') +
        String(today.getDate()).padStart(2, '0')

      debugLog('[fetchEmotionData] 请求日期:', dateStr)

      const params = [{
        ReqId: "200200",
        Code: "DXQX_AG",
        IndexCode: "999999",
        BeginDate: "",
        EndDate: dateStr,
        TradeDays: "1",
        Page: "0",
        PageSize: "5",
        modname: "mod_dxqx.dll"
      }]

      const result = await this.request('HQServ.hq_nlp_dxqx', params)

      // 直接解析 ResultSets（和HTML页面一样）
      if (result?.ResultSets && result.ResultSets.length > 1) {
        const rows = result.ResultSets[1].Content || []
        debugLog(`[fetchEmotionData] 获取到 ${rows.length} 行数据`)

        if (rows.length > 0) {
          const latest = rows[rows.length - 1]
          debugLog('[fetchEmotionData] 最新数据行:', latest)

          // 解析字段（数组索引）
          const date = latest[0]  // 日期
          const preclsoe = parseFloat(latest[1]) || 1  // 前收盘
          const min = latest[2]  // min字段


          // 解析min字段
          const minArr = min ? min.split(',') : []
          const lastVal = minArr.length > 0 ? parseFloat(minArr[minArr.length - 1]) : null


          let qxVal = 0
          if (lastVal !== null) {
            qxVal = 100 * lastVal / preclsoe
          }

          // 判断情绪状态（和HTML页面完全一样）
          let status = '震荡'
          if (qxVal >= 1) {
            status = '活跃'
          } else if (qxVal >= -2) {
            status = '震荡'
          } else if (qxVal >= -4) {
            status = '低迷'
          } else {
            status = '冰点'
          }
          return { value: qxVal, status }
        }
      } else {
        debugLog('[fetchEmotionData] 数据结构错误:', result)
      }
    } catch (error) {
      console.error('[fetchEmotionData] 请求失败:', error)
    }

    // 降级方案
    debugLog('[fetchEmotionData] 使用降级数据')
    return { value: 0, status: '震荡' }
  }

  /**
   * 获取前一个交易日（从快照列表中找）
   */
  private async getLastTradeDate(): Promise<string | null> {
    try {
      const bundles = await snapshotFacade.listSnapshotFrameBundles({
        type: 'daily',
        allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
        excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
        sort: 'desc',
        limit: 2,
      })

      const tradeDates = Array.from(
        new Set(
          (bundles || [])
            .map((bundle) => String(bundle.tradingDate || '').trim())
            .filter(Boolean),
        ),
      )
        .sort()
        .reverse() // 最新的在前

      if (tradeDates.length === 0) return null

      const todayStr = this.formatLocalTradingDate(new Date())

      // 如果最新的快照是今天，返回前一个
      if (tradeDates[0] === todayStr && tradeDates.length > 1) {
        return tradeDates[1]
      }

      // 否则返回最新的
      return tradeDates[0]
    } catch (error) {
      console.warn('[DragonBreathAnalyzer] 获取前一个交易日失败:', error)
      return null
    }
  }

  /**
   * 获取昨日涨停今日表现
   */
  private async fetchYesterdayLimitUpStats(): Promise<void> {
    try {
      // 获取前一个交易日（自动跳过周末）
      const lastTradeDate = await this.getLastTradeDate()

      if (!lastTradeDate) {
        debugLog('[DragonBreathAnalyzer] 无历史交易日数据，跳过')
        this.setDefaultStats()
        return
      }

      const [yesterdayBundle] = await snapshotFacade.listSnapshotFrameBundles({
        type: 'daily',
        tradingDate: lastTradeDate,
        allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
        excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
        sort: 'desc',
        limit: 1,
      })

      const yesterdayStocks = (yesterdayBundle?.hotlist || []).filter((stock: any) =>
        this.isSnapshotLimitUpStock(stock),
      )

      if (!yesterdayStocks.length) {
        debugLog(`[DragonBreathAnalyzer] ${lastTradeDate} 无涨停数据，跳过`)
        this.setDefaultStats()
        return
      }
      const codes = yesterdayStocks.map((s: any) => s.code).filter(Boolean)

      if (codes.length === 0) {
        this.setDefaultStats()
        return
      }

      const quotes = await apiService.getQuotes(codes, {
        context: 'breath',
        cache: false,
        priority: 'high',
      })

      const quoteMap: Record<string, any> = {}
      const diffArray = quotes?.data?.diff || []
      diffArray.forEach((item: any) => {
        const code = item.f12
        if (code) {
          quoteMap[code] = {
            change: item.f3,
            price: item.f2,
            name: item.f14,
          }
        }
      })

      // 调用 calculateStatsOnly 方法统计
      const stats = this.calculateStatsOnly(yesterdayStocks, quoteMap)
      this.state.marketData.yesterdayLimitStats = stats

      debugLog('[DragonBreathAnalyzer] 昨日涨停表现:', {
        日期: lastTradeDate,
        总数: stats.total,
        平均涨幅: stats.avgChange + '%',
        红盘率: ((stats.redCount / stats.total) * 100).toFixed(2) + '%',
        跌停: stats.dtCount,
        大面: stats.bigLossCount,
      })
    } catch (error) {
      console.warn('[DragonBreathAnalyzer] 获取昨日涨停统计数据失败:', error)
      this.setDefaultStats()
    }
  }

  /**
   * 统计涨停股票今日表现
   */
  private calculateStatsOnly(stocks: any[], quoteMap: any) {
    let totalDtCount = 0
    let totalBigLossCount = 0
    let totalRedCount = 0
    let totalGreenCount = 0
    const allChanges: number[] = []

    for (const stock of stocks) {
      const code = stock.code
      const quote = quoteMap[code]
      if (!quote) continue

      const change = quote.change
      allChanges.push(change)

      const isLimitDown = StockUtils.isLimitDown(change, code, stock.name)

      if (isLimitDown) totalDtCount++
      if (change <= -5) totalBigLossCount++
      if (change > 0) totalRedCount++
      if (change < 0) totalGreenCount++
    }

    const avgChange = allChanges.length
      ? allChanges.reduce((a, b) => a + b, 0) / allChanges.length
      : 0

    return {
      total: stocks.length,
      dtCount: totalDtCount,
      bigLossCount: totalBigLossCount,
      redCount: totalRedCount,
      greenCount: totalGreenCount,
      avgChange: Number(avgChange.toFixed(2)),
      maxChange: allChanges.length ? Math.max(...allChanges) : 0,
      minChange: allChanges.length ? Math.min(...allChanges) : 0,
    }
  }

  /**
   * 设置默认统计值
   */
  private setDefaultStats() {
    this.state.marketData.yesterdayLimitStats = {
      total: 0,
      dtCount: 0,
      bigLossCount: 0,
      redCount: 0,
      greenCount: 0,
      avgChange: 0,
      maxChange: 0,
      minChange: 0,
    }
  }

  private async fetchAllData(): Promise<void> {
    if (this.state._fetching) return
    this.state._fetching = true

    try {

      // 1. 先获取昨日信息（需要日期）
      const yesterdayInfo = await this.fetchYesterdayInfo()
      debugLog('[fetchAllData] 昨日信息:', yesterdayInfo)

      // 2. 并行获取其他不依赖的数据
      const [marketResult, todayLimitResult, zhabanResult, emotionResult] =
        await Promise.allSettled([
          this.fetchMarketStats(),
          this.fetchLimitData(), // 今日涨停
          this.fetchZhaban(),
          this.fetchEmotionData(),

        ])

      // 3. 获取昨日涨停数据（需要昨日日期）
      let yesterdayLimit = null
      if (yesterdayInfo.yesterdayDate) {
        yesterdayLimit = await this.fetchLimitData(yesterdayInfo.yesterdayDate)

      }

      // 处理市场统计数据
      if (marketResult.status === 'fulfilled' && marketResult.value) {
        const marketData = marketResult.value
        Object.assign(this.state.marketData, marketData)
      }


      // 处理炸板数据
      if (zhabanResult.status === 'fulfilled' && zhabanResult.value) {
        this.state.marketData.zhaban = zhabanResult.value
      }

      // 处理今日涨停数据
      if (todayLimitResult.status === 'fulfilled' && todayLimitResult.value) {
        const todayLimit = todayLimitResult.value
        this.state.marketData.limitData = todayLimit
        if (todayLimit.maxBoard) {
          this.state.marketData.maxContinuousDays = todayLimit.maxBoard
        }
      }

      // 处理昨日涨停数据
      if (yesterdayLimit) {
        this.state.marketData.yesterdayLimit = yesterdayLimit
        debugLog('[fetchAllData] 昨日涨停数据已设置:', yesterdayLimit)

        // 计算晋级率（如果今日和昨日数据都有）
        if (todayLimitResult.status === 'fulfilled' && todayLimitResult.value) {
          const todayLimit = todayLimitResult.value

          // 初始化晋级率对象
          this.state.marketData.passRate = {
            to2: 0,
            to3: 0,
            to4: 0,
          }

          // 计算一进二晋级率
          if (yesterdayLimit.yiban > 0) {
            this.state.marketData.passRate.to2 = (todayLimit.erban / yesterdayLimit.yiban) * 100
          }

          // 计算二进三晋级率
          if (yesterdayLimit.erban > 0) {
            this.state.marketData.passRate.to3 = (todayLimit.sanban / yesterdayLimit.erban) * 100
          }

          // 计算三进四晋级率
          if (yesterdayLimit.sanban > 0) {
            this.state.marketData.passRate.to4 = (todayLimit.sibanPlus / yesterdayLimit.sanban) * 100
          }

        }
      }

      // 处理情绪数据
      if (emotionResult.status === 'fulfilled' && emotionResult.value) {
        this.state.marketData.emotionValue = emotionResult.value.value
        this.state.marketData.emotionStatus = emotionResult.value.status
      }

      // 4. 获取昨日涨停详细统计（使用真实个股行情数据）
      await this.fetchYesterdayLimitUpStats()


      this.state.marketData.timestamp = Date.now()

      // ========== 存入 dataLayer ==========
      await this.saveToDataLayer()


    } catch (error) {
      console.error('[fetchAllData] 失败:', error)
    } finally {
      this.state._fetching = false
    }
  }

  /**
   * 将数据存入 dataLayer
   */
  private async saveToDataLayer(): Promise<void> {
    try {
      debugLog('[saveToDataLayer] 开始保存数据到 dataLayer...')

      // 构建因子数据
      const factors = this.buildFactorData()

      // 构建 breath 数据 - 确保包含所有字段
      const breathData = {
        timestamp: Date.now(),
        sentiment: {
          overall: this.state.sentiment.overall,
          phase: this.state.sentiment.phase,
          phaseName: this.state.sentiment.phaseName,
          riskLevel: this.state.sentiment.riskLevel,
          suggestion: this.state.sentiment.suggestion,
          phaseInfo: this.state.sentiment.phaseInfo,
          reference: { tdxEmotion: this.state.marketData.emotionValue },
        },
        marketData: {
          // 基础数据
          upCount: this.state.marketData.upCount,
          downCount: this.state.marketData.downCount,
          ztCount: this.state.marketData.ztCount,
          dtCount: this.state.marketData.dtCount,
          totalAmo: this.state.marketData.totalAmo,
          amoDiff: this.state.marketData.amoDiff,
          volumeRatio: this.state.marketData.volumeRatio,

          // 炸板数据
          zhaban: this.state.marketData.zhaban,
          zhabanRate: this.state.marketData.zhaban?.rate,

          // 涨停数据
          limitData: this.state.marketData.limitData,
          yesterdayLimit: this.state.marketData.yesterdayLimit,

          // 晋级率 - 确保传递
          passRate: this.state.marketData.passRate || { to2: 0, to3: 0, to4: 0 },

          // 指数数据
          indices: this.state.marketData.indices,

          // 风格指数 - 确保传递
          largeCapChange: this.state.marketData.largeCapChange,    // 大票
          microCapChange: this.state.marketData.microCapChange,    // 微盘

          // 资金流向
          moneyFlow: this.state.marketData.moneyFlow,
          cddje: this.state.marketData.cddje,
          cddjzb: this.state.marketData.cddjzb,

          // 情绪数据
          emotionValue: this.state.marketData.emotionValue,
          emotionStatus: this.state.marketData.emotionStatus,

          // 昨日涨停表现
          yesterdayZtPerformance: this.state.marketData.yesterdayZtPerformance,

          // 其他
          maxContinuousDays: this.state.marketData.maxContinuousDays,
          yesterdayLimitUpStats: this.state.marketData.yesterdayLimitStats,

          // 时间戳
          timestamp: this.state.marketData.timestamp,
        },
        factors,
      }

      debugLog('[saveToDataLayer] 准备保存的数据:')
      debugLog('  大票:', breathData.marketData.largeCapChange)
      debugLog('  微盘:', breathData.marketData.microCapChange)
      debugLog('  晋级率:', breathData.marketData.passRate)
      debugLog('  上证:', breathData.marketData.indices?.sh?.change)

      // 存入 dataLayer
      if (typeof dataLayer !== 'undefined') {
        dataLayer.updateBreathData(breathData)
        debugLog('[saveToDataLayer] ✅ 数据已保存到 dataLayer')
      } else {
        console.warn('[saveToDataLayer] dataLayer 未定义')
      }

    } catch (error) {
      console.error('[saveToDataLayer] 保存失败:', error)
    }
  }

  /**
 * 构建因子数据
 */
private buildFactorData(): any[] {
  try {
    const marketData = this.state.marketData

    const factors = Object.entries(EMOTION_FACTOR_CONFIG.factors).map(
      ([key, factor]: [string, EmotionFactor]) => {
        const rawValue = factor.getValue(marketData)

        return {
          id: factor.id,
          name: factor.name,
          rawValue: rawValue,
          description: factor.description,
          unit: factor.unit || '',
        }
      },
    )

    debugLog(`[buildFactorData] 构建了 ${factors.length} 个因子`)
    return factors

  } catch (error) {
    console.error('[buildFactorData] 构建因子数据失败:', error)
    return []
  }
}

  /**
   * 获取风险等级
   */
  private getRiskLevel(zhabanRate: number, phase?: string): string {
    if (phase) {
      switch (phase) {
        case '退潮':
          return '高'
        case '高潮':
          return zhabanRate > 30 ? '高' : '中'
        case '冰点':
          return '中'
      }
    }

    if (zhabanRate > 40) return '高'

    return '中'
  }

  /**
   * 获取完整的阶段信息
   */
  public getPhaseInfo(phaseName: string): EmotionPhase | null {
    return EMOTION_PHASE_BY_NAME[phaseName] || null
  }

  /**
   * 获取当前阶段的所有信息
   */
  public getCurrentPhaseInfo(): EmotionPhase {
    const currentPhaseName = this.state.sentiment.phaseName || '启动'
    return this.getPhaseInfo(currentPhaseName) || EMOTION_PHASES.START
  }

  /**
   * 检测是否为退潮期（基于市场结构）
   */
  private isRecession(marketData: MarketData): boolean {
    const zhabanRate = marketData.zhaban?.rate || 0
    const dtCount = marketData.dtCount
    const promotionRate = marketData.passRate?.to2 || 0
    const yesterdayZtAvgChange = marketData.yesterdayZtPerformance || 0
    const ztCount = marketData.ztCount

    // 获取前几天的数据用于对比
    const prevData = this.state.history[this.state.history.length - 1]?.marketData
    const prevZtCount = prevData?.ztCount || ztCount
    const prevDtCount = prevData?.dtCount || dtCount
    const prevMaxContinuousDays = prevData?.maxContinuousDays || 0

    // ========== 退潮核心风险信号 ==========
    let coreRiskSignals = 0

    // 1. 炸板率极高 >45%
    if (zhabanRate > 45) coreRiskSignals++

    // 2. 跌停潮 >20家
    if (dtCount > 20) coreRiskSignals++

    // 3. 晋级率崩盘 <10%
    if (promotionRate < 10) coreRiskSignals++

    // 4. 亏钱效应显著 昨日涨停表现 < -2%
    if (yesterdayZtAvgChange < -2) coreRiskSignals++

    // ========== 退潮辅助风险信号 ==========
    let supportRiskSignals = 0

    // 5. 炸板率高 35-45%
    if (zhabanRate > 35 && zhabanRate <= 45) supportRiskSignals++

    // 6. 跌停增加 比前一天翻倍且>10家
    if (dtCount > prevDtCount * 2 && dtCount > 10) supportRiskSignals++

    // 7. 涨停数大幅回落 比前一天下降50%以上
    if (ztCount < prevZtCount * 0.5 && prevZtCount > 60) supportRiskSignals++

    // 8. 连板高度断崖 前一天≥6板，今天≤2板
    if (prevMaxContinuousDays >= 6 && (marketData.maxContinuousDays || 0) <= 2) supportRiskSignals++

    // ========== 退潮期判断 ==========
    // 条件A：至少2个核心风险信号
    if (coreRiskSignals >= 2) {
      return true
    }

    // 条件B：1个核心风险信号 + 2个辅助风险信号
    if (coreRiskSignals >= 1 && supportRiskSignals >= 2) {
      return true
    }

    // 条件C：多个辅助结构信号同时恶化
    if (supportRiskSignals >= 3) {
      return true
    }

    return false
  }

  private resolveMarketEmotionPhase(marketData: MarketData): EmotionPhase {
    const zhabanRate = marketData.zhaban?.rate || 0
    const dtCount = marketData.dtCount || 0
    const ztCount = marketData.ztCount || 0
    const upCount = marketData.upCount || 0
    const downCount = marketData.downCount || 0
    const maxContinuousDays = marketData.maxContinuousDays || 0
    const promotionRate = marketData.passRate?.to2 || 0
    const yesterdayZtAvgChange =
      marketData.yesterdayLimitStats?.avgChange ?? marketData.yesterdayZtPerformance ?? 0
    const upRatio = upCount + downCount > 0 ? upCount / (upCount + downCount) : 0

    // 风险优先：退潮是结构恶化，不用分数硬判。
    if (
      this.isRecession(marketData) ||
      (zhabanRate >= 38 && promotionRate < 18) ||
      (dtCount >= 15 && upRatio < 0.52) ||
      (yesterdayZtAvgChange < -1.5 && zhabanRate >= 30)
    ) {
      return EMOTION_PHASES.RETREAT
    }

    // 高潮：强度高且风险尚未失控，重点识别“强但拥挤”。
    if (
      (ztCount >= 90 && maxContinuousDays >= 5 && zhabanRate < 35) ||
      (ztCount >= 75 && upRatio >= 0.68 && dtCount <= 8 && promotionRate >= 18)
    ) {
      return EMOTION_PHASES.CLIMAX
    }

    // 发酵：赚钱效应扩散，强度和承接同时改善。
    if (
      (ztCount >= 55 && upRatio >= 0.58 && promotionRate >= 18 && dtCount <= 10) ||
      (ztCount >= 45 && maxContinuousDays >= 3 && yesterdayZtAvgChange >= 1 && zhabanRate < 38)
    ) {
      return EMOTION_PHASES.FERMENT
    }

    // 启动：风险收缩、上涨比例改善，但扩散还不充分。
    if (
      (upRatio >= 0.48 && dtCount <= 12) ||
      (ztCount >= 30 && zhabanRate < 40) ||
      (promotionRate >= 12 && dtCount <= 15)
    ) {
      return EMOTION_PHASES.START
    }

    return EMOTION_PHASES.ICE
  }

  /**
   * 更新情绪阶段信息
   */
  private updateSentimentWithPhase(): void {
    try {
      const marketData = this.state.marketData
      let phaseInfo: EmotionPhase

      phaseInfo = this.resolveMarketEmotionPhase(marketData)

      const riskLevel = this.getRiskLevel(marketData.zhaban?.rate || 0, phaseInfo.name)

      this.state.sentiment = {
        ...this.state.sentiment,
        overall: 0,
        phase: phaseInfo.value,
        phaseName: phaseInfo.name, // ✅ 添加 phaseName
        phaseInfo: phaseInfo,
        riskLevel: riskLevel,
        suggestion: phaseInfo.suggestion,
        phaseIcon: phaseInfo.icon,
        phaseColor: phaseInfo.color,
        phaseGradient: phaseInfo.gradient,
        phaseFeatures: phaseInfo.features,
      }
    } catch (error) {
      console.error('[DragonBreathAnalyzer] 更新情绪阶段失败:', error)
      const defaultPhase = EMOTION_PHASES.START
      this.state.sentiment = {
        ...this.state.sentiment,
        overall: 0,
        phase: defaultPhase.value,
        phaseName: defaultPhase.name,
        phaseInfo: defaultPhase,
        riskLevel: '中',
        suggestion: defaultPhase.suggestion,
        phaseIcon: defaultPhase.icon,
        phaseColor: defaultPhase.color,
        phaseGradient: defaultPhase.gradient,
        phaseFeatures: defaultPhase.features,
      }
    }
  }

  async analyzeMarketBreath(force: boolean = false): Promise<boolean> {
    const now = Date.now()
    if (!force && now - this.lastAnalysisTime < this.ANALYSIS_COOLDOWN) {
      return false
    }
    if (this.state._analyzing) return false
    this.state._analyzing = true

    try {
      // 获取数据（会自动存入 dataLayer）
      await this.fetchAllData()

      // 更新情绪阶段
      this.updateSentimentWithPhase()

      // 触发事件
      EventManager.emit(AppEvents.BREATH.UPDATED, {
        sentiment: this.state.sentiment,
        marketData: this.state.marketData,
        timestamp: Date.now(),
      })

      this.feedbackToAlgorithm()
      this.recordHistory()
      this.lastAnalysisTime = Date.now()

      debugLog('[analyzeMarketBreath] ✅ 分析完成，情绪阶段:', this.state.sentiment.phaseName)
      return true

    } catch (error) {
      console.error('[analyzeMarketBreath] 分析失败:', error)
      return false
    } finally {
      this.state._analyzing = false
    }
  }

  /**
   * 记录历史
   */
  private recordHistory(): void {
    const snapshot: BreathHistorySnapshot = {
      timestamp: Date.now(),
      sentiment: { ...this.state.sentiment },
      marketData: {
        upCount: this.state.marketData.upCount,
        downCount: this.state.marketData.downCount,
        ztCount: this.state.marketData.ztCount,
        dtCount: this.state.marketData.dtCount,
        limitData: { ...this.state.marketData.limitData },
        zhaban: { ...this.state.marketData.zhaban },
        emotionValue: this.state.marketData.emotionValue,
        maxContinuousDays: this.state.marketData.maxContinuousDays,
        yesterdayZtPerformance: this.state.marketData.yesterdayZtPerformance,
      },
    }

    this.state.history.push(snapshot)
    if (this.state.history.length > 100) {
      this.state.history.shift()
    }
  }

  /**
   * 调度分析（防抖）
   */
  private scheduleAnalysis(): void {
    if (this.analysisTimeout) {
      clearTimeout(this.analysisTimeout)
    }

    this.analysisTimeout = setTimeout(() => {
      if (!this.destroyed && !this.state._analyzing) {
        this.analyzeMarketBreath()
      }
      this.analysisTimeout = null
    }, 500)
  }

  /**
   * 停止自动刷新
   */
  stopAutoRefresh(): void {
    refreshScheduler.stopTask('dragon.breath')
  }

  /**
   * 获取状态
   */
  getStatus(): any {
    if (this.destroyed) return null

    return {
      initialized: this.state.initialized,
      sentiment: {
        phase: this.state.sentiment.phase,
        phaseName: this.state.sentiment.phaseName,
        overall: this.state.sentiment.overall,
        riskLevel: this.state.sentiment.riskLevel,
      },
      marketData: {
        upCount: this.state.marketData.upCount,
        downCount: this.state.marketData.downCount,
        ztCount: this.state.marketData.ztCount,
        dtCount: this.state.marketData.dtCount,
        zhabanRate: this.state.marketData.zhaban.rate,
      },
      themeImpact: this.state.themeImpact,
      hotThemesCount: this.state.hotThemesCount,
      historyCount: this.state.history.length,
      listeners: this.unsubscribeFns.length,
      destroyed: this.destroyed,
    }
  }

  /**
   * 手动刷新
   */
  refresh(): Promise<boolean> {
    if (this.destroyed) return Promise.resolve(false)
    return this.analyzeMarketBreath()
  }

  /**
   * 获取市场情绪
   */
  getMarketSentiment(): Sentiment {
    if (this.destroyed) return this.getDefaultSentiment()
    return {
      ...this.state.sentiment,
      phaseInfo: this.state.sentiment.phaseInfo,
    }
  }

  /**
   * 获取市场数据
   */
  getMarketData(): MarketData {
    if (this.destroyed) return this.getDefaultMarketData()
    return { ...this.state.marketData }
  }

  /**
   * 清除缓存
   */
  clearCache(): void {
    if (this.destroyed) return
    this.state.history = []
    this.state.cache = {
      marketStats: null,
      limitStats: null,
      lastFetch: 0,
    }
  }

  /**
   * 重置
   */
  reset(): void {
    if (this.destroyed) return
    this.stopAutoRefresh()
    this.clearCache()

    this.state.marketData = this.getDefaultMarketData()
    this.state.sentiment = this.getDefaultSentiment()
    this.state.themeImpact = 0
    this.state.hotThemesCount = 0
  }

  /**
   * 销毁实例
   */
  destroy(): void {
    if (this.destroyed) return

    this.destroyed = true

    if (this.analysisTimeout) {
      clearTimeout(this.analysisTimeout)
      this.analysisTimeout = null
    }

    this.stopAutoRefresh()

    this.unsubscribeFns.forEach((unsub) => {
      try {
        unsub()
      } catch (e) {
        console.warn('[DragonBreathAnalyzer] 清理订阅失败:', e)
      }
    })
    this.unsubscribeFns = []

    this.state.initialized = false
  }

  static readonly PHASES = EMOTION_PHASES
  static readonly VERSION = '2.5.0' // 升级版本号
}

// 导出单例
export const dragonBreathAnalyzer = DragonBreathAnalyzer.getInstance()

// 挂载到 window
if (typeof window !== 'undefined') {
  ;(window as any).dragonBreathAnalyzer = dragonBreathAnalyzer
}
