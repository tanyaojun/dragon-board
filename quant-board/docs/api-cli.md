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
- `stockNameRefresh`：每日沪深 A 股基础信息同步任务的运行状态、最近结果和错误信息。

目标合同：健康检查必须能让调用方判断 MongoDB 主库和 MongoDB 备份能力是否可用。新增或改名字段时，必须同批更新本文和 [mongodb-migration-plan.md](mongodb-migration-plan.md)。

### launcher 健康契约（8000 / 8001 通用）

DragonBoardLauncher 消费的统一健康契约字段（两个 `/api/health` 都返回）：

| 字段 | 取值 | 含义 |
|---|---|---|
| `status` | `ok` / `degraded` / `error` | 服务健康等级 |
| `restartable` | `true` / `false` | 是否允许 launcher 自动重启 |
| `recommendedAction` | `none` / `restart` / `wait` / `alert` | launcher 应执行的动作 |
| `reason` | 字符串 | 人类可读原因 |

- 8000（`backend/main.py`）：进程存活即 `ok / restartable=true / action=none`；采集器状态见 `snapshotCollector` 兼容块。
- 8001（`backend/collector_main.py`）：由 `_collector_health_contract` 把调度器状态映射为契约——
  - 调度器未运行（`enabled` 但 `running=false`）：`error / restartable=true / action=restart`（硬故障）；
  - 最近有 `last_error`：`degraded / restartable=false / action=alert`（数据源暂时失败，重启无益）；
  - 其余：`ok / restartable=true / action=none`。
- **启动失败标记文件**：8001 锁冲突等导致进程启动失败退出时，`collector_main` 会把原因写入仓库根
  `logs/collector-startup-failure.json`（含 `restartable=false / recommendedAction=wait`）；launcher 探针在
  8001 不可达时读取该文件（10 分钟内新鲜有效）并按 wait 处理，不再"先杀再启"触发锁竞争重启风暴。
  成功拿到锁后该文件会被清除。
- launcher 侧实现：`tools/DragonBoardLauncher/SnapshotCollectorProbe.cs`。改契约字段时需同批更新
  该文件与本文；C# 侧已保留对旧 `snapshotCollector` 内部字段解析的兼容回退。

## MongoDB 备份与旧维护入口状态

MongoDB 模式下：

- 快照、研究、题材和股票基础数据 API 通过 MongoDB repository 运行。
- `/api/storage/archive/*` 旧 SQLite/Parquet 归档接口返回 410。
- `/api/sync/*` 旧 Supabase 同步接口返回 410。
- `/api/migrations/snapshots/import-json` 返回 410；历史导入只允许走停服迁移脚本。
- `/api/operations/after-market-once` 在 MongoDB 模式下只执行 `hotlistSentiment` 日终步骤，不执行旧 SQLite archive/prune 链路。
- CLI 旧 SQLite/Supabase/Parquet 命令拒绝执行；业务回测、优化、查询命令继续通过 MongoDB repository 运行。
- MongoDB 备份、校验、R2 上传和拉回恢复命令以 [mongodb-migration-plan.md](mongodb-migration-plan.md) 的当前实施状态为准。

### MongoDB 快照修复 CLI

正式快照质量修复统一使用：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live --apply
```

当前命令职责不再局限于“补空快照”，而是同时处理：

- 空 formal snapshot 补行
- `snapshot_record` 缺失补造
- frame `stockRowCount/sectorRowCount` 漂移修正
- 缺失盘后固定价格交易槽位时补造：`quarter_hour` 新增 `15:15`，`daily` 的唯一终值槽调整为 `15:30`；`hourly` 槽位不变。`half_hour` 曾含 `15:30`，2026-09-11 起止于 `15:00`（单日 10 槽），15:30 收盘定格值由 `daily` 独占。补造优先同粒度最近 donor，必要时允许显式跨粒度 donor。
- runtime MongoDB 缺失索引补回

验收命令：

```powershell
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type quarter_hour
```

2026-06-11 已执行一次正式修复，结果见 [mongodb-snapshot-audit-2026-06-11.md](mongodb-snapshot-audit-2026-06-11.md)。

### MongoDB 跃迁字段回填 CLI

回填历史快照中缺失的 `jumpDirection` 和 `jumpConfidence`。从 `snapshot_stock_rows` 的 `compRank` 跨帧序列重建百分位时间线，运行与前端 `detectRankJumps` 等价的跳变检测算法。

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli backfill-jump-fields --dataset-id dragonboard_live
.\.venv\Scripts\python.exe -m backend.cli backfill-jump-fields --dataset-id dragonboard_live --apply
.\.venv\Scripts\python.exe -m backend.cli backfill-jump-fields --trading-date 2026-06-19 --apply
```

回填字段：

| 字段 | 来源 | 不回填 |
|------|------|--------|
| `jumpDirection` | compRank 百分位序列 + 跳变检测 | — |
| `jumpConfidence` | 同上 | — |
| `macdCross` | MACD DIF/DEA 原始值未存储 | 不可回填 |
| `resonanceIntensity` | 依赖 macdCross，偏差 ±10% | 不可回填 |

2026-06-19 已执行一次全量回填：56 个交易日，362,718 行，0 错误。

## python-bridge 后端采集接口（Phase 2）

为支持 QuantBoard 后端独立采集（不依赖浏览器 WebSocket 订阅），`python-bridge` 新增以下 HTTP 接口：

### `POST /api/quotes/subscriptions`

设置后端采集订阅池。接收代码列表，立即 fetch 行情并缓存到 bridge 内存。后续 `GET /api/quotes/snapshot` 不带 `codes` 参数时可回退到此缓存。

请求：

```json
{"codes": ["000001", "600000", "300750"]}
```

响应：

```json
{
  "ok": true,
  "codes": ["000001", "300750", "600000"],
  "count": 3,
  "setAt": 1781170800000
}
```

### `GET /api/quotes/snapshot`（池模式）

不带 `codes` 参数时使用订阅池缓存。池为空时返回 `ok=false` 和 `"missing codes parameter and backend pool is empty"`。

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/quotes/snapshot
```

响应（池模式）：

```json
{
  "ok": true,
  "source": "python_bridge",
  "serverTs": 1781170800000,
  "subscribedCount": 3,
  "quotes": [],
  "depth": [],
  "ticks": [],
  "moneyFlow": [],
  "quoteStats": {},
  "l2": {},
  "pooled": true,
  "poolRefreshedAt": 1781170800000
}
```

带 `?codes=...` 参数时保持 Phase 1 按需抓取行为，此时响应中不包含 `pooled` / `poolRefreshedAt` 字段。

## 后端快照采集器 API

以下接口属于 `backend/snapshot_collector/` 模块，是 QuantBoard 后端的正式快照采集能力。写入 `dragonboard_live` 需设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=1`、`QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live` 和 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1`。所有响应使用统一的 `{"ok": true/false, "status": "...", "data": {...}}` 信封格式。

正式采集由独立进程承载（DragonBoardLauncher 核心启动项，默认端口 8001）：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m uvicorn backend.collector_main:app --host 127.0.0.1 --port 8001 --no-access-log
```

8000 Quant API 进程不再启动采集调度器；`QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS` 已废弃（next-slot 精确定时）。

采集器通过 FastAPI 主进程的 `startup`/`shutdown` 生命周期自动管理 `SnapshotCollectorScheduler`，与 QuantBoard API 共用 `8000` 端口，无需独立守护进程。

股票池优先读取 proxy-server `/api/cache/startup-bundle?key=default:YYYY-MM-DD`。startup bundle 缺失或过期时，collector 调用 proxy-server 的八个平台热榜接口做 union fallback，生成 `rank/compRank/platforms/avgRank/avgRankNum` 和各平台原始名次。任一平台失败只记录数据源健康和质量标记；只有 startup bundle 与八平台热榜全部不可用、无法采到任何股票时才阻断写入。frame 的 `metadata.rankProvenance` 同时保存当槽平台总行数、权重、字段映射和公式版本。

### `GET /api/snapshot-collector/status`

返回采集器当前运行状态，包括最近一次运行、统计摘要和数据源健康信息。

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/snapshot-collector/status
```

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "lastRunId": "sc-a1b2c3d4e5f6",
    "lastRunAt": "2026-06-12T10:30:00Z",
    "lastStatus": "completed",
    "totalRuns": 42,
    "completedRuns": 38,
    "dedupedRuns": 2,
    "blockedRuns": 2,
    "datasetIds": ["dragonboard_backend_shadow"]
  }
}
```

### `POST /api/snapshot-collector/run-once`

执行单次快照采集运行。采集流水线依次执行：创建 SnapshotSlot -> 判重 -> 采集数据源 -> 组装 payload -> 规范化 -> 质量门禁 -> 落库。

```json
{
  "datasetId": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "tradingDate": "2026-06-12",
  "slotTime": "10:30",
  "dryRun": false,
  "force": false
}
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `datasetId` | 是 | 目标数据集 ID，默认应为 `dragonboard_backend_shadow` |
| `snapshotType` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `tradingDate` | 是 | `YYYY-MM-DD` 格式交易日 |
| `slotTime` | 是 | `HH:MM` 格式槽位时间 |
| `dryRun` | 否 | 默认 `false`；为 `true` 时走完整流水线但不写库 |
| `force` | 否 | 默认 `false`；为 `true` 时跳过判重强制重写；写入失败时恢复替换前事实 |

成功响应（`status=completed`）：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "runId": "sc-a1b2c3d4e5f6",
    "snapshotId": "half_hour:2026-06-12:10:30",
    "deduped": false,
    "dryRun": false,
    "message": "done",
    "details": {
      "stockRowCount": 224,
      "frameCount": 1,
      "sectorRowCount": 12,
      "idempotencyKey": "dragonboard_backend_shadow:half_hour:2026-06-12:10:30:..."
    }
  },
  "quality": {
    "ok": true,
    "blockingIssues": [],
    "warnings": [],
    "sourceCounts": {"ok": 2, "failed": 0}
  }
}
```

去重响应（`status=deduped`，`ok=true`）：

```json
{
  "ok": true,
  "status": "deduped",
  "data": {
    "runId": "sc-b2c3d4e5f6a1",
    "snapshotId": "half_hour:2026-06-12:10:30",
    "deduped": true,
    "dryRun": false,
    "message": "Snapshot already exists"
  }
}
```

质量门禁阻止（`status=blocked`，`ok=false`）：

```json
{
  "ok": false,
  "status": "blocked",
  "data": {
    "runId": "sc-c3d4e5f6a1b2",
    "snapshotId": "half_hour:2026-06-12:15:05",
    "deduped": false,
    "dryRun": false,
    "message": "Quality gate blocked: ['startup_bundle_missing']"
  },
  "quality": {
    "ok": false,
    "blockingIssues": ["startup_bundle_missing"],
    "warnings": ["quote_provider_partial"],
    "sourceCounts": {"ok": 1, "failed": 2}
  }
}
```

dry-run 响应（`status=dry_run`，`ok=true`）：

```json
{
  "ok": true,
  "status": "dry_run",
  "data": {
    "runId": "sc-d4e5f6a1b2c3",
    "snapshotId": "half_hour:2026-06-12:10:30",
    "deduped": false,
    "dryRun": true,
    "message": "Dry-run completed successfully"
  },
  "quality": {
    "ok": true,
    "blockingIssues": [],
    "warnings": [],
    "sourceCounts": {"ok": 2, "failed": 0}
  }
}
```

### `POST /api/snapshot-collector/backfill-slots`

按日期区间批量执行采集。自动为区间内每个交易日生成所有符合条件的槽位时间，逐个调用 `run_once`；周末和已知节假日不会生成 backfill slot。

```json
{
  "datasetId": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "startDate": "2026-06-10",
  "endDate": "2026-06-12",
  "dryRun": true,
  "force": false
}
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `datasetId` | 是 | 目标数据集 ID |
| `snapshotType` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `endDate` | 是 | `YYYY-MM-DD` 格式截止日期；非交易日会被跳过 |
| `startDate` | 否 | 默认等于 `endDate`；区间起止含两端，非交易日会被跳过 |
| `dryRun` | 否 | 默认 `true`（backfill 默认不写库） |
| `force` | 否 | 默认 `false`；为 `true` 时跳过判重 |

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "total": 32,
    "succeeded": 28,
    "failed": 0,
    "blocked": 2,
    "deduped": 2,
    "details": [
      {"snapshotId": "half_hour:2026-06-10:09:30", "status": "completed", "message": "done"},
      {"snapshotId": "half_hour:2026-06-10:10:00", "status": "blocked", "message": "Quality gate blocked: ['startup_bundle_missing']"}
    ]
  }
}
```

`ok` 为 `false` 当且仅当存在 `failed` 或 `blocked` 时。

### `GET /api/snapshot-collector/runs`

列出历史采集运行记录，支持按数据集、状态和快照类型过滤。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshot-collector/runs?status=blocked&limit=20'
```

查询参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `datasetId` | 空 | 按数据集 ID 过滤 |
| `status` | 空 | 按状态过滤：`completed` / `dry_run` / `deduped` / `blocked` |
| `snapshotType` | 空 | 按快照类型过滤 |
| `limit` | `50` | 每页条数 |
| `offset` | `0` | 起始偏移 |

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "items": [
      {
        "runId": "sc-a1b2c3d4e5f6",
        "datasetId": "dragonboard_backend_shadow",
        "snapshotId": "half_hour:2026-06-12:10:30",
        "snapshotType": "half_hour",
        "tradingDate": "2026-06-12",
        "slotTime": "10:30",
        "status": "completed",
        "deduped": false,
        "dryRun": false,
        "createdAt": "2026-06-12T10:30:05Z"
      }
    ],
    "total": 42,
    "limit": 50,
    "offset": 0
  }
}
```

### `POST /api/snapshot-collector/audit`

审计指定数据集和快照类型的覆盖率。检查每个交易日每个槽位的采集状态、行数和质量。

```json
{
  "datasetId": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "tradingDate": "2026-06-12"
}
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `datasetId` | 是 | 目标数据集 ID |
| `snapshotType` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `tradingDate` | 否 | 可选单日过滤；不传时审计数据集全范围 |

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "datasetId": "dragonboard_backend_shadow",
    "snapshotType": "half_hour",
    "totalSlots": 16,
    "coveredSlots": 14,
    "missingSlots": 2,
    "missingSlotIds": [
      "half_hour:2026-06-12:11:00",
      "half_hour:2026-06-12:11:30"
    ],
    "qualitySummary": {
      "blockedRuns": 0,
      "warningRuns": 3
    },
    "slotDetails": [
      {
        "snapshotId": "half_hour:2026-06-12:10:00",
        "status": "covered",
        "stockRowCount": 224,
        "lastRunStatus": "completed"
      }
    ]
  }
}
```

### `POST /api/snapshot-collector/compare`

对比两个数据集的快照覆盖率和字段完整性（shadow vs live 审计）。

```json
{
  "datasetIdA": "dragonboard_live",
  "datasetIdB": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "tradingDate": "2026-06-12"
}
```

