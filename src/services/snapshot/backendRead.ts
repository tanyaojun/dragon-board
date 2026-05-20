import { apiService } from '../apiService'
import { FORMAL_SNAPSHOT_READ_POLICY } from './readPolicy'
import { assertFormalSnapshotType, assertFormalSnapshotTypes } from './identity'
import type {
  SnapshotFrameBundle,
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotQueryOptions,
  SnapshotRecord,
  SnapshotSectorRow,
  SnapshotSectorRowQueryOptions,
  SnapshotStockRow,
  SnapshotStockRowQueryOptions,
} from './types'

const DEFAULT_DATASET_ID = 'dragonboard_live'
const STOCK_VOLUME_HISTORY_CANDIDATE_FACTOR = 4
const STOCK_VOLUME_HISTORY_MIN_CANDIDATES = 12
const STOCK_VOLUME_HISTORY_BATCH_SIZE = 50

type BackendReadOptions = { datasetId?: string }
type BackendSnapshotFrameBundle = SnapshotFrameBundle & { entities?: unknown }

function unwrapResponse<T>(response: any, key: string, fallback: T): T {
  const data = response && typeof response === 'object' && 'data' in response ? response.data : response
  if (!data?.ok) {
    const message =
      [data?.errorCode, data?.message].filter(Boolean).join(':') || 'snapshot_backend_read_failed'
    throw new Error(message)
  }
  return (data[key] ?? fallback) as T
}

function withFormalPolicy<T extends { allowedCaptureModes?: any; excludeRestored?: boolean; datasetId?: string }>(
  options: T = {} as T,
): T {
  return {
    ...options,
    datasetId: options.datasetId || DEFAULT_DATASET_ID,
    allowedCaptureModes: options.allowedCaptureModes?.length
      ? options.allowedCaptureModes
      : [...FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes],
    excludeRestored: options.excludeRestored ?? FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
  }
}

function rowVolume(row: SnapshotStockRow): number {
  const volume = Number(row.volume)
  return Number.isFinite(volume) ? volume : 0
}

export class SnapshotBackendRead {
  async listSnapshots(options: SnapshotQueryOptions & BackendReadOptions = {}): Promise<SnapshotRecord[]> {
    assertFormalSnapshotType(options.type)
    assertFormalSnapshotTypes(options.types)
    return unwrapResponse<SnapshotRecord[]>(
      await apiService.listMongoSnapshotRecords(withFormalPolicy(options)),
      'records',
      [],
    )
  }

  async getSnapshotById(id: string, options: BackendReadOptions = {}): Promise<SnapshotRecord | null> {
    return unwrapResponse<SnapshotRecord | null>(
      await apiService.getMongoSnapshotRecord(id, withFormalPolicy({
        datasetId: options.datasetId || DEFAULT_DATASET_ID,
      })),
      'record',
      null,
    )
  }

  async getTradingDateSnapshot(
    type: SnapshotQueryOptions['type'],
    tradingDate: string,
    options: BackendReadOptions = {},
  ): Promise<SnapshotRecord | null> {
    const snapshots = await this.listSnapshots({
      ...options,
      type,
      tradingDate,
      sort: 'desc',
      limit: 1,
    })
    return snapshots[0] || null
  }

  async listSnapshotFrames(
    options: SnapshotFrameQueryOptions & BackendReadOptions = {},
  ): Promise<SnapshotFrameRow[]> {
    const frames = await this.listSnapshotFrameBundles(options)
    return (frames as BackendSnapshotFrameBundle[]).map(
      ({
        rows: _rows,
        hotlist: _hotlist,
        entities: _entities,
        sectors: _sectors,
        hotThemes: _hotThemes,
        rotationSummary,
        ...frame
      }) => {
        const { mainLines: _mainLines, ...plainRotationSummary } =
          rotationSummary && typeof rotationSummary === 'object' ? rotationSummary : {}
        return {
          ...frame,
          rotationSummary: plainRotationSummary,
        }
      },
    )
  }

  async listSnapshotStockRows(
    options: SnapshotStockRowQueryOptions & BackendReadOptions = {},
  ): Promise<SnapshotStockRow[]> {
    return unwrapResponse<SnapshotStockRow[]>(
      await apiService.listMongoSnapshotStockRows(withFormalPolicy(options)),
      'rows',
      [],
    )
  }

  async listSnapshotSectorRows(
    options: SnapshotSectorRowQueryOptions & BackendReadOptions = {},
  ): Promise<SnapshotSectorRow[]> {
    return unwrapResponse<SnapshotSectorRow[]>(
      await apiService.listMongoSnapshotSectorRows(withFormalPolicy(options)),
      'rows',
      [],
    )
  }

