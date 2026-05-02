import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../apiService', () => ({
  apiService: {
    get: vi.fn(),
    post: vi.fn(),
  },
}))

vi.mock('../snapshot/runtime', () => ({
  SnapshotRuntime: class {
    getStockVolumeHistory = vi.fn()
    setSqlitePrimaryWriteHandler = vi.fn()
    setSqlitePrimaryExistsHandler = vi.fn()
    listSnapshots = vi.fn()
    getSnapshotById = vi.fn()
    listSnapshotFrames = vi.fn()
    listSnapshotStockRows = vi.fn()
    listSnapshotSectorRows = vi.fn()
    getSnapshotProjectionMeta = vi.fn()
    rebuildSnapshotProjectionStores = vi.fn()
    alignSnapshotBackups = vi.fn()
    compactSnapshotRawRecords = vi.fn()
    runSnapshotStorageMaintenance = vi.fn()
    cleanupInvalidRuntimeSnapshots = vi.fn()
    exportSnapshotAsFile = vi.fn()
    exportAllSnapshots = vi.fn()
    deleteSnapshot = vi.fn()
    getSnapshotStorageStats = vi.fn()
    getBackupSnapshotStorageStats = vi.fn()
    getBackupBucketHealth = vi.fn()
    getCloudBackupHealth = vi.fn()
    getSnapshotBackupSyncState = vi.fn()
    listSnapshotBackupSyncStates = vi.fn()
    getSnapshotHealthOverview = vi.fn()
    restoreSnapshotsFromBackup = vi.fn()
    repairTradingDateSnapshotCoverage = vi.fn()
    saveFiveMinuteSnapshot = vi.fn()
    start = vi.fn()
    stop = vi.fn()
  },
}))

import { dataLayer } from '../DataLayer'

describe('DataLayer.getStockVolumeHistory', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('reads daily volumes from sqlite-backed stock rows and groups by code', async () => {
    const listRemoteSnapshotStockRows = vi
      .spyOn(dataLayer as any, 'listRemoteSnapshotStockRows')
      .mockResolvedValue([
        {
          code: '600001',
          tradingDate: '2026-04-24',
          volume: 300,
        },
        {
          code: '600001',
          tradingDate: '2026-04-24',
          volume: 280,
        },
        {
          code: '600001',
          tradingDate: '2026-04-23',
          volume: 200,
        },
        {
          code: '600002',
          tradingDate: '2026-04-24',
          volume: 180,
        },
      ] as any)

    const result = await dataLayer.getStockVolumeHistory(['600001', '600002'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })

    expect(listRemoteSnapshotStockRows).toHaveBeenCalledWith({
      type: 'daily',
      codes: ['600001', '600002'],
      beforeTradingDate: '2026-04-24',
      allowedCaptureModes: ['real_time', 'delayed'],
      excludeRestored: true,
      sort: 'desc',
    })
    expect(result.get('600001')).toEqual([300, 200])
    expect(result.get('600002')).toEqual([180])
  })
})
