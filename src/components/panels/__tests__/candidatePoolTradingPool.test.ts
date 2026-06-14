import { describe, expect, it } from 'vitest'

import {
  buildTradingPoolPersistencePlan,
  isTradingPoolSnapshotEqual,
  readTradingPoolSnapshot,
} from '../candidatePoolTradingPool'
import type { CandidateJournalEntry } from '@/services/candidate/types'

function entry(overrides: Partial<CandidateJournalEntry>): CandidateJournalEntry {
  return {
    id: '',
    stockCode: '',
    stockName: '',
    status: 'observe',
    tradeType: 'thesis',
    entryReason: '',
    tradeHypothesis: '',
    entryPrerequisites: '',
    invalidationRules: '',
    humanDecision: 'watch',
    skipReason: '',
    reviewOutcome: 'pending',
    modelResult: 'unknown',
    executionResult: 'unknown',
    reviewNotes: '',
    reviewTags: [],
    signalsSnapshot: null,
    createdAt: '',
    updatedAt: '',
    ...overrides,
  }
}

describe('candidatePoolTradingPool helpers', () => {
  it('defaults malformed trading-pool snapshots to stale quality and safe fallbacks', () => {
    const row = readTradingPoolSnapshot({
      quote: {
        code: '601208',
        name: '东材科技',
      },
      tradingPool: null,
    })

    expect(row).toEqual({
      code: '601208',
      name: '东材科技',
      status: '观察中',
      decision: 'watch',
      reasons: [],
      signalSnapshot: expect.objectContaining({
        dataQuality: 'stale',
      }),
    })
  })

  it('treats stable trading-pool snapshots as unchanged even if recompute time differs', () => {
    const row = {
      code: '601208',
      name: '东材科技',
      status: '观察买点',
      decision: 'enter',
      reasons: ['signal_resonance'],
      signalSnapshot: {
        directionSignal: 'buy',
        jumpConfidence: 0.88,
        macdCross: 'golden',
        accelerationSignal: 'buy',
        zeroCrossSignal: 'buy',
        momentumSyncBroken: false,
        lifecycleAction: null,
        dataQuality: 'fresh' as const,
      },
    }

    const existing = {
      tradingPool: {
        version: 'v2',
        code: '601208',
        name: '东材科技',
        status: '观察买点',
        decision: 'enter',
        reasons: ['signal_resonance'],
        signalSnapshot: row.signalSnapshot,
        dataQuality: 'fresh',
        lastRecomputedAt: '2026-06-14T10:00:00+08:00',
      },
    }

    expect(isTradingPoolSnapshotEqual(existing.tradingPool, row)).toBe(true)
  })

  it('keeps only one persistence task per candidate and splits updates from creates', () => {
    const candidates = [
      entry({
        id: 'tj_existing',
        stockCode: '601208',
        stockName: '东材科技',
        tradeType: 'thesis',
      }),
      entry({
        id: 'tj_other',
        stockCode: '300433',
        stockName: '蓝思科技',
        tradeType: 'thesis',
      }),
    ]

    const persistedEntries = [
      entry({
        id: 'tj_pool_1',
        stockCode: '601208',
        stockName: '东材科技',
        tradeType: 'trading_pool',
        candidateEntryId: 'tj_existing',
        status: 'active' as any,
        signalsSnapshot: {
          tradingPool: {
            version: 'v2',
            code: '601208',
            name: '东材科技',
            status: '观察买点',
            decision: 'enter',
            reasons: ['signal_resonance'],
            signalSnapshot: {
              directionSignal: 'buy',
              jumpConfidence: 0.8,
              macdCross: 'golden',
              accelerationSignal: 'buy',
              zeroCrossSignal: 'buy',
              momentumSyncBroken: false,
              lifecycleAction: null,
              dataQuality: 'fresh',
            },
            dataQuality: 'fresh',
          },
        },
      }),
    ]

    const rows = [
      {
        code: '601208',
        name: '东材科技',
        status: '观察买点',
        decision: 'enter',
        reasons: ['signal_resonance'],
        signalSnapshot: {
          directionSignal: 'buy',
          jumpConfidence: 0.88,
          macdCross: 'golden',
          accelerationSignal: 'buy',
          zeroCrossSignal: 'buy',
          momentumSyncBroken: false,
          lifecycleAction: null,
          dataQuality: 'fresh' as const,
        },
      },
      {
        code: '601208',
        name: '东材科技',
        status: '观察买点',
        decision: 'enter',
        reasons: ['signal_resonance'],
        signalSnapshot: {
          directionSignal: 'buy',
          jumpConfidence: 0.88,
          macdCross: 'golden',
          accelerationSignal: 'buy',
          zeroCrossSignal: 'buy',
          momentumSyncBroken: false,
          lifecycleAction: null,
          dataQuality: 'fresh' as const,
        },
      },
      {
        code: '300433',
        name: '蓝思科技',
        status: '观察中',
        decision: 'watch',
        reasons: ['resonance_incomplete'],
        signalSnapshot: {
          directionSignal: 'buy',
          jumpConfidence: 0.91,
          macdCross: 'golden',
          accelerationSignal: 'hold',
          zeroCrossSignal: 'hold',
          momentumSyncBroken: false,
          lifecycleAction: null,
          dataQuality: 'fresh' as const,
        },
      },
    ]

    const plan = buildTradingPoolPersistencePlan(rows, candidates, persistedEntries)

    expect(plan.updates).toHaveLength(1)
    expect(plan.updates[0].entry.id).toBe('tj_pool_1')
    expect(plan.creates).toHaveLength(1)
    expect(plan.creates[0].candidate.id).toBe('tj_other')
  })
})
