import { describe, expect, it } from 'vitest'
import type { QuotePatch, TickTrade } from '../../../types'
import {
  buildOfficialStyleMoneyFlow,
  classifyMoneyFlowOrder,
  estimateTdxMoneyFlow,
  summarizeMoneyFlowTicks,
} from '../MoneyFlowEstimator'

describe('MoneyFlowEstimator', () => {
  const baseQuote: QuotePatch = {
    code: '000001',
    lastPrice: 10,
    changePct: 2,
    volume: 100_000,
    amount: 120_000_000,
    tdxBuyVolume: 3_000,
    tdxSellVolume: 2_000,
    tdxCurrentVolume: 120,
    open: 9.8,
    high: 10.4,
    low: 9.6,
    preClose: 9.8,
  }

  it('does not derive official money-flow fields from L1 active buy-sell imbalance', () => {
    expect(estimateTdxMoneyFlow('000001', baseQuote)).toBeNull()
  })

  it('calculates the four money flow fields from official-style large order buckets', () => {
    const summary = {
      activeAmount: 1_600_000,
      mainNet: 800_000,
      superNet: 1_000_000,
    }

    expect(buildOfficialStyleMoneyFlow(summary, 2_000_000)).toMatchObject({
      zlje: 800_000,
      zljzb: 40,
      cddje: 1_000_000,
      cddjzb: 50,
      moneyFlowSource: 'tdx_estimate',
      moneyFlowEstimated: true,
    })
  })

  it('uses tick-trade buckets before the L1 active-volume estimate', () => {
    const result = estimateTdxMoneyFlow('000001', baseQuote, {
      activeAmount: 1_600_000,
      mainNet: 800_000,
      superNet: 1_000_000,
    })

    expect(result).toMatchObject({
      zlje: 800_000,
      zljzb: 0.67,
      cddje: 1_000_000,
      cddjzb: 0.83,
      tdxBuyVolume: 3_000,
      tdxSellVolume: 2_000,
      tdxCurrentVolume: 120,
    })
  })

  it('can calculate tick-based money flow even when L1 active volumes are missing', () => {
    const result = estimateTdxMoneyFlow(
      '000001',
      {
        ...baseQuote,
        tdxBuyVolume: 0,
        tdxSellVolume: 0,
      },
      {
        activeAmount: 1_600_000,
        mainNet: 800_000,
        superNet: 1_000_000,
      },
    )

    expect(result).toMatchObject({
      zlje: 800_000,
      cddje: 1_000_000,
      tdxBuyVolume: 0,
      tdxSellVolume: 0,
    })
  })

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
