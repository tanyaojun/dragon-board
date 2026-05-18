import type {
  CandidateAnalysisContext,
  CandidateAnalysisResult,
  CandidateConditionStatus,
  CandidateDataQuality,
  CandidateEvidenceDimension,
  CandidateEvidenceKind,
  CandidateGrade,
  CandidateRuleEvidence,
  CandidateScoreBreakdown,
  CandidateStatus,
  CandidateStructuredCondition,
  CandidateStructuredRisk,
  CandidateStructuredThesis,
  CandidateThemeExposureLike,
} from './types'
import { getTrustedVolumeRatio } from '../dataLoader/VolumeRatioTrust'

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
  const volumeRatio = getTrustedVolumeRatio(stock)
  let score = 0
  if (main > 0) score += 6
  if (mainPct > 0) score += 4
  if (superLarge > 0) score += 3
  if (volumeRatio >= 1 && volumeRatio <= 2.5) score += 2
  return clamp(score, 0, 15)
}

function hasFiniteValue(value: unknown): boolean {
  if (value == null) return false
  if (typeof value === 'string' && value.trim() === '') return false
  return Number.isFinite(Number(value))
}

function hasTrustedMoneyFlowValue(stock: Record<string, unknown>, key: string): boolean {
  if (key === 'volumeRatio') return getTrustedVolumeRatio(stock) > 0
  return hasFiniteValue(stock[key])
}

function evidence(
  dimension: CandidateEvidenceDimension,
  kind: CandidateEvidenceKind,
  title: string,
  detail: string,
  scoreImpact: number,
  dataQuality: CandidateDataQuality = 'ok',
  source?: string,
): CandidateRuleEvidence {
  return {
    dimension,
    kind,
    title,
    detail,
    scoreImpact,
    dataQuality,
    source,
  }
}

function condition(
  id: string,
  label: string,
  dimension: CandidateEvidenceDimension,
  status: CandidateConditionStatus,
  description: string,
): CandidateStructuredCondition {
  return {
    id,
    label,
    dimension,
    status,
    description,
  }
}

