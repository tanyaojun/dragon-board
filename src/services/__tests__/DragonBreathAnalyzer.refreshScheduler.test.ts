import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../utils/time', () => ({
  isTradingTime: vi.fn(() => true),
}))

import { dragonBreathAnalyzer } from '../DragonBreathAnalyzer'

describe('DragonBreathAnalyzer refresh scheduler integration', () => {
  beforeEach(async () => {
    dragonBreathAnalyzer.stopAutoRefresh()
    const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')
    refreshTaskRegistry.resetRuntimeState()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    dragonBreathAnalyzer.stopAutoRefresh()
    vi.useRealTimers()
  })

  it('records automatic breath refresh through the shared scheduler', async () => {
    vi.useFakeTimers()
    const analyze = vi
      .spyOn(dragonBreathAnalyzer, 'analyzeMarketBreath')
      .mockResolvedValue(true)
    const { refreshTaskRegistry } = await import('../refresh/RefreshTaskRuntime')

    dragonBreathAnalyzer.startAutoRefresh(1000)
    await vi.advanceTimersByTimeAsync(1000)

    expect(analyze).toHaveBeenCalledWith(false)
    expect(refreshTaskRegistry.getTask('dragon.breath')).toMatchObject({
      running: false,
      lastRunAt: expect.any(Number),
      lastSuccessAt: expect.any(Number),
      lastError: null,
      successCount: 1,
      source: 'scheduler',
    })
  })
})
