// src/types/core.ts
// 核心基础类型定义
import type { ThresholdMultiplier } from './emotion'

// ========== 基础股票类型 ==========
export interface Stock {
  // 基础信息
  code: string
  name: string

  // 行情数据
  price: number
  change: number
  volume: number
  turnover: number
  turnoverRate: number
  pe: number
  pb: number
  totalMV: number
  cirMV: number

  // 资金数据
  zlje: number // 主力净额
  zljzb: number // 主力占比
  cddje: number // 超大单净额
  cddjzb: number // 超大单占比

  // 八平台排名
  emRank: number
  thsRank: number
  kplRank: number
  tdxRank: number
  xqRank: number
  clsRank: number
  tgbRank: number
  dzhRank: number

  // 综合数据
  platforms: number
  avgRankNum: number
  avgRank: string
  compRank: number
  compScore: number

  // 龙头数据
  isSectorLeader: boolean
  leaderLevel: string
  leaderScore: number
  leaderReasons?: string[]
  continuousDays: number

  // 题材数据
  themes: any[]
  hotScore?: number

  // ========== 扩展字段 ==========
  speed?: number
  volumeRatio?: number
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
  capitalFlowSource?: 'broker_l2' | 'official_l2' | 'estimated_l1' | string
  capitalFlowConfidence?: 'high' | 'medium' | 'low' | string
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  fengdan?: number
  maxFengdan?: number
  hotness?: number
  tags?: any[]
  reason?: string
  isNew?: boolean
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  fundPenetration?: number
  mainTheme?: string
  themeHeat?: number
  themeLevel?: string
  rankChange?: number
  candidatePoolStatus?: 'observe' | 'candidate' | 'triggered' | 'tracking' | 'reviewed' | 'none'
  candidatePoolLabel?: string
  candidatePoolEntryId?: string
  candidatePoolSource?: string
  candidatePoolUpdatedAt?: string

  // 信号字段
  directionSignal?: 'buy' | 'sell' | 'hold' | 'none'
  directionConfidence?: number
  accelerationSignal?: 'buy' | 'sell' | 'hold' | 'none'
  accelerationConfidence?: number
  crossSignal?: 'buy' | 'sell' | 'hold' | 'none'
  crossConfidence?: number
  finalSignal?: 'buy' | 'sell' | 'hold' | 'none'
  finalConfidence?: number

  // MACD 字段
  macd?: number
  macdSignal?: number
  macdHistogram?: number
  ma5?: number
  ma10?: number
  maTrend?: 'up' | 'down' | 'steady'
  macdCross?: 'golden' | 'death' | 'none'

  // 时间戳
  updatedAt: number
  updateTime?: number
  algorithmScore?: number
  algorithmVersion?: number
  algorithmId?: string
  lastCalculated?: number

