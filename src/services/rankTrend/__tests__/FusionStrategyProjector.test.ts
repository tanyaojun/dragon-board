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
      executionStrategy: {
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

  it('maps V5 holding and exit lifecycle fields without deriving them from manual overlay', () => {
    const projection = buildFusionStrategyProjection({
      stock: createFusionStock('600001'),
      snapshotType: 'half_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-exit',
      frameTime: '2026-06-08T14:30:00+08:00',
      strategyLifecycle: {
        triggered: true,
        hasOpenPosition: true,
        exitWatch: true,
        triggerAt: '2026-06-08T10:00:00+08:00',
        entryAt: '2026-06-08T10:30:00+08:00',
        exitAt: '2026-06-08T14:30:00+08:00',
        holdingBars: 8,
        slotIndex: 7,
        maxPositions: 5,
        tPlusOneUnlocked: false,
        entryReason: 'V5 execution A_MAIN 入场',
        exitReason: '生命周期B反对且持仓未盈利',
        strategyEntryPrice: 12.5,
        strategyExitPrice: 11.9,
        strategyReturnPct: -0.048,
      },
      executionOverlay: {
        executed: true,
        entryTime: '2026-06-08T10:30:00+08:00',
        entryPrice: 12.5,
        exitTime: '2026-06-08T14:00:00+08:00',
        exitPrice: 12.1,
      },
    })

    expect(projection).toMatchObject({
      strategyState: 'exit_signaled',
      triggerAt: '2026-06-08T10:00:00+08:00',
      strategyEntryAt: '2026-06-08T10:30:00+08:00',
      strategyExitAt: '2026-06-08T14:30:00+08:00',
      holdingBars: 8,
      slotIndex: 7,
      maxPositions: 5,
      tPlusOneUnlocked: false,
      entryReason: 'V5 execution A_MAIN 入场',
      exitReason: '生命周期B反对且持仓未盈利',
      strategyEntryPrice: 12.5,
      strategyExitPrice: 11.9,
      strategyReturnPct: -0.048,
      executionOverlay: {
        executed: true,
        entryTime: '2026-06-08T10:30:00+08:00',
        exitTime: '2026-06-08T14:00:00+08:00',
      },
    })
  })

  it('uses executionStrategy candidate tier for live projection when it differs from display strategy', () => {
    const stock = createFusionStock('600001')
    stock.rankTrend.strategy = {
      candidateTier: 'N_NEUTRAL',
    }
    ;(stock.rankTrend as any).executionStrategy = {
      candidateTier: 'A_MAIN',
    }

    const projection = buildFusionStrategyProjection({
      stock,
      snapshotType: 'half_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-3',
      frameTime: '2026-06-08T10:00:00+08:00',
      strategyLifecycle: {
        triggered: true,
      },
    })

    expect(projection.candidateTier).toBe('A_MAIN')
  })

  it('does not fall back to display strategy when executionStrategy is missing', () => {
    const stock = createFusionStock('600001')
    delete (stock.rankTrend as any).executionStrategy
    stock.rankTrend.strategy = {
      candidateTier: 'A_MAIN',
    }

    const projection = buildFusionStrategyProjection({
      stock,
      snapshotType: 'half_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-4',
      frameTime: '2026-06-08T10:00:00+08:00',
      strategyLifecycle: {
        triggered: true,
      },
    })

    expect(projection.candidateTier).toBe('N_NEUTRAL')
  })

  it('marks triggered_wait_entry from the V5 execution contract when lifecycle is absent', () => {
    const stock = createFusionStock('600001')
    stock.rankTrend.strategy = {
      candidateTier: 'N_NEUTRAL',
    }
    ;(stock.rankTrend as any).executionStrategy = {
      candidateTier: 'A_MAIN',
    }

    const projection = buildFusionStrategyProjection({
      stock,
      snapshotType: 'half_hour',
      tradingDate: '2026-06-08',
      snapshotId: 'snap-5',
      frameTime: '2026-06-08T10:00:00+08:00',
    })

    expect(projection.strategyState).toBe('triggered_wait_entry')
    expect(projection.candidateTier).toBe('A_MAIN')
  })

  it('projects structured live entry decision for watch candidates', () => {
    const stock = createFusionStock('000970')
    stock.change = 6.5

    const projection = buildFusionStrategyProjection({
      stock,
      snapshotType: 'half_hour',
      tradingDate: '2026-06-10',
      snapshotId: 'snap-watch',
      frameTime: '2026-06-10T10:00:00+08:00',
    })

    expect(projection.strategyState).toBe('idle')
    expect(projection.entryDecision).toMatchObject({
      decisionState: 'watch_candidate',
      label: '观察候选',
      summary: '涨幅偏高，进入观察候选',
    })
    expect(projection.entryDecision?.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'change_position',
          status: 'warn',
          hardBlock: false,
        }),
      ]),
    )
  })
})
