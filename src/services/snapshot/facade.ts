import { dataLayer } from '../DataLayer'
import { snapshotBackendRead } from './backendRead'
import { assertFormalSnapshotType, assertFormalSnapshotTypes, type FormalSnapshotType } from './identity'
import { SnapshotRuntime } from './runtime'
import type {
  SnapshotFrameBundle,
  SnapshotFrameQueryOptions,
  SnapshotQueryOptions,
  SnapshotSectorRowQueryOptions,
  SnapshotStockRowQueryOptions,
  SnapshotType,
} from './types'

const PRIMARY_DB_NAME = 'DragonBoardData'
const PRIMARY_DB_VERSION = 9
const PRIMARY_STORE_NAME = 'snapshots'
const LEGACY_BACKUP_DB_NAME = 'DragonBoardDataBackup'
const BUCKET_BACKUP_DB_NAME = 'DragonBoardBucketBackup'
const BACKUP_DB_VERSION = 5
const BACKUP_STORE_NAME = 'snapshots_backup'
const BACKUP_BUCKET_NAME = 'dragon-snapshot-backup'
const SNAPSHOT_GUARD_MIN_BACKUP = 20
const SNAPSHOT_GUARD_RATIO = 0.4
const SNAPSHOT_SYNC_INTERVAL_MS = 5 * 60 * 1000
type FormalSnapshotQueryOptions = Omit<SnapshotQueryOptions, 'type' | 'types'> & {
  type?: FormalSnapshotType
  types?: FormalSnapshotType[]
}

const snapshotRuntime = new SnapshotRuntime({
  logger: console,
  primaryDbName: PRIMARY_DB_NAME,
  primaryDbVersion: PRIMARY_DB_VERSION,
  primaryStoreName: PRIMARY_STORE_NAME,
  enableIndexedDbSnapshotCache: false,
  legacyBackupDbName: LEGACY_BACKUP_DB_NAME,
  bucketBackupDbName: BUCKET_BACKUP_DB_NAME,
  backupDbVersion: BACKUP_DB_VERSION,
  backupStoreName: BACKUP_STORE_NAME,
  backupBucketName: BACKUP_BUCKET_NAME,
  minBackupCount: SNAPSHOT_GUARD_MIN_BACKUP,
  abnormalRatio: SNAPSHOT_GUARD_RATIO,
  syncIntervalMs: SNAPSHOT_SYNC_INTERVAL_MS,
  getStorageBucketManager: () =>
    typeof navigator === 'undefined' ? null : (navigator as any).storageBuckets || null,
  getBuildContext: () => ({
    stocks: dataLayer.getStocks() || [],
    depth10ByCode: dataLayer.getDepth10Map(),
    recentTicksByCode: dataLayer.getRecentTicksMap(),
    l2SummaryByCode: dataLayer.getL2SummaryMap(),
    breathData: dataLayer.getBreathData(),
    marketData: dataLayer.getBreathMarketData(),
    jxbkBlocks: dataLayer.getJxbkBlocksSorted(100),
    jxbkStocks: dataLayer.getJxbkStockMap(),
    hotThemes: dataLayer.getHotThemes() || [],
    rotationAnalysis: dataLayer.getCurrentRotation(),
    breathHistory: dataLayer.getBreathHistory(),
    breathFactors: dataLayer.getBreathFactors(),
    marketMode: dataLayer.getMarketMode(),
    stocksVersion: dataLayer.getVersion().stocks,
  }),
})

snapshotRuntime.setMongoPrimaryExistsHandler(async (snapshotId) => {
  const record = await snapshotBackendRead.getSnapshotById(snapshotId)
  return Boolean(record)
})

class SnapshotFacade {
  saveQuarterHourSnapshot = snapshotRuntime.saveQuarterHourSnapshot.bind(snapshotRuntime)
  saveHalfHourSnapshot = snapshotRuntime.saveHalfHourSnapshot.bind(snapshotRuntime)
  saveHourlySnapshot = snapshotRuntime.saveHourlySnapshot.bind(snapshotRuntime)
  generateDailySnapshot = snapshotRuntime.generateDailySnapshot.bind(snapshotRuntime)
  exportDailySnapshot = snapshotRuntime.exportDailySnapshot.bind(snapshotRuntime)
  exportStockQuarterSnapshots = snapshotRuntime.exportStockQuarterSnapshots.bind(snapshotRuntime)
  exportSnapshotToExcel = snapshotRuntime.exportSnapshotToExcel.bind(snapshotRuntime)
  exportSnapshotsRangeToExcel = snapshotRuntime.exportSnapshotsRangeToExcel.bind(snapshotRuntime)
  saveDailySnapshot = snapshotRuntime.saveDailySnapshot.bind(snapshotRuntime)
  async listSnapshots(options: FormalSnapshotQueryOptions = {}) {
    assertFormalSnapshotType(options.type)
    assertFormalSnapshotTypes(options.types)
    return snapshotBackendRead.listSnapshots(options as SnapshotQueryOptions)
  }

  async getSnapshotById(id: string) {
    return snapshotBackendRead.getSnapshotById(id)
  }

