import {
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  type RankTrendSnapshotType,
} from '../../type/rankTrendDefaults'

export interface SnapshotQualityGateOptions {
  enabled?: boolean
  strict?: boolean
  minHotlistSize?: number
  minSnapshotCount?: number
  requiredType?: RankTrendSnapshotType
}

type SnapshotFeatureCoverage = 'full' | 'partial'
// formal validation coverage 用来区分“能否作为正式验证样本”而不是“字段越多越好”的泛质量分。
export type SnapshotFormalValidationCoverage = 'full' | 'legacy_core' | 'optimizer_core' | 'partial'

type SnapshotMetadata = {
  version?: string
  featureCoverage?: SnapshotFeatureCoverage
  totalStocks?: number
  marketMode?: string
  dataVersion?: number
  timestamp?: number
}

type SnapshotHotlistItem = {
  code?: string
  stockCode?: string
  securityCode?: string
  symbol?: string
  rank?: number
  compRank?: number
  currentRank?: number
  price?: number
  currentPrice?: number
  latestPrice?: number
  lastPrice?: number
  platforms?: number
  avgRankNum?: number
  change?: number
  speed?: number
  turnover?: number
  turnoverRate?: number
  volumeRatio?: number
  zlje?: number
  zljzb?: number
  cddje?: number
  cddjzb?: number
  pe?: number
}

type SnapshotPayload = {
  type?: string
  timestamp?: number
  metadata?: SnapshotMetadata
  hotlist?: SnapshotHotlistItem[]
}

export interface SnapshotQualityGateResult {
  passed: boolean
  severity: 'pass' | 'warn' | 'fail'
  strict: boolean
  issues: string[]
  stats: {
    totalSnapshots: number
    validQuarterHourCount: number
    invalidTypeCount: number
    nonMonotonicTimestampCount: number
    duplicateKeyCount: number
    missingSnapshotCount: number
    emptyHotlistCount: number
    lowHotlistCount: number
    missingCoreFieldCount: number
    fullFeatureCoverageCount?: number
    partialFeatureCoverageCount?: number
    legacyCompatibleCount?: number
  }
}

export interface SnapshotSeriesItem {
  date: string
  snapshot: SnapshotPayload | null | undefined
}

export interface FormalValidationSnapshotSelection {
  snapshots: SnapshotSeriesItem[]
  autoAdjusted: boolean
  requestedCount: number
  selectedCount: number
  emptyHotlistCount: number
  legacyCompatibleCount: number
  nonEmptyPartialCount: number
  selectedStartDate: string | null
  selectedEndDate: string | null
}

export interface SnapshotSeriesFormalValidationSummary {
  coverage: SnapshotFormalValidationCoverage
  totalNonEmptySnapshots: number
  fullSnapshotCount: number
  legacyCoreSnapshotCount: number
  optimizerCoreSnapshotCount: number
  incompatibleSnapshotCount: number
  emptyHotlistCount: number
}

function parseDateKey(date: string): number {
  const cleaned = String(date || '').replace(/^\[[^\]]+\]\s*/, '').trim()
  const parsed = Date.parse(cleaned.replace(/\//g, '-'))
  return Number.isFinite(parsed) ? parsed : 0
}

function resolveNumber(...candidates: unknown[]): number {
  for (const candidate of candidates) {
    const parsed = Number(candidate)
    if (Number.isFinite(parsed)) return parsed
  }
  return Number.NaN
}

function resolvePositiveNumber(...candidates: unknown[]): number {
  for (const candidate of candidates) {
    const parsed = Number(candidate)
    if (Number.isFinite(parsed) && parsed > 0) return parsed
  }
  return Number.NaN
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null
}

function normalizeFeatureCoverage(value: unknown): SnapshotFeatureCoverage | null {
  return value === 'full' || value === 'partial' ? value : null
}

function normalizeVersionToken(value: unknown): string {
  const raw = String(value ?? '').trim().toLowerCase()
  if (!raw) return ''
  return raw.startsWith('v') ? raw.slice(1) : raw
}

function parseVersionParts(value: unknown): number[] {
  const normalized = normalizeVersionToken(value)
  if (!normalized) return []

  const matches = normalized.match(/\d+/g)
  if (!matches) return []

  return matches
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item >= 0)
}

