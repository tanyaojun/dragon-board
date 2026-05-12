import type { Depth10Book } from '../../types'
import type { RankTrendSnapshotType } from '../../types/rankTrendDefaults'

export type SnapshotType = RankTrendSnapshotType | 'five_minute'

export type SnapshotCaptureMode = 'real_time' | 'delayed' | 'restored'
export type SnapshotSource = 'browser_runtime' | 'bucket_restore' | 'manual'

export interface SnapshotQualityMetadata {
  captureMode: SnapshotCaptureMode
  capturedAt: number
  dataTimestamp: number
  delayMs: number
  qualityFlags: string[]
  source: SnapshotSource
}

export interface SnapshotRecord<T = any> {
  id: string
  type: SnapshotType
  tradingDate: string
  slotTime: string
  timestamp: number
  displayKey: string
  captureMode: SnapshotCaptureMode
  capturedAt: number
  dataTimestamp: number
  delayMs: number
  qualityFlags: string[]
  source: SnapshotSource
  payload: T
}

export interface SnapshotFrameRow {
  id: string
  snapshotId: string
  type: Exclude<SnapshotType, 'five_minute'>
  tradingDate: string
  slotTime: string
  timestamp: number
  displayKey: string
  captureMode: SnapshotCaptureMode
  source: SnapshotSource
  qualityFlags: string[]
  delayMs: number
  metadata: Record<string, any> | null
  marketStats: Record<string, any> | null
  sentiment: Record<string, any> | null
  moneyFlow: Record<string, any> | null
  indices: Record<string, any> | null
  limitSummary: Record<string, any> | null
  rotationSummary: Record<string, any> | null
  stockRowCount: number
  sectorRowCount: number
}

export interface SnapshotFrameBundle extends SnapshotFrameRow {
  rows: SnapshotStockRow[]
  hotlist: SnapshotStockRow[]
  sectors: Array<Record<string, any>>
  hotThemes: Array<Record<string, any>>
  rotationSummary: Record<string, any> | null
}

export interface SnapshotStockRow {
  id: string
  snapshotId: string
  type: Exclude<SnapshotType, 'five_minute'>
  tradingDate: string
  slotTime: string
  timestamp: number
  captureMode: SnapshotCaptureMode
  source: SnapshotSource
  code: string
  name: string
  rank: number
  compRank: number
  platforms: number
  avgRank?: string
  avgRankNum?: number
  price?: number
  change?: number
  volume?: number
  turnover?: number
  turnoverRate?: number
  totalMV?: number
  cirMV?: number
  zlje?: number
  zljzb?: number
  cddje?: number
  cddjzb?: number
  moneyFlowSource?: string
  moneyFlowEstimated?: boolean
  capitalFlowSource?: string
  capitalFlowConfidence?: string
  money_flow_source?: string
  money_flow_estimated?: boolean
  capital_flow_source?: string
  capital_flow_confidence?: string
  pe?: number
  pb?: number
  depth10?: Depth10Book
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
  volumeRatio?: number
  speed?: number
  leadStatus?: string
  leadTimes?: number
  lianbanStr?: string
  fengdan?: number
  maxFengdan?: number
  popularity?: number
  popularityChange?: number
  institutionBuy?: number
  bigMoney300?: number
  themes?: Array<{
    id?: string
    name?: string
    heatScore?: number
    role?: string
    exposureWeight?: number
    themeContribution?: number
    riskPenalty?: number
  }>
  themeContribution?: number
  themeRole?: string
  themeExposureWeight?: number
  themeRiskFlags?: string[]
  isNew?: boolean
  firstZtTime?: string
  lastZtTime?: string
  boardHeight?: number
  highDays?: number
  hotness?: number
  mainTheme?: string
  themeHeat?: number
  themeLevel?: string
  rankChange?: number
  directionSignal?: string
  directionConfidence?: number
  accelerationSignal?: string
  accelerationConfidence?: number
  crossSignal?: string
  crossConfidence?: number
  finalSignal?: string
  finalConfidence?: number
}

export type SnapshotSectorEntityType = 'sector' | 'hot_theme' | 'rotation_main_line'

