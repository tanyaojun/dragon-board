# QuantBoard Backend Snapshot Collector Design

> [!CAUTION]
> **本设计已被生产事故证伪，禁止作为当前实现或评审依据。** 文档仅作为事故历史保留。其中“正式写入前质量门禁”“硬性阻断”“只写 collector run、不写 snapshot facts”以及分阶段 shadow/live 切换方案，曾导致连续一周多快照数据缺失，平台排名和排名分析字段无法恢复。当前数据链路规则以根目录 `AGENTS.md` 的“4.0 数据链路禁止硬门禁”和 `skills/fail-visible-data-pipelines/SKILL.md` 为准：除全源无任何原始记录外，质量问题必须保存已有数据、标记并主动上报；读取、查询、回放和界面观察同样不得阻断或伪造为空、零值、单帧。

> **事故后的有效方向只有一个：采集与观察链路 fail visible，不因质量判断 fail closed。** 本文后续内容不再代表项目认可的架构口径。

## 背景

2026-06-11 的 MongoDB 快照质量审计已经证明，当前正式快照生产链路仍然依赖 Dragon Board 浏览器运行态。前端页面打开后，`SnapshotRuntime` 注册 `snapshot.sweep`，再从 `DataLayer` 内存读取热榜、行情、题材、情绪、轮动等上下文，构造 `SnapshotDayBundle`，最后调用 QuantBoard `POST /api/snapshots/ingest` 写入 MongoDB。

这个结构能工作，但它不是严格的前后端分离。浏览器页面是否打开、是否被系统休眠、是否被后台限流、`DataLayer` 是否已经初始化、实时行情 WebSocket 是否已经订阅，都会影响正式快照是否按时入库。`half_hour:15:00` 缺槽位问题就是这个架构风险的直接表现。

本设计的目标不是再补一个前端定时器，而是把正式采集能力收进 `quant-board/backend`，让 QuantBoard 后端成为正式数据生产、质量门禁、MongoDB 入库、快照审计和回测研究的唯一主链。Dragon Board 前端最终只负责展示、交互、手动诊断和调用后端 API。

## 目标

1. QuantBoard 后端独立按交易日槽位生成正式快照，不依赖 Dragon Board 页面是否打开。
2. Dragon Board 前端和 QuantBoard 后端形成清晰的前后端分离边界：前端消费 API，后端生产和存储事实数据。
3. MongoDB 仍是正式主库，正式写入只能走 QuantBoard 后端 repository，不允许前端或采集器直连 MongoDB。
4. 后端采集链路必须保留 `dataset_id`、`snapshot_type`、`snapshot_id`、`trading_date`、`slot_time`、`capture_mode`、`source`、`quality_flags` 等可追溯字段。
5. 后端采集链路必须有影子数据集、审计对比、生产切换门槛和回滚边界，不在未验证时替换现有生产快照。
6. 最终关闭 Dragon Board 浏览器自动正式快照写入，只保留手动诊断入口或显式 fallback。

## 非目标

1. 不在第一阶段重写 RankTrend、回测、优化或 ThemeTrend 策略。
2. 不让 Dragon Board 前端直连 MongoDB、R2、Supabase 或任何数据库密钥。
3. 不恢复 IndexedDB、SQLite 或 Supabase 作为正式快照读写 fallback。
4. 不把 `python-bridge` 当前的 L1 + 标准五档能力包装成官方客户端级 L2。
5. 不在第一阶段强制删除 `proxy-server`。它会先被收编为后端数据源适配对象，再逐步迁移或退役。
6. 不在主工作区直接改生产代码。实现必须在隔离 worktree 中完成，验证通过后再讨论合并。

## 当前链路审计结论

当前正式快照写入链路：

```text
Dragon Board 页面启动
  -> src/services/snapshot/facade.ts 自动 snapshotFacade.start()
  -> SnapshotRuntime.startTimer()
  -> refreshScheduler 每秒触发 snapshot.sweep
  -> collectPendingSnapshotSlots(now)
  -> saveQuarterHourSnapshot / saveHalfHourSnapshot / saveHourlySnapshot / saveDailySnapshot
  -> getBuildContext() 从 DataLayer 内存取 stocks / quotes / depth10 / ticks / themes / breath / rotation
  -> buildCanonicalProjectionBundle()
  -> snapshotBackendIngest.ingestDayBundle()
  -> QuantBoard POST /api/snapshots/ingest
  -> normalize_snapshot_ingest()
  -> MongoRepository.save_snapshot_ingest()
  -> snapshot_records / snapshot_frames / snapshot_stock_rows / snapshot_sector_rows
```

