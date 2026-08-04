import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { rankTrendAnalyzer } from '../../RankTrendAnalyzer'
import { apiService } from '../../apiService'
import { snapshotFacade } from '../../snapshot/facade'
import { observationProjectionCache, rankTrendObservationService } from '../RankTrendObservationService'

describe('RankTrendObservationService', () => {
  beforeEach(() => {
    observationProjectionCache.clear()
    vi.spyOn(apiService, 'analyzeRankTrend').mockResolvedValue({
      ok: true,
      frames: [],
      source: 'py_golden',
      issues: [],
    })
  })

  function mockRemoteFrames(
    frameKeys: string[],
    buildAnalysis: (frameKey: string, index: number) => any,
    frameMeta: (frameKey: string, index: number) => {
      marketMedianPercentile?: number | null
      marketMedianShortChange: number | null
      marketSampleCount: number
    } = () => ({
      marketMedianShortChange: null,
      marketSampleCount: 0,
    }),
  ) {
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: frameKeys.map((frameKey, index) => ({
        frameKey,
        regime: { state: 'normal', score: 50, reasons: [] },
        marketMedianPercentile: frameMeta(frameKey, index).marketMedianPercentile ?? null,
        marketMedianShortChange: frameMeta(frameKey, index).marketMedianShortChange,
        marketSampleCount: frameMeta(frameKey, index).marketSampleCount,
        totalCount: 200,
        stocks: [{ code: '002279', analysis: buildAnalysis(frameKey, index) }],
      })),
      source: 'py_golden',
      issues: [],
    })
  }

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
    expect(result.frames[0].analysis?.meta?.analysisSource).toBe('analysis_unavailable')
    expect(result.frames[1].analysis).toBe(currentAnalysis)
    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'history_source_unavailable',
      message: '历史快照原料读取失败: backend offline',
    }))
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'analysis_unavailable',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('builds the display rank series from rank-series snapshots when the in-memory series is missing', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue(null)
    vi.spyOn(rankTrendAnalyzer, 'getSnapshotsByType').mockResolvedValue([
      {
        date: '2026-07-28 14:30',
        timestamp: 1,
        type: 'half_hour',
        snapshot: {
          type: 'half_hour',
          tradingDate: '2026-07-28',
          slotTime: '14:30',
          totalCount: 100,
          hotlist: [{ code: '002279', rank: 28 }],
        },
      },
      {
        date: '2026-07-28 15:00',
        timestamp: 2,
        type: 'half_hour',
        snapshot: {
          type: 'half_hour',
          tradingDate: '2026-07-28',
          slotTime: '15:00',
          totalCount: 100,
          hotlist: [{ code: '002279', rank: 19 }],
        },
      },
    ])
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(rankTrendAnalyzer.getSnapshotsByType).toHaveBeenCalledWith('half_hour', {
      limit: 50,
      codes: ['002279'],
    })
    expect(result.frames).toHaveLength(2)
    expect(result.frames[0]).toMatchObject({
      key: '2026-07-28 14:30',
      percentile: 73,
    })
    expect(result.frames[1]).toMatchObject({
      key: '2026-07-28 15:00',
      percentile: 82,
    })
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
    expect(result.frames[0].analysis?.meta?.analysisSource).toBe('analysis_unavailable')
    expect(result.frames[1].analysis).toBeNull()
    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'current_analysis_unavailable',
    }))
  })

  it('keeps the current analysis frame when the in-memory rank series is unavailable', async () => {
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue(null)
    vi.spyOn(rankTrendAnalyzer, 'getSnapshotsByType').mockResolvedValue([])
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

  it('preserves rank-only resonance analysis when py golden frame is absent', async () => {
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

    expect(result.frames[0].analysis?.meta?.analysisSource).toBe('analysis_unavailable')
    expect(result.frames[0].analysis?.observation?.lifecycle).toBeUndefined()
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'analysis_unavailable',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('preserves the historical technical track from py golden when stock rows are unavailable', async () => {
    const frameKeys = Array.from({ length: 50 }, (_, index) => `frame-${index + 1}`)
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: frameKeys.map((_, index) => 80 - index),
      percentiles: frameKeys.map((_, index) => 20 + index),
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockRejectedValue(new Error('backend offline'))
    mockRemoteFrames(frameKeys.slice(-22, -1), () => ({
      meta: { code: '002279' },
      technical: { macd: { cross: 'golden' } },
      risk: { pressure: 0 },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      resonance: { status: 'ok', direction: 'buy', score: 80 },
    }))

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(result.frames).toHaveLength(22)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.technical?.macd)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.resonance)).toBe(true)
    expect(result.frames.slice(0, -1).every((frame) => frame.analysis?.risk)).toBe(true)
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
    mockRemoteFrames(frameKeys.slice(-22, -1), () => ({
      meta: { code: '002279' },
      technical: { macd: {} },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    const frame18Bars = result.frames.find((frame) => frame.key === 'frame-18')
    expect(frame18Bars).toBeTruthy()
    expect(frame18Bars.analysis?.technical).toBeTruthy()
    expect(frame18Bars.issues).toContainEqual(expect.objectContaining({
      code: 'technical_sample_insufficient',
      track: 'technical',
      message: expect.stringMatching(/样本不足/),
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
    mockRemoteFrames(frameKeys.slice(-22, -1), () => ({
      meta: { code: '002279' },
      technical: { macd: { cross: 'golden' } },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    const frame21Bars = result.frames.find((frame) => frame.key === 'frame-21')
    const frame22Bars = result.frames.find((frame) => frame.key === 'frame-22')
    expect(frame21Bars).toBeTruthy()
    expect(frame22Bars).toBeTruthy()
    expect(frame21Bars.analysis?.technical).toBeTruthy()
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

  it('历史帧市场基准来自 Python analyze 输出，不再本地横截面计算', async () => {
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
      return []
    })
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianShortChange: 0, marketSampleCount: 4 }),
    )

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(result.frames[0].marketMedianPercentile).toBeNull()
    expect(result.frames[0].marketMedianShortChange).toBe(0)
    expect(result.frames[0].marketSampleCount).toBe(4)
  })

  it('Python 未返回横截面基准时按轨道降级并给出结构化原因', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianShortChange: null, marketSampleCount: 0 }),
    )

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(result.frames[0].marketMedianShortChange).toBeNull()
    expect(result.frames[0].marketSampleCount).toBe(0)
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'market_sample_insufficient',
    }))
  })

  it('观察服务按帧请求 Python 分析，横截面基准来自响应', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianShortChange: 0, marketSampleCount: 4 }),
    )

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })

    expect(apiService.analyzeRankTrend).toHaveBeenCalledWith(expect.objectContaining({
      codes: ['002279'],
      frameKeys: ['2026-07-28 14:30'],
    }))
    expect(result.frames[0].marketMedianPercentile).toBeNull()
    expect(result.frames[0].marketMedianShortChange).toBe(0)
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
    mockRemoteFrames(frameKeys.slice(-22, -1), () => ({
      meta: { code: '002279' },
      observation: { lifecycle: { score: 80 } },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))

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

  it('历史帧市场环境与分析以 Python golden 输出为准', async () => {
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
    mockRemoteFrames(frameKeys.slice(0, -1), () => ({
      meta: { code: '002279' },
      strategy: { regime: { state: 'strong', score: 80, reasons: ['池内上涨100%'] } },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))
    const currentAnalysis = {
      meta: { code: '002279' },
      strategy: { regime: { state: 'strong', score: 90, reasons: ['强市'] } },
    }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    expect(apiService.analyzeRankTrend).toHaveBeenCalledWith(expect.objectContaining({
      codes: ['002279'],
      frameKeys: ['2026-07-28 14:30'],
    }))
    expect(result.frames[0].analysis?.strategy?.regime?.state).toBe('strong')
    expect(result.frames[0].issues.some((issue) => issue.code === 'analysis_unavailable')).toBe(false)
  })

  it('历史帧 Python 未返回结果时标记 analysis_unavailable', async () => {
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

    expect(result.frames[0].analysis?.meta?.analysisSource).toBe('analysis_unavailable')
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'analysis_unavailable',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('历史帧分析读取失败时给出服务级原因并逐帧降级', async () => {
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
    vi.mocked(apiService.analyzeRankTrend).mockRejectedValue(new Error('backend offline'))
    const currentAnalysis = {
      meta: { code: '002279' },
      strategy: { regime: { state: 'strong', score: 90, reasons: ['强市'] } },
    }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    expect(result.issues).toContainEqual(expect.objectContaining({
      code: 'historical_analysis_unavailable',
      message: '历史帧分析读取失败: backend offline',
    }))
    expect(result.frames[0].analysis?.meta?.analysisSource).toBe('analysis_unavailable')
    expect(result.frames[0].issues).toContainEqual(expect.objectContaining({
      code: 'analysis_unavailable',
      frameKey: '2026-07-28 14:30',
    }))
  })

  it('历史帧 Jump 事件来自 Python golden 输出，不依赖当前分析的近似索引', async () => {
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
    mockRemoteFrames(frameKeys.slice(-22, -1), (key) =>
      key === 'frame-6'
        ? {
            meta: { code: '002279' },
            jump: {
              event: 'jump',
              direction: 'buy',
              confidence: 80,
              events: [{ index: 5, direction: 'surge', magnitude: 20 }],
            },
          }
        : {
            meta: { code: '002279' },
            jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
          },
    )
    // 当前分析没有任何 jump 事件，历史帧 jump 必须来自 Python 输出
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

  it('当前帧市场基准回退到 Python resonance 输出', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianPercentile: 55, marketMedianShortChange: 1.5, marketSampleCount: 4 }),
    )
    const currentAnalysis = {
      meta: { code: '002279' },
      resonance: {
        status: 'ok',
        direction: 'buy',
        score: 80,
        marketMedianPercentile: 62,
        marketMedianShortChange: 7.5,
        marketSampleCount: 25,
      },
    }
    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    expect(result.frames[0].marketMedianPercentile).toBe(55)
    expect(result.frames[0].marketMedianShortChange).toBe(1.5)
    expect(result.frames[0].marketSampleCount).toBe(4)
    expect(result.frames[1].marketMedianPercentile).toBe(62)
    expect(result.frames[1].marketMedianShortChange).toBe(7.5)
    expect(result.frames[1].marketSampleCount).toBe(25)
  })

  it('历史帧技术质量以 Python sampleQuality 为准，degraded 不再标记样本不足', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(frameKeys.slice(0, -1), () => ({
      meta: {
        code: '002279',
        sampleQuality: { status: 'degraded', sampleCount: 12, requiredSampleCount: 30 },
      },
      technical: { macd: { cross: 'golden' } },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))
    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })
    const frame = result.frames[0]
    expect(frame.analysis?.technical).toBeTruthy()
    expect(frame.issues.some((issue) => issue.code === 'technical_sample_insufficient')).toBe(false)
    expect(frame.issues).toContainEqual(expect.objectContaining({
      code: 'technical_stable_window_insufficient',
      message: expect.stringMatching(/未达稳定观察窗口/),
    }))
  })

  it('历史帧 Python 标记 insufficient 时仍提示技术样本不足', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(frameKeys.slice(0, -1), () => ({
      meta: {
        code: '002279',
        sampleQuality: { status: 'insufficient', sampleCount: 3, requiredSampleCount: 30 },
      },
      technical: { macd: {} },
      jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
    }))
    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: { meta: { code: '002279' } },
    })
    const frame = result.frames[0]
    expect(frame.issues).toContainEqual(expect.objectContaining({
      code: 'technical_sample_insufficient',
      message: expect.stringMatching(/样本不足（当前 3 bar）/),
    }))
  })

  describe('观察投影缓存', () => {
    function buildStock(updateTime = 100) {
      return {
        code: '002279',
        name: '久其软件',
        rankTrend: {
          meta: { code: '002279', updateTime, analysisSource: 'py_golden' },
          resonance: {
            status: 'ok',
            direction: 'buy',
            score: 80,
            marketMedianShortChange: 1.5,
            marketSampleCount: 200,
          },
        },
      }
    }

    function mockSeries() {
      vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
        ranks: [28, 19],
        percentiles: [42, 67],
        frameKeys: ['2026-07-28 14:30', '2026-07-28 15:00'],
      })
    }

    it('同一股票重复打开命中投影缓存，不再请求后端', async () => {
      mockSeries()
      const stockRows = vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
      const analyze = vi.mocked(apiService.analyzeRankTrend)
      const stock = buildStock()

      const first = await rankTrendObservationService.load(stock)
      expect(first.source).toBe('live')
      expect(stockRows).toHaveBeenCalledTimes(1)

      const second = await rankTrendObservationService.load(stock)
      expect(second.source).toBe('cache')
      expect(stockRows).toHaveBeenCalledTimes(1)
      expect(analyze).toHaveBeenCalledTimes(1)
      expect(second.frames).toEqual(first.frames)
    })

    it('当前分析指纹变化时缓存失效并重新请求', async () => {
      mockSeries()
      const stockRows = vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])

      await rankTrendObservationService.load(buildStock(100))
      const second = await rankTrendObservationService.load(buildStock(101))

      expect(second.source).toBe('live')
      expect(stockRows).toHaveBeenCalledTimes(2)
    })

    it('TTL 过期后缓存失效并重新请求', async () => {
      vi.useFakeTimers()
      try {
        mockSeries()
        const stockRows = vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])

        await rankTrendObservationService.load(buildStock())
        vi.advanceTimersByTime(61_000)
        const second = await rankTrendObservationService.load(buildStock())

        expect(second.source).toBe('live')
        expect(stockRows).toHaveBeenCalledTimes(2)
      } finally {
        vi.useRealTimers()
      }
    })

    it('降级结果（历史帧分析失败）照常缓存并保留结构化 issues', async () => {
      mockSeries()
      vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
      const analyze = vi.mocked(apiService.analyzeRankTrend)
      analyze.mockRejectedValueOnce(new Error('backend offline'))
      const stock = buildStock()

      const first = await rankTrendObservationService.load(stock)
      expect(first.issues).toContainEqual(
        expect.objectContaining({ code: 'historical_analysis_unavailable' }),
      )
      expect(first.source).toBe('live')

      const second = await rankTrendObservationService.load(stock)
      expect(second.source).toBe('cache')
      expect(second.issues).toEqual(first.issues)
      expect(analyze).toHaveBeenCalledTimes(1)
    })
  })

  it('当前帧题材共振数据不足时按共振轨给出结构化原因', async () => {
    const frameKeys = ['2026-07-28 14:30', '2026-07-28 15:00']
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisSeries').mockReturnValue({
      ranks: [28, 19],
      percentiles: [42, 67],
      frameKeys,
    })
    vi.spyOn(rankTrendAnalyzer, 'getLatestAnalysisFrameKeys').mockReturnValue(frameKeys)
    vi.spyOn(snapshotFacade, 'listSnapshotStockRows').mockResolvedValue([])
    mockRemoteFrames(
      frameKeys.slice(0, -1),
      () => ({
        meta: { code: '002279' },
        jump: { event: 'none', direction: 'hold', confidence: 50, events: [] },
      }),
      () => ({ marketMedianShortChange: 0, marketSampleCount: 4 }),
    )
    const currentAnalysis = {
      meta: { code: '002279' },
      resonance: {
        status: 'ok',
        direction: 'buy',
        score: 70,
        label: '强',
        marketMedianShortChange: 1.5,
        marketSampleCount: 25,
        theme: { status: 'insufficient', reasons: ['theme_cross_section_insufficient'] },
      },
    }

    const result = await rankTrendObservationService.load({
      code: '002279',
      name: '久其软件',
      rankTrend: currentAnalysis as any,
    })

    const currentFrame = result.frames.at(-1)
    expect(currentFrame?.issues).toContainEqual(expect.objectContaining({
      code: 'theme_resonance_insufficient',
      track: 'resonance',
    }))
  })
})