export interface SnapshotSectorRow {
  id: string
  snapshotId: string
  type: Exclude<SnapshotType, 'five_minute'>
  tradingDate: string
  slotTime: string
  timestamp: number
  captureMode: SnapshotCaptureMode
  source: SnapshotSource
  entityType: SnapshotSectorEntityType
  entityKey: string
  entityCode?: string
  entityName: string
  rank: number
  strength?: number
  heatScore?: number
  heatLevel?: string
  change?: number
  mainNetInflow?: number
  bigMoney300?: number
  institutionBuy?: number
  volumeRatio?: number
  ztCount?: number
  leaderCount?: number
  persistentDays?: number
  netInflow?: number
  momentumScore?: number
  breadthScore?: number
  fundScore?: number
  leadershipScore?: number
  correlationScore?: number
  crowdingRisk?: number
  persistenceScore?: number
  rotationState?: string
  themeQualityFlags?: any[]
  metadata?: Record<string, any> | null
}

export type SnapshotProjectionBackfillStatus = 'idle' | 'running' | 'completed' | 'error'

export interface SnapshotProjectionMeta {
  key: 'global'
  schemaVersion: number
  backfillStatus: SnapshotProjectionBackfillStatus
  projectedBeforeTimestamp?: number
  lastBackfillCursor?: string
  lastBackfillAt?: number
  lastError?: string
}

export interface SnapshotProjectionBundle {
  record: SnapshotRecord
  frame: SnapshotFrameRow | null
  stockRows: SnapshotStockRow[]
  sectorRows: SnapshotSectorRow[]
}

export interface SnapshotProjectionRewriteResult {
  scanned: number
  rewritten: number
  affectedTradingDates: string[]
}

export interface SnapshotRawCompactionResult {
  scanned: number
  rewritten: number
  affectedTradingDates: string[]
}

export interface SnapshotPollutionCleanupResult {
  scanned: number
  deleted: number
  deletedFromPrimary: number
  deletedFromBucketBackup: number
  affectedTradingDates: string[]
  deletedSnapshotIds: string[]
}

export interface SnapshotBackupAlignmentResult {
  processedSnapshots: number
  localBundlesSynced: number
}

export interface SnapshotStorageMaintenanceResult {
  projectionRebuild: SnapshotProjectionRewriteResult
  backupAlignmentBeforeCompaction: SnapshotBackupAlignmentResult
  rawCompaction: SnapshotRawCompactionResult
  backupAlignmentAfterCompaction: SnapshotBackupAlignmentResult
}

export interface SnapshotQueryOptions {
  type?: SnapshotType
  types?: SnapshotType[]
  tradingDate?: string
  startDate?: string
  endDate?: string
  beforeTradingDate?: string
  allowedCaptureModes?: SnapshotCaptureMode[]
  excludeRestored?: boolean
  requireCoverage?: boolean
  coverageTolerance?: number
  sort?: 'asc' | 'desc'
  limit?: number
}

export interface SnapshotFrameQueryOptions {
  type?: Exclude<SnapshotType, 'five_minute'>
  types?: Array<Exclude<SnapshotType, 'five_minute'>>
  projection?: 'full' | 'ranktrend'
  tradingDate?: string
  startDate?: string
  endDate?: string
  beforeTradingDate?: string
  allowedCaptureModes?: SnapshotCaptureMode[]
  excludeRestored?: boolean
  sort?: 'asc' | 'desc'
  limit?: number
}

export interface SnapshotStockRowQueryOptions {
  snapshotId?: string
  type?: Exclude<SnapshotType, 'five_minute'>
  types?: Array<Exclude<SnapshotType, 'five_minute'>>
  tradingDate?: string
  startDate?: string
  endDate?: string
  beforeTradingDate?: string
  code?: string
  codes?: string[]
  slotTime?: string
  allowedCaptureModes?: SnapshotCaptureMode[]
  excludeRestored?: boolean
  sort?: 'asc' | 'desc'
  limit?: number
}

export interface RankTrendRankSeriesQueryOptions {
  datasetId?: string
  type?: Exclude<SnapshotType, 'five_minute'>
  types?: never
  tradingDate?: string
  startDate?: string
  endDate?: string
  beforeTradingDate?: string
  allowedCaptureModes?: SnapshotCaptureMode[]
  excludeRestored?: boolean
  codes?: string[]
  sort?: 'asc' | 'desc'
  limit?: number
}

export interface RankTrendRankSeriesFrame {
  snapshotId: string
  displayKey?: string
  timestamp: number
  type: Exclude<SnapshotType, 'five_minute'>
  tradingDate?: string
  slotTime?: string
  captureMode?: SnapshotCaptureMode
  totalCount: number
  ranks: Record<string, number>
}

export interface RankTrendRankSeriesResponse {
  ok: boolean
  datasetId: string
  snapshotType: Exclude<SnapshotType, 'five_minute'>
  frames: RankTrendRankSeriesFrame[]
  count: number
  source: string
  cache?: { hit: boolean; store: string }
}

