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

  it('does not expose the removed theme fund subscription channel', () => {
    const apply = vi.fn()
    const registry = new RealtimeSubscriptionRegistry({ apply })

    expect('setFundOwnerCodes' in registry).toBe(false)
    expect('clearFundOwner' in registry).toBe(false)
    expect('getMergedFundCodes' in registry).toBe(false)
  })

  it('forwards normal realtime owners to the independent market fund feed', () => {
    const apply = vi.fn()
    const applyMarketFunds = vi.fn()
    const registry = new RealtimeSubscriptionRegistry({ apply, applyMarketFunds })

    registry.setOwnerCodes('dataLoader.hotlist', ['600001', '000002'])
    registry.setOwnerCodes('eventRadar.tdxBlock', ['300001'])

    expect(applyMarketFunds).toHaveBeenLastCalledWith(['000002', '600001'])
    expect('setFundOwnerCodes' in registry).toBe(false)
  })
})