  // L2 摘要字段（十档盘口 / 逐笔聚合）
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

export interface DepthLevel {
  price: number
  volume: number
}

export interface Depth10Book {
  code: string
  bids: DepthLevel[]
  asks: DepthLevel[]
  sourceTs?: number
  seq?: number
  timestamp: number
  provider?: string
  depthLevelCount?: number
}

export interface TickTrade {
  code: string
  price: number
  volume: number
  amount: number
  side: 'buy' | 'sell' | 'neutral'
  tradeTime: string
  sourceTs?: number
  timestamp: number
  provider?: string
}

export interface QuotePatch {
  code: string
  name?: string
  lastPrice: number
  changePct: number
  changeAmount?: number
  speed?: number
  volume: number
  amount: number
  turnoverRate?: number
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  zlje?: number
  zljzb?: number
  cddje?: number
  cddjzb?: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  capitalFlowSource?: 'broker_l2' | 'official_l2' | 'estimated_l1' | string
  capitalFlowConfidence?: 'high' | 'medium' | 'low' | string
  open?: number
  high?: number
  low?: number
  preClose?: number
  capturedAt?: string
  bridgeTs?: string
  lastPriceSource?: string
  sampleKind?: string
  openingForcedSample?: boolean
  requestedCount?: number
  receivedCount?: number
  elapsedMs?: number
  slowBatches?: number
  truncatedBatches?: number
  previousWeakScore?: number
  previousWeakSignals?: string[]
  previousWeakSource?: string
  sourceTs?: number
  seq?: number
}

export interface L2Summary {
  code: string
  bid1Price: number
  bid1Volume: number
  ask1Price: number
  ask1Volume: number
  spread: number
  bid10Total: number
  ask10Total: number
  depthImbalance: number
  tickBuyVolume: number
  tickSellVolume: number
  tickBuyCount: number
  tickSellCount: number
  lastTradePrice: number
  lastTradeVolume: number
  timestamp: number
}

export interface RealtimeStreamStatus {
  status: 'connecting' | 'connected' | 'stale' | 'fallback' | 'disconnected'
  subscribedCount: number
  lastMessageTime: number | null
  lastHeartbeatTime: number | null
  fallbackActive: boolean
  tdxConnected: boolean
  reconnectAttempts: number
  transport: 'ws' | 'http' | 'idle'
  url: string
  l2?: L2ProviderStatus
}

export interface L2ProviderStatus {
  provider?: string
  enabled?: boolean
  status?: string
  message?: string
  lastProbeTs?: number
  lastDataTs?: number
  subscribedCount?: number
  depthLevelCount?: number
  fallbackActive?: boolean
}

export interface PlatformData {
  rank: number
  code: string
  name: string
  change?: number
  popularValue?: number
  continuenum?: number
  linkingBoard?: string
  reason?: string
  source: string
  rawData?: any
}

// ========== 因子相关 ==========
export interface FactorDetail {
  name: string
  score: number
  weight: number
  contribution: number
}

export interface ScoreResult {
  score: number
  details: Record<string, FactorDetail>
  timestamp: number
  algorithm: string
  algorithmName: string
}

// ========== 情绪相关 ==========
export interface MarketPhase {
  name: string
  value: string
  color: string
  gradient: string
  icon: string
  score?: number
  desc: string
  suggestion: string
  features: readonly string[]
  thresholdMultiplier?: ThresholdMultiplier
}

export interface LimitData {
  yiban: number
  erban: number
  sanban: number
  sibanPlus: number
  maxBoard?: number  // 最高连板数, fetchLimitData 侧根据原始行 N002 填
}

export interface ZhabanData {
  count: number
  rate: number
  fengbanRate: number
  ztCount?: number
}

export interface PreviousMarketStats {
  tradingDate: string
  ztCount?: number
  dtCount?: number
  source: 'daily_snapshot'
}

export type ThsLimitUpPoolKey =
  | 'one'
  | 'two'
  | 'three'
  | 'four'
  | 'high'
  | 'failed'
  | 'rushing'
  | 'drawdown'

export interface ThsLimitUpPoolError {
  pool: string
  errorCode?: string
  message?: string
}

export interface ThsLimitUpPoolEvidence {
  source: 'ths-limitup-pools'
  date?: string
  timestamp?: number
  degraded: boolean
  errors: ThsLimitUpPoolError[]
  poolCounts: Record<ThsLimitUpPoolKey, number>
  failedCount: number
  rushingCount: number
  drawdownCount: number
  drawdownRiskLabel: '涨停股回撤榜'
  maxDrawdown: number | null
  avgDrawdown: number | null
}

export interface LimitStockInfo {
  code: string
  name: string
  board: string
  boardDays: number
  reason: string
  time: string
  price: number
  change: number
  fengdan: number
}

export interface MarketData {
  // 基础数据
  timestamp: number | null
  upCount: number
  downCount: number
  ztCount: number
  dtCount: number
  totalAmo: number
  amoDiff: number
  limitData: LimitData
  yesterdayLimit: LimitData
  previousMarketStats?: PreviousMarketStats | null
  zhaban: ZhabanData
  thsLimitUpPools?: ThsLimitUpPoolEvidence | null
  indices: {
    sh: { change: number }
    hs300: { change: number }
    zz500: { change: number }
    zz1000: { change: number }
  }
  moneyFlow: { main: number; retail: number }
  emotionValue: number
  emotionStatus: string

