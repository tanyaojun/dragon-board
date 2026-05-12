# API 与 CLI 使用说明

QuantBoard API 和 CLI 共用同一套服务层。API 面向轻实验台和自动化脚本，CLI 面向本地批处理、调试和复现。

## API 响应口径

当前接口不是统一 `ok/data` 包装。成功时直接返回业务对象；失败时使用 HTTP `4xx/5xx`，FastAPI 在 `detail` 字段里返回错误信息。

前端和脚本应按 HTTP 状态判断失败，不要用 HTTP 200 + 空对象表示失败。

Dragon Board 前端调用 QuantBoard 快照 ingest 时会把 `503` 和其他 `5xx` 视为可重试错误；`4xx` 表示请求或数据合同错误，不做自动重试。

当前运行主库是 MongoDB。MongoDB 备份恢复、旧 SQLite/Supabase/Parquet 维护入口禁用清单和迁移验收见 [mongodb-migration-plan.md](mongodb-migration-plan.md)。本文保留的 SQLite/Supabase/Parquet API/CLI 段落属于迁移前历史合同；在 `QUANT_BOARD_STORAGE_BACKEND=mongodb` 下，这些旧维护入口应返回 410 或由 CLI 拒绝执行，不能作为当前生产链路。

## 数据集接口

### `GET /api/health`

健康检查。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

返回的 `database` 会报告 MongoDB 主库状态；`GET /api/health?deep=true` 还会做更完整的 MongoDB 连接和集合检查。旧 SQLite/Supabase 状态只属于迁移前模式，不是当前 MongoDB 生产健康判定。

- `primary.connected`：MongoDB 主库是否可用。
- `theme.connected`：MongoDB 题材集合是否可用。
- `mode`：当前应为 `mongodb_primary` 或等价 MongoDB 主库模式。
- `backup` / `archive`：仅表示 MongoDB dump/R2 备份相关状态；旧 Supabase 同构备份和 SQLite 归档状态不再作为生产健康条件。

目标合同：健康检查必须能让调用方判断 MongoDB 主库和 MongoDB 备份能力是否可用。新增或改名字段时，必须同批更新本文和 [mongodb-migration-plan.md](mongodb-migration-plan.md)。

## MongoDB 备份与旧维护入口状态

MongoDB 模式下：

- 快照、研究、题材和股票基础数据 API 通过 MongoDB repository 运行。
- `/api/storage/archive/*` 旧 SQLite/Parquet 归档接口返回 410。
- `/api/sync/*` 旧 Supabase 同步接口返回 410。
- `/api/migrations/snapshots/import-json` 返回 410；历史导入只允许走停服迁移脚本。
- CLI 旧 SQLite/Supabase/Parquet 命令拒绝执行；业务回测、优化、查询命令继续通过 MongoDB repository 运行。
- MongoDB 备份、校验、R2 上传和拉回恢复命令以 [mongodb-migration-plan.md](mongodb-migration-plan.md) 的当前实施状态为准。

## Parquet 归档与 DuckDB 查询

本节为迁移前 SQLite/Parquet 历史合同。MongoDB 模式下这些接口不再是生产链路。

### `POST /api/storage/archive/snapshots/preview`

预览快照明细归档，不写 Parquet，不清理 SQLite。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "beforeTradingDate": "2026-01-01",
  "maxPartitions": 5
}
```

### `POST /api/storage/archive/snapshots`

执行快照明细归档。成功写出 `records.parquet`、`frames.parquet`、`stock_rows.parquet`、`sector_rows.parquet` 和 `manifest.json`，并登记 `archive_manifests`。校验成功后只清理 SQLite 中对应 `dataset_id + snapshot_type + trading_date` 的 `snapshot_stock_rows` 和 `snapshot_sector_rows`；`snapshot_records` 和 `snapshot_frames` 保留。

CLI 等价命令：

```powershell
python -m backend.cli archive-snapshots --dataset-id dragonboard_live --snapshot-type half_hour --before-trading-date 2026-01-01 --dry-run
python -m backend.cli archive-snapshots --dataset-id dragonboard_live --snapshot-type half_hour --before-trading-date 2026-01-01 --apply
```

### `POST /api/storage/archive/research/preview`

预览回测研究明细归档。

### `POST /api/storage/archive/research`

执行回测研究明细归档。写出 `trades.parquet`、`equity_curve.parquet`、`signals.parquet` 和 `manifest.json`，保留 `backtest_runs` 和质量报告，校验后可清理 research SQLite 中的明细行。

CLI 等价命令：

```powershell
python -m backend.cli archive-research --older-than-days 30 --keep-latest-per-group 10 --dry-run
python -m backend.cli archive-research --older-than-days 30 --keep-latest-per-group 10 --apply
```

### `GET /api/storage/archive/manifests`

列出归档 manifest。可选 `scope=snapshots|research`。

### `POST /api/storage/archive/verify`

按 `archiveId` 严格校验本地归档。校验内容包括 DB manifest、本地 `manifest.json`、必要 Parquet 文件、sha256、字节数和行数。失败返回结构化错误，例如 `archive_file_missing`、`archive_sha256_mismatch`、`archive_row_count_mismatch`。

CLI 等价命令：

```powershell
python -m backend.cli verify-archive --archive-id <archive_id>
```

### `POST /api/storage/archive/restore`

按 `archiveId` 从本地 Parquet 恢复 SQLite 明细。

```json
{
  "archiveId": "snapshots_dragonboard_live_half_hour_2026-01-01",
  "apply": true
}
```

### `POST /api/storage/archive/auto-once`

手动执行一轮自动归档同口径任务。自动归档默认关闭，开启需配置 `QUANT_BOARD_ARCHIVE_AUTO_ENABLED=true`。

### `POST /api/storage/archive/smoke-object-backup`

R2/S3 对象备份探针。写入、读回并删除一个明确测试 object key。不会写 SQLite 业务数据。

### `POST /api/storage/archive/backup-snapshot-day`

把一个交易日的 SQLite 快照事实写成备份型 Parquet 并上传到 R2/S3。该入口用于 T+0/T+1 异地灾备，不删除 SQLite 明细，不写 `archive_manifests` 冷归档索引。未传 `trading_date` 时默认选择目标 `dataset_id/snapshot_type` 的最新交易日。

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/storage/archive/backup-snapshot-day?dry_run=true"
```

CLI 等价命令：

```powershell
python -m backend.cli backup-snapshot-day --dry-run
python -m backend.cli backup-snapshot-day
python -m backend.cli backup-snapshot-day --trading-date 2026-05-06
```

