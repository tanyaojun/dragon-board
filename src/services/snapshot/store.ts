import {
  buildSnapshotDisplayKey,
  buildSnapshotId,
  createSnapshotQualityMetadata,
  normalizeSnapshotSlotTime,
  SNAPSHOT_TYPE_LABELS,
  withSnapshotPayloadCompatFields,
} from './identity'
import {
  RANK_TREND_SNAPSHOT_TYPES,
} from '../../type/rankTrendDefaults'
import type {
  SnapshotCaptureMode,
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotProjectionBundle,
  SnapshotProjectionMeta,
  SnapshotQueryOptions,
  SnapshotRecord,
  SnapshotSectorEntityType,
  SnapshotSectorRow,
  SnapshotSectorRowQueryOptions,
  SnapshotStockRow,
  SnapshotStockRowQueryOptions,
  SnapshotStorageStats,
  SnapshotType,
} from './types'

interface SnapshotStoreConfig {
  dbName: string
  dbVersion: number
  storeName: string
  redundantStores?: string[]
  factoryProvider?: (() => Promise<any> | any) | any
}

interface SnapshotProjectionStoreConfig {
  dbName: string
  dbVersion: number
  snapshotStoreName: string
  redundantStores?: string[]
  factoryProvider?: (() => Promise<any> | any) | any
}

export const SNAPSHOT_FRAME_STORE_NAME = 'snapshot_frames'
export const SNAPSHOT_STOCK_ROW_STORE_NAME = 'snapshot_stock_rows'
export const SNAPSHOT_SECTOR_ROW_STORE_NAME = 'snapshot_sector_rows'
export const SNAPSHOT_PROJECTION_META_STORE_NAME = 'snapshot_projection_meta'

const SNAPSHOT_TYPE_VALUES: SnapshotType[] = [...RANK_TREND_SNAPSHOT_TYPES, 'five_minute']

const LEGACY_LABEL_TO_TYPE = Object.fromEntries(
  Object.entries(SNAPSHOT_TYPE_LABELS).map(([type, label]) => [label, type as SnapshotType]),
) as Record<string, SnapshotType>

function isSnapshotType(value: unknown): value is SnapshotType {
  return SNAPSHOT_TYPE_VALUES.includes(value as SnapshotType)
}

