import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEFAULT_RANK } from '@/types/config'
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
  applyGoldenFieldsToMerged,
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
    // 平台 rank 字段不由种子透传：合并链用实时热榜数据覆盖（展示字段，非计算输入）
    expect(seed.emRank).toBe(DEFAULT_RANK)
  })

  it('golden 排名字段逐位透传：compRank/compScore/avgRankNum/platforms/质量标记，rank := compRank', () => {
    const seed = buildFrameSeedStock(
      makeRow({
        avgRankNum: 37.5,
        avgRank: '37.5',
        compScore: 88.1234,
        compRank: 3,
        platforms: 5,
        fundPenetration: 1.23,
        qualityFlags: [],
        missingFields: [],
      }),
    )

    expect(seed.avgRankNum).toBe(37.5)
    expect(seed.avgRank).toBe('37.5')
    expect(seed.compScore).toBe(88.1234)
    expect(seed.compRank).toBe(3)
    expect(seed.rank).toBe(3)
    expect(seed.platforms).toBe(5)
    expect(seed.fundPenetration).toBe(1.23)
    expect(seed.qualityFlags).toEqual([])
    expect(seed.missingFields).toEqual([])
  })

  it('avgRank 缺失时由 golden avgRankNum 格式化派生（纯展示格式化，非计算）', () => {
    const seed = buildFrameSeedStock(makeRow({ avgRankNum: 42, avgRank: undefined }))

    expect(seed.avgRankNum).toBe(42)
    expect(seed.avgRank).toBe('42.0')
  })

  it('行无 golden 字段时如实缺省：compRank undefined、compScore 保持占位 0，不伪造', () => {
    const seed = buildFrameSeedStock(
      makeRow({
        avgRankNum: undefined,
        avgRank: undefined,
        compScore: undefined,
        compRank: undefined,
        fundPenetration: undefined,
      }),
    )

    expect(seed.avgRankNum).toBe(DEFAULT_RANK)
    expect(seed.compRank).toBeUndefined()
    expect(seed.rank).toBeUndefined()
    expect(seed.compScore).toBe(0)
    // fundPenetration 保持 createEmptyMergedStock 既有占位 0 口径（非本轮伪造）
    expect(seed.fundPenetration).toBe(0)
  })

  it('缺字段/非法值回退默认：NaN 价格、空名称不产生脏数据', () => {
    const seed = buildFrameSeedStock(makeRow({ price: undefined, name: '-', volume: Number.NaN }))

    expect(seed.price).toBe(0)
    expect(seed.volume).toBe(0)
    expect(seed.name).toBe('')
    expect(seed.platformName).toBe('')
  })
})

describe('applyGoldenFieldsToMerged（C1：既有行 golden 随新帧刷新）', () => {
  it('existing 行 golden 随新帧刷新，实时字段不被帧行覆盖', () => {
    const stocks = [
      {
        code: '600000',
        name: '浦发银行',
        price: 12.5,
        compRank: 200,
        compScore: 10,
        avgRankNum: 999,
        platforms: 0,
      },
    ] as any
    const rowsByCode = new Map([
      [
        '600000',
        makeRow({ compRank: 3, compScore: 88.1234, avgRankNum: 37.5, avgRank: '37.5', platforms: 5 }),
      ],
    ])
    applyGoldenFieldsToMerged(stocks, rowsByCode)

    expect(stocks[0].compRank).toBe(3)
    expect(stocks[0].rank).toBe(3)
    expect(stocks[0].compScore).toBe(88.1234)
    expect(stocks[0].avgRankNum).toBe(37.5)
    expect(stocks[0].avgRank).toBe('37.5')
    expect(stocks[0].platforms).toBe(5)
    // 实时字段不被帧行覆盖
    expect(stocks[0].price).toBe(12.5)
    expect(stocks[0].name).toBe('浦发银行')
  })

  it('降级行（无 golden）在帧池恢复后回填，行缺字段时占位保持不伪造', () => {
    const stocks = [{ code: '600000', compRank: undefined, avgRankNum: DEFAULT_RANK }] as any
    applyGoldenFieldsToMerged(stocks, new Map([['600000', makeRow()]]))

    expect(stocks[0].compRank).toBe(1)
    expect(stocks[0].rank).toBe(1)
    // makeRow 未提供 avgRankNum：占位保持，不伪造
    expect(stocks[0].avgRankNum).toBe(DEFAULT_RANK)
  })

  it('不在帧池中的行不触碰', () => {
    const stocks = [{ code: '000001', compRank: 9 }] as any
    applyGoldenFieldsToMerged(stocks, new Map())

    expect(stocks[0].compRank).toBe(9)
  })
})

