import { afterEach, describe, expect, it, vi } from 'vitest'

const registryCalls: Array<{ owner: string; codes: string[]; priorityCodes?: string[] }> = []
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
    setOwnerCodes: (owner: string, codes: string[], priorityCodes?: string[]) =>
      registryCalls.push({ owner, codes, priorityCodes }),
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
      {
        owner: 'dataLoader.hotlist',
        codes: ['300001', '600001'],
        // 均匀轮转（2026-08-11 方案 A）：不再上报 priorityCodes
        priorityCodes: undefined,
      },
    ])
    expect(webSocketService.setHotPool).not.toHaveBeenCalled()
    coordinator.destroy()
  })

  it('submits all codes without priority layering (uniform rotation)', () => {
    for (let index = 1; index <= 40; index += 1) {
      const code = String(index).padStart(6, '0')
      stocks.push({ code, rank: index, compRank: index })
    }
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(stocks.map((stock) => stock.code)),
      flushDelay: 1,
    })

    coordinator.syncRealtimeSubscription()

    const call = registryCalls[0]
    // 均匀轮转：全列表统一上报，无 P0/P1 分级
    expect(call.priorityCodes).toBeUndefined()
    expect(call.codes).toHaveLength(40)
    expect(call.codes?.[0]).toBe('000001')
    expect(call.codes?.[39]).toBe('000040')
    coordinator.destroy()
  })

  it('submits full list without P0/P1 split', () => {
    for (let index = 1; index <= 60; index += 1) {
      const code = String(index).padStart(6, '0')
      stocks.push({ code, rank: index, compRank: index })
    }
    const coordinator = new RealtimeQuoteCoordinator({
      getHotCodes: () => new Set(stocks.map((stock) => stock.code)),
      flushDelay: 1,
    })

    coordinator.syncRealtimeSubscription()

    const call = registryCalls[0]
    // 60 只全部上报（compRank 排序稳定），无 P0/P1 划分
    expect(call.priorityCodes).toBeUndefined()
    expect(call.codes).toHaveLength(60)
    expect(call.codes?.[0]).toBe('000001')
    expect(call.codes?.[59]).toBe('000060')
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
      { code: '000001', lastPrice: 10, zlje: 99, moneyFlowSource: 'tdx_transaction', moneyFlowEstimated: true },
    ])
    vi.advanceTimersByTime(10)

    expect(vi.mocked(dataLayer.applyRealtimeQuoteBatch)).toHaveBeenCalledWith([
      expect.objectContaining({ code: '000001', price: 10, zlje: undefined }),
    ])
    coordinator.destroy()
    vi.useRealTimers()
  })
})