### `POST /api/storage/archive/push-backup`

把本地 verified 归档上传到 R2/S3。只上传允许的归档文件：`*.parquet`、`manifest.json` 和 `archive_index.jsonl`。上传成功后 manifest 更新为 `status=uploaded` 并记录 `object_key`；上传失败不影响本地 verified 状态。

CLI 等价命令：

```powershell
python -m backend.cli push-archive-backup --limit 50
```

### `POST /api/storage/archive/pull-backup`

按 `archiveId` 从 R2/S3 拉回归档。`dryRun=true` 只列出远端 key；`apply=true` 会下载到 staging，校验 sha256 成功后发布到本地归档目录。

CLI 等价命令：

```powershell
python -m backend.cli pull-archive-backup --archive-id <archive_id> --dry-run
python -m backend.cli pull-archive-backup --archive-id <archive_id> --apply
```

读取口径：`GET /api/snapshots/stock-rows`、`GET /api/snapshots/sector-rows`、`GET /api/backtests/{run_id}/trades`、`/equity`、`/signals` 在 SQLite 明细缺失且存在 verified/uploaded manifest 时，可通过 DuckDB 读取 Parquet，并返回 `source=parquet_archive` 或混合来源。前端不得传入 SQL。

### `POST /api/operations/after-market-once`

盘后生产编排入口。顺序固定为：

1. `backup-snapshot-day`
2. `archive-auto-once`
3. `push-archive-backup`
4. `prune-backup`

前一步失败会停止后续步骤并返回 `stoppedAt`。`dry_run=true` 不上传 R2，不删除 Supabase 云端行。

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/operations/after-market-once?archive_limit=5&backup_limit=20&dry_run=true"
```

CLI 等价命令：

```powershell
python -m backend.cli after-market-once --dry-run
python -m backend.cli after-market-once --archive-limit 5 --backup-limit 20
```

### `POST /api/sync/push-backup`

> MongoDB 模式下该旧 Supabase 同步入口返回 410；以下为迁移前历史合同。

把本地 SQLite 快照库中的数据集和快照事实推送到 Supabase 备份库。回测、优化、Golden 和报告属于 research SQLite，不进入 Supabase Free 版备份目标。

默认只补推 Supabase 保留窗口内的数据，避免 500MB 免费库重新写入全历史。需要一次性全量补推时显式传入 `full_history=true`，或 CLI 使用 `--full-history`。

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/sync/push-backup
```

返回包含 outbox 补偿结果和全量补推结果：

```json
{
  "ok": true,
  "direction": "push",
  "outbox": {
    "scanned": 0,
    "succeeded": 0,
    "failed": 0,
    "skipped": 0,
    "items": []
  },
  "datasets": { "scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0 },
  "snapshotBundles": { "scanned": 0, "succeeded": 0, "failed": 0, "skipped": 0 },
  "research": { "policy": "local_research_db_only" },
  "errors": []
}
```

`push-backup` 会先消费 `sync_outbox` 中到期的 `pending/retry` 任务，再按 Supabase 保留窗口补推 SQLite 快照库已有的数据集和快照事实。失败项会进入 `errors`，结构为 `{type,key,error}`。

### `POST /api/sync/prune-backup`

按 Supabase 保留策略清理云端备份库。默认只处理 `dragonboard_live`，保留最近 10 个交易日。该接口只删除 Supabase 云端行，不删除本地 SQLite。

```powershell
Invoke-RestMethod -Method Post "http://127.0.0.1:8000/api/sync/prune-backup?dry_run=true"
```

实现细节：Supabase REST 写入使用分片 upsert，分片同时受行数和请求体大小限制。outbox 只保存业务键和重试状态，不保存完整 records/frames/rows；补推时按 `dataset_id/snapshot_id` 从事实表实时组包。

### `POST /api/sync/push-outbox`

只推送到期的 outbox，不做全量历史扫描。适合自动同步和低风险补偿。

```powershell
Invoke-RestMethod -Method Post 'http://127.0.0.1:8000/api/sync/push-outbox?limit=50'
```

返回：

```json
{
  "scanned": 1,
  "succeeded": 1,
  "failed": 0,
  "skipped": 0,
  "items": []
}
```

### `POST /api/sync/auto-once`

手动执行一次自动同步同口径的 outbox 推送。

```powershell
Invoke-RestMethod -Method Post 'http://127.0.0.1:8000/api/sync/auto-once?limit=50'
```

### `POST /api/sync/smoke-backup`

Supabase 联调探针。后端会在云端同构 `sync_outbox` 表写入一条 `op_type=supabase_smoke` 临时记录，读回后删除，用来确认云端 REST 写读删权限。

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/sync/smoke-backup
```

返回：

```json
{
  "ok": true,
  "configured": true,
  "connected": true,
  "write": true,
  "read": true,
  "cleanup": true,
  "last_error": null
}
```

该探针要求 Supabase 已按 [../backend/data/supabase_schema.sql](../backend/data/supabase_schema.sql) 建好快照事实同构表；如果仍是旧 `snapshots.payload` 兼容 schema，会返回缺表或写入失败。

### `POST /api/sync/pull-backup`

把 Supabase 备份库中的 QuantBoard 备份记录拉回本地 SQLite。用于本地主库损坏、重建或后续 failover 写入能力落地后的数据收敛。

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/sync/pull-backup
```

当前返回包含 `ok`、`direction`、快照对象计数、`research.policy=local_research_db_only` 和 `errors`。目标合同还应报告恢复数量、跳过数量、冲突数量、失败数量和需要人工处理的业务键。

### `POST /api/snapshots/ingest`

Dragon Board 正式快照写入入口。前端提交 v4 snapshot bundle，当前正常路径写入 MongoDB。Vue 前端不得直连 MongoDB 或 Supabase，也不得携带数据库密钥。

```json
{
  "bundle": {
    "version": "v4",
    "tradingDate": "2026-04-23",
    "items": [],
    "frames": [],
    "stockRows": [],
    "sectorRows": []
  },
  "tradingDate": "2026-04-23",
  "idempotencyKey": "dragonboard:2026-04-23:half_hour:...",
  "source": "dragon_board_runtime"
}
```

返回：

```json
{
  "ok": true,
  "dataset": { "id": "dragonboard_runtime_2026-04-23" },
  "status": "done",
  "outbox": {
    "op_type": "snapshot_ingest",
    "status": "done",
    "idempotency_key": "dragonboard:2026-04-23:half_hour:..."
  },
  "deduped": false
}
```

