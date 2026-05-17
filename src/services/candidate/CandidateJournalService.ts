import { apiService } from '@/services/apiService'
import { dataLayer } from '@/services/DataLayer'
import { dragonBreathAnalyzer } from '@/services/DragonBreathAnalyzer'
import { dragonReviewService } from '@/services/dragon/DragonReviewService'
import { getRankTrendAnalysis } from '@/services/rankTrend/compat'
import { themeFacade } from '@/services/theme/ThemeFacade'
import { useFavoriteStore } from '@/stores/favorite'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'
import { analyzeCandidateStock } from './CandidateAnalysisService'
import type {
  CandidateAnalysisContext,
  CandidateAnalysisResult,
  CandidateJournalEntry,
  CandidateReviewUpdate,
  CandidateSavedAnalysis,
  CandidateStatus,
  CandidateStockLike,
  CandidateThesisUpdate,
  CandidateWorkbenchReview,
} from './types'

interface CandidateApi {
  get<T = any>(url: string, options?: any): Promise<T>
  post<T = any>(url: string, data?: any, options?: any): Promise<T>
  put<T = any>(url: string, data?: any, options?: any): Promise<T>
  delete<T = any>(url: string, options?: any): Promise<T>
}

interface AddCandidateOptions {
  addToFavorites?: boolean
  source?: string
}

interface AddCandidateResult {
  created: boolean
  entry: CandidateJournalEntry | null
  analysis?: CandidateAnalysisResult
}

interface CandidateJournalServiceDeps {
  api?: CandidateApi
  analyze?: (context: CandidateAnalysisContext) => CandidateAnalysisResult
  addToFavorites?: (code: string) => boolean
  now?: () => number
}

