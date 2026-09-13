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

describe('RankTrend 决策合成五权重（2026-09-13 阶段 22.8 权重重定义合同锁）', () => {
  // py 对应锚：quant-board/tests/test_ranktrend_five_factor_decision.py
  // 默认值 = 阶段 22 p2_aggressive 实证口径（用户决策落默认），和恒=1，
  // 与 py RankTrendConfig 默认值逐位对齐。
  // 历史口径：阶段 21.7 五因子化落默认 0.24/0.20/0.16/0.20/0.20（设计值归一化）。
  it('默认五权重为实证精确值且和为 1', () => {
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.directionWeight).toBe(0.06)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.accelerationWeight).toBe(0.04)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.crossWeight).toBe(0.24)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.macdWeight).toBe(0.29)
    expect(DEFAULT_RANK_TREND_RUNTIME_CONFIG.maWeight).toBe(0.37)
    const sum = WEIGHT_FIELDS.reduce((total, field) => total + DEFAULT_RANK_TREND_RUNTIME_CONFIG[field], 0)
    expect(sum).toBeCloseTo(1, 6)
  })

  it('默认配置过归一化为幂等（noop）', () => {
    const normalized = normalizeRankTrendRuntimeConfig(cloneDefaultRankTrendRuntimeConfig())
    for (const field of WEIGHT_FIELDS) {
      expect(normalized[field]).toBe(DEFAULT_RANK_TREND_RUNTIME_CONFIG[field])
    }
  })

  it('maWeight 显式置 0 = 关闭 MA 分量，其余四权重按比例归一化回填', () => {
    const disabled = normalizeRankTrendRuntimeConfig(cloneDefaultRankTrendRuntimeConfig(), {
      maWeight: 0,
    })
    expect(disabled.maWeight).toBe(0)
    // 回填值 = 其余四权重（0.06/0.04/0.24/0.29，和=0.63）按比例归一化到和=1，与当前默认比例同构
    expect(disabled.directionWeight).toBeCloseTo(0.06 / 0.63, 6)
    expect(disabled.accelerationWeight).toBeCloseTo(0.04 / 0.63, 6)
    expect(disabled.crossWeight).toBeCloseTo(0.24 / 0.63, 6)
    expect(disabled.macdWeight).toBeCloseTo(0.29 / 0.63, 6)
  })

  it('clone 深拷贝含 maWeight 且与默认逐位一致', () => {
    const clone = cloneDefaultRankTrendRuntimeConfig()
    expect(clone.maWeight).toBe(0.37)
    for (const field of WEIGHT_FIELDS) {
      expect(clone[field]).toBe(DEFAULT_RANK_TREND_RUNTIME_CONFIG[field])
    }
  })
})
