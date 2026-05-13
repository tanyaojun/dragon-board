import { RankTrendGoldenReplayEngine } from '@/services/quantBoardGolden/RankTrendGoldenReplayEngine'
import {
  cloneDefaultRankTrendRuntimeConfig,
  DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
  type RankTrendSnapshotType,
  type RTConfigPatch,
} from '@/types/rankTrendDefaults'
import type {
  GoldenReplayFrame,
  GoldenReplayMarketContext,
  GoldenReplayMeta,
  GoldenReplaySignal,
  GoldenReplayStock,
  GoldenSnapshotType,
} from '@/services/quantBoardGolden/types'

type QuantBoardBridgeRequest = {
  type: 'quant-board:read-indexeddb'
  requestId: string
  dbName?: string
  snapshotType?: RankTrendSnapshotType
  limit?: number
  startDate?: string
  endDate?: string
}

type QuantBoardBridgeResponse = {
  type: 'quant-board:indexeddb-result'
  requestId: string
  ok: boolean
  payload?: Record<string, unknown>
  error?: string
}

const DEFAULT_DB_NAME = 'DragonBoardData'
const DEFAULT_LIMIT = 500
const DEFAULT_GOLDEN_SAMPLE_LIMIT = 100
const inFlightRequestIds = new Set<string>()

type QuantBoardTsGoldenExportOptions = {
  dbName?: string
  caseId?: string
  datasetId?: string
  snapshotType?: RankTrendSnapshotType
  limit?: number
  sampleLimit?: number
  startDate?: string
  endDate?: string
  rankTrendConfig?: RTConfigPatch
  download?: boolean
}

type QuantBoardTsGoldenPayload = {
  id: string
  caseId: string
  datasetId: string
  snapshotType: RankTrendSnapshotType
  source: 'ts_golden_import'
  generatedAt: string
  dragonBoardOrigin: string
  rankTrendConfig: ReturnType<typeof cloneDefaultRankTrendRuntimeConfig>
  input: {
    dbName: string
    frameCount: number
    signalCount: number
    sampleLimit: number
    startDate?: string
    endDate?: string
    frames: GoldenReplayFrame[]
    stockRows: Record<string, unknown>[]
  }
  signals: GoldenReplaySignal[]
}

function isAllowedQuantBoardOrigin(origin: string): boolean {
  try {
    const url = new URL(origin)
    return (
      url.protocol === 'http:' &&
      ['localhost', '127.0.0.1'].includes(url.hostname) &&
      ['5174', '4174'].includes(url.port)
    )
  } catch {
    return false
  }
}

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error('IndexedDB request failed'))
  })
}

function openDragonBoardDb(dbName: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName)
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => reject(request.error || new Error(`open IndexedDB failed: ${dbName}`))
    request.onupgradeneeded = () => {
      request.transaction?.abort()
      reject(new Error(`IndexedDB database does not exist or requires upgrade: ${dbName}`))
    }
  })
}

async function readStoreAll(db: IDBDatabase, storeName: string): Promise<Record<string, unknown>[]> {
  if (!db.objectStoreNames.contains(storeName)) {
    return []
  }
  const transaction = db.transaction(storeName, 'readonly')
  const store = transaction.objectStore(storeName)
  const rows = await requestToPromise(store.getAll())
  return Array.isArray(rows) ? (rows.filter((row) => row && typeof row === 'object') as Record<string, unknown>[]) : []
}

function rowDate(row: Record<string, unknown>): string {
  return String(row.tradingDate || row.trading_date || '')
}

function rowType(row: Record<string, unknown>): string {
  return String(row.type || '')
}

function rowTimestamp(row: Record<string, unknown>): number {
  return Number(row.timestamp || 0)
}

function rowSnapshotId(row: Record<string, unknown>): string {
  return String(row.snapshotId || row.snapshot_id || row.id || '')
}

