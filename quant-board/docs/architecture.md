# QuantBoard 架构设计

## 架构目标

首期架构只服务一个核心闭环：

`dragon-board 快照数据 -> QuantBoard 数据集 -> Python rankTrend -> 回测 -> 独立优化模块 -> API/CLI/前端报告`

这里的 Python rankTrend 必须对齐 TypeScript golden 标准。QuantBoard 是仓库内唯一回测平台，Dragon Board 根项目只提供实时看板、快照数据和 TypeScript golden 导出。

V12 目标新增一条与 RankTrend 并列的 ThemeTrend 研究链：

`dragon-board 快照题材/股票行 + MongoDB 题材基础映射 -> Python ThemeTrend -> 题材趋势/共振回测 -> 独立优化模块 -> API/CLI/前端报告`

该链路是新增平台化合同和首批落地方向，不表示所有实现已经完成。MongoDB 模式下 ThemeTrend 新研究结果保存在 MongoDB 研究集合，不进入 Supabase；题材基础映射集合只承载静态映射，不承载回测、优化、题材因子运行态或研究结果。Dragon Board 根项目不新增回测平台。

## 模块分层

```text
backend/
  data/                 # 数据库、快照导入、质量门禁、数据查询
  ranktrend/            # Python 版 rankTrend 分析链
  core/
    strategy/           # 策略接口和 rankTrend 候选策略
    engine/             # 回测事件循环、撮合、绩效统计
    portfolio/          # 现金、持仓、交易成本、风控
  optimization/         # 独立参数优化模块：搜索方法、目标函数、任务状态、实验记录
  api/                  # FastAPI 路由
  cli/                  # 命令行入口
  reports/              # 报告导出辅助
```

当前仓库已有 `backend/main.py`、`backend/settings.py`、`backend/data/database.py`、`backend/data/models.py`，后续实现应在这些骨架上增量补齐。

## 数据流

