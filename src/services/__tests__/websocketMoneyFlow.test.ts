import { afterEach, describe, expect, it, vi } from 'vitest'

import { webSocketService } from '../websocket'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { refreshScheduler, refreshTaskRegistry } from '../refresh/RefreshTaskRuntime'

function emitBridgeMessage(payload: Record<string, unknown>) {
  ;(webSocketService as any).handleMessage({ data: JSON.stringify(payload) })
}

describe('webSocketService unified money flow boundary', () => {
  afterEach(() => {
    refreshScheduler.stopTask('websocket.staleCheck')
    refreshTaskRegistry.resetRuntimeState()
    vi.useRealTimers()
  })

  it('ignores moneyFlow embedded in bridge full_state', () => {
    emitBridgeMessage({
      type: 'full_state',
      quotes: [{ code: '000001', lastPrice: 11, changePct: 3, volume: 2, amount: 22 }],
      moneyFlow: [{ code: '000001', zlje: 8800, moneyFlowSource: 'tdx_transaction' }],
    })

    expect(webSocketService.getLatestQuote('000001')).toEqual(
      expect.objectContaining({ code: '000001', lastPrice: 11 }),
    )
    expect(webSocketService.getLatestQuote('000001')).not.toHaveProperty('zlje')
  })

  it('does not publish bridge money_flow_patch', () => {
    const events: any[] = []
    const unsubscribe = EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, payload => events.push(payload))
    try {
      emitBridgeMessage({
        type: 'money_flow_patch',
        items: [{ code: '000001', zlje: 9900, moneyFlowSource: 'tdx_transaction' }],
      })
      expect(events).toHaveLength(0)
    } finally {
      unsubscribe()
    }
  })

  it('still updates provider status from l2_status messages', () => {
    emitBridgeMessage({
      type: 'l2_status',
      l2: { provider: 'qmt', enabled: true, status: 'empty_l2_data', fallbackActive: true },
    })
    expect(webSocketService.getStatus().l2).toEqual(
      expect.objectContaining({ provider: 'qmt', status: 'empty_l2_data' }),
    )
  })

  it('records stale checks through the shared refresh scheduler', async () => {
    vi.useFakeTimers()
    ;(webSocketService as any).stopStaleMonitor()
    ;(webSocketService as any).state = {
      ...(webSocketService as any).state,
      status: 'connected',
      lastMessageTime: Date.now() - 20_000,
      lastHeartbeatTime: null,
      fallbackActive: false,
      transport: 'ws',
    }

    ;(webSocketService as any).startStaleMonitor()
    await vi.advanceTimersByTimeAsync(500)

    expect(webSocketService.getStatus()).toMatchObject({
      status: 'stale',
      fallbackActive: true,
      transport: 'http',
    })
    expect(refreshTaskRegistry.getTask('websocket.staleCheck')).toMatchObject({
      running: false,
      lastRunAt: expect.any(Number),
      lastSuccessAt: expect.any(Number),
      lastError: null,
      successCount: 1,
      source: 'scheduler',
    })
  })
})
