import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'
import { rankTrendAnalyzer } from '../RankTrendAnalyzer'
import { apiService } from '../apiService'
import { snapshotFacade } from '../snapshot/facade'
import type { RankTrendAnalysisResult } from './types'

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

class RankTrendObservationService {
  async load(stock: any): Promise<RankTrendObservationViewModel> {
    const code = String(stock?.code || '')
    const currentAnalysis = stock?.rankTrend as RankTrendAnalysisResult | undefined
    let series = rankTrendAnalyzer.getLatestAnalysisSeries(code)
    if (!series) {
      // 展示序列自建兜底：从 rank-series API 读取该股历史排名（纯数据投影，非算法），
      // 保证后端 analyze 暂不可用时观察面板仍能展示历史排名曲线（fail-visible）。
      series = await this.buildSeriesFromSnapshots(code)
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
    let rows: Array<Record<string, any>> = []
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
        })
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

    return {
      code,
      name: String(stock?.name || ''),
      frames: allFrames.slice(-MAX_OBSERVATION_WINDOW_BARS),
      issues: serviceIssues,
    }
  }

  private async buildSeriesFromSnapshots(code: string): Promise<{
    ranks: number[]
    percentiles: number[]
    frameKeys: string[]
  } | null> {
    try {
      const snapshots = await rankTrendAnalyzer.getSnapshotsByType(DEFAULT_RANK_TREND_SNAPSHOT_TYPE, {
        limit: 50,
        codes: [code],
      })
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
