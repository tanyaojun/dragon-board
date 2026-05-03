import type { MergedStock } from '@/types'
import type {
  AuthorityClass,
  BattlefieldDominance,
  BattlefieldRecord,
  ChaseRisk,
  LeaderRole,
  ReviewFrame,
  ReviewHotStock,
  ReviewSegment,
  ReviewThemeRef,
  SignalStrength,
} from './types'

const SNAPSHOT_DATE_PATTERN = /\d{4}-\d{2}-\d{2}/

export function extractSnapshotDate(snapshotKey: string): string | null {
  const match = String(snapshotKey || '').match(SNAPSHOT_DATE_PATTERN)
  return match?.[0] || null
}

export function normalizeDate(input?: string | Date | null): string {
  if (!input) return new Date().toISOString().slice(0, 10)
  if (input instanceof Date) return input.toISOString().slice(0, 10)
  const extracted = extractSnapshotDate(input)
  return extracted || input.slice(0, 10)
}

export function parseTimeToMinutes(time?: string | null): number | null {
  if (!time) return null
  const match = String(time).match(/(\d{1,2}):(\d{2})/)
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (Number.isNaN(hours) || Number.isNaN(minutes)) return null
  return hours * 60 + minutes
}

export function toSignalStrength(score: number): SignalStrength {
  if (score >= 70) return 'strong'
  if (score >= 40) return 'medium'
  return 'weak'
}

export function dominanceWeight(value: BattlefieldDominance): number {
  switch (value) {
    case 'DOMINANT':
      return 3
    case 'CONTESTED':
      return 2
    default:
      return 1
  }
}

export function authorityWeight(value: AuthorityClass): number {
  switch (value) {
    case 'TRUE_LEADER':
      return 6
    case 'THEME_COMMANDER':
      return 5
    case 'CARRY_PROXY':
      return 4
    case 'HEIGHT_ONLY':
      return 3
    case 'HEAT_ONLY':
      return 2
    default:
      return 1
  }
}

export function chaseRiskWeight(value: ChaseRisk): number {
  switch (value) {
    case 'LOW':
      return 1
    case 'MEDIUM':
      return 2
    case 'HIGH':
      return 3
    default:
      return 4
  }
}

export function roleOrder(value: LeaderRole): number {
  switch (value) {
    case 'MARKET_CORE':
      return 1
    case 'THEME_CORE':
      return 2
    case 'SPACE_CORE':
      return 3
    case 'TREND_CORE':
      return 4
    case 'EMOTION_CORE':
      return 5
    default:
      return 9
  }
}

export function inferBoardHeight(stock: Partial<MergedStock> | ReviewHotStock): number {
  if (typeof stock.boardHeight === 'number' && stock.boardHeight > 0) return stock.boardHeight
  if (typeof stock.highDays === 'number' && stock.highDays > 0) return stock.highDays
  const continuousDays = (stock as Partial<MergedStock>).continuousDays
  if (typeof continuousDays === 'number' && continuousDays > 0) return continuousDays
  const raw = String((stock as any).lianbanStr || '')
  const match = raw.match(/(\d+)/)
  return match ? Number(match[1]) : 0
}

export function leadStatusRank(status?: string | null): number {
  const text = String(status || '')
  if (!text) return 0
  if (text.includes('龙一') || text.includes('总龙')) return 5
  if (text.includes('龙二')) return 4
  if (text.includes('龙三')) return 3
  if (text.includes('领涨')) return 2
  if (text.includes('龙')) return 1
  return 0
}

export function buildThemeRefs(
  stock: Partial<MergedStock> | ReviewHotStock | null | undefined,
): ReviewThemeRef[] {
  const rawThemes = (stock?.themes || []) as any[]
  return rawThemes
    .map((theme) => {
      if (!theme) return null
      if (typeof theme === 'string') return { name: theme }
      const name = theme.name || theme.Name || theme.label
      if (!name) return null
      return {
        id: theme.id,
        name,
        heatScore: theme.heatScore,
      }
    })
    .filter(Boolean) as ReviewThemeRef[]
}

export function themeNamesFromStock(
  stock: Partial<MergedStock> | ReviewHotStock | null | undefined,
): string[] {
  return buildThemeRefs(stock).map((theme) => theme.name)
}

export function asArray<T>(input: T | T[] | null | undefined): T[] {
  if (Array.isArray(input)) return input
  if (input === null || input === undefined) return []
  return [input]
}

export function getStockTagNames(
  stock: Partial<MergedStock> | ReviewHotStock | null | undefined,
): string[] {
  const tags = asArray(stock?.tags as any[])
  return tags
    .map((tag) => {
      if (!tag) return null
      if (typeof tag === 'string') return tag
      return tag.Name || tag.name || null
    })
    .filter(Boolean) as string[]
}

