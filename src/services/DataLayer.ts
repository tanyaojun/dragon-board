// src/services/DataLayer.ts

import { ref, reactive } from 'vue'
import type { BreathData, Depth10Book, L2Summary, TickTrade } from '../types'
import { ALERT_CONFIG } from '../config/constants'
import type { ThemeCorrelationDetail } from './ThemeCorrelationAnalyzer'
import {
  applyRankTrendAnalysis,
} from './rankTrend/compat'
import type { RankTrendAnalysisResult } from './rankTrend/types'
import type { RotationAnalysis } from '../types'
import type { StockAlert, AlertStats } from '../types'
import type { AlertType } from '../types/core'
import { apiService } from './apiService'
import { SnapshotRuntime } from './snapshot/runtime'
import { getExpectedSlots, slotTimeToMinutes } from './snapshot/schedule'
import type {
  SnapshotBackupSyncState,
  SnapshotBackupAlignmentResult,
  SnapshotDayBundle,
  SnapshotFrameBundle,
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotHealthOverview,
  SnapshotProjectionBundle,
  SnapshotProjectionRewriteResult,
  SnapshotProjectionMeta,
  SnapshotQueryOptions,
  SnapshotPollutionCleanupResult,
  SnapshotRawCompactionResult,
  SnapshotRecord,
  SnapshotSectorRow,
  SnapshotSectorRowQueryOptions,
  SnapshotStorageMaintenanceResult,
  SnapshotStockRow,
  SnapshotStockRowQueryOptions,
  SnapshotType,
} from './snapshot/types'
import type {
  AuthorityClass,
  BattlefieldRecord,
  ChaseRisk,
  LeaderRecord,
  LeaderRole,
  DragonReviewResult,
  LeaderTransition,
  PseudoLeaderRecord,
  Tradeability,
} from './dragon/types'
import type {
  BigOrderItem,
  BigOrderStatistics,
  DenseOrderAlert,
  PeriodStatistics,
} from '../types/big-order'

const REVIEW_ROLE_LABELS: Record<LeaderRole, string> = {
  MARKET_CORE: '市场总龙头',
  THEME_CORE: '题材真龙',
  SPACE_CORE: '空间龙头',
  TREND_CORE: '趋势中军',
  EMOTION_CORE: '情绪核心',
}

const REVIEW_AUTHORITY_SCORES: Record<AuthorityClass, number> = {
  TRUE_LEADER: 95,
  THEME_COMMANDER: 82,
  CARRY_PROXY: 68,
  HEIGHT_ONLY: 56,
  HEAT_ONLY: 52,
  PSEUDO_LEADER: 35,
}

const LEGACY_LEVEL_ROLE_MAP: Record<string, LeaderRole> = {
  TOTAL: 'MARKET_CORE',
  MARKET_CORE: 'MARKET_CORE',
  市场总龙头: 'MARKET_CORE',
  SECTOR: 'THEME_CORE',
  THEME_CORE: 'THEME_CORE',
  题材真龙: 'THEME_CORE',
  CONTINUOUS: 'SPACE_CORE',
  SPACE_CORE: 'SPACE_CORE',
  空间龙头: 'SPACE_CORE',
  MIDDLE: 'TREND_CORE',
  TREND_CORE: 'TREND_CORE',
  趋势中军: 'TREND_CORE',
  EMOTION: 'EMOTION_CORE',
  EMOTION_CORE: 'EMOTION_CORE',
  情绪核心: 'EMOTION_CORE',
}

const FORMAL_SQLITE_SNAPSHOT_TYPES: SnapshotType[] = ['quarter_hour', 'half_hour', 'hourly', 'daily']
const SNAPSHOT_INDEXEDDB_COUNT_STORES = [
  'snapshots',
  'snapshot_frames',
  'snapshot_stock_rows',
  'snapshot_sector_rows',
] as const
type SnapshotIndexedDbCountStore = (typeof SNAPSHOT_INDEXEDDB_COUNT_STORES)[number]
type SnapshotCountMap = Record<SnapshotIndexedDbCountStore, number>

interface SnapshotIndexedDbSqliteMigrationBatch {
  index: number
  snapshotCount: number
  frameCount: number
  stockRowCount: number
  sectorRowCount: number
  imported: number
  skipped: number
  deduped: boolean
  ok: boolean
  error?: string
}

interface SnapshotIndexedDbSqliteMigrationResult {
  ok: boolean
  datasetId: string
  dryRun: boolean
  sourceCounts: SnapshotCountMap
  scanned: number
  imported: number
  skipped: number
  batches: SnapshotIndexedDbSqliteMigrationBatch[]
  validation?: {
    ok: boolean
    datasetId: string
    indexedDb: SnapshotCountMap
    sqlite: SnapshotCountMap
    diffs: Record<string, { indexedDb: number; sqlite: number; delta: number }>
    source: 'sqlite'
  }
  errors: string[]
}

interface LeaderLookupRecord {
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

function normalizeLeaderRole(value?: string | null): LeaderRole | null {
  if (!value) return null
  return LEGACY_LEVEL_ROLE_MAP[value] || null
}

function getLeaderLevelName(role: LeaderRole): string {
  return REVIEW_ROLE_LABELS[role] || role
}

function getLeaderScore(authority?: AuthorityClass | null): number {
  if (!authority) return 50
  return REVIEW_AUTHORITY_SCORES[authority] || 50
}

function toLeaderLookupRecord(record: LeaderRecord, timestamp: number): LeaderLookupRecord {
  const level = record.primaryRole
  return {
    code: record.code,
    name: record.name,
    level,
    levelName: getLeaderLevelName(level),
    score: getLeaderScore(record.authority),
    continuousDays: record.continuousDays || 0,
    authority: record.authority,
    primaryRole: record.primaryRole,
    roles: [...record.roles],
    tradeability: record.tradeability,
    chaseRisk: record.chaseRisk,
    status: record.status,
    themeName: record.themeName,
    lastUpdate: timestamp,
  }
}

function toLegacyLeaderLookupRecord(record: Record<string, any>, timestamp: number): LeaderLookupRecord | null {
  const level = normalizeLeaderRole(record.primaryRole || record.level || record.levelName)
  if (!record.code || !level) return null

  const roles = Array.isArray(record.roles) && record.roles.length
    ? (record.roles.filter(Boolean) as LeaderRole[])
    : [level]
  const authority = (record.authority as AuthorityClass | undefined) || 'TRUE_LEADER'
  const tradeability = (record.tradeability as Tradeability | undefined) || 'WATCH_ONLY'
  const chaseRisk = (record.chaseRisk as ChaseRisk | undefined) || 'HIGH'

  return {
    code: record.code,
    name: record.name || '',
    level,
    levelName: record.levelName || getLeaderLevelName(level),
    score: typeof record.score === 'number' ? record.score : getLeaderScore(authority),
    continuousDays: Number(record.continuousDays) || 0,
    authority,
    primaryRole: level,
    roles: [...new Set(roles)],
    tradeability,
    chaseRisk,
    status: record.status,
    themeName: record.themeName,
    lastUpdate: timestamp,
  }
}

function getReviewRecordPool(result: DragonReviewResult): LeaderRecord[] {
  const deduped = new Map<string, LeaderRecord>()

  const addRecord = (record: LeaderRecord | null | undefined) => {
    if (!record || deduped.has(record.code)) return
    deduped.set(record.code, record)
  }

  addRecord(result.marketCore)
  ;[
    ...(result.trueLeaders || []),
    ...(result.heightBoard || []),
    ...(result.attentionBoard || []),
  ].forEach(addRecord)

  return Array.from(deduped.values())
}

const LEGACY_LEADER_FIELDS = ['isSectorLeader', 'leaderLevel', 'leaderScore'] as const

function stripLegacyLeaderFields<T extends object>(stock: T): T {
  const sanitized = { ...(stock as Record<string, unknown>) }

  LEGACY_LEADER_FIELDS.forEach((field) => {
    delete sanitized[field]
  })

  return sanitized as T
}

function applyReviewProjectionToStock(
  stock: MergedStock,
  leaderRecord: LeaderLookupRecord | null | undefined,
): MergedStock {
  const projected = { ...stock }

  if (!leaderRecord) {
    delete projected.reviewAuthority
    delete projected.reviewRole
    delete projected.tradeability
    delete projected.chaseRisk
    return projected
  }

  projected.reviewAuthority = leaderRecord.authority
  projected.reviewRole = leaderRecord.primaryRole
  projected.tradeability = leaderRecord.tradeability
  projected.chaseRisk = leaderRecord.chaseRisk
  if (!projected.continuousDays && leaderRecord.continuousDays) {
    projected.continuousDays = leaderRecord.continuousDays
  }

  return projected
}

interface DataVersion {
  stocks: number
  themes: number
  leaders: number
  review?: number
  quotes: number
  platforms: number
  breath: number
  algorithm: number
  rotation?: number
}
// ========== 题材指标类型 ==========
interface ThemeMetrics {
  // 基础热度（原有计算）
  heatScore: number
  heatLevel: string
  momentum: number
  trend: number
  acceleration: number
  correlation: number
  relatedThemes: any[]

  // 统计
  stats: {
    stockCount: number
    ztCount: number
    leaderCount: number
  }

  // jxbk 指标（新增）
  jxbk: {
    strength: number // 强度分数
    mainNetInflow: number // 主力净额
    bigMoney300: number // 300W大单
    institutionBuy: number // 机构增仓
    volumeRatio: number // 量比
  }

  lastUpdate: number
}

// ========== 涨停数据扩展类型 ==========
interface LimitUpExtData {
  firstZtTime?: string // 首次涨停时间
  lastZtTime?: string // 最后涨停时间
  boardHeight?: number // 封板高度
  highDays?: number // 连板天数
  fengdan?: number // 封单额（万元）
  maxFengdan?: number // 最大封单（万元）
  leadStatus?: string // 领涨状态（"破板"/"领涨"等）
  leadTimes?: number // 领涨次数
  lianbanStr?: string // 连板描述（"首板"、"2板"等）
  reason?: string // 涨停原因/关联原因
  tags?: Array<{ Name: string }> // 股票标签
  isNew?: boolean // 是否新股/新涨停
}

// ========== 股票扩展数据类型 ==========
interface StockExtData {
  speed?: number // 涨速（%）
  volumeRatio?: number // 量比
  leadTimes?: number // 领涨次数
  leadStatus?: string // 领涨状态（"破板"、"领涨"等）
  lianbanStr?: string // 连板描述（"首板"、"2板"、"3板"等）
  bigMoney300?: number // 300万以上大单（万元）
  popularity?: number // 人气排名
  popularityChange?: number // 人气排名变动
  institutionBuy?: number // 机构增仓（万元）
  mainBuy?: number // 主力买入（万元）
  mainSell?: number // 主力卖出（万元）
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
  fengdan?: number // 封单额（万元）
  maxFengdan?: number // 最大封单（万元）

  // L2 摘要
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

// ========== jxbk 数据类型 ==========

/** jxbk 板块数据（直接从API获取） */
interface JxbkBlockData {
  code: string // 板块代码
  name: string // 板块名称
  strength: number // 强度分数（原始值）
  change: number // 涨幅
  mainNetInflow: number // 主力净额
  bigMoney300: number // 300W大单
  institutionBuy: number // 机构增仓
  volumeRatio: number // 量比
  ztCount: number // 涨停数
}

/** jxbk 股票数据（直接从API获取） */
interface JxbkStockData {
  code: string
  name: string
  change: number // 涨幅
  speed: number // 涨速
  volumeRatio: number // 量比
  mainNetInflow: number // 主力净额
  leadTimes: number // 领次
  leadStatus: string // 领涨状态
  lianban: string // 连板
  bigMoney300: number // 300W大单
  popularity: number // 人气
  popularityChange: number // 变动
  blocks: string[] // 板块列表
  institutionBuy: number // 机构增仓
  mainBuy: number // 主力买入
  mainSell: number // 主力卖出
  fengdan: number // 封单额
  maxFengdan: number // 最大封单
  cirMV: number // 流通市值
}

// ========== 合并后的股票类型（包含所有字段） ==========
export interface MergedStock {
  // ========== 基础字段 ==========
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

  // ========== 平台排名 ==========
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

  // ========== 综合排名 ==========
  compRank?: number
  compScore?: number

  // ========== 时间戳 ==========
  updatedAt?: number
  firstSeen?: number
  lastSeen?: number

  // ========== 平台名称 ==========
  platformName?: string

  // ========== 真龙复盘字段 ==========
  reviewAuthority?: AuthorityClass
  reviewRole?: LeaderRole
  tradeability?: Tradeability
  chaseRisk?: ChaseRisk
  continuousDays?: number

  // ========== 题材数据 ==========
  themes?: any[]