export function compareSnapshotVersion(left: unknown, right: unknown): number {
  const leftParts = parseVersionParts(left)
  const rightParts = parseVersionParts(right)
  const length = Math.max(leftParts.length, rightParts.length)

  for (let index = 0; index < length; index++) {
    const leftPart = leftParts[index] ?? 0
    const rightPart = rightParts[index] ?? 0
    if (leftPart > rightPart) return 1
    if (leftPart < rightPart) return -1
  }

  return 0
}

function normalizeSnapshotTypeValue(type: unknown): RankTrendSnapshotType | null {
  const normalized = String(type ?? '')
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, '_')

  if (
    normalized === 'quarter_hour' ||
    normalized === 'quarterhour' ||
    normalized === 'quarter_hour_snapshot' ||
    normalized === '15m' ||
    normalized === '15min' ||
    normalized === '15_min'
  ) {
    return 'quarter_hour'
  }
  if (normalized === 'half_hour' || normalized === 'halfhour' || normalized === '30m' || normalized === '30min' || normalized === '30_min') {
    return 'half_hour'
  }
  if (normalized === 'hourly' || normalized === '1h' || normalized === '60m' || normalized === '60min') {
    return 'hourly'
  }
  if (normalized === 'daily' || normalized === 'day' || normalized === '1d') {
    return 'daily'
  }

  return null
}

function normalizeSnapshotCode(stock: Record<string, unknown>): string {
  for (const candidate of [stock.code, stock.stockCode, stock.securityCode, stock.symbol]) {
    const code = String(candidate ?? '').trim()
    if (code) return code
  }
  return ''
}

function normalizeSnapshotRank(stock: Record<string, unknown>, fallbackRank: number): number {
  const resolved = resolvePositiveNumber(stock.rank, stock.compRank, stock.currentRank)
  return Number.isFinite(resolved) ? resolved : fallbackRank
}

function normalizeSnapshotPrice(stock: Record<string, unknown>): number {
  return resolveNumber(stock.price, stock.currentPrice, stock.latestPrice, stock.lastPrice)
}

function normalizeSnapshotHotlist(hotlist: unknown): SnapshotHotlistItem[] {
  if (!Array.isArray(hotlist)) return []

  return hotlist
    .filter((item): item is Record<string, unknown> => !!item && typeof item === 'object')
    .map((stock, index) => {
      const code = normalizeSnapshotCode(stock)
      const rank = normalizeSnapshotRank(stock, index + 1)
      const price = normalizeSnapshotPrice(stock)
      const normalized: SnapshotHotlistItem = {
        ...(stock as SnapshotHotlistItem),
        code,
        rank,
      }
      if (Number.isFinite(price)) normalized.price = price
      return normalized
    })
}

function countEnhancedCoverageHotlistItems(hotlist: SnapshotHotlistItem[]): number {
  return hotlist.filter((stock) => {
    const platforms = Number(stock.platforms)
    const avgRankNum = Number(stock.avgRankNum)
    const compRank = Number(stock.compRank)
    return (
      (Number.isFinite(platforms) && platforms > 0) ||
      (Number.isFinite(avgRankNum) && avgRankNum > 0) ||
      (Number.isFinite(compRank) && compRank > 0)
    )
  }).length
}

const LEGACY_CORE_NUMERIC_FIELDS: Array<keyof SnapshotHotlistItem> = [
  'change',
  'speed',
  'turnover',
  'turnoverRate',
  'volumeRatio',
  'zlje',
  'zljzb',
  'cddje',
  'cddjzb',
]

function hasLegacyCoreFields(stock: SnapshotHotlistItem): boolean {
  return LEGACY_CORE_NUMERIC_FIELDS.every((key) => Number.isFinite(Number(stock[key])))
}

function countLegacyCoreCoverageHotlistItems(hotlist: SnapshotHotlistItem[]): number {
  return hotlist.filter((stock) => hasLegacyCoreFields(stock)).length
}

