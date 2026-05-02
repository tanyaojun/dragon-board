import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createSnapshotRecord } from '../identity'
import { SnapshotRuntime } from '../runtime'
import { getExpectedSlots } from '../schedule'
import type { SnapshotCaptureMode, SnapshotQueryOptions, SnapshotRecord, SnapshotType } from '../types'

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
    clear() {
      state.clear()
    },
  }
}

function createRuntime() {
  vi.stubGlobal('localStorage', createMemoryStorage())
  return new SnapshotRuntime({
    logger: {
      log: vi.fn(),
      warn: vi.fn(),
      error: vi.fn(),
      debug: vi.fn(),
    },
    primaryDbName: 'test-primary',
    primaryDbVersion: 1,
    primaryStoreName: 'snapshots',
    legacyBackupDbName: 'test-backup',
    bucketBackupDbName: 'test-bucket-backup',
    backupDbVersion: 1,
    backupStoreName: 'snapshots_backup',
    backupBucketName: 'snapshot-bucket',
    minBackupCount: 1,
    abnormalRatio: 0.5,
    syncIntervalMs: 60_000,
    getStorageBucketManager: () => null,
    getBuildContext: () => ({
      stocks: [],
      breathData: null,
      marketData: null,
      jxbkBlocks: [],
      jxbkStocks: {},
      hotThemes: [],
      rotationAnalysis: null,
      breathHistory: [],
      breathFactors: [],
      marketMode: 'full',
      stocksVersion: 1,
    }),
  })
}

function createRecord(
  type: SnapshotType,
  tradingDate: string,
  slotTime: string,
  meta?: {
    captureMode?: SnapshotCaptureMode
  },
): SnapshotRecord {
  return createSnapshotRecord(
    type,
    new Date(`${tradingDate}T${slotTime}:00`),
    {
      hotlist: [{ code: `${type}-${slotTime}`, rank: 1, price: 10 }],
    },
    {
      captureMode: meta?.captureMode || 'real_time',
    },
  )
}

function createTradingDateRecords(
  tradingDate: string,
  options?: {
    quarterHourSlots?: string[]
    halfHourSlots?: string[]
    hourlySlots?: string[]
    dailySlots?: string[]
  },
): SnapshotRecord[] {
  return [
    ...(options?.quarterHourSlots || getExpectedSlots('quarter_hour')).map((slotTime) =>
      createRecord('quarter_hour', tradingDate, slotTime),
    ),
    ...(options?.halfHourSlots || getExpectedSlots('half_hour')).map((slotTime) =>
      createRecord('half_hour', tradingDate, slotTime),
    ),
    ...(options?.hourlySlots || getExpectedSlots('hourly')).map((slotTime) =>
      createRecord('hourly', tradingDate, slotTime),
    ),
    ...(options?.dailySlots || getExpectedSlots('daily')).map((slotTime) =>
      createRecord('daily', tradingDate, slotTime),
    ),
  ]
}

