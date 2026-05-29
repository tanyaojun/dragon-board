# 数据导入与质量门禁

## 目标

QuantBoard 首期导入 dragon-board 的历史快照数据，形成可复现的数据集。导入结果必须能支持：

- Python rankTrend 逐快照分析；
- 回测事件循环；
- 参数优化；
- golden case 生成与验证；
- 前端报告查询。

## 数据来源

当前正式运行主库是 MongoDB（`dragon_board_quant` 数据库）。Dragon Board 正式快照通过 `POST /api/snapshots/ingest` 写入 MongoDB 集合 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows`。SQLite/Supabase/Parquet 旧链路仅作为迁移前历史、审计/离线备份参考，或在 Mongo 模式下显式禁用入口。

日常主路径：

1. MongoDB 快照库直接使用
   - 源数据集默认 `dragonboard_live`（MongoDB `DragonBoardData` 数据库）。
   - 回测/优化直接消费 `snapshot_frames` + `snapshot_stock_rows` + `snapshot_sector_rows`，不产生中间派生集。

迁移辅助路径：

2. 历史 JSON 迁移
   - `POST /api/migrations/snapshots/import-json` 导入旧 IndexedDB 导出、Dragon Board v4 bundle。
   - 适合一次性历史迁移。

MongoDB 模式下，`/api/datasets/import` (sourceType=sqlite_snapshots) 返回 410；旧 SQLite/Supabase/Parquet 维护入口已在 [mongodb-migration-plan.md](mongodb-migration-plan.md) 中标记为禁用。

IndexedDB 已从正式快照读写链路中移除。它只能作为历史迁移源或显式缓存。

## 标准数据集结构

导入后生成一个 `dataset_id`，所有表都带这个 ID。

```text
datasets
snapshot_records
snapshot_frames
snapshot_stock_rows
snapshot_sector_rows
```

正式分析优先读取：

- `snapshot_frames`
- `snapshot_stock_rows`
- `snapshot_sector_rows`

`snapshot_records` 用于追溯、排查和重新投影。

## 快照类型

默认导入和回测口径：

```text
snapshot_type = half_hour
```

可选导入：

- `quarter_hour`
- `hourly`
- `daily`

导入器可以同时导入多种类型，但回测请求必须明确使用哪一种。没有显式传入时使用 `half_hour`。

## 字段映射

### 快照级字段

| 标准字段 | 说明 |
| --- | --- |
| `snapshot_id` | 原始快照 ID 或导入器生成 ID |
| `type` | `half_hour`、`quarter_hour` 等 |
| `trading_date` | `YYYY-MM-DD` |
| `slot_time` | `HH:mm` |
| `timestamp` | 毫秒时间戳 |
| `display_key` | 可读名称 |
| `capture_mode` | `real_time`、`delayed`、`restored` |
| `source` | `sqlite_snapshots`、`snapshot_ingest`、`json_migration` 等 |
| `metadata_json` / `market_stats_json` / `sentiment_json` / `money_flow_json` / `indices_json` / `limit_summary_json` / `rotation_summary_json` | 从 IndexedDB frame 结构拆出的市场摘要、情绪、指数、涨跌停和轮动上下文 |

### 股票行字段

| 标准字段 | 说明 |
| --- | --- |
| `row_id` | `snapshot_id:code` |
| `code` | 股票代码 |
| `name` | 股票名 |
| `rank` | 热榜排名 |
| `price` | 当前价 |
| `change` | 涨跌幅 |
| `volume_ratio` | 量比 |
| `zlje` | 主力净额 |
| `zljzb` | 主力净占比 |
| `turnover` | 成交额 |
| `turnover_rate` | 换手率 |
| `depth10_json`、`themes_json` | 只保留小型结构化数组/对象，不再保存整行 payload |
| `theme_contribution`、`theme_role`、`theme_exposure_weight`、`theme_risk_flags_json` | Dragon Board V2 题材暴露摘要；旧快照缺失时允许为空 |

### 板块行字段

板块、题材、主线可统一映射到 `snapshot_sector_rows`：

- `entity_type`
- `entity_key`
- `entity_name`
- `rank`
- `metadata_json`
- `momentum_score`、`breadth_score`、`fund_score`、`leadership_score`、`correlation_score`、`crowding_risk`、`persistence_score`
- `rotation_state`
- `theme_quality_flags_json`

旧数据仍可只提供 `metadata_json.themeFactor`；导入和回测会优先读取稳定列，缺失时用 JSON fallback。

## 导入流程

### 从 SQLite 快照库生成研究数据集

1. 选择源数据集，默认 `dragonboard_live`。
2. 按 `snapshot_type`、日期区间和最大快照数筛选 `snapshot_frames`。
3. `dryRun=true` 时只返回带 `virtual=true`、`policy=snapshot_facts_view` 的预览摘要和质量门禁结果，不落库。
4. `dryRun=false` 时复制筛选出的 `snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows` 到新的 `ds_*` 派生数据集。
5. 源数据集不被删除、覆盖或改写；派生数据集的 `metadata.sourceDatasetId` 和 `metadata.filters` 记录来源和筛选条件。
6. 执行质量门禁，真实生成结果返回 `policy=snapshot_facts_derived_dataset`。
7. MongoDB 模式下不登记新的 Supabase 备份对象。

### 历史 JSON 迁移

1. 读取源文件或内联内容。
2. 识别 schema 版本和快照列表。
3. 标准化快照 ID、日期、时间、类型。
4. 写入原始 `snapshot_records`。
5. 投影到 `snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
6. 执行质量门禁。
7. 更新 `datasets` 汇总统计。
8. 返回迁移报告。

