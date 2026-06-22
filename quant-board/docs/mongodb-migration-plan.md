# MongoDB 全量主库迁移方案

本文是 QuantBoard 从 SQLite 主链切换到 MongoDB 的设计方案和实施记录。2026-05-12 停服窗口已完成真实数据迁移、`.env.local` 切换、MongoDB 本地全库备份、Cloudflare R2 上传和 R2 拉回到 `restore-staging` 校验。

## 目标结论

- 一次性切换运行主库到 MongoDB，不做 SQLite/MongoDB 双写，不保留 SQLite 运行时 fallback，不做灰度降级。
- 保留当前事实表颗粒度，MongoDB 使用集合承接原 SQLite 表，不把一个快照的所有股票行嵌入到单个大文档。
- 尽量把现有 JSON 文本字段拆成结构化字段、子文档或数组字段；MongoDB 中不再保存 `*_json` 字符串字段作为正式查询合同。
- 本轮正式迁移范围包括：
  - 快照库 `quant_board_snapshots.db`
  - 题材主库 `themeDATA.db`
  - 新增股票基础库 `stock_names`，从 `public/data/stock_code.json` 初始化
- 研究库 `quant_board_research.db` 旧数据按本次停服窗口决策暂不迁移；MongoDB 研究集合只创建空集合和索引，后续新回测、优化、Golden 和 ThemeTrend 研究结果直接写 MongoDB。
- MongoDB 主库保留全量快照历史；废止会导致 RankTrend 样本断裂的 90 交易日主库明细清理。
- Dragon Board 前端仍只能通过 QuantBoard 后端 API 访问正式数据，不直连 MongoDB。
- 2026-05-12 清理补充：正式库曾被测试/调试路径写入 59 个非正式 dataset；已通过 `cleanup-mongodb-datasets --apply` 清理，只保留 `dragonboard_live` 快照主库和全局基础数据。
- 2026-05-12 补数补充：对调试期产生的 5 个空股票快照，已通过 `backfill-empty-mongodb-snapshots --apply` 按同类型同交易日最近非空 frame 补齐股票行，并在 MongoDB frame metadata 中记录 donor。

## 当前实施状态

截至本轮代码改造，已落地：

- `QUANT_BOARD_STORAGE_BACKEND=mongodb` 后，QuantBoard 运行主仓库通过 `repository_factory.create_repository()` 切到 MongoDB。
- 快照、回测、优化、Golden、ThemeTrend 研究表、题材主库、股票基础表均有 Mongo repository。
- `migrate-mongodb --dry-run/--apply` 已实现，迁移源包含 `quant_board_snapshots.db`、`quant_board_research.db`、`themeDATA.db` 和 `public/data/stock_code.json`。
- `stock_names` 后端 API 已实现：`/api/stocks/names`、`/api/stocks/names/{code}`、`/api/stocks/search`；前端 `StockCodeManager` 已改为从 QuantBoard API 加载。
- 旧 SQLite/Supabase/Parquet 运行维护入口在 Mongo 模式下显式 410 或 CLI 拒绝，不再静默触碰旧主链。
- MongoDB 本地全量备份、校验、R2 上传、R2 拉回到 `restore-staging`、本地备份保留裁剪 CLI 已实现。
- `cleanup-mongodb-datasets` 已实现：默认 dry-run；`--apply` 只删除非保留 dataset、四个快照子集合、可通过 `datasetId/backtestRunId` 追踪的研究结果，不删除 `dragonboard_live`、`stock_names`、题材主数据或 `migration_audit`。
- `backfill-empty-mongodb-snapshots` 已实现：默认 dry-run；`--apply` 只处理已知空股票快照，复制同类型最近非空 donor 的股票行，重写 `snapshotId/type/tradingDate/slotTime/timestamp/rowId/id`，更新 frame/dataset 汇总，并写 `migration_audit`。
- `hotlist_sentiment` 已作为 MongoDB 研究集合接入，唯一业务键为 `datasetId + snapshotType + tradingDate`；历史回填脚本 `scripts/backfill_hotlist_sentiment.py` 默认 dry-run，显式 `--apply` 才会写入。
- MongoDB 模式下 `/api/operations/after-market-once` 和 CLI `after-market-once` 不再调用旧 archive/prune 链路，只执行 `hotlistSentiment` 日终步骤。

2026-05-12 停服窗口已执行：

- 已把 `.env.local` 切换为 `QUANT_BOARD_STORAGE_BACKEND=mongodb`，连接 `mongodb://127.0.0.1:27017/dragon_board_quant`。
- 已关闭旧 Supabase 自动同步、Supabase retention 和 SQLite 90 天归档自动任务。
- 已执行 `migrate-mongodb --apply --replace-confirmed --skip-research`。
- 已执行 MongoDB 本地全量备份，备份 ID `20260512T111904Z`，`verify-mongodb-backup` 通过。
- 已上传该备份到 Cloudflare R2 路径 `quant-board/mongodb-backups/full/backup_id=20260512T111904Z/`。
- 已从 R2 拉回到 `data/backups/mongodb/restore-staging/backup_id=20260512T111904Z`，22 个校验文件 hash 全部匹配。
- 已执行污染清理：`/api/datasets` 当前仅返回 `dragonboard_live`；`inspect-mongodb` 显示正式快照仍保留 519 records/frames、109936 stock rows、8353 sector rows。
- 已执行空股票快照补齐：`dragonboard_live` 当前仍为 519 records/frames，`snapshot_stock_rows` 从 109936 增至 110940，`snapshot_sector_rows` 仍为 8353。

## 实验性后端快照采集器（shadow 模式）

`backend/snapshot_collector/` 是一个实验性的后端快照采集器，当前处于 shadow-only 阶段。该模块从 proxy-server 和 python-bridge 实时拉取热榜与行情数据，在 QuantBoard 后端独立完成快照组装、规范化和质量门禁，不依赖 Dragon Board 前端运行时。

### `dragonboard_backend_shadow` 数据集

采集器写入一个独立的 shadow 数据集，不与 `dragonboard_live` 正式主库混写：

