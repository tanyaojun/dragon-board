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

  it('keeps backend compRank/compScore/avgRankNum from existingMap without recompute', async () => {
    // 前后端分离：前端 merge 直接继承 existingMap 后端 compRank（启动 bundle），不再五维重算
    const [stock] = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '000001', name: '样本股', rank: 1 }],
      },
      latestQuotes: new Map(),
      volumeHistoryMap: new Map(),
      intradayVolumeHistoryMap: new Map(),
      existingMap: new Map([
        [
          '000001',
          { code: '000001', name: '样本股', compRank: 7, compScore: 88.1, avgRankNum: 42.3 },
        ],
      ]),
    })

    expect(stock).toMatchObject({ compRank: 7, compScore: 88.1, avgRankNum: 42.3 })
  })

  it('leaves intraday new-stock compRank undefined and sorts safely without misordering', async () => {
    // 盘中新 tick 股票无 existingMap → createEmptyStock compRank=undefined；
    // 消费端排序须按 (b.compRank ?? 0) 降级，undefined 不产生 NaN/越界
    const merged = await new StockMergeCoordinator().merge({
      platformData: {
        eastmoney: [{ code: '600000', name: '新进', rank: 99 }],
      },
      latestQuotes: new Map(),
      volumeHistoryMap: new Map(),
      intradayVolumeHistoryMap: new Map(),
      existingMap: new Map(),
    })

    const [stock] = merged
    expect(stock.compRank).toBeUndefined()

    const rankCmp = (a: any, b: any) => (b?.compRank ?? 0) - (a?.compRank ?? 0)
    const sorted = [...merged].sort(rankCmp)
    expect(sorted[0].code).toBe('600000')
  })
})
