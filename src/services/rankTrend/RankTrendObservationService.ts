import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'
import { rankTrendAnalyzer } from '../RankTrendAnalyzer'
import { apiService } from '../apiService'
import { cacheManager } from '../LRUCache'
import { snapshotFacade } from '../snapshot/facade'
import type { RankTrendAnalysisResult } from './types'

export type ObservationTrack = 'resonance' | 'technical' | 'lifecycle' | 'theme'

export type RankTrendObservationIssue = {
  code: string
  message: string
  frameKey?: string
  field?: string
  track?: ObservationTrack
}

export type RankTrendObservationFrame = {
  key: string
  label: string
  percentile: number
  marketMedianPercentile: number | null
  marketMedianShortChange: number | null
  marketSampleCount: number
  analysis: RankTrendObservationAnalysis | null
  issues: RankTrendObservationIssue[]
}

export type RankTrendObservationAnalysis = Pick<RankTrendAnalysisResult, 'meta'> &
  Partial<Omit<RankTrendAnalysisResult, 'meta'>>

export type RankTrendObservationViewModel = {
  code: string
  name: string
  frames: RankTrendObservationFrame[]
  issues: RankTrendObservationIssue[]
  source: 'cache' | 'live'
}

/** 各观察轨的显示窗口（bar/帧），按信号可计算与稳定需求分别设定 */
export const OBSERVATION_WINDOW_BARS = {
  resonance: 9,
  technical: 22,
  lifecycle: 15,
  theme: 15, // 题材动量：日线口径，观察窗口按帧数对齐 lifecycle
} as const

export const MAX_OBSERVATION_WINDOW_BARS = Math.max(...Object.values(OBSERVATION_WINDOW_BARS))

/** 生命周期动量确认因子（mid 动量 + 加速度）可算窗口 */
export const LIFECYCLE_MIN_SAMPLES = 15

/** 观察投影缓存：同一股票同数据代次重复打开时 0 请求秒开（纯展示投影，不参与算法/回测） */
export const OBSERVATION_PROJECTION_CACHE_CAPACITY = 60
export const OBSERVATION_PROJECTION_CACHE_TTL_MS = 60_000

export const observationProjectionCache = cacheManager.createCache('observation', {
  capacity: OBSERVATION_PROJECTION_CACHE_CAPACITY,
  defaultTTL: OBSERVATION_PROJECTION_CACHE_TTL_MS,
  maxMemory: 24 * 1024 * 1024,
  ttlConfig: { observation: OBSERVATION_PROJECTION_CACHE_TTL_MS },
})

/**
 * stock-rows 查询投影缓存：同一股票历史快照行 30 分钟内不重复请求 MongoDB。
 * 该数据是投影瘦身后的只读历史行（tradingDate/slotTime/timestamp/code），一天内几乎不变；
 * 新帧 ingest 带来的延迟由 TTL 兜底，观察投影缓存（60s）与后端 generation 指纹负责数据新鲜度。
 */
export const OBSERVATION_STOCK_ROWS_CACHE_CAPACITY = 200
export const OBSERVATION_STOCK_ROWS_CACHE_TTL_MS = 30 * 60 * 1000

export const observationStockRowsCache = cacheManager.createCache('observationStockRows', {
  capacity: OBSERVATION_STOCK_ROWS_CACHE_CAPACITY,
  defaultTTL: OBSERVATION_STOCK_ROWS_CACHE_TTL_MS,
  maxMemory: 16 * 1024 * 1024,
  ttlConfig: { observationStockRows: OBSERVATION_STOCK_ROWS_CACHE_TTL_MS },
})

