import { describe, expect, it, vi } from 'vitest'
import { CandidateJournalService } from '../CandidateJournalService'
import type { CandidateAnalysisResult, CandidateStockLike } from '../types'

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
      entries: [
        {
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
          reviewOutcome: 'pending',
          modelResult: 'unknown',
          executionResult: 'unknown',
          reviewTags: [],
          signalsSnapshot: {},
          createdAt: '',
          updatedAt: '',
        },
      ],
      total: 1,
    })

    const result = await service.addCandidateFromStock(stock)

    expect(result.created).toBe(false)
    expect(result.entry?.id).toBe('tj_existing')
    expect(api.post).not.toHaveBeenCalled()
    expect(analyze).not.toHaveBeenCalled()
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
})
