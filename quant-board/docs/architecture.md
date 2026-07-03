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
  snapshot_collector/   # [实验] 后端快照采集器（shadow 模式），含 models/slots/providers/builder/quality_gate/state/repository_port/service/service_factory
  ranktrend/            # Python 版 rankTrend 分析链
  core/
    strategy/           # 策略接口和 rankTrend 候选策略
    engine/             # 回测事件循环、撮合、绩效统计
    portfolio/          # 现金、持仓、交易成本、风控
  optimization/         # 独立参数优化模块：搜索方法、目标函数、任务状态、实验记录
  api/                  # FastAPI 路由（含 `/api/snapshot-collector/*` 实验路由）
  cli/                  # 命令行入口（含 `snapshot-collector-*` 实验命令）
  reports/              # 报告导出辅助
```

当前仓库已有 `backend/main.py`、`backend/settings.py`、`backend/data/database.py`、`backend/data/models.py`，后续实现应在这些骨架上增量补齐。

### 实验性后端快照采集器（shadow 模式）

`backend/snapshot_collector/` 是一个实验性的后端快照采集器，当前处于 shadow-only 阶段。该模块从 proxy-server 和 python-bridge 实时拉取热榜与行情数据，在 QuantBoard 后端独立完成快照组装、规范化和质量门禁。它不嵌入浏览器运行时；为保持 shadow/live 股票覆盖一致，股票池优先复用 Dragon Board live 前端写入 proxy-server 的 startup bundle，缓存缺失时再走 proxy-server 八平台热榜 union fallback。

模块结构：

```text
backend/snapshot_collector/
  models.py           # SnapshotSlot, MarketDataContext, QualityResult, CollectorRunRequest/Result, SourceHealth
  slots.py            # SLOT_TIMES, generate_slots(), is_slot_eligible()
  trading_calendar.py # is_trading_day(), trading_date_from_ts()
  providers.py        # StartupBundleStockProvider, ProxyMergedHotlistProvider, ProxyHotlistProvider, ProxyQuoteProvider, BridgeQuoteProvider, ProxyLimitUpProvider, ThemeMappingProvider
  builder.py          # build_ingest_payload()
  quality_gate.py     # evaluate_quality()
  state.py            # record_run(), get_status()
  repository_port.py  # SnapshotRepository Protocol
  service.py          # SnapshotCollectorService (run_once, backfill_slots, audit 等)
  service_factory.py  # create_snapshot_collector_repository()
  scheduler.py        # SnapshotCollectorScheduler 后台 asyncio 轮询 runner
  supervisor.py       # Windows shadow 采集守护进程，复用依赖并在独立 8001 端口启动 collector API