  // ========== 个股扩展字段 ==========
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
  tdxBuyVolume?: number
  tdxSellVolume?: number
  tdxCurrentVolume?: number
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
  fundPenetration?: number
  mainTheme?: string
  themeHeat?: number
  themeLevel?: string

  // ========== 算法元数据 ==========
  algorithmScore?: number
  algorithmVersion?: number
  algorithmId?: string
  lastCalculated?: number

  // ========== 嵌套 RankTrend 分析结果 ========== 
  rankTrend?: RankTrendAnalysisResult
  rankTrendCoverageWarning?: string
}
export type {
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotProjectionMeta,
  SnapshotQueryOptions,
  SnapshotRecord,
  SnapshotSectorRow,
  SnapshotSectorRowQueryOptions,
  SnapshotStockRow,
  SnapshotStockRowQueryOptions,
  SnapshotType,
} from './snapshot/types'

interface DataState {
  // 原始数据
  raw: {
    stocks: any[]
    platforms: Record<string, any>
    themes: any[]
    fullMarket: any[]
  }

  // 实时数据
  realtime: {
    quotes: Map<string, any>
    depth10: Map<string, Depth10Book>
    recentTicks: Map<string, TickTrade[]>
    l2Summary: Map<string, L2Summary>
    lastUpdate: number | null
  }

  // 合并后的展示数据（供UI直接使用）
  merged: {
    stocks: MergedStock[] // 使用扩展后的股票类型
    themes: any[]
  }

  // 龙头数据
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

  // ========== 题材数据 ==========
  theme: {
    // 基础映射（来自 ThemeDataService，只读）
    base: {
      byCode: Map<string, any[]> // 股票 -> 题材列表（静态映射）
      byId: Map<string, any> // 题材ID -> 题材基础信息
      lastUpdate: string | null // 映射文件更新时间
    }

    // 实时指标（由 sectorAnalyzer 计算）
    metrics: {
      byTheme: Map<string, ThemeMetrics> // 题材ID -> 实时指标
      hotList: any[] // 热门题材列表
      rotation: any[] // 轮动数据
      lastUpdate: number | null
    }

    // jxbk 实时数据（来自5000接口）
    jxbk: {
      blocks: JxbkBlockData[] // 板块列表（带强度）
      blockMap: Record<string, JxbkBlockData> // 板块代码映射
      stockMap: Record<string, JxbkStockData> // 股票数据映射
      lastUpdate: number | null
    }

    // 个股联动分析
    correlation: {
      byTheme: Map<string, ThemeCorrelationDetail>
      lastUpdate: number | null
    }
  }

  tck2?: {
    stockHotness: Map<string, number> // 热度值 HotNum
    stockTags: Map<string, Array<{ Name: string }>> // 标签 Tag
    stockReasons: Map<string, string> // 涨停原因
    stockIsNew: Map<string, boolean> // 是否新涨停
    limitUpData: Map<string, LimitUpExtData> // 涨停池扩展数据
    lastUpdate: number | null
  }