function hasOptimizerCoreFields(stock: SnapshotHotlistItem): boolean {
  const code = String(stock.code ?? '').trim()
  const rank = Number(stock.rank)
  const price = Number(stock.price)
  return !!code && Number.isFinite(rank) && rank > 0 && Number.isFinite(price) && price > 0
}

function countOptimizerCoreCoverageHotlistItems(hotlist: SnapshotHotlistItem[]): number {
  return hotlist.filter((stock) => hasOptimizerCoreFields(stock)).length
}

function inferSnapshotFeatureCoverage(snapshot: SnapshotSeriesItem['snapshot']): SnapshotFeatureCoverage {
  const hotlist = normalizeSnapshotHotlist(snapshot?.hotlist)
  const enhancedCount = countEnhancedCoverageHotlistItems(hotlist)
  return enhancedCount >= Math.min(3, hotlist.length || 1) ? 'full' : 'partial'
}

export function resolveSnapshotFeatureCoverage(snapshot: SnapshotSeriesItem['snapshot']): SnapshotFeatureCoverage {
  const declared = normalizeFeatureCoverage(snapshot?.metadata?.featureCoverage)
  const inferred = inferSnapshotFeatureCoverage(snapshot)

  if (declared === 'partial') return 'partial'
  if (declared === 'full') return inferred === 'full' ? 'full' : 'partial'
  return inferred
}

export function resolveSnapshotFormalValidationCoverage(
  snapshot: SnapshotSeriesItem['snapshot'],
  minHotlistSize: number = 20,
): SnapshotFormalValidationCoverage {
  // 空热榜快照不在这里直接判失败，调用方会再结合样本数量与上下文决定是否降级。
  const hotlist = normalizeSnapshotHotlist(snapshot?.hotlist)
  if (hotlist.length === 0) return 'full'

  if (
    compareSnapshotVersion(resolveSnapshotVersion(snapshot), '2.1') >= 0 &&
    resolveSnapshotFeatureCoverage(snapshot) === 'full'
  ) {
    return 'full'
  }

  const requiredCount = Math.min(Math.max(1, minHotlistSize), hotlist.length)
  const legacyCoreCount = countLegacyCoreCoverageHotlistItems(hotlist.slice(0, requiredCount))
  if (legacyCoreCount >= requiredCount) return 'legacy_core'

  const optimizerCoreCount = countOptimizerCoreCoverageHotlistItems(hotlist.slice(0, requiredCount))
  return optimizerCoreCount >= requiredCount ? 'optimizer_core' : 'partial'
}

export function resolveSnapshotVersion(snapshot: SnapshotSeriesItem['snapshot']): string {
  const rawVersion = normalizeVersionToken(snapshot?.metadata?.version)
  if (rawVersion) return rawVersion

  if (normalizeFeatureCoverage(snapshot?.metadata?.featureCoverage)) return '2.1'
  return inferSnapshotFeatureCoverage(snapshot) === 'full' ? '2.1' : '2.0'
}

export function resolveSnapshotTimestamp(snapshot: SnapshotSeriesItem['snapshot'], date: string): number {
  const timestamp = resolvePositiveNumber(snapshot?.timestamp, snapshot?.metadata?.timestamp, parseDateKey(date))
  return Number.isFinite(timestamp) ? timestamp : 0
}

export function normalizeSnapshotPayload(
  snapshot: SnapshotSeriesItem['snapshot'],
  date: string,
): SnapshotSeriesItem['snapshot'] {
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return snapshot

  // 旧快照可能缺 metadata、type 或 timestamp，
  // 这里先补齐统一结构，再交给后续质量门禁和回测链路使用。
  const metadataRecord = asRecord(snapshot.metadata)
  const hotlist = normalizeSnapshotHotlist(snapshot.hotlist)
  const timestamp = resolveSnapshotTimestamp(snapshot, date)
  const metadata: SnapshotMetadata = {
    ...(metadataRecord || {}),
    version: resolveSnapshotVersion(snapshot),
    featureCoverage: resolveSnapshotFeatureCoverage(snapshot),
    totalStocks: resolvePositiveNumber(snapshot.metadata?.totalStocks, hotlist.length) || hotlist.length,
    timestamp,
  }

  const normalizedType = normalizeSnapshotTypeValue(snapshot.type)
  return {
    ...snapshot,
    ...(normalizedType ? { type: normalizedType } : {}),
    timestamp,
    metadata,
    hotlist,
  }
}