1. 导入阶段
   - 输入：MongoDB 主库中的正式快照事实集合，历史 SQLite/JSON/IndexedDB 导出只作为迁移来源。
   - 输出：`datasets`、`snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
   - 写入策略：Dragon Board 正式快照通过 `POST /api/snapshots/ingest` 落 MongoDB；`sourceType=mongodb_snapshots` 只建立研究视图/筛选口径，不再复制快照事实行。SQLite/Supabase 旧写入和 failover 链路在 Mongo 模式下禁用。

2. 分析阶段
   - 输入：按 `dataset_id + snapshot_type + date range` 查询的标准快照序列。
   - 输出：Python rankTrend 结果，结构对齐 golden case。
   - V12 目标：ThemeTrend 读取标准快照中的题材/板块行、股票行和 MongoDB 题材基础映射，输出题材强度、扩散、持续性、拥挤、风险和质量报告。ThemeTrend 与 RankTrend 并列，不替代 RankTrend golden 链。

3. 策略阶段
   - 输入：每个快照、每只股票的 rankTrend 结果和行情字段。
   - 输出：候选标的、入场/离场意图、解释原因。

4. 回测阶段
   - 输入：策略信号、价格、交易配置、随机种子。
   - 输出：权益曲线、交易列表、绩效指标、诊断信息。

5. 优化阶段
   - 输入：参数搜索空间、目标函数、训练/验证区间。
   - 处理：由 `backend/optimization/**` 独立编排搜索方法和任务状态；`runner.py` 只保留入口，`search_space.py`、`samplers.py`、`trial.py`、`objective.py`、`validation.py`、`walk_forward.py`、`stability.py` 等模块分别承担核心计算职责，并调用回测引擎执行 trial。
   - 输出：候选参数排名、样本内/样本外表现、`running/completed/failed` 状态和实验记录。

6. 展示阶段
   - 输入：MongoDB 研究集合中的 `backtest_runs`、`optimization_runs`、报告数据。
   - 输出：API、CLI、前端图表。

## 当前 MongoDB 主库、备份与旧链路边界

本节只描述当前架构边界。MongoDB 全量切换、备份恢复、禁用旧入口和验收清单统一维护在 [mongodb-migration-plan.md](mongodb-migration-plan.md)。下方保留的 SQLite/Supabase/Parquet 内容是迁移前历史方案，用于理解迁移来源和审计资产，不再代表当前生产运行主链。

当前数据库模式是 MongoDB 运行主库，R2/S3 保存 MongoDB dump/manifest 异地备份：

```text
QuantBoard API/CLI -> MongoDB primary -> MongoDB full backup -> R2/S3 object backup
Dragon Board theme mapping -> QuantBoard API -> MongoDB theme collections
SQLite/Supabase/Parquet legacy paths -> migration source or disabled endpoints in Mongo mode
```

规则：

- MongoDB 是正式快照、研究结果、题材基础映射和股票基础库的运行事实源。
- Dragon Board 前端仍只能通过 QuantBoard 后端 API 访问正式数据，不直连 MongoDB。
- `POST /api/snapshots/ingest` 是 Dragon Board 正式快照进入 MongoDB 的主入口。
- `GET /api/snapshots/frames`、`GET /api/snapshots/records`、`GET /api/snapshots/stock-rows`、`GET /api/snapshots/sector-rows` 和 `GET /api/snapshots/counts` 从 MongoDB 读取，响应字段保持既有 camelCase API 合同。
- `GET /api/themes/mapping`、`GET /api/themes/stocks/{theme_id}`、`GET /api/themes/stocks/by-code/{code}` 和 `GET /api/themes/counts` 从 MongoDB 题材集合读取。
- 旧 SQLite/Supabase/Parquet 同步、归档、清理和历史 JSON 导入入口在 Mongo 模式下返回 410 或 CLI 拒绝执行；不得静默触碰旧主链。
- MongoDB 不可用时正式接口必须结构化失败，不回退到 Supabase、SQLite、Parquet 或 IndexedDB 并伪装成功。

## 迁移前本地热库、Parquet 归档与对象备份

当前数据库模式是本地三库、Parquet 冷归档、DuckDB 只读查询和对象存储备份：

```text
QuantBoard API/CLI -> SQLite snapshot hot primary -> Parquet snapshot archive -> DuckDB read fallback -> R2/S3 object backup
QuantBoard API/CLI -> SQLite research hot DB -> Parquet research archive -> DuckDB read fallback
Dragon Board theme mapping -> SQLite themeDATA primary
Supabase keeps only the recent dragonboard_live disaster-recovery window
```

规则：

- `quant_board_snapshots.db` 是默认快照热库，负责正式快照即时写入、近期低延迟读取、frame/record 元数据和 `archive_manifests`。
- `quant_board_research.db` 是本地研究热库，负责回测、优化、Golden、报告索引和近期回测归一化结果明细。
- `themeDATA.db` 是题材静态映射主库，负责题材基础表、题材-股票关系、股票-题材反查、标签和原因。它不进入回测/优化事实链，也不承载题材因子运行态。
- V12 ThemeTrend 研究结果只写入 `quant_board_research.db` 或后续 research Parquet 归档，不进入 `themeDATA.db`、Supabase、`sync_outbox` 或快照事实库。
- `data/archive/**` 保存 Parquet 冷归档，默认使用 zstd 压缩。
- DuckDB 只在后端读取 Parquet，不提供任意 SQL API，也不暴露给 Vue 前端。
- R2/S3 兼容对象存储保存 Parquet 和 manifest 的异地备份。
- 旧 `quant_board.db` 只作为 legacy source 保留，用于 `migrate-legacy-db` 拆分迁移；它不再是默认主库。
- Supabase 不暴露给 Vue 前端，只由后端使用 `SUPABASE_URL` 和 `SUPABASE_SECRET_KEY` 访问；它只保留 `dragonboard_live` 最近 10 个交易日灾备窗口，不是大体积历史主线。
- 正常快照写入先提交 SQLite 快照库，再把同一份快照事实镜像到 Supabase。
- 快照库写入成功后会登记轻量 `sync_outbox`，即使 Supabase 当次不可用，也能通过 `push-backup` 按事实表实时组包补偿；outbox 只覆盖快照事实和数据集 bundle。
- SQLite 初始化或查询失败时，读路径会回退到 Supabase 备份记录。
- 迁移前 SQLite 不可用但 Supabase 可写时，快照 ingest 曾可切到 Supabase 并返回 `status=backup_only`；MongoDB 模式下该 failover 已禁用。
- `POST /api/sync/push-backup` 默认只把已有 SQLite 最近保留窗口内的数据主动推送到 Supabase；全历史推送必须显式使用 `full_history=true` 或 CLI `--full-history`。
- `POST /api/sync/prune-backup` 用于按最近 10 个交易日裁剪 Supabase 云端备份库，只删除云端 `snapshot_*` 和对应 `sync_outbox`，不删除本地 SQLite 或 Parquet。
- `POST /api/sync/push-outbox` 和后台自动同步只消费到期 outbox，不做全量历史扫描。
- `POST /api/sync/smoke-backup` 用于真实 Supabase REST 写读删联调，只写入并清理云端 `sync_outbox` 临时探针。
- `POST /api/snapshots/ingest` 是 Dragon Board 正式快照进入 QuantBoard 后端的主入口。
- `GET /api/snapshots/frames` 是 Dragon Board 正式分析读取 MongoDB 快照聚合帧的主入口。
- `GET /api/snapshots/records`、`GET /api/snapshots/records/{snapshot_id}`、`GET /api/snapshots/stock-rows`、`GET /api/snapshots/sector-rows` 是 Dragon Board `DataLayer` 零散正式读口的 MongoDB 承接层。
- `frames`、`records`、`stock-rows`、`sector-rows` 列表读口可通过 Redis read-through cache 加速；Redis 只缓存响应，MongoDB 仍是事实源。
- `GET /api/snapshots/counts` 用于 MongoDB 快照事实集合行数核对。
- `POST /api/datasets/import` 的日常主入口从 MongoDB 正式快照事实集合生成可复现研究视图，不复制快照事实行。
- `POST /api/migrations/snapshots/import-json` 是历史 IndexedDB/JSON/结构化导出的可重复迁移入口。
- `POST /api/migrations/themes/import-json` 是历史 `ThemeDataDB/theme_mapping` JSON 的可重复迁移入口。
- `GET /api/themes/mapping`、`GET /api/themes/stocks/{theme_id}`、`GET /api/themes/stocks/by-code/{code}` 和 `GET /api/themes/counts` 是 Dragon Board 题材基础数据的 MongoDB 正式读口。
- 同键重复同步必须幂等；同键不同 payload/hash 必须标记冲突，不允许静默覆盖。

Supabase 备份库必须使用快照事实库同构 schema，不再使用旧 `snapshots.payload` 兼容方案。云端 schema 由 [../backend/data/supabase_schema.sql](../backend/data/supabase_schema.sql) 维护，只包含 `datasets`、`snapshot_*` 和 `sync_outbox`。健康检查会逐表检查这些快照备份表是否可读；缺表时不得继续把备份链路视为可用。

回测、优化和 Golden 不再作为 Supabase Free 版备份目标。MongoDB 模式下 `backtest_runs`、`backtest_trades`、`backtest_equity_curve`、`backtest_signals`、质量报告和摘要进入 MongoDB 研究集合；旧 research SQLite 只作为迁移前历史来源。

### archive_manifests

保存 Parquet 归档索引。每条记录对应一个快照分区或一个回测 run，包含 `archive_id`、`scope`、`dataset_id`、`snapshot_type`、`trading_date`、`run_id`、`local_path`、`object_key`、`status`、行数、文件 hash、字节数和错误信息。恢复、DuckDB 查询和 R2 上传都以该表为入口。

Dragon Board 前端 `DataLayer` 对外字段不随迁移删改。正式快照写入通过 `POST /api/snapshots/ingest` 落 MongoDB；后端按 `dataset_id + snapshot_id` 和 `idempotencyKey` 做逻辑幂等，重复槽位不会覆盖既有事实行。正式读取走 QuantBoard MongoDB API，返回仍是 `SnapshotRecord`、`SnapshotFrameBundle`、`SnapshotStockRow`、`SnapshotSectorRow` 的现有 camelCase 字段。IndexedDB 快照缓存默认关闭，只保留历史迁移源和显式缓存用途；`five_minute` 浏览器本地入口不再保留。

Dragon Board 题材基础映射由 `ThemeDataService` 通过 `GET /api/themes/mapping` 读取 MongoDB 题材集合。旧 `themeDATA.db` 和浏览器 `ThemeDataDB/theme_mapping` 只保留为离线历史迁移源，不作为排障缓存或运行时 fallback；本地静态 JSON 和 `/api/themes/batch` 也不再补齐题材基础事实。新增或更新题材映射不得写回浏览器 IndexedDB。

如果后续调整 Supabase 表字段、索引、恢复策略或 payload JSON 字段，必须同批更新 [database-migration-plan.md](database-migration-plan.md)、[api-cli.md](api-cli.md) 和 SQL schema 文件。

## 关键数据库表

### datasets

记录一个可复现实验数据集：

- `id`：数据集 ID，例如 `ds_20260430_half_hour_import01`
- `source_type`：日常为 `sqlite_snapshots`；`json_bundle`、`browser_bridge`、`leveldb` 只作为迁移兼容来源
- `schema_fingerprint`：导入结构指纹
- `snapshot_count`、`frame_count`、`stock_row_count`
- `start_date`、`end_date`
- `snapshot_types_json`

### snapshot_records

保留快照元信息和采集质量字段，不再保存完整 payload。正式分析应优先读 frame/row 表。

### snapshot_frames

一条标准快照一行，保存市场摘要和统计上下文。

### snapshot_stock_rows

一条快照内的一只股票一行，是 rankTrend、回测、前端列表的主要事实表。
涨停池增强字段随股票行保存，包括 `reason`、`firstZtTime`、`lastZtTime`、`boardHeight`、`highDays`、`fengdan` 等；MongoDB 模式保持 camelCase 字段，SQLite/Supabase 历史同构表使用对应 snake_case 列。

### snapshot_sector_rows

一条快照内的板块、题材、主线实体一行。首期可先导入，策略使用可后置。

### golden_ranktrend_cases

MongoDB 模式下保存在 `golden_ranktrend_cases` 集合，保存 TypeScript golden 输入和期望输出。Python 移植必须用它做回归校验。

### backtest_runs

MongoDB 模式下保存在 `backtest_runs` 集合，保存单次回测请求和完整结果载荷。`request` 使用结构化子文档；完整回测结果优先写入可逆 gzip/base64 文本字段 `resultCompressed`，读取层透明还原为 `result_json`。如果压缩后仍超过安全阈值，则 `backtest_runs` 只保存 `resultChunked=true` 和分块数量，实际压缩文本按顺序写入 `backtest_result_chunks`，读取时透明拼接。旧数据中的 `result` 子文档只作为兼容读取字段。交易、权益曲线、信号和质量报告仍以独立集合为主。必须记录：

- `dataset_id`
- `strategy_name`
- `strategy_version`
- `snapshot_type`
- `config_hash`
- `random_seed`
- `date_start`
- `date_end`
- `finished_at`
- `error_reason`
- `request`
- `resultCompressed`
- `resultChunked`
- `resultChunkCount`

### backtest_result_chunks

MongoDB 模式下保存在 `backtest_result_chunks` 集合，保存压缩后仍过大的 `backtest_runs.resultCompressed` 分块。每行包含 `backtestRunId`、`sequence` 和 `payload`，并通过 `(backtestRunId, sequence)` 唯一索引保证顺序与幂等。该集合只服务兼容完整结果追溯；页面明细仍优先读取归一化的交易、权益、信号和质量集合。

### backtest_trades

MongoDB 模式下保存在 `backtest_trades` 集合，保存单次回测的成交和持仓生命周期明细。它是回测报告交易列表的主数据源，不进入 Supabase、`sync_outbox`、push/pull 或 failover 链路。

### backtest_equity_curve

MongoDB 模式下保存在 `backtest_equity_curve` 集合，保存单次回测权益曲线，按时间升序供图表读取。它不进入 Supabase。

### backtest_signals

MongoDB 模式下保存在 `backtest_signals` 集合，保存 RankTrend 信号诊断、候选分层和市场状态。信号诊断不能当作真实成交列表使用，交易列表必须读取 `backtest_trades`。

### backtest_quality_reports

MongoDB 模式下保存在 `backtest_quality_reports` 集合，保存样本覆盖率、质量门禁和研究等级。质量报告必须显式表达 `passed`、`severity` 和结构化原因，不能用空对象表示通过。

### optimization_runs

MongoDB 模式下保存在 `optimization_runs` 集合，保存一次优化实验及候选参数列表。优化不是覆盖默认参数的动作，而是产生可验证候选；任何优化结果都不得自动写回策略、API、CLI 或前端默认参数。

必须记录：

- `dataset_id`
- `strategy_name`
- `strategy_version`
- `snapshot_type`
- `config_hash`
- `random_seed`
- `method`
- `status`：`running`、`completed` 或 `failed`
- `request_json`
- `result_json`

### ThemeTrend 研究结果

V12 Phase 1 已落地 ThemeTrend 专用研究归一化表，写入 `quant_board_research.db`：

- `theme_factor_frames`：单帧题材因子快照，记录每个快照时刻的题材强度、动量、扩散、资金、龙头、联动、拥挤、持续性、轮动状态、生命周期和质量标记。
- `theme_stock_exposures`：单帧股票-题材暴露快照，记录每只股票在特定题材中的角色、得分、暴露权重、贡献度和风险惩罚。
- `theme_signals`：单帧题材信号，记录每个题材的策略信号（mainline/expansion/ignition/risk/reduce/watch）、风险类型和生命周期。
- `theme_quality_reports`：数据集级质量报告，记录门禁结果（passed/severity/researchGrade）、问题清单、警告清单和统计信息。

以上表均保留完整溯源链：`dataset_id`、`snapshot_id`、`snapshot_type`、`trading_date`、`slot_time`、`strategy_version`、`config_hash`、`random_seed`。

V12 后续 Phase 中，ThemeTrend 和 Theme Confluence 回测/优化仍复用现有 `backtest_runs`、`backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports` 和 `optimization_runs`。通过 `strategy_name=theme_trend_candidate` 或 `strategy_name=theme_confluence_candidate` 区分研究链。

首批不为 ThemeTrend 建 Supabase 同步链；所有 ThemeTrend 研究表归属 `quant_board_research.db` local-only 链路，不写入 `sync_outbox`。

### research SQLite 清理边界

历史回测清理只作用于 `quant_board_research.db`。前端“删除本次回测”、`DELETE /api/backtests/{run_id}` 和 CLI `delete-backtest` 会按固定顺序显式删除 `backtest_trades`、`backtest_equity_curve`、`backtest_signals`、`backtest_quality_reports`，最后删除 `backtest_runs`，不依赖 SQLite 外键级联。

批量清理通过 `research-cleanup-preview` / `research-cleanup` 或 CLI `cleanup-research` 执行，默认只清理 30 天以前的 completed 回测，并按 `dataset_id + strategy_name + strategy_version + snapshot_type + config_hash + random_seed` 分组至少保留最近 10 条。该能力不会删除 `quant_board_snapshots.db` 的正式快照事实，不会写入 `sync_outbox`，也不会同步到 Supabase。

在线 API 删除后只允许执行 `PRAGMA wal_checkpoint(TRUNCATE)`；真正收缩 SQLite 文件的 `VACUUM` 只能由 CLI 显式传入 `--vacuum` 执行，避免前端操作长时间锁库。

### sync_outbox

保存主库写入成功但 Supabase 镜像尚未确认的补偿同步任务。它只服务 SQLite 主库 + Supabase 备份库并行策略，不改变业务主链；详细语义以 [database-migration-plan.md](database-migration-plan.md) 为准。

当前支持的 `op_type`：

- `dataset_bundle`
- `snapshot_ingest`

状态语义：

- `pending`：SQLite 已成功写入，尚未确认 Supabase 镜像。
- `retry`：Supabase 镜像失败，等待 `next_retry_at` 后由 `push-backup` 重试。
- `done`：Supabase 已确认。
- `failed`：达到重试上限，需要人工检查 `last_error`。

后台自动同步：

- 默认关闭，需要设置 `QUANT_BOARD_AUTO_SYNC_ENABLED=true`。
- 启动后只调用 outbox 推送口径，不自动执行全量 `push-backup`。
- 设计目的只是补偿 Supabase 短暂不可用后的待同步业务对象，不承担历史大批量迁移。

## 配置来源

建议配置分三层：

1. 项目默认值：代码里的保守默认，例如 `snapshot_type=half_hour`。
2. YAML 配置：`config/*.yaml`，用于本地实验。
3. 请求参数：API/CLI 显式传入，优先级最高。

所有最终执行配置都要写入 `request_json`，并用稳定 JSON 计算 `config_hash`。

数据库相关环境变量：

| 变量 | 说明 |
| --- | --- |
| `QUANT_BOARD_SNAPSHOT_DATABASE_URL` | SQLite 快照事实库连接串，默认是 `quant-board/data/warehouse/quant_board_snapshots.db` |
| `QUANT_BOARD_RESEARCH_DATABASE_URL` | SQLite 研究库连接串，默认是 `quant-board/data/warehouse/quant_board_research.db` |
| `QUANT_BOARD_THEME_DATABASE_URL` | SQLite 题材映射主库连接串，默认是 `quant-board/data/warehouse/themeDATA.db` |
| `QUANT_BOARD_DATABASE_URL` | 旧兼容变量；如果指向 legacy `quant_board.db` 会被忽略，应改用上面两个双库变量 |
| `SUPABASE_URL` | Supabase 项目 URL |
| `SUPABASE_SECRET_KEY` | 后端专用密钥，禁止放入 `VITE_` 前端变量 |
| `QUANT_BOARD_ENABLE_SUPABASE_BACKUP` | 是否启用 Supabase 备份镜像，默认按 Supabase 配置自动启用 |
| `QUANT_BOARD_ENABLE_BACKUP_READ_FALLBACK` | 是否启用备份读回退，默认跟随备份镜像 |
| `QUANT_BOARD_BACKUP_TIMEOUT_SECONDS` | Supabase 请求超时时间 |
| `QUANT_BOARD_AUTO_SYNC_ENABLED` | 是否自动推送到期 outbox，默认关闭 |
| `QUANT_BOARD_AUTO_SYNC_INTERVAL_SECONDS` | 自动同步间隔，默认 60 秒 |
| `QUANT_BOARD_AUTO_SYNC_INITIAL_DELAY_SECONDS` | API 启动后首次同步延迟，默认 10 秒 |
| `QUANT_BOARD_AUTO_SYNC_BATCH_SIZE` | 单轮自动同步批量，默认 50 |

存储和同步配置的语义变更属于 API/运维合同变更，必须同批更新 [database-migration-plan.md](database-migration-plan.md)、[api-cli.md](api-cli.md) 和 [AI_COLLABORATION.md](AI_COLLABORATION.md)。

## 策略边界

首期策略名建议固定为：

```text
rank_trend_candidate
```

V12 拟新增策略名：

```text
theme_trend_candidate
theme_confluence_candidate
```

策略只消费 Python rankTrend 输出，不直接依赖 dragon-board UI、前端事件或浏览器全局对象。

ThemeTrend 策略消费 Python ThemeTrend 输出和标准快照事实；共振策略以 RankTrend 候选为主，ThemeTrend 只辅助候选排序、置信度、拥挤风险降级和解释，不得绕过 RankTrend 独立制造买入信号。

`src/services/strategyBacktest` 的历史职责归并到 Python 后端：

- 快照回放与样本质量：`backend.data.repository`、`backend.data.quality_gate`
- RankTrend 回放：`backend.analysis.ranktrend.RankTrendPythonEngine`
- 后验分布与 forward validation：`backend.core.backtest.OutcomeEvaluator`
- 交易模拟与撮合：`backend.core.backtest.TradeSimulator`
- 回测编排：`backend.core.backtest.BacktestEngine`
- 参数优化：`backend.optimization` 独立模块调用回测引擎执行 trial，并负责搜索方法、目标函数和实验记录

策略输出不等于交易指令。它应至少包含：

- 候选分层：`A_MAIN`、`B_IGNITION`、`C_CROWDED`、`D_EXIT_RISK`、`N_NEUTRAL`
- 建议动作：`focus`、`watch`、`hold`、`avoid`、`exit_watch`
- 风险解释
- 样本质量

交易执行由回测引擎根据入场/离场规则统一处理。

## 快照类型原则

默认：

```text
snapshot_type = half_hour
```

支持：

- `half_hour`：首期默认和主要验收口径。
- `quarter_hour`：显式选择的可选研究口径。
- `hourly`、`daily`：可导入和诊断，首期不作为主回测默认。

禁止：

- 在 API、CLI、前端里把 `quarter_hour` 写成默认。
- 在 API、CLI、前端里绕过 QuantBoard 后端另做根项目回测入口。

## 可复现性

同一组输入应能得到同一结果：

- 相同 `dataset_id`
- 相同 `snapshot_type`
- 相同日期区间
- 相同策略版本
- 相同参数
- 相同 `random_seed`

若结果不同，要优先检查排序稳定性、浮点舍入、缺失字段默认值、随机数来源和数据导入顺序。

## 错误处理

所有核心服务返回结构化错误：

```json
{
  "ok": false,
  "error": {
    "code": "QUALITY_GATE_FAILED",
    "message": "样本不足",
    "details": {
      "required_sample_count": 30,
      "actual_sample_count": 12
    }
  }
}
```

不要用空数组、空报告或 `0` 指标假装成功。

## 首期非目标

- 不接实盘交易。
- 不做自动下单。
- 不把优化结果自动写回 dragon-board、QuantBoard、API、CLI 或前端表单默认参数。
- 不在 Dragon Board 根项目重建回测模块。
- 不为了前端演示绕过 golden 校验和质量门禁。