function toDateFromTradingDateAndSlot(tradingDate: string, slotTime: string): Date | null {
  if (!tradingDate) return null
  const time = slotTime || '00:00'
  const parsed = new Date(`${tradingDate}T${time}:00`)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

function parseLegacySnapshotDate(displayKey: string): {
  type: SnapshotType | null
  tradingDate: string
  slotTime: string
} {
  const normalized = String(displayKey || '').trim()
  const labelMatch = normalized.match(/^\[([^\]]+)\]\s*(.+)$/)
  if (labelMatch) {
    const type = LEGACY_LABEL_TO_TYPE[labelMatch[1].trim()] || null
    const body = labelMatch[2].trim()
    const bodyMatch = body.match(/^(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?$/)
    if (bodyMatch) {
      return {
        type,
        tradingDate: bodyMatch[1],
        slotTime: bodyMatch[2] || '',
      }
    }
  }

  const fallbackMatch = normalized.match(/^(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?$/)
  return {
    type: null,
    tradingDate: fallbackMatch?.[1] || '',
    slotTime: fallbackMatch?.[2] || '',
  }
}

function inferLegacySnapshotType(rawRecord: any, sourceStoreName: string): SnapshotType | null {
  if (isSnapshotType(rawRecord?.type)) return rawRecord.type
  if (isSnapshotType(rawRecord?.payload?.type)) return rawRecord.payload.type
  if (sourceStoreName === 'daily_snapshots') return 'daily'

  const parsed = parseLegacySnapshotDate(
    String(rawRecord?.displayKey || rawRecord?.date || rawRecord?.payload?.date || ''),
  )
  if (parsed.type) return parsed.type

  if (rawRecord?.limitUpStocks || rawRecord?.indices || rawRecord?.market || rawRecord?.rotation) {
    return 'daily'
  }

  return null
}

// V3 升级时所有旧结构都会先归一成统一 SnapshotRecord，
// 后续查询层不再需要区分“老中文 key”还是“新结构化记录”。
function migrateLegacySnapshotRecord(rawRecord: any, sourceStoreName: string): SnapshotRecord | null {
  if (!rawRecord || typeof rawRecord !== 'object') return null
  if (
    typeof rawRecord.id === 'string' &&
    isSnapshotType(rawRecord.type) &&
    typeof rawRecord.tradingDate === 'string' &&
    typeof rawRecord.slotTime === 'string' &&
    rawRecord.payload
  ) {
    const slotDate =
      toDateFromTradingDateAndSlot(rawRecord.tradingDate, rawRecord.slotTime) ||
      new Date(Number(rawRecord.timestamp) || Date.now())
    return withSnapshotPayloadCompatFields({
      ...(rawRecord as SnapshotRecord),
      ...createSnapshotQualityMetadata(slotDate, {
        captureMode:
          rawRecord.captureMode === 'delayed' || rawRecord.captureMode === 'restored'
            ? rawRecord.captureMode
            : 'real_time',
        capturedAt: Number(rawRecord.capturedAt) || Number(rawRecord.timestamp) || slotDate.getTime(),
        dataTimestamp: Number(rawRecord.dataTimestamp) || Number(rawRecord.timestamp) || slotDate.getTime(),
        delayMs: Number(rawRecord.delayMs) || 0,
        qualityFlags: Array.isArray(rawRecord.qualityFlags) ? rawRecord.qualityFlags : [],
        source:
          rawRecord.source === 'bucket_restore' ||
          rawRecord.source === 'cloud_restore' ||
          rawRecord.source === 'manual'
            ? rawRecord.source
            : 'browser_runtime',
      }),
    } as SnapshotRecord)
  }

  const payloadSource =
    rawRecord.payload && typeof rawRecord.payload === 'object' ? rawRecord.payload : rawRecord
  const legacyDateText = String(
    rawRecord.displayKey || rawRecord.date || payloadSource.displayKey || payloadSource.date || '',
  ).trim()
  const parsed = parseLegacySnapshotDate(legacyDateText)
  const type = inferLegacySnapshotType(rawRecord, sourceStoreName) || parsed.type
  if (!type) return null

  const timestampCandidate = Number(rawRecord.timestamp ?? payloadSource.timestamp)
  const tradingDate =
    String(rawRecord.tradingDate || payloadSource.tradingDate || parsed.tradingDate || '').trim()
  const slotTime = normalizeSnapshotSlotTime(
    type,
    String(rawRecord.slotTime || payloadSource.slotTime || parsed.slotTime || '').trim(),
  )

  const fallbackDate = toDateFromTradingDateAndSlot(tradingDate, slotTime)
  const timestamp =
    Number.isFinite(timestampCandidate) && timestampCandidate > 0
      ? timestampCandidate
      : fallbackDate?.getTime() || 0

  if (!tradingDate || !timestamp) return null

  const displayKey = buildSnapshotDisplayKey(type, tradingDate, slotTime)
  const normalizedPayload = {
    ...payloadSource,
    type,
    date: displayKey,
    timestamp,
    tradingDate,
    slotTime,
    displayKey,
  }
  const quality = createSnapshotQualityMetadata(fallbackDate || new Date(timestamp), {
    captureMode:
      rawRecord.captureMode === 'delayed' || rawRecord.captureMode === 'restored'
        ? rawRecord.captureMode
        : 'real_time',
    capturedAt: Number(rawRecord.capturedAt ?? payloadSource.capturedAt) || timestamp,
    dataTimestamp: Number(rawRecord.dataTimestamp ?? payloadSource.dataTimestamp) || timestamp,
    delayMs: Number(rawRecord.delayMs ?? payloadSource.delayMs) || 0,
    qualityFlags: Array.isArray(rawRecord.qualityFlags ?? payloadSource.qualityFlags)
      ? (rawRecord.qualityFlags ?? payloadSource.qualityFlags)
      : [],
    source:
      rawRecord.source === 'bucket_restore' ||
      rawRecord.source === 'cloud_restore' ||
      rawRecord.source === 'manual'
        ? rawRecord.source
        : 'browser_runtime',
  })

  return withSnapshotPayloadCompatFields({
    id: buildSnapshotId(type, tradingDate, slotTime),
    type,
    tradingDate,
    slotTime,
    timestamp,
    displayKey,
    ...quality,
    payload: normalizedPayload,
  })
}

function normalizeStoredSnapshotRecord(
  rawRecord: any,
  sourceStoreName: string,
): SnapshotRecord | null {
  try {
    return migrateLegacySnapshotRecord(rawRecord, sourceStoreName)
  } catch (error) {
    console.warn?.('[SnapshotStore] Skip malformed snapshot record:', {
      sourceStoreName,
      id: rawRecord?.id,
      type: rawRecord?.type,
      error: error instanceof Error ? error.message : String(error),
    })
    return null
  }
}

function estimateSnapshotPayloadSize(payload: unknown): number {
  if (payload === null || payload === undefined) return 0
  if (typeof payload !== 'object') return String(payload).length

  const snapshot = payload as Record<string, unknown>
  const hotlistCount = Array.isArray(snapshot.hotlist) ? snapshot.hotlist.length : 0
  const sectorCount = Array.isArray(snapshot.sectors) ? snapshot.sectors.length : 0
  const hotThemeCount = Array.isArray(snapshot.hotThemes) ? snapshot.hotThemes.length : 0
  const factorCount = Array.isArray(snapshot.breathFactors) ? snapshot.breathFactors.length : 0
  const metadataSize = snapshot.metadata && typeof snapshot.metadata === 'object' ? 160 : 0
  const sentimentSize = snapshot.sentiment && typeof snapshot.sentiment === 'object' ? 180 : 0
  const marketStatsSize = snapshot.marketStats && typeof snapshot.marketStats === 'object' ? 240 : 0

  return (
    Object.keys(snapshot).length * 32 +
    hotlistCount * 220 +
    sectorCount * 160 +
    hotThemeCount * 120 +
    factorCount * 80 +
    metadataSize +
    sentimentSize +
    marketStatsSize
  )
}

function estimateSnapshotRecordSize(record: SnapshotRecord): number {
  return (
    192 +
    String(record.id || '').length +
    String(record.displayKey || '').length +
    String(record.tradingDate || '').length +
    String(record.slotTime || '').length +
    (Array.isArray(record.qualityFlags) ? record.qualityFlags.join('').length : 0) +
    estimateSnapshotPayloadSize(record.payload)
  )
}

function createSnapshotRecordStore(db: IDBDatabase, recordStoreName: string) {
  const store = db.createObjectStore(recordStoreName, { keyPath: 'id' })
  store.createIndex('type', 'type', { unique: false })
  store.createIndex('tradingDate', 'tradingDate', { unique: false })
  store.createIndex('timestamp', 'timestamp')
  store.createIndex('type_tradingDate', ['type', 'tradingDate'], { unique: false })
  return store
}

function ensureProjectionStore(
  db: IDBDatabase,
  upgradeTransaction: IDBTransaction,
  storeName: string,
  keyPath: string,
  indexes: Array<{ name: string; keyPath: string | string[]; unique?: boolean }>,
) {
  const recreateStore = () => {
    if (db.objectStoreNames.contains(storeName)) {
      db.deleteObjectStore(storeName)
    }
    const store = db.createObjectStore(storeName, { keyPath })
    indexes.forEach((index) => {
      store.createIndex(index.name, index.keyPath as never, { unique: index.unique === true })
    })
  }

  if (!db.objectStoreNames.contains(storeName)) {
    recreateStore()
    return
  }

  const store = upgradeTransaction.objectStore(storeName)
  const existingKeyPath = store.keyPath
  const existingIndexes = new Set<string>(Array.from(store.indexNames || []))
  const missingIndexes = indexes.some((index) => !existingIndexes.has(index.name))
  if (existingKeyPath !== keyPath || missingIndexes) {
    recreateStore()
  }
}

function ensureSnapshotProjectionStores(db: IDBDatabase, upgradeTransaction: IDBTransaction): void {
  ensureProjectionStore(db, upgradeTransaction, SNAPSHOT_FRAME_STORE_NAME, 'id', [
    { name: 'type', keyPath: 'type' },
    { name: 'tradingDate', keyPath: 'tradingDate' },
    { name: 'timestamp', keyPath: 'timestamp' },
    { name: 'type_tradingDate', keyPath: ['type', 'tradingDate'] },
    { name: 'type_timestamp', keyPath: ['type', 'timestamp'] },
    { name: 'tradingDate_timestamp', keyPath: ['tradingDate', 'timestamp'] },
  ])

  ensureProjectionStore(db, upgradeTransaction, SNAPSHOT_STOCK_ROW_STORE_NAME, 'id', [
    { name: 'snapshotId', keyPath: 'snapshotId' },
    { name: 'type_tradingDate', keyPath: ['type', 'tradingDate'] },
    { name: 'type_timestamp', keyPath: ['type', 'timestamp'] },
    { name: 'type_tradingDate_code', keyPath: ['type', 'tradingDate', 'code'] },
    { name: 'code_type_timestamp', keyPath: ['code', 'type', 'timestamp'] },
    { name: 'code_type_slot_timestamp', keyPath: ['code', 'type', 'slotTime', 'timestamp'] },
  ])

  ensureProjectionStore(db, upgradeTransaction, SNAPSHOT_SECTOR_ROW_STORE_NAME, 'id', [
    { name: 'snapshotId', keyPath: 'snapshotId' },
    { name: 'type_tradingDate', keyPath: ['type', 'tradingDate'] },
    { name: 'type_timestamp', keyPath: ['type', 'timestamp'] },
    { name: 'entity_type_timestamp', keyPath: ['entityKey', 'entityType', 'timestamp'] },
    { name: 'type_tradingDate_entity', keyPath: ['type', 'tradingDate', 'entityType', 'entityKey'] },
  ])

  ensureProjectionStore(db, upgradeTransaction, SNAPSHOT_PROJECTION_META_STORE_NAME, 'key', [])
}

function ensureSnapshotRecordStore(
  db: IDBDatabase,
  upgradeTransaction: IDBTransaction,
  recordStoreName: string,
  redundantStores: string[],
): void {
  // 升级时优先保证正式 store 的 keyPath 和索引完整，
  // 然后再把旧 store 数据迁入并删除冗余仓库，避免主库里长期并存多套快照结构。
  const requiredIndexes = new Set(['type', 'tradingDate', 'timestamp', 'type_tradingDate'])
  const storesToMigrate: string[] = []
  let currentStoreInvalid = false

  if (db.objectStoreNames.contains(recordStoreName)) {
    const existingStore = upgradeTransaction.objectStore(recordStoreName)
    const keyPath = existingStore?.keyPath
    const indexNames = new Set<string>(Array.from(existingStore?.indexNames || []))
    currentStoreInvalid =
      keyPath !== 'id' || Array.from(requiredIndexes).some((name) => !indexNames.has(name))
    if (currentStoreInvalid) {
      storesToMigrate.push(recordStoreName)
    }
  }

  for (const storeName of redundantStores) {
    if (storeName !== recordStoreName && db.objectStoreNames.contains(storeName)) {
      storesToMigrate.push(storeName)
    }
  }

  const finalizeStores = (legacyRecords: SnapshotRecord[]) => {
    let targetStore: IDBObjectStore

    if (currentStoreInvalid) {
      if (db.objectStoreNames.contains(recordStoreName)) {
        db.deleteObjectStore(recordStoreName)
      }
      targetStore = createSnapshotRecordStore(db, recordStoreName)
    } else if (!db.objectStoreNames.contains(recordStoreName)) {
      targetStore = createSnapshotRecordStore(db, recordStoreName)
    } else {
      targetStore = upgradeTransaction.objectStore(recordStoreName)
    }

    for (const migratedRecord of legacyRecords) {
      targetStore.put(migratedRecord)
    }

    for (const storeName of redundantStores) {
      if (storeName !== recordStoreName && db.objectStoreNames.contains(storeName)) {
        db.deleteObjectStore(storeName)
      }
    }
  }

  if (storesToMigrate.length > 0) {
    const migrated = new Map<string, SnapshotRecord>()
    let remaining = storesToMigrate.length
    const finish = () => {
      remaining -= 1
      if (remaining === 0) {
        finalizeStores(Array.from(migrated.values()).sort((a, b) => a.timestamp - b.timestamp))
      }
    }

    for (const storeName of storesToMigrate) {
      const request = upgradeTransaction.objectStore(storeName).getAll()
      request.onsuccess = () => {
        const sourceRecords = Array.isArray(request.result) ? request.result : []
        for (const rawRecord of sourceRecords) {
          const migratedRecord = migrateLegacySnapshotRecord(rawRecord, storeName)
          if (migratedRecord) {
            migrated.set(migratedRecord.id, migratedRecord)
          }
        }
        finish()
      }
      request.onerror = () => finish()
    }
    return
  }

  if (!db.objectStoreNames.contains(recordStoreName)) {
    createSnapshotRecordStore(db, recordStoreName)
  }

  for (const storeName of redundantStores) {
    if (storeName !== recordStoreName && db.objectStoreNames.contains(storeName)) {
      db.deleteObjectStore(storeName)
    }
  }
}

async function resolveFactory(factoryProvider?: (() => Promise<any> | any) | any): Promise<any> {
  if (!factoryProvider) return indexedDB
  return typeof factoryProvider === 'function' ? await factoryProvider() : factoryProvider
}

async function openSnapshotDatabase(config: {
  dbName: string
  dbVersion: number
  factoryProvider?: (() => Promise<any> | any) | any
  snapshotStoreName?: string
  redundantStores?: string[]
}): Promise<IDBDatabase> {
  const factory = await resolveFactory(config.factoryProvider)
  return new Promise((resolve, reject) => {
    const request = factory.open(config.dbName, config.dbVersion)

    request.onerror = () => reject(request.error)
    request.onsuccess = () => resolve(request.result)
    request.onupgradeneeded = (event: Event) => {
      const db = (event.target as IDBOpenDBRequest).result
      const upgradeTransaction = (event.target as IDBOpenDBRequest).transaction
      if (!upgradeTransaction) {
        throw new Error(`missing_upgrade_transaction:${config.dbName}`)
      }
      if (config.snapshotStoreName) {
        ensureSnapshotRecordStore(
          db,
          upgradeTransaction,
          config.snapshotStoreName,
          config.redundantStores || [],
        )
      }
      ensureSnapshotProjectionStores(db, upgradeTransaction)
      if (db.objectStoreNames.contains('snapshot_sync_jobs')) {
        db.deleteObjectStore('snapshot_sync_jobs')
      }
    }
  })
}

// SnapshotStore 只处理 IndexedDB 的结构化读写、迁移和轻量统计，
// 不承载调度、coverage、备份状态等上层语义。
export class SnapshotStore {
  private readonly dbName: string
  private readonly dbVersion: number
  private readonly storeName: string
  private readonly redundantStores: string[]
  private readonly factoryProvider?: (() => Promise<any> | any) | any

  constructor(config: SnapshotStoreConfig) {
    this.dbName = config.dbName
    this.dbVersion = config.dbVersion
    this.storeName = config.storeName
    this.redundantStores = config.redundantStores || []
    this.factoryProvider = config.factoryProvider
  }

  async put(record: SnapshotRecord): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readwrite')
      const store = transaction.objectStore(this.storeName)
      const request = store.put(record)

      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async getById(id: string): Promise<SnapshotRecord | null> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readonly')
      const store = transaction.objectStore(this.storeName)
      const request = store.get(id)

      request.onerror = () => reject(request.error)
      request.onsuccess = () =>
        resolve(normalizeStoredSnapshotRecord(request.result, this.storeName) || null)
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async getAll(): Promise<SnapshotRecord[]> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readonly')
      const store = transaction.objectStore(this.storeName)
      const request = store.getAll()

      request.onerror = () => reject(request.error)
      request.onsuccess = () =>
        resolve(
          ((request.result || []) as SnapshotRecord[])
            .map((record) => normalizeStoredSnapshotRecord(record, this.storeName))
            .filter((record): record is SnapshotRecord => !!record),
        )
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async list(options: SnapshotQueryOptions = {}): Promise<SnapshotRecord[]> {
    const db = await this.openDB()
    const sort = options.sort || 'desc'
    const types = options.type ? [options.type] : options.types || []
    const allowedCaptureModes = options.allowedCaptureModes?.length
      ? new Set<SnapshotCaptureMode>(options.allowedCaptureModes)
      : null

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readonly')
      const store = transaction.objectStore(this.storeName)
      const direction: IDBCursorDirection = sort === 'asc' ? 'next' : 'prev'
      const results: SnapshotRecord[] = []
      let settled = false

      // Store 层只负责索引过滤，不负责 requireCoverage 这类交易日级语义。
      const matchesRecord = (record: SnapshotRecord) => {
        if (types.length > 0 && !types.includes(record.type)) return false
        if (options.tradingDate && record.tradingDate !== options.tradingDate) return false
        if (options.startDate && record.tradingDate < options.startDate) return false
        if (options.endDate && record.tradingDate > options.endDate) return false
        if (options.beforeTradingDate && record.tradingDate >= options.beforeTradingDate) return false
        if (options.excludeRestored && record.captureMode === 'restored') return false
        if (allowedCaptureModes && !allowedCaptureModes.has(record.captureMode)) return false
        return true
      }

      const finalize = () => {
        if (settled) return
        settled = true
        resolve(results)
      }
      const stopWithError = (error?: unknown) => {
        if (settled) return
        settled = true
        reject(error || transaction.error)
      }
      const openCursor = (
        source: IDBObjectStore | IDBIndex,
        range?: IDBKeyRange,
        useDirection: IDBCursorDirection = direction,
      ) => {
        const request = source.openCursor(range, useDirection)
        request.onerror = () => stopWithError(request.error)
        request.onsuccess = () => {
          const cursor = request.result
          if (!cursor) {
            finalize()
            return
          }
          const record = normalizeStoredSnapshotRecord(cursor.value, this.storeName)
          if (!record) {
            cursor.continue()
            return
          }
          if (matchesRecord(record)) {
            results.push(record)
            if (options.limit && options.limit > 0 && results.length >= options.limit) {
              finalize()
              return
            }
          }
          cursor.continue()
        }
      }
      transaction.onerror = () => stopWithError(transaction.error)
      transaction.oncomplete = () => db.close()

      // 优先走最窄索引，尽量避免退化到 timestamp 全表扫描。
      if (options.tradingDate && options.type) {
        openCursor(store.index('type_tradingDate'), IDBKeyRange.only([options.type, options.tradingDate]))
        return
      }

      if (options.type && (options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.startDate ?? ''
        const upperDate =
          options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate
        const upper = upperDate ?? '\uffff'
        const range = IDBKeyRange.bound([options.type, lower], [options.type, upper], false, false)
        openCursor(store.index('type_tradingDate'), range)
        return
      }

      if (!options.type && !options.types?.length && (options.tradingDate || options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.tradingDate || options.startDate || ''
        const upper =
          options.tradingDate ||
          (options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate) ||
          '\uffff'
        const range =
          options.tradingDate && !options.startDate && !options.endDate && !options.beforeTradingDate
            ? IDBKeyRange.only(options.tradingDate)
            : IDBKeyRange.bound(lower, upper, false, false)
        openCursor(store.index('tradingDate'), range)
        return
      }

      openCursor(store.index('timestamp'))
    })
  }

  async delete(id: string): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readwrite')
      const store = transaction.objectStore(this.storeName)
      const request = store.delete(id)

      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async getStats(): Promise<SnapshotStorageStats> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([this.storeName], 'readonly')
      const store = transaction.objectStore(this.storeName)
      // 这里改成 cursor + 近似估算，避免历史快照变多后再走全量 JSON 序列化主路径。
      const request = store.index('timestamp').openCursor(null, 'prev')
      const dates: string[] = []
      let totalSnapshots = 0
      let estimatedSize = 0

      request.onerror = () => reject(request.error)
      request.onsuccess = () => {
        const cursor = request.result
        if (!cursor) {
          resolve({
            totalSnapshots,
            dates,
            estimatedSize,
          })
          return
        }

        const record = normalizeStoredSnapshotRecord(cursor.value, this.storeName)
        if (record) {
          totalSnapshots += 1
          dates.push(record.displayKey)
          estimatedSize += estimateSnapshotRecordSize(record)
        }
        cursor.continue()
      }
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  private async openDB(): Promise<IDBDatabase> {
    return openSnapshotDatabase({
      dbName: this.dbName,
      dbVersion: this.dbVersion,
      factoryProvider: this.factoryProvider,
      snapshotStoreName: this.storeName,
      redundantStores: this.redundantStores,
    })
  }
}

class ProjectionStoreBase {
  protected readonly dbName: string
  protected readonly dbVersion: number
  protected readonly snapshotStoreName: string
  protected readonly redundantStores: string[]
  protected readonly factoryProvider?: (() => Promise<any> | any) | any

  constructor(config: SnapshotProjectionStoreConfig) {
    this.dbName = config.dbName
    this.dbVersion = config.dbVersion
    this.snapshotStoreName = config.snapshotStoreName
    this.redundantStores = config.redundantStores || []
    this.factoryProvider = config.factoryProvider
  }

  protected async openDB(): Promise<IDBDatabase> {
    return openSnapshotDatabase({
      dbName: this.dbName,
      dbVersion: this.dbVersion,
      factoryProvider: this.factoryProvider,
      snapshotStoreName: this.snapshotStoreName,
      redundantStores: this.redundantStores,
    })
  }
}

function createCaptureModeMatcher(
  allowedCaptureModes?: SnapshotCaptureMode[],
  excludeRestored?: boolean,
) {
  const allowed = allowedCaptureModes?.length ? new Set<SnapshotCaptureMode>(allowedCaptureModes) : null
  return (captureMode: SnapshotCaptureMode) => {
    if (excludeRestored && captureMode === 'restored') return false
    if (allowed && !allowed.has(captureMode)) return false
    return true
  }
}

function deleteRowsBySnapshotId(store: IDBObjectStore, snapshotId: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = store.index('snapshotId').getAllKeys(IDBKeyRange.only(snapshotId))
    request.onerror = () => reject(request.error)
    request.onsuccess = () => {
      const keys = Array.isArray(request.result) ? request.result : []
      keys.forEach((key) => store.delete(key))
      resolve()
    }
  })
}

