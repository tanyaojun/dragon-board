import type {
  CloudBackupHealth,
  CloudDayBundleUploadResult,
  CloudManifestWindow,
  SnapshotDayBundle,
} from './types'

const DISABLED_MESSAGE = 'legacy_remote_snapshot_bundle_disabled'

// 坚果云 JSON day bundle 已退出正式链路；云端备份由 QuantBoard/Supabase outbox 承接。
export class SnapshotCloudBackup {
  async uploadDayBundle(bundle: SnapshotDayBundle): Promise<CloudDayBundleUploadResult> {
    throw new Error(`${DISABLED_MESSAGE}:${bundle.tradingDate}`)
  }

  async downloadDayBundle(tradingDate: string): Promise<SnapshotDayBundle | null> {
    throw new Error(`${DISABLED_MESSAGE}:${tradingDate}`)
  }

  async listManifestWindow(params?: {
    startDate?: string
    endDate?: string
    type?: string
    limit?: number
    cursor?: string
  }): Promise<CloudManifestWindow> {
    void params
    return { items: [], nextCursor: null }
  }

  async getHealth(): Promise<CloudBackupHealth> {
    return {
      ok: false,
      enabled: false,
      message: DISABLED_MESSAGE,
    }
  }
}
