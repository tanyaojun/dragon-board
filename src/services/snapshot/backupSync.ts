import { createSnapshotQualityMetadata } from './identity'
import { SnapshotFrameStore, SnapshotProjectionWriter, SnapshotSectorRowStore, SnapshotStockRowStore, SnapshotStore } from './store'
import { buildCanonicalProjectionBundle } from './projectionBundle'
import type { SnapshotProjectionBundle, SnapshotRecord } from './types'

type BackupMode = 'all'

interface BackupSyncLogger {
  debug?: (...args: any[]) => void
  log?: (...args: any[]) => void
  warn?: (...args: any[]) => void
}

interface SnapshotBackupSyncConfig {
  primaryStore: SnapshotStore
  primaryProjectionWriter?: SnapshotProjectionWriter
  primaryFrameStore?: SnapshotFrameStore
  primaryStockRowStore?: SnapshotStockRowStore
  primarySectorRowStore?: SnapshotSectorRowStore
  bucketStoreProvider: () => Promise<SnapshotStore | null>
  bucketFrameStoreProvider?: () => Promise<SnapshotFrameStore | null>
  bucketStockRowStoreProvider?: () => Promise<SnapshotStockRowStore | null>
  bucketSectorRowStoreProvider?: () => Promise<SnapshotSectorRowStore | null>
  bucketProjectionWriterProvider?: () => Promise<SnapshotProjectionWriter | null>
  bucketManagerProvider: () => any | null
  bucketName: string
  minBackupCount: number
  abnormalRatio: number
  logger?: BackupSyncLogger
  onBucketSyncSuccess?: (tradingDate: string, syncedAt: number) => void
  onBucketSyncError?: (tradingDate: string, error: unknown) => void
}

// 这个类只负责”主库和副本之间如何搬运”，不负责正式读取口径。
// 云端备份已废弃，由 QuantBoard/Supabase outbox 承接。
export class SnapshotBackupSync {
  private readonly primaryStore: SnapshotStore
  private readonly primaryProjectionWriter?: SnapshotProjectionWriter
  private readonly primaryFrameStore?: SnapshotFrameStore
  private readonly primaryStockRowStore?: SnapshotStockRowStore
  private readonly primarySectorRowStore?: SnapshotSectorRowStore
  private readonly bucketStoreProvider: () => Promise<SnapshotStore | null>
  private readonly bucketFrameStoreProvider?: () => Promise<SnapshotFrameStore | null>
  private readonly bucketStockRowStoreProvider?: () => Promise<SnapshotStockRowStore | null>
  private readonly bucketSectorRowStoreProvider?: () => Promise<SnapshotSectorRowStore | null>
  private readonly bucketProjectionWriterProvider?: () => Promise<SnapshotProjectionWriter | null>
  private readonly bucketManagerProvider: () => any | null
  private readonly bucketName: string
  private readonly minBackupCount: number
  private readonly abnormalRatio: number
  private readonly logger: BackupSyncLogger
  private readonly onBucketSyncSuccess?: (tradingDate: string, syncedAt: number) => void
  private readonly onBucketSyncError?: (tradingDate: string, error: unknown) => void

  constructor(config: SnapshotBackupSyncConfig) {
    this.primaryStore = config.primaryStore
    this.primaryProjectionWriter = config.primaryProjectionWriter
    this.primaryFrameStore = config.primaryFrameStore
    this.primaryStockRowStore = config.primaryStockRowStore
    this.primarySectorRowStore = config.primarySectorRowStore
    this.bucketStoreProvider = config.bucketStoreProvider
    this.bucketFrameStoreProvider = config.bucketFrameStoreProvider
    this.bucketStockRowStoreProvider = config.bucketStockRowStoreProvider
    this.bucketSectorRowStoreProvider = config.bucketSectorRowStoreProvider
    this.bucketProjectionWriterProvider = config.bucketProjectionWriterProvider
    this.bucketManagerProvider = config.bucketManagerProvider
    this.bucketName = config.bucketName
    this.minBackupCount = config.minBackupCount
    this.abnormalRatio = config.abnormalRatio
    this.logger = config.logger || {}
    this.onBucketSyncSuccess = config.onBucketSyncSuccess
    this.onBucketSyncError = config.onBucketSyncError
  }