  // 分析结果存储
  analysis: {
    breath: {
      sentiment: {
        overall: number
        phase: string // 英文值
        phaseName: string // 中文名
        riskLevel: string
        suggestion: string
        phaseInfo?: any // 阶段完整信息
      } | null
      marketData?: {
        // 添加 marketData 字段定义
        upCount: number
        downCount: number
        ztCount: number
        dtCount: number
        zhaban?: {
          count: number
          rate: number
          fengbanRate: number
          ztCount?: number
        }
        totalAmo: number
        amoDiff?: number
        volumeRatio?: number
        limitData: {
          yiban: number
          erban: number
          sanban: number
          sibanPlus: number
        }
        yesterdayLimit?: {
          total?: number
          ztCount?: number
          dtCount?: number
          bigLossCount?: number
          redCount?: number
          greenCount?: number
          avgChange?: number
          maxChange?: number
          minChange?: number
        }
        indices: {
          sh: { change: number }
          hs300: { change: number }
          zz500: { change: number }
          zz1000: { change: number }
        }
        moneyFlow?: {
          main: number
          retail: number
        }
        cddje?: number
        cddjzb?: number
        yesterdayZtPerformance?: number
        emotionValue?: number
        emotionStatus?: string
        timestamp?: number
        largeCapChange?: number
        microCapChange?: number
        passRate?: {               // 晋级率
          to2: number
          to3: number
          to4: number
        }
      }
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
    algorithm: {
      config: any
      results: Map<string, any>
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

  // ✅ 历史排名数据
  rankHistory: {
    byCode: Map<string, number>
    lastUpdate: number | null
    snapshotDate: string | null
  }

  // 版本控制
  version: DataVersion

  // 元数据
  meta: {
    initialized: boolean
    lastMergeTime: number | null
    marketMode: 'hot' | 'full'
  }
}

/**
 * 数据存储层
 * 职责单一：存储数据、提供访问接口、版本管理
 */
class DataLayer {
  private readonly PRIMARY_DB_NAME = 'DragonBoardData'
  private readonly PRIMARY_DB_VERSION = 9
  private readonly PRIMARY_STORE_NAME = 'snapshots'
  private readonly LEGACY_BACKUP_DB_NAME = 'DragonBoardDataBackup'
  private readonly BUCKET_BACKUP_DB_NAME = 'DragonBoardBucketBackup'
  private readonly BACKUP_DB_VERSION = 5
  private readonly BACKUP_STORE_NAME = 'snapshots_backup'
  private readonly BACKUP_BUCKET_NAME = 'dragon-snapshot-backup'
  private readonly SNAPSHOT_GUARD_MIN_BACKUP = 20
  private readonly SNAPSHOT_GUARD_RATIO = 0.4
  private readonly SNAPSHOT_SYNC_INTERVAL_MS = 5 * 60 * 1000
  private readonly bigOrderData = new Map<
    string,
    {
      orders: BigOrderItem[]
      statistics: BigOrderStatistics | null
      periods: PeriodStatistics[]
      lastUpdate: number
    }
  >()
  private readonly denseOrderAlerts: DenseOrderAlert[] = []
  private readonly snapshotRuntime = new SnapshotRuntime({
    logger: console,
    primaryDbName: this.PRIMARY_DB_NAME,
    primaryDbVersion: this.PRIMARY_DB_VERSION,
    primaryStoreName: this.PRIMARY_STORE_NAME,
    legacyBackupDbName: this.LEGACY_BACKUP_DB_NAME,
    bucketBackupDbName: this.BUCKET_BACKUP_DB_NAME,
    backupDbVersion: this.BACKUP_DB_VERSION,
    backupStoreName: this.BACKUP_STORE_NAME,
    backupBucketName: this.BACKUP_BUCKET_NAME,
    minBackupCount: this.SNAPSHOT_GUARD_MIN_BACKUP,
    abnormalRatio: this.SNAPSHOT_GUARD_RATIO,
    syncIntervalMs: this.SNAPSHOT_SYNC_INTERVAL_MS,
    getStorageBucketManager: () =>
      typeof navigator === 'undefined' ? null : (navigator as any).storageBuckets || null,
    getBuildContext: () => ({
      stocks: this.getStocks() || [],
      depth10ByCode: this.state.realtime.depth10,
      recentTicksByCode: this.state.realtime.recentTicks,
      l2SummaryByCode: this.state.realtime.l2Summary,
      breathData: this.getBreathData(),
      marketData: this.state.analysis.breath?.marketData,
      jxbkBlocks: this.getJxbkBlocksSorted(100),
      jxbkStocks: this.state.theme.jxbk.stockMap || {},
      hotThemes: this.getHotThemes() || [],
      rotationAnalysis: this.state.analysis.rotation?.current || null,
      breathHistory: this.getBreathHistory(),
      breathFactors: this.getBreathFactors(),
      marketMode: this.state.meta.marketMode,
      stocksVersion: this.state.version.stocks,
    }),
  })

  constructor() {
    this.snapshotRuntime.setSqlitePrimaryWriteHandler((bundle) => this.writeSnapshotBundleToSqlitePrimary(bundle))
    this.startTimer()
  }

  private state: DataState = reactive({
    raw: { stocks: [], platforms: {}, themes: [], fullMarket: [] },
    realtime: {
      quotes: new Map(),
      depth10: new Map(),
      recentTicks: new Map(),
      l2Summary: new Map(),
      lastUpdate: null,
    },
    merged: { stocks: [], themes: [] },

    // 龙头数据单独存储
    leader: {
      byCode: new Map(),
      byLevel: {},
      lastUpdate: null,
    },

    review: {
      result: null,
      marketCore: null,
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      battlefields: [],
      transitions: [],
      summaryLines: [],
      lastUpdate: null,
    },

    // ========== 题材数据  ==========
    theme: {
      base: {
        byCode: new Map(),
        byId: new Map(),
        lastUpdate: null,
      },
      metrics: {
        byTheme: new Map(),
        hotList: [],
        rotation: [],
        lastUpdate: null,
      },
      jxbk: {
        blocks: [],
        blockMap: {},
        stockMap: {},
        lastUpdate: null,
      },
      correlation: {
        byTheme: new Map(),
        lastUpdate: null,
      },
    },

    // 分析结果
    analysis: {
      breath: {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      },
      algorithm: {
        config: null,
        results: new Map(),
        lastUpdate: null,
      },
      // ✅ 添加 rotation
      rotation: {
        current: null,
        history: [],
        lastUpdate: null,
      },

      // 预警存储
      alerts: {
        items: [],
        stats: {
          total: 0,
          critical: 0,
          warning: 0,
          info: 0,
          byType: {} as Record<AlertType, number>,
          lastUpdate: 0,
        },
        lastUpdate: null,
      },
    },

    // ✅ 历史排名数据初始化
    rankHistory: {
      byCode: new Map(),
      lastUpdate: null,
      snapshotDate: null,
    },

    version: {
      stocks: 0,
      themes: 0,
      leaders: 0,
      review: 0,
      quotes: 0,
      platforms: 0,
      breath: 0,
      algorithm: 0,
      rotation: 0,
    },

    meta: {
      initialized: false,
      lastMergeTime: null,
      marketMode: 'hot',
    },
  })

  private subscribers = new Map<string, Set<(data: any) => void>>()
  private notifyTimer: ReturnType<typeof setTimeout> | null = null
  private pendingNotify: { path: string; data: any } | null = null

  // ========== 复盘兼容查询（只服务旧入口读取，不再产出龙头结论） ==========

  /**
   * 获取单个龙头信息
   */
  getLeaderByCode(code: string) {
    return this.state.leader.byCode.get(code) || null
  }

  /**
   * 按级别获取龙头
   */
  getLeadersByLevel(level: string) {
    const normalizedLevel = normalizeLeaderRole(level) || level
    return this.state.leader.byLevel[normalizedLevel] || []
  }

  /**
   * 获取所有龙头
   */
  getAllLeaders() {
    return Array.from(this.state.leader.byCode.values())
  }

  updateReviewData(result: DragonReviewResult) {
    const timestamp = Date.now()
    this.state.review = {
      result,
      marketCore: result.marketCore,
      trueLeaders: result.trueLeaders || [],
      heightBoard: result.heightBoard || [],
      attentionBoard: result.attentionBoard || [],
      pseudoLeaderGraveyard: result.pseudoLeaderGraveyard || [],
      battlefields: result.battlefields || [],
      transitions: result.transitions || [],
      summaryLines: result.summaryLines || [],
      lastUpdate: timestamp,
    }

    const compatibilityLeaders = new Map<string, LeaderLookupRecord>()
    const byLevel: Record<string, LeaderLookupRecord[]> = {}

    getReviewRecordPool(result).forEach((leader) => {
      if (compatibilityLeaders.has(leader.code)) return

      const record = toLeaderLookupRecord(leader, timestamp)
      compatibilityLeaders.set(leader.code, record)
      if (!byLevel[record.level]) byLevel[record.level] = []
      byLevel[record.level].push(record)
    })

    this.state.leader = {
      byCode: compatibilityLeaders,
      byLevel,
      lastUpdate: timestamp,
    }

    if (this.state.merged.stocks.length) {
      this.state.merged.stocks = this.state.merged.stocks.map((stock) =>
        applyReviewProjectionToStock(stock, compatibilityLeaders.get(stock.code) || null),
      )
      this.throttledNotify('merged.stocks', this.state.merged.stocks)
    }

    this.state.version.review = (this.state.version.review || 0) + 1
    this.state.version.leaders++
    this.throttledNotify('review.result', result)
    this.throttledNotify('version.review', this.state.version.review)
    this.throttledNotify('version.leaders', this.state.version.leaders)
  }

  getDragonReview(): DragonReviewResult | null {
    return this.state.review.result
  }

  getMarketCore() {
    return this.state.review.marketCore
  }

  getTrueLeaders() {
    return this.state.review.trueLeaders
  }

  getHeightBoard() {
    return this.state.review.heightBoard
  }

  getAttentionBoard() {
    return this.state.review.attentionBoard
  }

  getPseudoLeaderGraveyard() {
    return this.state.review.pseudoLeaderGraveyard
  }

  getReviewBattlefields() {
    return this.state.review.battlefields
  }

  getReviewTransitions() {
    return this.state.review.transitions
  }

  // ========== 题材数据管理 ==========
  /**
   * 更新基础题材映射（来自 ThemeDataService）
   */
  updateThemeBase(data: {
    byCode: Map<string, any[]>
    byId: Map<string, any>
    lastUpdate: string
  }) {
    this.state.theme.base.byCode = data.byCode
    this.state.theme.base.byId = data.byId
    this.state.theme.base.lastUpdate = data.lastUpdate
    this.state.version.themes++
  }

  /**
   * 更新股票对应的题材数据
   * @param updates  { code: string, themes: any[] }[]
   */
  updateStockThemes(
    updates: Array<{
      code: string
      themes: any[]
      mainTheme?: string
      themeHeat?: number
      themeLevel?: string
    }>,
  ) {
    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touchedMergedStocks = false

    updates.forEach(({ code, themes, mainTheme, themeHeat, themeLevel }) => {
      this.state.theme.base.byCode.set(code, themes)

      const stock = stockMap.get(code)
      if (stock) {
        stock.themes = themes
        stock.mainTheme = mainTheme || undefined
        stock.themeHeat = themeHeat ?? 0
        stock.themeLevel = themeLevel || '冷'
        stockMap.set(code, stock)
        touchedMergedStocks = true
      }
    })

    if (touchedMergedStocks) {
      this.state.merged.stocks = Array.from(stockMap.values())
      this.state.version.stocks++
    }

    this.state.version.themes++
  }

  /**
   * 更新热门题材列表
   */
  updateHotThemes(hotThemes: any[]) {
    this.state.theme.metrics.hotList = hotThemes
    this.state.theme.metrics.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新轮动数据
   */
  updateRotation(rotation: any[]) {
    this.state.theme.metrics.rotation = rotation
    this.state.theme.metrics.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新题材指标（包含 jxbk 数据）
   */
  updateThemeMetrics(
    updates: Array<{
      themeId: string
      heatScore: number
      heatLevel: string
      momentum: number
      trend: number
      acceleration: number
      correlation: number
      relatedThemes: any[]
      stats: { stockCount: number; ztCount: number; leaderCount: number }
      jxbk: {
        strength: number
        mainNetInflow: number
        bigMoney300: number
        institutionBuy: number
        volumeRatio: number
      }
    }>,
  ) {
    updates.forEach((update) => {
      this.state.theme.metrics.byTheme.set(update.themeId, {
        ...update,
        lastUpdate: Date.now(),
      })
    })

    this.state.version.themes++
  }

  /**
   * 获取题材指标
   */
  getThemeMetrics(themeId: string): ThemeMetrics | undefined {
    return this.state.theme.metrics.byTheme.get(themeId)
  }

  /**
   * 获取所有题材指标
   */
  getAllThemeMetrics(): Map<string, ThemeMetrics> {
    return this.state.theme.metrics.byTheme
  }

  /**
   * 获取股票的题材数据（从基础映射）
   */
  getStockThemes(code: string) {
    return this.state.theme.base.byCode.get(code) || []
  }

  /**
   * 获取题材详情（从基础映射）
   */
  getThemeById(id: string) {
    return this.state.theme.base.byId.get(id)
  }

  /**
   * 获取热门题材列表
   */
  getHotThemes() {
    return this.state.theme.metrics.hotList
  }

  /**
   * 获取题材轮动数据
   */
  getThemeRotation() {
    return this.state.theme.metrics.rotation
  }

  // ========== jxbk 数据管理 ==========

  /**
   * 更新 jxbk 板块数据
   */
  updateJxbkBlocks(blocks: JxbkBlockData[]) {
    const blockMap: Record<string, JxbkBlockData> = {}
    blocks.forEach((block) => {
      blockMap[block.code] = block
    })

    this.state.theme.jxbk.blocks = blocks
    this.state.theme.jxbk.blockMap = blockMap
    this.state.theme.jxbk.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 更新 jxbk 股票数据
   */
  updateJxbkStocks(stocks: JxbkStockData[]) {
    const stockMap: Record<string, JxbkStockData> = { ...this.state.theme.jxbk.stockMap }
    stocks.forEach((stock) => {
      stockMap[stock.code] = stock
    })

    this.state.theme.jxbk.stockMap = stockMap
    this.state.theme.jxbk.lastUpdate = Date.now()
    this.state.version.themes++
  }

  /**
   * 获取 jxbk 板块数据
   */
  getJxbkBlock(blockCode: string): JxbkBlockData | undefined {
    return this.state.theme.jxbk.blockMap[blockCode]
  }

  /**
   * 获取 jxbk 股票数据
   */
  getJxbkStock(stockCode: string): JxbkStockData | undefined {
    return this.state.theme.jxbk.stockMap[stockCode]
  }

  /**
   * 获取所有 jxbk 板块（按强度排序）
   */
  getJxbkBlocksSorted(limit?: number): JxbkBlockData[] {
    const blocks = [...this.state.theme.jxbk.blocks]
    blocks.sort((a, b) => b.strength - a.strength)
    return limit ? blocks.slice(0, limit) : blocks
  }

  // ========== 题材个股联动管理 ==========
  updateThemeCorrelation(themeId: string, correlation: ThemeCorrelationDetail) {
    if (!this.state.theme.correlation) {
      this.state.theme.correlation = { byTheme: new Map(), lastUpdate: null }
    }
    this.state.theme.correlation.byTheme.set(themeId, correlation)
    this.state.theme.correlation.lastUpdate = Date.now()
    this.state.version.themes++
  }

  // 获取方法
  getThemeCorrelation(themeId: string): ThemeCorrelationDetail | undefined {
    return this.state.theme.correlation?.byTheme.get(themeId)
  }

  // ========== 股票数据管理 ==========
  /**
   * 更新股票数据 - 供 dataLoader 调用
   */
  updateStocks(data: any[]) {
    // 保存原始数据
    this.state.raw.stocks = data.map((s) => ({
      ...stripLegacyLeaderFields(s),
      timestamp: Date.now(),
    }))

    this.state.version.stocks++
  }

  /**
   * 获取合并后的股票数据（供UI使用）
   */
  getStocks(): MergedStock[] {
    return this.state.merged.stocks
  }

  getMergedStocks(): MergedStock[] {
    return this.getStocks()
  }

  /**
   * 获取单个股票
   */
  getStock(code: string): MergedStock | null {
    return this.state.merged.stocks.find((s) => s.code === code) || null
  }

  /**
   * 获取股票带版本信息
   */
  getStocksWithVersion() {
    return {
      stocks: this.state.merged.stocks,
      version: this.state.version.stocks,
    }
  }

  /**
   * 批量获取股票
   */
  getStocksByCodes(codes: string[]): MergedStock[] {
    return this.state.merged.stocks.filter((s) => codes.includes(s.code))
  }

  // ========== 批量更新股票扩展数据 ==========
  /**
   * 批量更新股票的扩展数据（涨速、量比、人气等）
   */
  updateStockExtData(updates: Array<Partial<StockExtData> & { code: string }>) {
    if (!updates.length) return

    const stockMap = new Map(this.state.merged.stocks.map((s) => [s.code, s]))

    updates.forEach((update) => {
      const stock = stockMap.get(update.code)
      if (stock) {
        Object.assign(stock, update)
        stockMap.set(update.code, stock)
      }
    })

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
  }

  // ========== 获取股票扩展字段方法 ==========

  getStockSpeed(code: string): number | undefined {
    return this.getStock(code)?.speed
  }

  getStockVolumeRatio(code: string): number | undefined {
    return this.getStock(code)?.volumeRatio
  }

  getStockLeadStatus(code: string): string | undefined {
    return this.getStock(code)?.leadStatus
  }

  getStockPopularity(code: string): number | undefined {
    return this.getStock(code)?.popularity
  }

  getStockFengdan(code: string): number | undefined {
    return this.getStock(code)?.fengdan
  }

  getStockInstitutionBuy(code: string): number | undefined {
    return this.getStock(code)?.institutionBuy
  }

  // ========== 平台数据管理 ==========

  updatePlatforms(data: Record<string, any>) {
    this.state.raw.platforms = data
    this.state.version.platforms++
    this.throttledNotify('raw.platforms', data)
  }

  getRawPlatforms() {
    return this.state.raw.platforms
  }

  getPlatformData(platform: string) {
    return this.state.raw.platforms[platform] || []
  }

  // ========== 原始题材数据 ==========

  updateRawThemes(data: any[]) {
    this.state.raw.themes = data
    this.state.version.themes++
    this.throttledNotify('raw.themes', data)
  }

  getRawThemes() {
    return this.state.raw.themes
  }

  // ========== 实时行情数据 ==========
  updateQuotesBatch(changes: any[]) {
    if (!changes?.length) return

    changes.forEach((change) => {
      if (!change?.code) return
      const existing = this.state.realtime.quotes.get(change.code) || {}
      this.state.realtime.quotes.set(change.code, {
        ...existing,
        ...change,
        timestamp: Date.now(),
      })
    })

    this.state.realtime.lastUpdate = Date.now()
    this.state.version.quotes++

    this.throttledNotify('quotes:batch', { count: changes.length })
  }

  applyRealtimeQuoteBatch(changes: any[]) {
    if (!changes?.length) return

    this.updateQuotesBatch(changes)

    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touched = false

    changes.forEach((change) => {
      const code = String(change?.code || '')
      if (!code) return

      const stock = stockMap.get(code)
      if (!stock) return

      stock.price = Number(change.price ?? change.lastPrice ?? stock.price) || 0
      stock.change = Number(change.change ?? change.changePct ?? stock.change) || 0
      const nextSpeed = Number(change.speed)
      if (Number.isFinite(nextSpeed)) {
        stock.speed = nextSpeed
      }
      stock.volume = Number(change.volume ?? stock.volume) || 0
      stock.turnover = Number(change.turnover ?? change.amount ?? stock.turnover) || 0
      stock.turnoverRate = Number(change.turnoverRate ?? stock.turnoverRate) || 0
      stock.zlje = this.pickQuoteNumber(change.zlje, stock.zlje)
      stock.zljzb = this.pickQuoteNumber(change.zljzb, stock.zljzb)
      stock.cddje = this.pickQuoteNumber(change.cddje, stock.cddje)
      stock.cddjzb = this.pickQuoteNumber(change.cddjzb, stock.cddjzb)
      stock.tdxBuyVolume = this.pickQuoteNumber(change.tdxBuyVolume, stock.tdxBuyVolume)
      stock.tdxSellVolume = this.pickQuoteNumber(change.tdxSellVolume, stock.tdxSellVolume)
      stock.tdxCurrentVolume = this.pickQuoteNumber(change.tdxCurrentVolume, stock.tdxCurrentVolume)
      if (typeof change.moneyFlowSource === 'string' && change.moneyFlowSource.trim()) {
        stock.moneyFlowSource = change.moneyFlowSource
      }
      if (typeof change.moneyFlowEstimated === 'boolean') {
        stock.moneyFlowEstimated = change.moneyFlowEstimated
      }
      stock.updatedAt = Date.now()
      if (typeof change.name === 'string' && change.name.trim()) {
        stock.name = change.name.trim()
      }

      stockMap.set(code, stock)
      touched = true
    })

    if (!touched) return

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  private pickQuoteNumber(nextValue: unknown, currentValue: unknown): number {
    const nextNumber = Number(nextValue)
    const currentNumber = Number(currentValue)

    if (Number.isFinite(nextNumber) && nextNumber !== 0) return nextNumber
    if (Number.isFinite(currentNumber)) return currentNumber
    if (Number.isFinite(nextNumber)) return nextNumber
    return 0
  }

  updateQuote(code: string, data: any) {
    this.updateQuotesBatch([{ code, ...data }])
  }

  getQuote(code: string) {
    return this.state.realtime.quotes.get(code)
  }

  getQuotes(codes: string[]) {
    const result = new Map()
    codes.forEach((c) => {
      const q = this.state.realtime.quotes.get(c)
      if (q) result.set(c, q)
    })
    return result
  }

  getAllQuotes() {
    return Array.from(this.state.realtime.quotes.values())
  }

  getQuotesCount() {
    return this.state.realtime.quotes.size
  }

  getQuotesLastUpdate() {
    return this.state.realtime.lastUpdate
  }

  updateDepth10Batch(changes: Depth10Book[]) {
    if (!changes?.length) return

    changes.forEach((change) => {
      if (!change?.code) return
      this.state.realtime.depth10.set(change.code, {
        ...change,
        bids: [...(change.bids || [])].slice(0, 10),
        asks: [...(change.asks || [])].slice(0, 10),
        timestamp: Date.now(),
      })
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.depth10', { count: changes.length })
  }

  getDepth10(code: string): Depth10Book | null {
    return this.state.realtime.depth10.get(code) || null
  }

  updateRecentTicksBatch(changes: Array<{ code: string; items: TickTrade[] }>) {
    if (!changes?.length) return

    const now = Date.now()
    changes.forEach((change) => {
      const code = String(change?.code || '')
      if (!code) return

      const existing = this.state.realtime.recentTicks.get(code) || []
      const next = existing
        .filter((item) => now - Number(item?.timestamp || 0) <= 60_000)
        .concat(Array.isArray(change.items) ? change.items : [])
        .slice(-300)

      this.state.realtime.recentTicks.set(code, next)
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.ticks', { count: changes.length })
  }

  getRecentTicks(code: string): TickTrade[] {
    return [...(this.state.realtime.recentTicks.get(code) || [])]
  }

  updateL2SummaryBatch(changes: Array<Partial<L2Summary> & { code: string }>) {
    if (!changes?.length) return

    const stockMap = new Map(this.state.merged.stocks.map((stock) => [stock.code, stock]))
    let touched = false

    changes.forEach((change) => {
      if (!change?.code) return

      const existing = this.state.realtime.l2Summary.get(change.code)
      const nextSummary: L2Summary = {
        code: change.code,
        bid1Price: Number(change.bid1Price ?? existing?.bid1Price) || 0,
        bid1Volume: Number(change.bid1Volume ?? existing?.bid1Volume) || 0,
        ask1Price: Number(change.ask1Price ?? existing?.ask1Price) || 0,
        ask1Volume: Number(change.ask1Volume ?? existing?.ask1Volume) || 0,
        spread: Number(change.spread ?? existing?.spread) || 0,
        bid10Total: Number(change.bid10Total ?? existing?.bid10Total) || 0,
        ask10Total: Number(change.ask10Total ?? existing?.ask10Total) || 0,
        depthImbalance: Number(change.depthImbalance ?? existing?.depthImbalance) || 0,
        tickBuyVolume: Number(change.tickBuyVolume ?? existing?.tickBuyVolume) || 0,
        tickSellVolume: Number(change.tickSellVolume ?? existing?.tickSellVolume) || 0,
        tickBuyCount: Number(change.tickBuyCount ?? existing?.tickBuyCount) || 0,
        tickSellCount: Number(change.tickSellCount ?? existing?.tickSellCount) || 0,
        lastTradePrice: Number(change.lastTradePrice ?? existing?.lastTradePrice) || 0,
        lastTradeVolume: Number(change.lastTradeVolume ?? existing?.lastTradeVolume) || 0,
        timestamp: Number(change.timestamp ?? existing?.timestamp) || Date.now(),
      }

      this.state.realtime.l2Summary.set(change.code, nextSummary)

      const stock = stockMap.get(change.code)
      if (!stock) return

      Object.assign(stock, nextSummary)
      stock.updatedAt = Date.now()
      stockMap.set(change.code, stock)
      touched = true
    })

    this.state.realtime.lastUpdate = Date.now()
    this.throttledNotify('realtime.l2Summary', { count: changes.length })

    if (!touched) return

    this.state.merged.stocks = Array.from(stockMap.values())
    this.state.version.stocks++
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  getL2Summary(code: string): L2Summary | null {
    return this.state.realtime.l2Summary.get(code) || null
  }

  //=======龙息分析服务=========
  updateBreathData(data: any) {
    if (!this.state.analysis) this.state.analysis = {} as any

    if (!this.state.analysis.breath) {
      this.state.analysis.breath = {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      }
    }

    // 更新情绪数据
    this.state.analysis.breath.sentiment = {
      overall: data.sentiment.overall,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
      riskLevel: data.sentiment.riskLevel,
      suggestion: data.sentiment.suggestion,
      phaseInfo: data.sentiment.phaseInfo,
    }

    // 更新市场数据 - 确保包含所有字段
    this.state.analysis.breath.marketData = {
      upCount: data.marketData.upCount || 0,
      downCount: data.marketData.downCount || 0,
      ztCount: data.marketData.ztCount || 0,
      dtCount: data.marketData.dtCount || 0,
      zhaban: data.marketData.zhaban || {},
      totalAmo: data.marketData.totalAmo || 0,
      amoDiff: data.marketData.amoDiff || 0,
      volumeRatio: data.marketData.volumeRatio || 0,
      limitData: data.marketData.limitData || { yiban: 0, erban: 0, sanban: 0, sibanPlus: 0 },
      yesterdayLimit: data.marketData.yesterdayLimit || {},
      indices: data.marketData.indices || {},
      moneyFlow: data.marketData.moneyFlow || { main: 0, retail: 0 },
      cddje: data.marketData.cddje || 0,
      cddjzb: data.marketData.cddjzb || 0,
      yesterdayZtPerformance: data.marketData.yesterdayZtPerformance || 0,
      emotionValue: data.marketData.emotionValue || 0,
      emotionStatus: data.marketData.emotionStatus || '震荡',
      timestamp: data.marketData.timestamp || Date.now(),
      largeCapChange: data.marketData.largeCapChange || 0,  // 大票
      microCapChange: data.marketData.microCapChange || 0,   // 微盘
      passRate: data.marketData.passRate || { to2: 0, to3: 0, to4: 0 }, // 晋级率
    }

    // 更新因子数据
    if (data.factors) {
      this.state.analysis.breath.factors = data.factors
    }

    this.state.analysis.breath.lastUpdate = data.timestamp

    // 保存历史
    if (!this.state.analysis.breath.history) {
      this.state.analysis.breath.history = []
    }
    this.state.analysis.breath.history.push({
      timestamp: data.timestamp,
      phase: data.sentiment.phase,
      phaseName: data.sentiment.phaseName,
      riskLevel: data.sentiment.riskLevel,
    })
    if (this.state.analysis.breath.history.length > 100) {
      this.state.analysis.breath.history.shift()
    }
  }

  getBreathFactors() {
    return this.state.analysis.breath?.factors || []
  }

  getBreathData(): BreathData['sentiment'] | null {
    return this.state.analysis.breath.sentiment
  }

  getBreathHistory() {
    return this.state.analysis.breath.history
  }

  // ========== 算法结果管理 ==========
  updateAlgorithmResult(code: string, result: any) {
    if (!this.state.analysis.algorithm) {
      this.state.analysis.algorithm = {
        config: null, // ✅ 添加 config 属性
        results: new Map(),
        lastUpdate: null,
      }
    }

    this.state.analysis.algorithm.results.set(code, result)
    this.state.analysis.algorithm.lastUpdate = Date.now()
    this.state.version.algorithm = (this.state.version.algorithm || 0) + 1
  }

  getAlgorithmResult(code: string) {
    return this.state.analysis?.algorithm?.results?.get(code)
  }

  updateAlgorithmConfig(config: any) {
    this.state.analysis.algorithm.config = {
      ...config,
      timestamp: Date.now(),
    }
    this.state.version.algorithm = (this.state.version.algorithm || 0) + 1
    this.throttledNotify('analysis.algorithm.config', config)
  }

  getAlgorithmConfig() {
    return this.state.analysis.algorithm.config
  }

  // ========== 题材库数据管理 ==========

  private initTck2Store() {
    this.state.tck2 = {
      stockHotness: new Map(),
      stockTags: new Map(),
      stockReasons: new Map(),
      stockIsNew: new Map(),
      limitUpData: new Map<string, LimitUpExtData>(),
      lastUpdate: Date.now(),
    }
  }

  updateStockHotness(updates: Array<{ code: string; hotness: number }>) {
    if (!this.state.tck2) this.initTck2Store()
    updates.forEach(({ code, hotness }) => {
      this.state.tck2!.stockHotness.set(code, hotness)
    })
    this.throttledNotify('tck2.hotness', { count: updates.length })
  }

  updateStockTags(updates: Array<{ code: string; tags: Array<{ Name: string }> }>) {
    if (!this.state.tck2) this.initTck2Store()
    updates.forEach(({ code, tags }) => {
      this.state.tck2!.stockTags.set(code, tags)
    })
    this.throttledNotify('tck2.tags', { count: updates.length })
  }

  updateLimitUpData(
    updates: Array<{
      code: string
      reason?: string
      isNew?: boolean
      firstZtTime?: string
      lastZtTime?: string
      boardHeight?: number
      highDays?: number
      fengdan?: number
      maxFengdan?: number
      leadStatus?: string
      leadTimes?: number
      lianbanStr?: string
      tags?: Array<{ Name: string }>
    }>,
  ) {
    if (!this.state.tck2) this.initTck2Store()

    updates.forEach(({ code, reason, isNew, tags, ...rest }) => {
      // 更新 reason
      if (reason !== undefined) this.state.tck2!.stockReasons.set(code, reason)

      // 更新 isNew
      if (isNew !== undefined) this.state.tck2!.stockIsNew.set(code, isNew)

      // ✅ 更新 tags
      if (tags !== undefined) {
        this.state.tck2!.stockTags.set(code, tags)
      }

      // 构建 limitUpData 数据
      const limitData: any = { ...rest }
      if (tags !== undefined) {
        limitData.tags = tags
      }
      if (reason !== undefined) {
        limitData.reason = reason
      }

      // 更新 limitUpData
      const existing = this.state.tck2!.limitUpData.get(code) || {}
      this.state.tck2!.limitUpData.set(code, {
        ...existing,
        ...limitData,
      })
    })

    this.throttledNotify('tck2.limitup', { count: updates.length })
  }

  getStockHotness(code: string): number | undefined {
    const stored = this.state.tck2?.stockHotness.get(code)
    if (stored !== undefined) return stored
    return this.state.merged.stocks.find((stock) => stock.code === code)?.hotness
  }

  getStockTags(code: string): Array<{ Name: string }> | undefined {
    return this.state.tck2?.stockTags.get(code)
  }

  getStockReason(code: string): string | undefined {
    return this.state.tck2?.stockReasons.get(code)
  }

  getStockIsNew(code: string): boolean | undefined {
    return this.state.tck2?.stockIsNew.get(code)
  }

  getLimitUpData(code: string): LimitUpExtData | undefined {
    return this.state.tck2?.limitUpData.get(code)
  }

  /**
   * 手动设置合并后的股票数据
   * 供 dataLoader 调用，更新 merged.stocks
   */
  setMergedStocks(stocks: any[]) {
    const normalizedStocks = (stocks as MergedStock[]).map((stock) => {
      const normalized = stripLegacyLeaderFields(stock)
      if ('rankTrend' in normalized) {
        applyRankTrendAnalysis(normalized, normalized.rankTrend ?? null)
      }
      return applyReviewProjectionToStock(
        normalized,
        this.state.leader.byCode.get(normalized.code) || null,
      )
    })

    this.state.merged.stocks = normalizedStocks
    this.state.version.stocks++
    this.state.meta.lastMergeTime = Date.now()
    this.throttledNotify('merged.stocks', this.state.merged.stocks)
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  // ========== 工具方法 ==========

  hasStock(code: string) {
    return this.state.merged.stocks.some((s) => s.code === code)
  }

  getVersion() {
    return { ...this.state.version }
  }

  getLastMergeTime() {
    return this.state.meta.lastMergeTime
  }

  refreshStocksVersion() {
    this.state.version.stocks++
    this.throttledNotify('version.stocks', this.state.version.stocks)
  }

  bumpLeadersVersion() {
    this.state.version.leaders++
    this.throttledNotify('version.leaders', this.state.version.leaders)
  }

  // ========== 初始化状态 ==========

  isInitialized() {
    return this.state.meta.initialized
  }

  setInitialized(init = true) {
    this.state.meta.initialized = init
  }

  // ========== 订阅机制 ==========

  subscribe(path: string, callback: (data: any) => void) {
    if (!this.subscribers.has(path)) {
      this.subscribers.set(path, new Set())
    }
    this.subscribers.get(path)!.add(callback)
    return () => this.subscribers.get(path)?.delete(callback)
  }

  once(path: string, callback: (data: any) => void) {
    const unsubscribe = this.subscribe(path, (data) => {
      unsubscribe()
      callback(data)
    })
  }

  async waitFor(path: string, timeout = 10000): Promise<any> {
    const data = this.getPathData(path)
    if (data) return data

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        unsubscribe()
        reject(new Error(`等待 ${path} 超时`))
      }, timeout)

      const unsubscribe = this.subscribe(path, (data) => {
        clearTimeout(timer)
        unsubscribe()
        resolve(data)
      })
    })
  }

  private getPathData(path: string): any {
    return path.split('.').reduce((obj: any, key: string) => obj?.[key], this.state)
  }

  private throttledNotify(path: string, data: any) {
    this.pendingNotify = { path, data }
    if (this.notifyTimer) return

    this.notifyTimer = setTimeout(() => {
      if (this.pendingNotify) {
        this.subscribers.get(this.pendingNotify.path)?.forEach((cb) => {
          try {
            cb(this.pendingNotify!.data)
          } catch (error) {
            // ✅ 添加 error 参数
            console.warn('[DataLayer] 通知回调失败:', error)
          }
        })
        this.pendingNotify = null
      }
      this.notifyTimer = null
    }, 50)
  }

  // ========== 轮动数据管理 ==========

  updateRotationAnalysis(analysis: RotationAnalysis) {
    this.state.analysis.rotation.current = analysis
    this.state.analysis.rotation.history.push(analysis)
    if (this.state.analysis.rotation.history.length > 100) {
      this.state.analysis.rotation.history.shift()
    }
    this.state.analysis.rotation.lastUpdate = Date.now()
    this.state.version.rotation = (this.state.version.rotation || 0) + 1
    this.throttledNotify('analysis.rotation', analysis)
  }

  getCurrentRotation(): RotationAnalysis | null {
    return this.state.analysis.rotation.current
  }

  getRotationHistory(limit?: number): RotationAnalysis[] {
    const history = this.state.analysis.rotation.history
    return limit ? history.slice(-limit) : [...history]
  }

  // ========== 大单数据管理 ==========
  updateBigOrderData(
    stockCode: string,
    orders: BigOrderItem[],
    statistics: BigOrderStatistics,
    periods: PeriodStatistics[] = [],
  ) {
    this.bigOrderData.set(stockCode, {
      orders: [...orders],
      statistics,
      periods: [...periods],
      lastUpdate: Date.now(),
    })
    this.throttledNotify(`bigOrder.${stockCode}`, this.bigOrderData.get(stockCode))
  }

  getBigOrderData(stockCode: string) {
    return this.bigOrderData.get(stockCode) || null
  }

  getBigOrders(stockCode?: string): BigOrderItem[] {
    if (stockCode) {
      return [...(this.bigOrderData.get(stockCode)?.orders || [])]
    }
    return Array.from(this.bigOrderData.values()).flatMap((entry) => entry.orders)
  }

  getBigOrderStatistics(stockCode: string): BigOrderStatistics | null {
    return this.bigOrderData.get(stockCode)?.statistics || null
  }

  getBigOrderPeriods(stockCode: string): PeriodStatistics[] {
    return [...(this.bigOrderData.get(stockCode)?.periods || [])]
  }

  addDenseOrderAlert(alert: DenseOrderAlert) {
    this.denseOrderAlerts.unshift(alert)
    if (this.denseOrderAlerts.length > 200) {
      this.denseOrderAlerts.pop()
    }
    this.throttledNotify('bigOrder.denseAlerts', this.denseOrderAlerts)
  }

  getDenseOrderAlerts(limit?: number): DenseOrderAlert[] {
    return limit ? this.denseOrderAlerts.slice(0, limit) : [...this.denseOrderAlerts]
  }

  // ========== 预警数据管理 ==========
  addAlert(alert: StockAlert) {
    this.state.analysis.alerts.items.unshift(alert)
    if (this.state.analysis.alerts.items.length > ALERT_CONFIG.MAX_ALERTS) {
      this.state.analysis.alerts.items.pop()
    }
    this.updateAlertStats()
    this.state.analysis.alerts.lastUpdate = Date.now()
    this.throttledNotify('analysis.alerts', alert)
  }

  getAlerts(limit?: number): StockAlert[] {
    const items = this.state.analysis.alerts.items
    return limit ? items.slice(0, limit) : [...items]
  }

  getUnreadAlerts(): StockAlert[] {
    return this.state.analysis.alerts.items.filter((a) => a.status === 'pending')
  }

  markAlertAsRead(alertId: string) {
    const alert = this.state.analysis.alerts.items.find((a) => a.id === alertId)
    if (alert && alert.status === 'pending') {
      alert.status = 'read'
      alert.readTime = Date.now()
      this.updateAlertStats()
    }
  }

  private updateAlertStats() {
    const items = this.state.analysis.alerts.items
    const stats = {
      total: items.length,
      critical: items.filter((a) => a.level === 'critical').length,
      warning: items.filter((a) => a.level === 'warning').length,
      info: items.filter((a) => a.level === 'info').length,
      byType: {} as Record<string, number>,
      lastUpdate: Date.now(),
    }
    items.forEach((alert) => {
      stats.byType[alert.type] = (stats.byType[alert.type] || 0) + 1
    })
    this.state.analysis.alerts.stats = stats
  }

  getStats() {
    const now = Date.now()
    return {
      quotes: {
        count: this.state.realtime.quotes.size,
        age: this.state.realtime.lastUpdate
          ? ((now - this.state.realtime.lastUpdate) / 1000).toFixed(1) + 's'
          : 'N/A',
        lastUpdate: this.state.realtime.lastUpdate,
      },
      depth10: {
        count: this.state.realtime.depth10.size,
      },
      recentTicks: {
        codes: this.state.realtime.recentTicks.size,
      },
      versions: { ...this.state.version },
    }
  }

  // ========== 重置 ==========

  reset() {
    this.state.raw = { stocks: [], platforms: {}, themes: [], fullMarket: [] }
    this.state.realtime = {
      quotes: new Map(),
      depth10: new Map(),
      recentTicks: new Map(),
      l2Summary: new Map(),
      lastUpdate: null,
    }
    this.state.merged = { stocks: [], themes: [] }
    this.state.leader = {
      byCode: new Map(),
      byLevel: {},
      lastUpdate: null,
    }
    this.state.review = {
      result: null,
      marketCore: null,
      trueLeaders: [],
      heightBoard: [],
      attentionBoard: [],
      pseudoLeaderGraveyard: [],
      battlefields: [],
      transitions: [],
      summaryLines: [],
      lastUpdate: null,
    }
    this.state.theme = {
      base: {
        byCode: new Map(),
        byId: new Map(),
        lastUpdate: null,
      },
      metrics: {
        byTheme: new Map(),
        hotList: [],
        rotation: [],
        lastUpdate: null,
      },
      jxbk: {
        blocks: [],
        blockMap: {},
        stockMap: {},
        lastUpdate: null,
      },
      correlation: {
        byTheme: new Map(),
        lastUpdate: null,
      },
    }
    this.state.analysis = {
      breath: {
        sentiment: null,
        marketData: undefined,
        factors: undefined,
        history: [],
        lastUpdate: null,
      },
      algorithm: {
        config: null,
        results: new Map(),
        lastUpdate: null,
      },
      rotation: {
        current: null,
        history: [],
        lastUpdate: null,
      },
      alerts: {
        items: [],
        stats: {
          total: 0,
          critical: 0,
          warning: 0,
          info: 0,
          byType: {
            leader_fall: 0,
            leader_emerge: 0,
            batch_limit_up: 0,
            batch_explode: 0,
            strength_surge: 0,
            strength_plunge: 0,
            money_flow: 0,
            volume_surge: 0,
            rocket_launch: 0,
            waterfall_dive: 0,
            fengdan_drop: 0,
          },
          lastUpdate: 0,
        },
        lastUpdate: null,
      },
    }

    this.state.rankHistory = {
      byCode: new Map(),
      lastUpdate: null,
      snapshotDate: null,
    }

    this.state.version = {
      stocks: 0,
      themes: 0,
      leaders: 0,
      review: 0,
      quotes: 0,
      platforms: 0,
      breath: 0,
      algorithm: 0,
      rotation: 0,
    }
    this.state.meta = {
      initialized: false,
      lastMergeTime: null,
      marketMode: 'hot',
    }
    this.state.tck2 = undefined
  }

  async saveQuarterHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    return this.snapshotRuntime.saveQuarterHourSnapshot(snapshotTime)
  }

  async saveHalfHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    return this.snapshotRuntime.saveHalfHourSnapshot(snapshotTime)
  }

  async saveHourlySnapshot(snapshotTime?: Date): Promise<boolean> {
    return this.snapshotRuntime.saveHourlySnapshot(snapshotTime)
  }

  generateDailySnapshot(snapshotTime: Date = new Date()): any {
    return this.snapshotRuntime.generateDailySnapshot(snapshotTime)
  }

  exportDailySnapshot(): string {
    return this.snapshotRuntime.exportDailySnapshot()
  }

  async exportStockQuarterSnapshots(stockCode: string, stockName: string = ''): Promise<boolean> {
    return this.snapshotRuntime.exportStockQuarterSnapshots(stockCode, stockName)
  }

  async exportSnapshotToExcel(
    snapshotId: string,
    options?: {
      sheets?: ('hotlist' | 'sectors' | 'sentiment' | 'market')[]
      filename?: string
    },
  ): Promise<boolean> {
    return this.snapshotRuntime.exportSnapshotToExcel(snapshotId, options)
  }

  async exportSnapshotsRangeToExcel(startDate: string, endDate: string): Promise<boolean> {
    return this.snapshotRuntime.exportSnapshotsRangeToExcel(startDate, endDate)
  }

  async saveDailySnapshot(snapshotTime?: Date): Promise<boolean> {
    return this.snapshotRuntime.saveDailySnapshot(snapshotTime)
  }

  async listSnapshots(options: SnapshotQueryOptions = {}): Promise<SnapshotRecord[]> {
    const remote = await this.listRemoteSnapshots(options)
    if (remote) {
      return this.filterRemoteSnapshotsByCoverage(remote, options)
    }
    return this.snapshotRuntime.listSnapshots(options)
  }

  async getSnapshotById(id: string): Promise<SnapshotRecord | null> {
    const remote = await this.getRemoteSnapshotById(id)
    if (remote !== undefined) return remote
    return this.snapshotRuntime.getSnapshotById(id)
  }

  async getTradingDateSnapshot(type: SnapshotType, tradingDate: string): Promise<SnapshotRecord | null> {
    const snapshots = await this.listSnapshots({ type, tradingDate, sort: 'desc', limit: 1 })
    return snapshots[0] || null
  }

  async listSnapshotFrames(
    options: SnapshotFrameQueryOptions | SnapshotQueryOptions = {},
  ): Promise<SnapshotFrameRow[]> {
    const remoteBundles = await this.listRemoteSnapshotFrameBundles(options as SnapshotFrameQueryOptions)
    if (remoteBundles) {
      return remoteBundles.map((bundle) => this.snapshotFrameRowFromBundle(bundle))
    }
    return this.snapshotRuntime.listSnapshotFrames(options as SnapshotFrameQueryOptions)
  }

  async listSnapshotStockRows(
    options: SnapshotStockRowQueryOptions | SnapshotQueryOptions = {},
  ): Promise<SnapshotStockRow[]> {
    const remote = await this.listRemoteSnapshotStockRows(options as SnapshotStockRowQueryOptions)
    if (remote) return remote
    return this.snapshotRuntime.listSnapshotStockRows(options as SnapshotStockRowQueryOptions)
  }

  async listSnapshotSectorRows(
    options: SnapshotSectorRowQueryOptions | SnapshotQueryOptions = {},
  ): Promise<SnapshotSectorRow[]> {
    const remote = await this.listRemoteSnapshotSectorRows(options as SnapshotSectorRowQueryOptions)
    if (remote) return remote
    return this.snapshotRuntime.listSnapshotSectorRows(options as SnapshotSectorRowQueryOptions)
  }

  async getSnapshotProjectionMeta(): Promise<SnapshotProjectionMeta | null> {
    return this.snapshotRuntime.getSnapshotProjectionMeta()
  }

  async rebuildSnapshotProjectionStores(
    options: SnapshotQueryOptions = {},
  ): Promise<SnapshotProjectionRewriteResult> {
    return this.snapshotRuntime.rebuildSnapshotProjectionStores(options)
  }

  async alignSnapshotBackups(
    options?: SnapshotQueryOptions & { includeCloud?: boolean },
  ): Promise<SnapshotBackupAlignmentResult> {
    return this.snapshotRuntime.alignSnapshotBackups(options)
  }

  async compactSnapshotRawRecords(
    options: SnapshotQueryOptions = {},
  ): Promise<SnapshotRawCompactionResult> {
    return this.snapshotRuntime.compactSnapshotRawRecords(options)
  }

  async runSnapshotStorageMaintenance(
    options?: SnapshotQueryOptions & { includeCloud?: boolean },
  ): Promise<SnapshotStorageMaintenanceResult> {
    return this.snapshotRuntime.runSnapshotStorageMaintenance(options)
  }

  async cleanupInvalidRuntimeSnapshots(
    options: SnapshotQueryOptions = {},
  ): Promise<SnapshotPollutionCleanupResult> {
    return this.snapshotRuntime.cleanupInvalidRuntimeSnapshots(options)
  }

  async getStockVolumeHistory(
    codes: string[],
    options?: { anchorTradingDate?: string; lookbackDays?: number },
  ): Promise<Map<string, number[]>> {
    return this.snapshotRuntime.getStockVolumeHistory(codes, options)
  }

  // 正式聚合读口：把 frame/stock/sector 三张读模型表拼成消费方可直接使用的 bundle。
  async listSnapshotFrameBundles(
    options: SnapshotFrameQueryOptions | SnapshotQueryOptions = {},
  ): Promise<SnapshotFrameBundle[]> {
    const remoteBundles = await this.listRemoteSnapshotFrameBundles(options as SnapshotFrameQueryOptions)
    if (remoteBundles) {
      return remoteBundles
    }

    const frames = await this.listSnapshotFrames(options)
    if (frames.length === 0) return []

    const stockRowsBySnapshotId = new Map<string, SnapshotStockRow[]>()
    const sectorRowsBySnapshotId = new Map<string, SnapshotSectorRow[]>()

    await Promise.all(
      frames.map(async (frame) => {
        const [rows, entities] = await Promise.all([
          this.listSnapshotStockRows({ snapshotId: frame.snapshotId, sort: 'asc' }),
          this.listSnapshotSectorRows({ snapshotId: frame.snapshotId, sort: 'asc' }),
        ])
        stockRowsBySnapshotId.set(frame.snapshotId, rows)
        sectorRowsBySnapshotId.set(frame.snapshotId, entities)
      }),
    )

    return frames.map((frame) => {
      const rows = stockRowsBySnapshotId.get(frame.snapshotId) || []
      const entities = sectorRowsBySnapshotId.get(frame.snapshotId) || []
      const sectors = entities
        .filter((row) => row.entityType === 'sector')
        .map((row) => ({
          code: row.entityCode || row.entityKey,
          name: row.entityName,
          themeName: row.entityName,
          strength: row.strength || 0,
          heatScore: row.heatScore || 0,
          heatLevel: row.heatLevel,
          change: row.change || 0,
          mainNetInflow: row.mainNetInflow || 0,
          netInflow: row.netInflow || 0,
          bigMoney300: row.bigMoney300 || 0,
          institutionBuy: row.institutionBuy || 0,
          volumeRatio: row.volumeRatio || 0,
          ztCount: row.ztCount || 0,
          leaderCount: row.leaderCount || 0,
        }))
      const hotThemes = entities
        .filter((row) => row.entityType === 'hot_theme')
        .map((row) => ({
          id: row.entityKey,
          name: row.entityName,
          themeName: row.entityName,
          heatScore: row.heatScore || 0,
          heatLevel: row.heatLevel,
          strength: row.strength || 0,
          change: row.change || 0,
          mainNetInflow: row.mainNetInflow || 0,
          netInflow: row.netInflow || 0,
          ztCount: row.ztCount || 0,
          leaderCount: row.leaderCount || 0,
        }))
      const mainLines = entities
        .filter((row) => row.entityType === 'rotation_main_line')
        .map((row) => ({
          name: row.entityName,
          themeName: row.entityName,
          strength: row.strength || 0,
          heatScore: row.heatScore || 0,
          change: row.change || 0,
          mainNetInflow: row.mainNetInflow || 0,
          netInflow: row.netInflow || 0,
          leaderCount: row.leaderCount || 0,
          ztCount: row.ztCount || 0,
          persistentDays: row.persistentDays || 0,
        }))

      return {
        ...frame,
        rows,
        hotlist: rows,
        sectors,
        hotThemes,
        rotationSummary: frame.rotationSummary
          ? {
              ...frame.rotationSummary,
              mainLines,
            }
          : mainLines.length > 0
            ? { mainLines }
            : null,
      }
    })
  }

  private async listRemoteSnapshotFrameBundles(
    options: SnapshotFrameQueryOptions = {},
  ): Promise<SnapshotFrameBundle[] | null> {
    if (!this.shouldUseSqliteSnapshotRead(options as SnapshotQueryOptions)) return null
    try {
      const query = new URLSearchParams()
      const snapshotType = options.type || options.types?.[0] || 'half_hour'
      query.set('snapshot_type', snapshotType)
      if (options.tradingDate) query.set('trading_date', options.tradingDate)
      if (options.startDate) query.set('start_date', options.startDate)
      if (options.endDate) query.set('end_date', options.endDate)
      if (options.beforeTradingDate) query.set('before_trading_date', options.beforeTradingDate)
      if (options.allowedCaptureModes?.length) {
        query.set('allowed_capture_modes', options.allowedCaptureModes.join(','))
      }
      if (options.excludeRestored) query.set('exclude_restored', 'true')
      if (options.sort) query.set('sort', options.sort)
      if (options.limit && options.limit > 0) query.set('limit', String(options.limit))

      const response = await apiService.get<any>(`/api/snapshots/frames?${query.toString()}`, {
        context: 'quant-board',
        priority: 'medium',
        timeout: 15000,
        retries: 0,
        cache: false,
        silent: true,
        throwOnHttpError: true,
      })
      const data = response && typeof response === 'object' && 'data' in response ? (response as any).data : response
      const frames = Array.isArray(data?.frames) ? data.frames : []
      return frames.map((frame: any) => this.normalizeRemoteSnapshotFrameBundle(frame))
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot frame read failed:', error)
      return []
    }
  }

  private async writeSnapshotBundleToSqlitePrimary(
    bundle: SnapshotProjectionBundle,
  ): Promise<{ ok: boolean; error?: unknown }> {
    if (typeof window === 'undefined') return { ok: true }
    try {
      const dayBundle: SnapshotDayBundle = {
        version: 'v4',
        tradingDate: bundle.record.tradingDate,
        items: [bundle.record],
        frames: bundle.frame ? [bundle.frame] : [],
        stockRows: bundle.stockRows || [],
        sectorRows: bundle.sectorRows || [],
      }
      const response = await apiService.ingestSnapshotBundle(dayBundle, {
        datasetId: 'dragonboard_live',
        idempotencyKey: await this.digestSnapshotBundleForSqlite(bundle),
      })
      const data = response && typeof response === 'object' && 'data' in response ? (response as any).data : response
      if (!data?.ok) {
        return { ok: false, error: new Error(data?.status || data?.message || 'snapshot_backend_ingest_failed') }
      }
      return { ok: true }
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot primary write failed:', error)
      return { ok: false, error }
    }
  }

  private async digestSnapshotBundleForSqlite(bundle: SnapshotProjectionBundle): Promise<string> {
    const text = JSON.stringify({
      snapshotId: bundle.record.id,
      tradingDate: bundle.record.tradingDate,
      slotTime: bundle.record.slotTime,
      timestamp: bundle.record.timestamp,
      payload: bundle.record.payload,
      frame: bundle.frame,
      stockRows: bundle.stockRows,
      sectorRows: bundle.sectorRows,
    })
    if (typeof crypto === 'undefined' || !crypto.subtle) {
      return `snapshot_ingest:${bundle.record.id}:${bundle.record.timestamp}:${text.length}`
    }
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
    const hash = Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('')
    return `snapshot_ingest:${hash}`
  }

  private async listRemoteSnapshots(options: SnapshotQueryOptions = {}): Promise<SnapshotRecord[] | null> {
    if (!this.shouldUseSqliteSnapshotRead(options)) return null
    try {
      const query = this.buildSnapshotRecordQuery(options)
      const data = await this.getQuantBoardPayload(`/api/snapshots/records?${query.toString()}`, 15000)
      const records = Array.isArray(data?.records) ? data.records : []
      return records.map((record: any) => this.normalizeRemoteSnapshotRecord(record))
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot record read failed:', error)
      return []
    }
  }

  private async getRemoteSnapshotById(id: string): Promise<SnapshotRecord | null | undefined> {
    if (!id || id.startsWith('five_minute:')) return undefined
    try {
      const data = await this.getQuantBoardPayload(`/api/snapshots/records/${encodeURIComponent(id)}`, 10000)
      return data?.record ? this.normalizeRemoteSnapshotRecord(data.record) : null
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot get failed:', error)
      return null
    }
  }

  private async listRemoteSnapshotStockRows(
    options: SnapshotStockRowQueryOptions = {},
  ): Promise<SnapshotStockRow[] | null> {
    if (!this.shouldUseSqliteSnapshotRead(options as SnapshotQueryOptions)) return null
    try {
      const query = this.buildSnapshotRowQuery(options)
      if (options.code) query.set('code', options.code)
      if (options.codes?.length) query.set('codes', options.codes.join(','))
      if (options.slotTime) query.set('slot_time', options.slotTime)
      const data = await this.getQuantBoardPayload(`/api/snapshots/stock-rows?${query.toString()}`, 15000)
      const rows = Array.isArray(data?.rows) ? data.rows : []
      return rows.map((row: any) => this.normalizeRemoteSnapshotStockRow(row))
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot stock row read failed:', error)
      return []
    }
  }

  private async listRemoteSnapshotSectorRows(
    options: SnapshotSectorRowQueryOptions = {},
  ): Promise<SnapshotSectorRow[] | null> {
    if (!this.shouldUseSqliteSnapshotRead(options as SnapshotQueryOptions)) return null
    try {
      const query = this.buildSnapshotRowQuery(options)
      if (options.entityType) query.set('entity_type', options.entityType)
      if (options.entityTypes?.length) query.set('entity_types', options.entityTypes.join(','))
      if (options.entityKey) query.set('entity_key', options.entityKey)
      if (options.entityKeys?.length) query.set('entity_keys', options.entityKeys.join(','))
      const data = await this.getQuantBoardPayload(`/api/snapshots/sector-rows?${query.toString()}`, 15000)
      const rows = Array.isArray(data?.rows) ? data.rows : []
      return rows.map((row: any) => this.normalizeRemoteSnapshotSectorRow(row))
    } catch (error) {
      console.warn('[DataLayer] SQLite snapshot sector row read failed:', error)
      return []
    }
  }

  private async getQuantBoardPayload(path: string, timeout = 15000): Promise<any> {
    const response = await apiService.get<any>(path, {
      context: 'quant-board',
      priority: 'medium',
      timeout,
      retries: 0,
      cache: false,
      silent: true,
      throwOnHttpError: true,
    })
    return response && typeof response === 'object' && 'data' in response ? (response as any).data : response
  }

  private shouldUseSqliteSnapshotRead(options: SnapshotQueryOptions = {}): boolean {
    const requested = this.resolveRequestedSnapshotTypes(options)
    return requested.length === 0 || requested.every((type) => FORMAL_SQLITE_SNAPSHOT_TYPES.includes(type))
  }

  private resolveRequestedSnapshotTypes(options: SnapshotQueryOptions = {}): SnapshotType[] {
    if (options.type) return [options.type]
    if (options.types?.length) return options.types
    return []
  }

  private buildSnapshotRecordQuery(options: SnapshotQueryOptions = {}): URLSearchParams {
    const query = this.buildSnapshotBaseQuery(options)
    if (options.requireCoverage) {
      query.delete('limit')
    }
    return query
  }

  private buildSnapshotRowQuery(
    options: SnapshotStockRowQueryOptions | SnapshotSectorRowQueryOptions,
  ): URLSearchParams {
    const query = this.buildSnapshotBaseQuery(options as SnapshotQueryOptions)
    if (options.snapshotId) query.set('snapshot_id', options.snapshotId)
    return query
  }

  private buildSnapshotBaseQuery(options: SnapshotQueryOptions = {}): URLSearchParams {
    const query = new URLSearchParams()
    if (options.type) query.set('snapshot_type', options.type)
    if (options.types?.length) query.set('types', options.types.join(','))
    if (options.tradingDate) query.set('trading_date', options.tradingDate)
    if (options.startDate) query.set('start_date', options.startDate)
    if (options.endDate) query.set('end_date', options.endDate)
    if (options.beforeTradingDate) query.set('before_trading_date', options.beforeTradingDate)
    if (options.allowedCaptureModes?.length) {
      query.set('allowed_capture_modes', options.allowedCaptureModes.join(','))
    }
    if (options.excludeRestored) query.set('exclude_restored', 'true')
    if (options.sort) query.set('sort', options.sort)
    if (options.limit && options.limit > 0) query.set('limit', String(options.limit))
    return query
  }

  private filterRemoteSnapshotsByCoverage(
    records: SnapshotRecord[],
    options: SnapshotQueryOptions,
  ): SnapshotRecord[] {
    if (!options.requireCoverage) return records
    const requestedTypes = this.resolveRequestedSnapshotTypes(options)
    const effectiveTypes = (
      requestedTypes.length > 0
        ? requestedTypes.filter((type) => type !== 'five_minute')
        : FORMAL_SQLITE_SNAPSHOT_TYPES
    )
    const tolerance = Math.max(0, Math.floor(Number(options.coverageTolerance) || 0))
    const byTradingDate = new Map<string, SnapshotRecord[]>()
    records.forEach((record) => {
      if (!record.tradingDate) return
      const bucket = byTradingDate.get(record.tradingDate) || []
      bucket.push(record)
      byTradingDate.set(record.tradingDate, bucket)
    })
    const qualified = new Set<string>()
    byTradingDate.forEach((items, tradingDate) => {
      const ok = effectiveTypes.every((type) => {
        const typed = items.filter((record) => record.type === type)
        const expected = getExpectedSlots(type)
        const actual = typed.map((record) => record.slotTime).filter(Boolean)
        const valid = new Set(expected)
        const malformed = actual.filter((slot) => !valid.has(slot))
        const latestObserved = actual.reduce(
          (latest, slot) => (slotTimeToMinutes(slot) > slotTimeToMinutes(latest) ? slot : latest),
          '',
        )
        const effectiveExpected = latestObserved
          ? expected.filter((slot) => slotTimeToMinutes(slot) <= slotTimeToMinutes(latestObserved))
          : expected
        const missing = effectiveExpected.filter((slot) => !actual.includes(slot))
        return malformed.length === 0 && missing.length <= tolerance
      })
      if (ok) qualified.add(tradingDate)
    })
    const filtered = records.filter((record) => qualified.has(record.tradingDate))
    return options.limit && options.limit > 0 ? filtered.slice(0, options.limit) : filtered
  }

  private normalizeRemoteSnapshotRecord(record: any): SnapshotRecord {
    const payload = record?.payload && typeof record.payload === 'object' ? record.payload : record
    return {
      ...record,
      id: String(record?.id || record?.snapshotId || ''),
      snapshotId: String(record?.snapshotId || record?.id || ''),
      type: record?.type,
      tradingDate: String(record?.tradingDate || ''),
      slotTime: String(record?.slotTime || ''),
      timestamp: Number(record?.timestamp || 0),
      displayKey: String(record?.displayKey || record?.id || record?.snapshotId || ''),
      captureMode: record?.captureMode || 'real_time',
      capturedAt: Number(record?.capturedAt || record?.timestamp || Date.now()),
      dataTimestamp: Number(record?.dataTimestamp || record?.timestamp || 0),
      delayMs: Number(record?.delayMs || 0),
      qualityFlags: Array.isArray(record?.qualityFlags) ? record.qualityFlags : [],
      source: record?.source || 'browser_runtime',
      payload,
    } as SnapshotRecord
  }

  private normalizeRemoteSnapshotStockRow(row: any): SnapshotStockRow {
    return {
      ...row,
      id: String(row?.id || row?.rowId || `${row?.snapshotId || ''}:${row?.code || ''}`),
      rowId: String(row?.rowId || row?.id || `${row?.snapshotId || ''}:${row?.code || ''}`),
      snapshotId: String(row?.snapshotId || ''),
      type: row?.type,
      tradingDate: String(row?.tradingDate || ''),
      slotTime: String(row?.slotTime || ''),
      timestamp: Number(row?.timestamp || 0),
      captureMode: row?.captureMode || 'real_time',
      source: row?.source || 'browser_runtime',
      code: String(row?.code || ''),
      name: String(row?.name || row?.code || ''),
      rank: Number(row?.rank || row?.compRank || 0),
      compRank: Number(row?.compRank || row?.rank || 0),
      platforms: Number(row?.platforms || 0),
    } as SnapshotStockRow
  }

  private normalizeRemoteSnapshotSectorRow(row: any): SnapshotSectorRow {
    return {
      ...row,
      id: String(row?.id || row?.rowId || `${row?.snapshotId || ''}:${row?.entityType || ''}:${row?.entityKey || ''}`),
      rowId: String(row?.rowId || row?.id || `${row?.snapshotId || ''}:${row?.entityType || ''}:${row?.entityKey || ''}`),
      snapshotId: String(row?.snapshotId || ''),
      type: row?.type,
      tradingDate: String(row?.tradingDate || ''),
      slotTime: String(row?.slotTime || ''),
      timestamp: Number(row?.timestamp || 0),
      captureMode: row?.captureMode || 'real_time',
      source: row?.source || 'browser_runtime',
      entityType: row?.entityType || 'sector',
      entityKey: String(row?.entityKey || row?.entityCode || row?.id || ''),
      entityCode: row?.entityCode || row?.entityKey,
      entityName: String(row?.entityName || row?.name || row?.themeName || ''),
      rank: Number(row?.rank || 0),
    } as SnapshotSectorRow
  }

  private createEmptySnapshotCounts(): SnapshotCountMap {
    return {
      snapshots: 0,
      snapshot_frames: 0,
      snapshot_stock_rows: 0,
      snapshot_sector_rows: 0,
    }
  }

  private openIndexedDbForSnapshotCounts(): Promise<IDBDatabase> {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.PRIMARY_DB_NAME)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error || new Error(`open IndexedDB failed:${this.PRIMARY_DB_NAME}`))
      request.onupgradeneeded = () => {
        request.transaction?.abort()
        reject(new Error(`IndexedDB database requires upgrade:${this.PRIMARY_DB_NAME}`))
      }
    })
  }

  private countIndexedDbStore(db: IDBDatabase, storeName: SnapshotIndexedDbCountStore): Promise<number> {
    if (!db.objectStoreNames.contains(storeName)) return Promise.resolve(0)
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readonly')
      const store = transaction.objectStore(storeName)
      const request = store.count()
      request.onsuccess = () => resolve(Number(request.result) || 0)
      request.onerror = () => reject(request.error || new Error(`count IndexedDB store failed:${storeName}`))
      transaction.onerror = () => reject(transaction.error || new Error(`IndexedDB transaction failed:${storeName}`))
    })
  }

  private readIndexedDbStoreAll<T>(db: IDBDatabase, storeName: SnapshotIndexedDbCountStore): Promise<T[]> {
    if (!db.objectStoreNames.contains(storeName)) return Promise.resolve([])
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(storeName, 'readonly')
      const store = transaction.objectStore(storeName)
      const request = store.getAll()
      request.onsuccess = () => resolve(Array.isArray(request.result) ? (request.result as T[]) : [])
      request.onerror = () => reject(request.error || new Error(`read IndexedDB store failed:${storeName}`))
      transaction.onerror = () => reject(transaction.error || new Error(`IndexedDB transaction failed:${storeName}`))
    })
  }

