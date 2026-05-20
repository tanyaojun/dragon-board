import { filterValidStockCodes } from '@/utils/common'
import { clamp } from '../theme/utils'
import { toLocalTradingDate, type FormalSnapshotType } from '../snapshot/identity'
import { slotTimeToMinutes } from '../snapshot/schedule'
import { snapshotFacade } from '../snapshot/facade'
import type { SnapshotStockRow } from '../snapshot/types'
import { getAshareVolumeClockMinute } from './VolumeRatioCalculator'

const VOLUME_RATIO_HISTORY_DAYS = 3
const INTRADAY_STOCK_ROW_LOOKBACK = 240
const STOCK_ROW_QUERY_BATCH_SIZE = 12

function rowVolume(row: SnapshotStockRow): number | undefined {
  const volume = Number(row.volume)
  return Number.isFinite(volume) && volume > 0 ? volume : undefined
}

export class VolumeHistoryService {
  constructor(private readonly intradaySnapshotTypes: FormalSnapshotType[]) {}

  async buildIntradayVolumeHistoryMap(
    codes: string[] = [],
    date: Date = new Date(),
  ): Promise<Map<string, number[]>> {
    const targetCodes = filterValidStockCodes([...new Set(codes)])
    const targetClockMinute = getAshareVolumeClockMinute(date)
    if (targetCodes.length === 0 || targetClockMinute === undefined) return new Map()

    const anchorTradingDate = toLocalTradingDate(date)
    const rowsByCode = await this.loadIntradayRowsByCode(
      targetCodes,
      anchorTradingDate,
      targetClockMinute,
    )
    const result = new Map<string, number[]>()

    for (const code of targetCodes) {
      const volumes = this.selectIntradayVolumes(rowsByCode.get(code) || [], targetClockMinute)
      if (volumes.length) result.set(code, volumes)
    }

    return result
  }

  async buildVolumeHistoryMap(codes: string[] = []): Promise<Map<string, number[]>> {
    const targetCodes = filterValidStockCodes([...new Set(codes)])
    if (targetCodes.length === 0) return new Map()
    return snapshotFacade.getStockVolumeHistory(targetCodes, {
      anchorTradingDate: toLocalTradingDate(new Date()),
      lookbackDays: 4,
    })
  }

  private async loadIntradayRowsByCode(
    codes: string[],
    beforeTradingDate: string,
    targetClockMinute: number,
  ): Promise<Map<string, SnapshotStockRow[]>> {
    const rowsByCode = new Map<string, SnapshotStockRow[]>()
    const allowedCaptureModes: Array<'real_time' | 'delayed'> = ['real_time', 'delayed']
    const fallbackCodes: string[] = []

    for (let index = 0; index < codes.length; index += STOCK_ROW_QUERY_BATCH_SIZE) {
      const chunk = codes.slice(index, index + STOCK_ROW_QUERY_BATCH_SIZE)
      const batchLimit = INTRADAY_STOCK_ROW_LOOKBACK * chunk.length
      const rows = await snapshotFacade.listSnapshotStockRows({
        codes: chunk,
        types: this.intradaySnapshotTypes,
        beforeTradingDate,
        allowedCaptureModes,
        excludeRestored: true,
        sort: 'desc',
        limit: batchLimit,
      })
      this.appendRowsByCode(rowsByCode, rows, chunk)

      if (rows.length >= batchLimit) {
        fallbackCodes.push(
          ...chunk.filter(
            (code) =>
              this.selectIntradayVolumes(rowsByCode.get(code) || [], targetClockMinute).length <
              VOLUME_RATIO_HISTORY_DAYS,
          ),
        )
      }
    }

    for (let index = 0; index < fallbackCodes.length; index += STOCK_ROW_QUERY_BATCH_SIZE) {
      const chunk = fallbackCodes.slice(index, index + STOCK_ROW_QUERY_BATCH_SIZE)
      await Promise.all(
        chunk.map(async (code) => {
          const rows = await snapshotFacade.listSnapshotStockRows({
            code,
            types: this.intradaySnapshotTypes,
            beforeTradingDate,
            allowedCaptureModes,
            excludeRestored: true,
            sort: 'desc',
            limit: INTRADAY_STOCK_ROW_LOOKBACK,
          })
          rowsByCode.set(code, rows.filter((row) => row.code === code))
        }),
      )
    }

    return rowsByCode
  }

  private appendRowsByCode(
    rowsByCode: Map<string, SnapshotStockRow[]>,
    rows: SnapshotStockRow[],
    codes: string[],
  ): void {
    const codeSet = new Set(codes)
    rows.forEach((row) => {
      if (!codeSet.has(row.code)) return
      const list = rowsByCode.get(row.code) || []
      list.push(row)
      rowsByCode.set(row.code, list)
    })
    codes.forEach((code) => {
      if (!rowsByCode.has(code)) rowsByCode.set(code, [])
    })
  }

  private selectIntradayVolumes(rows: SnapshotStockRow[], targetClockMinute: number): number[] {
    const byDate = new Map<string, SnapshotStockRow[]>()
    rows.forEach((row) => {
      const tradingDate = row.tradingDate
      if (!tradingDate || row.slotTime === 'daily' || rowVolume(row) === undefined) return
      const list = byDate.get(tradingDate) || []
      list.push(row)
      byDate.set(tradingDate, list)
    })

    const volumes: number[] = []
    const dates = Array.from(byDate.keys()).sort((left, right) => right.localeCompare(left))

    for (const tradingDate of dates) {
      if (volumes.length >= VOLUME_RATIO_HISTORY_DAYS) break
      const rowsForDate = byDate
        .get(tradingDate)!
        .slice()
        .sort((left, right) => slotTimeToMinutes(left.slotTime) - slotTimeToMinutes(right.slotTime))

      let previous: SnapshotStockRow | undefined
      let next: SnapshotStockRow | undefined
      for (const row of rowsForDate) {
        const minute = slotTimeToMinutes(row.slotTime)
        if (minute < 0) continue
        if (minute <= targetClockMinute) previous = row
        if (minute >= targetClockMinute) {
          next = row
          break
        }
      }

      if (!previous) continue

      const volume = this.interpolateSnapshotVolume(
        {
          previous,
          next: next && next.id !== previous.id ? next : undefined,
        },
        targetClockMinute,
      )
      if (volume !== undefined) volumes.push(volume)
    }

    return volumes
  }

  private interpolateSnapshotVolume(
    selected: { previous: SnapshotStockRow; next?: SnapshotStockRow },
    targetClockMinute: number,
  ): number | undefined {
    const previousVolume = rowVolume(selected.previous)
    if (previousVolume === undefined) return undefined

    if (!selected.next) return previousVolume

    const previousMinute = slotTimeToMinutes(selected.previous.slotTime)
    const nextMinute = slotTimeToMinutes(selected.next.slotTime)
    if (previousMinute < 0 || nextMinute <= previousMinute) return previousVolume

    const nextVolume = rowVolume(selected.next)
    if (nextVolume === undefined || nextVolume < previousVolume) return previousVolume

    const progress = clamp(
      (targetClockMinute - previousMinute) / (nextMinute - previousMinute),
      0,
      1,
    )
    return previousVolume + (nextVolume - previousVolume) * progress
  }
}
