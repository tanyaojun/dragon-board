import { describe, expect, it, vi } from 'vitest'

import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { ThemeFundStreamService } from '../themeFundStream'

describe('ThemeFundStreamService', () => {
  it('publishes ths_main_monitor rows and rejects version rollback', () => {
    const service = new ThemeFundStreamService()
    const events: any[] = []
    const unsubscribe = EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, payload => events.push(payload))

    try {
      ;(service as any).handlePayload({
        type: 'fund_patch',
        version: 8,
        items: [{ code: '000001', zlje: 12.5, version: 8, moneyFlowSource: 'ths_main_monitor' }],
      })
      ;(service as any).handlePayload({
        type: 'fund_patch',
        version: 7,
        items: [{ code: '000001', zlje: 99, version: 7, moneyFlowSource: 'ths_main_monitor' }],
      })

      expect(events).toHaveLength(1)
      expect(events[0].items[0]).toEqual(expect.objectContaining({ code: '000001', zlje: 12.5 }))
    } finally {
      unsubscribe()
    }
  })

  it('rejects abandoned dashboard fund sources', () => {
    const service = new ThemeFundStreamService()
    const listener = vi.fn()
    const unsubscribe = EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, listener)

    try {
      ;(service as any).handlePayload({
        type: 'fund_full_state',
        version: 1,
        items: [
          { code: '000001', zlje: 1, version: 1, moneyFlowSource: 'tdx_transaction' },
          { code: '000002', zlje: 2, version: 1, moneyFlowSource: 'ths_l2' },
          { code: '000003', zlje: 3, version: 1, moneyFlowSource: 'qmt_l2' },
        ],
      })
      expect(listener).not.toHaveBeenCalled()
    } finally {
      unsubscribe()
    }
  })

  it('does not let a replacement full-state roll back a code version', () => {
    const service = new ThemeFundStreamService()
    const events: any[] = []
    const unsubscribe = EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, payload => events.push(payload))

    try {
      ;(service as any).handlePayload({
        type: 'fund_patch',
        items: [{ code: '000001', zlje: 8, version: 8, moneyFlowSource: 'ths_main_monitor' }],
      })
      ;(service as any).handlePayload({
        type: 'fund_full_state',
        items: [{ code: '000001', zlje: 1, version: 1, moneyFlowSource: 'ths_main_monitor' }],
      })

      expect(events).toHaveLength(1)
      expect(events[0].items[0]).toEqual(expect.objectContaining({ zlje: 8, version: 8 }))
    } finally {
      unsubscribe()
    }
  })

  it('sends market owner codes separately from connection priority codes', () => {
    const service = new ThemeFundStreamService()
    const send = vi.fn()
    ;(service as any).socket = { send }
    ;(service as any).marketCodes = ['000001']
    ;(service as any).priorityCodes = ['600000']

    ;(service as any).sendSubscription()

    expect(send).toHaveBeenCalledWith(JSON.stringify({
      marketCodes: ['000001'],
      priorityCodes: ['600000'],
    }))
  })
})
