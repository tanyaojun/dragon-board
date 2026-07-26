import { afterEach, describe, expect, it, vi } from 'vitest'

const registryCalls: Array<{ owner: string; codes: string[] }> = []
const clearedOwners: string[] = []
const stocks: any[] = []

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: () => stocks,
    getStock: (code: string) => stocks.find((stock) => stock.code === code),
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
import { dataLayer } from '../../DataLayer'

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

  it('merges THS fund-only and quote patches queued for the same stock', () => {
    vi.useFakeTimers()
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(['000001']),
      flushDelay: 10,
    })

    ;(coordinator as any).queueRealtimeQuotes([
      { code: '000001', zlje: 8, moneyFlowSource: 'ths_main_monitor' },
    ])
    ;(coordinator as any).queueRealtimeQuotes([
      { code: '000001', lastPrice: 10, changePct: 2, volume: 100, amount: 1000 },
    ])
    vi.advanceTimersByTime(10)

    expect(vi.mocked(dataLayer.applyRealtimeQuoteBatch)).toHaveBeenCalledWith([
      expect.objectContaining({ code: '000001', price: 10, zlje: 8 }),
    ])
    coordinator.destroy()
    vi.useRealTimers()
  })

  it('derives main money ratio from THS net inflow and the current turnover when the stream omits it', () => {
    vi.useFakeTimers()
    stocks.push({ code: '000001', turnover: 12_345_678 })
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(['000001']),
      flushDelay: 10,
    })

    ;(coordinator as any).queueRealtimeQuotes([
      { code: '000001', zlje: 315_000, moneyFlowSource: 'ths_main_monitor' },
    ])
    vi.advanceTimersByTime(10)

    expect(vi.mocked(dataLayer.applyRealtimeQuoteBatch)).toHaveBeenCalledWith([
      expect.objectContaining({ code: '000001', zlje: 315_000, zljzb: 2.55 }),
    ])
    coordinator.destroy()
    vi.useRealTimers()
  })

  it('does not project bridge money fields into the dashboard row', () => {
    vi.useFakeTimers()
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(['000001']),
      flushDelay: 10,
    })

    ;(coordinator as any).queueRealtimeQuotes([
      { code: '000001', lastPrice: 10, zlje: 99, moneyFlowSource: 'tdx_transaction' },
    ])
    vi.advanceTimersByTime(10)

    expect(vi.mocked(dataLayer.applyRealtimeQuoteBatch)).toHaveBeenCalledWith([
      expect.objectContaining({ code: '000001', price: 10, zlje: undefined }),
    ])
    coordinator.destroy()
    vi.useRealTimers()
  })
})
