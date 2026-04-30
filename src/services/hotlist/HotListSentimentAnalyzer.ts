import {
  buildRankTrendStatusContext,
  getRankTrendAnalysis,
  getRankTrendDisplayStatus,
  type RankTrendDisplayStatus,
} from '../rankTrend/compat'
import {
  EMOTION_CYCLE_STAGE_CONFIG,
  getEmotionCycleStageSummary,
  type EmotionCycleStage,
} from '../../types/emotion'

export type HotListStatusLabel =
  | '主升确认'
  | '点火观察'
  | '强资确认'
  | '新入观察'
  | '高位拥挤'
  | '资金背离'
  | '转弱预警'
  | '样本不足'

export interface HotListDayMetrics {
  tradingDate?: string
  total: number
  topN: number
  upCount: number
  downCount: number
  flatCount: number
  upRatio: number
  downRatio: number
  hotTrin: number | null
  totalTurnover: number
  upTurnover: number
  downTurnover: number
  mainNetAmount: number
  superNetAmount: number
  avgChange: number
  nearLimitUpCount: number
  highGainCount: number
  highTurnoverCount: number
  statusCounts: Record<HotListStatusLabel, number>
  statusShares: Record<HotListStatusLabel, number>
  opportunityCount: number
  opportunityShare: number
  riskCount: number
  riskShare: number
  crowdedCount: number
  crowdedShare: number
}

export interface HotListThreeDayComparison {
  today: HotListDayMetrics
  yesterday?: HotListDayMetrics
  dayBefore?: HotListDayMetrics
  totalChange1d: number | null
  totalChange2d: number | null
  top100RetainFromYesterday: number
  top100RetainFromDayBefore: number
  top100RetainRateFromYesterday: number
  top100RetainRateFromDayBefore: number
  newTop100Count: number
  newTop100StrongMoneyCount: number
  yesterdayStrongRetainRate: number | null
  yesterdayCrowdedRiskCount: number
}

export interface HotListSentimentMetrics {
  topN: number
  comparison: HotListThreeDayComparison
}

export interface HotListSentimentResult {
  stage: EmotionCycleStage
  confidence: number
  summary: string
  metrics: HotListSentimentMetrics
  signals: string[]
  warnings: string[]
}

export interface HotListSentimentSnapshot {
  tradingDate?: string
  hotlist?: any[]
  rows?: any[]
}

export interface HotListSentimentInput {
  stocks: any[]
  yesterday?: HotListSentimentSnapshot | null
  dayBefore?: HotListSentimentSnapshot | null
  topN?: number
}

const STATUS_LABELS: HotListStatusLabel[] = [
  '主升确认',
  '点火观察',
  '强资确认',
  '新入观察',
  '高位拥挤',
  '资金背离',
  '转弱预警',
  '样本不足',
]

const ZERO_STATUS_COUNTS = STATUS_LABELS.reduce(
  (record, label) => {
    record[label] = 0
    return record
  },
  {} as Record<HotListStatusLabel, number>,
)

function toNumber(value: unknown): number {
  const number = Number(value)
  return Number.isFinite(number) ? number : 0
}

function normalizeCode(code: unknown): string {
  return String(code || '').trim()
}

function getRows(snapshot?: HotListSentimentSnapshot | null): any[] {
  if (!snapshot) return []
  if (Array.isArray(snapshot.hotlist)) return snapshot.hotlist
  if (Array.isArray(snapshot.rows)) return snapshot.rows
  return []
}

function getRank(stock: any, fallbackIndex: number): number {
  const rank = toNumber(stock?.compRank ?? stock?.rank)
  return rank > 0 ? rank : fallbackIndex + 1
}

function sortByRank(stocks: any[]): any[] {
  return [...(stocks || [])]
    .filter(stock => normalizeCode(stock?.code))
    .sort((a, b) => getRank(a, 9999) - getRank(b, 9999))
}

function createStatusCounts(): Record<HotListStatusLabel, number> {
  return { ...ZERO_STATUS_COUNTS }
}

function getFallbackHistoricalStatus(stock: any): RankTrendDisplayStatus {
  const change = toNumber(stock?.change)
  const rank = toNumber(stock?.compRank ?? stock?.rank)
  const zlje = toNumber(stock?.zlje)
  const zljzb = toNumber(stock?.zljzb)
  const cddje = toNumber(stock?.cddje)
  const cddjzb = toNumber(stock?.cddjzb)
  const volumeRatio = toNumber(stock?.volumeRatio)
  const turnoverRate = toNumber(stock?.turnoverRate)

  const strongMoney = zlje > 0 && zljzb >= 8 && (cddje > 0 || cddjzb >= 3)
  const moneyWeak = zlje < 0 || zljzb <= -8 || (cddje < 0 && cddjzb <= -3)
  const highPosition = change >= 8 || rank <= 30
  const overheated = highPosition && (volumeRatio >= 1.8 || turnoverRate >= 10)

  if (moneyWeak && (rank <= 80 || change > 0)) {
    return { label: '资金背离', classKey: 'money_divergence', tooltip: '' }
  }
  if (overheated) return { label: '高位拥挤', classKey: 'crowded', tooltip: '' }
  if (strongMoney) return { label: '强资确认', classKey: 'strong_money', tooltip: '' }
  if (change >= 3 || rank <= 100) return { label: '新入观察', classKey: 'new_watch', tooltip: '' }
  return { label: '样本不足', classKey: 'insufficient', tooltip: '' }
}

