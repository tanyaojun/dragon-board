import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { SnapshotStockRow } from '../../snapshot/types'

const listSnapshotFrames = vi.fn()
const listSnapshotStockRows = vi.fn()

vi.mock('../../snapshot/backendRead', () => ({
  snapshotBackendRead: {
    listSnapshotFrames: (...args: unknown[]) => listSnapshotFrames(...args),
    listSnapshotStockRows: (...args: unknown[]) => listSnapshotStockRows(...args),
  },
}))

import {
  buildFrameSeedStock,
  fetchLatestFramePool,
  filterPlatformDataToCodes,
} from '../framePoolSource'

function makeRow(overrides: Partial<SnapshotStockRow> = {}): SnapshotStockRow {
  return {
    id: 'half_hour:2026-09-21:10:30:600000',
    snapshotId: 'half_hour:2026-09-21:10:30',
    type: 'half_hour',
    tradingDate: '2026-09-21',
    slotTime: '10:30',
    timestamp: 1758426600000,
    captureMode: 'real_time',
    source: 'quantboard_collector',
    code: '600000',
    name: '浦发银行',
    rank: 1,
    compRank: 1,
    platforms: 5,
    price: 12.34,
    change: 2.1,
    volume: 123456,
    turnoverRate: 3.2,
    ...overrides,
  } as SnapshotStockRow
}

describe('fetchLatestFramePool', () => {
  beforeEach(() => {
    listSnapshotFrames.mockReset()
    listSnapshotStockRows.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('正常路径：先取最新帧，再按 slotTime 取全量行', async () => {
    listSnapshotFrames.mockResolvedValue([
      { slotTime: '10:30', tradingDate: '2026-09-21', stockRowCount: 2 },
    ])
    listSnapshotStockRows.mockResolvedValue([makeRow(), makeRow({ code: '000001', name: '平安银行' })])

    const result = await fetchLatestFramePool()

    expect(listSnapshotFrames).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'half_hour', sort: 'desc', limit: 1 }),
    )
    expect(listSnapshotStockRows).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'half_hour', slotTime: '10:30', limit: 500 }),
    )
    expect(result.pool).not.toBeNull()
    expect(result.pool!.slotTime).toBe('10:30')
    expect(result.pool!.codes).toEqual(new Set(['600000', '000001']))
    expect(result.pool!.rowsByCode.get('600000')?.name).toBe('浦发银行')
  })

  it('当日无帧：返回结构化 no-frame，不抛异常', async () => {
    listSnapshotFrames.mockResolvedValue([])

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('no-frame')
    expect(listSnapshotStockRows).not.toHaveBeenCalled()
  })

  it('股票行为空：返回结构化 empty-rows', async () => {
    listSnapshotFrames.mockResolvedValue([{ slotTime: '10:30', tradingDate: '2026-09-21' }])
    listSnapshotStockRows.mockResolvedValue([])

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('empty-rows')
  })

  it('HTTP 失败：返回结构化 http-error 且带 message', async () => {
    listSnapshotFrames.mockRejectedValue(new Error('snapshot_backend_read_failed'))

    const result = await fetchLatestFramePool()

    expect(result.pool).toBeNull()
    expect(result.reason).toBe('http-error')
    expect(result.message).toContain('snapshot_backend_read_failed')
  })

  it('显式 tradingDate 透传（跨交易日场景由调用方决定日期）', async () => {
    listSnapshotFrames.mockResolvedValue([{ slotTime: '15:00', tradingDate: '2026-09-19' }])
    listSnapshotStockRows.mockResolvedValue([makeRow()])

    const result = await fetchLatestFramePool({ tradingDate: '2026-09-19' })

    expect(listSnapshotFrames).toHaveBeenCalledWith(
      expect.objectContaining({ tradingDate: '2026-09-19' }),
    )
    expect(result.pool!.tradingDate).toBe('2026-09-19')
  })
})

describe('buildFrameSeedStock', () => {
  it('帧行字段映射：名称/价格等为兜底值，平台排名保持 DEFAULT_RANK 占位', () => {
    const seed = buildFrameSeedStock(makeRow())

    expect(seed.code).toBe('600000')
    expect(seed.name).toBe('浦发银行')
    expect(seed.platformName).toBe('浦发银行')
    expect(seed.price).toBe(12.34)
    expect(seed.change).toBe(2.1)
    expect(seed.volume).toBe(123456)
    expect(seed.turnoverRate).toBe(3.2)
    // 排名字段仅占位：合并链由 ComprehensiveRankEngine 统一重算
    expect(seed.emRank).toBeDefined()
    expect(seed.platforms).toBe(0)
  })

  it('缺字段/非法值回退默认：NaN 价格、空名称不产生脏数据', () => {
    const seed = buildFrameSeedStock(makeRow({ price: undefined, name: '-', volume: Number.NaN }))

    expect(seed.price).toBe(0)
    expect(seed.volume).toBe(0)
    expect(seed.name).toBe('')
    expect(seed.platformName).toBe('')
  })
})

describe('filterPlatformDataToCodes', () => {
  it('只保留帧池 codes 内的行，空平台不保留键', () => {
    const platformData = {
      eastmoney: [
        { code: '600000', rank: 1 },
        { code: '999999', rank: 2 },
      ],
      ths: [{ code: '999999', rank: 1 }],
      kpl: [],
    }
    const filtered = filterPlatformDataToCodes(platformData, new Set(['600000']))

    expect(filtered.eastmoney).toEqual([{ code: '600000', rank: 1 }])
    expect(filtered.ths).toBeUndefined()
    expect(filtered.kpl).toBeUndefined()
  })

  it('非数组值原样透传，防御脏 platformData', () => {
    const platformData = { eastmoney: null } as any
    expect(filterPlatformDataToCodes(platformData, new Set(['600000']))).toEqual({ eastmoney: null })
  })
})
