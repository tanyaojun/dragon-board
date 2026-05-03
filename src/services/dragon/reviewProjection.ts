import type { LeaderLookupRecord, MergedStock } from '../../types/data-layer'
import type {
  AuthorityClass,
  ChaseRisk,
  DragonReviewResult,
  LeaderRecord,
  LeaderRole,
  Tradeability,
} from './types'

const REVIEW_ROLE_LABELS: Record<LeaderRole, string> = {
  MARKET_CORE: '市场总龙头',
  THEME_CORE: '题材真龙',
  SPACE_CORE: '空间龙头',
  TREND_CORE: '趋势中军',
  EMOTION_CORE: '情绪核心',
}

const REVIEW_AUTHORITY_SCORES: Record<AuthorityClass, number> = {
  TRUE_LEADER: 95,
  THEME_COMMANDER: 82,
  CARRY_PROXY: 68,
  HEIGHT_ONLY: 56,
  HEAT_ONLY: 52,
  PSEUDO_LEADER: 35,
}

const LEGACY_LEVEL_ROLE_MAP: Record<string, LeaderRole> = {
  TOTAL: 'MARKET_CORE',
  MARKET_CORE: 'MARKET_CORE',
  市场总龙头: 'MARKET_CORE',
  SECTOR: 'THEME_CORE',
  THEME_CORE: 'THEME_CORE',
  题材真龙: 'THEME_CORE',
  CONTINUOUS: 'SPACE_CORE',
  SPACE_CORE: 'SPACE_CORE',
  空间龙头: 'SPACE_CORE',
  MIDDLE: 'TREND_CORE',
  TREND_CORE: 'TREND_CORE',
  趋势中军: 'TREND_CORE',
  EMOTION: 'EMOTION_CORE',
  EMOTION_CORE: 'EMOTION_CORE',
  情绪核心: 'EMOTION_CORE',
}

export function normalizeLeaderRole(value?: string | null): LeaderRole | null {
  if (!value) return null
  return LEGACY_LEVEL_ROLE_MAP[value] || null
}

function getLeaderLevelName(role: LeaderRole): string {
  return REVIEW_ROLE_LABELS[role] || role
}

function getLeaderScore(authority?: AuthorityClass | null): number {
  if (!authority) return 50
  return REVIEW_AUTHORITY_SCORES[authority] || 50
}

function toLeaderLookupRecord(record: LeaderRecord, timestamp: number): LeaderLookupRecord {
  const level = record.primaryRole
  return {
    code: record.code,
    name: record.name,
    level,
    levelName: getLeaderLevelName(level),
    score: getLeaderScore(record.authority),
    continuousDays: record.continuousDays || 0,
    authority: record.authority,
    primaryRole: record.primaryRole,
    roles: [...record.roles],
    tradeability: record.tradeability,
    chaseRisk: record.chaseRisk,
    status: record.status,
    themeName: record.themeName,
    lastUpdate: timestamp,
  }
}

export function toLegacyLeaderLookupRecord(
  record: Record<string, any>,
  timestamp: number,
): LeaderLookupRecord | null {
  const level = normalizeLeaderRole(record.primaryRole || record.level || record.levelName)
  if (!record.code || !level) return null

  const roles = Array.isArray(record.roles) && record.roles.length
    ? (record.roles.filter(Boolean) as LeaderRole[])
    : [level]
  const authority = (record.authority as AuthorityClass | undefined) || 'TRUE_LEADER'
  const tradeability = (record.tradeability as Tradeability | undefined) || 'WATCH_ONLY'
  const chaseRisk = (record.chaseRisk as ChaseRisk | undefined) || 'HIGH'

  return {
    code: record.code,
    name: record.name || '',
    level,
    levelName: record.levelName || getLeaderLevelName(level),
    score: typeof record.score === 'number' ? record.score : getLeaderScore(authority),
    continuousDays: Number(record.continuousDays) || 0,
    authority,
    primaryRole: level,
    roles: [...new Set(roles)],
    tradeability,
    chaseRisk,
    status: record.status,
    themeName: record.themeName,
    lastUpdate: timestamp,
  }
}

function getReviewRecordPool(result: DragonReviewResult): LeaderRecord[] {
  const deduped = new Map<string, LeaderRecord>()

  const addRecord = (record: LeaderRecord | null | undefined) => {
    if (!record || deduped.has(record.code)) return
    deduped.set(record.code, record)
  }

  addRecord(result.marketCore)
  ;[
    ...(result.trueLeaders || []),
    ...(result.heightBoard || []),
    ...(result.attentionBoard || []),
  ].forEach(addRecord)

  return Array.from(deduped.values())
}

export function buildReviewLeaderProjection(
  result: DragonReviewResult,
  timestamp: number,
): {
  byCode: Map<string, LeaderLookupRecord>
  byLevel: Record<string, LeaderLookupRecord[]>
} {
  const byCode = new Map<string, LeaderLookupRecord>()
  const byLevel: Record<string, LeaderLookupRecord[]> = {}

  getReviewRecordPool(result).forEach((leader) => {
    if (byCode.has(leader.code)) return

    const record = toLeaderLookupRecord(leader, timestamp)
    byCode.set(leader.code, record)
    if (!byLevel[record.level]) byLevel[record.level] = []
    byLevel[record.level].push(record)
  })

  return { byCode, byLevel }
}

export function applyReviewProjectionToStock(
  stock: MergedStock,
  leaderRecord: LeaderLookupRecord | null | undefined,
): MergedStock {
  const projected = { ...stock }

  if (!leaderRecord) {
    delete projected.reviewAuthority
    delete projected.reviewRole
    delete projected.tradeability
    delete projected.chaseRisk
    return projected
  }

  projected.reviewAuthority = leaderRecord.authority
  projected.reviewRole = leaderRecord.primaryRole
  projected.tradeability = leaderRecord.tradeability
  projected.chaseRisk = leaderRecord.chaseRisk
  if (!projected.continuousDays && leaderRecord.continuousDays) {
    projected.continuousDays = leaderRecord.continuousDays
  }

  return projected
}

const LEGACY_LEADER_FIELDS = ['isSectorLeader', 'leaderLevel', 'leaderScore'] as const

export function stripLegacyLeaderFields<T extends object>(stock: T): T {
  const sanitized = { ...(stock as Record<string, unknown>) }

  LEGACY_LEADER_FIELDS.forEach((field) => {
    delete sanitized[field]
  })

  return sanitized as T
}
