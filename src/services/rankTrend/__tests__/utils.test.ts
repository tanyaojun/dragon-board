import { describe, expect, it } from 'vitest'

import {
  average,
  calculateSignalConfidence,
  calculateWeightedShare,
  clamp,
  getMacdMinSamples,
  getTechnicalMinSamples,
  normalizeSigned,
} from '../utils'

describe('clamp', () => {
  it('范围内不变', () => {
    expect(clamp(5, 0, 10)).toBe(5)
  })

  it('低于最小值拉回最小值', () => {
    expect(clamp(-3, 0, 10)).toBe(0)
  })

  it('高于最大值拉回最大值', () => {
    expect(clamp(15, 0, 10)).toBe(10)
  })

  it('等于边界不裁剪', () => {
    expect(clamp(0, 0, 10)).toBe(0)
    expect(clamp(10, 0, 10)).toBe(10)
  })

  it('NaN 返回最小值', () => {
    expect(clamp(NaN, 0, 10)).toBe(0)
  })

  it('Infinity 返回最小值', () => {
    expect(clamp(Infinity, 0, 10)).toBe(0)
    expect(clamp(-Infinity, 3, 8)).toBe(3)
  })
})

describe('average', () => {
  it('正常数组求均值', () => {
    expect(average([2, 4, 6])).toBe(4)
  })

  it('空数组返回 0', () => {
    expect(average([])).toBe(0)
  })

  it('单值返回自身', () => {
    expect(average([7])).toBe(7)
  })

  it('含零值正常计算', () => {
    expect(average([0, 10])).toBe(5)
  })
})

describe('normalizeSigned', () => {
  it('正值用 positiveScale 归一化', () => {
    const result = normalizeSigned(8, 8, 8)
    expect(result).toBeGreaterThan(0.7)
    expect(result).toBeLessThanOrEqual(1)
  })

  it('负值用 negativeScale 归一化', () => {
    const result = normalizeSigned(-6, 8, 6)
    expect(result).toBeLessThan(-0.7)
    expect(result).toBeGreaterThanOrEqual(-1)
  })

  it('零值返回 0', () => {
    expect(normalizeSigned(0, 5, 5)).toBe(0)
  })

  it('NaN 返回 0', () => {
    expect(normalizeSigned(NaN, 5, 5)).toBe(0)
  })

  it('scale 过小时使用 1e-6 保底不除零', () => {
    expect(() => normalizeSigned(5, 0, 0)).not.toThrow()
    const result = normalizeSigned(5, 0, 0)
    expect(result).toBeCloseTo(clamp(Math.tanh(5 / 1e-6), -1, 1))
  })
})

describe('calculateSignalConfidence', () => {
  it('零分返回基准 50', () => {
    expect(calculateSignalConfidence(0)).toBe(50)
  })

  it('高分提升置信度', () => {
    expect(calculateSignalConfidence(0.8)).toBeGreaterThanOrEqual(80)
  })

  it('负分按绝对值提升置信度', () => {
    expect(calculateSignalConfidence(-0.8)).toBeGreaterThanOrEqual(80)
  })

  it('agreementBonus 叠加不超 90', () => {
    expect(calculateSignalConfidence(0.5, 20)).toBeLessThanOrEqual(90)
  })

  it('不低于 50', () => {
    expect(calculateSignalConfidence(-100)).toBeGreaterThanOrEqual(50)
  })
})

describe('calculateWeightedShare', () => {
  const weights = [1, 2, 3]

  it('全部满足返回 1', () => {
    expect(calculateWeightedShare([1, 1, 1], weights, (s) => s > 0)).toBe(1)
  })

  it('全不满足返回 0', () => {
    expect(calculateWeightedShare([-1, -1, -1], weights, (s) => s > 0)).toBe(0)
  })

  it('部分满足按权重返回比例', () => {
    const share = calculateWeightedShare([1, -1, 1], weights, (s) => s > 0)
    expect(share).toBeCloseTo(4 / 6)
  })

  it('空数组返回 0', () => {
    expect(calculateWeightedShare([], [], () => true)).toBe(0)
  })

  it('权重含 NaN 或非正值时跳过该项', () => {
    expect(calculateWeightedShare([1, -1], [NaN, 1], (s) => s > 0)).toBe(0)
    expect(calculateWeightedShare([1, -1], [0, 1], (s) => s > 0)).toBe(0)
  })
})

describe('getMacdMinSamples', () => {
  it('正常配置返回 macdSlow', () => {
    expect(getMacdMinSamples({ macdSlow: 21 })).toBe(21)
  })

  it('macdSlow 为 0 时返回最小 2', () => {
    expect(getMacdMinSamples({ macdSlow: 0 })).toBe(2)
  })

  it('负数返回最小 2', () => {
    expect(getMacdMinSamples({ macdSlow: -5 })).toBe(2)
  })
})

describe('getTechnicalMinSamples', () => {
  const baseConfig = { macdSlow: 21, momentumPeriods: [3, 5, 8, 13, 21] }

  it('不小于 macdMinSamples、maxPeriod+1、30 三者的最大值', () => {
    const result = getTechnicalMinSamples(baseConfig)
    expect(result).toBeGreaterThanOrEqual(21) // macdSlow
    expect(result).toBeGreaterThanOrEqual(22) // maxPeriod(21)+1
    expect(result).toBeGreaterThanOrEqual(30) // 硬下限
    // 默认配置下 30 是最大值
    expect(result).toBe(30)
  })

  it('空 momentumPeriods 不影响计算', () => {
    const result = getTechnicalMinSamples({ ...baseConfig, momentumPeriods: [] })
    expect(result).toBe(30)
  })

  it('大周期推高阈值超过 30 时取周期值', () => {
    const result = getTechnicalMinSamples({ macdSlow: 12, momentumPeriods: [3, 5, 50] })
    expect(result).toBe(51) // maxPeriod(50)+1 > 30
  })
})
