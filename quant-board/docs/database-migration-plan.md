# SQLite 热库、Parquet 冷归档与对象备份实施计划

本文是 QuantBoard 存储迁移、归档、备份同步的主计划。涉及 SQLite 主库、Parquet 归档、DuckDB 查询、R2/S3 对象备份、Supabase 兼容链、快照入库、同步接口、API/CLI 合同或相关配置的改动，必须先对齐本文，再同步更新 [architecture.md](architecture.md)、[api-cli.md](api-cli.md)、[development-roadmap.md](development-roadmap.md) 和 [AI_COLLABORATION.md](AI_COLLABORATION.md)。

## 目标结论

- SQLite 采用三库边界：`quant_board_snapshots.db` 是快照热库与元数据索引库，`quant_board_research.db` 是回测、优化、Golden 和报告研究热库，`themeDATA.db` 是题材静态映射主库。
- Parquet 是历史冷数据事实归档：历史 `snapshot_stock_rows`、`snapshot_sector_rows` 和回测 `trades/equity/signals` 可按 manifest 归档到 `data/archive/**`。
- DuckDB 是后端只读归档查询引擎，用于在 SQLite 明细已清理时读取 Parquet，不提供任意 SQL API，也不暴露给 Vue 前端直连。
- R2/S3 兼容对象存储是新的大体积异地备份主线，只上传 Parquet、`manifest.json` 和归档索引。
- Supabase 降级为后端专用轻量兼容备份库，只同步 `datasets`、快照事实表和轻量 `sync_outbox`，不再扩展为大明细或研究结果云端备份主线。
- Supabase 免费库只保留 `dragonboard_live` 最近 10 个交易日快照事实；完整历史以 SQLite、Parquet、DuckDB 和 R2/S3 对象备份为主线。
- 正常路径是先写 SQLite 快照事实库，提交成功后把同一份快照事实镜像到 Supabase。
- SQLite 不可用时，`POST /api/snapshots/ingest` 已可在 Supabase 配置可写时临时落备份库并返回 `status=backup_only`；其他关键写入仍按各服务层能力逐步纳入 M3。
- 读路径优先 SQLite；仅当 SQLite 不可用或本地缺失目标记录时，才尝试 Supabase 回退。
- 所有同步、回退、归档和恢复都必须保留快照事实的 `dataset_id`、`snapshot_id`、`snapshot_type` 和行级业务键；研究库继续保留 `strategy_version`、`config_hash`、`random_seed` 等可复现字段，研究明细进入 Parquet/R2，不进入 Supabase Free 备份目标。

## 非目标

- 不把 Supabase 作为前端直连数据库。
- 不把 Supabase 备份当作新的实时协作主库。
- 不把 R2/S3 对象存储作为前端直连数据源。
- 不提供用户可传入 SQL 的 DuckDB 查询接口。
- 不在 Dragon Board 根项目新增回测或优化职责。
- 不为了备份同步绕过数据质量门禁、Golden 校验或回测合同。
- 不自动把优化结果写回 Dragon Board 默认参数。

## 当前事实

QuantBoard 当前拆成两个 SQLite 库。旧单库 `quant_board.db` 只作为 legacy source 保留，用于拆分迁移，不再作为默认主库。

快照事实库 `quant_board_snapshots.db` 包括：

- `datasets`
- `snapshot_records`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `sync_outbox`
- `archive_manifests`

研究库 `quant_board_research.db` 包括：

- `golden_ranktrend_cases`
- `backtest_runs`
- `backtest_trades`
- `backtest_equity_curve`
- `backtest_signals`
- `backtest_quality_reports`
- `optimization_runs`

当前工作区曾在基线分支验证过 `payload_json` 相关 outbox 测试，但该结论不能代表 `main` 已完成全量旧库迁移；迁移验收必须以当前工作区 `inspect-storage` 和 `migrate-legacy-db --dry-run/--apply` 输出为准。

Supabase 备份库必须与快照事实库保持同构 schema。云端需要使用 [../backend/data/supabase_schema.sql](../backend/data/supabase_schema.sql) 重建为同名表、同业务键和同索引。脚本末尾会执行 `notify pgrst, 'reload schema'`，执行后仍应通过 `smoke-backup` 或 `/api/health?deep=true` 确认 PostgREST 已看到新表结构：

- `datasets`
- `snapshot_records`
- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`
- `sync_outbox`

旧的 Supabase `snapshots` / payload 兼容方案已经废弃。云端不再使用 `quality_flags.kind=qb_dataset`、`qb_snapshot_bundle` 等业务枚举，也不再把 QuantBoard 明细塞进 `snapshots.payload`。如果 Supabase 仍只有旧 `snapshots`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows` 四张非同构表，健康检查会报告缺失表，`push-backup` 不应视为可用。

