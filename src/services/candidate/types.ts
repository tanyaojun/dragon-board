export type CandidateGrade = 'A' | 'B' | 'C' | 'D'
export type CandidateStatus = 'observe' | 'candidate' | 'triggered' | 'tracking' | 'reviewed'

export type CandidateStockLike = {
  code: string
  name?: string
  zlje?: number
  zljzb?: number
  cddje?: number
  volumeRatio?: number
  turnoverRate?: number
  themes?: Array<Record<string, unknown>>
} & Record<string, any>

export interface CandidateThemeExposureLike {
  themeId?: string
  themeName?: string
  role?: string
  roleScore?: number
  exposureWeight?: number
  themeContribution?: number
  riskPenalty?: number
  reasons?: string[]
}

export interface CandidateAnalysisContext {
  stock: CandidateStockLike
  allStocks?: CandidateStockLike[]
  rankTrend?: Record<string, any> | null
  themeExposures?: CandidateThemeExposureLike[]
  rotationSummary?: Record<string, any> | null
  dragonRecord?: Record<string, any> | null
  sentiment?: Record<string, any> | null
  now?: number
}

export interface CandidateScoreBreakdown {
  rankTrend: number
  theme: number
  dragon: number
  sentiment: number
  moneyFlow: number
}

export interface CandidateAnalysisResult {
  score: number
  grade: CandidateGrade
  suggestedStatus: Extract<CandidateStatus, 'observe' | 'candidate' | 'triggered'>
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  riskWarnings: string[]
  strengths: string[]
  weaknesses: string[]
  tags: string[]
  scoreBreakdown: CandidateScoreBreakdown
  signalsSnapshot: Record<string, any>
}

export interface CandidateJournalEntry {
  id: string
  stockCode: string
  stockName: string
  status: CandidateStatus
  tradeType: string
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  humanDecision: string
  reviewOutcome: string
  modelResult: string
  executionResult: string
  reviewTags: string[]
  signalsSnapshot: Record<string, any> | null
  createdAt: string
  updatedAt: string
}