const OPEN_STATUSES: CandidateStatus[] = ['observe', 'candidate', 'triggered', 'tracking']
function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function normalizeEntry(raw: any): CandidateJournalEntry {
  return {
    id: String(raw?.id || ''),
    stockCode: String(raw?.stockCode || raw?.stock_code || ''),
    stockName: String(raw?.stockName || raw?.stock_name || ''),
    status: String(raw?.status || 'observe') as CandidateStatus,
    tradeType: String(raw?.tradeType || raw?.trade_type || 'thesis'),
    entryReason: String(raw?.entryReason || raw?.entry_reason || ''),
    tradeHypothesis: String(raw?.tradeHypothesis || raw?.trade_hypothesis || ''),
    entryPrerequisites: String(raw?.entryPrerequisites || raw?.entry_prerequisites || ''),
    invalidationRules: String(raw?.invalidationRules || raw?.invalidation_rules || ''),
    humanDecision: String(raw?.humanDecision || raw?.human_decision || 'watch'),
    skipReason: String(raw?.skipReason || raw?.skip_reason || ''),
    reviewOutcome: String(raw?.reviewOutcome || raw?.review_outcome || 'pending'),
    modelResult: String(raw?.modelResult || raw?.model_result || 'unknown'),
    executionResult: String(raw?.executionResult || raw?.execution_result || 'unknown'),
    reviewNotes: String(raw?.reviewNotes || raw?.review_notes || ''),
    reviewTags: Array.isArray(raw?.reviewTags || raw?.review_tags)
      ? (raw.reviewTags || raw.review_tags).map((item: unknown) => String(item))
      : [],
    signalsSnapshot: (raw?.signalsSnapshot || raw?.signals_snapshot || null) as Record<string, any> | null,
    createdAt: String(raw?.createdAt || raw?.created_at || ''),
    updatedAt: String(raw?.updatedAt || raw?.updated_at || ''),
  }
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

function normalizeSavedAnalysis(snapshot: Record<string, any> | null | undefined): CandidateSavedAnalysis {
  const analysis = snapshot?.candidateAnalysis || {}
  return {
    score: Number(analysis.score || 0),
    grade: (analysis.grade || '-') as CandidateSavedAnalysis['grade'],
    suggestedStatus: (analysis.suggestedStatus || '') as CandidateSavedAnalysis['suggestedStatus'],
    riskWarnings: Array.isArray(analysis.riskWarnings)
      ? analysis.riskWarnings.map((item: unknown) => String(item))
      : [],
    strengths: Array.isArray(analysis.strengths) ? analysis.strengths.map((item: unknown) => String(item)) : [],
    weaknesses: Array.isArray(analysis.weaknesses) ? analysis.weaknesses.map((item: unknown) => String(item)) : [],
    scoreBreakdown: {
      rankTrend: Number(analysis.scoreBreakdown?.rankTrend || 0),
      theme: Number(analysis.scoreBreakdown?.theme || 0),
      dragon: Number(analysis.scoreBreakdown?.dragon || 0),
      sentiment: Number(analysis.scoreBreakdown?.sentiment || 0),
      moneyFlow: Number(analysis.scoreBreakdown?.moneyFlow || 0),
    },
    generatedAt: Number(analysis.generatedAt || 0) || undefined,
  }
}

function compareAnalysis(saved: CandidateSavedAnalysis, current: CandidateAnalysisResult) {
  const scoreDelta = current.score - saved.score
  const stateReasons: string[] = []

  if (scoreDelta >= 10) stateReasons.push(`当前评分较入池提升 ${scoreDelta} 分`)
  if (scoreDelta <= -10) stateReasons.push(`当前评分较入池下降 ${Math.abs(scoreDelta)} 分`)
  if (current.riskWarnings.length > saved.riskWarnings.length) stateReasons.push('当前风险提示增加')
  if (current.suggestedStatus !== saved.suggestedStatus) {
    stateReasons.push(`建议状态从 ${saved.suggestedStatus || '未设置'} 变为 ${current.suggestedStatus}`)
  }

  let stateLabel = '条件持平'
  if (current.riskWarnings.some((risk) => risk.includes('D_EXIT_RISK') || risk.includes('退潮'))) {
    stateLabel = '风险升高'
  } else if (scoreDelta >= 8) {
    stateLabel = '条件改善'
  } else if (scoreDelta <= -8 || current.riskWarnings.length > saved.riskWarnings.length) {
    stateLabel = '条件转弱'
  }

  if (!stateReasons.length) stateReasons.push('当前信号与入池快照差异不大')
  return { scoreDelta, stateLabel, stateReasons }
}

export class CandidateJournalService {
  private api: CandidateApi
  private analyze: (context: CandidateAnalysisContext) => CandidateAnalysisResult
  private addFavorite?: (code: string) => boolean
  private now: () => number

  constructor(deps: CandidateJournalServiceDeps = {}) {
    this.api = deps.api || apiService
    this.analyze = deps.analyze || analyzeCandidateStock
    this.addFavorite = deps.addToFavorites
    this.now = deps.now || Date.now
  }

  async listCandidates(params: { status?: string; stockCode?: string; limit?: number } = {}): Promise<CandidateJournalEntry[]> {
    const search = new URLSearchParams({ limit: String(params.limit || 100) })
    if (params.status) search.set('status', params.status)
    if (params.stockCode) search.set('stock_code', normalizeCode(params.stockCode))
    const data = await this.api.get(`/api/journal/entries?${search.toString()}`, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return Array.isArray(data?.entries) ? data.entries.map(normalizeEntry) : []
  }

  async addCandidateFromStock(
    stock: CandidateStockLike,
    options: AddCandidateOptions = {},
  ): Promise<AddCandidateResult> {
    const stockCode = normalizeCode(stock.code)
    if (!stockCode) {
      throw new Error('候选股代码无效')
    }

    const existing = await this.findOpenCandidate(stockCode)
    if (existing) {
      return { created: false, entry: existing }
    }

    const context = this.buildAnalysisContext({ ...stock, code: stockCode })
    const analysis = this.analyze(context)
    const payload = this.buildCreatePayload(context.stock, analysis)
    const created = await this.api.post('/api/journal/entries', payload, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })

    if (options.addToFavorites) {
      this.addFavorite ? this.addFavorite(stockCode) : useFavoriteStore().addToFavorites(stockCode)
    }

    EventManager.emit(AppEvents.UI.TOAST, {
      message: `已加入候选池：${context.stock.name || stockCode} · ${analysis.grade}级 ${analysis.score}分`,
      duration: 1800,
      type: 'success',
    })

    return { created: true, entry: normalizeEntry(created), analysis }
  }

  async updateCandidateStatus(id: string, status: CandidateStatus): Promise<CandidateJournalEntry> {
    const updated = await this.api.put(`/api/journal/entries/${id}`, { status }, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return normalizeEntry(updated)
  }

  async updateCandidateThesis(id: string, update: CandidateThesisUpdate): Promise<CandidateJournalEntry> {
    const updated = await this.api.put(`/api/journal/entries/${id}`, {
      entry_reason: update.entryReason,
      trade_hypothesis: update.tradeHypothesis,
      entry_prerequisites: update.entryPrerequisites,
      invalidation_rules: update.invalidationRules,
      human_decision: update.humanDecision,
      skip_reason: update.skipReason,
    }, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return normalizeEntry(updated)
  }

  async writeBackCurrentAnalysis(entry: CandidateJournalEntry): Promise<CandidateJournalEntry> {
    const current = this.reanalyzeCandidate(entry).currentAnalysis
    const updatedSnapshot = {
      ...(entry.signalsSnapshot || {}),
      ...current.signalsSnapshot,
    }
    const updated = await this.api.put(`/api/journal/entries/${entry.id}`, {
      signals_snapshot: updatedSnapshot,
      review_tags: current.tags,
    }, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return normalizeEntry(updated)
  }

  async saveCandidateReview(id: string, update: CandidateReviewUpdate): Promise<CandidateJournalEntry> {
    const payload: Record<string, unknown> = {
      review_outcome: update.reviewOutcome,
      model_result: update.modelResult,
      execution_result: update.executionResult,
      review_notes: update.reviewNotes,
    }
    if (update.reviewOutcome !== 'pending') {
      payload.status = 'reviewed'
    }
    const updated = await this.api.put(`/api/journal/entries/${id}`, {
      ...payload,
    }, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return normalizeEntry(updated)
  }

  async getOpenCandidateForStock(stockCode: string): Promise<CandidateJournalEntry | null> {
    const normalizedCode = normalizeCode(stockCode)
    if (!normalizedCode) return null
    return this.findOpenCandidate(normalizedCode)
  }

  reanalyzeCandidate(entry: CandidateJournalEntry): CandidateWorkbenchReview {
    const stockCode = normalizeCode(entry.stockCode)
    const stock = {
      ...(entry.signalsSnapshot?.quote || {}),
      ...(dataLayer.getStock(stockCode) || {}),
      code: stockCode,
      name: entry.stockName || entry.stockCode,
    } as CandidateStockLike
    const currentAnalysis = this.analyze(this.buildAnalysisContext(stock))
    const savedAnalysis = normalizeSavedAnalysis(entry.signalsSnapshot)
    const comparison = compareAnalysis(savedAnalysis, currentAnalysis)
    return {
      entry,
      savedAnalysis,
      currentAnalysis,
      ...comparison,
    }
  }

  private async findOpenCandidate(stockCode: string): Promise<CandidateJournalEntry | null> {
    const entries = await this.listCandidates({ stockCode, limit: 100 })
    return entries.find((entry) => OPEN_STATUSES.includes(entry.status)) || null
  }

  private buildAnalysisContext(stock: CandidateStockLike): CandidateAnalysisContext {
    const stockCode = normalizeCode(stock.code)
    const liveStock = dataLayer.getStock(stockCode) as CandidateStockLike | undefined
    const sourceStock = { ...(liveStock || {}), ...stock, code: stockCode }
    return {
      stock: sourceStock,
      allStocks: dataLayer.getStocks() as CandidateStockLike[],
      rankTrend: getRankTrendAnalysis(sourceStock),
      themeExposures: themeFacade.getStockExposures(stockCode) as any,
      rotationSummary: themeFacade.getRotationSummary() as any,
      dragonRecord: findDragonRecord(stockCode),
      sentiment: dragonBreathAnalyzer.getMarketSentiment() as any,
      now: this.now(),
    }
  }

  private buildCreatePayload(stock: CandidateStockLike, analysis: CandidateAnalysisResult) {
    return {
      stock_code: normalizeCode(stock.code),
      stock_name: stock.name || normalizeCode(stock.code),
      direction: 'buy',
      trade_type: 'thesis',
      price: Number(stock.price || 0),
      volume: 0,
      signals_snapshot: analysis.signalsSnapshot,
      notes: '',
      status: analysis.suggestedStatus,
      market_phase: String(analysis.signalsSnapshot?.sentiment?.phaseName || ''),
      theme_role: String(analysis.signalsSnapshot?.theme?.exposures?.[0]?.role || ''),
      stock_role: String(analysis.signalsSnapshot?.dragon?.primaryRole || ''),
      entry_reason: analysis.entryReason,
      trade_hypothesis: analysis.tradeHypothesis,
      entry_prerequisites: analysis.entryPrerequisites,
      invalidation_rules: analysis.invalidationRules,
      expected_holding_days: 3,
      human_decision: 'watch',
      skip_reason: '',
      review_outcome: 'pending',
      model_result: 'unknown',
      execution_result: 'unknown',
      review_notes: '',
      review_tags: analysis.tags,
    }
  }
}

export const candidateJournalService = new CandidateJournalService()
