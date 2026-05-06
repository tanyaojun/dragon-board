# SQLite + Parquet + DuckDB + R2 收口实施计划

> **给 agentic worker 的要求：** 执行本计划时必须使用 `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans`，按任务逐项实施。任务步骤使用 checkbox（`- [ ]`）格式，便于跟踪进度。

**目标：** 补齐 SQLite 热库、Parquet 冷归档、DuckDB 查询、自动归档和 R2 对象备份方案中剩余的生产可用性缺口。

**架构：** SQLite 继续作为事务型热库和元数据源。Parquet 作为不可变的冷明细归档，DuckDB 只作为后端只读查询引擎，R2/S3 对象存储作为异步备份目标。所有删除必须是明确条件的 SQLite 行级删除，或单个明确文件路径删除；不允许递归删除目录。

**技术栈：** FastAPI、SQLAlchemy、SQLite、PyArrow Parquet、DuckDB、boto3 兼容 S3/R2、pytest。

---

## 当前基线

计划启动前，在 `quant-board` 目录运行 `.\.venv\Scripts\python.exe -m pytest`，结果为 `134 passed`。执行完成后的最终验证结果记录在本文末尾。

已落地的基线：

- 归档配置和依赖已经加入。
- `archive_manifests` 表已经存在。
- 快照和研究回测的 Parquet 归档服务已经存在。
- DuckDB 已经支持部分快照明细和部分回测明细的归档 fallback。
- 自动归档 runner 和 `auto-once` 已经存在。
- 对象备份 smoke、push、pull 的基础骨架已经存在。
- 文档已经部分同步。

本轮已收口的缺口：

- 已移除归档生产代码和测试中的递归目录删除用法，并增加扫描测试防止回归。
- `verify-archive` 已形成 manifest、必要文件、sha256、字节数和行数校验合同。
- 自动归档已改为写归档、校验通过后才删除 SQLite 明细行。
- R2/S3 备份已支持 `archive_index.jsonl` 上传、allowlist、push/pull、dry-run 和 sha256 mismatch 状态。
- 研究回测归档候选已按 `(dataset_id, strategy_name, snapshot_type, strategy_version, config_hash, random_seed)` 分组保留最新 N 个 run。
- DuckDB 查询已补充 allowlist 过滤和结构化错误。

仍需人工验收：

- 真实 Cloudflare R2 环境的 `smoke-object-backup`、`push-archive-backup`、`pull-archive-backup --dry-run` 需要在配置好真实凭据后执行。

## 文件地图

- 修改 `quant-board/backend/data/archive/service.py`
  - 移除递归目录删除。
  - 增加严格归档校验。
  - 加固 restore、pull 和 hash conflict 行为。
  - 收紧研究回测归档候选选择。
- 修改 `quant-board/backend/data/archive/object_store.py`
  - 增加 `archive_index.jsonl` 上传支持。
  - 限制上传和下载文件为允许的归档文件名。
  - 返回结构化备份错误。
- 修改 `quant-board/backend/data/archive/auto_archive.py`
  - 增加显式预检、失败门禁、last_result 和 last_error 语义。
- 修改 `quant-board/backend/data/archive/duckdb_query.py`
  - 强制允许字段过滤，返回结构化查询错误。
- 修改 `quant-board/backend/data/repository.py`
  - 收口快照明细 `source` 标记和 mixed 范围查询行为。
- 修改 `quant-board/backend/services.py`
  - 收口研究回测明细 `source` 标记和分页 fallback 行为。
- 修改 `quant-board/backend/main.py`
  - 统一归档 API 响应和 health 中的归档状态。
- 修改 `quant-board/backend/cli.py`
  - 确保归档 CLI 与 API 行为一致。
- 修改测试：
  - `quant-board/tests/test_archive_snapshots.py`
  - `quant-board/tests/test_archive_research.py`
  - `quant-board/tests/test_duckdb_archive_query.py`
  - `quant-board/tests/test_auto_archive.py`
  - `quant-board/tests/test_object_backup.py`
  - `quant-board/tests/test_quant_board.py`
- 修改文档：
  - `quant-board/docs/database-migration-plan.md`
  - `quant-board/docs/architecture.md`
  - `quant-board/docs/api-cli.md`
  - `quant-board/docs/AI_COLLABORATION.md`
  - `docs/snapshot-storage-readme.md`

---

## 里程碑 1：合规与归档安全

**验收标准：** 归档实现和测试中不再使用递归目录删除。归档覆盖写入和冲突清理只能逐个删除已知文件，或写入新的 staging 目录并保留旧文件不动。

### 任务 1：移除归档服务中的递归目录删除

**文件：**

- 修改：`quant-board/backend/data/archive/service.py`
- 测试：`quant-board/tests/test_archive_snapshots.py`
- 测试：`quant-board/tests/test_object_backup.py`