同一 `idempotencyKey` 重放时返回 `deduped=true`，不会重复写入事实行。MongoDB 模式不再登记 Supabase outbox，也不通过 `push-backup` 补偿。

正式快照入库要求每个非 `five_minute` frame 至少有一条股票行。若 v4 bundle 中的 `items/records` 热榜为空，或显式 `stockRows` 缺失导致正式 frame 无股票行，接口返回 400，错误信息包含 `formal snapshot hotlist is empty`。历史导入数据中已经存在的空热榜快照仍由回测质量门禁和运行时过滤处理，不通过该正式写入口继续新增。

MongoDB 不可用时接口必须结构化失败，不回退 Supabase/SQLite 并返回 `backup_only`。

### `GET /api/snapshots/frames`

从 MongoDB 主库读取正式快照聚合帧，用于 Dragon Board 正式分析读取。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/frames?dataset_id=dragonboard_live&snapshot_type=half_hour&trading_date=2026-04-21'
```

常用查询参数：

- `dataset_id`：可选；缺省时优先 `dragonboard_live`，不存在时读取最新有 frame 的 MongoDB 数据集。
- `snapshot_type`：默认 `half_hour`。
- `trading_date` 或 `start_date/end_date`。
- `before_trading_date`。
- `allowed_capture_modes`：逗号分隔。
- `exclude_restored`。
- `sort=asc|desc`。
- `limit`。

返回 `dataset`、`frames`、`count`、`source=mongodb` 和 `cache`。`frames` 中每项包含 `rows/hotlist/sectors/hotThemes/rotationSummary`，供 Dragon Board `listSnapshotFrameBundles` 直接消费。正式快照不再把浏览器 IndexedDB 当事实读源；`five_minute` 浏览器本地入口也不再保留。

`frames`、`records`、`stock-rows` 和 `sector-rows` 列表读口可启用 Redis read-through cache。Redis 只缓存查询响应，不替代 MongoDB 事实源；命中时 `source` 仍表示原始事实来源，`cache.hit=true`、`cache.store=redis` 只用于诊断。Redis 不可用时读口直接回 MongoDB。

Dragon Board 根前端通过 `src/services/snapshot/backendRead.ts` 调用该接口。该适配层会默认带上
`dataset_id=dragonboard_live`、`allowed_capture_modes=real_time,delayed` 和
`exclude_restored=true`；QuantBoard 后端返回失败时，前端正式读取必须显式失败，不回落 IndexedDB。

### MongoDB 快照明细读口

这些接口承接 Dragon Board `DataLayer` 的正式快照读口，返回字段仍保持前端 camelCase 合同，不要求调用方理解 MongoDB 集合字段。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/records?dataset_id=dragonboard_live&snapshot_type=half_hour&limit=20'
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/records/half_hour%3A2026-04-21%3A10%3A00?dataset_id=dragonboard_live'
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/stock-rows?dataset_id=dragonboard_live&snapshot_id=half_hour%3A2026-04-21%3A10%3A00'
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/sector-rows?dataset_id=dragonboard_live&snapshot_id=half_hour%3A2026-04-21%3A10%3A00'
```

支持参数：

- 通用：`dataset_id`、`snapshot_type` 或 `types`、`trading_date`、`start_date/end_date`、`before_trading_date`、`allowed_capture_modes`、`exclude_restored`、`sort`、`limit`。
- 股票行：`snapshot_id`、`code`、`codes`、`slot_time`。
- 题材行：`snapshot_id`、`entity_type/entity_types`、`entity_key/entity_keys`。

Dragon Board `snapshotFacade.listSnapshots/getSnapshotById/listSnapshotFrames/listSnapshotStockRows/listSnapshotSectorRows/getStockVolumeHistory`
均通过这些 MongoDB 明细读口实现。列表读口返回 `cache` 诊断字段，单条 `records/{snapshot_id}` 仍直接读取 MongoDB。`getStockVolumeHistory` 固定读取 `daily` 的
`snapshot_stock_rows`，不再扫描浏览器 IndexedDB 原始快照。

### `GET /api/datasets`

返回数据集列表。

### `GET /api/datasets/{dataset_id}`

返回单个数据集详情。

### `DELETE /api/datasets/{dataset_id}`

删除 MongoDB 中的派生/测试数据集及其快照事实子集合行。

规则：

- 仅在 `QUANT_BOARD_STORAGE_BACKEND=mongodb` 下可用；非 MongoDB 模式返回 410。
- 禁止删除正式快照主库：`dragonboard_live` 或 `source_type=dragon_board_runtime` 返回 400。
- 删除范围只包含目标 dataset 的 `datasets`、`snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
- 不删除正式快照主库，不删除回测、优化、Golden、题材研究或 MongoDB 备份。

### `POST /api/datasets/import`

从 MongoDB 主库已有正式快照事实集合生成可复现研究视图。日常研究入口使用 `sourceType=mongodb_snapshots`；旧 `sqlite_snapshots` 只作为迁移前兼容口径。浏览器 IndexedDB/LevelDB/运行页桥接不再作为主采集方式。

常见请求：

```json
{
  "sourceType": "sqlite_snapshots",
  "sourceDatasetId": "dragonboard_live",
  "name": "2026-04 half_hour research",
  "snapshotTypes": ["half_hour"],
  "startDate": "2026-04-15",
  "endDate": "2026-04-30",
  "maxSnapshots": null,
  "dryRun": false
}
```

规则：

- `sourceDatasetId` 默认 `dragonboard_live`；迁移期如果该数据集不存在，后端可回退到最新有快照事实行的数据集。
- 接口不再把筛选后的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows` 复制到新的 `dataset_id`。返回对象使用源 `dataset_id`，并附带 `virtual=true`、`policy=snapshot_facts_view`，回测直接查询源快照事实表。
- 返回元数据中的 `metadata.filters` 记录快照类型、日期区间和最大快照数。
- `dryRun=true` 只返回会生成的数据集摘要和质量门禁结果，不落库。
- `mongodb_snapshots` 不产生新的快照事实复制。旧 `sqlite_snapshots` 只属于迁移前兼容口径，不产生新的 Supabase 备份对象。

旧兼容 `sourceType`：

- `json_bundle`
- `browser_bridge`
- `leveldb`

旧兼容来源只用于迁移或排障。MongoDB 切换后，历史 JSON、旧 IndexedDB 导出或备份文件不再通过在线 `import-json` 入口导入；需要补迁时应走 [mongodb-migration-plan.md](mongodb-migration-plan.md) 约定的停服迁移脚本。

