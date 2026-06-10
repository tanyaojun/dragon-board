import { describe, expect, it } from 'vitest'

import { buildLiveGateCheck, selectFirstBlockingCheck } from '../liveGateCheckBuilder'

describe('liveGateCheckBuilder', () => {
  it('builds a warn check without hard blocking', () => {
    const check = buildLiveGateCheck({
      key: 'change_position',
      label: '涨幅位置',
      status: 'warn',
      hardBlock: false,
      actual: 6.4,
      expected: '< 6 或观察',
      message: '涨幅偏高，进入观察候选',
    })

    expect(check).toMatchObject({
      key: 'change_position',
      status: 'warn',
      hardBlock: false,
      actual: 6.4,
    })
  })

  it('selects the first failed hard block only', () => {
    const warn = buildLiveGateCheck({
      key: 'change_position',
      label: '涨幅位置',
      status: 'warn',
      hardBlock: false,
      actual: 6.4,
      expected: '< 6 或观察',
      message: '涨幅偏高，进入观察候选',
    })
    const block = buildLiveGateCheck({
      key: 'limit_up',
      label: '涨停状态',
      status: 'fail',
      hardBlock: true,
      actual: true,
      expected: '未涨停',
      message: '涨停状态，阻断入场',
    })

    expect(selectFirstBlockingCheck([warn, block])).toBe(block)
    expect(selectFirstBlockingCheck([warn])).toBeUndefined()
  })
})
