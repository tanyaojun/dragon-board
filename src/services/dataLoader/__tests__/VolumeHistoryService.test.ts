import { beforeEach, describe, expect, it, vi } from 'vitest'

import { VolumeHistoryService } from '../VolumeHistoryService'
import { snapshotFacade } from '../../snapshot/facade'

vi.mock('../../snapshot/facade', () => ({
  snapshotFacade: {
    listSnapshotStockRows: vi.fn(),
  },
}))

function stockRow(input: {
  code?: string
  tradingDate: string
  slotTime: string
  volume: number
  timestamp?: number
}) {
  return {
    id: `${input.code || '603005'}:${input.tradingDate}:${input.slotTime}`,
    snapshotId: `quarter_hour:${input.tradingDate}:${input.slotTime}`,
    type: 'quarter_hour',
    tradingDate: input.tradingDate,
    slotTime: input.slotTime,
    timestamp: input.timestamp || 1,
    captureMode: 'real_time',
    source: 'browser_runtime',
    code: input.code || '603005',
    name: '晶方科技',
    rank: 1,
    compRank: 1,
    platforms: 1,
    volume: input.volume,
  } as any
}

describe('VolumeHistoryService', () => {
  beforeEach(() => {
    vi.resetAllMocks()
  })

  it('collects intraday history by stock code in a batched query', async () => {
    vi.mocked(snapshotFacade.listSnapshotStockRows).mockResolvedValue([
      stockRow({ tradingDate: '2026-04-17', slotTime: '14:45', volume: 563113, timestamp: 3 }),
      stockRow({ tradingDate: '2026-04-14', slotTime: '14:45', volume: 604882, timestamp: 2 }),
      stockRow({ tradingDate: '2026-04-03', slotTime: '14:45', volume: 228927, timestamp: 1 }),
      stockRow({
        code: '600001',
        tradingDate: '2026-04-17',
        slotTime: '14:45',
        volume: 100,
        timestamp: 3,
      }),
      stockRow({
        code: '600001',
        tradingDate: '2026-04-14',
        slotTime: '14:45',
        volume: 90,
        timestamp: 2,
      }),
    ])
    const service = new VolumeHistoryService(['quarter_hour', 'half_hour', 'hourly'])

    const result = await service.buildIntradayVolumeHistoryMap(
      ['603005', '600001'],
      new Date('2026-05-20T14:45:00+08:00'),
    )

    expect(snapshotFacade.listSnapshotStockRows).toHaveBeenCalledTimes(1)
    expect(snapshotFacade.listSnapshotStockRows).toHaveBeenCalledWith({
      codes: ['603005', '600001'],
      types: ['quarter_hour', 'half_hour', 'hourly'],
      beforeTradingDate: '2026-05-20',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
      sort: 'desc',
      limit: 480,
    })
    expect(result.get('603005')).toEqual([563113, 604882, 228927])
    expect(result.get('600001')).toEqual([100, 90])
  })

  it('interpolates a stock-specific intraday sample when adjacent rows exist', async () => {
    vi.mocked(snapshotFacade.listSnapshotStockRows).mockResolvedValue([
      stockRow({ tradingDate: '2026-05-19', slotTime: '15:00', volume: 200, timestamp: 2 }),
      stockRow({ tradingDate: '2026-05-19', slotTime: '14:30', volume: 100, timestamp: 1 }),
    ])
    const service = new VolumeHistoryService(['quarter_hour'])

    const result = await service.buildIntradayVolumeHistoryMap(
      ['603005'],
      new Date('2026-05-20T14:45:00+08:00'),
    )

    expect(result.get('603005')).toEqual([150])
  })

  it('falls back to a single-code query when the batched result is capped before a sparse stock is filled', async () => {
    vi.mocked(snapshotFacade.listSnapshotStockRows)
      .mockResolvedValueOnce(
        [
          stockRow({
            code: '600001',
            tradingDate: '2026-04-17',
            slotTime: '14:45',
            volume: 300,
            timestamp: 500,
          }),
          stockRow({
            code: '600001',
            tradingDate: '2026-04-14',
            slotTime: '14:45',
            volume: 200,
            timestamp: 499,
          }),
          stockRow({
            code: '600001',
            tradingDate: '2026-04-03',
            slotTime: '14:45',
            volume: 100,
            timestamp: 498,
          }),
          ...Array.from({ length: 477 }, (_, index) =>
            stockRow({
              code: '603005',
              tradingDate: index % 2 === 0 ? '2026-04-17' : '2026-04-14',
              slotTime: '14:45',
              volume: 100 + index,
              timestamp: index,
            }),
          ),
        ],
      )
      .mockResolvedValueOnce([
        stockRow({ tradingDate: '2026-04-17', slotTime: '14:45', volume: 563113, timestamp: 3 }),
        stockRow({ tradingDate: '2026-04-14', slotTime: '14:45', volume: 604882, timestamp: 2 }),
        stockRow({ tradingDate: '2026-04-03', slotTime: '14:45', volume: 228927, timestamp: 1 }),
      ])
    const service = new VolumeHistoryService(['quarter_hour', 'half_hour', 'hourly'])

    const result = await service.buildIntradayVolumeHistoryMap(
      ['603005', '600001'],
      new Date('2026-05-20T14:45:00+08:00'),
    )

    expect(snapshotFacade.listSnapshotStockRows).toHaveBeenCalledTimes(2)
    expect(snapshotFacade.listSnapshotStockRows).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        code: '603005',
        limit: 240,
      }),
    )
    expect(result.get('603005')).toEqual([563113, 604882, 228927])
  })
})
