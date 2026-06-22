import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createSnapshotRecord } from '../identity'
import { SnapshotRuntime, buildSnapshotBackendIngestIdempotencyKey } from '../runtime'
import { refreshResourceLocks } from '../../refresh/RefreshResourceLocks'
import { refreshScheduler, refreshTaskRegistry } from '../../refresh/RefreshTaskRuntime'
import { getExpectedSlots } from '../schedule'
import type { SnapshotBuildContext } from '../builders'
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

function createDefaultBuildContext(overrides: Partial<SnapshotBuildContext> = {}): SnapshotBuildContext {
  return {
    stocks: [],
    breathData: null,
    marketData: null,
    hotThemes: [],
    rotationAnalysis: null,
    breathHistory: [],
    breathFactors: [],
    marketMode: 'full',
    stocksVersion: 1,
    ...overrides,
  }
}

function createRuntime(buildContext: Partial<SnapshotBuildContext> = {}) {
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
    enableIndexedDbSnapshotCache: true,
    legacyBackupDbName: 'test-backup',
    bucketBackupDbName: 'test-bucket-backup',
    backupDbVersion: 1,
    backupStoreName: 'snapshots_backup',
    backupBucketName: 'snapshot-bucket',
    minBackupCount: 1,
    abnormalRatio: 0.5,
    syncIntervalMs: 60_000,
    getStorageBucketManager: () => null,
    getBuildContext: () => createDefaultBuildContext(buildContext),
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
    refreshScheduler.stopAll()
    refreshTaskRegistry.resetRuntimeState()
  })

  afterEach(() => {
    refreshScheduler.stopAll()
    refreshTaskRegistry.resetRuntimeState()
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

  it('ignores IndexedDB existence and writes formal snapshots through the backend primary', async () => {
    const runtime = createRuntime()
    const record = createRecord('half_hour', '2026-04-21', '10:00')
    const mongoWrite = vi.fn().mockResolvedValue({ ok: true })
    ;(runtime as any).mongoPrimaryWrite = mongoWrite
    runtime.setMongoPrimaryExistsHandler(vi.fn().mockResolvedValue(false))
    ;(runtime as any).snapshotStore = {
      getById: vi.fn().mockResolvedValue(record),
    }
    ;(runtime as any).snapshotStockRowStore = {
      list: vi.fn().mockResolvedValue([
        {
          id: `${record.id}:600001`,
          snapshotId: record.id,
          type: record.type,
          tradingDate: record.tradingDate,
          slotTime: record.slotTime,
          timestamp: record.timestamp,
          captureMode: record.captureMode,
          source: record.source,
          code: '600001',
          rank: 1,
        },
      ]),
    }
    ;(runtime as any).snapshotSectorRowStore = {
      list: vi.fn().mockResolvedValue([]),
    }
    ;(runtime as any).snapshotProjectionWriter = {
      saveBundle: vi.fn(),
    }
    ;(runtime as any).snapshotBackupSync = {
      saveToBackups: vi.fn().mockResolvedValue(undefined),
    }

    const saved = await (runtime as any).saveSnapshotRecord(record)

    expect(saved).toBe(true)
    expect(mongoWrite).toHaveBeenCalledTimes(1)
    expect((runtime as any).snapshotStore.getById).not.toHaveBeenCalled()
    expect((runtime as any).snapshotProjectionWriter.saveBundle).not.toHaveBeenCalled()
    const state = await runtime.getSnapshotBackupSyncState('2026-04-21')
    expect(state?.backendIngestedAt).toEqual(expect.any(Number))
  })

  it('writes formal snapshots to MongoDB without touching IndexedDB cache when cache is disabled', async () => {
    const runtime = new SnapshotRuntime({
      logger: {
        log: vi.fn(),
        warn: vi.fn(),
        error: vi.fn(),
        debug: vi.fn(),
      },
      primaryDbName: 'test-primary',
      primaryDbVersion: 1,
      primaryStoreName: 'snapshots',
      enableIndexedDbSnapshotCache: false,
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
        hotThemes: [],
        rotationAnalysis: null,
        breathHistory: [],
        breathFactors: [],
        marketMode: 'full',
        stocksVersion: 1,
      }),
    })
    const record = createRecord('half_hour', '2026-04-21', '10:00')
    const mongoWrite = vi.fn().mockResolvedValue({ ok: true })
    ;(runtime as any).mongoPrimaryWrite = mongoWrite
    ;(runtime as any).snapshotStore = {
      getById: vi.fn(),
    }
    ;(runtime as any).snapshotProjectionWriter = {
      saveBundle: vi.fn(),
    }
    ;(runtime as any).snapshotBackupSync = {
      saveToBackups: vi.fn(),
    }
    runtime.setMongoPrimaryExistsHandler(vi.fn().mockResolvedValue(false))

    const saved = await (runtime as any).saveSnapshotRecord(record, {
      record,
      frame: null,
      stockRows: [],
      sectorRows: [],
    })

    expect(saved).toBe(true)
    expect(mongoWrite).toHaveBeenCalledTimes(1)
    expect((runtime as any).snapshotStore.getById).not.toHaveBeenCalled()
    expect((runtime as any).snapshotProjectionWriter.saveBundle).not.toHaveBeenCalled()
    expect((runtime as any).snapshotBackupSync.saveToBackups).not.toHaveBeenCalled()
  })

  it('treats MongoDB duplicate snapshot responses as not-created without writing cache', async () => {
    const runtime = createRuntime()
    const record = createRecord('half_hour', '2026-04-21', '10:00')
    const mongoWrite = vi.fn().mockResolvedValue({ ok: true, skipped: true })
    ;(runtime as any).mongoPrimaryWrite = mongoWrite
    runtime.setMongoPrimaryExistsHandler(vi.fn().mockResolvedValue(false))
    ;(runtime as any).snapshotProjectionWriter = {
      saveBundle: vi.fn(),
    }
    ;(runtime as any).snapshotBackupSync = {
      saveToBackups: vi.fn(),
    }

    const saved = await (runtime as any).saveSnapshotRecord(record, {
      record,
      frame: null,
      stockRows: [],
      sectorRows: [],
    })

    expect(saved).toBe(false)
    expect(mongoWrite).toHaveBeenCalledTimes(1)
    expect((runtime as any).snapshotProjectionWriter.saveBundle).not.toHaveBeenCalled()
    expect((runtime as any).snapshotBackupSync.saveToBackups).not.toHaveBeenCalled()
  })

  it('skips formal snapshot writes when MongoDB already has the snapshot id', async () => {
    const runtime = createRuntime()
    const record = createRecord('half_hour', '2026-04-21', '10:00')
    const mongoWrite = vi.fn()
    const exists = vi.fn().mockResolvedValue(true)
    ;(runtime as any).mongoPrimaryWrite = mongoWrite
    runtime.setMongoPrimaryExistsHandler(exists)
    ;(runtime as any).snapshotProjectionWriter = {
      saveBundle: vi.fn(),
    }

    const saved = await (runtime as any).saveSnapshotRecord(record, {
      record,
      frame: null,
      stockRows: [],
      sectorRows: [],
    })

    expect(saved).toBe(false)
    expect(exists).toHaveBeenCalledWith(record.id)
    expect(mongoWrite).not.toHaveBeenCalled()
    expect((runtime as any).snapshotProjectionWriter.saveBundle).not.toHaveBeenCalled()
  })

  it('serializes snapshot record writes through the snapshot-write resource', async () => {
    const runtime = createRuntime()
    const releases: Array<() => void> = []
    const writeSnapshotBundleToMongoPrimary = vi.fn(
      () =>
        new Promise<{ ok: true }>((resolve) => {
          releases.push(() => resolve({ ok: true }))
        }),
    )
    ;(runtime as any).writeSnapshotBundleToMongoPrimary = writeSnapshotBundleToMongoPrimary

    const first = (runtime as any).saveSnapshotRecord(
      createRecord('half_hour', '2026-04-21', '10:00'),
    )

    await vi.waitFor(() => {
      expect(refreshResourceLocks.isLocked('snapshot-write')).toBe(true)
    })

    const second = (runtime as any).saveSnapshotRecord(
      createRecord('half_hour', '2026-04-21', '10:30'),
    )
    await Promise.resolve()

    expect(writeSnapshotBundleToMongoPrimary).toHaveBeenCalledTimes(1)

    releases.shift()?.()
    await expect(first).resolves.toBe(true)
    await vi.waitFor(() => {
      expect(writeSnapshotBundleToMongoPrimary).toHaveBeenCalledTimes(2)
    })
    releases.shift()?.()
    await expect(second).resolves.toBe(true)
    expect(refreshResourceLocks.isLocked('snapshot-write')).toBe(false)
  })

  it('builds stable backend ingest idempotency keys for the same snapshot slot', () => {
    const first = createRecord('half_hour', '2026-05-06', '09:30')
    const second: SnapshotRecord = {
      ...first,
      timestamp: first.timestamp + 1_000,
      payload: {
        ...first.payload,
        hotlist: [{ code: '600999', rank: 1, price: 99 }],
      },
    }

    expect(buildSnapshotBackendIngestIdempotencyKey(first)).toBe(
      buildSnapshotBackendIngestIdempotencyKey(second),
    )
  })

  it('collects pending scheduled slots by checking MongoDB existence first', async () => {
    const runtime = createRuntime()
    const exists = vi.fn(async (snapshotId: string) => snapshotId.includes('10:00'))
    runtime.setMongoPrimaryExistsHandler(exists)
    ;(runtime as any).snapshotStore = {
      getById: vi.fn(),
    }

    const candidates = await (runtime as any).collectPendingSnapshotSlots(new Date('2026-04-21T10:01:00'))

    expect(candidates.some((item: { slotTime: Date }) => item.slotTime.getHours() === 10)).toBe(false)
    expect((runtime as any).snapshotStore.getById).not.toHaveBeenCalled()
    expect(exists).toHaveBeenCalled()
  })

  it('records scheduled snapshot sweep and backup sync through the shared scheduler', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-04-21T10:00:00+08:00'))
    vi.stubGlobal('window', {
      setTimeout,
      clearTimeout,
      setInterval,
      clearInterval,
    })
    const runtime = createRuntime()
    const scheduleSnapshotSweep = vi.spyOn(runtime as any, 'scheduleSnapshotSweep').mockImplementation(() => {})
    const syncPrimarySnapshotsToBackup = vi
      .spyOn(runtime, 'syncPrimarySnapshotsToBackup')
      .mockResolvedValue({} as any)

    runtime.startTimer()
    ;(runtime as any).startSnapshotAutoSync()
    await vi.advanceTimersByTimeAsync(1_000)

    expect(scheduleSnapshotSweep).toHaveBeenCalledTimes(1)
    expect(refreshTaskRegistry.getTask('snapshot.sweep')).toMatchObject({
      running: false,
      lastRunAt: expect.any(Number),
      lastSuccessAt: expect.any(Number),
      lastError: null,
      successCount: 1,
      source: 'scheduler',
    })

    await vi.advanceTimersByTimeAsync(60_000)

    expect(syncPrimarySnapshotsToBackup).toHaveBeenCalled()
    expect(refreshTaskRegistry.getTask('snapshot.backupSync')).toMatchObject({
      running: false,
      lastRunAt: expect.any(Number),
      lastSuccessAt: expect.any(Number),
      lastError: null,
      successCount: 1,
      source: 'scheduler',
    })

    runtime.stop()
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

  it('does not write formal half-hour snapshots when the stock pool is empty', async () => {
    const runtime = createRuntime()
    const saveSnapshotRecord = vi.spyOn(runtime as any, 'saveSnapshotRecord').mockResolvedValue(true)

    const saved = await runtime.saveHalfHourSnapshot(new Date('2026-04-21T10:00:00'))

    expect(saved).toBe(false)
    expect(saveSnapshotRecord).not.toHaveBeenCalled()
  })

  it('does not write formal half-hour snapshots when theme heat factors are empty', async () => {
    const runtime = createRuntime({
      stocks: [{ code: '600001', rank: 1 }],
      hotThemes: [{ id: 'legacy-top-n', name: '旧UI题材' }],
      themeHeatFactors: [],
    })
    const saveSnapshotRecord = vi.spyOn(runtime as any, 'saveSnapshotRecord').mockResolvedValue(true)

    const saved = await runtime.saveHalfHourSnapshot(new Date('2026-04-21T10:00:00'))

    expect(saved).toBe(false)
    expect(saveSnapshotRecord).not.toHaveBeenCalled()
  })

  it('writes formal half-hour snapshots when stock pool and theme heat factors are ready', async () => {
    const runtime = createRuntime({
      stocks: [{ code: '600001', rank: 1 }],
      themeHeatFactors: [{ id: 'AI', name: '人工智能', heatScore: 88 }],
    })
    const saveSnapshotRecord = vi.spyOn(runtime as any, 'saveSnapshotRecord').mockResolvedValue(true)

    const saved = await runtime.saveHalfHourSnapshot(new Date('2026-04-21T10:00:00'))

    expect(saved).toBe(true)
    expect(saveSnapshotRecord).toHaveBeenCalledTimes(1)
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
    }
    const rawCompaction = {
      scanned: 10,
      rewritten: 8,
      affectedTradingDates: ['2026-04-24'],
    }
    const backupAfter = {
      processedSnapshots: 10,
      localBundlesSynced: 10,
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
