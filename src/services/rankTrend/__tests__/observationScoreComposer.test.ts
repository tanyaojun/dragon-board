import { describe, expect, it } from 'vitest'

import { composeObservationScores } from '../observationScoreComposer'

const createInput = () => ({
  technical: {
    momentumProfile: {
      short: 15,
      mid: 15,
      long: 10,
      acceleration: 8,
      shock: 0,
      composite: 12,
    },
  },
  cycle: {
    stage: 'expansion' as const,
    metrics: { rankPathCommitment: 0.8 },
    decision: { action: 'allow' as const, reasons: ['扩散阶段允许继续观察'] },
  },
  risk: { pressure: 0.1 },
  decision: {
    base: { signal: 'buy' as const, combinedScore: 0.64 },
  },
})

describe('composeObservationScores', () => {
  it('uses the absolute signed technical score as directional trend strength', () => {
    const input = createInput()
    input.decision.base.signal = 'sell'
    input.decision.base.combinedScore = -0.64

    const result = composeObservationScores(input)

    expect(result.rankTrend).toEqual({
      direction: 'sell',
      score: 64,
      signedScore: -0.64,
    })
  })

  it('composes lifecycle opportunity from stage, path, momentum, and risk safety', () => {
    const result = composeObservationScores(createInput())

    expect(result.lifecycle.score).toBe(93)
    expect(result.lifecycle.factors).toEqual({
      stageFitness: 1,
      pathCommitment: 0.8,
      momentumConfirmation: 1,
      riskSafety: 0.9,
    })
    expect(result.lifecycle.veto).toBe(false)
  })

  it('keeps the calculated lifecycle score when lifecycle marks a veto', () => {
    const input = createInput()
    input.cycle.stage = 'reversal'
    input.cycle.decision.action = 'veto'
    input.cycle.decision.reasons = ['生命周期进入反转路径']

    const result = composeObservationScores(input)

    expect(result.lifecycle.score).toBe(58)
    expect(result.lifecycle.veto).toBe(true)
    expect(result.lifecycle.reasons).toEqual(['生命周期进入反转路径'])
  })
})
