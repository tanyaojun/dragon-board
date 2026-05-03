import { dataLayer } from '../DataLayer'
import { SnapshotRuntime } from './runtime'
import type {
  SnapshotFrameBundle,
  SnapshotFrameQueryOptions,
  SnapshotQueryOptions,
  SnapshotSectorRow,
  SnapshotStockRow,
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
  listSnapshots = snapshotRuntime.listSnapshots.bind(snapshotRuntime)
  getSnapshotById = snapshotRuntime.getSnapshotById.bind(snapshotRuntime)
  getTradingDateSnapshot = snapshotRuntime.getTradingDateSnapshot.bind(snapshotRuntime)
  listSnapshotFrames = snapshotRuntime.listSnapshotFrames.bind(snapshotRuntime)
  listSnapshotStockRows = snapshotRuntime.listSnapshotStockRows.bind(snapshotRuntime)
  listSnapshotSectorRows = snapshotRuntime.listSnapshotSectorRows.bind(snapshotRuntime)
  getSnapshotProjectionMeta = snapshotRuntime.getSnapshotProjectionMeta.bind(snapshotRuntime)
  rebuildSnapshotProjectionStores = snapshotRuntime.rebuildSnapshotProjectionStores.bind(snapshotRuntime)
  alignSnapshotBackups = snapshotRuntime.alignSnapshotBackups.bind(snapshotRuntime)
  compactSnapshotRawRecords = snapshotRuntime.compactSnapshotRawRecords.bind(snapshotRuntime)
  runSnapshotStorageMaintenance = snapshotRuntime.runSnapshotStorageMaintenance.bind(snapshotRuntime)
  cleanupInvalidRuntimeSnapshots = snapshotRuntime.cleanupInvalidRuntimeSnapshots.bind(snapshotRuntime)
  getStockVolumeHistory = snapshotRuntime.getStockVolumeHistory.bind(snapshotRuntime)
  getLatestSnapshotRecord = snapshotRuntime.getLatestSnapshotRecord.bind(snapshotRuntime)
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
  saveFiveMinuteSnapshot = snapshotRuntime.saveFiveMinuteSnapshot.bind(snapshotRuntime)
  start = snapshotRuntime.start.bind(snapshotRuntime)
  stop = snapshotRuntime.stop.bind(snapshotRuntime)

  async listSnapshotFrameBundles(
    options: SnapshotFrameQueryOptions | SnapshotQueryOptions = {},
  ): Promise<SnapshotFrameBundle[]> {
    const frames = await snapshotRuntime.listSnapshotFrames(options as SnapshotFrameQueryOptions)
    if (frames.length === 0) return []

    const stockRowsBySnapshotId = new Map<string, SnapshotStockRow[]>()
    const sectorRowsBySnapshotId = new Map<string, SnapshotSectorRow[]>()

    await Promise.all(
      frames.map(async (frame) => {
        const [rows, entities] = await Promise.all([
          snapshotRuntime.listSnapshotStockRows({ snapshotId: frame.snapshotId, sort: 'asc' }),
          snapshotRuntime.listSnapshotSectorRows({ snapshotId: frame.snapshotId, sort: 'asc' }),
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
}

export const snapshotFacade = new SnapshotFacade()

if (typeof window !== 'undefined') {
  snapshotFacade.start()
  ;(window as any).snapshotFacade = snapshotFacade
}

export * from './types'
