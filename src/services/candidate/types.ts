import type { FusionExecutionOverlay } from '../../types/fusionStrategyProjection'

export type CandidateGrade = 'A' | 'B' | 'C' | 'D'
export type CandidateStatus = 'observe' | 'candidate' | 'triggered' | 'tracking' | 'reviewed'

export type CandidateExecutionOverlayByCode = Record<string, FusionExecutionOverlay | null>

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

export type CandidateEvidenceDimension = keyof CandidateScoreBreakdown
export type CandidateEvidenceKind = 'positive' | 'negative' | 'neutral' | 'missing'
export type CandidateDataQuality = 'ok' | 'missing' | 'low_sample' | 'invalid'
export type CandidateConditionStatus = 'met' | 'watch' | 'failed' | 'unknown'
export type CandidateRiskLevel = 'info' | 'warning' | 'danger'

export interface CandidateRuleEvidence {
  dimension: CandidateEvidenceDimension
  kind: CandidateEvidenceKind
  title: string
  detail: string
  scoreImpact: number
  dataQuality: CandidateDataQuality
  source?: string
}

export interface CandidateStructuredCondition {
  id: string
  label: string
  dimension: CandidateEvidenceDimension
  status: CandidateConditionStatus
  description: string
}

export interface CandidateStructuredThesis {
  triggerConditions: CandidateStructuredCondition[]
  entryPrerequisites: CandidateStructuredCondition[]
  invalidationConditions: CandidateStructuredCondition[]
}

export interface CandidateStructuredRisk {
  code: string
  level: CandidateRiskLevel
  dimension: CandidateEvidenceDimension | 'dataQuality'
  message: string
  reason: string
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
  evidence: CandidateRuleEvidence[]
  penalties: CandidateRuleEvidence[]
  structuredThesis: CandidateStructuredThesis
  structuredRisks: CandidateStructuredRisk[]
  tags: string[]
  scoreBreakdown: CandidateScoreBreakdown
  signalsSnapshot: Record<string, any>
}

export interface CandidateSavedAnalysis {
  score: number
  grade: CandidateGrade | '-'
  suggestedStatus: CandidateStatus | ''
  riskWarnings: string[]
  strengths: string[]
  weaknesses: string[]
  evidence: CandidateRuleEvidence[]
  penalties: CandidateRuleEvidence[]
  structuredThesis: CandidateStructuredThesis
  structuredRisks: CandidateStructuredRisk[]
  scoreBreakdown: CandidateScoreBreakdown
  generatedAt?: number
}

export interface CandidateWorkbenchReview {
  entry: CandidateJournalEntry
  savedAnalysis: CandidateSavedAnalysis
  currentAnalysis: CandidateAnalysisResult
  scoreDelta: number
  stateLabel: string
  stateReasons: string[]
}

export interface CandidateJournalEntry {
  id: string
  stockCode: string
  stockName: string
  status: CandidateStatus
  tradeType: string
  candidateEntryId?: string
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  humanDecision: string
  skipReason: string
  reviewOutcome: string
  modelResult: string
  executionResult: string
  reviewNotes: string
  reviewTags: string[]
  signalsSnapshot: Record<string, any> | null
  entryPrice?: number
  entryTime?: string
  exitPrice?: number
  exitTime?: string
  stopLossPrice?: number
  takeProfitPrice?: number
  positionPct?: number
  createdAt: string
  updatedAt: string
}

export interface CandidateThesisUpdate {
  entryReason: string
  tradeHypothesis: string
  entryPrerequisites: string
  invalidationRules: string
  humanDecision: string
  skipReason: string
}

export interface TradingPoolSignalSnapshotPayload {
  version: string
  code?: string
  name?: string
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
  signalSnapshot?: TradingPoolSignalSnapshot
  dataQuality?: TradingPoolSignalSnapshot['dataQuality']
  lastRecomputedAt?: string
}

export interface TradingPoolEntryUpdate {
  code?: string
  name?: string
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
  signalSnapshot?: TradingPoolSignalSnapshot
}

export interface TradeExecutionFields {
  entryPrice?: number
  entryTime?: string
  exitPrice?: number
  exitTime?: string
  stopLossPrice?: number
  takeProfitPrice?: number
  positionPct?: number
}

export interface CandidateReviewUpdate extends Partial<TradeExecutionFields> {
  reviewOutcome: string
  modelResult: string
  executionResult: string
  reviewNotes: string
}

export interface CandidateDiscoveryDuplicate {
  isOpen: boolean
  entryId?: string
  status?: CandidateStatus
}

export interface CandidateDiscoveryRecommendation {
  rank: number
  stock: CandidateStockLike
  analysis: CandidateAnalysisResult
  score: number
  grade: CandidateGrade
  suggestedStatus: Extract<CandidateStatus, 'observe' | 'candidate' | 'triggered'>
  reasons: string[]
  risks: string[]
  expectedTrackingDays: number
  duplicate: CandidateDiscoveryDuplicate
}

export interface CandidateDiscoveryResult {
  generatedAt: number
  totalAnalyzed: number
  recommendations: CandidateDiscoveryRecommendation[]
  skippedReason?: 'cooldown' | 'empty'
}

export type TradingPoolStatus =
  | '观察买点'
  | '准备介入'
  | '已介入'
  | '持仓观察'
  | '观察中'
  | '已退出'
  | '已完成'

export type TradingPoolDecision = 'enter' | 'watch' | 'downgrade' | 'exit' | 'stale'

export interface TradingPoolSignalSnapshot {
  directionSignal: string | null
  jumpConfidence: number | null
  macdCross: string | null
  accelerationSignal: string | null
  zeroCrossSignal: string | null
  momentumSyncBroken: boolean
  lifecycleAction: string | null
  dataQuality: 'fresh' | 'stale' | 'missing'
}

export interface TradingPoolAnalysisRow {
  code: string
  name?: string
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
  signalSnapshot: TradingPoolSignalSnapshot
}

export interface TradingPoolAnalysisResult {
  rows: TradingPoolAnalysisRow[]
  staleCount: number
  exitedCount: number
}
