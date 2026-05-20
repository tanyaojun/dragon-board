import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../../apiService'

vi.mock('../../apiService', () => ({
  apiService: {
    listMongoSnapshotFrames: vi.fn(),
    listMongoSnapshotRecords: vi.fn(),
    getMongoSnapshotRecord: vi.fn(),
    listMongoSnapshotStockRows: vi.fn(),
    listMongoSnapshotSectorRows: vi.fn(),
  },
}))

describe('snapshotBackendRead', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('maps formal frame bundle reads to QuantBoard MongoDB frames with formal policy', async () => {
    vi.mocked(apiService.listMongoSnapshotFrames).mockResolvedValue({
      ok: true,
      frames: [
        {
          id: 'half_hour:2026-04-24:10:00',
          snapshotId: 'half_hour:2026-04-24:10:00',
          type: 'half_hour',
          tradingDate: '2026-04-24',
          slotTime: '10:00',
          timestamp: 1,
          displayKey: '[半小时] 2026-04-24 10:00',
          captureMode: 'real_time',
          source: 'browser_runtime',
          qualityFlags: [],
          delayMs: 0,
          metadata: null,
          marketStats: null,
          sentiment: null,
          moneyFlow: null,
          indices: null,
          limitSummary: null,
          rotationSummary: null,
          stockRowCount: 1,
          sectorRowCount: 0,
          rows: [{ code: '600001', name: '测试股' }],
          hotlist: [{ code: '600001', name: '测试股' }],
          sectors: [],
          hotThemes: [],
        },
      ],
    })

    const { snapshotBackendRead } = await import('../backendRead')
    const frames = await snapshotBackendRead.listSnapshotFrameBundles({
      type: 'half_hour',
      tradingDate: '2026-04-24',
      sort: 'asc',
    })

    expect(apiService.listMongoSnapshotFrames).toHaveBeenCalledWith({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      tradingDate: '2026-04-24',
      sort: 'asc',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })
    expect(frames).toHaveLength(1)
    expect(frames[0].rows[0].code).toBe('600001')
  })

  it('requests ranktrend projection for lightweight frame bundle reads', async () => {
    vi.mocked(apiService.listMongoSnapshotFrames).mockResolvedValue({
      ok: true,
      frames: [],
    })

    const { snapshotBackendRead } = await import('../backendRead')
    await snapshotBackendRead.listSnapshotFrameBundles({
      type: 'half_hour',
      sort: 'desc',
      projection: 'ranktrend',
    })

    expect(apiService.listMongoSnapshotFrames).toHaveBeenCalledWith({
      datasetId: 'dragonboard_live',
      type: 'half_hour',
      sort: 'desc',
      projection: 'ranktrend',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })
  })

  it('unwraps MongoDB stock rows for volume history consumers', async () => {
    vi.mocked(apiService.listMongoSnapshotStockRows).mockResolvedValue({
      ok: true,
      rows: [
        { code: '600001', tradingDate: '2026-04-24', timestamp: 2, volume: 300 },
        { code: '600001', tradingDate: '2026-04-23', timestamp: 1, volume: 200 },
      ],
    })

    const { snapshotBackendRead } = await import('../backendRead')
    const rows = await snapshotBackendRead.listSnapshotStockRows({
      code: '600001',
      type: 'daily',
      beforeTradingDate: '2026-04-25',
      sort: 'desc',
      limit: 3,
    })

    expect(apiService.listMongoSnapshotStockRows).toHaveBeenCalledWith({
      datasetId: 'dragonboard_live',
      code: '600001',
      type: 'daily',
      beforeTradingDate: '2026-04-25',
      sort: 'desc',
      limit: 3,
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })
    expect(rows.map((row) => row.volume)).toEqual([300, 200])
  })

  it('reads daily volume history candidates in batches before de-duplicating by stock', async () => {
    vi.mocked(apiService.listMongoSnapshotStockRows).mockResolvedValue({
      ok: true,
      rows: [
        { code: '603005', tradingDate: '2026-04-17', timestamp: 2, volume: 563113 },
        { code: '603005', tradingDate: '2026-04-17', timestamp: 1, volume: 0 },
        { code: '603005', tradingDate: '2026-04-14', timestamp: 1, volume: 604882 },
        { code: '603005', tradingDate: '2026-04-03', timestamp: 1, volume: 228927 },
        { code: '600001', tradingDate: '2026-04-17', timestamp: 2, volume: 300 },
        { code: '600001', tradingDate: '2026-04-14', timestamp: 1, volume: 200 },
      ],
    })

    const { snapshotBackendRead } = await import('../backendRead')
    const history = await snapshotBackendRead.getStockVolumeHistory(['603005', '600001'], {
      anchorTradingDate: '2026-05-20',
      lookbackDays: 3,
    })

    expect(apiService.listMongoSnapshotStockRows).toHaveBeenCalledTimes(1)
    expect(apiService.listMongoSnapshotStockRows).toHaveBeenCalledWith({
      datasetId: 'dragonboard_live',
      codes: ['603005', '600001'],
      type: 'daily',
      beforeTradingDate: '2026-05-20',
      sort: 'desc',
      limit: 24,
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })
    expect(history.get('603005')).toEqual([563113, 604882, 228927])
    expect(history.get('600001')).toEqual([300, 200])
  })

  it('falls back to a single-code daily history query when batched rows are capped', async () => {
    vi.mocked(apiService.listMongoSnapshotStockRows)
      .mockResolvedValueOnce({
        ok: true,
        rows: [
          { code: '600001', tradingDate: '2026-04-17', timestamp: 30, volume: 300 },
          { code: '600001', tradingDate: '2026-04-14', timestamp: 29, volume: 200 },
          { code: '600001', tradingDate: '2026-04-03', timestamp: 28, volume: 100 },
          ...Array.from({ length: 21 }, (_, index) => ({
            code: '603005',
            tradingDate: index % 2 === 0 ? '2026-04-17' : '2026-04-14',
            timestamp: index,
            volume: 100 + index,
          })),
        ],
      })
      .mockResolvedValueOnce({
        ok: true,
        rows: [
          { code: '603005', tradingDate: '2026-04-17', timestamp: 3, volume: 563113 },
          { code: '603005', tradingDate: '2026-04-14', timestamp: 2, volume: 604882 },
          { code: '603005', tradingDate: '2026-04-03', timestamp: 1, volume: 228927 },
        ],
      })

    const { snapshotBackendRead } = await import('../backendRead')
    const history = await snapshotBackendRead.getStockVolumeHistory(['603005', '600001'], {
      anchorTradingDate: '2026-05-20',
      lookbackDays: 3,
    })

    expect(apiService.listMongoSnapshotStockRows).toHaveBeenCalledTimes(2)
    expect(apiService.listMongoSnapshotStockRows).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        code: '603005',
        limit: 12,
      }),
    )
    expect(history.get('603005')).toEqual([563113, 604882, 228927])
  })

  it('throws when MongoDB backend returns an unsuccessful envelope', async () => {
    vi.mocked(apiService.listMongoSnapshotRecords).mockResolvedValue({
      ok: false,
      errorCode: 'snapshot_mongo_unavailable',
      message: 'primary database is unavailable',
    })

    const { snapshotBackendRead } = await import('../backendRead')

    await expect(snapshotBackendRead.listSnapshots({ type: 'half_hour' })).rejects.toThrow(
      'snapshot_mongo_unavailable:primary database is unavailable',
    )
  })

  it('passes formal policy to MongoDB record detail reads', async () => {
    vi.mocked(apiService.getMongoSnapshotRecord).mockResolvedValue({
      ok: true,
      record: { id: 'half_hour:2026-04-24:10:00', captureMode: 'real_time' },
    })

    const { snapshotBackendRead } = await import('../backendRead')
    const record = await snapshotBackendRead.getSnapshotById('half_hour:2026-04-24:10:00')

    expect(apiService.getMongoSnapshotRecord).toHaveBeenCalledWith('half_hour:2026-04-24:10:00', {
      datasetId: 'dragonboard_live',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
    })
    expect(record?.captureMode).toBe('real_time')
  })

  it('splits multi-type frame bundle reads because QuantBoard frames endpoint accepts one snapshot type', async () => {
    vi.mocked(apiService.listMongoSnapshotFrames)
      .mockResolvedValueOnce({
        ok: true,
        frames: [{ snapshotId: 'daily:2026-04-24:15:00', timestamp: 2, type: 'daily' }],
      })
      .mockResolvedValueOnce({
        ok: true,
        frames: [{ snapshotId: 'half_hour:2026-04-24:10:00', timestamp: 1, type: 'half_hour' }],
      })

    const { snapshotBackendRead } = await import('../backendRead')
    const frames = await snapshotBackendRead.listSnapshotFrameBundles({
      types: ['daily', 'half_hour'],
      sort: 'desc',
      limit: 5,
    })

    expect(apiService.listMongoSnapshotFrames).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({ type: 'daily', types: undefined, limit: 5 }),
    )
    expect(apiService.listMongoSnapshotFrames).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ type: 'half_hour', types: undefined, limit: 5 }),
    )
    expect(frames.map((frame) => frame.snapshotId)).toEqual([
      'daily:2026-04-24:15:00',
      'half_hour:2026-04-24:10:00',
    ])
  })

  it('rejects five minute frame bundle reads before calling QuantBoard frames API', async () => {
    const { snapshotBackendRead } = await import('../backendRead')

    await expect(snapshotBackendRead.listSnapshotFrameBundles({ type: 'five_minute' })).rejects.toThrow(
      'unsupported formal snapshot type: five_minute',
    )
    expect(apiService.listMongoSnapshotFrames).not.toHaveBeenCalled()
  })

  it('returns plain frame rows without bundle aggregation fields', async () => {
    vi.mocked(apiService.listMongoSnapshotFrames).mockResolvedValue({
      ok: true,
      frames: [
        {
          id: 'half_hour:2026-04-24:10:00',
          snapshotId: 'half_hour:2026-04-24:10:00',
          type: 'half_hour',
          timestamp: 1,
          rotationSummary: { mainLines: [{ name: '主线' }] },
          rows: [{ code: '600001' }],
          hotlist: [{ code: '600001' }],
          entities: [{ entityType: 'rotation_main_line', entityName: '主线' }],
          sectors: [{ name: '板块' }],
          hotThemes: [{ name: '主题' }],
        },
      ],
    })

    const { snapshotBackendRead } = await import('../backendRead')
    const [frame] = await snapshotBackendRead.listSnapshotFrames({ type: 'half_hour' })

    expect(frame).not.toHaveProperty('rows')
    expect(frame).not.toHaveProperty('hotlist')
    expect(frame).not.toHaveProperty('entities')
    expect(frame).not.toHaveProperty('sectors')
    expect(frame).not.toHaveProperty('hotThemes')
    expect(frame.rotationSummary).toEqual({})
  })
})
