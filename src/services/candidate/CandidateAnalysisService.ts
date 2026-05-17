import type {
  CandidateAnalysisContext,
  CandidateAnalysisResult,
  CandidateGrade,
  CandidateScoreBreakdown,
  CandidateStatus,
  CandidateThemeExposureLike,
} from './types'

const ANALYSIS_VERSION = 'candidate-rules-v1'

function toNumber(value: unknown, fallback = 0): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value))
}

function gradeFromScore(score: number): CandidateGrade {
  if (score >= 80) return 'A'
  if (score >= 65) return 'B'
  if (score >= 50) return 'C'
  return 'D'
}

function statusFromScore(score: number, riskWarnings: string[]): 'observe' | 'candidate' | 'triggered' {
  const hasMajorRisk = riskWarnings.some((risk) =>
    risk.includes('拥挤') || risk.includes('退潮') || risk.includes('D_EXIT_RISK'),
  )
  if (score >= 75 && !hasMajorRisk) return 'candidate'
  return 'observe'
}

function rankTrendScore(rankTrend: Record<string, any> | null | undefined): number {
  const tier = String(rankTrend?.strategy?.candidateTier || 'N_NEUTRAL')
  if (tier === 'A_MAIN') return 30
  if (tier === 'B_IGNITION') return 23
  if (tier === 'N_NEUTRAL') return 10
  if (tier === 'C_CROWDED') return 8
  if (tier === 'D_EXIT_RISK') return 0
  return 8
}

function primaryThemeName(exposures: CandidateThemeExposureLike[] | undefined, stockThemes: unknown): string {
  const exposure = exposures?.[0]
  if (exposure?.themeName) return String(exposure.themeName)
  if (Array.isArray(stockThemes) && stockThemes[0]) {
    const firstTheme = stockThemes[0] as Record<string, unknown>
    return String(firstTheme.name || firstTheme.Name || '')
  }
  return ''
}

function themeScore(exposures: CandidateThemeExposureLike[] | undefined): number {
  const exposure = exposures?.[0]
  if (!exposure) return 0
  const exposureWeight = toNumber(exposure.exposureWeight)
  const contribution = toNumber(exposure.themeContribution)
  const roleBonus = ['leader', 'core'].includes(String(exposure.role || '')) ? 4 : 0
  const riskPenalty = Math.max(0, toNumber(exposure.riskPenalty))
  return clamp(exposureWeight * 0.14 + contribution * 0.35 + roleBonus - riskPenalty, 0, 20)
}

function dragonScore(dragonRecord: Record<string, any> | null | undefined): number {
  if (!dragonRecord) return 0
  const role = String(dragonRecord.primaryRole || dragonRecord.role || '').toLowerCase()
  const authority = String(dragonRecord.authority || dragonRecord.authorityClass || '').toLowerCase()
  if (role.includes('leader') || authority.includes('market_core')) return 20
  if (role.includes('core')) return 15
  if (role.includes('follow')) return 8
  return 10
}

function sentimentScore(sentiment: Record<string, any> | null | undefined): number {
  const phase = String(sentiment?.phaseName || sentiment?.phase || '')
  if (phase.includes('退潮')) return 3
  if (phase.includes('冰点')) return 5
  return clamp(toNumber(sentiment?.overall) * 0.15, 0, 15)
}

function moneyFlowScore(stock: Record<string, unknown>): number {
  const main = toNumber(stock.zlje)
  const mainPct = toNumber(stock.zljzb)
  const superLarge = toNumber(stock.cddje)
  const volumeRatio = toNumber(stock.volumeRatio)
  let score = 0
  if (main > 0) score += 6
  if (mainPct > 0) score += 4
  if (superLarge > 0) score += 3
  if (volumeRatio >= 1 && volumeRatio <= 2.5) score += 2
  return clamp(score, 0, 15)
}

function buildRiskWarnings(context: CandidateAnalysisContext): string[] {
  const risks: string[] = []
  const tier = String(context.rankTrend?.strategy?.candidateTier || '')
  const phase = String(context.sentiment?.phaseName || context.sentiment?.phase || '')
  const stock = context.stock

  if (tier === 'C_CROWDED') risks.push('RankTrend 进入拥挤区，避免把高热度误判为新买点')
  if (tier === 'D_EXIT_RISK') risks.push('RankTrend 为 D_EXIT_RISK，候选失效风险高')
  if (phase.includes('退潮')) risks.push('市场情绪处于退潮期，候选需要降低优先级')
  if (toNumber(stock.zlje) < 0 || toNumber(stock.zljzb) < 0) {
    risks.push('主力净额转负，资金确认不足')
  }
  if (!context.rankTrend) risks.push('RankTrend 样本缺失，候选解释可信度下降')
  return [...new Set(risks)]
}

