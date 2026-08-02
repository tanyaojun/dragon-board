import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'
import { rankTrendAnalyzer } from '../RankTrendAnalyzer'
import { apiService } from '../apiService'
import { snapshotFacade } from '../snapshot/facade'
import type { SnapshotStockRow } from '../snapshot/types'
import { analyzeRankResonance } from './resonanceAnalyzer'
import type { RankTrendAnalysisResult } from './types'
import type { SnapshotFrameRow } from '../snapshot/types'

export type ObservationTrack = 'resonance' | 'technical' | 'lifecycle'

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
}

/** 各观察轨的显示窗口（bar/帧），按信号可计算与稳定需求分别设定 */
export const OBSERVATION_WINDOW_BARS = {
  resonance: 9,
  technical: 22,
  lifecycle: 15,
} as const

export const MAX_OBSERVATION_WINDOW_BARS = Math.max(...Object.values(OBSERVATION_WINDOW_BARS))

/** 生命周期动量确认因子（mid 动量 + 加速度）可算窗口 */
export const LIFECYCLE_MIN_SAMPLES = 15

/** 市场横截面单次读取的行数上限（覆盖观察窗口各帧全市场行） */
const MARKET_CROSS_SECTION_ROW_LIMIT = 20000

/** 历史帧市场环境原料单次读取的帧数上限（覆盖观察窗口即可） */
const HISTORY_FRAME_READ_LIMIT = 200

/** 市场横截面计算所需的最小字段集（按帧真实横截面只依赖这几列） */
const MARKET_CROSS_SECTION_FIELDS = ['tradingDate', 'slotTime', 'code', 'avgRankNum'] as const

function median(values: number[]): number | null {
  if (!values.length) return null
  const sorted = [...values].sort((left, right) => left - right)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2
    ? sorted[middle]
    : (sorted[middle - 1] + sorted[middle]) / 2
}

function barFrameKey(bar: any): string {
  return `${bar?.tradingDate || ''} ${bar?.slotTime || ''}`.trim()
}

function frameLabel(frameKey: string): string {
  const match = frameKey.match(/(\d{2}-\d{2})\s+(\d{2}:\d{2})/)
  if (match) return `${match[1]} ${match[2]}`
  return frameKey.startsWith('current:') ? '当前' : frameKey
}

type FrameCrossSections = Map<string, Map<string, number>>

function buildFrameCrossSections(rows: SnapshotStockRow[]): FrameCrossSections {
  const byFrame = new Map<string, Array<{ code: string; avgRankNum: number }>>()
  for (const row of rows) {
    const key = barFrameKey(row)
    if (!key) continue
    const code = String(row.code || '')
    const avgRankNum = Number(row.avgRankNum)
    if (!code || !Number.isFinite(avgRankNum) || avgRankNum <= 0) continue
    const list = byFrame.get(key) ?? []
    list.push({ code, avgRankNum })
    byFrame.set(key, list)
  }

  const result: FrameCrossSections = new Map()
  for (const [key, list] of byFrame) {
    const sorted = [...list].sort(
      (left, right) => left.avgRankNum - right.avgRankNum || left.code.localeCompare(right.code),
    )
    const totalCount = sorted.length
    const percentiles = new Map<string, number>()
    sorted.forEach((item, index) => {
      percentiles.set(item.code, ((totalCount - index) / totalCount) * 100)
    })
    result.set(key, percentiles)
  }
  return result
}

