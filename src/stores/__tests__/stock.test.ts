import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '@/services/DataLayer'
import { AppEvents } from '@/types'
import { EventManager } from '@/utils/eventManager'
import { useStockStore } from '../stock'

vi.mock('@/services/dragon/DragonReviewService', () => ({
  dragonReviewService: {
    getAllLeaders: vi.fn(() => []),
  },
}))

describe('StockStore refresh listeners', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
    EventManager.clearHistory()
  })

  it('does not reload twice when DATA.MERGED and DataLayer stock notification share one version', () => {
    vi.useFakeTimers()
    const store = useStockStore()
    const dispose = store.init()

    try {
      expect(store.version).toBe(0)

      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])
      EventManager.emit(AppEvents.DATA.MERGED, { count: 1 })
      vi.advanceTimersByTime(50)

      expect(store.version).toBe(1)
      expect(store.stocks).toEqual([expect.objectContaining({ code: '000001' })])
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})
