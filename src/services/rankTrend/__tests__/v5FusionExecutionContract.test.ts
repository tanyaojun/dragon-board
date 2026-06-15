import { describe, expect, it } from 'vitest'

import {
  V5_FUSION_DEFAULTS,
  evaluateV5FusionEntry,
  evaluateV5FusionExit,
} from '../v5FusionExecutionContract'

function createStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '002552',
    name: '宝鼎科技',
    change: 5,
    accDelta: 8,
    rankTrend: {
      meta: {
        sampleQuality: {
          status: 'ok',
          snapshotType: 'half_hour',
        },
      },
      jump: { direction: 'buy', confidence: 92 },
      technical: {
        momentumProfile: { short: 12, mid: 22, long: 6, acceleration: 12 },
        signals: {
          zeroCross: { signal: 'buy' },
        },
      },
      cycle: {
        decision: { action: 'allow', reasons: [] },
      },
      strategy: {
        candidateTier: 'N_NEUTRAL',
      },
      executionStrategy: {
        candidateTier: 'A_MAIN',
        reasons: ['fixture'],
      },
    },
    ...overrides,
  }
}

describe('evaluateV5FusionEntry', () => {
  it('accepts a V5 A_MAIN execution candidate using jump confidence', () => {
    const result = evaluateV5FusionEntry(createStock())

    expect(V5_FUSION_DEFAULTS.minJumpConfidence).toBe(90)
    expect(result).toMatchObject({
      accepted: true,
      candidateTier: 'A_MAIN',
      jumpConfidence: 92,
      blockedReasons: [],
    })
  })

  it('blocks when executionStrategy is missing instead of falling back to display strategy', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        strategy: { candidateTier: 'A_MAIN' },
        executionStrategy: undefined,
      },
    })

    const result = evaluateV5FusionEntry(stock)

    expect(result.accepted).toBe(false)
    expect(result.candidateTier).toBe('N_NEUTRAL')
    expect(result.blockedReasons).toContain('缺失 executionStrategy，阻断 V5 入场')
  })

  it('blocks lifecycle veto even when execution tier and jump are strong', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        cycle: { decision: { action: 'veto', reasons: ['risk'] } },
      },
    })

    const result = evaluateV5FusionEntry(stock)

    expect(result.accepted).toBe(false)
    expect(result.blockedReasons).toContain('生命周期辅助决策一票否决')
  })

  it('treats change >= 6 as watch candidate in default balanced mode', () => {
    const result = evaluateV5FusionEntry(createStock({ change: 6.5 }))

    expect(result.accepted).toBe(false)
    expect(result.decisionState).toBe('watch_candidate')
    expect(result.blockedReasons).not.toContain('涨幅过高，阻断早期入场')
    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'change_position',
          status: 'warn',
          hardBlock: false,
        }),
      ]),
    )
  })

  it('blocks change >= 6 only in strict execution mode', () => {
    const result = evaluateV5FusionEntry(createStock({ change: 6.5 }), {
      mode: 'strict_execution',
    })

    expect(result.accepted).toBe(false)
    expect(result.decisionState).toBe('blocked_candidate')
    expect(result.firstBlockingCheck).toMatchObject({
      key: 'change_position',
      status: 'fail',
      hardBlock: true,
    })
  })

  it('blocks degraded sample quality in strict execution mode', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        meta: {
          sampleQuality: {
            status: 'degraded',
            snapshotType: 'half_hour',
          },
        },
      },
    })

    const result = evaluateV5FusionEntry(stock, { mode: 'strict_execution' })

    expect(result.decisionState).toBe('blocked_candidate')
    expect(result.firstBlockingCheck).toMatchObject({
      key: 'sample_quality',
      status: 'fail',
    })
  })

  it('keeps non A/B execution tiers as watch candidates in balanced mode', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        executionStrategy: {
          candidateTier: 'N_NEUTRAL',
        },
      },
    })

    const result = evaluateV5FusionEntry(stock)

    expect(result.decisionState).toBe('watch_candidate')
    expect(result.accepted).toBe(false)
    expect(result.checks).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          key: 'candidate_tier',
          status: 'warn',
          hardBlock: false,
        }),
      ]),
    )
  })

  it('keeps jump confidence as a hard block even when RankTrend consensus is strong', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        jump: { direction: 'buy', confidence: 87.9 },
        decision: { final: { signal: 'buy', confidence: 91 } },
        technical: {
          momentumProfile: { short: 12, mid: 22, long: 6, acceleration: 12 },
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 90 },
            acceleration: { signal: 'buy', confidence: 90 },
            zeroCross: { signal: 'buy', confidence: 90 },
          },
        },
      },
    })

    const result = evaluateV5FusionEntry(stock, {
      mode: 'strict_execution',
      minJumpConfidence: 90,
    })

    expect(result.accepted).toBe(false)
    expect(result.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
      status: 'fail',
      hardBlock: true,
    })
  })

  it('keeps jump confidence as a hard block in balanced mode', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        jump: { direction: 'buy', confidence: 82.9 },
        decision: { final: { signal: 'buy', confidence: 91 } },
        technical: {
          momentumProfile: { short: 12, mid: 22, long: 6, acceleration: 12 },
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 90 },
            acceleration: { signal: 'buy', confidence: 90 },
            zeroCross: { signal: 'buy', confidence: 90 },
          },
        },
      },
    })

    const result = evaluateV5FusionEntry(stock, {
      mode: 'balanced',
      minJumpConfidence: 85,
    })

    expect(result.accepted).toBe(false)
    expect(result.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
      status: 'fail',
      hardBlock: true,
    })
  })

  it('keeps jump confidence as a hard block in recall-first mode', () => {
    const stock = createStock({
      rankTrend: {
        ...(createStock().rankTrend as Record<string, unknown>),
        jump: { direction: 'buy', confidence: 78 },
        decision: { final: { signal: 'buy', confidence: 91 } },
        technical: {
          momentumProfile: { short: 12, mid: 22, long: 6, acceleration: 12 },
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 90 },
            acceleration: { signal: 'buy', confidence: 90 },
            zeroCross: { signal: 'buy', confidence: 90 },
          },
        },
      },
    })

    const result = evaluateV5FusionEntry(stock, {
      mode: 'recall_first',
      minJumpConfidence: 80,
    })

    expect(result.accepted).toBe(false)
    expect(result.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
      status: 'fail',
      hardBlock: true,
    })
  })
})

describe('evaluateV5FusionExit', () => {
  it('signals early exit only when lifecycle opposes a non-profitable open position', () => {
    const result = evaluateV5FusionExit(
      createStock({
        rankTrend: {
          ...(createStock().rankTrend as Record<string, unknown>),
          cycle: { decision: { action: 'veto', reasons: ['risk'] } },
        },
      }),
      { hasOpenPosition: true, grossReturn: -0.01 },
    )

    expect(result).toEqual({
      exitWatch: true,
      reason: '生命周期B反对且未盈利',
    })
  })

  it('does not let lifecycle veto create an exit when no position is open', () => {
    const result = evaluateV5FusionExit(
      createStock({
        rankTrend: {
          ...(createStock().rankTrend as Record<string, unknown>),
          cycle: { decision: { action: 'veto', reasons: ['risk'] } },
        },
      }),
      { hasOpenPosition: false, grossReturn: -0.01 },
    )

    expect(result.exitWatch).toBe(false)
  })
})
