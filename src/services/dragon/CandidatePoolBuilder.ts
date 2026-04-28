import { dataLayer } from '../../services/DataLayer'
import type { MergedStock } from '../../services/DataLayer'
import type { BattlefieldRecord, CandidateRecord, ReviewFrame, ReviewSegment, StockArc } from './types'
import {
  getNetCapital,
  inferBoardHeight,
  leadStatusRank,
  parseTimeToMinutes,
  rankInFrame,
  themeNamesFromStock,
} from './helpers'

export interface CandidateBuildResult {
  battlefields: BattlefieldRecord[]
  candidates: CandidateRecord[]
  arcsByCode: Map<string, StockArc>
}

function getLateRank(frames: ReviewFrame[], code: string): number {
  const lateFrame = [...frames].reverse().find((frame) => frame.segment === 'late')
  const rank = lateFrame ? rankInFrame(lateFrame, code) : null
  return rank ?? 999
}

function frameHitsBySegment(frames: ReviewFrame[], code: string, segment: ReviewSegment): number {
  return frames.filter((frame) => frame.segment === segment && rankInFrame(frame, code) !== null).length
}

function buildArc(
  stock: MergedStock,
  battlefield: BattlefieldRecord,
  frames: ReviewFrame[],
  battlefieldCodes: Set<string>,
): StockArc {
  // arc 记录的是一只票在当日复盘中的轨迹切片：
  // 什么时候出现、跨了几个 segment、收盘排位如何、有没有把跟风带出来。
  const arcFrames = frames
    .map((frame) => {
      const rank = rankInFrame(frame, stock.code)
      if (rank === null) return null
      const hot = frame.hotlist.find((item) => item.code === stock.code)
      return {
        frameId: frame.id,
        segment: frame.segment || 'late',
        timestamp: frame.timestamp,
        rank,
        change: hot?.change || stock.change || 0,
        leadStatus: hot?.leadStatus || stock.leadStatus,
      }
    })
    .filter(Boolean) as StockArc['frames']

  const segmentHits = [...new Set(arcFrames.map((frame) => frame.segment))] as ReviewSegment[]
  const earlyFrames = frames.filter((frame) => frame.segment === 'early')
  const lateFrames = frames.filter((frame) => frame.segment === 'late')
  const followerCountEarly = new Set(
    earlyFrames.flatMap((frame) =>
      frame.hotlist
        .filter((item) => item.code !== stock.code && battlefieldCodes.has(item.code))
        .map((item) => item.code),
    ),
  ).size
  const followerCountLate = new Set(
    lateFrames.flatMap((frame) =>
      frame.hotlist
        .filter((item) => item.code !== stock.code && battlefieldCodes.has(item.code))
        .map((item) => item.code),
    ),
  ).size

  return {
    code: stock.code,
    name: stock.name,
    battlefieldId: battlefield.battlefieldId,
    themeId: battlefield.themeId,
    themeName: battlefield.themeName,
    current: stock,
    frames: arcFrames,
    segmentHits,
    frameHitCount: arcFrames.length,
    earlyTop2: frameHitsBySegment(frames, stock.code, 'early') > 0 && getEarlyBestRank(frames, stock.code) <= 2,
    midTop2: frameHitsBySegment(frames, stock.code, 'mid') > 0 && getMidBestRank(frames, stock.code) <= 2,
    lateTop2: frameHitsBySegment(frames, stock.code, 'late') > 0 && getLateRank(frames, stock.code) <= 2,
    earlyRank: getEarlyBestRank(frames, stock.code),
    lateRank: getLateRank(frames, stock.code),
    bestRank: arcFrames.length ? Math.min(...arcFrames.map((frame) => frame.rank)) : stock.compRank || 999,
    firstSeenAt: arcFrames[0]?.timestamp,
    firstStrongAt: arcFrames[0]?.timestamp,
    followerCountEarly,
    followerCountLate,
    followerIncrease: followerCountLate - followerCountEarly,
    themeRankRise: calculateThemeRankRise(frames, battlefield.themeName),
  }
}

function getEarlyBestRank(frames: ReviewFrame[], code: string): number {
  const ranks = frames
    .filter((frame) => frame.segment === 'early')
    .map((frame) => rankInFrame(frame, code))
    .filter((rank): rank is number => rank !== null)
  return ranks.length ? Math.min(...ranks) : 999
}

function getMidBestRank(frames: ReviewFrame[], code: string): number {
  const ranks = frames
    .filter((frame) => frame.segment === 'mid')
    .map((frame) => rankInFrame(frame, code))
    .filter((rank): rank is number => rank !== null)
  return ranks.length ? Math.min(...ranks) : 999
}

function calculateThemeRankRise(frames: ReviewFrame[], themeName: string): number {
  const ranks = frames
    .map((frame) => {
      const index = frame.sectors.findIndex((sector) => sector.name === themeName)
      return index >= 0 ? index + 1 : null
    })
    .filter((rank): rank is number => rank !== null)
  if (ranks.length < 2) return 0
  return Math.max(0, ranks[0] - ranks[ranks.length - 1])
}