  async saveToBackups(
    snapshotOrBundle: SnapshotRecord | SnapshotProjectionBundle,
    options?: { overwrite?: boolean },
  ): Promise<void> {
    const bundle = this.normalizeProjectionBundle(snapshotOrBundle)
    await this.syncRecordToLocalBackups(bundle.record, {
      bundle,
      overwrite: options?.overwrite,
    })
  }

  async getBackupStats(): Promise<{
    totalSnapshots: number
    estimatedSize: number
    mode: BackupMode
    bucketSnapshots: number
  }> {
    try {
      const bucketStore = await this.bucketStoreProvider()
      const bucketRecords = bucketStore ? await bucketStore.getAll() : []
      const allRecords = new Map<string, SnapshotRecord>()

      for (const record of bucketRecords) {
        allRecords.set(record.id, record)
      }

      return {
        totalSnapshots: allRecords.size,
        estimatedSize: Array.from(allRecords.values()).reduce(
          (sum, item) => sum + JSON.stringify(item.payload).length,
          0,
        ),
        mode: 'all',
        bucketSnapshots: bucketRecords.length,
      }
    } catch (error) {
      this.logger.warn?.('[DataLayer] Failed to collect backup stats:', error)
      return {
        totalSnapshots: 0,
        estimatedSize: 0,
        mode: 'all',
        bucketSnapshots: 0,
      }
    }
  }

  async getBucketHealth(): Promise<{
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
    const manager = this.bucketManagerProvider()
    if (!manager) {
      return {
        supported: false,
        bucketName: this.bucketName,
        bucketOpened: false,
        error: 'storage_buckets_not_supported',
      }
    }

    try {
      const bucketStore = await this.bucketStoreProvider()
      if (!bucketStore) {
        return {
          supported: true,
          bucketName: this.bucketName,
          bucketOpened: false,
          error: 'bucket_open_failed',
        }
      }

      const keys = typeof manager.keys === 'function' ? ((await manager.keys()) as string[]) : []
      const bucket = typeof manager.open === 'function' ? await manager.open(this.bucketName) : null
      const persisted =
        typeof bucket?.persisted === 'function' ? ((await bucket.persisted()) as boolean) : undefined
      const durability =
        typeof bucket?.durability === 'function' ? String(await bucket.durability()) : undefined
      const estimate =
        typeof bucket?.estimate === 'function' ? ((await bucket.estimate()) as StorageEstimate) : undefined

      return {
        supported: true,
        bucketName: this.bucketName,
        bucketOpened: true,
        persisted,
        durability,
        usage: estimate?.usage,
        quota: estimate?.quota,
        keys,
      }
    } catch (error) {
      return {
        supported: true,
        bucketName: this.bucketName,
        bucketOpened: false,
        error: error instanceof Error ? error.message : String(error),
      }
    }
  }

  getCloudHealth() {
    return {
      ok: false,
      enabled: false,
      message: 'cloud_backup_disabled',
    }
  }

  async deleteFromLocalBackups(snapshotId: string): Promise<boolean> {
    if (!snapshotId) return false
    const [bucketStore, bucketFrameStore, bucketStockRowStore, bucketSectorRowStore] = await Promise.all([
      this.bucketStoreProvider(),
      this.bucketFrameStoreProvider?.() || Promise.resolve(null),
      this.bucketStockRowStoreProvider?.() || Promise.resolve(null),
      this.bucketSectorRowStoreProvider?.() || Promise.resolve(null),
    ])
    if (!bucketStore) return false

    const existing = await bucketStore.getById(snapshotId)
    if (!existing) return false

    await Promise.all([
      bucketFrameStore?.deleteBySnapshotId(snapshotId) || Promise.resolve(),
      bucketStockRowStore?.deleteBySnapshotId(snapshotId) || Promise.resolve(),
      bucketSectorRowStore?.deleteBySnapshotId(snapshotId) || Promise.resolve(),
    ])
    await bucketStore.delete(snapshotId)
    return true
  }

