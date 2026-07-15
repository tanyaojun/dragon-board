import { describe, expect, it } from 'vitest'
import type { TickTrade } from '../../../types'
import {
  classifyMoneyFlowOrder,
  summarizeMoneyFlowTicks,
} from '../MoneyFlowEstimator'

describe('MoneyFlowEstimator', () => {
  it('classifies order buckets with EastMoney-style amount or share thresholds', () => {
    expect(classifyMoneyFlowOrder(1_000_000, 1)).toBe('super')
    expect(classifyMoneyFlowOrder(1, 500_000)).toBe('super')
    expect(classifyMoneyFlowOrder(200_000, 1)).toBe('large')
    expect(classifyMoneyFlowOrder(1, 100_000)).toBe('large')
    expect(classifyMoneyFlowOrder(199_999, 99_999)).toBe('other')
  })

  it('summarizes active, main and super money flow ticks', () => {
    const ticks: TickTrade[] = [
      {
        code: '000001',
        price: 10,
        volume: 100,
        amount: 1_000_000,
        side: 'buy',
        tradeTime: '09:30:01',
        timestamp: 1,
      },
      {
        code: '000001',
        price: 10,
        volume: 20,
        amount: 200_000,
        side: 'sell',
        tradeTime: '09:30:02',
        timestamp: 2,
      },
      {
        code: '000001',
        price: 10,
        volume: 10,
        amount: 50_000,
        side: 'neutral',
        tradeTime: '09:30:03',
        timestamp: 3,
      },
    ]

    expect(summarizeMoneyFlowTicks(ticks)).toEqual({
      activeAmount: 1_200_000,
      mainNet: 800_000,
      superNet: 1_000_000,
    })
  })
})
