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
})