export async function replaceProjectionBundleRows(
  snapshotStore: IDBObjectStore,
  frameStore: IDBObjectStore,
  stockStore: IDBObjectStore,
  sectorStore: IDBObjectStore,
  bundles: SnapshotProjectionBundle[],
): Promise<void> {
  const normalizedBundles = Array.from(
    new Map(
      bundles
        .filter((bundle) => bundle?.record?.id)
        .map((bundle) => [bundle.record.id, bundle] satisfies [string, SnapshotProjectionBundle]),
    ).values(),
  )

  for (const bundle of normalizedBundles) {
    const snapshotId = bundle.record.id
    frameStore.delete(snapshotId)
    await deleteRowsBySnapshotId(stockStore, snapshotId)
    await deleteRowsBySnapshotId(sectorStore, snapshotId)

    snapshotStore.put(bundle.record)
    if (bundle.frame) {
      frameStore.put(bundle.frame)
    }
    bundle.stockRows.forEach((row) => stockStore.put(row))
    bundle.sectorRows.forEach((row) => sectorStore.put(row))
  }
}

export class SnapshotProjectionWriter extends ProjectionStoreBase {
  async saveBundle(bundle: SnapshotProjectionBundle): Promise<void> {
    return this.saveBundles([bundle])
  }

  async saveBundles(bundles: SnapshotProjectionBundle[]): Promise<void> {
    if (!bundles.length) return
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(
        [
          this.snapshotStoreName,
          SNAPSHOT_FRAME_STORE_NAME,
          SNAPSHOT_STOCK_ROW_STORE_NAME,
          SNAPSHOT_SECTOR_ROW_STORE_NAME,
        ],
        'readwrite',
      )
      const snapshotStore = transaction.objectStore(this.snapshotStoreName)
      const frameStore = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const stockStore = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      const sectorStore = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)