// 2026-09-21 15:00 收盘帧真实数据（GET /api/snapshots/stock-rows，仅保留契约相关字段）。
// golden 合同锁：后端字段名/语义变化（如 compRank 改名、avgRank 缺失）会让本组用例变红，
// 防止前端静默丢排名（spec §6.1 对齐验证）。
const REAL_FRAME_ROWS = [
  {
    id: 'half_hour:2026-09-21:15:00:600127',
    snapshotId: 'half_hour:2026-09-21:15:00',
    type: 'half_hour',
    tradingDate: '2026-09-21',
    slotTime: '15:00',
    code: '600127',
    name: '金健米业',
    price: 15.75,
    platforms: 8,
    avgRankNum: 12.48483166851646,
    avgRank: '12.5',
    rank: 1,
    compScore: 81.3782,
    compRank: 1,
    qualityFlags: ['missing_comprehensive_fields'],
    missingFields: ['zljzb', 'fundPenetration'],
  },
  {
    id: 'half_hour:2026-09-21:15:00:002185',
    snapshotId: 'half_hour:2026-09-21:15:00',
    type: 'half_hour',
    tradingDate: '2026-09-21',
    slotTime: '15:00',
    code: '002185',
    name: '华天科技',
    price: 18.53,
    platforms: 7,
    avgRankNum: 14.220495745467995,
    avgRank: '14.2',
    rank: 2,
    compScore: 80.0196,
    compRank: 2,
    qualityFlags: ['missing_comprehensive_fields'],
    missingFields: ['zljzb', 'fundPenetration'],
  },
  {
    id: 'half_hour:2026-09-21:15:00:000636',
    snapshotId: 'half_hour:2026-09-21:15:00',
    type: 'half_hour',
    tradingDate: '2026-09-21',
    slotTime: '15:00',
    code: '000636',
    name: '风华高科',
    price: 59.25,
    platforms: 7,
    avgRankNum: 17.059563448020715,
    avgRank: '17.1',
    rank: 3,
    compScore: 77.7974,
    compRank: 3,
    qualityFlags: ['missing_comprehensive_fields'],
    missingFields: ['zljzb', 'fundPenetration'],
  },
] as unknown as SnapshotStockRow[]

describe('真实帧 golden 对齐验证（2026-09-21 15:00 收盘帧合同锁）', () => {
  it('种子行 golden 字段与后端行逐位一致，rank := compRank', () => {
    for (const row of REAL_FRAME_ROWS) {
      const seed = buildFrameSeedStock(row)

      expect(seed.compRank).toBe(row.compRank)
      expect(seed.rank).toBe(row.compRank)
      expect(seed.compScore).toBe(row.compScore)
      expect(seed.avgRankNum).toBe(row.avgRankNum)
      expect(seed.avgRank).toBe(row.avgRank)
      expect(seed.platforms).toBe(row.platforms)
      expect(seed.qualityFlags).toEqual(row.qualityFlags)
      expect(seed.missingFields).toEqual(row.missingFields)
    }
  })

  it('既有行经刷新后与后端行逐位一致（对齐验证）', () => {
    const stocks = [{ code: '600127', compRank: 200, compScore: 10, avgRankNum: 999 }] as any
    applyGoldenFieldsToMerged(
      stocks,
      new Map(REAL_FRAME_ROWS.map((row) => [String(row.code), row])),
    )

    expect(stocks[0].compRank).toBe(1)
    expect(stocks[0].compScore).toBe(81.3782)
    expect(stocks[0].avgRankNum).toBe(12.48483166851646)
    expect(stocks[0].avgRank).toBe('12.5')
    expect(stocks[0].platforms).toBe(8)
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
