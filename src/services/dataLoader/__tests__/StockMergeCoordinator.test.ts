import { describe, expect, it } from 'vitest'

import { StockMergeCoordinator } from '../StockMergeCoordinator'

describe('StockMergeCoordinator', () => {
  it('does not calculate volume ratio during stock merge', async () => {
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            volume: 120000,
            turnover: 1000000,
            turnoverRate: 3,
          },
        ],
      ]),
      volumeHistoryMap: new Map([['000001', [100000, 110000, 90000]]]),
      intradayVolumeHistoryMap: new Map([['000001', [60000, 65000, 55000]]]),
      existingMap: new Map(),
    })

    expect(stock.volume).toBe(120000)
    expect(stock.volumeRatio).toBeUndefined()
    expect(stock.volumeRatioMeta).toBeUndefined()
  })

  it('keeps quote-provided volume ratio during stock merge', async () => {
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            volume: 120000,
            volumeRatio: 1.88,
          },
        ],
      ]),
      volumeHistoryMap: new Map(),
      intradayVolumeHistoryMap: new Map(),
      existingMap: new Map(),
    })

    expect(stock).toMatchObject({
      volume: 120000,
      volumeRatio: 1.88,
      volumeRatioMeta: expect.objectContaining({
        status: 'fresh',
        source: 'daily_snapshot',
        reason: 'quote_feed',
      }),
    })
  })

  it('keeps golden volume ratio and does not override with quote fallback', async () => {
    // golden 3 日量比已存在（existingMap 保留）时，腾讯 quote 只应兜底缺失，不覆盖已有值（口径一致）
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            volume: 120000,
            volumeRatio: 1.88,
          },
        ],
      ]),
      volumeHistoryMap: new Map(),
      intradayVolumeHistoryMap: new Map(),
      existingMap: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            volumeRatio: 2.45,
            volumeRatioMeta: { status: 'fresh', source: 'daily_snapshot' },
          },
        ],
      ]),
    })

    expect(stock.volumeRatio).toBe(2.45)
    expect(stock.volumeRatioMeta?.reason).not.toBe('quote_feed')
  })

  it('lets explicit zero money-flow fields clear existing values', async () => {
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map([
        [
          '000001',
          {
            code: '000001',
            zlje: 500,
            zljzb: 5,
            cddje: 0,
            cddjzb: 0,
            moneyFlowSource: 'ths_main_monitor',
            moneyFlowEstimated: false,
          },
        ],
      ]),
      existingMap: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            zlje: 100,
            zljzb: 1,
            cddje: 50,
            cddjzb: 0.5,
          },
        ],
      ]),
    })

    expect(stock).toMatchObject({
      zlje: 500,
      zljzb: 5,
      cddje: 0,
      cddjzb: 0,
    })
  })

  it('keeps existing fund flow when quote has no authoritative money-flow source', async () => {
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map([
        [
          '000001',
          {
            code: '000001',
            price: 10,
            zlje: 0,
            zljzb: 0,
            cddje: 0,
            cddjzb: 0,
          },
        ],
      ]),
      existingMap: new Map([
        [
          '000001',
          {
            code: '000001',
            name: '样本股',
            zlje: -9700,
            zljzb: -4.5,
            cddje: -10800,
            cddjzb: -5.1,
            moneyFlowSource: 'eastmoney',
            moneyFlowEstimated: false,
            capitalFlowSource: 'official_l2',
          },
        ],
      ]),
    })

    expect(stock).toMatchObject({
      price: 10,
      zlje: -9700,
      zljzb: -4.5,
      cddje: -10800,
      cddjzb: -5.1,
      moneyFlowSource: 'eastmoney',
    })
  })

  it('口径唯一化：golden compRank 不被本地重算覆盖（2026-09-21 裁决 A）', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map(),
      existingMap: new Map([
        ['000001', { code: '000001', name: '样本股', compRank: 7, compScore: 55.5, avgRankNum: 37.5, rank: 7 }],
      ]),
    })

    expect(stocks[0].compRank).toBe(7)
    expect(stocks[0].compScore).toBe(55.5)
    expect(stocks[0].avgRankNum).toBe(37.5)
    expect(stocks[0].rank).toBe(7)
  })

  it('列表排序按 golden compRank 降序稳定（缺省垫底，并列按 code）', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {},
      latestQuotes: new Map(),
      existingMap: new Map([
        ['300002', { code: '300002', name: '丙', compRank: undefined }],
        ['000001', { code: '000001', name: '乙', compRank: 3 }],
        ['600001', { code: '600001', name: '甲', compRank: 1 }],
      ]),
    })

    expect(stocks.map((s: { code: string }) => s.code)).toEqual(['600001', '000001', '300002'])
  })

  it('平台 rank 字段仍实时合并（展示字段），降级行无排名不伪造', async () => {
    const stocks = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 2 }],
      },
      latestQuotes: new Map(),
      // compScore: 0 是 createEmptyMergedStock 的占位默认，真实存量行都带该形状
      existingMap: new Map([['000001', { code: '000001', name: '样本股', compScore: 0 }]]),
    })

    expect(stocks[0].emRank).toBe(2)
    expect(stocks[0].compRank).toBeUndefined()
    expect(stocks[0].compScore).toBe(0)
  })
})
