import { describe, expect, test, vi } from 'vitest'
import { dataLayer } from '../DataLayer'

describe('DataLayer throttled notifications', () => {
  test('flushes each pending path and keeps only the latest payload per path', () => {
    vi.useFakeTimers()

    try {
      dataLayer.reset()
      const mergedStocks = vi.fn()
      const versionStocks = vi.fn()
      const unsubscribeMergedStocks = dataLayer.subscribe('merged.stocks', mergedStocks)
      const unsubscribeVersionStocks = dataLayer.subscribe('version.stocks', versionStocks)

      dataLayer.setMergedStocks([{ code: '000001', name: 'first' }])
      dataLayer.setMergedStocks([{ code: '000002', name: 'second' }])

      expect(mergedStocks).not.toHaveBeenCalled()
      expect(versionStocks).not.toHaveBeenCalled()

      vi.advanceTimersByTime(50)

      expect(mergedStocks).toHaveBeenCalledTimes(1)
      expect(mergedStocks).toHaveBeenCalledWith([{ code: '000002', name: 'second' }])
      expect(versionStocks).toHaveBeenCalledTimes(1)
      expect(versionStocks).toHaveBeenCalledWith(2)

      unsubscribeMergedStocks()
      unsubscribeVersionStocks()
    } finally {
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})

describe('DataLayer money flow source precedence', () => {
  test('keeps EastMoney fund flow when later TDX L1 estimates arrive', () => {
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          price: 10,
          change: 1,
          volume: 1000,
          turnover: 10000,
          turnoverRate: 2,
          zlje: 5000,
          zljzb: 5,
          cddje: 2000,
          cddjzb: 2,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
        },
      ])
      dataLayer.updateQuote('000001', {
        zlje: 5000,
        zljzb: 5,
        cddje: 2000,
        cddjzb: 2,
        moneyFlowSource: 'eastmoney',
        moneyFlowEstimated: false,
        capitalFlowSource: 'official_l2',
        capitalFlowConfidence: 'medium',
      })

      dataLayer.applyRealtimeQuoteBatch([
        {
          code: '000001',
          price: 10.1,
          zlje: -1000,
          zljzb: -1,
          cddje: -500,
          cddjzb: -0.5,
          moneyFlowSource: 'tdx_estimate',
          moneyFlowEstimated: true,
          capitalFlowSource: 'estimated_l1',
          capitalFlowConfidence: 'low',
        },
      ])

      const stock = dataLayer.getStock('000001')
      expect(stock?.price).toBe(10.1)
      expect(stock?.zlje).toBe(5000)
      expect(stock?.zljzb).toBe(5)
      expect(stock?.cddje).toBe(2000)
      expect(stock?.cddjzb).toBe(2)
      expect(stock?.moneyFlowSource).toBe('eastmoney')
      expect(stock?.moneyFlowEstimated).toBe(false)
      expect(stock?.capitalFlowSource).toBe('official_l2')
      expect(stock?.capitalFlowConfidence).toBe('medium')

      const quote = dataLayer.getQuote('000001')
      expect(quote?.zlje).toBe(5000)
      expect(quote?.moneyFlowSource).toBe('eastmoney')
      expect(quote?.moneyFlowEstimated).toBe(false)
      expect(quote?.capitalFlowSource).toBe('official_l2')
    } finally {
      dataLayer.reset()
    }
  })

  test('allows higher priority fund flow sources to replace lower priority sources', () => {
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          zlje: 100,
          zljzb: 1,
          cddje: 50,
          cddjzb: 0.5,
          moneyFlowSource: 'tdx_estimate',
          moneyFlowEstimated: true,
          capitalFlowSource: 'estimated_l1',
          capitalFlowConfidence: 'low',
        },
      ])

      dataLayer.applyRealtimeQuoteBatch([
        {
          code: '000001',
          zlje: 5000,
          zljzb: 5,
          cddje: 2000,
          cddjzb: 2,
          moneyFlowSource: 'eastmoney',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'medium',
        },
      ])

      expect(dataLayer.getStock('000001')?.moneyFlowSource).toBe('eastmoney')
      expect(dataLayer.getStock('000001')?.zlje).toBe(5000)

      dataLayer.applyRealtimeQuoteBatch([
        {
          code: '000001',
          zlje: 9000,
          zljzb: 9,
          cddje: 6000,
          cddjzb: 6,
          moneyFlowSource: 'qmt_l2',
          moneyFlowEstimated: false,
          capitalFlowSource: 'broker_l2',
          capitalFlowConfidence: 'high',
        },
      ])

      const stock = dataLayer.getStock('000001')
      expect(stock?.moneyFlowSource).toBe('qmt_l2')
      expect(stock?.moneyFlowEstimated).toBe(false)
      expect(stock?.capitalFlowSource).toBe('broker_l2')
      expect(stock?.capitalFlowConfidence).toBe('high')
      expect(stock?.zlje).toBe(9000)
      expect(stock?.cddje).toBe(6000)
    } finally {
      dataLayer.reset()
    }
  })
})

describe('DataLayer realtime merge arbitration', () => {
  test('keeps realtime quote and L2 fields when merged stocks are written later', () => {
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          price: 10,
          change: 1,
          volume: 1000,
          turnover: 10000,
          turnoverRate: 2,
        },
      ])

      dataLayer.applyRealtimeQuoteBatch([
        {
          code: '000001',
          price: 10.8,
          change: 8,
          volume: 1800,
          turnover: 18000,
          turnoverRate: 3,
          tdxBuyVolume: 900,
        },
      ])
      dataLayer.updateL2SummaryBatch([
        {
          code: '000001',
          bid1Price: 10.79,
          bid1Volume: 1200,
          ask1Price: 10.81,
          ask1Volume: 800,
          spread: 0.02,
          bid10Total: 10000,
          ask10Total: 9000,
          depthImbalance: 0.08,
          tickBuyVolume: 5000,
          tickSellVolume: 3200,
          tickBuyCount: 42,
          tickSellCount: 31,
          lastTradePrice: 10.8,
          lastTradeVolume: 100,
        },
      ])

      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          price: 10,
          change: 1,
          volume: 1000,
          turnover: 10000,
          turnoverRate: 2,
        },
      ])

      expect(dataLayer.getStock('000001')).toMatchObject({
        price: 10.8,
        change: 8,
        volume: 1800,
        turnover: 18000,
        turnoverRate: 3,
        tdxBuyVolume: 900,
        bid1Price: 10.79,
        bid1Volume: 1200,
        ask1Price: 10.81,
        ask1Volume: 800,
        depthImbalance: 0.08,
        lastTradePrice: 10.8,
      })
    } finally {
      dataLayer.reset()
    }
  })
})