  async getTradingDateSnapshot(type: FormalSnapshotType, tradingDate: string) {
    assertFormalSnapshotType(type)
    return snapshotBackendRead.getTradingDateSnapshot(type, tradingDate)
  }

  async listSnapshotFrames(options: SnapshotFrameQueryOptions = {}) {
    return snapshotBackendRead.listSnapshotFrames(options)
  }

  async listSnapshotStockRows(options: SnapshotStockRowQueryOptions = {}) {
    return snapshotBackendRead.listSnapshotStockRows(options)
  }

  async listSnapshotSectorRows(options: SnapshotSectorRowQueryOptions = {}) {
    return snapshotBackendRead.listSnapshotSectorRows(options)
  }
  getSnapshotProjectionMeta = snapshotRuntime.getSnapshotProjectionMeta.bind(snapshotRuntime)
  rebuildSnapshotProjectionStores = snapshotRuntime.rebuildSnapshotProjectionStores.bind(snapshotRuntime)
  alignSnapshotBackups = snapshotRuntime.alignSnapshotBackups.bind(snapshotRuntime)
  compactSnapshotRawRecords = snapshotRuntime.compactSnapshotRawRecords.bind(snapshotRuntime)
  runSnapshotStorageMaintenance = snapshotRuntime.runSnapshotStorageMaintenance.bind(snapshotRuntime)
  cleanupInvalidRuntimeSnapshots = snapshotRuntime.cleanupInvalidRuntimeSnapshots.bind(snapshotRuntime)
  getStockVolumeHistory = snapshotBackendRead.getStockVolumeHistory.bind(snapshotBackendRead)

  async getLatestSnapshotRecord(options?: {
    type?: FormalSnapshotType
    beforeTradingDate?: string
    allowedCaptureModes?: Array<'real_time' | 'delayed' | 'restored'>
    excludeRestored?: boolean
  }) {
    assertFormalSnapshotType(options?.type)
    const records = await snapshotBackendRead.listSnapshots({
      type: options?.type,
      beforeTradingDate: options?.beforeTradingDate,
      allowedCaptureModes: options?.allowedCaptureModes,
      excludeRestored: options?.excludeRestored,
      sort: 'desc',
      limit: 1,
    })
    return records[0] || null
  }
  exportSnapshotAsFile = snapshotRuntime.exportSnapshotAsFile.bind(snapshotRuntime)
  exportAllSnapshots = snapshotRuntime.exportAllSnapshots.bind(snapshotRuntime)
  deleteSnapshot = snapshotRuntime.deleteSnapshot.bind(snapshotRuntime)
  getSnapshotStorageStats = snapshotRuntime.getSnapshotStorageStats.bind(snapshotRuntime)
  getBackupSnapshotStorageStats = snapshotRuntime.getBackupSnapshotStorageStats.bind(snapshotRuntime)
  getBackupBucketHealth = snapshotRuntime.getBackupBucketHealth.bind(snapshotRuntime)
  getCloudBackupHealth = snapshotRuntime.getCloudBackupHealth.bind(snapshotRuntime)
  getSnapshotBackupSyncState = snapshotRuntime.getSnapshotBackupSyncState.bind(snapshotRuntime)
  listSnapshotBackupSyncStates = snapshotRuntime.listSnapshotBackupSyncStates.bind(snapshotRuntime)
  getSnapshotHealthOverview = snapshotRuntime.getSnapshotHealthOverview.bind(snapshotRuntime)
  restoreSnapshotsFromBackup = snapshotRuntime.restoreSnapshotsFromBackup.bind(snapshotRuntime)
  syncPrimarySnapshotsToBackup = snapshotRuntime.syncPrimarySnapshotsToBackup.bind(snapshotRuntime)
  syncPrimarySnapshotsToCloud = snapshotRuntime.syncPrimarySnapshotsToCloud.bind(snapshotRuntime)
  syncAllSnapshotStores = snapshotRuntime.syncAllSnapshotStores.bind(snapshotRuntime)
  runSnapshotAutoRecoveryCheck = snapshotRuntime.runSnapshotAutoRecoveryCheck.bind(snapshotRuntime)
  inspectTradingDateSnapshotCoverage = snapshotRuntime.inspectTradingDateSnapshotCoverage.bind(snapshotRuntime)
  buildSnapshotCoverageWindow = snapshotRuntime.buildSnapshotCoverageWindow.bind(snapshotRuntime)
  repairTradingDateSnapshotCoverage = snapshotRuntime.repairTradingDateSnapshotCoverage.bind(snapshotRuntime)
  start = snapshotRuntime.start.bind(snapshotRuntime)
  stop = snapshotRuntime.stop.bind(snapshotRuntime)

  async listSnapshotFrameBundles(
    options: SnapshotFrameQueryOptions | FormalSnapshotQueryOptions = {},
  ): Promise<SnapshotFrameBundle[]> {
    assertFormalSnapshotType(options.type)
    assertFormalSnapshotTypes((options as FormalSnapshotQueryOptions).types)
    return snapshotBackendRead.listSnapshotFrameBundles(options)
  }
}

export const snapshotFacade = new SnapshotFacade()

if (typeof window !== 'undefined') {
  snapshotFacade.start()
  ;(window as any).snapshotFacade = snapshotFacade
}

export * from './types'
