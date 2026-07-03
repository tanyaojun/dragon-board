import {
  buildSnapshotFrameRow,
  buildSnapshotSectorRows,
  buildSnapshotStockRows,
  type SnapshotBuildContext,
} from './builders'
import type {
  SnapshotProjectionBundle,
  SnapshotRecord,
  SnapshotSectorEntityType,
  SnapshotSectorRow,
  SnapshotStockRow,
  SnapshotType,
} from './types'

const PRESERVED_STOCK_SIGNAL_FIELDS: Array<keyof SnapshotStockRow> = [
  'rankChange',
  'directionSignal',
  'directionConfidence',
  'accelerationSignal',
  'accelerationConfidence',
  'crossSignal',
  'crossConfidence',
  'finalSignal',
  'finalConfidence',
]

const STOCK_ROW_RECORD_FIELDS: Array<keyof SnapshotStockRow> = [
  'id',
  'snapshotId',
  'type',
  'tradingDate',
  'slotTime',
  'timestamp',
  'captureMode',
  'source',
]

const SECTOR_ROW_RECORD_FIELDS: Array<keyof SnapshotSectorRow> = [
  'id',
  'snapshotId',
  'type',
  'tradingDate',
  'slotTime',
  'timestamp',
  'captureMode',
  'source',
]

function clonePlain<T>(value: T): T {
  if (value === null || value === undefined) return value
  return JSON.parse(JSON.stringify(value))
}

function toBaseStockRowRecordFields(record: SnapshotRecord, code: string) {
  return {
    id: `${record.id}:${code}`,
    snapshotId: record.id,
    type: record.type as Exclude<SnapshotType, 'five_minute'>,
    tradingDate: record.tradingDate,
    slotTime: record.slotTime,
    timestamp: record.timestamp,
    captureMode: record.captureMode,
    source: record.source,
  } satisfies Pick<
    SnapshotStockRow,
    'id' | 'snapshotId' | 'type' | 'tradingDate' | 'slotTime' | 'timestamp' | 'captureMode' | 'source'
  >
}

function toBaseSectorRowRecordFields(
  record: SnapshotRecord,
  entityType: SnapshotSectorEntityType,
  entityKey: string,
) {
  return {
    id: `${record.id}:${entityType}:${entityKey}`,
    snapshotId: record.id,
    type: record.type as Exclude<SnapshotType, 'five_minute'>,
    tradingDate: record.tradingDate,
    slotTime: record.slotTime,
    timestamp: record.timestamp,
    captureMode: record.captureMode,
    source: record.source,
  } satisfies Pick<
    SnapshotSectorRow,
    'id' | 'snapshotId' | 'type' | 'tradingDate' | 'slotTime' | 'timestamp' | 'captureMode' | 'source'
  >
}

function dedupeStockRows(rows: SnapshotStockRow[]): SnapshotStockRow[] {
  const byCode = new Map<string, SnapshotStockRow>()
  rows.forEach((row) => {
    const code = String(row?.code || '').trim()
    if (!code) return
    byCode.set(code, row)
  })
  return Array.from(byCode.values()).sort(
    (left, right) => (Number(left.rank) || 0) - (Number(right.rank) || 0) || left.code.localeCompare(right.code),
  )
}

function dedupeSectorRows(rows: SnapshotSectorRow[]): SnapshotSectorRow[] {
  const byKey = new Map<string, SnapshotSectorRow>()
  rows.forEach((row) => {
    const entityType = String(row?.entityType || '').trim()
    const entityKey = String(row?.entityKey || '').trim()
    if (!entityType || !entityKey) return
    byKey.set(`${entityType}:${entityKey}`, row)
  })
  return Array.from(byKey.values()).sort(
    (left, right) =>
      (Number(left.rank) || 0) - (Number(right.rank) || 0) ||
      `${left.entityType}:${left.entityKey}`.localeCompare(`${right.entityType}:${right.entityKey}`),
  )
}

function canDeriveSectorEntityType(
  record: SnapshotRecord,
  entityType: SnapshotSectorEntityType,
  buildContext?: SnapshotBuildContext,
): boolean {
  const payload =
    record.payload && typeof record.payload === 'object'
      ? (record.payload as Record<string, any>)
      : ({} as Record<string, any>)

  if (entityType === 'sector') {
    return Array.isArray(payload.sectors)
  }
  if (entityType === 'hot_theme') {
    return Array.isArray(payload.hotThemes) || Array.isArray(buildContext?.hotThemes)
  }
  return (
    Array.isArray(payload.rotation?.mainLines) ||
    Array.isArray(payload.rotationSummary?.mainLines) ||
    Array.isArray(buildContext?.rotationAnalysis?.mainLines)
  )
}

