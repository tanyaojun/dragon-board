import { describe, expect, it, vi } from 'vitest'
import { CandidateDiscoveryService } from '../CandidateDiscoveryService'
import type {
  CandidateAnalysisContext,
  CandidateAnalysisResult,
  CandidateJournalEntry,
  CandidateStockLike,
} from '../types'

function analysisFor(score: number, overrides: Partial<CandidateAnalysisResult> = {}): CandidateAnalysisResult {
  const grade = score >= 80 ? 'A' : score >= 65 ? 'B' : score >= 50 ? 'C' : 'D'
  return {
    score,
    grade,
    suggestedStatus: score >= 75 ? 'candidate' : 'observe',
    entryReason: `综合评分 ${score} 分，值得纳入候选观察。`,
    tradeHypothesis: '未来 3-5 天持续跟踪。',
    entryPrerequisites: '排名维持前排，资金不转弱。',
    invalidationRules: 'RankTrend 降为 D_EXIT_RISK。',
    riskWarnings: [],
    strengths: [`强度 ${score}`],
    weaknesses: [],
    evidence: [
      {
        dimension: 'rankTrend',
        kind: 'positive',
        title: `RankTrend ${score}`,
        detail: '排名趋势支持候选跟踪',
        scoreImpact: Math.min(score, 30),
        dataQuality: 'ok',
      },
    ],
    penalties: [],
    structuredThesis: {
      triggerConditions: [],
      entryPrerequisites: [],
      invalidationConditions: [],
    },
    structuredRisks: [],
    tags: [grade, 'A_MAIN', '先进封装'],
    scoreBreakdown: {
      rankTrend: 30,
      theme: 18,
      dragon: 15,
      sentiment: 10,
      moneyFlow: Math.max(0, score - 73),
    },
    signalsSnapshot: {
      quote: {},
      theme: { primaryTheme: '先进封装' },
      candidateAnalysis: { score, grade },
    },
    ...overrides,
  } as CandidateAnalysisResult
}

function existingCandidate(stockCode: string): CandidateJournalEntry {
  return {
    id: `tj_${stockCode}`,
    stockCode,
    stockName: stockCode,
    status: 'observe',
    tradeType: 'thesis',
    entryReason: '',
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
    signalsSnapshot: null,
    createdAt: '2026-05-17T10:00:00+08:00',
    updatedAt: '2026-05-17T10:00:00+08:00',
  }
}

