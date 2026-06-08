import { candidateJournalService } from './CandidateJournalService'
import type { CandidateJournalEntry, CandidateStatus } from './types'

type CandidatePoolProjectedStatus = CandidateStatus | 'none'
type CandidatePoolStockFields = {
  candidatePoolStatus?: CandidatePoolProjectedStatus
  candidatePoolLabel?: string
  candidatePoolEntryId?: string
  candidatePoolSource?: string
  candidatePoolUpdatedAt?: string
}

const STATUS_LABELS: Record<CandidatePoolProjectedStatus, string> = {
  none: '未入池',
  observe: '观察',
  candidate: '候选',
  triggered: '已触发',
  tracking: '跟踪中',
  reviewed: '已复盘',
}

const STATUS_PRIORITY: Record<CandidatePoolProjectedStatus, number> = {
  none: 0,
  reviewed: 1,
  observe: 2,
  candidate: 3,
  triggered: 4,
  tracking: 5,
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function getEntryPriority(entry: CandidateJournalEntry): number {
  return STATUS_PRIORITY[entry.status] || 0
}

function getEntryTimestamp(entry: CandidateJournalEntry): number {
  const updated = Date.parse(entry.updatedAt || entry.createdAt || '')
  return Number.isFinite(updated) ? updated : 0
}

function selectPreferredEntry(
  current: CandidateJournalEntry | undefined,
  next: CandidateJournalEntry,
): CandidateJournalEntry {
  if (!current) return next
  const priorityDelta = getEntryPriority(next) - getEntryPriority(current)
  if (priorityDelta !== 0) {
    return priorityDelta > 0 ? next : current
  }
  return getEntryTimestamp(next) >= getEntryTimestamp(current) ? next : current
}

function getEntrySource(entry: CandidateJournalEntry | undefined): string {
  if (!entry) return ''
  const triggerSource = entry?.signalsSnapshot?.triggerMeta?.source
  if (triggerSource) return String(triggerSource)
  const reviewSource = entry?.reviewNotes?.trim()
  return reviewSource || 'manual'
}

export function projectCandidatePoolStatus<T extends Record<string, any>>(
  stocks: Array<T & CandidatePoolStockFields>,
  entries: CandidateJournalEntry[],
): Array<T & CandidatePoolStockFields> {
  const entryByCode = new Map<string, CandidateJournalEntry>()
  for (const entry of entries) {
    const code = normalizeCode(entry.stockCode)
    if (!code) continue
    entryByCode.set(code, selectPreferredEntry(entryByCode.get(code), entry))
  }

  for (const stock of stocks) {
    const entry = entryByCode.get(normalizeCode(stock.code))
    const status: CandidatePoolProjectedStatus = entry?.status || 'none'
    stock.candidatePoolStatus = status
    stock.candidatePoolLabel = STATUS_LABELS[status]
    stock.candidatePoolEntryId = entry?.id || ''
    stock.candidatePoolSource = getEntrySource(entry)
    stock.candidatePoolUpdatedAt = entry?.updatedAt || entry?.createdAt || ''
  }

  return stocks
}

export async function applyCandidatePoolStatus<T extends Record<string, any>>(
  stocks: Array<T & CandidatePoolStockFields>,
): Promise<Array<T & CandidatePoolStockFields>> {
  const entries = await candidateJournalService.listCandidates({ limit: 1000 })
  return projectCandidatePoolStatus(stocks, entries)
}
