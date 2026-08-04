import { afterEach, describe, expect, it, vi } from 'vitest'

function buildHotlist(rank: number, total = 100) {
  const rows = Array.from({ length: total }, (_, index) => ({
    code: `FILL${String(index + 1).padStart(3, '0')}`,
    name: `填充${index + 1}`,
    rank: index + 1,
    price: 10 + index,
  }))

  rows[rank - 1] = {
    code: '600001',
    name: '测试样本',
    rank,
    price: 12.3,
    change: 2.4,
    turnover: 8.6e8,
    turnoverRate: 4.2,
    volumeRatio: 1.8,
    zlje: 1.2e7,
    zljzb: 3.1,
    cddje: 0,
    cddjzb: 0,
    pe: 24,
    pb: 2.1,
  }

  return rows
}

const mockStocks = [
  {
    code: '600001',
    name: '测试样本',
    change: 2.4,
    turnover: 8.6e8,
    turnoverRate: 4.2,
    volumeRatio: 1.8,
    zlje: 1.2e7,
    zljzb: 3.1,
    cddje: 0,
    cddjzb: 0,
    price: 12.3,
    platforms: 4,
    avgRankNum: 12,
    compRank: 15,
  },
]

vi.mock('../DataLayer', () => ({
  dataLayer: {
    getStocks: () => mockStocks,
    getStock: (code: string) => mockStocks.find((stock) => stock.code === code) || null,
    getBreathData: () => ({
      overall: 58,
      marketData: { ztCount: 52, dtCount: 3, upCount: 3100, downCount: 1800, totalAmo: 1.1e12 },
      passRate: { to2: 42 },
      timestamp: 1,
    }),
  },
}))

vi.mock('../dataLoader', () => ({
  dataLoader: {
    updateStockSignals: vi.fn(),
  },
}))

vi.mock('../apiService', () => ({
  apiService: {
    getRankTrendRankSeries: vi.fn(),
    analyzeRankTrend: vi.fn(),
  },
}))

vi.mock('../snapshot/facade', () => ({
  snapshotFacade: {
    listSnapshotFrameBundles: vi.fn(),
  },
}))

function buildAnalyzeFrame(frameKey: string, entries: Array<[string, Record<string, unknown>]>) {
  return {
    frameKey,
    regime: { state: 'normal', score: 50, reasons: [] },
    totalCount: 100,
    stocks: entries.map(([code, analysis]) => ({ code, analysis })),
  }
}

function baseAnalysis(code: string, rank: number, percentile: number) {
  return {
    meta: {
      code,
      currentRank: rank,
      currentPercentile: percentile,
      change: 1,
      rawChange: 2,
      updateTime: 1,
    },
    technical: {},
    cycle: {},
    risk: {},
    decision: {},
    strategy: { candidateTier: 'A_MAIN', regime: { state: 'normal', score: 50 } },
    executionStrategy: { candidateTier: 'A_MAIN', hotlist: { state: 'missing' } },
  }
}