describe('CandidateDiscoveryService', () => {
  it('builds ranked manual-confirm recommendations from quote stocks without writing journal entries', () => {
    const stocks: CandidateStockLike[] = [
      { code: '600584', name: '长电科技' },
      { code: '002407', name: '多氟多' },
      { code: '000001', name: '平安银行' },
    ]
    const scores: Record<string, CandidateAnalysisResult> = {
      '600584': analysisFor(82),
      '002407': analysisFor(74, {
        riskWarnings: ['RankTrend 进入拥挤区，避免把高热度误判为新买点'],
        structuredRisks: [
          {
            code: 'RANKTREND_CROWDED',
            level: 'warning',
            dimension: 'rankTrend',
            message: 'RankTrend 进入拥挤区，避免把高热度误判为新买点',
            reason: '候选分层为 C_CROWDED',
          },
        ],
      }),
      '000001': analysisFor(42),
    }
    const analyze = vi.fn((context: CandidateAnalysisContext) => scores[context.stock.code])
    const service = new CandidateDiscoveryService({
      analyze,
      buildContext: (stock) => ({ stock, allStocks: stocks }),
      now: () => 1778992800000,
    })

    const result = service.discover({
      stocks,
      existingCandidates: [existingCandidate('002407')],
      limit: 5,
      minScore: 60,
      force: true,
    })

    expect(result.skippedReason).toBeUndefined()
    expect(result.totalAnalyzed).toBe(3)
    expect(result.recommendations).toHaveLength(2)
    expect(result.recommendations.map((item) => item.stock.code)).toEqual(['600584', '002407'])
    expect(result.recommendations[0]).toMatchObject({
      rank: 1,
      score: 82,
      grade: 'A',
      expectedTrackingDays: 5,
      duplicate: { isOpen: false },
    })
    expect(result.recommendations[0].reasons[0]).toContain('强度 82')
    expect(result.recommendations[1].duplicate).toMatchObject({
      isOpen: true,
      entryId: 'tj_002407',
      status: 'observe',
    })
    expect(result.recommendations[1].risks[0]).toContain('拥挤')
    expect(analyze).toHaveBeenCalledTimes(3)
  })

  it('reuses the previous recommendation list during cooldown unless forced', () => {
    let now = 1778992800000
    const stocks: CandidateStockLike[] = [{ code: '600584', name: '长电科技' }]
    const analyze = vi.fn(() => analysisFor(82))
    const service = new CandidateDiscoveryService({
      analyze,
      buildContext: (stock) => ({ stock, allStocks: stocks }),
      now: () => now,
    })

    const first = service.discover({ stocks, cooldownMs: 60_000 })
    now += 30_000
    const second = service.discover({ stocks, cooldownMs: 60_000 })
    const forced = service.discover({ stocks, cooldownMs: 60_000, force: true })

    expect(first.recommendations).toHaveLength(1)
    expect(second.skippedReason).toBe('cooldown')
    expect(second.recommendations).toBe(first.recommendations)
    expect(forced.skippedReason).toBeUndefined()
    expect(analyze).toHaveBeenCalledTimes(2)
  })

  it('refreshes duplicate markers when existing candidates change during cooldown', () => {
    let now = 1778992800000
    const stocks: CandidateStockLike[] = [{ code: '600584', name: '长电科技' }]
    const analyze = vi.fn(() => analysisFor(82))
    const service = new CandidateDiscoveryService({
      analyze,
      buildContext: (stock) => ({ stock, allStocks: stocks }),
      now: () => now,
    })

    const first = service.discover({
      stocks,
      existingCandidates: [],
      cooldownMs: 60_000,
    })
    now += 30_000
    const second = service.discover({
      stocks,
      existingCandidates: [existingCandidate('600584')],
      cooldownMs: 60_000,
    })

    expect(first.recommendations[0].duplicate).toEqual({ isOpen: false })
    expect(second.skippedReason).toBe('cooldown')
    expect(second.recommendations[0].duplicate).toMatchObject({
      isOpen: true,
      entryId: 'tj_600584',
      status: 'observe',
    })
    expect(analyze).toHaveBeenCalledTimes(1)
  })

  it('does not reuse cooldown recommendations when quote universe or scoring options change', () => {
    let now = 1778992800000
    const firstStocks: CandidateStockLike[] = [
      { code: '600584', name: '长电科技' },
      { code: '002407', name: '多氟多' },
    ]
    const secondStocks: CandidateStockLike[] = [{ code: '601991', name: '大唐发电' }]
    const scores: Record<string, CandidateAnalysisResult> = {
      '600584': analysisFor(82),
      '002407': analysisFor(66),
      '601991': analysisFor(76),
    }
    const analyze = vi.fn((context: CandidateAnalysisContext) => scores[context.stock.code])
    const service = new CandidateDiscoveryService({
      analyze,
      buildContext: (stock, allStocks) => ({ stock, allStocks }),
      now: () => now,
    })

    const first = service.discover({
      stocks: firstStocks,
      minScore: 80,
      limit: 1,
      cooldownMs: 60_000,
    })
    now += 30_000
    const second = service.discover({
      stocks: secondStocks,
      minScore: 55,
      limit: 6,
      cooldownMs: 60_000,
    })

    expect(first.recommendations.map((item) => item.stock.code)).toEqual(['600584'])
    expect(second.skippedReason).toBeUndefined()
    expect(second.recommendations.map((item) => item.stock.code)).toEqual(['601991'])
    expect(analyze).toHaveBeenCalledTimes(3)
  })

  it('keeps empty quote universe classified as empty instead of cooldown', () => {
    let now = 1778992800000
    const analyze = vi.fn(() => analysisFor(82))
    const service = new CandidateDiscoveryService({
      analyze,
      buildContext: (stock, allStocks) => ({ stock, allStocks }),
      now: () => now,
    })

    const first = service.discover({ stocks: [], cooldownMs: 60_000 })
    now += 30_000
    const second = service.discover({ stocks: [], cooldownMs: 60_000 })

    expect(first.skippedReason).toBe('empty')
    expect(second.skippedReason).toBe('empty')
    expect(second.recommendations).toEqual([])
    expect(analyze).not.toHaveBeenCalled()
  })
})