      void replaceProjectionBundleRows(snapshotStore, frameStore, stockStore, sectorStore, bundles).catch(
        (error) => reject(error),
      )

      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
    })
  }

  async clearProjectionStores(): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction(
        [SNAPSHOT_FRAME_STORE_NAME, SNAPSHOT_STOCK_ROW_STORE_NAME, SNAPSHOT_SECTOR_ROW_STORE_NAME],
        'readwrite',
      )
      const frameStore = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const stockStore = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      const sectorStore = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)
      frameStore.clear()
      stockStore.clear()
      sectorStore.clear()

      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
    })
  }
}

export class SnapshotFrameStore extends ProjectionStoreBase {
  async list(options: SnapshotFrameQueryOptions = {}): Promise<SnapshotFrameRow[]> {
    const db = await this.openDB()
    const sort = options.sort || 'desc'
    const types = options.type ? [options.type] : options.types || []
    const matchesCaptureMode = createCaptureModeMatcher(
      options.allowedCaptureModes,
      options.excludeRestored,
    )

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_FRAME_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const direction: IDBCursorDirection = sort === 'asc' ? 'next' : 'prev'
      const results: SnapshotFrameRow[] = []

      const matches = (row: SnapshotFrameRow) => {
        if (types.length > 0 && !types.includes(row.type)) return false
        if (options.tradingDate && row.tradingDate !== options.tradingDate) return false
        if (options.startDate && row.tradingDate < options.startDate) return false
        if (options.endDate && row.tradingDate > options.endDate) return false
        if (options.beforeTradingDate && row.tradingDate >= options.beforeTradingDate) return false
        return matchesCaptureMode(row.captureMode)
      }

      const finish = () => resolve(results)
      const requestCursor = (source: IDBObjectStore | IDBIndex, range?: IDBKeyRange) => {
        const request = source.openCursor(range, direction)
        request.onerror = () => reject(request.error)
        request.onsuccess = () => {
          const cursor = request.result
          if (!cursor) {
            finish()
            return
          }
          const row = cursor.value as SnapshotFrameRow
          if (matches(row)) {
            results.push(row)
            if (options.limit && options.limit > 0 && results.length >= options.limit) {
              finish()
              return
            }
          }
          cursor.continue()
        }
      }

      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()

      if (options.tradingDate && options.type) {
        requestCursor(
          store.index('type_tradingDate'),
          IDBKeyRange.only([options.type, options.tradingDate]),
        )
        return
      }
      if (options.type && (options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.startDate ?? ''
        const upperDate =
          options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate
        const upper = upperDate ?? '\uffff'
        requestCursor(store.index('type_tradingDate'), IDBKeyRange.bound([options.type, lower], [options.type, upper]))
        return
      }
      if (!options.type && !options.types?.length && (options.tradingDate || options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.tradingDate || options.startDate || ''
        const upper =
          options.tradingDate ||
          (options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate) ||
          '\uffff'
        const range =
          options.tradingDate && !options.startDate && !options.endDate && !options.beforeTradingDate
            ? IDBKeyRange.only(options.tradingDate)
            : IDBKeyRange.bound(lower, upper)
        requestCursor(store.index('tradingDate'), range)
        return
      }
      if (options.type && options.limit && options.limit > 0) {
        requestCursor(store.index('type_timestamp'), IDBKeyRange.bound([options.type, 0], [options.type, Number.MAX_SAFE_INTEGER]))
        return
      }
      requestCursor(store.index('timestamp'))
    })
  }

