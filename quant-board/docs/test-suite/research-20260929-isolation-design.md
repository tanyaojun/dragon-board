# 生产/测试环境完全隔离 + sqlite 退役 — 代码级调研与分阶段设计方案

> 2026-09-29 只读调研。调研范围：quant-board 全部 backend/scripts/tests 配置面、数据层、入口写库点、备份链、测试隔离件。
> 目标状态（用户已裁决）：
> 1. 回测 = 生产链路，数据入生产 MongoDB `dragon_board_quant`（mongodb://127.0.0.1:27017，本机无认证）；
> 2. pytest 数据只能进测试库 `dragon_board_test`，绝不触碰生产库与生产 Redis；
> 3. sqlite 存储链退役：不再是任何生产路径的默认/可用链路（分阶段）;
> 4. Redis：生产前缀 `hellobiga:dragon-board:*`，pytest 强制前缀 `hellobiga:dragon-board:pytest`。

---

## 一、现状地图

### 1.1 配置面

代码默认值（`backend/core/settings.py`）：

| 配置 | 默认值 | 位置 |
| --- | --- | --- |
| `storage_backend` | **`"sqlite"`**（仅允许 `{"sqlite","mongodb"}`） | settings.py:121, :354-356 |
| `mongodb_database` | `dragon_board_quant` | settings.py:107 |
| `mongodb_uri` | `""`（空则 get_mongodb_database 抛 RuntimeError） | settings.py:106 |
| `redis_key_prefix` | `hellobiga:dragon-board:local` | settings.py:123 |
| snapshot/research/theme 三个 database_url | 兜底 `sqlite:///{warehouse}/quant_board_snapshots.db`、`quant_board_research.db`、`themeDATA.db` | settings.py:204-219 |
| `backup_mirror_enabled` | 缺省=bool(supabase_url+secret)，受 `QUANT_BOARD_ENABLE_SUPABASE_BACKUP` 覆盖 | settings.py:223-226 |
| `mongodb_tools_bin` | `D:\APP_SOFT\MongoDB\tools\bin`（mongodump/restore） | settings.py:120 |

`.env.local`（quant-board/.env.local，生产实际生效；敏感键已屏蔽）：

- `QUANT_BOARD_STORAGE_BACKEND=mongodb`、`QUANT_BOARD_MONGODB_URI=mongodb://127.0.0.1:27017`、`QUANT_BOARD_MONGODB_DATABASE=dragon_board_quant`
- 采集：`SNAPSHOT_COLLECTOR_ENABLED=1`、`DATASET_ID=dragonboard_live`、`ALLOW_LIVE_DATASET=1`、types=五类
- Redis：`QUANT_BOARD_REDIS_URL=redis://127.0.0.1:6379/0`、`QUANT_BOARD_REDIS_KEY_PREFIX=hellobiga:dragon-board:local`、`SNAPSHOT_CACHE_ENABLED=true`
- Supabase：URL/KEY 已配置但 `QUANT_BOARD_ENABLE_SUPABASE_BACKUP=false`、`AUTO_SYNC_ENABLED=false`、`SUPABASE_RETENTION_ENABLED=false`（即 Supabase 备份链生产也关闭）
- R2 对象备份：`OBJECT_BACKUP_ENABLED=true`（bucket `quant-board-archive`）+ `MONGODB_OBJECT_BACKUP_ENABLED=true`、`MONGODB_REMOTE_BACKUP_KEEP=13`、`MONGODB_BACKUP_RETENTION_DAYS=7`
- 注意：settings._load_env_file 只在环境变量缺失时补值（settings.py:24），因此 conftest 先写死 os.environ 即可压过 .env.local——这是现有隔离的机制基础。

### 1.2 数据层

