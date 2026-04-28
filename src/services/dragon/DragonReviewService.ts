import { EventManager } from '../../utils/eventManager'
import { AppEvents } from '../../types'
import { dataLayer } from '../../services/DataLayer'
import { frameNormalizer } from './FrameNormalizer'
import { sessionSegmenter } from './SessionSegmenter'
import { regimeClassifier } from './RegimeClassifier'
import { battlefieldBuilder } from './BattlefieldBuilder'
import { candidatePoolBuilder } from './CandidatePoolBuilder'
import { leadershipAuthorityEngine } from './LeadershipAuthorityEngine'
import { tradeabilityEngine } from './TradeabilityEngine'
import { reviewComposer } from './ReviewComposer'
import type {
  LeaderRecord,
  DragonReviewResult,
  LeaderRole,
  LeaderTransition,
  ReviewRegime,
} from './types'

function mapLegacyLevel(level?: string): LeaderRole | null {
  // 兼容旧调用方沿用的 level 口径，但内部已经全面切到新角色体系。
  // 这里只做单向映射，不再把旧分级语义带回真龙引擎。
  switch (level) {
    case 'TOTAL':
      return 'MARKET_CORE'
    case 'SECTOR':
      return 'THEME_CORE'
    case 'CONTINUOUS':
      return 'SPACE_CORE'
    case 'MIDDLE':
      return 'TREND_CORE'
    case 'EMOTION':
      return 'EMOTION_CORE'
    default:
      return null
  }
}

class DragonReviewService {
  private initialized = false
  private building = false
  private lastResult: DragonReviewResult | null = null
  private allRecords: LeaderRecord[] = []

  /**
   * 兼容层统一从当前内存结果或 DataLayer 的 review 切片派生记录池。
   * 这样冷启动或局部刷新时，不会出现“面板已有数据，但旧入口还是空数组”的分裂状态。
   */
  private getRecordPool(): LeaderRecord[] {
    if (this.allRecords.length) {
      return [...this.allRecords]
    }

    const review = this.getLatestReview()
    if (!review) return []

    const deduped = new Map<string, LeaderRecord>()
    ;[
      ...(review.trueLeaders || []),
      ...(review.heightBoard || []),
      ...(review.attentionBoard || []),
    ].forEach((record) => {
      if (!deduped.has(record.code)) {
        deduped.set(record.code, record)
      }
    })

    if (review.marketCore && !deduped.has(review.marketCore.code)) {
      deduped.set(review.marketCore.code, review.marketCore)
    }

    return Array.from(deduped.values())
  }

  async init(): Promise<boolean> {
    if (this.initialized) return true
    this.initialized = true
    await this.runFullUpdate()
    return true
  }

  async runFullUpdate(date?: string): Promise<number> {
    const result = await this.rebuildReview(date)
    this.syncData()
    return result.trueLeaders.length
  }

  async recalculateAll(date?: string): Promise<number> {
    return this.runFullUpdate(date)
  }

  async rebuildReview(date?: string): Promise<DragonReviewResult> {
    if (this.building) {
      // 刷新链可能从面板、导出、应用启动同时触发。
      // 并发时直接复用上一份结果，避免同日出现两套互相覆盖的复盘结论。
      return this.lastResult || this.createEmptyResult(date)
    }

    this.building = true
    try {
      // 真龙复盘主链路固定串行执行，任何模块都不能绕过 authority 阶段直接产出“龙头”。
      const { reviewDate, frames, missingData } = await frameNormalizer.normalize(date)
      if (!frames.length) {
        this.lastResult = this.createEmptyResult(reviewDate, missingData)
        return this.lastResult
      }

      const segmentedFrames = sessionSegmenter.assign(frames)
      const regime = regimeClassifier.classify(segmentedFrames)
      const battlefields = battlefieldBuilder.build(segmentedFrames)
      const candidateContext = candidatePoolBuilder.build(battlefields, segmentedFrames)
      const authorityResult = leadershipAuthorityEngine.evaluate(
        candidateContext.battlefields,
        candidateContext.candidates,
        segmentedFrames,
      )
      const tradedRecords = tradeabilityEngine.apply(authorityResult.leaders)
      const composed = reviewComposer.compose({
        reviewDate,
        regime,
        battlefields: authorityResult.battlefields,
        leaders: tradedRecords,
        graveyard: authorityResult.graveyard,
        previous: this.lastResult,
        missingData,
      })

      if (composed.marketCore) {
        const marketCoreCode = composed.marketCore.code
        // marketCore 是在真龙结果上的额外授予，只补 MARKET_CORE 角色标签，
        // 不回写四道门、对决和 authority 结论。
        composed.marketCore = {
          ...composed.marketCore,
          roles: [...new Set<LeaderRole>([...composed.marketCore.roles, 'MARKET_CORE'])],
          primaryRole: 'MARKET_CORE',
        }
        const idx = tradedRecords.findIndex((record) => record.code === marketCoreCode)
        if (idx >= 0) {
          tradedRecords[idx] = {
            ...tradedRecords[idx],
            roles: [...new Set<LeaderRole>([...tradedRecords[idx].roles, 'MARKET_CORE'])],
            primaryRole: 'MARKET_CORE',
          }
        }
      }

      this.allRecords = tradedRecords
      this.lastResult = {
        ...composed,
        trueLeaders: tradedRecords.filter((record) => record.authority === 'TRUE_LEADER'),
        heightBoard: composed.heightBoard,
        attentionBoard: composed.attentionBoard,
      }

      return this.lastResult
    } finally {
      this.building = false
    }
  }