Supabase schema 不再包含回测、优化和 Golden 表，也不再对研究 JSON 做云端压缩备份。`backtest_runs`、`backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports`、优化和 Golden 都是 research SQLite `local-only` 数据，大型研究结果留在本地研究库或报告文件目录，避免挤占 Supabase Free 版容量。

题材模块 V2 增加了快照事实库题材列：`snapshot_stock_rows` 保存 `theme_contribution/theme_role/theme_exposure_weight/theme_risk_flags_json`，`snapshot_sector_rows` 保存题材因子稳定列和 `theme_quality_flags_json`。这些字段属于快照事实合同，因此 SQLite 与 Supabase 同构 schema 必须同时更新；旧库通过 idempotent `ALTER TABLE ADD COLUMN` 兼容迁移。

研究库 `backtest_signals` 也增加题材解释列：`main_theme/theme_heat/theme_contribution/theme_role/theme_support_score/theme_risk_flags_json/theme_reasons_json`。研究库仍是 local-only，不进入 Supabase 备份链路。

题材模块 V8 新增独立题材主库 `themeDATA.db`，包含 `theme_metadata`、`themes`、`theme_stock_mappings`。该库只保存题材基础映射、题材-股票关系、股票-题材反查、标签和原因；不保存题材因子、轮动、预警、回测或快照事实。旧浏览器 `ThemeDataDB/theme_mapping` 只作为历史迁移源，正式读口固定为 `GET /api/themes/mapping`。V11 后 Dragon Board 运行时不再使用浏览器 IndexedDB、本地静态 JSON 或 `/api/themes/batch` 作为题材兜底事实源。

长期增长控制由 Parquet 归档承担：默认保留最近 90 个交易日的 SQLite 热数据，超过保留窗口的股票/板块明细可归档到 `quant-board/data/archive/snapshots/**`；回测 trades/equity/signals 可归档到 `quant-board/data/archive/research/**`。归档成功必须写入 `archive_manifests`，记录行数、sha256、字节数、本地路径、对象存储 key 和状态。归档校验失败时不得清理 SQLite 明细。

研究库历史回测清理属于本地维护动作，不属于 Supabase 备份、pull/push 或 failover 合同。`DELETE /api/backtests/{run_id}`、`POST /api/storage/research-cleanup` 和 CLI `cleanup-research` 只能删除 `quant_board_research.db` 中的回测结果表，不能删除 `quant_board_snapshots.db` 的正式快照事实，也不能登记 `sync_outbox`。删除单个回测时必须先显式删除 `backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports`，最后删除 `backtest_runs`。

在线清理后可执行 `PRAGMA wal_checkpoint(TRUNCATE)` 收敛 WAL；`VACUUM` 只允许 CLI 显式 `--vacuum`，避免前端 API 在用户使用期间长时间锁定 research SQLite。

当前 WP2/WP3/WP4 批次已落地的能力：

- `dataset_bundle`、`snapshot_ingest` 会在快照事实库写入成功后登记 `sync_outbox`；回测、优化和 Golden 只写 research 库，`sync_outbox` 不覆盖研究结果。
- Supabase 立即镜像成功时，对应 outbox 标记为 `done`；镜像失败时标记为 `retry` 并写入 `last_error`、`retry_count`、`next_retry_at`。
- `push-backup` 会先消费到期的 `pending/retry` outbox，再做全量扫描补推。
- Dragon Board 正式快照保存不再以 IndexedDB 是否已有记录作为幂等依据；定时保存和手工保存先查询 SQLite/QuantBoard 后端是否已有同一 `snapshot_id`，缺失时再执行 `POST /api/snapshots/ingest`。
- `POST /api/snapshots/ingest` 除 `idempotency_key` 外，还会按 `dataset_id + snapshot_id` 做逻辑幂等；同一快照槽位已存在时返回 `deduped=true`，不会覆盖已落库的事实行。
- Dragon Board 正式聚合读口已固定为 SQLite 唯一来源：`listSnapshotFrameBundles` 调用 QuantBoard `GET /api/snapshots/frames`，不再回落浏览器 IndexedDB。
- Dragon Board 正式零散读口已固定为 SQLite 唯一来源：`snapshotFacade.listSnapshots`、`getSnapshotById`、`listSnapshotFrames`、`listSnapshotStockRows`、`listSnapshotSectorRows` 通过根前端 `src/services/snapshot/backendRead.ts` 直接读 QuantBoard SQLite API，保持原快照字段合同不变；不再保留 `five_minute` 浏览器本地读取入口。
- Dragon Board 正式写入口已切为 SQLite 主写：正式快照保存必须先通过 `POST /api/snapshots/ingest` 落 SQLite；浏览器 IndexedDB 快照缓存默认关闭，后续只允许作为显式开启的临时缓存或历史迁移源。
- SQLite 主库完全不可用时，`POST /api/snapshots/ingest` 不再提前 503；后端会尝试把同一份 v4 bundle 直接镜像到 Supabase 同构表，成功时返回 `status=backup_only`、`outbox=null` 和 `failover` 诊断，待 SQLite 恢复后通过 `pull-backup` 收敛回主库。
- 历史 JSON 迁移入口 `POST /api/migrations/snapshots/import-json` 已可处理 v4 bundle、records/snapshots、frames/stockRows/sectorRows 和常见 SQLite/备份导出字段。

