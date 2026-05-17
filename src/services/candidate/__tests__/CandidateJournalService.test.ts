import { describe, expect, it, vi } from 'vitest'
import { CandidateJournalService } from '../CandidateJournalService'
import type { CandidateAnalysisResult, CandidateJournalEntry, CandidateStockLike } from '../types'

const stock: CandidateStockLike = {
  code: '600584',
  name: '长电科技',
  zlje: 10,
}

const analysis: CandidateAnalysisResult = {
  score: 82,
  grade: 'A',
  suggestedStatus: 'candidate',
  entryReason: 'RankTrend A_MAIN，题材先进封装共振',
  tradeHypothesis: '未来 3-5 天持续跟踪',
  entryPrerequisites: '排名维持前排',
  invalidationRules: 'RankTrend 降为 D_EXIT_RISK',
  riskWarnings: [],
  strengths: ['RankTrend A_MAIN'],
  weaknesses: [],
  tags: ['A', 'A_MAIN', '先进封装'],
  scoreBreakdown: {
    rankTrend: 30,
    theme: 18,
    dragon: 20,
    sentiment: 10,
    moneyFlow: 4,
  },
  signalsSnapshot: {
    candidateAnalysis: {
      version: 'candidate-rules-v1',
      score: 82,
      grade: 'A',
    },
  },
}

const existingCandidate: CandidateJournalEntry = {
  id: 'tj_existing',
  stockCode: '600584',
  stockName: '长电科技',
  status: 'observe',
  tradeType: 'thesis',
  entryReason: '已有候选',
  tradeHypothesis: '',
  entryPrerequisites: '',
  invalidationRules: '',
  humanDecision: 'watch',
  skipReason: '',
  reviewOutcome: 'pending',
  modelResult: 'unknown',
  executionResult: 'unknown',
  reviewNotes: '',
  reviewTags: [],
  signalsSnapshot: {},
  createdAt: '',
  updatedAt: '',
}

function createService() {
  const api = {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  }
  const analyze = vi.fn(() => analysis)
  const addToFavorites = vi.fn(() => true)
  const service = new CandidateJournalService({
    api,
    analyze,
    addToFavorites,
    now: () => 1778992800000,
  })
  return { service, api, analyze, addToFavorites }
}

