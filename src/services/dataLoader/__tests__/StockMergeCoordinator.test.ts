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
            moneyFlowSource: 'ths_l2',
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
})