- `backend/data/models/database.py:24-34`：**模块导入即创建** sqlite `engine`/`research_engine`（URL 来自 settings；sqlite engine 惰性连接，连接才落文件）。`init_db()`（:40-64）在 mongodb 模式直接早退；`get_db()`（:143-154）在 mongodb 模式 yield None。
- `backend/data/models/theme_database.py:20-24`：同构的 `theme_engine`（themeDATA.db）。
- `backend/data/repositories/repository_factory.py:16-36`：`create_repository` 按 storage_backend 分发；mongodb 走 `MongoResearchRepository(get_runtime_mongodb_database())`；`get_runtime_mongodb_database` 是唯一运行时 Mongo 连接入口（单例缓存）。
- `backend/data/migrations/mongodb_migration.py:851-884`：`get_mongodb_database()` 内置 pytest 硬护栏——`PYTEST_CURRENT_TEST` 存在时禁连 `dragon_board_quant`、只允许 `dragon_board_test`。**该护栏是全项目 Mongo 连接唯一真理源，但只覆盖经过它的连接（见缺口 1）。**
- sqlite 仓库链（待退役面）：`repository.py`(40 行, mixin 聚合+backup client) + `snapshot_repository.py`(1609) + `backtest_repository.py`(703) + `outbox_repository.py`(223) + `shared.py`(60) + `theme_repository.py`(163)；归档 `archive/service.py`(1119) 与备份链 `backup_sync.py`(290)/`backup_retention.py`(189)/`auto_sync.py`(72)/`supabase_homomorphic.py`(1281)/`supabase_backup.py`(10)；legacy 迁移 `migration.py`(374)/`legacy_split_migration.py`(285)/`theme_migration.py`(213)。
- **关键耦合**：`models.py`(652 行) 的 ORM 领域类被 mongo 仓库复用（`mongo_research_repository.py:8`、`mongo_repository.py:10`、`backtest_service.py:21-23` 直接构造 `BacktestRun/Dataset/OptimizationRun` 并 import `SessionLocal`）——models.py 不能随 sqlite 一刀切删除，需先与 `Base`/engine 解绑。

### 1.3 入口与写库点

| 入口 | 文件 | 写库路径 |
| --- | --- | --- |
| 8000 Quant API | `backend/main.py` | `POST /api/snapshots/ingest`(:681) → `create_repository(db).save_snapshot_ingest`；backtest/optimize/golden/journal/datasets 各路由均经 `create_repository`；模块导入时注册 after-save 钩子(:108-115)。startup(:212-397)：**无条件做 Redis TTL prune**(:218-241)；仅非 mongo 模式启动 auto_sync/archive/backup_retention runners(:242-247)；mongo 模式启动 KPL 缓存、L2 资金冷启动恢复、量比/frame_bundles/analyze 预热(:258-389)。sqlite 归档/备份 API 已全部 410(:578-678, :1416-1542) |
| 8001 collector | `backend/collector_main.py` | lifespan 抢 Redis 实例锁(:248-262，key `snapshot-collector:instance-lock:{dataset}` **无 hellobiga 前缀**)；写库经 `service_factory.create_snapshot_collector_repository`——**强制 mongodb，sqlite 直接 ValueError**(service_factory.py:466-484)；catchup 循环(:121-223)同样走该 factory |
| 采集调度器 | `backend/snapshot_collector/scheduler.py` | `run_info_diff_loop`(:476-500) 每日 16:30/17:00/17:30 调 `wechat_info_diff_ingest.ingest_today_if_published`（**生产自动写库，见缺口 1**） |
| CLI | `backend/cli.py`(2229 行) | mongo 命令走 `get_runtime_mongodb_database`；legacy sqlite/supabase 命令由 `reject_legacy_storage_command_in_mongodb` 统一拒绝（tests/storage/test_mongodb_runtime_switch.py:343-351 参数化覆盖 18 个命令） |
| scripts/ | 4 个研究/回填脚本 | 全部经 `get_runtime_mongodb_database`（settings 驱动）；`clone_mongo_test_db.py` mongodump 生产库→restore 测试库（双断言防误指目标库）；`scheduled_backup.py` 走 `mongodb_backup` 服务（Windows 计划任务，不在 pytest 链） |

### 1.4 备份链与 pytest 防护

