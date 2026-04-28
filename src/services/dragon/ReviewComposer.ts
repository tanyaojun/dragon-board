import type {
  BattlefieldRecord,
  DragonReviewResult,
  LeaderRecord,
  LeaderTransition,
  PseudoLeaderRecord,
  ReviewRegime,
} from './types'
import {
  authorityWeight,
  chaseRiskWeight,
  dominanceWeight,
  roleOrder,
  sortBattlefields,
} from './helpers'
import { regimeLabel, roleLabel } from './labels'

const MAX_ATTENTION_BOARD_SIZE = 12
const MAX_TIMELINE_RECORDS = 10

function battlefieldMap(battlefields: BattlefieldRecord[]) {
  return new Map(battlefields.map((battlefield) => [battlefield.battlefieldId, battlefield]))
}

function uniqueLeadersByCode(records: LeaderRecord[]): LeaderRecord[] {
  const deduped = new Map<string, LeaderRecord>()
  records.forEach((record) => {
    if (!deduped.has(record.code)) {
      deduped.set(record.code, record)
    }
  })
  return Array.from(deduped.values())
}

function uniquePseudoByCode(records: PseudoLeaderRecord[]): PseudoLeaderRecord[] {
  const deduped = new Map<string, PseudoLeaderRecord>()
  records.forEach((record) => {
    if (!deduped.has(record.code)) {
      deduped.set(record.code, record)
    }
  })
  return Array.from(deduped.values())
}

function sortByAuthority(records: LeaderRecord[], battlefields: BattlefieldRecord[]): LeaderRecord[] {
  const fieldMap = battlefieldMap(battlefields)
  return [...records].sort((a, b) => {
    const authorityDiff = authorityWeight(b.authority) - authorityWeight(a.authority)
    if (authorityDiff !== 0) return authorityDiff
    const dominanceDiff =
      dominanceWeight(fieldMap.get(b.battlefieldId)?.dominance || 'WEAK') -
      dominanceWeight(fieldMap.get(a.battlefieldId)?.dominance || 'WEAK')
    if (dominanceDiff !== 0) return dominanceDiff
    const riskDiff = chaseRiskWeight(a.chaseRisk) - chaseRiskWeight(b.chaseRisk)
    if (riskDiff !== 0) return riskDiff
    return roleOrder(a.primaryRole) - roleOrder(b.primaryRole)
  })
}

function signalStrengthWeight(value: BattlefieldRecord['continuity']): number {
  if (value === 'strong') return 3
  if (value === 'medium') return 2
  return 1
}

function attentionContextScore(battlefield: BattlefieldRecord): number {
  const strongCount = [
    battlefield.continuity,
    battlefield.carryStrength,
    battlefield.quality,
    battlefield.capital,
  ].filter((value) => value === 'strong').length
  const fragilityPenalty =
    battlefield.fragility === 'high' ? 18 : battlefield.fragility === 'mid' ? 8 : 0

  return (
    battlefield.attentionScore +
    dominanceWeight(battlefield.dominance) * 6 +
    strongCount * 5 +
    (battlefield.isMainLine ? 10 : 0) -
    fragilityPenalty
  )
}

function recordAttentionSignalScore(record: LeaderRecord): number {
  const popularityBonus = record.popularity > 0 ? Math.min(22, Math.log10(record.popularity + 1) * 6) : 0
  const popularityChangeBonus =
    record.popularityChange > 0 ? Math.min(24, record.popularityChange / 3) : 0
  const authorityBonus = record.authority === 'HEAT_ONLY' ? 10 : record.primaryRole === 'EMOTION_CORE' ? 6 : 0
  return record.hotness + popularityBonus + popularityChangeBonus + authorityBonus
}

function isThemeAttentionBattlefield(battlefield: BattlefieldRecord): boolean {
  if (battlefield.type !== 'THEME') return false
  return Boolean(
    battlefield.dominance !== 'WEAK' &&
      (
        battlefield.themeHeatScore >= 60 ||
        battlefield.themeZtCount >= 2 ||
        battlefield.isMainLine ||
        battlefield.attentionScore >= 65 ||
        signalStrengthWeight(battlefield.carryStrength) + signalStrengthWeight(battlefield.continuity) >= 5
      ),
  )
}

