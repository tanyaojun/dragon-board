import { describe, expect, it } from 'vitest'

import {
  average,
  clamp,
  getTechnicalMinSamples,
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
