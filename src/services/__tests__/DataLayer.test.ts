import { describe, expect, test, vi } from 'vitest'
import { dataLayer } from '../DataLayer'

describe('DataLayer breath market data', () => {
  test('keeps THS limit-up pool evidence for snapshot builders', () => {
    dataLayer.reset()

    try {
      dataLayer.updateBreathData({
        timestamp: 1779084000000,
        sentiment: {
          overall: 60,
          phase: 'start',
          phaseName: '启动期',
          riskLevel: 'medium',
          suggestion: 'observe',
          phaseInfo: { name: '启动期' },
        },
        marketData: {
          upCount: 3000,
          downCount: 1800,
          ztCount: 74,
          dtCount: 18,
          previousMarketStats: {
            tradingDate: '2026-05-19',
            ztCount: 122,
            dtCount: 58,
            source: 'daily_snapshot',
          },
          zhaban: { count: 37, rate: 33.6, fengbanRate: 66.4 },
          thsLimitUpPools: {
            source: 'limitup-ths-pools',
            timestamp: 1779084000000,
            degraded: false,
            poolCounts: {
              one: 65,
              two: 5,
              three: 1,
              four: 2,
              high: 1,
              failed: 37,
              rushing: 20,
              drawdown: 6,
            },
            failedCount: 37,
            drawdownCount: 6,
            drawdownRiskLabel: '涨停股回撤榜',
            avgDrawdown: -13.2,
            maxDrawdown: -18.19,
            errors: [],
          },
        },
      })

      expect(dataLayer.getBreathMarketData()?.thsLimitUpPools).toMatchObject({
        failedCount: 37,
        drawdownCount: 6,
        poolCounts: {
          one: 65,
          failed: 37,
          drawdown: 6,
        },
        degraded: false,
      })
      expect(dataLayer.getBreathMarketData()?.previousMarketStats).toMatchObject({
        tradingDate: '2026-05-19',
        ztCount: 122,
        dtCount: 58,
        source: 'daily_snapshot',
      })
    } finally {
      dataLayer.reset()
    }
  })
})

describe('DataLayer limit-up runtime projection', () => {
  test('applies limit-up updates to already merged stocks before the next platform merge', () => {
    vi.useFakeTimers()
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '样本股' }])
      dataLayer.updateLimitUpData([
        {
          code: '000001',
          reason: '存储芯片+先进封装',
          firstZtTime: '09:37:00',
          lastZtTime: '09:37:00',
          boardHeight: 2,
          highDays: 2,
        },
      ])

      expect(dataLayer.getStock('000001')).toMatchObject({
        reason: '存储芯片+先进封装',
        firstZtTime: '09:37:00',
        lastZtTime: '09:37:00',
        boardHeight: 2,
        highDays: 2,
      })
    } finally {
      vi.runOnlyPendingTimers()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  test('projects isNew to already merged stocks before the next platform merge', () => {
    vi.useFakeTimers()
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '样本股', isNew: false }])
      dataLayer.updateLimitUpData([{ code: '000001', isNew: true }])

      expect(dataLayer.getStock('000001')?.isNew).toBe(true)
      expect(dataLayer.getStockIsNew('000001')).toBe(true)
      expect(dataLayer.getLimitUpData('000001')?.isNew).toBe(true)
    } finally {
      vi.runOnlyPendingTimers()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  test('does not overwrite quote fields with THS pool-only metrics during instant projection', () => {
    vi.useFakeTimers()
    dataLayer.reset()

    try {
      dataLayer.setMergedStocks([
        { code: '000001', name: '样本股', speed: 0.8, turnover: 1000000 } as any,
      ])
      dataLayer.updateLimitUpData([
        {
          code: '000001',
          reason: '存储芯片',
          speed: 5.6,
          turnover: 9999999,
          poolType: 'failed',
        } as any,
      ])

      expect(dataLayer.getStock('000001')).toMatchObject({
        reason: '存储芯片',
        speed: 0.8,
        turnover: 1000000,
      })
    } finally {
      vi.runOnlyPendingTimers()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})

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

  test('marks volume ratio stale when realtime quote changes current volume', () => {
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
          volumeRatio: 1.2,
          volumeRatioMeta: {
            status: 'fresh',
            source: 'daily_snapshot',
            calculatedAt: 1000,
            currentVolume: 1000,
            capped: false,
          },
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
        },
      ])

      expect(dataLayer.getStock('000001')).toMatchObject({
        volume: 1800,
        volumeRatio: 1.2,
        volumeRatioMeta: expect.objectContaining({
          status: 'stale',
          reason: 'volume_changed_after_ratio_calculated',
          currentVolume: 1800,
        }),
      })
    } finally {
      dataLayer.reset()
    }
  })
})
