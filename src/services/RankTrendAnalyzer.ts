import { debugLog } from '@/utils/logger'
// src/services/RankTrendAnalyzer.ts
import { EventManager } from '../utils/eventManager'
import { apiService } from './apiService'
import { dataLayer } from './DataLayer'
import {
  cloneDefaultRankTrendRuntimeConfig,
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  type RankTrendSnapshotType,
  normalizeRankTrendRuntimeConfig,
  type RTConfigPatch,
} from '../types/rankTrendDefaults'
import {
  summarizeRankTrendStrategyDistribution,
  type RankTrendStrategyValidationReport,
} from './rankTrend/strategyValidation'
import { getMaxStableBars } from './rankTrend/utils'
import { analyzeRankTrendCoalesced } from './rankTrend/analyzeCoalescer'
import { rankTrendResultCache, rankTrendResultCacheKey } from './rankTrend/rankTrendCache'
import type {
  RankTrendAnalysisResult,
  RankTrendRuntimeConfig as RankTrendRuntimeConfigModel,
} from './rankTrend/types'

function toOptionalFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

const runtimeConfig: RankTrendRuntimeConfigModel = cloneDefaultRankTrendRuntimeConfig()
type SnapshotCaptureMode = 'real_time' | 'delayed' | 'restored'
type SupportedSnapshotType = RankTrendSnapshotType
type RankTrendRankSeriesFrame = {
  snapshotId: string
  displayKey?: string
  timestamp: number
  type: SupportedSnapshotType
  tradingDate?: string
  slotTime?: string
  captureMode?: SnapshotCaptureMode
  totalCount: number
  ranks: Record<string, number>
  bars?: Array<{
    code?: string
    rank?: number
    snapshotId?: string
    timestamp?: number
    tradingDate?: string
    slotTime?: string
    captureMode?: SnapshotCaptureMode
    totalCount?: number
  }>
}

const FORMAL_SNAPSHOT_READ_POLICY = {
  allowedCaptureModes: ['real_time', 'delayed'] as SnapshotCaptureMode[],
  excludeRestored: true,
}

type RankTrendAnalysisSnapshot = {
  date: string
  timestamp: number
  type: SupportedSnapshotType
  tradingDate?: string
  slotTime?: string
  captureMode?: SnapshotCaptureMode
  snapshot: any
}

type RankTrendAnalysisOptions = {
  updateSignalStore?: boolean
  preferredSnapshotType?: SupportedSnapshotType
  /**
   * 已废弃：前端本地 golden 计算链已随 Python 迁移移除，只消费 analyze API 输出。
   * 保留字段仅为调用方兼容，不再影响行为。
   */
  preferRemoteAnalysis?: boolean
  skipLocalCompute?: boolean
  /** 远程 analyze 只请求这些代码（面板只需选中股票时，响应从 20+MB 降到 KB 级） */
  remoteCodes?: string[]
  /** 主动刷新场景（量比刷新后信号重算）绕过前端 LRU 缓存，强制打后端 analyze；
   * 后端 Redis 缓存键含 current_frame（量价输入指纹）保证量价分随输入变化刷新 */
  forceRemote?: boolean
}
type RankTrendAnalysisSeries = {
  ranks: number[]
  percentiles: number[]
  frameKeys: string[]
}

type DataLoaderApi = {
  updateStockSignals(
    updates: Array<{ code: string; rankTrend: RankTrendResult; coverageWarning: string | null }>,
  ): void
}

type ApiServiceApi = {
  getRankTrendRankSeries(options: Record<string, unknown>, requestOptions?: { signal?: AbortSignal }): Promise<{
    frames?: RankTrendRankSeriesFrame[]
    marketFrames?: RankTrendRankSeriesFrame[]
    series?: Record<string, { code?: string; bars?: RankTrendRankSeriesFrame['bars']; snapshotType?: SupportedSnapshotType }>
    count?: number
    cache?: { hit: boolean; store: string }
  }>
}

export interface RankTrendResult extends RankTrendAnalysisResult {
  code: string
  currentRank: number
  change: number
  rawChange: number
  ma5: number
  ma10: number
  maTrend: 'up' | 'down' | 'steady'
  macd: number
  macdSignal: number
  macdHistogram: number
  macdCross: 'golden' | 'death' | 'none'
  signal: 'buy' | 'sell' | 'hold'
  confidence: number
  directionSignal: 'buy' | 'sell' | 'hold'
  directionConfidence: number
  accelerationSignal: 'buy' | 'sell' | 'hold'
  accelerationConfidence: number
  crossSignal: 'buy' | 'sell' | 'hold'
  crossConfidence: number
  finalSignal: 'buy' | 'sell' | 'hold'
  finalConfidence: number
  updateTime: number
}

