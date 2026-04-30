import type { IndexedDbPreview, IndexedDbStorePreview } from "./types";

const DEFAULT_SAMPLE_LIMIT = 5;

function requestToPromise<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error("IndexedDB request failed"));
  });
}

function openDatabase(dbName: string): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error || new Error(`无法打开 IndexedDB: ${dbName}`));
    request.onupgradeneeded = () => {
      request.transaction?.abort();
      reject(new Error(`数据库 ${dbName} 不存在或版本不可读`));
    };
  });
}

async function readStorePreview(
  db: IDBDatabase,
  storeName: string,
  sampleLimit: number
): Promise<IndexedDbStorePreview> {
  const transaction = db.transaction(storeName, "readonly");
  const store = transaction.objectStore(storeName);
  const samples: unknown[] = [];

  const count = await requestToPromise(store.count());
  await new Promise<void>((resolve, reject) => {
    const cursorRequest = store.openCursor();

    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result;
      if (!cursor || samples.length >= sampleLimit) {
        resolve();
        return;
      }
      samples.push(cursor.value);
      cursor.continue();
    };

    cursorRequest.onerror = () => {
      reject(cursorRequest.error || new Error(`读取 ${storeName} 样本失败`));
    };
  });

  return {
    name: storeName,
    keyPath: store.keyPath,
    autoIncrement: store.autoIncrement,
    indexes: Array.from(store.indexNames),
    count,
    samples
  };
}

function looksLikeSnapshotRow(value: unknown): boolean {
  if (!value || typeof value !== "object") {
    return false;
  }
  const row = value as Record<string, unknown>;
  return Boolean(
    row.snapshotId ||
      row.snapshot_id ||
      row.tradingDate ||
      row.trading_date ||
      row.timestamp ||
      row.stocks ||
      row.sectors ||
      row.marketContext
  );
}

export async function inspectIndexedDb(
  dbName: string,
  sampleLimit = DEFAULT_SAMPLE_LIMIT
): Promise<IndexedDbPreview> {
  const db = await openDatabase(dbName);
  try {
    const stores = await Promise.all(
      Array.from(db.objectStoreNames).map((storeName) => readStorePreview(db, storeName, sampleLimit))
    );
    const snapshotLikeRows = stores.reduce((total, store) => {
      return total + store.samples.filter(looksLikeSnapshotRow).length;
    }, 0);

    return {
      dbName,
      version: db.version,
      stores,
      snapshotLikeRows,
      capturedAt: new Date().toISOString()
    };
  } finally {
    db.close();
  }
}

export function flattenIndexedDbSamples(preview: IndexedDbPreview | null): unknown[] {
  if (!preview) {
    return [];
  }
  return preview.stores.flatMap((store) =>
    store.samples.map((sample) => ({
      __store: store.name,
      ...((sample && typeof sample === "object" ? sample : { value: sample }) as Record<string, unknown>)
    }))
  );
}
