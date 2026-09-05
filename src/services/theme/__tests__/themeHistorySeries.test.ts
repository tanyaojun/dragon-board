import { describe, expect, it } from 'vitest'
import {
  fetchThemeHistorySeries,
  type ThemeHistoryFetchers,
} from '../themeHistorySeries'

// ---------- fakes ----------

function makeFetchers(overrides?: Partial<ThemeHistoryFetchers>): ThemeHistoryFetchers {
  return {
    fetchSectorRows: async () => ({ ok: true, rows: [], count: 0, source: 'mongodb' }),
    fetchVolumeSeries: async () => ({ ok: true, rows: [], count: 0, source: 'mongodb' }),
    ...overrides,
  }
}

function sectorRow(overrides: Record<string, unknown>) {
  return {
    entityType: 'hot_theme',
    entityKey: '25',
    entityName: 'AI硬件',
    type: 'half_hour',
    sort: undefined,
    ...overrides,
  }
}

// 固定"现在"：2026-09-04 15:30 (UTC+8) = timestamp 1788507000000
const NOW_MS = 1788507000000

describe('fetchThemeHistorySeries', () => {
  it('maps sector rows into history points with heat/zt/leader/change', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 2,
        source: 'mongodb',
        rows: [
          {
            tradingDate: '2026-09-04',
            slotTime: '10:30',
            timestamp: 1788498600000,
            heatScore: 419057,
            ztCount: 1,
            leaderCount: 0,
            change: -2.29,
          },
          {
            tradingDate: '2026-09-04',
            slotTime: '11:00',
            timestamp: 1788500400000,
            heatScore: 425000,
            ztCount: 2,
            leaderCount: 1,
            change: 1.5,
          },
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.ok).toBe(true)
    expect(result.points).toHaveLength(2)
    expect(result.points[0]).toMatchObject({
      timestamp: 1788498600000,
      tradingDate: '2026-09-04',
      slotTime: '10:30',
      heat: 419057,
      ztCount: 1,
      leaderCount: 0,
      avgChange: -2.29,
    })
    // volume 源无该槽位数据 → 成交量字段缺失为 null，不伪造 0
    expect(result.points[0].totalVolume).toBeNull()
    expect(result.points[0].totalAmount).toBeNull()
    expect(result.sectorRows.ok).toBe(true)
    expect(result.volumeSeries.ok).toBe(true)
  })

  it('keeps missing heat fields as null instead of faking zeros', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [
          {
            tradingDate: '2026-09-04',
            slotTime: '10:30',
            timestamp: 1788498600000,
            // heatScore/ztCount/leaderCount/change 全缺
          },
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.points[0].heat).toBeNull()
    expect(result.points[0].ztCount).toBeNull()
    expect(result.points[0].leaderCount).toBeNull()
    expect(result.points[0].avgChange).toBeNull()
  })

  it('merges volume rows into the sector timeline by timestamp', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [sectorRow({ tradingDate: '2026-09-04', slotTime: '10:30', timestamp: 1788498600000, heatScore: 100 })],
      }),
      fetchVolumeSeries: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [
          {
            tradingDate: '2026-09-04',
            slotTime: '10:30',
            timestamp: 1788498600000,
            totalVolume: 120500,
            totalAmount: 990000000,
            stockCount: 12,
            volumeCount: 12,
            amountCount: 10,
          },
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.points).toHaveLength(1)
    expect(result.points[0].totalVolume).toBe(120500)
    expect(result.points[0].totalAmount).toBe(990000000)
    expect(result.points[0].stockCount).toBe(12)
    expect(result.points[0].heat).toBe(100)
  })

  it('keeps volume-only slots as independent track with null heat fields', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 0,
        source: 'mongodb',
        rows: [],
      }),
      fetchVolumeSeries: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [
          {
            tradingDate: '2026-09-04',
            slotTime: '10:30',
            timestamp: 1788498600000,
            totalVolume: 120500,
            totalAmount: null,
            stockCount: 12,
            volumeCount: 12,
            amountCount: 0,
          },
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    // sector 源为空不清空 volume 独立轨道（fail-visible：独立轨道不被连带清空）
    expect(result.points).toHaveLength(1)
    expect(result.points[0].heat).toBeNull()
    expect(result.points[0].totalVolume).toBe(120500)
    // amountCount=0 表示组内无可加数值 → totalAmount 缺失为 null，不保留聚合伪 0
    expect(result.points[0].totalAmount).toBeNull()
  })

  it('reports sector source failure without losing volume data', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => {
        throw new Error('backend unreachable')
      },
      fetchVolumeSeries: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [
          {
            tradingDate: '2026-09-04',
            slotTime: '10:30',
            timestamp: 1788498600000,
            totalVolume: 120500,
            totalAmount: 990000000,
            stockCount: 12,
            volumeCount: 12,
            amountCount: 10,
          },
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.ok).toBe(true)
    expect(result.sectorRows.ok).toBe(false)
    expect(result.sectorRows.message).toContain('backend unreachable')
    expect(result.volumeSeries.ok).toBe(true)
    expect(result.points).toHaveLength(1)
    expect(result.points[0].totalVolume).toBe(120500)
  })

  it('reports volume source failure without losing heat series', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 1,
        source: 'mongodb',
        rows: [sectorRow({ tradingDate: '2026-09-04', slotTime: '10:30', timestamp: 1788498600000, heatScore: 100 })],
      }),
      fetchVolumeSeries: async () => {
        throw new Error('volume series 503')
      },
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.ok).toBe(true)
    expect(result.volumeSeries.ok).toBe(false)
    expect(result.volumeSeries.message).toContain('volume series 503')
    expect(result.points[0].heat).toBe(100)
    expect(result.points[0].totalVolume).toBeNull()
  })

  it('returns structured failure when both sources fail', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => {
        throw new Error('sector down')
      },
      fetchVolumeSeries: async () => {
        throw new Error('volume down')
      },
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1d', nowMs: NOW_MS },
      fetchers,
    )

    expect(result.ok).toBe(false)
    expect(result.points).toEqual([])
    expect(result.sectorRows.ok).toBe(false)
    expect(result.volumeSeries.ok).toBe(false)
    expect(result.message).toBeTruthy()
  })

  it('filters points outside the selected time window', async () => {
    const fetchers = makeFetchers({
      fetchSectorRows: async () => ({
        ok: true,
        count: 3,
        source: 'mongodb',
        rows: [
          sectorRow({ tradingDate: '2026-09-04', slotTime: '09:30', timestamp: 1788492600000 }), // 早于窗口
          sectorRow({ tradingDate: '2026-09-04', slotTime: '14:30', timestamp: 1788503400000 }), // 窗口内（1h 前）
          sectorRow({ tradingDate: '2026-09-04', slotTime: '15:00', timestamp: 1788505200000 }), // 窗口内
        ],
      }),
    })

    const result = await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1h', nowMs: NOW_MS },
      fetchers,
    )

    // 1h 窗口：cutoff = 1788503400000
    expect(result.points.map(p => p.slotTime)).toEqual(['14:30', '15:00'])
  })

  it('passes themeId/name and half_hour window params to both sources', async () => {
    let sectorParams: any = null
    let volumeParams: any = null
    const fetchers = makeFetchers({
      fetchSectorRows: async params => {
        sectorParams = params
        return { ok: true, rows: [], count: 0 }
      },
      fetchVolumeSeries: async params => {
        volumeParams = params
        return { ok: true, rows: [], count: 0 }
      },
    })

    await fetchThemeHistorySeries(
      { themeId: '25', themeName: 'AI硬件', timeRange: '1w', nowMs: NOW_MS },
      fetchers,
    )

    expect(sectorParams.entityKey).toBe('25')
    expect(sectorParams.entityType).toBe('hot_theme')
    expect(sectorParams.types).toEqual(['half_hour'])
    expect(sectorParams.sort).toBe('asc')
    // 1w cutoff = 2026-08-28
    expect(sectorParams.startDate).toBe('2026-08-28')
    expect(sectorParams.endDate).toBe('2026-09-04')

    expect(volumeParams.themeName).toBe('AI硬件')
    expect(volumeParams.types).toBe('half_hour')
    expect(volumeParams.startDate).toBe('2026-08-28')
    expect(volumeParams.endDate).toBe('2026-09-04')
  })
})
