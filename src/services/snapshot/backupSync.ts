// IndexedDB backup sync removed — formal persistence is MongoDB-only.
// This file provides stub no-op implementations to preserve API surface compatibility.

import { SnapshotFrameStore, SnapshotProjectionWriter, SnapshotSectorRowStore, SnapshotStockRowStore, SnapshotStore } from './store'
import type { SnapshotProjectionBundle, SnapshotRecord } from './types'

interface BackupStubLogger {
  debug?: (...args: unknown[]) => void
  log?: (...args: unknown[]) => void
  warn?: (...args: unknown[]) => void
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
  bucketManagerProvider: () => unknown
  bucketName: string
  minBackupCount: number
  abnormalRatio: number
  logger?: BackupStubLogger
  onBucketSyncSuccess?: (tradingDate: string, syncedAt: number) => void
  onBucketSyncError?: (tradingDate: string, error: unknown) => void
}

export class SnapshotBackupSync {
  constructor(_config: SnapshotBackupSyncConfig) {
    // IndexedDB backup sync removed — stub only
  }

  async saveToBackups(
    _snapshotOrBundle: SnapshotRecord | SnapshotProjectionBundle,
    _options?: { overwrite?: boolean },
  ): Promise<void> {
    // no-op: IndexedDB backup removed
  }

  async getBackupStats(): Promise<{
    totalSnapshots: number
    estimatedSize: number
    mode: string
    bucketSnapshots: number
  }> {
    return { totalSnapshots: 0, estimatedSize: 0, mode: 'all', bucketSnapshots: 0 }
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
    return {
      supported: false,
      bucketName: '',
      bucketOpened: false,
      error: 'indexeddb_backup_removed',
    }
  }

  getCloudHealth() {
    return { ok: false, enabled: false, message: 'cloud_backup_disabled' }
  }

  async deleteFromLocalBackups(_snapshotId: string): Promise<boolean> {
    return false
  }

  async cleanupInvalidLocalBackups(
    _isInvalid: (record: SnapshotRecord) => boolean,
  ): Promise<{
    scanned: number
    deleted: number
    affectedTradingDates: string[]
    deletedSnapshotIds: string[]
  }> {
    return { scanned: 0, deleted: 0, affectedTradingDates: [], deletedSnapshotIds: [] }
  }

  async restorePrimaryFromBackups(_options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    restored: number
    skipped: number
    totalFromBackup: number
    mode: string
  }> {
    return { restored: 0, skipped: 0, totalFromBackup: 0, mode: 'all' }
  }

  async syncPrimaryToBackups(_options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    synced: number
    skipped: number
    totalPrimary: number
    bucketSynced: number
    mode: string
  }> {
    return { synced: 0, skipped: 0, totalPrimary: 0, bucketSynced: 0, mode: 'all' }
  }

  async syncAllStores(_options?: {
    overwrite?: boolean
    limit?: number
  }): Promise<{
    primaryCount: number
    bucketBackupCount: number
    insertedToPrimary: number
    insertedToBucketBackup: number
    mode: string
  }> {
    return { primaryCount: 0, bucketBackupCount: 0, insertedToPrimary: 0, insertedToBucketBackup: 0, mode: 'all' }
  }

  async runAutoRecoveryCheck(_options?: {
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
    mode: string
  }> {
    return {
      checked: true,
      recovered: false,
      reason: 'indexeddb_backup_removed',
      primaryCount: 0,
      backupCount: 0,
      restored: 0,
      skipped: 0,
      mode: 'all',
    }
  }

  async syncPrimaryToCloud(_options?: {
    limit?: number
    overwrite?: boolean
    tradingDate?: string
    startDate?: string
    endDate?: string
  }) {
    return { queued: 0, totalPrimary: 0 }
  }
}