MongoDB 模式下 `SUPABASE_URL` 和 `SUPABASE_SECRET_KEY` 不参与正式写入、读回退或 failover。MongoDB 不可用时，尚未完成的写入口必须明确返回不可用。

新增或修改导入请求字段、快照入库 payload、同步返回字段、错误结构时，必须同批更新 [mongodb-migration-plan.md](mongodb-migration-plan.md)。

### `POST /api/datasets/upload`

上传 JSON 内容并导入，供轻实验台文件上传使用。

### `POST /api/migrations/snapshots/import-json`

历史快照迁移入口。MongoDB 模式下该在线入口返回 410；旧 IndexedDB 导出、Dragon Board v4 bundle、结构化 frames/rows 或 SQLite/备份导出 JSON 需要补迁时，应走停服迁移脚本。

路径导入：

```powershell
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/migrations/snapshots/import-json `
  -ContentType 'application/json' `
  -Body (@{
    datasetId = 'dragonboard_history'
    sourcePath = 'd:/exports/dragonboard-v4.json'
    name = 'DragonBoard history'
    dryRun = $false
  } | ConvertTo-Json -Depth 20)
```

内联导入：

```json
{
  "datasetId": "dragonboard_history",
  "content": {
    "version": "v4",
    "items": []
  },
  "idempotencyKey": "migration:dragonboard_history:2026-04",
  "dryRun": true
}
```

返回：

### 快照 ingest 幂等口径

`POST /api/snapshots/ingest` 是 Dragon Board 正式快照写入 MongoDB 的入口。调用方应传入稳定的 `datasetId`、`idempotencyKey` 和 v4 `bundle`；后端会先按 `idempotencyKey` 判重，再按 `dataset_id + snapshot_id` 做逻辑幂等。若同一快照槽位已经存在，接口返回 `ok=true`、`deduped=true`，不会删除或覆盖已落库的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows`。

Dragon Board 当前会在写入前通过 MongoDB 后端读口确认同一 `snapshot_id` 是否已存在，避免定时保存反复提交同一槽位。IndexedDB 不再参与正式快照写入判重。

示例响应：

```json
{
  "ok": true,
  "deduped": true,
  "status": "pending",
  "dataset": { "id": "dragonboard_live" },
  "outbox": {
    "op_type": "snapshot_ingest",
    "status": "pending"
  }
}
```

```json
{
  "ok": true,
  "datasetId": "dragonboard_history",
  "deduped": false,
  "report": {
    "scanned": 2,
    "imported": 2,
    "skipped": 0,
    "errors": [],
    "dry_run": false
  }
}
```

`dryRun=true` 只解析和统计，不落库。同一 `idempotencyKey` 或已存在的 `dataset_id + snapshot_id` 会被跳过，重复执行不会制造重复快照。

## 题材基础数据接口

题材基础映射已经从 Dragon Board 浏览器 IndexedDB 和旧 `themeDATA.db` 迁移到 MongoDB 题材集合。这些接口只承载题材静态映射、题材-股票关系、股票-题材反查、标签和原因，不承载题材因子、轮动、预警、回测或快照事实。Dragon Board 运行时只读取 QuantBoard 后端接口；QuantBoard 不可用或返回空映射时，前端必须显式失败，不回落浏览器 IndexedDB、`/data/theme_base_mapping.json` 或 `/api/themes/batch`。

### `POST /api/migrations/themes/import-json`

历史题材映射迁移入口。MongoDB 模式下在线导入入口应返回 410；旧 `ThemeDataDB/theme_mapping` 或 `themeDATA.db` 只作为停服迁移源。

```json
{
  "version": "theme-v8",
  "lastUpdate": "2026-05-05T09:30:00.000Z",
  "totalThemes": 2,
  "themes": [
    {
      "id": "AI",
      "name": "人工智能",
      "zsCode": "BK0800",
      "stocks": ["000001", "600001"],
      "stockTags": {
        "000001": [{ "Name": "算力", "Reason": "服务器订单" }]
      },
      "stockReasons": {
        "000001": "算力龙头"
      }
    }
  ]
}
```

重复导入同一 payload 不会重复写入关系行；缺字段、空题材、非法股票代码会返回 `400`，`detail` 至少包含 `code`、`field`、`message`。

### `POST /api/migrations/themes/verify-json`

只读校验入口。用于把旧 `ThemeMappingData` JSON 或旧 `themeDATA.db` 与当前 MongoDB 题材集合做迁移验收，不写库、不自动修复。

返回字段固定包含：

- `ok`
- `expected`
- `actual`
- `mismatches`
- `missingThemes`
- `extraThemes`
- `missingMappings`
- `extraMappings`
- `source=mongodb`

缺字段、空题材、非法股票代码沿用导入接口的结构化 `400 detail`。

### `GET /api/themes/mapping`

Dragon Board `ThemeDataService` 的正式读口。返回结构兼容旧 `ThemeMappingData`，外层补充 `ok` 和 `source=mongodb`。`mapping.themes[*]` 必须包含当前库内已有的 `stocks`、`stockTags` 和 `stockReasons`，前端不再通过额外批量 API 补齐标签或原因。

### `GET /api/themes/stocks/{theme_id}`

按题材 ID 读取成分股。

### `GET /api/themes/stocks/by-code/{code}`

按股票代码读取所属题材、标签和原因。股票代码使用六位数字口径。

### `GET /api/themes/counts`

读取 MongoDB 题材基础集合行数，用于迁移验收和排障。返回 `ok`、`source=mongodb` 和 `counts`；`counts` 至少包含 `themeCount`、`mappingCount`、`stockCount`、`version`、`lastUpdate`、`source=mongodb`。

CLI 校验：

```powershell
.\.venv\Scripts\python.exe -m backend.cli verify-themes `
  --path data\staging\theme_mapping.json
```

CLI 输出与 `POST /api/migrations/themes/verify-json` 一致。

## Golden 接口

### `POST /api/golden/import`

导入 TypeScript 端导出的 TS Golden JSON。

```json
{
  "caseId": "rank_trend_default",
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "source": "ts_golden_import",
  "payload": {
    "signals": []
  }
}
```

`source=ts_golden_import` 才能作为正式跨语言验收。Python 自基线不是 TS Golden。

### `POST /api/golden/baseline`

把 Python 当前输出保存成临时自基线。

```json
{
  "caseId": "rank_trend_default",
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "sampleLimit": 100
}
```

用途是快速检查 Python 后续代码是否漂移，不能证明 TypeScript/Python 已经跨语言对齐。

