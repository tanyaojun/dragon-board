import { describe, expect, it, vi } from 'vitest'

import { RealtimeSubscriptionRegistry } from '../RealtimeSubscriptionRegistry'

describe('RealtimeSubscriptionRegistry', () => {
  it('merges subscription codes from multiple owners before applying to the realtime bridge', () => {
    const apply = vi.fn()
    const registry = new RealtimeSubscriptionRegistry({ apply })

    registry.setOwnerCodes('dataLoader.hotlist', ['600001', '000002.SZ', '600001'])
    registry.setOwnerCodes('eventRadar.tdxBlock', ['300001', '000002'])

    expect(registry.getOwnerCodes('dataLoader.hotlist')).toEqual(['000002', '600001'])
    expect(registry.getOwnerCodes('eventRadar.tdxBlock')).toEqual(['000002', '300001'])
    expect(registry.getMergedCodes()).toEqual(['000002', '300001', '600001'])
    expect(apply).toHaveBeenLastCalledWith(['000002', '300001', '600001'])
  })

  it('clears one owner without removing subscriptions owned by another owner', () => {
    const apply = vi.fn()
    const registry = new RealtimeSubscriptionRegistry({ apply })

    registry.setOwnerCodes('dataLoader.hotlist', ['600001', '000002'])
    registry.setOwnerCodes('eventRadar.tdxBlock', ['300001'])
    registry.clearOwner('dataLoader.hotlist')

    expect(registry.getMergedCodes()).toEqual(['300001'])
    expect(apply).toHaveBeenLastCalledWith(['300001'])
  })

  it('adds expanded theme stocks only to the fund stream', () => {
    const apply = vi.fn()
    const applyFunds = vi.fn()
    const registry = new RealtimeSubscriptionRegistry({ apply, applyFunds })

    registry.setOwnerCodes('dataLoader.hotlist', ['000001'])
    registry.setFundOwnerCodes('theme.AI', ['600000'])

    expect(apply).toHaveBeenLastCalledWith(['000001'])
    expect(applyFunds).toHaveBeenLastCalledWith(['000001'], ['600000'])
    expect(registry.getMergedCodes()).toEqual(['000001'])
    expect(registry.getMergedFundCodes()).toEqual(['000001', '600000'])
  })
})
