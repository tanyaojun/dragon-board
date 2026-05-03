import { describe, expect, it, vi } from 'vitest'

const start = vi.fn()
const getStockVolumeHistory = vi.fn()

vi.mock('../../DataLayer', () => ({
  dataLayer: {
    getStocks: vi.fn(() => []),
    getDepth10Map: vi.fn(() => new Map()),
    getRecentTicksMap: vi.fn(() => new Map()),
    getL2SummaryMap: vi.fn(() => new Map()),
    getBreathData: vi.fn(() => null),
    getBreathMarketData: vi.fn(() => undefined),
    getJxbkBlocksSorted: vi.fn(() => []),
    getJxbkStockMap: vi.fn(() => ({})),
    getHotThemes: vi.fn(() => []),
    getCurrentRotation: vi.fn(() => null),
    getBreathHistory: vi.fn(() => []),
    getBreathFactors: vi.fn(() => []),
    getMarketMode: vi.fn(() => 'hot'),
    getVersion: vi.fn(() => ({ stocks: 0 })),
  },
}))

vi.mock('../runtime', () => ({
  SnapshotRuntime: class {
    start = start
    stop = vi.fn()
    saveQuarterHourSnapshot = vi.fn()
    saveHalfHourSnapshot = vi.fn()
    saveHourlySnapshot = vi.fn()
    generateDailySnapshot = vi.fn()
    exportDailySnapshot = vi.fn()
    exportStockQuarterSnapshots = vi.fn()
    exportSnapshotToExcel = vi.fn()
    exportSnapshotsRangeToExcel = vi.fn()
    saveDailySnapshot = vi.fn()
    listSnapshots = vi.fn()
    getSnapshotById = vi.fn()
    getTradingDateSnapshot = vi.fn()
    listSnapshotFrames = vi.fn()
    listSnapshotStockRows = vi.fn()
    listSnapshotSectorRows = vi.fn()
    getSnapshotProjectionMeta = vi.fn()
    rebuildSnapshotProjectionStores = vi.fn()
    alignSnapshotBackups = vi.fn()
    compactSnapshotRawRecords = vi.fn()
    runSnapshotStorageMaintenance = vi.fn()
    cleanupInvalidRuntimeSnapshots = vi.fn()
    getStockVolumeHistory = getStockVolumeHistory
    getLatestSnapshotRecord = vi.fn()
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
    syncPrimarySnapshotsToBackup = vi.fn()
    syncPrimarySnapshotsToCloud = vi.fn()
    syncAllSnapshotStores = vi.fn()
    runSnapshotAutoRecoveryCheck = vi.fn()
    inspectTradingDateSnapshotCoverage = vi.fn()
    buildSnapshotCoverageWindow = vi.fn()
    repairTradingDateSnapshotCoverage = vi.fn()
    saveFiveMinuteSnapshot = vi.fn()
  },
}))

describe('snapshotFacade', () => {
  it('exposes stock volume history reads without auto-starting outside the browser', async () => {
    getStockVolumeHistory.mockResolvedValue(new Map([['600001', [300, 200]]]))

    const { snapshotFacade } = await import('../facade')
    const result = await snapshotFacade.getStockVolumeHistory(['600001'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })

    expect(start).not.toHaveBeenCalled()
    expect(getStockVolumeHistory).toHaveBeenCalledWith(['600001'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })
    expect(result.get('600001')).toEqual([300, 200])
  })
})