  async getBySnapshotId(snapshotId: string): Promise<SnapshotFrameRow | null> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_FRAME_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const request = store.get(snapshotId)
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve((request.result as SnapshotFrameRow | undefined) || null)
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async deleteBySnapshotId(snapshotId: string): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_FRAME_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const request = store.delete(snapshotId)
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async clearAll(): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_FRAME_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_FRAME_STORE_NAME)
      const request = store.clear()
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }
}

export class SnapshotStockRowStore extends ProjectionStoreBase {
  async list(options: SnapshotStockRowQueryOptions = {}): Promise<SnapshotStockRow[]> {
    const db = await this.openDB()
    const sort = options.sort || 'desc'
    const types = options.type ? [options.type] : options.types || []
    const codes = options.code ? [options.code] : options.codes || []
    const matchesCaptureMode = createCaptureModeMatcher(
      options.allowedCaptureModes,
      options.excludeRestored,
    )

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_STOCK_ROW_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      const direction: IDBCursorDirection = sort === 'asc' ? 'next' : 'prev'
      const results: SnapshotStockRow[] = []

      const matches = (row: SnapshotStockRow) => {
        if (options.snapshotId && row.snapshotId !== options.snapshotId) return false
        if (types.length > 0 && !types.includes(row.type)) return false
        if (codes.length > 0 && !codes.includes(row.code)) return false
        if (options.slotTime && row.slotTime !== options.slotTime) return false
        if (options.tradingDate && row.tradingDate !== options.tradingDate) return false
        if (options.startDate && row.tradingDate < options.startDate) return false
        if (options.endDate && row.tradingDate > options.endDate) return false
        if (options.beforeTradingDate && row.tradingDate >= options.beforeTradingDate) return false
        return matchesCaptureMode(row.captureMode)
      }

      const finish = () => resolve(results)
      const requestCursor = (source: IDBObjectStore | IDBIndex, range?: IDBKeyRange) => {
        const request = source.openCursor(range, direction)
        request.onerror = () => reject(request.error)
        request.onsuccess = () => {
          const cursor = request.result
          if (!cursor) {
            finish()
            return
          }
          const row = cursor.value as SnapshotStockRow
          if (matches(row)) {
            results.push(row)
            if (options.limit && options.limit > 0 && results.length >= options.limit) {
              finish()
              return
            }
          }
          cursor.continue()
        }
      }

      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()

      if (options.snapshotId) {
        requestCursor(store.index('snapshotId'), IDBKeyRange.only(options.snapshotId))
        return
      }
      if (codes.length === 1 && options.type && options.slotTime) {
        requestCursor(
          store.index('code_type_slot_timestamp'),
          IDBKeyRange.bound(
            [codes[0], options.type, options.slotTime, 0],
            [codes[0], options.type, options.slotTime, Number.MAX_SAFE_INTEGER],
          ),
        )
        return
      }
      if (codes.length === 1 && options.type) {
        requestCursor(
          store.index('code_type_timestamp'),
          IDBKeyRange.bound(
            [codes[0], options.type, 0],
            [codes[0], options.type, Number.MAX_SAFE_INTEGER],
          ),
        )
        return
      }
      if (options.type && options.tradingDate) {
        requestCursor(
          store.index('type_tradingDate_code'),
          IDBKeyRange.bound(
            [options.type, options.tradingDate, ''],
            [options.type, options.tradingDate, '\uffff'],
          ),
        )
        return
      }
      if (options.type && (options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.startDate ?? ''
        const upperDate =
          options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate
        const upper = upperDate ?? '\uffff'
        requestCursor(
          store.index('type_tradingDate'),
          IDBKeyRange.bound([options.type, lower], [options.type, upper]),
        )
        return
      }
      if (options.type && options.limit && options.limit > 0) {
        requestCursor(
          store.index('type_timestamp'),
          IDBKeyRange.bound([options.type, 0], [options.type, Number.MAX_SAFE_INTEGER]),
        )
        return
      }
      requestCursor(store.index('type_timestamp'))
    })
  }

  async countBySnapshotId(snapshotId: string): Promise<number> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_STOCK_ROW_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      const request = store.index('snapshotId').count(IDBKeyRange.only(snapshotId))
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve(Number(request.result) || 0)
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async deleteBySnapshotId(snapshotId: string): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_STOCK_ROW_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      void deleteRowsBySnapshotId(store, snapshotId).catch((error) => reject(error))
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
    })
  }

  async clearAll(): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_STOCK_ROW_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_STOCK_ROW_STORE_NAME)
      const request = store.clear()
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }
}

