import type { RankTrendAnalysisResult } from './types'

export interface RankTrendDisplayStatus {
  label: string
  classKey: string
  tooltip: string
}

export interface RankTrendDisplayBreakdown {
  qualityLabel: string
  qualityBadgeLabel: string
  showQualityBadge: boolean
  cycleLabel: string
  tierLabel: string
  riskLabel: string
  tooltip: string
  classKeys: {
    quality: string
    cycle: string
    tier: string
    risk: string
  }
}

export type VolumeConfirmation = 'healthy' | 'weak' | 'overheated' | 'divergent'

export interface RankTrendStatusContext {
  turnoverP50: number
  turnoverP70: number
  turnoverP85: number
  volumeRatioP50: number
  volumeRatioP70: number
  volumeRatioP85: number
  turnoverRateP50: number
  turnoverRateP70: number
  turnoverRateP85: number
}

const CANDIDATE_TIER_STATUS: Record<string, RankTrendDisplayStatus> = {
  A_MAIN: {
    label: '主升确认',
    classKey: 'main_confirmed',
    tooltip: '注意力趋势已被快照确认，资金未明显背离，作为重点跟踪对象。',
  },
  B_IGNITION: {
    label: '点火观察',
    classKey: 'ignition_watch',
    tooltip: '注意力开始启动，仍需后续半小时快照确认扩散。',
  },
  C_CROWDED: {
    label: '高位拥挤',
    classKey: 'crowded',
    tooltip: '热度和位置偏高，追击赔率下降，重点防止情绪追高。',
  },
  D_EXIT_RISK: {
    label: '转弱预警',
    classKey: 'weakening',
    tooltip: '注意力或资金已经转弱，优先控制风险，不按机会票处理。',
  },
  N_NEUTRAL: {
    label: '新入观察',
    classKey: 'new_watch',
    tooltip: '刚进入热榜视野，资金确认一般，先看下一轮排名和资金能否延续。',
  },
}

const FALLBACK_STATUS_CONTEXT: RankTrendStatusContext = {
  turnoverP50: 0,
  turnoverP70: 0,
  turnoverP85: 0,
  volumeRatioP50: 1,
  volumeRatioP70: 1.5,
  volumeRatioP85: 1.8,
  turnoverRateP50: 3,
  turnoverRateP70: 6,
  turnoverRateP85: 10,
}

const INSUFFICIENT_STATUS: RankTrendDisplayStatus = {
  label: '样本不足',
  classKey: 'insufficient',
  tooltip: '快照样本不足，且资金确认不明显，暂不作为重点状态。',
}

const INVALID_QUOTE_STATUS: RankTrendDisplayStatus = {
  label: '样本不足',
  classKey: 'insufficient',
  tooltip: '行情价格或成交额无效，暂不参与状态分层。',
}

const SAMPLE_QUALITY_LABELS: Record<string, string> = {
  ok: '样本OK',
  degraded: '样本降级',
  insufficient: '样本不足',
  unknown: '样本未知',
}

const CYCLE_LABELS: Record<string, string> = {
  ignition: '启动',
  expansion: '扩散',
  crowded: '拥挤',
  reversal: '反转',
  cooling: '降温',
}

const RISK_LABELS: Record<string, string> = {
  crowded: '拥挤风险',
  money_divergence: '资金背离',
  weakening: '转弱预警',
  insufficient: '数据不足',
}

const RISK_CLASS_KEYS: Record<string, string> = {
  crowded: 'risk-crowded',
  money_divergence: 'risk-money_divergence',
  weakening: 'risk-weakening',
  insufficient: 'risk-insufficient',
}

