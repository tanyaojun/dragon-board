import { describe, expect, it } from 'vitest'

import {
  classifyVolumeRatio,
  toFiniteNumber,
  volumeRatioStateLabel,
} from '@/utils/volumeRatio'
import { ALERT_THRESHOLDS } from '@/config/constants'

const UP = ALERT_THRESHOLDS.VOLUME_RATIO_ABSOLUTE.UP
const DOWN = ALERT_THRESHOLDS.VOLUME_RATIO_ABSOLUTE.DOWN

describe('classifyVolumeRatio（3 日量比绝对阈值：>1 放量、<1 缩量）', () => {
  it('量比 ≥ 1.05 判定为放量（超过 3 日同期均量）', () => {
    expect(classifyVolumeRatio(3.0, 2.0)).toBe('up')
    expect(classifyVolumeRatio(UP, undefined)).toBe('up')
    expect(classifyVolumeRatio(1.11, 2.0)).toBe('up') // 盛达资源放量涨停 vr=1.11
    expect(classifyVolumeRatio(2.6, 1.74)).toBe('up')
  })

  it('量比 ≤ 0.95 判定为缩量', () => {
    expect(classifyVolumeRatio(0.8, 2.0)).toBe('down')
    expect(classifyVolumeRatio(DOWN, undefined)).toBe('down')
    expect(classifyVolumeRatio(0.75, 1.04)).toBe('down') // 哈药 vr=0.75
    expect(classifyVolumeRatio(0.6, 1.3)).toBe('down')
  })

  it('1.0 附近（0.95-1.05）为常态', () => {
    expect(classifyVolumeRatio(1.0, 2.0)).toBe('normal')
    expect(classifyVolumeRatio(0.97, 1.04)).toBe('normal')
    expect(classifyVolumeRatio(1.03, 1.04)).toBe('normal')
  })

  it('数值缺失/无效时返回 unknown（基准不再参与判定）', () => {
    expect(classifyVolumeRatio(null, 2.0)).toBe('unknown')
    expect(classifyVolumeRatio(undefined, 2.0)).toBe('unknown')
    expect(classifyVolumeRatio(1.5, null)).toBe('up') // median 仅参考，不参与分类
    expect(classifyVolumeRatio(1.5, undefined)).toBe('up')
    expect(classifyVolumeRatio(0, 2.0)).toBe('unknown')
    expect(classifyVolumeRatio(-1, 2.0)).toBe('unknown')
    expect(classifyVolumeRatio(1.5, 0)).toBe('up')
    expect(classifyVolumeRatio(NaN, 2.0)).toBe('unknown')
  })

  it('label 覆盖四种状态', () => {
    expect(volumeRatioStateLabel('up')).toBe('放量')
    expect(volumeRatioStateLabel('down')).toBe('缩量')
    expect(volumeRatioStateLabel('normal')).toBe('常态')
    expect(volumeRatioStateLabel('unknown')).toContain('基准')
  })
})

describe('toFiniteNumber', () => {
  it('只接受有限数值', () => {
    expect(toFiniteNumber(1.5)).toBe(1.5)
    expect(toFiniteNumber('2.5')).toBe(2.5)
    expect(toFiniteNumber(null)).toBeNull()
    expect(toFiniteNumber(undefined)).toBeNull()
    expect(toFiniteNumber(NaN)).toBeNull()
    expect(toFiniteNumber(Infinity)).toBeNull()
  })
})
