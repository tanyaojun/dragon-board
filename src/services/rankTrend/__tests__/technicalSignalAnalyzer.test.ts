import { describe, expect, it } from 'vitest'

import { cloneDefaultRankTrendRuntimeConfig } from '../../../types/rankTrendDefaults'
import { STABLE_BARS, getMaxStableBars, getMacdMinSamples } from '../utils'
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
    const config = cloneDefaultRankTrendRuntimeConfig()
    const technical = analyzeTechnicalSignals(
      Array.from({ length: config.macdSlow + config.macdSignal }, (_, index) => 35 + index * 1.15),
      config,
    )

    expect(Math.abs(technical.macd.dif)).toBeGreaterThan(0)
    expect(Math.abs(technical.macd.dea)).toBeGreaterThan(0)
    expect(Math.abs(technical.macd.histogram)).toBeGreaterThan(0)
    expect(technical.macd.cross).toBe('none')
  })

  it('MACD bars 不足 macdSlow 时返回全零值', () => {
    const config = cloneDefaultRankTrendRuntimeConfig()
    const technical = analyzeTechnicalSignals(
      Array.from({ length: getMacdMinSamples(config) - 1 }, (_, i) => 35 + i),
      config,
    )

    expect(technical.macd.dif).toBe(0)
    expect(technical.macd.dea).toBe(0)
    expect(technical.macd.histogram).toBe(0)
    expect(technical.macd.cross).toBe('none')
  })

  it('动量 percentiles 达到 max(momentumPeriods)+1 时产出动量分析数据', () => {
    const config = cloneDefaultRankTrendRuntimeConfig()
    const maxPeriod = Math.max(...config.momentumPeriods)
    const percentiles = Array.from({ length: maxPeriod + 1 }, (_, i) => 50 + i * 0.5)

    const technical = analyzeTechnicalSignals(percentiles, config)

    expect(technical.momentumScore).toBeTypeOf('number')
    expect(Number.isFinite(technical.momentumScore)).toBe(true)
  })

  it('动量 percentiles 不足 max(momentumPeriods)+1 时不产出动量方向信号', () => {
    const config = cloneDefaultRankTrendRuntimeConfig()
    const maxPeriod = Math.max(...config.momentumPeriods)
    const percentiles = Array.from({ length: maxPeriod }, (_, i) => 50 + i * 0.5)

    const technical = analyzeTechnicalSignals(percentiles, config)

    expect(technical.momentumScore).toBe(0)
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

describe('STABLE_BARS', () => {
  it('MACD 稳定窗口为 30', () => {
    expect(STABLE_BARS.macd).toBe(30)
  })

  it('动量稳定窗口为 50', () => {
    expect(STABLE_BARS.momentum).toBe(50)
  })

  it('零线交叉稳定窗口为 8', () => {
    expect(STABLE_BARS.zeroCross).toBe(8)
  })

  it('getMaxStableBars 返回最大值 50', () => {
    expect(getMaxStableBars()).toBe(50)
  })
})
