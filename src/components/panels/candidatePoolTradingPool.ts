import type {
  CandidateJournalEntry,
  TradingPoolAnalysisRow,
  TradingPoolDecision,
  TradingPoolSignalSnapshot,
  TradingPoolStatus,
} from '@/services/candidate/types'

const TRADING_POOL_STATUSES = new Set<TradingPoolStatus>([
  '观察买点',
  '准备介入',
  '已介入',
  '持仓观察',
  '观察中',
  '已退出',
  '已完成',
])

const TRADING_POOL_DECISIONS = new Set<TradingPoolDecision>([
  'enter',
  'watch',
  'downgrade',
  'exit',
  'stale',
])

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function normalizeText(value: unknown): string {
  return value == null ? '' : String(value)
}

function normalizeStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item: unknown) => normalizeText(item)) : []
}

function normalizeNumber(value: unknown): number | null {
  if (value == null || value === '') return null
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : null
}

function normalizeBoolean(value: unknown): boolean {
  if (value === true || value === 'true') return true
  if (value === false || value === 'false') return false
  return Boolean(value)
}

function normalizeTradingPoolStatus(value: unknown): TradingPoolStatus {
  const status = normalizeText(value) as TradingPoolStatus
  return TRADING_POOL_STATUSES.has(status) ? status : '观察中'
}

function normalizeTradingPoolDecision(value: unknown): TradingPoolDecision {
  const decision = normalizeText(value) as TradingPoolDecision
  return TRADING_POOL_DECISIONS.has(decision) ? decision : 'watch'
}

function normalizeDataQuality(
  primary: unknown,
  fallback: unknown,
): TradingPoolSignalSnapshot['dataQuality'] {
  const quality = normalizeText(primary)
  if (quality === 'fresh' || quality === 'stale' || quality === 'missing') return quality
  const fallbackQuality = normalizeText(fallback)
  if (fallbackQuality === 'fresh' || fallbackQuality === 'stale' || fallbackQuality === 'missing') {
    return fallbackQuality
  }
  return 'stale'
}

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function buildComparableTradingPoolSnapshot(row: TradingPoolAnalysisRow) {
  return {
    version: 'v2',
    code: normalizeCode(row.code),
    name: normalizeText(row.name),
    status: normalizeTradingPoolStatus(row.status),
    decision: normalizeTradingPoolDecision(row.decision),
    reasons: normalizeStringArray(row.reasons),
    signalSnapshot: {
      directionSignal: row.signalSnapshot.directionSignal ?? null,
      jumpConfidence: normalizeNumber(row.signalSnapshot.jumpConfidence),
      macdCross: row.signalSnapshot.macdCross ?? null,
      accelerationSignal: row.signalSnapshot.accelerationSignal ?? null,
      zeroCrossSignal: row.signalSnapshot.zeroCrossSignal ?? null,
      momentumSyncBroken: normalizeBoolean(row.signalSnapshot.momentumSyncBroken),
      lifecycleAction: row.signalSnapshot.lifecycleAction ?? null,
      dataQuality: normalizeDataQuality(
        row.signalSnapshot.dataQuality,
        row.signalSnapshot.dataQuality,
      ),
    },
    dataQuality: normalizeDataQuality(row.signalSnapshot.dataQuality, row.signalSnapshot.dataQuality),
  }
}

function buildComparableTradingPoolSnapshotFromEntry(entry: Record<string, any>) {
  const signalSnapshot = isRecord(entry.signalSnapshot) ? entry.signalSnapshot : null
  return {
    version: normalizeText(entry.version) || 'v2',
    code: normalizeCode(entry.code),
    name: normalizeText(entry.name),
    status: normalizeTradingPoolStatus(entry.status),
    decision: normalizeTradingPoolDecision(entry.decision),
    reasons: normalizeStringArray(entry.reasons),
    signalSnapshot: {
      directionSignal: signalSnapshot?.directionSignal ?? null,
      jumpConfidence: normalizeNumber(signalSnapshot?.jumpConfidence),
      macdCross: signalSnapshot?.macdCross ?? null,
      accelerationSignal: signalSnapshot?.accelerationSignal ?? null,
      zeroCrossSignal: signalSnapshot?.zeroCrossSignal ?? null,
      momentumSyncBroken: normalizeBoolean(signalSnapshot?.momentumSyncBroken),
      lifecycleAction: signalSnapshot?.lifecycleAction ?? null,
      dataQuality: normalizeDataQuality(entry.dataQuality, signalSnapshot?.dataQuality),
    },
    dataQuality: normalizeDataQuality(entry.dataQuality, signalSnapshot?.dataQuality),
  }
}

function stableStringify(value: unknown): string {
  return JSON.stringify(value)
}