请求字段：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `datasetIdA` | 是 | 基准数据集 ID（通常为 `dragonboard_live`） |
| `datasetIdB` | 是 | 对比数据集 ID（通常为 `dragonboard_backend_shadow`） |
| `snapshotType` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `tradingDate` | 否 | 可选单日对比；不传时对比所有共同交易日 |

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "ok": true,
    "datasetA": "dragonboard_live",
    "datasetB": "dragonboard_backend_shadow",
    "snapshotType": "half_hour",
    "tradingDates": ["2026-06-11", "2026-06-12"],
    "perDate": [
      {
        "tradingDate": "2026-06-12",
        "totalExpectedSlots": 10,
        "slotsInBoth": ["half_hour:2026-06-12:10:00"],
        "slotsOnlyInA": [],
        "slotsOnlyInB": ["half_hour:2026-06-12:09:30"],
        "slotsMissingInBoth": [],
        "slotDetails": [
          {
            "snapshotId": "half_hour:2026-06-12:10:00",
            "inA": true,
            "inB": true,
            "stockRowCountA": 224,
            "stockRowCountB": 210,
            "sectorRowCountA": 35,
            "sectorRowCountB": 0,
            "fieldMissingRatesA": {},
            "fieldMissingRatesB": {"depth10": {"present": 0, "missing": 210, "rate": 1.0}}
          }
        ]
      }
    ],
    "summary": {
      "totalSlotsCompared": 20,
      "slotsInBoth": 18,
      "slotsOnlyInA": 1,
      "slotsOnlyInB": 1,
      "slotsMissingInBoth": 0,
      "avgStockRowDiff": 14.0,
      "emptyFramesA": 0,
      "emptyFramesB": 1
    }
  }
}
```

### `GET /api/snapshot-collector/scheduler/status`

返回调度器运行状态，包括启用/禁用、运行中、轮询间隔、最近采集的 slot、采集计数和错误计数。

响应示例：

```json
{
  "ok": true,
  "status": "completed",
  "data": {
    "enabled": true,
    "running": true,
    "dataset_id": "dragonboard_backend_shadow",
    "snapshot_types": ["half_hour", "daily"],
    "poll_seconds": 1.0,
    "grace_minutes": 5,
    "last_run_at": "2026-06-15T10:00:01+08:00",
    "last_slot_collected": "half_hour:2026-06-15:10:00",
    "last_error": null,
    "collection_count": 3,
    "error_count": 0,
    "in_flight_slots": []
  }
}
```

调度器状态同样包含在 `GET /api/health` 响应的 `snapshotCollector` 字段中。

注意：进程重启后内存态 `last_run_at` 会清零，健康端点只会用 MongoDB 里
**属于当前交易日**的最近 completed 运行记录回填；跨日的旧记录不会写入
`last_run_at`，避免新交易日开盘瞬间被启动管理器探针误判为“超过2小时未执行”
而杀重启。若今天尚未有任何采集，`last_run_at` 保持 `null`，由调度器内存态
在首次采集后自行填充。

## 热榜情绪 API、回填和盘后调度

### `POST /api/hotlist-sentiment/ingest`

写入一个 `datasetId + snapshotType + tradingDate` 的日终热榜情绪结果。MongoDB 是唯一运行主链；MongoDB 不可用时返回 `503`，不会写入 SQLite/Supabase fallback。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "tradingDate": "2026-06-05",
  "stage": "发酵",
  "riskLevel": "中",
  "confidence": 72,
  "metrics": {},
  "turnover": {},
  "signals": [],
  "warnings": []
}
```

### 历史回填脚本

脚本从 MongoDB `snapshot_frames` 选择每个交易日最后一帧，再读取对应 `snapshot_stock_rows` 生成 `hotlist_sentiment`。默认 dry-run；只有显式 `--apply` 才写库。

```powershell
cd quant-board
.\.venv\Scripts\python.exe scripts\backfill_hotlist_sentiment.py --dry-run
.\.venv\Scripts\python.exe scripts\backfill_hotlist_sentiment.py --apply
```

### `POST /api/operations/after-market-once`

MongoDB 模式下，该入口只执行日终热榜情绪落库：

```json
{
  "ok": true,
  "steps": ["hotlistSentiment"],
  "results": {
    "hotlistSentiment": {
      "ok": true,
      "datasetId": "dragonboard_live",
      "snapshotType": "half_hour",
      "tradingDate": "2026-06-05",
      "written": 1
    }
  }
}
```

迁移前 SQLite 模式仍保留旧 `backup-snapshot-day -> archive-auto-once -> push-archive-backup -> prune-backup` 编排；MongoDB 模式不得触碰旧 archive/prune 链路。

MongoDB 模式盘后链（`scripts/register_after_market_task.ps1` 注册，每日 16:00）在三个生产步
（`hotlistSentiment` / `mongodbBackup` / `snapshotArchiveR2`，任一失败置 `stoppedAt`）之后跑一串
**advisory 步**（失败/跳过只进 `results`，不翻转整体 ok、不参与 `stoppedAt`）：`phasePulse`、
`jiuyanLabel`、`zhabanLabel`、`relayIndex`、`relayBand`、`phaseBand`、`deepValley`、
`peakRevalidate`、`jevDailyLine`、`calibDriftMonitor`、`amountVsSameRecord`、`voteWinrateLedger`。
其中 `relayBand`（2026-10-19）重算分带实测表（零模型调用，门控=产物 `window.end` < 最新 ok 判定日
才跑；失败保留旧表并撤掉半成品）。

## jev 热榜情绪观察轨道 API（2026-10-08）

独立观察轨道（详见 `architecture.md` jev 节与 `docs/hotlist-jev/hotlist-jev-emotion-observe-design.md`）。

### `POST /api/hotlist-jev/evaluate`

手动触发双问题评判，**不受 `JEV_SENTIMENT_ENABLED` gate 限制**（显式意图），origin=manual：

```json
{ "tradingDate": "2026-10-08", "scope": "slot", "slotTime": "10:00", "datasetId": "dragonboard_live" }
```

`scope` = `slot`（缺省 slotTime 取当日最新已采 half_hour 槽）或 `day`（盘后日级固定）。返回
`{ok, status: ok|degraded|no_data, ...}`；当日无帧且未给 slotTime → 404 `errorCode=no_slot`。

### `POST /api/hotlist-jev/relay-index/rerun`

连板情绪指数**单日复跑**（2026-10-19，JEV 叙事工作台「重跑」按钮）：网络抖动导致的 degraded
日手动重判。**不受 `JEV_SENTIMENT_ENABLED` gate 限制**（显式意图），复用生产入口
`run_relay_index_day`（叙事拼装 + jev 退避重试），origin 仍为 `relay_index_daily`：

```json
{ "date": "2026-10-19", "force": true, "datasetId": "dragonboard_live" }
```

返回 `{ok, date, day, status, relayIndex, relayPhase, errorCode, errorDetail}`；`day` 与
`GET /relay-index` 的单日文档同形（含 `relayStructure`）。失败/降级照常落库并原样透出原因，
**不伪造读数**；韭研 final 缺失（入口跳过不写）→ `errorCode=not_written`；**该日已有旧档但入口未重判**
（`computedAt` 未刷新）→ `errorCode=not_rerun`（旧档状态不代表本次结果）；token 未配置 →
`missing_token`。页面 :8008 经 `serve_relay_page` POST 透传（超时 `_POST_PROXY_TIMEOUT_SECONDS=400s`，
≥jev 退避预算）。

### `POST /api/hotlist-jev/slots/rerun`

jev 帧级槽位情绪**单日单槽复跑**（2026-10-19，工作台当日逐槽详情卡「重跑」按钮）：网络抖动
导致的 degraded/no_data 槽手动重判。**不受 `JEV_SENTIMENT_ENABLED` gate 限制**（显式意图），
复用生产入口 `compute_and_upsert_for_slot`（origin=`manual`，与 /evaluate 手动补评同源）：

```json
{ "tradingDate": "2026-10-19", "slotTime": "10:00", "snapshotType": "half_hour", "datasetId": "dragonboard_live" }
```

`snapshotType` 显式透传（防 quarter_hour 槽被按 half_hour 重判），缺省 `half_hour`。返回
`{ok, slot, status, errorCode, errorDetail}`；`slot` 与 `GET /series` 的槽位文档同形。
失败/降级照常落库并原样透出原因，**不伪造读数**；入口未落文档 → `errorCode=not_written`；
token 未配置 → `missing_token`；缺 tradingDate/slotTime → `bad_slot`。

### `POST /api/hotlist-jev/eod/rerun`

日级 EOD 情绪**单日复跑**（2026-10-19，当日逐槽表 EOD 行「重跑」按钮）：网络抖动导致的
degraded/no_data EOD 手动重判。**不受 `JEV_SENTIMENT_ENABLED` gate 限制**（显式意图），
复用生产入口 `compute_and_upsert_for_day`（origin=`manual`）：

```json
{ "tradingDate": "2026-10-19", "snapshotType": "half_hour", "datasetId": "dragonboard_live" }
```

返回 `{ok, eod, status, errorCode, errorDetail}`；`eod` 与 `GET /series` 的 `eod` 文档同形。
失败/降级照常落库并原样透出原因，**不伪造读数**；入口未落文档 → `errorCode=not_written`；
token 未配置 → `missing_token`；缺 tradingDate → `bad_date`。

### `GET /api/hotlist-jev/relay-band`

连板指数**分带实测读数**读口（离线诊断产物）——不加工不重算，只读
`data/backups/relay-band-table.json`（env `QUANT_BOARD_RELAY_BAND_TABLE` 可覆盖）。
产物缺失/损坏/空 → `ok=false + reason + hint`（fail-visible，不静默空表）。

### `POST` / `GET /api/hotlist-jev/relay-band/refresh`

分带表**后台重算**（2026-10-19 用户需求；页面滞后黄条 / 未就绪提示内置按钮触发）——**零模型调用**
（只读 Mongo + 本地通达信日线，全窗约 5–9 分钟）。POST 起任务（`{days?: 0}`，0=全窗），已运行
时不重复起（`already_running`）；GET 轮询状态 `{running, ok, startedAt, finishedAt, returncode,
error, days, logPath, artifactPath, logTail}`。产物先写临时文件、成功退出后原子替换：
**刷新期间旧表完整可读**，失败保留旧表并原样透出 `script_exit_N` / `artifact_missing` /
`artifact_replace_failed`，以及 spawn/log 类结构化错误（`spawn_failed` / `log_dir_failed` /
`log_open_failed` / `band_refresh_timeout`）。`days>0` 为**冒烟跑**：因产物 `window.end` 仍是全量末日，产物**另存**
`data/backups/relay-band-table-days<N>.json`，绝不覆盖正式读数（否则门控会误判已覆盖最新日、
永久跳过全窗重建）。

该重算亦已挂入 **16:00 盘后链**（advisory 步 `relayBand`，`backend/operations/schedule.py`；
路径/命令/原子替换的单一事实源 = `backend/services/jev/relay_band.py`）：门控自愈式，产物
`window.end` < 最新 `status=ok 且 relayIndex 非空` 判定日才重算（已覆盖则零成本跳过；门控查询
失败按 skipped 处理，与兄弟 advisory 步一致），因此页面日常不再滞后。

### `GET /api/hotlist-jev/series`

单日读口：`?dataset_id=&date=YYYY-MM-DD`（缺省取库内最新交易日）→
`{ok, date, slots: [槽位文档升序], eod, degradedCount}`；无文档时返回空集不报错（v1 无缓存）。

### 回放 runner

```bash
export JEV_CF_TOKEN=<token>   # 不入仓
cd quant-board
./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 3 --dry-run
./.venv/Scripts/python.exe -m backend.operations.jev_sentiment_replay --days 3
```

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

### `GET /api/theme-rotation/summary`

返回最近一个含引擎 `rotationSummary` 的 frame 及其 sector rows 轮动状态（只读，不计算）。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/theme-rotation/summary?dataset_id=dragonboard_live&snapshot_type=half_hour&trading_date=2026-08-04'
```

参数：`dataset_id`（默认 `dragonboard_live`）、`snapshot_type`（默认 `half_hour`）、
可选 `trading_date`、`slot_time`。查询条件按
`rotationSummary.algorithmVersion` 存在过滤（只认引擎产出的帧，空 dict 不命中）。
返回 `data.frame`（`snapshotId/tradingDate/slotTime/timestamp/rotationSummary`）
与 `data.statuses`（`themeId/themeName/rank/rankChange/rotationState/lifecycle/
rotationScore/heatTrend/flowTrend/breadthTrend/crowdingTrend/
mainlineConcentrationRank/reasons/factorBreakdown/qualityFlags`）。
无匹配帧时返回 404（`ok=false`）。

该接口接入 Redis read-through 缓存（`snapshot_cache`，默认 TTL 60s，可用环境变量
`QUANT_BOARD_THEME_ROTATION_CACHE_TTL_SECONDS` 调整）；响应 key 注册到 dataset/date
索引，采集落库（ingest）时随现有失效链路自动清除，补采/force 重采后不会读到旧结果。
`rotationSummary.inflowThemes/outflowThemes` 为 `[{themeId, themeName}]` 对象列表。

### `GET /api/theme-momentum/summary`

题材动量 v2 只读摘要（独立第四维板块动量，2026-08-06）。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/theme-momentum/summary?dataset_id=dragonboard_live&snapshot_type=half_hour'
```

参数：`dataset_id`（默认 `dragonboard_live`）、`snapshot_type`（默认 `half_hour`）。
从 `snapshot_sector_rows`（`entityType=hot_theme`）按交易日聚合日线序列（收盘槽
`change` 累乘合成虚拟收益指数），计算 v2 六维动量（板块 RPS 5/10/20 / 距年内高点 /
多窗口动量 / 整体性 / 资金量能 / 拥挤惩罚），返回按 `score` 降序的 Top-50 排行。
响应：`{ ok, status, version, factors[], qualityFlags, computedAt, cache }`，其中
`factors[]` 每项含 `themeId/themeName/score/direction/phaseLabel/rps{nearHigh/
windowMomentum/breadth/flowVolume/crowdingPenalty/intraday/reasons`。
`phaseLabel`（启动/扩散/过热/退潮/中性）为展示标签非状态机；`direction` 为
`up/neutral/down`。日线/横截面不足时打 `qualityFlags`（如 `cross_section_insufficient`）
并保留可算部分（fail-visible，不补零不伪造）。接入 Redis read-through 缓存
（TTL 与 theme-rotation/summary 一致，ingest 时随 dataset 索引失效）。

> ⚠️ v1 题材动量（并入 `resonance.theme`，`themeMomentumScore` 六因子同构）已于
> 2026-08-06 废弃（D2 完全解耦）：`resonance` 回归纯个股六因子，题材动量独立为
> 本接口 + `analysis.themeMomentum`。旧 `resonance.theme` 字段不再产出。

### `POST /api/operations/after-market-once`

> MongoDB 模式下该入口执行 `hotlistSentiment` 日终步骤；以下为迁移前 SQLite/Parquet 历史合同。

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

快照写入成功后的**缓存失效统一由数据层钩子触发**（2026-09-10 重构，见 `backend/data/repositories/snapshot_post_save.py` 与 `backend/services/snapshot_post_save_hooks.py`）：`save_snapshot_ingest`（MongoDB 与 SQLite 两个实现）在返回前调用注册的钩子，默认钩子只剩**快照缓存失效**。钩子异常只记 warning，绝不影响写库结果，也不改写库返回值。

**analyze 产物落库（`snapshot_analysis`）是写路径自身的同步步骤**（2026-09-15 重构）：

- **采集主链**（`snapshot_collector/service.py` `_run_post_persist_chain`，经 `asyncio.to_thread` 在线程池执行）：落帧 → analyze 落库 → 槽位情绪（displayStatus join）→ 当日 EOD 刷新，顺序同步执行；每步失败只记 warning 进 run doc（fail-visible），不阻断采集；
- **本 ingest 路由**（手工/诊断导入）：响应后由 FastAPI `BackgroundTasks` 同步执行逐帧 analyze（`_analyze_ingested_snapshots`），失败只记日志；
- **为什么不再用"数据层钩子 + 后台 worker"**：2026-09-10 曾把 analyze 下移到数据层钩子并交给进程内单线程 worker（`analysis_worker.py`，已退役删除）异步执行——该路径在"落帧完成"与"analyze 落库"之间留 30s~2min 时序空窗，热榜情绪的 displayStatus join 恒 miss（槽位文档长期 100% fallback），盘中 EOD 首算落在空窗内则全天固化 fallback 口径（2026-09-08~09-15 生产实测）。同步链让顺序本身保证正确性；
- **开关**：环境变量 `QUANT_BOARD_SNAPSHOT_ANALYSIS_ENABLED`，默认 `1`（开启）；置 `0` 关闭（情绪计算照常，join miss → fallback 带 warning，fail-visible）；`/api/health` 的 `snapshotCollector.snapshotAnalysis` 可见开关与模式；
- `deduped` 帧跳过（补历史用 CLI `snapshot-analysis-backfill`）；`current_frame` 直接用该 bundle 的 `stockRows` 组装（含 `stocks`，`ranktrend_routes` 依赖 `current_frame["stocks"]`），无需回查库。

