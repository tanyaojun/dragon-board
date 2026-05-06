# Supabase 10 交易日保留与归档落地计划

## 目标

Supabase 不再承担完整历史快照库职责，只作为 `dragonboard_live` 最近 10 个交易日的轻量灾备。完整历史主线固定为：

```text
SQLite 热库 -> Parquet 冷归档 -> DuckDB 后端只读查询 -> R2/S3 对象备份
```

本地 SQLite 和 Parquet 归档不因 Supabase 容量限制而降级数据完整性。

## 近期 Supabase 策略

- 默认只处理 `dataset_id=dragonboard_live`。
- 默认保留最近 `10` 个交易日，不按自然日清理。
- 清理范围只在云端 Supabase：`snapshot_sector_rows`、`snapshot_stock_rows`、`snapshot_frames`、`snapshot_records` 和 `sync_outbox`。
- 清理后刷新云端 `datasets` 的快照数量、行数、起止日期和快照类型。
- 本地 `quant_board_snapshots.db` 不因该任务删除任何数据。

## 运维命令

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli prune-backup --dry-run
.\.venv\Scripts\python.exe -m backend.cli prune-backup
```

`push-backup` 默认只补推 Supabase 保留窗口内数据，避免重新写入全历史：

```powershell
.\.venv\Scripts\python.exe -m backend.cli push-backup
```

只有明确需要一次性全量补推时才使用：

```powershell
.\.venv\Scripts\python.exe -m backend.cli push-backup --full-history
```

## 自动任务配置

```text
QUANT_BOARD_SUPABASE_RETENTION_ENABLED=false
QUANT_BOARD_SUPABASE_RETENTION_KEEP_TRADING_DAYS=10
QUANT_BOARD_SUPABASE_RETENTION_DATASET_IDS=dragonboard_live
QUANT_BOARD_SUPABASE_RETENTION_INTERVAL_SECONDS=86400
QUANT_BOARD_SUPABASE_RETENTION_INITIAL_DELAY_SECONDS=120
```

推荐盘后顺序：

1. `archive-auto-once`：归档本地超保留期明细到 Parquet。
2. `push-archive-backup`：上传 verified 归档到 R2/S3。
3. `prune-backup`：清理 Supabase，只保留最近 10 个交易日。

## 验收

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_backup_retention.py tests/test_quant_board.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_archive_snapshots.py tests/test_duckdb_archive_query.py tests/test_object_backup.py -q
```

配置真实 R2 凭据后再执行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli smoke-object-backup
.\.venv\Scripts\python.exe -m backend.cli push-archive-backup --limit 1
.\.venv\Scripts\python.exe -m backend.cli pull-archive-backup --archive-id <archive_id> --dry-run
```