- Supabase auto-sync / supabase retention / sqlite archive runners 只在 `storage_backend != "mongodb"` 时启动（main.py:242-247, :402-405）——生产（mongodb）与 pytest（conftest 强制 mongodb）均不会启动。
- `Repository(enable_backup=True)` 默认经 `get_backup_client()` → `SupabaseBackupClient.from_settings`（supabase_homomorphic.py:261-268）：`backup_mirror_enabled=False` 返回 None。pytest 由 conftest.py:20 强制 `QUANT_BOARD_ENABLE_SUPABASE_BACKUP=0` → client 为 None。**但 `from_settings` 无 `PYTEST_CURRENT_TEST` 运行时护栏**（缺口 4）。
- R2 对象备份（mongodb_backup / object_store）：不在 startup 启动，仅 after-market-once/计划任务/CLI 触发；测试用假件覆盖（tests/platform/test_operations_schedule.py:546-615 等）。
- 结论：当前 pytest 不会写 Supabase/R2，但属于"配置约定+假件"级防护，不是结构性禁用。

### 1.5 测试隔离现状

- `tests/conftest.py:14-26`：任何 backend import 前写死 `storage_backend=mongodb`、`mongodb_database=dragon_board_test`、`redis_key_prefix=hellobiga:dragon-board:pytest`、`ENABLE_SUPABASE_BACKUP=0`；同时把三个 sqlite URL 指到 `data/warehouse/test_quant_board_snapshots_v2.db` / `test_quant_board_research_v2.db` / `test_themeDATA_v8.db`（**固定文件，非 tmp_path；当前实测 446MB+183MB，跨轮持久**）。
- `tests/conftest.py:86-98`：session 级 autouse 护栏断言 `storage_backend==mongodb` 且 `mongodb_database==dragon_board_test`（不校验 redis 前缀）。
- pytest.ini：11 个领域 marker + unit/integration 自动打标；`testpaths=tests`。
- 规模：rg 实测 `def test_` 2827 个（README 基线 2940 含参数化展开），tests/storage 228 个。
- sqlite 遗留测试面：
  - 整文件 `pytestmark.skipif(mongodb)`（README 称 `sqlite_legacy` 口径）：`tests/storage/test_ingest_outbox.py`(18)、`test_archive_research.py`(6)、`test_duckdb_archive_query.py`(9)、`test_backup_retention.py`(7) = **40 用例在默认模式下跳过**；
  - `_sqlite_only` 装饰：`tests/theme/test_theme_database.py`(2 用例)、`test_theme_research.py`(1 用例)；
  - 双链条件分支（同用例内 mongodb/sqlite 两套期望）：`tests/snapshot/test_snapshot_read_api.py`（`source in {"sqlite","mongodb"}` 2 处；`totalCount` mongo=窗口 5 / sqlite=全量 8 的条件断言 :805-806；detail 投影差异 :1001-1005；attention 503 用 monkeypatch 模拟 sqlite :554-567）；`tests/snapshot/test_snapshot_ingest_outbox_dedupe.py`（2 用例 mongodb 早退+sqlite 断言 :70-125）；`tests/fixtures/helpers.py` `BacktestRepoWriter` 双链分发(:416-472)；`tests/platform/test_operations_schedule.py` 4 个显式 fake `storage_backend="sqlite"` 的旧 after-market 用例(:49,:115,:181,:245，纯假件不写真 sqlite)。
- Redis 在测试中的真实使用：`snapshot_cache.get_snapshot_redis_cache()`（snapshot_cache.py:215-229）用 settings.redis_url 建真客户端——**conftest 未改 redis_url、未关 cache**，即 pytest 与生产共用同一 Redis 实例 db0，仅靠前缀隔离。全部缓存 key 均由 `settings.redis_key_prefix` 派生（15 个文件一致，rg 验证）；实例锁 key 无前缀但测试用 FakeRedis。测试内自建 FakeCache/FakeRedis 的文件约 20+。

---

## 二、缺口清单（每条含证据）