  private async readIndexedDbSnapshotMigrationRows(): Promise<{
    records: SnapshotRecord[]
    frames: SnapshotFrameRow[]
    stockRows: SnapshotStockRow[]
    sectorRows: SnapshotSectorRow[]
    counts: SnapshotCountMap
  }> {
    if (typeof indexedDB === 'undefined') {
      return {
        records: [],
        frames: [],
        stockRows: [],
        sectorRows: [],
        counts: this.createEmptySnapshotCounts(),
      }
    }
    const db = await this.openIndexedDbForSnapshotCounts()
    try {
      const [records, frames, stockRows, sectorRows] = await Promise.all([
        this.readIndexedDbStoreAll<SnapshotRecord>(db, 'snapshots'),
        this.readIndexedDbStoreAll<SnapshotFrameRow>(db, 'snapshot_frames'),
        this.readIndexedDbStoreAll<SnapshotStockRow>(db, 'snapshot_stock_rows'),
        this.readIndexedDbStoreAll<SnapshotSectorRow>(db, 'snapshot_sector_rows'),
      ])
      return {
        records,
        frames,
        stockRows,
        sectorRows,
        counts: {
          snapshots: records.length,
          snapshot_frames: frames.length,
          snapshot_stock_rows: stockRows.length,
          snapshot_sector_rows: sectorRows.length,
        },
      }
    } finally {
      db.close()
    }
  }

