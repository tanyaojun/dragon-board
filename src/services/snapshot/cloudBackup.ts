import { apiService, type ApiEnvelope } from '../apiService'
import type {
  CloudBackupHealth,
  CloudDayBundleUploadResult,
  CloudManifestWindow,
  SnapshotDayBundle,
} from './types'

// 云端备份只负责 HTTP 协议与错误归一，不承载交易日去重或恢复策略判断。
export class SnapshotCloudBackup {
  async uploadDayBundle(bundle: SnapshotDayBundle): Promise<CloudDayBundleUploadResult> {
    return this.executeCloudRequest<CloudDayBundleUploadResult>(
      () => apiService.uploadSnapshotRemoteDayBundle(bundle),
      'remote_day_bundle_upload_failed',
    )
  }

  async downloadDayBundle(tradingDate: string): Promise<SnapshotDayBundle | null> {
    return this.executeCloudRequest<SnapshotDayBundle | null>(
      () => apiService.downloadSnapshotRemoteDayBundle(tradingDate),
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
    return this.executeCloudRequest<CloudManifestWindow>(
      () => apiService.listSnapshotRemoteManifest(params),
      'remote_manifest_failed',
    )
  }

  async getHealth(): Promise<CloudBackupHealth> {
    try {
      return await this.executeCloudRequest<CloudBackupHealth>(
        () => apiService.getSnapshotRemoteHealth(),
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