- 数据集 ID：`dragonboard_backend_shadow`（由 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID` 控制）。
- 用途：平行对照和验收。该数据集只保存后端采集器的快照事实，用于与 Dragon Board 前端提交的 `dragonboard_live` 快照做覆盖率对比、质量审计和一致性校验。
- 隔离规则：`QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET` 默认 `false`，禁止采集器写入 `dragonboard_live` 或其他正式数据集。
- 该数据集不参与正式回测、优化或 RankTrend 研究作为默认数据源；仅用于 shadow 验收。

### 运维集合

采集器引入两个新的 MongoDB 运维集合：

`snapshot_collector_runs`

- 记录每次采集运行的完整审计轨迹。每条文档对应一次 `run_once` 调用。
- 字段：`runId`、`datasetId`、`snapshotId`、`snapshotType`、`tradingDate`、`slotTime`、`status`（`completed` / `dry_run` / `deduped` / `blocked`）、`deduped`、`dryRun`、`blockingIssues`、`warnings`、`createdAt`。
- 索引：`{ runId: 1 }` unique、`{ datasetId: 1, createdAt: -1 }`、`{ status: 1, createdAt: -1 }`。

`snapshot_collector_state`

- 保存采集器的轻量运行状态，供状态查询和健康检查使用。
- 字段：`lastRunId`、`lastRunAt`、`lastStatus`、`totalRuns`、`completedRuns`、`dedupedRuns`、`blockedRuns`。
- 该集合只保留最新一条状态文档，不累积历史。

### 质量门禁

采集器在写入快照事实前执行质量门禁（`quality_gate.evaluate_quality()`）：

- 检查数据源健康（proxy-server 和 python-bridge 均可达）。
- 检查股票行数量（至少 1 条非空股票行）。
- 检查时间窗口（当前时间在交易时段或收盘后 grace 窗口内）。
- 质量门禁失败时运行状态标记为 `blocked`，写入 `snapshot_collector_runs` 保留审计轨迹，不写入快照事实集合。
- 质量门禁只做阻塞判断，不修改上游数据源内容。

### 审计要求（shadow 验收）

shadow 采集器必须通过以下验收后才能讨论 live cutover：

- shadow/live 对比必须显式报告 `slotsMissingInBoth`，不能因两侧同时缺失而把预期槽位排除在统计之外。
- 覆盖率审计：通过 `POST /api/snapshot-collector/audit` 或 CLI `snapshot-collector-audit` 对比 shadow 数据集与 live 数据集的槽位覆盖率和股票行数。
- 质量门禁通过率：`blocked` 运行占比应可解释（如非交易时段、数据源短暂不可用），不得存在系统性静默丢弃。
- 数据一致性：shadow 快照的关键字段（价格、排名、热榜组成）应与同槽位 Dragon Board 前端快照可比。
- 强制重采替换同一 `snapshotId` 前保留旧事实；任一集合写入失败时恢复替换前 records、frames、stock rows、sector rows 和 dataset 摘要，不得留下半写快照。
- 审计轨迹完整：`snapshot_collector_runs` 中每次运行都有明确状态和阻塞原因，不得存在状态缺失的运行记录。
- 验收命令：`verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour` 应通过。
- 2026-06-22 起重新开始连续观察，至少采集两个完整交易日后再复评阶段 5。新帧必须保存完整 `hot_theme` rows，并记录 `themeCount/sectorRowCount/quoteCoverageRatio/fundCoverageRatio/factorVersion`；row count drift 或腾讯覆盖低于门槛时审计失败。替换前 `sector_rows=0` 属于历史已知缺口，不回填、不伪造，研究按实际切换时间过滤或标记 `theme_sector_history_missing` 排除。

shadow 验收不通过时，不得提升采集器为正式快照来源，也不得将 `dragonboard_backend_shadow` 数据集用于生产回测或策略决策。

## 非目标

- 不在交易时间修改快照写入链路。
- 不把 MongoDB 当作前端直连数据库。
- 不把历史 Parquet 归档作为 RankTrend 主查询链路。
- 不继续维护 SQLite + Supabase failover 作为运行时降级路径。
- 不借迁移重写 RankTrend、回测、优化或题材策略算法。
- 不把 `public/data/stock_code.json` 长期作为正式运行依赖；它只作为 `stock_names` 首次导入源和人工补救源。

## 当前 SQLite 事实

### 快照库

`quant_board_snapshots.db` 当前保存正式快照事实和同步/归档元数据。

| 表 | 停服迁移源行数 | MongoDB 文档数 | 关键约束/索引 | MongoDB 迁移集合 |
| --- | ---: | --- | --- |
| `datasets` | 4 | 4 | `id` 主键 | `datasets` |
| `snapshot_records` | 536 | 536 | unique `dataset_id + snapshot_id` | `snapshot_records` |
| `snapshot_frames` | 536 | 536 | unique `dataset_id + snapshot_id` | `snapshot_frames` |
| `snapshot_stock_rows` | 109952 | 109952 | unique `dataset_id + row_id`，索引 `dataset_id/type/trading_date/timestamp/code/snapshot_id` | `snapshot_stock_rows` |
| `snapshot_sector_rows` | 8369 | 8369 | unique `dataset_id + row_id`，索引 `dataset_id/type/trading_date/timestamp/snapshot_id` | `snapshot_sector_rows` |
| `sync_outbox` | 172 | 0 | unique `idempotency_key` | 不进入新运行主链 |
| `archive_manifests` | 3 | 3 | unique `archive_id` | `archive_manifests`，只保留审计和历史恢复参考 |

当前问题是归档链路会在校验后删除 SQLite 中的 `snapshot_stock_rows` 和 `snapshot_sector_rows`，但 `load_frame_bundles`、`load_frames`、`load_rank_series` 等 RankTrend 主入口仍依赖 SQLite 明细行。因此会出现有 `snapshot_frames` 元数据、但缺少股票行，导致 RankTrend 样本不足。

### 研究库

`quant_board_research.db` 当前保存回测、优化、Golden 和 ThemeTrend 研究结果。

| 表 | 停服迁移源行数 | MongoDB 文档数 | 关键约束/索引 | MongoDB 迁移集合 |
| --- | ---: | --- | --- |
| `golden_ranktrend_cases` | 1 | 0 | `id` 主键 | `golden_ranktrend_cases` |
| `backtest_runs` | 1030 | 0 | `id` 主键，索引 `dataset_id` | `backtest_runs` |
| `backtest_trades` | 122 | 0 | 索引 `backtest_run_id/code` | `backtest_trades` |
| `backtest_equity_curve` | 1045 | 0 | 索引 `backtest_run_id` | `backtest_equity_curve` |
| `backtest_signals` | 170527 | 0 | 索引 `backtest_run_id/snapshot_id/code` | `backtest_signals` |
| `backtest_quality_reports` | 26 | 0 | 索引 `backtest_run_id` | `backtest_quality_reports` |
| `optimization_runs` | 32 | 0 | `id` 主键，索引 `dataset_id` | `optimization_runs` |
| `theme_factor_frames` | 0 | 0 | 索引 `dataset_id/snapshot_id/trading_date` | `theme_factor_frames` |
| `theme_stock_exposures` | 0 | 0 | 索引 `dataset_id/snapshot_id/code/trading_date` | `theme_stock_exposures` |
| `theme_signals` | 0 | 0 | 索引 `dataset_id/snapshot_id/trading_date` | `theme_signals` |
| `theme_quality_reports` | 0 | 0 | 索引 `dataset_id` | `theme_quality_reports` |

`backtest_signals` 是当前研究库增长压力最大表。本次停服窗口按决策暂不迁移旧研究库数据，MongoDB 只创建空研究集合和索引；后续新研究结果保留按 `runId`、`snapshotId`、`code` 查询的能力，不嵌入到 `backtest_runs` 大文档。

### 题材主库

`themeDATA.db` 当前保存题材基础映射。

| 表 | 停服迁移源行数 | MongoDB 文档数 | 关键约束/索引 | MongoDB 迁移集合 |
| --- | ---: | --- | --- |
| `themes` | 237 | 237 | `id` 主键 | `themes` |
| `theme_stock_mappings` | 12215 | 12215 | unique `theme_id + stock_code` | `theme_stock_mappings` |
| `theme_metadata` | 2 | 2 | `key` 主键 | `theme_metadata` |

题材基础库仍只保存静态映射、标签和原因，不保存 ThemeTrend 运行态因子、回测、优化或快照事实。

### 股票代码静态源

当前 `src/services/StockCodeManager.ts` 已从 QuantBoard `/api/stocks/*` 读取股票基础库。停服迁移时 `public/data/stock_code.json` 源文件 5617 条，其中 `871753` 重复 1 条；MongoDB `stock_names` 去重后 5616 条，重复项写入 `migration_audit`。

迁移后新增 `stock_names` 集合，前端 `StockCodeManager` 通过 QuantBoard 后端 API 读取，不再依赖静态 JSON 文件。

## MongoDB 建模原则

### 保留事实表颗粒度

MongoDB 集合按原表边界设计：

- 一条 `snapshot_frame` 仍是一条文档。
- 一条快照内的一只股票仍是一条 `snapshot_stock_rows` 文档。
- 一条快照内的一个板块/题材/主线实体仍是一条 `snapshot_sector_rows` 文档。
- 一条回测 signal 仍是一条 `backtest_signals` 文档。
- 一条题材-股票关系仍是一条 `theme_stock_mappings` 文档。

这样能保留当前查询模式，避免大文档超过合理大小，也方便按股票、日期、回测 run 分页读取。

### 拆散 JSON 字段

SQLite 中的 `*_json` 字段迁移到 MongoDB 时应解析为结构化字段：

| SQLite 字段 | MongoDB 字段 |
| --- | --- |
| `quality_flags_json` | `qualityFlags: string[]` |
| `metadata_json` | `metadata: object` |
| `market_stats_json` | `marketStats: object` |
| `sentiment_json` | `sentiment: object` |
| `money_flow_json` | `moneyFlow: object` |
| `indices_json` | `indices: object` |
| `limit_summary_json` | `limitSummary: object` |
| `rotation_summary_json` | `rotationSummary: object` |
| `depth10_json` | `depth10: object` |
| `themes_json` | `themes: string[]` |
| `theme_risk_flags_json` | `themeRiskFlags: string[]` |
| `theme_quality_flags_json` | `themeQualityFlags: string[]` |
| `snapshot_types_json` | `snapshotTypes: string[]` |
| `request_json` | `request: object` |
| `result_json` | `resultCompressed: "__qb_gzip_b64__:<payload>" 或未压缩 JSON 文本；读取层透明还原。压缩后仍超过安全阈值时写入 `backtest_result_chunks(backtestRunId, sequence, payload)` 并在 `backtest_runs` 标记 `resultChunked=true`。旧迁移遗留的 `result: object` 仅作为兼容读取字段。`backtest_runs` 不再直接嵌入完整 `result` 子文档，避免 MongoDB 16MB 单文档限制。 |
| `input_json` | `input: object` |
| `expected_json` | `expected: object` |
| `fill_detail_json` | `fillDetail: object` |
| `reasons_json` | `reasons: string[]` |
| `risk_flags_json` | `riskFlags: string[]` |
| `theme_reasons_json` | `themeReasons: string[]` |
| `warnings_json` | `warnings: string[]` |
| `issues_json` | `issues: object[]` |
| `stats_json` | `stats: object` |
| `missing_fields_json` | `missingFields: object` |
| `nan_counts_json` | `nanCounts: object` |
| `inf_counts_json` | `infCounts: object` |
| `stock_tags_json` | `stockTags: object[]` |
| `row_counts_json` | `rowCounts: object` |
| `file_hashes_json` | `fileHashes: object` |

迁移脚本遇到非法 JSON 时不得静默丢弃，应写入 `migration_audit`，并使用字段默认值继续迁移该行。MongoDB 正式集合不得保留 `*_json` 字符串字段；如果为了排障需要保留原始字符串，只能写入 `migration_audit.rawValue`，不能进入业务集合。

### 字段命名

MongoDB 正式字段使用 camelCase，保持 Dragon Board 和 QuantBoard API 的既有返回合同：

- `dataset_id` -> `datasetId`
- `snapshot_id` -> `snapshotId`
- `trading_date` -> `tradingDate`
- `slot_time` -> `slotTime`
- `row_id` -> `rowId`
- `backtest_run_id` -> `backtestRunId`
- `theme_id` -> `themeId`
- `stock_code` -> `stockCode`

后端 API 继续返回现有 camelCase 字段，前端类型不因数据库迁移删除或重命名。

## 集合与索引设计

### 快照集合

`datasets`

- unique `{ id: 1 }`
- `{ sourceType: 1, createdAt: -1 }`

`snapshot_records`

- unique `{ datasetId: 1, snapshotId: 1 }`
- `{ datasetId: 1, type: 1, tradingDate: 1, timestamp: 1 }`
- `{ datasetId: 1, captureMode: 1, tradingDate: 1 }`

`snapshot_frames`

- unique `{ datasetId: 1, snapshotId: 1 }`
- `{ datasetId: 1, type: 1, tradingDate: 1, timestamp: 1 }`
- `{ datasetId: 1, type: 1, timestamp: 1 }`

`snapshot_stock_rows`

- unique `{ datasetId: 1, rowId: 1 }`
- `{ datasetId: 1, snapshotId: 1, rank: 1 }`
- `{ datasetId: 1, type: 1, tradingDate: 1, timestamp: 1, rank: 1 }`
- `{ datasetId: 1, type: 1, tradingDate: 1, slotTime: 1, captureMode: 1, timestamp: 1, rank: 1 }`
- `{ datasetId: 1, code: 1, type: 1, tradingDate: 1, timestamp: 1 }`
- `{ datasetId: 1, code: 1, timestamp: 1 }`

文档保留 Dragon Board 快照股票行的 camelCase 字段合同。涨停池增强字段 `reason/firstZtTime/lastZtTime/boardHeight/highDays/fengdan` 必须随 `snapshot_stock_rows` 写入和读回，用于复盘与导出。

`snapshot_sector_rows`

- unique `{ datasetId: 1, rowId: 1 }`
- `{ datasetId: 1, snapshotId: 1, rank: 1 }`
- `{ datasetId: 1, snapshotId: 1, timestamp: 1, rank: 1 }`
- `{ datasetId: 1, entityType: 1, entityKey: 1, tradingDate: 1 }`
- `{ datasetId: 1, entityType: 1, entityKey: 1, type: 1, tradingDate: 1, timestamp: 1 }`
- `{ datasetId: 1, type: 1, tradingDate: 1, timestamp: 1, rank: 1 }`

### 研究集合

`backtest_runs`

- unique `{ id: 1 }`
- `{ datasetId: 1, strategyName: 1, snapshotType: 1, createdAt: -1 }`
- `{ status: 1, createdAt: -1 }`

`backtest_trades`

- `{ backtestRunId: 1, sequence: 1 }`
- `{ backtestRunId: 1, code: 1 }`
- `{ backtestRunId: 1, entryTime: 1 }`

`backtest_equity_curve`

- `{ backtestRunId: 1, sequence: 1 }`
- `{ backtestRunId: 1, timestamp: 1 }`

`backtest_signals`

- `{ backtestRunId: 1, snapshotId: 1 }`
- `{ backtestRunId: 1, code: 1 }`
- `{ backtestRunId: 1, signal: 1 }`
- `{ backtestRunId: 1, sequence: 1 }`
- `{ backtestRunId: 1, candidateTier: 1, regime: 1, sequence: 1 }`

迁移时保留 SQLite 自增 `id` 为 `sequence` 或 `legacyId`，用于延续旧分页顺序和稳定排序。

大型报告导出和回测报告页面明细读取优先走 `backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports` 这些归一化集合。`backtest_runs.resultCompressed` 与 `backtest_result_chunks` 只保留兼容完整结果追溯，不再作为常规导出主路径。导出热路径应命中 `{ backtestRunId: 1, sequence: 1 }`，避免大规模 in-memory sort。

`backtest_quality_reports`

- `{ backtestRunId: 1 }`

`hotlist_sentiment`

- unique `{ datasetId: 1, snapshotType: 1, tradingDate: 1 }`
- `{ datasetId: 1, snapshotType: 1, computedAt: -1 }`

一条文档对应一个数据集、快照粒度和交易日的日终热榜情绪结果。写入来源包括 Dragon Board/QuantBoard API 日终落库、`scripts/backfill_hotlist_sentiment.py --apply` 历史回填，以及 MongoDB 模式下的 `after-market-once` 盘后步骤。该集合是策略研究输入，不进入 SQLite/Supabase 运行 fallback。

`optimization_runs`

- unique `{ id: 1 }`
- `{ datasetId: 1, strategyName: 1, method: 1, createdAt: -1 }`
- `{ status: 1, createdAt: -1 }`

`golden_ranktrend_cases`

- unique `{ id: 1 }`

字段必须包含 `id/name/datasetId/input/expected/createdAt`。`input_json` 和 `expected_json` 必须解析为 `input` 与 `expected` 对象，不能以字符串形式保留。

ThemeTrend 研究集合：

- `theme_factor_frames`: unique `{ datasetId: 1, snapshotId: 1, strategyVersion: 1, configHash: 1, themeId: 1 }`，普通索引 `{ datasetId: 1, themeId: 1, tradingDate: 1 }`
- `theme_stock_exposures`: unique `{ datasetId: 1, snapshotId: 1, strategyVersion: 1, configHash: 1, code: 1, themeId: 1 }`，普通索引 `{ datasetId: 1, code: 1, tradingDate: 1 }`
- `theme_signals`: unique `{ datasetId: 1, snapshotId: 1, strategyVersion: 1, configHash: 1, themeId: 1 }`，普通索引 `{ datasetId: 1, themeId: 1, tradingDate: 1 }`
- `theme_quality_reports`: unique `{ datasetId: 1, snapshotType: 1, strategyVersion: 1, configHash: 1, randomSeed: 1 }`，普通索引 `{ datasetId: 1, snapshotType: 1, createdAt: -1 }`

### 题材和股票基础集合

`themes`

- unique `{ id: 1 }`
- `{ name: 1 }`

字段必须保留 `id/name/zsCode/createdAt/updatedAt`，其中 `zs_code` 迁移为 `zsCode`。

`theme_stock_mappings`

- unique `{ themeId: 1, stockCode: 1 }`
- `{ stockCode: 1 }`
- `{ themeId: 1 }`

字段必须保留 `themeId/stockCode/stockTags/stockReason/createdAt/updatedAt`。题材映射 API 验收必须检查标签和原因不能丢失。

`theme_metadata`

- unique `{ key: 1 }`

`stock_names`

- unique `{ code: 1 }`
- `{ active: 1, market: 1, type: 1, code: 1 }`
- `{ active: 1, code: 1 }`
- `{ active: 1, pinyinInitials: 1 }`
- `{ active: 1, nameNormalized: 1 }`

建议文档：

```json
{
  "code": "000001",
  "name": "平安银行",
  "market": "SZ",
  "type": "stock",
  "nameNormalized": "平安银行",
  "pinyinInitials": "payh",
  "pinyinFull": "pinganyinhang",
  "searchText": "000001 平安银行 payh pinganyinhang",
  "source": "stock_code_json",
  "active": true,
  "createdAt": "2026-05-12T00:00:00Z",
  "updatedAt": "2026-05-12T00:00:00Z"
}
```

## API 合同调整

### 保持不变的正式快照 API

以下 API 路径保持不变，只替换内部 repository：

- `POST /api/snapshots/ingest`
- `GET /api/snapshots/frames`
- `GET /api/ranktrend/rank-series`
- `GET /api/snapshots/records`
- `GET /api/snapshots/records/{snapshot_id}`
- `GET /api/snapshots/stock-rows`
- `GET /api/snapshots/sector-rows`
- `GET /api/snapshots/counts`

响应中的 `source` 从 `sqlite` 改为 `mongodb`。如果 MongoDB 不可用，正式接口应结构化失败，不返回空列表伪装成功。

### 保持不变的题材 API

- `GET /api/themes/mapping`
- `GET /api/themes/stocks/{theme_id}`
- `GET /api/themes/stocks/by-code/{code}`
- `GET /api/themes/counts`
- `POST /api/migrations/themes/import-json`
- `POST /api/migrations/themes/verify-json`

响应 `source` 改为 `mongodb`。

### 新增股票基础 API

`GET /api/stocks/names`

查询参数：

- `market`：可选，`SH/SZ/BJ`
- `type`：可选，`stock/index/etf/bond`
- `active`：默认 `true`
- `cursor`：分页游标，可选
- `limit`：可选；未传时必须返回全部 active 股票。若后端因体积限制启用分页，响应必须返回 `total/nextCursor`，前端必须循环拉取到 `nextCursor=null`

返回：

```json
{
  "ok": true,
  "source": "mongodb",
  "count": 5617,
  "total": 5617,
  "nextCursor": null,
  "version": "20260512",
  "updatedAt": "2026-05-12T00:00:00Z",
  "stocks": []
}
```

`GET /api/stocks/names/{code}`

返回单只股票基础信息。未命中返回 404，不伪造名称。

`GET /api/stocks/search`

查询参数：

- `q`：代码、名称或拼音
- `limit`：默认 50
- `market`：可选
- `type`：可选
- `active`：默认 `true`

搜索排序固定为：精确代码优先，其次代码前缀、名称前缀、名称包含、拼音首字母前缀、拼音全拼前缀；同一优先级内按 `code` 升序稳定排序。返回字段与 `StockCodeInfo` 保持一致。

用于替代前端 `StockCodeManager.search` 的本地全量搜索。首期可由前端加载全量后本地搜索，也可以直接由后端搜索；若保持前端本地搜索，`GET /api/stocks/names` 必须足够快并可缓存。

### 前端股票基础库合同

`StockCodeManager` 迁移后仍保留内存 `stockMap`，以兼容当前同步调用：

- 应用启动时异步调用 `GET /api/stocks/names` 拉取全量 active 股票，并构建 `stockCodes/codeStrings/stockMap`。
- `getStockInfo/getStockName/getCodesByMarket/search` 继续同步读取内存，不在调用点临时发起远端请求。
- 自选股添加前必须等待 `StockCodeManager.waitForReady()`；未就绪时返回结构化“股票基础库不可用”提示，不把未知代码伪装成有效股票。
- `StockMergeCoordinator.merge` 前应确保股票基础库已加载；若未加载，只允许名称临时回退为平台名或 `-`，不得把未加载解释为股票不存在。
- 迁移后禁止运行时 `fetch('/data/stock_code.json')` fallback；该 JSON 文件只允许迁移或人工导入使用。
- 如保留 `localStorage` 缓存，缓存响应必须带 `source=local_cache/stale=true/version`，不得伪装为 MongoDB 成功；迁移当天必须 bump cache key 或清理旧 `stock_codes_cache`。

前端 API 改造点：

- 在 `apiService` 中新增 `getStockNames/getStockName/searchStocks`。
- `/api/stocks/*` 必须显式使用 QuantBoard API context，并加入 `inferContext` 规则，避免请求落到根代理服务 `localhost:3000`。
- 新增测试覆盖全量加载、缓存刷新、API 不可用、自选股等待 ready、市场过滤和搜索排序。

## 配置调整

新增环境变量：

| 变量 | 说明 |
| --- | --- |
| `QUANT_BOARD_MONGODB_URI` | MongoDB 连接串 |
| `QUANT_BOARD_MONGODB_DATABASE` | 默认 `dragon_board_quant` |
| `QUANT_BOARD_MONGODB_CONNECT_TIMEOUT_MS` | 连接超时 |
| `QUANT_BOARD_MONGODB_SERVER_SELECTION_TIMEOUT_MS` | server selection 超时 |
| `QUANT_BOARD_MONGODB_BACKUP_DIR` | 本地 MongoDB 备份目录，默认 `quant-board/data/backups/mongodb` |
| `QUANT_BOARD_MONGODB_BACKUP_RETENTION_DAYS` | 本地备份保留天数，只作用备份文件，不删除 MongoDB 主库明细 |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_ENABLED` | 是否把 MongoDB 备份上传到 Cloudflare R2/S3 兼容对象存储 |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_BUCKET` | MongoDB 备份使用的 R2 bucket |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_PREFIX` | MongoDB 备份对象存储前缀，建议 `quant-board/mongodb-backups/` |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_ENDPOINT_URL` | Cloudflare R2 S3 兼容 endpoint |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_ACCESS_KEY_ID` | R2 access key id，后端专用 |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_SECRET_ACCESS_KEY` | R2 secret access key，后端专用 |
| `QUANT_BOARD_MONGODB_OBJECT_BACKUP_REGION` | R2 region，默认 `auto` |

迁移完成后废止运行时变量：

- `QUANT_BOARD_SNAPSHOT_DATABASE_URL`
- `QUANT_BOARD_RESEARCH_DATABASE_URL`
- `QUANT_BOARD_THEME_DATABASE_URL`
- `QUANT_BOARD_ENABLE_SUPABASE_BACKUP`
- `QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK`
- `QUANT_BOARD_SUPABASE_RETENTION_*`
- `QUANT_BOARD_ARCHIVE_AUTO_ENABLED`
- `QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS`

Parquet/R2 相关变量可以保留为离线备份能力，但不得再作为 RankTrend 正式读取主链，也不得删除 MongoDB 主库明细。

## 旧机制处置

迁移后旧 SQLite/Supabase/Parquet 维护链路不得继续按原语义运行。

| 旧机制 | 迁移后处置 |
| --- | --- |
| `archive-auto-once` / `ArchiveAutoRunner` | 停用原 SQLite 明细清理语义。后续如保留归档，只能从 MongoDB 导出备份文件，不得删除 MongoDB 主库明细。 |
| `QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS=90` | 废止运行时保留窗口，不再用于删除 RankTrend 所需快照明细。 |
| `backup-snapshot-day` | 改造为 MongoDB 日备份或直接由 MongoDB dump/快照承担；不能继续只备份 SQLite 当日数据。 |
| `push-archive-backup` / `pull-archive-backup` | 仅保留为历史 Parquet/R2 审计和人工恢复工具；不得作为正式读取 fallback。 |
| `verify-archive` / `restore-archive` | 只用于旧归档资产核验。若恢复到 MongoDB，必须走显式人工恢复脚本和迁移审计。 |
| `prune-backup` / `BackupRetentionRunner` | Supabase 灾备清理废止。MongoDB 切换后不得继续清理 Supabase 并把结果视为正式备份状态。 |
| `sync_outbox` | 不进入新运行主链。迁移后不再登记 SQLite/Supabase outbox。 |
| Windows `after-market-once` 任务 | 停服前必须禁用旧任务；迁移后重建为 MongoDB 盘后任务，当前只执行 `hotlistSentiment` 日终落库，确认不调用旧 archive/prune 命令。 |

已实现的 Mongo 模式行为：

- `/api/sync/push-backup`、`/api/sync/pull-backup`、`/api/sync/push-outbox`、`/api/sync/auto-once`、`/api/sync/prune-backup`、`/api/sync/smoke-backup` 返回 410。
- `/api/storage/archive/*` 旧 SQLite/Parquet 归档接口返回 410。
- `/api/operations/after-market-once` 在 MongoDB 模式下执行 `hotlistSentiment` 步骤，从 `snapshot_frames/snapshot_stock_rows` 读取最新交易日最后一帧并 upsert `hotlist_sentiment`；旧 archive/prune 步骤不执行。
- `/api/migrations/snapshots/import-json` 返回 410；Mongo 全量切换后历史导入只允许走停服迁移脚本。
- CLI 旧 SQLite/Supabase/Parquet 命令在 Mongo 模式下直接拒绝；业务回测、优化、查询命令通过 Mongo repository 运行。

## MongoDB 备份、恢复和归档

MongoDB 主库保留全量正式事实数据。备份和归档只复制数据，不承担主库瘦身职责，也不得删除 `snapshot_stock_rows`、`snapshot_sector_rows`、`backtest_signals` 等 RankTrend 和研究所需明细。

### 备份目标

采用三层备份：

1. MongoDB 主库：正式读写唯一事实源。
2. 本地备份目录：保存 `mongodump` 全库备份、校验文件和备份 manifest。
3. Cloudflare R2/S3 兼容对象存储：保存本地备份目录的异地副本。

备份目录建议：

```text
quant-board/data/backups/mongodb/
  full/
    backup_id=<timestamp>/
      dump/
      manifest.json
      sha256sums.txt
  collections/
    backup_id=<timestamp>/
      snapshot_stock_rows.bson
      ...
  restore-staging/
```

`manifest.json` 至少记录：

- `backupId`
- `database`
- `createdAt`
- `gitCommit`
- `sourceMongoUriRedacted`
- `collections`：每个集合的文档数、索引摘要、文件 hash 和字节数
- `strategy`：`full_dump`、`collection_dump` 或 `pre_migration_snapshot`
- `objectKey`
- `objectStore`：例如 `cloudflare_r2`
- `bucket`
- `endpointHost`
- `verified`
- `lastError`

Cloudflare R2 对象 key 建议：

```text
quant-board/mongodb-backups/
  full/backup_id=<timestamp>/manifest.json
  full/backup_id=<timestamp>/sha256sums.txt
  full/backup_id=<timestamp>/dump/<mongodb dump files>
  indexes/archive_index.jsonl
```

R2 中的 `archive_index.jsonl` 只作为备份索引，记录每次备份的 `backupId/objectKey/sha256/byteSize/createdAt/verified`。它不参与正式查询，不替代 MongoDB 主库索引。

### 备份命令合同

新增 CLI：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id <backup_id>
.\.venv\Scripts\python.exe -m backend.cli push-mongodb-backup --backup-id <backup_id>
.\.venv\Scripts\python.exe -m backend.cli pull-mongodb-backup --backup-id <backup_id> --dry-run
.\.venv\Scripts\python.exe -m backend.cli list-mongodb-backups
.\.venv\Scripts\python.exe -m backend.cli prune-mongodb-backups --dry-run
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-datasets
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-datasets --apply
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --apply
```

行为要求：

- `backup-mongodb --full` 使用 MongoDB 原生 dump 或等价驱动导出，导出所有业务集合和索引元数据。
- 备份成功后必须计算 sha256、写 manifest，并执行一次本地 verify。
- `push-mongodb-backup` 只上传已 `verified=true` 的备份到 Cloudflare R2。
- `pull-mongodb-backup` 只下载到本地 `restore-staging`，不得直接覆盖正式 MongoDB。
- 自动备份默认只在盘后任务中运行，不在交易时间抢占资源。
- `prune-mongodb-backups` 只删除超过 `QUANT_BOARD_MONGODB_BACKUP_RETENTION_DAYS` 的本地备份目录，不删除 MongoDB 主库数据，也不删除 R2 对象。

### Cloudflare R2 复用边界

可以复用旧 SQLite 归档链路中的对象存储能力：

- S3 兼容 endpoint、bucket、access key、secret key、region 配置模式。
- 上传前本地 sha256 校验。
- `manifest.json`、对象 key、字节数、上传状态、错误信息。
- 只上传已验证产物的原则。
- R2 作为异地灾备目标的盘后调度思想。

不能复用旧语义：

- 不允许“上传 R2 成功后删除 MongoDB 主库明细”。
- 不允许把 R2 备份作为 RankTrend、回测或题材 API 的在线 fallback。
- 不允许沿用 Supabase retention 或 SQLite archive retention 的保留窗口来裁剪 MongoDB 主库。
- 不允许前端直连 R2 读取正式数据。

R2 凭据只能由 QuantBoard 后端读取，禁止进入 `VITE_*`、Dragon Board 前端构建产物或浏览器 localStorage。

### 盘后调度

迁移后的盘后任务建议替换为：

```text
mongodb-health-check
  -> backup-mongodb --full
  -> verify-mongodb-backup
  -> push-mongodb-backup to Cloudflare R2
  -> prune-local-mongodb-backups
```

禁止在新盘后任务中调用旧 `archive-auto-once`、`prune-backup` 或任何会删除主库快照明细的命令。

### 恢复策略

恢复不等于运行时 fallback。MongoDB 损坏或误删时，恢复必须停服执行：

1. 停止 Dragon Board 写入和 QuantBoard API。
2. 选择一个 `verified=true` 的备份。
3. 如果本地没有该备份，先从 Cloudflare R2 执行 `pull-mongodb-backup --dry-run` 校验远端对象列表，再下载到 `restore-staging`。
4. 校验下载后的 sha256 和 manifest。
5. 将备份恢复到临时库，例如 `dragon_board_quant_restore_staging`。
6. 对临时库运行 `verify-mongodb-migration` 同级校验：
   - 集合文档数。
   - 关键 unique index。
   - 快照 frame/stock/sector 连续性。
   - RankTrend 固定股票完整序列。
   - 题材映射和 `stock_names` 计数。
7. 校验通过后再切换正式库别名或连接配置。
8. 启动 QuantBoard API，确认 `source=mongodb` 和健康检查。
9. 在 `migration_audit` 或 `restore_audit` 记录恢复来源、时间、操作者、备份 ID、R2 object key 和校验结果。

如果恢复点之后 MongoDB 已产生正式新写入，不能直接用旧备份覆盖。必须先导出新写入业务键，并制定人工补偿方案。

### 归档策略

MongoDB 迁移后的“归档”定义改为长期备份和审计导出，不再表示从主库删除历史明细。

允许的归档：

- 按交易日导出 `snapshot_records/snapshot_frames/snapshot_stock_rows/snapshot_sector_rows` 到 Parquet 或 BSON，上传 R2/S3。
- 按回测 run 导出 `backtest_trades/backtest_equity_curve/backtest_signals`，用于离线报告和灾备。
- 导出 `archive_manifests` 或新的 `backup_manifests` 作为审计索引。
- 将全库 `mongodump`、集合级导出和 manifest 上传到 Cloudflare R2。

禁止的归档：

- 归档成功后删除 MongoDB 主库中的股票行、板块行、回测 signals 或 ThemeTrend 明细。
- 把归档文件作为正式 RankTrend 查询 fallback。
- 用归档清理来解决主库容量问题。容量问题应通过 MongoDB 索引、分片、压缩、磁盘扩容或冷热节点设计解决。

### 备份验收

迁移上线前必须至少完成一次备份恢复演练：

- 对迁移后的 MongoDB 执行 `backup-mongodb --full`。
- 校验备份 manifest 文档数与主库一致。
- 上传到 Cloudflare R2，并从 R2 拉回到 `restore-staging`。
- 恢复到 staging 数据库。
- 对 staging 运行 `verify-mongodb-migration`。
- 抽查历史 RankTrend、题材映射、回测详情和 `stock_names`。
- 确认恢复过程不依赖 SQLite、Supabase 或旧 Parquet fallback，只依赖 MongoDB 本地备份或 Cloudflare R2 备份。

## 停服迁移流程

交易时间内只允许编写文档、迁移脚本 dry-run 和只读审计。正式迁移必须等收盘后执行。

### 停服前检查

- 确认当前时间已过收盘窗口，且 Dragon Board 不再产生正式快照。
- 禁用 Dragon Board 定时快照、QuantBoard 后台自动同步、`ArchiveAutoRunner`、`BackupRetentionRunner` 和 Windows `after-market-once` 任务。
- 记录当前 Git commit、`.env.local` 快照、SQLite 文件路径、MongoDB 连接目标。
- 备份三个 SQLite 文件和 `public/data/stock_code.json`，并生成 sha256 校验值。
- 确认 MongoDB 已启用 replica set 或明确记录单机无事务风险。
- 确认 MongoDB 目标数据库为空，或已显式传入 `--replace-confirmed` 并完成旧目标备份。
- 清理或准备 Redis/cache 失效方案，避免切换后返回旧 `source=sqlite` 或旧股票代码缓存。
- 准备 MongoDB 备份目录和对象存储目标；确认有足够空间保存至少一份全库备份。
- 确认 Cloudflare R2 bucket、endpoint、access key、secret key 可用，且凭据只存在后端环境变量中。

### 执行步骤

1. 停止 Dragon Board 定时快照写入。
2. 停止 QuantBoard 后端 API。
3. 备份三个 SQLite 文件：
   - `quant-board/data/warehouse/quant_board_snapshots.db`
   - `quant-board/data/warehouse/quant_board_research.db`
   - `quant-board/data/warehouse/themeDATA.db`
4. 备份 `public/data/stock_code.json`。
5. 创建 MongoDB 数据库、集合和索引。
6. 执行迁移 dry-run，输出行数、JSON 解析错误、唯一键冲突。
7. 确认 dry-run 无阻断错误后执行 apply。
8. 执行全量校验：
   - SQLite 表行数 vs MongoDB 集合文档数。
   - SQLite 唯一键数量 vs MongoDB unique key 数量。
   - JSON 字段解析错误清单为空或可解释。
   - 指定历史日期能读取 frame + stock rows。
   - `stock_names` 数量等于 `stock_code.json` 有效代码数量。
9. 切换 `.env.local` 到 MongoDB。
10. 启动 QuantBoard 后端。
11. 启动 Dragon Board，手工保存一条快照并确认进入 MongoDB。
12. 执行一次 `backup-mongodb --full`、`verify-mongodb-backup` 和 `push-mongodb-backup`。
13. 运行最小自动化验证。

实际执行记录：

- 源文件备份：`data/backups/pre_mongodb_migration_20260512_184927/`。
- 正式迁移命令：`migrate-mongodb --apply --replace-confirmed --skip-research`。
- 迁移结果：快照集合、题材集合、`stock_names` 完成写入；研究集合按本次决策跳过旧数据，仅保留空集合和索引。
- `stock_names` 源 5617 条，去重后 5616 条；重复代码 `871753` 已写入 `migration_audit`。
- 已知源数据质量事项：源 SQLite 中有 5 个历史 frame 无 stock rows，集中在 2026-05-08 13:45-14:15 的空快照，迁移未新增该缺口。

### 停服后检查

- `GET /api/health?deep=true` 显示 MongoDB 主库可用。
- 快照、题材、回测和股票基础 API 均返回 `source=mongodb`。
- 手工保存的新快照在 `snapshot_records/snapshot_frames/snapshot_stock_rows/snapshot_sector_rows` 四个集合中都有对应记录。
- `GET /api/ranktrend/rank-series` 历史连续性检查通过，不只是返回非空。
- `GET /api/themes/mapping` 的 `themeCount/mappingCount/stockCount` 与迁移报告一致。
- `StockCodeManager` 首次加载返回 `source=mongodb`，旧 `stock_codes_cache` 不再影响结果。
- 旧 `archive-auto-once/prune-backup/after-market-once` 调度确认不会再运行。
- 至少一份 MongoDB 全库备份 `verified=true`，已上传 Cloudflare R2，并可从 R2 拉回恢复到 staging 库通过校验。

实际检查结果：

- `GET /api/health?deep=true` 返回 `mode=mongodb_primary`，MongoDB primary/theme 均 connected。
- 快照 counts、stock rows、sector rows、RankTrend rank-series、题材 counts、股票基础库和股票搜索接口均返回 `source=mongodb`。
- MongoDB 本地备份 `20260512T111904Z` 已 `verified=true`。
- R2 上传和拉回均成功；`restore-staging/backup_id=20260512T111904Z` 中 22 个 `sha256sums.txt` 记录文件校验通过。

## 回滚边界

本方案不提供运行时降级策略，但需要定义迁移失败处理边界：

- 切换 `.env.local` 前，任一 dry-run、apply 或校验失败，必须中止迁移，继续使用旧 SQLite 链路，不修改运行配置。
- 切换 `.env.local` 后、QuantBoard 尚未对外恢复服务前，如果 MongoDB 健康检查失败，可以恢复旧 `.env.local` 和 SQLite 备份后重新启动旧链路。
- QuantBoard 已启动但 Dragon Board 尚未产生新的正式快照写入前，如果发现阻断问题，可以停服并恢复旧 `.env.local`。
- 一旦 MongoDB 已接收新的正式快照、题材或研究写入，不允许静默切回 SQLite。必须先导出 MongoDB 新增业务对象，制定人工补偿或 fix-forward 方案，并在 `migration_audit` 记录处理结果。
- 如果 MongoDB 写入后出现索引或 repository bug，优先 fix-forward。只有确认新增写入已完整补偿回 SQLite 或明确丢弃且有人工记录时，才能恢复旧链路。

## 迁移脚本要求

迁移脚本应放在 `quant-board/backend/data/mongodb_migration.py` 或同等后端数据目录中，提供 CLI：

```powershell
.\.venv\Scripts\python.exe -m backend.cli migrate-mongodb --dry-run
.\.venv\Scripts\python.exe -m backend.cli migrate-mongodb --apply
```

脚本必须：

- 只读 SQLite 源库。
- 对 MongoDB 写入使用 bulk upsert。
- 按集合建立索引后再导入，或在导入前显式检查唯一键冲突。
- 将 JSON 字符串解析为结构化字段。
- 对字段缺失、非法 JSON、重复业务键输出 `migration_audit`。
- 支持重复 dry-run。
- `--apply` 前必须显式确认目标 MongoDB 数据库为空或传入 `--replace-confirmed`。

交易时间内如提前编写迁移脚本，只能满足以下条件：

- 不被生产入口 import。
- 不修改现有 API、配置解析、定时任务或依赖锁文件。
- dry-run 只能读取 SQLite、本地 JSON 和本地 Parquet 索引。
- 不创建、不清空、不写入正式 MongoDB 数据库。
- 不修改 `.env.local`。

## 验收标准

### 数据验收

- `datasets`、`snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows` 文档数与 SQLite 源表一致。已验收：4 / 536 / 536 / 109952 / 8369。
- `backtest_*`、`optimization_runs`、`golden_ranktrend_cases` 本轮按 `--skip-research` 暂不迁移旧数据，MongoDB 研究集合文档数为 0，索引已创建。
- `themes`、`theme_stock_mappings`、`theme_metadata` 文档数与 SQLite 源表一致。已验收：237 / 12215 / 2。
- `stock_names` 文档数等于 `public/data/stock_code.json` 有效去重代码数量。已验收：源 5617，重复 `871753` 1 条，MongoDB 5616。
- 所有 unique index 无冲突。
- `migration_audit` 中无阻断级错误。
- 对每个 `datasetId + snapshotType + tradingDate` 输出 frame、stock row、sector row 计数，并与 SQLite 源表一致。
- 列出所有有 frame 但无 stock rows 的 `snapshotId`；正式迁移验收要求该清单为空，或每条都有明确质量原因且不参与 RankTrend 样本。
- 对最早交易日、最新交易日、90 交易日前窗口分别校验 frame/stock/sector 连续性。

### 业务验收

- Dragon Board 正式快照保存成功，MongoDB 中出现对应 `snapshot_records/snapshot_frames/snapshot_stock_rows/snapshot_sector_rows`。
- 带涨停池增强的正式快照保存后，`snapshot_stock_rows` 能读回 `reason`、涨停时间和连板高度。
- `GET /api/snapshots/frames?dataset_id=dragonboard_live&snapshot_type=half_hour` 返回 `source=mongodb`。
- `GET /api/ranktrend/rank-series` 对 90 交易日以前日期仍能返回股票排名序列。
- 对固定股票代码集合运行完整 rank-series 校验，报告首尾日期、快照数、缺失 snapshot 数和 sampleQuality 分布；不得只验证默认 `limit=50` 的非空返回。
- RankTrend 前端刷新不再出现因历史股票行缺失导致的样本不足。
- 回测列表、回测详情、交易列表、权益曲线、signals 能正常读取。
- 题材映射 `GET /api/themes/mapping` 正常返回，计数与迁移前一致。
- 自选股添加时，`StockCodeManager` 能从后端股票基础库识别代码和名称。
- `GET /api/stocks/names` 全量返回数量、`total` 和 `stock_names` 集合计数一致；市场过滤、单票 404、搜索排序和 API 不可用错误均有测试覆盖。

### 验证命令

根项目：

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

QuantBoard：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backend.cli list-datasets
```

新增迁移验收命令：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli inspect-mongodb
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id <backup_id>
.\.venv\Scripts\python.exe -m backend.cli push-mongodb-backup --backup-id <backup_id>
.\.venv\Scripts\python.exe -m backend.cli pull-mongodb-backup --backup-id <backup_id> --dry-run
.\.venv\Scripts\python.exe -m backend.cli prune-mongodb-backups --dry-run
```

## 风险和处理

### 关系型约束丢失

MongoDB 不会自动执行跨集合外键。处理方式是用业务唯一键和迁移校验替代：

- 所有引用字段保留稳定业务键，例如 `datasetId`、`snapshotId`、`backtestRunId`、`themeId`、`stockCode`。
- Repository 写入时先验证必需父对象存在。
- 迁移后运行 orphan 检查，发现孤儿行必须进入 `migration_audit`。

### 事务边界变化

快照 ingest 需要同时写入 records、frames、stock rows、sector rows。MongoDB 应启用 replica set 并使用事务；如果本地单机 MongoDB 未启用事务，则 repository 必须通过 idempotent upsert 和写入批次审计降低半写风险。正式运行推荐使用 replica set。

### JSON 字段解析失败

非法 JSON 不应阻塞整库迁移，但必须：

- 写入 `migration_audit`。
- 使用安全默认值。
- 在最终报告中列出表名、主键、字段、错误原因。

### 大集合性能

`snapshot_stock_rows`、`backtest_signals` 是主要增长集合。必须先建复合索引，再按查询路径压测：

- 单日全快照读取。
- 单票跨日期 RankTrend 读取。
- 回测 run signals 分页读取。

### 备份恢复失效

备份恢复链路不能只在文档中存在，必须定期演练：

- 备份文件缺失、hash 不一致或 manifest 文档数不一致时，不得标记为 `verified=true`。
- Cloudflare R2 上传失败不影响 MongoDB 主库写入，但必须在健康检查或运维报告中暴露。
- R2 拉回校验失败时，不得用该备份恢复正式库。
- 恢复演练失败时，不得继续扩大主库清理或归档策略；应先修复备份链路。

### 当前交易时间窗口

在下午 3 点停服前：

- 不改 `.env.local`。
- 不改 `database.py`、`repository.py`、`main.py`。
- 不执行 `archive-auto-once`、`prune-backup` 或任何清理命令。
- 只允许写文档、写迁移脚本草案和 dry-run 只读审计。

## 实施顺序建议

1. 已完成：冻结本文方案。
2. 已完成：新增 MongoDB 配置和连接层。
3. 已完成：新增 Mongo repository，并保持 API 合同不变。
4. 已完成：新增 `StockNameRepository`、`/api/stocks/*` FastAPI 路由和 pytest 覆盖。
5. 已完成：前端 `apiService.listStockNames` 和 `StockCodeManager` 改为读取后端股票基础 API。
6. 已完成：新增 SQLite -> MongoDB 全量迁移脚本。
7. 已完成：新增 MongoDB 备份、校验、上传、staging 拉回和本地保留裁剪 CLI。
8. 已完成：真实数据 dry-run 和 apply，本轮使用 `--skip-research`。
9. 已完成：切换后端到 MongoDB。
10. 已完成：MongoDB 全库备份、R2 上传、R2 拉回到 staging 和 hash 校验。
11. 已完成：跑验收命令和手工检查。
12. 已完成：SQLite 文件作为迁移前备份封存，不再作为运行时主库。

本轮已验证：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_mongodb_migration.py -q
.\.venv\Scripts\python.exe -m backend.cli migrate-mongodb --dry-run --skip-research
.\.venv\Scripts\python.exe -m backend.cli migrate-mongodb --apply --replace-confirmed --skip-research
.\.venv\Scripts\python.exe -m backend.cli list-datasets
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id 20260512T111904Z
.\.venv\Scripts\python.exe -m backend.cli push-mongodb-backup --backup-id 20260512T111904Z
.\.venv\Scripts\python.exe -m backend.cli pull-mongodb-backup --backup-id 20260512T111904Z --dry-run
.\.venv\Scripts\python.exe -m backend.cli pull-mongodb-backup --backup-id 20260512T111904Z
```

验证结果：迁移测试 `11 passed`；MongoDB 主库、API、R2 上传和 R2 拉回 hash 校验通过。

2026-05-12 追加清理验收：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-datasets
.\.venv\Scripts\python.exe -m backend.cli cleanup-mongodb-datasets --apply
.\.venv\Scripts\python.exe -m backend.cli inspect-mongodb
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
```

结果：

- dry-run 清单确认只会删除非保留 datasets。
- apply 删除 59 个非保留 datasets、867 条非主库 `snapshot_records`、867 条非主库 `snapshot_frames`、1604 条非主库 `snapshot_stock_rows`、74 条非主库 `snapshot_sector_rows`、61 条非主库 `backtest_runs` 及其派生研究结果。
- `datasets` 当前为 1，仅 `dragonboard_live`。
- `dragonboard_live` 正式快照主库仍保留 519 records、519 frames、109936 stock rows、8353 sector rows。
- 随后执行 `backfill-empty-mongodb-snapshots --apply`：
  - `half_hour:2026-05-08:14:00` 从 `half_hour:2026-05-08:13:30` 复制 224 条股票行。
  - `hourly:2026-05-08:14:00` 从 `hourly:2026-05-08:13:00` 复制 100 条股票行。
  - `quarter_hour:2026-05-08:13:45` 从 `quarter_hour:2026-05-08:13:30` 复制 224 条股票行。
  - `quarter_hour:2026-05-08:14:00` 从 `quarter_hour:2026-05-08:13:30` 复制 224 条股票行。
  - `quarter_hour:2026-05-08:14:15` 从 `quarter_hour:2026-05-08:14:30` 复制 232 条股票行。
- 补齐后 `verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour` 通过，`emptyFrames=[]`。