- [ ] 增加一个测试，扫描归档源码和测试文件中是否存在被禁止的递归删除字符串。

运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_archive_snapshots.py::test_archive_code_does_not_use_recursive_delete -q
```

修复前预期：只要 `shutil.rmtree` 仍存在，该测试失败。

- [ ] 在 `service.py` 中增加辅助函数：

```python
ALLOWED_ARCHIVE_FILENAMES = {
    "records.parquet",
    "frames.parquet",
    "stock_rows.parquet",
    "sector_rows.parquet",
    "trades.parquet",
    "equity_curve.parquet",
    "signals.parquet",
    "manifest.json",
    "archive_index.jsonl",
}


def _remove_known_archive_files(directory: Path) -> list[str]:
    removed: list[str] = []
    for name in ALLOWED_ARCHIVE_FILENAMES:
        path = directory / name
        if path.is_file():
            path.unlink()
            removed.append(str(path))
    return removed
```

- [ ] 将归档生产代码中所有 `shutil.rmtree(...)` 替换为 staging 目录逻辑，或 `_remove_known_archive_files(...)` 逻辑。

- [ ] 将测试中递归删除目录的写法改为删除单个明确文件，或为每个测试使用新的临时归档路径。

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_archive_snapshots.py tests/test_object_backup.py -q
```

预期：通过。

## 里程碑 2：完整归档校验

**验收标准：** `verify-archive` 能完整校验 DB manifest、本地 `manifest.json`、文件存在性、sha256、字节数、行数、按 scope 要求的必要文件，并返回结构化错误。

### 任务 2：实现严格的 `verify_archive`

**文件：**

- 修改：`quant-board/backend/data/archive/service.py`
- 修改：`quant-board/backend/main.py`
- 修改：`quant-board/backend/cli.py`
- 测试：`quant-board/tests/test_archive_snapshots.py`
- 测试：`quant-board/tests/test_archive_research.py`

- [ ] 增加以下测试：
  - 有效快照归档可以通过校验。
  - 文件缺失返回 `archive_file_missing`。
  - sha256 不匹配返回 `archive_sha256_mismatch`。
  - 行数不匹配返回 `archive_row_count_mismatch`。
  - 不支持的 scope 返回 `unsupported_archive_scope`。

- [ ] 增加 `ArchiveService.verify_archive(archive_id: str) -> dict[str, Any]`。

成功响应要求：

```json
{
  "ok": true,
  "archiveId": "snapshots_ds_half_hour_2026-01-01",
  "status": "verified",
  "checkedFiles": 5,
  "rowCounts": {}
}
```

失败响应要求：

```json
{
  "ok": false,
  "error": {
    "code": "archive_sha256_mismatch",
    "archiveId": "..."
  }
}
```

- [ ] 将 CLI `verify-archive` 和 API `POST /api/storage/archive/verify` 接到严格校验方法。

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_archive_snapshots.py tests/test_archive_research.py -q
```

预期：通过。

## 里程碑 3：DuckDB 查询合同收口

**验收标准：** 现有读取 API 能透明返回归档数据，并具备正确的 `source`、支持的过滤、排序、limit 和 offset。查询失败时返回结构化错误，不能静默返回空数据。

### 任务 3：加固 DuckDB 过滤和错误处理

**文件：**

- 修改：`quant-board/backend/data/archive/duckdb_query.py`
- 修改：`quant-board/backend/data/archive/service.py`
- 修改：`quant-board/backend/data/repository.py`
- 修改：`quant-board/backend/services.py`
- 测试：`quant-board/tests/test_duckdb_archive_query.py`
- 测试：`quant-board/tests/test_quant_board.py`

- [ ] 增加以下测试：
  - 快照 stock rows 同时命中归档日期范围和热库日期范围时返回 `mixed`。
  - 快照 sector rows 支持归档范围查询。
  - 不支持的归档过滤字段抛出或返回 `archive_query_filter_unsupported`。
  - parquet 文件缺失返回 `archive_file_missing`，而不是空成功。
  - 回测 trades 和 signals 从 Parquet 读取时遵守 `limit` 与 `offset`。

- [ ] 在 `DuckDBArchiveQuery` 中按表定义允许过滤字段：

```python
ALLOWED_FILTERS = {
    "stock_rows": {"dataset_id", "snapshot_type", "trading_date", "code", "snapshot_id"},
    "sector_rows": {"dataset_id", "snapshot_type", "trading_date", "entity_type", "entity_key", "snapshot_id"},
    "trades": {"backtest_run_id", "code", "side"},
    "equity_curve": {"backtest_run_id"},
    "signals": {"backtest_run_id", "code", "signal"},
}
```

- [ ] 通过 service 层包装返回结构化错误。不得向调用方暴露 SQL。

- [ ] 将 API 响应中的 `source` 统一为以下三个值：
  - `sqlite`
  - `parquet_archive`
  - `mixed`

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_duckdb_archive_query.py tests/test_quant_board.py -q
```