仍未完成的边界：

- failover 写入当前只覆盖正式快照 ingest、数据集 bundle；回测、优化和 Golden 属于本地 research 库，不进入 Supabase failover 目标。数据集导入、历史迁移 API 等仍依赖 SQLite 主库事务，主库不可用时必须明确失败。
- IndexedDB 已从正式快照读写链路中移除：后续只能作为显式缓存和历史迁移来源；`five_minute` 浏览器本地入口不再保留。完全删除历史或停用迁移工具前必须保留一次人工验收记录，确认 SQLite 四张事实表全量行数与浏览器历史一致。
- Dragon Board 正式读取不得在 QuantBoard 后端不可用时静默 fallback 到 IndexedDB；读取失败应暴露为后端/API 错误，由 UI 或诊断工具明确提示 SQLite 快照库不可用。
- Dragon Board 题材基础映射不再以 IndexedDB 作为事实源；`ThemeDataService` 只读取 QuantBoard `GET /api/themes/mapping`，旧 IndexedDB 只保留为离线导出迁移来源。QuantBoard 题材库不可用、返回空映射或结构异常时，前端必须显式失败，不回落 `/data/theme_base_mapping.json` 或 `/api/themes/batch`。
- Supabase 云端 schema 需要用户先在 SQL Editor 执行 `quant-board/backend/data/supabase_schema.sql`；执行前旧云端表会被删除重建，必须确认旧云端数据已经不需要或已另行备份。

## 存储拓扑

```text
Dragon Board 正式快照
  -> QuantBoard API/CLI
  -> SQLite snapshot hot primary
  -> Parquet archive
  -> DuckDB archive read fallback
  -> R2/S3 object backup
  -> Supabase lightweight compatibility backup

QuantBoard research
  -> SQLite research hot DB
  -> Parquet research archive
  -> DuckDB archive read fallback

Dragon Board theme mapping
  -> QuantBoard API
  -> SQLite themeDATA primary
```

职责边界：

- Dragon Board 负责实时看板、正式快照生成和 TypeScript golden 导出。
- QuantBoard API/CLI 负责导入、质量门禁、回测、优化、报告和同步编排。
- SQLite 快照库保存标准化后的近期热数据、frame/record 元数据和归档 manifest。
- SQLite research 库保存回测、优化、Golden、报告索引和近期研究明细。
- SQLite themeDATA 库保存题材静态映射和正反查基础事实。
- Parquet 保存历史冷明细，DuckDB 负责后端只读查询。
- R2/S3 保存大体积归档文件的异地备份。
- Supabase 只保留轻量兼容备份，不承担大体积归档或研究结果备份。

## 归档与对象备份合同

快照归档入口：

- `POST /api/storage/archive/snapshots/preview`
- `POST /api/storage/archive/snapshots`
- CLI `archive-snapshots`

研究归档入口：

- `POST /api/storage/archive/research/preview`
- `POST /api/storage/archive/research`
- CLI `archive-research`

恢复与校验入口：

- `GET /api/storage/archive/manifests`
- `POST /api/storage/archive/verify`
- `POST /api/storage/archive/restore`
- CLI `verify-archive`
- CLI `restore-archive`

自动归档默认关闭，由 `QUANT_BOARD_ARCHIVE_AUTO_ENABLED=true` 显式开启。自动归档每轮先 preview，单轮最多处理 `QUANT_BOARD_ARCHIVE_AUTO_MAX_PARTITIONS` 个分区，只归档早于最近 `QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS` 个交易日的数据。任何 manifest 冲突、Parquet 写入失败或校验失败都必须停止本轮，并且不得清理 SQLite 明细。

对象备份入口：

