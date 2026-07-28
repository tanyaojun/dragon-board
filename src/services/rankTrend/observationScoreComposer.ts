import type {
  AttentionStage,
  RankSignalDirection,
  RankTrendObservationScores,
} from './types'
import { clamp } from './utils'

const STAGE_FITNESS: Record<AttentionStage, number> = {
  expansion: 1,
  ignition: 0.8,
  crowded: 0.35,
  cooling: 0.2,
  reversal: 0,
}

type ObservationScoreInput = {
  technical: {
    momentumProfile: {
      short: number
      mid: number
      acceleration: number
    }
  }
  cycle: {
    stage: AttentionStage
    metrics: { rankPathCommitment: number }
    decision: {
      action: 'allow' | 'caution' | 'veto' | 'exit_watch'
      reasons: string[]
    }
  }
  risk: { pressure: number }
  decision: {
    base: {
      signal: RankSignalDirection
      combinedScore: number
    }
  }
}

export function composeObservationScores(
  input: ObservationScoreInput,
): RankTrendObservationScores {
  const signedScore = clamp(input.decision.base.combinedScore, -1, 1)
  const momentum = input.technical.momentumProfile
  const momentumConfirmation =
    0.3 * clamp(momentum.short / 15, 0, 1) +
    0.45 * clamp(momentum.mid / 15, 0, 1) +
    0.25 * clamp(momentum.acceleration / 8, 0, 1)
  const factors = {
    stageFitness: STAGE_FITNESS[input.cycle.stage],
    pathCommitment: clamp(input.cycle.metrics.rankPathCommitment, 0, 1),
    momentumConfirmation: clamp(momentumConfirmation, 0, 1),
    riskSafety: 1 - clamp(input.risk.pressure, 0, 1),
  }
  const lifecycleScore =
    0.35 * factors.stageFitness +
    0.25 * factors.pathCommitment +
    0.2 * factors.momentumConfirmation +
    0.2 * factors.riskSafety

  return {
    rankTrend: {
      direction: input.decision.base.signal,
      score: Math.round(Math.abs(signedScore) * 100),
      signedScore,
    },
    lifecycle: {
      stage: input.cycle.stage,
      score: Math.round(clamp(lifecycleScore, 0, 1) * 100),
      veto: input.cycle.decision.action === 'veto',
      reasons: [...input.cycle.decision.reasons],
      factors,
    },
  }
}
