# API 与 CLI 使用说明

QuantBoard API 和 CLI 共用同一套服务层。API 面向轻实验台和自动化脚本，CLI 面向本地批处理、调试和复现。

## API 响应口径

当前接口不是统一 `ok/data` 包装。成功时直接返回业务对象；失败时使用 HTTP `4xx/5xx`，FastAPI 在 `detail` 字段里返回错误信息。

前端和脚本应按 HTTP 状态判断失败，不要用 HTTP 200 + 空对象表示失败。

Dragon Board 前端调用 QuantBoard 快照 ingest 时会把 `503` 和其他 `5xx` 视为可重试错误；`4xx` 表示请求或数据合同错误，不做自动重试。

SQLite 主库 + Supabase 备份库的完整读写、同步、恢复和冲突规则见 [database-migration-plan.md](database-migration-plan.md)。本文件只记录 API/CLI 对外合同。

## 数据集接口

### `GET /api/health`

健康检查。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

返回的 `database` 会同时报告本地 SQLite 主库和 Supabase 备份库状态。默认健康检查走快速路径，不发起 Supabase 网络请求，避免页面状态被云端备份库表结构探测拖慢；需要完整 Supabase 同构表检查时使用 `GET /api/health?deep=true`。

- `primary.connected`：本地主库是否可用。
- `backup.connected`：默认快速路径为 `null`，表示未做云端探测；`deep=true` 时表示 Supabase REST 备份库是否可用。
- `backup.schema`：当前要求为 `sqlite_homomorphic`。
- `backup.missing_or_unreadable_tables`：仅 `deep=true` 时返回，同构表缺失或不可读列表；非空时不能执行正式云端同步。
- `mode`：当前为 `sqlite_primary_supabase_backup`。
- `outbox`：待补偿同步队列摘要；字段以当前后端实现为准。
- `autoSync`：自动 outbox 推送状态、间隔、批量大小和最近一次结果。

目标合同：健康检查必须能让调用方判断主库、备份库、读回退和补偿同步是否可用。新增或改名字段时，必须同批更新本文和 [database-migration-plan.md](database-migration-plan.md)。

### `POST /api/sync/push-backup`

把本地 SQLite 快照库中的数据集和快照事实推送到 Supabase 备份库。回测、优化、Golden 和报告属于 research SQLite，不进入 Supabase Free 版备份目标。

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

`push-backup` 会先消费 `sync_outbox` 中到期的 `pending/retry` 任务，再扫描 SQLite 快照库已有的数据集和快照事实做补推。失败项会进入 `errors`，结构为 `{type,key,error}`。

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

Dragon Board 正式快照写入入口。前端提交 v4 snapshot bundle，正常路径先写 SQLite，再登记/更新 Supabase 备份 outbox。Vue 前端不得直连 Supabase，也不得携带数据库密钥。

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

同一 `idempotencyKey` 重放时返回 `deduped=true`，不会重复写入事实行。若 Supabase 镜像失败，本地 SQLite 写入仍成立，`status` 会是 `retry/failed`，后续由 `push-backup` 补偿。

当 SQLite 主库完全不可用但 Supabase 同构备份库可写时，接口会临时执行 failover 写入，返回 `ok=true`、`status=backup_only`、`outbox=null`，并带上 `failover.active=true`、`reason`、`idempotency_key` 和恢复提示。该路径不会伪造 SQLite outbox；主库恢复后需要执行 `POST /api/sync/pull-backup` 把备份记录拉回 SQLite。若 Supabase 也不可写，接口返回 503。

### `GET /api/snapshots/frames`

