import { describe, expect, it, vi } from 'vitest'

const start = vi.fn()
const getStockVolumeHistory = vi.fn()
const runtimeListSnapshotFrameBundles = vi.fn()
const runtimeListSnapshots = vi.fn()
const setSqlitePrimaryExistsHandler = vi.fn()
const backendListSnapshotFrameBundles = vi.fn()
const backendListSnapshots = vi.fn()
const backendGetSnapshotById = vi.fn()
const backendGetStockVolumeHistory = vi.fn()

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
    listSnapshots = runtimeListSnapshots
    getSnapshotById = vi.fn()
    getTradingDateSnapshot = vi.fn()
    listSnapshotFrames = vi.fn()
    listSnapshotStockRows = vi.fn()
    listSnapshotSectorRows = vi.fn()
    getSnapshotProjectionMeta = vi.fn()
    setSqlitePrimaryExistsHandler = setSqlitePrimaryExistsHandler
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
  },
}))

vi.mock('../backendRead', () => ({
  snapshotBackendRead: {
    listSnapshots: backendListSnapshots,
    getSnapshotById: backendGetSnapshotById,
    getTradingDateSnapshot: vi.fn(),
    listSnapshotFrames: vi.fn(),
    listSnapshotStockRows: vi.fn(),
    listSnapshotSectorRows: vi.fn(),
    listSnapshotFrameBundles: backendListSnapshotFrameBundles,
    getStockVolumeHistory: backendGetStockVolumeHistory,
  },
}))

describe('snapshotFacade', () => {
  it('routes formal stock volume history reads to sqlite without auto-starting outside the browser', async () => {
    backendGetStockVolumeHistory.mockResolvedValue(new Map([['600001', [300, 200]]]))

    const { snapshotFacade } = await import('../facade')
    const result = await snapshotFacade.getStockVolumeHistory(['600001'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })

    expect(start).not.toHaveBeenCalled()
    expect(getStockVolumeHistory).not.toHaveBeenCalled()
    expect(backendGetStockVolumeHistory).toHaveBeenCalledWith(['600001'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })
    expect(result.get('600001')).toEqual([300, 200])
  })

  it('routes formal frame bundle reads to sqlite backend', async () => {
    backendListSnapshotFrameBundles.mockResolvedValue([{ snapshotId: 'half_hour:2026-04-24:10:00' }])

    const { snapshotFacade } = await import('../facade')
    const result = await snapshotFacade.listSnapshotFrameBundles({ type: 'half_hour' })

    expect(backendListSnapshotFrameBundles).toHaveBeenCalledWith({ type: 'half_hour' })
    expect(runtimeListSnapshotFrameBundles).not.toHaveBeenCalled()
    expect(result).toEqual([{ snapshotId: 'half_hour:2026-04-24:10:00' }])
  })

  it('does not keep five minute reads on the local IndexedDB runtime path', async () => {
    const { snapshotFacade } = await import('../facade')

    await expect(snapshotFacade.listSnapshots({ type: 'five_minute' })).rejects.toThrow(
      'unsupported formal snapshot type: five_minute',
    )
    expect(runtimeListSnapshots).not.toHaveBeenCalled()
    expect(backendListSnapshots).not.toHaveBeenCalled()
  })

  it('checks sqlite backend before formal snapshot writes', async () => {
    backendGetSnapshotById.mockResolvedValue({ id: 'half_hour:2026-05-06:09:30' })

    await import('../facade')

    expect(setSqlitePrimaryExistsHandler).toHaveBeenCalledTimes(1)
    const handler = setSqlitePrimaryExistsHandler.mock.calls[0]?.[0]
    await expect(handler('half_hour:2026-05-06:09:30')).resolves.toBe(true)
    expect(backendGetSnapshotById).toHaveBeenCalledWith('half_hour:2026-05-06:09:30')
  })
})
