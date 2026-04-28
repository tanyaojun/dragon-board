import type { MergedStock } from '../../services/DataLayer'
import type {
  AuthorityClass,
  BattlefieldRecord,
  CandidateRecord,
  DuelResult,
  FatalNegative,
  LeaderEvidence,
  LeaderRecord,
  LeaderRole,
  LeaderStatus,
  PseudoLeaderRecord,
  ReviewFrame,
  ReviewSegment,
  StockArc,
} from './types'
import {
  getNetCapital,
  inferBoardHeight,
  leadStatusRank,
  median,
  parseTimeToMinutes,
  rankInFrame,
  roleOrder,
} from './helpers'

interface AuthorityEvaluationResult {
  battlefields: BattlefieldRecord[]
  leaders: LeaderRecord[]
  graveyard: PseudoLeaderRecord[]
}

interface GateResult {
  pass: boolean
  note: string
}

interface CandidateAssessment {
  candidate: CandidateRecord
  battlefield: BattlefieldRecord
  duelResults: DuelResult[]
  gateA: GateResult
  gateB: GateResult
  gateC: GateResult
  gateD: GateResult
  fatalNegatives: FatalNegative[]
  invalidationReasons: string[]
  authority: AuthorityClass
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  roles: LeaderRole[]
  status: LeaderStatus
  evidence: LeaderEvidence[]
  contradictions: string[]
  successors: string[]
  timeline: LeaderRecord['timeline']
}

const AUTHORITY_ORDER: Record<AuthorityClass, number> = {
  TRUE_LEADER: 6,
  THEME_COMMANDER: 5,
  CARRY_PROXY: 4,
  HEIGHT_ONLY: 3,
  HEAT_ONLY: 2,
  PSEUDO_LEADER: 1,
}

function capitalOf(stock: Partial<MergedStock>): number {
  return getNetCapital(stock)
}

function boardHeightOf(stock: Partial<MergedStock>): number {
  return Math.max(inferBoardHeight(stock), stock.continuousDays || 0, stock.highDays || 0)
}

function closeMetricScore(stock: Partial<MergedStock>, arc: StockArc): number {
  const acceptance = (stock.fengdan || 0) + (stock.maxFengdan || 0)
  return (
    boardHeightOf(stock) * 30 +
    leadStatusRank(stock.leadStatus) * 18 +
    capitalOf(stock) / 1e7 +
    acceptance / 1e7 +
    Math.max(0, 12 - (arc.lateRank || 999)) * 10
  )
}

function firstStrongMinutes(stock: Partial<MergedStock>, arc: StockArc): number {
  return parseTimeToMinutes(stock.firstZtTime) ?? parseTimeToMinutes(stock.lastZtTime) ?? Math.floor((arc.firstStrongAt || arc.firstSeenAt || 0) / 60000)
}

function isOneWordIsolation(stock: Partial<MergedStock>): boolean {
  return (stock.continuousDays || 0) > 1 && (stock.turnoverRate || 0) < 3
}

function isLateHeatChase(stock: Partial<MergedStock>, arc: StockArc): boolean {
  return !arc.earlyTop2 && (arc.lateRank || 999) <= 3 && ((stock.hotness || 0) >= 80 || (stock.popularity || 999) <= 10)
}

function isIntradayFade(arc: StockArc): boolean {
  return arc.earlyTop2 && (arc.lateRank || 999) > 5
}

function buildTimeline(arc: StockArc, authority: AuthorityClass): LeaderRecord['timeline'] {
  const earlyFrame = arc.frames.find((frame) => frame.segment === 'early')
  const midFrame = arc.frames.find((frame) => frame.segment === 'mid')
  const lateFrame = [...arc.frames].reverse().find((frame) => frame.segment === 'late')
  const weakeningFrame = [...arc.frames]
    .reverse()
    .find((frame) => frame.segment === 'late' && frame.rank > 3)

  return {
    candidateAt: arc.firstSeenAt,
    probingAt: earlyFrame?.timestamp,
    confirmedAt: authority === 'TRUE_LEADER' || authority === 'THEME_COMMANDER' ? midFrame?.timestamp || earlyFrame?.timestamp : undefined,
    commandingAt: authority === 'TRUE_LEADER' && lateFrame ? lateFrame.timestamp : undefined,
    weakeningAt: weakeningFrame?.timestamp,
    deposedAt: authority === 'PSEUDO_LEADER' && lateFrame ? lateFrame.timestamp : undefined,
  }
}

