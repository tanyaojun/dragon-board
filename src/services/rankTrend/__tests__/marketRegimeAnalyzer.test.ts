import { describe, expect, it } from 'vitest'

import { analyzeMarketRegime } from '../marketRegimeAnalyzer'

describe('analyzeMarketRegime', () => {
  it('无市场数据时得分 50 判定为 weak', () => {
    const regime = analyzeMarketRegime({})

    expect(regime.state).toBe('weak')
    expect(regime.score).toBe(50)
    expect(regime.reasons).toContain('市场环境数据不足，按中性处理')
  })

  it('冰点阶段下修得分明显', () => {
    const noPhase = analyzeMarketRegime({ breathData: { marketData: {} } })
    const icePhase = analyzeMarketRegime({
      breathData: { marketData: {}, sentiment: { phaseName: '冰点期' } },
    })

    expect(icePhase.score).toBeLessThan(noPhase.score)
  })

  it('退潮阶段向弱势方向下修', () => {
    const regime = analyzeMarketRegime({
      breathData: { marketData: {}, sentiment: { phaseName: '退潮期' } },
    })

    expect(regime.score).toBeLessThan(50)
    expect(regime.reasons.some((r) => r.includes('退潮'))).toBe(true)
  })

  it('高潮阶段上修得分', () => {
    const regime = analyzeMarketRegime({
      breathData: { marketData: {}, sentiment: { phaseName: '高潮期' } },
    })

    expect(regime.score).toBeGreaterThan(52)
    expect(regime.reasons.some((r) => r.includes('高潮'))).toBe(true)
  })

  it('phase 不带"期"后缀仍能识别', () => {
    const regime = analyzeMarketRegime({
      breathData: { marketData: {}, sentiment: { phaseName: '高潮' } },
    })

    expect(regime.reasons.some((r) => r.includes('高潮'))).toBe(true)
  })

  it('高涨停数推升得分', () => {
    const base = analyzeMarketRegime({ breathData: { marketData: { ztCount: '80' } } })
    const low = analyzeMarketRegime({ breathData: { marketData: { ztCount: '10' } } })

    expect(base.score).toBeGreaterThan(low.score)
  })

  it('跌停数多拉低得分', () => {
    const base = analyzeMarketRegime({ breathData: { marketData: { dtCount: '30' } } })
    const clean = analyzeMarketRegime({ breathData: { marketData: { dtCount: '0' } } })

    expect(base.score).toBeLessThan(clean.score)
  })

  it('涨跌比正向推动得分', () => {
    const bull = analyzeMarketRegime({ breathData: { marketData: { upCount: 300, downCount: 100 } } })
    const bear = analyzeMarketRegime({ breathData: { marketData: { upCount: 100, downCount: 300 } } })

    expect(bull.score).toBeGreaterThan(bear.score)
    expect(bull.reasons.some((r) => r.includes('涨跌扩散'))).toBe(true)
  })

  it('热榜资金正向比例影响得分', () => {
    const rich = analyzeMarketRegime({
      stocks: [
        { zlje: 1e8, volumeRatio: 1.2 },
        { zlje: 5e7, volumeRatio: 1.1 },
        { zlje: 2e8, volumeRatio: 1.5 },
      ],
    })
    const poor = analyzeMarketRegime({
      stocks: [
        { zlje: -1e7, volumeRatio: 0.8 },
        { zlje: -5e6, volumeRatio: 0.6 },
      ],
    })

    expect(rich.score).toBeGreaterThan(poor.score)
  })

  it('可疑封顶量比不计入市场量能活跃占比', () => {
    const suspicious = analyzeMarketRegime({
      stocks: Array.from({ length: 10 }, () => ({
        zlje: 1e8,
        volumeRatio: 99.99,
        volumeRatioMeta: {
          status: 'suspicious',
          source: 'intraday_snapshot',
          calculatedAt: Date.now(),
          currentVolume: 100000,
          capped: true,
          reason: 'ratio_capped',
        },
      })),
    })
    const trusted = analyzeMarketRegime({
      stocks: Array.from({ length: 10 }, () => ({
        zlje: 1e8,
        volumeRatio: 2,
        volumeRatioMeta: {
          status: 'fresh',
          source: 'intraday_snapshot',
          calculatedAt: Date.now(),
          currentVolume: 100000,
        },
      })),
    })

    expect(suspicious.score).toBeLessThan(trusted.score)
    expect(suspicious.reasons.some((reason) => reason.includes('量能活跃'))).toBe(false)
  })

  it('score 不会超出 [0, 100]', () => {
    const regime = analyzeMarketRegime({
      breathData: {
        marketData: {
          ztCount: '200',
          upCount: 2000,
          downCount: 0,
          totalAmo: '2e12',
          passRate: { to2: '80' },
        },
        sentiment: { phaseName: '高潮期' },
      },
      stocks: Array.from({ length: 50 }, () => ({
        zlje: 1e9,
        volumeRatio: 2,
      })),
    })

    expect(regime.score).toBeGreaterThanOrEqual(0)
    expect(regime.score).toBeLessThanOrEqual(100)

    const retreat = analyzeMarketRegime({
      breathData: {
        marketData: {
          dtCount: '200',
          upCount: 0,
          downCount: 2000,
        },
        sentiment: { phaseName: '冰点期' },
      },
    })

    expect(retreat.score).toBeGreaterThanOrEqual(0)
    expect(retreat.score).toBeLessThanOrEqual(100)
  })

  it('score>=72 判定为 strong', () => {
    const regime = analyzeMarketRegime({
      breathData: {
        marketData: { ztCount: '120', upCount: 1000, downCount: 100, totalAmo: '1.5e12' },
        sentiment: { phaseName: '高潮期' },
      },
      stocks: Array.from({ length: 30 }, () => ({ zlje: 1e9, volumeRatio: 2 })),
    })

    if (regime.score >= 72) {
      expect(regime.state).toBe('strong')
    }
  })

  it('score 低于 35 判定为 retreat', () => {
    const regime = analyzeMarketRegime({
      breathData: {
        marketData: { dtCount: '100', upCount: 100, downCount: 800 },
        sentiment: { phaseName: '冰点期' },
      },
    })

    if (regime.score < 35) {
      expect(regime.state).toBe('retreat')
    }
  })
})
