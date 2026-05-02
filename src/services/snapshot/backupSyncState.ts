import type { SnapshotBackupSyncState } from './types'

type SnapshotBackupSyncStateMap = Record<string, SnapshotBackupSyncState>
type BackupSyncErrorKind = 'bucket' | 'cloud'

interface SnapshotBackupSyncStateStoreOptions {
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
  storageKey: string
  maxTradingDates?: number
}

function isPositiveTimestamp(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0
}

function normalizeStateMap(raw: unknown): SnapshotBackupSyncStateMap {
  if (!raw || typeof raw !== 'object') return {}
  const input = raw as Record<string, unknown>
  const normalized: SnapshotBackupSyncStateMap = {}

  Object.entries(input).forEach(([tradingDate, value]) => {
    if (!tradingDate || typeof value !== 'object' || !value) return
    const entry = value as Record<string, unknown>
    normalized[tradingDate] = {
      tradingDate,
      ...(isPositiveTimestamp(entry.bucketSyncedAt) ? { bucketSyncedAt: entry.bucketSyncedAt } : {}),
      ...(isPositiveTimestamp(entry.cloudBundleUploadedAt)
        ? { cloudBundleUploadedAt: entry.cloudBundleUploadedAt }
        : {}),
      ...(typeof entry.lastError === 'string' && entry.lastError.trim()
        ? { lastError: entry.lastError.trim() }
        : {}),
    }
  })

  return normalized
}

function sortStatesDesc(states: SnapshotBackupSyncState[]): SnapshotBackupSyncState[] {
  return [...states].sort((left, right) => right.tradingDate.localeCompare(left.tradingDate))
}

// 这里只存“最近若干交易日”的轻状态，不存快照正文，也不存同步任务队列。
export class SnapshotBackupSyncStateStore {
  private readonly storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
  private readonly storageKey: string
  private readonly maxTradingDates: number

  constructor(options: SnapshotBackupSyncStateStoreOptions) {
    this.storage = options.storage
    this.storageKey = options.storageKey
    this.maxTradingDates = Math.max(1, Math.floor(options.maxTradingDates ?? 40))
  }

  // UI 展示只关心最近若干交易日，因此读出后统一按交易日倒序裁剪。
  list(limit?: number): SnapshotBackupSyncState[] {
    const states = sortStatesDesc(Object.values(this.readStateMap()))
    const effectiveLimit = Math.max(1, Math.floor(limit || states.length || 1))
    return states.slice(0, effectiveLimit)
  }

  get(tradingDate: string): SnapshotBackupSyncState | null {
    if (!tradingDate) return null
    return this.readStateMap()[tradingDate] || null
  }

  remove(tradingDate: string): void {
    if (!tradingDate || !this.storage) return
    const stateMap = this.readStateMap()
    if (!stateMap[tradingDate]) return
    delete stateMap[tradingDate]
    this.persistStateMap(stateMap)
  }

  getLatestCloudSyncedTradingDate(): string {
    return (
      this.list()
        .filter((item) => isPositiveTimestamp(item.cloudBundleUploadedAt))
        .at(0)?.tradingDate || ''
    )
  }

  // bucket 成功后只清 bucket 类错误，不应顺手覆盖 cloud 同步失败状态。
  markBucketSynced(tradingDate: string, syncedAt: number = Date.now()): SnapshotBackupSyncState {
    return this.upsert(tradingDate, (current) => ({
      ...current,
      bucketSyncedAt: syncedAt,
      lastError: this.clearErrorKind(current.lastError, 'bucket'),
    }))
  }

  // 云端 bundle 成功与本地 bucket 成功是两套状态，分别独立回写。
  markCloudBundleUploaded(tradingDate: string, uploadedAt: number = Date.now()): SnapshotBackupSyncState {
    return this.upsert(tradingDate, (current) => ({
      ...current,
      cloudBundleUploadedAt: uploadedAt,
      lastError: this.clearErrorKind(current.lastError, 'cloud'),
    }))
  }

  // lastError 采用 kind:message 形式，方便 UI 与诊断层区分 bucket/cloud 的失败来源。
  markError(kind: BackupSyncErrorKind, tradingDate: string, error: unknown): SnapshotBackupSyncState {
    const message =
      error instanceof Error ? error.message : typeof error === 'string' ? error : String(error || 'unknown_error')
    return this.upsert(tradingDate, (current) => ({
      ...current,
      lastError: `${kind}:${message}`,
    }))
  }

  private upsert(
    tradingDate: string,
    updater: (current: SnapshotBackupSyncState) => SnapshotBackupSyncState,
  ): SnapshotBackupSyncState {
    if (!tradingDate) {
      throw new Error('snapshot_backup_sync_state_requires_trading_date')
    }

    const stateMap = this.readStateMap()
    const current = stateMap[tradingDate] || { tradingDate }
    stateMap[tradingDate] = this.normalizeState(updater(current))
    this.persistStateMap(stateMap)
    return stateMap[tradingDate]
  }

  private normalizeState(state: SnapshotBackupSyncState): SnapshotBackupSyncState {
    return {
      tradingDate: state.tradingDate,
      ...(isPositiveTimestamp(state.bucketSyncedAt) ? { bucketSyncedAt: state.bucketSyncedAt } : {}),
      ...(isPositiveTimestamp(state.cloudBundleUploadedAt)
        ? { cloudBundleUploadedAt: state.cloudBundleUploadedAt }
        : {}),
      ...(typeof state.lastError === 'string' && state.lastError.trim()
        ? { lastError: state.lastError.trim() }
        : {}),
    }
  }

  private clearErrorKind(lastError: string | undefined, kind: BackupSyncErrorKind): string | undefined {
    if (!lastError || !lastError.startsWith(`${kind}:`)) return lastError
    return undefined
  }

  private readStateMap(): SnapshotBackupSyncStateMap {
    if (!this.storage) return {}
    try {
      const raw = this.storage.getItem(this.storageKey)
      if (!raw) return {}
      return normalizeStateMap(JSON.parse(raw))
    } catch {
      return {}
    }
  }

  private persistStateMap(stateMap: SnapshotBackupSyncStateMap): void {
    if (!this.storage) return
    // 轻状态只服务最近排障与 UI 展示，超过窗口的历史状态直接裁掉，避免 localStorage 膨胀。
    const sorted = sortStatesDesc(Object.values(stateMap)).slice(0, this.maxTradingDates)
    const normalized = Object.fromEntries(sorted.map((item) => [item.tradingDate, this.normalizeState(item)]))

    try {
      this.storage.setItem(this.storageKey, JSON.stringify(normalized))
    } catch {
      // ignore persistence failures
    }
  }
}