function normalizeExistingStockRows(record: SnapshotRecord, rows: SnapshotStockRow[]): SnapshotStockRow[] {
  return dedupeStockRows(rows).map((row) => ({
    ...clonePlain(row),
    ...toBaseStockRowRecordFields(record, row.code),
  }))
}

function normalizeExistingSectorRows(record: SnapshotRecord, rows: SnapshotSectorRow[]): SnapshotSectorRow[] {
  return dedupeSectorRows(rows).map((row) => ({
    ...clonePlain(row),
    ...toBaseSectorRowRecordFields(record, row.entityType, row.entityKey),
  }))
}

function reconcileStockRows(
  record: SnapshotRecord,
  derivedRows: SnapshotStockRow[],
  existingRows: SnapshotStockRow[],
): SnapshotStockRow[] {
  if (record.type === 'five_minute') return []

  const normalizedExisting = normalizeExistingStockRows(record, existingRows)
  if (derivedRows.length === 0) {
    return []
  }
  if (normalizedExisting.length === 0) {
    return derivedRows
  }

  const existingByCode = new Map(normalizedExisting.map((row) => [row.code, row]))
  const derivedCodes = derivedRows.map((row) => row.code)
  const sameCodeSet =
    normalizedExisting.length === derivedRows.length &&
    normalizedExisting.every((row) => derivedCodes.includes(row.code))

  if (sameCodeSet) {
    return derivedRows.map((row) => {
      const existing = existingByCode.get(row.code)
      return existing
        ? ({
            ...existing,
            ...toBaseStockRowRecordFields(record, row.code),
          } satisfies SnapshotStockRow)
        : row
    })
  }

  return derivedRows.map((row) => {
    const existing = existingByCode.get(row.code)
    if (!existing) return row

    const patched = {
      ...row,
    } as SnapshotStockRow

    PRESERVED_STOCK_SIGNAL_FIELDS.forEach((field) => {
      const value = existing[field]
      if (value !== undefined && value !== null && value !== '') {
        ;(patched as any)[field] = value
      }
    })

    return patched
  })
}

function reconcileSectorRows(
  record: SnapshotRecord,
  derivedRows: SnapshotSectorRow[],
  existingRows: SnapshotSectorRow[],
  buildContext?: SnapshotBuildContext,
): SnapshotSectorRow[] {
  if (record.type === 'five_minute') return []

  const normalizedExisting = normalizeExistingSectorRows(record, existingRows)
  if (normalizedExisting.length === 0) {
    return derivedRows
  }
  if (derivedRows.length === 0) {
    const hasAnyDerivableEntityType =
      canDeriveSectorEntityType(record, 'sector', buildContext) ||
      canDeriveSectorEntityType(record, 'hot_theme', buildContext) ||
      canDeriveSectorEntityType(record, 'rotation_main_line', buildContext)
    return hasAnyDerivableEntityType ? [] : normalizedExisting
  }

  const derivedIds = new Set(derivedRows.map((row) => row.id))
  const preserved = normalizedExisting.filter(
    (row) => !canDeriveSectorEntityType(record, row.entityType, buildContext) && !derivedIds.has(row.id),
  )

  return [...derivedRows, ...preserved].sort(
    (left, right) =>
      (Number(left.rank) || 0) - (Number(right.rank) || 0) ||
      `${left.entityType}:${left.entityKey}`.localeCompare(`${right.entityType}:${right.entityKey}`),
  )
}

function compactRotationSummary(rotation: any): Record<string, any> | undefined {
  if (!rotation || typeof rotation !== 'object') return undefined

  const compact = {
    marketPhase: typeof rotation.marketPhase === 'string' ? rotation.marketPhase : '',
    rotationSpeed: Number(rotation.rotationSpeed) || 0,
    suggestion: typeof rotation.suggestion === 'string' ? rotation.suggestion : '',
  } as Record<string, any>

  if (!compact.marketPhase && !compact.rotationSpeed && !compact.suggestion) {
    return undefined
  }

  return compact
}

