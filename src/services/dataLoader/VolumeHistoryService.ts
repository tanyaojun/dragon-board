import { filterValidStockCodes } from '@/utils/common'
import { clamp } from '../theme/utils'
import { toLocalTradingDate, type FormalSnapshotType } from '../snapshot/identity'
import { slotTimeToMinutes } from '../snapshot/schedule'
import { snapshotFacade } from '../snapshot/facade'
import type { SnapshotRecord, SnapshotStockRow } from '../snapshot/types'
import { getAshareVolumeClockMinute } from './VolumeRatioCalculator'

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
    const allowedCaptureModes: Array<'real_time' | 'delayed'> = ['real_time', 'delayed']
    const snapshotGroups = await Promise.all(
      this.intradaySnapshotTypes.map((type) =>
        snapshotFacade.listSnapshots({
          type,
          beforeTradingDate: anchorTradingDate,
          allowedCaptureModes,
          excludeRestored: true,
          sort: 'desc',
          limit: 120,
        }),
      ),
    )

    const selectedByDate = this.selectIntradayVolumeSnapshots(
      snapshotGroups.flat(),
      targetClockMinute,
    )
    const selectedEntries = Array.from(selectedByDate.values()).slice(0, 3)
    if (!selectedEntries.length) return new Map()

    const snapshotIds = selectedEntries.flatMap((entry) =>
      entry.next ? [entry.previous.id, entry.next.id] : [entry.previous.id],
    )
    const rowsBySnapshotId = await this.loadSnapshotRowsById(snapshotIds, targetCodes)
    const result = new Map<string, number[]>()

    for (const code of targetCodes) {
      const volumes: number[] = []
      selectedEntries.forEach((entry) => {
        const volume = this.interpolateSnapshotVolume(
          code,
          entry,
          rowsBySnapshotId,
          targetClockMinute,
        )
        if (volume !== undefined) volumes.push(volume)
      })
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

  private selectIntradayVolumeSnapshots(
    snapshots: SnapshotRecord[],
    targetClockMinute: number,
  ): Map<string, { previous: SnapshotRecord; next?: SnapshotRecord }> {
    const byDate = new Map<string, SnapshotRecord[]>()
    snapshots.forEach((snapshot) => {
      const tradingDate = snapshot.tradingDate
      if (!tradingDate || snapshot.slotTime === 'daily') return
      const list = byDate.get(tradingDate) || []
      list.push(snapshot)
      byDate.set(tradingDate, list)
    })

    const selected = new Map<string, { previous: SnapshotRecord; next?: SnapshotRecord }>()
    const dates = Array.from(byDate.keys()).sort((left, right) => right.localeCompare(left))

    for (const tradingDate of dates) {
      if (selected.size >= 3) break

      const records = byDate
        .get(tradingDate)!
        .slice()
        .sort((left, right) => slotTimeToMinutes(left.slotTime) - slotTimeToMinutes(right.slotTime))

      let previous: SnapshotRecord | undefined
      let next: SnapshotRecord | undefined
      for (const record of records) {
        const minute = slotTimeToMinutes(record.slotTime)
        if (minute < 0) continue
        if (minute <= targetClockMinute) previous = record
        if (minute >= targetClockMinute) {
          next = record
          break
        }
      }

      if (previous) {
        selected.set(tradingDate, {
          previous,
          next: next && next.id !== previous.id ? next : undefined,
        })
      }
    }

    return selected
  }

  private async loadSnapshotRowsById(
    snapshotIds: string[],
    codes: string[],
  ): Promise<Map<string, Map<string, SnapshotStockRow>>> {
    const rowsBySnapshotId = new Map<string, Map<string, SnapshotStockRow>>()
    const uniqueSnapshotIds = [...new Set(snapshotIds)]

    await Promise.all(
      uniqueSnapshotIds.map(async (snapshotId) => {
        const rows = await snapshotFacade.listSnapshotStockRows({ snapshotId, codes })
        const rowsByCode = new Map<string, SnapshotStockRow>()
        rows.forEach((row) => {
          if (row.code) rowsByCode.set(row.code, row)
        })
        rowsBySnapshotId.set(snapshotId, rowsByCode)
      }),
    )

    return rowsBySnapshotId
  }

  private interpolateSnapshotVolume(
    code: string,
    selected: { previous: SnapshotRecord; next?: SnapshotRecord },
    rowsBySnapshotId: Map<string, Map<string, SnapshotStockRow>>,
    targetClockMinute: number,
  ): number | undefined {
    const previousRow = rowsBySnapshotId.get(selected.previous.id)?.get(code)
    const previousVolume = Number(previousRow?.volume)
    if (!Number.isFinite(previousVolume) || previousVolume <= 0) return undefined

    if (!selected.next) return previousVolume

    const previousMinute = slotTimeToMinutes(selected.previous.slotTime)
    const nextMinute = slotTimeToMinutes(selected.next.slotTime)
    if (previousMinute < 0 || nextMinute <= previousMinute) return previousVolume

    const nextRow = rowsBySnapshotId.get(selected.next.id)?.get(code)
    const nextVolume = Number(nextRow?.volume)
    if (!Number.isFinite(nextVolume) || nextVolume < previousVolume) return previousVolume

    const progress = clamp(
      (targetClockMinute - previousMinute) / (nextMinute - previousMinute),
      0,
      1,
    )
    return previousVolume + (nextVolume - previousVolume) * progress
  }
}