function normalizeNumber(value: unknown): number | undefined {
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function normalizeReplayStock(row: Record<string, unknown>, index: number): GoldenReplayStock | null {
  const code = String(row.code || row.stockCode || row.securityCode || '').trim()
  if (!code) return null
  return {
    ...row,
    code,
    name: String(row.name || row.stockName || code),
    rank: normalizeNumber(row.rank || row.compRank) ?? index + 1,
    price: normalizeNumber(row.price || row.latestPrice),
    change: normalizeNumber(row.change || row.changePct),
    volumeRatio: normalizeNumber(row.volumeRatio || row.volume_ratio),
    zlje: normalizeNumber(row.zlje),
    zljzb: normalizeNumber(row.zljzb),
    turnoverRate: normalizeNumber(row.turnoverRate || row.turnover_rate),
  }
}

function normalizeMarketContext(frame: Record<string, unknown>): GoldenReplayMarketContext {
  const payload = frame.payload && typeof frame.payload === 'object' ? (frame.payload as Record<string, unknown>) : {}
  return {
    marketStats: (frame.marketStats as Record<string, unknown>) || (payload.marketStats as Record<string, unknown>) || null,
    sentiment: (frame.sentiment as Record<string, unknown>) || (payload.sentiment as Record<string, unknown>) || null,
    moneyFlow: (frame.moneyFlow as Record<string, unknown>) || (payload.moneyFlow as Record<string, unknown>) || null,
    indices: (frame.indices as Record<string, unknown>) || (payload.indices as Record<string, unknown>) || null,
    limitSummary:
      (frame.limitSummary as Record<string, unknown>) || (payload.limitSummary as Record<string, unknown>) || null,
    rotationSummary:
      (frame.rotationSummary as Record<string, unknown>) ||
      (payload.rotationSummary as Record<string, unknown>) ||
      null,
    payload,
  }
}

function buildReplayMeta(
  frames: GoldenReplayFrame[],
  snapshotType: GoldenSnapshotType,
  requestedTypes: GoldenSnapshotType[],
): GoldenReplayMeta {
  const tradingDates = Array.from(new Set(frames.map((frame) => frame.tradingDate).filter(Boolean))).sort()
  const delayedCount = frames.filter((frame) => frame.captureMode === 'delayed').length
  const restoredCount = frames.filter((frame) => frame.captureMode === 'restored').length
  const emptyHotlistCount = frames.filter((frame) => frame.stocks.length === 0).length
  const lowHotlistCount = frames.filter((frame) => frame.stocks.length > 0 && frame.stocks.length < 20).length
  const warnings: string[] = []
  if (emptyHotlistCount) warnings.push(`存在 ${emptyHotlistCount} 个空热榜快照`)
  if (lowHotlistCount) warnings.push(`存在 ${lowHotlistCount} 个低热榜样本`)
  if (delayedCount) warnings.push(`包含 ${delayedCount} 个 delayed 快照`)
  if (restoredCount) warnings.push(`包含 ${restoredCount} 个 restored 快照`)

  return {
    snapshotTypeUsed: snapshotType,
    requestedSnapshotTypes: requestedTypes,
    snapshotCount: frames.length,
    tradingDateCount: tradingDates.length,
    tradingDateRange: { start: tradingDates[0] || null, end: tradingDates[tradingDates.length - 1] || null },
    delayedCount,
    restoredCount,
    emptyHotlistCount,
    lowHotlistCount,
    sampleQuality: warnings.length || frames.length < 30 ? 'degraded' : 'ok',
    featureCoverage: 'full',
    warnings,
    generatedAt: Date.now(),
  }
}

function buildReplayFrames(
  frames: Record<string, unknown>[],
  stockRows: Record<string, unknown>[],
  snapshotType: RankTrendSnapshotType,
): GoldenReplayFrame[] {
  const rowsBySnapshotId = new Map<string, Record<string, unknown>[]>()
  for (const row of stockRows) {
    const snapshotId = rowSnapshotId(row)
    if (!snapshotId) continue
    const rows = rowsBySnapshotId.get(snapshotId) || []
    rows.push(row)
    rowsBySnapshotId.set(snapshotId, rows)
  }

  return frames
    .map((frame): GoldenReplayFrame | null => {
      const snapshotId = rowSnapshotId(frame)
      const timestamp = rowTimestamp(frame)
      if (!snapshotId || !timestamp) return null
      const stocks = (rowsBySnapshotId.get(snapshotId) || [])
        .map((row, index) => normalizeReplayStock(row, index))
        .filter((row: GoldenReplayStock | null): row is GoldenReplayStock => row !== null)
        .sort((left, right) => left.rank - right.rank)
      return {
        snapshotId,
        timestamp,
        tradingDate: rowDate(frame),
        slotTime: String(frame.slotTime || frame.slot_time || ''),
        type: snapshotType as GoldenSnapshotType,
        captureMode: (frame.captureMode || frame.capture_mode || 'real_time') as GoldenReplayFrame['captureMode'],
        stocks,
        marketContext: normalizeMarketContext(frame),
      }
    })
    .filter((frame: GoldenReplayFrame | null): frame is GoldenReplayFrame => frame !== null)
    .sort((left, right) => left.timestamp - right.timestamp)
}

function downloadJson(filename: string, payload: unknown): void {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.style.display = 'none'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function filterByRequest(rows: Record<string, unknown>[], request: QuantBoardBridgeRequest): Record<string, unknown>[] {
  const snapshotType = request.snapshotType || 'half_hour'
  const limit = Math.max(1, Math.min(Number(request.limit || DEFAULT_LIMIT), 5000))
  return rows
    .filter((row) => rowType(row) === snapshotType)
    .filter((row) => !request.startDate || rowDate(row) >= request.startDate)
    .filter((row) => !request.endDate || rowDate(row) <= request.endDate)
    .sort((left, right) => rowTimestamp(left) - rowTimestamp(right))
    .slice(-limit)
}

function postBridgeResponse(target: Window, origin: string, response: QuantBoardBridgeResponse): void {
  target.postMessage(response, origin)
}

async function handleBridgeRequest(event: MessageEvent<QuantBoardBridgeRequest>): Promise<void> {
  if (!isAllowedQuantBoardOrigin(event.origin)) {
    return
  }
  const request = event.data
  if (!request || request.type !== 'quant-board:read-indexeddb' || !request.requestId) {
    return
  }
  if (!event.source || typeof (event.source as Window).postMessage !== 'function') {
    return
  }
  if (inFlightRequestIds.has(request.requestId)) {
    return
  }
  inFlightRequestIds.add(request.requestId)

  try {
    const db = await openDragonBoardDb(request.dbName || DEFAULT_DB_NAME)
    try {
      const allFrames = await readStoreAll(db, 'snapshot_frames')
      const frames = filterByRequest(allFrames, request)
      const snapshotIds = new Set(frames.map(rowSnapshotId).filter(Boolean))
      const records = (await readStoreAll(db, 'snapshots')).filter((row) => snapshotIds.has(rowSnapshotId(row)))
      const stockRows = (await readStoreAll(db, 'snapshot_stock_rows')).filter((row) => snapshotIds.has(rowSnapshotId(row)))
      const sectorRows = (await readStoreAll(db, 'snapshot_sector_rows')).filter((row) => snapshotIds.has(rowSnapshotId(row)))

      postBridgeResponse(event.source as Window, event.origin, {
        type: 'quant-board:indexeddb-result',
        requestId: request.requestId,
        ok: true,
        payload: {
          metadata: {
            reader: 'dragon_board_runtime_bridge',
            db_name: request.dbName || DEFAULT_DB_NAME,
            origin: window.location.origin,
            capturedAt: new Date().toISOString(),
            snapshotType: request.snapshotType || 'half_hour',
            limit: request.limit || DEFAULT_LIMIT,
          },
          records,
          frames,
          stockRows,
          sectorRows,
        },
      })
    } finally {
      db.close()
    }
  } catch (error) {
    postBridgeResponse(event.source as Window, event.origin, {
      type: 'quant-board:indexeddb-result',
      requestId: request.requestId,
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    })
  } finally {
    inFlightRequestIds.delete(request.requestId)
  }
}

export function installQuantBoardBridge(): void {
  if (typeof window === 'undefined' || (window as any).__quantBoardBridgeInstalled) {
    return
  }
  ;(window as any).__quantBoardBridgeInstalled = true
  window.addEventListener('message', (event) => {
    void handleBridgeRequest(event as MessageEvent<QuantBoardBridgeRequest>)
  })
  ;(window as any).quantBoardExportRankTrendGolden = exportQuantBoardRankTrendGolden
  console.log('[QuantBoardBridge] ready for local QuantBoard runtime import')
  console.log(
    '[QuantBoardBridge] TS Golden export: window.quantBoardExportRankTrendGolden({ datasetId: "ds_xxx", sampleLimit: 100 })',
  )
}

export async function exportQuantBoardRankTrendGolden(
  options: QuantBoardTsGoldenExportOptions = {},
): Promise<QuantBoardTsGoldenPayload> {
  // 历史遗留：仅读取迁移前的 IndexedDB 历史数据，不再作为正式快照来源。
  // 正式快照已迁移至 MongoDB 后端，此函数仅用于回放旧数据或导出 golden case。
  const dbName = options.dbName || DEFAULT_DB_NAME
  const snapshotType = options.snapshotType || DEFAULT_RANK_TREND_SNAPSHOT_TYPE
  const limit = Math.max(1, Math.min(Number(options.limit || DEFAULT_LIMIT), 5000))
  const sampleLimit = Math.max(1, Math.min(Number(options.sampleLimit || DEFAULT_GOLDEN_SAMPLE_LIMIT), 5000))
  const db = await openDragonBoardDb(dbName)

  try {
    const allFrames = await readStoreAll(db, 'snapshot_frames')
    const frames = filterByRequest(allFrames, { type: 'quant-board:read-indexeddb', requestId: 'ts-golden-export', dbName, snapshotType, limit, startDate: options.startDate, endDate: options.endDate })
    const snapshotIds = new Set(frames.map(rowSnapshotId).filter(Boolean))
    const stockRows = (await readStoreAll(db, 'snapshot_stock_rows')).filter((row) => snapshotIds.has(rowSnapshotId(row)))
    const replayFrames = buildReplayFrames(frames, stockRows, snapshotType)

    if (!replayFrames.length) {
      throw new Error(`DragonBoard IndexedDB has no replayable ${snapshotType} frames`)
    }

    const requestedTypes = [snapshotType as GoldenSnapshotType]
    const meta = buildReplayMeta(replayFrames, snapshotType as GoldenSnapshotType, requestedTypes)
    const rankTrendConfig = { ...cloneDefaultRankTrendRuntimeConfig(), ...(options.rankTrendConfig || {}) }
    const signals = new RankTrendGoldenReplayEngine(options.rankTrendConfig || {}).replay(replayFrames, {
      windowSize: 50,
      maxSignals: sampleLimit,
      meta,
    })
    const caseId = options.caseId || 'rank_trend_default'
    const payload: QuantBoardTsGoldenPayload = {
      id: caseId,
      caseId,
      datasetId: options.datasetId || 'dragonboard_current_indexeddb',
      snapshotType,
      source: 'ts_golden_import',
      generatedAt: new Date().toISOString(),
      dragonBoardOrigin: window.location.origin,
      rankTrendConfig,
      input: {
        dbName,
        frameCount: replayFrames.length,
        signalCount: signals.length,
        sampleLimit,
        startDate: options.startDate,
        endDate: options.endDate,
        frames: replayFrames,
        stockRows: stockRows,
      },
      signals,
    }

    if (options.download !== false) {
      downloadJson(`${caseId}.${snapshotType}.ts-golden.json`, payload)
    }

    return payload
  } finally {
    db.close()
  }
}