  // 专业情绪指标
  yesterdayZtPerformance: number
  yesterdayZtAvgLoss: number
  maxContinuousDays: number
  limitStocks: LimitStockInfo[]
  bigLossCount: number
  volumeRatio: number
  largeCapChange: number
  microCapChange: number
  fengbanAmount: number
  fengbanRate: number
  passRate: {
    to2: number
    to3: number
    to4: number
  }
  repairRate: number
  cddje?: number
  cddjzb?: number
  // 市场亏钱效应统计数据
  marketLossStats?: {
    bigLossRatio: number // 跌幅>5%的股票比例
    mediumLossRatio: number // 跌幅>3%的股票比例
    bigLossCount: number // 跌幅>5%的股票数量
    mediumLossCount: number // 跌幅>3%的股票数量
    totalStocks: number // 总股票数
    timestamp: number
  }
  // 市场赚钱效益统计数据
  profitEstimate?: {
    gt5Ratio: number // 涨幅>5%比例
    gt7Ratio: number // 涨幅>7%比例
    gt3Ratio: number // 涨幅>3%比例
    ztRatio: number // 涨停比例
    timestamp: number
  }

  // 昨日涨停详细统计
  yesterdayLimitStats?: {
    total: number
    dtCount: number
    bigLossCount: number
    redCount: number
    greenCount: number
    avgChange: number
    maxChange: number
    minChange: number
  }
}

export interface Sentiment {
  overall: number
  shortTerm?: number
  phase: string
  phaseName?: string
  phaseInfo?: MarketPhase
  riskLevel: string
  suggestion: string
  timestamp: number
  themeImpact?: number
  hotThemesCount?: number
  phaseIcon?: string
  phaseColor?: string
  phaseGradient?: string
  phaseFeatures?: readonly string[]
  metrics?: {
    yesterdayZtPerformance?: number
    maxContinuousDays?: number
    ztCount?: number
    dtCount?: number
    zhabanRate?: number
    upDownRatio?: number
  }
}

export interface BreathReport {
  timestamp: number
  sentiment: {
    score: string
    phase: string
    risk: string
    suggestion: string
  }
  market: {
    up: number
    down: number
    zt: number
    dt: number
    zhabanRate: string
    amount: string
  }
  limit: {
    yiban: number
    erban: number
    sanban: number
    sibanPlus: number
  }
  emotion: {
    value?: string
    status: string
  }
}

export interface BreathHistorySnapshot {
  timestamp: number
  sentiment: Sentiment
  marketData: {
    upCount: number
    downCount: number
    ztCount: number
    dtCount: number
    previousMarketStats?: PreviousMarketStats | null
    limitData: LimitData
    zhaban: ZhabanData
    thsLimitUpPools?: ThsLimitUpPoolEvidence | null
    emotionValue: number
    maxContinuousDays?: number
    yesterdayZtPerformance?: number
  }
}

// ========== 性能监控类型 ==========
export interface PerformanceRecord {
  algorithm: string
  score: number
  success: boolean
  timestamp: number
}

export interface PerformanceStat {
  count: number
  successCount: number
  totalScore: number
  avgScore: number
  successRate: string
}

export interface Board {
  id: string
  name: string // 板块名称（如：电力、AI硬件、石油油气等）
  color?: string // 板块颜色
  count: number // 板块内股票数量
  createTime: number
  updateTime?: number
}

export interface FavoriteStock {
  code: string
  name: string
  group: string
  notes?: string
  addTime: number
  lastPrice: number
  lastChange: number
  lastUpdate: number
}

export interface FavoriteGroup {
  name: string
  color: string
  count: number
  createTime: number
}

export interface FavoriteStats {
  total: number
  groups: number
  byGroup: Array<{
    name: string
    count: number
    color: string
  }>
}

export type MarketMode = 'hybrid' | 'local' | 'realtime' | 'mock'

// 板块分组
export interface BoardGroup {
  id: string
  name: string // 分组名称（如：热门板块、自选板块等）
  boards: string[] // 板块ID列表
  createTime: number
}

// 股票板块关联
export interface StockBoard {
  stockCode: string
  boardId: string
  addTime: number
  notes?: string // 备注（如：次队列、冷备等）
}

// 板块统计数据
export interface BoardStats {
  totalBoards: number
  totalGroups: number
  topBoards: Array<{
    name: string
    count: number
    trend: 'up' | 'down' | 'stable'
  }>
}

//市场情绪相关
export interface BreathData {
  timestamp: number
  sentiment: {
    overall: number
    phase: string
    phaseName?: string
    riskLevel: string
    suggestion: string
    phaseInfo?: MarketPhase
  }
  market: {
    upCount: number
    downCount: number
    ztCount: number
    dtCount: number
    zhabanRate: number
    totalAmo: number
    emotionValue: number
  }
  limit: {
    yiban: number
    erban: number
    sanban: number
    sibanPlus: number
  }
}

// ========== 题材信息类型 ==========
export interface ThemeInfo {
  id: string
  name: string
  heatScore: number
  heatLevel: string
  heatIcon?: string
  heatColor?: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: Array<{
    id: string
    name: string
    correlation: number
  }>
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }
  leaders: Array<{
    code: string
    name: string
    level: string
    change: number
    continuousDays: number
    score: number
  }>
  history: any[]
  lastUpdate: number | null
}