function getStockStatus(stock: any, contextStocks: any[]): RankTrendDisplayStatus {
  const context = buildRankTrendStatusContext(contextStocks)
  const rankTrend = getRankTrendAnalysis(stock)
  if (rankTrend) return getRankTrendDisplayStatus(rankTrend, stock, context)
  return getFallbackHistoricalStatus(stock)
}

function countByCode(stocks: any[]): Map<string, any> {
  const entries: Array<[string, any]> = []
  for (const stock of stocks) {
    const code = normalizeCode(stock?.code)
    if (code) entries.push([code, stock])
  }
  return new Map(entries)
}

function safeDivide(numerator: number, denominator: number): number {
  if (!denominator) return 0
  return numerator / denominator
}

function calculateHotTrin(upCount: number, downCount: number, upTurnover: number, downTurnover: number): number | null {
  if (upCount <= 0 || downCount <= 0 || upTurnover <= 0 || downTurnover <= 0) return null
  return (upCount / downCount) / (upTurnover / downTurnover)
}

function buildDayMetrics(stocks: any[], options: { topN: number; tradingDate?: string }): HotListDayMetrics {
  const sorted = sortByRank(stocks)
  const top = sorted.slice(0, options.topN)
  const statusCounts = createStatusCounts()

  let upCount = 0
  let downCount = 0
  let flatCount = 0
  let upTurnover = 0
  let downTurnover = 0
  let totalTurnover = 0
  let mainNetAmount = 0
  let superNetAmount = 0
  let changeSum = 0
  let nearLimitUpCount = 0
  let highGainCount = 0
  let highTurnoverCount = 0

  for (const stock of top) {
    const change = toNumber(stock?.change)
    const turnover = toNumber(stock?.turnover)
    const turnoverRate = toNumber(stock?.turnoverRate)
    const status = getStockStatus(stock, sorted)
    const label = STATUS_LABELS.includes(status.label as HotListStatusLabel)
      ? status.label as HotListStatusLabel
      : '样本不足'

    statusCounts[label] += 1
    totalTurnover += turnover
    mainNetAmount += toNumber(stock?.zlje)
    superNetAmount += toNumber(stock?.cddje)
    changeSum += change

    if (change > 0) {
      upCount += 1
      upTurnover += turnover
    } else if (change < 0) {
      downCount += 1
      downTurnover += turnover
    } else {
      flatCount += 1
    }

    if (change >= 9.5) nearLimitUpCount += 1
    if (change >= 7) highGainCount += 1
    if (turnoverRate >= 10) highTurnoverCount += 1
  }

  const statusShares = createStatusCounts()
  for (const label of STATUS_LABELS) {
    statusShares[label] = safeDivide(statusCounts[label], top.length)
  }

  const opportunityCount = statusCounts['主升确认'] + statusCounts['点火观察'] + statusCounts['强资确认'] + statusCounts['新入观察']
  const riskCount = statusCounts['资金背离'] + statusCounts['转弱预警']
  const crowdedCount = statusCounts['高位拥挤']

  return {
    tradingDate: options.tradingDate,
    total: sorted.length,
    topN: top.length,
    upCount,
    downCount,
    flatCount,
    upRatio: safeDivide(upCount, top.length),
    downRatio: safeDivide(downCount, top.length),
    hotTrin: calculateHotTrin(upCount, downCount, upTurnover, downTurnover),
    totalTurnover,
    upTurnover,
    downTurnover,
    mainNetAmount,
    superNetAmount,
    avgChange: safeDivide(changeSum, top.length),
    nearLimitUpCount,
    highGainCount,
    highTurnoverCount,
    statusCounts,
    statusShares,
    opportunityCount,
    opportunityShare: safeDivide(opportunityCount, top.length),
    riskCount,
    riskShare: safeDivide(riskCount, top.length),
    crowdedCount,
    crowdedShare: safeDivide(crowdedCount, top.length),
  }
}

