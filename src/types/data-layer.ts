import type { ThemeCorrelationDetail } from '@/services/ThemeCorrelationAnalyzer'
import type { RankTrendAnalysisResult } from '@/services/rankTrend/types'
import type {
  AuthorityClass,
  BattlefieldRecord,
  ChaseRisk,
  DragonReviewResult,
  LeaderRecord,
  LeaderRole,
  LeaderTransition,
  PseudoLeaderRecord,
  Tradeability,
} from '@/services/dragon/types'
import type { RotationAnalysis } from './core'
import type { AlertStats, StockAlert } from './core'
import type { AlertType } from './core'
import type { BreathData, Depth10Book, L2Summary, TickTrade } from './core'

export interface LeaderLookupRecord {
  code: string
  name: string
  level: LeaderRole
  levelName: string
  score: number
  continuousDays: number
  authority: AuthorityClass
  primaryRole: LeaderRole
  roles: LeaderRole[]
  tradeability: Tradeability
  chaseRisk: ChaseRisk
  status?: LeaderRecord['status']
  themeName?: string
  lastUpdate: number
}

export interface DataVersion {
  stocks: number
  themes: number
  leaders: number
  review?: number
  quotes: number
  platforms: number
  platformStatus: number
  breath: number
  rotation?: number
}

/** 单平台热榜加载状态：区分“真实空榜”与“来源失败/降级”，失败原因结构化保留。 */
export interface PlatformStatusInfo {
  rowCount: number
  success: boolean
  /** 连续失败次数；undefined 表示非重试类失败（如白名单不可用），直接按失败展示 */
  consecutiveFailures?: number
  error?: string
}

export interface ThemeMetrics {
  heatScore: number
  heatLevel: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: any[]
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }
  lastUpdate: number
}

export interface LimitUpExtData {
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  fengdan?: number
  maxFengdan?: number
  openNum?: number
  leadStatus?: string
  leadTimes?: number
  lianbanStr?: string
  reason?: string
  tags?: Array<{ Name: string }>
  isNew?: boolean
}

export interface StockExtData {
  speed?: number
  volumeRatio?: number
  volumeRatioMeta?: VolumeRatioMeta
  leadTimes?: number
  leadStatus?: string
  lianbanStr?: string
  bigMoney300?: number
  popularity?: number
  popularityChange?: number
  institutionBuy?: number
  mainBuy?: number
  mainSell?: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  capitalFlowSource?: string
  capitalFlowConfidence?: string
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  open?: number
  high?: number
  low?: number
  preClose?: number
  fengdan?: number
  maxFengdan?: number
  bid1Price?: number
  bid1Volume?: number
  ask1Price?: number
  ask1Volume?: number
  spread?: number
  bid10Total?: number
  ask10Total?: number
  depthImbalance?: number
  tickBuyVolume?: number
  tickSellVolume?: number
  tickBuyCount?: number
  tickSellCount?: number
  lastTradePrice?: number
  lastTradeVolume?: number
}

export interface MergedStock {
  code: string
  name: string
  price: number
  change: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  pb: number
  totalMV: number
  cirMV: number
  zlje: number
  zljzb: number
  cddje: number
  cddjzb: number
  emRank?: number
  thsRank?: number
  kplRank?: number
  tdxRank?: number
  xqRank?: number
  clsRank?: number
  tgbRank?: number
  dzhRank?: number
  platforms?: number
  avgRankNum?: number
  avgRank?: string
  compRank?: number
  compScore?: number
  /** 综合排名（语义 := compRank，compScore 降序 + code 稳定序；golden 来自后端快照行） */
  rank?: number
  qualityFlags?: string[]
  missingFields?: string[]
  updatedAt?: number
  firstSeen?: number
  lastSeen?: number
  platformName?: string
  reviewAuthority?: AuthorityClass
  reviewRole?: LeaderRole
  tradeability?: Tradeability
  chaseRisk?: ChaseRisk
  continuousDays?: number
  themes?: any[]
  speed?: number
  volumeRatio?: number
  volumeRatioMeta?: VolumeRatioMeta
  leadTimes?: number
  leadStatus?: string
  lianbanStr?: string
  bigMoney300?: number
  popularity?: number
  popularityChange?: number
  institutionBuy?: number
  mainBuy?: number
  mainSell?: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  capitalFlowSource?: string
  capitalFlowConfidence?: string
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  open?: number
  high?: number
  low?: number
  preClose?: number
  fengdan?: number
  maxFengdan?: number
  bid1Price?: number
  bid1Volume?: number
  ask1Price?: number
  ask1Volume?: number
  spread?: number
  bid10Total?: number
  ask10Total?: number
  depthImbalance?: number
  tickBuyVolume?: number
  tickSellVolume?: number
  tickBuyCount?: number
  tickSellCount?: number
  lastTradePrice?: number
  lastTradeVolume?: number
  hotness?: number
  tags?: any[]
  reason?: string
  isNew?: boolean
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  openNum?: number
  /** 涨停原因（同花顺涨停池 reason_type，仅涨停股有值）；与 reason（关联原因静态文本）是两个不同字段 */
  limitUpReason?: string
  fundPenetration?: number
  mainTheme?: string
  themeHeat?: number | null
  themeLevel?: string
  rankTrend?: RankTrendAnalysisResult
  rankTrendCoverageWarning?: string
}

