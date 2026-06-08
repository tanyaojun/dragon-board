import { describe, expect, it } from 'vitest'

import { buildFusionStrategyProjection } from '../FusionStrategyProjector'

function createFusionStock(code: string) {
  return {
    code,
    name: `股票${code}`,
    change: 3.2,
    accDelta: 9,
    rankTrend: {
      jump: { direction: 'buy', confidence: 92 },
      technical: {
        signals: { zeroCross: { signal: 'buy' } },
        momentumProfile: { short: 12, mid: 22, long: 11, acceleration: 12, shock: 2, composite: 70 },
      },
      cycle: {
        decision: {
          action: 'allow',
        },
      },
      strategy: {
        candidateTier: 'A_MAIN',
      },
    },
  }
}

describe('FusionStrategyProjector', () => {
  it('does not infer active_holding from manual execution overlay alone', () => {
    const projection = buildFusionStrategyProjection({
      stock: createFusionStock('600001'),
      snapshotType: 'half_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-1',
      frameTime: '2026-06-08T10:00:00+08:00',
      strategyLifecycle: {
        triggered: true,
        hasOpenPosition: false,
      },
      executionOverlay: {
        executed: true,
        entryTime: '2026-06-08T10:30:00+08:00',
        entryPrice: 12.5,
      },
    })

    expect(projection.strategyState).toBe('triggered_wait_entry')
    expect(projection.executionOverlay).toMatchObject({
      executed: true,
      entryTime: '2026-06-08T10:30:00+08:00',
      entryPrice: 12.5,
    })
  })

  it('does not infer closed from execution exit facts when lifecycle has not confirmed closure', () => {
    const projection = buildFusionStrategyProjection({
      stock: createFusionStock('600001'),
      snapshotType: 'quarter_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-2',
      frameTime: '2026-06-08T14:00:00+08:00',
      strategyLifecycle: {
        triggered: true,
        hasOpenPosition: true,
        closed: false,
        entryAt: '2026-06-08T10:30:00+08:00',
      },
      executionOverlay: {
        executed: true,
        entryTime: '2026-06-08T10:30:00+08:00',
        entryPrice: 12.5,
        exitTime: '2026-06-08T13:30:00+08:00',
        exitPrice: 11.8,
      },
    })

    expect(projection.strategyState).toBe('active_holding')
    expect(projection.snapshotType).toBe('quarter_hour')
  })
})
