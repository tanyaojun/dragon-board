import { describe, expect, it } from 'vitest'

import {
  getMoneyFlowSourceRank,
  isDashboardFundSource,
  shouldApplyMoneyFlowUpdate,
} from '../moneyFlowSourcePriority'

describe('moneyFlowSourcePriority', () => {
  it('accepts only THS L2 as the dashboard fund source', () => {
    const l2 = { moneyFlowSource: 'ths_main_monitor' }
    const akshare = { moneyFlowSource: 'akshare_ths_individual', moneyFlowEstimated: true }

    expect(getMoneyFlowSourceRank(l2)).toBeGreaterThan(0)
    // akshare 同花顺网页估算源只供 theme_fund 题材聚合（HTTP /api/themes/fund-rows），
    // 不进入行情主页资金列白名单
    expect(getMoneyFlowSourceRank(akshare)).toBe(0)
    expect(shouldApplyMoneyFlowUpdate(undefined, l2)).toBe(true)
    expect(shouldApplyMoneyFlowUpdate(undefined, akshare)).toBe(false)
    // 已废弃/不可用源一律 rank 0（seed 从未启动、东财限流、TDX L1 分笔不完整）
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'eastmoney_seed' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'ths_web_seed' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'tdx_transaction' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'tdx_estimate' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'eastmoney' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'ths_l2' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'qmt_l2' })).toBe(0)
  })

  it('isDashboardFundSource accepts only THS L2', () => {
    expect(isDashboardFundSource({ moneyFlowSource: 'ths_main_monitor' })).toBe(true)
    expect(isDashboardFundSource({ moneyFlowSource: 'akshare_ths_individual' })).toBe(false)
    expect(isDashboardFundSource({ moneyFlowSource: 'eastmoney_seed' })).toBe(false)
    expect(isDashboardFundSource({ moneyFlowSource: 'ths_web_seed' })).toBe(false)
    expect(isDashboardFundSource({ moneyFlowSource: 'tdx_transaction' })).toBe(false)
    expect(isDashboardFundSource(null)).toBe(false)
    expect(isDashboardFundSource(undefined)).toBe(false)
  })

  it('shouldApplyMoneyFlowUpdate only applies for the L2 source', () => {
    const l2 = { moneyFlowSource: 'ths_main_monitor' }
    expect(shouldApplyMoneyFlowUpdate(undefined, l2)).toBe(true)
    expect(shouldApplyMoneyFlowUpdate(l2, l2)).toBe(true)
    expect(shouldApplyMoneyFlowUpdate(l2, { moneyFlowSource: 'akshare_ths_individual' })).toBe(
      false,
    )
    expect(shouldApplyMoneyFlowUpdate({ moneyFlowSource: 'akshare_ths_individual' }, l2)).toBe(
      true,
    )
  })
})
