// src/services/theme/themeHistorySeries.ts
// 题材历史趋势序列：SectorDetail 历史趋势页签的生产数据源装配层。
//
// 数据链（两源并行、槽位对齐）：
// - 热度/涨停/龙头/涨跌：GET /api/snapshots/sector-rows（entityKey=题材 id）
// - 成交量/成交额：GET /api/themes/stock-volume-series（题材名聚合成分股 stock rows）
//
// fail-visible 约束：
// - 两源独立成败，任一失败不清空另一源数据，结构化记入 sources 状态。
// - 缺失值保持 null，禁止补 0；聚合端 amountCount/volumeCount=0 时对应总和视为缺失。
import { apiService } from '../apiService'
import type { SnapshotSectorEntityType } from '../snapshot/types'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE, type RankTrendSnapshotType } from '../../types/rankTrendDefaults'

export type ThemeHistoryTimeRange = '1h' | '6h' | '1d' | '1w' | '1m'

export interface ThemeHistoryPoint {
  timestamp: number
  tradingDate: string
  slotTime: string
  heat: number | null
  ztCount: number | null
  leaderCount: number | null
  avgChange: number | null
  totalVolume: number | null
  totalAmount: number | null
  stockCount: number | null
  volumeCount: number | null
  amountCount: number | null
  rank: number | null
  mainNetInflow: number | null
  rotationState: string | null
}

export interface ThemeHistorySourceStatus {
  ok: boolean
  count: number
  message?: string
}

export interface ThemeHistorySeriesResult {
  ok: boolean
  points: ThemeHistoryPoint[]
  sectorRows: ThemeHistorySourceStatus
  volumeSeries: ThemeHistorySourceStatus
  message?: string
  /** 窗口锚定的最后可用数据交易日（YYYY-MM-DD）；与今天不同时 UI 提示"已锚定最后交易日" */
  anchorDate?: string
}

export interface ThemeHistorySectorRowsParams {
  entityType: SnapshotSectorEntityType
  entityKey: string
  types: RankTrendSnapshotType[]
  startDate: string
  endDate: string
  sort: 'asc' | 'desc'
  limit: number
}

export interface ThemeHistoryVolumeSeriesParams {
  themeName: string
  types: string
  startDate: string
  endDate: string
  limit: number
}

export interface ThemeHistoryFetchers {
  fetchSectorRows: (params: ThemeHistorySectorRowsParams) => Promise<{ ok: boolean; rows: any[]; count: number }>
  fetchVolumeSeries: (params: ThemeHistoryVolumeSeriesParams) => Promise<{ ok: boolean; rows: any[]; count: number }>
}

const RANGE_MS: Record<ThemeHistoryTimeRange, number> = {
  '1h': 60 * 60 * 1000,
  '6h': 6 * 60 * 60 * 1000,
  '1d': 24 * 60 * 60 * 1000,
  '1w': 7 * 24 * 60 * 60 * 1000,
  '1m': 30 * 24 * 60 * 60 * 1000,
}

const SECTOR_ROW_LIMIT = 5000

