import { describe, expect, it, vi } from 'vitest'

import { webSocketService } from '../websocket'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'

function emitBridgeMessage(payload: Record<string, unknown>) {
  ;(webSocketService as any).handleMessage({
    data: JSON.stringify(payload),
  })
}

describe('webSocketService money flow patches', () => {
  it('updates provider status from l2_status messages', () => {
    emitBridgeMessage({
      type: 'l2_status',
      serverTs: 1000,
      l2: {
        provider: 'qmt',
        enabled: true,
        status: 'empty_l2_data',
        message: 'QMT returned no Level2 rows',
        fallbackActive: true,
        depthLevelCount: 0,
      },
    })

    expect(webSocketService.getStatus().l2).toEqual(
      expect.objectContaining({
        provider: 'qmt',
        status: 'empty_l2_data',
        fallbackActive: true,
      }),
    )
  })

  it('preserves realtime quote fields when full_state and money_flow_patch carry only fund flow data', () => {
    const quotePatchEvents: any[] = []
    const unsubscribe = EventManager.on(AppEvents.WEBSOCKET.QUOTE_PATCH, (payload) => {
      quotePatchEvents.push(payload)
    })

    try {
      emitBridgeMessage({
        type: 'full_state',
        serverTs: 1000,
        quotes: [
          {
            code: '000001',
            lastPrice: 11,
            changePct: 3,
            volume: 2000,
            amount: 22000,
          },
        ],
        moneyFlow: [
          {
            code: '000001',
            zlje: 8800,
            cddje: 6600,
            moneyFlowSource: 'qmt_l2',
            moneyFlowEstimated: false,
            capitalFlowSource: 'broker_l2',
            capitalFlowConfidence: 'high',
          },
        ],
      })

      expect(webSocketService.getLatestQuote('000001')).toEqual(
        expect.objectContaining({
          code: '000001',
          lastPrice: 11,
          changePct: 3,
          volume: 2000,
          amount: 22000,
          zlje: 8800,
          cddje: 6600,
          moneyFlowSource: 'qmt_l2',
        }),
      )

      emitBridgeMessage({
        type: 'money_flow_patch',
        serverTs: 1100,
        items: [
          {
            code: '000001',
            zlje: 9900,
            cddje: 7700,
            moneyFlowSource: 'qmt_l2',
            moneyFlowEstimated: false,
            capitalFlowSource: 'broker_l2',
            capitalFlowConfidence: 'high',
          },
        ],
      })

      const latest = webSocketService.getLatestQuote('000001')
      expect(latest).toEqual(
        expect.objectContaining({
          lastPrice: 11,
          changePct: 3,
          volume: 2000,
          amount: 22000,
          zlje: 9900,
          cddje: 7700,
        }),
      )
      expect(quotePatchEvents.at(-1)?.items?.[0]).toEqual(
        expect.objectContaining({
          lastPrice: 11,
          amount: 22000,
          zlje: 9900,
        }),
      )
    } finally {
      unsubscribe()
      vi.clearAllMocks()
    }
  })
})