function statusFromAssessment(authority: AuthorityClass, arc: StockArc): LeaderStatus {
  if (authority === 'TRUE_LEADER') {
    return arc.lateTop2 ? 'COMMANDING' : 'CONFIRMED_LEADER'
  }
  if (authority === 'THEME_COMMANDER') {
    return arc.lateTop2 ? 'CONFIRMED_LEADER' : 'WEAKENING'
  }
  if (authority === 'PSEUDO_LEADER') {
    return arc.lateTop2 ? 'WEAKENING' : 'DEPOSED'
  }
  if (arc.earlyTop2 || arc.midTop2) {
    return 'PROBING_LEADER'
  }
  return 'CANDIDATE'
}

function deriveRoles(
  authority: AuthorityClass,
  battlefield: BattlefieldRecord,
  stock: MergedStock,
  arc: StockArc,
): LeaderRole[] {
  const roles: LeaderRole[] = []

  if (
    battlefield.type === 'THEME' &&
    (authority === 'TRUE_LEADER' || authority === 'THEME_COMMANDER')
  ) {
    roles.push('THEME_CORE')
  }

  if (
    authority !== 'HEAT_ONLY' &&
    (boardHeightOf(stock) >= 2 || arc.frameHitCount >= 2 || (stock.highDays || 0) >= 2)
  ) {
    roles.push('SPACE_CORE')
  }

  if (
    (authority === 'TRUE_LEADER' || authority === 'THEME_COMMANDER' || authority === 'CARRY_PROXY') &&
    battlefield.capital !== 'weak' &&
    battlefield.carryStrength !== 'weak' &&
    (stock.totalMV || 0) >= 5e9
  ) {
    roles.push('TREND_CORE')
  }

  if (
    authority === 'HEAT_ONLY' ||
    authority === 'PSEUDO_LEADER' ||
    (stock.hotness || 0) >= 70 ||
    ((stock.popularity || 999) > 0 && (stock.popularity || 999) <= 10)
  ) {
    roles.push('EMOTION_CORE')
  }

  if (!roles.length) {
    if (authority === 'HEIGHT_ONLY') {
      roles.push('SPACE_CORE')
    } else if (authority === 'CARRY_PROXY') {
      roles.push('TREND_CORE')
    } else {
      roles.push('EMOTION_CORE')
    }
  }

  return Array.from(new Set(roles)).sort((a, b) => roleOrder(a) - roleOrder(b))
}

function confidenceFromAssessment(
  gateA: GateResult,
  gateB: GateResult,
  gateC: GateResult,
  gateD: GateResult,
  duelResults: DuelResult[],
  authority: AuthorityClass,
): 'HIGH' | 'MEDIUM' | 'LOW' {
  const gateCount = [gateA, gateB, gateC, gateD].filter((gate) => gate.pass).length
  const duelWins = duelResults.length
    ? Math.min(...duelResults.map((duel) => duel.wins))
    : 4

  if (authority === 'TRUE_LEADER' && gateCount === 4 && duelWins >= 4) return 'HIGH'
  if (gateCount >= 3) return 'MEDIUM'
  return 'LOW'
}

function buildEvidence(
  battlefield: BattlefieldRecord,
  stock: MergedStock,
  arc: StockArc,
  gateA: GateResult,
  gateB: GateResult,
  gateC: GateResult,
  gateD: GateResult,
): LeaderEvidence[] {
  const entries: Array<[string, string, boolean]> = [
    ['battlefield', `战场 ${battlefield.dominance}`, gateA.pass],
    ['causality', gateB.note, gateB.pass],
    ['disagreement', gateC.note, gateC.pass],
    ['close', gateD.note, gateD.pass],
    ['capital', `净额 ${capitalOf(stock).toFixed(0)}`, capitalOf(stock) > 0],
    ['carry', `跟风扩散 ${arc.followerIncrease}`, arc.followerIncrease >= 2],
  ]

  return entries.map(([id, label, pass]) => ({
    id,
    label,
    verdict: pass ? 'support' : 'contradict',
  }))
}