| # | 缺口 | 证据 | 影响 |
| --- | --- | --- | --- |
| 1 | **operations 3 文件硬编码 `MongoClient("mongodb://localhost:27017")["dragon_board_quant"]`，绕过 get_mongodb_database 护栏与 settings**；其中 `wechat_info_diff_ingest.ingest_today_if_published` 在生产采集 scheduler 每日 16:30/17:00/17:30 自动写 `theme_stock_mappings.stockReason` | backend/operations/wechat_info_diff_ingest.py:78-79, :92；jev_label_driver.py:76；jev_label_driver_report.py:68；触发链 scheduler.py:476→run_info_diff_loop | pytest 若触发该函数（当前未触发，hotlist 测试只 import 纯匹配模块 wechat_info_diff.py）将直写生产库；URI/库名不受配置与护栏管理。这是隔离体系最大的结构性旁路 |
| 2 | **`storage_backend` 代码默认 `sqlite`，且三个 database_url 兜底指向 `data/warehouse/*.db`**——任何丢失/绕过 .env.local 的裸跑（新 clone、CI、错误 cwd、计划任务）会静默回退 sqlite 链并在 warehouse 建库写数 | settings.py:121, :204-219 | 与"sqlite 不再是任何生产路径默认链路"的目标直接冲突；也是 sqlite 链仍存活的根因 |
| 3 | **pytest 与生产共用同一 Redis 实例 db0，仅靠叶子前缀隔离**；conftest 未关 `SNAPSHOT_CACHE_ENABLED`、未换 redis_url/db；session 护栏不校验前缀 | conftest.py:14-26（无 redis url 项）+ snapshot_cache.py:190-229；生产 prefix=`hellobiga:dragon-board:local`，pytest=`...:pytest` | 前缀一旦误配（如测试内改 settings、或未来新代码硬编码 key）即串写生产缓存；实例锁 key `snapshot-collector:instance-lock:*` 也不在前缀体系内（collector_main.py:248 + instance_lock.py:58） |
| 4 | **Supabase/R2 备份链无 PYTEST 运行时硬护栏**：`SupabaseBackupClient.from_settings` 只看 `backup_mirror_enabled` | supabase_homomorphic.py:261-268；防护仅靠 conftest.py:20 的 env 值 | 未来某测试 monkeypatch env 或新入口直接构造 client 时可能外发网络写；属纵深防御缺失 |
| 5 | **测试 sqlite 写入固定 warehouse 文件（630MB），非 tmp_path、跨轮持久** | conftest.py:24-26；实测 `data/warehouse/test_quant_board_snapshots_v2.db`=446MB、`test_quant_board_research_v2.db`=183MB（mtime 2026-09-29） | 并行 pytest 会互踩；磁盘持续增长；退役前 sqlite 测试与 mongodb 测试共库双轨增加维护面 |
| 6 | **生产 sqlite 文件近期仍被写入过**：`data/warehouse/quant_board_snapshots.db` mtime=2026-09-28 08:47（mongodb 为主的后端下 init_db 不应触它） | ls 实测 | 说明仍有人/进程在跑 sqlite 链（疑似手动 legacy CLI 或某次 sqlite 后端运行），来源未定位——退役前必须查明 |
| 7 | 双链语义长期滞留：`totalCount` 全量计数（sqlite）vs 窗口计数（mongo）、outbox 登记、detail 投影差异等双套期望分散在用例内 | test_snapshot_read_api.py:776-806, :1001-1005；test_snapshot_ingest_outbox_dedupe.py:70-125 | sqlite 删除时这些条件分支是主要改造点；不先移植会留下死分支与误导性断言 |
| 8 | `backtest_service.py:23` 等生产代码仍 import `SessionLocal`（sqlite engine）；models.py 领域类与 SQLAlchemy `Base` 绑定且被 mongo 仓库复用 | backtest_service.py:21-23；mongo_research_repository.py:8；mongo_repository.py:10 | sqlite 退役的真正难点：需先解绑领域模型，否则删 database.py 即断 mongo 链 |

