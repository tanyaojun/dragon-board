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
  activeOpportunityCount: number
  activeOpportunityShare: number
  opportunityCount: number
  opportunityShare: number
  riskCount: number
  riskShare: number
  crowdedCount: number
  crowdedShare: number
}

export type HotListLayerKey = 'top20' | 'top50' | 'top100'

export type HotListLayerSet = Record<HotListLayerKey, HotListDayMetrics>

export interface HotListYesterdayStrongPerformance {
  count: number
  matchedCount: number
  retainedTop100Count: number
  avgChange: number | null
  positiveCount: number
  positiveRate: number | null
  weakeningCount: number
  weakeningRate: number | null
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
  yesterdayStrongPerformance: HotListYesterdayStrongPerformance
}

export interface HotListSentimentMetrics {
  topN: number
  layers: HotListLayerSet
  comparison: HotListThreeDayComparison
}

export type HotListSentimentRiskLevel = '低' | '中' | '高'

export interface HotListSentimentResult {
  stage: EmotionCycleStage
  riskLevel: HotListSentimentRiskLevel
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

const YESTERDAY_STRONG_LABELS = new Set<HotListStatusLabel>([
  '主升确认',
  '点火观察',
  '强资确认',
])

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

function createStockStatusResolver(contextStocks: any[]): (stock: any) => RankTrendDisplayStatus {
  const context = buildRankTrendStatusContext(contextStocks)
  return (stock: any) => {
    const rankTrend = getRankTrendAnalysis(stock)
    if (rankTrend) return getRankTrendDisplayStatus(rankTrend, stock, context)
    return getFallbackHistoricalStatus(stock)
  }
}

function getStockStatus(stock: any, contextStocks: any[]): RankTrendDisplayStatus {
  return createStockStatusResolver(contextStocks)(stock)
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

function buildDayMetricsFromSorted(sorted: any[], options: { topN: number; tradingDate?: string }): HotListDayMetrics {
  const top = sorted.slice(0, options.topN)
  const statusCounts = createStatusCounts()
  const getStatus = createStockStatusResolver(sorted)

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
    const status = getStatus(stock)
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

  const activeOpportunityCount = statusCounts['主升确认'] + statusCounts['点火观察'] + statusCounts['强资确认']
  const opportunityCount = activeOpportunityCount + statusCounts['新入观察']
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
    activeOpportunityCount,
    activeOpportunityShare: safeDivide(activeOpportunityCount, top.length),
    opportunityCount,
    opportunityShare: safeDivide(opportunityCount, top.length),
    riskCount,
    riskShare: safeDivide(riskCount, top.length),
    crowdedCount,
    crowdedShare: safeDivide(crowdedCount, top.length),
  }
}

function buildDayMetrics(stocks: any[], options: { topN: number; tradingDate?: string }): HotListDayMetrics {
  return buildDayMetricsFromSorted(sortByRank(stocks), options)
}

function buildLayerMetrics(stocks: any[], tradingDate?: string): HotListLayerSet {
  const sorted = sortByRank(stocks)
  return {
    top20: buildDayMetricsFromSorted(sorted, { topN: 20, tradingDate }),
    top50: buildDayMetricsFromSorted(sorted, { topN: 50, tradingDate }),
    top100: buildDayMetricsFromSorted(sorted, { topN: 100, tradingDate }),
  }
}

function createEmptyYesterdayStrongPerformance(): HotListYesterdayStrongPerformance {
  return {
    count: 0,
    matchedCount: 0,
    retainedTop100Count: 0,
    avgChange: null,
    positiveCount: 0,
    positiveRate: null,
    weakeningCount: 0,
    weakeningRate: null,
  }
}

function buildYesterdayStrongPerformance(
  yesterdayRows: any[],
  todayRows: any[],
  topN: number,
): HotListYesterdayStrongPerformance {
  if (!yesterdayRows.length) return createEmptyYesterdayStrongPerformance()

  const getYesterdayStatus = createStockStatusResolver(yesterdayRows)
  const getTodayStatus = createStockStatusResolver(todayRows)
  const todayByCode = countByCode(todayRows)
  const todayTopCodes = new Set(todayRows.slice(0, topN).map(stock => normalizeCode(stock?.code)))

  const strongCodes = yesterdayRows
    .slice(0, topN)
    .filter((stock) => {
      const label = getYesterdayStatus(stock).label as HotListStatusLabel
      return YESTERDAY_STRONG_LABELS.has(label)
    })
    .map(stock => normalizeCode(stock?.code))
    .filter(Boolean)

  if (!strongCodes.length) return createEmptyYesterdayStrongPerformance()

  let matchedCount = 0
  let retainedTop100Count = 0
  let changeSum = 0
  let positiveCount = 0
  let weakeningCount = 0

  for (const code of strongCodes) {
    const stock = todayByCode.get(code)
    if (!stock) {
      weakeningCount += 1
      continue
    }

    const change = toNumber(stock?.change)
    const todayStatus = getTodayStatus(stock).label

    matchedCount += 1
    changeSum += change
    if (change > 0) positiveCount += 1
    if (todayTopCodes.has(code)) retainedTop100Count += 1
    if (change <= -2 || todayStatus === '资金背离' || todayStatus === '转弱预警') {
      weakeningCount += 1
    }
  }

  return {
    count: strongCodes.length,
    matchedCount,
    retainedTop100Count,
    avgChange: matchedCount ? safeDivide(changeSum, matchedCount) : null,
    positiveCount,
    positiveRate: matchedCount ? safeDivide(positiveCount, matchedCount) : null,
    weakeningCount,
    weakeningRate: safeDivide(weakeningCount, strongCodes.length),
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
  const getTodayStatus = createStockStatusResolver(todayRows)
  const getYesterdayStatus = createStockStatusResolver(yesterdayRows)

  const today = buildDayMetricsFromSorted(todayRows, { topN })
  const yesterday = yesterdayRows.length
    ? buildDayMetricsFromSorted(yesterdayRows, { topN, tradingDate: yesterdaySnapshot?.tradingDate })
    : undefined
  const dayBefore = dayBeforeRows.length
    ? buildDayMetricsFromSorted(dayBeforeRows, { topN, tradingDate: dayBeforeSnapshot?.tradingDate })
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
    return stock && getTodayStatus(stock).label === '强资确认'
  }).length

