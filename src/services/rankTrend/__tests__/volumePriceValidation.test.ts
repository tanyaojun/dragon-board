import { describe, expect, it } from 'vitest'

import {
  classifyFundSignal,
  classifyVolumePriceQuadrant,
  computeVolumePriceScore,
  getVolumePriceQuadrantLabel,
} from '@/services/rankTrend/volumePriceValidation'

// 当日中位数基准（放量 ≥ median×1.5，缩量 ≤ median×0.5）
const MEDIAN = 2.0

describe('classifyFundSignal（资金子信号）', () => {
  it('zlje>0 且 zljzb>0 → 资金配合', () => {
    expect(classifyFundSignal(1000000, 0.5)).toBe('support')
    expect(classifyFundSignal(1000000, 1.2)).toBe('support')
  })

  it('zljzb 缺失时仅用 zlje', () => {
    expect(classifyFundSignal(1000000, null)).toBe('support')
    expect(classifyFundSignal(1000000, undefined)).toBe('support')
  })

  it('zlje<=0 → 资金背离；zlje 缺失 → noData', () => {
    expect(classifyFundSignal(0, 0.5)).toBe('divergent')
    expect(classifyFundSignal(-500000, 0.5)).toBe('divergent')
    expect(classifyFundSignal(null, 0.5)).toBe('noData')
    expect(classifyFundSignal(undefined, 0.5)).toBe('noData')
  })

  it('zlje>0 但 zljzb<=0（数据不一致）→ 背离', () => {
    expect(classifyFundSignal(1000000, 0)).toBe('divergent')
    expect(classifyFundSignal(1000000, -0.1)).toBe('divergent')
  })
})

describe('classifyVolumePriceQuadrant（四象限）', () => {
  it('涨跌 × 放缩量交叉', () => {
    expect(classifyVolumePriceQuadrant(3, 4, MEDIAN)).toBe('rise_volume') // 涨+放量
    expect(classifyVolumePriceQuadrant(3, 0.5, MEDIAN)).toBe('rise_shrink') // 涨+缩量
    expect(classifyVolumePriceQuadrant(-3, 4, MEDIAN)).toBe('fall_volume') // 跌+放量
    expect(classifyVolumePriceQuadrant(-3, 0.5, MEDIAN)).toBe('fall_shrink') // 跌+缩量
    expect(classifyVolumePriceQuadrant(3, 2, MEDIAN)).toBe('rise_volume') // 2 ≥ 1.05 放量（绝对阈值）
  })

  it('缺失/无效 → null', () => {
    expect(classifyVolumePriceQuadrant(null, 4, MEDIAN)).toBeNull()
    expect(classifyVolumePriceQuadrant(3, null, MEDIAN)).toBeNull()
    expect(classifyVolumePriceQuadrant(3, 4, null)).toBe('rise_volume') // median 仅参考，不参与分类
    expect(classifyVolumePriceQuadrant(0, 4, MEDIAN)).toBe('normal') // 平盘无方向
  })
})

describe('getVolumePriceQuadrantLabel', () => {
  it('四象限 + 常态 + 缺失标签', () => {
    expect(getVolumePriceQuadrantLabel('rise_volume')).toBe('放量上涨')
    expect(getVolumePriceQuadrantLabel('rise_shrink')).toBe('缩量上涨')
    expect(getVolumePriceQuadrantLabel('fall_volume')).toBe('放量下跌')
    expect(getVolumePriceQuadrantLabel('fall_shrink')).toBe('缩量下跌')
    expect(getVolumePriceQuadrantLabel('normal')).toBe('量能常态')
    expect(getVolumePriceQuadrantLabel(null)).toBe('--')
  })
})