function compactHotlistItem(item: any): Record<string, any> {
  const compact = {
    code: item?.code,
    name: item?.name,
    rank: item?.rank,
    compRank: item?.compRank,
    platforms: item?.platforms,
    avgRank: item?.avgRank,
    avgRankNum: item?.avgRankNum,
    price: item?.price,
    change: item?.change,
    volume: item?.volume,
    turnover: item?.turnover,
    turnoverRate: item?.turnoverRate,
    totalMV: item?.totalMV,
    cirMV: item?.cirMV,
    zlje: item?.zlje,
    zljzb: item?.zljzb,
    cddje: item?.cddje,
    cddjzb: item?.cddjzb,
    pe: item?.pe,
    pb: item?.pb,
    volumeRatio: item?.volumeRatio,
    speed: item?.speed,
    leadStatus: item?.leadStatus,
    leadTimes: item?.leadTimes,
    lianbanStr: item?.lianbanStr,
    fengdan: item?.fengdan,
    maxFengdan: item?.maxFengdan,
    popularity: item?.popularity,
    popularityChange: item?.popularityChange,
    institutionBuy: item?.institutionBuy,
    bigMoney300: item?.bigMoney300,
    themes: clonePlain(item?.themes),
    isNew: item?.isNew,
    reason: item?.reason,
    firstZtTime: item?.firstZtTime,
    lastZtTime: item?.lastZtTime,
    boardHeight: item?.boardHeight,
    highDays: item?.highDays,
    hotness: item?.hotness,
    mainTheme: item?.mainTheme,
    themeHeat: item?.themeHeat,
    themeLevel: item?.themeLevel,
  } as Record<string, any>

  return Object.fromEntries(Object.entries(compact).filter(([, value]) => value !== undefined))
}

export function buildCanonicalProjectionBundle(
  record: SnapshotRecord,
  options?: {
    existingStockRows?: SnapshotStockRow[]
    existingSectorRows?: SnapshotSectorRow[]
    sourceStocksByCode?: Map<string, any>
    buildContext?: SnapshotBuildContext
  },
): SnapshotProjectionBundle {
  if (record.type === 'five_minute') {
    return {
      record,
      frame: null,
      stockRows: [],
      sectorRows: [],
    }
  }

  const derivedStockRows = buildSnapshotStockRows(record, options?.sourceStocksByCode)
  const derivedSectorRows = buildSnapshotSectorRows(record, options?.buildContext)
  const stockRows = reconcileStockRows(record, derivedStockRows, options?.existingStockRows || [])
  const sectorRows = reconcileSectorRows(
    record,
    derivedSectorRows,
    options?.existingSectorRows || [],
    options?.buildContext,
  )
  const frame = buildSnapshotFrameRow(record)

  if (frame) {
    frame.stockRowCount = stockRows.length
    frame.sectorRowCount = sectorRows.length
  }

  return {
    record,
    frame,
    stockRows,
    sectorRows,
  }
}

export function compactSnapshotPayload(
  type: SnapshotType,
  payload: unknown,
): Record<string, any> {
  const source = payload && typeof payload === 'object' ? (payload as Record<string, any>) : {}
  const compact: Record<string, any> = {}

  if (source.timestamp !== undefined) compact.timestamp = source.timestamp
  if (source.sentiment && typeof source.sentiment === 'object') compact.sentiment = clonePlain(source.sentiment)
  if (source.moneyFlow && typeof source.moneyFlow === 'object') compact.moneyFlow = clonePlain(source.moneyFlow)
  if (Array.isArray(source.sectors)) compact.sectors = clonePlain(source.sectors)
  if (Array.isArray(source.hotlist)) compact.hotlist = source.hotlist.map((item) => compactHotlistItem(item))

  if (source.marketStats && typeof source.marketStats === 'object') {
    compact.marketStats = clonePlain(source.marketStats)
  }
  if (source.market && typeof source.market === 'object') {
    compact.market = clonePlain(source.market)
  }
  if (source.indices && typeof source.indices === 'object') {
    compact.indices = clonePlain(source.indices)
  }
  if (source.metadata && typeof source.metadata === 'object') {
    compact.metadata = clonePlain(source.metadata)
  }
  if (source.zhaban && typeof source.zhaban === 'object') {
    compact.zhaban = clonePlain(source.zhaban)
  }
  if (source.yesterdayZt && typeof source.yesterdayZt === 'object') {
    compact.yesterdayZt = clonePlain(source.yesterdayZt)
  }
  if (source.limit && typeof source.limit === 'object') {
    compact.limit = clonePlain(source.limit)
  }
  if (source.stats && typeof source.stats === 'object') {
    compact.stats = clonePlain(source.stats)
  }
  if (source.continuousBoards && typeof source.continuousBoards === 'object') {
    compact.continuousBoards = clonePlain(source.continuousBoards)
  }

  const rotationSummary = compactRotationSummary(source.rotationSummary || source.rotation)
  if (rotationSummary) {
    compact.rotationSummary = rotationSummary
  }

  if (type === 'daily' && !compact.market && source.marketStats && typeof source.marketStats === 'object') {
    compact.market = clonePlain(source.marketStats)
  }

  return compact
}

export function compactSnapshotRecord(record: SnapshotRecord): SnapshotRecord {
  return {
    ...record,
    payload: compactSnapshotPayload(record.type, record.payload),
  }
}