describe('RankTrendAnalyzer', () => {
  afterEach(async () => {
    vi.useRealTimers()
    vi.resetAllMocks()
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    rankTrendAnalyzer.stop()
    const { resetAnalyzeCoalescer } = await import('../rankTrend/analyzeCoalescer')
    resetAnalyzeCoalescer()
  })

  it('默认路径消费 Python golden 结果并标记分析来源', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: [buildAnalyzeFrame('2026-04-27 current:1', [['600001', baseAnalysis('600001', 33, 68)]])],
      source: 'py_golden',
      issues: [],
    })

    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
      preferredSnapshotType: 'quarter_hour',
    })

    const result = results.get('600001')
    expect(result).toBeTruthy()
    expect(result?.meta.analysisSource).toBe('py_golden')
    expect(result?.strategy?.candidateTier).toBe('A_MAIN')
    expect(apiService.getRankTrendRankSeries).not.toHaveBeenCalled()
  })

  it('全量路径把全部 codes 与当前帧发给 Python，不再读取 rank-series 原料', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: [
        buildAnalyzeFrame('2026-08-02 current:1', [
          ['600001', baseAnalysis('600001', 33, 68)],
          ['600002', baseAnalysis('600002', 44, 57)],
        ]),
      ],
      source: 'py_golden',
      issues: [],
    })

    const results = await rankTrendAnalyzer.getRankTrends(
      new Map([
        ['600001', 33],
        ['600002', 44],
      ]),
      { updateSignalStore: false },
    )

    expect(apiService.getRankTrendRankSeries).not.toHaveBeenCalled()
    expect(apiService.analyzeRankTrend).toHaveBeenCalledWith(
      expect.objectContaining({
        codes: ['600001', '600002'],
        currentFrame: expect.objectContaining({ stocks: expect.any(Array) }),
      }),
      { bypassQueue: true },
    )
    expect(results.size).toBe(2)
    expect(results.get('600001')?.meta.analysisSource).toBe('py_golden')
    expect(results.get('600002')?.strategy?.candidateTier).toBe('A_MAIN')
  })

  it('当前帧题材字段规范化为名称列表，供题材共振匹配', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    mockStocks[0] = {
      ...mockStocks[0],
      themes: [
        { id: '370', name: '谷歌概念', role: 'follower' },
        { id: '361', name: 'AMD概念' },
      ],
      mainTheme: '谷歌概念',
      themeRole: 'follower',
      themeContribution: 6.9,
    }
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: [buildAnalyzeFrame('2026-08-04 current:1', [['600001', baseAnalysis('600001', 33, 68)]])],
      source: 'py_golden',
      issues: [],
    })

    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
    })

    expect(apiService.analyzeRankTrend).toHaveBeenCalledWith(
      expect.objectContaining({
        currentFrame: expect.objectContaining({
          stocks: [
            expect.objectContaining({
              themes: ['谷歌概念', 'AMD概念'],
              mainTheme: '谷歌概念',
              themeRole: 'follower',
              themeContribution: 6.9,
            }),
          ],
        }),
      }),
      expect.anything(),
    )
    expect(results.size).toBe(1)
  })

  it('remoteCodes 收窄时只请求指定股票，面板可按需分析', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: [buildAnalyzeFrame('2026-08-02 current:1', [['600001', baseAnalysis('600001', 33, 68)]])],
      source: 'py_golden',
      issues: [],
    })

    const results = await rankTrendAnalyzer.getRankTrends(
      new Map([
        ['600001', 33],
        ['600002', 44],
      ]),
      { updateSignalStore: false, remoteCodes: ['600001'] },
    )

    expect(apiService.analyzeRankTrend).toHaveBeenCalledWith(
      expect.objectContaining({ codes: ['600001'] }),
      { bypassQueue: true },
    )
    expect(results.size).toBe(1)
  })

  it('远程分析失败时返回空结果，由面板回退到 DataLayer 现有分析', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.analyzeRankTrend).mockRejectedValue(new Error('backend offline'))

    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
      remoteCodes: ['600001'],
    })

    expect(results.size).toBe(0)
  })

  it('从 Python 帧构建最新分析序列供观察面板消费', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.analyzeRankTrend).mockResolvedValue({
      ok: true,
      frames: [
        buildAnalyzeFrame('2026-04-27 10:00', [['600001', baseAnalysis('600001', 40, 60)]]),
        buildAnalyzeFrame('2026-04-27 current:1', [['600001', baseAnalysis('600001', 33, 68)]]),
      ],
      source: 'py_golden',
      issues: [],
    })

    await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), { updateSignalStore: false })

    expect(rankTrendAnalyzer.getLatestAnalysisSeries('600001')).toEqual({
      ranks: [40, 33],
      percentiles: [60, 68],
      frameKeys: ['2026-04-27 10:00', '2026-04-27 current:1'],
    })
    expect(rankTrendAnalyzer.getLatestAnalysisFrameKeys()).toEqual([
      '2026-04-27 10:00',
      '2026-04-27 current:1',
    ])
  })

  it('getSnapshotsByType 读取 RankTrend 专用排名时序而不是完整快照帧', async () => {
    const { apiService } = await import('../apiService')
    const { snapshotFacade } = await import('../snapshot/facade')
    vi.mocked(snapshotFacade.listSnapshotFrameBundles).mockRejectedValue(
      new Error('RankTrend should not read snapshot frame bundles'),
    )
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 50,
      frames: Array.from({ length: 50 }, (_, index) => {
        const timestamp = Date.parse('2026-04-27T09:30:00') + index * 30 * 60 * 1000
        return {
          snapshotId: `half_hour:2026-04-27:${index}`,
          displayKey: `[半小时快照] 2026-04-27 ${index}`,
          timestamp,
          type: 'half_hour',
          tradingDate: '2026-04-27',
          slotTime: '09:30',
          captureMode: 'real_time',
          totalCount: 100,
          ranks: { '600001': Math.max(1, 80 - index) },
        }
      }),
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const snapshots = await rankTrendAnalyzer.getSnapshotsByType('half_hour', {
      limit: 50,
      codes: ['600001'],
    })

    expect(apiService.getRankTrendRankSeries).toHaveBeenCalledWith({
      type: 'half_hour',
      startDate: undefined,
      endDate: undefined,
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
      rankBasis: 'attention',
      sort: 'desc',
      limit: 50,
      windowBars: 50,
      codes: ['600001'],
    })
    expect(snapshotFacade.listSnapshotFrameBundles).not.toHaveBeenCalled()
    expect(snapshots.length).toBe(50)
  })
})
