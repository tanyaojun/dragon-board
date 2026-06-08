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
  CandidateRuleEvidence,
  CandidateSavedAnalysis,
  CandidateStatus,
  CandidateStockLike,
  CandidateStructuredCondition,
  CandidateStructuredRisk,
  CandidateStructuredThesis,
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
  statusOverride?: CandidateStatus
  signalsSnapshotPatch?: Record<string, any>
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
const BREAKDOWN_LABELS: Record<keyof CandidateSavedAnalysis['scoreBreakdown'], string> = {
  rankTrend: 'RankTrend',
  theme: '题材',
  dragon: '龙头/地位',
  sentiment: '情绪',
  moneyFlow: '资金流',
}

function normalizeCode(code: unknown): string {
  const digits = String(code || '').replace(/\D/g, '')
  return digits ? digits.padStart(6, '0').slice(-6) : ''
}

function toSafeNumber(value: unknown, fallback = 0): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
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
    entryPrice: toSafeNumber(raw?.entryPrice ?? raw?.entry_price),
    entryTime: String(raw?.entryTime || raw?.entry_time || ''),
    exitPrice: toSafeNumber(raw?.exitPrice ?? raw?.exit_price),
    exitTime: String(raw?.exitTime || raw?.exit_time || ''),
    stopLossPrice: toSafeNumber(raw?.stopLossPrice ?? raw?.stop_loss_price),
    takeProfitPrice: toSafeNumber(raw?.takeProfitPrice ?? raw?.take_profit_price),
    positionPct: toSafeNumber(raw?.positionPct ?? raw?.position_pct),
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
    score: toSafeNumber(analysis.score),
    grade: (analysis.grade || '-') as CandidateSavedAnalysis['grade'],
    suggestedStatus: (analysis.suggestedStatus || '') as CandidateSavedAnalysis['suggestedStatus'],
    riskWarnings: Array.isArray(analysis.riskWarnings)
      ? analysis.riskWarnings.map((item: unknown) => String(item))
      : [],
    strengths: Array.isArray(analysis.strengths) ? analysis.strengths.map((item: unknown) => String(item)) : [],
    weaknesses: Array.isArray(analysis.weaknesses) ? analysis.weaknesses.map((item: unknown) => String(item)) : [],
    evidence: normalizeEvidenceList(analysis.evidence),
    penalties: normalizeEvidenceList(analysis.penalties),
    structuredThesis: normalizeStructuredThesis(analysis.structuredThesis),
    structuredRisks: normalizeStructuredRisks(analysis.structuredRisks),
    scoreBreakdown: {
      rankTrend: toSafeNumber(analysis.scoreBreakdown?.rankTrend),
      theme: toSafeNumber(analysis.scoreBreakdown?.theme),
      dragon: toSafeNumber(analysis.scoreBreakdown?.dragon),
      sentiment: toSafeNumber(analysis.scoreBreakdown?.sentiment),
      moneyFlow: toSafeNumber(analysis.scoreBreakdown?.moneyFlow),
    },
    generatedAt: toSafeNumber(analysis.generatedAt) || undefined,
  }
}

function normalizeEvidenceList(value: unknown): CandidateRuleEvidence[] {
  if (!Array.isArray(value)) return []
  return value.map((item: any) => ({
    dimension: String(item?.dimension || 'rankTrend') as CandidateRuleEvidence['dimension'],
    kind: String(item?.kind || 'neutral') as CandidateRuleEvidence['kind'],
    title: String(item?.title || ''),
    detail: String(item?.detail || ''),
    scoreImpact: toSafeNumber(item?.scoreImpact),
    dataQuality: String(item?.dataQuality || 'ok') as CandidateRuleEvidence['dataQuality'],
    source: item?.source ? String(item.source) : undefined,
  }))
}

function normalizeConditionList(value: unknown): CandidateStructuredCondition[] {
  if (!Array.isArray(value)) return []
  return value.map((item: any) => ({
    id: String(item?.id || ''),
    label: String(item?.label || ''),
    dimension: String(item?.dimension || 'rankTrend') as CandidateStructuredCondition['dimension'],
    status: String(item?.status || 'unknown') as CandidateStructuredCondition['status'],
    description: String(item?.description || ''),
  }))
}

function normalizeStructuredThesis(value: any): CandidateStructuredThesis {
  return {
    triggerConditions: normalizeConditionList(value?.triggerConditions),
    entryPrerequisites: normalizeConditionList(value?.entryPrerequisites),
    invalidationConditions: normalizeConditionList(value?.invalidationConditions),
  }
}

function normalizeStructuredRisks(value: unknown): CandidateStructuredRisk[] {
  if (!Array.isArray(value)) return []
  return value.map((item: any) => ({
    code: String(item?.code || ''),
    level: String(item?.level || 'info') as CandidateStructuredRisk['level'],
    dimension: String(item?.dimension || 'dataQuality') as CandidateStructuredRisk['dimension'],
    message: String(item?.message || ''),
    reason: String(item?.reason || ''),
  }))
}

