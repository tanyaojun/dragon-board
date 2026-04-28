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

describe('RankTrendAnalyzer', () => {
  afterEach(async () => {
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
})