---

## 三、分阶段设计方案

### 阶段 A：生产边界加固（预估 2~3 人日）

目标：不改行为语义，把"默认/旁路/纵深防御"三处堵死。全部可独立回滚（每步一个 commit）。

- **A1 默认后端翻转 + sqlite 显式 opt-in**（0.5d）
  - `settings.py`：`storage_backend` 默认改 `"mongodb"`；新增 `QUANT_BOARD_ALLOW_SQLITE_BACKEND`（默认 false）。为 false 时若最终解析值是 `sqlite` → `get_settings()` 直接 raise（含提示语：生产禁止 sqlite 链）。sqlite URL 兜底(:204-219)仅在 ALLOW_SQLITE 时填充。
  - 影响：裸环境从"静默写 sqlite"变"启动即报错"，正是 fail-visible；生产 .env.local 已是 mongodb，行为不变。
  - 风险：本机若有依赖默认 sqlite 的一次性脚本会立刻暴露（预期收益）。回滚：`QUANT_BOARD_ALLOW_SQLITE_BACKEND=1` 或 revert。
- **A2 堵 MongoClient 直连旁路**（0.5d）
  - `wechat_info_diff_ingest.py`、`jev_label_driver.py`、`jev_label_driver_report.py` 改走 `repository_factory.get_runtime_mongodb_database()`（吃 settings 的 URI/库名，pytest 下自动受护栏）。
  - 风险：wechat 是生产采集链，改动必须在非交易日或 16:30 前部署并观察当日 16:30 槽；行为等价（同 URI 同库）。回滚：revert 单文件。
- **A3 护栏扩展**（1d）
  - `repository_factory.create_repository`：pytest 下拒绝 sqlite Repository 分支（过渡期可用 `QUANT_BOARD_TEST_ALLOW_SQLITE_CHAIN=1` 给 `_sqlite_only` 用例显式放行，阶段 B 收口后删除）。
  - `theme_database.init_theme_db`：pytest 下拒绝建库（同上 opt-in）。
  - `supabase_homomorphic.from_settings`：`PYTEST_CURRENT_TEST` 存在时恒返 None。
  - `tests/conftest.py` session 护栏追加：`redis_key_prefix` 必须以 `hellobiga:dragon-board:pytest` 开头；可同时断言 `mongodb_uri` 指向本机。
- **A4 生产入口 fail-fast**（0.25d）
  - `main.py` startup / `collector_main.lifespan`：`storage_backend != "mongodb"` 且未 ALLOW_SQLITE → 启动失败并结构化落因（复用 collector 的 `_write_startup_failure` 模式）。
- **验证门（阶段 A 整体）**：`pytest` 全量绿；裸 env 冒烟 `python -m backend.cli list-datasets`（应报错而非建 sqlite 文件）；生产冒烟 `verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour`；`rg "MongoClient\(" backend` 仅剩 mongodb_migration.py 一处。

### 阶段 B：sqlite 退役（预估 5~8 人日，四步串行）

原则：先隔离标记测试 → 移植双链语义 → 删生产代码 → 处置数据文件。每步一个 commit，可逐步 revert。

- **B1 测试隔离与夹具切换**（0.5~1d）
  - 删除 conftest.py:24-26 的三个 sqlite URL 注入；`_sqlite_only`/`sqlite_legacy` 用例（40+3 个）迁入 `tests/_legacy_sqlite/`（显式跑法：需要时设 `QUANT_BOARD_TEST_ALLOW_SQLITE_CHAIN=1` + 本地 tmp_path sqlite），或按决策点 1 直接删除。
  - 验证门：全量 pytest；`data/warehouse/test_*.db` 停止增长（随后按决策点 4 归档删除，删除遵守"一次一个明确路径"纪律）。