  syncData(): void {
    if (!this.lastResult) return
    // DataLayer 同时保留 review 原始结果和一层兼容投影，
    // 这样旧 UI/旧导出即便还没完全迁移，也会读到新引擎产出的结果。
    dataLayer.updateReviewData(this.lastResult)
    EventManager.emit(AppEvents.DRAGON.UPDATED, {
      timestamp: Date.now(),
      result: this.lastResult,
    })
    this.lastResult.transitions.forEach((transition) => {
      EventManager.emit(AppEvents.DRAGON.CHANGED, transition)
    })
  }

  getLatestReview(): DragonReviewResult | null {
    return this.lastResult || dataLayer.getDragonReview()
  }

  getMarketCore(): LeaderRecord | null {
    return this.getLatestReview()?.marketCore || null
  }

  getTrueLeaders(): LeaderRecord[] {
    return this.getLatestReview()?.trueLeaders || []
  }

  getHeightBoard(): LeaderRecord[] {
    return this.getLatestReview()?.heightBoard || []
  }

  getAttentionBoard(): LeaderRecord[] {
    return this.getLatestReview()?.attentionBoard || []
  }

  getPseudoLeaderGraveyard() {
    return this.getLatestReview()?.pseudoLeaderGraveyard || []
  }

  getBattlefields() {
    return this.getLatestReview()?.battlefields || []
  }

  getReviewTransitions(): LeaderTransition[] {
    return this.getLatestReview()?.transitions || []
  }

  getAllLeaders(options?: { level?: string; theme?: string; limit?: number }) {
    // 旧入口继续允许按“级别”取数，但数据源已经统一收敛到新 review 记录。
    let records = this.getRecordPool()
    const targetRole = mapLegacyLevel(options?.level)
    if (targetRole) {
      records = records.filter((record) => record.roles.includes(targetRole))
    }
    if (options?.theme) {
      records = records.filter((record) => record.themeName === options.theme)
    }
    records.sort((a, b) => {
      const authorityDiff =
        (b.authority === 'TRUE_LEADER' ? 2 : b.authority === 'THEME_COMMANDER' ? 1 : 0) -
        (a.authority === 'TRUE_LEADER' ? 2 : a.authority === 'THEME_COMMANDER' ? 1 : 0)
      if (authorityDiff !== 0) return authorityDiff
      return b.change - a.change
    })
    return options?.limit ? records.slice(0, options.limit) : records
  }

  getLeadersByLevel(level: string, limit: number = 10) {
    return this.getAllLeaders({ level, limit })
  }

  getLeaderByCode(code: string): LeaderRecord | null {
    return this.getRecordPool().find((record) => record.code === code) || null
  }

  getLeaderChanges(limit: number = 10): LeaderTransition[] {
    return this.getReviewTransitions().slice(0, limit)
  }

  getLeaderDistribution() {
    const byLevel: Record<string, number> = {}
    const byTheme: Record<string, number> = {}
    const recordPool = this.getRecordPool()
    recordPool.forEach((record) => {
      byLevel[record.primaryRole] = (byLevel[record.primaryRole] || 0) + 1
      if (record.themeName) {
        byTheme[record.themeName] = (byTheme[record.themeName] || 0) + 1
      }
    })
    return {
      byLevel,
      byTheme,
      total: recordPool.length,
    }
  }

  getStats() {
    // 统计字段名暂时保持旧口径，降低迁移成本；
    // 实际统计依据已经变成新的 role/authority 组合。
    const recordPool = this.getRecordPool()
    const stats = {
      totalLeaders: recordPool.length,
      totalLeadersCount: 0,
      sectorLeaders: 0,
      continuousLeaders: 0,
      middleLeaders: 0,
      emotionLeaders: 0,
      themeLeaders: 0,
      lastUpdate: this.getLatestReview() ? Date.now() : (null as number | null),
    }

    recordPool.forEach((record) => {
      if (record.roles.includes('MARKET_CORE')) stats.totalLeadersCount++
      if (record.roles.includes('THEME_CORE')) {
        stats.sectorLeaders++
        stats.themeLeaders++
      }
      if (record.roles.includes('SPACE_CORE')) stats.continuousLeaders++
      if (record.roles.includes('TREND_CORE')) stats.middleLeaders++
      if (record.roles.includes('EMOTION_CORE')) stats.emotionLeaders++
    })

    return stats
  }

  isLeader(code: string): boolean {
    const record = this.getLeaderByCode(code)
    return Boolean(record && ['TRUE_LEADER', 'THEME_COMMANDER'].includes(record.authority))
  }

  repairConsistency(): Promise<boolean> {
    return this.runFullUpdate().then(() => true).catch(() => false)
  }

  debug() {
    return {
      initialized: this.initialized,
      lastResult: this.lastResult,
      records: this.getRecordPool().length,
    }
  }

  private createEmptyResult(date?: string, missingData: string[] = []): DragonReviewResult {
    return {
      reviewDate: date || new Date().toISOString().slice(0, 10),
      regime: 'ROTATION_NO_CORE',
      marketCore: null,
      battlefields: [],
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      transitions: [],
      summaryLines: ['当前没有足够数据形成真龙复盘结果'],
      missingData,
      reviewCompleteness: 'partial',
    }
  }
}

export const dragonReviewService = new DragonReviewService()

if (typeof window !== 'undefined') {
  ;(window as any).dragonReviewService = dragonReviewService
}