// ========== 龙头信息类型 ==========
export interface LeaderInfo {
  code: string
  name: string
  level: string
  levelName: string
  score: number
  change: number
  price: number
  continuousDays: number
  themeId?: string
  themeName?: string
  block?: string
  blockStrength?: number
  blockChange?: number
  mainNetInflow?: number
  bigMoney300?: number
  institutionBuy?: number
  leadTimes?: number
  leadStatus?: string
  lianbanStr?: string
  popularity?: number
  fengdan?: number
  maxFengdan?: number
}

// ========== 轮动系统类型定义 ==========

/** 轮动方向 */
export type RotationDirection = 'inflow' | 'outflow' | 'neutral'

/** 轮动强度 */
export type RotationStrength = 'strong' | 'medium' | 'weak'

/** 市场阶段类型 */
export type MarketPhaseType =
  | 'ice'
  | 'accumulation'
  | 'rising'
  | 'climax'
  | 'distribution'
  | 'falling'

/** 单个题材的轮动状态 */
export interface ThemeRotationStatus {
  themeId: string
  themeName: string

  // 资金数据（万元）
  inflow: number // 流入资金
  outflow: number // 流出资金
  netInflow: number // 净流入

  // 量价数据
  avgChange: number // 平均涨幅
  totalTurnover: number // 总成交额（万元）
  ztCount: number // 涨停数
  stockCount: number // 成分股数量

  // 轮动指标
  rank: number // 当前排名
  rankChange: number // 排名变化（负值表示上升）
  direction: RotationDirection
  strength: RotationStrength

  // 持续性
  persistentDays: number // 持续天数（同方向）
  isMainLine: boolean // 是否主线（持续3天以上且净流入）

  // 关联板块
  relatedThemes: Array<{
    id: string
    name: string
    correlation: number // 相关性 0-1
  }>

  /** 强度分数（0-100） */
  strengthScore?: number

  /** 量比 */
  volumeRatio?: number

  /** 300W大单净额 */
  bigMoney300?: number

  /** 机构增仓净额 */
  institutionBuy?: number

  /** 资金变化率（%） */
  inflowChange?: number

  /** 总封板高度 */
  totalBoardHeight?: number

  /** 平均封板高度 */
  avgBoardHeight?: number

  /** 高标天数 */
  highDays?: number

  /** 涨停原因列表 */
  topReasons?: string[]
}

/** 轮动分析结果 */
export interface RotationAnalysis {
  timestamp: number

  // 资金流入板块（进攻方向）
  inflowThemes: ThemeRotationStatus[]

  // 资金流出板块（退潮方向）
  outflowThemes: ThemeRotationStatus[]

  // 主线板块（持续3天以上）
  mainLines: ThemeRotationStatus[]

  // 快速轮动板块（一日游）
  quickRotation: ThemeRotationStatus[]

  // 轮动速度（0-100，越高说明轮动越快）
  rotationSpeed: number

  // 市场阶段
  marketPhase: MarketPhaseType

  // 轮动总结
  summary: {
    mainLineCount: number
    inflowCount: number
    outflowCount: number
    topInflow: string
    topOutflow: string
    suggestion: string
    strongCount: number
    topStrength: string
  }

  emotion?: {
    value: number
    status: string
    phase: string
    score?: number
  }

  strongThemes?: Array<{
    themeId: string
    themeName: string
    strengthScore: number
  }>
}

/** 轮动存储结构 */
export interface RotationStore {
  current: RotationAnalysis | null
  history: RotationAnalysis[]
  lastUpdate: number | null
}

