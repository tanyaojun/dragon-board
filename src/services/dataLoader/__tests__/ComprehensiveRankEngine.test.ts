import { describe, expect, it } from 'vitest'

import {
  calculateAverageRank,
  calculateComprehensiveRanks,
  calculatePlatformTotals,
  getPlatformWeight,
  getRankField,
  rankMergedStocks,
} from '../ComprehensiveRankEngine'

describe('ComprehensiveRankEngine', () => {
  it('maps platform rank fields and platform weights', () => {
    expect(getRankField('eastmoney')).toBe('emRank')
    expect(getRankField('xueqiu')).toBe('xqRank')
    expect(getRankField('unknown')).toBeNull()

    expect(getPlatformWeight('kpl')).toBe(1)
    expect(getPlatformWeight('tdx')).toBe(0.9)
    expect(getPlatformWeight('unknown')).toBe(0.5)
  })

  it('calculates platform totals from platform data arrays', () => {
    const totals = calculatePlatformTotals({
      eastmoney: [{ code: '000001' }, { code: '000002' }],
      ths: [{ code: '000001' }],
      kpl: null,
      tdx: undefined,
    })

    expect(totals).toEqual({
      eastmoney: 2,
      ths: 1,
      kpl: 0,
      tdx: 0,
      xueqiu: 0,
      cls: 0,
      tgb: 0,
      dzh: 0,
    })
  })

  it('calculates weighted average rank with DEFAULT_RANK penalty for missing ranks', () => {
    const stock = calculateAverageRank(
      {
        emRank: 1,
        thsRank: 999,
        kplRank: 999,
        tdxRank: 999,
        xqRank: 999,
        clsRank: 999,
        tgbRank: 999,
        dzhRank: 999,
      },
      {
        eastmoney: 2,
        ths: 2,
        kpl: 0,
        tdx: 0,
        xueqiu: 0,
        cls: 0,
        tgb: 0,
        dzh: 0,
      },
    )

    expect(stock.platforms).toBe(1)
    expect(stock.avgRankNum).toBeCloseTo(
      (50 * getPlatformWeight('eastmoney') + 100 * getPlatformWeight('ths')) /
        (getPlatformWeight('eastmoney') + getPlatformWeight('ths')),
    )
    expect(stock.avgRank).toBe('76.6')
  })

  it('calculates fund penetration, compScore, and compRank by comprehensive score', () => {
    const stocks = [
      {
        code: '000001',
        avgRankNum: 80,
        zljzb: 1,
        zlje: 20,
        cirMV: 200,
        turnover: 100,
        turnoverRate: 1,
      },
      {
        code: '000002',
        avgRankNum: 20,
        zljzb: 5,
        zlje: 60,
        cirMV: 200,
        turnover: 300,
        turnoverRate: 15,
      },
    ]

    calculateComprehensiveRanks(stocks)

    expect(stocks[0].fundPenetration).toBe(10)
    expect(stocks[1].fundPenetration).toBe(30)
    expect(stocks[1].compScore).toBeGreaterThan(stocks[0].compScore)
    expect(stocks[1].compRank).toBe(1)
    expect(stocks[0].compRank).toBe(2)
  })

  it('ranks merged stocks by comprehensive score and sets display rank', () => {
    const stockMap = new Map([
      [
        '000001',
        {
          code: '000001',
          emRank: 2,
          thsRank: 999,
          kplRank: 999,
          tdxRank: 999,
          xqRank: 999,
          clsRank: 999,
          tgbRank: 999,
          dzhRank: 999,
          zljzb: 1,
          zlje: 20,
          cirMV: 200,
          turnover: 100,
          turnoverRate: 1,
        },
      ],
      [
        '000002',
        {
          code: '000002',
          emRank: 1,
          thsRank: 999,
          kplRank: 999,
          tdxRank: 999,
          xqRank: 999,
          clsRank: 999,
          tgbRank: 999,
          dzhRank: 999,
          zljzb: 5,
          zlje: 60,
          cirMV: 200,
          turnover: 300,
          turnoverRate: 15,
        },
      ],
    ])

    const ranked = rankMergedStocks(stockMap, {
      eastmoney: [{ code: '000001' }, { code: '000002' }],
    })

    expect(ranked.map((stock) => stock.code)).toEqual(['000002', '000001'])
    expect(ranked.map((stock) => stock.rank)).toEqual([1, 2])
    expect(ranked.map((stock) => stock.compRank)).toEqual([1, 2])
  })
})
