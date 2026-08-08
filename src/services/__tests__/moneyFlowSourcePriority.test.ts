import { describe, expect, it } from 'vitest'

import {
  getMoneyFlowSourceRank,
  isDashboardFundSource,
  shouldApplyMoneyFlowUpdate,
} from '../moneyFlowSourcePriority'

describe('moneyFlowSourcePriority', () => {
  it('accepts only dashboard fund sources for money flow', () => {
    const l2 = { moneyFlowSource: 'ths_main_monitor' }
    const seed = { moneyFlowSource: 'eastmoney_seed', moneyFlowEstimated: true }
    const legacyWebSeed = { moneyFlowSource: 'ths_web_seed', moneyFlowEstimated: true }

    expect(getMoneyFlowSourceRank(l2)).toBeGreaterThan(0)
    expect(getMoneyFlowSourceRank(seed)).toBeGreaterThan(0)
    expect(getMoneyFlowSourceRank(legacyWebSeed)).toBeGreaterThan(0)
    expect(getMoneyFlowSourceRank(seed)).toBeLessThan(getMoneyFlowSourceRank(l2))
    expect(shouldApplyMoneyFlowUpdate(undefined, l2)).toBe(true)
    expect(shouldApplyMoneyFlowUpdate(undefined, seed)).toBe(true)
    // L1 分笔自算不完整（非全日分笔），不作为资金列来源，仅 bridge /health 诊断
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'tdx_transaction' })).toBe(0)
    // legacy eastmoney（无后缀）/ ths_l2 / qmt_l2 保持 rank 0
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'eastmoney' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'ths_l2', moneyFlowEstimated: false })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'qmt_l2', moneyFlowEstimated: false })).toBe(0)
  })

  it('lower-rank seed never overrides higher-rank L2', () => {
    const l2 = { moneyFlowSource: 'ths_main_monitor' }
    const seed = { moneyFlowSource: 'ths_web_seed', moneyFlowEstimated: true }

    expect(shouldApplyMoneyFlowUpdate(l2, seed)).toBe(false)
    expect(shouldApplyMoneyFlowUpdate(seed, l2)).toBe(true)
  })

  it('isDashboardFundSource accepts only known sources', () => {
    expect(isDashboardFundSource({ moneyFlowSource: 'ths_main_monitor' })).toBe(true)
    expect(isDashboardFundSource({ moneyFlowSource: 'eastmoney_seed' })).toBe(true)
    expect(isDashboardFundSource({ moneyFlowSource: 'ths_web_seed' })).toBe(true)
    expect(isDashboardFundSource({ moneyFlowSource: 'tdx_transaction' })).toBe(false)
    expect(isDashboardFundSource({ moneyFlowSource: 'eastmoney' })).toBe(false)
    expect(isDashboardFundSource({ moneyFlowSource: 'ths_l2' })).toBe(false)
    expect(isDashboardFundSource(null)).toBe(false)
    expect(isDashboardFundSource(undefined)).toBe(false)
  })
})