  async listSnapshotFrameBundles(
    options: (SnapshotFrameQueryOptions | SnapshotQueryOptions) & BackendReadOptions = {},
  ): Promise<SnapshotFrameBundle[]> {
    assertFormalSnapshotType(options.type)
    assertFormalSnapshotTypes((options as SnapshotQueryOptions).types)
    const requestedTypes = Array.isArray((options as SnapshotFrameQueryOptions).types)
      ? (options as SnapshotFrameQueryOptions).types || []
      : []
    if (!options.type && requestedTypes.length > 0) {
      const merged = (
        await Promise.all(
          requestedTypes.map((type) => {
            const typedOptions = {
              ...options,
              type,
              types: undefined,
            } as SnapshotFrameQueryOptions & BackendReadOptions
            return this.listSnapshotFrameBundles(typedOptions)
          }),
        )
      ).flat()
      const sort = options.sort || 'asc'
      const sorted = merged.sort((left, right) =>
        sort === 'asc'
          ? Number(left.timestamp || 0) - Number(right.timestamp || 0)
          : Number(right.timestamp || 0) - Number(left.timestamp || 0),
      )
      return options.limit && options.limit > 0 ? sorted.slice(0, options.limit) : sorted
    }

    return unwrapResponse<SnapshotFrameBundle[]>(
      await apiService.listMongoSnapshotFrames(withFormalPolicy(options as SnapshotFrameQueryOptions & BackendReadOptions)),
      'frames',
      [],
    )
  }

  async getStockVolumeHistory(
    codes: string[],
    options?: { anchorTradingDate?: string; lookbackDays?: number },
  ): Promise<Map<string, number[]>> {
    const requestedCodes = Array.from(new Set((codes || []).filter(Boolean)))
    const result = new Map<string, number[]>()
    if (requestedCodes.length === 0) return result

    const lookbackDays = Math.max(1, Math.min(10, Number(options?.lookbackDays) || 3))
    const candidateLimit = Math.max(
      lookbackDays * STOCK_VOLUME_HISTORY_CANDIDATE_FACTOR,
      STOCK_VOLUME_HISTORY_MIN_CANDIDATES,
    )
    const loadRows = (params: { code?: string; codes?: string[]; limit: number }) =>
      this.listSnapshotStockRows({
        ...params,
        type: 'daily',
        beforeTradingDate: options?.anchorTradingDate,
        sort: 'desc',
      })
    const appendHistory = (rows: SnapshotStockRow[]) => {
      const historyByCode = new Map<string, Map<string, { volume: number; timestamp: number }>>()
      for (const row of rows || []) {
        const code = String(row.code || '')
        const tradingDate = String(row.tradingDate || '')
        const volume = rowVolume(row)
        if (!code || !tradingDate || volume <= 0) continue
        const byDate = historyByCode.get(code) || new Map<string, { volume: number; timestamp: number }>()
        const existing = byDate.get(tradingDate)
        const timestamp = Number(row.timestamp) || 0
        if (!existing || timestamp > existing.timestamp) {
          byDate.set(tradingDate, { volume, timestamp })
        }
        historyByCode.set(code, byDate)
      }

      historyByCode.forEach((volumesByDate, code) => {
        const volumes = Array.from(volumesByDate.entries())
          .sort(([leftDate, left], [rightDate, right]) => {
            const dateOrder = rightDate.localeCompare(leftDate)
            return dateOrder !== 0 ? dateOrder : right.timestamp - left.timestamp
          })
          .slice(0, lookbackDays)
          .map(([, item]) => item.volume)
        if (volumes.length > 0) {
          result.set(code, volumes)
        }
      })
    }

    const fallbackCodes: string[] = []
    for (let index = 0; index < requestedCodes.length; index += STOCK_VOLUME_HISTORY_BATCH_SIZE) {
      const chunk = requestedCodes.slice(index, index + STOCK_VOLUME_HISTORY_BATCH_SIZE)
      const batchLimit = candidateLimit * chunk.length
      const rows = await loadRows({ codes: chunk, limit: batchLimit })
      appendHistory(rows)
      if (rows.length >= batchLimit) {
        fallbackCodes.push(
          ...chunk.filter((code) => (result.get(code)?.length || 0) < lookbackDays),
        )
      }
    }

    for (let index = 0; index < fallbackCodes.length; index += STOCK_VOLUME_HISTORY_BATCH_SIZE) {
      const chunk = fallbackCodes.slice(index, index + STOCK_VOLUME_HISTORY_BATCH_SIZE)
      await Promise.all(
        chunk.map(async (code) => {
          const rows = await loadRows({ code, limit: candidateLimit })
          appendHistory(rows)
        }),
      )
    }

    return result
  }
}

export const snapshotBackendRead = new SnapshotBackendRead()