function risk(
  code: string,
  level: CandidateStructuredRisk['level'],
  dimension: CandidateStructuredRisk['dimension'],
  message: string,
  reason: string,
): CandidateStructuredRisk {
  return {
    code,
    level,
    dimension,
    message,
    reason,
  }
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

function buildEvidence(
  context: CandidateAnalysisContext,
  breakdown: CandidateScoreBreakdown,
  tier: string,
  themeName: string,
  phase: string,
): CandidateRuleEvidence[] {
  const stock = context.stock
  const exposure = context.themeExposures?.[0]
  const dragonRole = String(context.dragonRecord?.primaryRole || context.dragonRecord?.role || '')

  const items: CandidateRuleEvidence[] = []

  if (!context.rankTrend) {
    items.push(evidence('rankTrend', 'missing', 'RankTrend 样本缺失', '无法确认排名趋势分层', 0, 'missing'))
  } else if (tier === 'A_MAIN' || tier === 'B_IGNITION') {
    items.push(evidence('rankTrend', 'positive', `RankTrend ${tier}`, '排名趋势支持候选跟踪', breakdown.rankTrend))
  } else if (tier === 'C_CROWDED' || tier === 'D_EXIT_RISK') {
    items.push(evidence('rankTrend', 'negative', `RankTrend ${tier}`, '排名趋势进入拥挤或失效区', breakdown.rankTrend))
  } else {
    items.push(evidence('rankTrend', 'neutral', `RankTrend ${tier}`, '排名趋势未形成强确认', breakdown.rankTrend))
  }

  if (!exposure && themeName === '无明确题材') {
    items.push(evidence('theme', 'missing', '题材样本缺失', '未识别到明确题材暴露', 0, 'missing'))
  } else if (breakdown.theme >= 12) {
    items.push(evidence('theme', 'positive', `题材 ${themeName}`, '题材暴露和贡献支持候选', breakdown.theme))
  } else if (toNumber(exposure?.riskPenalty) > 0) {
    items.push(evidence('theme', 'negative', `题材 ${themeName}`, '题材存在拥挤或风险扣分', breakdown.theme))
  } else {
    items.push(evidence('theme', 'neutral', `题材 ${themeName}`, '题材贡献尚未形成强共振', breakdown.theme))
  }

  if (!context.dragonRecord) {
    items.push(evidence('dragon', 'missing', '龙头/地位样本缺失', '未匹配到龙头复盘地位记录', 0, 'missing'))
  } else if (breakdown.dragon >= 15) {
    items.push(evidence('dragon', 'positive', '龙头/核心地位', `当前地位 ${dragonRole || '核心候选'}`, breakdown.dragon))
  } else {
    items.push(evidence('dragon', 'neutral', '龙头/地位一般', `当前地位 ${dragonRole || '未明确'}`, breakdown.dragon))
  }

  if (!context.sentiment) {
    items.push(evidence('sentiment', 'missing', '情绪样本缺失', '无法确认市场情绪阶段', 0, 'missing'))
  } else if (phase.includes('退潮') || phase.includes('冰点')) {
    items.push(evidence('sentiment', 'negative', `情绪 ${phase}`, '市场情绪不支持提高优先级', breakdown.sentiment))
  } else {
    items.push(evidence('sentiment', 'positive', `情绪 ${phase}`, '市场情绪未处于退潮', breakdown.sentiment))
  }

  const hasMoneyFlow = ['zlje', 'zljzb', 'cddje', 'volumeRatio'].some((key) =>
    hasTrustedMoneyFlowValue(stock, key),
  )
  if (!hasMoneyFlow) {
    items.push(evidence('moneyFlow', 'missing', '资金流样本缺失', '主力净额、占比或量比缺失', 0, 'missing'))
  } else if (toNumber(stock.zlje) < 0 || toNumber(stock.zljzb) < 0) {
    items.push(evidence('moneyFlow', 'negative', '资金流转弱', '主力净额或主力占比为负', breakdown.moneyFlow))
  } else if (breakdown.moneyFlow >= 10) {
    items.push(evidence('moneyFlow', 'positive', '资金流正向', '主力净额、占比和超大单提供确认', breakdown.moneyFlow))
  } else {
    items.push(evidence('moneyFlow', 'neutral', '资金确认一般', '资金流未明显转负，但确认强度不足', breakdown.moneyFlow))
  }

  return items
}

function buildStructuredRisks(
  context: CandidateAnalysisContext,
  tier: string,
  phase: string,
  themeName: string,
): CandidateStructuredRisk[] {
  const risks: CandidateStructuredRisk[] = []
  const stock = context.stock

  if (!context.rankTrend) {
    risks.push(risk('RANKTREND_MISSING', 'warning', 'rankTrend', 'RankTrend 样本缺失，候选解释可信度下降', '缺少排名趋势样本'))
  } else if (tier === 'C_CROWDED') {
    risks.push(risk('RANKTREND_CROWDED', 'warning', 'rankTrend', 'RankTrend 进入拥挤区，避免把高热度误判为新买点', '候选分层为 C_CROWDED'))
  } else if (tier === 'D_EXIT_RISK') {
    risks.push(risk('RANKTREND_EXIT_RISK', 'danger', 'rankTrend', 'RankTrend 为 D_EXIT_RISK，候选失效风险高', '候选分层为 D_EXIT_RISK'))
  }

  if (themeName === '无明确题材') {
    risks.push(risk('THEME_MISSING', 'info', 'theme', '题材样本缺失，无法确认主线共振', '未识别到题材暴露'))
  }
  if (phase.includes('退潮')) {
    risks.push(risk('SENTIMENT_EBB', 'warning', 'sentiment', '市场情绪处于退潮期，候选需要降低优先级', `当前阶段：${phase}`))
  } else if (!context.sentiment) {
    risks.push(risk('SENTIMENT_MISSING', 'info', 'sentiment', '情绪样本缺失，无法确认市场环境', '缺少市场情绪输入'))
  }

  const hasMoneyFlow = ['zlje', 'zljzb', 'cddje', 'volumeRatio'].some((key) =>
    hasTrustedMoneyFlowValue(stock, key),
  )
  if (!hasMoneyFlow) {
    risks.push(risk('MONEY_FLOW_MISSING', 'info', 'moneyFlow', '资金流样本缺失，无法确认买盘强度', '资金字段缺失或无效'))
  } else if (toNumber(stock.zlje) < 0 || toNumber(stock.zljzb) < 0) {
    risks.push(risk('MONEY_FLOW_NEGATIVE', 'warning', 'moneyFlow', '主力净额转负，资金确认不足', '主力净额或主力占比为负'))
  }

  if ((context.allStocks?.length || 0) > 0 && (context.allStocks?.length || 0) < 5) {
    risks.push(risk('DATA_LOW_SAMPLE', 'info', 'dataQuality', '候选上下文样本量偏低，横向比较可信度下降', '当前行情样本少于 5 只股票'))
  }

  return risks
}

function statusFromBoolean(value: boolean | null): CandidateConditionStatus {
  if (value === null) return 'unknown'
  return value ? 'met' : 'watch'
}

function buildStructuredThesis(
  context: CandidateAnalysisContext,
  breakdown: CandidateScoreBreakdown,
  tier: string,
  themeName: string,
  phase: string,
): CandidateStructuredThesis {
  const stock = context.stock
  const rankTrendConfirmed = context.rankTrend ? tier === 'A_MAIN' || tier === 'B_IGNITION' : null
  const themeConfirmed = themeName === '无明确题材' ? null : breakdown.theme >= 12
  const moneyFlowConfirmed = ['zlje', 'zljzb', 'cddje', 'volumeRatio'].some((key) =>
    hasTrustedMoneyFlowValue(stock, key),
  )
    ? toNumber(stock.zlje) >= 0 && toNumber(stock.zljzb) >= 0 && breakdown.moneyFlow >= 8
    : null
  const sentimentOk = context.sentiment ? !phase.includes('退潮') && !phase.includes('冰点') : null

  return {
    triggerConditions: [
      condition('ranktrend-trigger', 'RankTrend 进入候选层', 'rankTrend', statusFromBoolean(rankTrendConfirmed), tier),
      condition('theme-trigger', '题材形成共振', 'theme', statusFromBoolean(themeConfirmed), themeName),
      condition('moneyflow-trigger', '资金确认未转弱', 'moneyFlow', statusFromBoolean(moneyFlowConfirmed), `资金分 ${breakdown.moneyFlow}`),
    ],
    entryPrerequisites: [
      condition('ranktrend-hold', '排名维持前排或继续改善', 'rankTrend', statusFromBoolean(rankTrendConfirmed), '排名趋势不能快速回落'),
      condition('theme-hold', `${themeName} 不退潮`, 'theme', statusFromBoolean(themeConfirmed), '题材热度和贡献不能明显背离'),
      condition('sentiment-hold', '市场情绪不退潮', 'sentiment', statusFromBoolean(sentimentOk), phase),
      condition('moneyflow-hold', '主力净额不连续转负', 'moneyFlow', statusFromBoolean(moneyFlowConfirmed), '分时不出现放量滞涨'),
    ],
    invalidationConditions: [
      condition('ranktrend-exit', 'RankTrend 降为 D_EXIT_RISK', 'rankTrend', tier === 'D_EXIT_RISK' ? 'failed' : 'watch', tier),
      condition('theme-exit', '题材拥挤或背离', 'theme', toNumber(context.themeExposures?.[0]?.riskPenalty) > 0 ? 'failed' : 'watch', themeName),
      condition('sentiment-exit', '市场情绪退潮', 'sentiment', phase.includes('退潮') ? 'failed' : 'watch', phase),
      condition('moneyflow-exit', '主力净额连续转负', 'moneyFlow', toNumber(stock.zlje) < 0 || toNumber(stock.zljzb) < 0 ? 'failed' : 'watch', `资金分 ${breakdown.moneyFlow}`),
    ],
  }
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
  const evidenceItems = buildEvidence(context, breakdown, tier, themeName, phase)
  const penalties = evidenceItems.filter((item) => item.kind === 'negative' || item.kind === 'missing')
  const structuredRisks = buildStructuredRisks(context, tier, phase, themeName)
  const structuredThesis = buildStructuredThesis(context, breakdown, tier, themeName, phase)
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
    evidence: evidenceItems,
    penalties,
    structuredThesis,
    structuredRisks,
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
        evidence: evidenceItems,
        penalties,
        structuredThesis,
        structuredRisks,
        scoreBreakdown: breakdown,
        generatedAt: context.now || Date.now(),
      },
    },
  }
}