function qualifiesForAttentionBoard(record: LeaderRecord, battlefield?: BattlefieldRecord): boolean {
  if (!battlefield) return false
  if (battlefield.type === 'STYLE') return false

  const heatIdentity = record.authority === 'HEAT_ONLY' || record.primaryRole === 'EMOTION_CORE'
  if (!heatIdentity) return false

  const heatSignalStrong =
    record.hotness >= 35 ||
    record.popularityChange >= 10 ||
    (record.hotness >= 25 && record.popularity > 0)
  if (!heatSignalStrong) return false

  if (battlefield.type === 'INDEPENDENT') {
    return Boolean(
      (battlefield.dominance !== 'WEAK' || battlefield.attentionScore >= 55) &&
        (record.boardHeight >= 2 || record.continuousDays >= 2 || record.hotness >= 55),
    )
  }

  return isThemeAttentionBattlefield(battlefield)
}

function buildAttentionBoard(records: LeaderRecord[], battlefields: BattlefieldRecord[]): LeaderRecord[] {
  const fieldMap = battlefieldMap(battlefields)
  return uniqueLeadersByCode(
    records
      .filter((record) => qualifiesForAttentionBoard(record, fieldMap.get(record.battlefieldId)))
      .sort((a, b) => {
        const contextDiff =
          attentionContextScore(fieldMap.get(b.battlefieldId)!) -
          attentionContextScore(fieldMap.get(a.battlefieldId)!)
        if (contextDiff !== 0) return contextDiff
        const signalDiff = recordAttentionSignalScore(b) - recordAttentionSignalScore(a)
        if (signalDiff !== 0) return signalDiff
        return authorityWeight(b.authority) - authorityWeight(a.authority)
      }),
  ).slice(0, MAX_ATTENTION_BOARD_SIZE)
}

function pickMarketCore(records: LeaderRecord[], battlefields: BattlefieldRecord[]): LeaderRecord | null {
  const fieldMap = battlefieldMap(battlefields)
  const candidates = records.filter((record) => {
    if (record.authority !== 'TRUE_LEADER') return false
    const battlefield = fieldMap.get(record.battlefieldId)
    if (!battlefield || battlefield.dominance !== 'DOMINANT') return false
    if (!record.duelResults.some((duel) => duel.dimensions.carryEffect === 'win')) return false
    if (!record.duelResults.some((duel) => duel.dimensions.segmentPersistence === 'win')) return false
    if (
      record.fatalNegatives.includes('LATE_HEAT_CHASE') ||
      record.fatalNegatives.includes('ONE_WORD_ISOLATION')
    ) {
      return false
    }
    return battlefield.type === 'THEME' || battlefield.type === 'INDEPENDENT'
  })

  if (!candidates.length) return null

  return [...candidates].sort((a, b) => {
    const battleDiff =
      dominanceWeight(fieldMap.get(b.battlefieldId)?.dominance || 'WEAK') -
      dominanceWeight(fieldMap.get(a.battlefieldId)?.dominance || 'WEAK')
    if (battleDiff !== 0) return battleDiff

    const attentionDiff =
      (fieldMap.get(b.battlefieldId)?.attentionScore || 0) -
      (fieldMap.get(a.battlefieldId)?.attentionScore || 0)
    if (attentionDiff !== 0) return attentionDiff

    const carryWinsB = b.duelResults.filter((duel) => duel.dimensions.carryEffect === 'win').length
    const carryWinsA = a.duelResults.filter((duel) => duel.dimensions.carryEffect === 'win').length
    if (carryWinsB !== carryWinsA) return carryWinsB - carryWinsA

    return b.boardHeight - a.boardHeight
  })[0]
}

