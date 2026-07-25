import { describe, expect, it } from 'vitest'

import { getMoneyFlowSourceRank, shouldApplyMoneyFlowUpdate } from '../moneyFlowSourcePriority'

describe('moneyFlowSourcePriority', () => {
  it('accepts only ths_main_monitor for dashboard money flow', () => {
    const row = { moneyFlowSource: 'ths_main_monitor' }

    expect(getMoneyFlowSourceRank(row)).toBeGreaterThan(0)
    expect(shouldApplyMoneyFlowUpdate(undefined, row)).toBe(true)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'tdx_transaction' })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'ths_l2', moneyFlowEstimated: false })).toBe(0)
    expect(getMoneyFlowSourceRank({ moneyFlowSource: 'qmt_l2', moneyFlowEstimated: false })).toBe(0)
  })
})
