import type { MergedStock } from '../../services/DataLayer'
import type { RankTrendSnapshotType } from '../../type/rankTrendDefaults'

export type ReviewSegment = 'early' | 'mid' | 'late'
export type FrameSource = RankTrendSnapshotType | 'close'
export type SignalStrength = 'strong' | 'medium' | 'weak'
export type FragilityLevel = 'low' | 'mid' | 'high'
export type BattlefieldType = 'THEME' | 'STYLE' | 'INDEPENDENT'
export type BattlefieldDominance = 'DOMINANT' | 'CONTESTED' | 'WEAK'
export type LeaderRole =
  | 'MARKET_CORE'
  | 'THEME_CORE'
  | 'SPACE_CORE'
  | 'TREND_CORE'
  | 'EMOTION_CORE'
export type AuthorityClass =
  | 'TRUE_LEADER'
  | 'THEME_COMMANDER'
  | 'CARRY_PROXY'
  | 'HEIGHT_ONLY'
  | 'HEAT_ONLY'
  | 'PSEUDO_LEADER'
export type Tradeability = 'ACTIONABLE' | 'WATCH_ONLY' | 'DO_NOT_CHASE'
export type ChaseRisk = 'LOW' | 'MEDIUM' | 'HIGH' | 'EXTREME'
export type LeaderStatus =
  | 'CANDIDATE'
  | 'PROBING_LEADER'
  | 'CONFIRMED_LEADER'
  | 'COMMANDING'
  | 'WEAKENING'
  | 'DEPOSED'
export type ReviewRegime =
  | 'MAINLINE_ADVANCE'
  | 'MULTI_FRONT_CONTEST'
  | 'HIGH_LEVEL_HUG'
  | 'REPAIR_ATTEMPT'
  | 'ROTATION_NO_CORE'
  | 'DISTRIBUTION_DECAY'
export type FatalNegative =
  | 'ONE_WORD_ISOLATION'
  | 'NO_FOLLOWERS'
  | 'LATE_HEAT_CHASE'
  | 'INTRADAY_FADE'
  | 'CLOSE_LOST_LEADERSHIP'
  | 'WEAK_BATTLEFIELD'
  | 'MAPPING_UNCERTAIN'

export interface ReviewThemeRef {
  id?: string
  name: string
  heatScore?: number
}

export interface ReviewHotStock {
  code: string
  name: string
  rank?: number
  compRank?: number
  price?: number
  change?: number
  turnover?: number
  turnoverRate?: number
  totalMV?: number
  cirMV?: number
  zlje?: number
  volumeRatio?: number
  leadStatus?: string
  leadTimes?: number
  lianbanStr?: string
  popularity?: number
  popularityChange?: number
  institutionBuy?: number
  mainBuy?: number
  mainSell?: number
  fengdan?: number
  maxFengdan?: number
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  hotness?: number
  themes?: ReviewThemeRef[]
  tags?: Array<{ Name?: string } | string>
  reason?: string
  isNew?: boolean
  mainTheme?: string
  themeHeat?: number
  themeLevel?: string
}

export interface ReviewSector {
  code?: string
  name: string
  strength?: number
  change?: number
  mainNetInflow?: number
  bigMoney300?: number
  institutionBuy?: number
  volumeRatio?: number
  ztCount?: number
}

export interface ReviewFrame {
  id: string
  date: string
  source: FrameSource
  timestamp: number
  segment?: ReviewSegment
  hotlist: ReviewHotStock[]
  sectors: ReviewSector[]
  marketStats: {
    upCount: number
    downCount: number
    ztCount: number
    dtCount: number
    totalAmo?: number
    zhabanRate?: number
  }
  sentiment: {
    overall: number
    phase: string
    phaseName: string
    emotionValue?: number
  }
  rawCoverage: {
    hasHotlist: boolean
    hasSectors: boolean
    hasMarketStats: boolean
  }
}

export interface StockArcFrame {
  frameId: string
  segment: ReviewSegment
  timestamp: number
  rank: number
  change: number
  leadStatus?: string
  hotness?: number
  popularity?: number
  popularityChange?: number
  boardHeight?: number
  highDays?: number
}

