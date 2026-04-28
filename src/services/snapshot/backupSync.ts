import { SnapshotCloudBackup } from './cloudBackup'
import { createSnapshotQualityMetadata } from './identity'
import { SnapshotFrameStore, SnapshotProjectionWriter, SnapshotSectorRowStore, SnapshotStockRowStore, SnapshotStore } from './store'
import { buildCanonicalProjectionBundle } from './projectionBundle'
import type { CloudManifestItem, SnapshotDayBundle, SnapshotProjectionBundle, SnapshotRecord } from './types'

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
  cloudBackup: SnapshotCloudBackup
  logger?: BackupSyncLogger
  onBucketSyncSuccess?: (tradingDate: string, syncedAt: number) => void
  onBucketSyncError?: (tradingDate: string, error: unknown) => void
  onCloudBundleUploaded?: (tradingDate: string, uploadedAt: number) => void
  onCloudBundleError?: (tradingDate: string, error: unknown) => void
}

// 这个类只负责“主库和副本之间如何搬运”，不负责正式读取口径。
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
  private readonly cloudBackup: SnapshotCloudBackup
  private readonly logger: BackupSyncLogger
  private readonly onBucketSyncSuccess?: (tradingDate: string, syncedAt: number) => void
  private readonly onBucketSyncError?: (tradingDate: string, error: unknown) => void
  private readonly onCloudBundleUploaded?: (tradingDate: string, uploadedAt: number) => void
  private readonly onCloudBundleError?: (tradingDate: string, error: unknown) => void

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
    this.cloudBackup = config.cloudBackup
    this.logger = config.logger || {}
    this.onBucketSyncSuccess = config.onBucketSyncSuccess
    this.onBucketSyncError = config.onBucketSyncError
    this.onCloudBundleUploaded = config.onCloudBundleUploaded
    this.onCloudBundleError = config.onCloudBundleError
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
    remoteCloudSnapshots: number
  }> {
    try {
      const bucketStore = await this.bucketStoreProvider()
      const bucketRecords = bucketStore ? await bucketStore.getAll() : []
      const remoteManifest = await this.safeListRemoteManifest({ limit: 5000 })
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
        remoteCloudSnapshots: remoteManifest.length,
      }
    } catch (error) {
      this.logger.warn?.('[DataLayer] Failed to collect backup stats:', error)
      return {
        totalSnapshots: 0,
        estimatedSize: 0,
        mode: 'all',
        bucketSnapshots: 0,
        remoteCloudSnapshots: 0,
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

  async getCloudHealth() {
    return this.cloudBackup.getHealth()
  }

  async restorePrimaryFromBackups(options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    restored: number
    skipped: number
    totalFromBackup: number
    mode: BackupMode
    remoteRestored: number
  }> {
    // 恢复顺序是“先本地副本、再远端云端”，并把回主库的记录统一标成 restored。
    const all = await this.getUnionBackupBundles()
    const maxCount = options?.limit && options.limit > 0 ? options.limit : all.length
    const target = all
      .sort((left, right) => (left.record?.timestamp || 0) - (right.record?.timestamp || 0))
      .slice(0, maxCount)

    let restored = 0
    let skipped = 0
    let remoteRestored = 0

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

    if (restored < maxCount) {
      const manifest = await this.safeListRemoteManifest({ limit: maxCount })
      const existingIds = new Set((await this.primaryStore.getAll()).map((item) => item.id))
      const tradingDates = Array.from(
        new Set(
          manifest
            .map((item) => item.tradingDate)
            .filter((tradingDate): tradingDate is string => Boolean(tradingDate)),
        ),
      )
      for (const tradingDate of tradingDates) {
        if (remoteRestored + restored >= maxCount) break
        try {
          const bundle = await this.cloudBackup.downloadDayBundle(tradingDate)
          const projectionBundles = this.extractBundlesFromDayBundle(bundle)
          for (const projectionBundle of projectionBundles) {
            const snapshot = projectionBundle.record
            if (remoteRestored + restored >= maxCount) break
            if (!snapshot?.id) continue
            if (!options?.overwrite && existingIds.has(snapshot.id)) continue
            await this.restorePrimaryBundle(this.asRestoredBundle(projectionBundle, 'cloud_restore'))
            existingIds.add(snapshot.id)
            remoteRestored++
          }
        } catch (error) {
          this.logger.warn?.('[DataLayer] Remote snapshot restore failed:', tradingDate, error)
        }
      }
    }

    return {
      restored: restored + remoteRestored,
      skipped,
      totalFromBackup: all.length,
      mode: 'all',
      remoteRestored,
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
    remoteCloudSynced: number
    mode: BackupMode
  }> {
    // 日常主路径只要求主库 -> 本地备份补齐，不在这里顺手做云端上传。
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
      remoteCloudSynced: 0,
      mode: 'all',
    }
  }

  async syncAllStores(options?: {
    overwrite?: boolean
    limit?: number
    includeRemoteCloud?: boolean
  }): Promise<{
    primaryCount: number
    bucketBackupCount: number
    remoteCloudCount: number
    insertedToPrimary: number
    insertedToBucketBackup: number
    insertedToRemoteCloud: number
    mode: BackupMode
  }> {
    // 这是运维向的“全量对账”接口，不是正常写入链的一部分。
    const primary = await this.primaryStore.list({ sort: 'desc' })
    const bucketStore = await this.bucketStoreProvider()
    const bucketRecords = bucketStore ? await bucketStore.getAll() : []
    const union = new Map<string, SnapshotRecord>()

    for (const record of [...primary, ...bucketRecords]) {
      union.set(record.id, record)
    }

    const primaryKeys = new Set(primary.map((item) => item.id))
    const bucketKeys = new Set(bucketRecords.map((item) => item.id))
    const includeRemoteCloud = options?.includeRemoteCloud === true
    const remoteManifest = includeRemoteCloud ? await this.safeListRemoteManifest({ limit: 5000 }) : []
    const remoteKeys = new Set(remoteManifest.map((item) => item.tradingDate).filter(Boolean))
    const remoteTradingDatesToUpload = new Set<string>()

    let insertedToPrimary = 0
    let insertedToBucketBackup = 0
    let insertedToRemoteCloud = 0

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

      if (includeRemoteCloud && record.tradingDate && (options?.overwrite || !remoteKeys.has(record.tradingDate))) {
        remoteTradingDatesToUpload.add(record.tradingDate)
        remoteKeys.add(record.tradingDate)
      }
    }

    for (const tradingDate of remoteTradingDatesToUpload) {
      try {
        await this.uploadTradingDateBundle(tradingDate)
        insertedToRemoteCloud++
      } catch (error) {
        this.logger.warn?.('[DataLayer] Snapshot cloud bundle sync failed:', tradingDate, error)
      }
    }

    return {
      primaryCount: primary.length,
      bucketBackupCount: bucketRecords.length,
      remoteCloudCount: remoteKeys.size,
      insertedToPrimary,
      insertedToBucketBackup,
      insertedToRemoteCloud,
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
    remoteRestored: number
    mode: BackupMode
  }> {
    // 先判断要不要补种备份，再判断要不要从备份反向恢复主库，避免轻微波动触发误恢复。
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
        remoteRestored: 0,
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
        remoteRestored: 0,
        mode: 'all',
      }
    }

    const restored = await this.restorePrimaryFromBackups({ overwrite: false })
    this.logger.warn?.(
      `[DataLayer] Snapshot auto-recovery executed: primary=${primary.totalSnapshots}, backup=${backup.totalSnapshots}, restored=${restored.restored}, skipped=${restored.skipped}, remote=${restored.remoteRestored}, mode=${restored.mode}`,
    )
    return {
      checked: true,
      recovered: restored.restored > 0,
      reason: 'auto_recovered',
      primaryCount: primary.totalSnapshots,
      backupCount: backup.totalSnapshots,
      restored: restored.restored,
      skipped: restored.skipped,
      remoteRestored: restored.remoteRestored,
      mode: restored.mode,
    }
  }

  async syncPrimaryToCloud(options?: {
    limit?: number
    overwrite?: boolean
    tradingDate?: string
    startDate?: string
    endDate?: string
  }) {
    // 云端同步按交易日聚合，不再维护 per-snapshot jobs。
    const snapshots = await this.primaryStore.list({
      sort: 'desc',
      tradingDate: options?.tradingDate,
      startDate: options?.startDate,
      endDate: options?.endDate,
      allowedCaptureModes: ['real_time', 'delayed', 'restored'],
    })
    const targetSnapshots = snapshots.slice(0, options?.limit && options.limit > 0 ? options.limit : snapshots.length)
    const tradingDates = Array.from(
      new Set(
        targetSnapshots
          .map((record) => record.tradingDate)
          .filter((tradingDate): tradingDate is string => Boolean(tradingDate)),
      ),
    )
    const remoteManifest = options?.overwrite ? [] : await this.safeListRemoteManifest({ limit: 5000 })
    const remoteTradingDates = new Set(remoteManifest.map((item) => item.tradingDate).filter(Boolean))
    let queued = 0

    for (const tradingDate of tradingDates) {
      if (options?.overwrite || !remoteTradingDates.has(tradingDate)) {
        await this.uploadTradingDateBundle(tradingDate)
        queued++
      }
    }

    return {
      queued,
      totalPrimary: snapshots.length,
    }
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

  private async safeListRemoteManifest(params: {
    startDate?: string
    endDate?: string
    type?: string
    limit?: number
  }): Promise<CloudManifestItem[]> {
    try {
      const merged: CloudManifestItem[] = []
      let cursor = params.limit ? '0' : ''
      do {
        const result = await this.cloudBackup.listManifestWindow({
          ...params,
          cursor: cursor || undefined,
        })
        merged.push(...(result.items || []))
        cursor = result.nextCursor || ''
      } while (cursor)
      return Array.from(new Map(merged.map((item) => [item.id, item])).values()).sort(
        (left, right) => right.timestamp - left.timestamp,
      )
    } catch (error) {
      this.logger.warn?.('[DataLayer] Remote manifest list failed:', error)
      return []
    }
  }

  private async uploadTradingDateBundle(tradingDate: string): Promise<void> {
    // day bundle 以上传“当天完整记录集”为目标，因此这里会先按交易日重新查询主库。
    const bundle = await this.buildTradingDateBundle(tradingDate)
    if (bundle.items.length === 0) {
      const error = new Error(`cloud_bundle_missing_records:${tradingDate}`)
      this.onCloudBundleError?.(tradingDate, error)
      throw error
    }

    try {
      const result = await this.cloudBackup.uploadDayBundle(bundle)
      this.onCloudBundleUploaded?.(tradingDate, Number(result.uploadedAt) || Date.now())
    } catch (error) {
      this.onCloudBundleError?.(tradingDate, error)
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

  private extractBundlesFromDayBundle(bundle: SnapshotDayBundle | null): SnapshotProjectionBundle[] {
    if (!bundle) return []

    const frameBySnapshotId = new Map((bundle.frames || []).map((frame) => [frame.snapshotId, frame]))
    const stockRowsBySnapshotId = new Map<string, SnapshotProjectionBundle['stockRows']>()
    const sectorRowsBySnapshotId = new Map<string, SnapshotProjectionBundle['sectorRows']>()

    ;(bundle.stockRows || []).forEach((row) => {
      const rows = stockRowsBySnapshotId.get(row.snapshotId) || []
      rows.push(row)
      stockRowsBySnapshotId.set(row.snapshotId, rows)
    })

    ;(bundle.sectorRows || []).forEach((row) => {
      const rows = sectorRowsBySnapshotId.get(row.snapshotId) || []
      rows.push(row)
      sectorRowsBySnapshotId.set(row.snapshotId, rows)
    })

    return (bundle.items || []).map((record) =>
      buildCanonicalProjectionBundle(record, {
        existingStockRows: stockRowsBySnapshotId.get(record.id) || [],
        existingSectorRows: sectorRowsBySnapshotId.get(record.id) || [],
      }),
    )
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
    source: 'bucket_restore' | 'cloud_restore',
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
    source: 'bucket_restore' | 'cloud_restore',
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

  private async buildTradingDateBundle(tradingDate: string): Promise<SnapshotDayBundle> {
    const [items, frames, stockRows, sectorRows] = await Promise.all([
      this.primaryStore.list({
        tradingDate,
        allowedCaptureModes: ['real_time', 'delayed', 'restored'],
        sort: 'asc',
      }),
      this.primaryFrameStore
        ? this.primaryFrameStore.list({
            tradingDate,
            allowedCaptureModes: ['real_time', 'delayed', 'restored'],
            sort: 'asc',
          })
        : Promise.resolve([]),
      this.primaryStockRowStore
        ? this.primaryStockRowStore.list({
            tradingDate,
            allowedCaptureModes: ['real_time', 'delayed', 'restored'],
            sort: 'asc',
          })
        : Promise.resolve([]),
      this.primarySectorRowStore
        ? this.primarySectorRowStore.list({
            tradingDate,
            allowedCaptureModes: ['real_time', 'delayed', 'restored'],
            sort: 'asc',
          })
        : Promise.resolve([]),
    ])

    return {
      version: 'v4',
      tradingDate,
      items,
      frames,
      stockRows,
      sectorRows,
    }
  }
}
