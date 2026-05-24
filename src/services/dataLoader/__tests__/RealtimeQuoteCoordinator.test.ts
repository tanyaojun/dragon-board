import { afterEach, describe, expect, it, vi } from 'vitest'

const registryCalls: Array<{ owner: string; codes: string[] }> = []
const clearedOwners: string[] = []
const stocks: any[] = []

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: () => stocks,
    applyRealtimeQuoteBatch: vi.fn(),
    updateDepth10Batch: vi.fn(),
    updateL2SummaryBatch: vi.fn(),
    updateRecentTicksBatch: vi.fn(),
    getRecentTicks: vi.fn(() => []),
  },
}))

vi.mock('../../realtime/RealtimeSubscriptionRegistry', () => ({
  realtimeSubscriptionRegistry: {
    setOwnerCodes: (owner: string, codes: string[]) => registryCalls.push({ owner, codes }),
    clearOwner: (owner: string) => clearedOwners.push(owner),
  },
}))

vi.mock('../../websocket', () => ({
  webSocketService: {
    setHotPool: vi.fn(),
    getStatus: vi.fn(() => ({ subscribedCount: 0 })),
    isTdxRealtimeHealthy: vi.fn(() => false),
  },
}))

import { RealtimeQuoteCoordinator } from '../RealtimeQuoteCoordinator'
import { webSocketService } from '../../websocket'

describe('RealtimeQuoteCoordinator', () => {
  afterEach(() => {
    registryCalls.length = 0
    clearedOwners.length = 0
    stocks.length = 0
    vi.clearAllMocks()
  })

  it('registers hotlist subscription codes through the shared realtime subscription registry', () => {
    stocks.push(
      { code: '600001', rank: 2, compRank: 2 },
      { code: '300001', rank: 1, compRank: 1 },
      { code: '688001', rank: 3, compRank: 3 },
    )
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(['600001', '300001']),
      flushDelay: 1,
    })

    coordinator.syncRealtimeSubscription()

    expect(registryCalls).toEqual([
      { owner: 'dataLoader.hotlist', codes: ['300001', '600001'] },
    ])
    expect(webSocketService.setHotPool).not.toHaveBeenCalled()
    coordinator.destroy()
  })

  it('clears the hotlist realtime subscription owner when destroyed', () => {
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(['600001']),
      flushDelay: 1,
    })

    coordinator.destroy()

    expect(clearedOwners).toEqual(['dataLoader.hotlist'])
  })
})
