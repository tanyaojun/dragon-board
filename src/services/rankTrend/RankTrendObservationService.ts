import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/types/rankTrendDefaults'
import { dataLayer } from '../DataLayer'
import { rankTrendAnalyzer } from '../RankTrendAnalyzer'
import { snapshotFacade } from '../snapshot/facade'
import type { SnapshotStockRow } from '../snapshot/types'
import { analyzeRankResonance } from './resonanceAnalyzer'
import { runRankTrendAnalysisPipeline } from './runRankTrendAnalysisPipeline'
import { analyzeTechnicalSignals } from './technicalSignalAnalyzer'
import type { RankTrendAnalysisResult } from './types'
import { getTechnicalMinSamples } from './utils'

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

function calculateMarketMedian(frameKey: string, marketFrameKeys: string[]) {
  const targetIndex = marketFrameKeys.indexOf(frameKey)
  if (targetIndex < 0) return { percentile: null, shortChange: null, sampleCount: 0 }
  const startKey = targetIndex >= 3 ? marketFrameKeys[targetIndex - 3] : null
  const percentiles: number[] = []
  const changes: number[] = []

  for (const stock of dataLayer.getStocks()) {
    const series = rankTrendAnalyzer.getLatestAnalysisSeries(stock.code)
    if (!series) continue
    const endIndex = series.frameKeys.indexOf(frameKey)
    if (endIndex < 0) continue
    const percentile = series.percentiles[endIndex]
    if (Number.isFinite(percentile)) percentiles.push(percentile)
    if (startKey) {
      const startIndex = series.frameKeys.indexOf(startKey)
      if (startIndex < 0) continue
      const change = percentile - series.percentiles[startIndex]
      if (Number.isFinite(change)) changes.push(change)
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

function invalidHistoryFields(row: SnapshotStockRow): string[] {
  return (['change', 'volumeRatio', 'zlje', 'zljzb'] as const).filter((field) => {
    const value: unknown = row[field]
    return value === null || value === undefined || value === '' || !Number.isFinite(Number(value))
  })
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
    const config = rankTrendAnalyzer.getRuntimeConfig()
    const regime = currentAnalysis?.strategy?.regime || {
      state: 'normal' as const,
      score: 0,
      reasons: ['历史市场环境未单独持久化'],
    }
    const allFrames: RankTrendObservationFrame[] = []

    for (let index = 0; index < series.frameKeys.length; index += 1) {
      const key = series.frameKeys[index]
      const isCurrent = index === series.frameKeys.length - 1
      const row = rowsByFrame.get(key)
      const market = calculateMarketMedian(key, marketFrameKeys)
      const issues: RankTrendObservationIssue[] = []
      let analysis: RankTrendObservationAnalysis | null = null

      if (isCurrent) {
        analysis = currentAnalysis ?? null
      } else {
        const ranks = series.ranks.slice(0, index + 1)
        const percentiles = series.percentiles.slice(0, index + 1)
        const previousRank = ranks.at(-2) ?? ranks.at(-1) ?? 0
        const currentRank = ranks.at(-1) ?? 0
        const displayChange = previousRank > 0
          ? ((previousRank - currentRank) / previousRank) * 100
          : 0
        const jumpEvents = (currentAnalysis?.jump?.events || []).filter((event) => event.index <= index)
        const latestJump = jumpEvents.at(-1)
        const jumpDirection = latestJump?.direction === 'surge'
          ? 'buy'
          : latestJump?.direction === 'collapse'
            ? 'sell'
            : 'hold'
        const resonance = analyzeRankResonance({
          percentiles,
          sampleQuality: { status: percentiles.length >= 9 ? 'ok' : 'insufficient' },
          marketMedianShortChange: market.shortChange ?? Number.NaN,
          marketSampleCount: market.sampleCount,
          jump: {
            direction: jumpDirection,
            event: latestJump?.index === index ? 'jump' : 'none',
            events: jumpEvents,
          },
        })
        analysis = {
          meta: {
            ...(currentAnalysis?.meta || {
              code,
              change: displayChange,
              rawChange: previousRank - currentRank,
              updateTime: Number(row?.timestamp || 0),
            }),
            currentRank,
            currentPercentile: percentiles.at(-1) ?? 0,
          },
          resonance,
        }

        const requiredSamples = getTechnicalMinSamples(config)
        if (percentiles.length >= requiredSamples) {
          analysis.technical = analyzeTechnicalSignals(percentiles, config)
        } else {
          issues.push(observationIssue(
            'technical_sample_insufficient',
            `该帧技术结构样本不足（${percentiles.length}/${requiredSamples}）`,
            { frameKey: key, track: 'technical' },
          ))
        }

        const invalidFields = row ? invalidHistoryFields(row) : []
        if (!row) {
          issues.push(observationIssue(
            'history_material_unavailable',
            serviceIssues.some((issue) => issue.code === 'history_source_unavailable')
              ? '历史快照原料不可用，生命周期与风险轨不可计算'
              : '该帧资金与行情原料缺失，生命周期与风险轨不可计算',
            { frameKey: key, track: 'lifecycle' },
          ))
        } else if (invalidFields.length) {
          issues.push(
            ...invalidFields.map((field) => observationIssue(
              'history_field_invalid',
              `该帧 ${field} 缺失或非法，依赖该字段的生命周期与风险轨不可计算`,
              { frameKey: key, field, track: 'lifecycle' },
            )),
          )
        } else {
          const pipeline = runRankTrendAnalysisPipeline({
            ranks,
            percentiles,
            currentPercentile: percentiles.at(-1) ?? 0,
            displayChange,
            stockChange: Number(row.change),
            volumeRatio: Number(row.volumeRatio),
            zlje: Number(row.zlje),
            zljzb: Number(row.zljzb),
            regime,
            config,
          })
          analysis = { ...analysis, ...pipeline, resonance }
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
      frames: allFrames.slice(-9),
      issues: serviceIssues,
    }
  }
}

export const rankTrendObservationService = new RankTrendObservationService()