- `POST /api/storage/archive/smoke-object-backup`
- CLI `smoke-object-backup`
- `POST /api/storage/archive/backup-snapshot-day`
- CLI `backup-snapshot-day`
- `POST /api/operations/after-market-once`
- CLI `after-market-once`

R2/S3 凭据只允许后端读取，不得进入 `VITE_*` 或 Vue 前端构建产物。

生产盘后调度以 `after-market-once` 为单入口，顺序固定为最新交易日快照备份、本地 90 交易日冷归档、R2/S3 冷归档上传、Supabase 10 交易日清理。Windows 任务计划程序应调用该 CLI；后端常驻 runner 保留为显式开启的后台能力和 health 可观测入口。`after-market-once --dry-run` 不上传 R2，也不删除 Supabase 云端行。

每日备份型 Parquet 与冷归档 Parquet 必须区分：`backup-snapshot-day` 只做异地灾备，不删除 SQLite 明细，也不写 `archive_manifests` 冷归档索引；`archive-auto-once` 只处理超过 `QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS` 的历史明细，校验成功后才允许清理 SQLite 明细。

## 写入合同

正常写入顺序：

1. 校验请求、快照类型和质量门禁。
2. 写入 SQLite，并提交事务。
3. 在同一快照库事务中登记 `sync_outbox`，只保存 `op_type`、业务键、状态、错误和重试字段，不保存完整 payload。
4. 以同一业务对象构造 Supabase 备份记录。
5. Supabase 写入成功时将 outbox 标记为 `done`。
6. Supabase 写入失败时不得回滚已成功提交的 SQLite 业务事务，但必须将 outbox 标记为 `retry/failed` 并记录结构化同步诊断。

关键要求：

- SQLite 事务失败时，不得声明业务写入成功。
- Supabase 镜像失败不应阻塞本地研究主链，但必须可被 `push-backup` 后续补偿。
- 备份补推必须能按 `dataset_id/snapshot_id` 从事实表实时组包，不允许把完整 records/frames/rows 塞进 outbox。
- `sync_outbox` 只覆盖快照事实和数据集 bundle；回测归一化结果、优化结果和 Golden 结果是 `local_research_db_only`，不进入 Supabase push/pull/failover。
- `dataset_id`、`snapshot_type`、`run_id`、`case_id` 等业务键必须稳定，不能由恢复流程重新随机生成。
- 对同一业务键重复同步必须幂等，不能产生重复数据或覆盖更新更晚版本。

当前 `sync_outbox` 合同：

| 字段 | 说明 |
| --- | --- |
| `op_type` | 当前支持 `dataset_bundle`、`snapshot_ingest` |
| `idempotency_key` | 幂等键；Dragon Board ingest 使用前端/后端共同生成的业务键，数据集 bundle 使用对象键和事实摘要 hash 组合 |
| `status` | `pending`、`retry`、`done`、`failed` |
| `retry_count` | 失败重试次数；达到上限后进入 `failed` |
| `last_error` | 最近一次 Supabase 镜像失败原因 |
| `next_retry_at` | 下次允许 `push-backup` 消费该任务的时间 |

`list_pending_outbox` 只返回 `pending/retry` 且 `next_retry_at` 已到期的任务。

## 读取合同

读取优先级：

1. SQLite 主库。
2. Supabase 备份库回退。
3. 明确失败，返回结构化原因。

允许回退的场景：

- SQLite 初始化失败。
- SQLite 查询异常。
- SQLite 中缺失目标 `dataset_id`、`run_id` 或 `case_id`，但 Supabase 有对应备份记录。

禁止行为：

- 在 SQLite 有可用记录时静默返回 Supabase 旧记录。
- 用空列表、空报告或默认指标伪装读取成功。
- 前端直接读取 Supabase 密钥或 Supabase 表。

## 同步接口合同

### `POST /api/sync/push-backup`

用途：把 SQLite 快照库里已有的数据集和快照事实补推到 Supabase。

当前返回：

- `ok`：本次是否无错误完成。
- `direction=push`。
- `outbox`：`scanned`、`succeeded`、`failed`、`skipped`、`items`。
- `datasets`、`snapshotBundles`：每类对象都有 `scanned`、`succeeded`、`failed`、`skipped`。
- `research`：当前固定返回 `policy=local_research_db_only`。
- `errors`：结构为 `{type,key,error}`。

行为规则：