```

当前状态和边界：

- 默认禁用：通过 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=false` 关闭所有采集行为。
- 写目标独立：默认只写入 `dragonboard_backend_shadow` 数据集（由 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID` 控制），不得在未进入正式切换流程时写入 `dragonboard_live` 正式主库。
- 禁止写入 live 数据集：`QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET` 默认 `false`，防止实验采集污染正式快照事实；Phase 6 正式切换时必须显式设为 `true`，CLI 预检和 quality gate 才会放行 `dragonboard_live`，其它 dataset 仍拒绝。
- Shadow-only：该采集器产出仅用于平行对照和验收，不得作为生产快照来源或 Dragon Board 正式读源。
- 质量门禁在前：quality_gate 在写入前检查数据源健康、股票行数量和时间窗口，被阻止的运行写入 `snapshot_collector_runs`（状态 `blocked`）并保留审计轨迹。运行记录会保存 `sourceHealth`、`captureMode`、核心行数和完成时间，方便 Phase 4 shadow/live 对比审计。
- API 路由 `/api/snapshot-collector/*` 和 CLI 命令 `snapshot-collector-*` 只服务实验运维和审计。
- 自动调度器（Phase 3）：`SnapshotCollectorScheduler` 是独立的 `asyncio` 后台 runner（模块级单例），在 FastAPI `startup` 时注册到事件循环。轮询间隔由 `QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS`（默认 1000ms）控制，每个 tick 检查交易日、槽位表、时间窗口和 MongoDB 中的 `datasetId + snapshotId` 是否已存在，只为真正缺失且符合条件的 slot 启动 fire-and-forget 采集任务。调度器在非 MongoDB 模式或 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=0` 时自动禁用。采集任务的并发保护通过内存中的 `_in_flight_slots` 集合实现，确保同一 slot 不会重复采集。
- 本机 shadow 守护：`supervisor.py` 只负责实验采集运行环境，不改变采集业务合同。它复用健康的 MongoDB、proxy-server 和 python-bridge，并使用 `8001` 运行目标工作区 collector API，避免替换主工作区 `8000` API。MongoDB 通过 `ping` 检查，proxy-server/python-bridge 校验结构化 `/health` 服务身份；collector 必须同时满足 scheduler `enabled=true`、`running=true` 和 `dataset_id=dragonboard_backend_shadow`。`proxy-server` 只复用健康的 `127.0.0.1:3000`，缺失或不健康时标记 `blocked`，不得从隔离 worktree 启动代理接管主看板端口。守护进程自己启动的非 proxy 服务如仍占端口但健康检查失败，会被终止并重启；未知外部进程只标记 `blocked`，不会误杀。
- 后端 collector 优先通过 `StartupBundleStockProvider` 读取 proxy-server `/api/cache/startup-bundle` 中由 Dragon Board live 前端写入的 merged stocks，作为与 live 快照一致的完整股票池；若 startup bundle 缺失或无效，默认改用 `ProxyMergedHotlistProvider` 调用八个平台热榜接口做 union 合并，避免 shadow 静默降级为东财 top100。单平台 `ProxyHotlistProvider` 只保留为诊断工具。只有 startup bundle 失败且 `merged_hotlist_proxy` 也未成功时，质量门禁才以 `startup_bundle_missing` 阻断写入。
- 后端 collector 通过共享 `ThemeHeatService` 写入全量 `entityType=hot_theme` rows；`sector_rows=0` 仅是替换前历史快照的已知缺口，新 shadow 帧不得再以外部端口不可用为由允许空题材行。
- 正式切换要求：shadow 采集器必须通过完整审计（覆盖率、质量门禁、数据一致性）后才能讨论 live cutover。

**生产口径尚未完成的接入（截至 Phase 4 审计后的当前状态）：**

以下数据源在生产级快照中是必需的。当前后端 collector 已补齐前端已有来源中明确漏接的逐股题材、涨停池、bridge 盘口和 bridge 高低价解析；历史 shadow 数据不会因此自动回填，必须以后续新采集审计为准。

1. **Depth（盘口深度）**：默认 provider 已挂载 `BridgeQuoteProvider`，并兼容 python-bridge 返回的 `bids/asks` 结构，builder 会落 `depth10`、`bid1Price/bid1Volume`、`ask1Price/ask1Volume`。当前 bridge 已验证边界仍是 L1 + 标准五档，不得描述成官方客户端级 L2 或真十档。

2. **股票快照行情接管**：股票池已通过 live startup bundle 优先对齐 live merged stocks，并在缓存缺失时通过八平台 union fallback 保持覆盖范围不退回单平台 top100。行情增量同时使用 `ProxyQuoteProvider` 和 `BridgeQuoteProvider`：proxy 补资金流/东财字段，bridge 补实时价格、盘口、高低价和昨收；builder 会派生 `amplitude`，但该字段只在 Mongo shadow payload 中自然保留，SQLite 历史模型没有独立列。

3. **Theme 数据源**：MongoDB 全市场映射、腾讯基础行情和东财资金字段已由共享 `ThemeHeatService` 聚合，使用 `theme-market-v1`、5 分钟缓存和覆盖率门禁；collector 保存全部 factors 为 `hot_theme` rows。默认 provider 也会挂载 `ThemeMappingProvider`，逐股写入 `themes/mainTheme/sectorLabel`。少数股票仍可能因题材基础库未覆盖而缺失，这属于映射库质量缺口，不是 collector 未接入。

4. **市场情绪 / 涨停池 / 轮动摘要**：涨停池已接入 `ProxyLimitUpProvider`，写入 `limitUpPool/reason/firstZtTime/lastZtTime/boardHeight/highDays/fengdan` 等事件字段。该字段只应出现在涨停池相关股票上，不能按全量股票 100% 覆盖要求审计。市场情绪和轮动摘要仍依赖既有研究链路或后续专项，不应伪造成空字段通过。

当前代码接入类缺口已补齐，但 shadow 仍需至少两个完整交易日的新采集落库审计，确认 row count、字段覆盖、题材映射缺口、资金降级和质量警告后，才能讨论 live cutover。

API 路由：

- `GET /api/snapshot-collector/status`：采集器运行状态
- `POST /api/snapshot-collector/run-once`：单次采集运行
- `POST /api/snapshot-collector/backfill-slots`：按日期区间回填槽位
- `GET /api/snapshot-collector/runs`：历史运行记录
- `POST /api/snapshot-collector/audit`：快照覆盖率审计
- `POST /api/snapshot-collector/compare`：两数据集快照对比（shadow vs live），同时报告仅单侧存在和两侧共同缺失的预期槽位
- `GET /api/snapshot-collector/scheduler/status`：调度器运行状态

CLI 命令：

- `snapshot-collector-status`：打印采集器运行状态
- `snapshot-collector-run-once`：执行单次采集并输出 JSON 结果
- `snapshot-collector-backfill`：按日期区间批量采集
- `snapshot-collector-audit`：审计覆盖率并输出结构化 JSON
- `snapshot-collector-compare`：对比两个数据集的快照覆盖率和字段完整性
- `snapshot-collector-scheduler-status`：打印调度器运行状态

响应信封格式：所有 `/api/snapshot-collector/*` 接口使用统一的 `{"ok": true/false, "status": "...", "data": {...}}` 信封。这与现有 API 的混合格式不同，仅用于采集器实验路由。

python-bridge 采集接口（Phase 2）：

为支持后端独立采集（不依赖浏览器 WebSocket 订阅），`python-bridge` 新增以下 HTTP 接口：

- `POST /api/quotes/subscriptions` — 设置后端采集订阅池，body `{"codes": ["000001", "600000"]}`，立即 fetch 行情并缓存
- `GET /api/quotes/snapshot` — 不带 `codes` 参数时回退到订阅池缓存，返回 `{"pooled": true, "poolRefreshedAt": ...}` 标记；带 `?codes=...` 时保持 Phase 1 按需抓取行为

BridgeQuoteProvider（`backend/snapshot_collector/providers.py`）已适配：
- `set_pool(codes)` — 注册采样池到 bridge
- `collect(use_pool=True)` — 使用池缓存抓取，含 `poolStalenessMs`（默认 30s）陈旧检测

StartupBundleStockProvider — 当前默认股票池来源：

`StartupBundleStockProvider` 调用 proxy-server 的启动缓存接口读取 live 前端最近写入的完整 merged stocks：

- `GET /api/cache/startup-bundle?key=default:YYYY-MM-DD` — 返回 `schemaVersion=1` 的 startup bundle，包含 `platformData` 和完整 `stocks`
- collector 使用 run request 的 `tradingDate` 构造 key，因此按目标交易日对齐 live 缓存
- `collect_market_context` 在 startup bundle 成功时直接以其 `stocks` 作为 `MarketDataContext.stocks`，并跳过热榜 fallback
- startup bundle 缺失、过期或结构无效时，`SourceHealth(source=startup_bundle, ok=false)` 会进入审计；collector 随后运行 `ProxyMergedHotlistProvider`，从 `eastmoney/ths/kpl/tdx/xueqiu/cls/tgb/dzh` 八个平台取数、按代码 union、生成各平台 rank 字段和 `avgRank/compRank/rank`
- 只有 startup bundle 失败且 `ProxyMergedHotlistProvider` 未成功产出股票池时，新 shadow 写入才会被 `startup_bundle_missing` 阻断

该设计优先复用 live 已完成的八平台合并、综合排名、题材/涨停扩展和 RankTrend 增强结果；当 live 页面或主工作区近期未刷新 startup bundle 时，后端只复制股票池覆盖所需的最小合并合同（八平台 union 和排名字段），不复制前端完整热度/题材/涨停增强算法。

ProxyQuoteProvider — 当前默认 quote 数据源（过渡方案）：

`service.py` 的 `_create_providers` 当前同时挂载 `ProxyQuoteProvider` 和 `BridgeQuoteProvider`。`ProxyQuoteProvider` 保留为东财 quote/资金字段补充；`BridgeQuoteProvider` 是实时价格、五档盘口、高低价和昨收的主要来源。

`ProxyQuoteProvider` 直接调用 proxy-server 的 EastMoney HTTP 端点获取实时行情和资金流数据：

- `GET /api/quotes/eastmoney?codes=...` — proxy-server 的 EastMoney 行情端点，返回 f12(代码)、f2(价格)、f3(涨跌幅)、f5(成交额)、f6(成交量)、f8(换手率)、f9(市盈率)、f20(总市值) 以及 f62/f66/f69/f184(资金流) 字段
- `ProxyQuoteProvider.collect(codes)` — 接收代码列表，返回 `{quotes, depth: [], money_flow, market_meta}` 结构，与 `BridgeQuoteProvider` 兼容，可在 `collect_market_context` 中互换路由
- 当 proxy-server 返回 `ok=false` 或 `degraded=true` 的降级信封时，`ProxyQuoteProvider` 会把本次 quote 源标记为 `SourceHealth(ok=false)`，不把 HTTP 200 的降级响应当成健康行情。
- `collect_market_context` 将 `ProxyQuoteProvider` 返回的 `money_flow` 写入 `MarketDataContext.money_flow`，由 builder 的 `_enrich_stock_rows_from_quotes()` 同步填充到 stock rows 的 `moneyFlow`（结构化 dict）、`pe` 和 `totalMarketValue` 字段

仍需注意的能力边界：

- `ProxyQuoteProvider` 自身的 `depth` 仍为空；盘口来自 `BridgeQuoteProvider`。
- 当前 bridge 盘口是已验证的五档边界，不是真 L2 十档。`depth10` 字段名沿用前端合同，但正常情况下可能只有五档。
- `amplitude` 由 bridge 的 `high/low/preClose` 派生；历史 live/shadow 快照中该字段可能仍为空，因为旧前端快照 builder 没有落该字段。

生产口径的预期终态：

1. `BridgeQuoteProvider` 作为实时 quote/depth 源，通过 python-bridge 获取 TDX 实时行情和五档盘口。
2. `ProxyQuoteProvider` 作为东财 quote/资金补充和 bridge 异常时的辅助来源。
3. `depth` 字段在 bridge 正常运行时非空，审计应按实际采集日期报告覆盖率。
4. 后续如需真 L2 十档或逐笔，必须走隔离探针或 QMT/券商 L2 来源，不得把当前五档能力升级描述。

**进入 live cutover 前，仍需用新 shadow 落库数据证明字段覆盖和质量门禁稳定，而不是用历史缺字段快照推断当前代码能力。**

## 数据流

1. 导入阶段
   - 输入：MongoDB 主库中的正式快照事实集合，历史 SQLite/JSON/IndexedDB 导出只作为迁移来源。
   - 输出：`datasets`、`snapshot_records`、`snapshot_frames`、`snapshot_stock_rows`、`snapshot_sector_rows`。
   - 写入策略：Dragon Board 正式快照通过 `POST /api/snapshots/ingest` 落 MongoDB；`sourceType=mongodb_snapshots` 只建立研究视图/筛选口径，不再复制快照事实行。SQLite/Supabase 旧写入和 failover 链路在 Mongo 模式下禁用。

2. 分析阶段
   - 输入：按 `dataset_id + snapshot_type + date range` 查询的标准快照序列。
   - 输出：Python rankTrend 结果，结构对齐 golden case。
   - 热榜情绪：日终热榜情绪写入 MongoDB `hotlist_sentiment`，按 `datasetId + snapshotType + tradingDate` 唯一定位；RankTrend 策略层读取该集合替代全市场 `market_regime()` 作为候选分层情绪输入。
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
- `POST /api/hotlist-sentiment/ingest`、历史回填脚本和 MongoDB 模式 `after-market-once` 共同写入 `hotlist_sentiment`；MongoDB 不可用时结构化失败，策略回测只能显式中性回退并保留原因。
- 正式主库的历史残缺修复通过 `backfill-empty-mongodb-snapshots` 统一处理，允许补空快照、补 `snapshot_record`、修 frame 计数、补缺失的 `15:00` formal close slot，以及补运行库缺失索引；补槽位优先同粒度最近 donor，必要时允许显式跨粒度 donor；修复动作必须写 `migration_audit(opType=mongodb_snapshot_repair)`。
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

MongoDB 模式下 `snapshot_frames` 还承担 formal snapshot 修复对账基线：

- `stockRowCount/sectorRowCount` 必须与对应子集合真实行数一致。
- 历史修复产生的 donor 信息写入 `metadata.backfill`。
- 跨粒度补槽位会把 `captureMode` 标记为 `synthesized`，并把 `source` 标记为 `cross_type_backfill`。

### snapshot_stock_rows

一条快照内的一只股票一行，是 rankTrend、回测、前端列表的主要事实表。
涨停池增强字段随股票行保存，包括 `reason`、`firstZtTime`、`lastZtTime`、`boardHeight`、`highDays`、`fengdan` 等；MongoDB 模式保持 camelCase 字段，SQLite/Supabase 历史同构表使用对应 snake_case 列。

RankTrend 信号列随股票行保存：`directionSignal/Confidence`、`accelerationSignal/Confidence`、`crossSignal/Confidence`（零轴穿越）、`finalSignal/Confidence`、`jumpDirection`（跃迁方向）、`jumpConfidence`（跃迁度）、`macdCross`（MACD 金叉死叉）、`resonanceIntensity`（共振强度，由上述信号加权派生）。

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

常规报告导出与页面展示不再以 `backtest_runs.resultCompressed` 或 `backtest_result_chunks` 作为首选明细源。默认路径应直接迭代 `backtest_trades`、`backtest_equity_curve`、`backtest_signals` 和 `backtest_quality_reports`，并在需要落盘时输出 `jsonl-bundle` 或流式 `json.gz`。兼容完整结果追溯时才回退到 `resultCompressed/resultChunked`。

### backtest_trades

MongoDB 模式下保存在 `backtest_trades` 集合，保存单次回测的成交和持仓生命周期明细。它是回测报告交易列表的主数据源，不进入 Supabase、`sync_outbox`、push/pull 或 failover 链路。导出热路径按 `backtestRunId + sequence` 升序迭代读取。

### backtest_equity_curve

MongoDB 模式下保存在 `backtest_equity_curve` 集合，保存单次回测权益曲线，按时间升序供图表读取。它不进入 Supabase。导出热路径按 `backtestRunId + sequence` 升序迭代读取。

### backtest_signals

MongoDB 模式下保存在 `backtest_signals` 集合，保存 RankTrend 信号诊断、候选分层和市场状态。信号诊断不能当作真实成交列表使用，交易列表必须读取 `backtest_trades`。大报告导出默认按 `backtestRunId + sequence` 升序流式读取，不再先聚合成单个超大 Python dict。

### backtest_quality_reports

MongoDB 模式下保存在 `backtest_quality_reports` 集合，保存样本覆盖率、质量门禁和研究等级。质量报告必须显式表达 `passed`、`severity` 和结构化原因，不能用空对象表示通过。

### hotlist_sentiment

MongoDB 模式下保存在 `hotlist_sentiment` 集合，保存每日热榜情绪研究输入。唯一业务键是 `datasetId + snapshotType + tradingDate`，默认 `snapshotType=half_hour`。字段包括 `stage`、`riskLevel`、`confidence`、`metrics`、`turnover`、`signals` 和 `warnings`。历史回填和日终调度都必须复用同一字段合同，不得用临时简化口径生成参与回测的 `stage/riskLevel`。

### trade_journal

MongoDB 模式下保存在 `trade_journal` 集合，承载候选池、交易池和真实历史交易日志三类语义：

- `tradeType=thesis`：候选池 thesis 记录，是交易池二次筛选的来源。
- `tradeType=trading_pool`：交易池 V2 持久化记录，通过顶层 `candidateEntryId` 指向来源 thesis，并在 `signalsSnapshot.tradingPool` 保存当前状态、决策、原因、信号快照和 `lastRecomputedAt`。
- `tradeType=entry/exit`：真实历史交易日志，只表示实际买卖。

交易池记录不得反向改写候选池 lifecycle，也不得创建真实 `entry` 交易记录；`已介入` 只是交易池工作台确认态。

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
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED` | 是否启用后端快照采集器，默认 `false` |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID` | 采集器写入目标数据集 ID，默认 `dragonboard_backend_shadow` |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES` | 采集器覆盖的快照类型，逗号分隔，默认 `half_hour,daily` |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS` | 采集轮询间隔（毫秒），默认 1000 |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_CLOSE_GRACE_MINUTES` | 收盘后宽限采集分钟数，默认 5 |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_PROXY_BASE_URL` | proxy-server 基础 URL，默认 `http://127.0.0.1:3000` |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_BRIDGE_BASE_URL` | python-bridge 基础 URL，默认 `http://127.0.0.1:8765` |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_PROVIDER_TIMEOUT_MS` | 数据源请求超时（毫秒），默认 30000；覆盖 `proxy-server` EastMoney quote fallback 的慢请求窗口 |
| `QUANT_BOARD_THEME_HEAT_BATCH_SIZE` | 腾讯题材基础行情批大小，默认 50 |
| `QUANT_BOARD_THEME_HEAT_MAX_CONCURRENCY` | 腾讯批次最大并发，默认 3 |
| `QUANT_BOARD_THEME_HEAT_CACHE_TTL_SECONDS` | 全市场题材热度缓存秒数，默认 300 |
| `QUANT_BOARD_THEME_HEAT_FAILED_BATCH_RETRIES` | 失败批次重试次数，默认 1 |
| `QUANT_BOARD_THEME_HEAT_QUOTE_COLLECTION_TIMEOUT_MS` | 腾讯全市场行情整次采集预算，默认 90000 毫秒；超时后剩余批次记为失败并进入覆盖率门禁 |
| `QUANT_BOARD_THEME_HEAT_FUND_COLLECTION_TIMEOUT_MS` | 东财资金整次采集预算，默认 30000 毫秒；超时后资金字段按 null 降级 |
| `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET` | 是否允许写入 live 数据集，默认 `false` |

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
