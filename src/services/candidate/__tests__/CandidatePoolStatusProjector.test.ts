import { describe, expect, it } from 'vitest'

import type { FusionStrategyProjection } from '@/types/fusionStrategyProjection'
import { projectCandidatePoolStatus } from '../CandidatePoolStatusProjector'

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
      candidatePoolLabel: '策略持有中',
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

  it('uses entry decision label and summary for live watch candidates', () => {
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
        strategyState: 'idle',
        candidateTier: 'A_MAIN',
        lifecycleAction: 'allow',
        executionOverlay: null,
        entryDecision: {
          accepted: false,
          decisionState: 'watch_candidate',
          label: '观察候选',
          summary: '涨幅偏高，进入观察候选',
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
      candidatePoolStatus: 'idle',
      candidatePoolLabel: '观察候选',
      candidatePoolProjection: projections[0],
    })
  })
})