- 先消费到期 outbox，再按 Supabase retention 窗口补推 SQLite 快照事实；只有显式 `full_history=true` 或 CLI `--full-history` 才允许全量扫描补推。
- outbox 成功后标记 `done`；失败后更新 `retry_count`、`last_error` 和 `next_retry_at`。
- 不支持的 outbox 类型计入 `skipped`，不能静默丢弃。
- Supabase REST upsert 使用 `return=minimal`，并按行数和请求体大小双限制分片；研究库 JSON 不进入 Supabase。

### `POST /api/sync/push-outbox`

用途：只推送到期的 `sync_outbox` 任务，不做 SQLite 全量历史扫描。它是自动同步调度器使用的最小补偿动作。

行为规则：

- 只处理 `pending/retry` 且 `next_retry_at` 已到期的任务。
- 默认批量大小来自 `QUANT_BOARD_AUTO_SYNC_BATCH_SIZE`。
- 返回结构与 `push-backup.outbox` 一致。

### `POST /api/sync/auto-once`

用途：手动执行一次自动同步同口径的 outbox 推送，便于联调和排障。

### `POST /api/sync/smoke-backup`

用途：Supabase 联调写读删探针。后端会在云端 `sync_outbox` 写入一条 `op_type=supabase_smoke` 的临时记录，读回确认后删除。

行为规则：

- 只验证 Supabase REST 的写入、读取和清理权限。
- 不写入 SQLite，不登记业务 outbox。
- 返回 `write`、`read`、`cleanup` 和 `last_error`。
- 该探针依赖 Supabase 已按 `supabase_schema.sql` 建好同构 `sync_outbox` 表。

### `POST /api/sync/pull-backup`

用途：把 Supabase 备份记录恢复到 SQLite，用于本地主库损坏、重建或后续 failover 写入能力落地后的收敛。

必须返回：

- 拉取对象类型。
- 发现数量、恢复数量、跳过数量、冲突数量、失败数量。
- 冲突处理策略和业务键。
- 是否需要用户人工确认的不可自动合并项。

### `GET /api/health`

必须同时报告：

- SQLite 主库连接状态。
- Supabase 备份库连接状态。
- 当前存储模式，例如 `sqlite_primary_supabase_backup`。
- 备份回退是否启用。

默认 `GET /api/health` 使用快速路径，不发起 Supabase 网络请求，供前端频繁轮询。需要完整同构表和字段检查时调用 `GET /api/health?deep=true`；深检结果中的 `missing_or_unreadable_tables` 非空时，不能执行正式云端同步验收。

### `POST /api/snapshots/ingest`

用途：Dragon Board 正式快照后端入库入口。前端提交 v4 snapshot bundle，后端按 `dataset_id + snapshot_id + idempotency_key` 幂等写入 SQLite 并登记 Supabase 备份 outbox。

请求核心字段：

- `bundle`：Dragon Board v4 bundle，包含 `items/records`、`frames`、`stockRows`、`sectorRows`。
- `tradingDate`：交易日。
- `idempotencyKey`：可选；缺省时后端根据交易日、快照 ID 和来源生成。
- `source`：默认 `dragon_board_runtime`。

返回核心字段：

- `ok`
- `dataset`
- `status`：当前 outbox 状态；SQLite 不可用但 Supabase 写入成功时为 `backup_only`。
- `outbox`：SQLite 主写路径返回 outbox；`backup_only` 路径返回 `null`。
- `deduped`
- `failover`：仅 `backup_only` 路径返回，包含 `active/reason/idempotency_key/recovery`，提示 SQLite 恢复后执行 `pull-backup`。

### `GET /api/snapshots/frames`

用途：Dragon Board 和 QuantBoard 从 SQLite 主库读取正式快照聚合帧。该接口返回 frame + stock rows + sector rows 组合后的 bundle，是逐步替换 IndexedDB 正式读取的主接口。

查询字段：

- `dataset_id`：可选；缺省时后端优先使用 `dragonboard_live`，不存在时选择最新有 frame 的 SQLite 数据集，便于历史迁移期逐步替换 IndexedDB。
- `snapshot_type`：默认 `half_hour`。
- `trading_date`、`start_date`、`end_date`、`before_trading_date`。
- `allowed_capture_modes`：逗号分隔，例如 `real_time,delayed`。
- `exclude_restored`。
- `sort`：`asc` 或 `desc`。
- `limit`。

返回核心字段：

- `ok`
- `dataset`
- `datasetId`
- `snapshotType`
- `frames`
- `count`
- `source=sqlite`

Dragon Board 前端正式分析入口 `listSnapshotFrameBundles` 必须调用该接口；正式快照不再把 IndexedDB 当事实读源，`five_minute` 浏览器本地入口也不再保留。

### `GET /api/snapshots/records`

