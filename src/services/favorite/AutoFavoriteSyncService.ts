import { useFavoriteStore } from '@/stores/favorite'
import type { FavoriteStockSource } from '@/types'

/**
 * 自选股自动同步服务
 *
 * 挂在行情主页自动刷新（RankTrend 信号刷新）链路上，按用户规则维护自选股：
 * - 加入：本轮热榜股票中【排名趋势】为 MACD 金叉（technical.macd.cross === 'golden'）、
 *   【共振强度】方向向上（resonance.status === 'ok' && resonance.direction === 'buy'）、
 *   共振强度 >= 80%（resonance.score >= MIN_AUTO_ADD_RESONANCE_SCORE），
 *   且【生命周期】为点火或扩散（observation.lifecycle.stage ∈ ignition/expansion）
 *   → 加入自选股（来源标记为 auto）。
 * - 删除：来源为 auto 的自选股中，排名趋势转为死叉（macd.cross === 'death'）、
 *   生命周期进入降温/反转（stage ∈ cooling/reversal），或已退出本轮热榜股票池
 *   → 自动删除。
 *
 * 约束：
 * - 只增删来源为 auto 的自选股；用户手动加入（manual）的自选股绝不被自动删除。
 * - 候选池自动入池 / 飞书推送仍由 FusionCandidateNotifier 的 V5 合同独立判定，本服务不改动它。
 * - 本轮无热榜数据（stocks 为空）时不执行任何增删，避免误删。
 */

export const AUTO_FAVORITE_SOURCE: FavoriteStockSource = 'auto'

/** 自动加入自选股所需的共振强度下限（%） */
export const MIN_AUTO_ADD_RESONANCE_SCORE = 80

/** 允许自动入池的生命周期阶段：点火 / 扩散 */
const AUTO_ADD_LIFECYCLE_STAGES: ReadonlySet<string> = new Set(['ignition', 'expansion'])

/** 触发自动出池的生命周期阶段：降温 / 反转 */
const AUTO_REMOVE_LIFECYCLE_STAGES: ReadonlySet<string> = new Set(['cooling', 'reversal'])

export interface AutoFavoriteSyncResult {
  added: string[]
  removed: string[]
}

export interface AutoFavoriteOps {
  isFavorite: (code: string) => boolean
  listAutoFavorites: () => Array<{ code: string }>
  addAutoFavorite: (code: string) => boolean
  removeAutoFavorite: (code: string) => boolean
}

export interface AutoFavoriteSyncDeps extends Partial<AutoFavoriteOps> {
  getMacdCross?: (stock: any) => string
  getResonanceDirection?: (stock: any) => string | null
  getResonanceScore?: (stock: any) => number | null
  getLifecycleStage?: (stock: any) => string | null
  normalizeCode?: (code: unknown) => string
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function readMacdCross(stock: any): string {
  return stock?.rankTrend?.technical?.macd?.cross ?? 'none'
}

function readResonanceDirection(stock: any): string | null {
  const resonance = stock?.rankTrend?.resonance
  return resonance?.status === 'ok' ? (resonance.direction ?? null) : null
}

function readResonanceScore(stock: any): number | null {
  const resonance = stock?.rankTrend?.resonance
  if (resonance?.status !== 'ok') return null
  const score = Number(resonance.score)
  return Number.isFinite(score) ? score : null
}

function readLifecycleStage(stock: any): string | null {
  return stock?.rankTrend?.observation?.lifecycle?.stage ?? null
}

export class AutoFavoriteSyncService {
  private deps: AutoFavoriteSyncDeps

  constructor(deps: AutoFavoriteSyncDeps = {}) {
    this.deps = deps
  }

  private getMacdCross(stock: any): string {
    return this.deps.getMacdCross ? this.deps.getMacdCross(stock) : readMacdCross(stock)
  }

  private getResonanceDirection(stock: any): string | null {
    return this.deps.getResonanceDirection
      ? this.deps.getResonanceDirection(stock)
      : readResonanceDirection(stock)
  }

