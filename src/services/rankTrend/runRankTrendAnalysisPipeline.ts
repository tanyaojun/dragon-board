import { composeCandidateTier } from '@/services/rankTrend/candidateTierComposer'
import { analyzeAttentionCycle } from '@/services/rankTrend/attentionCycleAnalyzer'
import { composeDecision } from '@/services/rankTrend/resultComposer'
import { analyzeRiskSignals } from '@/services/rankTrend/riskSignalAnalyzer'
import {
  analyzeFallbackTechnicalSignals,
  analyzeTechnicalSignals,
} from '@/services/rankTrend/technicalSignalAnalyzer'
import type {
  MarketRegimeAnalysis,
  RankTrendAnalysisResult,
  RankTrendRuntimeConfig,
} from '@/services/rankTrend/types'
import { getTechnicalMinSamples } from '@/services/rankTrend/utils'

type RankTrendAnalysisPipelineResult = {
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  risk: RankTrendAnalysisResult['risk']
  decision: RankTrendAnalysisResult['decision']
  strategy: NonNullable<RankTrendAnalysisResult['strategy']>
}

type RunRankTrendAnalysisPipelineInput = {
  ranks: number[]
  percentiles: number[]
  currentPercentile: number
  displayChange: number
  stockChange: number
  volumeRatio: number
  zlje: number
  zljzb: number
  regime: MarketRegimeAnalysis
  config: RankTrendRuntimeConfig
  requiredSamples?: number
}

export function runRankTrendAnalysisPipeline(
  input: RunRankTrendAnalysisPipelineInput,
): RankTrendAnalysisPipelineResult {
  const {
    ranks,
    percentiles,
    currentPercentile,
    displayChange,
    stockChange,
    volumeRatio,
    zlje,
    zljzb,
    regime,
    config,
  } = input
  const requiredSamples = input.requiredSamples ?? getTechnicalMinSamples(config)

  const technical =
    percentiles.length >= requiredSamples
      ? analyzeTechnicalSignals(percentiles, config)
      : analyzeFallbackTechnicalSignals({
          percentiles,
          displayChange,
          stockChange,
          volumeRatio,
          zlje,
          zljzb,
          config,
        })

  let cycle = analyzeAttentionCycle({
    ranks,
    percentiles,
    momentumProfile: technical.momentumProfile,
  })
  const risk = analyzeRiskSignals({
    currentPercentile,
    technical,
    cycle,
    zlje,
    zljzb,
    volumeRatio,
  })
  cycle = analyzeAttentionCycle({
    ranks,
    percentiles,
    momentumProfile: technical.momentumProfile,
    risk: {
      pressure: risk.pressure,
      divergenceSeverity: risk.divergence.severity,
      overheatSeverity: risk.overheat.severity,
    },
  })
  const decision = composeDecision({
    technical,
    cycle,
    risk,
    config,
  })
  const strategy = composeCandidateTier({
    technical,
    cycle,
    risk,
    regime,
  })

  return {
    technical,
    cycle,
    risk,
    decision,
    strategy,
  }
}