### `POST /api/golden/validate`

校验 Python 当前输出和已保存 Golden。

```json
{
  "caseId": "rank_trend_default",
  "datasetId": "ds_xxx",
  "tolerance": 0.000001,
  "strict": true
}
```

返回字段重点：

- `passed`
- `source`
- `isFormalTsGolden`
- `checked`
- `issueCount`
- `issues`
- `expectedPreview`
- `actualPreview`

## 回测接口

### `POST /api/backtests/rank-trend`

运行 RankTrend 回测。

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "strategyName": "rank_trend_candidate",
  "randomSeed": 20260430,
  "initialCash": 1000000,
  "maxPositions": 5,
  "positionSize": 0.2,
  "executionMode": "current_bar",
  "targetHoldingDays": 5,
  "maxHoldingBars": 40,
  "takeProfitPct": 0.12,
  "stopLossPct": 0.06,
  "feeRate": 0.0003,
  "stampTaxRate": 0.0005,
  "slippageRate": 0.001,
  "useOrderBookPrice": true,
  "enforceLimitStatus": true,
  "enforceVolumeLimit": true,
  "enforceOrderBookQueue": true,
  "allowPartialFills": true,
  "volumeParticipationRate": 0.05,
  "orderBookParticipationRate": 0.3,
  "useIntrabarStops": true,
  "intrabarAmbiguity": "stop_first",
  "momentumPeriods": [3, 5, 8, 13, 21],
  "macdFast": 21,
  "macdSlow": 34,
  "macdSignal": 13
}
```

返回会包含 `runId`，并把完整结果落库到 `backtest_runs`。MongoDB 模式下完整结果写入 `resultCompressed` 可逆压缩字段，读取层透明还原；不裁剪 `backtest_runs` 中的回测结果。为避免真实数据集响应过大，接口默认只返回前 120 条 `signals` 预览，完整结果通过 `runId` 读取。报告会包含 `researchDiagnostics`，用于展示 1/2/5 bars 后验表现、市场环境和生命周期下的候选分层分布、展示状态分布及对照组表现；该字段只作为研究诊断，不会自动写回默认参数。

### `GET /api/backtests/{run_id}`

读取兼容回测报告。SQLite 模式读取 `backtest_runs.result_json`；MongoDB 模式读取 `backtest_runs.resultCompressed` 并透明解压，旧 `result` 子文档仅作为兼容字段。新页面需要完整交易、权益曲线、信号和质量报告时，应继续调用下列归一化结果端点。

### `GET /api/backtests/{run_id}/report`

读取回测报告，和 `GET /api/backtests/{run_id}` 同口径，供页面语义化调用。

### `DELETE /api/backtests/{run_id}`

删除单次历史回测及其归一化明细。MongoDB 模式下该操作只影响 MongoDB 研究集合，不会删除快照事实集合，也不会触发 Supabase `sync_outbox`。

删除顺序固定为：

1. `backtest_trades`
2. `backtest_equity_curve`
3. `backtest_signals`
4. `backtest_quality_reports`
5. `backtest_runs`

返回：

```json
{
  "ok": true,
  "runId": "bt_xxx",
  "deleted": {
    "backtest_trades": 3,
    "backtest_equity_curve": 40,
    "backtest_signals": 120,
    "backtest_quality_reports": 1,
    "backtest_runs": 1
  }
}
```

不存在的 `run_id` 返回 `404` 和 `code=backtest_run_not_found`。

### `GET /api/backtests/{run_id}/trades`

读取归一化交易明细，数据源为 MongoDB `backtest_trades` 集合，不从 `result` 摘要反解析。

查询参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `limit` | `100` | 每页条数，范围 `1..1000` |
| `offset` | `0` | 起始偏移，必须大于等于 `0` |

返回：

```json
{
  "runId": "bt_xxx",
  "items": [],
  "limit": 100,
  "offset": 0,
  "total": 0
}
```

### `GET /api/backtests/{run_id}/equity`

读取归一化权益曲线，数据源为 MongoDB `backtest_equity_curve` 集合。权益曲线用于图表，按时间升序全量返回，不分页。

```json
{
  "runId": "bt_xxx",
  "items": []
}
```

### `GET /api/backtests/{run_id}/signals`

读取归一化信号诊断，数据源为 MongoDB `backtest_signals` 集合。该端点用于解释候选分层、状态和过滤原因，不能代替 `backtest_trades` 展示真实成交。

查询参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `tier` | 空 | 可选候选分层筛选，例如 `A_MAIN` |
| `regime` | 空 | 可选市场状态筛选，例如 `advance` |
| `limit` | `200` | 每页条数，范围 `1..1000` |
| `offset` | `0` | 起始偏移，必须大于等于 `0` |

```json
{
  "runId": "bt_xxx",
  "items": [],
  "filters": {
    "tier": "A_MAIN",
    "regime": "advance"
  },
  "limit": 200,
  "offset": 0,
  "total": 0
}
```

### `GET /api/backtests/{run_id}/quality`

读取归一化质量报告，数据源为 MongoDB `backtest_quality_reports` 集合。

```json
{
  "runId": "bt_xxx",
  "qualityReport": {
    "passed": true,
    "severity": "pass",
    "researchGrade": "research_ready"
  }
}
```

### `POST /api/backtests/compare`

对比多个回测 run 的摘要指标。对比只读取服务层聚合结果，不要求调用方理解 repository 私有结构。

请求：

```json
{
  "run_ids": ["bt_001", "bt_002"],
  "metrics": ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
}
```

首批允许的 `metrics`：

```text
totalReturn
realizedReturn
maxDrawdown
sharpe
winRate
totalTrades
profitFactor
openPositionCount
```

响应：

```json
{
  "runs": [
    {
      "runId": "bt_001",
      "datasetId": "ds_001",
      "snapshotType": "half_hour",
      "strategyName": "rank_trend_candidate",
      "strategyVersion": "0.1.0",
      "configHash": "abc123",
      "randomSeed": 20260430,
      "metrics": {
        "totalReturn": 0.12,
        "maxDrawdown": -0.08,
        "sharpe": 1.4,
        "winRate": 0.52
      },
      "missingMetrics": []
    }
  ],
  "metrics": ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
}
```

找不到 run 返回 `404`，`detail.code=backtest_run_not_found`。非法分页参数返回 `400` 或 `422`，错误体至少包含 `code`、`field` 和 `value`。非法指标返回 `400`，`detail.code=invalid_backtest_metric`，并返回 `allowedMetrics`。旧 `result_json` 中缺失的指标用 `null`，同时在对应 run 的 `missingMetrics` 列出字段名，不能用 `0` 代替。

归一化回测结果属于 MongoDB 研究集合，`GET /api/backtests/{run_id}/trades`、`/equity`、`/signals`、`/quality` 和 `POST /api/backtests/compare` 都不读取 Supabase，也不触发 `sync_outbox`、push/pull 或 failover。

### V12 ThemeTrend 回测接口

以下接口是 V12 已落地的 ThemeTrend 研究回测合同。ThemeTrend 回测和共振回测结果属于 MongoDB 研究集合，不读取或写入 Supabase，不触发 `sync_outbox`、push/pull 或 failover；题材基础映射来自 MongoDB 题材集合。

当前实现会把题材暴露投影为可执行股票信号，复用现有 `TradeSimulator` 产出 `tradeSimulation`，并双写 `/api/backtests/{run_id}/trades`、`/equity`、`/signals`、`/quality`。完整报告归因、TS golden 严格对齐和 Dragon Board 面板级解释仍按 V12 后续项推进。

### `POST /api/backtests/theme-trend`

运行纯 ThemeTrend 题材趋势回测。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "strategyName": "theme_trend_candidate",
  "strategyVersion": "0.1.0",
  "randomSeed": 20260430,
  "lookbackBars": 8,
  "persistenceBars": 3,
  "breadthMinStocks": 5,
  "minThemeCoverage": 0.7,
  "maxThemeCrowding": 0.85,
  "initialCash": 1000000,
  "maxPositions": 5,
  "positionSize": 0.2
}
```