  private getResonanceScore(stock: any): number | null {
    return this.deps.getResonanceScore
      ? this.deps.getResonanceScore(stock)
      : readResonanceScore(stock)
  }

  private getLifecycleStage(stock: any): string | null {
    return this.deps.getLifecycleStage
      ? this.deps.getLifecycleStage(stock)
      : readLifecycleStage(stock)
  }

  private getNormalizeCode(): (code: unknown) => string {
    return this.deps.normalizeCode ?? normalizeCode
  }

  /**
   * 是否满足自动加入自选股：排名趋势 MACD 金叉 且 共振强度方向向上 且 共振强度 >= 80%
   * 且 生命周期为点火（ignition）或扩散（expansion）。
   */
  shouldAutoAdd(stock: any): boolean {
    const score = this.getResonanceScore(stock)
    const stage = this.getLifecycleStage(stock)
    return (
      this.getMacdCross(stock) === 'golden' &&
      this.getResonanceDirection(stock) === 'buy' &&
      score != null &&
      score >= MIN_AUTO_ADD_RESONANCE_SCORE &&
      stage != null &&
      AUTO_ADD_LIFECYCLE_STAGES.has(stage)
    )
  }

  /** 生命周期是否触发自动出池：降温（cooling）或反转（reversal）；缺失时不触发 */
  shouldAutoRemoveLifecycle(stock: any): boolean {
    const stage = this.getLifecycleStage(stock)
    return stage != null && AUTO_REMOVE_LIFECYCLE_STAGES.has(stage)
  }

  private resolveOps(): AutoFavoriteOps | null {
    const { isFavorite, listAutoFavorites, addAutoFavorite, removeAutoFavorite } = this.deps
    if (isFavorite && listAutoFavorites && addAutoFavorite && removeAutoFavorite) {
      return { isFavorite, listAutoFavorites, addAutoFavorite, removeAutoFavorite }
    }
    try {
      const store = useFavoriteStore()
      return {
        isFavorite: (code: string) => store.isFavorite(code),
        listAutoFavorites: () =>
          store.favoriteList.filter((fav) => fav.source === AUTO_FAVORITE_SOURCE),
        addAutoFavorite: (code: string) =>
          store.addToFavorites(code, '默认', '', AUTO_FAVORITE_SOURCE, true),
        removeAutoFavorite: (code: string) => store.removeFromFavorites(code, true),
      }
    } catch {
      return null
    }
  }

  /**
   * 执行一轮自选股自动同步，返回本次加入/删除的股票代码。
   * 本轮 stocks 为空时不执行任何增删。
   */
  sync(stocks: any[]): AutoFavoriteSyncResult {
    const result: AutoFavoriteSyncResult = { added: [], removed: [] }
    if (!Array.isArray(stocks) || stocks.length === 0) return result

    const ops = this.resolveOps()
    if (!ops) {
      console.warn('[AutoFavoriteSyncService] favorite store 不可用，跳过自选股自动同步')
      return result
    }

    const normalize = this.getNormalizeCode()
    const stockByCode = new Map<string, any>()
    for (const stock of stocks) {
      const code = normalize(stock?.code)
      if (code) stockByCode.set(code, stock)
    }

    // 1. 加入：本轮热榜中金叉 + 共振向上的股票
    for (const stock of stocks) {
      const code = normalize(stock?.code)
      if (!code || !this.shouldAutoAdd(stock)) continue
      if (ops.isFavorite(code)) continue
      if (ops.addAutoFavorite(code)) result.added.push(code)
    }

    // 2. 删除：auto 自选中死叉、生命周期降温/反转，或已退出热榜股票池
    for (const fav of ops.listAutoFavorites()) {
      const code = normalize(fav?.code)
      if (!code) continue
      const stock = stockByCode.get(code)
      const shouldRemove =
        !stock || this.getMacdCross(stock) === 'death' || this.shouldAutoRemoveLifecycle(stock)
      if (!shouldRemove) continue
      if (ops.removeAutoFavorite(code)) result.removed.push(code)
    }

    return result
  }
}

export const autoFavoriteSyncService = new AutoFavoriteSyncService()