正式快照入库要求每个非 `five_minute` frame 至少有一条股票行。若 v4 bundle 中的 `items/records` 热榜为空，或显式 `stockRows` 缺失导致正式 frame 无股票行，接口返回 400，错误信息包含 `formal snapshot hotlist is empty`。历史导入数据中已经存在的空热榜快照仍由回测质量门禁和运行时过滤处理，不通过该正式写入口继续新增。

MongoDB 不可用时接口必须结构化失败，不回退 Supabase/SQLite 并返回 `backup_only`。

### `GET /api/snapshots/analysis`

读取后端持久化的 **analyze 产物**（**顶层字段全集**：`observation` / `resonance` / `technical` / `risk` / `strategy` / `executionStrategy` / `jump` / `decision` / `cycle` / `meta` / `displayStatus` / `themeMomentum` —— 2026-09-10 起不再裁剪落库），供**历史回放/对比**（当前帧仍保留实时 analyze）。仅 MongoDB 生产态有效；非 MongoDB 返回 `degraded=true` 且 `analysis={}`。

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/snapshots/analysis?dataset_id=dragonboard_live&snapshot_id=half_hour%3A2026-04-21%3A10%3A00'
```

查询参数：`dataset_id`、`snapshot_id` 必填；`codes` 可选（逗号分隔，缺省返回该快照全部）。返回 `{ ok, dataset_id, snapshot_id, analysis: { code: {…12 个顶层字段} } }`。

其中 **`displayStatus` 是 `cycle.stage` 的纯投影**（2026-09-10）：`{stage, label, tooltip}`，`stage` 为 5 态之一或 `null`（缺失/非法 → `label="无阶段"`）。**不再有 8 类 label/classKey**；阶段缺失直接体现为 EOD 文档的 `stageCounts.unknown`，`statusSourceCounts.stageMissing` 已删除（详见 `docs/ranktrend/lifecycle-layering-contract.md` 与 `docs/superpowers/specs/2026-09-10-displaystatus-stage-projection-design.md`）。

写入路径：快照入库后的**数据层 after-save 钩子**统一触发（ingest 路由与 collector 直写两条路径一致），属稳定回放口径；历史帧用 `snapshot-analysis-backfill` 补跑（**旧文档字段更少且仍是 8 类投影，必须重跑才切到新结构**）。`cycle` 必须一并落库 —— join 侧与 `stageCounts` 都读 `analysis.cycle.stage`。

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

`projection=ranktrend` 时 `rows/hotlist` 每行返回 `code/name/rank/avgRankNum/change/volumeRatio/zlje/zljzb`；`avgRankNum` 是趋势计算与市场横截面的唯一核心原料（旧 TS attention 口径），`rank/compRank` 只用于池子大小与展示，缺失 `avgRankNum` 的行不参与百分位计算，也不回退到 `rank/compRank`。

`POST /api/ranktrend/analyze` 的市场横截面基准（`marketMedianPercentile/marketMedianShortChange/marketSampleCount`）与共振/趋势百分位均按每帧 `avgRankNum` 升序、代码并列次序重排后计算；`marketSampleCount` 为该帧有效 `avgRankNum` 股票数。

`POST /api/ranktrend/analyze` 使用 Redis 缓存（方案 6.3）：缓存键含 `dataset_id/snapshot_type/frameKeys/codes`、规范化后的 `currentFrame` 与 dataset generation；`currentFrame.slotTime` 会去掉前端自增的 `current:N` 序列号，`stocks` 只保留 `code/rank/avgRankNum` 稳定身份字段，避免面板每次打开因序列号或实时行情字段变化而缓存永不命中。TTL 固定 300s（`RANK_TREND_ANALYZE_CACHE_TTL_SECONDS`），与前端 `rankTrendResultCache` LRU TTL（300s）一致；快照 ingest 递增 generation 并按 dataset 索引失效。命中响应带 `cache.hit=true`。

`POST /api/ranktrend/analyze` 新进热榜股票（历史快照无该 code，2026-08-24）：`currentFrame.stocks` 含量能字段（`turnover/turnoverRate/volumeRatio`，前端已传）时，后端用与历史帧同构的 attention percentile（`attention_rank_lookup` + `percentile_rank`，G3 权威算法）为新股注册**单点序列**，不再整只丢弃——量价/横截可计算，共振/趋势/周期因单点样本走 `sampleQuality.status=insufficient` 降级（fail-visible）；历史已有该 code 的股票仍复用权威历史帧 percentile（修复 A 防漂移口径不变，老股票序列不受影响）。

`POST /api/ranktrend/analyze` 带并发闸门：缓存未命中进入计算前，先按缓存键取 per-key 单飞锁（同 key 并发只计算一次，其余等待后共享缓存结果），再取全局有界信号量（默认 2，环境变量 `QUANT_BOARD_ANALYZE_MAX_CONCURRENCY` 可调），同一时刻最多 N 个 golden 计算并发。目的是防止前端刷新风暴或重复请求把 FastAPI 线程池打满导致 8000 假死；并发上限不改变响应结构与缓存合同。

`POST /api/ranktrend/analyze` 响应帧题材动量（v2，2026-08-06 D2 解耦）：帧级 `themeContext`（`version/factors/marketThemeMedianShortChange/themeSampleCount/qualityFlags/hotThemesFallback`，`factors` 只回传 top-10 题材动量摘要）与 `themeMomentumContext`（`version/factors/qualityFlags/computedAt`，v2 日线动量 Top-20）；每股 `analysis.themeMomentum`（`status/themeId/themeName/score/direction/role/phaseLabel/reasons`，只读投影，第4轨数据源，不参与 decision）。题材动量 v2 由 `backend/analysis/theme/momentum.py` + `daily_series.py` 按交易日聚合成日线序列计算（RPS 5/10/20 / 距年内高点 / 多窗口动量 / 整体性 / 资金量能 / 拥挤惩罚）；`resonance` 回归纯个股六因子，不再含 `theme` 子对象。v1 融合（`resonance.theme.themeMomentumScore`）已废弃。

`hotThemesFallback=true` 表示该帧没有自身的 `hotThemes`（collector 未落库题材因子行），个股题材匹配回退到最近历史帧；此时 `qualityFlags` 追加 `theme_hot_themes_fallback`，`resonance.theme.reasons` 追加同名单（fail-visible，不静默重复题材）。collector 落库的 `snapshot_sector_rows` 含 `rotationState`（生命周期加成/惩罚原料），`snapshot_stock_rows` 含 `themes/mainTheme/themeRole/themeContribution/leadStatus`（角色/贡献按涨跌幅派生落库）。

题材数据链缓存：`ranktrend+themes` 的 `load_frame_bundles`（MongoDB sector/stock rows 读取）走 Redis 读穿缓存（TTL 与快照缓存一致，ingest 递增 generation 并按 snapshot 索引失效）；`compute_theme_momentum_series` 按“帧窗口题材指纹 + generation”缓存 60 秒，不同 codes 共享同一历史帧窗口时复用计算。前端复用 `src/services/LRUCache.ts`：题材映射 10 分钟 TTL、题材热度快照与题材成分股 30 秒 TTL（force 均绕过）。

`frames`、`records`、`stock-rows` 和 `sector-rows` 列表读口可启用 Redis read-through cache。Redis 只缓存查询响应，不替代 MongoDB 事实源；命中时 `source` 仍表示原始事实来源，`cache.hit=true`、`cache.store=redis` 只用于诊断。Redis 不可用时读口直接回 MongoDB。

`rank-series` 使用同一缓存合同。服务日志以 `snapshot_response resource=ranktrend:rank-series cache_hit=<true|false> elapsed_ms=<n>` 记录命中与端到端耗时；Mongo 查询日志记录代码数、返回 bar 数、批量查询、关注度横截面重排和总耗时。API ingest 与后台 snapshot collector 每次成功写入快照事实后都会递增 dataset generation，并按 dataset/date/snapshot 索引失效关联 key，慢读无法在新 generation 中回写旧响应；前端现有 `dataLoader.ranktrendSignal` 仍按 30 分钟轮询读取。

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

`stock-rows` 额外支持投影参数 `fields`（逗号分隔字段名）：指定后后端只返回这些 camelCase 字段（`_id` 不返回），用于大范围全市场横截面读取瘦身；不传时保持原有全量行合同（仅排除 `depth10`）。RankTrend 观察舱按帧市场基准读取即使用 `fields=tradingDate,slotTime,code,avgRankNum`，避免 2 万行全字段响应超过前端读超时。

`stock-rows` 额外支持 `include_analysis=true`（2026-09-21）：把该快照帧在 `snapshot_analysis` 集合已落库的 analyze 产物按 `code` 注入每行 `analysis` 字段，并在响应体返回 `analysisAttached`（成功注入的行数）。用于 Dragon Board 行情列表观察六列（共振/趋势/热度/量价/周期/五维）随帧池种子行**首屏同步投影**，不必等前端异步 signal 增强。fail-visible：无落库产物的行不带 `analysis` 键（不伪造空产物）；SQLite 本地/测试态仓库无 snapshot_analysis 读方法时 `analysisAttached=0` 且不报错。落库产物由采集 after-save 钩子（`save_snapshot_ingest` 共享钩子）与 `snapshot-analysis-backfill` 补跑写入，读口不现算。

**`meta.liveRanking`（2026-09-22 实时口径裁决）**：`POST /api/ranktrend/analyze` 携带 `currentFrame` 时，路由层对 current 帧行调用 `compute_live_ranking`（`analysis/ranktrend/ranking/comprehensive_rank.py`，与采集入库同模块同公式）实时计算 compScore/compRank/avgRankNum/platforms，注入最后一帧 `stocks[].analysis.meta.liveRanking`；均榜输入为 currentFrame 行的八平台 rank 字段（调用方须过滤 ≥999 哨兵），榜单总数由行内每平台最大 rank 推断。该字段**仅存在于实时 analyze 响应**（缓存键含 currentFrame 指纹）；`snapshot_analysis` 落库产物与历史帧查询保持帧内稳定口径、不含 liveRanking。Dragon Board 列表均榜/综合两列以此为权威 live 面，帧池 golden 降级为 analyze 不可用时的历史回溯兜底。

Dragon Board `snapshotFacade.listSnapshots/getSnapshotById/listSnapshotFrames/listSnapshotStockRows/listSnapshotSectorRows/getStockVolumeHistory`
均通过这些 MongoDB 明细读口实现。列表读口返回 `cache` 诊断字段，单条 `records/{snapshot_id}` 仍直接读取 MongoDB。`getStockVolumeHistory` 固定读取 `daily` 的
`snapshot_stock_rows`，不再扫描浏览器 IndexedDB 原始快照。

### `GET /api/ranktrend/rank-series`

RankTrend 专用排名时序读口，按 `code + snapshotType` 读取单票历史窗口，避免被最近全局快照帧截断。

**查询参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dataset_id` | string | 默认数据集 | 数据集 ID |
| `snapshot_type` | string | `half_hour` | 快照类型（`quarter_hour`、`half_hour`、`hourly`、`daily`） |
| `codes` | string | 必填 | 股票代码，逗号分隔；空值返回 400，禁止全历史扫描 |
| `trading_date` | string | — | 交易日过滤（同 start_date 和 end_date） |
| `start_date` | string | — | 起始交易日 |
| `end_date` | string | — | 结束交易日 |
| `before_trading_date` | string | — | 严格早于指定交易日 |
| `allowed_capture_modes` | string | — | capture mode 过滤，逗号分隔 |
| `exclude_restored` | bool | `false` | 排除 restored 快照 |
| `sort` | string | `asc` | 排序方向 |
| `limit` | int | `50` | 返回帧数量上限 |
| `window_bars` | int | — | 单票 bar 数量上限（新增，独立于 limit） |
| `rank_basis` | string | `composite` | `composite` 返回原始综合排名；`attention` 仅在 MongoDB 主库内按有效 `avgRankNum ASC, code ASC` 重排，返回均榜关注度排名。无有效 `avgRankNum` 的股票不返回 bar，绝不回退到综合排名；非 MongoDB 环境请求该口径返回 `503`。 |

后端执行一次 `code: {$in: [...]}` 聚合，并在 MongoDB 内按 code 分区保留最近 `window_bars`，不会为每只股票发起独立查询，也不会把全部历史行传入 Python 后再截断。attention 横截面按组合索引排序后流式编号，不使用 `$group + $push + $unwind` 物化整帧数组。`series.bars` 只返回 `snapshotId/timestamp/type/tradingDate/slotTime/captureMode/code/rank/totalCount`；完整股票原始行仍通过 `/api/snapshots/stock-rows` 读取。

**响应结构：**

```json
{
  "ok": true,
  "dataset": { ... },
  "datasetId": "...",
  "snapshotType": "half_hour",
  "rankBasis": "attention",
  "frames": [
    {
      "snapshotId": "half_hour:2026-04-21:10:00:xxx",
      "displayKey": "[半小时快照] 2026-04-21 10:00",
      "timestamp": 1776746400000,
      "type": "half_hour",
      "tradingDate": "2026-04-21",
      "slotTime": "10:00",
      "captureMode": "real_time",
      "totalCount": 200,
      "ranks": { "600001": 5, "600002": 8 }
    }
  ],
  "marketFrames": [
    {
      "snapshotId": "half_hour:2026-04-21:10:00:xxx",
      "timestamp": 1776746400000,
      "type": "half_hour",
      "tradingDate": "2026-04-21",
      "slotTime": "10:00",
      "captureMode": "real_time",
      "totalCount": 200,
      "ranks": {}
    }
  ],
  "series": {
    "600001": {
      "code": "600001",
      "bars": [
        {
          "snapshotId": "half_hour:2026-04-21:10:00:xxx",
          "timestamp": 1776746400000,
          "rank": 5,
          "tradingDate": "2026-04-21",
          "slotTime": "10:00"
        }
      ],
      "totalCount": 120,
      "latestSnapshotId": "half_hour:2026-06-14:14:30:xxx",
      "latestTradingDate": "2026-06-14",
      "latestSlotTime": "14:30"
    }
  },
  "count": 8,
  "source": "mongodb"
}
```

