import { dataLayer } from '@/services/DataLayer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import { getRankTrendAnalysis } from '@/services/rankTrend/compat'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { analyzeCandidateStock } from './CandidateAnalysisService'
import type {
  CandidateAnalysisContext,
  CandidateAnalysisResult,
  CandidateDiscoveryRecommendation,
  CandidateDiscoveryResult,
  CandidateJournalEntry,
  CandidateStockLike,
} from './types'

interface CandidateDiscoveryOptions {
  stocks?: CandidateStockLike[]
  existingCandidates?: CandidateJournalEntry[]
  limit?: number
  minScore?: number
  cooldownMs?: number
  force?: boolean
}

interface CandidateDiscoveryServiceDeps {
  analyze?: (context: CandidateAnalysisContext) => CandidateAnalysisResult
  buildContext?: (stock: CandidateStockLike, allStocks: CandidateStockLike[]) => CandidateAnalysisContext
  now?: () => number
}

const DEFAULT_LIMIT = 6
const DEFAULT_MIN_SCORE = 55
const DEFAULT_COOLDOWN_MS = 60_000
const OPEN_STATUSES = new Set(['observe', 'candidate', 'triggered', 'tracking'])

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function expectedTrackingDays(analysis: CandidateAnalysisResult): number {
  if (analysis.grade === 'A') return 5
  if (analysis.grade === 'B') return 4
  return 3
}

function buildExistingCandidateMap(candidates: CandidateJournalEntry[] = []) {
  return new Map(
    candidates
      .filter((entry) => OPEN_STATUSES.has(entry.status))
      .map((entry) => [normalizeCode(entry.stockCode), entry]),
  )
}

function duplicateFor(
  stockCode: string,
  existingByCode: Map<string, CandidateJournalEntry>,
): CandidateDiscoveryRecommendation['duplicate'] {
  const existing = existingByCode.get(normalizeCode(stockCode))
  return existing
    ? {
        isOpen: true,
        entryId: existing.id,
        status: existing.status,
      }
    : { isOpen: false }
}

function withDuplicateMarkers(
  result: CandidateDiscoveryResult,
  existingCandidates: CandidateJournalEntry[] = [],
): CandidateDiscoveryResult {
  const existingByCode = buildExistingCandidateMap(existingCandidates)
  return {
    ...result,
    recommendations: result.recommendations.map((item) => ({
      ...item,
      duplicate: duplicateFor(item.stock.code, existingByCode),
    })),
  }
}

function buildCacheKey(stocks: CandidateStockLike[], options: CandidateDiscoveryOptions): string {
  return JSON.stringify({
    codes: stocks.map((stock) => normalizeCode(stock.code)).sort(),
    limit: options.limit ?? DEFAULT_LIMIT,
    minScore: options.minScore ?? DEFAULT_MIN_SCORE,
  })
}

function compactReasons(analysis: CandidateAnalysisResult): string[] {
  return [
    ...analysis.strengths,
    ...analysis.evidence
      .filter((item) => item.kind === 'positive')
      .map((item) => `${item.title}：${item.detail}`),
    analysis.entryReason,
  ]
    .filter(Boolean)
    .slice(0, 3)
}

function findDragonRecord(stockCode: string): Record<string, any> | null {
  const review = dragonReviewService.getLatestReview()
  if (!review) return null
  const groups = [
    review.trueLeaders || [],
    review.heightBoard || [],
    review.attentionBoard || [],
  ] as Array<Array<Record<string, any>>>
  for (const group of groups) {
    const record = group.find((item) => normalizeCode(item.code) === stockCode)
    if (record) return record
  }
  const marketCore = review.marketCore as Record<string, any> | undefined
  return marketCore && normalizeCode(marketCore.code) === stockCode ? marketCore : null
}