- **B2 双链用例移植**（2~3d）
  - `test_snapshot_read_api.py`：totalCount/detail/attention 分支固定为 mongodb 口径（窗口计数 5、detail 投影含 payload、attention 可用）；`test_snapshot_ingest_outbox_dedupe.py` 删 sqlite 断言；`helpers.BacktestRepoWriter` 删 sqlite 分支；`test_operations_schedule.py` 删 4 个 sqlite 旧链 after-market 用例（mongodb 分支已有 4 个对应用例 :297-456）。
  - 验证门：`pytest tests/snapshot tests/platform tests/backtest`。
- **B3 生产代码删除**（2~3d）
  1. `backtest_service.py` 等 `SessionLocal` import 改经 repository_factory（行为不变）。
  2. models.py 领域类与 `Base`/engine 解绑（保留类与其字段默认逻辑，mongo 仓库继续复用；SQLAlchemy 声明可保留但不绑引擎，或改 dataclass——见决策点 6）。
  3. 删 sqlite 仓库链：repository.py + snapshot_repository.py + backtest_repository.py + outbox_repository.py + shared.py（约 2635 行）+ theme_repository.py(163)。
  4. 删 `models/database.py`、`models/theme_database.py` 的 engine/SessionLocal/init_db（`get_db` 依赖改为直接 503 或删除）。
  5. 删 supabase 备份链：backup_sync/backup_retention/auto_sync/supabase_homomorphic/supabase_backup（约 1842 行）及 main.py 中对应 410 死分支；删 archive sqlite service(1119)。
  6. legacy 迁移工具（migration.py/legacy_split_migration.py/theme_migration.py）与 cli legacy 命令、`reject_legacy_storage_command_in_mongodb` 一并删除；`mongodb_migration.py` 的 sqlite 只读源处理按决策点 2 处置。
  - 风险：models.py 解绑是最敏感步（mongo 仓库构造 ORM 对象）；每删一层跑 `pytest tests/storage tests/backtest` + 生产冒烟。回滚：按步 revert。
- **B4 数据文件处置**（0.5d）
  - `data/warehouse/quant_board_snapshots.db`、`themeDATA.db`、test_*.db 先推 R2 归档（复用 object_backup 通道）再逐个删除本地文件；`data/archive/**` Parquet 同口径。先完成缺口 6 的写入来源排查再动手。
- **验证门（阶段 B 整体）**：全量 pytest；8000/8001 生产冒烟；`rg -l "sqlite" backend` 期望仅剩迁移历史文档引用（或为零，取决于决策点 2）；`verify-mongodb-migration` 通过。

### 阶段 C：文档与验收口径（预估 1 人日）

需同步修订的条目：

1. **根 AGENTS.md §4.2**：「存储主链 MongoDB 主库 + Supabase 备份库，须按 `supabase_schema.sql` 同构」已过期（生产 .env.local 已关 Supabase 备份，AI_COLLABORATION.md:18/:100-102 明确禁用）→ 改为「MongoDB 单主库（dragon_board_quant）+ R2 对象备份；回测=生产链入生产库；pytest 只入 dragon_board_test，Redis 强制 pytest 前缀」。
2. `docs/database-migration-plan.md`：顶部补「sqlite 链已退役（日期+commit）」终局说明，正文全部降级为纯历史档案。
3. `docs/test-suite/README.md`：删 `sqlite_legacy` 跳过口径节与 conftest sqlite URL 描述；补阶段 A 新护栏（redis 前缀断言、from_settings PYTEST 护栏、sqlite opt-in 开关）。
4. `docs/mongodb-migration-plan.md`：补退役实施记录；`docs/README.md` L12、`architecture.md`、`api-cli.md` 同步删除 sqlite/Supabase 运行语义。
5. `quant-board/.env.local` 无需变更（已是目标态）；可在注释中标注 ALLOW_SQLITE 开关语义。

**可检查的验收口径**（建议写入 test-suite/README）：