function duelDimension(
  left: CandidateRecord,
  right: CandidateRecord,
  selector: (entry: CandidateRecord) => number,
  tieTolerance: number = 0,
): 'win' | 'tie' | 'lose' {
  const diff = selector(left) - selector(right)
  if (Math.abs(diff) <= tieTolerance) return 'tie'
  return diff > 0 ? 'win' : 'lose'
}

function buildDuel(
  candidate: CandidateRecord,
  challenger: CandidateRecord,
  battlefield: BattlefieldRecord,
): DuelResult {
  const acceptanceScore = (entry: CandidateRecord) => {
    const rate = entry.stock.turnoverRate || 0
    const healthy = rate >= 4 && rate <= 28 ? 20 : 0
    return healthy + ((entry.stock.fengdan || 0) + (entry.stock.maxFengdan || 0)) / 1e7
  }

  const carryScore = (entry: CandidateRecord) => entry.arc.followerIncrease * 15 + entry.arc.themeRankRise * 8
  const persistenceScore = (entry: CandidateRecord) =>
    entry.arc.segmentHits.length * 20 +
    (entry.arc.earlyTop2 ? 10 : 0) +
    (entry.arc.midTop2 ? 10 : 0) +
    (entry.arc.lateTop2 ? 10 : 0)

  const closeScore = (entry: CandidateRecord) =>
    closeMetricScore(entry.stock, entry.arc) + (battlefield.themeName === entry.themeName ? 12 : 0)

  const dimensions: DuelResult['dimensions'] = {
    initiative: duelDimension(candidate, challenger, (entry) => -firstStrongMinutes(entry.stock, entry.arc), 3),
    height: duelDimension(candidate, challenger, (entry) => boardHeightOf(entry.stock), 0),
    acceptance: duelDimension(candidate, challenger, acceptanceScore, 3),
    capitalRecognition: duelDimension(candidate, challenger, (entry) => capitalOf(entry.stock), 5e6),
    carryEffect: duelDimension(candidate, challenger, carryScore, 10),
    segmentPersistence: duelDimension(candidate, challenger, persistenceScore, 5),
    closeIntegrity: duelDimension(candidate, challenger, closeScore, 20),
  }

  const values = Object.values(dimensions)
  const wins = values.filter((value) => value === 'win').length
  const losses = values.filter((value) => value === 'lose').length
  const ties = values.filter((value) => value === 'tie').length

  return {
    againstCode: challenger.code,
    wins,
    losses,
    ties,
    dimensions,
  }
}

function gateAResult(battlefield: BattlefieldRecord): GateResult {
  if (battlefield.dominance === 'WEAK') {
    return { pass: false, note: '战场偏弱，默认不产真龙' }
  }
  if (battlefield.type === 'STYLE' && !battlefield.themeId) {
    return { pass: false, note: '风格战场无真实题材承接' }
  }
  return { pass: true, note: `战场 ${battlefield.dominance}` }
}

function gateBResult(candidate: CandidateRecord, peers: CandidateRecord[]): GateResult {
  const followerMedian = median(
    peers
      .filter((peer) => peer.code !== candidate.code)
      .map((peer) => firstStrongMinutes(peer.stock, peer.arc))
      .filter((value) => Number.isFinite(value) && value > 0),
  )
  const candidateMinute = firstStrongMinutes(candidate.stock, candidate.arc)
  const earlyDriven =
    candidate.arc.earlyTop2 && candidate.arc.followerIncrease >= 2
  const diffusionDriven =
    candidate.arc.themeRankRise >= 3 || candidate.arc.followerIncrease >= 2

  if (followerMedian > 0 && candidateMinute > 0 && candidateMinute <= followerMedian - 15) {
    return { pass: true, note: '启动领先同战场跟风中位时间 15 分钟以上' }
  }
  if (earlyDriven) {
    return { pass: true, note: '早段已居前二，后续跟风扩散明显' }
  }
  if (diffusionDriven) {
    return { pass: true, note: '首次强势后题材热度与跟风同步扩散' }
  }
  return { pass: false, note: '更像热度结果，不像发动原因' }
}

function gateCResult(candidate: CandidateRecord): GateResult {
  if (isOneWordIsolation(candidate.stock)) {
    return { pass: false, note: '连续一字且换手不足，未完成分歧检验' }
  }
  if (candidate.arc.segmentHits.length >= 2 && (candidate.arc.earlyTop2 || candidate.arc.midTop2 || candidate.arc.lateTop2)) {
    return { pass: true, note: '跨两个以上 segment 保持前二' }
  }
  return { pass: false, note: '仅有单段强势，分歧检验不足' }
}

