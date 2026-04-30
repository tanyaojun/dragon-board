import { describe, expect, it } from 'vitest'

import { HotListSentimentAnalyzer } from '../HotListSentimentAnalyzer'

function stock(code: string, input: Record<string, any> = {}) {
  return {
    code,
    name: code,
    compRank: Number(code),
    price: 10,
    change: 1,
    turnover: 10e8,
    turnoverRate: 5,
    volumeRatio: 1.1,
    zlje: 0,
    zljzb: 0,
    cddje: 0,
    cddjzb: 0,
    ...input,
  }
}

function makeStocks(count: number, factory: (index: number) => Record<string, any> = () => ({})) {
  return Array.from({ length: count }, (_, index) => stock(String(index + 1).padStart(6, '0'), {
    compRank: index + 1,
    ...factory(index),
  }))
}

describe('HotListSentimentAnalyzer', () => {
  it('强扩散但高拥挤时识别为高潮', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(120, (index) => ({
      change: index < 28 ? 9.8 : 2,
      turnoverRate: index < 28 ? 18 : 6,
      volumeRatio: index < 28 ? 2.6 : 1.2,
      turnover: index < 28 ? 20e8 : 8e8,
      zlje: index < 60 ? 2e8 : 0,
      zljzb: index < 60 ? 15 : 0,
      cddje: index < 60 ? 8000e4 : 0,
      cddjzb: index < 60 ? 6 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      yesterday: { tradingDate: '2026-04-29', hotlist: makeStocks(95) },
      dayBefore: { tradingDate: '2026-04-28', hotlist: makeStocks(88) },
    })

    expect(result.stage).toBe('高潮')
    expect(result.metrics.comparison.today.crowdedShare).toBeGreaterThan(0.18)
    expect(result.warnings.join('')).toContain('拥挤')
  })

  it('强资确认增加且风险低时识别为发酵', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(110, (index) => ({
      change: index < 70 ? 3 : -1,
      turnover: index < 22 ? 18e8 : 8e8,
      volumeRatio: index < 22 ? 1.5 : 1,
      turnoverRate: index < 22 ? 6 : 4,
      zlje: index < 22 ? 2e8 : 0,
      zljzb: index < 22 ? 16 : 0,
      cddje: index < 22 ? 9000e4 : 0,
      cddjzb: index < 22 ? 7 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      yesterday: { tradingDate: '2026-04-29', hotlist: makeStocks(105, index => ({ change: index < 48 ? 2 : -1 })) },
      dayBefore: { tradingDate: '2026-04-28', hotlist: makeStocks(100) },
    })

    expect(result.stage).toBe('发酵')
    expect(result.metrics.comparison.today.statusCounts['强资确认']).toBeGreaterThanOrEqual(8)
  })

  it('新入和机会状态改善时识别为启动', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(125, index => ({
      code: index < 60 ? String(index + 1).padStart(6, '0') : `9${String(index).padStart(5, '0')}`,
      change: index < 58 ? 2 : -0.5,
      zlje: index < 6 ? 1.2e8 : 0,
      zljzb: index < 6 ? 12 : 0,
      cddje: index < 6 ? 4000e4 : 0,
      cddjzb: index < 6 ? 4 : 0,
    }))
    const yesterday = { tradingDate: '2026-04-29', hotlist: makeStocks(90, index => ({ change: index < 40 ? 0.8 : -1 })) }

    const result = analyzer.analyze({ stocks: current, yesterday })

    expect(result.stage).toBe('启动')
    expect(result.metrics.comparison.newTop100Count).toBeGreaterThan(20)
  })

  it('风险状态上升且 TRIN 偏弱时识别为退潮', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(90, index => ({
      change: index < 45 ? 1 : -3,
      turnover: index < 45 ? 2e8 : 18e8,
      zlje: index < 30 ? -2e8 : 0,
      zljzb: index < 30 ? -12 : 0,
      cddje: index < 30 ? -8000e4 : 0,
      cddjzb: index < 30 ? -5 : 0,
    }))
    const yesterday = {
      tradingDate: '2026-04-29',
      hotlist: makeStocks(120, index => ({
        change: index < 70 ? 2 : -1,
        zlje: index < 18 ? 2e8 : 0,
        zljzb: index < 18 ? 16 : 0,
        cddje: index < 18 ? 8000e4 : 0,
        cddjzb: index < 18 ? 6 : 0,
      })),
    }

    const result = analyzer.analyze({ stocks: current, yesterday })

    expect(result.stage).toBe('退潮')
    expect(result.metrics.comparison.today.hotTrin).toBeGreaterThan(1)
  })

  it('热榜收缩且机会少时识别为冰点', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(70, index => ({
      change: index < 25 ? 0.5 : -2,
      turnover: 5e8,
    }))
    const yesterday = { tradingDate: '2026-04-29', hotlist: makeStocks(120) }
    const dayBefore = { tradingDate: '2026-04-28', hotlist: makeStocks(130) }

    const result = analyzer.analyze({ stocks: current, yesterday, dayBefore })

    expect(result.stage).toBe('冰点')
    expect(result.metrics.comparison.totalChange1d).toBeLessThan(0)
  })
})