返回字段沿用 RankTrend 回测口径，至少包含 `runId`、`datasetId`、`snapshotType`、`strategyName`、`strategyVersion`、`configHash`、`randomSeed`、`metrics`、`qualityReport` 和 signals 预览。质量门禁失败时使用 HTTP `4xx` 或结构化失败详情，不能返回空成功报告。

### `POST /api/backtests/theme-confluence`

运行 RankTrend + ThemeTrend 共振回测。RankTrend 候选仍是交易候选主来源，ThemeTrend 只辅助排序、置信度、拥挤风险降级和解释。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "strategyName": "theme_confluence_candidate",
  "strategyVersion": "0.1.0",
  "randomSeed": 20260430,
  "rankTrendWeight": 0.65,
  "themeWeight": 0.35,
  "lookbackBars": 8,
  "persistenceBars": 3,
  "minThemeCoverage": 0.7,
  "maxThemeCrowding": 0.85,
  "initialCash": 1000000,
  "maxPositions": 5,
  "positionSize": 0.2
}
```

共振 signals 必须区分 `rankTrendSignal`、`themeTrendSignal`、`confluenceScore`、`riskFlags`、`quality` 和真实成交结果；不得把题材趋势分数当作唯一交易结论。

### `GET /api/storage/research-summary`

读取 MongoDB 研究集合的轻量统计，用于前端维护页或 CLI 对照。当前返回各研究集合文档数和回测创建时间范围。

### `POST /api/storage/research-cleanup-preview`

预览历史回测清理，不实际删除。请求字段：

| 字段 | 默认 | 说明 |
| --- | --- | --- |
| `olderThanDays` | `30` | 只匹配早于该天数的回测 |
| `keepLatestPerGroup` | `10` | 每个 `dataset/strategy/version/snapshot/config/seed` 分组至少保留最近 N 条 |
| `datasetId` | 空 | 可选，只清理某个数据集的研究结果 |
| `snapshotType` | 空 | 可选，`half_hour` 或 `quarter_hour` |
| `includeFailed` | `false` | 是否纳入非 completed 回测 |

### `POST /api/storage/research-cleanup`

执行历史回测清理。请求字段同 preview，但必须额外传入 `confirm=true`。该接口会显式删除回测归一化子表并执行 `PRAGMA wal_checkpoint(TRUNCATE)`；不会自动 `VACUUM`，避免在线前端操作长时间锁库。

## 优化接口

### `POST /api/optimizations/rank-trend`

启动异步参数优化任务。接口创建 `optimization_runs` 记录后立即返回 `status=running` 和 `runId`，完整结果通过 `GET /api/optimizations/{run_id}` 轮询读取。优化结果只生成候选参数，不会自动写回任何默认参数。

```json
{
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "strategyName": "rank_trend_candidate",
  "method": "bayesian",
  "objective": "stability",
  "trials": 36,
  "validationMode": "auto",
  "validationRatio": 0.3,
  "walkForward": {
    "enabled": true,
    "trainWindowDays": 5,
    "validationWindowDays": 1,
    "stepDays": 1,
    "topTrials": 5
  },
  "parameterGrid": {
    "momentumPeriods": [[3, 5, 8, 13, 21]],
    "takeProfitPct": [0.08, 0.12, 0.16],
    "stopLossPct": [0.04, 0.06, 0.08],
    "maxPositions": [3, 5, 8]
  }
}
```

返回：

```json
{
  "runId": "opt_xxx",
  "status": "running"
}
```

搜索方法：

| method | 说明 |
| --- | --- |
| `grid` | 穷举离散参数组合 |
| `random` | 固定 `randomSeed` 时可复现的随机采样 |
| `bayesian` | Optuna `GPSampler` 高斯过程优化 |
| `tpe` | Optuna `TPESampler` TPE 采样 |

`method=bayesian` 必须写入 `optimizer=optuna_gp` 和 `optimizerMeta.sampler=GPSampler`。TPE 采样口径使用 `method=tpe`，并写入 `optimizer=optuna_tpe`、`optimizerMeta.sampler=TPESampler`。后端仍接受历史请求里的 `method=optuna_tpe`，但它只是 `tpe` 的兼容别名，不作为新的搜索方法展示。

### `GET /api/optimizations/{run_id}`

读取优化任务状态和结果。

运行中：

```json
{
  "runId": "opt_xxx",
  "status": "running",
  "progress": {
    "completedTrials": 8,
    "totalTrials": 36
  }
}
```

完成：

```json
{
  "runId": "opt_xxx",
  "status": "completed",
  "result": {
    "best": {},
    "trials": []
  }
}
```

失败：

```json
{
  "runId": "opt_xxx",
  "status": "failed",
  "error": {
    "code": "OPTIMIZATION_FAILED",
    "message": "参数优化失败",
    "details": {}
  }
}
```

`status` 只能是 `running`、`completed` 或 `failed`。`failed` 必须返回结构化错误，不能用空 `trials` 或空 `best` 表示失败。

### V12 ThemeTrend 优化接口

以下接口是 V12 已落地的 ThemeTrend 优化合同。优化结果只生成候选参数，不自动写回 Python、TypeScript、API、CLI、前端表单或文档默认值。

### `POST /api/optimizations/theme-trend`

启动 ThemeTrend 参数优化任务。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "strategyName": "theme_trend_candidate",
  "strategyVersion": "0.1.0",
  "method": "bayesian",
  "objective": "stability",
  "trials": 36,
  "randomSeed": 20260430,
  "parameterGrid": {
    "lookbackBars": [5, 8, 13],
    "persistenceBars": [2, 3, 5],
    "breadthMinStocks": [3, 5, 8],
    "maxThemeCrowding": [0.75, 0.85, 0.92]
  }
}
```

