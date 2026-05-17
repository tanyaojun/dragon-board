import { describe, expect, it, vi } from 'vitest'

vi.mock('@/utils/time', () => ({
  isTradingTime: vi.fn(() => true),
}))

import { dragonBreathAnalyzer } from '../DragonBreathAnalyzer'
import { refreshResourceLocks } from '../refresh/RefreshResourceLocks'

describe('DragonBreathAnalyzer resource lock integration', () => {
  it('holds the dragon-breath resource while market breath analysis is running', async () => {
    const fetchAllData = vi.spyOn(dragonBreathAnalyzer as any, 'fetchAllData').mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          setTimeout(resolve, 10)
        }),
    )

    try {
      const run = dragonBreathAnalyzer.analyzeMarketBreath(true)
      await vi.waitFor(() => {
        expect(refreshResourceLocks.isLocked('dragon-breath')).toBe(true)
      })

      await run

      expect(fetchAllData).toHaveBeenCalledTimes(1)
      expect(refreshResourceLocks.isLocked('dragon-breath')).toBe(false)
    } finally {
      fetchAllData.mockRestore()
    }
  })
})