function timelinePriority(record: LeaderRecord, battlefields: BattlefieldRecord[]): number {
  const battlefield = battlefieldMap(battlefields).get(record.battlefieldId)
  return (
    authorityWeight(record.authority) * 100 +
    dominanceWeight(battlefield?.dominance || 'WEAK') * 20 +
    (record.status === 'COMMANDING' ? 12 : record.status === 'WEAKENING' ? 4 : 0) +
    (record.boardHeight || 0)
  )
}

function shouldAppearInTimeline(record: LeaderRecord, battlefields: BattlefieldRecord[]): boolean {
  const battlefield = battlefieldMap(battlefields).get(record.battlefieldId)
  if (!battlefield) return false
  if (record.authority === 'TRUE_LEADER' || record.authority === 'THEME_COMMANDER') return true
  if (record.authority === 'HEIGHT_ONLY' && record.boardHeight >= 3) return true
  if (record.authority === 'HEAT_ONLY' && record.fatalNegatives.includes('INTRADAY_FADE')) return true
  return Boolean(
    battlefield.dominance !== 'WEAK' &&
      (record.timeline.candidateAt || record.timeline.weakeningAt),
  )
}

function buildIntradayTransitions(
  current: LeaderRecord[],
  battlefields: BattlefieldRecord[],
): LeaderTransition[] {
  const transitions: LeaderTransition[] = []

  sortByAuthority(current, battlefields)
    .filter((record) => shouldAppearInTimeline(record, battlefields))
    .slice(0, MAX_TIMELINE_RECORDS)
    .forEach((record) => {
      if (record.timeline.candidateAt) {
        transitions.push({
          type: 'candidate',
          code: record.code,
          name: record.name,
          role: record.primaryRole,
          to: record.authority,
          reason: record.playbook[0] || '进入复盘候选池',
          timestamp: record.timeline.candidateAt,
        })
      }

      if (record.timeline.confirmedAt) {
        transitions.push({
          type: 'confirm',
          code: record.code,
          name: record.name,
          role: record.primaryRole,
          to: record.authority,
          reason: record.evidence.find((item) => item.verdict === 'support')?.label || '通过关键确认阶段',
          timestamp: record.timeline.confirmedAt,
        })
      }

      if (record.timeline.commandingAt) {
        transitions.push({
          type: 'command',
          code: record.code,
          name: record.name,
          role: record.primaryRole,
          to: record.status,
          reason: '收盘仍保持战场主导权',
          timestamp: record.timeline.commandingAt,
        })
      }

      if (record.timeline.weakeningAt) {
        transitions.push({
          type: 'weaken',
          code: record.code,
          name: record.name,
          role: record.primaryRole,
          to: record.status,
          reason: record.invalidationReasons[0] || '尾段优势开始转弱',
          timestamp: record.timeline.weakeningAt,
        })
      }

      if (record.timeline.deposedAt) {
        transitions.push({
          type: 'depose',
          code: record.code,
          name: record.name,
          role: record.primaryRole,
          to: 'removed',
          reason: record.invalidationReasons[0] || '退出本轮领导权竞争',
          timestamp: record.timeline.deposedAt,
        })
      }
    })

  return transitions
    .sort((a, b) => a.timestamp - b.timestamp)
    .slice(-MAX_TIMELINE_RECORDS)
}