### `POST /api/optimizations/theme-confluence`

启动 RankTrend + ThemeTrend 共振策略参数优化任务。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "strategyName": "theme_confluence_candidate",
  "strategyVersion": "0.1.0",
  "method": "bayesian",
  "objective": "stability",
  "trials": 36,
  "randomSeed": 20260430,
  "parameterGrid": {
    "rankTrendWeight": [0.55, 0.65, 0.75],
    "themeWeight": [0.25, 0.35, 0.45],
    "lookbackBars": [5, 8, 13],
    "maxThemeCrowding": [0.75, 0.85, 0.92]
  }
}
```

搜索方法沿用 `grid`、`random`、`bayesian`、`tpe`。返回和轮询口径沿用 `POST /api/optimizations/rank-trend` 与 `GET /api/optimizations/{run_id}`。

## CLI 命令

入口：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli <command>
```

### `import-idb`

导入数据集。

```powershell
.\.venv\Scripts\python.exe -m backend.cli import-idb `
  --source json_bundle `
  --path d:\path\to\snapshot-bundle.json `
  --name "2026-04 half_hour" `
  --snapshot-type half_hour
```

### `list-datasets`

列出数据集。

```powershell
.\.venv\Scripts\python.exe -m backend.cli list-datasets
```

### `run-ranktrend`

运行回测。

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --strategy-name rank_trend_candidate `
  --seed 20260430 `
  --initial-cash 1000000 `
  --max-positions 5 `
  --position-size 0.2 `
  --execution-mode next_bar `
  --target-holding-days 5 `
  --max-holding-bars 40 `
  --take-profit-pct 0.12 `
  --stop-loss-pct 0.06 `
  --fee-rate 0.0003 `
  --stamp-tax-rate 0.0005 `
  --slippage-rate 0.001 `
  --volume-participation-rate 0.05 `
  --order-book-participation-rate 0.3 `
  --intrabar-ambiguity stop_first `
  --macd-fast 21 `
  --macd-slow 34 `
  --macd-signal 13 `
  --momentum-periods 3,5,8,13,21
```

命令输出摘要应由后端服务层返回，至少包含：

```text
backtest_id: bt_xxx
config_hash: abc123
quality_status: pass|warn|fail
quality_coverage: 0.95
total_return: 0.234
max_drawdown: -0.12
sharpe: 1.45
trade_count: 67
win_rate: 0.52
```

### `compare-backtests`

对比多个回测 run：

```powershell
.\.venv\Scripts\python.exe -m backend.cli compare-backtests --run-ids bt_001 bt_002 bt_003
```

可通过 `--metrics totalReturn,sharpe,maxDrawdown,winRate` 显式指定指标；未指定时使用 API 合同里的首批默认指标。CLI 只负责参数解析和格式化输出，必须调用服务层的 compare 能力，不直连 repository。

### `export-report`

导出完整回测报告 JSON：

```powershell
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_001 --output quant-board\data\reports\bt_001.json
```

导出字段至少包括 `request`、`metrics`、`trades`、`equityCurve`、`signals`、`qualityReport`。`--output` 必须是用户显式传入的单个文件路径；如文件已存在，可以覆盖该明确文件，但不得批量清理或覆盖目录，并必须打印 `output` 路径。

```json
{
  "runId": "bt_001",
  "datasetId": "ds_001",
  "snapshotType": "half_hour",
  "strategyName": "rank_trend_candidate",
  "strategyVersion": "0.1.0",
  "configHash": "abc123",
  "randomSeed": 20260430,
  "request": {},
  "metrics": {},
  "trades": [],
  "equityCurve": [],
  "signals": [],
  "qualityReport": {},
  "exportedAt": "2026-05-04T00:00:00Z"
}
```

找不到 run 时返回非零退出码，并输出一行结构化错误摘要，例如：

```json
{"ok":false,"error":{"code":"backtest_run_not_found","runId":"bt_missing"}}
```

### `optimize-ranktrend`

运行参数优化。

```powershell
.\.venv\Scripts\python.exe -m backend.cli optimize-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --strategy-name rank_trend_candidate `
  --method bayesian `
  --objective stability `
  --validation-mode auto `
  --walk-forward `
  --trials 36 `
  --seed 20260430
```

`--method` 可选 `grid`、`random`、`bayesian`、`tpe`。`bayesian` 对应 Optuna `GPSampler` 高斯过程；`tpe` 对应 Optuna `TPESampler`。

默认 CLI 会等待任务完成并输出最终结果。需要只提交异步任务、拿到 `runId` 后立即返回时，加 `--no-wait`：

```powershell
.\.venv\Scripts\python.exe -m backend.cli optimize-ranktrend `
  --dataset-id ds_xxx `
  --snapshot-type half_hour `
  --method tpe `
  --objective stability `
  --trials 36 `
  --seed 20260430 `
  --no-wait
```

### V12 ThemeTrend CLI

这些命令已作为 V12 ThemeTrend 研究主链入口落地。命令必须复用后端服务层，不直连 repository，不在 Dragon Board 根项目实现回测。

运行纯 ThemeTrend 回测：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-theme-trend `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --strategy-name theme_trend_candidate `
  --seed 20260430 `
  --lookback-bars 8 `
  --persistence-bars 3 `
  --breadth-min-stocks 5 `
  --min-theme-coverage 0.7 `
  --max-theme-crowding 0.85
```

运行 RankTrend + ThemeTrend 共振回测：

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-theme-confluence `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --strategy-name theme_confluence_candidate `
  --seed 20260430 `
  --rank-trend-weight 0.65 `
  --theme-weight 0.35 `
  --lookback-bars 8 `
  --max-theme-crowding 0.85
```

优化纯 ThemeTrend：