function findTradingPoolCandidate(
  candidates: CandidateJournalEntry[],
  row: TradingPoolAnalysisRow,
): CandidateJournalEntry | null {
  const code = normalizeCode(row.code)
  return candidates.find((entry) => normalizeCode(entry.stockCode) === code && entry.tradeType === 'thesis') || null
}

function findTradingPoolEntryForCandidate(
  persistedEntries: CandidateJournalEntry[],
  candidate: CandidateJournalEntry,
): CandidateJournalEntry | null {
  return (
    persistedEntries.find((entry) => entry.candidateEntryId === candidate.id) ||
    persistedEntries.find((entry) => normalizeCode(entry.stockCode) === normalizeCode(candidate.stockCode)) ||
    null
  )
}

export function readTradingPoolSnapshot(
  signalsSnapshot: Record<string, any> | null | undefined,
): TradingPoolAnalysisRow | null {
  const tradingPool = isRecord(signalsSnapshot?.tradingPool) ? signalsSnapshot?.tradingPool : null
  const quote = isRecord(signalsSnapshot?.quote) ? signalsSnapshot?.quote : null
  const rankTrend = isRecord(signalsSnapshot?.rankTrend) ? signalsSnapshot?.rankTrend : null
  const code = normalizeCode(tradingPool?.code || quote?.code || '')
  if (!code) return null

  const signalSnapshotSource = isRecord(tradingPool?.signalSnapshot)
    ? tradingPool?.signalSnapshot
    : rankTrend

  return {
    code,
    name: normalizeText(tradingPool?.name || quote?.name),
    status: normalizeTradingPoolStatus(tradingPool?.status),
    decision: normalizeTradingPoolDecision(tradingPool?.decision),
    reasons: normalizeStringArray(tradingPool?.reasons),
    signalSnapshot: {
      directionSignal: signalSnapshotSource?.directionSignal ?? null,
      jumpConfidence: normalizeNumber(signalSnapshotSource?.jumpConfidence),
      macdCross: signalSnapshotSource?.macdCross ?? null,
      accelerationSignal: signalSnapshotSource?.accelerationSignal ?? null,
      zeroCrossSignal: signalSnapshotSource?.zeroCrossSignal ?? null,
      momentumSyncBroken: normalizeBoolean(signalSnapshotSource?.momentumSyncBroken),
      lifecycleAction: signalSnapshotSource?.lifecycleAction ?? null,
      dataQuality: normalizeDataQuality(tradingPool?.dataQuality, signalSnapshotSource?.dataQuality),
    },
  }
}

export function isTradingPoolSnapshotEqual(
  existingTradingPool: Record<string, any> | null | undefined,
  row: TradingPoolAnalysisRow,
): boolean {
  if (!existingTradingPool) return false
  return (
    stableStringify(buildComparableTradingPoolSnapshotFromEntry(existingTradingPool)) ===
    stableStringify(buildComparableTradingPoolSnapshot(row))
  )
}

export function buildTradingPoolPersistencePlan(
  rows: TradingPoolAnalysisRow[],
  candidates: CandidateJournalEntry[],
  persistedEntries: CandidateJournalEntry[],
): {
  updates: Array<{ entry: CandidateJournalEntry; row: TradingPoolAnalysisRow }>
  creates: Array<{ candidate: CandidateJournalEntry; row: TradingPoolAnalysisRow }>
} {
  const grouped = new Map<string, { candidate: CandidateJournalEntry; row: TradingPoolAnalysisRow }>()

  for (const row of rows) {
    const candidate = findTradingPoolCandidate(candidates, row)
    if (!candidate || grouped.has(candidate.id)) continue
    grouped.set(candidate.id, { candidate, row })
  }

  const updates: Array<{ entry: CandidateJournalEntry; row: TradingPoolAnalysisRow }> = []
  const creates: Array<{ candidate: CandidateJournalEntry; row: TradingPoolAnalysisRow }> = []

  for (const { candidate, row } of grouped.values()) {
    const existing = findTradingPoolEntryForCandidate(persistedEntries, candidate)
    if (existing) {
      if (isTradingPoolSnapshotEqual(existing.signalsSnapshot?.tradingPool, row)) continue
      updates.push({ entry: existing, row })
      continue
    }
    creates.push({ candidate, row })
  }

  return { updates, creates }
}

export function getTradingPoolEntryCandidate(
  entries: CandidateJournalEntry[],
  row: TradingPoolAnalysisRow,
): CandidateJournalEntry | null {
  return findTradingPoolCandidate(entries, row)
}

export function getTradingPoolEntryForCandidate(
  persistedEntries: CandidateJournalEntry[],
  candidate: CandidateJournalEntry,
): CandidateJournalEntry | null {
  return findTradingPoolEntryForCandidate(persistedEntries, candidate)
}