function toNumber(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function hasValue(value: unknown): boolean {
  return value !== undefined && value !== null && value !== ''
}

function percentile(values: number[], ratio: number): number {
  const sorted = values.filter(value => Number.isFinite(value) && value > 0).sort((a, b) => a - b)
  if (!sorted.length) return 0

  const index = (sorted.length - 1) * ratio
  const lower = Math.floor(index)
  const upper = Math.ceil(index)
  if (lower === upper) return sorted[lower]

  return sorted[lower] + (sorted[upper] - sorted[lower]) * (index - lower)
}

export function buildRankTrendStatusContext(stocks: any[]): RankTrendStatusContext {
  const turnoverValues = stocks.map(stock => toNumber(stock?.turnover))
  const volumeRatioValues = stocks.map(stock => toNumber(stock?.volumeRatio))
  const turnoverRateValues = stocks.map(stock => toNumber(stock?.turnoverRate))

  return {
    turnoverP50: percentile(turnoverValues, 0.5),
    turnoverP70: percentile(turnoverValues, 0.7),
    turnoverP85: percentile(turnoverValues, 0.85),
    volumeRatioP50: percentile(volumeRatioValues, 0.5) || FALLBACK_STATUS_CONTEXT.volumeRatioP50,
    volumeRatioP70: percentile(volumeRatioValues, 0.7) || FALLBACK_STATUS_CONTEXT.volumeRatioP70,
    volumeRatioP85: percentile(volumeRatioValues, 0.85) || FALLBACK_STATUS_CONTEXT.volumeRatioP85,
    turnoverRateP50: percentile(turnoverRateValues, 0.5) || FALLBACK_STATUS_CONTEXT.turnoverRateP50,
    turnoverRateP70: percentile(turnoverRateValues, 0.7) || FALLBACK_STATUS_CONTEXT.turnoverRateP70,
    turnoverRateP85: percentile(turnoverRateValues, 0.85) || FALLBACK_STATUS_CONTEXT.turnoverRateP85,
  }
}

function getStatusContext(context?: RankTrendStatusContext): RankTrendStatusContext {
  return context ?? FALLBACK_STATUS_CONTEXT
}

function isSampleInsufficient(rankTrend?: RankTrendAnalysisResult | null): boolean {
  return !rankTrend || rankTrend.meta?.sampleQuality?.status === 'insufficient'
}

function isInvalidQuoteData(stock: any): boolean {
  if (!stock) return false

  const priceCandidate = stock.price ?? stock.latestPrice ?? stock.lastPrice ?? stock.close
  if (hasValue(priceCandidate)) {
    const price = Number(priceCandidate)
    if (!Number.isFinite(price) || price <= 0) return true
  }

  if (hasValue(stock.turnover)) {
    const turnover = Number(stock.turnover)
    if (!Number.isFinite(turnover) || turnover < 0) return true
  }

  return false
}

function isStrongMoney(stock: any): boolean {
  const zlje = toNumber(stock?.zlje)
  const zljzb = toNumber(stock?.zljzb)
  const cddje = toNumber(stock?.cddje)
  const cddjzb = toNumber(stock?.cddjzb)

  if (isEstimatedMoneyFlow(stock)) {
    return zlje > 0 && zljzb >= 10 && cddje > 0 && cddjzb >= 3
  }

  return zlje > 0 && zljzb >= 8 && (cddje > 0 || cddjzb >= 3)
}

function isEstimatedMoneyFlow(stock: any): boolean {
  return stock?.moneyFlowEstimated === true || stock?.moneyFlowSource === 'tdx_estimate'
}

function isMoneyWeak(stock: any): boolean {
  const zlje = toNumber(stock?.zlje)
  const zljzb = toNumber(stock?.zljzb)
  const cddje = toNumber(stock?.cddje)
  const cddjzb = toNumber(stock?.cddjzb)

  if (isEstimatedMoneyFlow(stock)) {
    return zljzb <= -8 && cddje < 0 && cddjzb <= -3
  }

  return zlje < 0 || zljzb <= -3 || (cddje < 0 && cddjzb <= 0)
}

function isHotAttention(rankTrend: RankTrendAnalysisResult | null | undefined, stock: any): boolean {
  const currentPercentile = toNumber(rankTrend?.meta?.currentPercentile)
  const compRank = toNumber(stock?.compRank ?? stock?.rank)
  const rankChange = toNumber(rankTrend?.meta?.change ?? stock?.rankChange)

  return currentPercentile >= 70 || (compRank > 0 && compRank <= 50) || rankChange > 0
}

function isHighCrowded(rankTrend: RankTrendAnalysisResult | null | undefined, stock: any): boolean {
  const change = toNumber(stock?.change)
  const volumeRatio = toNumber(stock?.volumeRatio)
  const turnoverRate = toNumber(stock?.turnoverRate)
  const currentPercentile = toNumber(rankTrend?.meta?.currentPercentile)

  return (change >= 8 || currentPercentile >= 88) && (volumeRatio >= 1.8 || turnoverRate >= 10)
}

function isMoneyNotWeak(stock: any): boolean {
  return !isMoneyWeak(stock)
}

function isTurnoverSupported(stock: any, context: RankTrendStatusContext): boolean {
  const turnover = toNumber(stock?.turnover)
  return turnover > 0 && turnover >= context.turnoverP50
}

function isVolumeRatioSupported(stock: any, context: RankTrendStatusContext): boolean {
  const volumeRatio = toNumber(stock?.volumeRatio)
  return volumeRatio > 0 && volumeRatio >= context.volumeRatioP50
}

function isTurnoverRateSupported(stock: any, context: RankTrendStatusContext): boolean {
  const turnoverRate = toNumber(stock?.turnoverRate)
  return turnoverRate > 0 && turnoverRate >= context.turnoverRateP50
}

function isMoneyAcceptanceSupported(stock: any, context: RankTrendStatusContext): boolean {
  return (
    isTurnoverSupported(stock, context) ||
    isVolumeRatioSupported(stock, context) ||
    isTurnoverRateSupported(stock, context)
  )
}

function isVolumeReasonable(stock: any, context: RankTrendStatusContext): boolean {
  const volumeRatio = toNumber(stock?.volumeRatio)
  const turnoverRate = toNumber(stock?.turnoverRate)
  return volumeRatio < context.volumeRatioP85 && turnoverRate < context.turnoverRateP85
}

function isNearLimitUp(stock: any): boolean {
  const change = toNumber(stock?.change)
  return change >= 9.5
}

function isVolumeAmplified(stock: any, context: RankTrendStatusContext): boolean {
  const turnover = toNumber(stock?.turnover)
  const volumeRatio = toNumber(stock?.volumeRatio)
  return (turnover > 0 && turnover >= context.turnoverP70) || volumeRatio >= context.volumeRatioP70
}

function isVolumeOverheated(stock: any, context: RankTrendStatusContext): boolean {
  const change = toNumber(stock?.change)
  const volumeRatio = toNumber(stock?.volumeRatio)
  const turnoverRate = toNumber(stock?.turnoverRate)
  return (change >= 8 || isNearLimitUp(stock)) && (volumeRatio >= context.volumeRatioP85 || turnoverRate >= context.turnoverRateP85)
}

export function classifyVolumeConfirmation(
  rankTrend?: RankTrendAnalysisResult | null,
  stock?: any,
  context?: RankTrendStatusContext,
): VolumeConfirmation {
  const statusContext = getStatusContext(context)
  const strongMoney = isStrongMoney(stock)
  const moneyWeak = isMoneyWeak(stock)
  const hotAttention = isHotAttention(rankTrend, stock)

  if (hotAttention && isVolumeAmplified(stock, statusContext) && moneyWeak) return 'divergent'
  if (isVolumeOverheated(stock, statusContext)) return 'overheated'

  const healthy =
    isTurnoverSupported(stock, statusContext) &&
    isVolumeRatioSupported(stock, statusContext) &&
    toNumber(stock?.turnoverRate) < statusContext.turnoverRateP85 &&
    !moneyWeak

  if (healthy) return 'healthy'

  const weak =
    (!isTurnoverSupported(stock, statusContext) || !isVolumeRatioSupported(stock, statusContext)) &&
    !strongMoney

  return weak ? 'weak' : 'healthy'
}

function createStrongMoneyStatus(volumeConfirmation: VolumeConfirmation, reason?: 'attentionWeak'): RankTrendDisplayStatus {
  const overheatedSuffix =
    volumeConfirmation === 'overheated'
      ? '量能偏热，不能直接视为主升确认。'
      : reason === 'attentionWeak'
        ? '注意力轨迹回落，但资金确认仍在，继续看后续留榜与承接。'
        : '资金确认成立，趋势持续性仍需后续快照确认。'

  return {
    label: '强资确认',
    classKey: 'strong_money',
    tooltip: `资金明显介入，但趋势样本仍需确认，重点看后续留榜和资金持续。${overheatedSuffix}`,
  }
}

// 状态判定优先级（风险优先于机会，数字越小优先级越高）：
//  (1) 无效行情 → 样本不足
//  (2) D_EXIT_RISK+资金走弱 → 转弱预警
//  (3) D_EXIT_RISK+强资金+高位 → 高位拥挤
//  (4) D_EXIT_RISK+强资金+承接 → 强资确认
//  (5) 量能背离/热+资金弱 → 资金背离
//  (6) C_CROWDED/高位拥挤 → 高位拥挤
//  (7) A_MAIN+过热 → 高位拥挤
//  (8) A_MAIN+资金不弱 → 主升确认
//  (9) B_IGNITION+资金不弱 → 点火观察
//  (10) 强资金+承接 → 强资确认
//  (11) 有热度 → 新入观察
//  (12) 兜底 → 样本不足/新入观察
export function getRankTrendDisplayStatus(
  rankTrend?: RankTrendAnalysisResult | null,
  stock?: any,
  context?: RankTrendStatusContext,
): RankTrendDisplayStatus {
  const statusContext = getStatusContext(context)
  const tier = rankTrend?.strategy?.candidateTier
  const insufficient = isSampleInsufficient(rankTrend)
  const hotAttention = isHotAttention(rankTrend, stock)
  const strongMoney = isStrongMoney(stock)
  const moneyWeak = isMoneyWeak(stock)
  const volumeConfirmation = classifyVolumeConfirmation(rankTrend, stock, statusContext)
  const volumeRatioSupported = isVolumeRatioSupported(stock, statusContext)
  const moneyAcceptanceSupported = isMoneyAcceptanceSupported(stock, statusContext)
  const volumeReasonable = isVolumeReasonable(stock, statusContext)

  if (isInvalidQuoteData(stock)) return INVALID_QUOTE_STATUS

  if (tier === 'D_EXIT_RISK') {
    if (moneyWeak) return CANDIDATE_TIER_STATUS.D_EXIT_RISK
    if (strongMoney && (volumeConfirmation === 'overheated' || isHighCrowded(rankTrend, stock))) {
      return CANDIDATE_TIER_STATUS.C_CROWDED
    }
    if (strongMoney && moneyAcceptanceSupported) {
      return createStrongMoneyStatus(volumeConfirmation, 'attentionWeak')
    }
    return CANDIDATE_TIER_STATUS.D_EXIT_RISK
  }

  if (volumeConfirmation === 'divergent' || (hotAttention && moneyWeak)) {
    return {
      label: '资金背离',
      classKey: 'money_divergence',
      tooltip: '热度仍在，但主力资金不支持，警惕冲高回落或诱多。',
    }
  }

  if (insufficient && strongMoney && volumeConfirmation === 'overheated') {
    return createStrongMoneyStatus(volumeConfirmation)
  }

  if (tier === 'C_CROWDED' || isHighCrowded(rankTrend, stock)) {
    return CANDIDATE_TIER_STATUS.C_CROWDED
  }

  if (tier === 'A_MAIN' && !insufficient && volumeConfirmation === 'overheated') {
    return CANDIDATE_TIER_STATUS.C_CROWDED
  }

  if (tier === 'A_MAIN' && !insufficient && isMoneyNotWeak(stock)) {
    return CANDIDATE_TIER_STATUS.A_MAIN
  }

  if (tier === 'B_IGNITION' && !insufficient && isMoneyNotWeak(stock)) {
    if (volumeConfirmation === 'healthy' && volumeRatioSupported && volumeReasonable) {
      return {
        ...CANDIDATE_TIER_STATUS.B_IGNITION,
        tooltip: '注意力开始启动，量能配合较好，但仍需后续半小时快照确认扩散。',
      }
    }
    return CANDIDATE_TIER_STATUS.B_IGNITION
  }

  if (strongMoney && moneyAcceptanceSupported) {
    return createStrongMoneyStatus(volumeConfirmation)
  }

  if (hotAttention) {
    return CANDIDATE_TIER_STATUS.N_NEUTRAL
  }

  return insufficient ? INSUFFICIENT_STATUS : CANDIDATE_TIER_STATUS.N_NEUTRAL
}

export function getRankTrendDisplayBreakdown(
  rankTrend?: RankTrendAnalysisResult | null,
  stock?: any,
  context?: RankTrendStatusContext,
): RankTrendDisplayBreakdown {
  const status = getRankTrendDisplayStatus(rankTrend, stock, context)
  const sampleStatus = rankTrend ? rankTrend.meta?.sampleQuality?.status ?? 'unknown' : 'insufficient'
  const stage = rankTrend?.cycle?.stage ?? ''
  const qualityLabel = SAMPLE_QUALITY_LABELS[sampleStatus] ?? '样本未知'
  const showQualityBadge = false
  const qualityBadgeLabel = ''
  const cycleLabel = stage ? CYCLE_LABELS[stage] ?? String(stage) : '-'
  const riskLabel = RISK_LABELS[status.classKey] ?? '正常'
  const tooltip = [
    `样本：${qualityLabel}`,
    `周期：${cycleLabel}`,
    `分层：${status.label}`,
    `风险：${riskLabel}`,
    status.tooltip,
  ].filter(Boolean).join('\n')

  return {
    qualityLabel,
    qualityBadgeLabel,
    showQualityBadge,
    cycleLabel,
    tierLabel: status.label,
    riskLabel,
    tooltip,
    classKeys: {
      quality: `quality-${sampleStatus}`,
      cycle: stage ? `cycle-${stage}` : 'cycle-empty',
      tier: status.classKey,
      risk: RISK_CLASS_KEYS[status.classKey] ?? 'risk-normal',
    },
  }
}
