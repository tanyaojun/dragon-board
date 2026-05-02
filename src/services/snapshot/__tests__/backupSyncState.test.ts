import { describe, expect, it } from 'vitest'

import { SnapshotBackupSyncStateStore } from '../backupSyncState'

function createMemoryStorage() {
  const state = new Map<string, string>()
  return {
    getItem(key: string) {
      return state.has(key) ? state.get(key)! : null
    },
    setItem(key: string, value: string) {
      state.set(key, String(value))
    },
    removeItem(key: string) {
      state.delete(key)
    },
  }
}

describe('SnapshotBackupSyncStateStore', () => {
  it('records independent bucket, cloud bundle, and backend ingest states', () => {
    const store = new SnapshotBackupSyncStateStore({
      storage: createMemoryStorage(),
      storageKey: 'snapshot-backup-sync-state',
      maxTradingDates: 40,
    })

    store.markError('bucket', '2026-04-21', 'bucket_failed')
    store.markBucketSynced('2026-04-21', 111)

    expect(store.get('2026-04-21')).toMatchObject({
      tradingDate: '2026-04-21',
      bucketSyncedAt: 111,
    })
    expect(store.get('2026-04-21')?.lastError).toBeUndefined()

    store.markError('backendIngest', '2026-04-21', 'ingest_failed')
    store.markError('cloudBundle', '2026-04-21', 'cloud_failed')
    store.markCloudBundleUploaded('2026-04-21', 222)

    expect(store.get('2026-04-21')).toMatchObject({
      tradingDate: '2026-04-21',
      bucketSyncedAt: 111,
      cloudBundleUploadedAt: 222,
      lastBackendIngestError: 'ingest_failed',
    })
    expect(store.get('2026-04-21')?.lastCloudBundleError).toBeUndefined()
    expect(store.get('2026-04-21')?.lastError).toBe('backendIngest:ingest_failed')

    store.markBackendIngested('2026-04-21', 333)
    expect(store.get('2026-04-21')).toMatchObject({
      backendIngestedAt: 333,
      cloudBundleUploadedAt: 222,
    })
    expect(store.get('2026-04-21')?.lastBackendIngestError).toBeUndefined()
    expect(store.get('2026-04-21')?.lastError).toBeUndefined()
    expect(store.getLatestCloudSyncedTradingDate()).toBe('2026-04-21')
  })

  it('keeps only the newest trading dates within the configured window', () => {
    const store = new SnapshotBackupSyncStateStore({
      storage: createMemoryStorage(),
      storageKey: 'snapshot-backup-sync-state',
      maxTradingDates: 2,
    })

    store.markBucketSynced('2026-04-20', 100)
    store.markBucketSynced('2026-04-21', 200)
    store.markBucketSynced('2026-04-22', 300)

    expect(store.list()).toEqual([
      { tradingDate: '2026-04-22', bucketSyncedAt: 300 },
      { tradingDate: '2026-04-21', bucketSyncedAt: 200 },
    ])
    expect(store.get('2026-04-20')).toBeNull()
  })
})