export interface SnapshotSectorRowQueryOptions {
  snapshotId?: string
  type?: Exclude<SnapshotType, 'five_minute'>
  types?: Array<Exclude<SnapshotType, 'five_minute'>>
  tradingDate?: string
  startDate?: string
  endDate?: string
  beforeTradingDate?: string
  entityType?: SnapshotSectorEntityType
  entityTypes?: SnapshotSectorEntityType[]
  entityKey?: string
  entityKeys?: string[]
  allowedCaptureModes?: SnapshotCaptureMode[]
  excludeRestored?: boolean
  sort?: 'asc' | 'desc'
  limit?: number
}

export interface SnapshotStorageStats {
  totalSnapshots: number
  dates: string[]
  estimatedSize: number
}

export interface SnapshotCoverageBucket {
  expected: string[]
  actual: string[]
  missing: string[]
  malformed: string[]
  delayed: string[]
  restored: string[]
}

export interface SnapshotCoverageReport {
  quarterHour: SnapshotCoverageBucket
  halfHour: SnapshotCoverageBucket
  hourly: SnapshotCoverageBucket
  daily: SnapshotCoverageBucket
}

export interface SnapshotCoverageWindowItem {
  tradingDate: string
  quarterHour: SnapshotCoverageBucket
  halfHour: SnapshotCoverageBucket
  hourly: SnapshotCoverageBucket
  daily: SnapshotCoverageBucket
  severity: 'ok' | 'warn' | 'danger'
}

export interface SnapshotRepairCandidate {
  id: string
  type: SnapshotType
  tradingDate: string
  slotTime: string
  timestamp: number
  displayKey: string
  payload: any
  reason: string
}

export interface SnapshotCoverageRepairResult {
  normalizedQuarterCandidates: SnapshotRepairCandidate[]
  derivedHalfHourCandidates: SnapshotRepairCandidate[]
  rejectedCandidates: Array<{
    type: SnapshotType
    tradingDate: string
    slotTime: string
    reason: string
  }>
  reason: string
  normalizedQuarter: number
  createdHalfHour: number
  skipped: number
}

export type SnapshotBackupSyncErrorKind = 'bucket' | 'cloudBundle' | 'backendIngest'

export interface SnapshotBackupSyncState {
  tradingDate: string
  bucketSyncedAt?: number
  cloudBundleUploadedAt?: number
  backendIngestedAt?: number
  lastBucketError?: string
  lastCloudBundleError?: string
  lastBackendIngestError?: string
  lastError?: string
}

export interface SnapshotFormalReadPolicy {
  mode: 'formal_analysis'
  allowedCaptureModes: SnapshotCaptureMode[]
  excludeRestored: boolean
  description: string
}

export interface SnapshotHealthOverview {
  tradingDate: string | null
  coverage: SnapshotCoverageReport | null
  severity: 'ok' | 'warn' | 'danger'
  backupSyncState: SnapshotBackupSyncState | null
  formalReadPolicy: SnapshotFormalReadPolicy
}

export interface CloudManifestItem {
  id: string
  type: SnapshotType
  tradingDate: string
  slotTime: string
  timestamp: number
  displayKey: string
  size: number
  contentHash: string
  uploadedAt: number
  storageKey: string
}

export interface CloudManifestWindow {
  items: CloudManifestItem[]
  nextCursor?: string | null
}

export interface CloudUploadResult {
  ok: boolean
  id: string
  uploadedAt: number
  contentHash: string
  storageKey: string
}

export interface CloudDayBundleUploadResult {
  ok: boolean
  tradingDate: string
  uploadedAt: number
  contentHash: string
  storageKey: string
  snapshotCount: number
  frameCount?: number
  stockRowCount?: number
  sectorRowCount?: number
}

export interface SnapshotDayBundle {
  version: 'v4'
  tradingDate: string
  items: SnapshotRecord[]
  frames: SnapshotFrameRow[]
  stockRows: SnapshotStockRow[]
  sectorRows: SnapshotSectorRow[]
}

export interface CloudBatchUploadResult {
  ok: boolean
  total: number
  success: number
  failed: number
  results: CloudUploadResult[]
  errors: Array<{ id: string; message: string }>
}

export interface CloudBackupHealth {
  ok: boolean
  enabled: boolean
  requestId?: string
  message?: string
  rootPath?: string
  baseUrl?: string
  writable?: boolean
  errorCode?: string
}