  async cleanupInvalidLocalBackups(
    isInvalid: (record: SnapshotRecord) => boolean,
  ): Promise<{
    scanned: number
    deleted: number
    affectedTradingDates: string[]
    deletedSnapshotIds: string[]
  }> {
    const [bucketStore, bucketFrameStore, bucketStockRowStore, bucketSectorRowStore] = await Promise.all([
      this.bucketStoreProvider(),
      this.bucketFrameStoreProvider?.() || Promise.resolve(null),
      this.bucketStockRowStoreProvider?.() || Promise.resolve(null),
      this.bucketSectorRowStoreProvider?.() || Promise.resolve(null),
    ])
    if (!bucketStore) {
      return { scanned: 0, deleted: 0, affectedTradingDates: [], deletedSnapshotIds: [] }
    }

    const records = await bucketStore.getAll()
    const affectedTradingDates = new Set<string>()
    const deletedSnapshotIds: string[] = []

    for (const record of records) {
      if (!record?.id || !isInvalid(record)) continue
      await Promise.all([
        bucketFrameStore?.deleteBySnapshotId(record.id) || Promise.resolve(),
        bucketStockRowStore?.deleteBySnapshotId(record.id) || Promise.resolve(),
        bucketSectorRowStore?.deleteBySnapshotId(record.id) || Promise.resolve(),
      ])
      await bucketStore.delete(record.id)
      deletedSnapshotIds.push(record.id)
      if (record.tradingDate) affectedTradingDates.add(record.tradingDate)
    }

    return {
      scanned: records.length,
      deleted: deletedSnapshotIds.length,
      affectedTradingDates: Array.from(affectedTradingDates).sort(),
      deletedSnapshotIds,
    }
  }

  async restorePrimaryFromBackups(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    restored: number
    skipped: number
    totalFromBackup: number
    mode: BackupMode
  }> {
    const all = await this.getUnionBackupBundles()
    const maxCount = options?.limit && options.limit > 0 ? options.limit : all.length
    const target = all
      .sort((left, right) => (left.record?.timestamp || 0) - (right.record?.timestamp || 0))
      .slice(0, maxCount)

    let restored = 0
    let skipped = 0

    for (const bundle of target) {
      const snapshot = bundle.record
      if (!snapshot?.id) {
        skipped++
        continue
      }
      if (!options?.overwrite) {
        const existing = await this.primaryStore.getById(snapshot.id)
        if (existing) {
          skipped++
          continue
        }
      }
      await this.restorePrimaryBundle(this.asRestoredBundle(bundle, 'bucket_restore'))
      restored++
    }

    return {
      restored,
      skipped,
      totalFromBackup: all.length,
      mode: 'all',
    }
  }

  async syncPrimaryToBackups(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    synced: number
    skipped: number
    totalPrimary: number
    bucketSynced: number
    mode: BackupMode
  }> {
    const bucketStore = await this.bucketStoreProvider()
    const bucketRecords = bucketStore ? await bucketStore.getAll() : []
    const bucketKeys = new Set<string>(bucketRecords.map((item) => item.id).filter(Boolean))
    const snapshots = await this.primaryStore.list({ sort: 'desc' })
    const maxCount = options?.limit && options.limit > 0 ? options.limit : snapshots.length
    const targetSnapshots = snapshots.slice(0, maxCount)

    let synced = 0
    let skipped = 0
    let bucketSynced = 0

    for (const snapshot of targetSnapshots) {
      const bundle = await this.buildProjectionBundleFromPrimary(snapshot)
      const localResult = await this.syncRecordToLocalBackups(snapshot, {
        bundle,
        overwrite: options?.overwrite,
        bucketKeys,
        bucketStore,
      })
      bucketSynced += localResult.bucketSynced

      if (localResult.changed) {
        synced++
      } else {
        skipped++
      }
    }

    return {
      synced,
      skipped,
      totalPrimary: snapshots.length,
      bucketSynced,
      mode: 'all',
    }
  }

