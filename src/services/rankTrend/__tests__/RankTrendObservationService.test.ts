import { afterEach, describe, expect, it, vi } from 'vitest'

import { rankTrendAnalyzer } from '../../RankTrendAnalyzer'
import { snapshotFacade } from '../../snapshot/facade'
import { rankTrendObservationService } from '../RankTrendObservationService'

describe('RankTrendObservationService', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the in-memory rank path and reports the API issue when historical rows fail to load', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys: ['2026-07-28 14:30', '2026-07-28 15:00'],
    })
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockRejectedValue(new Error('backend offline'))

    const currentAnalysis = { meta: { code: '002279' } }
    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis,
    })

    expect(result.frames).toHaveLength(2)
    expect(result.frames[0]).toMatchObject({
      key: '2026-07-28 14:30',
      percentile: 42,
    })
    expect(result.frames[0].analysis?.resonance).toBeTruthy()
    expect(result.frames[1].analysis).toBe(currentAnalysis)
    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'history_source_unavailable',
      message: '历史快照原料读取失败: backend offline',
    }))
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'history_material_unavailable',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('keeps the rank path when current analysis is unavailable', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys: ['2026-07-28 14:30', '2026-07-28 15:00'],
    })
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockRejectedValue(new Error('backend offline'))

    const result = await rankTrendObservationService.load({ code: '002279', name: '久其软件' })

    expect(result.frames).toHaveLength(2)
    expect(result.frames[0].analysis?.resonance).toBeTruthy()
    expect(result.frames[1].analysis).toBeNull()
    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'current_analysis_unavailable',
    }))
  })

  it('keeps the current analysis frame when the in-memory rank series is unavailable', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue(null)
    const currentAnalysis = {
      meta: { code: '603580', currentPercentile: 83, updateTime: 1 },
      observation: { lifecycle: { score: 90 } },
    }

    const result = await rankTrendObservationService.load({
      code: '603580',
      name: '艾艾精工',
      rankTrend: currentAnalysis,
    })

    expect(result.frames).toHaveLength(1)
    expect(result.frames[0]).toMatchObject({
      label: '当前',
      percentile: 83,
      analysis: currentAnalysis,
    })
    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'rank_series_unavailable',
    }))
  })

  it('reports missing historical fields while preserving rank-only resonance analysis', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys: ['2026-07-28 14:30', '2026-07-28 15:00'],
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue([])
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([
      {
        code: '002279',
        tradingDate: '2026-07-28',
        slotTime: '14:30',
        change: 1.2,
        volumeRatio: Number.NaN,
      } as any,
    ])

    const currentAnalysis = { meta: { code: '002279' } }
    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis,
    })

    expect(result.frames[0].analysis?.resonance).toBeTruthy()
    expect(result.frames[0].analysis?.observation?.lifecycle).toBeUndefined()
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'history_field_invalid',
      field: 'volumeRatio',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('preserves the historical MACD track when stock-row material is unavailable', async () => {
    const frameKeys = Array.from({ length: 40 }, (_, index) => `frame-${index + 1}`)
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: frameKeys.map((_, index) => 80 - index),
      percentiles: frameKeys.map((_, index) => 20 + index),
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockRejectedValue(new Error('backend offline'))

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(result.frames).toHaveLength(9)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.technical?.macd)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.resonance)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.risk === undefined)).toBe(true)
  })
})