  private buildSnapshotMigrationBatches(
    rows: {
      records: SnapshotRecord[]
      frames: SnapshotFrameRow[]
      stockRows: SnapshotStockRow[]
      sectorRows: SnapshotSectorRow[]
    },
    batchSize: number,
  ): Array<{
    records: SnapshotRecord[]
    frames: SnapshotFrameRow[]
    stockRows: SnapshotStockRow[]
    sectorRows: SnapshotSectorRow[]
    snapshotIds: string[]
  }> {
    const records = rows.records
      .filter((record) => record?.id && record.type !== 'five_minute')
      .sort((left, right) => Number(left.timestamp || 0) - Number(right.timestamp || 0))
    const frameBySnapshotId = new Map(
      rows.frames
        .filter((frame) => frame?.snapshotId || frame?.id)
        .map((frame) => [String(frame.snapshotId || frame.id), frame]),
    )
    const stockRowsBySnapshotId = new Map<string, SnapshotStockRow[]>()
    rows.stockRows.forEach((row) => {
      const snapshotId = String(row?.snapshotId || '')
      if (!snapshotId) return
      const bucket = stockRowsBySnapshotId.get(snapshotId) || []
      bucket.push(row)
      stockRowsBySnapshotId.set(snapshotId, bucket)
    })
    const sectorRowsBySnapshotId = new Map<string, SnapshotSectorRow[]>()
    rows.sectorRows.forEach((row) => {
      const snapshotId = String(row?.snapshotId || '')
      if (!snapshotId) return
      const bucket = sectorRowsBySnapshotId.get(snapshotId) || []
      bucket.push(row)
      sectorRowsBySnapshotId.set(snapshotId, bucket)
    })

    const batches: Array<{
      records: SnapshotRecord[]
      frames: SnapshotFrameRow[]
      stockRows: SnapshotStockRow[]
      sectorRows: SnapshotSectorRow[]
      snapshotIds: string[]
    }> = []
    const effectiveBatchSize = Math.max(1, Math.min(100, Math.floor(batchSize) || 25))

    for (let index = 0; index < records.length; index += effectiveBatchSize) {
      const batchRecords = records.slice(index, index + effectiveBatchSize)
      const snapshotIds = batchRecords.map((record) => record.id)
      const frames = snapshotIds
        .map((snapshotId) => frameBySnapshotId.get(snapshotId))
        .filter((frame): frame is SnapshotFrameRow => !!frame)
      batches.push({
        records: batchRecords,
        frames,
        stockRows: snapshotIds.flatMap((snapshotId) => stockRowsBySnapshotId.get(snapshotId) || []),
        sectorRows: snapshotIds.flatMap((snapshotId) => sectorRowsBySnapshotId.get(snapshotId) || []),
        snapshotIds,
      })
    }

    return batches
  }