关键问题：

- 定时器在浏览器进程内，页面关闭则没有采集。
- 快照原材料在 `DataLayer` 内存内，后端没有独立构建 `SnapshotBuildContext` 的能力。
- `snapshot.sweep` 虽然已经设置为隐藏时继续运行，但仍受浏览器生命周期、系统睡眠和前端初始化状态影响。
- QuantBoard 后端目前只有被动 ingest 能力，没有主动 scheduler、collector、builder 和生产状态 API。
- `proxy-server` 现在是 Dragon Board 前端配套代理，但里面已有热榜、行情、市场概览、情绪、涨停池等正式采集能力；这些能力需要被 QuantBoard 后端接管或迁移。

## 目标架构

最终架构：

```text
External data sources
  ├─ public hotlist APIs
  ├─ market overview APIs
  ├─ theme mapping in MongoDB
  ├─ python-bridge / TDX quote bridge
  └─ future official/broker L2 source

QuantBoard Backend
  ├─ snapshot_collector/
  │   ├─ __init__.py
  │   ├─ models.py
  │   ├─ slots.py
  │   ├─ providers.py
  │   ├─ builder.py
  │   ├─ quality_gate.py
  │   ├─ state.py
  │   ├─ repository_port.py
  │   ├─ service.py
  │   ├─ service_factory.py
  │   └─ scheduler.py            # Phase 2+ 自动调度
  └─ data/
      └─ snapshot_ingest_normalizer.py  # 从 backend/main.py 解耦提取
  ├─ MongoRepository
  ├─ /api/snapshots/*
  ├─ /api/snapshot-collector/*
  └─ backend.cli snapshot-collector-*

Dragon Board Frontend
  ├─ read-only snapshot API client
  ├─ live UI data display
  ├─ backend collector status panel or diagnostics
  └─ manual/debug snapshot save only
```

正式数据生产归属：

- `quant-board/backend` 是唯一正式快照生产者。
- `Dragon Board src/**` 不再拥有生产级定时快照职责。
- `proxy-server` 短期作为数据源代理，长期要么迁入 QuantBoard 后端，要么定义为独立 Market Data Service，不再是 Dragon Board 前端附属服务。
- `python-bridge` 保持本地行情桥角色，但调用方从浏览器迁到 QuantBoard 后端。

## 模块设计

### `snapshot_collector.models`

负责定义后端采集链路内部模型。模型不直接复用前端 Vue 或 `DataLayer` 类型，但字段名要对齐 MongoDB 和 API camelCase 合同。

核心模型：

- `SnapshotSlot`: `snapshot_type`、`trading_date`、`slot_time`、`timestamp_ms`。
- `CollectorRunRequest`: 手动或定时触发参数，例如 `dataset_id`、`snapshot_types`、`now`、`force`、`dry_run`。
- `CollectorRunResult`: 采集结果，例如 `status`、`snapshot_id`、`created`、`deduped`、`quality_issues`、`source_counts`、`error`。
- `MarketDataContext`: 后端版快照构建上下文，承接股票、行情、depth、tick、题材、市场情绪、指数、涨停池、轮动摘要。
- `SourceHealth`: 数据源健康度，例如 `source`、`ok`、`latency_ms`、`row_count`、`error`、`captured_at`。

设计原则：

- 后端模型只服务采集和构建，不让 Dragon Board 前端运行时对象进入后端。
- `MarketDataContext` 必须能表达“某个来源缺失但不阻断”的情况，由质量门禁决定是否允许入库。
- 所有时间统一用 Asia/Shanghai 交易日和毫秒时间戳，MongoDB 中继续保存 `timestamp` 毫秒值。

### `snapshot_collector.slots`

负责槽位表、交易日历和槽位时间规则。与 `models.py` 中的 `SnapshotSlot` 模型配合，提供槽位生成、交易时间判断、午休过滤和 close slot grace window 逻辑。

槽位表（从 `scheduler` 职责中拆分，Phase 1 即可验证）：

```text
quarter_hour: 09:30,09:45,10:00,10:15,10:30,10:45,11:00,11:15,11:30,13:00,13:15,13:30,13:45,14:00,14:15,14:30,14:45,15:00
half_hour:    09:30,10:00,10:30,11:00,11:30,13:00,13:30,14:00,14:30,15:00
hourly:       10:00,11:00,13:00,14:00,15:00
daily:        15:00
```