function closeWinCount(candidate: CandidateRecord, challenger: CandidateRecord): number {
  let wins = 0
  if (boardHeightOf(candidate.stock) >= boardHeightOf(challenger.stock)) wins++
  if (leadStatusRank(candidate.stock.leadStatus) >= leadStatusRank(challenger.stock.leadStatus)) wins++
  if (capitalOf(candidate.stock) >= capitalOf(challenger.stock)) wins++
  if (((candidate.stock.fengdan || 0) + (candidate.stock.maxFengdan || 0)) >= ((challenger.stock.fengdan || 0) + (challenger.stock.maxFengdan || 0))) wins++
  if (candidate.arc.followerIncrease >= challenger.arc.followerIncrease) wins++
  return wins
}

function gateDResult(candidate: CandidateRecord, challengers: CandidateRecord[]): GateResult {
  if (!candidate.arc.lateTop2) {
    return { pass: false, note: '收盘段未守住战场前二' }
  }

  const closeLoser = challengers.find((challenger) => closeWinCount(candidate, challenger) <= 2)
  if (closeLoser) {
    return {
      pass: false,
      note: `${closeLoser.name} 在收盘维度上反超，领导权未守住`,
    }
  }

  return { pass: true, note: '收盘段仍守住战场主导权' }
}

function fatalNegativesFor(
  battlefield: BattlefieldRecord,
  candidate: CandidateRecord,
  gateA: GateResult,
  gateD: GateResult,
): FatalNegative[] {
  const negatives: FatalNegative[] = []
  if (!gateA.pass) negatives.push('WEAK_BATTLEFIELD')
  if (isOneWordIsolation(candidate.stock)) negatives.push('ONE_WORD_ISOLATION')
  if (candidate.arc.followerIncrease <= 0 && candidate.arc.followerCountLate <= 1) negatives.push('NO_FOLLOWERS')
  if (isLateHeatChase(candidate.stock, candidate.arc)) negatives.push('LATE_HEAT_CHASE')
  if (isIntradayFade(candidate.arc)) negatives.push('INTRADAY_FADE')
  if (!gateD.pass) negatives.push('CLOSE_LOST_LEADERSHIP')
  if (battlefield.type === 'STYLE' || (battlefield.type === 'INDEPENDENT' && !battlefield.themeId)) {
    negatives.push('MAPPING_UNCERTAIN')
  }
  return Array.from(new Set(negatives))
}

function invalidationReasonsFor(
  candidate: CandidateRecord,
  gateA: GateResult,
  gateB: GateResult,
  gateC: GateResult,
  gateD: GateResult,
): string[] {
  return [gateA, gateB, gateC, gateD]
    .filter((gate) => !gate.pass)
    .map((gate) => gate.note)
}

function authorityFor(
  battlefield: BattlefieldRecord,
  candidate: CandidateRecord,
  duelResults: DuelResult[],
  gateA: GateResult,
  gateB: GateResult,
  gateC: GateResult,
  gateD: GateResult,
  fatalNegatives: FatalNegative[],
): AuthorityClass {
  const minWins = duelResults.length ? Math.min(...duelResults.map((duel) => duel.wins)) : 4
  const hasFatal = fatalNegatives.length > 0
  const boardHeight = boardHeightOf(candidate.stock)
  const hotOnly = (candidate.stock.hotness || 0) >= 75 || ((candidate.stock.popularity || 999) > 0 && (candidate.stock.popularity || 999) <= 10)
  const capitalStrong = capitalOf(candidate.stock) > 0 && battlefield.capital !== 'weak'

  if (gateA.pass && gateB.pass && gateC.pass && gateD.pass && minWins >= 4 && !hasFatal) {
    return 'TRUE_LEADER'
  }
  if (gateA.pass && gateB.pass && gateD.pass && minWins >= 3 && fatalNegatives.every((item) => item !== 'WEAK_BATTLEFIELD')) {
    return 'THEME_COMMANDER'
  }
  if (capitalStrong && !gateB.pass) {
    return 'CARRY_PROXY'
  }
  if (boardHeight >= 2 && (!gateB.pass || !gateC.pass)) {
    return 'HEIGHT_ONLY'
  }
  if (hotOnly && (!gateA.pass || !gateB.pass)) {
    return 'HEAT_ONLY'
  }
  return 'PSEUDO_LEADER'
}

