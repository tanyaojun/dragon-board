import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { dataLayer } from '../../services/DataLayer'
import { AppEvents } from '../../types'
import { EventManager } from '../../utils/eventManager'
import { useUIStore } from '../ui'

describe('UIStore data version', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    dataLayer.reset()
  })

  it('reacts to DataLayer stock version notifications without data events', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])

      expect(uiStore.dataVersion).toBe(0)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
      expect(uiStore.rawStocks).toEqual([expect.objectContaining({ code: '000001' })])
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  it('does not double-count when data event arrives before DataLayer version notification', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])
      EventManager.emit(AppEvents.DATA.MERGED, { count: 1 })

      expect(uiStore.dataVersion).toBe(1)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })

  it('does not double-count when realtime data update arrives before DataLayer version notification', () => {
    vi.useFakeTimers()
    const uiStore = useUIStore()
    const dispose = uiStore.init()

    try {
      dataLayer.setMergedStocks([{ code: '000001', name: '平安银行' }])
      EventManager.emit(AppEvents.DATA.UPDATED, { quotes: 1, source: 'tdx_l2' })

      expect(uiStore.dataVersion).toBe(1)

      vi.advanceTimersByTime(50)

      expect(uiStore.dataVersion).toBe(1)
    } finally {
      dispose()
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})