从 SQLite 主库读取正式快照聚合帧，用于逐步替换 Dragon Board 对 IndexedDB 的正式分析读取。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/frames?dataset_id=dragonboard_live&snapshot_type=half_hour&trading_date=2026-04-21'
```

常用查询参数：

- `dataset_id`：可选；缺省时优先 `dragonboard_live`，不存在时读取最新有 frame 的 SQLite 数据集。
- `snapshot_type`：默认 `half_hour`。
- `trading_date` 或 `start_date/end_date`。
- `before_trading_date`。
- `allowed_capture_modes`：逗号分隔。
- `exclude_restored`。
- `sort=asc|desc`。
- `limit`。

返回 `dataset`、`frames`、`count` 和 `source=sqlite`。`frames` 中每项包含 `rows/hotlist/sectors/hotThemes/rotationSummary`，供 Dragon Board `listSnapshotFrameBundles` 直接消费。正式快照不再把浏览器 IndexedDB 当事实读源；`five_minute` 等非正式临时数据仍可留在浏览器本地。

### SQLite 快照明细读口

这些接口承接 Dragon Board `DataLayer` 的正式快照读口，返回字段仍保持前端 camelCase 合同，不要求调用方理解 SQLite 列名。

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

### `GET /api/datasets`

返回数据集列表。

### `GET /api/datasets/{dataset_id}`

返回单个数据集详情。

### `POST /api/datasets/import`

从 SQLite 主库已有正式快照事实表生成可复现研究视图。日常研究入口使用 `sourceType=sqlite_snapshots`；浏览器 IndexedDB/LevelDB/运行页桥接不再作为主采集方式。

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
- `sqlite_snapshots` 不产生新的快照事实复制，也不产生新的 Supabase 备份对象。

旧兼容 `sourceType`：

- `json_bundle`
- `browser_bridge`
- `leveldb`

旧兼容来源只用于迁移或排障。历史 JSON、旧 IndexedDB 导出或备份文件建议优先走 `POST /api/migrations/snapshots/import-json` 写入正式快照事实表，再用 `sqlite_snapshots` 生成研究数据集。

如果 `SUPABASE_URL` 和 `SUPABASE_SECRET_KEY` 已配置，正式写入会先落本地 SQLite，再镜像到 Supabase 备份库。`POST /api/snapshots/ingest` 已支持 SQLite 不可用时的 Supabase `backup_only` failover；其他尚未纳入 failover 的写入口仍必须明确返回不可用。读路径会在本地无数据或本地不可用时按主计划回退读取备份库。

新增或修改导入请求字段、快照入库 payload、同步返回字段、错误结构时，必须同批更新 [database-migration-plan.md](database-migration-plan.md)。

### `POST /api/datasets/upload`

上传 JSON 内容并导入，供轻实验台文件上传使用。

### `POST /api/migrations/snapshots/import-json`

历史快照迁移入口。用于把旧 IndexedDB 导出、Dragon Board v4 bundle、结构化 frames/rows 或 SQLite/备份导出 JSON 导入正式 SQLite 主库，并复用 `sync_outbox` 同步到 Supabase。

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

`POST /api/snapshots/ingest` 是 Dragon Board 正式快照写入 SQLite 的入口。调用方应传入稳定的 `datasetId`、`idempotencyKey` 和 v4 `bundle`；后端会先按 `idempotencyKey` 判重，再按 `dataset_id + snapshot_id` 做逻辑幂等。若同一快照槽位已经存在，接口返回 `ok=true`、`deduped=true`，不会删除或覆盖已落库的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows`。

Dragon Board 当前会在写入前通过 SQLite 读口确认同一 `snapshot_id` 是否已存在，避免定时保存反复提交同一槽位。IndexedDB 不再参与正式快照写入判重。

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

返回会包含 `runId`，并把完整结果落库到 `backtest_runs`。为避免真实数据集响应过大，接口默认只返回前 120 条 `signals` 预览，完整结果通过 `runId` 读取。

### `GET /api/backtests/{run_id}`

读取回测报告。

### `GET /api/backtests/{run_id}/report`

读取回测报告，和 `GET /api/backtests/{run_id}` 同口径，供页面语义化调用。

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

### 备份同步 CLI

CLI 与 API 复用同一服务层：

```powershell
cd d:\dragon-board\quant-board
.\.venv\Scripts\python.exe -m backend.cli smoke-backup
.\.venv\Scripts\python.exe -m backend.cli push-outbox --limit 50
.\.venv\Scripts\python.exe -m backend.cli push-backup
.\.venv\Scripts\python.exe -m backend.cli pull-backup
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

## 验收清单

- API 和 CLI 走同一服务层。
- 默认快照是 `half_hour`。
- `quarter_hour` 必须显式传入。
- 回测和优化结果可通过 run id 重复读取。
- `config_hash` 必须包含最终 `strategy_config` 和 `trade_config`。
- Golden 正式验收必须使用 `source=ts_golden_import`。
- 存储、同步、快照入库、API/CLI 请求响应字段或错误结构变更时，必须同批更新相关文档。
