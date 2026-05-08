import { describe, expect, test, vi } from 'vitest'
import { dataLayer } from '../DataLayer'

describe('DataLayer throttled notifications', () => {
  test('flushes each pending path and keeps only the latest payload per path', () => {
    vi.useFakeTimers()

    try {
      dataLayer.reset()
      const mergedStocks = vi.fn()
      const versionStocks = vi.fn()
      const unsubscribeMergedStocks = dataLayer.subscribe('merged.stocks', mergedStocks)
      const unsubscribeVersionStocks = dataLayer.subscribe('version.stocks', versionStocks)

      dataLayer.setMergedStocks([{ code: '000001', name: 'first' }])
      dataLayer.setMergedStocks([{ code: '000002', name: 'second' }])

      expect(mergedStocks).not.toHaveBeenCalled()
      expect(versionStocks).not.toHaveBeenCalled()

      vi.advanceTimersByTime(50)

      expect(mergedStocks).toHaveBeenCalledTimes(1)
      expect(mergedStocks).toHaveBeenCalledWith([{ code: '000002', name: 'second' }])
      expect(versionStocks).toHaveBeenCalledTimes(1)
      expect(versionStocks).toHaveBeenCalledWith(2)

      unsubscribeMergedStocks()
      unsubscribeVersionStocks()
    } finally {
      dataLayer.reset()
      vi.useRealTimers()
    }
  })
})