function buildStrengths(context: CandidateAnalysisContext, breakdown: CandidateScoreBreakdown): string[] {
  const strengths: string[] = []
  const tier = String(context.rankTrend?.strategy?.candidateTier || 'N_NEUTRAL')
  const themeName = primaryThemeName(context.themeExposures, context.stock.themes)

  if (breakdown.rankTrend >= 23) strengths.push(`RankTrend ${tier} 提供候选动量`)
  if (breakdown.theme >= 12 && themeName) strengths.push(`题材共振较强：${themeName}`)
  if (breakdown.dragon >= 15) strengths.push('龙头/核心地位有加分')
  if (breakdown.moneyFlow >= 10) strengths.push('资金流保持正向')
  return strengths
}

function buildWeaknesses(riskWarnings: string[]): string[] {
  return riskWarnings.map((risk) => risk.replace(/，.*$/, ''))
}

export function analyzeCandidateStock(context: CandidateAnalysisContext): CandidateAnalysisResult {
  const riskWarnings = buildRiskWarnings(context)
  const breakdown: CandidateScoreBreakdown = {
    rankTrend: rankTrendScore(context.rankTrend),
    theme: themeScore(context.themeExposures),
    dragon: dragonScore(context.dragonRecord),
    sentiment: sentimentScore(context.sentiment),
    moneyFlow: moneyFlowScore(context.stock),
  }
  const score = Math.round(
    breakdown.rankTrend + breakdown.theme + breakdown.dragon + breakdown.sentiment + breakdown.moneyFlow,
  )
  const grade = gradeFromScore(score)
  const suggestedStatus = statusFromScore(score, riskWarnings)
  const tier = String(context.rankTrend?.strategy?.candidateTier || 'N_NEUTRAL')
  const themeName = primaryThemeName(context.themeExposures, context.stock.themes) || '无明确题材'
  const phase = String(context.sentiment?.phaseName || context.sentiment?.phase || '市场环境未明')
  const strengths = buildStrengths(context, breakdown)
  const weaknesses = buildWeaknesses(riskWarnings)
  const stockName = context.stock.name || context.stock.code
  const tags = [
    grade,
    tier,
    themeName,
    ...riskWarnings.map((risk) => (risk.includes('拥挤') ? '拥挤风险' : '风险提示')),
  ].filter(Boolean)

  const entryReason = `${stockName} 当前 RankTrend 为 ${tier}，题材聚焦 ${themeName}，${phase} 下综合评分 ${score} 分。${
    strengths.length ? strengths.join('；') : '暂无强共振信号'
  }。`
  const tradeHypothesis = `若题材继续扩散、排名趋势不明显回落且资金确认不转弱，未来 3-5 天可作为候选样本持续跟踪。`
  const entryPrerequisites = `排名维持前排或继续改善，${themeName} 不退潮，主力净额不转负，分时不出现放量滞涨。`
  const invalidationRules = `RankTrend 降为 D_EXIT_RISK，题材进入拥挤/背离，市场情绪退潮，或主力净额连续转负。`

  return {
    score,
    grade,
    suggestedStatus,
    entryReason,
    tradeHypothesis,
    entryPrerequisites,
    invalidationRules,
    riskWarnings,
    strengths,
    weaknesses,
    tags,
    scoreBreakdown: breakdown,
    signalsSnapshot: {
      quote: {
        code: context.stock.code,
        name: context.stock.name,
        zlje: context.stock.zlje,
        zljzb: context.stock.zljzb,
        cddje: context.stock.cddje,
        volumeRatio: context.stock.volumeRatio,
        turnoverRate: context.stock.turnoverRate,
      },
      rankTrend: context.rankTrend || null,
      theme: {
        primaryTheme: themeName,
        exposures: context.themeExposures || [],
        rotationSummary: context.rotationSummary || null,
      },
      dragon: context.dragonRecord || null,
      sentiment: context.sentiment || null,
      candidateAnalysis: {
        version: ANALYSIS_VERSION,
        score,
        grade,
        suggestedStatus,
        strengths,
        weaknesses,
        riskWarnings,
        scoreBreakdown: breakdown,
        generatedAt: context.now || Date.now(),
      },
    },
  }
}