export class SnapshotSectorRowStore extends ProjectionStoreBase {
  async list(options: SnapshotSectorRowQueryOptions = {}): Promise<SnapshotSectorRow[]> {
    const db = await this.openDB()
    const sort = options.sort || 'desc'
    const types = options.type ? [options.type] : options.types || []
    const entityTypes = options.entityType ? [options.entityType] : options.entityTypes || []
    const entityKeys = options.entityKey ? [options.entityKey] : options.entityKeys || []
    const matchesCaptureMode = createCaptureModeMatcher(
      options.allowedCaptureModes,
      options.excludeRestored,
    )

    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_SECTOR_ROW_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)
      const direction: IDBCursorDirection = sort === 'asc' ? 'next' : 'prev'
      const results: SnapshotSectorRow[] = []

      const matches = (row: SnapshotSectorRow) => {
        if (options.snapshotId && row.snapshotId !== options.snapshotId) return false
        if (types.length > 0 && !types.includes(row.type)) return false
        if (entityTypes.length > 0 && !entityTypes.includes(row.entityType)) return false
        if (entityKeys.length > 0 && !entityKeys.includes(row.entityKey)) return false
        if (options.tradingDate && row.tradingDate !== options.tradingDate) return false
        if (options.startDate && row.tradingDate < options.startDate) return false
        if (options.endDate && row.tradingDate > options.endDate) return false
        if (options.beforeTradingDate && row.tradingDate >= options.beforeTradingDate) return false
        return matchesCaptureMode(row.captureMode)
      }