  private async importIndexedDbSnapshotBatchToSqlite(params: {
    datasetId: string
    batch: {
      records: SnapshotRecord[]
      frames: SnapshotFrameRow[]
      stockRows: SnapshotStockRow[]
      sectorRows: SnapshotSectorRow[]
      snapshotIds: string[]
    }
    batchIndex: number
    dryRun: boolean
  }): Promise<SnapshotIndexedDbSqliteMigrationBatch> {
    const idempotencyKey = await this.digestIndexedDbSnapshotMigrationBatch(
      params.datasetId,
      params.batch.snapshotIds,
    )
    const content = {
      version: 'indexeddb-v4',
      records: params.batch.records,
      frames: params.batch.frames,
      stockRows: params.batch.stockRows,
      sectorRows: params.batch.sectorRows,
      metadata: {
        source: 'dragon_board_indexeddb',
        batchIndex: params.batchIndex,
      },
    }
    const response = await apiService.post<any>(
      '/api/migrations/snapshots/import-json',
      {
        datasetId: params.datasetId,
        source: 'dragon_board_indexeddb_migration',
        name: 'DragonBoard IndexedDB Migration',
        idempotencyKey,
        content,
        dryRun: params.dryRun,
      },
      {
        context: 'quant-board',
        priority: 'high',
        timeout: 120000,
        retries: 0,
        cache: false,
        throwOnHttpError: true,
      },
    )
    const data = response && typeof response === 'object' && 'data' in response ? (response as any).data : response
    const report = data?.report || {}
    return {
      index: params.batchIndex,
      snapshotCount: params.batch.records.length,
      frameCount: params.batch.frames.length,
      stockRowCount: params.batch.stockRows.length,
      sectorRowCount: params.batch.sectorRows.length,
      imported: Number(report.imported || 0),
      skipped: Number(report.skipped || 0),
      deduped: Boolean(data?.deduped),
      ok: Boolean(data?.ok),
      error: Array.isArray(report.errors) && report.errors.length > 0 ? report.errors.join('; ') : undefined,
    }
  }

