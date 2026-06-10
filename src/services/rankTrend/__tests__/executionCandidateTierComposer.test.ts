import { describe, expect, it } from 'vitest'

import { composeExecutionCandidateTier } from '../executionCandidateTierComposer'
import type { MarketRegimeAnalysis, RankTrendAnalysisResult } from '../types'

const regime: MarketRegimeAnalysis = {
  state: 'normal',
  score: 0.4,
  reasons: ['test'],
}

function technical(
  momentum: Partial<RankTrendAnalysisResult['technical']['momentumProfile']> = {},
  signal: 'buy' | 'hold' = 'buy',
): RankTrendAnalysisResult['technical'] {
  return {
    movingAverage: { ma5: 80, ma10: 75, trend: 'up' },
    macd: {
      dif: 1,
      dea: 0.6,
      histogram: 0.4,
      cross: signal === 'buy' ? 'golden' : 'none',
      rawScore: 0.7,
      confirmed: signal === 'buy',
    },
    signals: {
      direction: { signal, confidence: 80, score: signal === 'buy' ? 0.7 : 0 },
      acceleration: { signal, confidence: 78, score: signal === 'buy' ? 0.6 : 0 },
      zeroCross: { signal: 'hold', confidence: 50, score: 0 },
    },
    momentumScore: 70,
    momentumProfile: {
      short: 8,
      mid: 6,
      long: 2,
      acceleration: 3,
      shock: 1,
      composite: 7,
      ...momentum,
    },
  }
}

function cycle(
  stage: RankTrendAnalysisResult['cycle']['stage'],
  action: RankTrendAnalysisResult['cycle']['decision']['action'] = 'allow',
  reasons: string[] = [],
): RankTrendAnalysisResult['cycle'] {
  return {
    rawStage: stage,
    stage,
    previousStage: null,
    transition: stage,
    confidence: 80,
    metrics: {
      rankVelocity: 1,
      rankAcceleration: 1,
      rankShock: 0,
      hotZoneStreak: 1,
      bestRecentRank: 12,
      drawdownFromPeak: 0,
      rankPathCommitment: 0.8,
    },
    entryAdvice: {
      bias: action === 'veto' ? 'blocked' : 'preferred',
      allowed: action !== 'veto',
      reason: reasons[0] || 'test',
    },
    decision: {
      action,
      confidence: 80,
      reasons,
      discovery: { action: 'none', reasons: [] },
      evidence: {
        rawStage: stage,
        stage,
        transition: stage,
        rankVelocity: 1,
        rankAcceleration: 1,
        drawdownFromPeak: 0,
        hotZoneStreak: 1,
        rankPathCommitment: 0.8,
        momentumShort: 8,
        momentumMid: 6,
        momentumLong: 2,
        momentumAcceleration: 3,
        riskPressure: 0.2,
        divergenceSeverity: 0.2,
        overheatSeverity: 0.2,
      },
    },
  }
}

function risk(
  pressure = 0.2,
  divergenceSeverity = 0.2,
  overheatSeverity = 0.2,
): RankTrendAnalysisResult['risk'] {
  return {
    pressure,
    synergy: 0.5,
    divergence: { score: divergenceSeverity, signal: 'hold', severity: divergenceSeverity },
    overheat: { score: overheatSeverity, signal: 'hold', severity: overheatSeverity },
  }
}

describe('composeExecutionCandidateTier', () => {
  it('发酵或高潮且风险不高时，扩散结构可以形成 A_MAIN execution tier', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 8, short: 6 }),
      cycle: cycle('expansion'),
      risk: risk(),
      regime,
      hotlistSentiment: { phaseName: '发酵', riskLevel: '中', confidence: 82 },
    })

    expect(result.candidateTier).toBe('A_MAIN')
    expect(result.hotlist).toMatchObject({ state: 'present', stage: '发酵', riskLevel: '中' })
    expect(result.reasons.join(' ')).toContain('热榜情绪支持A_MAIN')
  })

  it('启动期不允许扩散结构直接升成 A_MAIN', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 8, short: 6 }),
      cycle: cycle('expansion'),
      risk: risk(),
      regime,
      hotlistSentiment: { phaseName: '启动', riskLevel: '中', confidence: 78 },
    })

    expect(result.candidateTier).toBe('N_NEUTRAL')
    expect(result.reasons.join(' ')).toContain('A_MAIN暂缓')
  })

  it('热榜高风险时，即使扩散和动量满足也不能形成 A_MAIN', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 8, short: 6 }),
      cycle: cycle('expansion'),
      risk: risk(),
      regime,
      hotlistSentiment: { phaseName: '发酵', riskLevel: '高', confidence: 82 },
    })

    expect(result.candidateTier).not.toBe('A_MAIN')
    expect(result.reasons.join(' ')).toContain('高风险')
  })

  it('生命周期 veto 是 execution tier 的一票否决，不允许 A/B 入池', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 8, short: 6 }),
      cycle: cycle('expansion', 'veto', ['假突破承接不足']),
      risk: risk(),
      regime,
      hotlistSentiment: { phaseName: '高潮', riskLevel: '中', confidence: 85 },
    })

    expect(result.candidateTier).toBe('N_NEUTRAL')
    expect(result.reasons.join(' ')).toContain('生命周期辅助决策一票否决')
  })

  it('点火期在启动/发酵/高潮情绪下可以形成 B_IGNITION', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ short: 5, acceleration: 1, mid: 2, long: 1 }),
      cycle: cycle('ignition', 'caution', ['低可见度点火']),
      risk: risk(0.3),
      regime,
      hotlistSentiment: { phaseName: '启动', riskLevel: '中', confidence: 76 },
    })

    expect(result.candidateTier).toBe('B_IGNITION')
    expect(result.reasons.join(' ')).toContain('B_IGNITION')
    expect(result.reasons.join(' ')).toContain('低可见度点火诊断')
  })

  it('退潮或冰点阶段暂停入场，动量或风险转弱时进入 D_EXIT_RISK', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ short: -3, acceleration: -2.5, mid: -1 }),
      cycle: cycle('reversal'),
      risk: risk(0.6),
      regime,
      hotlistSentiment: { phaseName: '退潮', riskLevel: '高', confidence: 30 },
    })

    expect(result.candidateTier).toBe('D_EXIT_RISK')
    expect(result.action).toBe('exit_watch')
    expect(result.reasons.join(' ')).toContain('动量衰减触发退出风险')
  })

  it('热榜情绪缺失按中性处理，但会在 execution reason 中显式标注', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 8, short: 6 }),
      cycle: cycle('expansion'),
      risk: risk(),
      regime,
      hotlistSentiment: null,
    })

    expect(result.hotlist).toMatchObject({ state: 'missing', stage: null, riskLevel: null })
    expect(result.candidateTier).toBe('A_MAIN')
    expect(result.reasons.join(' ')).toContain('热榜情绪缺失，按中性处理')
  })
})