function candidatePriority(stock: MergedStock, arc: StockArc): number {
  // 这里只用于战场内“谁值得进入复核池”的排序，
  // 不是龙头总分，更不能替代四道门和 duel 结果。
  let score = 0
  score += leadStatusRank(stock.leadStatus) * 30
  const firstZtMinutes = parseTimeToMinutes(stock.firstZtTime)
  if (firstZtMinutes !== null) {
    score += Math.max(0, 90 - firstZtMinutes / 5)
  }
  score += Math.max(stock.continuousDays || 0, stock.highDays || 0, inferBoardHeight(stock)) * 18
  score += Math.min(100, getNetCapital(stock) / 1e7)
  score += Math.max(0, 24 - (arc.lateRank || 24)) * 8
  score += Math.max(0, 12 - (stock.compRank || 999) / 10)
  score += (stock.hotness || 0) / 10
  score += Math.max(0, 60 - (stock.popularity || 999)) / 2
  return score
}

function qualifiesAsCandidate(stock: MergedStock, arc: StockArc, battlefieldStocks: MergedStock[]): boolean {
  // 候选池入口故意放宽，只要有“像龙”的理由就先保留，
  // 真龙与伪龙的分水岭放在 LeadershipAuthorityEngine 处理。
  const netCapital = getNetCapital(stock)
  const topCapital = [...battlefieldStocks]
    .sort((a, b) => getNetCapital(b) - getNetCapital(a))
    .slice(0, 2)
    .some((item) => item.code === stock.code)
  const topPopularity = [...battlefieldStocks]
    .sort((a, b) => (a.popularity || 999) - (b.popularity || 999))
    .slice(0, 2)
    .some((item) => item.code === stock.code)

  return Boolean(
    (stock.leadStatus || '').includes('龙') ||
      (stock.firstZtTime && (arc.lateRank || 999) <= 3) ||
      (stock.continuousDays || 0) >= 2 ||
      (stock.highDays || 0) >= 2 ||
      arc.frameHitCount >= 2 && (arc.bestRank || 999) <= 20 ||
      topCapital ||
      netCapital > 0 && topCapital ||
      topPopularity ||
      ((stock.hotness || 0) > 0 && topPopularity),
  )
}

export class CandidatePoolBuilder {
  build(battlefields: BattlefieldRecord[], frames: ReviewFrame[]): CandidateBuildResult {
    const currentStocks = dataLayer.getStocks()
    const stockMap = new Map(currentStocks.map((stock) => [stock.code, stock]))
    const arcsByCode = new Map<string, StockArc>()
    const candidates: CandidateRecord[] = []

    const patchedBattlefields = battlefields.map((battlefield) => {
      const battlefieldStocks = battlefield.candidateCodes
        .map((code) => stockMap.get(code))
        .filter(Boolean) as MergedStock[]
      const battlefieldCodeSet = new Set(battlefieldStocks.map((stock) => stock.code))

      const scoped = battlefieldStocks
        .map((stock) => {
          const arc = buildArc(stock, battlefield, frames, battlefieldCodeSet)
          arcsByCode.set(stock.code, arc)
          return { stock, arc }
        })
        .filter(({ stock, arc }) => qualifiesAsCandidate(stock, arc, battlefieldStocks))
        .sort((a, b) => candidatePriority(b.stock, b.arc) - candidatePriority(a.stock, a.arc))

      // 每个战场最多只留 5 个候选，强制缩小对决面，避免轮动市里把噪声全部放进后续判定。
      const selected = scoped.slice(0, 5)
      selected.forEach(({ stock, arc }) => {
        candidates.push({
          code: stock.code,
          battlefieldId: battlefield.battlefieldId,
          themeId: battlefield.themeId,
          themeName: battlefield.themeName,
          stock,
          arc,
          reasons: [
            (stock.leadStatus || '').includes('龙') ? '领涨状态显性入池' : '',
            (stock.continuousDays || 0) >= 2 ? `${stock.continuousDays} 连板/高标` : '',
            arc.frameHitCount >= 2 ? '多段热榜持续出现' : '',
            themeNamesFromStock(stock).length ? `所属题材 ${themeNamesFromStock(stock)[0]}` : '',
          ].filter(Boolean),
        })
      })

      return {
        ...battlefield,
        candidateCodes: selected.map((item) => item.stock.code),
        challengerCodes: selected.slice(1, 3).map((item) => item.stock.code),
        followerCodes: battlefieldStocks
          .map((stock) => stock.code)
          .filter((code) => !selected.some((item) => item.stock.code === code))
          .slice(0, 10),
      }
    })

    return {
      battlefields: patchedBattlefields,
      candidates,
      arcsByCode,
    }
  }
}

export const candidatePoolBuilder = new CandidatePoolBuilder()
