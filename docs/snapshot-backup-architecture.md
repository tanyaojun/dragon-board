# 快照备份架构

## 当前结构
快照备份当前只保留两条正式链路：

1. 主库 `DragonBoardData`
2. 本地 bucket 备份 `DragonBoardBucketBackup`

普通 IndexedDB 备份库 `DragonBoardDataBackup` 已退出正式链路，只保留遗留清理逻辑。云端备份改由 QuantBoard SQLite outbox 同步到 Supabase 承接，不再由根前端在 15:30 打包 JSON 上传坚果云。

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

## 遗留 cloud day bundle
cloud day bundle 只保留为历史 JSON 恢复、手工迁移和兼容读取能力，不再作为正式自动备份链路。旧 bundle 口径是 `v4`：

- `items`
- `frames`
- `stockRows`
- `sectorRows`

当前代码仍保留旧实现文件用于历史对照，但代理服务默认不再挂载：

- `proxy-server/server.js` 不再注册 `/api/snapshots/remote/*`
- `proxy-server/snapshotRemoteRoutes.js` 是未挂载的遗留 WebDAV 实现，不属于正式运行链路
- `apiService.ts` 不再暴露 `upload-day-bundle`、manifest、health 或 download 方法
- 历史上传目录为 `bundles/by-date/{tradingDate}.json.gz`
- 读取顺序为 `bundles/by-date/{tradingDate}.json.gz` -> `bundles/by-date/{tradingDate}.json` -> `day-bundles/{tradingDate}.json`
- `day-bundles/{tradingDate}.json` 只作为旧路径读取兼容，不再写入
- `snapshots/` 是旧的单条快照目录，当前正式链路不再写入
- `manifests/` 是历史目录，当前代码不再使用

恢复时优先直接恢复这些正式读模型数据；如果遇到旧 bundle，则先恢复 raw，再由本地维护入口重建 projection。

## 同步状态
同步状态使用 [backupSyncState.ts](/D:/dragon-board/src/services/snapshot/backupSyncState.ts) 的轻量 `localStorage` JSON 持久化，仅保留最近交易日窗口内的信息：

- `bucketSyncedAt`
- `cloudBundleUploadedAt`（遗留字段，仅用于识别历史状态）
- `lastError`

这部分不再建立额外 store，也不再回到 jobs 模式。

## 自动同步策略
本地自动同步只执行一件事：

1. 把主库正式快照同步到 bucket

交易日 15:30 后不再尝试 cloud day bundle 上传。云端备份以 QuantBoard 后端写入 SQLite 后登记的 Supabase outbox 为准。

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
- bucket 对齐应始终建立在主库 projection 已一致的前提下。
- 任何需要长期存在的导出、回放、诊断逻辑，都不应重新引入 `DragonBoardDataBackup` 这条普通备份链。
