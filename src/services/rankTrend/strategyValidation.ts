import type {
  CandidateTier,
  MarketRegimeState,
  RankTrendAnalysisResult,
} from './types'

export interface TierDistributionItem {
  count: number
  percent: number
  averageConfidence: number
}

export interface RegimeDistributionItem {
  count: number
  percent: number
  averageScore: number
}

export interface SampleQualityDistributionItem {
  count: number
  percent: number
}

export interface RankTrendStrategyValidationReport {
  generatedAt: number
  total: number
  missingStrategyCount: number
  tiers: Record<CandidateTier, TierDistributionItem>
  regimes: Record<MarketRegimeState, RegimeDistributionItem>
  sampleQuality: {
    bySnapshotType: Record<string, SampleQualityDistributionItem>
    byStatus: Record<string, SampleQualityDistributionItem>
    delayedCount: number
    restoredCount: number
  }
  warnings: string[]
}

export interface StrategyDistributionOptions {
  maxMainTierShare?: number
  maxAggressiveShareInWeakRegime?: number
  minExitRiskShareInRetreat?: number
}

const CANDIDATE_TIERS: CandidateTier[] = [
  'A_MAIN',
  'B_IGNITION',
  'C_CROWDED',
  'D_EXIT_RISK',
  'N_NEUTRAL',
]

const REGIME_STATES: MarketRegimeState[] = ['strong', 'normal', 'weak', 'retreat']

function createTierDistribution(): Record<CandidateTier, TierDistributionItem> {
  return CANDIDATE_TIERS.reduce((acc, tier) => {
    acc[tier] = { count: 0, percent: 0, averageConfidence: 0 }
    return acc
  }, {} as Record<CandidateTier, TierDistributionItem>)
}

function createRegimeDistribution(): Record<MarketRegimeState, RegimeDistributionItem> {
  return REGIME_STATES.reduce((acc, state) => {
    acc[state] = { count: 0, percent: 0, averageScore: 0 }
    return acc
  }, {} as Record<MarketRegimeState, RegimeDistributionItem>)
}

function incrementQualityBucket(
  buckets: Record<string, SampleQualityDistributionItem>,
  key: string | undefined,
  total: number,
): void {
  if (!key) return
  if (!buckets[key]) buckets[key] = { count: 0, percent: 0 }
  buckets[key].count += 1
  buckets[key].percent = total > 0 ? buckets[key].count / total : 0
}

function normalizeInput(
  results:
    | Iterable<RankTrendAnalysisResult | null | undefined>
    | ReadonlyMap<string, RankTrendAnalysisResult | null | undefined>,
): Array<RankTrendAnalysisResult> {
  const maybeMap = results as ReadonlyMap<string, RankTrendAnalysisResult | null | undefined>
  const values =
    typeof maybeMap.values === 'function' && typeof maybeMap.get === 'function'
      ? maybeMap.values()
      : (results as Iterable<RankTrendAnalysisResult | null | undefined>)
  return Array.from(values).filter((item): item is RankTrendAnalysisResult => Boolean(item))
}

export function summarizeRankTrendStrategyDistribution(
  results:
    | Iterable<RankTrendAnalysisResult | null | undefined>
    | ReadonlyMap<string, RankTrendAnalysisResult | null | undefined>,
  options: StrategyDistributionOptions = {},
): RankTrendStrategyValidationReport {
  const list = normalizeInput(results)
  const total = list.length
  const tiers = createTierDistribution()
  const regimes = createRegimeDistribution()
  const tierConfidenceSum = CANDIDATE_TIERS.reduce((acc, tier) => {
    acc[tier] = 0
    return acc
  }, {} as Record<CandidateTier, number>)
  const regimeScoreSum = REGIME_STATES.reduce((acc, state) => {
    acc[state] = 0
    return acc
  }, {} as Record<MarketRegimeState, number>)
  const bySnapshotType: Record<string, SampleQualityDistributionItem> = {}
  const byStatus: Record<string, SampleQualityDistributionItem> = {}
  const warnings: string[] = []

  let missingStrategyCount = 0
  let delayedCount = 0
  let restoredCount = 0

  for (const result of list) {
    const strategy = result.strategy
    if (!strategy) {
      missingStrategyCount += 1
      continue
    }

    tiers[strategy.candidateTier].count += 1
    tierConfidenceSum[strategy.candidateTier] += Number(result.decision?.final?.confidence ?? 0)

    regimes[strategy.regime.state].count += 1
    regimeScoreSum[strategy.regime.state] += Number(strategy.regime.score ?? 0)

    const quality = result.meta?.sampleQuality
    incrementQualityBucket(bySnapshotType, quality?.snapshotType, total)
    incrementQualityBucket(byStatus, quality?.status, total)
    delayedCount += Number(quality?.delayedCount ?? 0)
    restoredCount += Number(quality?.restoredCount ?? 0)
  }

  for (const tier of CANDIDATE_TIERS) {
    const count = tiers[tier].count
    tiers[tier].percent = total > 0 ? count / total : 0
    tiers[tier].averageConfidence = count > 0 ? tierConfidenceSum[tier] / count : 0
  }

  for (const state of REGIME_STATES) {
    const count = regimes[state].count
    regimes[state].percent = total > 0 ? count / total : 0
    regimes[state].averageScore = count > 0 ? regimeScoreSum[state] / count : 0
  }

  const maxMainTierShare = options.maxMainTierShare ?? 0.1
  const maxAggressiveShareInWeakRegime = options.maxAggressiveShareInWeakRegime ?? 0.05
  const minExitRiskShareInRetreat = options.minExitRiskShareInRetreat ?? 0.05
  const aggressiveShare = tiers.A_MAIN.percent + tiers.B_IGNITION.percent
  const weakRegimeShare = regimes.weak.percent + regimes.retreat.percent

  if (missingStrategyCount > 0) {
    warnings.push(`有 ${missingStrategyCount} 条结果缺少 strategy 字段`)
  }
  if (tiers.A_MAIN.percent > maxMainTierShare) {
    warnings.push(`A_MAIN 占比 ${(tiers.A_MAIN.percent * 100).toFixed(1)}%，超过 ${(maxMainTierShare * 100).toFixed(0)}% 上限`)
  }
  if (weakRegimeShare >= 0.5 && aggressiveShare > maxAggressiveShareInWeakRegime) {
    warnings.push(`弱势/退潮环境占优时，A/B 候选池仍有 ${(aggressiveShare * 100).toFixed(1)}%`)
  }
  if (regimes.retreat.percent >= 0.5 && tiers.D_EXIT_RISK.percent < minExitRiskShareInRetreat) {
    warnings.push(`退潮环境占优时，D_EXIT_RISK 占比仅 ${(tiers.D_EXIT_RISK.percent * 100).toFixed(1)}%`)
  }

  return {
    generatedAt: Date.now(),
    total,
    missingStrategyCount,
    tiers,
    regimes,
    sampleQuality: {
      bySnapshotType,
      byStatus,
      delayedCount,
      restoredCount,
    },
    warnings,
  }
}