预期：通过。

## 里程碑 4：自动归档生产门禁

**验收标准：** 自动归档可以安全开启。每轮先 preview，只处理保留期外数据，遵守 max partitions；上一轮失败后停止；校验失败后绝不删除 SQLite 行；health 暴露状态。

### 任务 4：强化自动归档状态机

**文件：**

- 修改：`quant-board/backend/data/archive/auto_archive.py`
- 修改：`quant-board/backend/main.py`
- 测试：`quant-board/tests/test_auto_archive.py`
- 测试：`quant-board/tests/test_quant_board.py`

- [ ] 增加以下测试：
  - 默认关闭时不会启动后台归档。
  - 开启后只处理早于保留期 cutoff 的日期。
  - 一次失败会阻止下一次自动运行，直到手工 `auto-once` 成功或状态被清理。
  - manifest 冲突记录 `last_error`，且不删除 SQLite 行。
  - parquet 校验失败记录 `last_error`，且不删除 SQLite 行。
  - max partitions 生效。

- [ ] 增加显式 `ArchiveAutoState` 字段：

```python
enabled: bool
running: bool
interval_seconds: int
last_result: dict[str, Any] | None
last_error: str | None
last_started_at: str | None
last_finished_at: str | None
consecutive_failures: int
```

- [ ] 确保自动循环和 `POST /api/storage/archive/auto-once` 调用同一套实现。

- [ ] 确保 apply 流程为：
  - preview。
  - 写归档。
  - verify archive。
  - 只有校验成功后才删除 SQLite 明细行。

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_auto_archive.py tests/test_quant_board.py -q
```

预期：通过。

## 里程碑 5：R2 备份完成

**验收标准：** R2/S3 备份支持 smoke、push、pull、sha256 校验、manifest 状态流转、`archive_index.jsonl`，并补充真实 R2 smoke 文档。上传失败不影响本地归档成功状态。

### 任务 5：补齐 push/pull 备份语义

**文件：**

- 修改：`quant-board/backend/data/archive/object_store.py`
- 修改：`quant-board/backend/data/archive/service.py`
- 修改：`quant-board/backend/main.py`
- 修改：`quant-board/backend/cli.py`
- 测试：`quant-board/tests/test_object_backup.py`

- [ ] 增加以下测试：
  - 存在 `archive_index.jsonl` 时会上传。
  - allowlist 外文件不会上传。
  - push 更新 `status=uploaded`、`object_key`、`uploaded_at`。
  - 上传失败时 manifest 仍保持 `verified`，并记录 `last_error`。
  - pull dry-run 只列出远端 key，不写本地文件。
  - pull apply 先写 staging 目录，校验 sha256 后再发布本地文件。
  - sha256 不匹配时设置 `status=hash_mismatch`，不得标记为 verified。

- [ ] 将对象上传文件名限制为：

```python
{"records.parquet", "frames.parquet", "stock_rows.parquet", "sector_rows.parquet", "trades.parquet", "equity_curve.parquet", "signals.parquet", "manifest.json", "archive_index.jsonl"}
```

- [ ] 确保 `smoke-object-backup` 只写入、读回、删除一个明确测试 key。

- [ ] 在文档中增加真实 R2 手工验证命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli smoke-object-backup
.\.venv\Scripts\python.exe -m backend.cli push-archive-backup --limit 1
.\.venv\Scripts\python.exe -m backend.cli pull-archive-backup --archive-id <archive_id> --dry-run
```

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_object_backup.py -q
```

预期：通过。

## 里程碑 6：研究回测归档策略加固

**验收标准：** 研究回测归档能确定性选择旧 run，保留摘要，按 dataset/strategy/snapshot/config 分组保留最新 N 个 run，恢复时保持原 `run_id`，并支持 trades/equity/signals 的 API fallback。

### 任务 6：收紧研究回测归档候选选择

**文件：**

- 修改：`quant-board/backend/data/archive/service.py`
- 修改：`quant-board/backend/services.py`
- 测试：`quant-board/tests/test_archive_research.py`
- 测试：`quant-board/tests/test_duckdb_archive_query.py`

- [ ] 增加以下测试：
  - `older_than_days` 排除近期 run。
  - `keep_latest_per_group` 按分组保留最新 run。
  - 归档只删除 `backtest_trades`、`backtest_equity_curve`、`backtest_signals`。
  - `backtest_runs` 和 `backtest_quality_reports` 保留。
  - restore 保持原 `run_id`。
  - API fallback 能返回归档后的 equity 和 signals，不只支持 trades。

- [ ] 定义分组 key：

```python
(dataset_id, strategy_name, snapshot_type, strategy_version, config_hash, random_seed)
```

- [ ] 按 `created_at desc` 排序候选，并在每个分组中保留最新 `keep_latest_per_group` 个 run。

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_archive_research.py tests/test_duckdb_archive_query.py -q
```