  const yesterdayStrongCodes = yesterdayRows
    .slice(0, topN)
    .filter(stock => getYesterdayStatus(stock).label === '强资确认')
    .map(stock => normalizeCode(stock?.code))
    .filter(Boolean)

  const yesterdayCrowdedCodes = yesterdayRows
    .slice(0, topN)
    .filter(stock => getYesterdayStatus(stock).label === '高位拥挤')
    .map(stock => normalizeCode(stock?.code))
    .filter(Boolean)

  const yesterdayStrongRetainRate = yesterdayStrongCodes.length
    ? safeDivide(yesterdayStrongCodes.filter(code => todayTopCodes.has(code)).length, yesterdayStrongCodes.length)
    : null

  const yesterdayCrowdedRiskCount = yesterdayCrowdedCodes.filter((code) => {
    const stock = todayByCode.get(code)
    if (!stock) return false
    const label = getTodayStatus(stock).label
    return label === '资金背离' || label === '转弱预警'
  }).length
  const yesterdayStrongPerformance = buildYesterdayStrongPerformance(yesterdayRows, todayRows, topN)

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
    yesterdayStrongPerformance,
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

type TapeStrengthLevel = 'strong' | 'firm' | 'mixed' | 'weak'
type MoneyAcceptanceLevel = 'strong' | 'neutral' | 'weak' | 'unknown'
type OpportunityExpansionLevel = 'broad' | 'improving' | 'normal' | 'scarce'
type RiskPressureLevel = 'severe' | 'high' | 'crowded' | 'low'
type ContinuityLevel = 'strong' | 'normal' | 'weak'

interface StageEvidence<T extends string> {
  level: T
  signals: string[]
  warnings: string[]
}

function evaluateTapeStrength(today: HotListDayMetrics, layers?: HotListLayerSet): StageEvidence<TapeStrengthLevel> {
  const top20 = layers?.top20 ?? today
  const top50 = layers?.top50 ?? today
  const top100 = layers?.top100 ?? today
  const signals: string[] = []
  const warnings: string[] = []

  const strong = top20.upRatio >= 0.65 && top50.upRatio >= 0.55 && top100.upRatio >= 0.55
  const firm = top20.upRatio >= 0.6 && top100.upRatio >= 0.48
  const weak = top100.upRatio <= 0.42 || (top20.upRatio < 0.5 && top50.upRatio < 0.45)
  const level: TapeStrengthLevel = strong ? 'strong' : firm ? 'firm' : weak ? 'weak' : 'mixed'

  pushIf(signals, strong, '前20/前50/前100上涨扩散较强')
  pushIf(signals, !strong && firm, '前排上涨修复，前100仍有承接')
  pushIf(signals, today.nearLimitUpCount >= 8, `前100近涨停 ${today.nearLimitUpCount} 只`)
  pushIf(signals, today.highGainCount >= 18, `前100高涨幅 ${today.highGainCount} 只`)
  pushIf(warnings, weak, `热榜上涨宽度偏弱，前100上涨 ${(top100.upRatio * 100).toFixed(0)}%`)

  return { level, signals, warnings }
}

function evaluateMoneyAcceptance(today: HotListDayMetrics): StageEvidence<MoneyAcceptanceLevel> {
  const signals: string[] = []
  const warnings: string[] = []
  let level: MoneyAcceptanceLevel = 'neutral'

  if (today.hotTrin === null) {
    level = 'unknown'
  } else if (isTrinStrong(today.hotTrin)) {
    level = 'strong'
    signals.push(`热榜 TRIN ${today.hotTrin.toFixed(2)}，上涨股成交承接占优`)
  } else if (isTrinWeak(today.hotTrin)) {
    level = 'weak'
    warnings.push(`热榜 TRIN ${today.hotTrin.toFixed(2)}，上涨家数与成交承接不匹配`)
  }

  return { level, signals, warnings }
}

function evaluateOpportunityExpansion(comparison: HotListThreeDayComparison): StageEvidence<OpportunityExpansionLevel> {
  const today = comparison.today
  const yesterday = comparison.yesterday
  const signals: string[] = []
  const warnings: string[] = []
  const activeOpportunityShare = today.activeOpportunityShare
  const strongMoneyShare = today.statusShares['强资确认']
  const opportunityRising = Boolean(
    yesterday && activeOpportunityShare > yesterday.activeOpportunityShare + 0.04,
  )

  const broad = activeOpportunityShare >= 0.18 && strongMoneyShare >= 0.08
  const improving = opportunityRising || comparison.newTop100Count >= 25
  const scarce = activeOpportunityShare < 0.08
  const level: OpportunityExpansionLevel = broad ? 'broad' : improving ? 'improving' : scarce ? 'scarce' : 'normal'

  pushIf(signals, broad, `强资确认与点火观察形成扩散，占比 ${(activeOpportunityShare * 100).toFixed(0)}%`)
  pushIf(signals, !broad && opportunityRising, '有效机会占比较昨日改善')
  pushIf(signals, !broad && comparison.newTop100Count >= 25, `今日新入前100 ${comparison.newTop100Count} 只`)
  pushIf(warnings, scarce, `有效机会偏少，占比 ${(activeOpportunityShare * 100).toFixed(0)}%`)

  return { level, signals, warnings }
}

function evaluateRiskPressure(comparison: HotListThreeDayComparison): StageEvidence<RiskPressureLevel> {
  const today = comparison.today
  const yesterday = comparison.yesterday
  const signals: string[] = []
  const warnings: string[] = []
  const riskRising = Boolean(yesterday && today.riskShare > yesterday.riskShare + 0.04)
  const crowdedRising = Boolean(yesterday && today.crowdedShare > yesterday.crowdedShare + 0.04)

  let level: RiskPressureLevel = 'low'
  if (today.riskShare >= 0.35) {
    level = 'severe'
  } else if (today.riskShare >= 0.2 || riskRising) {
    level = 'high'
  } else if (today.crowdedShare >= 0.18 || crowdedRising) {
    level = 'crowded'
  }

  pushIf(warnings, today.riskShare >= 0.35, `风险压力 ${(today.riskShare * 100).toFixed(0)}%，资金背离与转弱预警偏高`)
  pushIf(warnings, today.riskShare >= 0.2 && today.riskShare < 0.35, `风险压力 ${(today.riskShare * 100).toFixed(0)}%`)
  pushIf(warnings, riskRising, '资金背离与转弱预警占比上升')
  pushIf(warnings, today.crowdedShare >= 0.18, `高位拥挤 ${(today.crowdedShare * 100).toFixed(0)}%`)
  pushIf(warnings, crowdedRising, '高位拥挤占比上升')
  pushIf(signals, level === 'low', '风险压力暂未扩散')

  return { level, signals, warnings }
}

function evaluateContinuity(comparison: HotListThreeDayComparison): StageEvidence<ContinuityLevel> {
  const signals: string[] = []
  const warnings: string[] = []
  const retainRate = comparison.yesterdayStrongRetainRate
  const performance = comparison.yesterdayStrongPerformance
  const positiveRate = performance.positiveRate
  const weakeningRate = performance.weakeningRate
  const weak =
    (weakeningRate !== null && weakeningRate >= 0.45) ||
    (retainRate !== null && retainRate <= 0.25)
  const strong =
    !weak &&
    ((positiveRate !== null && positiveRate >= 0.6) ||
      (retainRate !== null && retainRate >= 0.6))

  pushIf(signals, retainRate !== null && retainRate >= 0.6, '昨日强资确认留榜率较高')
  pushIf(warnings, retainRate !== null && retainRate <= 0.25, '昨日强资确认留榜率偏低')
  pushIf(
    signals,
    positiveRate !== null && positiveRate >= 0.6,
    `昨日强票今日正收益率 ${(((positiveRate ?? 0) * 100)).toFixed(0)}%`,
  )
  pushIf(
    warnings,
    weakeningRate !== null && weakeningRate >= 0.45,
    `昨日强票转弱或掉榜率 ${(((weakeningRate ?? 0) * 100)).toFixed(0)}%`,
  )

  return { level: weak ? 'weak' : strong ? 'strong' : 'normal', signals, warnings }
}

function isRiskElevated(risk: RiskPressureLevel): boolean {
  return risk === 'high' || risk === 'severe'
}

function resolveRiskLevel(
  riskPressure: StageEvidence<RiskPressureLevel>,
  continuity: StageEvidence<ContinuityLevel>,
): HotListSentimentRiskLevel {
  if (riskPressure.level === 'severe' || (riskPressure.level === 'high' && continuity.level === 'weak')) {
    return '高'
  }
  if (riskPressure.level === 'high' || riskPressure.level === 'crowded' || continuity.level === 'weak') {
    return '中'
  }
  return '低'
}

function resolveStage(comparison: HotListThreeDayComparison, layers?: HotListLayerSet): {
  stage: EmotionCycleStage
  riskLevel: HotListSentimentRiskLevel
  signals: string[]
  warnings: string[]
} {
  const today = comparison.today
  const tapeStrength = evaluateTapeStrength(today, layers)
  const moneyAcceptance = evaluateMoneyAcceptance(today)
  const opportunityExpansion = evaluateOpportunityExpansion(comparison)
  const riskPressure = evaluateRiskPressure(comparison)
  const continuity = evaluateContinuity(comparison)
  const signals = [
    ...tapeStrength.signals,
    ...moneyAcceptance.signals,
    ...opportunityExpansion.signals,
    ...riskPressure.signals,
    ...continuity.signals,
  ]
  const warnings = [
    ...tapeStrength.warnings,
    ...moneyAcceptance.warnings,
    ...opportunityExpansion.warnings,
    ...riskPressure.warnings,
    ...continuity.warnings,
  ]

  const totalExpanded = comparison.totalChange1d !== null ? comparison.totalChange1d > 0 : false
  const totalShrank = comparison.totalChange1d !== null ? comparison.totalChange1d < 0 : false
  const riskElevated = isRiskElevated(riskPressure.level)
  const riskLevel = resolveRiskLevel(riskPressure, continuity)
  const tapeWeak = tapeStrength.level === 'weak'
  const tapeStrong = tapeStrength.level === 'strong'
  const tapeAtLeastFirm = tapeStrength.level === 'strong' || tapeStrength.level === 'firm'
  const moneyWeak = moneyAcceptance.level === 'weak'
  const moneyNotWeak = moneyAcceptance.level !== 'weak'
  const effectiveSpread =
    today.activeOpportunityShare >= 0.12 &&
    today.statusShares['强资确认'] >= 0.08
  const broadSpread = opportunityExpansion.level === 'broad'
  const highHeat =
    today.nearLimitUpCount >= 10 ||
    (today.highGainCount >= 25 && today.highTurnoverCount >= 20)
  const severeRiskWithShrinkingBreadth =
    riskPressure.level === 'severe' &&
    totalShrank &&
    opportunityExpansion.level !== 'broad' &&
    moneyAcceptance.level !== 'strong'

  pushIf(signals, totalExpanded, `热榜池较上一日扩张 ${comparison.totalChange1d} 只`)
  pushIf(warnings, totalShrank, `热榜池较上一日收缩 ${Math.abs(comparison.totalChange1d || 0)} 只`)
  pushIf(
    warnings,
    riskLevel === '高' && !tapeWeak && !moneyWeak,
    `风险等级高，但上涨和成交承接尚未破坏，按阶段主方向处理`,
  )

  const retreat =
    severeRiskWithShrinkingBreadth ||
    (riskElevated && (tapeWeak || moneyWeak)) ||
    (riskPressure.level === 'severe' && continuity.level === 'weak' && today.upRatio < 0.52) ||
    (totalShrank && opportunityExpansion.level === 'scarce' && today.upRatio < 0.5)

  if (retreat) {
    return {
      stage: '退潮',
      riskLevel,
      signals,
      warnings: warnings.length ? warnings : ['风险状态占比偏高，先按防守阶段处理'],
    }
  }

  const climax =
    tapeStrong &&
    moneyNotWeak &&
    (
      (moneyAcceptance.level === 'strong' && highHeat && broadSpread) ||
      (today.nearLimitUpCount >= 8 && today.crowdedShare >= 0.18 && broadSpread) ||
      (today.crowdedShare >= 0.28 && today.activeOpportunityShare >= 0.22)
    )

  if (climax) {
    return {
      stage: '高潮',
      riskLevel,
      signals: signals.length ? signals : ['前排高涨幅与高位拥挤同时增加'],
      warnings: warnings.length ? warnings : ['热度强但追击赔率下降，注意高位兑现风险'],
    }
  }

  const ferment =
    (opportunityExpansion.level === 'broad' || effectiveSpread) &&
    tapeAtLeastFirm &&
    moneyNotWeak

  if (ferment) {
    return {
      stage: '发酵',
      riskLevel,
      signals: signals.length ? signals : ['强资确认与点火观察形成有效扩散'],
      warnings,
    }
  }

  const start =
    (totalExpanded || opportunityExpansion.level === 'improving' || comparison.newTop100Count >= 25) &&
    today.upRatio >= 0.42 &&
    moneyNotWeak &&
    !tapeWeak

  if (start) {
    return {
      stage: '启动',
      riskLevel,
      signals: signals.length ? signals : ['热榜新增和机会状态开始改善'],
      warnings,
    }
  }

  return {
    stage: '冰点',
    riskLevel,
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
    const layers = buildLayerMetrics(input.stocks || [])
    const comparison = buildComparison(input.stocks || [], input.yesterday, input.dayBefore, topN)
    const stageEvidence = resolveStage(comparison, layers)
    const confidence = calculateConfidence(stageEvidence.stage, stageEvidence.signals, stageEvidence.warnings)

    return {
      stage: stageEvidence.stage,
      riskLevel: stageEvidence.riskLevel,
      confidence,
      summary: getEmotionCycleStageSummary(stageEvidence.stage),
      metrics: {
        topN,
        layers,
        comparison,
      },
      signals: stageEvidence.signals,
      warnings: stageEvidence.warnings,
    }
  }
}

export const hotListSentimentAnalyzer = new HotListSentimentAnalyzer()
