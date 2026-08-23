import { describe, expect, it } from 'vitest'

import { COMPREHENSIVE_WEIGHTS, OPTIMAL_TURNOVER, TURNOVER_SIGMA } from '../config'

describe('五维综合权重金标准（前后端一致性防漂移锁）', () => {
  // 五维综合排名 compScore/compRank 已后端化（backend/analysis/ranktrend/comprehensive_rank.py 为 golden），
  // 前端这些常量是历史合同/只读。此测试锁定前端值与后端一致，任一端改动不同步即红。
  // 后端对应金标准断言见 quant-board/tests/test_comprehensive_rank.py::test_weights_aligned_with_frontend_golden。
  it('与后端 comprehensive_rank 权重/参数一致', () => {
    expect(COMPREHENSIVE_WEIGHTS.HOT_RANK).toBe(0.45)
    expect(COMPREHENSIVE_WEIGHTS.MONEY_RATIO).toBe(0.25)
    expect(COMPREHENSIVE_WEIGHTS.FUND_PENETRATION).toBe(0.1)
    expect(COMPREHENSIVE_WEIGHTS.TURNOVER_RATE).toBe(0.12)
    expect(COMPREHENSIVE_WEIGHTS.VOLUME).toBe(0.08)
    expect(OPTIMAL_TURNOVER).toBe(15)
    expect(TURNOVER_SIGMA).toBe(10)
  })
})
