# 快照备份架构

## 当前三层结构
快照备份当前只保留三层：

1. 主库 `DragonBoardData`
2. 本地 bucket 备份 `DragonBoardBucketBackup`
3. cloud day bundle

普通 IndexedDB 备份库 `DragonBoardDataBackup` 已退出正式链路，只保留遗留清理逻辑。

## 主库
主库保存：

- `snapshots`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `snapshot_projection_meta`

写入正式快照时，主库会按同一套 projection bundle 同步落地原始记录和读模型记录。

## 本地 bucket 备份
bucket 备份保存与主库一致的正式快照数据：

- `snapshots_backup`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`

bucket 是当前正式本地备份链，不再通过普通 IndexedDB 备份库兜底。

## cloud day bundle
cloud 端按交易日上传 bundle，当前口径是 `v4`：

- `items`
- `frames`
- `stockRows`
- `sectorRows`

恢复时优先直接恢复这些正式读模型数据；如果遇到旧 bundle，则先恢复 raw，再由本地维护入口重建 projection。

## 同步状态
同步状态使用 [backupSyncState.ts](/D:/dragon-board/src/services/snapshot/backupSyncState.ts) 的轻量 `localStorage` JSON 持久化，仅保留最近交易日窗口内的信息：

- `bucketSyncedAt`
- `cloudBundleUploadedAt`
- `lastError`

这部分不再建立额外 store，也不再回到 jobs 模式。

## 维护顺序
当前推荐维护顺序：

1. 重建 projection：`rebuildSnapshotProjectionStores`
2. 对齐备份：`alignSnapshotBackups`
3. 压缩 raw：`compactSnapshotRawRecords`
4. 再次对齐备份：`alignSnapshotBackups`

封装入口见 [runSnapshotStorageMaintenance](/D:/dragon-board/src/services/snapshot/runtime.ts)。

## 当前实现注意点
- 正式消费链默认只读 `real_time / delayed`。
- `restored/manual` 不进入正式分析结果。
- bucket/cloud 对齐应始终建立在主库 projection 已一致的前提下。
- 任何需要长期存在的导出、回放、诊断逻辑，都不应重新引入 `DragonBoardDataBackup` 这条普通备份链。