export function resolveSnapshotSeriesFeatureCoverage(
  snapshots: SnapshotSeriesItem[],
): SnapshotFeatureCoverage {
  if (!Array.isArray(snapshots) || snapshots.length === 0) return 'partial'

  const effectiveSnapshots = snapshots.filter((item) => {
    const normalized = normalizeSnapshotPayload(item?.snapshot, item?.date || '')
    return Array.isArray(normalized?.hotlist) && normalized.hotlist.length > 0
  })

  if (effectiveSnapshots.length === 0) return 'partial'

  return effectiveSnapshots.every((item) => {
    const normalized = normalizeSnapshotPayload(item?.snapshot, item?.date || '')
    return resolveSnapshotFeatureCoverage(normalized) === 'full'
  })
    ? 'full'
    : 'partial'
}

export function summarizeSnapshotSeriesFormalValidationCoverage(
  snapshots: SnapshotSeriesItem[],
  minHotlistSize: number = 20,
): SnapshotSeriesFormalValidationSummary {
  // 这是“整段样本的覆盖等级摘要”，用于解释为什么某段历史被降级或自动裁剪。
  const normalizedSnapshots = sortSnapshotSeriesItems(snapshots)
  let fullSnapshotCount = 0
  let legacyCoreSnapshotCount = 0
  let optimizerCoreSnapshotCount = 0
  let incompatibleSnapshotCount = 0
  let emptyHotlistCount = 0

  for (const item of normalizedSnapshots) {
    const snapshot = item.snapshot
    if (isEmptyHotlistSnapshot(snapshot)) {
      emptyHotlistCount += 1
      continue
    }

    const coverage = resolveSnapshotFormalValidationCoverage(snapshot, minHotlistSize)
    if (coverage === 'full') fullSnapshotCount += 1
    else if (coverage === 'legacy_core') legacyCoreSnapshotCount += 1
    else if (coverage === 'optimizer_core') optimizerCoreSnapshotCount += 1
    else incompatibleSnapshotCount += 1
  }

  const totalNonEmptySnapshots =
    fullSnapshotCount + legacyCoreSnapshotCount + optimizerCoreSnapshotCount + incompatibleSnapshotCount
  const coverage: SnapshotFormalValidationCoverage =
    incompatibleSnapshotCount > 0
      ? 'partial'
      : legacyCoreSnapshotCount > 0
        ? 'legacy_core'
        : optimizerCoreSnapshotCount > 0
          ? 'optimizer_core'
          : 'full'

  return {
    coverage,
    totalNonEmptySnapshots,
    fullSnapshotCount,
    legacyCoreSnapshotCount,
    optimizerCoreSnapshotCount,
    incompatibleSnapshotCount,
    emptyHotlistCount,
  }
}

function sortSnapshotSeriesItems(snapshots: SnapshotSeriesItem[]): SnapshotSeriesItem[] {
  return [...snapshots]
    .map((item) => ({
      date: item.date,
      snapshot: normalizeSnapshotPayload(item?.snapshot, item?.date || ''),
    }))
    .sort((left, right) => {
      const leftTimestamp = resolveSnapshotTimestamp(left.snapshot, left.date)
      const rightTimestamp = resolveSnapshotTimestamp(right.snapshot, right.date)
      return leftTimestamp - rightTimestamp
    })
}

function isEmptyHotlistSnapshot(snapshot: SnapshotSeriesItem['snapshot']): boolean {
  return !Array.isArray(snapshot?.hotlist) || snapshot.hotlist.length === 0
}

function isFormalFullCoverageSnapshot(snapshot: SnapshotSeriesItem['snapshot']): boolean {
  if (isEmptyHotlistSnapshot(snapshot)) return true
  return (
    compareSnapshotVersion(resolveSnapshotVersion(snapshot), '2.1') >= 0 &&
    resolveSnapshotFeatureCoverage(snapshot) === 'full'
  )
}