### `snapshot_collector.repository_port`

定义 collector 对 MongoDB 仓储的抽象协议（`Protocol`），包含 `snapshot_exists`、`save_snapshot_ingest`、`insert_run`、`list_runs`、`collector_status`、`audit_dataset`。实现层由现有 `mongo_repository.py` 补最小方法后适配，API 和 CLI 通过 `service_factory` 获取实现，不直接依赖具体仓储类。

### `snapshot_collector.service_factory`

负责从环境变量 `QUANT_BOARD_STORAGE_BACKEND` 创建正确的 service/repository 实例。API 路由和 CLI 通过 `service_factory` 获取 `SnapshotCollectorService`，避免重复构造依赖链。

### `snapshot_collector.scheduler`

负责后端常驻槽位扫描。**Phase 1 只设计接口，实现在 Phase 3 完成。**

启动后使用轻量 asyncio 后台任务，不引入重型调度框架。原因是当前任务只有快照槽位扫描和审计，FastAPI startup/shutdown 已有后台 runner 先例，轻量 runner 更容易控制启停、测试和生产切换。

职责：

- 根据槽位表生成待采集 slot。
- 支持 `quarter_hour`、`half_hour`、`hourly`、`daily`。
- 支持交易日判断、午休、节假日、15:00 close slot grace window。
- 每次触发前先查询 MongoDB 是否已有 `datasetId + snapshotId`；已存在 slot 不创建后台采集任务。
- 防止同一 slot 并发采集。
- 支持影子 dataset 和正式 dataset 分离。
- 维护最近运行状态，供 API 查询。

默认槽位：

```text
quarter_hour: 09:30,09:45,10:00,10:15,10:30,10:45,11:00,11:15,11:30,13:00,13:15,13:30,13:45,14:00,14:15,14:30,14:45,15:00
half_hour:    09:30,10:00,10:30,11:00,11:30,13:00,13:30,14:00,14:30,15:00
hourly:       10:00,11:00,13:00,14:00,15:00
daily:        15:00
```

生产配置：

- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=0` 默认关闭。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_backend_shadow` 默认写影子数据集。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES=half_hour,daily` 第一阶段默认只开最小闭环。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_POLL_MS=1000`。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_CLOSE_GRACE_MINUTES=5`。后端 collector 不依赖浏览器生命周期，收盘后数据源通常在数秒内就绪，5 分钟 grace window 足够覆盖网络抖动和 provider 延迟；不需要前端那种大窗口。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_PROXY_BASE_URL=http://127.0.0.1:3000`。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_BRIDGE_BASE_URL=http://127.0.0.1:8765`。
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_PROVIDER_TIMEOUT_MS=5000`。
  Correction note (2026-06-23): two-day shadow/live audit showed the
  proxy EastMoney quote path can exceed 5s while exercising fallback/cache
  paths, so the runtime default was raised to `30000`.
- `QUANT_BOARD_SNAPSHOT_COLLECTOR_ALLOW_LIVE_DATASET=0`。额外安全开关，即使 `ENABLED=1` 且 `DATASET_ID=dragonboard_live`，也必须在 `ALLOW_LIVE_DATASET=1` 时才会真正写入正式数据集；防止误配置直接污染生产数据。

### `snapshot_collector.providers`

负责从后端拉取数据源，不做快照业务构建。

短期 Provider：

- `StartupBundleStockProvider`: 优先读取 proxy-server startup bundle，复用 live 前端写入的完整 merged stocks。
- `ProxyMergedHotlistProvider`: startup bundle 缺失时调用 `proxy-server` 八个平台热榜接口做 union fallback，保持 shadow 股票覆盖不退回单平台 top100。
- `ProxyHotlistProvider`: 调用 `proxy-server` 单平台热榜接口，仅作为诊断 provider 保留。
- `ProxyQuoteProvider` (当前默认，**过渡方案**): 调用 `proxy-server` EastMoney 行情端点 `GET /api/quotes/eastmoney?codes=...`，获取实时行情和资金流数据。返回 `{quotes, depth: [], money_flow, market_meta}`，其中 money_flow 的 `mediumNetInflow` 由 EastMoney 字段推导。depth 固定为空（proxy-server 无盘口端点）。proxy-server 返回 `ok=false` 或 `degraded=true` 的降级信封时，本 provider 必须返回 `SourceHealth(ok=false)`，避免把降级 HTTP 200 误判为健康行情。**这是临时过渡配置：生产口径应使用 `BridgeQuoteProvider` 作为主 quote 源（通过 python-bridge 获取 TDX 实时行情和五档盘口），`ProxyQuoteProvider` 仅作为 bridge 离线时的 fallback。**`service_factory.py` 当前只挂载 `ProxyQuoteProvider`，不挂载 `BridgeQuoteProvider`，是 Phase 4 验证阶段的临时安排。
- `BridgeQuoteProvider`: 调用 `python-bridge` 新增或既有接口获取当前行情、depth、tick、money flow。保留用于需要 bridge WebSocket pool 模式的场景。
- `ThemeMappingProvider`: 直接通过 QuantBoard MongoDB 题材集合读取题材映射。
- `StockNameProvider`: 读取 MongoDB `stock_names`，补充名称和基础状态。

长期 Provider：

- 把 `proxy-server` 中正式数据源适配能力迁入 QuantBoard 后端，形成 Python provider。
- `proxy-server` 只保留本地开发代理或完全退役。
- L2 资金流 Provider 明确区分 `estimated_l1`、`broker_l2`、`official_l2`。

Provider 返回必须包含：

- 数据行。
- 来源名。
- 采集时间。
- 延迟。
- 是否降级。
- 错误信息。

Provider 不允许：

- 直接写 MongoDB 快照集合。
- 生成 snapshot_id。
- 决定正式入库成功。

### `python-bridge` 接口补充

当前 `python-bridge` 主要通过 WebSocket 推送给浏览器。后端采集更适合读取一次性快照，因此需要新增只读 HTTP 接口。

建议新增：

```text
GET /api/quotes/snapshot
```

返回当前 bridge 缓存的完整状态：

```json
{
  "ok": true,
  "source": "python_bridge",
  "serverTs": 1781170800000,
  "subscribedCount": 214,
  "quotes": [],
  "depth": [],
  "ticks": [],
  "moneyFlow": [],
  "quoteStats": {},
  "l2": {}
}
```

设计要求：

- 该接口只读，不触发大规模重新订阅。
- 如果当前没有订阅池，返回结构化 `ok=false` 或 `subscribedCount=0`，由后端 collector 记录数据源不足。
- 不能因为新增 HTTP 快照接口改变现有 WebSocket 行为。
- 当前 bridge 的 L2 状态必须原样返回，不能把估算资金流伪装成正式 L2。

订阅池问题：

- 当前前端通过 WebSocket 订阅热榜股票池，bridge 的 `aggregate_pool()` 才知道要拉哪些代码。
- 后端 collector 接管后，必须由 QuantBoard 后端根据热榜结果调用 bridge 订阅或提供采样代码池。
- 第一阶段只实现 `GET /api/quotes/snapshot?codes=000001,600000`（显式传入代码列表），不新增 `POST /api/quotes/subscriptions`。
- Phase 2 再引入后端维护的采样股票池和稳定订阅。
- 长期应由 QuantBoard 后端维护当天采样股票池，bridge 只负责行情读取。

### `snapshot_collector.builder`

负责把 `MarketDataContext` 转为和现有 `SnapshotDayBundle` 等价的 records、frames、stockRows、sectorRows。

第一阶段策略：

- 不追求一次复刻前端全部 UI 派生字段。
- 先保证正式回测和 RankTrend 需要的稳定字段完整，包括排名、价格、涨幅、成交额、成交量、换手、量比、热度、题材、资金流来源、depth10、涨停池字段、市场上下文。
- 生成的 bundle 继续通过现有 `normalize_snapshot_ingest()` 和 `MongoRepository.save_snapshot_ingest()` 入库。

实现前置条件：`normalize_snapshot_ingest()` 当前位于 `backend/main.py`，collector 模块不能 import `backend.main`（会造成循环导入）。Phase 1 第一步必须把该函数及其直接依赖提取到 `backend/data/snapshot_ingest_normalizer.py`，`backend/main.py` 改为从新位置 re-import。提取行为不改变现有 ingest 行为。
- `source` 写为 `quantboard_backend_collector`。
- `captureMode` 根据 slot 时间和实际采集时间计算：实时窗口内为 `real_time`，超过阈值为 `delayed`。
- `qualityFlags` 必须记录延迟、缺少 provider、低样本、行情陈旧等问题。

与前端 builder 的关系：

- 第一阶段后端 builder 可以用 Python 独立实现字段映射，不从 `src/services/snapshot/builders.ts` 运行时 import。
- 需要建立 golden 对齐测试：同一组固定 `MarketDataContext`，后端 builder 输出的关键字段与前端旧 bundle 样例一致。
- 字段兼容性以 MongoDB API 合同和 RankTrend 读取需求为准，不以 UI 内部临时字段为准。

### `snapshot_collector.quality_gate`

正式写入前必须执行质量门禁，不能让空快照或伪完整数据进入主库。

硬性阻断：

- formal snapshot 的股票行数为 0。
- `snapshot_id`、`type`、`tradingDate`、`slotTime` 缺失或非法。
- 热榜来源全部失败。
- 股票代码全为空或非 A 股代码。
- `timestamp` 不落在目标 `tradingDate + slotTime`。
- 写入目标 dataset 是正式 `dragonboard_live`，但 collector 仍处于 shadow-only 模式。

允许入库但记录质量标记：

- 行情 Provider 缺少部分股票。
- depth10 缺失。
- money flow 为 `estimated_l1`。
- 题材映射缺少部分股票。
- 延迟采集。
- sector rows 少于预期但 stock rows 完整。

质量输出：

```json
{
  "ok": true,
  "blockingIssues": [],
  "warnings": ["quote_provider_partial"],
  "sourceCounts": {
    "hotlistRows": 214,
    "quoteRows": 209,
    "depthRows": 180,
    "sectorRows": 32
  }
}
```

### `snapshot_collector.state`

负责保存采集器运行态和审计事件。

建议新增 MongoDB 集合：

- `snapshot_collector_runs`
- `snapshot_collector_state`

`snapshot_collector_runs` 记录每次 slot 尝试：

```json
{
  "runId": "collector:half_hour:2026-06-11:15:00:1781170800000",
  "datasetId": "dragonboard_backend_shadow",
  "snapshotId": "half_hour:2026-06-11:15:00",
  "type": "half_hour",
  "tradingDate": "2026-06-11",
  "slotTime": "15:00",
  "status": "completed",
  "created": true,
  "deduped": false,
  "source": "quantboard_backend_collector",
  "sourceHealth": [],
  "captureMode": "real_time",
  "stockRowCount": 120,
  "frameCount": 1,
  "sectorRowCount": 4,
  "quality": {},
  "startedAt": "2026-06-11T15:00:01+08:00",
  "finishedAt": "2026-06-11T15:00:04+08:00",
  "error": null
}
```

`snapshot_collector_state` 保存最近状态：

- 是否启用。
- 当前 dataset。
- 最近成功 slot。
- 最近失败 slot。
- 当前是否运行中。
- 当前版本。
- 上次审计结果。

这些集合只服务采集状态和排障，不替代正式快照事实集合。

### API 设计

新增 API：

```text
GET  /api/snapshot-collector/status
POST /api/snapshot-collector/run-once
POST /api/snapshot-collector/backfill-slots
GET  /api/snapshot-collector/runs
POST /api/snapshot-collector/audit
```

`GET /api/snapshot-collector/status`

- 返回 collector 是否启用、目标 dataset、运行中状态、最近成功/失败、配置、最近审计摘要。

`POST /api/snapshot-collector/run-once`

请求：

```json
{
  "datasetId": "dragonboard_backend_shadow",
  "snapshotType": "half_hour",
  "tradingDate": "2026-06-11",
  "slotTime": "15:00",
  "dryRun": true,
  "force": false
}
```

行为：

- `dryRun=true` 只构建和质量检查，不写正式快照集合。
- `force=false` 时已有 snapshot 则返回 deduped。
- `datasetId=dragonboard_live` 必须要求 collector 处于正式启用状态，避免误写生产。

`POST /api/snapshot-collector/backfill-slots`

- 用于后台采集链路运行后补缺槽。
- 默认 dry-run。
- 可传日期范围、类型、目标 dataset。
- 不替代现有 `backfill-empty-mongodb-snapshots`，后者仍是 MongoDB 事实层修复工具。
- 日期范围按 `startDate` 和 `endDate` 闭区间生成目标 slot，不允许隐式扩大范围；周末和已知节假日会被跳过。
- `force=false` 时已有 slot 必须跳过并返回 `deduped` 或 `skipped_existing`。
- `dryRun=true` 必须完整执行 slot 生成、provider 读取、builder、normalizer 和质量门禁，但不得写事实集合。
- `apply` 模式只写缺失且通过质量门禁的 slot。
- 部分 slot 失败时返回 `ok=false` 和 per-slot 结果，成功 slot 不回滚；每个尝试都必须写 collector run 记录。

`GET /api/snapshot-collector/runs`

- 分页查询采集运行记录。
- 支持按 dataset、type、tradingDate、status 过滤。

`POST /api/snapshot-collector/audit`

- 对后端采集目标 dataset 执行缺槽、空帧、record 缺失、计数漂移审计。
- 正式切换前必须用于 shadow vs live 对比。

### CLI 设计

新增 CLI：

```powershell
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-status
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00 --dry-run
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-backfill --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --start-date 2026-06-11 --end-date 2026-06-11 --dry-run
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
```

CLI 用途：

- 不依赖前端页面和浏览器。
- 方便在隔离 worktree、任务计划程序或人工运维中验证。
- 与 API 使用同一 service，避免两套实现。

## 分阶段实施

### Phase 0: 隔离工作区和基线冻结

目标：

- 在独立 worktree 中实施，不影响当前主工作区。
- 冻结当前前端快照合同、MongoDB ingest 合同和审计工具结果。

工作：

- 创建 `quantboard-backend-snapshot-collector` worktree。
- 记录当前 `git status` 和基线测试。
- 在 shadow dataset 模式下做所有实现。
- 不修改 `.env.local` 的生产 MongoDB 配置。

验收：

- worktree 路径清晰。
- 基线测试结果记录。
- 主工作区没有新增代码改动。

### Phase 1: 后端 collector 最小闭环

目标：

- 不打开 Dragon Board 页面、也不依赖浏览器 WebSocket 订阅，手动运行后端 collector 能构建并写入 `half_hour` 和 `daily` 影子快照。

范围：

- 新增 `quant-board/backend/snapshot_collector/**`。
- 新增 API 和 CLI 的最小 run-once。
- Provider 可先调用 `proxy-server` 现有能力。
- 在 `python-bridge/main.py` 新增最小只读 `GET /api/quotes/snapshot?codes=...`，让后端可以显式传入股票池并读取行情快照。
- Builder 先覆盖 RankTrend 和正式快照必需字段。

验收：

```powershell
python -m unittest discover python-bridge -p "test_*.py"
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector.py -q
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00 --dry-run
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type daily --trading-date 2026-06-11 --slot-time 15:00 --dry-run
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
```

通过条件：

- shadow dataset 中有 record、frame、stock rows、sector rows。
- formal snapshot 股票行数大于 0。
- dry-run 不写库。
- 重复运行 deduped。
- 没有浏览器连接时，后端仍能指定代码并获得行情结果。

### Phase 2: Bridge 订阅池和行情稳定性增强

目标：

- QuantBoard 后端可以稳定从 `python-bridge` 获取指定股票池的行情快照，不依赖浏览器 WebSocket 订阅。

范围：

- 在 Phase 1 的 `GET /api/quotes/snapshot?codes=...` 基础上增加后端维护的采样池。
- 支持批量 codes、缓存状态、失败降级和行情陈旧标记。
- QuantBoard `BridgeQuoteProvider` 使用稳定订阅池而不是每次临时拼接。
- QuantBoard `BridgeQuoteProvider` 使用稳定订阅池而不是每次临时拼接。
- QuantBoard `ProxyQuoteProvider` 已落地，通过 proxy-server EastMoney 端点获取实时行情和资金流数据，写入 `MarketDataContext.money_flow`，由 builder 的 `_enrich_stock_rows_from_quotes()` 充实 stock rows。**这是过渡方案，不是生产口径。**生产口径应挂载 `BridgeQuoteProvider` 作为主 quote 源（具备 depth 和 TDX 实时行情），`ProxyQuoteProvider` 降级为 fallback。截至 Phase 4，`service_factory.py` 仍只挂载 `ProxyQuoteProvider`，depth 恒为空。

验收：

```powershell
python -m unittest discover python-bridge -p "test_*.py"
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_bridge_provider.py -q
```

通过条件：

- 没有浏览器连接时，后端仍能维护采样池并获得行情结果。
- bridge 原 WebSocket 行为不变。
- 行情缺失时返回结构化错误，不写空正式快照。

### Phase 3: 四类快照和自动 scheduler

目标：

- 后端自动按槽位写入 `quarter_hour`、`half_hour`、`hourly`、`daily` 影子快照。

范围：

- Scheduler 支持所有槽位。
- 交易日和 close slot grace window 与前端现有 schedule 对齐。
- 采集运行记录写入 `snapshot_collector_runs`。

验收：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_scheduler.py -q
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_backend_shadow --snapshot-type quarter_hour
```

通过条件：

- 模拟时间测试覆盖 09:30、午休、15:00、非交易日。
- 15:00 slot 不因交易时间边界提前停止。
- 重启后不会重复写入已存在 slot。

### Phase 4: Shadow vs Live 对比

目标：

- 后端影子数据与现有生产数据可比，且质量优于或不低于前端链路。

范围：

- 同一天同时保留前端 live 和后端 shadow。
- 对比 snapshot ids、slot 完整性、stock row count、sector row count、关键字段缺失率。
- 对比 RankTrend 读取结果的样本质量。

验收：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-audit --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
```

通过条件：

- 连续至少 2 个完整交易日 shadow 无缺槽、无空帧、无 record 缺失、无计数漂移。
- 15:00 `half_hour` 和 `daily` 稳定完整。
- shadow 的关键字段缺失率有结构化报告。

已知限制（Phase 4 范围外，待 BridgeQuoteProvider 挂载后解决）：

- `depth` 字段缺失率为 100%（`ProxyQuoteProvider` 恒返回空列表）。这会导致 shadow vs live 的 depth 对比无意义，审计报告必须显式标注此口径差异。
- 题材运行时、市场情绪、涨停池等辅助数据域在后端 collector 中无对应 provider，shadow 快照在这些维度上弱于前端 live 快照。这些缺口不影响 Phase 4 的槽位完整性验收，但在讨论 live cutover 之前必须补齐。

### Phase 5: Dragon Board 前端生产职责退役

目标：

- Dragon Board 前端不再自动生产正式快照。

范围：

- 增加前端配置开关，默认关闭 `snapshot.sweep` 的正式写库行为。
- `snapshotFacade.save*` 保留手动诊断能力，但不作为生产调度入口。
- 前端读取继续走 QuantBoard API。
- 可新增后端 collector 状态展示，但不在本阶段做复杂 UI。

验收：

```powershell
pnpm test -- --run src/services/snapshot/__tests__/runtime.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

通过条件：

- 前端默认不会启动正式快照自动写库。
- 手动保存入口仍有明确诊断用途。
- 正式读取合同不变。

### Phase 6: 正式切换

目标：

- 后端 collector 写入 `dragonboard_live`，前端正式定时写库关闭。

前置门槛：

- shadow 连续通过审计。
- MongoDB 全量备份完成并验证。
- `snapshot_collector/status` 可查询运行状态。
- `snapshot_collector/runs` 可追溯最近运行。
- `verify-mongodb-migration` 对 `dragonboard_live` 和 shadow 均通过。

切换步骤：

1. 停止前端正式快照自动写入。
2. 执行 MongoDB 全量备份。
3. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_DATASET_ID=dragonboard_live`。
4. 设置 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED=1`。
5. 重启 QuantBoard 后端。
6. 当天收盘后执行审计。
7. 连续观察至少一个完整交易日。

验收：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type quarter_hour
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-status
```

通过条件：

- 不打开 Dragon Board 页面，正式 `dragonboard_live` 仍按时出现所有目标 slot。
- `half_hour:15:00` 和 `daily:15:00` 成套完整。
- MongoDB 审计无缺槽、空帧、record 缺失、计数漂移。

### Phase 7: proxy-server 迁移或收编

目标：

- 完成前后端彻底分离的长期架构，不让 Dragon Board 前端附属代理承担正式数据源职责。

可选终态：

1. 把 `proxy-server` 正式数据源逻辑迁入 QuantBoard 后端，`proxy-server` 退役。
2. 把 `proxy-server` 改名和重定位为独立 Market Data Service，由 QuantBoard 后端调用，Dragon Board 前端不直接依赖。

推荐路径：

- 先迁移热榜、市场概览、情绪、涨停池这些正式快照必需接口。
- 保留本地开发代理一段时间，避免一次性影响 UI 调试。
- 最终 Dragon Board 前端所有正式数据都来自 QuantBoard API 或明确的只读展示 API。

验收：

- Dragon Board 前端启动不再要求 `proxy-server` 作为正式数据写入前置条件。
- QuantBoard 后端有独立 provider 测试。
- 快照 collector 不依赖前端 Vite 代理。

## 生产安全策略

### 影子数据集

所有新 collector 初期默认写：

```text
dragonboard_backend_shadow
```

不允许默认写：

```text
dragonboard_live
```

只有满足正式切换门槛后，才允许把环境变量切到 `dragonboard_live`。

### 幂等和并发

- 正式快照唯一业务键仍是 `datasetId + snapshotId`。
- run-once 和 scheduler 都必须先检查目标 snapshot 是否存在。
- MongoRepository 保持已有 dedupe 语义。
- 同一个 slot 在同一进程内必须有锁，避免 scheduler 和手动 run-once 并发。

### 失败处理

- Provider 失败不直接写空快照。
- 质量门禁阻断时写 collector run 记录，但不写 snapshot facts。
- MongoDB 写入失败时保留错误和 idempotency key。
- bridge 离线、proxy 离线、MongoDB 离线都必须返回结构化状态。

### 回滚边界

shadow 阶段：

- 直接关闭 `QUANT_BOARD_SNAPSHOT_COLLECTOR_ENABLED`。
- 删除 shadow dataset 可通过现有清理工具单独执行，不能影响 `dragonboard_live`。

正式阶段：

- 如果后端 collector 切入 `dragonboard_live` 后出现问题，优先 fix-forward。
- 若当天尚未产生正式后端快照，可以关闭 collector 并临时恢复前端 fallback。
- 若已经产生正式后端快照，不允许静默切回前端链路；必须先审计新增 snapshot ids，并记录修复或保留策略。

## 测试策略

### 单元测试

新增 pytest 覆盖：

- slot 生成和交易时间判断。
- close slot grace window。
- provider 部分失败。
- quality gate 阻断空热榜。
- builder 输出 records、frames、stock rows、sector rows。
- dedupe 行为。
- run state 写入。

### 集成测试

新增后端集成测试：

- fake provider 构造完整 `MarketDataContext`。
- run-once dry-run 不写 MongoDB。
- run-once apply 写 shadow dataset。
- 重复 apply 返回 deduped。
- audit 能发现缺槽和空帧。

### 真实环境验收

在隔离 worktree 中手动执行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00 --dry-run
.\.venv\Scripts\python.exe -m backend.cli snapshot-collector-run-once --dataset-id dragonboard_backend_shadow --snapshot-type half_hour --trading-date 2026-06-11 --slot-time 15:00
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_backend_shadow --snapshot-type half_hour
```

实际执行时把 `2026-06-11` 替换为当天交易日，命令结构保持不变。

正式切换前执行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id 20260611T093132Z
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type quarter_hour
```

实际执行时使用 `backup-mongodb --full` 返回的新 `backupId`，这里的 `20260611T093132Z` 只表示命令格式。

## 文档更新要求

实现阶段必须同步更新：

- `quant-board/docs/architecture.md`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/mongodb-migration-plan.md`
- `quant-board/docs/AI_COLLABORATION.md`
- `quant-board/docs/user-manual.md` 只在用户可见操作流程发生变化时更新；Phase 1 shadow-only 不默认改用户手册。

文档必须明确：

- 正式快照生产者从 Dragon Board 浏览器迁到 QuantBoard 后端。
- Dragon Board 前端不再承担正式定时写库。
- `proxy-server` 的过渡状态和长期归宿。
- 后端 collector 的环境变量、API、CLI、审计方式。
- 生产切换和回滚边界。

## 合并策略

实现不直接在主工作区进行。推荐流程：

1. 创建隔离 worktree。
2. 在 worktree 内按 phase 实施。
3. 每个 phase 至少有一组自动化验证和一份审计结果。
4. shadow 数据连续通过后再进入正式切换 phase。
5. 正式切换通过后做 code review。
6. 确认主工作区当前未提交改动边界后，再合并。

## 最终完成定义

本项目只有在以下条件全部满足时，才算“完全达成目标”：

- QuantBoard 后端默认负责正式快照采集和入库。
- Dragon Board 前端默认不再启动正式快照自动写库。
- 不打开 Dragon Board 页面，`dragonboard_live` 仍能稳定生成正式快照。
- `half_hour:15:00`、`daily:15:00` 成套存在且股票行完整。
- `verify-mongodb-migration` 对 `half_hour` 和 `quarter_hour` 通过。
- 后端 collector 有状态 API、运行日志和审计 CLI。
- 生产切换前后都有 MongoDB 备份和恢复边界。
- 文档明确当前生产链路，不再把浏览器运行态描述为正式快照主链。
