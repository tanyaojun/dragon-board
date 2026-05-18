import { afterEach, describe, expect, it, vi } from 'vitest'

import { apiService } from '../apiService'
import { buildThsLimitUpPoolEvidence, dragonBreathAnalyzer } from '../DragonBreathAnalyzer'

describe('buildThsLimitUpPoolEvidence', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns degraded empty evidence when ths pool response is unavailable', () => {
    const evidence = buildThsLimitUpPoolEvidence(null)

    expect(evidence.degraded).toBe(true)
    expect(evidence.errors).toEqual([
      {
        pool: 'all',
        errorCode: 'THS_POOL_UNAVAILABLE',
        message: '同花顺涨停池不可用',
      },
    ])
    expect(evidence.failedCount).toBe(0)
    expect(evidence.drawdownCount).toBe(0)
  })

  it('returns degraded empty evidence when the ths pool request fails', async () => {
    vi.spyOn(apiService, 'getThsLimitUpPools').mockRejectedValue(new Error('upstream timeout'))

    const evidence = await (dragonBreathAnalyzer as any).fetchThsLimitUpPoolEvidence()

    expect(evidence.degraded).toBe(true)
    expect(evidence.failedCount).toBe(0)
    expect(evidence.drawdownCount).toBe(0)
  })

  it('normalizes THS pool counts and drawdown risk facts', () => {
    const evidence = buildThsLimitUpPoolEvidence({
      date: '20260518',
      timestamp: 1779066000000,
      degraded: true,
      errors: [{ pool: 'rushing', message: 'timeout' }],
      pools: {
        one: { total: 41, items: [{ code: '600001' }] },
        two: { items: [{ code: '600002' }, { code: '600003' }] },
        three: { total: 3 },
        four: { total: 1 },
        high: { total: 5 },
        failed: { total: 11 },
        rushing: { total: 8 },
        drawdown: {
          items: [
            { code: '600010', max_drawdown: -8.5 },
            { code: '600011', max_drawdown: '-12.4' },
            { code: '600012', maxDrawdown: -6.1 },
          ],
        },
      },
    })

    expect(evidence.poolCounts).toMatchObject({
      one: 41,
      two: 2,
      three: 3,
      four: 1,
      high: 5,
      failed: 11,
      rushing: 8,
      drawdown: 3,
    })
    expect(evidence.failedCount).toBe(11)
    expect(evidence.rushingCount).toBe(8)
    expect(evidence.drawdownCount).toBe(3)
    expect(evidence.drawdownRiskLabel).toBe('涨停股回撤榜')
    expect(evidence.maxDrawdown).toBe(-12.4)
    expect(evidence.avgDrawdown).toBeCloseTo(-9)
    expect(evidence.degraded).toBe(true)
    expect(evidence.errors).toEqual([{ pool: 'rushing', message: 'timeout' }])
  })
})
