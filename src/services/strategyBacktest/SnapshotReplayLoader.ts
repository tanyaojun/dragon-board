import { dataLayer } from '@/services/DataLayer'
import { DEFAULT_RANK_TREND_SNAPSHOT_TYPE } from '@/type/rankTrendDefaults'
import type {
  SnapshotCaptureMode,
  SnapshotRecord,
  SnapshotStockRow,
  SnapshotType,
} from '@/services/snapshot/types'
import type {
  BacktestMeta,
  BacktestSnapshotType,
  LoadedReplayFrames,
  ReplayFrame,
  ReplayMarketContext,
  ReplayStock,
  StrategyBacktestRunOptions,
} from './types'

const DEFAULT_SNAPSHOT_TYPES: BacktestSnapshotType[] = [DEFAULT_RANK_TREND_SNAPSHOT_TYPE]
const LOW_HOTLIST_THRESHOLD = 20

function normalizeNumber(value: unknown): number | undefined {
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

function normalizeStock(row: SnapshotStockRow | any, index: number): ReplayStock | null {
  const code = String(row?.code || '').trim()
  if (!code) return null
  const rank = normalizeNumber(row?.rank) ?? index + 1
  return {
    ...row,
    code,
    name: String(row?.name || code),
    rank,
    price: normalizeNumber(row?.price),
    change: normalizeNumber(row?.change),
    volumeRatio: normalizeNumber(row?.volumeRatio),
    zlje: normalizeNumber(row?.zlje),
    zljzb: normalizeNumber(row?.zljzb),
    turnoverRate: normalizeNumber(row?.turnoverRate),
  }
}

function getPayloadHotlist(record: SnapshotRecord): ReplayStock[] {
  const payload = record.payload || {}
  const hotlist = Array.isArray(payload.hotlist)
    ? payload.hotlist
    : Array.isArray((record as any).hotlist)
      ? (record as any).hotlist
      : []
  return hotlist
    .map((row: any, index: number) => normalizeStock(row, index))
    .filter((row: ReplayStock | null): row is ReplayStock => row !== null)
    .sort((a, b) => a.rank - b.rank)
}

function buildMarketContext(record: SnapshotRecord): ReplayMarketContext {
  const payload = record.payload || {}
  return {
    marketStats: payload.marketStats || payload.market || payload.marketData || null,
    sentiment: payload.sentiment || payload.breathData || payload.dragonBreath || null,
    moneyFlow: payload.moneyFlow || null,
    indices: payload.indices || null,
    limitSummary: payload.limitSummary || payload.limitPool || null,
    rotationSummary: payload.rotationSummary || null,
    payload,
  }
}

function makeEmptyMeta(
  requestedSnapshotTypes: BacktestSnapshotType[],
  warnings: string[] = [],
): BacktestMeta {
  return {
    snapshotTypeUsed: null,
    requestedSnapshotTypes,
    snapshotCount: 0,
    tradingDateCount: 0,
    tradingDateRange: { start: null, end: null },
    delayedCount: 0,
    restoredCount: 0,
    emptyHotlistCount: 0,
    lowHotlistCount: 0,
    sampleQuality: 'insufficient',
    featureCoverage: 'partial',
    warnings,
    generatedAt: Date.now(),
  }
}

export class SnapshotReplayLoader {
  async load(options: StrategyBacktestRunOptions = {}): Promise<LoadedReplayFrames> {
    const requestedTypes = options.snapshotTypes?.length
      ? options.snapshotTypes
      : DEFAULT_SNAPSHOT_TYPES
    const warnings: string[] = []

    for (const type of requestedTypes) {
      const records = await dataLayer.listSnapshots({
        type: type as SnapshotType,
        startDate: options.startDate,
        endDate: options.endDate,
        sort: 'asc',
      })

      if (!records.length) {
        warnings.push(`${type} 无可用快照`)
        continue
      }

      const { frames, usedProjectionRows } = await this.buildFrames(records, type)
      if (!frames.length) {
        warnings.push(`${type} 快照没有可回放热榜`)
        continue
      }

      return {
        frames,
        meta: this.buildMeta({
          frames,
          records,
          type,
          requestedTypes,
          usedProjectionRows,
          inheritedWarnings: warnings,
        }),
      }
    }

    return {
      frames: [],
      meta: makeEmptyMeta(requestedTypes, warnings),
    }
  }

  async loadSingleFrame(snapshotId: string): Promise<ReplayFrame | null> {
    const record = await dataLayer.getSnapshotById(snapshotId)
    if (!record || record.type === 'five_minute') return null
    const { frames } = await this.buildFrames(
      [record],
      record.type as BacktestSnapshotType,
    )
    return frames[0] || null
  }

  private async buildFrames(
    records: SnapshotRecord[],
    type: BacktestSnapshotType,
  ): Promise<{ frames: ReplayFrame[]; usedProjectionRows: boolean }> {
    let usedProjectionRows = true
    const frames: ReplayFrame[] = []

    for (const record of records) {
      const projectionRows = await dataLayer.listSnapshotStockRows({
        snapshotId: record.id,
        sort: 'asc',
      })
      let stocks = projectionRows
        .map((row, index) => normalizeStock(row, index))
        .filter((row: ReplayStock | null): row is ReplayStock => row !== null)
        .sort((a, b) => a.rank - b.rank)

      if (!stocks.length) {
        stocks = getPayloadHotlist(record)
        usedProjectionRows = false
      }

      frames.push({
        snapshotId: record.id,
        timestamp: Number(record.timestamp) || 0,
        tradingDate: record.tradingDate || '',
        slotTime: record.slotTime || '',
        type,
        captureMode: (record.captureMode || 'real_time') as SnapshotCaptureMode,
        stocks,
        marketContext: buildMarketContext(record),
      })
    }

    return {
      frames: frames
        .filter((frame) => frame.timestamp > 0)
        .sort((a, b) => a.timestamp - b.timestamp),
      usedProjectionRows,
    }
  }

  private buildMeta(input: {
    frames: ReplayFrame[]
    records: SnapshotRecord[]
    type: BacktestSnapshotType
    requestedTypes: BacktestSnapshotType[]
    usedProjectionRows: boolean
    inheritedWarnings: string[]
  }): BacktestMeta {
    const { frames, type, requestedTypes, usedProjectionRows, inheritedWarnings } = input
    const tradingDates = Array.from(new Set(frames.map((frame) => frame.tradingDate).filter(Boolean))).sort()
    const delayedCount = frames.filter((frame) => frame.captureMode === 'delayed').length
    const restoredCount = frames.filter((frame) => frame.captureMode === 'restored').length
    const emptyHotlistCount = frames.filter((frame) => frame.stocks.length === 0).length
    const lowHotlistCount = frames.filter(
      (frame) => frame.stocks.length > 0 && frame.stocks.length < LOW_HOTLIST_THRESHOLD,
    ).length
    const warnings = [...inheritedWarnings]

    if (!usedProjectionRows) warnings.push('部分快照投影表缺失，已回退 payload.hotlist')
    if (emptyHotlistCount > 0) warnings.push(`存在 ${emptyHotlistCount} 个空热榜快照`)
    if (lowHotlistCount > 0) warnings.push(`存在 ${lowHotlistCount} 个低热榜样本`)
    if (restoredCount > 0) warnings.push(`包含 ${restoredCount} 个 restored 快照`)
    if (frames.length < 5) warnings.push('快照数量过少，后验统计只能作为调试参考')

    const sampleQuality =
      frames.length === 0
        ? 'insufficient'
        : warnings.length > 0 || frames.length < 30
          ? 'degraded'
          : 'ok'

    return {
      snapshotTypeUsed: type,
      requestedSnapshotTypes: requestedTypes,
      snapshotCount: frames.length,
      tradingDateCount: tradingDates.length,
      tradingDateRange: {
        start: tradingDates[0] || null,
        end: tradingDates[tradingDates.length - 1] || null,
      },
      delayedCount,
      restoredCount,
      emptyHotlistCount,
      lowHotlistCount,
      sampleQuality,
      featureCoverage: usedProjectionRows ? 'full' : 'partial',
      warnings,
      generatedAt: Date.now(),
    }
  }
}
