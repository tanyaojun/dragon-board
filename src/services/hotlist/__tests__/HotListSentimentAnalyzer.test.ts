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

  it('上涨承接较强时高风险压力不直接判为退潮', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(120, index => ({
      change: index < 60 ? 4 : -1,
      turnover: index < 60 ? 18e8 : 4e8,
      turnoverRate: 6,
      volumeRatio: 1.1,
      zlje: index < 12 ? -2e8 : index < 28 ? 2e8 : index < 59 ? -2e8 : 0,
      zljzb: index < 12 ? -12 : index < 28 ? 16 : index < 59 ? -12 : 0,
      cddje: index < 12 ? -8000e4 : index < 28 ? 8000e4 : index < 59 ? -8000e4 : 0,
      cddjzb: index < 12 ? -5 : index < 28 ? 6 : index < 59 ? -5 : 0,
    }))
    const yesterday = {
      tradingDate: '2026-04-29',
      hotlist: makeStocks(115, index => ({
        change: index < 55 ? 2 : -1,
        zlje: index < 12 ? 2e8 : 0,
        zljzb: index < 12 ? 15 : 0,
        cddje: index < 12 ? 8000e4 : 0,
        cddjzb: index < 12 ? 6 : 0,
      })),
    }

    const result = analyzer.analyze({ stocks: current, yesterday })

    expect(result.metrics.comparison.today.riskShare).toBeGreaterThan(0.35)
    expect(result.metrics.comparison.today.upRatio).toBeGreaterThanOrEqual(0.5)
    expect(result.metrics.comparison.today.hotTrin).toBeLessThan(1)
    expect(result.metrics.comparison.yesterdayStrongPerformance.weakeningRate).toBeGreaterThanOrEqual(0.45)
    expect(result.stage).toBe('发酵')
    expect(result.riskLevel).toBe('高')
  })

  it('严重风险叠加昨日强票失败且成交承接转弱时识别为退潮', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(120, index => ({
      change: index < 60 ? 4 : -1,
      turnover: index < 60 ? 2e8 : 18e8,
      turnoverRate: 6,
      volumeRatio: 1.1,
      zlje: index < 12 ? -2e8 : index < 28 ? 2e8 : index < 59 ? -2e8 : 0,
      zljzb: index < 12 ? -12 : index < 28 ? 16 : index < 59 ? -12 : 0,
      cddje: index < 12 ? -8000e4 : index < 28 ? 8000e4 : index < 59 ? -8000e4 : 0,
      cddjzb: index < 12 ? -5 : index < 28 ? 6 : index < 59 ? -5 : 0,
    }))
    const yesterday = {
      tradingDate: '2026-04-29',
      hotlist: makeStocks(130, index => ({
        change: index < 12 ? 3 : 1,
        zlje: index < 12 ? 2e8 : 0,
        zljzb: index < 12 ? 15 : 0,
        cddje: index < 12 ? 8000e4 : 0,
        cddjzb: index < 12 ? 6 : 0,
      })),
    }

    const result = analyzer.analyze({ stocks: current, yesterday })

    expect(result.metrics.comparison.today.riskShare).toBeGreaterThan(0.35)
    expect(result.metrics.comparison.today.hotTrin).toBeGreaterThan(1)
    expect(result.metrics.comparison.yesterdayStrongPerformance.weakeningRate).toBeGreaterThanOrEqual(0.45)
    expect(result.stage).toBe('退潮')
    expect(result.riskLevel).toBe('高')
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

  it('输出前20、前50、前100分层统计', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(120, index => ({
      change: index < 30 ? 5 : index < 70 ? 1 : -2,
      zlje: index < 25 ? 2e8 : index < 85 ? 0 : -1e8,
      zljzb: index < 25 ? 15 : index < 85 ? 0 : -10,
      cddje: index < 25 ? 8000e4 : index < 85 ? 0 : -4000e4,
      cddjzb: index < 25 ? 6 : index < 85 ? 0 : -4,
    }))

    const result = analyzer.analyze({ stocks: current })

    expect(result.metrics.layers.top20.topN).toBe(20)
    expect(result.metrics.layers.top50.topN).toBe(50)
    expect(result.metrics.layers.top100.topN).toBe(100)
    expect(result.metrics.layers.top20.upRatio).toBeGreaterThan(result.metrics.layers.top100.upRatio)
    expect(result.metrics.layers.top20.activeOpportunityCount).toBeGreaterThan(0)
  })

  it('按A股板块阈值统计热榜涨停和近涨停证据', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = [
      stock('600001', { compRank: 1, name: '主板股', change: 9.9 }),
      stock('300001', { compRank: 2, name: '创业板股', change: 9.9 }),
      stock('688001', { compRank: 3, name: '科创板股', change: 19.8 }),
      stock('830001', { compRank: 4, name: '北交所股', change: 29 }),
      stock('000001', { compRank: 5, name: '*ST测试', change: 4.9 }),
      ...makeStocks(10, index => ({ code: `0010${String(index).padStart(2, '0')}`, compRank: index + 6 })),
    ]

    const result = analyzer.analyze({ stocks: current, topN: 100 })
    const evidence = result.metrics.limitEvidence.intersection

    expect(evidence.top100LimitUpCount).toBe(3)
    expect(evidence.top100NearLimitUpCount).toBe(4)
  })

  it('热榜涨停证据只使用热榜交集，全市场数据仅作为背景', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(100, index => ({
      change: index < 4 ? 9.9 : 1,
      zlje: index < 15 ? 2e8 : 0,
      zljzb: index < 15 ? 15 : 0,
      cddje: index < 15 ? 8000e4 : 0,
      cddjzb: index < 15 ? 6 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      marketData: {
        ztCount: 98,
        zhaban: { count: 24, fengbanRate: 80 },
        limitData: { yiban: 61, erban: 14, sanban: 3, sibanPlus: 1 },
        maxContinuousDays: 5,
      },
    })

    expect(result.metrics.limitEvidence.market.ztCount).toBe(98)
    expect(result.metrics.limitEvidence.market.zhabanCount).toBe(24)
    expect(result.metrics.limitEvidence.intersection.top100LimitUpCount).toBe(4)
    expect(result.signals.join('')).toContain('全市场涨停 98 只')
  })

  it('THS炸板池和涨停股回撤榜只作为全市场补充证据', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const current = makeStocks(100, index => ({
      change: index < 4 ? 9.9 : 1,
      zlje: index < 15 ? 2e8 : 0,
      zljzb: index < 15 ? 15 : 0,
      cddje: index < 15 ? 8000e4 : 0,
      cddjzb: index < 15 ? 6 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      marketData: {
        ztCount: 98,
        zhaban: { count: 24, fengbanRate: 80 },
        thsLimitUpPools: {
          source: 'ths-limitup-pools',
          degraded: false,
          errors: [],
          poolCounts: {
            one: 61,
            two: 14,
            three: 3,
            four: 1,
            high: 5,
            failed: 11,
            rushing: 8,
            drawdown: 7,
          },
          failedCount: 11,
          rushingCount: 8,
          drawdownCount: 7,
          drawdownRiskLabel: '涨停股回撤榜',
          maxDrawdown: -12.4,
          avgDrawdown: -6.3,
        },
      },
    })

    expect(result.metrics.limitEvidence.market.zhabanCount).toBe(24)
    expect(result.metrics.limitEvidence.market.thsPools.failedCount).toBe(11)
    expect(result.metrics.limitEvidence.market.thsPools.drawdownCount).toBe(7)
    expect(result.metrics.limitEvidence.market.thsPools.drawdownRiskLabel).toBe('涨停股回撤榜')
    expect(result.warnings.join('')).toContain('THS炸板池 11 只')
    expect(result.warnings.join('')).toContain('不等同于全市场亏钱效应')
  })

  it('昨日热榜涨停今日表现纳入持续性证据', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const yesterday = makeStocks(100, index => ({
      change: index < 6 ? 9.9 : 1,
      zlje: index < 10 ? 2e8 : 0,
      zljzb: index < 10 ? 15 : 0,
      cddje: index < 10 ? 8000e4 : 0,
      cddjzb: index < 10 ? 6 : 0,
    }))
    const current = makeStocks(100, index => ({
      change: index < 2 ? 3 : index < 6 ? -3 : 1,
      zlje: index < 2 ? 2e8 : index < 6 ? -1e8 : 0,
      zljzb: index < 2 ? 15 : index < 6 ? -10 : 0,
      cddje: index < 2 ? 8000e4 : index < 6 ? -4000e4 : 0,
      cddjzb: index < 2 ? 6 : index < 6 ? -4 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      yesterday: { tradingDate: '2026-04-29', hotlist: yesterday },
    })
    const evidence = result.metrics.limitEvidence.yesterdayHotLimit

    expect(evidence.count).toBe(6)
    expect(evidence.retainedTop100Count).toBe(6)
    expect(evidence.positiveRate).toBeCloseTo(2 / 6)
    expect(evidence.failedOrWeakRate).toBeGreaterThanOrEqual(0.5)
    expect(result.warnings.join('')).toContain('昨日热榜涨停')
  })

  it('统计昨日强票今日平均涨幅、正收益率和转弱率', () => {
    const analyzer = new HotListSentimentAnalyzer()
    const yesterday = makeStocks(100, index => ({
      change: index < 10 ? 3 : 1,
      zlje: index < 10 ? 2e8 : 0,
      zljzb: index < 10 ? 15 : 0,
      cddje: index < 10 ? 8000e4 : 0,
      cddjzb: index < 10 ? 6 : 0,
    }))
    const current = makeStocks(100, index => ({
      change: index < 6 ? 2 : index < 10 ? -3 : 0,
      zlje: index < 6 ? 2e8 : index < 10 ? -1e8 : 0,
      zljzb: index < 6 ? 15 : index < 10 ? -10 : 0,
      cddje: index < 6 ? 8000e4 : index < 10 ? -4000e4 : 0,
      cddjzb: index < 6 ? 6 : index < 10 ? -4 : 0,
    }))

    const result = analyzer.analyze({
      stocks: current,
      yesterday: { tradingDate: '2026-04-29', hotlist: yesterday },
    })
    const performance = result.metrics.comparison.yesterdayStrongPerformance

    expect(performance.count).toBe(10)
    expect(performance.matchedCount).toBe(10)
    expect(performance.positiveRate).toBeCloseTo(0.6)
    expect(performance.weakeningRate).toBeCloseTo(0.4)
    expect(performance.avgChange).toBeCloseTo(0)
  })
})