```powershell
.\.venv\Scripts\python.exe -m backend.cli optimize-theme-trend `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --method random `
  --objective stability `
  --trials 36 `
  --seed 20260430
```

优化共振策略：

```powershell
.\.venv\Scripts\python.exe -m backend.cli optimize-theme-confluence `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --method random `
  --objective stability `
  --trials 36 `
  --seed 20260430
```

CLI 输出摘要至少包含：

```text
run_id: bt_xxx|opt_xxx
strategy_name: theme_rotation|leader_theme_confirmation|hotlist_theme_confluence
config_hash: abc123
quality_status: pass|warn|fail
theme_coverage: 0.82
sample_count: 120
total_return: 0.123
max_drawdown: -0.08
```

### `validate-golden`

校验 Golden。

```powershell
.\.venv\Scripts\python.exe -m backend.cli validate-golden `
  --case-id rank_trend_default `
  --tolerance 0.000001
```

### `show-report`

读取报告。

```powershell
.\.venv\Scripts\python.exe -m backend.cli show-report --run-id bt_xxx
```

### research 清理 CLI

查看 `quant_board_research.db` 的研究表行数：

```powershell
.\.venv\Scripts\python.exe -m backend.cli inspect-research-storage
```

删除单个历史回测 run 及其归一化子表：

```powershell
.\.venv\Scripts\python.exe -m backend.cli delete-backtest --run-id bt_xxx
```

预览历史回测清理，默认只匹配 30 天以前的 completed 回测，并按分组至少保留最近 10 条：

```powershell
.\.venv\Scripts\python.exe -m backend.cli cleanup-research --older-than-days 30
```

确认后执行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli cleanup-research --older-than-days 30 --apply
```

如果需要真正缩小 SQLite 文件体积，可在无人使用 QuantBoard 时显式追加 `--vacuum`。`VACUUM` 会锁库，因此不由前端删除按钮自动执行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli cleanup-research --older-than-days 30 --apply --vacuum
```

### 备份同步 CLI

CLI 与 API 复用同一服务层：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli smoke-backup
.\.venv\Scripts\python.exe -m backend.cli push-outbox --limit 50
.\.venv\Scripts\python.exe -m backend.cli push-backup
.\.venv\Scripts\python.exe -m backend.cli push-backup --full-history
.\.venv\Scripts\python.exe -m backend.cli prune-backup --dry-run
.\.venv\Scripts\python.exe -m backend.cli pull-backup
```

### 存储收敛 CLI

只读诊断 SQLite 文件体积、表行数和 JSON 字段占用：

```powershell
.\.venv\Scripts\python.exe -m backend.cli inspect-storage
```

拆分旧单库到双库，默认 dry run，不改动目标库：

```powershell
.\.venv\Scripts\python.exe -m backend.cli migrate-legacy-db `
  --source data\warehouse\quant_board.db
```

确认输出后显式执行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli migrate-legacy-db `
  --source data\warehouse\quant_board.db `
  --apply
```

压缩 SQLite 本地大 JSON 字段，默认 dry run；正式执行必须显式 `--apply`。`--vacuum` 只在用户明确传入时对目标数据库执行，不会批量清理文件。

```powershell
.\.venv\Scripts\python.exe -m backend.cli compact-json-fields
.\.venv\Scripts\python.exe -m backend.cli compact-json-fields --apply
```

历史快照迁移后可用 dry-run 报告核对四张事实表行数：

```powershell
.\.venv\Scripts\python.exe -m backend.cli verify-snapshot-migration `
  --dataset-id dragonboard_live `
  --source-report data\staging\migration-dry-run.json
```

历史迁移演练：

```powershell
.\.venv\Scripts\python.exe -m backend.cli migrate-snapshots `
  --path d:\exports\dragonboard-v4.json `
  --dataset-id dragonboard_history `
  --name "DragonBoard history" `
  --dry-run
```

确认 dry run 的 `report.scanned`、`frame_count`、`stock_row_count`、`start_date`、`end_date`、`snapshot_types` 后，去掉 `--dry-run` 正式导入。

## 默认参数边界

这里必须区分两套默认：

| 场景 | MACD 默认 | 说明 |
| --- | --- | --- |
| Python RankTrend 复刻 / Golden | `13/21/8` | 跟随 TypeScript `DEFAULT_RANK_TREND_RUNTIME_CONFIG` |
| QuantBoard 回测研究页 / API / CLI | `21/34/13` | 当前短线研究默认，MACD 只作为辅助观察 |

回测默认：

| 参数 | 默认 |
| --- | --- |
| `snapshotType` | `half_hour` |
| `strategyName` | `rank_trend_candidate` |
| `initialCash` | `1000000` |
| `maxPositions` | `5` |
| `positionSize` | `0.2` |
| `targetHoldingDays` | `5` |
| `maxHoldingBars` | `40` |
| `takeProfitPct` | `0.12` |
| `stopLossPct` | `0.06` |
| `executionMode` | `current_bar` |
| `randomSeed` | `20260430` |
| `tradeConfig.useThemeFactorForExecution` | `false` |

V12 ThemeTrend 默认：

| 参数 | 默认 |
| --- | --- |
| `snapshotType` | `half_hour` |
| `strategyName` | `theme_trend_candidate` |
| `confluenceStrategyName` | `theme_confluence_candidate` |
| `strategyVersion` | `0.1.0` |
| `randomSeed` | `20260430` |
| `lookbackBars` | `8` |
| `persistenceBars` | `3` |
| `breadthMinStocks` | `5` |
| `minThemeCoverage` | `0.7` |
| `maxThemeCrowding` | `0.85` |
| `themeWeight` | `0.35` |
| `rankTrendWeight` | `0.65` |

题材因子执行开关：

- API 请求可在 `tradeConfig` 中传 `useThemeFactorForExecution=true`。
- CLI 使用 `run-ranktrend --use-theme-factor-for-execution`。
- 默认关闭时，题材因子只进入候选解释和 `backtest_signals` 字段，不改变交易结果。
- 打开后，强题材支持可小幅提高置信度，高拥挤风险会把买入降级为观察。

## 验收清单

- API 和 CLI 走同一服务层。
- 默认快照是 `half_hour`。
- `quarter_hour` 必须显式传入。
- 回测和优化结果可通过 run id 重复读取。
- `config_hash` 必须包含最终 `strategy_config` 和 `trade_config`。
- Golden 正式验收必须使用 `source=ts_golden_import`。
- 存储、同步、快照入库、API/CLI 请求响应字段或错误结构变更时，必须同批更新相关文档。