function calculateMarketMedian(
  frameKey: string,
  marketFrameKeys: string[],
  crossSections: FrameCrossSections,
) {
  const crossSectionKey = frameKey.startsWith('current:')
    ? marketFrameKeys.filter((key) => !key.startsWith('current:')).at(-1) ?? frameKey
    : frameKey
  const targetIndex = marketFrameKeys.indexOf(crossSectionKey)
  if (targetIndex < 0) return { percentile: null, shortChange: null, sampleCount: 0 }
  const startKey = targetIndex >= 3 ? marketFrameKeys[targetIndex - 3] : null
  const framePercentiles = crossSections.get(crossSectionKey)
  if (!framePercentiles || framePercentiles.size === 0) {
    return { percentile: null, shortChange: null, sampleCount: 0 }
  }

  const percentiles = Array.from(framePercentiles.values())
  const changes: number[] = []
  if (startKey) {
    const startPercentiles = crossSections.get(startKey)
    if (startPercentiles) {
      for (const [code, percentile] of framePercentiles) {
        const start = startPercentiles.get(code)
        if (start !== undefined) changes.push(percentile - start)
      }
    }
  }

  return {
    percentile: median(percentiles),
    shortChange: median(changes),
    sampleCount: percentiles.length,
  }
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

class RankTrendObservationService {
  async load(stock: any): Promise<RankTrendObservationViewModel> {
    const code = String(stock?.code || '')
    const currentAnalysis = stock?.rankTrend as RankTrendAnalysisResult | undefined
    const series = rankTrendAnalyzer.getLatestAnalysisSeries(code)
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
        }
      }
      return {
        code,
        name: String(stock?.name || ''),
        frames: [],
        issues,
      }
    }

    const serviceIssues: RankTrendObservationIssue[] = []
    if (!currentAnalysis) {
      serviceIssues.push(
        observationIssue('current_analysis_unavailable', '当前 RankTrend 分析结果不可用，保留排名路径'),
      )
    }
    let rows: SnapshotStockRow[] = []
    try {
      rows = await snapshotFacade.listSnapshotStockRows({
        type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
        code,
        sort: 'desc',
        limit: 50,
        allowedCaptureModes: ['real_time', 'delayed'],
        excludeRestored: true,
      })
      const frameKeys = new Set(series.frameKeys)
      rows = rows.filter((row) => frameKeys.has(barFrameKey(row)))
    } catch (error) {
      serviceIssues.push(
        observationIssue(
          'history_source_unavailable',
          `历史快照原料读取失败: ${errorMessage(error)}`,
        ),
      )
    }
    const rowsByFrame = new Map(rows.map((row) => [barFrameKey(row), row]))
    const marketFrameKeys = rankTrendAnalyzer.getLatestAnalysisFrameKeys()
    const windowFrameKeys = series.frameKeys.slice(-MAX_OBSERVATION_WINDOW_BARS)
    const windowDates = windowFrameKeys
      .map((key) => key.split(' ')[0])
      .filter((date) => /^\d{4}-\d{2}-\d{2}$/.test(date))
    let crossSections: FrameCrossSections = new Map()
    if (windowDates.length > 0) {
      try {
        const crossSectionRows = await snapshotFacade.listSnapshotStockRows({
          type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          startDate: windowDates[0],
          endDate: windowDates[windowDates.length - 1],
          sort: 'asc',
          limit: MARKET_CROSS_SECTION_ROW_LIMIT,
          fields: [...MARKET_CROSS_SECTION_FIELDS],
          allowedCaptureModes: ['real_time', 'delayed'],
          excludeRestored: true,
        })
        crossSections = buildFrameCrossSections(crossSectionRows)
      } catch (error) {
        serviceIssues.push(
          observationIssue(
            'market_cross_section_unavailable',
            `市场横截面读取失败: ${errorMessage(error)}`,
          ),
        )
      }
    }
    const frameRowsByKey = new Map<string, SnapshotFrameRow>()
    if (windowDates.length > 0) {
      try {
        const historyFrames = await snapshotFacade.listSnapshotFrames({
          type: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          startDate: windowDates[0],
          endDate: windowDates[windowDates.length - 1],
          sort: 'asc',
          limit: HISTORY_FRAME_READ_LIMIT,
          projection: 'ranktrend',
          allowedCaptureModes: ['real_time', 'delayed'],
          excludeRestored: true,
        })
        for (const historyFrame of historyFrames) {
          const frameKey = barFrameKey(historyFrame)
          if (frameKey) frameRowsByKey.set(frameKey, historyFrame)
        }
      } catch (error) {
        serviceIssues.push(
          observationIssue(
            'historical_frames_unavailable',
            `历史帧市场环境原料读取失败: ${errorMessage(error)}`,
          ),
        )
      }
    }

    // Python golden 批量分析历史帧（technical/cycle/risk/decision/observation/strategy/jump/regime）
    const historyFrameKeys = series.frameKeys.slice(-MAX_OBSERVATION_WINDOW_BARS, -1)
    const remoteByFrame = new Map<string, RankTrendObservationAnalysis>()
    if (historyFrameKeys.length > 0) {
      try {
        const remote = await apiService.analyzeRankTrend({
          snapshotType: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
          codes: [code],
          frameKeys: historyFrameKeys,
        })
        if (remote?.ok) {
          for (const frame of remote.frames || []) {
            const first = frame.stocks?.[0]
            if (first?.analysis) {
              remoteByFrame.set(frame.frameKey, first.analysis as RankTrendObservationAnalysis)
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
      const market = calculateMarketMedian(key, marketFrameKeys, crossSections)
      const issues: RankTrendObservationIssue[] = []
      let analysis: RankTrendObservationAnalysis | null = null

      if (isCurrent) {
        analysis = currentAnalysis ?? null
      } else {
        const percentiles = series.percentiles.slice(0, index + 1)
        const remoteAnalysis = remoteByFrame.get(key)
        const pyJump = (remoteAnalysis?.jump ?? {
          event: 'none',
          direction: 'hold',
          confidence: 50,
          events: [],
        }) as NonNullable<RankTrendObservationAnalysis['jump']>
        const resonance = analyzeRankResonance({
          percentiles,
          sampleQuality: { status: percentiles.length >= 9 ? 'ok' : 'insufficient' },
          marketMedianShortChange: market.shortChange ?? Number.NaN,
          marketSampleCount: market.sampleCount,
          jump: {
            direction: pyJump.direction === 'buy' ? 'buy' : pyJump.direction === 'sell' ? 'sell' : 'hold',
            event: pyJump.event === 'jump' ? 'jump' : 'none',
            events: Array.isArray(pyJump.events) ? pyJump.events : [],
          },
        })
        if (remoteAnalysis) {
          analysis = { ...remoteAnalysis, resonance }
          if (percentiles.length < OBSERVATION_WINDOW_BARS.technical) {
            issues.push(observationIssue(
              'technical_sample_insufficient',
              `该帧技术结构样本不足（当前 ${percentiles.length} bar）`,
              { frameKey: key, track: 'technical' },
            ))
          } else if (percentiles.length < 30) {
            issues.push(observationIssue(
              'technical_stable_window_insufficient',
              `该帧技术结构已计算，未达稳定观察窗口（${percentiles.length}/30）`,
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
            resonance,
          }
          issues.push(observationIssue(
            'analysis_unavailable',
            '历史帧分析不可用：Python 后端未返回该帧结果',
            { frameKey: key },
          ))
        }
      }

      if (market.percentile == null || market.sampleCount < 20) {
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

    return {
      code,
      name: String(stock?.name || ''),
      frames: allFrames.slice(-MAX_OBSERVATION_WINDOW_BARS),
      issues: serviceIssues,
    }
  }
}

export const rankTrendObservationService = new RankTrendObservationService()
