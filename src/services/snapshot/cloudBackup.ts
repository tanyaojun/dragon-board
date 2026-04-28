import { apiService } from '../apiService'
import type {
  CloudBackupHealth,
  CloudBatchUploadResult,
  CloudDayBundleUploadResult,
  CloudManifestWindow,
  CloudUploadResult,
  SnapshotDayBundle,
  SnapshotRecord,
} from './types'

interface ApiEnvelope<T> {
  ok: boolean
  requestId?: string
  message?: string
  errorCode?: string
  data: T
  details?: unknown
}

// 云端备份只负责 HTTP 协议与错误归一，不承载交易日去重或恢复策略判断。
export class SnapshotCloudBackup {
  async uploadSnapshot(record: SnapshotRecord): Promise<CloudUploadResult> {
    return this.executeCloudRequest<CloudUploadResult>(
      () =>
        apiService.post<ApiEnvelope<CloudUploadResult>>('/api/snapshots/remote/upload', record, {
          context: 'unknown',
          priority: 'low',
          retries: 1,
          timeout: 30000,
          cache: false,
        }),
      'remote_upload_failed',
    )
  }

  async uploadBatch(records: SnapshotRecord[]): Promise<CloudBatchUploadResult> {
    return this.executeCloudRequest<CloudBatchUploadResult>(
      () =>
        apiService.post<ApiEnvelope<CloudBatchUploadResult>>('/api/snapshots/remote/upload-batch', { items: records }, {
          context: 'unknown',
          priority: 'low',
          retries: 1,
          timeout: 60000,
          cache: false,
        }),
      'remote_batch_upload_failed',
    )
  }

  async uploadDayBundle(bundle: SnapshotDayBundle): Promise<CloudDayBundleUploadResult> {
    return this.executeCloudRequest<CloudDayBundleUploadResult>(
      () =>
        apiService.post<ApiEnvelope<CloudDayBundleUploadResult>>(
          '/api/snapshots/remote/upload-day-bundle',
          bundle,
          {
            context: 'unknown',
            priority: 'low',
            retries: 1,
            timeout: 60000,
            cache: false,
          },
        ),
      'remote_day_bundle_upload_failed',
    )
  }

  async downloadDayBundle(tradingDate: string): Promise<SnapshotDayBundle | null> {
    return this.executeCloudRequest<SnapshotDayBundle | null>(
      () =>
        apiService.get<ApiEnvelope<SnapshotDayBundle | null>>(
          `/api/snapshots/remote/download-day-bundle/${encodeURIComponent(tradingDate)}`,
          {
            context: 'unknown',
            priority: 'low',
            retries: 1,
            timeout: 15000,
            cache: false,
          },
        ),
      'remote_day_bundle_download_failed',
    )
  }

  async listManifestWindow(params?: {
    startDate?: string
    endDate?: string
    type?: string
    limit?: number
    cursor?: string
  }): Promise<CloudManifestWindow> {
    const query = new URLSearchParams()
    if (params?.startDate) query.set('startDate', params.startDate)
    if (params?.endDate) query.set('endDate', params.endDate)
    if (params?.type) query.set('type', params.type)
    if (params?.limit) query.set('limit', String(params.limit))
    if (params?.cursor) query.set('cursor', params.cursor)
    const url = `/api/snapshots/remote/manifest${query.size > 0 ? `?${query.toString()}` : ''}`
    return this.executeCloudRequest<CloudManifestWindow>(
      () =>
        apiService.get<ApiEnvelope<CloudManifestWindow>>(url, {
          context: 'unknown',
          priority: 'low',
          retries: 1,
          timeout: 15000,
          cache: false,
        }),
      'remote_manifest_failed',
    )
  }

  async downloadSnapshot(id: string): Promise<SnapshotRecord | null> {
    return this.executeCloudRequest<SnapshotRecord | null>(
      () =>
        apiService.get<ApiEnvelope<SnapshotRecord | null>>(
          `/api/snapshots/remote/download/${encodeURIComponent(id)}`,
          {
            context: 'unknown',
            priority: 'low',
            retries: 1,
            timeout: 15000,
            cache: false,
          },
        ),
      'remote_download_failed',
    )
  }

  async getHealth(): Promise<CloudBackupHealth> {
    try {
      return await this.executeCloudRequest<CloudBackupHealth>(
        () =>
          apiService.get<ApiEnvelope<CloudBackupHealth>>('/api/snapshots/remote/health', {
            context: 'unknown',
            priority: 'low',
            retries: 0,
            timeout: 8000,
            cache: false,
            silent: true,
          }),
        'remote_health_failed',
      )
    } catch (error) {
      return {
        ok: false,
        enabled: false,
        message: error instanceof Error ? error.message : String(error),
      }
    }
  }

  private async executeCloudRequest<T>(
    request: () => Promise<ApiEnvelope<T>>,
    fallbackCode: string,
  ): Promise<T> {
    try {
      const response = await request()
      if (!response?.ok) {
        const message = [response?.errorCode, response?.message].filter(Boolean).join(':') || fallbackCode
        throw new Error(message)
      }
      return response.data
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error)
      // 代理层如果返回 HTML，一般意味着请求打到了错误页面或代理未启动，这里统一转成可诊断错误码。
      if (message.includes('Unexpected token') && message.includes('<!DOCTYPE')) {
        throw new Error(`${fallbackCode}:non_json_response_from_proxy`)
      }
      if (message === fallbackCode) {
        throw new Error(`${fallbackCode}:request_failed_without_detail`)
      }
      throw error instanceof Error ? error : new Error(message)
    }
  }
}