      const finish = () => resolve(results)
      const requestCursor = (source: IDBObjectStore | IDBIndex, range?: IDBKeyRange) => {
        const request = source.openCursor(range, direction)
        request.onerror = () => reject(request.error)
        request.onsuccess = () => {
          const cursor = request.result
          if (!cursor) {
            finish()
            return
          }
          const row = cursor.value as SnapshotSectorRow
          if (matches(row)) {
            results.push(row)
            if (options.limit && options.limit > 0 && results.length >= options.limit) {
              finish()
              return
            }
          }
          cursor.continue()
        }
      }

      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()

      if (options.snapshotId) {
        requestCursor(store.index('snapshotId'), IDBKeyRange.only(options.snapshotId))
        return
      }
      if (entityKeys.length === 1 && entityTypes.length === 1) {
        requestCursor(
          store.index('entity_type_timestamp'),
          IDBKeyRange.bound(
            [entityKeys[0], entityTypes[0], 0],
            [entityKeys[0], entityTypes[0], Number.MAX_SAFE_INTEGER],
          ),
        )
        return
      }
      if (options.type && options.tradingDate && entityTypes.length === 1) {
        requestCursor(
          store.index('type_tradingDate_entity'),
          IDBKeyRange.bound(
            [options.type, options.tradingDate, entityTypes[0], ''],
            [options.type, options.tradingDate, entityTypes[0], '\uffff'],
          ),
        )
        return
      }
      if (options.type && (options.tradingDate || options.startDate || options.endDate || options.beforeTradingDate)) {
        const lower = options.tradingDate || options.startDate || ''
        const upper =
          options.tradingDate ||
          (options.beforeTradingDate && (!options.endDate || options.beforeTradingDate <= options.endDate)
            ? options.beforeTradingDate
            : options.endDate) ||
          '\uffff'
        requestCursor(
          store.index('type_tradingDate'),
          IDBKeyRange.bound([options.type, lower], [options.type, upper]),
        )
        return
      }
      requestCursor(store.index('type_timestamp'))
    })
  }

  async countBySnapshotId(snapshotId: string): Promise<number> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_SECTOR_ROW_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)
      const request = store.index('snapshotId').count(IDBKeyRange.only(snapshotId))
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve(Number(request.result) || 0)
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async deleteBySnapshotId(snapshotId: string): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_SECTOR_ROW_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)
      void deleteRowsBySnapshotId(store, snapshotId).catch((error) => reject(error))
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => {
        db.close()
        resolve()
      }
    })
  }

  async clearAll(): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_SECTOR_ROW_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_SECTOR_ROW_STORE_NAME)
      const request = store.clear()
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }
}

export class SnapshotProjectionMetaStore extends ProjectionStoreBase {
  async get(): Promise<SnapshotProjectionMeta | null> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_PROJECTION_META_STORE_NAME], 'readonly')
      const store = transaction.objectStore(SNAPSHOT_PROJECTION_META_STORE_NAME)
      const request = store.get('global')
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve((request.result as SnapshotProjectionMeta | undefined) || null)
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async put(meta: SnapshotProjectionMeta): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_PROJECTION_META_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_PROJECTION_META_STORE_NAME)
      const request = store.put(meta)
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }

  async clear(): Promise<void> {
    const db = await this.openDB()
    return new Promise((resolve, reject) => {
      const transaction = db.transaction([SNAPSHOT_PROJECTION_META_STORE_NAME], 'readwrite')
      const store = transaction.objectStore(SNAPSHOT_PROJECTION_META_STORE_NAME)
      const request = store.clear()
      request.onerror = () => reject(request.error)
      request.onsuccess = () => resolve()
      transaction.onerror = () => reject(transaction.error)
      transaction.oncomplete = () => db.close()
    })
  }
}