用途：从 SQLite 主库读取 `SnapshotRecord` 列表，承接 Dragon Board `DataLayer.listSnapshots`。

查询字段：

- `dataset_id`：可选；缺省解析规则同 `/api/snapshots/frames`。
- `snapshot_type` 或 `types`。
- `trading_date`、`start_date`、`end_date`、`before_trading_date`。
- `allowed_capture_modes`、`exclude_restored`。
- `sort=asc|desc`。
- `limit`。

返回 `records`，字段保持 Dragon Board `SnapshotRecord` 的 camelCase 合同，包括 `id/type/tradingDate/slotTime/timestamp/displayKey/captureMode/source/payload`。重构后 `payload` 固定为空对象；明细必须从 frame/stock/sector 行读取。

### `GET /api/snapshots/records/{snapshot_id}`

用途：从 SQLite 主库按快照 ID 读取单条 `SnapshotRecord`，承接 Dragon Board `DataLayer.getSnapshotById`。可选 `dataset_id` 用于限定数据集。

### `GET /api/snapshots/stock-rows`

用途：从 SQLite 主库读取正式股票投影行，承接 Dragon Board `DataLayer.listSnapshotStockRows`。

查询字段：

- `dataset_id`、`snapshot_id`。
- `snapshot_type` 或 `types`。
- `trading_date`、`start_date`、`end_date`、`before_trading_date`。
- `code` 或 `codes`。
- `slot_time`。
- `allowed_capture_modes`、`exclude_restored`。
- `sort=asc|desc`、`limit`。

返回 `rows`，字段保持 Dragon Board `SnapshotStockRow` 合同，不允许删除 DataLayer 现有字段。

### `GET /api/snapshots/sector-rows`

用途：从 SQLite 主库读取正式题材/主线投影行，承接 Dragon Board `DataLayer.listSnapshotSectorRows`。

查询字段：

- `dataset_id`、`snapshot_id`。
- `snapshot_type` 或 `types`。
- `trading_date`、`start_date`、`end_date`、`before_trading_date`。
- `entity_type/entity_types`、`entity_key/entity_keys`。
- `allowed_capture_modes`、`exclude_restored`。
- `sort=asc|desc`、`limit`。

`snapshot_sector_rows` 表已有独立 `capture_mode/source` 列；返回不再依赖 `payload_json` 还原。

### `GET /api/snapshots/counts`

用途：读取 SQLite 主库中 `snapshots/snapshot_frames/snapshot_stock_rows/snapshot_sector_rows` 四张事实表行数。可选 `dataset_id`。

### `POST /api/migrations/themes/import-json`

用途：把旧浏览器 `ThemeDataDB/theme_mapping` 导出的 `ThemeMappingData` JSON 幂等导入独立题材主库 `themeDATA.db`。

行为规则：

- 按 `theme_id + stock_code` 做关系幂等。
- 重复题材和重复股票代码会归一化后覆盖为单条关系。
- 缺失 `themes`、缺失题材 ID、缺失题材名称、非法股票代码返回结构化 `400`，`detail` 包含 `code/field/message`。
- 不写 `quant_board_snapshots.db`、`quant_board_research.db`、Supabase 或 outbox。

### `GET /api/themes/mapping`

用途：Dragon Board 题材模块读取正式题材基础映射。返回旧 `ThemeMappingData` 兼容结构，并带 `source=sqlite`。响应必须包含库内已有标签和原因，前端不再执行独立批量补齐。

### `GET /api/themes/stocks/{theme_id}` / `GET /api/themes/stocks/by-code/{code}` / `GET /api/themes/counts`

用途：题材-股票正查、股票-题材反查和迁移行数验收。`counts` 至少包含 `themeCount/mappingCount/stockCount/version/lastUpdate/source`。

### `POST /api/datasets/import`

用途：从 SQLite 主库已有正式快照事实表派生可复现研究数据集。该接口的主路径是 `sourceType=sqlite_snapshots`，不再承担日常浏览器 IndexedDB/LevelDB/运行页桥接采集职责。

请求核心字段：

- `sourceType=sqlite_snapshots`
- `sourceDatasetId`：源快照数据集，默认 `dragonboard_live`。
- `name`
- `snapshotTypes`
- `startDate/endDate`
- `maxSnapshots`
- `dryRun`

返回核心字段沿用 `DatasetSummary`，并在 `metadata` 中保留 `sourceDatasetId`、源数据集名称、筛选条件和质量门禁结果。

行为规则：