function toDateStr(ms: number): string {
  const d = new Date(ms)
  const month = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${month}-${day}`
}

function numOrNull(value: unknown): number | null {
  if (value === null || value === undefined) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function errorMessage(err: unknown): string {
  if (err instanceof Error) return err.message
  return String(err)
}

function toPointBase(row: any): ThemeHistoryPoint {
  return {
    timestamp: Number(row?.timestamp) || 0,
    tradingDate: String(row?.tradingDate || ''),
    slotTime: String(row?.slotTime || ''),
    heat: numOrNull(row?.heatScore),
    ztCount: numOrNull(row?.ztCount),
    leaderCount: numOrNull(row?.leaderCount),
    avgChange: numOrNull(row?.change),
    totalVolume: null,
    totalAmount: null,
    stockCount: null,
    volumeCount: null,
    amountCount: null,
    rank: numOrNull(row?.rank),
    mainNetInflow: numOrNull(row?.mainNetInflow),
    rotationState: row?.rotationState ? String(row.rotationState) : null,
  }
}

function mergeVolumePoint(point: ThemeHistoryPoint, volumeRow: any): void {
  point.totalVolume = numOrNull(volumeRow?.totalVolume)
  point.totalAmount = numOrNull(volumeRow?.totalAmount)
  point.stockCount = numOrNull(volumeRow?.stockCount)
  point.volumeCount = numOrNull(volumeRow?.volumeCount)
  point.amountCount = numOrNull(volumeRow?.amountCount)
  // 聚合端 $sum 全缺语义为 0：count=0 表示组内无可加数值，视为缺失而非真实 0
  if (point.volumeCount === 0) point.totalVolume = null
  if (point.amountCount === 0) point.totalAmount = null
}

async function defaultFetchSectorRows(params: ThemeHistorySectorRowsParams) {
  return apiService.listMongoSnapshotSectorRows(params)
}

async function defaultFetchVolumeSeries(params: ThemeHistoryVolumeSeriesParams) {
  return apiService.getThemeStockVolumeSeries(params)
}

export async function fetchThemeHistorySeries(
  options: {
    themeId: string
    themeName: string
    timeRange: ThemeHistoryTimeRange
    nowMs?: number
  },
  fetchers?: Partial<ThemeHistoryFetchers>,
): Promise<ThemeHistorySeriesResult> {
  const { themeId, themeName, timeRange } = options
  const nowMs = options.nowMs ?? Date.now()

  const fetchSectorRows = fetchers?.fetchSectorRows ?? defaultFetchSectorRows
  const fetchVolumeSeries = fetchers?.fetchVolumeSeries ?? defaultFetchVolumeSeries

  // 窗口锚点探测：按自然日从"现在"回望在非交易日/长假会整窗落空（2026-09-27 实证：
  // 周末+中秋窗口 0 行）。先探最后一条可用数据行，把窗口锚定到最后交易日——
  // "最近1天"=最后一个交易日的槽位序列，而不是"昨天到现在"。
  let anchorMs = nowMs
  let anchorDate: string | undefined
  try {
    const probe = await fetchSectorRows({
      entityType: 'hot_theme',
      entityKey: themeId,
      types: [DEFAULT_RANK_TREND_SNAPSHOT_TYPE],
      startDate: '',
      endDate: '',
      sort: 'desc',
      limit: 1,
    })
    // 取返回行中时间戳最大者（不依赖调用方的排序实现）
    let probeRow: any = null
    for (const row of Array.isArray(probe?.rows) ? probe.rows : []) {
      if (!probeRow || (Number(row?.timestamp) || 0) > (Number(probeRow.timestamp) || 0)) probeRow = row
    }
    if (probeRow?.tradingDate) {
      anchorMs = Number(probeRow.timestamp) || Date.parse(`${probeRow.tradingDate}T15:00:00`) || nowMs
      const todayStr = toDateStr(nowMs)
      if (String(probeRow.tradingDate) !== todayStr) anchorDate = String(probeRow.tradingDate)
    }
  } catch {
    // 探测失败不阻断：退回按"现在"锚定的原口径
  }

  const cutoff = anchorMs - RANGE_MS[timeRange]
  const startDate = toDateStr(cutoff)
  const endDate = toDateStr(anchorMs)

  const sectorParams: ThemeHistorySectorRowsParams = {
    entityType: 'hot_theme',
    entityKey: themeId,
    types: [DEFAULT_RANK_TREND_SNAPSHOT_TYPE],
    startDate,
    endDate,
    sort: 'asc',
    limit: SECTOR_ROW_LIMIT,
  }
  const volumeParams: ThemeHistoryVolumeSeriesParams = {
    themeName,
    types: DEFAULT_RANK_TREND_SNAPSHOT_TYPE,
    startDate,
    endDate,
    limit: SECTOR_ROW_LIMIT,
  }

  // 两源独立成败：任一失败保留另一源数据并结构化记录原因（fail-visible）
  const [sectorOutcome, volumeOutcome] = await Promise.allSettled([
    fetchSectorRows(sectorParams),
    fetchVolumeSeries(volumeParams),
  ])

  const sectorRows =
    sectorOutcome.status === 'fulfilled' && Array.isArray(sectorOutcome.value?.rows)
      ? sectorOutcome.value.rows
      : []
  const volumeRows =
    volumeOutcome.status === 'fulfilled' && Array.isArray(volumeOutcome.value?.rows)
      ? volumeOutcome.value.rows
      : []

  const sectorStatus: ThemeHistorySourceStatus =
    sectorOutcome.status === 'fulfilled'
      ? { ok: true, count: sectorRows.length }
      : { ok: false, count: 0, message: errorMessage(sectorOutcome.reason) }
  const volumeStatus: ThemeHistorySourceStatus =
    volumeOutcome.status === 'fulfilled'
      ? { ok: true, count: volumeRows.length }
      : { ok: false, count: 0, message: errorMessage(volumeOutcome.reason) }

  // volume rows 按 timestamp 建索引，与 sector 时间轴合并
  const volumeByTimestamp = new Map<number, any>()
  for (const row of volumeRows) {
    const ts = Number(row?.timestamp) || 0
    if (ts > 0) volumeByTimestamp.set(ts, row)
  }

  // sector 时间轴为主轨道
  const byTimestamp = new Map<number, ThemeHistoryPoint>()
  for (const row of sectorRows) {
    const point = toPointBase(row)
    if (!point.timestamp) continue
    const volumeRow = volumeByTimestamp.get(point.timestamp)
    if (volumeRow) mergeVolumePoint(point, volumeRow)
    byTimestamp.set(point.timestamp, point)
  }
  // volume 独有槽位保留为独立轨道（sector 缺槽不清空成交量）；
  // heat 等字段由 toPointBase 对 volume 行缺省为 null，不伪造
  for (const [ts, volumeRow] of volumeByTimestamp) {
    if (byTimestamp.has(ts)) continue
    const point = toPointBase(volumeRow)
    mergeVolumePoint(point, volumeRow)
    byTimestamp.set(ts, point)
  }

  // 时间窗过滤 + 升序
  const points = [...byTimestamp.values()]
    .filter(point => point.timestamp >= cutoff)
    .sort((a, b) => a.timestamp - b.timestamp)

  const allFailed = !sectorStatus.ok && !volumeStatus.ok
  return {
    ok: !allFailed,
    points,
    sectorRows: sectorStatus,
    volumeSeries: volumeStatus,
    anchorDate,
    message: allFailed ? `题材历史数据不可用: ${sectorStatus.message}; ${volumeStatus.message}` : undefined,
  }
}
