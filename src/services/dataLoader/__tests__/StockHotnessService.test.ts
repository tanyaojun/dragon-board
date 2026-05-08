import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../DataLayer'
import { StockHotnessService } from '../StockHotnessService'

let emittedEvents = 0

vi.mock('@/utils/eventManager', () => ({
  EventManager: {
    emit: vi.fn(() => {
      emittedEvents++
    }),
  },
}))

describe('StockHotnessService', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    emittedEvents = 0
    vi.restoreAllMocks()
  })

  it('keeps hotness recalculation as calculation-only by default', () => {
    dataLayer.setMergedStocks([
      { code: '000001', name: '平安银行', sources: ['eastmoney'], rank: 1 } as any,
    ])
    emittedEvents = 0

    const service = new StockHotnessService()
    const stocks = service.recalculateStockHotness(8)

    expect(stocks).toEqual([
      expect.objectContaining({
        code: '000001',
        hotness: expect.any(Number),
      }),
    ])
    expect(emittedEvents).toBe(0)
  })
})
