import { describe, expect, it } from 'vitest'

import {
  DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
  RANK_TREND_LIVE_STRATEGY_PRESETS,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'

describe('rankTrendLiveStrategyConfig', () => {
  it('defaults to balanced mode without hard blocking change >= 6', () => {
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.mode).toBe('balanced')
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.changeGate.mode).toBe('warn')
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.changeGate.maxEntryChangePct).toBe(6)
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.requireCandidateTier).toBe(false)
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.allowDegradedSample).toBe(true)
  })

  it('keeps strict execution available as an explicit preset', () => {
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.changeGate.mode).toBe('block')
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.requireCandidateTier).toBe(true)
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.minJumpConfidence).toBe(90)
  })

  it('normalizes invalid patch values to safe defaults', () => {
    const normalized = normalizeRankTrendLiveStrategyConfig({
      mode: 'balanced',
      minJumpConfidence: 999,
      accelerationMin: -1,
      accDeltaMin: Number.NaN,
      allowDegradedSample: 'yes' as never,
      requireCandidateTier: 'no' as never,
      allowedCandidateTiers: ['A_MAIN', 'BAD_TIER'] as never,
      changeGate: { mode: 'block', maxEntryChangePct: 88 },
    })

    expect(normalized.minJumpConfidence).toBe(100)
    expect(normalized.accelerationMin).toBe(0)
    expect(normalized.accDeltaMin).toBe(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.accDeltaMin)
    expect(normalized.allowDegradedSample).toBe(true)
    expect(normalized.requireCandidateTier).toBe(false)
    expect(normalized.allowedCandidateTiers).toEqual(['A_MAIN'])
    expect(normalized.changeGate.maxEntryChangePct).toBe(30)
  })

  it('builds preset config by mode', () => {
    expect(normalizeRankTrendLiveStrategyConfig({ mode: 'recall_first' }).mode).toBe(
      'recall_first',
    )
    expect(normalizeRankTrendLiveStrategyConfig({ mode: 'strict_execution' }).mode).toBe(
      'strict_execution',
    )
  })
})
