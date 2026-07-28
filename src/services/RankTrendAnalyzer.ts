import { debugLog } from '@/utils/logger'
// src/services/RankTrendAnalyzer.ts
import { EventManager } from '../utils/eventManager'
import { apiService } from './apiService'
import { dataLayer } from './DataLayer'
import {
  buildRankTrendSnapshotPriority,
  cloneDefaultRankTrendRuntimeConfig,
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  type RankTrendSnapshotType,
  normalizeRankTrendRuntimeConfig,
  type RTConfigPatch,
} from '../types/rankTrendDefaults'
import { analyzeMarketRegime } from './rankTrend/marketRegimeAnalyzer'
import { runRankTrendAnalysisPipeline } from './rankTrend/runRankTrendAnalysisPipeline'
import { getTrustedVolumeRatio } from './dataLoader/VolumeRatioTrust'
import { getExpectedSlots } from './snapshot/schedule'
import {
  summarizeRankTrendStrategyDistribution,
  type RankTrendStrategyValidationReport,
} from './rankTrend/strategyValidation'
import { getMaxStableBars, getTechnicalMinSamples } from './rankTrend/utils'
import type {
  RankTrendAnalysisResult,
  RankTrendRuntimeConfig as RankTrendRuntimeConfigModel,
} from './rankTrend/types'

const runtimeConfig: RankTrendRuntimeConfigModel = cloneDefaultRankTrendRuntimeConfig()
const MAX_LIVE_HISTORY_GAP_MS = 7 * 24 * 60 * 60 * 1000
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
  snapshots?: Array<{ date: string; timestamp?: number; snapshot: any }>
  updateSignalStore?: boolean
  preferredSnapshotType?: SupportedSnapshotType
  fromDate?: Date
  toDate?: Date
  codes?: string[]
}

export type RankTrendPreparedSnapshot = NonNullable<RankTrendAnalysisOptions['snapshots']>[number]

type RankHistoryData = {
  snapshotSignature: string
  ranks: number[]
  percentiles: number[]
  totalCounts: number[]
  frameKeys: string[]
}

type RankTrendAnalysisSeries = Pick<RankHistoryData, 'ranks' | 'percentiles' | 'frameKeys'>

type SampleQualitySummary = NonNullable<RankTrendAnalysisResult['meta']['sampleQuality']>
type DataLayerApi = {
  getStocks(): any[]
  getStock(code: string): any
  getBreathData?(): any
}

type DataLoaderApi = {
  updateStockSignals(
    updates: Array<{ code: string; rankTrend: RankTrendResult; coverageWarning: string | null }>,
  ): void
}