## 历史 JSON 迁移入口

`POST /api/migrations/snapshots/import-json` 是数据库重构期间的正式迁移入口。它和普通 `POST /api/datasets/import` 的区别是：

- 支持指定固定 `datasetId`，便于反复迁移同一个历史库。
- 支持 `sourcePath`，也支持内联 `content` / `bundle` / `payload`。
- 支持 `dryRun`，只解析、计数和检查已存在快照，不落库。
- 写入时复用 `save_snapshot_ingest`，因此会登记 `sync_outbox` 并进入 Supabase 备份补偿链。
- 对同一 `idempotencyKey` 或已存在的 `dataset_id + snapshot_id` 幂等跳过。

支持的 JSON 形态：

- Dragon Board v4 bundle：`items`、`frames`、`stockRows`、`sectorRows`。
- 旧 records/snapshots 数组。
- 结构化 `frames`、`stockRows`、`sectorRows`。
- 常见 SQLite/备份导出字段，例如 `snapshot_id`、`trading_date`、`slot_time`、`row_id`、`market_context_json`。

迁移报告字段：

```json
{
  "scanned": 80,
  "imported": 80,
  "skipped": 0,
  "errors": [],
  "dry_run": false,
  "record_count": 80,
  "frame_count": 80,
  "stock_row_count": 16000,
  "sector_row_count": 1200,
  "start_date": "2026-04-01",
  "end_date": "2026-04-30",
  "snapshot_types": ["half_hour"]
}
```

`skipped` 表示目标 `dataset_id` 下已存在的快照或同一迁移幂等键已经执行过。重复导入不能制造重复数据。

正式迁移前必须先 dry run，检查快照数、股票行数、日期范围和快照类型是否符合预期。正式导入后再运行 `push-outbox` 或等待自动 outbox 同步；大批量历史补推使用 `push-backup` 手动触发。

完成历史迁移后，使用 `verify-snapshot-migration --dataset-id <id> --source-report <dry-run-report.json>` 对齐 `records/frames/stock_rows/sector_rows` 四类行数。验收完成前，不删除浏览器 IndexedDB，不关闭迁移工具。

## 质量门禁

质量门禁分为导入门禁和回测门禁。

### 导入门禁

导入门禁关注数据是否能入库：

- 是否能解析为 JSON；
- 是否存在快照数组或可识别对象；
- 快照是否有 `type`、`trading_date`、`timestamp`；
- 股票行是否有 `code`、`rank`；
- 同一 `dataset_id + snapshot_id` 是否重复；
- 同一 `snapshot_id + code` 是否重复。

导入门禁失败可以整批失败，也可以进入 `partial` 状态，但必须返回错误明细。

### 回测门禁

回测门禁关注数据是否足够支持策略：