function buildTransitions(
  current: LeaderRecord[],
  previous: DragonReviewResult | null,
  marketCore: LeaderRecord | null,
  battlefields: BattlefieldRecord[],
): LeaderTransition[] {
  const transitions = buildIntradayTransitions(current, battlefields)
  if (!previous) return transitions

  const previousRecords = new Map<string, LeaderRecord>()
  ;[
    ...(previous.trueLeaders || []),
    ...(previous.heightBoard || []),
    ...(previous.attentionBoard || []),
  ].forEach((record) => previousRecords.set(record.code, record))
  if (previous.marketCore) {
    previousRecords.set(previous.marketCore.code, previous.marketCore)
  }

  current.forEach((record) => {
    const oldRecord = previousRecords.get(record.code)
    if (!oldRecord) return

    if (oldRecord.authority !== record.authority) {
      transitions.push({
        type:
          authorityWeight(record.authority) > authorityWeight(oldRecord.authority)
            ? 'confirm'
            : 'weaken',
        code: record.code,
        name: record.name,
        role: record.primaryRole,
        from: oldRecord.authority,
        to: record.authority,
        reason: record.invalidationReasons[0] || record.evidence[0]?.label || '领导权状态发生变化',
        timestamp: Date.now(),
      })
    }

    if (oldRecord.status !== record.status && record.status === 'COMMANDING') {
      transitions.push({
        type: 'command',
        code: record.code,
        name: record.name,
        role: record.primaryRole,
        from: oldRecord.status,
        to: record.status,
        reason: '收盘主导权加强',
        timestamp: Date.now(),
      })
    }
  })

  if (marketCore && previous.marketCore && previous.marketCore.code !== marketCore.code) {
    transitions.push({
      type: 'replace',
      code: marketCore.code,
      name: marketCore.name,
      role: 'MARKET_CORE',
      from: previous.marketCore.code,
      to: marketCore.code,
      reason: '市场总龙头切换',
      timestamp: Date.now(),
    })
  }

  return transitions
    .sort((a, b) => a.timestamp - b.timestamp)
    .slice(-MAX_TIMELINE_RECORDS)
}

function buildSummary(
  regime: ReviewRegime,
  marketCore: LeaderRecord | null,
  trueLeaders: LeaderRecord[],
  graveyard: PseudoLeaderRecord[],
): string[] {
  const lines = [`市场复盘态：${regimeLabel(regime)}`]
  if (marketCore) {
    lines.push(`市场总龙头：${marketCore.name}（${marketCore.themeName || roleLabel(marketCore.primaryRole)}）`)
  } else {
    lines.push('市场总龙头：空缺，今天更适合分战场看真龙')
  }
  lines.push(`真龙榜 ${trueLeaders.length} 只，高标/热度陷阱样本 ${graveyard.length} 只`)
  const doNotChase = trueLeaders.filter((leader) => leader.tradeability === 'DO_NOT_CHASE').length
  if (doNotChase > 0) {
    lines.push(`即使是真龙，也有 ${doNotChase} 只处于“不能追”的状态`)
  }
  return lines
}

export class ReviewComposer {
  compose(params: {
    reviewDate: string
    regime: ReviewRegime
    battlefields: BattlefieldRecord[]
    leaders: LeaderRecord[]
    graveyard: PseudoLeaderRecord[]
    previous: DragonReviewResult | null
    missingData: string[]
  }): DragonReviewResult {
    const sortedBattlefields = sortBattlefields(params.battlefields)
    const sortedLeaders = uniqueLeadersByCode(sortByAuthority(params.leaders, sortedBattlefields))
    const graveyard = uniquePseudoByCode(params.graveyard)
    const trueLeaders = sortedLeaders.filter((leader) => leader.authority === 'TRUE_LEADER')
    const heightBoard = sortByAuthority(
      sortedLeaders.filter(
        (leader) => leader.roles.includes('SPACE_CORE') || leader.authority === 'HEIGHT_ONLY',
      ),
      sortedBattlefields,
    )
    const attentionBoard = buildAttentionBoard(params.leaders, sortedBattlefields)
    const marketCore = pickMarketCore(trueLeaders, sortedBattlefields)
    const transitions = buildTransitions(
      sortedLeaders,
      params.previous,
      marketCore,
      sortedBattlefields,
    )

    return {
      reviewDate: params.reviewDate,
      regime: params.regime,
      marketCore,
      battlefields: sortedBattlefields,
      trueLeaders,
      heightBoard,
      attentionBoard,
      pseudoLeaderGraveyard: graveyard,
      transitions,
      summaryLines: buildSummary(params.regime, marketCore, trueLeaders, graveyard),
      missingData: params.missingData,
      reviewCompleteness: params.missingData.length > 0 ? 'partial' : 'complete',
    }
  }
}

export const reviewComposer = new ReviewComposer()