- 只复制筛选后的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows` 到新 `dataset_id`，不得删除或覆盖源事实表。
- 新数据集必须记录 `source_type=sqlite_snapshots`、`source_path=<sourceDatasetId>` 和稳定 `schema_fingerprint`。
- `dryRun=true` 不落库，不登记 outbox。
- 正式写入仍按 `dataset_bundle` 登记 `sync_outbox`，由 Supabase 备份链路补偿同步。
- `json_bundle/browser_bridge/leveldb` 只保留为迁移兼容来源；前端轻实验台默认不再展示为主入口。

### `POST /api/migrations/snapshots/import-json`

用途：把旧 IndexedDB 导出、Dragon Board v4 bundle、结构化 frames/rows 或 SQLite/备份导出 JSON 导入正式 SQLite 主库，并复用 `save_snapshot_ingest` 进入 outbox 同步链路。

请求核心字段：

- `datasetId`
- `sourcePath`，或 `content` / `bundle` / `payload`
- `idempotencyKey`
- `name`
- `source`
- `dryRun`

返回核心字段：

- `ok`
- `datasetId`
- `deduped`
- `dataset`
- `report.scanned`
- `report.imported`
- `report.skipped`
- `report.errors`
- `report.dry_run`

同一 `idempotencyKey` 且请求内所有 `snapshot_id` 都已存在时返回 `deduped=true`。如果迁移中断后重跑，同一 `idempotencyKey` 请求里仍有 SQLite 缺失的 `snapshot_id`，后端会为缺失部分派生内部幂等键继续补入，不会因为旧 outbox 记录直接跳过缺失快照。

重复迁移同一 `idempotencyKey` 或同一批已存在 `snapshot_id` 时，必须跳过已入库快照，不能制造重复事实行。

## 题材映射迁移校验

`themeDATA.db` 的题材映射迁移验收使用只读校验，不自动修复、不自动重新导入。

- API：`POST /api/migrations/themes/verify-json`
- CLI：`python -m backend.cli verify-themes --path <theme-json>`
- 校验源：旧 `ThemeMappingData` JSON。
- 校验目标：当前 `themeDATA.db` 中的 `themes` 与 `theme_stock_mappings`。
- 返回字段：`ok`、`expected`、`actual`、`mismatches`、`missingThemes`、`extraThemes`、`missingMappings`、`extraMappings`、`source=sqlite`。

校验和导入复用同一股票代码归一化规则：市场前缀会被剥离，股票代码补齐为六位数字；空题材、缺 `id/name`、非法股票代码返回结构化错误。

## 冲突和幂等规则

首期采用保守策略：

- 同一业务键、相同 `config_hash` 或相同 payload hash：视为已同步，跳过。
- 同一业务键、不同 payload hash：标记冲突，不自动覆盖。
- SQLite 已有记录且 Supabase 较旧：保留 SQLite，记录跳过原因。
- Supabase 有记录而 SQLite 缺失：恢复到 SQLite。
- 无法判断新旧时返回结构化冲突，由用户决定是否人工处理。

后续若引入版本号或更新时间戳作为自动合并依据，必须同步更新 API 返回字段和本文规则。

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `QUANT_BOARD_SNAPSHOT_DATABASE_URL` | SQLite 快照事实库连接串，默认指向 `quant-board/data/warehouse/quant_board_snapshots.db` |
| `QUANT_BOARD_RESEARCH_DATABASE_URL` | SQLite 研究库连接串，默认指向 `quant-board/data/warehouse/quant_board_research.db` |
| `QUANT_BOARD_THEME_DATABASE_URL` | SQLite 题材主库连接串，默认指向 `quant-board/data/warehouse/themeDATA.db` |
| `QUANT_BOARD_DATABASE_URL` | 旧兼容变量；如果指向 legacy `quant_board.db` 会被忽略，避免把双库主链静默切回旧单库 |
| `SUPABASE_URL` | Supabase 项目 URL |
| `SUPABASE_SECRET_KEY` | 后端专用密钥，禁止放入 `VITE_` 前端变量 |
| `QUANT_BOARD_ENABLE_SUPABASE_BACKUP` | 是否启用 Supabase 备份镜像，默认按 Supabase 配置自动启用 |
| `QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK` | 是否启用备份读回退，默认跟随备份镜像 |
| `QUANT_BOARD_BACKUP_TIMEOUT_SECONDS` | Supabase 请求超时时间 |
| `QUANT_BOARD_AUTO_SYNC_ENABLED` | 是否在 API 启动后自动推送到期 outbox，默认 `false` |
| `QUANT_BOARD_AUTO_SYNC_INTERVAL_SECONDS` | 自动 outbox 推送间隔，默认 `60`，最小 `5` |
| `QUANT_BOARD_AUTO_SYNC_INITIAL_DELAY_SECONDS` | API 启动后首次自动同步延迟，默认 `10` |
| `QUANT_BOARD_AUTO_SYNC_BATCH_SIZE` | 单轮自动同步最多处理多少条 outbox，默认 `50` |
| `QUANT_BOARD_SUPABASE_RETENTION_ENABLED` | 是否自动清理 Supabase 旧快照，默认 `false` |
| `QUANT_BOARD_SUPABASE_RETENTION_KEEP_TRADING_DAYS` | Supabase 保留交易日数，默认 `10` |
| `QUANT_BOARD_SUPABASE_RETENTION_DATASET_IDS` | Supabase retention 作用数据集，默认 `dragonboard_live` |
| `QUANT_BOARD_SUPABASE_RETENTION_INTERVAL_SECONDS` | Supabase retention 自动清理间隔，默认 `86400` |
| `QUANT_BOARD_SUPABASE_RETENTION_INITIAL_DELAY_SECONDS` | API 启动后首次 retention 延迟，默认 `120` |

自动同步默认关闭。打开后只消费到期 outbox，不做全量 `push-backup`，避免服务启动时把大量历史数据误推到 Supabase。全量补推仍必须手动调用 `push-backup` 或 CLI。

## 分阶段落地

### M0：文档和合同冻结

验收：

- 新增本文作为数据库迁移主计划。
- README、路线图、架构、API/CLI、AI 协作规范和根 AGENTS.md 都引用或同步本文规则。
- 文档明确存储、同步、快照、API/CLI 合同变更必须同批更新文档。

### M1：SQLite 主库合同收敛

验收：

- 所有导入、Golden、回测、优化写入都以 SQLite 为主链。
- 数据表字段能保留可复现所需关键字段。
- 空数据、NaN、缺字段、时间乱序和低样本量仍走质量门禁，不因备份机制降级。

### M2：Supabase 镜像写入

验收：

- 配置 Supabase 后，正式写入先落 SQLite，再镜像到 Supabase。
- Supabase 写入失败有结构化诊断。
- `push-backup` 能补偿历史 SQLite 记录。
- `sync_outbox` 已覆盖快照 ingest 和数据集 bundle；回测、优化和 Golden 业务对象保持 `local_research_db_only`，不进入 outbox 或 Supabase。
- 自动同步可按配置启动，只推送到期 outbox；Supabase smoke 探针可验证真实云端写读删。

### M3：读取回退与 failover 写入

验收：

- SQLite 读取失败或本地缺失目标记录时，能按业务键从 Supabase 回退。
- SQLite 不可用但 Supabase 可写时，正式快照 ingest 能临时落备份库并返回 `backup_only` 诊断；尚未纳入 failover 的写接口必须明确返回不可用，不能伪装成功。
- 恢复后 `pull-backup` 能把备份记录拉回 SQLite。

### M4：冲突诊断和恢复演练

验收：

- 同键同 hash 幂等跳过。
- 同键不同 hash 标记冲突，不自动覆盖。
- 有文档化的主库损坏恢复流程。
- 测试覆盖 push、pull、回退、冲突、Supabase 不可用和 SQLite 不可用。

## 验证清单

文档验收：

- [README.md](README.md) 索引包含本文。
- [development-roadmap.md](development-roadmap.md) 指向本文，不重复维护细节。
- [architecture.md](architecture.md) 的存储拓扑与本文一致。
- [api-cli.md](api-cli.md) 的同步接口字段与本文一致。
- [AI_COLLABORATION.md](AI_COLLABORATION.md) 明确合同改动必须同批更新文档。
- 根 [AGENTS.md](../../AGENTS.md) 明确跨项目协作规则。

代码验收：

- `quant-board` 目录下测试覆盖 SQLite 主库、Supabase 备份、读回退和恢复。
- API/CLI 对同一服务层行为一致。
- `SUPABASE_SECRET_KEY` 只在后端读取，不进入前端构建产物。
- 失败时返回结构化原因，不用空对象或空报告代表成功。

## 文档维护规则

以下任一改动必须同批更新相关文档：

- 存储拓扑、主备角色、读写优先级或 failover 规则。
- Supabase 表、`type` 枚举、payload 结构或恢复策略。
- SQLite 表字段、索引、业务键、唯一约束或迁移策略。
- 快照入库合同、快照类型默认值或质量门禁规则。
- API/CLI 请求字段、响应字段、错误结构或同步接口语义。
- 回测、优化、Golden 记录的可复现字段。

如果代码和文档不一致，后续协作者应先记录差异，再按任务范围修正文档或代码；不能静默扩大实现范围。
