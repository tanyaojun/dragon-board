import { describe, expect, it } from 'vitest'
import type { QuotePatch, TickTrade } from '../../../types'
import {
  calculateTdxDarkMoneyFactor,
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

  it('returns null when price or active volume is invalid', () => {
    expect(estimateTdxMoneyFlow('000001', { ...baseQuote, lastPrice: 0 })).toBeNull()
    expect(
      estimateTdxMoneyFlow('000001', {
        ...baseQuote,
        tdxBuyVolume: 0,
        tdxSellVolume: 0,
      }),
    ).toBeNull()
  })

  it('estimates TDX money flow fields from valid quote active volume', () => {
    const result = estimateTdxMoneyFlow('000001', baseQuote)

    expect(result).toMatchObject({
      tdxBuyVolume: 3_000,
      tdxSellVolume: 2_000,
      tdxCurrentVolume: 120,
      moneyFlowSource: 'tdx_estimate',
      moneyFlowEstimated: true,
    })
    expect(result?.zlje).toEqual(expect.any(Number))
    expect(result?.zljzb).toEqual(expect.any(Number))
    expect(result?.cddje).toEqual(expect.any(Number))
    expect(result?.cddjzb).toEqual(expect.any(Number))
  })

  it('calculates dark money factors from OHLC structure', () => {
    const factor = calculateTdxDarkMoneyFactor(baseQuote)

    expect(factor.x16).toBeCloseTo(0.0644, 4)
    expect(factor.amplitude).toBeCloseTo(0.0816, 4)
    expect(factor.closePosition).toBeCloseTo(0.5, 4)
  })

  it('keeps existing order classification thresholds', () => {
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