type ApiServiceApi = {
  getRankTrendRankSeries(options: Record<string, unknown>): Promise<{
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

function parseTradingDateFromLabel(label?: string): string | undefined {
  const match = String(label || '').match(/(\d{4}-\d{2}-\d{2})/)
  return match?.[1]
}

function parseSlotTimeFromLabel(label?: string): string | undefined {
  const match = String(label || '').match(/(\d{2}:\d{2})/)
  return match?.[1]
}

export class RankTrendAnalyzer {
  private static instance: RankTrendAnalyzer
  private isRunning = false
  private initPromise: Promise<void> | null = null
  private unsubscribeHandlers: Array<() => void> = []
  private runtimeConfigApplyCount = 0
  private rankHistoryCache = new Map<string, RankHistoryData>()
  private latestAnalysisSeries = new Map<string, RankTrendAnalysisSeries>()
  private latestMarketSnapshots: RankTrendAnalysisSnapshot[] = []
  private latestAnalysisFrameKeys: string[] = []
  private currentFrameSequence = 0
  private marketRegimeCache: { signature: string; value: ReturnType<typeof analyzeMarketRegime> } | null = null
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

    const dataLayer = await this.getDataLayer()
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
    this.rankHistoryCache.clear()
    this.latestAnalysisSeries.clear()
    this.latestAnalysisFrameKeys = []
    this.marketRegimeCache = null
  }

  getCachedPercentiles(code: string): number[] | null {
    const entry = this.rankHistoryCache.get(code)
    if (!entry || !Array.isArray(entry.percentiles) || entry.percentiles.length === 0) {
      return null
    }
    return [...entry.percentiles]
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
    })
    debugLog('[RankTrendAnalyzer] rank-series 响应', {
      cacheHit: response.cache?.hit ?? false,
      cacheStore: response.cache?.store ?? 'unknown',
      frameCount: response.count ?? response.frames?.length ?? 0,
      elapsedMs: Math.round(performance.now() - startedAt),
    })

    const hasSeriesData = this.hasRankSeriesData(response, options?.codes)
    const snapshots = this.normalizeRankSeriesResponse(response, type, options?.codes)
    this.latestMarketSnapshots = this.normalizeFramesToSnapshots(response.marketFrames || [], type, true)

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
    const results = new Map<string, RankTrendResult>()
    this.latestAnalysisSeries.clear()
    this.latestAnalysisFrameKeys = []
    const recentSnapshots = options.snapshots?.length
      ? this.normalizeAnalysisSnapshots(options.snapshots)
      : await this.loadRequiredSnapshots({ ...options, codes: Array.from(rankMap.keys()) })

    if (recentSnapshots.length === 0) {
      debugLog('[RankTrendAnalyzer] 快照不足，跳过计算')
      return results
    }

    const marketSnapshots = options.snapshots?.length
      ? recentSnapshots
      : this.latestMarketSnapshots.length
        ? this.latestMarketSnapshots
        : recentSnapshots
    const { snapshots: recentMarketWindow, skippedHistoryCount } = this.getLatestContinuousMarketWindow(
      marketSnapshots,
    )
    const sampleQuality = this.buildSampleQualitySummary(
      recentMarketWindow.slice(-getMaxStableBars()),
      options.preferredSnapshotType,
      !options.snapshots?.length,
    )
    if (skippedHistoryCount > 0) {
      sampleQuality.coverageWarning = [
        sampleQuality.coverageWarning,
        `较早市场帧存在断层，已仅使用最近连续 ${recentMarketWindow.length} 帧`,
      ]
        .filter(Boolean)
        .join('；')
    }
    const enforceLiveTimeline = !options.snapshots?.length
    const { prevRankMap, prevTotalCount } = this.getLatestRankSnapshot(recentSnapshots)
    const currentTotalCount = rankMap.size
    const snapshotsMap = this.buildSnapshotsMap(recentSnapshots)
    const snapshotSignature = this.buildSnapshotSignature(recentSnapshots)
    const weekdays = recentSnapshots.map((item) => item.date)
    const appendCurrentFrame = this.shouldAppendCurrentFrame(
      rankMap,
      prevRankMap,
      currentTotalCount,
      prevTotalCount,
    )
    const currentFrameKey = `current:${++this.currentFrameSequence}`
    this.latestAnalysisFrameKeys = appendCurrentFrame ? [...weekdays, currentFrameKey] : weekdays

    const computedResults = await Promise.all(
      Array.from(rankMap.entries()).map(([code, currentRank]) =>
        this.computeStockRankTrend({
          code,
          currentRank,
          currentTotalCount,
          prevRankMap,
          prevTotalCount,
          weekdays,
          snapshots: snapshotsMap,
          snapshotSignature,
          sampleQuality,
          enforceLiveTimeline,
          currentFrameKey,
          appendCurrentFrame,
        }),
      ),
    )

    for (const [code, result] of computedResults) {
      if (result) results.set(code, result)
    }

    this.lastStrategyValidationReport = summarizeRankTrendStrategyDistribution(results.values())

    if (options.updateSignalStore !== false) {
      await this.batchUpdateSignals(results)
    }

    return results
  }

  public validateStrategyResults(
    results: Iterable<RankTrendAnalysisResult | null | undefined>,
  ): RankTrendStrategyValidationReport {
    return summarizeRankTrendStrategyDistribution(results)
  }

  public getLastStrategyValidationReport(): RankTrendStrategyValidationReport | null {
    return this.lastStrategyValidationReport
  }

  public async preloadSnapshots(
    options: Pick<
      RankTrendAnalysisOptions,
      'preferredSnapshotType' | 'fromDate' | 'toDate' | 'codes'
    > = {},
  ): Promise<RankTrendPreparedSnapshot[]> {
    const snapshots = await this.loadRequiredSnapshots(options)
    return snapshots.map((item) => ({
      date: item.date,
      timestamp: item.timestamp,
      snapshot: item.snapshot,
    }))
  }

  private async loadRequiredSnapshots(options: RankTrendAnalysisOptions): Promise<RankTrendAnalysisSnapshot[]> {
    const requiredSnapshots = getTechnicalMinSamples(runtimeConfig)
    const limit = 50
    const preferredType = options.preferredSnapshotType ?? DEFAULT_RANK_TREND_SNAPSHOT_TYPE
    const priorityTypes = buildRankTrendSnapshotPriority(preferredType)

    const readOptions = {
      limit,
      fromDate: options.fromDate,
      toDate: options.toDate,
      codes: options.codes,
    }
    const preferredSnapshots = await this.getSnapshotsByType(preferredType, readOptions)
    if (preferredSnapshots.length >= requiredSnapshots) return preferredSnapshots

    const fallbackTypes = priorityTypes.filter((type) => type !== preferredType)
    const fallbackResults = await Promise.all(
      fallbackTypes.map(async (type) => ({
        type,
        snapshots: await this.getSnapshotsByType(type, readOptions),
      })),
    )
    const strictFallback = fallbackResults.find((item) => item.snapshots.length >= requiredSnapshots)
    if (strictFallback) {
      debugLog(
        `[RankTrendAnalyzer] 首选快照不足，回退 ${strictFallback.type}: ${strictFallback.snapshots.length} 条`,
      )
      return strictFallback.snapshots
    }

    const looseFallback = [
      { type: preferredType, snapshots: preferredSnapshots },
      ...fallbackResults,
    ].reduce<{ type: SupportedSnapshotType; snapshots: RankTrendAnalysisSnapshot[] } | null>(
      (picked, item) => (!picked || item.snapshots.length > picked.snapshots.length ? item : picked),
      null,
    )

    if (looseFallback?.snapshots.length) {
      debugLog(
        `[RankTrendAnalyzer] 快照不足最小阈值(${requiredSnapshots})，使用可用最多类型: ${looseFallback.type} ${looseFallback.snapshots.length} 条`,
      )
      return looseFallback.snapshots
    }

    return []
  }

  private normalizeAnalysisSnapshots(
    snapshots: Array<{ date: string; timestamp?: number; snapshot: any }>,
  ): RankTrendAnalysisSnapshot[] {
    return snapshots
      .map((item, index) => {
        const snapshot = item.snapshot || {}
        const date = item.date
        const timestamp =
          Number(item.timestamp ?? snapshot.timestamp) || this.deriveTimestampFromDate(date, index)
        const type = (snapshot.type || DEFAULT_RANK_TREND_SNAPSHOT_TYPE) as SupportedSnapshotType
        return {
          date,
          timestamp,
          type,
          tradingDate: snapshot.tradingDate || parseTradingDateFromLabel(date),
          slotTime: snapshot.slotTime || parseSlotTimeFromLabel(date),
          captureMode: snapshot.captureMode,
          snapshot,
        }
      })
      .sort((left, right) => left.timestamp - right.timestamp)
  }

  private deriveTimestampFromDate(date: string, fallbackIndex: number): number {
    const dateTimeMatch = date.match(/(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})/)
    if (dateTimeMatch) {
      const parsed = Date.parse(`${dateTimeMatch[1]}T${dateTimeMatch[2]}:00`)
      if (Number.isFinite(parsed)) return parsed
    }

    const dateMatch = date.match(/(\d{4}-\d{2}-\d{2})/)
    if (dateMatch) {
      const parsed = Date.parse(`${dateMatch[1]}T00:00:00`)
      if (Number.isFinite(parsed)) return parsed + fallbackIndex
    }

    return fallbackIndex
  }

  private buildSampleQualitySummary(
    snapshots: RankTrendAnalysisSnapshot[],
    preferredType?: SupportedSnapshotType,
    enforceLiveTimeline = false,
  ): SampleQualitySummary {
    const requiredSampleCount = getTechnicalMinSamples(runtimeConfig)
    const sampleCount = snapshots.length
    const latestSnapshot = snapshots[snapshots.length - 1]
    const latestTradingDate = latestSnapshot?.tradingDate || parseTradingDateFromLabel(latestSnapshot?.date)
    const latestSlotTime = latestSnapshot?.slotTime || parseSlotTimeFromLabel(latestSnapshot?.date)
    const snapshotType = latestSnapshot?.type || preferredType || DEFAULT_RANK_TREND_SNAPSHOT_TYPE
    const delayedCount = snapshots.filter((item) => item.captureMode === 'delayed').length
    const restoredCount = snapshots.filter((item) => item.captureMode === 'restored').length
    const preferred = preferredType ?? DEFAULT_RANK_TREND_SNAPSHOT_TYPE
    const timelineWarnings = enforceLiveTimeline ? this.getLiveTimelineWarnings(snapshots) : []

    let status: SampleQualitySummary['status'] = 'insufficient'
    if (timelineWarnings.length > 0) {
      status = 'insufficient'
    } else if (sampleCount >= requiredSampleCount) {
      status = 'ok'
    } else if (sampleCount >= 5) {
      status = 'degraded'
    }

    const warnings: string[] = []
    if (snapshotType !== preferred) {
      warnings.push(`首选 ${preferred} 样本不足，已回退 ${snapshotType}`)
    }
    if (sampleCount < requiredSampleCount) {
      warnings.push(`样本不足 ${sampleCount}/${requiredSampleCount}`)
    }
    if (delayedCount > 0) {
      warnings.push(`包含 ${delayedCount} 个 delayed 快照`)
    }
    if (restoredCount > 0) {
      warnings.push(`包含 ${restoredCount} 个 restored 快照`)
    }
    warnings.push(...timelineWarnings)

    return {
      snapshotType,
      sampleCount,
      requiredSampleCount,
      status,
      timelineValid: timelineWarnings.length === 0,
      coverageWarning: warnings.length > 0 ? warnings.join('；') : undefined,
      latestTradingDate,
      latestSlotTime,
      delayedCount,
      restoredCount,
    }
  }

  private getLiveTimelineWarnings(snapshots: RankTrendAnalysisSnapshot[]): string[] {
    if (!snapshots.length) return []

    const warnings: string[] = []
    for (let index = 1; index < snapshots.length; index++) {
      const gap = snapshots[index].timestamp - snapshots[index - 1].timestamp
      if (gap <= 0) {
        warnings.push('历史快照时间乱序或重复')
        break
      }
      if (gap > MAX_LIVE_HISTORY_GAP_MS) {
        warnings.push('历史快照存在超过 7 天的时间断层')
        break
      }

      const previous = snapshots[index - 1]
      const current = snapshots[index]
      if (previous.type !== current.type) continue
      const expectedSlots = getExpectedSlots(current.type)
      const previousSlotIndex = expectedSlots.indexOf(previous.slotTime || '')
      const currentSlotIndex = expectedSlots.indexOf(current.slotTime || '')
      if (previousSlotIndex < 0 || currentSlotIndex < 0) continue

      const sameTradingDate = previous.tradingDate === current.tradingDate
      const isConsecutive = sameTradingDate
        ? currentSlotIndex === previousSlotIndex + 1
        : previousSlotIndex === expectedSlots.length - 1 && currentSlotIndex === 0
      if (!isConsecutive) {
        warnings.push('历史快照存在缺失槽位')
        break
      }
    }

    const latestTimestamp = snapshots.at(-1)?.timestamp || 0
    if (latestTimestamp > 0 && Date.now() - latestTimestamp > MAX_LIVE_HISTORY_GAP_MS) {
      warnings.push('历史快照陈旧，最新帧距当前超过 7 天')
    }
    return warnings
  }

  private getLatestContinuousMarketWindow(
    snapshots: RankTrendAnalysisSnapshot[],
  ): { snapshots: RankTrendAnalysisSnapshot[]; skippedHistoryCount: number } {
    if (snapshots.length < 2) return { snapshots, skippedHistoryCount: 0 }

    let startIndex = snapshots.length - 1
    while (startIndex > 0) {
      const previous = snapshots[startIndex - 1]
      const current = snapshots[startIndex]
      const gap = current.timestamp - previous.timestamp
      if (gap <= 0 || gap > MAX_LIVE_HISTORY_GAP_MS) {
        if (previous.tradingDate === current.tradingDate) {
          return { snapshots, skippedHistoryCount: 0 }
        }
        break
      }
      if (previous.type === current.type) {
        const expectedSlots = getExpectedSlots(current.type)
        const previousSlotIndex = expectedSlots.indexOf(previous.slotTime || '')
        const currentSlotIndex = expectedSlots.indexOf(current.slotTime || '')
        if (previousSlotIndex >= 0 && currentSlotIndex >= 0) {
          const isConsecutive = previous.tradingDate === current.tradingDate
            ? currentSlotIndex === previousSlotIndex + 1
            : previousSlotIndex === expectedSlots.length - 1 && currentSlotIndex === 0
          if (!isConsecutive) {
            if (previous.tradingDate === current.tradingDate) {
              return { snapshots, skippedHistoryCount: 0 }
            }
            break
          }
        }
      }
      startIndex -= 1
    }

    return { snapshots: snapshots.slice(startIndex), skippedHistoryCount: startIndex }
  }

  private shouldAppendCurrentFrame(
    currentRanks: Map<string, number>,
    previousRanks: Map<string, number>,
    currentTotalCount: number,
    previousTotalCount: number,
  ): boolean {
    if (currentTotalCount !== previousTotalCount || currentRanks.size !== previousRanks.size) return true
    return Array.from(currentRanks).some(([code, rank]) => previousRanks.get(code) !== rank)
  }

  private derivePerStockSampleQuality(
    base: SampleQualitySummary,
    sampleCount: number,
  ): SampleQualitySummary {
    const status: SampleQualitySummary['status'] =
      base.status === 'insufficient'
        ? 'insufficient'
        : sampleCount >= base.requiredSampleCount
          ? 'ok'
          : sampleCount >= 5
            ? 'degraded'
            : 'insufficient'

    const warnings = base.coverageWarning ? [base.coverageWarning] : []
    if (sampleCount < base.requiredSampleCount) {
      warnings.push(`个股有效样本不足 ${sampleCount}/${base.requiredSampleCount}`)
    }
    return {
      ...base,
      sampleCount,
      status,
      timelineValid: base.timelineValid !== false,
      coverageWarning: warnings.length > 0 ? Array.from(new Set(warnings)).join('；') : undefined,
    }
  }

  private buildSnapshotsMap(snapshots: RankTrendAnalysisSnapshot[]): Map<string, any> {
    const map = new Map<string, any>()
    for (const item of snapshots) {
      map.set(item.date, item.snapshot)
    }
    return map
  }

  private buildSnapshotSignature(snapshots: RankTrendAnalysisSnapshot[]): string {
    return snapshots.map((item) => `${item.type}:${item.date}:${item.timestamp}`).join('|')
  }

  private getLatestRankSnapshot(
    recentSnapshots: RankTrendAnalysisSnapshot[],
  ): { prevRankMap: Map<string, number>; prevTotalCount: number } {
    const prevSnapshot = recentSnapshots[recentSnapshots.length - 1] || null
    const prevTotalCount =
      Number(prevSnapshot?.snapshot?.totalCount) || prevSnapshot?.snapshot?.hotlist?.length || 200
    const prevRankMap = new Map<string, number>()

    if (prevSnapshot?.snapshot?.hotlist) {
      prevSnapshot.snapshot.hotlist.forEach((item: any, index: number) => {
        const rank = Number(item?.rank ?? index + 1)
        if (item?.code && rank > 0) {
          prevRankMap.set(item.code, rank)
        }
      })
    }

    return { prevRankMap, prevTotalCount }
  }

  private resolveMarketRegime(snapshotSignature: string, dataLayer: any) {
    const stocks = typeof dataLayer.getStocks === 'function' ? dataLayer.getStocks() : []
    const breathData = typeof dataLayer.getBreathData === 'function' ? dataLayer.getBreathData() : null
    const signature = `${snapshotSignature}:${stocks.length}:${breathData?.lastUpdate || breathData?.timestamp || ''}`

    if (this.marketRegimeCache?.signature === signature) {
      return this.marketRegimeCache.value
    }

    const value = analyzeMarketRegime({ breathData, stocks })
    this.marketRegimeCache = { signature, value }
    return value
  }

  private async computeStockRankTrend(input: {
    code: string
    currentRank: number
    currentTotalCount: number
    prevRankMap: Map<string, number>
    prevTotalCount: number
    weekdays: string[]
    snapshots: Map<string, any>
    snapshotSignature: string
    sampleQuality: SampleQualitySummary
    enforceLiveTimeline: boolean
    currentFrameKey: string
    appendCurrentFrame: boolean
  }): Promise<[string, RankTrendResult | null]> {
    const {
      code,
      currentRank,
      currentTotalCount,
      prevRankMap,
      prevTotalCount,
      weekdays,
      snapshots,
      snapshotSignature,
      sampleQuality,
      enforceLiveTimeline,
      currentFrameKey,
      appendCurrentFrame,
    } = input

    const cacheKey = code
    let rankHistoryData = this.rankHistoryCache.get(cacheKey)
    const dataLayer = await this.getDataLayer()

    if (!rankHistoryData || rankHistoryData.snapshotSignature !== snapshotSignature) {
      const ranks: number[] = []
      const percentiles: number[] = []
      const totalCounts: number[] = []
      const frameKeys: string[] = []

      for (const date of weekdays) {
        const snapshot = snapshots.get(date)
        const hotlist = Array.isArray(snapshot?.hotlist) ? snapshot.hotlist : []
        const itemIndex = hotlist.findIndex((item: any) => item.code === code)
        const item = itemIndex >= 0 ? hotlist[itemIndex] : null
        const totalCount = Number(snapshot?.totalCount) || hotlist.length
        const rank = Number(item?.rank ?? (itemIndex >= 0 ? itemIndex + 1 : 0))
        if (rank > 0 && totalCount > 0) {
          ranks.push(rank)
          percentiles.push(this.calculatePercentileRank(rank, totalCount))
          totalCounts.push(totalCount)
          frameKeys.push(date)
        }
      }

      rankHistoryData = { snapshotSignature, ranks, percentiles, totalCounts, frameKeys }
      this.rankHistoryCache.set(cacheKey, rankHistoryData)
    }

    const { ranks, percentiles, frameKeys } = rankHistoryData
    if (ranks.length === 0 && !dataLayer.getStock(code)) return [code, null]
    const currentPercentile = this.calculatePercentileRank(currentRank, currentTotalCount)
    const prevRank = prevRankMap.get(code)
    const prevPercentile = prevRank
      ? this.calculatePercentileRank(prevRank, prevTotalCount)
      : currentPercentile
    const displayChange = prevRank ? currentPercentile - prevPercentile : 0
    const analysisRanks = appendCurrentFrame ? [...ranks, currentRank] : [...ranks]
    const analysisPercentiles = appendCurrentFrame ? [...percentiles, currentPercentile] : [...percentiles]
    const analysisFrameKeys = appendCurrentFrame ? [...frameKeys, currentFrameKey] : [...frameKeys]
    this.latestAnalysisSeries.set(code, {
      ranks: [...analysisRanks],
      percentiles: [...analysisPercentiles],
      frameKeys: analysisFrameKeys,
    })
    const stockSampleQuality = this.derivePerStockSampleQuality(
      sampleQuality,
      analysisPercentiles.length,
    )

    const stock = dataLayer.getStock(code)
    // || 0 防御 Number("abc") 等非数字字符串产生 NaN 污染下游计算链
    const stockChange = Number(stock?.change ?? 0) || 0
    const volumeRatio = getTrustedVolumeRatio(stock)
    const zlje = Number(stock?.zlje ?? 0) || 0
    const zljzb = Number(stock?.zljzb ?? 0) || 0
    const requiredSamples = stockSampleQuality.requiredSampleCount
    const regime = this.resolveMarketRegime(snapshotSignature, dataLayer)

    const { technical, cycle, risk, decision, strategy, executionStrategy } = runRankTrendAnalysisPipeline({
      ranks: analysisRanks,
      percentiles: analysisPercentiles,
      currentPercentile,
      displayChange,
      stockChange,
      volumeRatio,
      zlje,
      zljzb,
      regime,
      hotlistSentiment: typeof dataLayer.getBreathData === 'function' ? dataLayer.getBreathData() : null,
      config: runtimeConfig,
      requiredSamples,
    })

    const updateTime = Date.now()
    const rawChange = analysisRanks[0] - analysisRanks[analysisRanks.length - 1]
    const rankTrend: RankTrendAnalysisResult = {
      meta: {
        code,
        currentRank,
        currentPercentile,
        change: displayChange,
        rawChange,
        updateTime,
        sampleQuality: stockSampleQuality,
      },
      technical,
      cycle,
      risk,
      decision,
      strategy,
      executionStrategy,
    }

    const result: RankTrendResult = Object.assign(rankTrend, {
      code,
      currentRank,
      change: displayChange,
      rawChange,
      ma5: technical.movingAverage.ma5,
      ma10: technical.movingAverage.ma10,
      maTrend: technical.movingAverage.trend,
      macd: technical.macd.dif,
      macdSignal: technical.macd.dea,
      macdHistogram: technical.macd.histogram,
      macdCross: technical.macd.cross,
      signal: decision.base.signal,
      confidence: decision.base.confidence,
      directionSignal: technical.signals.direction.signal,
      directionConfidence: technical.signals.direction.confidence,
      accelerationSignal: technical.signals.acceleration.signal,
      accelerationConfidence: technical.signals.acceleration.confidence,
      crossSignal: technical.signals.zeroCross.signal,
      crossConfidence: technical.signals.zeroCross.confidence,
      finalSignal: decision.final.signal,
      finalConfidence: decision.final.confidence,
      updateTime,
    })

    return [code, result]
  }

  private calculatePercentileRank(rank: number, totalCount: number): number {
    if (!Number.isFinite(rank) || !Number.isFinite(totalCount) || totalCount <= 0) return 0
    return ((totalCount - rank + 1) / totalCount) * 100
  }

  private async getDataLayer(): Promise<DataLayerApi> {
    return dataLayer as DataLayerApi
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
