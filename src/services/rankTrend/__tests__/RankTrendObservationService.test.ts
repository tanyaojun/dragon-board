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
    const frameKeys = Array.from({ length: 50 }, (_, index) => `frame-${index + 1}`)
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

    expect(result.frames).toHaveLength(22)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.technical?.macd)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.resonance)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.risk === undefined)).toBe(true)
  })

  it('低于最小可计算窗口时按特征解释样本不足原因，不再用稳定窗口 30 掩盖', async () => {
    const frameKeys = Array.from({ length: 19 }, (_, index) => `frame-${index + 1}`)
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

    const frame18Bars = result.frames.find((frame) => frame.key === 'frame-18')
    expect(frame18Bars).toBeTruthy()
    expect(frame18Bars.analysis?.technical).toBeUndefined()
    expect(frame18Bars.issues).toContainEqual(expect.objectContaining({
      code: 'technical_sample_insufficient',
      track: 'technical',
      message: expect.stringMatching(/MACD 需 ≥21 bar、动量需 ≥22 bar/),
    }))
  })

  it('达到最小可计算窗口（22 bar）后即使未达稳定窗口 30 也计算技术信号', async () => {
    const frameKeys = Array.from({ length: 25 }, (_, index) => `frame-${index + 1}`)
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

    const frame21Bars = result.frames.find((frame) => frame.key === 'frame-21')
    const frame22Bars = result.frames.find((frame) => frame.key === 'frame-22')
    expect(frame21Bars).toBeTruthy()
    expect(frame22Bars).toBeTruthy()
    expect(frame21Bars.analysis?.technical).toBeUndefined()
    expect(frame21Bars.issues).toContainEqual(expect.objectContaining({
      code: 'technical_sample_insufficient',
    }))
    expect(frame22Bars.analysis?.technical?.macd).toBeTruthy()
    expect(frame22Bars.issues).toContainEqual(expect.objectContaining({
      code: 'technical_stable_window_insufficient',
      message: expect.stringMatching(/未达稳定观察窗口/),
    }))
    expect(frame22Bars.issues.some((issue) => issue.code === 'technical_sample_insufficient')).toBe(false)
  })

  it('历史帧市场基准使用对应帧全市场横截面，不再用当前股票列表近似', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00', '2026-07-28 15:30', '2026-07-28 16:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19, 12, 9],
      percentiles: [42, 67, 80, 88],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return [{ code: '002279', tradingDate: '2026-07-28', slotTime: '16:00', change: 1, volumeRatio: 1, zlje: 0, zljzb: 0 }]
      }
      // 市场横截面：4 帧、每帧 4 只股票，avgRankNum 升序有效
      return [
        { code: 'A', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 1 },
        { code: 'B', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 2 },
        { code: 'C', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 3 },
        { code: 'D', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 4 },
        { code: 'A', tradingDate: '2026-07-28', slotTime: '15:00', avgRankNum: 1 },
        { code: 'B', tradingDate: '2026-07-28', slotTime: '15:00', avgRankNum: 2 },
        { code: 'C', tradingDate: '2026-07-28', slotTime: '15:00', avgRankNum: 3 },
        { code: 'D', tradingDate: '2026-07-28', slotTime: '15:00', avgRankNum: 4 },
        { code: 'A', tradingDate: '2026-07-28', slotTime: '15:30', avgRankNum: 1 },
        { code: 'B', tradingDate: '2026-07-28', slotTime: '15:30', avgRankNum: 2 },
        { code: 'C', tradingDate: '2026-07-28', slotTime: '15:30', avgRankNum: 3 },
        { code: 'D', tradingDate: '2026-07-28', slotTime: '15:30', avgRankNum: 4 },
        { code: 'A', tradingDate: '2026-07-28', slotTime: '16:00', avgRankNum: 1 },
        { code: 'B', tradingDate: '2026-07-28', slotTime: '16:00', avgRankNum: 2 },
        { code: 'C', tradingDate: '2026-07-28', slotTime: '16:00', avgRankNum: 3 },
        { code: 'D', tradingDate: '2026-07-28', slotTime: '16:00', avgRankNum: 4 },
      ]
    })

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    // 4 只股票百分位 100/75/50/25，中位数 62.5
    expect(result.frames[0].marketMedianPercentile).toBe(62.5)
    expect(result.frames[0].marketSampleCount).toBe(4)
    // 16:00 与 14:30 的短周期变化中位数（每只股票变化 0，中位数 0）
    expect(result.frames[3].marketMedianShortChange).toBe(0)
  })

  it('市场横截面读取失败时按轨道降级并给出结构化原因，不静默用当前股票列表', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return [{ code: '002279', tradingDate: '2026-07-28', slotTime: '15:00', change: 1, volumeRatio: 1, zlje: 0, zljzb: 0 }]
      }
      throw new Error('cross-section offline')
    })

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'market_cross_section_unavailable',
    }))
    expect(result.frames[0].marketMedianPercentile).toBeNull()
    expect(result.frames[0].marketSampleCount).toBe(0)
  })

  it('市场横截面读取只请求必要字段，投影行仍能计算每帧市场基准', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    let crossSectionOptions: any = null
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return [
          {
            code: '002279',
            tradingDate: '2026-07-28',
            slotTime: '15:00',
            change: 1,
            volumeRatio: 1,
            zlje: 0,
            zljzb: 0,
          },
        ]
      }
      crossSectionOptions = options
      // 模拟后端 fields 投影：只返回 4 个必要字段
      return [
        { code: 'A', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 1 },
        { code: 'B', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 2 },
        { code: 'C', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 3 },
        { code: 'D', tradingDate: '2026-07-28', slotTime: '14:30', avgRankNum: 4 },
      ]
    })

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(crossSectionOptions).toMatchObject({
      fields: ['tradingDate', 'slotTime', 'code', 'avgRankNum'],
      startDate: '2026-07-28',
      endDate: '2026-07-28',
      limit: 20000,
    })
    expect(result.frames[0].marketMedianPercentile).toBe(62.5)
    expect(result.frames[0].marketSampleCount).toBe(4)
  })

  it('低于生命周期可算窗口（15 bar）的历史帧按轨降级并给出结构化原因', async () => {
    const frameKeys = Array.from({ length: 18 }, (_, index) => `frame-${index + 1}`)
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: frameKeys.map((_, index) => 80 - index),
      percentiles: frameKeys.map((_, index) => 20 + index),
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return frameKeys.map((key) => ({
          code: '002279',
          tradingDate: key.split(' ')[0],
          slotTime: key.split(' ')[1] ?? '',
          change: 1,
          volumeRatio: 1,
          zlje: 0,
          zljzb: 0,
        }))
      }
      return []
    })

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    const frame10Bars = result.frames.find((frame) => frame.key === 'frame-10')
    const frame16Bars = result.frames.find((frame) => frame.key === 'frame-16')
    expect(frame10Bars).toBeTruthy()
    expect(frame16Bars).toBeTruthy()
    expect(frame10Bars.analysis?.observation?.lifecycle).toBeUndefined()
    expect(frame10Bars.issues).toContainEqual(expect.objectContaining({
      code: 'lifecycle_sample_insufficient',
      track: 'lifecycle',
    }))
    expect(frame16Bars.analysis?.observation?.lifecycle).toBeTruthy()
    expect(frame16Bars.issues.some((issue) => issue.code === 'lifecycle_sample_insufficient')).toBe(false)
  })

  it('历史帧不使用当前帧 regime，改为中性环境并给出结构化原因', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return frameKeys.map((key) => ({
          code: '002279',
          tradingDate: key.split(' ')[0],
          slotTime: key.split(' ')[1] ?? '',
          change: 1,
          volumeRatio: 1,
          zlje: 0,
          zljzb: 0,
        }))
      }
      return []
    })
    const currentAnalysis = {
      meta: { code: '002279' },
      strategy: { regime: { state: 'strong', score: 90, reasons: ['强市'] } },
    }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    expect(result.frames[0].analysis?.strategy?.regime?.state).toBe('normal')
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'historical_regime_unavailable',
    }))
  })

  it('历史帧 Jump 事件独立重算，不依赖当前分析的近似索引', async () => {
    const frameKeys = Array.from({ length: 8 }, (_, index) => `frame-${index + 1}`)
    // 第 6 帧累计变化 20 > 15，触发 surge jump
    const percentiles = [20, 21, 22, 23, 24, 40, 42, 43]
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: frameKeys.map((_, index) => 60 - index),
      percentiles,
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockImplementation(async (options: any) => {
      if (options.code) {
        return frameKeys.map((key) => ({
          code: '002279',
          tradingDate: key.split(' ')[0],
          slotTime: key.split(' ')[1] ?? '',
          change: 1,
          volumeRatio: 1,
          zlje: 0,
          zljzb: 0,
        }))
      }
      return []
    })
    // 当前分析没有任何 jump 事件，历史帧必须独立重算
    const currentAnalysis = { meta: { code: '002279' }, jump: { event: 'none', direction: 'hold', confidence: 50, events: [] } }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    const jumpFrame = result.frames.find((frame) => frame.key === 'frame-6')
    expect(jumpFrame).toBeTruthy()
    expect(jumpFrame.analysis?.jump?.event).toBe('jump')
    expect(jumpFrame.analysis?.jump?.direction).toBe('buy')
    expect(result.frames.every((frame) => Array.isArray(frame.analysis?.jump?.events))).toBe(true)
  })
})