- 回测入生产：生产 env 下 `POST /api/backtests/rank-trend`（或 CLI run-ranktrend）产生的 run 可在 `dragon_board_quant.backtest_runs` 按 `dataset_id+config_hash+random_seed` 查到；pytest 会话内同一查询只落在 `dragon_board_test`。
- 回归隔离三断言：① conftest session fixture 断言 `mongodb/{dragon_board_test}`（已有）；② pytest 下 `get_mongodb_database` 拒绝其他库名（现有 test_mongodb_runtime_switch.py:291-317 保留）；③ session 护栏断言 redis 前缀 `hellobiga:dragon-board:pytest`（A3 新增）。
- sqlite 退役完成定义：`rg -l "sqlite" backend --type py` 为空或仅剩 mongodb_migration 只读源；`data/warehouse` 无 .db 文件；全量 pytest 不创建任何 sqlite 文件。

---

## 四、sqlite 退役涉及面汇总

- 生产代码：直接含 "sqlite" 的 backend 文件 27 个；核心删除量约 **7000+ 行**（sqlite 仓库链 ~2635、supabase 备份链 ~1842、sqlite 归档 service 1119、legacy 迁移 ~872、database.py/theme_database.py 引擎层、cli legacy 命令段）；models.py(652) 保留但需解绑。
- 测试：2827 个用例中，受影响约 **25 个文件**：整文件跳过 40 用例 + `_sqlite_only` 3 用例 + 双链条件分支文件 6 个（test_snapshot_read_api、test_snapshot_ingest_outbox_dedupe、test_backtest_core、test_backtest_dry_run、helpers.py、test_operations_schedule 4 用例）+ 零星 sqlite 注释/夹具引用（theme volume/support/gating、mongo_repository、stock_name_refresh_scheduler、collector service/scheduler）。
- scripts：无需改（已全走 settings 驱动入口）；clone_mongo_test_db.py 保留为测试库克隆工具。

## 五、需要用户拍板的决策点

1. **sqlite 遗留测试（40+3 用例）**：删除，还是移入 `tests/_legacy_sqlite/` 保留显式跑法（sqlite 语义如 totalCount 全量计数将随之消失）？
2. **settings 默认值策略**：A1 采用「默认 mongodb + `QUANT_BOARD_ALLOW_SQLITE_BACKEND` 显式 opt-in」还是「sqlite 完全非法、无开关」？以及 `mongodb_migration.py` 的 sqlite 只读迁移源处理是保留（归档工具）还是一并删除。
3. **Redis pytest 隔离级别**：维持「同实例 db0 + 前缀隔离」（现状+前缀断言），还是升级为「pytest 独立 logical db（如 /15）+ 前缀」双保险？
4. **数据文件处置授权**：data/warehouse 三个 .db（含 630MB 测试文件）与 Parquet 归档推 R2 后删除；以及 quant_board_snapshots.db 2026-09-28 写入来源的排查优先级。
5. **wechat_info_diff_ingest 改造窗口**（生产采集链）：建议非交易日合并并在下一交易日 16:30 后核对 stockReason 写入。
6. **models.py 解绑深度**：保留 SQLAlchemy 声明仅断开引擎绑定（改动小），还是改 dataclass（彻底摆脱 sqlalchemy 依赖，改动大、收益是依赖瘦身）。


---

## 附：执行修正（2026-09-29 实施后回写）

本报告两处判断在实施中被修正，以本节为准：

1. **archive/service.py 不是 sqlite 专属**：`run_mongodb_snapshot_archive_once`（生产 mongodb 快照→R2 归档链）依赖它，且其 manifest 台账也写在 sqlite（ArchiveManifestModel）。实施改为把 ArchiveService 重写为 mongodb 单链、manifest 迁移到 Mongo `archive_manifests` 集合（对齐已迁移文档的 camelCase 形状），未按本报告"删除 1119 行"执行。
2. **theme_migration.py 不是纯 sqlite**：`cmd_verify_themes` 在 mongodb 模式活跃使用 `ThemeMigrationService(None)`。实施保留该模块并删除其 sqlite 分支（原计划整文件删除）。

其余结论（缺口 1-8、阶段 A/B 框架、测试面清单）按计划执行；阶段 B 的 supabase_homomorphic/models.py 按保守裁决保留未删。