describe('computeVolumePriceScore（量价综合评估值，缩量涨停最优/过度放量出货）', () => {
  it('缩量涨停 + 正常流入 → 93（主板 10%：50+15+25+3）', () => {
    const r = computeVolumePriceScore({ change: 9.97, volumeRatio: 0.75, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    expect(r.score).toBe(93)
    expect(r.direction).toBe('up')
    expect(r.reasons).toContain('缩量涨停（封板惜售，好票）')
  })

  it('缩量涨停按板块：创业板 20%（300xxx change 19.97）与北交所 30%（8xxxxx change 29.9）同样判涨停', () => {
    const cyb = computeVolumePriceScore({ code: '300001', change: 19.97, volumeRatio: 0.6, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    const bj = computeVolumePriceScore({ code: '830001', change: 29.9, volumeRatio: 0.6, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    expect(cyb.reasons).toContain('缩量涨停（封板惜售，好票）')
    expect(bj.reasons).toContain('缩量涨停（封板惜售，好票）')
    expect(cyb.score).toBe(93)
    expect(bj.score).toBe(93)
  })

  it('创业板 20% 缩量上涨（未达 20% 涨停）不判涨停', () => {
    const r = computeVolumePriceScore({ code: '300001', change: 12, volumeRatio: 0.6, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    expect(r.reasons).not.toContain('缩量涨停（封板惜售，好票）')
    expect(r.reasons.some((reason) => reason.includes('缩量上涨'))).toBe(true)
  })

  it('缩量上涨（非涨停）+ 流入 → 71（50+4.5+15+1.5）', () => {
    const r = computeVolumePriceScore({ change: 3, volumeRatio: 0.5, median: MEDIAN, zlje: 1000000, zljzb: 0.5 })
    expect(r.score).toBe(71)
    expect(r.direction).toBe('up')
    expect(r.reasons.some((reason) => reason.includes('缩量上涨'))).toBe(true)
  })

  it('温和放量上涨 + 流入 → 69（50+4.5+12.5+1.5）', () => {
    const r = computeVolumePriceScore({ change: 3, volumeRatio: 1.5, median: MEDIAN, zlje: 1000000, zljzb: 0.5 })
    expect(r.score).toBe(69)
    expect(r.direction).toBe('up')
    expect(r.reasons).toContain('放量上涨（量价配合）')
  })

  it('过度放量上涨 + 流出 → 34（出货风险：50+4.5-20-0.6）', () => {
    const r = computeVolumePriceScore({ change: 3, volumeRatio: 3, median: MEDIAN, zlje: -500000, zljzb: -0.2 })
    expect(r.score).toBe(34)
    expect(r.direction).toBe('up')
    expect(r.reasons).toContain('过度放量上涨（疑似出货）')
  })

  it('放量下跌 + 流出 → 25（风险：50-4.5-20-0.6）', () => {
    const r = computeVolumePriceScore({ change: -3, volumeRatio: 4, median: MEDIAN, zlje: -500000, zljzb: -0.2 })
    expect(r.score).toBe(25)
    expect(r.direction).toBe('down')
    expect(r.reasons).toContain('放量下跌（风险）')
  })

  it('缩量下跌 + 流出 → 35（50-4.5-10-0.6）', () => {
    const r = computeVolumePriceScore({ change: -3, volumeRatio: 0.5, median: MEDIAN, zlje: -500000, zljzb: -0.2 })
    expect(r.score).toBe(35)
    expect(r.direction).toBe('down')
  })

  it('异常高净占比（对倒出货）→ 52，不奖反罚（50+4.5+12.5-15）', () => {
    const r = computeVolumePriceScore({ change: 3, volumeRatio: 1.5, median: MEDIAN, zlje: 999999, zljzb: 53.83 })
    expect(r.score).toBe(52)
    expect(r.reasons).toContain('主力净占比异常高（疑似对倒出货）')
  })

  it('量比边界：2.0-2.5 渐扣、>2.5 转出货惩罚', () => {
    const r20 = computeVolumePriceScore({ code: '600001', change: 3, volumeRatio: 2.0, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    const r25 = computeVolumePriceScore({ code: '600001', change: 3, volumeRatio: 2.5, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    const r26 = computeVolumePriceScore({ code: '600001', change: 3, volumeRatio: 2.6, median: MEDIAN, zlje: 1000000, zljzb: 1 })
    expect(r20.breakdown.volume).toBe(15) // vr=2 → +15（温和放量上限）
    expect(r25.breakdown.volume).toBe(10) // vr=2.5 → +10（放量过大渐扣）
    expect(r26.breakdown.volume).toBe(-16) // vr=2.6 → -16（过度放量出货）
  })

  it('净占比边界：>20% 由加分转出货惩罚', () => {
    const r19 = computeVolumePriceScore({ code: '600001', change: 3, volumeRatio: 1.5, median: MEDIAN, zlje: 1000000, zljzb: 19 })
    const r21 = computeVolumePriceScore({ code: '600001', change: 3, volumeRatio: 1.5, median: MEDIAN, zlje: 1000000, zljzb: 21 })
    expect(r19.breakdown.fund).toBe(15) // 19×3 → 封顶 +15
    expect(r21.breakdown.fund).toBeLessThan(0) // 21>20 → 出货惩罚（负分）
  })

  it('平盘无方向 → 无箭头（neutral）', () => {
    const r = computeVolumePriceScore({ change: 0, volumeRatio: 2, median: MEDIAN, zlje: 1000000, zljzb: 0.5 })
    expect(r.direction).toBe('neutral')
    expect(r.score).toBe(52) // 50+0+0+1.5（平盘 quadrant=normal，量价 0 分）
  })

  it('量价数据不足 → score null（不伪造）', () => {
    const r = computeVolumePriceScore({ change: 3, volumeRatio: null, median: null, zlje: null, zljzb: null })
    expect(r.score).toBeNull()
    expect(r.direction).toBeNull()
    expect(r.reasons.some((reason) => reason.includes('量价数据不足'))).toBe(true)
  })

  it('score 始终 clamp 到 0-100', () => {
    const max = computeVolumePriceScore({ change: 9, volumeRatio: 9, median: MEDIAN, zlje: 999999, zljzb: 9 })
    const min = computeVolumePriceScore({ change: -9, volumeRatio: 0.1, median: MEDIAN, zlje: -999999, zljzb: -9 })
    expect(max.score).toBeLessThanOrEqual(100)
    expect(min.score).toBeGreaterThanOrEqual(0)
  })
})