  async syncAllStores(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    primaryCount: number
    bucketBackupCount: number
    insertedToPrimary: number
    insertedToBucketBackup: number
    mode: BackupMode
  }> {
    const primary = await this.primaryStore.list({ sort: 'desc' })
    const bucketStore = await this.bucketStoreProvider()
    const bucketRecords = bucketStore ? await bucketStore.getAll() : []
    const union = new Map<string, SnapshotRecord>()

    for (const record of [...primary, ...bucketRecords]) {
      union.set(record.id, record)
    }

    const primaryKeys = new Set(primary.map((item) => item.id))
    const bucketKeys = new Set(bucketRecords.map((item) => item.id))

    let insertedToPrimary = 0
    let insertedToBucketBackup = 0

    const allRecords = Array.from(union.values())
      .sort((a, b) => a.timestamp - b.timestamp)
      .slice(0, options?.limit && options.limit > 0 ? options.limit : union.size)

    for (const record of allRecords) {
      if ((options?.overwrite || !primaryKeys.has(record.id)) && !primaryKeys.has(record.id)) {
        await this.primaryStore.put(record)
        primaryKeys.add(record.id)
        insertedToPrimary++
      }

      const bundle = await this.buildProjectionBundleFromPrimary(record)
      const localResult = await this.syncRecordToLocalBackups(record, {
        bundle,
        overwrite: options?.overwrite,
        bucketKeys,
        bucketStore,
      })
      insertedToBucketBackup += localResult.bucketSynced
    }

    return {
      primaryCount: primary.length,
      bucketBackupCount: bucketRecords.length,
      insertedToPrimary,
      insertedToBucketBackup,
      mode: 'all',
    }
  }