export type RankTrendRuntimeConfig = RankTrendRuntimeConfigModel
type RankTrendConfigUpdate = RTConfigPatch

function toTradingDateString(input?: Date): string | undefined {
  if (!(input instanceof Date) || Number.isNaN(input.getTime())) return undefined
  const year = input.getFullYear()
  const month = String(input.getMonth() + 1).padStart(2, '0')
  const day = String(input.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

export class RankTrendAnalyzer {
  private static instance: RankTrendAnalyzer
  private isRunning = false
  private initPromise: Promise<void> | null = null
  private unsubscribeHandlers: Array<() => void> = []
  private runtimeConfigApplyCount = 0
  private latestAnalysisSeries = new Map<string, RankTrendAnalysisSeries>()
  private latestAnalysisFrameKeys: string[] = []
  private currentFrameSequence = 0
  private lastStrategyValidationReport: RankTrendStrategyValidationReport | null = null

  private constructor() {
    this.initPromise = this.start()
  }

  static getInstance(): RankTrendAnalyzer {
    if (!RankTrendAnalyzer.instance) {
      RankTrendAnalyzer.instance = new RankTrendAnalyzer()
    }
    return RankTrendAnalyzer.instance
  }

  async start() {
    if (this.isRunning) return
    this.isRunning = true

    let retries = 0
    while (dataLayer.getStocks().length === 0 && retries < 10) {
      await new Promise((resolve) => setTimeout(resolve, 1000))
      retries += 1
    }

    EventManager.on('data:stocks-updated', () => {
      debugLog('[RankTrendAnalyzer] 数据版本变化，清除缓存')
      this.invalidateCache()
    })

    EventManager.on('snapshots:updated', () => {
      debugLog('[RankTrendAnalyzer] 快照更新，清除缓存')
      this.invalidateCache()
    })

    const unsubscribeConfig = EventManager.on('rankTrend:updateConfig', (config: RankTrendConfigUpdate) => {
      this.applyRuntimeConfig(config)
    })
    this.unsubscribeHandlers.push(unsubscribeConfig)
  }

  private invalidateCache() {
    this.latestAnalysisSeries.clear()
    this.latestAnalysisFrameKeys = []
  }

  getLatestAnalysisSeries(code: string): RankTrendAnalysisSeries | null {
    const entry = this.latestAnalysisSeries.get(code)
    if (!entry || entry.percentiles.length === 0 || entry.ranks.length === 0) return null
    return {
      ranks: [...entry.ranks],
      percentiles: [...entry.percentiles],
      frameKeys: [...entry.frameKeys],
    }
  }

  getLatestAnalysisFrameKeys(): string[] {
    return [...this.latestAnalysisFrameKeys]
  }

  private logRuntimeConfigApplied(): void {
    this.runtimeConfigApplyCount += 1
    if (this.runtimeConfigApplyCount <= 3 || this.runtimeConfigApplyCount % 20 === 0) {
      debugLog(`[RankTrendAnalyzer] 已应用运行时参数更新 (${this.runtimeConfigApplyCount})`)
    }
  }

  public getRuntimeConfig(): RankTrendRuntimeConfig {
    return {
      momentumPeriods: [...runtimeConfig.momentumPeriods],
      momentumWeights: [...runtimeConfig.momentumWeights],
      buyThresholds: [...runtimeConfig.buyThresholds],
      sellThresholds: [...runtimeConfig.sellThresholds],
      macdFast: runtimeConfig.macdFast,
      macdSlow: runtimeConfig.macdSlow,
      macdSignal: runtimeConfig.macdSignal,
      directionWeight: runtimeConfig.directionWeight,
      accelerationWeight: runtimeConfig.accelerationWeight,
      crossWeight: runtimeConfig.crossWeight,
      macdWeight: runtimeConfig.macdWeight,
      maWeight: runtimeConfig.maWeight,
      buyScoreThreshold: runtimeConfig.buyScoreThreshold,
      sellScoreThreshold: runtimeConfig.sellScoreThreshold,
    }
  }

  private applyRuntimeConfig(config: RankTrendConfigUpdate): void {
    if (!config || typeof config !== 'object') return
    const normalized = normalizeRankTrendRuntimeConfig(runtimeConfig as any, config)
    Object.assign(runtimeConfig, normalized)

    this.invalidateCache()
    this.logRuntimeConfigApplied()
    debugLog('[RankTrendAnalyzer] 已应用运行时参数更新')
  }

  public updateRuntimeConfig(config: RankTrendConfigUpdate): RankTrendRuntimeConfig {
    this.applyRuntimeConfig(config)
    return this.getRuntimeConfig()
  }

  public async getSnapshotsByType(
    type: SupportedSnapshotType,
    options?: {
      limit?: number
      minRequired?: number
      fromDate?: Date
      toDate?: Date
      codes?: string[]
    },
    requestOptions?: { signal?: AbortSignal },
  ): Promise<RankTrendAnalysisSnapshot[]> {
    const apiService = await this.getApiService()
    const readLimit = options?.limit ? Math.max(options.limit, options.minRequired ?? 0) : options?.minRequired
    const startedAt = performance.now()
    const response = await apiService.getRankTrendRankSeries({
      type,
      startDate: toTradingDateString(options?.fromDate),
      endDate: toTradingDateString(options?.toDate),
      allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
      excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
      rankBasis: 'attention',
      sort: 'desc',
      limit: readLimit,
      windowBars: getMaxStableBars(),
      codes: options?.codes,
    }, requestOptions)
    debugLog('[RankTrendAnalyzer] rank-series 响应', {
      cacheHit: response.cache?.hit ?? false,
      cacheStore: response.cache?.store ?? 'unknown',
      frameCount: response.count ?? response.frames?.length ?? 0,
      elapsedMs: Math.round(performance.now() - startedAt),
    })

    const hasSeriesData = this.hasRankSeriesData(response, options?.codes)
    const snapshots = this.normalizeRankSeriesResponse(response, type, options?.codes)

    if (options?.minRequired && snapshots.length < options.minRequired) {
      return []
    }

    if (!hasSeriesData && options?.limit && options.limit > 0 && snapshots.length > options.limit) {
      return snapshots.slice(-options.limit)
    }

    return snapshots
  }

  private hasRankSeriesData(
    response: {
      series?: Record<string, { bars?: RankTrendRankSeriesFrame['bars'] }>
    },
    codes?: string[],
  ): boolean {
    const series = response.series || {}
    const matchedCodes = Array.isArray(codes) && codes.length ? codes : Object.keys(series)
    return matchedCodes.some((code) => {
      const entry = series[code]
      return Array.isArray(entry?.bars) && entry.bars.length > 0
    })
  }

  private normalizeRankSeriesResponse(
    response: {
      frames?: RankTrendRankSeriesFrame[]
      series?: Record<string, { code?: string; bars?: RankTrendRankSeriesFrame['bars']; snapshotType?: SupportedSnapshotType; totalCount?: number }>
    },
    preferredType: SupportedSnapshotType,
    codes?: string[],
  ): RankTrendAnalysisSnapshot[] {
    const series = response.series || {}
    const frames = response.frames || []

    // Fallback: if series has no matching codes, use frames directly.
    const hasSeriesData = this.hasRankSeriesData(response, codes)
    if (!hasSeriesData && frames.length > 0) {
      return this.normalizeFramesToSnapshots(frames, preferredType)
    }
    // Build frame totalCount lookup for accurate percentile calculations
    const frameTotalCounts = new Map<string, number>()
    for (const frame of frames) {
      if (frame.snapshotId && frame.totalCount > 0) {
        frameTotalCounts.set(frame.snapshotId, frame.totalCount)
      }
    }
    const defaultTotalCount = 200

    const preferredCodes = Array.isArray(codes) && codes.length ? codes : Object.keys(series)
    const snapshotsBySignature = new Map<string, RankTrendAnalysisSnapshot>()

    for (const code of preferredCodes) {
      const entry = series[code]
      const bars = Array.isArray(entry?.bars) ? entry.bars : []
      for (const bar of bars) {
        const snapshotId = String(bar?.snapshotId || '')
        const timestamp = Number(bar?.timestamp || 0)
        if (!snapshotId || !Number.isFinite(timestamp)) continue
        const date = `${bar.tradingDate || ''} ${bar.slotTime || ''}`.trim() || snapshotId
        const existing = snapshotsBySignature.get(snapshotId)
        const hotlist = existing?.snapshot?.hotlist ? [...existing.snapshot.hotlist] : []
        const rank = Number(bar?.rank || 0)
        if (bar.code && rank > 0 && !hotlist.some((item: any) => item.code === bar.code)) {
          hotlist.push({ code: bar.code, rank })
        }
        const barTotalCount = Number(bar?.totalCount || 0)
        const totalCount = (barTotalCount > 0 ? barTotalCount : frameTotalCounts.get(snapshotId)) || Math.max(hotlist.length, defaultTotalCount)
        snapshotsBySignature.set(snapshotId, {
          date,
          timestamp,
          type: (bar?.captureMode ? preferredType : preferredType) as SupportedSnapshotType,
          tradingDate: bar.tradingDate,
          slotTime: bar.slotTime,
          captureMode: bar.captureMode,
          snapshot: {
            date,
            type: preferredType,
            timestamp,
            tradingDate: bar.tradingDate,
            slotTime: bar.slotTime,
            captureMode: bar.captureMode,
            hotlist,
            totalCount,
            sectors: [],
            marketStats: {},
            sentiment: {},
            moneyFlow: {},
            indices: {},
            limitSummary: {},
            rotationSummary: {},
          },
        })
      }
    }

    return Array.from(snapshotsBySignature.values())
      .sort((left, right) => left.timestamp - right.timestamp)
  }

  private normalizeFramesToSnapshots(
    frames: RankTrendRankSeriesFrame[],
    preferredType: SupportedSnapshotType,
    allowEmptyHotlist = false,
  ): RankTrendAnalysisSnapshot[] {
    return frames
      .map((frame): RankTrendAnalysisSnapshot | null => {
        const ranks = frame.ranks && typeof frame.ranks === 'object' ? frame.ranks : {}
        const hotlist = Object.entries(ranks)
          .map(([code, rank]) => ({ code, rank: Number(rank) }))
          .filter((item) => Number.isFinite(item.rank) && item.rank > 0)
          .sort((left, right) => left.rank - right.rank)
        if ((!allowEmptyHotlist && !hotlist.length) || !frame.timestamp) return null

        const date = frame.displayKey || frame.snapshotId
        return {
          date,
          timestamp: Number(frame.timestamp),
          type: preferredType,
          tradingDate: frame.tradingDate,
          slotTime: frame.slotTime,
          captureMode: frame.captureMode,
          snapshot: {
            date,
            type: preferredType,
            timestamp: Number(frame.timestamp),
            tradingDate: frame.tradingDate,
            slotTime: frame.slotTime,
            captureMode: frame.captureMode,
            hotlist,
            totalCount: Number(frame.totalCount) || hotlist.length,
            sectors: [],
            marketStats: {},
            sentiment: {},
            moneyFlow: {},
            indices: {},
            limitSummary: {},
            rotationSummary: {},
          },
        }
      })
      .filter((item): item is NonNullable<typeof item> => item !== null)
      .sort((left, right) => left.timestamp - right.timestamp)
  }

  async getRankTrends(
    rankMap: Map<string, number>,
    options: RankTrendAnalysisOptions = {},
  ): Promise<Map<string, RankTrendResult>> {
    // 前端不再保留本地 golden 计算链：结果一律来自 Python analyze API（golden 事实标准）。
    const results = new Map<string, RankTrendResult>()
    const currentFrameKey = `current:${++this.currentFrameSequence}`
    const remoteCodes = options.remoteCodes?.length ? options.remoteCodes : Array.from(rankMap.keys())
    const snapshotType = options.preferredSnapshotType || DEFAULT_RANK_TREND_SNAPSHOT_TYPE

    // 前端 LRU TTL 缓存（rankTrendResultCache，300s 与后端 Redis 对齐）：
    // 命中直接返回，未命中才请求 Python analyze，再写回缓存。
    // 四个观察字段（共振/趋势/量价/周期）均来自 rankTrend 结果，统一随此缓存预热，
    // 避免数据刷新循环重复打后端、分析未完成时整列回退 '--'。
    // forceRemote（主动刷新）：跳过读缓存，强制打后端——量比刷新后量价输入已变，
    // 后端缓存键含 current_frame 指纹，输入变化会重新计算量价分，结果仍写回前端缓存。
    const cachedResults = new Map<string, RankTrendResult>()
    const missCodes: string[] = []
    const forceRemote = options.forceRemote === true
    for (const code of remoteCodes) {
      if (forceRemote) {
        missCodes.push(code)
        continue
      }
      const cached = rankTrendResultCache.get(rankTrendResultCacheKey(code, snapshotType))
      if (cached) cachedResults.set(code, cached)
      else missCodes.push(code)
    }
    if (!forceRemote && missCodes.length === 0) {
      return cachedResults
    }

    const stocks = typeof dataLayer.getStocks === 'function' ? dataLayer.getStocks() : []
    // rank 类哨兵（DEFAULT_RANK=999 / ≥999 占位）不传后端：实时综合评分与均榜
    // 的归一化会把占位值当真实排名（2026-09-22 实时口径修复）
    const finiteRank = (value: unknown): number | undefined => {
      const parsed = toOptionalFiniteNumber(value)
      return parsed != null && parsed < 999 ? parsed : undefined
    }
    const currentFrameStocks = stocks
      .filter((stock: any) => remoteCodes.includes(String(stock?.code)))
      .map((stock: any) => ({
        code: String(stock?.code),
        rank: finiteRank(stock?.compRank ?? stock?.rank),
        avgRankNum: finiteRank(stock?.avgRankNum),
        change: toOptionalFiniteNumber(stock?.change),
        volumeRatio: toOptionalFiniteNumber(stock?.volumeRatio),
        zlje: toOptionalFiniteNumber(stock?.zlje),
        zljzb: toOptionalFiniteNumber(stock?.zljzb),
        amount: toOptionalFiniteNumber(stock?.amount ?? stock?.turnover),
        price: toOptionalFiniteNumber(stock?.price ?? stock?.lastTradePrice),
        high: toOptionalFiniteNumber(stock?.high ?? stock?.highPrice),
        low: toOptionalFiniteNumber(stock?.low ?? stock?.lowPrice),
        close: toOptionalFiniteNumber(stock?.close ?? stock?.price ?? stock?.lastTradePrice),
        // 2026-08-24 回滚后（compRank 恢复前端本地计算）这些字段不再用于后端注入 compRank：
        // avgRankNum 用于后端新股单点 percentile 排序（attention_rank_lookup，G3 权威算法）；
        // turnover/turnoverRate 用于 frame_market_percentiles；rank=compRank 仅作缓存键身份与
        // 排序展示（后端 percentile 计算不读 rank）。这些字段由后端缓存键完整指纹化。
        turnover: toOptionalFiniteNumber(stock?.turnover),
        turnoverRate: toOptionalFiniteNumber(stock?.turnoverRate),
        fundPenetration: toOptionalFiniteNumber(stock?.fundPenetration),
        platforms: toOptionalFiniteNumber(stock?.platforms),
        // 八平台 rank 透传（2026-09-22 实时均榜输入）：后端按 weighted_platform_percentile_v1
        // 对 current 帧行实时算 avgRankNum（榜单总数由行内每平台最大 rank 推断）
        emRank: finiteRank(stock?.emRank),
        thsRank: finiteRank(stock?.thsRank),
        kplRank: finiteRank(stock?.kplRank),
        tdxRank: finiteRank(stock?.tdxRank),
        xqRank: finiteRank(stock?.xqRank),
        clsRank: finiteRank(stock?.clsRank),
        tgbRank: finiteRank(stock?.tgbRank),
        dzhRank: finiteRank(stock?.dzhRank),
        // 题材暴露字段：题材动量共振需要在当前帧内做个股-题材匹配；
        // dataLayer 的 themes 是详情对象数组，这里规范化为名称/ID 列表
        themes: Array.isArray(stock?.themes)
          ? stock.themes.map((theme: any) => String(theme?.name || theme?.id || theme))
          : [],
        mainTheme: String(stock?.mainTheme || ''),
        themeRole: String(stock?.themeRole || ''),
        themeContribution: toOptionalFiniteNumber(stock?.themeContribution),
        leadStatus: String(stock?.leadStatus || ''),
      }))

    try {
      const remote = await analyzeRankTrendCoalesced({
        snapshotType,
        codes: missCodes,
        currentFrame: {
          tradingDate: new Date().toISOString().slice(0, 10),
          slotTime: currentFrameKey,
          stocks: currentFrameStocks,
        },
      })
      if (remote?.ok && remote.frames?.length) {
        // 从 Python 输出构建观察面板所需的最新分析序列（含当前帧）
        this.updateLatestAnalysisSeries(remote.frames)
        const frameResult = remote.frames[remote.frames.length - 1]
        const byCode = new Map(frameResult.stocks.map((item) => [item.code, item.analysis]))
        for (const [code, analysis] of byCode) {
          if (!analysis) continue
          const result = { ...analysis } as unknown as RankTrendResult
          result.meta = {
            ...result.meta,
            analysisSource: 'py_golden' as const,
          }
          results.set(code, result)
          rankTrendResultCache.set(rankTrendResultCacheKey(code, snapshotType), result)
        }
        // 合并缓存命中部分 + 本次新分析结果（覆盖全部 remoteCodes）
        for (const [code, result] of cachedResults) {
          results.set(code, result)
        }
        this.lastStrategyValidationReport = summarizeRankTrendStrategyDistribution(results.values())
        if (options.updateSignalStore !== false) {
          await this.batchUpdateSignals(results)
        }
        return results
      }
    } catch (error) {
      // 远程失败：不返回伪造结果，缓存命中部分仍可用（fail-visible），缺失部分由面板/观察层回退
      debugLog('[RankTrendAnalyzer] Python analyze 不可用:', error)
      return cachedResults
    }

    // analyze 无 ok/无 frames：仅返回缓存命中部分，不伪造缺失结果（fail-visible）
    for (const [code, result] of cachedResults) {
      results.set(code, result)
    }
    this.lastStrategyValidationReport = summarizeRankTrendStrategyDistribution(results.values())

    if (options.updateSignalStore !== false) {
      await this.batchUpdateSignals(results)
    }

    return results
  }

  /**
   * 从 Python analyze 输出帧构建“每股最新分析序列”，仅供观察面板展示消费，不承载算法。
   */
  private updateLatestAnalysisSeries(
    frames: Array<{
      frameKey?: string
      stocks?: Array<{ code?: string; analysis?: Record<string, unknown> }>
    }>,
  ): void {
    this.latestAnalysisSeries.clear()
    this.latestAnalysisFrameKeys = []
    const seriesByCode = new Map<string, RankTrendAnalysisSeries>()

    for (const frame of frames) {
      const key = String(frame?.frameKey || '')
      if (!key) continue
      this.latestAnalysisFrameKeys.push(key)
      for (const stock of frame?.stocks || []) {
        const code = String(stock?.code || '')
        const meta = stock?.analysis?.meta as RankTrendAnalysisResult['meta'] | undefined
        if (!code || !meta) continue
        const entry = seriesByCode.get(code) || { ranks: [], percentiles: [], frameKeys: [] }
        const rank = Number(meta.currentRank)
        if (Number.isFinite(rank) && rank > 0) entry.ranks.push(rank)
        const percentile = Number(meta.currentPercentile)
        if (Number.isFinite(percentile)) entry.percentiles.push(percentile)
        entry.frameKeys.push(key)
        seriesByCode.set(code, entry)
      }
    }

    for (const [code, series] of seriesByCode) {
      this.latestAnalysisSeries.set(code, {
        ranks: series.ranks,
        percentiles: series.percentiles,
        frameKeys: series.frameKeys,
      })
    }
  }

  public validateStrategyResults(
    results: Iterable<RankTrendAnalysisResult | null | undefined>,
  ): RankTrendStrategyValidationReport {
    return summarizeRankTrendStrategyDistribution(results)
  }

  public getLastStrategyValidationReport(): RankTrendStrategyValidationReport | null {
    return this.lastStrategyValidationReport
  }

  private async getApiService(): Promise<ApiServiceApi> {
    return apiService as ApiServiceApi
  }

  private async batchUpdateSignals(results: Map<string, RankTrendResult>): Promise<void> {
    const module = await import('./dataLoader')
    const dataLoader = module.dataLoader as DataLoaderApi
    const signalUpdates = Array.from(results.entries())
      .filter(([, result]) => Boolean(result))
      .map(([code, result]) => ({
        code,
        rankTrend: result,
        coverageWarning: result.meta.sampleQuality?.coverageWarning || null,
      }))

    if (signalUpdates.length > 0) {
      dataLoader.updateStockSignals(signalUpdates)
    }
  }

  stop() {
    this.isRunning = false
    this.unsubscribeHandlers.forEach((off) => off())
    this.unsubscribeHandlers = []
    this.invalidateCache()
  }
}

export const rankTrendAnalyzer = RankTrendAnalyzer.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).rankTrendAnalyzer = rankTrendAnalyzer
}