  private async digestIndexedDbSnapshotMigrationBatch(
    datasetId: string,
    snapshotIds: string[],
  ): Promise<string> {
    const payload = JSON.stringify({
      datasetId,
      snapshotIds,
    })
    if (typeof crypto === 'undefined' || !crypto.subtle) {
      const first = snapshotIds[0] || ''
      const last = snapshotIds[snapshotIds.length - 1] || ''
      return `migration:indexeddb:${datasetId}:${snapshotIds.length}:${first}:${last}`.slice(0, 160)
    }
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(payload))
    const hash = Array.from(new Uint8Array(digest))
      .map((byte) => byte.toString(16).padStart(2, '0'))
      .join('')
    return `migration:indexeddb:${datasetId}:${hash}`.slice(0, 160)
  }

  private normalizeRemoteSnapshotFrameBundle(frame: any): SnapshotFrameBundle {
    const rows = Array.isArray(frame.rows) ? frame.rows : Array.isArray(frame.hotlist) ? frame.hotlist : []
    const sectors = Array.isArray(frame.sectors) ? frame.sectors : []
    const hotThemes = Array.isArray(frame.hotThemes) ? frame.hotThemes : []
    return {
      ...frame,
      id: frame.id || frame.snapshotId,
      snapshotId: frame.snapshotId || frame.id,
      displayKey: frame.displayKey || frame.snapshotId || frame.id,
      captureMode: frame.captureMode || 'real_time',
      source: frame.source || 'browser_runtime',
      qualityFlags: Array.isArray(frame.qualityFlags) ? frame.qualityFlags : [],
      delayMs: Number(frame.delayMs || 0),
      metadata: frame.metadata || null,
      marketStats: frame.marketStats || frame.marketContext?.marketStats || null,
      sentiment: frame.sentiment || frame.marketContext?.sentiment || null,
      moneyFlow: frame.moneyFlow || frame.marketContext?.moneyFlow || null,
      indices: frame.indices || frame.marketContext?.indices || null,
      limitSummary: frame.limitSummary || frame.marketContext?.limitSummary || null,
      rotationSummary: frame.rotationSummary || frame.marketContext?.rotationSummary || null,
      stockRowCount: Number(frame.stockRowCount || rows.length || 0),
      sectorRowCount: Number(frame.sectorRowCount || sectors.length + hotThemes.length || 0),
      rows,
      hotlist: rows,
      sectors,
      hotThemes,
    } as SnapshotFrameBundle
  }