预期：通过。

## 里程碑 7：API、CLI 与文档最终收口

**验收标准：** API/CLI 合同与文档一致，并返回统一响应形态。文档清楚区分 SQLite 热库、Parquet 冷归档、DuckDB 读取引擎、R2 对象备份和旧 Supabase 兼容链路。

### 任务 7：统一 API 和 CLI 响应合同

**文件：**

- 修改：`quant-board/backend/main.py`
- 修改：`quant-board/backend/cli.py`
- 修改：`quant-board/docs/database-migration-plan.md`
- 修改：`quant-board/docs/architecture.md`
- 修改：`quant-board/docs/api-cli.md`
- 修改：`quant-board/docs/AI_COLLABORATION.md`
- 修改：`docs/snapshot-storage-readme.md`
- 测试：`quant-board/tests/test_quant_board.py`

- [ ] 增加 API 测试：
  - archive preview 响应形态。
  - archive apply 响应形态。
  - verify 响应形态。
  - restore 响应形态。
  - auto-once 响应形态。
  - object smoke/push/pull 响应形态。
  - health archive auto state。

- [ ] 确保成功响应形态使用：

```json
{
  "ok": true,
  "dryRun": false,
  "archiveId": "...",
  "scope": "snapshots",
  "status": "verified",
  "source": "sqlite",
  "target": "parquet_local",
  "rowCounts": {},
  "files": [],
  "deletedFromSqlite": {},
  "errors": []
}
```

- [ ] 确保失败响应形态使用：

```json
{
  "ok": false,
  "error": {
    "code": "archive_hash_conflict",
    "archiveId": "...",
    "message": "existing archive has different file hash"
  }
}
```

- [ ] 用最终命令列表更新文档：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli archive-snapshots --dataset-id dragonboard_live --snapshot-type half_hour --before-trading-date 2026-01-01 --dry-run
.\.venv\Scripts\python.exe -m backend.cli archive-snapshots --dataset-id dragonboard_live --snapshot-type half_hour --before-trading-date 2026-01-01 --apply
.\.venv\Scripts\python.exe -m backend.cli archive-research --older-than-days 30 --keep-latest-per-group 10 --dry-run
.\.venv\Scripts\python.exe -m backend.cli verify-archive --archive-id <archive_id>
.\.venv\Scripts\python.exe -m backend.cli restore-archive --archive-id <archive_id> --dry-run
.\.venv\Scripts\python.exe -m backend.cli archive-auto-once --limit 5
.\.venv\Scripts\python.exe -m backend.cli smoke-object-backup
.\.venv\Scripts\python.exe -m backend.cli push-archive-backup --limit 50
.\.venv\Scripts\python.exe -m backend.cli pull-archive-backup --archive-id <archive_id> --dry-run
```

- [ ] 运行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -q
```

预期：通过。

## 最终验证

- [ ] 运行完整后端测试：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
```

预期：全部通过。

- [ ] 运行 CLI dry-run：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli archive-snapshots --dataset-id dragonboard_live --snapshot-type half_hour --before-trading-date 2026-01-01 --dry-run
.\.venv\Scripts\python.exe -m backend.cli archive-research --older-than-days 30 --keep-latest-per-group 10 --dry-run
```

预期：返回结构化 JSON；不写文件；不删除 SQLite 行。

- [ ] 仅在 R2 环境变量已经配置时运行对象存储 smoke：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli smoke-object-backup
```

预期：写入、读回、删除一个明确的 smoke object。

## 发布建议

- **V1.0.1：** 里程碑 1 和 2。关闭删除规则违规和归档校验缺口。
- **V1.1.0：** 里程碑 3。让 DuckDB fallback 达到生产安全。
- **V1.2.0：** 里程碑 4。用严格门禁启用自动归档。
- **V1.3.0：** 里程碑 5。完成 R2 备份。
- **V1.3.1：** 里程碑 6 和 7。加固研究回测归档，并完成 docs/API 一致性。

## 回滚策略

- 自动归档默认保持关闭。
- 如果 DuckDB fallback 在生产中出现问题，只禁用归档明细 fallback，保留归档文件和 manifest。
- 如果 R2 上传失败，保留本地 manifest 的 `verified` 状态；不得因为备份失败而降级本地归档成功状态。
- 如果 restore 校验失败，保持现有 SQLite 行不变，并返回结构化错误。
- 回滚时不要删除归档目录。保留本地 Parquet 文件，并显式更新 manifest 状态或错误。