export interface StockArc {
  code: string
  name: string
  battlefieldId: string
  themeId?: string
  themeName?: string
  current: MergedStock | null
  frames: StockArcFrame[]
  segmentHits: ReviewSegment[]
  frameHitCount: number
  earlyTop2: boolean
  midTop2: boolean
  lateTop2: boolean
  earlyRank?: number
  lateRank?: number
  bestRank?: number
  firstSeenAt?: number
  firstStrongAt?: number
  followerCountEarly: number
  followerCountLate: number
  followerIncrease: number
  themeRankRise: number
  currentHotness?: number
  peakHotness?: number
  currentPopularity?: number
  bestPopularity?: number
  currentPopularityChange?: number
  peakBoardHeight?: number
  peakHighDays?: number
}

export interface CandidateRecord {
  code: string
  battlefieldId: string
  themeId?: string
  themeName?: string
  stock: MergedStock
  arc: StockArc
  reasons: string[]
}

export interface LeaderEvidence {
  id: string
  label: string
  verdict: 'support' | 'neutral' | 'contradict'
  note?: string
}

export interface DuelResult {
  againstCode: string
  wins: number
  losses: number
  ties: number
  dimensions: Record<
    | 'initiative'
    | 'height'
    | 'acceptance'
    | 'capitalRecognition'
    | 'carryEffect'
    | 'segmentPersistence'
    | 'closeIntegrity',
    'win' | 'tie' | 'lose'
  >
}

export interface BattlefieldRecord {
  battlefieldId: string
  type: BattlefieldType
  themeId?: string
  themeName: string
  aliases: string[]
  dominance: BattlefieldDominance
  continuity: SignalStrength
  carryStrength: SignalStrength
  quality: SignalStrength
  capital: SignalStrength
  fragility: FragilityLevel
  themeHeatScore: number
  themeZtCount: number
  themeMainNetInflow: number
  overallCorrelation: number
  persistentDays: number
  isMainLine: boolean
  attentionScore: number
  candidateCodes: string[]
  challengerCodes: string[]
  followerCodes: string[]
  leaderCode?: string
  evidence: string[]
  risks: string[]
}

export interface LeaderTimeline {
  candidateAt?: number
  probingAt?: number
  confirmedAt?: number
  commandingAt?: number
  weakeningAt?: number
  deposedAt?: number
}

export interface LeaderRecord {
  code: string
  name: string
  primaryRole: LeaderRole
  roles: LeaderRole[]
  authority: AuthorityClass
  tradeability: Tradeability
  chaseRisk: ChaseRisk
  status: LeaderStatus
  battlefieldId: string
  themeId?: string
  themeName?: string
  evidence: LeaderEvidence[]
  contradictions: string[]
  fatalNegatives: FatalNegative[]
  invalidationReasons: string[]
  successors: string[]
  timeline: LeaderTimeline
  playbook: string[]
  duelResults: DuelResult[]
  confidence: 'HIGH' | 'MEDIUM' | 'LOW'
  price: number
  change: number
  turnover: number
  turnoverRate: number
  zlje: number
  continuousDays: number
  highDays: number
  hotness: number
  popularity: number
  popularityChange: number
  leadStatus: string
  lianbanStr: string
  boardHeight: number
  themes: ReviewThemeRef[]
}

export interface PseudoLeaderRecord {
  code: string
  name: string
  pseudoType: AuthorityClass
  battlefieldId?: string
  themeName?: string
  whyLookedLikeLeader: string[]
  whyNotLeader: string[]
  whyChasingHurts: string[]
  price: number
  change: number
  continuousDays: number
  leadStatus?: string
}

export interface LeaderTransition {
  type: 'candidate' | 'confirm' | 'command' | 'weaken' | 'replace' | 'depose'
  code: string
  name: string
  role?: LeaderRole
  from?: string
  to?: string
  reason: string
  timestamp: number
}

export interface DragonReviewResult {
  reviewDate: string
  regime: ReviewRegime
  marketCore: LeaderRecord | null
  battlefields: BattlefieldRecord[]
  trueLeaders: LeaderRecord[]
  heightBoard: LeaderRecord[]
  attentionBoard: LeaderRecord[]
  pseudoLeaderGraveyard: PseudoLeaderRecord[]
  transitions: LeaderTransition[]
  summaryLines: string[]
  missingData: string[]
  reviewCompleteness: 'complete' | 'partial'
}