  async runAutoRecoveryCheck(options?: {
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
    mode: BackupMode
  }> {
    const primary = await this.primaryStore.getStats()
    const backup = await this.getBackupStats()
    const bucketHealth = await this.getBucketHealth()

    if (primary.totalSnapshots > 0 && backup.totalSnapshots === 0) {
      const seedResult = await this.syncPrimaryToBackups({ overwrite: false })
      this.logger.warn?.(
        `[DataLayer] Backup seed executed: primary=${primary.totalSnapshots}, synced=${seedResult.synced}, skipped=${seedResult.skipped}, mode=${seedResult.mode}`,
      )
      return {
        checked: true,
        recovered: seedResult.synced > 0,
        reason: 'backup_seeded_from_primary',
        primaryCount: primary.totalSnapshots,
        backupCount: backup.totalSnapshots,
        restored: seedResult.synced,
        skipped: seedResult.skipped,
        mode: seedResult.mode,
      }
    }

    const minBackupCount = options?.minBackupCount ?? this.minBackupCount
    const abnormalRatio = options?.abnormalRatio ?? this.abnormalRatio
    const ratio = backup.totalSnapshots > 0 ? primary.totalSnapshots / backup.totalSnapshots : 1
    const shouldRecover =
      options?.force === true ||
      (backup.totalSnapshots >= minBackupCount &&
        primary.totalSnapshots < backup.totalSnapshots &&
        ratio <= abnormalRatio)

    if (!shouldRecover) {
      if (bucketHealth.supported) {
        this.logger.log?.(
          `[DataLayer] Snapshot guard check: bucketOpened=${bucketHealth.bucketOpened}, persisted=${String(bucketHealth.persisted)}, durability=${bucketHealth.durability || 'n/a'}, primary=${primary.totalSnapshots}, backup=${backup.totalSnapshots}`,
        )
      }
      return {
        checked: true,
        recovered: false,
        reason: 'no_recovery_needed',
        primaryCount: primary.totalSnapshots,
        backupCount: backup.totalSnapshots,
        restored: 0,
        skipped: 0,
        mode: 'all',
      }
    }

    const restored = await this.restorePrimaryFromBackups({ overwrite: false })
    this.logger.warn?.(
      `[DataLayer] Snapshot auto-recovery executed: primary=${primary.totalSnapshots}, backup=${backup.totalSnapshots}, restored=${restored.restored}, skipped=${restored.skipped}, mode=${restored.mode}`,
    )
    return {
      checked: true,
      recovered: restored.restored > 0,
      reason: 'auto_recovered',
      primaryCount: primary.totalSnapshots,
      backupCount: backup.totalSnapshots,
      restored: restored.restored,
      skipped: restored.skipped,
      mode: restored.mode,
    }
  }

  async syncPrimaryToCloud(_options?: {
    limit?: number
    overwrite?: boolean
    tradingDate?: string
    startDate?: string
    endDate?: string
  }) {
    // 云端备份已由 QuantBoard/Supabase outbox 承接。
    return { queued: 0, totalPrimary: 0 }
  }

  private async syncRecordToLocalBackups(
    snapshot: SnapshotRecord,
    state?: {
      bundle?: SnapshotProjectionBundle
      overwrite?: boolean
      bucketKeys?: Set<string>
      bucketStore?: SnapshotStore | null
      bucketProjectionWriter?: SnapshotProjectionWriter | null
    },
  ): Promise<{ changed: boolean; bucketSynced: number }> {
    try {
      const bundle = this.normalizeProjectionBundle(state?.bundle || snapshot)
      // 批量同步时会把 keys 和 bucketStore 复用传进来，避免每条记录都重复全表读取。
      const bucketStore = state?.bucketStore === undefined ? await this.bucketStoreProvider() : state.bucketStore
      const bucketProjectionWriter =
        state?.bucketProjectionWriter === undefined
          ? (await this.bucketProjectionWriterProvider?.()) || null
          : state.bucketProjectionWriter
      const bucketKeys =
        state?.bucketKeys ||
        new Set<string>((bucketStore ? await bucketStore.getAll() : []).map((item) => item.id))

      let bucketSynced = 0

      const needsBucket = bucketStore ? state?.overwrite || !bucketKeys.has(snapshot.id) : false

      if (bucketStore && (bucketProjectionWriter || needsBucket)) {
        if (bucketProjectionWriter) {
          await bucketProjectionWriter.saveBundle(bundle)
        } else if (needsBucket) {
          await bucketStore.put(snapshot)
        }
      }
      if (needsBucket) {
        bucketKeys.add(snapshot.id)
        bucketSynced++
      }
      if (bucketStore && snapshot.tradingDate && (bucketSynced > 0 || bucketKeys.has(snapshot.id))) {
        this.onBucketSyncSuccess?.(snapshot.tradingDate, Date.now())
      }

      return {
        changed: bucketSynced > 0,
        bucketSynced,
      }
    } catch (error) {
      if (snapshot.tradingDate) {
        this.onBucketSyncError?.(snapshot.tradingDate, error)
      }
      throw error
    }
  }

  private async getUnionBackupBundles(): Promise<SnapshotProjectionBundle[]> {
    const bundles = new Map<string, SnapshotProjectionBundle>()

    const bucketStore = await this.bucketStoreProvider()
    if (bucketStore) {
      const [bucketFrameStore, bucketStockRowStore, bucketSectorRowStore] = await Promise.all([
        this.bucketFrameStoreProvider?.() || Promise.resolve(null),
        this.bucketStockRowStoreProvider?.() || Promise.resolve(null),
        this.bucketSectorRowStoreProvider?.() || Promise.resolve(null),
      ])
      const bucketRecords = await bucketStore.getAll()
      for (const record of bucketRecords) {
        const bundle = await this.buildProjectionBundleFromExternalStores(record, {
          frameStore: bucketFrameStore || undefined,
          stockRowStore: bucketStockRowStore || undefined,
          sectorRowStore: bucketSectorRowStore || undefined,
        })
        bundles.set(record.id, bundle)
      }
    }

    return Array.from(bundles.values())
  }

  private async restorePrimaryBundle(bundle: SnapshotProjectionBundle): Promise<void> {
    if (this.primaryProjectionWriter) {
      await this.primaryProjectionWriter.saveBundle(bundle)
      return
    }

    await this.primaryStore.put(bundle.record)
  }

  private async buildProjectionBundleFromExternalStores(
    record: SnapshotRecord,
    stores: {
      frameStore?: SnapshotFrameStore
      stockRowStore?: SnapshotStockRowStore
      sectorRowStore?: SnapshotSectorRowStore
    },
  ): Promise<SnapshotProjectionBundle> {
    if (record.type === 'five_minute') {
      return this.normalizeProjectionBundle(record)
    }

    const [existingFrame, existingStockRows, existingSectorRows] = await Promise.all([
      stores.frameStore?.getBySnapshotId(record.id) || Promise.resolve(null),
      stores.stockRowStore?.list({ snapshotId: record.id, sort: 'asc' }) || Promise.resolve([]),
      stores.sectorRowStore?.list({ snapshotId: record.id, sort: 'asc' }) || Promise.resolve([]),
    ])

    const bundle = buildCanonicalProjectionBundle(record, {
      existingStockRows,
      existingSectorRows,
    })

    if (bundle.frame && existingFrame) {
      bundle.frame.stockRowCount = bundle.stockRows.length
      bundle.frame.sectorRowCount = bundle.sectorRows.length
    }

    return bundle
  }

  private asRestoredRecord(
    snapshot: SnapshotRecord,
    source: 'bucket_restore',
  ): SnapshotRecord {
    // 恢复记录必须显式标成 restored，正式分析默认会排除它们。
    const slotDate = new Date(snapshot.timestamp || Date.now())
    return {
      ...snapshot,
      ...createSnapshotQualityMetadata(slotDate, {
        captureMode: 'restored',
        capturedAt: Date.now(),
        dataTimestamp: snapshot.dataTimestamp || snapshot.timestamp,
        delayMs: snapshot.delayMs || 0,
        qualityFlags: Array.from(new Set([...(snapshot.qualityFlags || []), 'restored_from_backup'])),
        source,
      }),
    }
  }

  private asRestoredBundle(
    bundle: SnapshotProjectionBundle,
    source: 'bucket_restore',
  ): SnapshotProjectionBundle {
    const restoredRecord = this.asRestoredRecord(bundle.record, source)
    return buildCanonicalProjectionBundle(restoredRecord, {
      existingStockRows: bundle.stockRows,
      existingSectorRows: bundle.sectorRows,
    })
  }

  private normalizeProjectionBundle(snapshotOrBundle: SnapshotRecord | SnapshotProjectionBundle): SnapshotProjectionBundle {
    if (snapshotOrBundle && typeof snapshotOrBundle === 'object' && 'record' in snapshotOrBundle) {
      return {
        record: snapshotOrBundle.record,
        frame: snapshotOrBundle.frame || null,
        stockRows: Array.isArray(snapshotOrBundle.stockRows) ? snapshotOrBundle.stockRows : [],
        sectorRows: Array.isArray(snapshotOrBundle.sectorRows) ? snapshotOrBundle.sectorRows : [],
      }
    }

    return {
      record: snapshotOrBundle,
      frame: null,
      stockRows: [],
      sectorRows: [],
    }
  }

  private async buildProjectionBundleFromPrimary(record: SnapshotRecord): Promise<SnapshotProjectionBundle> {
    if (record.type === 'five_minute') {
      return this.normalizeProjectionBundle(record)
    }

    const [existingFrame, stockRows, sectorRows] = await Promise.all([
      this.primaryFrameStore?.getBySnapshotId(record.id) || Promise.resolve(null),
      this.primaryStockRowStore?.list({ snapshotId: record.id, sort: 'asc' }) || Promise.resolve([]),
      this.primarySectorRowStore?.list({ snapshotId: record.id, sort: 'asc' }) || Promise.resolve([]),
    ])

    const bundle = buildCanonicalProjectionBundle(record, {
      existingStockRows: stockRows,
      existingSectorRows: sectorRows,
    })

    if (bundle.frame && existingFrame) {
      bundle.frame.stockRowCount = bundle.stockRows.length
      bundle.frame.sectorRowCount = bundle.sectorRows.length
    }

    return bundle
  }

}