- `frames` 保持向后兼容，每帧含 `ranks` 映射（code → rank）；它来自 per-code 窗口的并集，不能作为全市场时间轴。
- `marketFrames` 是不受 `codes` 过滤影响的正式全市场 frame 元数据，按时间升序返回最近 `limit` 个槽位。RankTrend 仅用它做市场时间轴与样本质量判断，质量异常必须作为结构化状态暴露，不能阻断原始数据或抹成全零结果。
- `series` 为新增 per-code 窗口，以 code 为主键，`bars` 按时间升序排列
- `window_bars` 控制单票取 bar 数量上限，未指定时使用 `limit` 值
- 当 `series` 中无匹配 codes 数据时，前端自动回退到 `frames` 扫描路径

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
- `dryRun=true` 只返回会生成的数据集摘要和质量门禁结果，不落库；返回对象带 `virtual=true`、`policy=snapshot_facts_view`。
- `dryRun=false` 会复制筛选后的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows` 到新的 `ds_*` 派生数据集；源数据集不被删除、覆盖或改写。
- 真实生成结果返回 `policy=snapshot_facts_derived_dataset`，元数据中的 `metadata.sourceDatasetId` 和 `metadata.filters` 记录来源数据集、快照类型、日期区间和最大快照数。
- `mongodb_snapshots` / `sqlite_snapshots` 生成派生研究数据集时不产生新的 Supabase 备份对象。

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

`snapshot_stock_rows` 读写保持 camelCase 合同，涨停池复盘字段会随 `/api/snapshots/stock-rows` 返回，包括 `reason`、`firstZtTime`、`lastZtTime`、`boardHeight`、`highDays` 和 `fengdan`。迁移前 SQLite/Supabase 历史链路使用对应 snake_case 列保存 `reason`。

排名字段合同包括 `rank/compRank/platforms/avgRank/avgRankNum` 和 `emRank/thsRank/kplRank/tdxRank/xqRank/clsRank/tgbRank/dzhRank`。历史后端采集器快照若仅保留严格连续且唯一的 `rank=1..N`，可用以下脚本精确回填 `compRank=rank`；默认 dry-run，只有 `--apply` 写库：

```powershell
.\.venv\Scripts\python.exe scripts\backfill_snapshot_rank_fields.py --dataset-id dragonboard_live --dry-run
.\.venv\Scripts\python.exe scripts\backfill_snapshot_rank_fields.py --dataset-id dragonboard_live --apply
```

该脚本只处理 `source=quantboard_backend_collector`，逐槽验证股票代码唯一和排名连续性。缺少每只股票当时的各平台原始名次时，不能从榜单固定容量反算 `platforms/avgRank/avgRankNum`，脚本不会伪造这些字段。

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

### `GET /api/themes/stock-volume-series`

题材成分股成交量/成交额槽位聚合序列，服务 Dragon Board 题材详情面板"历史趋势"页签（前端装配层 `src/services/theme/themeHistorySeries.ts`，与 `/api/snapshots/sector-rows` 两源并行、按 timestamp 对齐）。聚合对象为 `snapshot_stock_rows`（`themes` 题材名数组等值匹配 = 元素包含语义），`$group` 按 `tradingDate + slotTime + timestamp` 输出 `totalVolume/totalAmount/stockCount`，并附 `volumeCount/amountCount`（组内可加数值行数）——某槽位全缺时 MongoDB `$sum` 语义为 0，消费方以对应 count 是否为 0 区分"真实 0"与"缺失"，缺失在前端保持 `null` 不伪造曲线。

- 参数：`theme_name`（必填，空返回 400 `theme_name_required`）、`dataset_id`（默认 `dragonboard_live`）、`snapshot_type`/`types`（逗号分隔，对应 `_snapshot_row_query` 的 `$in` 语义）、`trading_date`（优先于区间）、`start_date`/`end_date`、`limit`（默认 2000，上限 20000）。
- 仅 MongoDB 主链提供：`storage_backend != mongodb` 一律返回 503 `storage_unavailable`（守卫只看 storage label 不看 `db` 是否为 None——sqlite 模式 `get_db` 会给出 session，而 SQL Repository 没有该聚合方法，落过去会变成 AttributeError 500 而非结构化 503）。
- 实测性能（2026-09-05）：2 个月窗口 494 行 0.6~1.1 秒，暂无需额外索引。

### `GET /api/themes/counts`

读取 MongoDB 题材基础集合行数，用于迁移验收和排障。返回 `ok`、`source=mongodb` 和 `counts`；`counts` 至少包含 `themeCount`、`mappingCount`、`stockCount`、`version`、`lastUpdate`、`source=mongodb`。

### `GET /api/themes/heat?force=false`

返回基于 MongoDB 全市场题材映射计算的 `theme-market-v2` factors（`heatScore` 为 KPL 人气总和绝对值；自 2026-09-03 起每个 factor 另带 `heatLevel`——0-100 rank 百分位相对分，热度缺失时为 `null`，不伪装 0；响应顶层与 factor metadata 携带 `factorVersion` 口径标记）。基础行情固定使用腾讯批量行情（50 只/批、有限并发、默认整次预算 90 秒）；资金字段来自两层来源：① 题材估算层（2026-09-29 用户确认切换：默认东财 push2 主力资金 `eastmoney_main`，`ulist.np` 批量直连、不走 akshare；`QUANT_BOARD_THEME_FUND_SOURCE=akshare` 回退同花顺网页口径 `akshare_ths_individual`；`QUANT_BOARD_THEME_FUND_SEED_ENABLED=false` 停用估算层刷新，冷启动改从 MongoDB `fund_flow_l2` 恢复最近交易日 L2 行（零第三方请求））；② 盘中由 `mainMonitorDetail`（`ths_main_monitor`，L2 口径）按展示池逐票校准覆盖。题材估算源行只供题材聚合（不进行情主页资金列白名单），低 rank 不覆盖高 rank。服务端复用最近行情快照，资金 version 变化只重算题材资金聚合，不重新请求全市场行情。`force=true` 跳过行情缓存。公开响应不包含全市场逐股 quote/fund map。heatLevel 解释与消费统一走 `backend/analysis/theme/heat_level.py` `resolve_heat_level`。

⚠️ 口径说明：运行态资金列当前由两层组成——种子层取东财排行接口主力净流入（`eastmoney_seed`，= 超大单 + 大单净流入，与 L2 `mainMonitorDetail` 的 `mainbuy − mainsell` 近似，实盘验证差异远小于同花顺网页口径）；权威层取 `mainMonitorDetail` L2 口径（`ths_main_monitor`）。**历史快照/旧缓存中的 `ths_web_seed` 行是同花顺网页口径**（`净额 = 主力流入 − 主力流出`），该口径与 L2 **不等价**——同一交易日同一只票两者数值甚至符号都可能不同（实测 300720 分别为 +1.245 亿 与 −0.831 亿）。因此运行态资金字段与历史快照中旧口径的 `zlje/mainNetInflow` 不可直接混算或跨口径比较。

当腾讯覆盖率低于门槛时不整段 `503`（fail-visible）：接口返回 `200`，`data.degraded=true`，`data.quality.errorCode=quote_coverage_blocked` 并携带覆盖率/返回数等结构化原因；因子保留已计算部分，但 `rank=0`、`rankEligible=false`，由前端展示可计算数据和缺失原因。只有题材映射本身为空（`mapping_empty`）这类"全源无数据"情形才返回结构化 `503` 并携带 `staleData`。未覆盖资金的股票不按零值聚合，相关 `fundScore/mainNetInflow` 保持空值。

### THS 主力资金运行态接口

- `GET /api/big-order/ths-detail?stockCode=002297`：返回单票 THS 原始明细，供 `tools/THSBigOrder` 使用；缓存命中时通过 `fetchedAt`、`servedAt` 和 `data.dragonMeta.cache.uiStale` 标识时效。上游成功刷新后同步归档到 `quant-board/data/big-order/ths/<sessionDate>/<stockCode>.json.gz`。**查看即刷新（2026-08-11）**：拿到有效 `mainbuy/mainsell` 摘要时同步写入 `theme-fund:v3:latest` 资金列——调度器只刷 fund-stream 订阅池（前端行情列表全部 codes），用户查看的非订阅池个股资金列会停留在 MongoDB 恢复的历史旧值，此入口保证"看到即最新"；解析失败保留 last-good，不影响明细返回。
- `GET /api/big-order/ths-fund-batch?codes=000001,600000&concurrency=2`：按最多 5 只股票返回标准化 `zlje`、`sessionDate` 和逐票失败；并发限制在 1 到 2。**查看即刷新**：rows（摘要行）批量同步写入 `theme-fund:v3:latest`。
- `GET /api/themes/fund-rows?codes=000001,600000`：只读 Redis last-good 的诊断接口，不触发上游请求。

全市场刷新周期只有一个旋钮：东财模式 `QUANT_BOARD_THEME_FUND_EM_REFRESH_INTERVAL_SECONDS`（默认 1800 秒）。**2026-10-19 用户决定删除 akshare 同花顺网页回退源**（akshare 被风控限流），`QUANT_BOARD_THEME_FUND_SOURCE` 只接受 `eastmoney`，写 `akshare` 会告警并固定走东财档位（原 `QUANT_BOARD_THEME_FUND_REFRESH_INTERVAL_SECONDS` 已删除）。题材估算层默认由 `EastmoneyFundProvider` 请求东财 `push2.eastmoney.com/api/qt/ulist.np/get` 批量拉取（800 只/请求、全市场约 7 批，httpx 独立 URL 直连、不走 akshare）：**风控纪律（防封 IP，社区实测阈值校准，详见 docs/eastmoney-fund-source.md）**——全程串行无并发、Keep-Alive 复用连接（连接重建频率本身是风控指纹）、相邻请求发起间隔 ≥60s+随机抖动（分钟级摊开，任意 1 分钟窗口最多 1 个请求）、UA/Referer 请求级注入、命中 429/403/5xx/断连立即中止剩余批次（`truncated_by` 结构化上报，调度器熔断 1800s 不反复刺激 WAF）、连续 3 批失败中止、单批超时只记批级 failure 继续；刷新周期 30 分钟（轮内约 6 分钟完成、其余静默），夜间/周末零请求（仅进程启动预热、或题材缓存缺失冷启动时例外一轮）；universe 取自腾讯全市场行情缓存（零额外上游请求）。东财限流/风控错误映射 `em_rate_limited`/`em_upstream_unavailable`，超时映射 `em_timeout`，调度器进入熔断并保留 last-good。可覆盖：`QUANT_BOARD_THEME_FUND_EM_BATCH_SIZE`（默认 800，下限 50）、`QUANT_BOARD_THEME_FUND_EM_REQUEST_INTERVAL_SECONDS`（默认 60，下限 30）、`QUANT_BOARD_THEME_FUND_EM_REQUEST_TIMEOUT_SECONDS`（默认 15）、`QUANT_BOARD_THEME_FUND_EM_REFRESH_INTERVAL_SECONDS`（默认 1800，下限 600）。同 sessionDate 下 rank 高者权威（题材 hash 内 eastmoney > akshare）：**当日盘中切回 akshare 不会覆盖当日已写入的东财行，切源需跨交易日生效**，调度器 status 以 `provider_source_stale_rows` 暴露行源不一致。展示池 L2 校准由 `ThsFundRefreshScheduler` 完成（**均匀轮转，2026-08-11 方案 A，用户确认**：去 P0/P1 分级，全列表统一 `refresh_interval_seconds`（默认 180 秒），每批 ≤5 只、并发 ≤2、批次间按 `batch_interval_seconds` 自然错峰——列表内数据时效一致，避免综合排名对比时新旧混杂；单票失败退避、系统性限流全局冷却 30 秒 + 并发降 1、连续 3 批成功恢复并发 2）。**刷新范围（2026-08-11 用户确认，取消热度池）**：universe = 前端 fund-stream 订阅池 = **行情列表全部股票**（前端 `dataLayer.getStocks()` 合并后的完整展示列表，不再按热榜 codes 过滤）——行情列表显示的任何票都无条件在刷新范围内，全量轮转覆盖；**不再有后端独立热度池**（`hotlist_pool_codes`/`base_pool` 已移除）。owner 持久化：浏览器断开后按最后已知池继续刷新（`ownerState`：active/persisted/none）；交易日时段策略：周一至周五 09:30-11:30、13:00-15:00 正常轮转，非交易时段已初始化则暂停（保留 last-good），冷启动例外（从未刷过/缓存非最近交易日）允许非交易时段刷一轮拿最近交易日 L2——**该轮只写 Redis 热缓存（首屏不空），不写 MongoDB**（MongoDB 只固化交易时段数据，避免非交易日垃圾文档）。**MongoDB 故障隔离**：页面展示走 Redis/进程内 last-good（不经过 MongoDB），MongoDB upsert 失败/挂起仅记日志（`mongo_write_timeout_seconds` 默认 5 秒超时，不拖慢刷新节奏）。状态见 `/api/health` 的 `thsFundRefresh`。**2026-08-11 首屏链路修复**：`fund_full_state` 快照与 `fund_patch` 只下发**最近交易日**行（`sessionDate == 最近工作日`）——Redis 旧交易日行（TTL 7 天不清）不再随快照下发，旧票资金列显示 `-`（等待刷新）而非过期累计值；配合调度器轮转（约 10 分钟全列表补齐）与查看即刷新（点击/THSBigOrder 经 ths-detail 拉当日值并 publish）。**2026-08-11 审计加固**：非交易时段一觉睡到下一开盘（跨午休/周末，不再每小时空转）；冷启动判定结合 Redis 缓存（**仅当缓存 sessionDate == 最近交易日**才算已初始化，旧交易日缓存仍触发冷刷，修复盘后重启显示旧值）；stale raw（上游失败回退的旧缓存）只写 Redis 不写 MongoDB；`fund_flow_l2` 唯一索引改为首次 `run_once` 异步 ensure（不再同步阻塞启动）；查看即刷新（`ths-detail`/`ths-fund-batch`）写缓存后 publish 到 fund-stream，前端**即时收到** fund_patch 无需刷新页面。按需 THS 明细接口仍可用 `QUANT_BOARD_THEME_FUND_CONCURRENCY`、`QUANT_BOARD_THEME_FUND_UPSTREAM_TIMEOUT_SECONDS` 和 `QUANT_BOARD_THEME_FUND_THS_UPSTREAM_URL` 覆盖；默认分别为 2、15 秒和 THS `mainMonitorDetail` 官方地址。

资金流 provider（`AkshareFundProvider`，**2026-10-19 起已不被调度器选中，模块按用户要求保留**）抓取期间会强制 `getaddrinfo` 优先返回 IPv4 记录，并给 akshare 内部的 `requests` 调用注入单请求超时（默认取 `QUANT_BOARD_MARKET_FUND_FETCH_TIMEOUT_SECONDS` 的一半、上限 30 秒）。原因：`data.10jqka.com.cn` 在本机 IPv6 链路存在 TCP 可建连但数据被黑洞的问题，akshare 自身 `requests.get` 不带 timeout，上游挂起会让线程无限堆积并饿死调度器；IPv4 优先 + 超时双保险后，超时统一映射为 `ths_timeout` 进入熔断重试。

该资金缓存（进程内 `ThemeFundCache`，last-good）只服务 Dragon Board 运行态行情列表和题材分析；快照采集器只接受 `ths_main_monitor`（L2 权威）行带入 snapshot stock rows，`ths_web_seed`/`eastmoney_seed` 估算种子行不进入正式快照。正式 RankTrend、回测、优化和历史数据集入库不把它当作历史资金口径；后端重启后冷启动从 MongoDB `fund_flow_l2` 恢复最近交易日 L2 行（零第三方请求），盘中 `ThsFundRefreshScheduler` 继续校准覆盖；MongoDB 不可用时前端保留 last-good 展示。

**Redis 持久化（2026-08-08）**：本机 Redis 8.10.0 已开启 RDB 自动保存 `save 900 1 300 10 60 10000`（900 秒内 ≥1 写 / 300 秒内 ≥10 写 / 60 秒内 ≥10000 写即 BGSAVE），`appendonly no` 保持关闭（RDB 即可满足冷缓存快速恢复；若要求分钟级更新零丢失再单独评估 AOF）。Redis 重启/崩溃后自动从 `dump.rdb` 读取磁盘冷缓存快速恢复内存状态，前端无需等重新填充；崩溃最多丢约 60 秒数据。Redis 故障时进程内 last-good 仍兜底展示，不阻断数据链路。**清理策略（2026-08-11 用户确认，容灾 1 个交易日）**：① `theme-fund:v3:latest` 资金行缓存每次写入按 `sessionDate` 主动清理旧交易日行（Redis 只保留最近 1 个交易日，避免旧累计值滞留），TTL 兜底 3 天（`QUANT_BOARD_THEME_FUND_CACHE_TTL_SECONDS`，覆盖跨周末 72h）；② `theme-fund:v3:version` 与 latest 同生命周期（3 天 TTL，停止写入后重置）；③ `ths-main-monitor:raw:*` 明细缓存加 3 天 TTL；④ `snapshot:generation:*` 缓存失效标记加 7 天 TTL（此前 57 个永久累积）；⑤ **启动时 `prune_legacy_redis_ttl` 一次性给存量永久 key 补 TTL**（raw/generation/version，best-effort 不阻塞启动）。**环境修复（2026-08-11）**：Redis `stop-writes-on-bgsave-error` 曾导致写命令被禁用（MISCONF，"永远旧数据"直接根因）——已 `CONFIG SET stop-writes-on-bgsave-error no` 恢复写入；RDB `dir` 配置与运行态不一致（`/Redis-8.10.0`）导致 BGSAVE 失败，需重启 Redis 加载正确 `dir` 配置后 RDB 持久化恢复（数据有 MongoDB `fund_flow_l2` 长期归档兜底）。

### fund_flow_l2 持久化（2026-08-08）

MongoDB 集合 `fund_flow_l2`（仅 `QUANT_BOARD_STORAGE_BACKEND=mongodb` 模式启用）：一行一股一日，唯一索引 `{sessionDate, code}`。文档含 `total`（`mainMonitorDetail` title 摘要：`zlje = mainbuy − mainsell`、`buyAmount`、`sellAmount`）与 `buckets`（7 档逐笔聚合，按 `data.list` 的 `money` 分档、`tradetype` 1=买 2=卖：`ge_1000w`/`700_1000w`/`500_700w`/`300_500w` 大单系、`100_300w` 中单、`50_100w`/`30_50w` 小单，每档 `buyCount/sellCount/buyAmount/sellAmount/net`，低于 30 万不入档）。写入：`ThsFundRefreshScheduler` 每只 `load_raw` 一次拉取 → `parse_l2_summary` 写 Redis 行 + `aggregate_l2_buckets` 写 MongoDB（异步 `to_thread` upsert，不阻塞 180 秒刷新循环，盘中异动随轮转滚动覆盖）。**2026-08-11 实盘复盘加固**：① 每批写入后 `MarketFundStream.publish` 推送 `fund_patch` 到浏览器（此前只靠 300s idle 断线重连拿快照，前端滞后 ≤5 分钟）；② upsert 带 `sourceTs` 条件（旧写不覆盖新写，防 MongoDB 慢时后台旧线程回退数据）；③ THS `list` 为空（buckets 全 0）时跳过 Mongo 写入（防全 0 覆盖历史 7 档），Redis total 摘要照常落库；④ 单票落库被拒时回滚常规刷新周期，让 30 秒退避真正生效。读取：`backend/main.py` `on_startup` 的 `restore_fund_flow_from_mongodb()`（mongodb 模式）投影最近交易日 `total.zlje` → `ThemeFundCache.put_many`。设计见 `docs/theme-module/2026-08-08-fund-flow-l2-mongodb-persistence-design.md`。

### proxy-server 迁移接口（akshare）

以下路由已从 Node proxy-server 迁到 QuantBoard，proxy 仅按前缀转发到本服务（`/api/market/`、`/api/quotes/`）。

- `GET /api/quotes/tencent?codes=000001,600519`：行情数据，返回 `{rc, data: {diff: [...]}}`，
  字段沿用旧 f 合同（f12/f14/f2/f3/f6/f5/f8/f9/f10/f20/f21/f23），供前端 QuoteHttpFeed 直接消费。
  数据源为 akshare `stock_zh_a_spot_tx()`（腾讯全市场排名，一次约 5000+ 只），由后台任务周期刷新
  （`QUANT_BOARD_MARKET_QUOTES_REFRESH_INTERVAL_SECONDS`，默认 300 秒、下限 60 秒），
  进程内 last-good：上游失败保留上一份并记录错误，不返回伪造零值。`/api/quotes/sina` 同源别名。
- `GET /api/market/overview`：指数大盘概览，数据源为 akshare `stock_zh_index_spot_sina()`（新浪指数实时，
  约 562 个指数，进程内 10 秒缓存），返回 `{ok, source, timestamp, stale, items: [...]}`；
  上游失败返回结构化 `503` 并携带 `staleData`（如有上次成功结果）。

说明：不使用东财行情/资金接口（限流与风控）；东财热榜不在迁移范围，仍由 proxy-server 直连。

#### 热榜、涨停池、异动与情绪（Batch 2）

以下路由同样已迁到 QuantBoard（proxy 按前缀转发），响应结构保持与旧 proxy 一致，前端 adapter 无需改动：

- `GET/POST /api/{platform}/hot`（platform ∈ xueqiu/cls/eastmoney/ths/kpl/tdx/tgb/dzh）：八平台热榜，
  httpx 直连原上游（雪球需 `XUEQIU_COOKIE`，财联社沿用 sha1+md5 签名，东财热榜继续直连），
  进程内 60s TTL 缓存，上游失败返回 last-good 或平台空壳降级。
- `GET /api/limitup/10jqka?date=YYYYMMDD`：同花顺涨停池，httpx 直连 10jqka dataapi（需浏览器 UA），
  30s TTL 缓存；非交易日或无数据时按旧合同降级为 `{data:{info:[]}}`。
- `GET /api/limitup/ths/pools?date=YYYYMMDD`：同花顺细分涨停池（一板/二板/三板/四板/高位/炸板/冲板/炸板大单回撤），
  8 路并行抓取，结构 `{ok, degraded, date, timestamp, pools, errors}`。
- `GET /api/surge-stock/performance`：昨日涨停/异动股表现（选股宝 flash-api 直连，30s 缓存）。
- `GET /api/sentiment/composite`：聚合 overview + 涨停池 + 异动，任一腿失败置 `degraded=true` 并保留其余可计算部分。

配置：`XUEQIU_COOKIE` 统一放在 `quant-board/.env.local`（settings 启动时自动加载），
也支持环境变量 `XUEQIU_COOKIE` / `QUANT_BOARD_XUEQIU_COOKIE` 覆盖。

#### 选股宝事件与大单监控（Batch 3）

- `GET /api/xuangubao/events?count=&types=`：选股宝异动事件，双 host 容错直连，默认事件类型集合与
  count 上限（100/200）同旧 proxy；返回 `{ok, source, data, upstreamCode, timestamp}`，30s 缓存。
- `GET /api/big-order/main-monitor?stockCode=&limit=&money=&index=`：龙虎榜大单分页
  （`apphwhq.longhuvip.com` GetMainMonitor_w30，单页 200，内部拆页），返回未包裹的
  `{errcode, Total, List}`（List 元素 `[type, orderId, volume, amount, price, time]`）。
- `GET /api/big-order/all-day?stockCode=&money=`：全天大单，分页重建 + 60s 进程内缓存 + last-good，
  返回 `{List}`；上游失败按旧合同降级为 `data:{List:[]}`。

说明：龙虎榜盘后归档/采集（`/api/big-order/longhu/*`）仍保留在 proxy-server（内部工具链，Batch 4 再定去向）；
deprecated 题材路由（`/api/theme/:id`、`/api/themes/batch`）已随 Batch 3 删除，前端无引用。

Batch 4（2026-08-01）收尾：proxy-server 最终形态确认为「本地服务壳 + `/api` 转发」，
前端/采集器 baseURL 与启动器不变（快照采集器仍以 `http://127.0.0.1:3000` 为入口）；
已删除无引用死代码 `/api/quotes/tencent/spk` 与 `/api/snapshots/remote/*`
（`snapshotRemoteRoutes.js` 未挂载的遗留 WebDAV 实现）。

### `GET /api/themes/heat/{theme_id}/stocks`

返回指定题材的全市场成分股详情，支持 `offset`、`limit`、`sort_by` 和 `descending`。该接口是 Dragon Board 详情、树形列表和联动分析的正式读口，不从八平台热榜股票池反推成分股。

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

## 交易日记与候选池接口

Dragon Board 候选池复用 QuantBoard journal 存储。候选记录使用 `trade_type=thesis`；交易池 V2 使用同一 MongoDB `trade_journal` 集合中的 `trade_type=trading_pool` 记录，并通过顶层 `candidate_entry_id` / `candidateEntryId` 指向来源候选 thesis。真实历史交易继续只使用 `trade_type=entry` 和 `trade_type=exit`。

### `POST /api/journal/entries`

创建交易日记或候选池记录。候选池入池时至少提交：

```json
{
  "stock_code": "000001",
  "stock_name": "平安银行",
  "direction": "buy",
  "trade_type": "thesis",
  "status": "candidate",
  "price": 0,
  "volume": 0,
  "signals_snapshot": {
    "candidateAnalysis": {
      "version": "candidate-rules-v1",
      "score": 82,
      "grade": "A"
    }
  },
  "entry_reason": "规则分析生成的入池理由",
  "trade_hypothesis": "3-5 天候选跟踪假设",
  "entry_prerequisites": "买入前提",
  "invalidation_rules": "失效条件",
  "expected_holding_days": 3,
  "human_decision": "watch",
  "review_tags": ["A", "B_IGNITION", "主线题材"]
}
```

响应仍返回 camelCase 字段，例如 `stockCode`、`signalsSnapshot`、`tradeHypothesis`、`reviewTags`。创建候选时 `review_tags` 必须入库，后续候选过滤和复盘统计会依赖这些标签。

创建交易池 V2 记录时至少提交：

```json
{
  "stock_code": "601208",
  "stock_name": "东材科技",
  "direction": "buy",
  "trade_type": "trading_pool",
  "candidate_entry_id": "tj_thesis_1",
  "status": "观察买点",
  "signals_snapshot": {
    "tradingPool": {
      "version": "v2",
      "code": "601208",
      "name": "东材科技",
      "status": "观察买点",
      "decision": "enter",
      "reasons": ["signal_resonance"],
      "signalSnapshot": {},
      "dataQuality": "fresh",
      "lastRecomputedAt": "2026-06-14T12:00:00.000Z"
    }
  }
}
```

`trading_pool` 不是历史成交；`status=已介入` 只表示交易池工作台内的人工确认，不会生成真实 `entry` 记录。

### `GET /api/journal/entries`

读取 journal 记录，支持 `stock_code`、`trade_type`、`direction`、`status`、`candidate_entry_id`、`date_from/date_to`、`review_tags`、`limit`、`offset`。候选池面板固定读取 `trade_type=thesis`；交易池面板固定读取 `trade_type=trading_pool`，可附加 `candidate_entry_id` 精确定位，不读取 `entry/exit` 历史交易。

### `PUT /api/journal/entries/{entry_id}`

更新记录。候选池当前主要用于推进 `status`，也可更新 `review_tags`、`signals_snapshot`、`trade_hypothesis`、`entry_prerequisites`、`invalidation_rules`、`review_outcome`、`model_result`、`execution_result` 等复盘字段。交易池 V2 更新只写 `trade_type=trading_pool` 记录的 `status` 与 `signals_snapshot.tradingPool`，不得修改真实历史 `entry/exit` 记录。

V2 Layer 3 新增 7 个执行字段（与回测信号对齐）：
- `entryPrice` (float)：实际买入价
- `entryTime` (str, ISO 8601)：实际买入时间
- `exitPrice` (float)：实际卖出价
- `exitTime` (str, ISO 8601)：实际卖出时间
- `stopLossPrice` (float)：止损线
- `takeProfitPrice` (float)：止盈线
- `positionPct` (float)：仓位占比

这些字段在 `POST /api/journal/entries` 创建和 `PUT /api/journal/entries/{entry_id}` 更新时均可选传入。

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
  "excludeNonPositivePriceRows": false,
  "excludeCrossMarketZeroPriceRows": false,
  "excludeAllZeroPriceFrames": false,
  "momentumPeriods": [3, 5, 8, 13, 21],
  "macdFast": 21,
  "macdSlow": 34,
  "macdSignal": 13
}
```

返回会包含 `runId`，并把完整结果落库到 `backtest_runs`。MongoDB 模式下完整结果优先写入 `resultCompressed` 可逆压缩字段；如果压缩后仍超过安全阈值，则拆入 `backtest_result_chunks`，读取层透明拼接并还原。为避免真实数据集响应过大，接口默认只返回轻量摘要、前 120 条 `signals` 预览、交易/权益预览和 `strategyDecisions` 帧计数，完整结果通过 `runId` 追溯。报告会包含 `researchDiagnostics`，用于展示 1/2/5 bars 后验表现、市场环境和生命周期下的候选分层分布、展示状态分布及对照组表现；该字段只作为研究诊断，不会自动写回默认参数。

`excludeNonPositivePriceRows` 默认关闭。显式设为 `true` 时，服务会在 RankTrend replay 前剔除每个 frame 中 `price <= 0` 或无法解析为正价格的股票行，并把统计写入 `dataQuality.runtimeFilter.priceFilter`。该字段仅用于研究复跑和质量诊断，不修改 MongoDB 源快照事实，不代表默认 formal quality gate。

`excludeCrossMarketZeroPriceRows` 与 `excludeAllZeroPriceFrames` 也默认关闭。前者只过滤带零行情形态的跨市场/非 A 股热榜条目，并把统计写入 `dataQuality.runtimeFilter.crossMarketPriceFilter`；后者只剔除整帧股票行价格全为 `0` 或不可解析的异常快照，并把统计写入 `dataQuality.runtimeFilter.allZeroPriceFrameFilter`。两者都只用于 Phase 12 价格质量归因研究，不修改 MongoDB 源快照事实，不改变默认回测口径。

默认回测还会输出只读价格质量诊断，不触发过滤、不写入 warnings、不改变 `severity` 或 `researchGrade`。字段位于 `dataQuality.reportOnlyDiagnostics.priceQuality`，包含 `crossMarketZeroPriceRows`、`allZeroPriceFrames` 和 `partialAshareZeroPriceRows`，用于后续长测 checkpoint 观察价格污染来源。

`dryRun`（2026-09-23 引擎提速立项层 2）默认 `false`，正式回测与既有 API 合同不变。显式设为 `true` 时跳过五表落库（`backtest_runs` / `backtest_trades` / `backtest_equity_curve` / `backtest_signals` / `backtest_quality_reports`）与 `result_json` 大 JSON gzip 序列化；响应 `dryRun=true`，`runId` 仅为响应标识、不可追溯（不落库），全量 `trades` 与 `equityCurve` 直接随轻量摘要返回（不做 120 条截断），notes 显式说明未落库。全量返回仅限顶层 `trades` 与 `equityCurve` 两键；其余归因列表（`tradeEvents`、`roundTripTrades`、`openPositions`、`tradeSimulation` 内层列表）仍为 120 条预览。该开关供 harness / 隔离扫描 runner（`exit-scan-trial-runner.py --dry-run`）使用，优化链接入预留；分析脚本从响应体取 trades 归因，而不是读 Mongo。

### `GET /api/backtests/{run_id}`

读取兼容回测报告。SQLite 模式读取 `backtest_runs.result_json`；MongoDB 模式读取 `backtest_runs.resultCompressed`，或在 `resultChunked=true` 时读取 `backtest_result_chunks` 后透明拼接解压；旧 `result` 子文档仅作为兼容字段。新页面需要完整交易、权益曲线、信号和质量报告时，应继续调用下列归一化结果端点。

### `GET /api/backtests/{run_id}/report`

读取回测报告，和 `GET /api/backtests/{run_id}` 同口径，供页面语义化调用。

### `GET /api/backtests/alignment`

Layer 3 实盘对齐端点。交叉比对 `trade_journal` 执行记录与 checkpoint 回测信号。

请求参数：
- `checkpoint_id` (必填)：长测 checkpoint ID
- `start_date` (可选)：过滤 trade_journal 日期范围起
- `end_date` (可选)：过滤 trade_journal 日期范围止

返回：
```json
{
  "checkpointId": "checkpoint_2026-05-29",
  "journalExecutedCount": 5,
  "signalCodeCount": 2338,
  "intersectionCount": 3,
  "intersectionCodes": ["000001", "600519", "300750"],
  "intersectionPnl": 1250.0,
  "intersectionPnlPct": 0.0125,
  "sufficientSample": false,
  "alignmentStatus": "insufficient_data"
}
```

- `alignmentStatus`: `"sufficient"` (≥10 笔执行记录) / `"insufficient_data"` (<10) / `"unavailable"` (journal 不可用)
- 依赖 MongoDB `trade_journal` 集合。非 MongoDB 存储返回 `unavailable`

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

### `GET /api/backtests/{run_id}/fusion-projections`

读取 fusion 候选池历史投影，当前策略锚点固定为 `ranktrend_early_big_move_v3_lifecycle_fusion`。

用途：

- 给 Dragon Board / QuantBoard 候选池历史视图提供统一的 `FusionStrategyProjection` rows。
- 用 `backtest signals + tradeSimulation.roundTripTrades/trades + tradeEvents/openPositions` 还原策略生命周期。
- `trade_journal` 不参与主状态判定；它只能作为前端后续拼接的 execution overlay 来源。

硬约束：

- 不能按股票代码把整次回测粗暴折叠成一条 trade。
- 同一股票的多段独立入场/退出必须保留为独立 lifecycle segment。
- `snapshotType` 合同支持 `half_hour | quarter_hour`；当 run 元数据缺失时默认回落 `half_hour`。
- 对于仍处于 `active_holding / exit_signaled` 的 row，`strategyExitAt / strategyExitPrice / strategyReturnPct / exitReason` 必须保持 `null`，不能提前泄露未来 closed 事实。
- 同一 entry 若 `openPositions` 仍然存在，后端必须以 open 策略事实为准，不能让旧 closed trade 覆盖后续状态。

错误：

- 非 fusion run 返回 `409`，`detail.code=unsupported_strategy`，并带 `expectedStrategyName=ranktrend_early_big_move_v3_lifecycle_fusion`。

返回：

```json
{
  "ok": true,
  "runId": "bt_xxx",
  "datasetId": "ds_xxx",
  "snapshotType": "half_hour",
  "strategyName": "ranktrend_early_big_move_v3_lifecycle_fusion",
  "strategyVersion": "0.1.0",
  "configHash": "abc123",
  "randomSeed": 20260430,
  "count": 3,
  "rows": [
    {
      "stockCode": "600001",
      "stockName": "示例股",
      "strategyName": "ranktrend_early_big_move_v3_lifecycle_fusion",
      "snapshotType": "half_hour",
      "tradingDate": "2026-06-03",
      "snapshotId": "half_hour:2026-06-03:10:00",
      "frameTime": "2026-06-03T10:00:00+08:00",
      "projectionSource": "backtest",
      "strategyState": "active_holding",
      "candidateTier": "A_MAIN",
      "lifecycleAction": "allow",
      "triggerAt": "2026-06-03T10:00:00+08:00",
      "strategyEntryAt": "2026-06-03T10:00:00+08:00",
      "strategyExitAt": null,
      "holdingBars": 0,
      "slotIndex": null,
      "maxPositions": 5,
      "tPlusOneUnlocked": false,
      "entryReason": "A_MAIN 入场",
      "exitReason": null,
      "strategyEntryPrice": 10.0,
      "strategyExitPrice": null,
      "strategyReturnPct": null,
      "executionOverlay": null
    }
  ]
}
```

状态语义：

- `triggered_wait_entry`：候选已触发，但回测事实尚未确认进入策略持有。
- `active_holding`：回测路径确认当前仍在持有。
- `exit_signaled`：回测路径确认进入退出观察，但该段持有尚未关闭。
- `closed`：回测路径确认该段持有已经关闭。

这个端点优先读取 `BacktestRun.result_json` 中的原始时间序列，以便保留 `lifecycleAction`、`finalSignal` 和 `tradeEvents`。只有在历史 run 缺失这些字段时，后端才允许回退归一化集合读取；回退也不能重新引入按 `code` 聚合 lifecycle 的错误口径。

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

**队列护栏（2026-09-23）**：每个优化任务都会持有全量 frames 数据（生产数据集约 2-4GB 内存）。执行中 1 个 + 排队最多 2 个；排队已满时新任务返回 **HTTP 429**，同时已落库的 `running` 记录立即收口为 `failed`（错误码 `OPTIMIZATION_QUEUE_FULL`）。调用方（批次脚本）应串行提交、轮询等待前序任务完成后再提交下一个，不要并发轰任务。

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
    "minJumpConfidence": [90.0],
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

### `POST /api/research/ranktrend-jump`

运行 RankTrend Jump 内生阈值研究复跑。该入口是轻量研究工具，不自动写回默认参数，也不代表自动下单能力。

```json
{
  "datasetId": "dragonboard_live",
  "snapshotType": "half_hour",
  "randomSeed": 20260430,
  "trials": 24,
  "fillFallbackMode": "fallback_penalized",
  "validationRatio": 0.3,
  "walkForwardTrainDays": 8,
  "walkForwardValidationDays": 2,
  "walkForwardStepDays": 2
}
```

口径：

- `method=tpe`，使用 Optuna `TPESampler`。
- `jumpDeltaPct` 默认连续搜索范围为 `8.0 ~ 22.0`；`delta=15` 只作为候选区间内的研究值，不写回默认。
- `strategyName=ranktrend_jump`，`objective=ranktrend_jump`。
- 固定保留 `dataset_id`、`snapshot_type`、`strategy_version`、`config_hash`、`random_seed`。
- 交易模拟使用当前 bar 信号成交、A 股 T+1、`maxHoldingBars=40`、真实权益曲线、涨跌停可成交检查、盘口对手价、成交量/盘口参与率约束。
- `fillFallbackMode=strict_fill|blocked_fill|fallback_penalized`。前两者缺买一/卖一直接不成交；`fallback_penalized` 允许快照价回退，但增加额外滑点，并在 `researchSummary` 中报告回退占比。

返回包含 `summary` / `researchSummary`：

```json
{
  "runId": "opt_xxx",
  "status": "completed",
  "analysisMode": "ranktrend_jump_research",
  "strategyName": "ranktrend_jump",
  "method": "tpe",
  "randomSeed": 20260430,
  "configHash": "abc123",
  "summary": {
    "bestDeltaPct": 13.62,
    "riskLevel": "medium",
    "snapshotFallbackRate": 0.0421,
    "walkForward": {
      "enabled": true,
      "segmentCount": 4,
      "positiveReturnSegmentRate": 0.25
    },
    "conclusion": "该结果只作为 RankTrend Jump 实盘验证候选，不自动写回默认参数。"
  }
}
```

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
  --exclude-non-positive-price-rows `
  --exclude-cross-market-zero-price-rows `
  --exclude-all-zero-price-frames `
  --macd-fast 21 `
  --macd-slow 34 `
  --macd-signal 13 `
  --momentum-periods 3,5,8,13,21
```

`--exclude-non-positive-price-rows` 是显式研究开关，默认不启用。启用后只在本次回测内过滤 `price<=0` 股票行，并在报告中记录 `priceFilter` 统计。

`--exclude-cross-market-zero-price-rows` 和 `--exclude-all-zero-price-frames` 是 Phase 12 价格质量归因开关，默认不启用。前者用于单独评估跨市场/非 A 股零行情条目的影响，后者用于单独评估整帧零价采集异常的影响。两个开关可以和 `--exclude-non-positive-price-rows` 分开使用，以避免把不同数据问题混成一个结论。

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

默认导出目录型 `jsonl-bundle`，用于大型回测报告：

```powershell
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_001 --output quant-board\data\reports\bt_001
```

- `manifest.json`：run 元信息、metrics、文件清单和行数。
- `signals.jsonl`：按 `sequence` 升序的信号明细。
- `trades.jsonl`：按 `sequence` 升序的交易明细。
- `equity_curve.jsonl`：按 `sequence` 升序的权益曲线。
- `quality_report.json`：质量门禁和样本质量报告。
- `result_summary.json`：轻量结果摘要。

如需单文件导出，可显式选择：

```powershell
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_001 --output quant-board\data\reports\bt_001.json.gz --format json.gz
.\.venv\Scripts\python.exe -m backend.cli export-report --run-id bt_001 --output quant-board\data\reports\bt_001.json --format legacy-json
```

`legacy-json` 保留旧单文件 JSON 语义，但大型数据集不推荐使用。常规页面与导出主路径优先使用归一化集合 + `jsonl-bundle`，避免一次性组装超大报告对象。

```json
{
  "ok": true,
  "format": "jsonl-bundle",
  "runId": "bt_001",
  "output": "quant-board\\data\\reports\\bt_001"
}
```

找不到 run 时返回非零退出码，并输出一行结构化错误摘要，例如：

```json
{"ok":false,"error":{"code":"backtest_run_not_found","runId":"bt_missing"}}
```

### `run-longtest-baselines`

一键复跑长测固定基线集合。该命令只编排现有 RankTrend 回测服务，不启动优化、不写回任何候选参数。

```powershell
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_initial

.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_price_filter `
  --exclude-non-positive-price-rows

.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_cross_market_zero_filter `
  --exclude-cross-market-zero-price-rows

.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines `
  --checkpoint-id checkpoint_2026-05-21_all_zero_frame_filter `
  --exclude-all-zero-price-frames
```

默认 baseline set 为 `early_big_move_v5`，固定执行两条基线：

| Label | strategy_name | snapshot_type | execution_mode | max_holding_bars | volume_participation_rate | 用途 |
| --- | --- | --- | --- | ---: | ---: | --- |
| `V5_E1_half_hour_fusion_signal_forward30` | `ranktrend_early_big_move_v3_lifecycle_fusion` | `half_hour` | `current_bar` | `30` | `0.1` | V5 fusion 候选召回，不执行交易模拟 |
| `V5_E2_half_hour_fusion_current_bar` | `ranktrend_early_big_move_v3_lifecycle_fusion` | `half_hour` | `current_bar` | `30` | `0.1` | V5 主长测基线 |

历史对照可通过 `--baseline-set` 显式选择：`early_big_move_v1`、`early_big_move_v2`、`early_big_move_v3`、`legacy_lifecycle_v1`。

默认把 checkpoint 摘要以 JSONL 追加到 `data/reports/long_test_runs.jsonl`。每行保留 `checkpointId`、`runId`、`datasetId`、`snapshotType`、`strategyName`、`strategyVersion`、`configHash`、`randomSeed`、核心收益/回撤/交易指标、`maxHoldingBars`、`volumeParticipationRate`、质量等级、资金流缺失统计，以及显式价格过滤统计。价格统计包括全量非正价格过滤 `priceFilter`、跨市场零行情过滤 `crossMarketPriceFilter`、全零异常帧过滤 `allZeroPriceFrameFilter`，以及默认 report-only 的 `priceQualityDiagnostics`。

V2 四层决策框架新增字段（每条 baseline 内）：

- `layer1SignalEfficacy`：信号有效性诊断。包含 `tierRatio`（A+B 占比）、`directionAccuracy`（A_MAIN 下 bar 上涨比例）、`tierDiscrimination`（层级区分度）、`binomialPValue`（二项检验 p 值）、`layer1Status`（green/red）
- `layer2ExecutionQuality`：执行质量诊断（H1/H2 基线含）。包含 `bias`（H1-H2 收益偏差）、`biasThreshold`（相对阈值）、`drawdownDiff`（回撤差异）、`layer2Status`（green/yellow/red）
- `layer3Alignment`：实盘对齐摘要（checkpoint 级）。包含 `journalExecutedCount`、`signalCodeCount`、`intersectionCount`、`intersectionPnlPct`、`alignmentStatus`
- `crossPeriod`：跨期状态追踪。包含 `layer1MeltdownH1`（熔断检测，含 `meltdown`/`consecutiveRedPeriods`）和 `layer3Trend`（对齐趋势，含 `greenLight`/`recentStatuses`）

可用 `--output` 指定单个输出文件，或用 `--dry-run` 只查看将要执行的三条 payload。

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

### `audit-ranktrend-live-gates`

对 live gate 做 research-only shadow audit。该命令只用于研究和审计 shadow variant 与 baseline 的差异，不会改 live 自动入池，不会把排序结果当成正式交易信号，也不会写回默认 gate。

```powershell
.\.venv\Scripts\python.exe -m backend.cli audit-ranktrend-live-gates `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour `
  --start-date 2026-05-26 `
  --end-date 2026-06-06 `
  --focus-code 600186 `
  --focus-code 002156 `
  --anchor-file quant-board\data\research\hotlist-anchor-samples.json `
  --confidence-thresholds 70,75,80,85,90,95 `
  --research-all-frames `
  --output quant-board\data\reports\ranktrend-live-gates-audit.json
```

参数口径：

- `--dataset-id`：研究样本数据集，默认仍应显式传入，常见为 `dragonboard_live`
- `--snapshot-type`：默认研究口径是 `half_hour`；`quarter_hour` 只能显式传入
- `--start-date` / `--end-date`：审计窗口，建议覆盖连续交易日
- `--focus-code`：可重复传入多个股票代码；默认 `focusCodes=["600186", "002156"]` 只是近期漏票样本的临时默认值，不是长期正式观察池
- `--anchor-file`：可选 JSON 锚点文件，文件内容必须是数组；每条样本按 `code`、`tradingDate`、`slotTime`、`snapshotType`、`label`、`evidence`、`annotator`、`status` 读取，`status` 支持 `confirmed`、`borderline`、`exclude`
- `--confidence-thresholds`：逗号分隔的 jump confidence 扫描阈值，默认 `70,75,80,85,90,95`；只影响审计输出里的阈值扫描，不改 live gate 默认参数
- `--research-all-frames`：默认只围绕 `focus-code` 产出扩展研究样本；开启后会扫描当前 `dragonboard_live` 热榜覆盖窗口内的全部快照帧
- `--output`：把完整审计结果写到用户指定的单个 JSON 文件

输出结构至少包含：

- `meta`
- `focusFindings`
- `dailySummaries`
- `rankingSuggestions`
- `anchorFindings`
- `extendedHotlistFindings`
- `confidenceThresholdScan`
- `jumpDefinitionReplaySummary`
- `fusionGateMissSummary`

输出说明：

- `meta.accDeltaPolicy` 会解释当前 live 数据里 `accDelta` 缺失，因此 acceleration gate 目前主要依赖 `acceleration`
- `meta.anchorSampleStatusCounts` 会统计锚点文件中的 `confirmed` / `borderline` / `exclude` 数量；`borderline` 样本可见但不进入首批主统计
- `meta.outcomeLabelPolicy` 会说明后续涨停型/短线爆发型只从外部或人工后验标签读取；没有后验标签时，不自动用收益推断正样本
- `focusFindings` 会按关注股票展示 `baseline` 与各个 shadow variant 的对比，并且同时给出 `jump` / `fusion` 两层结果
- `dailySummaries` 用于汇总每个交易日的 baseline 命中、shadow 命中、差异原因和临时观察结论
- `rankingSuggestions` 只是排序建议，用于后续研究排查优先级，不是正式交易信号，也不会直接驱动 live 自动入池
- `anchorFindings` 只包含锚点文件中 `status=confirmed` 且在研究范围内命中的样本，用于人工标注样本回放
- `extendedHotlistFindings` 是 `dragonboard_live` 热榜覆盖样本中被审计规则识别出的扩展热榜样本，不是全市场股票池扫描
- `confidenceThresholdScan` 会按 `--confidence-thresholds` 回放不同 jump confidence 阈值下的锚点召回、正样本召回和噪声情况
- `jumpDefinitionReplaySummary` 汇总 jump 定义 shadow replay 的命中差异，用于比较阈值放宽是否带来召回改善
- `fusionGateMissSummary` 汇总 fusion gate 未命中的首个原因，帮助区分 jump 召回不足、fusion 二次过滤或样本质量问题

边界说明：

- 该命令是 research-only 工具；新增锚点、扩展热榜样本和 confidence 扫描都只写入本次 CLI 输出，不会修改 live 自动入池逻辑、不会写回 RankTrend 默认参数，也不会改变 Dragon Board 实时看板候选池。
- `extendedHotlistFindings` 的“扩展样本”来自 `dragonboard_live` 数据集中已有热榜覆盖快照帧；它不是全市场复盘，不会加载未进入 Dragon Board 热榜覆盖范围的股票。

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

### 后端快照采集器 CLI

以下命令属于 `backend/snapshot_collector/`。正式采集由独立进程 `backend.collector_main`（8001）执行；CLI 用于状态查询、人工单次采集、补采和审计。写入 `dragonboard_live` 必须同时设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live` 与 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=1`。命令直接输出 JSON，不做富文本格式化。

### `snapshot-collector-status`

输出采集器当前运行状态 JSON。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-status
```

输出示例：

```json
{
  "lastRunId": "sc-a1b2c3d4e5f6",
  "lastRunAt": "2026-06-12T10:30:00Z",
  "lastStatus": "completed",
  "totalRuns": 42,
  "completedRuns": 38,
  "dedupedRuns": 2,
  "blockedRuns": 2
}
```

### `snapshot-collector-run-once`

执行单次快照采集并输出 JSON 结果。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once `
  --dataset-id dragonboard_backend_shadow `
  --snapshot-type half_hour `
  --trading-date 2026-06-12 `
  --slot-time 10:30 `
  --dry-run
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id` | 是 | 目标数据集 ID |
| `--snapshot-type` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `--trading-date` | 是 | `YYYY-MM-DD` 格式交易日 |
| `--slot-time` | 是 | `HH:MM` 格式槽位时间 |
| `--dry-run` | 否 | 存在即为 true；走完整流水线但不写库 |
| `--force` | 否 | 存在即为 true；跳过判重强制重写 |

输出示例（成功）：

```json
{
  "runId": "sc-a1b2c3d4e5f6",
  "snapshotId": "half_hour:2026-06-12:10:30",
  "status": "completed",
  "deduped": false,
  "dryRun": false,
  "message": "done",
  "details": {
    "stockRowCount": 224,
    "frameCount": 1,
    "sectorRowCount": 12
  }
}
```

### `snapshot-collector-backfill`

按日期区间批量采集，输出汇总 JSON。区间内只生成交易日 slot，周末和已知节假日会被跳过。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-backfill `
  --dataset-id dragonboard_backend_shadow `
  --snapshot-type half_hour `
  --start-date 2026-06-10 `
  --end-date 2026-06-12 `
  --dry-run
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id` | 是 | 目标数据集 ID |
| `--snapshot-type` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `--end-date` | 是 | `YYYY-MM-DD` 格式截止日期；非交易日会被跳过 |
| `--start-date` | 否 | 默认等于 `end_date`；区间起止含两端，非交易日会被跳过 |
| `--dry-run` | 否 | 存在即为 true（backfill 默认 dry-run） |
| `--force` | 否 | 存在即为 true；跳过判重 |

输出示例：

```json
{
  "total": 32,
  "succeeded": 28,
  "failed": 0,
  "blocked": 2,
  "deduped": 2,
  "details": [
    {"snapshotId": "half_hour:2026-06-10:09:30", "status": "completed", "message": "done"},
    {"snapshotId": "half_hour:2026-06-10:10:00", "status": "blocked", "message": "Quality gate blocked: ['no_stock_rows']"}
  ]
}
```

### `snapshot-analysis-backfill`

对**已入库的帧**补跑 golden analyze，把 analyze **顶层字段全集**（`ANALYSIS_PERSIST_FIELDS`：
`observation` / `resonance` / `technical` / `risk` / `strategy` / `executionStrategy` / `jump` /
`decision` / `cycle` / `meta` / `displayStatus` / `themeMomentum`）幂等写入 `snapshot_analysis`
（MongoDB 以 `(dataset_id, snapshot_id, code)` 为唯一键）。

**为什么需要它**：analyze 产物原本只由 `POST /api/snapshots/ingest` 的后台任务写入，而日常采集走
`snapshot_collector` 直写库、**绕过该路由** → `snapshot_analysis` 长期为空（2026-09-10 实测 0 文档），
热榜情绪面板的 `displayStatus` join 恒为 0、8 类分布 100% 走 fallback 旧口径。（该触发点已于同日
**下移到数据层 after-save 钩子**，两条写入路径自动一致；本命令用于补齐历史。）

**2026-09-10 字段补齐**：此前只落 5 个字段（`observation/displayStatus/meta/resonance/cycle`），
而 `technical`（macd/movingAverage/momentumScore/crossSection/signals）、`risk`、`strategy`、
`executionStrategy`、`jump`、`decision`、`themeMomentum` 全部丢失 → 读口只能拿到残缺分析。
四信号中「共振」= `resonance`（顶层）、「趋势」= `observation.rankTrend`、「横截面」=
`observation.crossSection`、「量价」= `observation.volumePrice`，后三者随 `observation` 落库。
**已存在的旧文档仍只有 5 字段**，必须重跑本命令才会补齐。

**2026-09-10 零兜底补全（用户裁决 B）**：部分股票在整个历史窗口内没有有效 `avgRankNum`
（八平台均榜排名）→ 建不起 attention 序列 → 被 `_analyze_frames` 的 gate 跳过（
`if not bars or pos is None: continue`）→ 原本**不落库** → hotlist join 取不到 `displayStatus`
→ 落旧口径 `fallback` 兜底（实测 `2026-07-06`：该帧 205 行只有 187 份 analyze，差 18 只，
正好等于 `fallback: 18`）。全库约 1/5 的 `snapshot_stock_rows` 无有效 `avgRankNum`
（625,218 行中仅 490,974 行 `> 0`），所以兜底靠"补算"永远消不掉。

现在 `compute_snapshot_analysis` 对此类行**补一条落库 entry**：`meta.sampleQuality.status=insufficient`
+ `observation.status=insufficient` + 由 `compute_display_status` 第 1 步样本质量门产出的
`displayStatus`（8 类中的「样本不足」，**不新增类目**）。效果：

- 每帧 `snapshot_analysis` 覆盖该帧**全部股票行** → hotlist join 100% 命中 → `fallback` 归零；
- **不伪造结论**（不编造 stage / 趋势 / 量价），"算不出来"仍 fail-visible（label + tooltip +
  8 类计数都看得到），未被静默、未被伪装成别的状态；
- **不动 golden 在线链路**：`POST /api/ranktrend/analyze`（前端实时 analyze）口径不变，
  改动只在落库侧 `compute_snapshot_analysis`；
- 无帧 / 无输出时也整帧落「样本不足」，不再静默返回 0 条。

实测（`half_hour:2026-07-06:14:00` dry-run）：205 行 → **205 entries、0 行无 label**，
label 分布 `转弱预警 165 / 样本不足 38 / 高位拥挤 2`（其中 18 只来自本次补全，20 只是引擎
自身判定的样本不足，`165 + 38 + 2 = 205` 与 `fallback: 0` 严格一致）。

**旧文档既只有 5 字段、也不含补全行**，必须重跑本命令才会同时补齐两者。

```powershell
# 单帧验证（dry-run，默认不写库）
.\.venv\Scripts\python.exe -m backend.cli snapshot-analysis-backfill `
  --dataset-id dragonboard_live --snapshot-type half_hour --limit 1

# 全量历史回填（4 种帧类型；已算过的帧会重算，幂等、可重复执行）
.\.venv\Scripts\python.exe -m backend.cli snapshot-analysis-backfill `
  --dataset-id dragonboard_live `
  --snapshot-type half_hour --snapshot-type quarter_hour --snapshot-type hourly --snapshot-type daily `
  --start-date 2026-01-01 --limit 0 --workers 6 --apply
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id` | 否 | 默认 `dragonboard_live` |
| `--snapshot-type` | 否 | 可重复或逗号分隔；默认 `half_hour` |
| `--limit` | 否 | 补跑最近 N 帧（按 `tradingDate`+`slotTime` 倒序），默认 `1`；`0` = 不限（需配合 `--start-date`） |
| `--start-date` | 否 | `YYYY-MM-DD` 下界（含当日），用于按日期范围回填、断点续跑 |
| `--workers` | 否 | 并行进程数，默认 `1`（串行）。全量回填用 `6~8`；进度写 stderr，stdout 保持纯 JSON。子进程自建 Mongo 连接（spawn context），单帧失败只标记该帧 `written=0` + `reason`，不阻断整批 |
| `--apply` | 否 | **不传为 dry-run**（只算不写）；传了才写库 |

**注意**：analyze 的 `current_frame` 必须是**含 stocks 行的帧**，而 `snapshot_frames` 文档只有
`stockRowCount` → 本命令从 `snapshot_stock_rows` 组装。单帧全市场 analyze 约 20~40s CPU；
全量历史（~2800 帧）串行需十几小时，`--workers 6` 约 3 小时。

### `hotlist-sentiment-recompute`

强制重算并**覆盖**指定交易日（默认最新交易日）的 `hotlist_sentiment` EOD 文档。

**为什么需要它**：series 读口只对**最新**交易日 lazy compute —— 已持久化文档不会被重算，
因此补跑 analyze 之后必须重算，新的 `displayStatus` join 与 `statusSourceCounts` 才会生效。
重算前旧文档会写入 `hotlist_sentiment_recompute_backup`（新集合）以便回滚；重算写库后会
**立即失效** `GET /api/hotlist-sentiment/series` 的读口缓存。

```powershell
# 全量历史重算（全部交易日；消除 fallback 兜底口径）
.\.venv\Scripts\python.exe -m backend.cli hotlist-sentiment-recompute `
  --dataset-id dragonboard_live --snapshot-type half_hour --days 0 --apply

# 最近 10 个交易日
.\.venv\Scripts\python.exe -m backend.cli hotlist-sentiment-recompute `
  --dataset-id dragonboard_live --snapshot-type half_hour --days 10 --apply
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id` | 否 | 默认 `dragonboard_live` |
| `--snapshot-type` | 否 | 默认 `half_hour` |
| `--trading-date` | 否 | `YYYY-MM-DD`；给了它则忽略 `--days` |
| `--days` | 否 | 重算最近 N 个交易日；**`0` = 全部交易日**；默认 `1` |
| `--apply` | 否 | **不传为 dry-run**（只算不写） |

输出为 before/after 摘要（`statusSourceCounts` / `stageCounts` / `stage`）。

**读口缓存（2026-09-10）**：`GET /api/hotlist-sentiment/series` 现在走 Redis TTL 缓存 —— key 为
`<prefix>:hotlist:sentiment:series:<dataset_id>:<snapshot_type>:<days>:v1`，TTL 由
`QUANT_BOARD_HOTLIST_SENTIMENT_CACHE_TTL_SECONDS` 控制（默认 60s），命中时响应带
`cache.hit=true`。缓存**只存 `ok=true` 的成功响应**（降级/异常响应不入缓存，fail-visible），并注册
依赖到 `<prefix>:snapshot:index:dataset:<dataset_id>` —— **任何**快照写入（ingest 路由或 collector
直写，统一经数据层 after-save 钩子）**或**本命令重算都会立即失效它，不必等 TTL 过期。

**读口缓存（2026-09-12）**：`GET /api/research/theme-summary` 同口径走 Redis TTL 缓存 —— key 为
`<prefix>:research:theme-summary:<dataset_id>:<snapshot_type>`，TTL 由
`QUANT_BOARD_THEME_RESEARCH_SUMMARY_CACHE_TTL_SECONDS` 控制（默认 600s）。背景：该读口每次
请求全量 `load_frame_bundles(limit=200)` + ThemeTrend 引擎重放（实测 8~18s），前端超时必然
abort。缓存**只存 `available=true` 的成功响应**（降级/异常不入缓存），依赖注册与失效口径与
series 读口相同（任何快照写入立即失效）。

**上线核对口径（2026-09-10 实测）**：`displayStatus=235 / fallback=0 / stageMissing=0`，
且 8 类分布与 5 态严格对账 —— `转弱预警 220`（=`cooling 213 − 强资确认 5` + `reversal 12`）、
`强资确认 5`（cooling 中强资金+量能承接）、`高位拥挤 3` + `样本不足 6`（= `crowded 9`）、
`点火观察 1`（= `ignition 1`）。

### `GET /api/hotlist-sentiment/slots`

当日槽位情绪文档序列读口（2026-09-15 新增，Dragon Breath「日内情绪轨迹」消费）。与 `series`
（EOD 日终值，回答"近几日怎么变"）互补，本读口返回当日 9:30→15:00 逐槽文档升序（回答
"今天情绪怎么走到现在"）。槽位文档由采集主链同步后处理链逐槽写入（见"快照写入"一节：
analyze → 槽位情绪 → EOD）。

- 参数：`dataset_id`（默认 `dragonboard_live`）、`snapshot_type`（默认 `half_hour`）、
  `trading_date`（缺省回落最新交易日）；
- 响应：`{ok, datasetId, snapshotType, tradingDate, items[]}`，`items` 为当日槽位文档
  （`slotTime` 升序，剔除 EOD 哨兵行），字段与 series 文档一致；`metrics.transitionCounts`
  （2026-09-16 新增）为阶段迁移计数——join 层注入 `cycleTransition` 后按 golden 行聚合，
  键为 `cycle.transition` 原始串（`"a->b"` 迁移 / 单段 `"a"` 延续），按次数降序，供
  Dragon Breath「日内情绪轨迹」迁移预警条消费；
- 无帧时 `{ok:false, degraded:true, reason:"no_snapshot_trading_date"}`（fail-visible）；
- 缓存与 series 同口径：Redis TTL（key 后缀 `:hotlist:sentiment:slots:...`）+ dataset 索引
  依赖失效，只缓存 `ok=true` 响应。

### `GET /api/hotlist-sentiment/limit-stocks`

涨停池成分股明细读口（2026-09-25 新增，热榜情绪面板「热榜概览」三容器 → `HotlistLimitStocksPanel`
明细面板消费）。一次返回三份名单，口径唯一来源 = `analysis.hotlist.sentiment` 涨停证据纯函数，
与 `metrics.limitEvidence` 聚合同源（明细行数可与聚合数对账，生产口径 `top_n=None` → 全池不截断）：

- **`pool` 热榜池涨停**：最新交易日最新帧全池快照行按 `_has_limit_up_evidence` 过滤，行含
  `code/name/rank/change/boardHeight/nearLimitUp/zhaban/mainNet/firstLimitUpTime/lastLimitUpTime/
  statusLabel`（displayStatus join 注入，异常进 `diagnostics`）。炸板（`zhaban`）口径：
  优先行上 TS 时代炸板布尔字段，缺失时价格推导兜底（`high ≥ limitUpPrice` 且当前未封住，
  2026-09-25 修复采集链炸板恒 0）；推导依赖行情行 `high/limitUpPrice`（bridge 行情透传，
  bridge 离线或停牌股缺失时按未炸计），输入缺失行数由编排层写进情绪文档 `diagnostics`
  （「炸板推导输入缺失 N 行」），与「真无炸板」可分辨；
- **`yesterday` 昨日热榜涨停**：上一交易日全池涨停行 × 今日表现 join（判据同
  `build_yesterday_hot_limit_evidence`：`matched/retained/positive/weakened/failedOrWeak/
  todayChange/todayRank`）；
- **`market` 全市场涨停**：THS 涨停池实时接口（`backend.market_proxy.limitup`）按最近交易日
  取数，非交易日自然回落上一交易日；行含 `code/name/change/highDays/boardHeight/
  firstLimitUpTime/lastLimitUpTime/turnoverRate/openNum/limitUpType/reasonType`；
- 参数：`dataset_id`（默认 `dragonboard_live`）、`snapshot_type`（默认 `half_hour`）；
- 响应：`{ok, degraded, reason, tradingDate, prevTradingDate, snapshotId, diagnostics[],
  pool{rows}, market{rows, degraded, reason}, yesterday{rows}}`；
- fail-visible：昨日行缺失 / displayStatus join 异常 / THS 上游失败互不阻断，各自结构化
  标注（`diagnostics` / `market.degraded+reason`），返回可用部分不伪造名单；无交易日或
  无帧时 `{ok:false, degraded:true, reason}`；
- 无缓存（直读 MongoDB + THS 实时接口）。

### `snapshot-collector-audit`

审计覆盖率并输出结构化 JSON。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit `
  --dataset-id dragonboard_backend_shadow `
  --snapshot-type half_hour `
  --trading-date 2026-06-12
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id` | 是 | 目标数据集 ID |
| `--snapshot-type` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `--trading-date` | 否 | 可选单日过滤；不传时审计数据集全范围 |

输出示例：

```json
{
  "datasetId": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "totalSlots": 16,
  "coveredSlots": 14,
  "missingSlots": 2,
  "missingSlotIds": [
    "half_hour:2026-06-12:11:00",
    "half_hour:2026-06-12:11:30"
  ]
}
```

### `snapshot-collector-compare`

对比两个数据集的快照覆盖率和字段完整性（shadow vs live 审计）。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-compare `
  --dataset-id-a dragonboard_live `
  --dataset-id-b dragonboard_backend_shadow `
  --snapshot-type half_hour `
  --trading-date 2026-06-12
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--dataset-id-a` | 是 | 基准数据集 ID（通常为 `dragonboard_live`） |
| `--dataset-id-b` | 是 | 对比数据集 ID（通常为 `dragonboard_backend_shadow`） |
| `--snapshot-type` | 是 | `quarter_hour` / `half_hour` / `hourly` / `daily` |
| `--trading-date` | 否 | 可选单日对比；不传时对比所有共同交易日 |

输出示例：

```json
{
  "ok": true,
  "datasetA": "dragonboard_live",
  "datasetB": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "tradingDates": ["2026-06-12"],
  "perDate": [
    {
      "tradingDate": "2026-06-12",
      "totalExpectedSlots": 10,
      "slotsInBoth": ["half_hour:2026-06-12:10:00"],
      "slotsOnlyInA": [],
      "slotsOnlyInB": ["half_hour:2026-06-12:09:30"],
      "slotsMissingInBoth": [],
      "slotDetails": [
        {
          "snapshotId": "half_hour:2026-06-12:10:00",
          "inA": true,
          "inB": true,
          "stockRowCountA": 224,
          "stockRowCountB": 210,
          "fieldMissingRatesA": {},
          "fieldMissingRatesB": {"depth10": {"present": 0, "missing": 210, "rate": 1.0}}
        }
      ]
    }
  ],
  "summary": {
    "totalSlotsCompared": 10,
    "slotsInBoth": 8,
    "slotsOnlyInA": 1,
    "slotsOnlyInB": 1,
    "slotsMissingInBoth": 0,
    "avgStockRowDiff": 14.0,
    "emptyFramesA": 0,
    "emptyFramesB": 1
  }
}
```

### `snapshot-collector-scheduler-status`

打印调度器运行状态，包括启用/禁用、运行中、轮询配置、最近采集的 slot 和错误计数。

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-scheduler-status
```

输出示例：

```json
{
  "enabled": true,
  "running": true,
  "dataset_id": "dragonboard_backend_shadow",
  "snapshot_types": ["half_hour", "daily"],
  "poll_seconds": 1.0,
  "grace_minutes": 5,
  "last_run_at": "2026-06-15T10:00:01+08:00",
  "last_slot_collected": "half_hour:2026-06-15:10:00",
  "last_error": null,
  "collection_count": 3,
  "error_count": 0,
  "in_flight_slots": []
}
```

### `copy-missing-mongodb-snapshot-slots`

从一个 donor 数据集复制同 `snapshotId` 的快照事实到目标数据集，用于修复“目标数据集整槽缺失，但 donor 数据集同槽位事实完整”的 MongoDB 历史缺口。默认 dry-run；只有显式 `--apply` 才写入。该命令会复制 `snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`，并在目标 frame/record 的 metadata 中写入 repair provenance，同时登记 `migration_audit(opType=mongodb_snapshot_slot_copy)`。

```powershell
.\.venv\Scripts\python.exe -m backend.cli copy-missing-mongodb-snapshot-slots `
  --target-dataset-id dragonboard_backend_shadow `
  --donor-dataset-id dragonboard_live `
  --snapshot-id half_hour:2026-06-22:15:00
```

参数：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--target-dataset-id` | 是 | 待修复的数据集，例如 `dragonboard_backend_shadow` |
| `--donor-dataset-id` | 是 | donor 数据集，例如 `dragonboard_live` |
| `--snapshot-id` | 是 | 可重复传入；每个值为要复制的完整 `snapshotId` |
| `--apply` | 否 | 存在即写库；默认只输出修复计划 |

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

以下是 SQLite/Supabase 迁移前的旧备份命令，MongoDB 模式下已禁用：

```powershell
.\.venv\Scripts\python.exe -m backend.cli push-backup        # 已禁用
.\.venv\Scripts\python.exe -m backend.cli pull-backup        # 已禁用
```

#### MongoDB 备份

2026-09-16 起备份引擎为 `mongodump --gzip`（manifest `schemaVersion=mongodb_backup.v2`），产物 mongorestore 可直接恢复；历史 v1（JSONL）备份仍可校验。mongodump/mongorestore 路径由 `QUANT_BOARD_MONGODB_TOOLS_BIN` 配置（默认 `D:\APP_SOFT\MongoDB\tools\bin`）。

**手动备份与恢复：**

```powershell
# 轻量备份（仅快照四表）
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --light

# 全量备份（一次 mongodump 全库）
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full

# 查看备份列表
.\.venv\Scripts\python.exe -m backend.cli list-mongodb-backups

# 校验备份
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id 20260916T140348Z

# 恢复到 staging 库（拒绝恢复到正式库名；备份需已 verify）
.\.venv\Scripts\python.exe -m backend.cli restore-mongodb-backup --backup-id 20260916T140348Z --drop

# 校验 restore-staging 拉回的备份
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-restore-staging --backup-id 20260916T140348Z

# 清理过期备份（默认保留30天）
.\.venv\Scripts\python.exe -m backend.cli prune-mongodb-backups --dry-run
.\.venv\Scripts\python.exe -m backend.cli prune-mongodb-backups
```

**盘后自动备份（并入 after-market-once）：**

| 任务名 | 频率 | 时间 | 内容 |
|--------|------|------|------|
| `QuantBoard After Market` | 周一至周五 | 15:30 | hotlistSentiment + mongodbBackup（交易日 light / 周五 full + verify + prune，周五 push R2；push 后远端自动保留最近 4 份全量，`QUANT_BOARD_MONGODB_REMOTE_BACKUP_KEEP` 可调） |

2026-09-16 起旧的 `QuantBoard-LightBackup`、`QuantBoard-FullBackup` 独立任务已删除，备份并入 `QuantBoard After Market` 盘后链；任务由 `scripts/register_after_market_task.ps1` 注册（幂等，可重建），带 `StartWhenAvailable` 可靠性设置。任务失败以非零码退出，任务计划历史可见。非交易日备份自动跳过。

```powershell
# 注册/重建计划任务（需要管理员权限运行一次）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_after_market_task.ps1

# 手动执行盘后链
.venv\Scripts\python.exe -m backend.cli after-market-once
```

**一次性死数据清理（默认 dry-run）：**

```powershell
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-dead-data --drop-dead-collections --cleanup-datasets --purge-result-chunks                        # 预览
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-dead-data --drop-dead-collections --cleanup-datasets --purge-result-chunks --compact --apply      # 执行（删除后 compact 回收磁盘）
```

三个子步骤独立开关：drop 全仓库零引用死集合（逐集合先 mongodump）、清理数据集残留（非保留 dataset + five_minute 残留）、删旧研究 run 的 `backtest_result_chunks`（run 元数据保留，读取返回 `resultPurged` 标记）。`--compact` 在删除后对涉及集合执行 compact 回收磁盘（drop 集合由文件释放无需 compact；单独 `--compact` 无删除步骤时对历史大删除热点集合执行）。apply 时产物备份到 `data/backups/mongodb/pre-cleanup-<ts>/` 并写 `migration_audit(opType=mongodb_dead_data_cleanup)`。2026-09-16 已执行一轮：7 个死集合 drop、`ds_ffa379a00efe47d0` 与 `dragonboard_backend_shadow` 清理、five_minute 50 条 records 删除、18 个旧 run 共 281 条 chunks 删除；compact 后库 storage 从 8.45GB 降至 1.71GB。

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

v3 锚专属默认（`strategyName=ranktrend_early_big_move_v3_lifecycle_fusion` 时覆盖上表，
2026-09-23 落默认；依据 `docs/ranktrend-tier-backtest/exit-scan-batch3-verdict.md`）：

| 参数 | 默认 | 变更 |
| --- | --- | --- |
| `maxHoldingBars` | `30` | — |
| `stopLoss` | `-0.05` | — |
| `takeProfit` | `0.06` | 2026-09-23 由 9.99 落默认 |
| `breakevenTrailing` | `true` | 2026-09-23 由 false 落默认 |
| `breakevenThreshold` | `0.02` | — |
| `volumeParticipationRate` | `0.1` | — |

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

## 历史大单归档

```http
GET /api/big-order/history?source=longhu&stockCode=002297&sessionDate=2026-07-24
GET /api/big-order/history?source=ths&stockCode=002297&sessionDate=2026-07-24
```

该接口只读 `data/big-order` 本地 gzip 归档，并按数据源、六位股票代码和 ISO 日期精确匹配。龙虎文件为 `longhu/<date>/<code>.money0.json.gz`，THS 文件为 `ths/<date>/<code>.json.gz`；不回退相邻日期。

成功返回 `{ "ok": true, "data": <archive> }`。文件不存在返回 HTTP 404 和 `errorCode=archive_not_found`；gzip、JSON、元数据或 payload 结构错误返回 HTTP 422 和 `errorCode=archive_invalid`；非法数据源或股票代码返回 HTTP 422 和 `errorCode=invalid_request`。

---

## 阶段多帧确认字段合同（2026-09-24）

`hotlist_sentiment` 文档新增三个字段：`rawStage`（本帧截面事实，`resolve_stage` 输出，唯一权威真值）、
`stage`（确认投影——当日「严格早于当前槽」的截面序列 + 本帧一次，重放 `stage_confirm.confirm_stage`
滞回；候选阶段连续 `confirmSlots` 槽复现才切换，默认 2）、`stageConfirmState`
（`pending` / `pendingStage` / `pendingSince` / `confirmSlots` / `historyStatus`，枚举
complete / empty / legacy_fallback / unavailable）。`summary`/`riskLevel`/`confidence`/
`signals`/`warnings` 仍是本帧截面证据，不按确认阶段二次计算。

关键语义：EOD 与其锚定槽同帧只计一次（结果一致）；历史重算按当前槽因果截断，未来槽不得污染；
旧文档以 `rawStage ?? stage` 兼容读取（`legacy_fallback` 计数进 `diagnostics`）；
EOD 双形态排除（日级 `_id` 与 `slotTime="EOD"`）；独立轨道降级（`stageShares` 缺失不影响
阶段序列，反之亦然）。

读写与回退：四个生产写口（lazy compute、`compute_and_upsert_for_slot`、`run_for_date`、
`run_for_date_slots`）与 `/api/hotlist-sentiment/ingest` 共用同一投影；ingest 未提供确认字段时
不伪造（`exclude_none`）。series/slots 响应合同变化已升 Redis 缓存版本 `v2`（共享常量
`_HOTLIST_SENTIMENT_CACHE_VERSION`）。回退：`HOTLIST_STAGE_CONFIRM_SLOTS=1` 逐槽等价
（`stage == rawStage`），非法配置回裁决默认 2 并落诊断；不删除任何历史字段或文档。

回放验收基线（2026-09-24，14 个交易日，输入 `rawStage ?? stage`）：原始切换 39 → 确认后 15（减少 61.5%）、确认延迟 max=1 avg=1.00、吸收单槽候选 8 次、阈值 1 逐槽等价 PASS（`operations/replay_stage_confirm.py`，只读）。

## 路线 B 连续情绪评分（2026-09-30）

EOD 档位主定义已从布尔级联切换为**连续评分驱动**（设计 `docs/superpowers/specs/2026-09-30-emotion-score-design.md`（仓库根路径，下同）
v3 + 审计 `2026-09-30-emotion-score-audit.md` + 校准 `2026-09-30-emotion-score-calibration.md`；迁移与典型日对照
`docs/hotlist-jev/emotion-score-migration-report.md`）：

- **判档来源**：`emotion_score.compute_emotion_score`（8 维等权连续分 0-100，jev 聚合口径 1068 槽实测校准，
  缺维跳过权重归一化）→ `map_stage`（≥75 高潮 / 60-75 发酵 / 40-60 启动 / <40 按当日斜率分退潮·冰点；
  高潮压制条款已删除）→ 分数域确认（复用 `stage_confirm.confirm_stage` 滞回，confirmSlots 语义不变）。
- **字段合同**：`rawStage`=本帧映射档位（含斜率；证据全缺时 null——方案 B 不伪造档位）；`stage`=确认投影；
  新增 `emotionScore` 子文档（score/dims/skippedDims/computedAt/slope/version，可分解审计；其中
  `stageCandidate` 与 rawStage 同值）与 `legacyCascadeStage`（旧级联截面对照面，`resolve_stage` 函数保留不删）。
- **斜率**：`_collect_intraday_state.scorePoints` 因果收集当日早槽 `emotionScore.score`，slope=上一有效槽差；
  prev 缺失（首槽不标）落 `emotion_slope_unavailable:prev_score_missing` 诊断；score 全缺落
  `emotion_score_unavailable:slot=<槽位>` 诊断且确认序列跳过该槽（含 historyStatus=unavailable
  分支，禁字符串 "None"）。
- **evidence 取数降级**：写口的 analysis_by_code/昨日同期总额读取失败降级为空 +
  `emotion_evidence_load_failed:*` 诊断，不阻断写库（部分来源失败仍落档，fail-visible）。
- **写口与缓存**：四个写口 evidence parts（yesterday_rows 复用 previous_day_stocks；analysis_by_code 与昨日同期
  总额复用 jev 服务层取数）共用同一投影；series/slots 缓存版本 `v3`；ingest 白名单含
  `emotionScore`/`legacyCascadeStage`（禁止静默丢弃）。
- **历史与回退**：113 交易日 1182 文档已全量重算（新口径，幂等脚本 `backend/operations/emotion_score_recompute.py`）；
  回退 = 调用点切回级联 + 历史 stage 从 `legacyCascadeStage` 重算恢复。策略层消费不变（`risk.py stage_adjust`
  仍读五档枚举），regime 影响量化见 `docs/hotlist-jev/emotion-score-regime-diff-report.md`（EOD 层 meanDiff +2.44，
  68% 天数受影响）。校准重校准触发条款见设计 v3 §9。

