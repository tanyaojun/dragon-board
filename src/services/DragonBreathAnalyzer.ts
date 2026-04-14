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
  getEmotionPhaseByScore,
  type EmotionPhase, // ← 确保这行存在
} from '../types/emotion'
import { apiService } from './apiService'
import { EventManager } from '../utils/eventManager'
import { API_CONFIG } from '../config/constants'
import { dataLayer } from './DataLayer'
import { isTradingTime } from '../utils/time'
import { StockUtils } from '../utils/common'

import { EMOTION_SCORE_CONFIG, type EmotionFactor } from '../types/emotion'

/**
 * 龙息分析器状态
 */
interface DragonBreathState {
  initialized: boolean
  marketData: MarketData
  sentiment: Sentiment
  history: BreathHistorySnapshot[]
  refreshTimer: number | null
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
      refreshTimer: null,
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

    console.log('[DragonBreathAnalyzer] 📊 初始化龙息分析器...')

    // 设置必要的监听器
    this.setupEssentialListeners()

    // 执行首次分析
    await this.analyzeMarketBreath()

    // ✅ 启动定时刷新（只在交易时间执行）
    this.startAutoRefresh()

    this.state.initialized = true

    console.log('[DragonBreathAnalyzer] ✅ 初始化完成')

    return true
  }

  /**
   * 启动定时刷新
   */
  startAutoRefresh(interval: number = 300000): void {
    if (this.state.refreshTimer) {
      clearInterval(this.state.refreshTimer)
    }

    this.state.refreshTimer = setInterval(() => {
      if (!isTradingTime()) return
      this.analyzeMarketBreath(false).catch((err) => {
        console.warn('[DragonBreathAnalyzer] 定时分析失败:', err)
      })
    }, interval) as unknown as number
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
        sz: { change: 0 },
        cy: { change: 0 },
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
      smallCapChange: 0,
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
    const defaultPhase = EMOTION_PHASES.OSCILLATION
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
      factorScores: {},
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
        score: sentiment.overall,
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
            sz: { change: this.utils.safeGet(m.a399001zaf) },
            cy: { change: this.utils.safeGet(m.a399006zaf) },
            hs300: { change: this.utils.safeGet(m.a300zaf) },
            zz500: { change: this.utils.safeGet(m.a500zaf) },
            zz1000: { change: this.utils.safeGet(m.a1000zaf) },
          },

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
      const params = JSON.parse(JSON.stringify(API_CONFIG.TDX_PARAMS.LIMIT_DATA))
      params[0].Tdate = date
      const result = await this.request(API_CONFIG.ENDPOINTS.TDX.LIMIT_DATA, params)

      const data = this.utils.parseNewFormat(result)
      const limitStats: LimitData = { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 }
      let found = false

      if (data && data.ResultSets && data.ResultSets.length >= 2) {
        const rows = data.ResultSets[1].Content || []
        const cols = data.ResultSets[1].ColDes || []

        let n002Idx = 1,
          n003Idx = 2
        cols.forEach((col: any, idx: number) => {
          if (col.Name === 'N002') n002Idx = idx
          if (col.Name === 'N003') n003Idx = idx
        })

        rows.forEach((row: any[]) => {
          const ban = parseInt(row[n002Idx]) || 0
          const count = parseInt(row[n003Idx]) || 0

          if (ban === 1) limitStats.yiban = count
          else if (ban === 2) limitStats.erban = count
          else if (ban === 3) limitStats.sanban = count
          else if (ban >= 4) limitStats.sibanPlus += count

          if (count > 0) found = true
        })
      } else if (data && data.tables && data.tables.length >= 2) {
        data.tables[1].forEach((row: any) => {
          const ban = parseInt(row.N002) || 0
          const count = parseInt(row.N003) || 0

          if (ban === 1) limitStats.yiban = count
          else if (ban === 2) limitStats.erban = count
          else if (ban === 3) limitStats.sanban = count
          else if (ban >= 4) limitStats.sibanPlus += count

          if (count > 0) found = true
        })
      }

      return found ? limitStats : null
    } catch (error) {
      return null
    }
  }

  /**
   * 获取昨日信息
   */
  private async fetchYesterdayInfo(): Promise<{
    yesterdayDate: string | null
    yesterdayFengban: number | null
  }> {
    try {
      const result = await this.request(
        API_CONFIG.ENDPOINTS.TDX.YESTERDAY_INFO,
        API_CONFIG.TDX_PARAMS.YESTERDAY_INFO,
      )

      if (result?.ResultSets && result.ResultSets.length >= 2) {
        const rs0 = result.ResultSets[0]
        const rs1 = result.ResultSets[1]

        let yesterdayDate = null
        let yesterdayFengban = null

        if (rs0.Content && rs0.Content[0]) {
          let dateStr = rs0.Content[0][0]
          if (dateStr && dateStr.includes('-')) {
            dateStr = dateStr.split(' ')[0].replace(/-/g, '')
          }
          yesterdayDate = dateStr
        }

        if (rs1.Content && rs1.Content[0]) {
          yesterdayFengban = rs1.Content[0][2]
        }

        return { yesterdayDate, yesterdayFengban }
      }
    } catch (error) {}
    return { yesterdayDate: null, yesterdayFengban: null }
  }

  /**
   * 获取炸板数据
   */
  private async fetchZhaban(): Promise<ZhabanData | null> {
    try {
      const result = await this.request(
        API_CONFIG.ENDPOINTS.TDX.ZHABAN_DATA,
        API_CONFIG.TDX_PARAMS.ZHABAN_DATA,
      )

      const data = this.utils.parseNewFormat(result)

      if (data && data.ErrorCode === 0 && data.tables && data.tables.length >= 2) {
        const info = data.tables[1][0] || {}
        const zhabanNum = parseFloat(info.N007) || 0
        const ztNum = parseFloat(info.N018) || 0
        const total = zhabanNum + ztNum

        return {
          count: zhabanNum,
          rate: total > 0 ? (zhabanNum / total) * 100 : 0,
          fengbanRate: total > 0 ? (ztNum / total) * 100 : 0,
          ztCount: ztNum,
        }
      }
    } catch (error) {}
    return null
  }

  /**
   * 获取情绪数据
   */
  private async fetchEmotionData(): Promise<{ value: number; status: string }> {
    try {
      const today = this.utils.getTodayDate()
      const params = JSON.parse(JSON.stringify(API_CONFIG.TDX_PARAMS.EMOTION_DATA))
      params[0].EndDate = today
      const result = await this.request(API_CONFIG.ENDPOINTS.TDX.EMOTION_DATA, params)

      if (result?.ResultSets && result.ResultSets.length >= 2) {
        const dataPoints = result.ResultSets[1]?.Content || []

        if (dataPoints.length > 0) {
          const latest = dataPoints[dataPoints.length - 1]
          // 假设情绪值在索引 3，并且是 0-100 的值
          let rawValue = parseFloat(latest[3])

          if (!isNaN(rawValue)) {
            // 如果值大于 1，说明是百分比，除以 100 得到 0-1 范围
            let emotionValue = rawValue > 1 ? rawValue / 100 : rawValue

            // 如果还是大于 1，说明是 0-100 的原始值，再除一次
            if (emotionValue > 1) {
              emotionValue = emotionValue / 100
            }

            let status = '震荡'
            if (emotionValue >= 0.7) status = '活跃'
            else if (emotionValue >= 0.5) status = '正常'
            else if (emotionValue >= 0.3) status = '低迷'
            else status = '冰点'

            return { value: emotionValue, status }
          }
        }
      }
    } catch (error) {
      console.warn('[DragonBreathAnalyzer] 获取情绪数据失败:', error)
    }
    return { value: 0.5, status: '震荡' }
  }

  /**
   * 获取前一个交易日（从快照列表中找）
   */
  private async getLastTradeDate(): Promise<string | null> {
    try {
      const snapshotDates = await dataLayer.getSnapshotDates()

      // 过滤出日级快照
      const tradeDates = snapshotDates
        .filter((date) => date.includes('日级快照'))
        .map((date) => date.replace('[日级快照] ', ''))
        .sort()
        .reverse() // 最新的在前

      if (tradeDates.length === 0) return null

      const todayStr = new Date().toISOString().slice(0, 10)

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
        console.log('[DragonBreathAnalyzer] 无历史交易日数据，跳过')
        this.setDefaultStats()
        return
      }

      const yesterdaySnapshot = await dataLayer.getSnapshotFromDB(`[日级快照] ${lastTradeDate}`)

      if (!yesterdaySnapshot?.limitUpStocks?.length) {
        console.log(`[DragonBreathAnalyzer] ${lastTradeDate} 无涨停数据，跳过`)
        this.setDefaultStats()
        return
      }

      const yesterdayStocks = yesterdaySnapshot.limitUpStocks
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

      console.log('[DragonBreathAnalyzer] 昨日涨停表现:', {
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
      // 第一批：基础数据获取
      const [marketResult, limitResult, yesterdayResult, tdxZhabanResult, emotionResult] =
        await Promise.allSettled([
          this.fetchMarketStats(),
          this.fetchLimitData(),
          this.fetchYesterdayInfo(),
          this.fetchZhaban(),
          this.fetchEmotionData(),
          // this.fetchYesterdayLimitUpStats(),
        ])

      await this.fetchYesterdayLimitUpStats()

      // 第二批：辅助数据获取（移除 fetchMarketLossStats 和 fetchYesterdayZtPerformance）
      const [zhabanDetailResult, overviewResult] = await Promise.allSettled([
        this.fetchZhabanDetail(),
        this.fetchMarketOverview(),
      ])

      // 处理市场统计数据
      if (marketResult.status === 'fulfilled' && marketResult.value) {
        Object.assign(this.state.marketData, marketResult.value)
      }

      // 处理炸板数据（优先使用详细接口）
      if (zhabanDetailResult.status === 'fulfilled' && zhabanDetailResult.value) {
        const data = zhabanDetailResult.value
        this.state.marketData.zhaban = {
          count: data.totalZhaban || 0,
          rate: parseFloat(data.zhabanRate || 0),
          fengbanRate: parseFloat(data.fengbanRate || 0),
        }
      } else if (tdxZhabanResult.status === 'fulfilled' && tdxZhabanResult.value) {
        this.state.marketData.zhaban = tdxZhabanResult.value
      }

      // 处理市场概览数据
      if (overviewResult.status === 'fulfilled' && overviewResult.value) {
        const data = overviewResult.value

        if (data.moneyFlow) {
          this.state.marketData.moneyFlow = data.moneyFlow
        }

        if (data.cddje !== undefined) {
          this.state.marketData.cddje = data.cddje
        }
        if (data.cddjzb !== undefined) {
          this.state.marketData.cddjzb = data.cddjzb
        }

        // 补全涨跌家数（如果 marketStats 没有返回）
        if (data.upCount && !this.state.marketData.upCount) {
          this.state.marketData.upCount = data.upCount
        }
        if (data.downCount && !this.state.marketData.downCount) {
          this.state.marketData.downCount = data.downCount
        }

        // 获取量比数据（如果 marketStats 没有返回）
        if (data.volumeRatio && !this.state.marketData.volumeRatio) {
          this.state.marketData.volumeRatio = data.volumeRatio
        }
      }

      // 处理涨停数据
      if (limitResult.status === 'fulfilled' && limitResult.value) {
        this.state.marketData.limitData = limitResult.value
        this.state.marketData.ztCount =
          limitResult.value.yiban +
          limitResult.value.erban +
          limitResult.value.sanban +
          limitResult.value.sibanPlus
      }

      // 处理昨日信息
      if (yesterdayResult.status === 'fulfilled' && yesterdayResult.value) {
        const yesterdayValue = yesterdayResult.value
        if (yesterdayValue.yesterdayDate) {
          const yesterdayLimit = await this.fetchLimitData(yesterdayValue.yesterdayDate)
          if (yesterdayLimit) {
            this.state.marketData.yesterdayLimit = yesterdayLimit
          }
        }
      }

      // 处理情绪数据
      if (emotionResult.status === 'fulfilled' && emotionResult.value) {
        this.state.marketData.emotionValue = emotionResult.value.value
        this.state.marketData.emotionStatus = emotionResult.value.status
      }

      // 计算连板高度
      if (this.state.marketData.limitData) {
        const { sibanPlus, sanban, erban } = this.state.marketData.limitData
        if (sibanPlus > 0) this.state.marketData.maxContinuousDays = 4
        else if (sanban > 0) this.state.marketData.maxContinuousDays = 3
        else if (erban > 0) this.state.marketData.maxContinuousDays = 2
        else this.state.marketData.maxContinuousDays = 1
      }

      // 计算晋级率（用于 passRate）
      if (
        this.state.marketData.yesterdayLimit?.erban > 0 &&
        this.state.marketData.limitData?.sanban > 0
      ) {
        this.state.marketData.passRate = {
          to2:
            (this.state.marketData.limitData.erban / this.state.marketData.yesterdayLimit.yiban) *
            100,
          to3:
            (this.state.marketData.limitData.sanban / this.state.marketData.yesterdayLimit.erban) *
            100,
          to4:
            (this.state.marketData.limitData.sibanPlus /
              this.state.marketData.yesterdayLimit.sanban) *
            100,
        }
      }

      this.state.marketData.timestamp = Date.now()
    } finally {
      this.state._fetching = false
    }
  }

  /**
   * 获取炸板数据（同花顺接口）
   */
  private async fetchZhabanDetail(): Promise<any> {
    try {
      const response = await apiService.get(API_CONFIG.ENDPOINTS.LIMITUP.DETAIL, {
        context: 'breath',
        ...API_CONFIG.CONTEXTS.BREATH,
      })
      return response
    } catch (error) {
      return null
    }
  }

  /**
   * 获取市场整体数据
   */
  private async fetchMarketOverview(): Promise<any> {
    try {
      const response = await apiService.get('/api/market/overview', {
        context: 'breath',
        priority: 'high',
        timeout: 5000,
        retries: 2,
        cache: true,
        cacheTTL: 10000,
      })

      return response
    } catch (error) {
      return null
    }
  }

  /**
   * 获取风险等级
   */
  private getRiskLevel(score: number, zhabanRate: number, phase?: string): string {
    if (phase) {
      switch (phase) {
        case '冰点期':
          return score < 20 ? '低' : '中'
        case '退潮期':
          return '高'
        case '高潮期':
          return zhabanRate > 30 ? '高' : '中'
      }
    }

    if (score < 30) return '低'
    if (score < 60) {
      if (zhabanRate > 50) return '高'
      if (zhabanRate > 30) return '中'
      return '中'
    }
    if (score >= 80) {
      if (zhabanRate > 40) return '高'
      return '中'
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
    const currentPhaseName = this.state.sentiment.phaseName || '震荡期'
    return this.getPhaseInfo(currentPhaseName) || EMOTION_PHASES.OSCILLATION
  }

  /**
   * 计算情绪分数
   */
  private calculateSentimentScore(): { score: number; factorScores: Record<string, number> } {
    const m = this.state.marketData
    const factorScores: Record<string, number> = {}
    let totalScore = 0

    for (const [key, factor] of Object.entries(EMOTION_SCORE_CONFIG.factors) as [
      string,
      EmotionFactor,
    ][]) {
      const value = factor.getValue(m)
      let score: number

      if (value !== null && value !== undefined) {
        score = factor.getScore(value)
      } else {
        // 无数据时给默认分（最高分的一半）
        score = Math.floor(factor.maxScore / 2)
      }

      factorScores[key] = score

      // ✅ 每个因子的贡献 = (得分 / 该因子满分) × 该因子权重
      // 权重已经是在100分总分中的占比，所以直接累加即可
      const contribution = (score / factor.maxScore) * factor.weight
      totalScore += contribution
    }

    // 边界处理
    const clampedScore = Math.max(0, Math.min(100, Math.round(totalScore)))

    return { score: clampedScore, factorScores }
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

    // 计算当前分数（用于参考）
    const currentScore = this.state.sentiment.overall

    // ========== 退潮核心信号（权重高） ==========
    let highWeightSignals = 0

    // 1. 炸板率极高 >45%
    if (zhabanRate > 45) highWeightSignals++

    // 2. 跌停潮 >20家
    if (dtCount > 20) highWeightSignals++

    // 3. 晋级率崩盘 <10%
    if (promotionRate < 10) highWeightSignals++

    // 4. 亏钱效应显著 昨日涨停表现 < -2%
    if (yesterdayZtAvgChange < -2) highWeightSignals++

    // ========== 退潮辅助信号（权重低） ==========
    let lowWeightSignals = 0

    // 5. 炸板率高 35-45%
    if (zhabanRate > 35 && zhabanRate <= 45) lowWeightSignals++

    // 6. 跌停增加 比前一天翻倍且>10家
    if (dtCount > prevDtCount * 2 && dtCount > 10) lowWeightSignals++

    // 7. 涨停数大幅回落 比前一天下降50%以上
    if (ztCount < prevZtCount * 0.5 && prevZtCount > 60) lowWeightSignals++

    // 8. 连板高度断崖 前一天≥6板，今天≤2板
    if (prevMaxContinuousDays >= 6 && (marketData.maxContinuousDays || 0) <= 2) lowWeightSignals++

    // ========== 退潮期判断 ==========
    // 条件A：至少2个高权重信号
    if (highWeightSignals >= 2) {
      return true
    }

    // 条件B：1个高权重信号 + 2个低权重信号
    if (highWeightSignals >= 1 && lowWeightSignals >= 2) {
      return true
    }

    // 条件C：分数较高但结构恶化（85分以上但出现退潮信号）
    if (currentScore > 85 && (highWeightSignals >= 1 || lowWeightSignals >= 3)) {
      return true
    }

    return false
  }

  /**
   * 更新情绪阶段信息
   * @param score 情绪总分
   * @param factorScores 各因子得分
   */
  private updateSentimentWithPhase(score: number, factorScores: Record<string, number>): void {
    try {
      const marketData = this.state.marketData
      let phaseInfo: EmotionPhase

      // 优先判断退潮期
      if (this.isRecession(marketData)) {
        phaseInfo = EMOTION_PHASES.RECESSION
      } else {
        // 其他阶段按分数判断
        phaseInfo = getEmotionPhaseByScore(score)
      }

      const riskLevel = this.getRiskLevel(score, marketData.zhaban?.rate || 0, phaseInfo.name)

      this.state.sentiment = {
        ...this.state.sentiment,
        overall: score,
        phase: phaseInfo.value,
        phaseName: phaseInfo.name, // ✅ 添加 phaseName
        phaseInfo: phaseInfo,
        riskLevel: riskLevel,
        suggestion: phaseInfo.suggestion,
        phaseIcon: phaseInfo.icon,
        phaseColor: phaseInfo.color,
        phaseGradient: phaseInfo.gradient,
        phaseFeatures: phaseInfo.features,
        factorScores: factorScores,
      }
    } catch (error) {
      console.error('[DragonBreathAnalyzer] 更新情绪阶段失败:', error)
      const defaultPhase = EMOTION_PHASES.OSCILLATION
      this.state.sentiment = {
        ...this.state.sentiment,
        overall: score,
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
      await this.fetchAllData()

      // 使用新的情绪分数计算
      const { score: calculatedScore, factorScores } = this.calculateSentimentScore()

      // 更新情绪阶段
      this.updateSentimentWithPhase(calculatedScore, factorScores)

      // 保存因子得分和参考指标
      this.state.sentiment.factorScores = factorScores

      // 构建因子数据（用于 dataLayer）
      let factors: any[] = []
      try {
        const marketData = this.state.marketData
        const factorScores = this.state.sentiment.factorScores

        factors = Object.entries(EMOTION_SCORE_CONFIG.factors).map(
          ([key, factor]: [string, EmotionFactor]) => {
            const rawValue = factor.getValue(marketData)
            const score = factorScores?.[key] ?? 0

            return {
              id: factor.id,
              name: factor.name,
              rawValue: rawValue,
              score: score,
              weight: factor.weight,
              maxScore: factor.maxScore,
              description: factor.description,
              unit: factor.unit || '',
            }
          },
        )
      } catch (e) {
        console.warn('[DragonBreathAnalyzer] 构建因子数据失败:', e)
      }

      // 存入 DataLayer
      if (typeof dataLayer !== 'undefined') {
        const breathData = {
          timestamp: Date.now(),
          sentiment: {
            overall: calculatedScore,
            phase: this.state.sentiment.phase,
            phaseName: this.state.sentiment.phaseName,
            riskLevel: this.state.sentiment.riskLevel,
            suggestion: this.state.sentiment.suggestion,
            phaseInfo: this.state.sentiment.phaseInfo,
            factorScores: factorScores,
            reference: { tdxEmotion: this.state.marketData.emotionValue },
          },
          marketData: {
            upCount: this.state.marketData.upCount,
            downCount: this.state.marketData.downCount,
            ztCount: this.state.marketData.ztCount,
            dtCount: this.state.marketData.dtCount,
            zhaban: this.state.marketData.zhaban,
            zhabanRate: this.state.marketData.zhaban?.rate,
            totalAmo: this.state.marketData.totalAmo,
            emotionValue: this.state.marketData.emotionValue,
            limitData: this.state.marketData.limitData,
            indices: this.state.marketData.indices,
            yesterdayLimit: this.state.marketData.yesterdayLimit,
            moneyFlow: this.state.marketData.moneyFlow,
            amoDiff: this.state.marketData.amoDiff,
            volumeRatio: this.state.marketData.volumeRatio,
            cddje: this.state.marketData.cddje,
            cddjzb: this.state.marketData.cddjzb,
            yesterdayZtPerformance: this.state.marketData.yesterdayZtPerformance,
            maxContinuousDays: this.state.marketData.maxContinuousDays,
            yesterdayLimitUpStats: this.state.marketData.yesterdayLimitStats,
          },
          factors,
        }
        dataLayer.updateBreathData(breathData)
      }

      // 触发事件
      EventManager.emit(AppEvents.BREATH.UPDATED, {
        sentiment: this.state.sentiment,
        marketData: this.state.marketData,
        timestamp: Date.now(),
      })

      this.feedbackToAlgorithm()
      this.recordHistory()
      this.lastAnalysisTime = Date.now()

      return true
    } catch (error) {
      console.error('[DragonBreath] 分析失败:', error)
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
    if (this.state.refreshTimer) {
      clearInterval(this.state.refreshTimer)
      this.state.refreshTimer = null
    }
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