describe('SnapshotRuntime', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('filters trading dates by four-type coverage and tolerance', async () => {
    const runtime = createRuntime()
    const records = [
      ...createTradingDateRecords('2026-04-21', {
        hourlySlots: getExpectedSlots('hourly').filter((slotTime) => slotTime !== '14:00'),
      }),
      ...createTradingDateRecords('2026-04-22'),
    ]

    ;(runtime as any).snapshotStore = {
      list: vi.fn().mockResolvedValue(records),
    }

    const strict = await runtime.listSnapshots({
      startDate: '2026-04-21',
      endDate: '2026-04-22',
      sort: 'asc',
      requireCoverage: true,
    })
    const tolerant = await runtime.listSnapshots({
      startDate: '2026-04-21',
      endDate: '2026-04-22',
      sort: 'asc',
      requireCoverage: true,
      coverageTolerance: 1,
    })

    expect(new Set(strict.map((item) => item.tradingDate))).toEqual(new Set(['2026-04-22']))
    expect(new Set(tolerant.map((item) => item.tradingDate))).toEqual(
      new Set(['2026-04-21', '2026-04-22']),
    )
  })

  it('builds four-type coverage reports with delayed, restored, missing, and malformed slots', async () => {
    const runtime = createRuntime()
    const quarterRecords = [
      createRecord('quarter_hour', '2026-04-21', '09:30'),
      createRecord('quarter_hour', '2026-04-21', '09:45', { captureMode: 'delayed' }),
      createRecord('quarter_hour', '2026-04-21', '10:00', { captureMode: 'restored' }),
    ]
    const halfRecords = [
      createRecord('half_hour', '2026-04-21', '09:30'),
      createRecord('half_hour', '2026-04-21', '10:05', { captureMode: 'delayed' }),
    ]
    const hourlyRecords = [createRecord('hourly', '2026-04-21', '10:00', { captureMode: 'delayed' })]
    const dailyRecords: SnapshotRecord[] = []

    vi.spyOn(runtime, 'listSnapshots').mockImplementation(async (options: SnapshotQueryOptions = {}) => {
      if (options.type === 'quarter_hour') return quarterRecords
      if (options.type === 'half_hour') return halfRecords
      if (options.type === 'hourly') return hourlyRecords
      if (options.type === 'daily') return dailyRecords
      return []
    })

    const coverage = await runtime.inspectTradingDateSnapshotCoverage('2026-04-21')

    expect(coverage.quarterHour.expected).toEqual(['09:30', '09:45', '10:00'])
    expect(coverage.quarterHour.delayed).toEqual(['09:45'])
    expect(coverage.quarterHour.restored).toEqual(['10:00'])
    expect(coverage.halfHour.expected).toEqual(['09:30', '10:00'])
    expect(coverage.halfHour.missing).toEqual(['10:00'])
    expect(coverage.halfHour.malformed).toEqual(['10:05'])
    expect(coverage.hourly.expected).toEqual(['10:00'])
    expect(coverage.hourly.delayed).toEqual(['10:00'])
    expect(coverage.daily.expected).toEqual(['15:00'])
    expect(coverage.daily.missing).toEqual(['15:00'])
  })

  it('updates cloud bundle sync state after trading-date upload succeeds', async () => {
    const runtime = createRuntime()
    const uploadedAt = 1_714_000_000_000

    ;(runtime as any).snapshotBackupSync = {
      syncPrimaryToCloud: vi.fn(async (options?: { tradingDate?: string }) => {
        ;(runtime as any).recordCloudBundleUploaded(options?.tradingDate || '', uploadedAt)
        return { queued: 1, totalPrimary: 8 }
      }),
    }

    await runtime.syncPrimarySnapshotsToCloud({ tradingDate: '2026-04-21' })

    await expect(runtime.getSnapshotBackupSyncState('2026-04-21')).resolves.toMatchObject({
      tradingDate: '2026-04-21',
      cloudBundleUploadedAt: uploadedAt,
    })
  })

  it('backfills pending cloud trading dates after 15:30 in ascending order', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-28T15:35:00'))

    const runtime = createRuntime()
    const syncPrimarySnapshotsToCloud = vi
      .spyOn(runtime, 'syncPrimarySnapshotsToCloud')
      .mockImplementation(async (options?: { tradingDate?: string }) => {
        const tradingDate = options?.tradingDate || ''
        ;(runtime as any).recordCloudBundleUploaded(tradingDate, Date.now())
        return { queued: 1, totalPrimary: 8 }
      })

    ;(runtime as any).recordBucketSyncSuccess('2026-04-27', Date.now() - 60_000)
    ;(runtime as any).recordBucketSyncSuccess('2026-04-28', Date.now())
    ;(runtime as any).snapshotStore = {
      list: vi.fn().mockResolvedValue([
        createRecord('daily', '2026-04-28', '15:00'),
        createRecord('daily', '2026-04-27', '15:00'),
      ]),
    }

    await (runtime as any).runDailyCloudSyncIfDue()

    expect(syncPrimarySnapshotsToCloud).toHaveBeenNthCalledWith(1, {
      overwrite: false,
      tradingDate: '2026-04-27',
    })
    expect(syncPrimarySnapshotsToCloud).toHaveBeenNthCalledWith(2, {
      overwrite: false,
      tradingDate: '2026-04-28',
    })
  })

  it('does not collect scheduled snapshot slots on 2026 Labor Day market holiday', async () => {
    const runtime = createRuntime()

    const candidates = await (runtime as any).collectPendingSnapshotSlots(
      new Date('2026-05-01T15:35:00'),
    )

    expect(candidates).toEqual([])
  })

  it('does not write manual snapshots on weekend non-trading days', async () => {
    const runtime = createRuntime()
    const saveSnapshotRecord = vi.spyOn(runtime as any, 'saveSnapshotRecord')

    const saved = await runtime.saveHalfHourSnapshot(new Date('2026-05-02T10:00:00'))

    expect(saved).toBe(false)
    expect(saveSnapshotRecord).not.toHaveBeenCalled()
  })

  it('cleans non-trading-day runtime snapshots from primary projections and local backups', async () => {
    const runtime = createRuntime()
    const polluted = createRecord('half_hour', '2026-05-02', '10:00')
    const valid = createRecord('half_hour', '2026-04-30', '10:00')

    ;(runtime as any).snapshotStore = {
      list: vi.fn().mockResolvedValue([polluted, valid]),
      getById: vi.fn(async (id: string) => (id === polluted.id ? polluted : id === valid.id ? valid : null)),
      delete: vi.fn().mockResolvedValue(undefined),
    }
    ;(runtime as any).snapshotFrameStore = {
      deleteBySnapshotId: vi.fn().mockResolvedValue(undefined),
    }
    ;(runtime as any).snapshotStockRowStore = {
      deleteBySnapshotId: vi.fn().mockResolvedValue(undefined),
    }
    ;(runtime as any).snapshotSectorRowStore = {
      deleteBySnapshotId: vi.fn().mockResolvedValue(undefined),
    }
    ;(runtime as any).snapshotBackupSync = {
      cleanupInvalidLocalBackups: vi.fn(async (predicate: (record: SnapshotRecord) => boolean) => {
        expect(predicate(polluted)).toBe(true)
        expect(predicate(valid)).toBe(false)
        return {
          scanned: 1,
          deleted: 1,
          affectedTradingDates: ['2026-05-02'],
          deletedSnapshotIds: [polluted.id],
        }
      }),
    }

    const result = await runtime.cleanupInvalidRuntimeSnapshots()

    expect(result).toMatchObject({
      scanned: 3,
      deleted: 1,
      deletedFromPrimary: 1,
      deletedFromBucketBackup: 1,
      affectedTradingDates: ['2026-05-02'],
      deletedSnapshotIds: [polluted.id],
    })
    expect((runtime as any).snapshotStore.delete).toHaveBeenCalledWith(polluted.id)
    expect((runtime as any).snapshotStore.delete).not.toHaveBeenCalledWith(valid.id)
    expect((runtime as any).snapshotFrameStore.deleteBySnapshotId).toHaveBeenCalledWith(polluted.id)
    expect((runtime as any).snapshotStockRowStore.deleteBySnapshotId).toHaveBeenCalledWith(polluted.id)
    expect((runtime as any).snapshotSectorRowStore.deleteBySnapshotId).toHaveBeenCalledWith(polluted.id)
    expect((runtime as any).snapshotBackupSync.cleanupInvalidLocalBackups).toHaveBeenCalledTimes(1)
  })

  it('uses recent primary trading dates as cloud backfill candidates when sync state is missing', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-28T15:35:00'))

    const runtime = createRuntime()
    const syncPrimarySnapshotsToCloud = vi
      .spyOn(runtime, 'syncPrimarySnapshotsToCloud')
      .mockResolvedValue({ queued: 1, totalPrimary: 8 })

    ;(runtime as any).snapshotStore = {
      list: vi.fn().mockResolvedValue([
        createRecord('daily', '2026-04-28', '15:00'),
        createRecord('daily', '2026-04-27', '15:00'),
      ]),
    }

    await (runtime as any).runDailyCloudSyncIfDue()

    expect(syncPrimarySnapshotsToCloud).toHaveBeenNthCalledWith(1, {
      overwrite: false,
      tradingDate: '2026-04-27',
    })
    expect(syncPrimarySnapshotsToCloud).toHaveBeenNthCalledWith(2, {
      overwrite: false,
      tradingDate: '2026-04-28',
    })
  })

  it('returns repair candidates without writing into the primary store', async () => {
    const runtime = createRuntime()
    const primaryPut = vi.fn()

    ;(runtime as any).snapshotStore = {
      put: primaryPut,
    }

    vi.spyOn(runtime, 'listSnapshots').mockImplementation(async (options: SnapshotQueryOptions = {}) => {
      if (options.type === 'quarter_hour') {
        return [createRecord('quarter_hour', '2026-04-21', '09:32')]
      }
      if (options.type === 'half_hour') {
        return []
      }
      return []
    })

    const result = await runtime.repairTradingDateSnapshotCoverage('2026-04-21', {
      toleranceMinutes: 5,
    })

    expect(result.reason).toBe('memory_only_repair_candidates')
    expect(result.normalizedQuarter).toBe(1)
    expect(result.createdHalfHour).toBe(1)
    expect(primaryPut).not.toHaveBeenCalled()
  })

  it('reads close-slot volume history from projected stock rows', async () => {
    const runtime = createRuntime()
    ;(runtime as any).ensureProjectedRawRecords = vi.fn().mockResolvedValue(undefined)

    ;(runtime as any).snapshotStockRowStore = {
      list: vi
        .fn()
        .mockResolvedValueOnce([
          {
            snapshotId: 'daily:2026-04-24:15:00',
            type: 'daily',
            tradingDate: '2026-04-24',
            slotTime: '15:00',
            timestamp: Date.parse('2026-04-24T15:00:00'),
            captureMode: 'real_time',
            source: 'browser_runtime',
            code: '600001',
            volume: 300,
          },
          {
            snapshotId: 'daily:2026-04-23:15:00',
            type: 'daily',
            tradingDate: '2026-04-23',
            slotTime: '15:00',
            timestamp: Date.parse('2026-04-23T15:00:00'),
            captureMode: 'delayed',
            source: 'browser_runtime',
            code: '600001',
            volume: 200,
          },
        ])
        .mockResolvedValueOnce([
          {
            snapshotId: 'daily:2026-04-24:15:00',
            type: 'daily',
            tradingDate: '2026-04-24',
            slotTime: '15:00',
            timestamp: Date.parse('2026-04-24T15:00:00'),
            captureMode: 'real_time',
            source: 'browser_runtime',
            code: '600002',
            volume: 180,
          },
        ]),
    }

    const result = await runtime.getStockVolumeHistory(['600001', '600002'], {
      anchorTradingDate: '2026-04-24',
      lookbackDays: 3,
    })

    expect(result.get('600001')).toEqual([300, 200])
    expect(result.get('600002')).toEqual([180])
  })

  it('rewrites projection bundle when frame exists but child-row counts drift', async () => {
    const runtime = createRuntime()
    const rawRecord = createRecord('quarter_hour', '2026-04-24', '14:15')
    const rewrittenRows = [
      {
        id: `${rawRecord.id}:600001`,
        snapshotId: rawRecord.id,
        type: 'quarter_hour',
        tradingDate: rawRecord.tradingDate,
        slotTime: rawRecord.slotTime,
        timestamp: rawRecord.timestamp,
        captureMode: rawRecord.captureMode,
        source: rawRecord.source,
        code: '600001',
        name: '样本股',
        rank: 1,
        compRank: 1,
      },
    ]

    ;(runtime as any).snapshotStore = {
      getById: vi.fn().mockResolvedValue(rawRecord),
    }
    ;(runtime as any).snapshotFrameStore = {
      getBySnapshotId: vi.fn().mockResolvedValue({
        snapshotId: rawRecord.id,
        stockRowCount: 1,
        sectorRowCount: 0,
      }),
    }
    ;(runtime as any).snapshotStockRowStore = {
      countBySnapshotId: vi.fn().mockResolvedValue(0),
      list: vi
        .fn()
        .mockResolvedValueOnce([])
        .mockResolvedValueOnce(rewrittenRows),
    }
    ;(runtime as any).snapshotSectorRowStore = {
      countBySnapshotId: vi.fn().mockResolvedValue(0),
      list: vi.fn().mockResolvedValue([]),
    }
    ;(runtime as any).snapshotProjectionWriter = {
      saveBundle: vi.fn().mockResolvedValue(undefined),
    }

    const rows = await runtime.listSnapshotStockRows({ snapshotId: rawRecord.id })

    expect((runtime as any).snapshotProjectionWriter.saveBundle).toHaveBeenCalledTimes(1)
    expect(rows).toEqual(rewrittenRows)
  })

  it('runs storage maintenance in P1-P3 order', async () => {
    const runtime = createRuntime()
    const projectionRebuild = {
      scanned: 10,
      rewritten: 10,
      affectedTradingDates: ['2026-04-24'],
    }
    const backupBefore = {
      processedSnapshots: 10,
      localBundlesSynced: 10,
      cloudEnabled: false,
      cloudUploadedTradingDates: [],
    }
    const rawCompaction = {
      scanned: 10,
      rewritten: 8,
      affectedTradingDates: ['2026-04-24'],
    }
    const backupAfter = {
      processedSnapshots: 10,
      localBundlesSynced: 10,
      cloudEnabled: false,
      cloudUploadedTradingDates: [],
    }

    const rebuildSpy = vi
      .spyOn(runtime, 'rebuildSnapshotProjectionStores')
      .mockResolvedValue(projectionRebuild as any)
    const alignSpy = vi
      .spyOn(runtime, 'alignSnapshotBackups')
      .mockResolvedValueOnce(backupBefore as any)
      .mockResolvedValueOnce(backupAfter as any)
    const compactSpy = vi
      .spyOn(runtime, 'compactSnapshotRawRecords')
      .mockResolvedValue(rawCompaction as any)

    const result = await runtime.runSnapshotStorageMaintenance({
      tradingDate: '2026-04-24',
      includeCloud: false,
    })

    expect(rebuildSpy.mock.invocationCallOrder[0]).toBeLessThan(alignSpy.mock.invocationCallOrder[0])
    expect(alignSpy.mock.invocationCallOrder[0]).toBeLessThan(compactSpy.mock.invocationCallOrder[0])
    expect(compactSpy.mock.invocationCallOrder[0]).toBeLessThan(alignSpy.mock.invocationCallOrder[1])
    expect(alignSpy).toHaveBeenNthCalledWith(1, {
      tradingDate: '2026-04-24',
      includeCloud: false,
    })
    expect(alignSpy).toHaveBeenNthCalledWith(2, {
      tradingDate: '2026-04-24',
      includeCloud: false,
    })
    expect(result).toEqual({
      projectionRebuild,
      backupAlignmentBeforeCompaction: backupBefore,
      rawCompaction,
      backupAlignmentAfterCompaction: backupAfter,
    })
  })
})