// ========== 预警系统类型定义 ==========

export interface StockAlert {
  id: string // 唯一ID
  type: AlertType // 预警类型
  level: AlertLevel // 预警级别
  title: string // 标题
  message: string // 详细消息
  timestamp: number // 触发时间
  expireTime: number // 过期时间
  readTime?: number // 阅读时间
  status: 'pending' | 'read' | 'resolved'

  // 关联数据
  code?: string // 股票代码
  name?: string // 股票名称
  themeId?: string // 板块ID
  themeName?: string // 板块名称

  // 预警时的快照数据
  snapshot?: {
    price?: number // 当前价
    change?: number // 涨跌幅
    ztCount?: number // 涨停数
    netInflow?: number // 主力净额
    strength?: number // 板块强度
    volumeRatio?: number // 量比
  }
}

export type AlertType =
  | 'leader_fall' // 龙头倒下
  | 'leader_emerge' // 龙头涌现
  | 'batch_limit_up' // 批量涨停
  | 'batch_explode' // 批量炸板
  | 'strength_surge' // 强度飙升
  | 'strength_plunge' // 强度骤降
  | 'money_flow' // 资金异动
  | 'data_anomaly' // 数据异常
  | 'volume_surge' // 放量异动
  | 'rocket_launch' // 火箭发射
  | 'waterfall_dive' // 瀑布跳水
  | 'fengdan_drop' // 封单减少

export type AlertLevel = 'critical' | 'warning' | 'info'

export interface AlertStats {
  total: number
  critical: number
  warning: number
  info: number
  byType: Record<AlertType, number>
  lastUpdate: number
}

export interface AlertStore {
  items: StockAlert[]
  stats: AlertStats
  lastUpdate: number | null
}

// ========== 扩展的分析结果存储 ==========
/** 扩展的分析结果存储（用于 DataLayer） */
export interface ExtendedAnalysis {
  breath: {
    sentiment: any
    history: any[]
    lastUpdate: number | null
  }
  algorithm: {
    config: any
    results: Map<string, any>
    lastUpdate: number | null
  }
  rotation: RotationStore // 新增轮动存储
  alerts: AlertStore // 新增预警存储
}

// ========== 扩展的股票类型（可选） ==========
export interface ExtendedStock extends Stock {
  // 轮动相关
  rotationRank?: number
  rotationChange?: number

  // 预警相关
  alertCount?: number
  lastAlert?: StockAlert
}

// ========== 配置类型定义 ==========
export interface SystemConfig {
  version: string
  debug: boolean
  env: 'development' | 'production'
  proxyUrl: string
  timeout: number
  retryCount: number
  useMockWebSocket: boolean
}

export interface DataLoaderConfig {
  platforms: string[]
  platformWeights: Record<string, number>
  quoteBatchSize: number
  quoteBatchDelay: number
}

export interface RendererConfig {
  fontSize: number
  rowHeight: number
  showLeaderBadge: boolean
  showSectorTags: boolean
}

export interface DragonBreathConfig {
  autoRefresh: boolean
  refreshInterval: number
}

export interface ModulesConfig {
  dataLoader: DataLoaderConfig
  renderer: RendererConfig
  dragonBreath: DragonBreathConfig
}

export interface CacheItemConfig {
  enabled: boolean
  capacity: number
  ttl: number
  maxMemory: number
  persist: boolean
}

export interface CacheConfig {
  stock: CacheItemConfig
  leader: CacheItemConfig
  sector: CacheItemConfig
  quote: CacheItemConfig
}

export interface UserConfig {
  theme: 'dark' | 'light' | 'matrix' | 'cream'
  followSystemTheme: boolean
  refreshStrategy: 'balanced' | 'aggressive' | 'conservative' | 'recovery'
  refreshEnabled: boolean
  tradingTimeOnly: boolean
  fullRefreshInterval: number
  favoriteGroups: string[]
}

export interface AlgorithmConfig {
  current: string
  thresholds: {
    totalLeader: number
    sectorLeader: number
    continuousLeader: number
    middleLeader: number
    emotionLeader: number
  }
}

export interface AppConfig {
  system: SystemConfig
  modules: ModulesConfig
  cache: CacheConfig
  user: UserConfig
  algorithm: AlgorithmConfig
}
