import { describe, expect, it } from 'vitest'

import { cloneDefaultRankTrendRuntimeConfig } from '../../../types/rankTrendDefaults'
import { analyzeFallbackTechnicalSignals, analyzeTechnicalSignals } from '../technicalSignalAnalyzer'

describe('technicalSignalAnalyzer', () => {
  it('样本不足时不会伪造 MACD 金叉/死叉', () => {
    const technical = analyzeFallbackTechnicalSignals({
      percentiles: [55, 58, 61],
      displayChange: 3,
      stockChange: 5.6,
      volumeRatio: 2.1,
      zlje: 36_000_000,
      zljzb: 5.2,
      config: cloneDefaultRankTrendRuntimeConfig(),
    })

    expect(technical.macd.dif).toBe(0)
    expect(technical.macd.dea).toBe(0)
    expect(technical.macd.histogram).toBe(0)
    expect(technical.macd.cross).toBe('none')
    expect(technical.macd.rawScore).toBe(0)
  })

  it('达到 macdSlow 后会计算出 MACD 数值，但没有真实穿越时仍是 none', () => {
    const technical = analyzeTechnicalSignals(
      Array.from({ length: 21 }, (_, index) => 35 + index * 1.15),
      cloneDefaultRankTrendRuntimeConfig(),
    )

    expect(Math.abs(technical.macd.dif)).toBeGreaterThan(0)
    expect(Math.abs(technical.macd.dea)).toBeGreaterThan(0)
    expect(Math.abs(technical.macd.histogram)).toBeGreaterThan(0)
    expect(technical.macd.cross).toBe('none')
  })

  it('fallback 代理分不会在真实 MACD 无交叉时硬给 cross', () => {
    const technical = analyzeFallbackTechnicalSignals({
      percentiles: Array.from({ length: 25 }, () => 50),
      displayChange: 3,
      stockChange: 6.1,
      volumeRatio: 2.4,
      zlje: 48_000_000,
      zljzb: 6.4,
      config: cloneDefaultRankTrendRuntimeConfig(),
    })

    expect(technical.macd.cross).toBe('none')
    expect(technical.macd.rawScore).toBe(0)
  })
})