export function buildHotStockFromMergedStock(stock: MergedStock, rank: number): ReviewHotStock {
  return {
    code: stock.code,
    name: stock.name,
    rank,
    compRank: stock.compRank,
    price: stock.price,
    change: stock.change,
    turnover: stock.turnover,
    turnoverRate: stock.turnoverRate,
    totalMV: stock.totalMV,
    cirMV: stock.cirMV,
    zlje: stock.zlje,
    volumeRatio: stock.volumeRatio,
    leadStatus: stock.leadStatus,
    leadTimes: stock.leadTimes,
    lianbanStr: stock.lianbanStr,
    popularity: stock.popularity,
    popularityChange: stock.popularityChange,
    institutionBuy: stock.institutionBuy,
    mainBuy: stock.mainBuy,
    mainSell: stock.mainSell,
    fengdan: stock.fengdan,
    maxFengdan: stock.maxFengdan,
    firstZtTime: stock.firstZtTime,
    lastZtTime: stock.lastZtTime,
    boardHeight: inferBoardHeight(stock),
    highDays: stock.highDays || stock.continuousDays || 0,
    hotness: stock.hotness,
    themes: buildThemeRefs(stock),
    tags: stock.tags,
    reason: stock.reason,
    isNew: stock.isNew,
    mainTheme: stock.mainTheme,
    themeHeat: stock.themeHeat,
    themeLevel: stock.themeLevel,
  }
}

export function getSegmentForIndex(index: number, total: number): ReviewSegment {
  if (total <= 1) return 'late'
  const ratio = (index + 1) / total
  if (ratio <= 0.3) return 'early'
  if (ratio <= 0.7) return 'mid'
  return 'late'
}

export function rankInFrame(frame: ReviewFrame, code: string): number | null {
  const index = frame.hotlist.findIndex((item) => item.code === code)
  return index >= 0 ? index + 1 : null
}

export function positiveNumber(value: unknown): number {
  const numeric = Number(value || 0)
  return Number.isFinite(numeric) ? numeric : 0
}

export function firstPositiveMetric(...values: unknown[]): number {
  for (const value of values) {
    const numeric = Number(value)
    if (Number.isFinite(numeric) && numeric > 0) return numeric
  }
  return 0
}

export function getNetCapital(
  stock: Partial<MergedStock> | ReviewHotStock | null | undefined,
): number {
  const zlje = positiveNumber(stock?.zlje)
  const mainBuy = positiveNumber((stock as any)?.mainBuy)
  const mainSell = positiveNumber((stock as any)?.mainSell)
  return zlje || mainBuy - mainSell
}

export function median(values: number[]): number {
  if (!values.length) return 0
  const sorted = [...values].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  if (sorted.length % 2 === 0) {
    return (sorted[mid - 1] + sorted[mid]) / 2
  }
  return sorted[mid]
}

export function uniq<T>(items: T[]): T[] {
  return Array.from(new Set(items))
}

export function battlefieldPriorityScore(battlefield: BattlefieldRecord): number {
  const dominanceBonus = dominanceWeight(battlefield.dominance) * 24
  const mainLineBonus = battlefield.isMainLine ? 12 : 0
  const correlationScore = Math.min(100, Math.round((battlefield.overallCorrelation || 0) * 100))
  const persistenceScore = Math.min(100, (battlefield.persistentDays || 0) * 20)
  const inflowScore = Math.min(
    100,
    Math.round(Math.log10(Math.abs(battlefield.themeMainNetInflow || 0) + 1) * 12),
  )

  return (
    dominanceBonus +
    mainLineBonus +
    battlefield.attentionScore * 0.3 +
    battlefield.themeHeatScore * 0.24 +
    persistenceScore * 0.16 +
    correlationScore * 0.15 +
    inflowScore * 0.1 +
    Math.min(12, battlefield.themeZtCount * 2)
  )
}

/**
 * 战场排序恢复成“主战场优先”，不再按类型硬切。
 */
export function sortBattlefields(battlefields: BattlefieldRecord[]): BattlefieldRecord[] {
  return [...battlefields].sort((a, b) => {
    const dominanceDiff = dominanceWeight(b.dominance) - dominanceWeight(a.dominance)
    if (dominanceDiff !== 0) return dominanceDiff

    const priorityDiff = battlefieldPriorityScore(b) - battlefieldPriorityScore(a)
    if (priorityDiff !== 0) return priorityDiff

    const heatDiff = b.themeHeatScore - a.themeHeatScore
    if (heatDiff !== 0) return heatDiff

    const persistenceDiff = b.persistentDays - a.persistentDays
    if (persistenceDiff !== 0) return persistenceDiff

    const correlationDiff = (b.overallCorrelation || 0) - (a.overallCorrelation || 0)
    if (correlationDiff !== 0) return correlationDiff

    const inflowDiff = (b.themeMainNetInflow || 0) - (a.themeMainNetInflow || 0)
    if (inflowDiff !== 0) return inflowDiff

    const carryDiff =
      b.candidateCodes.length +
      b.followerCodes.length -
      (a.candidateCodes.length + a.followerCodes.length)
    if (carryDiff !== 0) return carryDiff

    return a.themeName.localeCompare(b.themeName, 'zh-CN')
  })
}