  private snapshotFrameRowFromBundle(bundle: SnapshotFrameBundle): SnapshotFrameRow {
    return {
      id: bundle.id || bundle.snapshotId,
      snapshotId: bundle.snapshotId || bundle.id,
      type: bundle.type,
      tradingDate: bundle.tradingDate,
      slotTime: bundle.slotTime,
      timestamp: bundle.timestamp,
      displayKey: bundle.displayKey || bundle.snapshotId || bundle.id,
      captureMode: bundle.captureMode,
      source: bundle.source,
      qualityFlags: bundle.qualityFlags || [],
      delayMs: Number(bundle.delayMs || 0),
      metadata: bundle.metadata || null,
      marketStats: bundle.marketStats || null,
      sentiment: bundle.sentiment || null,
      moneyFlow: bundle.moneyFlow || null,
      indices: bundle.indices || null,
      limitSummary: bundle.limitSummary || null,
      rotationSummary: bundle.rotationSummary || null,
      stockRowCount: Number(bundle.stockRowCount || bundle.rows?.length || 0),
      sectorRowCount: Number(bundle.sectorRowCount || 0),
    } as SnapshotFrameRow
  }

  async getLatestSnapshotRecord(options?: {
    type?: SnapshotType
    beforeTradingDate?: string
    allowedCaptureModes?: ('real_time' | 'delayed' | 'restored')[]
    excludeRestored?: boolean
  }): Promise<SnapshotRecord | null> {
    const snapshots = await this.listSnapshots({
      type: options?.type,
      beforeTradingDate: options?.beforeTradingDate,
      allowedCaptureModes: options?.allowedCaptureModes,
      excludeRestored: options?.excludeRestored,
      sort: 'desc',
      limit: 1,
    })
    return snapshots[0] || null
  }

  async exportSnapshotAsFile(id: string): Promise<void> {
    return this.snapshotRuntime.exportSnapshotAsFile(id)
  }

  async exportAllSnapshots(): Promise<void> {
    return this.snapshotRuntime.exportAllSnapshots()
  }

  async deleteSnapshot(id: string): Promise<boolean> {
    return this.snapshotRuntime.deleteSnapshot(id)
  }

  async getSnapshotStorageStats(): Promise<{
    totalSnapshots: number
    dates: string[]
    estimatedSize: number
  }> {
    return this.snapshotRuntime.getSnapshotStorageStats()
  }

  async getBackupSnapshotStorageStats(): Promise<{
    totalSnapshots: number
    estimatedSize: number
    mode: 'all'
    bucketSnapshots: number
    remoteCloudSnapshots: number
  }> {
    return this.snapshotRuntime.getBackupSnapshotStorageStats()
  }

  async getBackupBucketHealth(): Promise<{
    supported: boolean
    bucketName: string
    bucketOpened: boolean
    persisted?: boolean
    durability?: string
    usage?: number
    quota?: number
    keys?: string[]
    error?: string
  }> {
    return this.snapshotRuntime.getBackupBucketHealth()
  }

  async getCloudBackupHealth() {
    return this.snapshotRuntime.getCloudBackupHealth()
  }

  async getSnapshotBackupSyncState(tradingDate?: string): Promise<SnapshotBackupSyncState | null> {
    return this.snapshotRuntime.getSnapshotBackupSyncState(tradingDate)
  }

  async listSnapshotBackupSyncStates(limit?: number): Promise<SnapshotBackupSyncState[]> {
    return this.snapshotRuntime.listSnapshotBackupSyncStates(limit)
  }

  async getSnapshotHealthOverview(tradingDate?: string): Promise<SnapshotHealthOverview> {
    return this.snapshotRuntime.getSnapshotHealthOverview(tradingDate)
  }

  async getIndexedDbSnapshotCounts(): Promise<SnapshotCountMap> {
    const empty = this.createEmptySnapshotCounts()
    if (typeof indexedDB === 'undefined') return empty
    const db = await this.openIndexedDbForSnapshotCounts()
    try {
      const entries = await Promise.all(
        SNAPSHOT_INDEXEDDB_COUNT_STORES.map(async (storeName) => [
          storeName,
          await this.countIndexedDbStore(db, storeName),
        ] as const),
      )
      return Object.fromEntries(entries) as SnapshotCountMap
    } finally {
      db.close()
    }
  }

  async validateSnapshotIndexedDbSqliteCounts(datasetId?: string | null): Promise<{
    ok: boolean
    datasetId: string
    indexedDb: SnapshotCountMap
    sqlite: SnapshotCountMap
    diffs: Record<string, { indexedDb: number; sqlite: number; delta: number }>
    source: 'sqlite'
  }> {
    const indexedDbCounts = await this.getIndexedDbSnapshotCounts()
    const payload: { datasetId?: string; indexedDbCounts: SnapshotCountMap } = {
      indexedDbCounts,
    }
    if (datasetId?.trim()) {
      payload.datasetId = datasetId.trim()
    }
    const response = await apiService.post<any>(
      '/api/snapshots/validate-indexeddb-counts',
      payload,
      {
        context: 'quant-board',
        priority: 'medium',
        timeout: 15000,
        retries: 0,
        cache: false,
        throwOnHttpError: true,
      },
    )
    const data = response && typeof response === 'object' && 'data' in response ? (response as any).data : response
    return {
      ok: Boolean(data?.ok),
      datasetId: String(data?.datasetId || datasetId || ''),
      indexedDb: { ...this.createEmptySnapshotCounts(), ...(data?.indexedDb || indexedDbCounts) },
      sqlite: { ...this.createEmptySnapshotCounts(), ...(data?.sqlite || {}) },
      diffs: data?.diffs || {},
      source: 'sqlite',
    }
  }

  async migrateIndexedDbSnapshotsToSqlite(options?: {
    datasetId?: string
    batchSize?: number
    dryRun?: boolean
    validate?: boolean
  }): Promise<SnapshotIndexedDbSqliteMigrationResult> {
    const datasetId = options?.datasetId?.trim() || 'dragonboard_live'
    const dryRun = options?.dryRun === true
    const validate = options?.validate !== false
    const { records, frames, stockRows, sectorRows, counts } = await this.readIndexedDbSnapshotMigrationRows()
    const batches = this.buildSnapshotMigrationBatches(
      { records, frames, stockRows, sectorRows },
      options?.batchSize || 20,
    )
    const batchReports: SnapshotIndexedDbSqliteMigrationBatch[] = []
    const errors: string[] = []

    for (let index = 0; index < batches.length; index += 1) {
      try {
        const report = await this.importIndexedDbSnapshotBatchToSqlite({
          datasetId,
          batch: batches[index],
          batchIndex: index + 1,
          dryRun,
        })
        batchReports.push(report)
        if (!report.ok && report.error) {
          errors.push(`batch ${index + 1}: ${report.error}`)
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error)
        errors.push(`batch ${index + 1}: ${message}`)
        batchReports.push({
          index: index + 1,
          snapshotCount: batches[index].records.length,
          frameCount: batches[index].frames.length,
          stockRowCount: batches[index].stockRows.length,
          sectorRowCount: batches[index].sectorRows.length,
          imported: 0,
          skipped: 0,
          deduped: false,
          ok: false,
          error: message,
        })
      }
    }

    let validation: SnapshotIndexedDbSqliteMigrationResult['validation']
    if (!dryRun && validate) {
      validation = await this.validateSnapshotIndexedDbSqliteCounts(datasetId)
      if (!validation.ok) {
        errors.push('IndexedDB and SQLite counts are still different after migration')
      }
    }

    return {
      ok: errors.length === 0 && (dryRun || validation?.ok === true || validate === false),
      datasetId,
      dryRun,
      sourceCounts: counts,
      scanned: batches.reduce((total, batch) => total + batch.snapshotIds.length, 0),
      imported: batchReports.reduce((total, batch) => total + batch.imported, 0),
      skipped: batchReports.reduce((total, batch) => total + batch.skipped, 0),
      batches: batchReports,
      validation,
      errors,
    }
  }

  async restoreSnapshotsFromBackup(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    restored: number
    skipped: number
    totalFromBackup: number
    mode: 'all'
    remoteRestored: number
  }> {
    return this.snapshotRuntime.restoreSnapshotsFromBackup(options)
  }

  async syncPrimarySnapshotsToBackup(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    synced: number
    skipped: number
    totalPrimary: number
    bucketSynced: number
    remoteCloudSynced: number
    mode: 'all'
  }> {
    return this.snapshotRuntime.syncPrimarySnapshotsToBackup(options)
  }

  async syncPrimarySnapshotsToCloud(options?: {
    overwrite?: boolean
    limit?: number
    tradingDate?: string
    startDate?: string
    endDate?: string
  }): Promise<{
    queued: number
    totalPrimary: number
  }> {
    return this.snapshotRuntime.syncPrimarySnapshotsToCloud(options)
  }

  async syncAllSnapshotStores(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    primaryCount: number
    bucketBackupCount: number
    remoteCloudCount: number
    insertedToPrimary: number
    insertedToBucketBackup: number
    insertedToRemoteCloud: number
    mode: 'all'
  }> {
    return this.snapshotRuntime.syncAllSnapshotStores(options)
  }

  async runSnapshotAutoRecoveryCheck(options?: {
    minBackupCount?: number
    abnormalRatio?: number
    force?: boolean
  }): Promise<{
    checked: boolean
    recovered: boolean
    reason: string
    primaryCount: number
    backupCount: number
    restored: number
    skipped: number
    remoteRestored: number
    mode: 'all'
  }> {
    return this.snapshotRuntime.runSnapshotAutoRecoveryCheck(options)
  }

  async inspectTradingDateSnapshotCoverage(tradingDate: string) {
    return this.snapshotRuntime.inspectTradingDateSnapshotCoverage(tradingDate)
  }

  async buildSnapshotCoverageWindow(options?: {
    startDate?: string
    endDate?: string
    limit?: number
  }) {
    return this.snapshotRuntime.buildSnapshotCoverageWindow(options)
  }

  async repairTradingDateSnapshotCoverage(
    tradingDate: string,
    options?: {
      toleranceMinutes?: number
      deriveHalfHourFromQuarter?: boolean
    },
  ) {
    return this.snapshotRuntime.repairTradingDateSnapshotCoverage(tradingDate, options)
  }

  async saveFiveMinuteSnapshot(snapshotTime: Date = new Date()): Promise<boolean> {
    return this.snapshotRuntime.saveFiveMinuteSnapshot(snapshotTime)
  }

  startTimer() {
    this.snapshotRuntime.start()
  }

  stopTimer() {
    this.snapshotRuntime.stop()
  }
}

// 在文件末尾更新导出
export const dataLayer = new DataLayer()

if (typeof window !== 'undefined') {
  ;(window as any).dataLayer = dataLayer
}