function observationProjectionCacheKey(
  code: string,
  series: { frameKeys: string[]; percentiles: number[] },
  currentAnalysis: RankTrendAnalysisResult | undefined,
): string {
  const lastPercentile = series.percentiles.at(-1)
  const seriesSig = [
    series.frameKeys.length,
    series.frameKeys[0] ?? '',
    series.frameKeys.at(-1) ?? '',
    Number.isFinite(lastPercentile) ? Math.round(Number(lastPercentile) * 100) : '',
  ].join(':')
  const currentSig = [
    currentAnalysis?.meta?.updateTime ?? 0,
    currentAnalysis?.meta?.analysisSource ?? 'none',
  ].join(':')
  return `observation:${DEFAULT_RANK_TREND_SNAPSHOT_TYPE}:${code}:${seriesSig}:${currentSig}`
}

function barFrameKey(bar: any): string {
  return `${bar?.tradingDate || ''} ${bar?.slotTime || ''}`.trim()
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function frameLabel(frameKey: string): string {
  const match = frameKey.match(/(\d{2}-\d{2})\s+(\d{2}:\d{2})/)
  if (match) return `${match[1]} ${match[2]}`
  return frameKey.startsWith('current:') ? '当前' : frameKey
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function observationIssue(
  code: string,
  message: string,
  details: Omit<RankTrendObservationIssue, 'code' | 'message'> = {},
): RankTrendObservationIssue {
  return { code, message, ...details }
}

export type ObservationLoadOptions = { signal?: AbortSignal }

type ObservationInflight = {
  promise: Promise<RankTrendObservationViewModel>
  controller: AbortController
  refs: number
}

class RankTrendObservationService {
  /** in-flight 合并：同股票并发 load 共享同一请求；所有 waiter 取消后 abort 共享请求 */
  private inflight = new Map<string, ObservationInflight>()

  load(stock: any, options: ObservationLoadOptions = {}): Promise<RankTrendObservationViewModel> {
    const code = String(stock?.code || '')
    const existing = this.inflight.get(code)
    if (existing) {
      return this.wrapWaiter(existing, options.signal)
    }
    const controller = new AbortController()
    const entry: ObservationInflight = {
      controller,
      refs: 0,
      promise: this.doLoad(stock, controller.signal),
    }
    entry.promise.then(
      () => this.releaseInflight(code, entry),
      () => this.releaseInflight(code, entry),
    )
    this.inflight.set(code, entry)
    return this.wrapWaiter(entry, options.signal)
  }

  private releaseInflight(code: string, entry: ObservationInflight): void {
    if (this.inflight.get(code) === entry) this.inflight.delete(code)
  }

  /**
   * 为单个调用方包装共享请求：
   * - 无 signal：直接复用共享 promise（refs 持有，永不主动取消）；
   * - 带 signal：signal abort 时该 waiter 立即 reject，refs 递减；
   *   所有 waiter（含无 signal 的持有）都释放后 abort 共享请求。
   */
  private wrapWaiter(
    entry: ObservationInflight,
    signal?: AbortSignal,
  ): Promise<RankTrendObservationViewModel> {
    entry.refs += 1
    if (!signal) return entry.promise
    if (signal.aborted) {
      entry.refs -= 1
      if (entry.refs <= 0) entry.controller.abort()
      return Promise.reject(new DOMException('Request aborted', 'AbortError'))
    }
    return new Promise<RankTrendObservationViewModel>((resolve, reject) => {
      const onAbort = () => {
        entry.refs -= 1
        if (entry.refs <= 0) entry.controller.abort()
        reject(new DOMException('Request aborted', 'AbortError'))
      }
      signal.addEventListener('abort', onAbort, { once: true })
      entry.promise.then(
        (value) => {
          signal.removeEventListener('abort', onAbort)
          resolve(value)
        },
        (error) => {
          signal.removeEventListener('abort', onAbort)
          reject(error)
        },
      )
    })
  }

  private async doLoad(stock: any, signal?: AbortSignal): Promise<RankTrendObservationViewModel> {
    const code = String(stock?.code || '')
    const currentAnalysis = stock?.rankTrend as RankTrendAnalysisResult | undefined
    let series = rankTrendAnalyzer.getLatestAnalysisSeries(code)
    if (!series) {
      // 展示序列自建兜底：从 rank-series API 读取该股历史排名（纯数据投影，非算法），
      // 保证后端 analyze 暂不可用时观察面板仍能展示历史排名曲线（fail-visible）。
      series = await this.buildSeriesFromSnapshots(code, signal)
    }
    if (!series) {
      const issues = [
        observationIssue(
          'rank_series_unavailable',
          currentAnalysis
            ? '当前 RankTrend 排名序列不可用，仅展示当前分析帧'
            : '当前 RankTrend 排名序列不可用',
        ),
      ]
      if (currentAnalysis) {
        const percentile = Number(currentAnalysis.meta?.currentPercentile)
        if (!Number.isFinite(percentile)) {
          issues.push(
            observationIssue('current_percentile_invalid', '当前关注度百分位缺失或非法'),
          )
        }
        return {
          code,
          name: String(stock?.name || ''),
          frames: [{
            key: `current:${code}`,
            label: '当前',
            percentile: Number.isFinite(percentile) ? percentile : Number.NaN,
            marketMedianPercentile: null,
            marketMedianShortChange: null,
            marketSampleCount: 0,
            analysis: currentAnalysis,
            issues: [],
          }],
          issues,
          source: 'live',
        }
      }
      return {
        code,
        name: String(stock?.name || ''),
        frames: [],
        issues,
        source: 'live',
      }
    }

    const cacheKey = observationProjectionCacheKey(code, series, currentAnalysis)
    const cached = observationProjectionCache.get(cacheKey) as RankTrendObservationViewModel | null
    if (cached) {
      return { ...cached, source: 'cache' }
    }

    const serviceIssues: RankTrendObservationIssue[] = []
    if (!currentAnalysis) {
      serviceIssues.push(
        observationIssue('current_analysis_unavailable', '当前 RankTrend 分析结果不可用，保留排名路径'),
      )
    }
    let rows: Array<Record<string, any>> = []
    // 缓存 key 含 limit/fields 维度，防止未来参数变化串 key；fields 投影后行小，容量充裕
    const stockRowsCacheKey = `${DEFAULT_RANK_TREND_SNAPSHOT_TYPE}:${code}:rows:50:4fields`
    const cachedRows = observationStockRowsCache.get(stockRowsCacheKey) as
      | Array<Record<string, any>>
      | null
    if (cachedRows) {
      rows = cachedRows
    } else {
      try {
        rows = await snapshotFacade.listSnapshotStockRows({
          type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          code,
          sort: 'desc',
          limit: 50,
          allowedCaptureModes: ['real_time', 'delayed'],
          excludeRestored: true,
          // fields 投影瘦身：观察服务只需帧身份字段，避免整行 107 字段全量传输
          fields: ['tradingDate', 'slotTime', 'timestamp', 'code'],
          // 交互关键路径：显式 high，避免被后台批量读取（medium 共享槽）拖慢
          priority: 'high',
          signal,
        })
        // 30 分钟查询投影缓存：减少对 MongoDB 的重复查询；abort 的请求结果不缓存
        if (!signal?.aborted) {
          observationStockRowsCache.setWithType(stockRowsCacheKey, rows, 'observationStockRows')
        }
      } catch (error) {
        serviceIssues.push(
          observationIssue(
            'history_source_unavailable',
            `历史快照原料读取失败: ${errorMessage(error)}`,
          ),
        )
      }
    }
    const frameKeys = new Set(series.frameKeys)
    rows = rows.filter((row) => frameKeys.has(barFrameKey(row)))
    const rowsByFrame = new Map(rows.map((row) => [barFrameKey(row), row]))
    // Python golden 批量分析历史帧（technical/cycle/risk/decision/observation/strategy/jump/regime/resonance/横截面基准）
    const historyFrameKeys = series.frameKeys.slice(-MAX_OBSERVATION_WINDOW_BARS, -1)
    const remoteByFrame = new Map<string, {
      analysis: RankTrendObservationAnalysis
      marketMedianPercentile: number | null
      marketMedianShortChange: number | null
      marketSampleCount: number
    }>()
    if (historyFrameKeys.length > 0) {
      try {
        const remote = await apiService.analyzeRankTrend({
          snapshotType: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          codes: [code],
          frameKeys: historyFrameKeys,
        }, { signal })
        if (remote?.ok) {
          for (const frame of remote.frames || []) {
            const first = frame.stocks?.[0]
            if (first?.analysis) {
              remoteByFrame.set(frame.frameKey, {
                analysis: first.analysis as RankTrendObservationAnalysis,
                marketMedianPercentile:
                  typeof frame.marketMedianPercentile === 'number' &&
                  Number.isFinite(frame.marketMedianPercentile)
                    ? frame.marketMedianPercentile
                    : null,
                marketMedianShortChange:
                  typeof frame.marketMedianShortChange === 'number' && Number.isFinite(frame.marketMedianShortChange)
                    ? frame.marketMedianShortChange
                    : null,
                marketSampleCount: Number(frame.marketSampleCount) || 0,
              })
            }
          }
        }
      } catch (error) {
        serviceIssues.push(
          observationIssue(
            'historical_analysis_unavailable',
            `历史帧分析读取失败: ${errorMessage(error)}`,
          ),
        )
      }
    }
    const allFrames: RankTrendObservationFrame[] = []

    for (let index = 0; index < series.frameKeys.length; index += 1) {
      const key = series.frameKeys[index]
      const isCurrent = index === series.frameKeys.length - 1
      const row = rowsByFrame.get(key)
      const remoteMeta = remoteByFrame.get(key)
      // 当前帧不在历史帧批量请求内，市场基准回退到实时 analyze 输出的 resonance
      const currentResonance = isCurrent ? currentAnalysis?.resonance ?? null : null
      const market = {
        percentile:
          remoteMeta?.marketMedianPercentile ??
          currentResonance?.marketMedianPercentile ??
          null,
        shortChange:
          remoteMeta?.marketMedianShortChange ??
          currentResonance?.marketMedianShortChange ??
          null,
        sampleCount: remoteMeta?.marketSampleCount ?? currentResonance?.marketSampleCount ?? 0,
      }
      const issues: RankTrendObservationIssue[] = []
      let analysis: RankTrendObservationAnalysis | null = null

      if (isCurrent) {
        analysis = currentAnalysis ?? null
        if (analysis?.themeMomentum?.status === 'insufficient') {
          issues.push(
            observationIssue(
              'theme_momentum_insufficient',
              `题材动量数据不足: ${(analysis.themeMomentum.reasons || []).join('、')}`,
              { frameKey: key, track: 'theme' },
            ),
          )
        }
      } else {
        const percentiles = series.percentiles.slice(0, index + 1)
        const remoteAnalysis = remoteMeta?.analysis
        if (remoteAnalysis) {
          analysis = { ...remoteAnalysis }
          const sampleStatus = remoteAnalysis.meta?.sampleQuality?.status
          const goldenSampleCount =
            remoteAnalysis.meta?.sampleQuality?.sampleCount ?? percentiles.length
          const hasGoldenQuality =
            sampleStatus === 'ok' || sampleStatus === 'degraded' || sampleStatus === 'insufficient'
          if (
            sampleStatus === 'insufficient' ||
            (!hasGoldenQuality && percentiles.length < OBSERVATION_WINDOW_BARS.technical)
          ) {
            issues.push(observationIssue(
              'technical_sample_insufficient',
              `该帧技术结构样本不足（当前 ${goldenSampleCount} bar）`,
              { frameKey: key, track: 'technical' },
            ))
          } else if (sampleStatus === 'degraded' || (!hasGoldenQuality && percentiles.length < 30)) {
            issues.push(observationIssue(
              'technical_stable_window_insufficient',
              `该帧技术结构已计算，未达稳定观察窗口（${goldenSampleCount}/30）`,
              { frameKey: key, track: 'technical' },
            ))
          }
          if (percentiles.length < LIFECYCLE_MIN_SAMPLES) {
            issues.push(observationIssue(
              'lifecycle_sample_insufficient',
              `该帧生命周期样本不足（当前 ${percentiles.length} bar；动量确认需 ≥${LIFECYCLE_MIN_SAMPLES} bar）`,
              { frameKey: key, track: 'lifecycle' },
            ))
            if (analysis.observation) {
              analysis.observation = { ...analysis.observation, lifecycle: undefined }
            }
          }
        } else {
          const currentMeta = currentAnalysis?.meta
          analysis = {
            meta: {
              code,
              currentRank: Number(currentMeta?.currentRank || 0),
              currentPercentile: percentiles.at(-1) ?? 0,
              change: Number(currentMeta?.change || 0),
              rawChange: Number(currentMeta?.rawChange || 0),
              updateTime: Number(row?.timestamp || currentMeta?.updateTime || 0),
              analysisSource: 'analysis_unavailable',
              analysisUnavailableReason: 'Python 后端未返回该帧分析结果',
            },
          }
          issues.push(observationIssue(
            'analysis_unavailable',
            '历史帧分析不可用：Python 后端未返回该帧结果',
            { frameKey: key },
          ))
        }
      }

      if (market.shortChange == null || market.sampleCount < 20) {
        issues.push(observationIssue(
          'market_sample_insufficient',
          '该帧市场横截面样本不足',
          { frameKey: key, track: 'resonance' },
        ))
      }
      allFrames.push({
        key,
        label: frameLabel(key),
        percentile: series.percentiles[index],
        marketMedianPercentile: market.percentile,
        marketMedianShortChange: market.shortChange,
        marketSampleCount: market.sampleCount,
        analysis,
        issues,
      })
    }

    const viewModel: RankTrendObservationViewModel = {
      code,
      name: String(stock?.name || ''),
      frames: allFrames.slice(-MAX_OBSERVATION_WINDOW_BARS),
      issues: serviceIssues,
      source: 'live',
    }
    // 被取消（abort）的请求结果不写投影缓存：降级结果可能不完整，避免下次打开秒开"历史帧分析不可用"
    if (!signal?.aborted) {
      observationProjectionCache.setWithType(cacheKey, viewModel, 'observation')
    }
    return viewModel
  }

  private async buildSeriesFromSnapshots(
    code: string,
    signal?: AbortSignal,
  ): Promise<{
    ranks: number[]
    percentiles: number[]
    frameKeys: string[]
  } | null> {
    try {
      const snapshots = await rankTrendAnalyzer.getSnapshotsByType(
        DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
        {
          limit: 50,
          codes: [code],
        },
        { signal },
      )
      const ranks: number[] = []
      const percentiles: number[] = []
      const frameKeys: string[] = []
      for (const item of snapshots) {
        const hotlist = Array.isArray(item?.snapshot?.hotlist) ? item.snapshot.hotlist : []
        const index = hotlist.findIndex((row: any) => normalizeCode(row?.code) === code)
        const row = index >= 0 ? hotlist[index] : null
        const totalCount = Number(item.snapshot?.totalCount) || hotlist.length || 0
        const rank = Number(row?.rank ?? (index >= 0 ? index + 1 : 0))
        if (rank > 0 && totalCount > 0) {
          ranks.push(rank)
          percentiles.push(((totalCount - rank + 1) / totalCount) * 100)
          frameKeys.push(String(item.date || ''))
        }
      }
      if (!ranks.length) return null
      return { ranks, percentiles, frameKeys }
    } catch (error) {
      console.warn('[RankTrendObservation] 自建排名序列读取失败:', error)
      return null
    }
  }
}

export const rankTrendObservationService = new RankTrendObservationService()