function buildComparison(
  stocks: any[],
  yesterdaySnapshot: HotListSentimentSnapshot | null | undefined,
  dayBeforeSnapshot: HotListSentimentSnapshot | null | undefined,
  topN: number,
): HotListThreeDayComparison {
  const todayRows = sortByRank(stocks)
  const yesterdayRows = sortByRank(getRows(yesterdaySnapshot))
  const dayBeforeRows = sortByRank(getRows(dayBeforeSnapshot))

  const today = buildDayMetrics(todayRows, { topN })
  const yesterday = yesterdayRows.length
    ? buildDayMetrics(yesterdayRows, { topN, tradingDate: yesterdaySnapshot?.tradingDate })
    : undefined
  const dayBefore = dayBeforeRows.length
    ? buildDayMetrics(dayBeforeRows, { topN, tradingDate: dayBeforeSnapshot?.tradingDate })
    : undefined

  const todayTopCodes = new Set(todayRows.slice(0, topN).map(stock => normalizeCode(stock?.code)))
  const yesterdayTopCodes = new Set(yesterdayRows.slice(0, topN).map(stock => normalizeCode(stock?.code)))
  const dayBeforeTopCodes = new Set(dayBeforeRows.slice(0, topN).map(stock => normalizeCode(stock?.code)))
  const todayByCode = countByCode(todayRows)

  const top100RetainFromYesterday = [...todayTopCodes].filter(code => yesterdayTopCodes.has(code)).length
  const top100RetainFromDayBefore = [...todayTopCodes].filter(code => dayBeforeTopCodes.has(code)).length
  const newTop100Codes = [...todayTopCodes].filter(code => !yesterdayTopCodes.has(code))
  const newTop100StrongMoneyCount = newTop100Codes.filter((code) => {
    const stock = todayByCode.get(code)
    return stock && getStockStatus(stock, todayRows).label === '强资确认'
  }).length

  const yesterdayStrongCodes = yesterdayRows
    .slice(0, topN)
    .filter(stock => getStockStatus(stock, yesterdayRows).label === '强资确认')
    .map(stock => normalizeCode(stock?.code))
    .filter(Boolean)

  const yesterdayCrowdedCodes = yesterdayRows
    .slice(0, topN)
    .filter(stock => getStockStatus(stock, yesterdayRows).label === '高位拥挤')
    .map(stock => normalizeCode(stock?.code))
    .filter(Boolean)

  const yesterdayStrongRetainRate = yesterdayStrongCodes.length
    ? safeDivide(yesterdayStrongCodes.filter(code => todayTopCodes.has(code)).length, yesterdayStrongCodes.length)
    : null

  const yesterdayCrowdedRiskCount = yesterdayCrowdedCodes.filter((code) => {
    const stock = todayByCode.get(code)
    if (!stock) return false
    const label = getStockStatus(stock, todayRows).label
    return label === '资金背离' || label === '转弱预警'
  }).length

  return {
    today,
    yesterday,
    dayBefore,
    totalChange1d: yesterday ? today.total - yesterday.total : null,
    totalChange2d: dayBefore ? today.total - dayBefore.total : null,
    top100RetainFromYesterday,
    top100RetainFromDayBefore,
    top100RetainRateFromYesterday: safeDivide(top100RetainFromYesterday, Math.min(topN, yesterdayRows.length || topN)),
    top100RetainRateFromDayBefore: safeDivide(top100RetainFromDayBefore, Math.min(topN, dayBeforeRows.length || topN)),
    newTop100Count: newTop100Codes.length,
    newTop100StrongMoneyCount,
    yesterdayStrongRetainRate,
    yesterdayCrowdedRiskCount,
  }
}

function pushIf(target: string[], condition: boolean, text: string) {
  if (condition) target.push(text)
}

function isTrinStrong(value: number | null): boolean {
  return value !== null && value < 1
}

function isTrinWeak(value: number | null): boolean {
  return value !== null && value > 1.15
}

