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
  test('allows higher priority fund flow sources to replace lower priority sources', () => {
    dataLayer.reset()

    try {
      // 先写入低优先级 qmt_l2，再推送高优先级 ths_l2，后者应覆盖前者
      dataLayer.setMergedStocks([
        {
          code: '000001',
          name: '平安银行',
          zlje: 100,
          zljzb: 1,
          cddje: 50,
          cddjzb: 0.5,
          moneyFlowSource: 'qmt_l2',
          moneyFlowEstimated: false,
          capitalFlowSource: 'broker_l2',
          capitalFlowConfidence: 'high',
        },
      ])

      dataLayer.applyRealtimeQuoteBatch([
        {
          code: '000001',
          zlje: 9000,
          zljzb: 9,
          cddje: 6000,
          cddjzb: 6,
          moneyFlowSource: 'ths_l2',
          moneyFlowEstimated: false,
          capitalFlowSource: 'official_l2',
          capitalFlowConfidence: 'high',
        },
      ])

      const stock = dataLayer.getStock('000001')
      expect(stock?.moneyFlowSource).toBe('ths_l2')
      expect(stock?.moneyFlowEstimated).toBe(false)
      expect(stock?.capitalFlowSource).toBe('official_l2')
      expect(stock?.capitalFlowConfidence).toBe('high')
      expect(stock?.zlje).toBe(9000)
      expect(stock?.cddje).toBe(6000)
    } finally {
      dataLayer.reset()
    }
  })
})