function toPseudoLeaderRecord(assessment: CandidateAssessment): PseudoLeaderRecord {
  const support = assessment.evidence
    .filter((entry) => entry.verdict === 'support')
    .map((entry) => entry.label)
    .slice(0, 3)
  const chaseHurts = assessment.fatalNegatives.length
    ? assessment.fatalNegatives.map((item) => item.replaceAll('_', ' '))
    : ['领导权未闭环，追涨胜率差']

  return {
    code: assessment.candidate.code,
    name: assessment.candidate.stock.name,
    pseudoType: assessment.authority,
    battlefieldId: assessment.battlefield.battlefieldId,
    themeName: assessment.battlefield.themeName,
    whyLookedLikeLeader: support.length ? support : assessment.candidate.reasons,
    whyNotLeader: assessment.invalidationReasons.length
      ? assessment.invalidationReasons
      : ['战场内对决未取胜'],
    whyChasingHurts: chaseHurts,
    price: assessment.candidate.stock.price || 0,
    change: assessment.candidate.stock.change || 0,
    continuousDays: assessment.candidate.stock.continuousDays || assessment.candidate.stock.highDays || 0,
    leadStatus: assessment.candidate.stock.leadStatus,
  }
}

function toLeaderRecord(assessment: CandidateAssessment): LeaderRecord {
  const stock = assessment.candidate.stock
  const roles = assessment.roles
  return {
    code: stock.code,
    name: stock.name,
    primaryRole: roles[0],
    roles,
    authority: assessment.authority,
    tradeability: 'WATCH_ONLY',
    chaseRisk: 'HIGH',
    status: assessment.status,
    battlefieldId: assessment.battlefield.battlefieldId,
    themeId: assessment.candidate.themeId,
    themeName: assessment.candidate.themeName,
    evidence: assessment.evidence,
    contradictions: assessment.contradictions,
    fatalNegatives: assessment.fatalNegatives,
    invalidationReasons: assessment.invalidationReasons,
    successors: assessment.successors,
    timeline: assessment.timeline,
    playbook: [],
    duelResults: assessment.duelResults,
    confidence: assessment.confidence,
    price: stock.price || 0,
    change: stock.change || 0,
    turnover: stock.turnover || 0,
    turnoverRate: stock.turnoverRate || 0,
    zlje: stock.zlje || capitalOf(stock),
    continuousDays: stock.continuousDays || 0,
    highDays: stock.highDays || 0,
    hotness: stock.hotness || 0,
    popularity: stock.popularity || 0,
    popularityChange: stock.popularityChange || 0,
    leadStatus: stock.leadStatus || '',
    lianbanStr: stock.lianbanStr || '',
    boardHeight: boardHeightOf(stock),
    themes: stock.themes || [],
  }
}