function resolveStage(comparison: HotListThreeDayComparison): {
  stage: EmotionCycleStage
  signals: string[]
  warnings: string[]
} {
  const today = comparison.today
  const yesterday = comparison.yesterday
  const signals: string[] = []
  const warnings: string[] = []

  const activeOpportunityShare = today.statusShares['强资确认'] + today.statusShares['点火观察']
  const riskShare = today.riskShare
  const crowdedShare = today.crowdedShare
  const totalExpanded = comparison.totalChange1d !== null ? comparison.totalChange1d > 0 : false
  const totalShrank = comparison.totalChange1d !== null ? comparison.totalChange1d < 0 : false
  const riskRising = Boolean(yesterday && today.riskShare > yesterday.riskShare + 0.04)
  const opportunityRising = Boolean(
    yesterday && activeOpportunityShare > yesterday.statusShares['强资确认'] + yesterday.statusShares['点火观察'] + 0.04,
  )
  const crowdedRising = Boolean(yesterday && crowdedShare > yesterday.crowdedShare + 0.04)

  pushIf(signals, totalExpanded, `热榜池较上一日扩张 ${comparison.totalChange1d} 只`)
  pushIf(warnings, totalShrank, `热榜池较上一日收缩 ${Math.abs(comparison.totalChange1d || 0)} 只`)
  pushIf(signals, today.upRatio >= 0.58, `前100上涨比例 ${(today.upRatio * 100).toFixed(0)}%`)
  pushIf(warnings, today.upRatio <= 0.42, `前100上涨比例偏低，仅 ${(today.upRatio * 100).toFixed(0)}%`)
  pushIf(signals, isTrinStrong(today.hotTrin), `热榜 TRIN ${today.hotTrin?.toFixed(2)}，上涨股成交承接占优`)
  pushIf(warnings, isTrinWeak(today.hotTrin), `热榜 TRIN ${today.hotTrin?.toFixed(2)}，上涨家数与成交承接不匹配`)
  pushIf(signals, opportunityRising, '强资确认与点火观察占比扩张')
  pushIf(warnings, riskRising, '资金背离与转弱预警占比上升')
  pushIf(warnings, crowdedRising, '高位拥挤占比上升')
  pushIf(signals, comparison.yesterdayStrongRetainRate !== null && comparison.yesterdayStrongRetainRate >= 0.6, '昨日强资确认留榜率较高')
  pushIf(warnings, comparison.yesterdayStrongRetainRate !== null && comparison.yesterdayStrongRetainRate <= 0.35, '昨日强资确认留榜率偏低')

  const retreat =
    riskShare >= 0.2 ||
    (riskRising && isTrinWeak(today.hotTrin)) ||
    (comparison.yesterdayStrongRetainRate !== null && comparison.yesterdayStrongRetainRate <= 0.25 && today.upRatio < 0.55)

  if (retreat) {
    return {
      stage: '退潮',
      signals,
      warnings: warnings.length ? warnings : ['风险状态占比偏高，先按防守阶段处理'],
    }
  }

  const climax =
    (crowdedShare >= 0.18 && today.upRatio >= 0.5) ||
    (today.nearLimitUpCount >= 8 && crowdedShare >= 0.12) ||
    (today.highGainCount >= 18 && today.highTurnoverCount >= 18 && riskShare < 0.2)

  if (climax) {
    return {
      stage: '高潮',
      signals: signals.length ? signals : ['前排高涨幅与高位拥挤同时增加'],
      warnings: warnings.length ? warnings : ['热度强但追击赔率下降，注意高位兑现风险'],
    }
  }

  const ferment =
    activeOpportunityShare >= 0.18 &&
    today.statusShares['强资确认'] >= 0.08 &&
    today.upRatio >= 0.48 &&
    riskShare < 0.16 &&
    (isTrinStrong(today.hotTrin) || comparison.yesterdayStrongRetainRate === null || comparison.yesterdayStrongRetainRate >= 0.45)

  if (ferment) {
    return {
      stage: '发酵',
      signals: signals.length ? signals : ['强资确认与点火观察形成有效扩散'],
      warnings,
    }
  }

  const start =
    (totalExpanded || opportunityRising || comparison.newTop100Count >= 25) &&
    today.upRatio >= 0.42 &&
    riskShare < 0.18

  if (start) {
    return {
      stage: '启动',
      signals: signals.length ? signals : ['热榜新增和机会状态开始改善'],
      warnings,
    }
  }

  return {
    stage: '冰点',
    signals: signals.length ? signals : ['热榜机会状态尚未形成有效扩散'],
    warnings: warnings.length ? warnings : ['强资确认与点火观察偏少，等待下一轮扩散确认'],
  }
}

function calculateConfidence(stage: EmotionCycleStage, signals: string[], warnings: string[]): number {
  const base = EMOTION_CYCLE_STAGE_CONFIG[stage].confidenceBase
  const adjustment = Math.min(18, signals.length * 5) - Math.min(12, warnings.length * 3)
  return Math.max(45, Math.min(90, base + adjustment))
}

export class HotListSentimentAnalyzer {
  analyze(input: HotListSentimentInput): HotListSentimentResult {
    const topN = input.topN && input.topN > 0 ? input.topN : 100
    const comparison = buildComparison(input.stocks || [], input.yesterday, input.dayBefore, topN)
    const stageEvidence = resolveStage(comparison)
    const confidence = calculateConfidence(stageEvidence.stage, stageEvidence.signals, stageEvidence.warnings)

    return {
      stage: stageEvidence.stage,
      confidence,
      summary: getEmotionCycleStageSummary(stageEvidence.stage),
      metrics: {
        topN,
        comparison,
      },
      signals: stageEvidence.signals,
      warnings: stageEvidence.warnings,
    }
  }
}

export const hotListSentimentAnalyzer = new HotListSentimentAnalyzer()
