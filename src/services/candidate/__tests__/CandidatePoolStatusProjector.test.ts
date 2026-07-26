import { describe, expect, it } from 'vitest'

import type { FusionStrategyProjection } from '@/types/fusionStrategyProjection'
import { isResonanceObserve, projectCandidatePoolStatus } from '../CandidatePoolStatusProjector'

describe('CandidatePoolStatusProjector', () => {
  it('maps fusion strategy projections back to table-friendly candidate pool fields', () => {
    const stocks = [
      { code: '600001', name: '甲' },
      { code: '600002', name: '乙' },
    ]

    const projections: FusionStrategyProjection[] = [
      {
        stockCode: '600001',
        stockName: '甲',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'quarter_hour',
        tradingDate: '2026-06-08',
        snapshotId: 'snap-1',
        frameTime: '2026-06-08T10:00:00+08:00',
        projectionSource: 'live',
        strategyState: 'triggered_wait_entry',
        candidateTier: 'A_MAIN',
        lifecycleAction: 'allow',
        triggerAt: '2026-06-08T10:00:00+08:00',
        executionOverlay: null,
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], projections)

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'triggered_wait_entry',
      candidatePoolLabel: '待入场',
      candidatePoolProjection: projections[0],
      candidatePoolSource: 'ranktrend_early_big_move_v3_lifecycle_fusion',
      candidatePoolUpdatedAt: '2026-06-08T10:00:00+08:00',
    })
    expect(result[1]).toMatchObject({
      candidatePoolStatus: 'idle',
      candidatePoolLabel: '未触发',
      candidatePoolProjection: null,
      candidatePoolSource: '',
      candidatePoolUpdatedAt: '',
    })
  })

  it('uses explicit strategy lifecycle states instead of journal workflow labels', () => {
    const stocks = [{ code: '600001', name: '甲' }]
    const projections: FusionStrategyProjection[] = [
      {
        stockCode: '600001',
        stockName: '甲',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'half_hour',
        tradingDate: '2026-06-08',
        snapshotId: 'snap-2',
        frameTime: '2026-06-08T13:30:00+08:00',
        projectionSource: 'live',
        strategyState: 'active_holding',
        candidateTier: 'A_MAIN',
        lifecycleAction: 'allow',
        triggerAt: '2026-06-08T10:00:00+08:00',
        strategyEntryAt: '2026-06-08T10:30:00+08:00',
        holdingBars: 2,
        executionOverlay: {
          executed: true,
          entryTime: '2026-06-08T10:35:00+08:00',
          entryPrice: 12.5,
        },
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], projections)

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'active_holding',
      candidatePoolLabel: '已入场',
      candidatePoolProjection: expect.objectContaining({
        strategyState: 'active_holding',
        executionOverlay: expect.objectContaining({
          entryTime: '2026-06-08T10:35:00+08:00',
        }),
      }),
    })
    expect(result[0].candidatePoolLabel).not.toBe('已触发')
  })

  it('falls back to idle for all stocks when projections array is empty', () => {
    const stocks = [
      { code: '600001', name: '甲' },
      { code: '600002', name: '乙' },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], [])

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'idle',
      candidatePoolLabel: '未触发',
      candidatePoolProjection: null,
      candidatePoolSource: '',
      candidatePoolUpdatedAt: '',
    })
    expect(result[1]).toMatchObject({
      candidatePoolStatus: 'idle',
      candidatePoolLabel: '未触发',
      candidatePoolProjection: null,
    })
  })

  it('clears the resonance observation marker when the resonance is no longer eligible', () => {
    const stocks = [
      {
        code: '600001',
        candidateResonanceObserve: true,
        rankTrend: { resonance: { status: 'insufficient', direction: 'hold', score: 0 } },
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], [])

    expect(result[0].candidateResonanceObserve).toBe(false)
  })

  it('keeps table label on strategy lifecycle when live entry decision is blocked', () => {
    const stocks = [{ code: '000970', name: '中科三环' }]
    const projections: FusionStrategyProjection[] = [
      {
        stockCode: '000970',
        stockName: '中科三环',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'half_hour',
        tradingDate: '2026-06-10',
        snapshotId: 'snap-watch',
        frameTime: '2026-06-10T10:00:00+08:00',
        projectionSource: 'live',
        strategyState: 'triggered_wait_entry',
        candidateTier: 'A_MAIN',
        lifecycleAction: 'veto',
        triggerAt: '2026-06-12T15:00:00+08:00',
        executionOverlay: null,
        entryDecision: {
          accepted: false,
          decisionState: 'blocked_candidate',
          label: '被阻断',
          summary: '生命周期辅助决策一票否决',
          checks: [],
          configSnapshot: {
            version: 'live-v5.1.0',
            mode: 'balanced',
            minJumpConfidence: 85,
            allowDegradedSample: true,
            requireCandidateTier: false,
            allowedCandidateTiers: ['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'],
            requireTierBMidAndZeroCross: false,
            tierBMidMin: 20,
            accelerationMin: 10,
            accDeltaMin: 8,
            changeGate: { mode: 'warn', maxEntryChangePct: 6 },
            limitUpPolicy: 'quote_first',
          },
        },
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], projections)

    expect(result[0]).toMatchObject({
      candidatePoolStatus: 'triggered_wait_entry',
      candidatePoolLabel: '待入场',
      candidatePoolLiveDecisionLabel: '被阻断',
      candidatePoolProjection: projections[0],
    })
  })

  it('marks strong resonance observe when signals pass but entry not accepted', () => {
    const stocks = [{
      code: '603738',
      name: '泰晶科技',
      rankTrend: {
        resonance: { status: 'ok', direction: 'buy', score: 91 },
        decision: { final: { signal: 'buy', confidence: 91 } },
        jump: { direction: 'buy', confidence: 87.9 },
        technical: {
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 88.83 },
            acceleration: { signal: 'buy', confidence: 90 },
            zeroCross: { signal: 'buy', confidence: 90 },
          },
        },
        cycle: { decision: { action: 'allow' } },
      },
    }]

    const projections: FusionStrategyProjection[] = [
      {
        stockCode: '603738',
        stockName: '泰晶科技',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'half_hour',
        tradingDate: '2026-06-16',
        snapshotId: 'snap-resonance',
        frameTime: '2026-06-16T10:00:00+08:00',
        projectionSource: 'live',
        strategyState: 'triggered_wait_entry' as const,
        candidateTier: 'A_MAIN',
        lifecycleAction: 'allow',
        triggerAt: '2026-06-16T10:00:00+08:00',
        executionOverlay: null,
        entryDecision: {
          accepted: false,
          decisionState: 'blocked_candidate',
          label: '被阻断',
          summary: 'Jump置信度未达候选池严格阈值',
          checks: [{
            key: 'jump_confidence',
            label: 'Jump置信度',
            status: 'fail' as const,
            hardBlock: true,
            actual: 87.9,
            expected: '>= 90',
            message: 'Jump置信度未达候选池严格阈值',
          }],
          configSnapshot: {
            version: 'live-v5.1.0',
            mode: 'balanced',
            minJumpConfidence: 90,
            allowDegradedSample: true,
            requireCandidateTier: false,
            allowedCandidateTiers: ['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'],
            requireTierBMidAndZeroCross: false,
            tierBMidMin: 20,
            accelerationMin: 10,
            accDeltaMin: 8,
            changeGate: { mode: 'warn', maxEntryChangePct: 6 },
            limitUpPolicy: 'quote_first',
          },
        },
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], projections)

    expect(result[0].candidatePoolStatus).toBe('triggered_wait_entry')
    expect((result[0] as any).candidateResonanceObserve).toBe(true)
  })

  it('does not mark resonance observe when entry was already accepted', () => {
    const stocks = [{
      code: '600001',
      name: '已通过候选',
      rankTrend: {
        decision: { final: { signal: 'buy', confidence: 93 } },
        jump: { direction: 'buy', confidence: 92 },
        technical: {
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 90 },
            acceleration: { signal: 'buy', confidence: 90 },
            zeroCross: { signal: 'buy', confidence: 90 },
          },
        },
        cycle: { decision: { action: 'allow' } },
      },
    }]

    const projections: FusionStrategyProjection[] = [
      {
        stockCode: '600001',
        stockName: '已通过候选',
        strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
        snapshotType: 'half_hour',
        tradingDate: '2026-06-16',
        snapshotId: 'snap-accepted',
        frameTime: '2026-06-16T10:00:00+08:00',
        projectionSource: 'live',
        strategyState: 'active_holding' as const,
        candidateTier: 'A_MAIN',
        lifecycleAction: 'allow',
        triggerAt: '2026-06-16T09:30:00+08:00',
        strategyEntryAt: '2026-06-16T10:00:00+08:00',
        holdingBars: 2,
        executionOverlay: {
          executed: true,
          entryTime: '2026-06-16T10:05:00+08:00',
          entryPrice: 15.8,
          entryId: 'entry-001',
        },
        entryDecision: {
          accepted: true,
          decisionState: 'candidate_active' as const,
          label: '已入场',
          summary: '候选已通过并入场',
          checks: [],
          configSnapshot: {
            version: 'live-v5.1.0',
            mode: 'balanced',
            minJumpConfidence: 85,
            allowDegradedSample: true,
            requireCandidateTier: false,
            allowedCandidateTiers: ['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'],
            requireTierBMidAndZeroCross: false,
            tierBMidMin: 20,
            accelerationMin: 10,
            accDeltaMin: 8,
            changeGate: { mode: 'warn', maxEntryChangePct: 6 },
            limitUpPolicy: 'quote_first',
          },
        },
      },
    ]

    const result = projectCandidatePoolStatus(stocks as any[], projections)

    expect(result[0].candidatePoolStatus).toBe('active_holding')
    expect((result[0] as any).candidateResonanceObserve).toBe(false)
  })
})

describe('isResonanceObserve', () => {
  it('returns true for a strong unified resonance', () => {
    expect(isResonanceObserve({
      resonance: { status: 'ok', direction: 'buy', score: 87 },
    })).toBe(true)
  })

  it.each([
    ['status', { status: 'insufficient', direction: 'buy', score: 90 }],
    ['direction', { status: 'ok', direction: 'hold', score: 90 }],
    ['score', { status: 'ok', direction: 'buy', score: 84 }],
  ])('returns false when resonance %s is ineligible', (_field, resonance) => {
    expect(isResonanceObserve({ resonance })).toBe(false)
  })
})