export type VolumeRatioSource = 'intraday_snapshot' | 'daily_snapshot' | 'unavailable'
export type VolumeRatioStatus = 'fresh' | 'suspicious' | 'stale' | 'unavailable'

export interface VolumeRatioMeta {
  status: VolumeRatioStatus
  source: VolumeRatioSource
  calculatedAt: number
  currentVolume: number
  expectedVolume?: number
  historyVolumes?: number[]
  rawRatio?: number
  capped?: boolean
  reason?: string
}

export interface DataState {
  raw: {
    stocks: any[]
    platforms: Record<string, any>
    platformStatus: Record<string, PlatformStatusInfo>
    themes: any[]
    fullMarket: any[]
  }
  realtime: {
    quotes: Map<string, any>
    depth10: Map<string, Depth10Book>
    recentTicks: Map<string, TickTrade[]>
    l2Summary: Map<string, L2Summary>
    lastUpdate: number | null
  }
  merged: {
    stocks: MergedStock[]
    themes: any[]
  }
  listPoolProvenance: ListPoolProvenance | null
  leader: {
    byCode: Map<string, LeaderLookupRecord>
    byLevel: Record<string, LeaderLookupRecord[]>
    lastUpdate: number | null
  }
  review: {
    result: DragonReviewResult | null
    marketCore: LeaderRecord | null
    trueLeaders: LeaderRecord[]
    heightBoard: LeaderRecord[]
    attentionBoard: LeaderRecord[]
    pseudoLeaderGraveyard: PseudoLeaderRecord[]
    battlefields: BattlefieldRecord[]
    transitions: LeaderTransition[]
    summaryLines: string[]
    lastUpdate: number | null
  }
  theme: {
    base: {
      byCode: Map<string, any[]>
      byId: Map<string, any>
      lastUpdate: string | null
    }
    metrics: {
      byTheme: Map<string, ThemeMetrics>
      hotList: any[]
      rotation: any[]
      lastUpdate: number | null
    }
    correlation: {
      byTheme: Map<string, ThemeCorrelationDetail>
      lastUpdate: number | null
    }
  }
  tck2?: {
    stockHotness: Map<string, number>
    stockTags: Map<string, Array<{ Name: string }>>
    stockReasons: Map<string, string>
    stockIsNew: Map<string, boolean>
    limitUpData: Map<string, LimitUpExtData>
    lastUpdate: number | null
  }
  analysis: {
    breath: {
      sentiment: BreathData['sentiment'] | null
      marketData?: any
      factors?: Array<{
        id: string
        name: string
        rawValue: number | null
        description?: string
        unit?: string
        category?: string
      }>
      history: any[]
      lastUpdate: number | null
    }
    rotation: {
      current: RotationAnalysis | null
      history: RotationAnalysis[]
      lastUpdate: number | null
    }
    alerts: {
      items: StockAlert[]
      stats: AlertStats
      lastUpdate: number | null
    }
  }
  rankHistory: {
    byCode: Map<string, number>
    lastUpdate: number | null
    snapshotDate: string | null
  }
  version: DataVersion
  meta: {
    initialized: boolean
    lastMergeTime: number | null
    marketMode: 'hot' | 'full'
  }
}

/** 行情列表池来源（2026-09-21 池源替换）：frame-pool=后端最新 half_hour 帧池 */
export type ListPoolSource = 'frame-pool' | 'hotlist-merged' | 'startup-bundle'

/** 列表池 provenance：对账注脚与诊断依据，随每次池发布更新 */
export interface ListPoolProvenance {
  source: ListPoolSource
  slotTime?: string
  tradingDate?: string
  degradeReason?: string
  updatedAt: number
}