export function selectFormalValidationSnapshots(
  snapshots: SnapshotSeriesItem[],
  minSnapshotCount: number,
): FormalValidationSnapshotSelection {
  // 当历史样本前半段还是旧结构、后半段已经完整时，
  // 这里会尽量裁出“最新完整后缀”，避免老样本把正式验证整体拖成 partial。
  const normalizedSnapshots = sortSnapshotSeriesItems(snapshots)
  const requestedCount = normalizedSnapshots.length

  let emptyHotlistCount = 0
  let legacyCompatibleCount = 0
  let nonEmptyPartialCount = 0

  for (const item of normalizedSnapshots) {
    const snapshot = item.snapshot
    if (!snapshot || typeof snapshot !== 'object') continue

    if (isEmptyHotlistSnapshot(snapshot)) {
      emptyHotlistCount += 1
      continue
    }

    if (compareSnapshotVersion(resolveSnapshotVersion(snapshot), '2.1') < 0) {
      legacyCompatibleCount += 1
    }
    if (resolveSnapshotFeatureCoverage(snapshot) !== 'full') {
      nonEmptyPartialCount += 1
    }
  }

  const requestedCoverage = resolveSnapshotSeriesFeatureCoverage(normalizedSnapshots)
  if (requestedCoverage === 'full') {
    return {
      snapshots: normalizedSnapshots,
      autoAdjusted: false,
      requestedCount,
      selectedCount: requestedCount,
      emptyHotlistCount,
      legacyCompatibleCount,
      nonEmptyPartialCount,
      selectedStartDate: normalizedSnapshots[0]?.date || null,
      selectedEndDate: normalizedSnapshots[normalizedSnapshots.length - 1]?.date || null,
    }
  }

  const suffix: SnapshotSeriesItem[] = []
  for (let index = normalizedSnapshots.length - 1; index >= 0; index--) {
    const item = normalizedSnapshots[index]
    if (isFormalFullCoverageSnapshot(item.snapshot)) {
      suffix.unshift(item)
      continue
    }
    break
  }

  const canAutoAdjust = suffix.length >= Math.max(1, minSnapshotCount)
  const selectedSnapshots = canAutoAdjust ? suffix : normalizedSnapshots

  return {
    snapshots: selectedSnapshots,
    autoAdjusted: canAutoAdjust && selectedSnapshots.length < normalizedSnapshots.length,
    requestedCount,
    selectedCount: selectedSnapshots.length,
    emptyHotlistCount,
    legacyCompatibleCount,
    nonEmptyPartialCount,
    selectedStartDate: selectedSnapshots[0]?.date || null,
    selectedEndDate: selectedSnapshots[selectedSnapshots.length - 1]?.date || null,
  }
}

function createStats(totalSnapshots: number) {
  return {
    totalSnapshots,
    validQuarterHourCount: 0,
    invalidTypeCount: 0,
    nonMonotonicTimestampCount: 0,
    duplicateKeyCount: 0,
    missingSnapshotCount: 0,
    emptyHotlistCount: 0,
    lowHotlistCount: 0,
    missingCoreFieldCount: 0,
    fullFeatureCoverageCount: 0,
    partialFeatureCoverageCount: 0,
    legacyCompatibleCount: 0,
  }
}

export function normalizeSnapshotQualityGateOptions(
  options?: SnapshotQualityGateOptions,
): Required<SnapshotQualityGateOptions> {
  return {
    enabled: options?.enabled ?? true,
    strict: options?.strict ?? false,
    minHotlistSize: Math.max(1, options?.minHotlistSize ?? 20),
    minSnapshotCount: Math.max(2, options?.minSnapshotCount ?? 50),
    requiredType: options?.requiredType ?? DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  }
}

