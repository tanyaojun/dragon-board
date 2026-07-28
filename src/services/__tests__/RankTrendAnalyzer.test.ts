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
  },
}))

vi.mock('../snapshot/facade', () => ({
  snapshotFacade: {
    listSnapshotFrameBundles: vi.fn(),
  },
}))

describe('RankTrendAnalyzer', () => {
  afterEach(async () => {
    vi.useRealTimers()
    vi.resetAllMocks()
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    rankTrendAnalyzer.stop()
  })

  it('会把实际样本类型与质量写入 meta.sampleQuality', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const snapshots = [
      { date: '2026-04-27 09:30', timestamp: Date.parse('2026-04-27T09:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '09:30', hotlist: buildHotlist(78) } },
      { date: '2026-04-27 10:00', timestamp: Date.parse('2026-04-27T10:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:00', hotlist: buildHotlist(66) } },
      { date: '2026-04-27 10:30', timestamp: Date.parse('2026-04-27T10:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:30', hotlist: buildHotlist(58) } },
      { date: '2026-04-27 11:00', timestamp: Date.parse('2026-04-27T11:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '11:00', hotlist: buildHotlist(49) } },
      { date: '2026-04-27 13:30', timestamp: Date.parse('2026-04-27T13:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '13:30', hotlist: buildHotlist(42) } },
      { date: '2026-04-27 14:00', timestamp: Date.parse('2026-04-27T14:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '14:00', hotlist: buildHotlist(36) } },
    ]

    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
      preferredSnapshotType: 'quarter_hour',
      snapshots,
    })

    const result = results.get('600001')
    expect(result).toBeTruthy()
    expect(result?.meta.sampleQuality?.snapshotType).toBe('half_hour')
    expect(result?.meta.sampleQuality?.status).toBe('degraded')
    expect(result?.meta.sampleQuality?.coverageWarning).toContain('回退 half_hour')
    expect(result?.meta.sampleQuality?.latestTradingDate).toBe('2026-04-27')
  })

  it('当前完整排名与最新正式帧一致时不重复追加当前帧', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const currentRanks = new Map<string, number>(
      Array.from({ length: 100 }, (_, index) => [
        index === 32 ? '600001' : `CURRENT${String(index + 1).padStart(3, '0')}`,
        index + 1,
      ]),
    )
    const currentHotlist = Array.from(currentRanks, ([code, rank]) => ({ code, rank }))
    const snapshots = [
      {
        date: '2026-04-27 14:30',
        timestamp: Date.parse('2026-04-27T14:30:00'),
        snapshot: {
          type: 'half_hour',
          tradingDate: '2026-04-27',
          slotTime: '14:30',
          totalCount: 100,
          hotlist: currentHotlist.map((item) =>
            item.code === '600001' ? { ...item, rank: 40 } : item,
          ),
        },
      },
      {
        date: '2026-04-27 15:00',
        timestamp: Date.parse('2026-04-27T15:00:00'),
        snapshot: {
          type: 'half_hour',
          tradingDate: '2026-04-27',
          slotTime: '15:00',
          totalCount: 100,
          hotlist: currentHotlist,
        },
      },
    ]

    await rankTrendAnalyzer.getRankTrends(currentRanks, {
      updateSignalStore: false,
      snapshots,
    })

    expect(rankTrendAnalyzer.getLatestAnalysisSeries('600001')?.ranks).toEqual([40, 33])
    expect(rankTrendAnalyzer.getLatestAnalysisFrameKeys()).toEqual([
      '2026-04-27 14:30',
      '2026-04-27 15:00',
    ])
  })

  it('本轮快照读取为空时保留上一轮可读分析序列', async () => {
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const snapshots = [
      {
        date: '2026-04-27 14:30',
        timestamp: Date.parse('2026-04-27T14:30:00'),
        snapshot: {
          type: 'half_hour',
          tradingDate: '2026-04-27',
          slotTime: '14:30',
          hotlist: buildHotlist(40),
        },
      },
    ]
    await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
      snapshots,
    })
    const previousSeries = rankTrendAnalyzer.getLatestAnalysisSeries('600001')
    const snapshotSpy = vi
      .spyOn(rankTrendAnalyzer as any, 'loadRequiredSnapshots')
      .mockResolvedValue([])
    try {
      const result = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 32]]), {
        updateSignalStore: false,
      })

      expect(result.size).toBe(0)
      expect(rankTrendAnalyzer.getLatestAnalysisSeries('600001')).toEqual(previousSeries)
    } finally {
      snapshotSpy.mockRestore()
    }
  })

  it('实时排名历史陈旧时标记样本不足并给出时间原因', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-28T10:00:00+08:00'))
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 50,
      frames: Array.from({ length: 50 }, (_, index) => ({
        snapshotId: `half_hour:2026-07-03:${index}`,
        timestamp: Date.parse('2026-07-03T09:30:00+08:00') + index * 30 * 60 * 1000,
        type: 'half_hour' as const,
        tradingDate: '2026-07-03',
        slotTime: '15:00',
        captureMode: 'real_time' as const,
        totalCount: 100,
        ranks: { '600001': Math.max(1, 80 - index) },
      })),
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const result = (await rankTrendAnalyzer.getRankTrends(new Map([['600001', 30]]), {
      updateSignalStore: false,
    })).get('600001')

    expect(result?.meta.sampleQuality?.status).toBe('insufficient')
    expect(result?.meta.sampleQuality?.coverageWarning).toContain('历史快照陈旧')
  })

  it('单票旧窗口不会污染最近稳定市场窗口的样本质量', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-28T15:01:00+08:00'))
    const { apiService } = await import('../apiService')
    const slots = ['09:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30', '15:00']
    const tradingDates = ['2026-07-22', '2026-07-23', '2026-07-24', '2026-07-27', '2026-07-28']
    const recentBars = tradingDates.flatMap((tradingDate) =>
      slots.map((slotTime, index) => ({
        snapshotId: `half_hour:${tradingDate}:${slotTime}`,
        timestamp: Date.parse(`${tradingDate}T${slotTime}:00+08:00`),
        code: '600001',
        rank: 80 - index,
        totalCount: 100,
        tradingDate,
        slotTime,
        captureMode: 'real_time' as const,
      })),
    )
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 51,
      frames: [],
      series: {
        '600001': { code: '600001', bars: recentBars },
        '600002': {
          code: '600002',
          bars: [{
            snapshotId: 'half_hour:2026-04-21:10:30',
            timestamp: Date.parse('2026-04-21T10:30:00+08:00'),
            code: '600002',
            rank: 10,
            totalCount: 100,
            tradingDate: '2026-04-21',
            slotTime: '10:30',
            captureMode: 'real_time' as const,
          }],
        },
      },
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const result = (await rankTrendAnalyzer.getRankTrends(
      new Map([['600001', 30], ['600002', 20]]),
      { updateSignalStore: false },
    )).get('600001')

    expect(result?.meta.sampleQuality?.status).toBe('ok')
    expect(result?.meta.sampleQuality?.coverageWarning ?? '').not.toContain('时间断层')
  })

  it('个股未上榜中间市场帧时保留离散排名，并报告降级样本', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-28T15:01:00+08:00'))
    const { apiService } = await import('../apiService')
    const slots = ['09:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30', '15:00']
    const frames = slots.map((slotTime, index) => ({
      snapshotId: `half_hour:2026-07-28:${slotTime}`,
      timestamp: Date.parse(`2026-07-28T${slotTime}:00+08:00`),
      type: 'half_hour' as const,
      tradingDate: '2026-07-28',
      slotTime,
      captureMode: 'real_time' as const,
      totalCount: 100,
      ranks: { '600002': index + 1 },
    }))
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: frames.length,
      frames,
      series: {
        '600001': {
          code: '600001',
          snapshotType: 'half_hour',
          bars: frames
            .filter((_, index) => index !== 4)
            .map((frame, index) => ({
              code: '600001',
              rank: 60 - index,
              snapshotId: frame.snapshotId,
              timestamp: frame.timestamp,
              tradingDate: frame.tradingDate,
              slotTime: frame.slotTime,
              captureMode: frame.captureMode,
              totalCount: frame.totalCount,
            })),
        },
        '600002': {
          code: '600002',
          snapshotType: 'half_hour',
          bars: frames.map((frame, index) => ({
            code: '600002',
            rank: index + 1,
            snapshotId: frame.snapshotId,
            timestamp: frame.timestamp,
            tradingDate: frame.tradingDate,
            slotTime: frame.slotTime,
            captureMode: frame.captureMode,
            totalCount: frame.totalCount,
          })),
        },
      },
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const result = (await rankTrendAnalyzer.getRankTrends(
      new Map([['600001', 30], ['600002', 20]]),
      { updateSignalStore: false },
    )).get('600001')

    expect(result?.meta.sampleQuality?.status).toBe('degraded')
    expect(result?.meta.sampleQuality?.timelineValid).toBe(true)
    expect(result?.meta.sampleQuality?.coverageWarning).toContain('个股有效样本不足')
  })

  it('实时正式时间轴缺失盘中槽位时标记样本不足', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-28T15:01:00+08:00'))
    const { apiService } = await import('../apiService')
    const slots = ['09:30', '10:00', '10:30', '11:00', '13:00', '13:30', '14:00', '14:30', '15:00']
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: slots.length,
      frames: slots.map((slotTime, index) => ({
        snapshotId: `half_hour:2026-07-28:${slotTime}`,
        timestamp: Date.parse(`2026-07-28T${slotTime}:00+08:00`),
        type: 'half_hour' as const,
        tradingDate: '2026-07-28',
        slotTime,
        captureMode: 'real_time' as const,
        totalCount: 100,
        ranks: { '600001': 60 - index },
      })),
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const result = (await rankTrendAnalyzer.getRankTrends(new Map([['600001', 30]]), {
      updateSignalStore: false,
    })).get('600001')

    expect(result?.meta.sampleQuality?.status).toBe('insufficient')
    expect(result?.meta.sampleQuality?.coverageWarning).toContain('历史快照存在缺失槽位')
  })

  it('per-code 历史并集含旧断层时仍使用最新连续市场窗口', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-28T15:01:00+08:00'))
    const { apiService } = await import('../apiService')
    const recentSlots = ['09:30', '10:00', '10:30', '11:00', '11:30', '13:00', '13:30', '14:00', '14:30']
    const bars = [
      {
        code: '600001',
        rank: 80,
        snapshotId: 'half_hour:2026-07-03:15:00',
        timestamp: Date.parse('2026-07-03T15:00:00+08:00'),
        tradingDate: '2026-07-03',
        slotTime: '15:00',
        captureMode: 'real_time' as const,
        totalCount: 100,
      },
      ...recentSlots.map((slotTime, index) => ({
        code: '600001',
        rank: 70 - index,
        snapshotId: `half_hour:2026-07-28:${slotTime}`,
        timestamp: Date.parse(`2026-07-28T${slotTime}:00+08:00`),
        tradingDate: '2026-07-28',
        slotTime,
        captureMode: 'real_time' as const,
        totalCount: 100,
      })),
    ]
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: bars.length,
      frames: [],
      marketFrames: recentSlots.map((slotTime) => ({
        snapshotId: `half_hour:2026-07-28:${slotTime}`,
        timestamp: Date.parse(`2026-07-28T${slotTime}:00+08:00`),
        type: 'half_hour' as const,
        tradingDate: '2026-07-28',
        slotTime,
        captureMode: 'real_time' as const,
        totalCount: 100,
        ranks: {},
      })),
      series: {
        '600001': { code: '600001', bars },
      },
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const result = (await rankTrendAnalyzer.getRankTrends(new Map([['600001', 60]]), {
      updateSignalStore: false,
    })).get('600001')

    expect(result?.meta.sampleQuality?.status).toBe('degraded')
    expect(result?.meta.sampleQuality?.timelineValid).toBe(true)
  })

  it('读取 RankTrend 专用排名时序而不是完整快照帧', async () => {
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
          ranks: {
            '600001': Math.max(1, 80 - index),
          },
        }
      }),
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
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
    expect(results.get('600001')?.change).toBeTypeOf('number')
    expect(results.get('600001')?.confidence).toBeTypeOf('number')
  })

  it('首选快照样本不足时并发读取备用 RankTrend 时序', async () => {
    const { apiService } = await import('../apiService')
    const requestedTypes: string[] = []
    const pendingFallbackTypes = new Set<string>()
    const releaseFallbacks: Array<() => void> = []
    vi.mocked(apiService.getRankTrendRankSeries).mockImplementation(async (params: any) => {
      const type = String(params.type)
      requestedTypes.push(type)
      if (type === 'half_hour') {
        return {
          ok: true,
          datasetId: 'dragonboard_live',
          snapshotType: type,
          source: 'mongodb',
          count: 0,
          frames: [],
        }
      }
      pendingFallbackTypes.add(type)
      await new Promise<void>((resolve) => {
        releaseFallbacks.push(resolve)
      })
      return {
        ok: true,
        datasetId: 'dragonboard_live',
        snapshotType: type,
        source: 'mongodb',
        count: 0,
        frames: [],
      }
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const promise = rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
    })

    await vi.waitFor(() => {
      expect(pendingFallbackTypes).toEqual(new Set(['quarter_hour', 'hourly', 'daily']))
      expect(requestedTypes).toEqual(['half_hour', 'quarter_hour', 'hourly', 'daily'])
    })

    releaseFallbacks.forEach((release) => release())
    await promise
  })

  it('rank-series 过滤 codes 后仍使用 totalCount 计算上一期百分位', async () => {
    const { apiService } = await import('../apiService')
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 50,
      frames: Array.from({ length: 50 }, (_, index) => {
        const rank = index === 49 ? 90 : Math.max(1, 100 - index)
        return {
          snapshotId: `half_hour:2026-04-27:${String(index).padStart(2, '0')}`,
          displayKey: `[半小时快照] 2026-04-27 ${index}`,
          timestamp: Date.parse('2026-04-27T09:30:00') + index * 30 * 60 * 1000,
          type: 'half_hour',
          tradingDate: '2026-04-27',
          slotTime: '09:30',
          captureMode: 'real_time',
          totalCount: 100,
          ranks: {
            '600001': rank,
          },
        }
      }),
      series: {
        '600001': {
          code: '600001',
          bars: Array.from({ length: 50 }, (_, index) => ({
            snapshotId: `half_hour:2026-04-27:${String(index).padStart(2, '0')}`,
            timestamp: Date.parse('2026-04-27T09:30:00') + index * 30 * 60 * 1000,
            code: '600001',
            rank: index === 49 ? 90 : Math.max(1, 100 - index),
            tradingDate: '2026-04-27',
            slotTime: '09:30',
          })),
          totalCount: 50,
          latestSnapshotId: 'half_hour:2026-04-27:49',
          latestTradingDate: '2026-04-27',
          latestSlotTime: '09:30',
        },
      },
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const rankMap = new Map<string, number>(
      Array.from({ length: 100 }, (_, index) => [
        index === 21 ? '600001' : `FILL${String(index + 1).padStart(3, '0')}`,
        index + 1,
      ]),
    )
    const results = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
    })

    expect(results.get('600001')?.change).toBeCloseTo(68, 6)
  })

  it('可疑封顶量比不推高 RankTrend 风险背离分', async () => {
    Object.assign(mockStocks[0], {
      volumeRatio: 99.99,
      volumeRatioMeta: {
        status: 'suspicious',
        source: 'intraday_snapshot',
        calculatedAt: Date.now(),
        currentVolume: 100000,
        capped: true,
        reason: 'ratio_capped',
      },
      zlje: -10_000_000,
      zljzb: -3,
    })
    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const snapshots = [
      { date: '2026-04-27 09:30', timestamp: Date.parse('2026-04-27T09:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '09:30', hotlist: buildHotlist(78) } },
      { date: '2026-04-27 10:00', timestamp: Date.parse('2026-04-27T10:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:00', hotlist: buildHotlist(70) } },
      { date: '2026-04-27 10:30', timestamp: Date.parse('2026-04-27T10:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '10:30', hotlist: buildHotlist(62) } },
      { date: '2026-04-27 11:00', timestamp: Date.parse('2026-04-27T11:00:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '11:00', hotlist: buildHotlist(54) } },
      { date: '2026-04-27 13:30', timestamp: Date.parse('2026-04-27T13:30:00'), snapshot: { type: 'half_hour', tradingDate: '2026-04-27', slotTime: '13:30', hotlist: buildHotlist(46) } },
    ]
    const rankMap = new Map<string, number>(
      Array.from({ length: 100 }, (_, index) => [
        index === 20 ? '600001' : `FILL${String(index + 1).padStart(3, '0')}`,
        index + 1,
      ]),
    )

    const suspiciousResults = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
      snapshots,
    })
    Object.assign(mockStocks[0].volumeRatioMeta, {
      status: 'fresh',
      reason: undefined,
    })
    const trustedResults = await rankTrendAnalyzer.getRankTrends(rankMap, {
      updateSignalStore: false,
      snapshots,
    })

    expect(suspiciousResults.get('600001')?.risk.divergence.score).toBeLessThan(
      trustedResults.get('600001')?.risk.divergence.score || 0,
    )
  })

  it('uses per-code series bars for rank history when series is available instead of scanning frames', async () => {
    const { apiService } = await import('../apiService')
    // Build per-code series with 30 bars for 600001
    const seriesBars = Array.from({ length: 30 }, (_, i) => ({
      snapshotId: `half_hour:2026-04-27:${String(i).padStart(2, '0')}`,
      timestamp: Date.parse('2026-04-27T09:30:00') + i * 30 * 60 * 1000,
      code: '600001',
      rank: 80 - i,
      totalCount: 200,
      tradingDate: '2026-04-27',
      slotTime: `09:${String(i).padStart(2, '0')}`,
    }))
    const seriesData = {
      '600001': {
        code: '600001',
        bars: seriesBars,
        totalCount: 30,
        latestSnapshotId: 'half_hour:2026-04-27:29',
        latestTradingDate: '2026-04-27',
        latestSlotTime: '09:29',
      },
    }
    // Frames: 600001 only appears in the last 3 frames
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 50,
      frames: Array.from({ length: 50 }, (_, index) => ({
        snapshotId: `half_hour:2026-04-27:${String(index).padStart(2, '0')}`,
        displayKey: `[半小时快照] 2026-04-27 ${index}`,
        timestamp: Date.parse('2026-04-27T09:30:00') + index * 30 * 60 * 1000,
        type: 'half_hour',
        tradingDate: '2026-04-27',
        slotTime: '09:30',
        captureMode: 'real_time',
        totalCount: 100,
        ranks: {
          ...(index >= 47 ? { '600001': 80 - (30 - (index - 47 + 1)) } : {}),
          ...Object.fromEntries(
            Array.from({ length: 99 }, (_, j) => [`FILL${String(j + 1).padStart(3, '0')}`, j + 1]),
          ),
        },
      })),
      series: seriesData,
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const results = await rankTrendAnalyzer.getRankTrends(new Map([['600001', 33]]), {
      updateSignalStore: false,
    })

    const result = results.get('600001')
    expect(result).toBeTruthy()
    // With 30 bars from series, should produce technical signals
    // (frame scanning would only give 3 data points, which is below min samples)
    expect(result?.technical).toBeTruthy()
    expect(result?.meta.sampleQuality?.status).not.toBe('min_samples_not_met')
  })

  it('keeps each code window when another code has newer rank-series bars', async () => {
    const { apiService } = await import('../apiService')
    const earlyBars = Array.from({ length: 30 }, (_, index) => ({
      snapshotId: `half_hour:600601:${String(index).padStart(2, '0')}`,
      timestamp: Date.parse('2026-04-27T09:30:00') + index * 30 * 60 * 1000,
      code: '600601',
      rank: 90 - index,
      totalCount: 304,
      tradingDate: '2026-04-27',
      slotTime: `09:${String(index).padStart(2, '0')}`,
    }))
    const newerBars = Array.from({ length: 50 }, (_, index) => ({
      snapshotId: `half_hour:600001:${String(index).padStart(2, '0')}`,
      timestamp: Date.parse('2026-04-28T09:30:00') + index * 30 * 60 * 1000,
      code: '600001',
      rank: 80 - index,
      totalCount: 304,
      tradingDate: '2026-04-28',
      slotTime: `09:${String(index).padStart(2, '0')}`,
    }))
    vi.mocked(apiService.getRankTrendRankSeries).mockResolvedValue({
      ok: true,
      datasetId: 'dragonboard_live',
      snapshotType: 'half_hour',
      source: 'mongodb',
      count: 50,
      frames: [],
      series: {
        '600601': {
          code: '600601',
          bars: earlyBars,
          totalCount: 189,
          latestSnapshotId: 'half_hour:600601:29',
          latestTradingDate: '2026-04-27',
          latestSlotTime: '09:29',
        },
        '600001': {
          code: '600001',
          bars: newerBars,
          totalCount: 50,
          latestSnapshotId: 'half_hour:600001:49',
          latestTradingDate: '2026-04-28',
          latestSlotTime: '09:49',
        },
      },
    })

    const { rankTrendAnalyzer } = await import('../RankTrendAnalyzer')
    const results = await rankTrendAnalyzer.getRankTrends(
      new Map([
        ['600601', 45],
        ['600001', 33],
      ]),
      { updateSignalStore: false },
    )

    expect(results.get('600601')?.meta.sampleQuality?.sampleCount).toBeGreaterThanOrEqual(30)
    expect(results.get('600601')?.technical.macd.dif).not.toBe(0)
  })
})