export class CandidateDiscoveryService {
  private analyze: (context: CandidateAnalysisContext) => CandidateAnalysisResult
  private buildContextOverride?: (
    stock: CandidateStockLike,
    allStocks: CandidateStockLike[],
  ) => CandidateAnalysisContext
  private now: () => number
  private lastResult: CandidateDiscoveryResult | null = null
  private lastGeneratedAt = 0
  private lastCacheKey = ''

  constructor(deps: CandidateDiscoveryServiceDeps = {}) {
    this.analyze = deps.analyze || analyzeCandidateStock
    this.buildContextOverride = deps.buildContext
    this.now = deps.now || Date.now
  }

  discover(options: CandidateDiscoveryOptions = {}): CandidateDiscoveryResult {
    const now = this.now()
    const cooldownMs = options.cooldownMs ?? DEFAULT_COOLDOWN_MS

    const stocks = (options.stocks || (dataLayer.getStocks() as CandidateStockLike[])).filter((stock) =>
      Boolean(normalizeCode(stock.code)),
    )
    const cacheKey = buildCacheKey(stocks, options)
    if (!stocks.length) {
      const result = {
        generatedAt: now,
        totalAnalyzed: 0,
        recommendations: [],
        skippedReason: 'empty' as const,
      }
      this.lastResult = result
      this.lastGeneratedAt = now
      this.lastCacheKey = cacheKey
      return result
    }

    if (
      !options.force &&
      this.lastResult &&
      this.lastCacheKey === cacheKey &&
      now - this.lastGeneratedAt < cooldownMs
    ) {
      const result = options.existingCandidates
        ? withDuplicateMarkers(this.lastResult, options.existingCandidates)
        : this.lastResult
      return {
        ...result,
        skippedReason: 'cooldown',
      }
    }

    const existingByCode = buildExistingCandidateMap(options.existingCandidates)
    const minScore = options.minScore ?? DEFAULT_MIN_SCORE
    const limit = options.limit ?? DEFAULT_LIMIT

    const recommendations = stocks
      .map((stock) => {
        const normalizedStock = { ...stock, code: normalizeCode(stock.code) }
        const analysis = this.analyze(this.buildContext(normalizedStock, stocks))
        const existing = existingByCode.get(normalizedStock.code)
        return {
          rank: 0,
          stock: normalizedStock,
          analysis,
          score: analysis.score,
          grade: analysis.grade,
          suggestedStatus: analysis.suggestedStatus,
          reasons: compactReasons(analysis),
          risks: analysis.riskWarnings,
          expectedTrackingDays: expectedTrackingDays(analysis),
          duplicate: duplicateFor(normalizedStock.code, existingByCode),
        } satisfies CandidateDiscoveryRecommendation
      })
      .filter((item) => item.score >= minScore)
      .sort((left, right) => {
        const scoreDelta = right.score - left.score
        if (scoreDelta !== 0) return scoreDelta
        return left.stock.code.localeCompare(right.stock.code)
      })
      .slice(0, limit)
      .map((item, index) => ({ ...item, rank: index + 1 }))

    const result = {
      generatedAt: now,
      totalAnalyzed: stocks.length,
      recommendations,
    }
    this.lastResult = result
    this.lastGeneratedAt = now
    this.lastCacheKey = cacheKey
    return result
  }

  private buildContext(stock: CandidateStockLike, allStocks: CandidateStockLike[]): CandidateAnalysisContext {
    if (this.buildContextOverride) return this.buildContextOverride(stock, allStocks)
    const liveStock = dataLayer.getStock(stock.code) as CandidateStockLike | null
    const sourceStock = { ...(liveStock || {}), ...stock }
    return {
      stock: sourceStock,
      allStocks,
      rankTrend: getRankTrendAnalysis(sourceStock),
      themeExposures: themeFacade.getStockExposures(stock.code) as any,
      rotationSummary: themeFacade.getRotationSummary() as any,
      dragonRecord: findDragonRecord(stock.code),
      sentiment: dragonBreathAnalyzer.getMarketSentiment() as any,
      now: this.now(),
    }
  }
}

export const candidateDiscoveryService = new CandidateDiscoveryService()
