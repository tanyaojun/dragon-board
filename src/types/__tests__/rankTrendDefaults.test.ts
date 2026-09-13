import { describe, expect, it } from 'vitest'

import {
  cloneDefaultRankTrendRuntimeConfig,
  DEFAULT_RANK_TREND_RUNTIME_CONFIG,
  normalizeRankTrendRuntimeConfig,
} from '../rankTrendDefaults'

const WEIGHT_FIELDS = [
  'directionWeight',
  'accelerationWeight',
  'crossWeight',
  'macdWeight',
  'maWeight',
] as const

describe('RankTrend 决策合成五权重（2026-09-13 阶段 21.7 五因子化合同锁）', () => {
  // py 对应锚：quant-board/tests/test_ranktrend_five_factor_decision.py
  // 默认值 = 设计值（0.30/0.25/0.20/0.25 + MA 0.25）经五权重归一化的精确值，和恒=1，
  // 与 py RankTrendConfig 默认值逐位对齐（= 阶段 20.4 ma_join 实证口径）。
  it('默认五权重为归一化精确值且和为 1', () => {
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.directionWeight).toBe(0.24)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.accelerationWeight).toBe(0.2)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.crossWeight).toBe(0.16)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.macdWeight).toBe(0.2)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.maWeight).toBe(0.2)
    const sum = WEIGHT_FIELDS.reduce((total, field) => total + DEFAULT_RANK_TREND_RUNTIME_CONFIG[field], 0)
    expect(sum).toBeCloseTo(1, 6)
  })

  it('默认配置过归一化为幂等（noop）', () => {
    const normalized = normalizeRankTrendRuntimeConfig(cloneDefaultRankTrendRuntimeConfig())
    for (const field of WEIGHT_FIELDS) {
      expect(normalized[field]).toBe(DEFAULT_RANK_TREND_RUNTIME_CONFIG[field])
    }
  })

  it('maWeight 显式置 0 = 关闭 MA 分量，其余四权重按比例归一化回填旧四因子口径', () => {
    const disabled = normalizeRankTrendRuntimeConfig(cloneDefaultRankTrendRuntimeConfig(), {
      maWeight: 0,
    })
    expect(disabled.maWeight).toBe(0)
    expect(disabled.directionWeight).toBeCloseTo(0.3, 6)
    expect(disabled.accelerationWeight).toBeCloseTo(0.25, 6)
    expect(disabled.crossWeight).toBeCloseTo(0.2, 6)
    expect(disabled.macdWeight).toBeCloseTo(0.25, 6)
  })

  it('clone 深拷贝含 maWeight 且与默认逐位一致', () => {
    const clone = cloneDefaultRankTrendRuntimeConfig()
    expect(clone.maWeight).toBe(0.2)
    for (const field of WEIGHT_FIELDS) {
      expect(clone[field]).toBe(DEFAULT_RANK_TREND_RUNTIME_CONFIG[field])
    }
  })
})