- `snapshot_type` 是否存在；
- 日期区间内快照数量是否达到最低要求；
- 快照时间是否单调递增；
- 股票行数量是否合理；
- 核心价格字段是否有效；
- `capture_mode=restored` 是否被正式回测排除；
- 单只股票有效样本是否达到 rankTrend 最低要求。

最低样本数应由 Python rankTrend 配置计算，默认可参考 TypeScript `getTechnicalMinSamples()`：`max(macdSlow, max(momentumPeriods)+1, 30)`。

QuantBoard 当前把质量分成两层：

- 可运行门槛：快照数量足够、时间顺序合法、capture mode 合法，并且剔除空热榜后仍有足够可交易快照；
- 研究可信度门槛：热榜横截面行数建议不少于 `20`。低于该阈值的快照不会直接阻断回测，但会在 `qualityGate`、回测 `dataQuality` 和优化 `warnings` 中标记为 degraded。

因此“质量门禁通过但仍有低热榜 warning”是允许状态，含义是结果可用于候选观察，不应直接用于严格验收或定参数。

正式 `POST /api/snapshots/ingest` 不再接受非 `five_minute` 空热榜 frame，避免 Dragon Board 自动保存阶段继续产生空正式快照。历史导入或迁移数据中已经存在的空热榜快照会在导入质量门禁中记录为问题；回测/优化运行时会自动剔除这些不可交易快照继续执行，并在报告中输出 `runtimeFilter`、`droppedEmptyHotlistSnapshots`、源快照数和实际运行快照数。

## 样本质量状态

rankTrend 输出应保留样本质量：

```json
{
  "snapshotType": "half_hour",
  "sampleCount": 32,
  "requiredSampleCount": 30,
  "status": "ok",
  "coverageWarning": null,
  "latestTradingDate": "2026-04-30",
  "latestSlotTime": "14:30",
  "delayedCount": 1,
  "restoredCount": 0
}
```

状态定义：

- `ok`：达到最低样本数。
- `degraded`：样本不足但不少于 5，可用于观察，不宜作为强交易信号。
- `insufficient`：样本严重不足，不参与重点候选。

## capture_mode 规则

正式回测默认读取：

- `real_time`
- `delayed`

正式回测默认排除：

- `restored`
- `manual`

如果用户为了诊断显式包含恢复快照，报告必须标注 `include_restored=true`，不能和正式回测结果混排。

## 导入报告

建议返回：

```json
{
  "dataset_id": "ds_20260430_001",
  "source_type": "sqlite_snapshots",
  "snapshot_count": 80,
  "frame_count": 80,
  "stock_row_count": 16000,
  "sector_row_count": 1200,
  "snapshot_types": ["half_hour"],
  "start_date": "2026-04-20",
  "end_date": "2026-04-30",
  "warnings": [],
  "errors": []
}
```

## 验收清单

- 同一源文件重复导入时，能通过 `dataset_id` 或唯一键避免数据混乱。
- 默认 `snapshot_type` 为 `half_hour`。
- `quarter_hour` 只有在显式选择时进入回测。
- 门禁失败返回结构化原因。
- 导入后可以按 `dataset_id + snapshot_type + trading_date` 稳定查询。
- 查询结果按 `timestamp` 升序，保证回测事件顺序稳定。

## 数据修复：缺失 bar 补齐

当 half_hour 或 quarter_hour 快照帧在某个交易日的某些时点缺失时，可通过 `bar_repair.py` 工具补齐：

```powershell
.\.venv\Scripts\python.exe -m backend.data.bar_repair
```

工具会：
1. 遍历每个交易日，找出缺失的时点
2. 对每只股票，使用前后相邻 bar 的价格/成交量/成交额做线性插值
3. 板块数据复制最近邻
4. 生成帧和行标记为 `captureMode: "synthesized"`、`qualityFlags: ["synthesized"]`

合成数据是估算值，不反映真实市场价格。回测质量门禁接受 `synthesized` 模式不报错。如需回退到纯真实数据，可通过 `captureMode` 过滤排除合成帧。

## 其他 MongoDB 集合

- `trade_journal`：候选池交易日志。V2 Layer 3 实盘对齐使用其中带 `entryPrice` 的记录与回测信号交叉比对
- `stock_names`：A 股代码表。跨市场零行情过滤使用此表识别非 A 股代码