function formatDimensionChange(label: string, action: '改善' | '走弱', points: number): string {
  const separator = /^[A-Za-z]/.test(label) ? ' ' : ''
  return `${label}${separator}${action} ${points} 分`
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

  const dimensions = Object.keys(BREAKDOWN_LABELS) as Array<keyof CandidateSavedAnalysis['scoreBreakdown']>
  for (const dimension of dimensions) {
    const delta = current.scoreBreakdown[dimension] - saved.scoreBreakdown[dimension]
    if (delta >= 5) {
      stateReasons.push(formatDimensionChange(BREAKDOWN_LABELS[dimension], '改善', delta))
    } else if (delta <= -5) {
      stateReasons.push(formatDimensionChange(BREAKDOWN_LABELS[dimension], '走弱', Math.abs(delta)))
    }
  }

  const savedRiskByCode = new Map(saved.structuredRisks.map((item) => [item.code, item]))
  const currentRiskByCode = new Map(current.structuredRisks.map((item) => [item.code, item]))
  const newRisks = current.structuredRisks.filter(
    (item) => item.code && !savedRiskByCode.has(item.code) && (item.level === 'warning' || item.level === 'danger'),
  )
  const removedRisks = saved.structuredRisks.filter((item) => item.code && !currentRiskByCode.has(item.code))
  for (const item of newRisks) {
    stateReasons.push(`新增风险：${item.message}`)
  }
  for (const item of removedRisks) {
    stateReasons.push(`风险解除：${item.message}`)
  }

  const missingEvidence = current.evidence.filter((item) => item.kind === 'missing')
  if (missingEvidence.length) {
    stateReasons.push(`缺样本：${missingEvidence.map((item) => item.title).join('、')}`)
  }

  let stateLabel = '条件持平'
  if (
    newRisks.some((item) => item.level === 'danger') ||
    current.riskWarnings.some((risk) => risk.includes('D_EXIT_RISK') || risk.includes('退潮'))
  ) {
    stateLabel = '风险升高'
  } else if (scoreDelta >= 8) {
    stateLabel = '条件改善'
  } else if (scoreDelta <= -8 || current.riskWarnings.length > saved.riskWarnings.length) {
    stateLabel = '条件转弱'
  } else if (missingEvidence.length) {
    stateLabel = '样本不足'
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
    const search = new URLSearchParams({
      limit: String(params.limit || 100),
      trade_type: 'thesis',
    })
    if (params.status) search.set('status', params.status)
    if (params.stockCode) search.set('stock_code', normalizeCode(params.stockCode))
    const data = await this.api.get(`/api/journal/entries?${search.toString()}`, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return Array.isArray(data?.entries)
      ? data.entries.map(normalizeEntry).filter((entry: CandidateJournalEntry) => entry.tradeType === 'thesis')
      : []
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
    const payload = this.buildCreatePayload(context.stock, analysis, options)
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
      entry_price: update.entryPrice,
      entry_time: update.entryTime,
      exit_price: update.exitPrice,
      exit_time: update.exitTime,
      stop_loss_price: update.stopLossPrice,
      take_profit_price: update.takeProfitPrice,
      position_pct: update.positionPct,
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

  async deleteCandidate(entry: CandidateJournalEntry): Promise<void> {
    if (entry.tradeType !== 'thesis') {
      throw new Error('仅允许删除候选池记录')
    }
    await this.api.delete(`/api/journal/entries/${entry.id}`, {
      context: 'quant-board',
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
  }

  addCandidateToFavorites(entry: CandidateJournalEntry): boolean {
    const stockCode = normalizeCode(entry.stockCode)
    if (!stockCode) return false
    return this.addFavorite ? this.addFavorite(stockCode) : useFavoriteStore().addToFavorites(stockCode)
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

  private buildCreatePayload(
    stock: CandidateStockLike,
    analysis: CandidateAnalysisResult,
    options: AddCandidateOptions,
  ) {
    const signalsSnapshot = {
      ...analysis.signalsSnapshot,
      ...(options.signalsSnapshotPatch || {}),
    }

    return {
      stock_code: normalizeCode(stock.code),
      stock_name: stock.name || normalizeCode(stock.code),
      direction: 'buy',
      trade_type: 'thesis',
      price: Number(stock.price || 0),
      volume: 0,
      signals_snapshot: signalsSnapshot,
      notes: '',
      status: options.statusOverride || analysis.suggestedStatus,
      market_phase: String(signalsSnapshot?.sentiment?.phaseName || ''),
      theme_role: String(signalsSnapshot?.theme?.exposures?.[0]?.role || ''),
      stock_role: String(signalsSnapshot?.dragon?.primaryRole || ''),
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
      review_notes: options.source ? `[自动入池] ${options.source}` : '',
      review_tags: analysis.tags,
    }
  }
}

export const candidateJournalService = new CandidateJournalService()
