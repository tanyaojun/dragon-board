import { describe, expect, it } from 'vitest'

import {
  buildMoneyFlowDiagnostics,
  summarizeMoneyFlowTicks,
  type MoneyFlowDiagnosticStock,
} from '../moneyFlowDiagnostics'

function usableTicks() {
  return [{ side: 'buy' as const, amount: 3_000_000, volume: 3_000 }]
}

function createStock(index: number, overrides: Partial<MoneyFlowDiagnosticStock> = {}): MoneyFlowDiagnosticStock {
  return {
    code: String(600000 + index).padStart(6, '0'),
    name: `S${index}`,
    price: 20,
    change: 2,
    compRank: index,
    volumeRatio: 1,
    turnover: 10_000_000_000,
    turnoverRate: 5,
    zlje: 20_000_000,
    zljzb: 2,
    cddje: 5_000_000,
    cddjzb: 0.5,
    moneyFlowSource: 'tdx_estimate',
    moneyFlowEstimated: true,
    tdxBuyVolume: 50_000,
    tdxSellVolume: 45_000,
    recentTicks: usableTicks(),
    ...overrides,
  }
}

describe('moneyFlowDiagnostics', () => {
  it('识别热榜前100估算资金整体偏负的系统性风险', () => {
    const stocks = Array.from({ length: 100 }, (_, index) =>
      createStock(index + 1, {
        change: index < 20 ? 10 : 2,
        zlje: -100_000_000,
        zljzb: -45,
        cddje: -30_000_000,
        cddjzb: -15,
        recentTicks: [],
      }),
    )

    const diagnostics = buildMoneyFlowDiagnostics(stocks)

    expect(diagnostics.groups.top100.total).toBe(100)
    expect(diagnostics.groups.top100.estimatedShare).toBe(1)
    expect(diagnostics.groups.top100.zljeNegativeShare).toBe(1)
    expect(diagnostics.groups.top100.severeNegativeShare).toBe(1)
    expect(diagnostics.diagnosis.suspectBias).toBe(true)
    expect(diagnostics.diagnosis.suspectSevereBias).toBe(true)
    expect(diagnostics.diagnosis.suspectStrongStockContradiction).toBe(true)
    expect(diagnostics.diagnosis.suspectThinTickSample).toBe(true)
    expect(diagnostics.diagnosis.suspectUnit).toBe(false)
    expect(diagnostics.extremeNegativeRows).toHaveLength(20)
  })

  it('识别TDX主动成交额明显大于成交额的单位异常', () => {
    const stocks = Array.from({ length: 30 }, (_, index) =>
      createStock(index + 1, {
        price: 50,
        turnover: 1_000_000_000,
        tdxBuyVolume: 1_200_000,
        tdxSellVolume: 900_000,
      }),
    )

    const diagnostics = buildMoneyFlowDiagnostics(stocks)

    expect(diagnostics.groups.top100.avgTdxActiveAmountToTurnover).toBeGreaterThan(1.5)
    expect(diagnostics.diagnosis.suspectUnit).toBe(true)
    expect(diagnostics.diagnosis.suspectBias).toBe(false)
  })

  it('资金分布正常且逐笔样本可用时不误报偏差', () => {
    const stocks = Array.from({ length: 100 }, (_, index) => {
      const isNegative = index < 40
      return createStock(index + 1, {
        zlje: isNegative ? -5_000_000 : 20_000_000,
        zljzb: isNegative ? -4 : 2,
        cddje: isNegative ? 2_000_000 : 5_000_000,
        cddjzb: isNegative ? 0.2 : 0.5,
      })
    })

    const diagnostics = buildMoneyFlowDiagnostics(stocks)

    expect(diagnostics.groups.top100.zljeNegativeShare).toBe(0.4)
    expect(diagnostics.groups.top100.usableTickSampleShare).toBe(1)
    expect(diagnostics.diagnosis.suspectBias).toBe(false)
    expect(diagnostics.diagnosis.suspectSevereBias).toBe(false)
    expect(diagnostics.diagnosis.suspectStrongStockContradiction).toBe(false)
    expect(diagnostics.diagnosis.suspectUnit).toBe(false)
    expect(diagnostics.diagnosis.suspectThinTickSample).toBe(false)
    expect(diagnostics.diagnosis.notes).toEqual([])
  })

  it('按涨停、大跌、高换手和量比分组输出诊断统计', () => {
    const stocks = [
      createStock(1, { change: 10, turnoverRate: 12, volumeRatio: 1.8 }),
      createStock(2, { change: 8, turnoverRate: 11, volumeRatio: 1.4 }),
      createStock(3, { change: -6, turnoverRate: 4, volumeRatio: 0.8 }),
      createStock(4, { change: 1, turnoverRate: 3, volumeRatio: 1 }),
    ]

    const diagnostics = buildMoneyFlowDiagnostics(stocks, { topSize: 4 })

    expect(diagnostics.groups.limitUp.total).toBe(1)
    expect(diagnostics.groups.weak.total).toBe(1)
    expect(diagnostics.groups.highTurnoverRate.total).toBe(2)
    expect(diagnostics.groups.highVolumeRatio.total).toBe(2)
  })

  it('按dataLoader同口径汇总逐笔大单样本', () => {
    const summary = summarizeMoneyFlowTicks([
      { side: 'buy', amount: 300_000, volume: 200 },
      { side: 'sell', amount: 1_200_000, volume: 200 },
      { side: 'neutral', amount: 2_000_000, volume: 1_000 },
    ])

    expect(summary.activeAmount).toBe(1_500_000)
    expect(summary.mainNet).toBe(-900_000)
    expect(summary.superNet).toBe(-1_200_000)
  })
})