export class LeadershipAuthorityEngine {
  evaluate(
    battlefields: BattlefieldRecord[],
    candidates: CandidateRecord[],
    frames: ReviewFrame[],
  ): AuthorityEvaluationResult {
    const candidatesByBattlefield = new Map<string, CandidateRecord[]>()
    candidates.forEach((candidate) => {
      if (!candidatesByBattlefield.has(candidate.battlefieldId)) {
        candidatesByBattlefield.set(candidate.battlefieldId, [])
      }
      candidatesByBattlefield.get(candidate.battlefieldId)!.push(candidate)
    })

    const reviewedBattlefields: BattlefieldRecord[] = []
    const leaders: LeaderRecord[] = []
    const graveyard: PseudoLeaderRecord[] = []

    for (const battlefield of battlefields) {
      const scopedCandidates = candidatesByBattlefield.get(battlefield.battlefieldId) || []
      if (!scopedCandidates.length) {
        reviewedBattlefields.push(battlefield)
        continue
      }

      const assessments = scopedCandidates.map((candidate) => {
        const challengers = scopedCandidates.filter((entry) => entry.code !== candidate.code)
        const duelResults = challengers.map((challenger) => buildDuel(candidate, challenger, battlefield))
        const gateA = gateAResult(battlefield)
        const gateB = gateBResult(candidate, scopedCandidates)
        const gateC = gateCResult(candidate)
        const gateD = gateDResult(candidate, challengers.slice(0, 3))
        const fatalNegatives = fatalNegativesFor(battlefield, candidate, gateA, gateD)
        const authority = authorityFor(
          battlefield,
          candidate,
          duelResults,
          gateA,
          gateB,
          gateC,
          gateD,
          fatalNegatives,
        )
        const confidence = confidenceFromAssessment(gateA, gateB, gateC, gateD, duelResults, authority)
        const roles = deriveRoles(authority, battlefield, candidate.stock, candidate.arc)
        const evidence = buildEvidence(battlefield, candidate.stock, candidate.arc, gateA, gateB, gateC, gateD)
        const invalidationReasons = invalidationReasonsFor(candidate, gateA, gateB, gateC, gateD)
        const contradictions = fatalNegatives.map((item) => item.replaceAll('_', ' '))
        const status = statusFromAssessment(authority, candidate.arc)
        const timeline = buildTimeline(candidate.arc, authority)

        return {
          candidate,
          battlefield,
          duelResults,
          gateA,
          gateB,
          gateC,
          gateD,
          fatalNegatives,
          invalidationReasons,
          authority,
          confidence,
          roles,
          status,
          evidence,
          contradictions,
          successors: challengers.slice(0, 2).map((entry) => entry.code),
          timeline,
        } satisfies CandidateAssessment
      })

      assessments.sort((left, right) => {
        const authorityDiff = AUTHORITY_ORDER[right.authority] - AUTHORITY_ORDER[left.authority]
        if (authorityDiff !== 0) return authorityDiff
        const duelDiff =
          (right.duelResults[0]?.wins || 0) - (left.duelResults[0]?.wins || 0)
        if (duelDiff !== 0) return duelDiff
        return (left.candidate.arc.lateRank || 999) - (right.candidate.arc.lateRank || 999)
      })

      const winner = assessments[0]
      const runner = assessments[1]
      if (
        winner &&
        runner &&
        winner.authority === 'TRUE_LEADER' &&
        ((winner.duelResults[0]?.wins || 0) <= 3 || Math.abs((winner.duelResults[0]?.wins || 0) - (runner.duelResults[0]?.wins || 0)) <= 1)
      ) {
        winner.authority = 'THEME_COMMANDER'
        winner.contradictions.push('战场争夺未分出绝对胜负，降为主将')
      }

      const scopedLeaders = assessments.map((assessment, index) => {
        if (index > 0 && (assessment.authority === 'TRUE_LEADER' || assessment.authority === 'THEME_COMMANDER')) {
          assessment.authority = 'PSEUDO_LEADER'
          assessment.invalidationReasons.push('战场内对决落败，未拿到唯一领导权')
          assessment.contradictions.push('同战场已有更强主导者')
        }
        assessment.roles = deriveRoles(assessment.authority, battlefield, assessment.candidate.stock, assessment.candidate.arc)
        assessment.status = statusFromAssessment(assessment.authority, assessment.candidate.arc)
        assessment.confidence = confidenceFromAssessment(
          assessment.gateA,
          assessment.gateB,
          assessment.gateC,
          assessment.gateD,
          assessment.duelResults,
          assessment.authority,
        )
        assessment.timeline = buildTimeline(assessment.candidate.arc, assessment.authority)
        return toLeaderRecord(assessment)
      })

      const scopedGraveyard = assessments
        .filter((assessment) => assessment.authority === 'PSEUDO_LEADER')
        .map(toPseudoLeaderRecord)

      const leaderCode = scopedLeaders.find((record) =>
        record.authority === 'TRUE_LEADER' || record.authority === 'THEME_COMMANDER',
      )?.code

      reviewedBattlefields.push({
        ...battlefield,
        leaderCode,
        challengerCodes: scopedLeaders.slice(1, 3).map((record) => record.code),
        evidence: [...battlefield.evidence],
        risks: [...battlefield.risks],
      })

      leaders.push(...scopedLeaders)
      graveyard.push(...scopedGraveyard)
    }

    return {
      battlefields: reviewedBattlefields,
      leaders,
      graveyard,
    }
  }
}

export const leadershipAuthorityEngine = new LeadershipAuthorityEngine()