describe('CandidateJournalService', () => {
  it('creates a candidate journal entry from a stock and analysis result', async () => {
    const { service, api, analyze, addToFavorites } = createService()
    api.get.mockResolvedValue({ entries: [], total: 0 })
    api.post.mockResolvedValue({
      id: 'tj_1',
      stockCode: '600584',
      stockName: '长电科技',
      status: 'candidate',
      tradeType: 'thesis',
      entryReason: analysis.entryReason,
      tradeHypothesis: analysis.tradeHypothesis,
      entryPrerequisites: analysis.entryPrerequisites,
      invalidationRules: analysis.invalidationRules,
      humanDecision: 'watch',
      reviewOutcome: 'pending',
      modelResult: 'unknown',
      executionResult: 'unknown',
      reviewTags: analysis.tags,
      signalsSnapshot: analysis.signalsSnapshot,
      createdAt: '2026-05-17T10:00:00+08:00',
      updatedAt: '2026-05-17T10:00:00+08:00',
    })

    const result = await service.addCandidateFromStock(stock, { addToFavorites: true })

    expect(result.created).toBe(true)
    expect(result.entry?.id).toBe('tj_1')
    expect(analyze).toHaveBeenCalledWith(expect.objectContaining({ stock }))
    expect(addToFavorites).toHaveBeenCalledWith('600584')
    expect(api.post).toHaveBeenCalledWith(
      '/api/journal/entries',
      expect.objectContaining({
        stock_code: '600584',
        stock_name: '长电科技',
        status: 'candidate',
        trade_type: 'thesis',
        entry_reason: analysis.entryReason,
        trade_hypothesis: analysis.tradeHypothesis,
        entry_prerequisites: analysis.entryPrerequisites,
        invalidation_rules: analysis.invalidationRules,
        review_tags: analysis.tags,
        signals_snapshot: analysis.signalsSnapshot,
      }),
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })

  it('returns an existing open candidate instead of creating duplicates', async () => {
    const { service, api, analyze } = createService()
    api.get.mockResolvedValue({
      entries: [existingCandidate],
      total: 1,
    })

    const result = await service.addCandidateFromStock(stock)

    expect(result.created).toBe(false)
    expect(result.entry?.id).toBe('tj_existing')
    expect(api.post).not.toHaveBeenCalled()
    expect(analyze).not.toHaveBeenCalled()
  })

  it('exposes the current open candidate for a stock code so UI can avoid duplicate add actions', async () => {
    const { service, api } = createService()
    api.get.mockResolvedValue({ entries: [existingCandidate], total: 1 })

    const result = await service.getOpenCandidateForStock('sh600584')

    expect(result?.id).toBe('tj_existing')
    expect(api.get).toHaveBeenCalledWith(
      '/api/journal/entries?limit=100&stock_code=600584',
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })

  it('reanalyzes an existing candidate from the latest stock context without mutating the saved snapshot', async () => {
    const { service, analyze } = createService()

    const result = service.reanalyzeCandidate({
      ...existingCandidate,
      signalsSnapshot: {
        candidateAnalysis: {
          score: 43,
          grade: 'D',
        },
      },
    })

    expect(result.entry.id).toBe('tj_existing')
    expect(result.savedAnalysis.score).toBe(43)
    expect(result.currentAnalysis.score).toBe(82)
    expect(result.scoreDelta).toBe(39)
    expect(result.stateLabel).toBe('条件改善')
    expect(analyze).toHaveBeenCalledWith(
      expect.objectContaining({
        stock: expect.objectContaining({ code: '600584', name: '长电科技' }),
      }),
    )
  })

  it('rejects stocks without a valid code before querying or creating candidates', async () => {
    const { service, api, analyze } = createService()

    await expect(service.addCandidateFromStock({ code: '无效代码', name: '无效样本' })).rejects.toThrow(
      '候选股代码无效',
    )

    expect(api.get).not.toHaveBeenCalled()
    expect(api.post).not.toHaveBeenCalled()
    expect(analyze).not.toHaveBeenCalled()
  })

  it('updates lightweight thesis fields without replacing the saved analysis snapshot', async () => {
    const { service, api } = createService()
    api.put.mockResolvedValue({
      ...existingCandidate,
      entryReason: '人工修正后的入池理由',
      tradeHypothesis: '人工修正后的交易假设',
      entryPrerequisites: '人工修正后的买入前提',
      invalidationRules: '人工修正后的失效条件',
      humanDecision: 'skip',
      skipReason: '条件未确认',
    })

    const result = await service.updateCandidateThesis('tj_existing', {
      entryReason: '人工修正后的入池理由',
      tradeHypothesis: '人工修正后的交易假设',
      entryPrerequisites: '人工修正后的买入前提',
      invalidationRules: '人工修正后的失效条件',
      humanDecision: 'skip',
      skipReason: '条件未确认',
    })

    expect(result.tradeHypothesis).toBe('人工修正后的交易假设')
    expect(api.put).toHaveBeenCalledWith(
      '/api/journal/entries/tj_existing',
      {
        entry_reason: '人工修正后的入池理由',
        trade_hypothesis: '人工修正后的交易假设',
        entry_prerequisites: '人工修正后的买入前提',
        invalidation_rules: '人工修正后的失效条件',
        human_decision: 'skip',
        skip_reason: '条件未确认',
      },
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })

  it('writes the current rule analysis back to the candidate snapshot on demand', async () => {
    const { service, api, analyze } = createService()
    api.put.mockResolvedValue({
      ...existingCandidate,
      reviewTags: analysis.tags,
      signalsSnapshot: {
        quote: { code: '600584' },
        ...analysis.signalsSnapshot,
      },
    })

    const result = await service.writeBackCurrentAnalysis({
      ...existingCandidate,
      signalsSnapshot: { quote: { code: '600584' } },
    })

    expect(result.reviewTags).toEqual(analysis.tags)
    expect(analyze).toHaveBeenCalled()
    expect(api.put).toHaveBeenCalledWith(
      '/api/journal/entries/tj_existing',
      expect.objectContaining({
        review_tags: analysis.tags,
        signals_snapshot: expect.objectContaining({
          quote: { code: '600584' },
          candidateAnalysis: analysis.signalsSnapshot.candidateAnalysis,
        }),
      }),
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })

  it('saves review outcome, model result and execution result as a reviewed candidate', async () => {
    const { service, api } = createService()
    api.put.mockResolvedValue({
      ...existingCandidate,
      status: 'reviewed',
      reviewOutcome: 'success',
      modelResult: 'correct',
      executionResult: 'missed',
      reviewNotes: '模型判断正确，但盘中没有执行。',
    })

    const result = await service.saveCandidateReview('tj_existing', {
      reviewOutcome: 'success',
      modelResult: 'correct',
      executionResult: 'missed',
      reviewNotes: '模型判断正确，但盘中没有执行。',
    })

    expect(result.status).toBe('reviewed')
    expect(result.reviewOutcome).toBe('success')
    expect(api.put).toHaveBeenCalledWith(
      '/api/journal/entries/tj_existing',
      {
        status: 'reviewed',
        review_outcome: 'success',
        model_result: 'correct',
        execution_result: 'missed',
        review_notes: '模型判断正确，但盘中没有执行。',
      },
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })

  it('keeps a pending review in its current lifecycle status when saving review notes', async () => {
    const { service, api } = createService()
    api.put.mockResolvedValue({
      ...existingCandidate,
      reviewOutcome: 'pending',
      modelResult: 'unknown',
      executionResult: 'unknown',
      reviewNotes: '先记录观察，尚未复盘。',
    })

    const result = await service.saveCandidateReview('tj_existing', {
      reviewOutcome: 'pending',
      modelResult: 'unknown',
      executionResult: 'unknown',
      reviewNotes: '先记录观察，尚未复盘。',
    })

    expect(result.status).toBe('observe')
    expect(api.put).toHaveBeenCalledWith(
      '/api/journal/entries/tj_existing',
      {
        review_outcome: 'pending',
        model_result: 'unknown',
        execution_result: 'unknown',
        review_notes: '先记录观察，尚未复盘。',
      },
      expect.objectContaining({ context: 'quant-board', throwOnHttpError: true }),
    )
  })
})