export function evaluateSnapshotQualityGate(
  snapshots: SnapshotSeriesItem[],
  options?: SnapshotQualityGateOptions,
): SnapshotQualityGateResult {
  // 质量门禁既检查“有没有快照”，也检查“结构是否一致、时间是否单调、热榜核心字段是否完整”。
  const normalized = normalizeSnapshotQualityGateOptions(options)
  if (!normalized.enabled) {
    return {
      passed: true,
      severity: 'pass',
      strict: normalized.strict,
      issues: [],
      stats: {
        ...createStats(snapshots.length),
        validQuarterHourCount: snapshots.length,
      },
    }
  }

  const issues: string[] = []
  const seenKeys = new Set<string>()
  let prevTimestamp = Number.NEGATIVE_INFINITY
  const stats = createStats(snapshots.length)

  for (const item of snapshots) {
    const snapshot = normalizeSnapshotPayload(item?.snapshot, item?.date || '')
    if (!snapshot || typeof snapshot !== 'object') {
      stats.missingSnapshotCount += 1
      continue
    }

    if (snapshot.type !== normalized.requiredType) {
      stats.invalidTypeCount += 1
      continue
    }
    stats.validQuarterHourCount += 1

    const featureCoverage = resolveSnapshotFeatureCoverage(snapshot)
    if (featureCoverage === 'full') stats.fullFeatureCoverageCount += 1
    else stats.partialFeatureCoverageCount += 1

    if (compareSnapshotVersion(resolveSnapshotVersion(snapshot), '2.1') < 0) {
      stats.legacyCompatibleCount += 1
    }

    const timestamp = Number(snapshot.timestamp)
    const key = `${snapshot.type}#${timestamp}`
    if (seenKeys.has(key)) stats.duplicateKeyCount += 1
    else seenKeys.add(key)

    if (!Number.isFinite(timestamp) || timestamp <= 0) {
      stats.missingCoreFieldCount += 1
    } else if (timestamp < prevTimestamp) {
      stats.nonMonotonicTimestampCount += 1
      prevTimestamp = timestamp
    } else {
      prevTimestamp = timestamp
    }

    const hotlist = Array.isArray(snapshot.hotlist) ? snapshot.hotlist : []
    if (hotlist.length === 0) {
      stats.emptyHotlistCount += 1
      continue
    }
    if (hotlist.length < normalized.minHotlistSize) stats.lowHotlistCount += 1

    for (const stock of hotlist.slice(0, Math.min(hotlist.length, normalized.minHotlistSize))) {
      if (!stock?.code || !Number.isFinite(Number(stock.rank)) || !Number.isFinite(Number(stock.price))) {
        stats.missingCoreFieldCount += 1
      }
    }
  }

  const requiredTypeLabel = String(normalized.requiredType)
  if (stats.validQuarterHourCount < normalized.minSnapshotCount) {
    issues.push(`${requiredTypeLabel} snapshots below minimum ${normalized.minSnapshotCount}: ${stats.validQuarterHourCount}`)
  }
  if (stats.missingSnapshotCount > 0) issues.push(`Missing snapshot payload: ${stats.missingSnapshotCount}`)
  if (stats.invalidTypeCount > 0) issues.push(`Non-${requiredTypeLabel} snapshot count: ${stats.invalidTypeCount}`)
  if (stats.duplicateKeyCount > 0) issues.push(`Duplicate (type + timestamp) key: ${stats.duplicateKeyCount}`)
  if (stats.nonMonotonicTimestampCount > 0) issues.push(`Non-monotonic timestamp: ${stats.nonMonotonicTimestampCount}`)
  if (stats.emptyHotlistCount > 0) issues.push(`Empty hotlist snapshot: ${stats.emptyHotlistCount}`)
  if (stats.lowHotlistCount > 0) {
    issues.push(`Hotlist below min size ${normalized.minHotlistSize}: ${stats.lowHotlistCount}`)
  }
  if (stats.missingCoreFieldCount > 0) issues.push(`Missing core field count: ${stats.missingCoreFieldCount}`)

  const fatal =
    stats.validQuarterHourCount < normalized.minSnapshotCount ||
    stats.missingSnapshotCount > 0 ||
    stats.invalidTypeCount > 0 ||
    stats.duplicateKeyCount > 0 ||
    stats.nonMonotonicTimestampCount > 0 ||
    stats.missingCoreFieldCount > 0
  const warning = stats.emptyHotlistCount > 0 || stats.lowHotlistCount > 0
  const passed = normalized.strict ? !fatal && !warning : !fatal

  return {
    passed,
    severity: fatal ? 'fail' : warning ? 'warn' : 'pass',
    strict: normalized.strict,
    issues,
    stats,
  }
}
