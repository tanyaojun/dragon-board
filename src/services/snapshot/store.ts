// IndexedDB snapshot store removed — formal persistence is MongoDB-only.
// This file provides stub no-op implementations to preserve API surface compatibility.
// Five-minute snapshots confirmed nonexistent in practice.

import type {
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotProjectionBundle,
  SnapshotProjectionMeta,
  SnapshotQueryOptions,
  SnapshotRecord,
  SnapshotSectorRowQueryOptions,
  SnapshotSectorRow,
  SnapshotStockRowQueryOptions,
  SnapshotStockRow,
  SnapshotStorageStats,
} from './types'

export const SNAPSHOT_FRAME_STORE_NAME = 'snapshot_frames'
export const SNAPSHOT_STOCK_ROW_STORE_NAME = 'snapshot_stock_rows'
export const SNAPSHOT_SECTOR_ROW_STORE_NAME = 'snapshot_sector_rows'
export const SNAPSHOT_PROJECTION_META_STORE_NAME = 'snapshot_projection_meta'

interface StubStoreConfig {
  dbName?: string
  dbVersion?: number
  storeName?: string
  snapshotStoreName?: string
  redundantStores?: string[]
  factoryProvider?: unknown
}

// ── SnapshotStore ──────────────────────────────────────────────

export class SnapshotStore {
  constructor(_config: StubStoreConfig) {
    // IndexedDB store removed — stub only
  }

  async put(_record: SnapshotRecord): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async getById(_id: string): Promise<SnapshotRecord | null> {
    return null
  }

  async getAll(): Promise<SnapshotRecord[]> {
    return []
  }

  async list(_options: SnapshotQueryOptions = {}): Promise<SnapshotRecord[]> {
    return []
  }

  async delete(_id: string): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async getStats(): Promise<SnapshotStorageStats> {
    return { totalSnapshots: 0, dates: [], estimatedSize: 0 }
  }
}

// ── replaceProjectionBundleRows ────────────────────────────────

export async function replaceProjectionBundleRows(
  _snapshotStore: unknown,
  _frameStore: unknown,
  _stockStore: unknown,
  _sectorStore: unknown,
  _bundles: SnapshotProjectionBundle[],
): Promise<void> {
  // no-op: IndexedDB storage removed
}

// ── Base class for projection stores ──────────────────────────

class ProjectionStoreBase {
  constructor(_config: StubStoreConfig) {
    // IndexedDB store removed — stub only
  }

  protected async openDB(): Promise<unknown> {
    throw new Error('IndexedDB snapshot store removed — use MongoDB backend')
  }
}

// ── SnapshotProjectionWriter ───────────────────────────────────

export class SnapshotProjectionWriter extends ProjectionStoreBase {
  async saveBundle(_bundle: SnapshotProjectionBundle): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async saveBundles(_bundles: SnapshotProjectionBundle[]): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async clearProjectionStores(): Promise<void> {
    // no-op: IndexedDB storage removed
  }
}

// ── SnapshotFrameStore ─────────────────────────────────────────

export class SnapshotFrameStore extends ProjectionStoreBase {
  async list(_options: SnapshotFrameQueryOptions = {}): Promise<SnapshotFrameRow[]> {
    return []
  }

  async getBySnapshotId(_snapshotId: string): Promise<SnapshotFrameRow | null> {
    return null
  }

  async deleteBySnapshotId(_snapshotId: string): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async clearAll(): Promise<void> {
    // no-op: IndexedDB storage removed
  }
}

// ── SnapshotStockRowStore ──────────────────────────────────────

export class SnapshotStockRowStore extends ProjectionStoreBase {
  async list(_options: SnapshotStockRowQueryOptions = {}): Promise<SnapshotStockRow[]> {
    return []
  }

  async countBySnapshotId(_snapshotId: string): Promise<number> {
    return 0
  }

  async deleteBySnapshotId(_snapshotId: string): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async clearAll(): Promise<void> {
    // no-op: IndexedDB storage removed
  }
}

// ── SnapshotSectorRowStore ─────────────────────────────────────

export class SnapshotSectorRowStore extends ProjectionStoreBase {
  async list(_options: SnapshotSectorRowQueryOptions = {}): Promise<SnapshotSectorRow[]> {
    return []
  }

  async countBySnapshotId(_snapshotId: string): Promise<number> {
    return 0
  }

  async deleteBySnapshotId(_snapshotId: string): Promise<void> {
    // no-op: IndexedDB storage removed
  }

  async clearAll(): Promise<void> {
    // no-op: IndexedDB storage removed
  }
}

// ── SnapshotProjectionMetaStore ────────────────────────────────

export class SnapshotProjectionMetaStore extends ProjectionStoreBase {
  async get(): Promise<SnapshotProjectionMeta | null> {
    return null
  }

  async put(_meta: SnapshotProjectionMeta): Promise<void> {
    // no-op: IndexedDB storage removed
  }
}
