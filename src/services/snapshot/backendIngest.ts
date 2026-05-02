import { apiService } from '../apiService'
import type { SnapshotDayBundle } from './types'

export interface SnapshotIngestResponse {
  ok: boolean
  dataset: Record<string, any>
  status: string
  deduped: boolean
  outbox: Record<string, any>
}

export class SnapshotBackendIngest {
  async ingestDayBundle(
    bundle: SnapshotDayBundle,
    options?: {
      datasetId?: string
      idempotencyKey?: string
    },
  ): Promise<SnapshotIngestResponse> {
    const response = await apiService.ingestSnapshotBundle(bundle, options)
    const data = response && typeof response === 'object' && 'data' in response ? (response as any).data : response
    if (!data?.ok) {
      const message =
        [data?.errorCode, data?.message].filter(Boolean).join(':') || 'snapshot_backend_ingest_failed'
      throw new Error(message)
    }
    return data as SnapshotIngestResponse
  }
}

export const snapshotBackendIngest = new SnapshotBackendIngest()
