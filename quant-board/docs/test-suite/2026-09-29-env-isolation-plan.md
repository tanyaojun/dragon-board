# 环境隔离与测试库瘦身实施计划（2026-09-29）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development（本计划即按该模式执行：每任务派新 subagent，规格评审→质量评审两道关）。
> **2026-09-29 用户补充裁决：调研已由 subagent 完成；后续计划与执行改在主线程完成（不再派执行 subagent），控制器逐任务执行并自验门禁。**
> **提交纪律：本轮所有改动不 commit**（工作区已有上一轮未提交的 tests 重构大变更集，避免混提交），每任务产出明确文件清单，由用户复核后统一提交。涉及回滚时用反向编辑，不用 `git checkout --`。

**Goal:** ①清理 pytest 对生产环境的污染残留（Redis）；②测试库 dragon_board_test 瘦身为空结构（只留集合骨架）；③生产/测试完全隔离——回测入生产库 `dragon_board_quant`，回归测试只入 `dragon_board_test`，sqlite 链退役成历史。

**Architecture:** 三份只读调研报告为事实基础（见下）。执行顺序：T1 Redis 清理（数据操作）→ T2 测试库瘦身（脚本+数据操作）→ T3 生产边界加固（代码，TDD）→ T4 sqlite 测试层退役（代码）→ T5 sqlite 生产代码删除（代码，分批+门禁）→ T6 文档同步 → T7 终验。

**调研依据（执行 subagent 必读）：**
- `quant-board/docs/test-suite/research-20260929-prod-pollution-audit.md`（R1：生产 Mongo 零污染；Redis 320 个测试键全部带 TTL；旧库已不存在）
- `quant-board/docs/test-suite/research-20260929-testdb-slim.md`（R2：测试库 12.46GB，99% 为 dragonboard_live 克隆，无用例函数级读取）
- `quant-board/docs/test-suite/research-20260929-isolation-design.md`（R3：8 条隔离缺口 + 分阶段设计）

**环境事实（所有任务通用）：**
- 仓库 `D:\dragon-board`（win32 + Git Bash）；QuantBoard venv：`D:/dragon-board/quant-board/.venv/Scripts/python.exe`；mongo 工具 `D:\APP_SOFT\MongoDB\tools\bin`。
- MongoDB `mongodb://127.0.0.1:27017`：生产 `dragon_board_quant` / 测试 `dragon_board_test`。
- Redis `redis://127.0.0.1:6379/0`：生产前缀 `hellobiga:dragon-board:local`，pytest 前缀 `hellobiga:dragon-board:pytest`。
- pytest：`cd quant-board && ./.venv/Scripts/python.exe -m pytest ...`；全量约 2940 用例，当前已知 18 个 research 锚代际失败为存量问题（读 `config/ranktrend-anchors.json` 与模块冻结常量，与库无关，**不在本计划范围**，终验时允许存在并单独列出）。
- 硬纪律（AGENTS.md）：禁止 `rm -rf`/批量删除；禁止 `git reset --hard`/`git checkout --`；Mongo 删除前必须先归档；不跑全量以外的大促不做。

**控制器裁决记录（保守默认，用户可推翻）：**

| # | 裁决 | 理由 |
| --- | --- | --- |
| D1 | ~~Supabase 备份链不删~~ → **2026-09-29 用户裁决推翻：Supabase 备份链整链删除**（supabase_homomorphic.py、supabase_backup.py、settings supabase/backup_* 字段一并移除），备份统一收敛到 R2 对象存储（archive/object_store + mongodb_backup cloudflare_r2） | 原「MongoDB 主库 + Supabase 备份库」口径已同步改为「MongoDB 单主库 + R2 对象备份」（AGENTS.md §4.2 已更新）；sqlite 时代 sync runner（backup_sync/auto_sync/backup_retention）随链一并退役 |
| D2 | models.py 保持 SQLAlchemy 声明不改动，只删 `models/database.py` 的 engine/Session/init_db | mongo 仓库复用领域类；解绑深度（改 dataclass）留给用户后续决策 |
| D3 | **（用户 2026-09-29 补充裁决）sqlite 遗留测试（40+3=43 skip 用例）直接删除**，不做隔离保留；过期方案/冗余测试代码一律清理（用户任务4） | 用户裁决「方案过期、代码冗余全部清理掉」；删除代码后这些测试失去被测对象，保留即死导入；git 历史可溯 |
| D4 | Redis 隔离维持「同实例 db0 + 前缀隔离」，本轮只加 conftest 前缀断言，不换 logical db | 换 db 号牵动 FakeRedis 生态，收益低 |
| D5 | `data/warehouse/*.db`（630MB 测试文件 + 生产 .db）本轮**只停写、不删不移** | 物理删除需用户逐个授权（AGENTS.md 一次一个明确路径）；T7 报告列出待授权清单 |
| D6 | `mongodb_migration.py` 的 sqlite 只读源处理**保留**（归档/回填工具身份），护栏现状不变 | 历史迁移工具与测试库护栏是两回事 |
| D7 | T3 完成后重启 8000/8001 验证（两者允许自行重启）；wechat 改造选在 16:30 信息差槽位前部署 | 生产采集链变更需当日可观察 |

---

## Task 1：Redis 测试残留清理（数据操作，只动 Redis）

**依据：** R1 报告 §3/§5.1。清理对象仅两类，共约 320 键（时点值，以执行时 SCAN 为准）：
1. `hellobiga:dragon-board:pytest:*`（pytest 命名空间，全部可删）；
2. `hellobiga:dragon-board:local:snapshot:generation:*` 且键名匹配测试家族正则 `^dragonboard_(projection_|sqlite_|rank_series|ranktrend_projection_|live_test|live_existing|live_summary|live_mixed|live_reason|history|analysis_attach|cache_)` 且带 `_\d{17}` 时间戳后缀。

**明确不可删（硬排除清单）：** `generation:dragonboard_live`、`generation:dragonboard_backend_shadow`、`generation:shadow`、`generation:dragonboard_live_outbox_dedupe_*`（11 键，来源不明）、一切 `index:*`、`ths-main-monitor:*`、payload/theme-fund/market:quotes 键、`snapshot-collector:instance-lock:*`。

**Files:**
- Create: `quant-board/.tmp/redis_cleanup_20260929.py`（一次性脚本，gitignore 区）
- Create: `quant-board/data/backups/redis/redis_residue_20260929.jsonl`（归档回滚件）

**Steps:**
1. 写脚本：SCAN（COUNT 1000，严禁 KEYS）收集两类候选键 → 逐键 `DUMP`+`TYPE`+`TTL` 写 JSONL（`{"key","type","ttl","payload_hex"}`）→ 打印键名清单与计数，**先归档后删除**。
2. 人工复核步骤（脚本内硬断言，不满足即中止）：每个待删键必须命中两类条件之一；待删清单与硬排除清单交集必须为空；键数 >500 时中止（说明条件失配，报告而非硬删）。
3. 分批 `UNLINK`（每批 ≤200）→ 重扫复核：两类模式残留=0；抽查 5 个生产键（`local:snapshot:index:*`、`generation:dragonboard_live`）仍存在。
4. 回滚方式记录到报告：对 JSONL 逐行 `RESTORE key ttl payload`（TTL 取 max(剩余,1)）。
5. 在 R1 报告末尾追加「清理执行记录」小节：执行时间、删除键数（分类）、归档路径、复核结果。

**验证门：** 重扫两类模式=0；生产键抽查无缺失；Mongo 生产库零改动（本任务不碰 Mongo）。

---

## Task 2：测试库瘦身 + clone 脚本种子化（脚本改造 + 数据操作）

**依据：** R2 报告（无用例函数级读取克隆数据；保留=空库+29 空集合结构）。

**Files:**
- Modify: `quant-board/scripts/clone_mongo_test_db.py`（重写为多模式）
- Create: `quant-board/data/backups/mongodb/dragon_board_test_pre_slim_20260929.archive.gz`（回滚件）

**Steps:**
1. 先做回滚件：`mongodump --uri mongodb://127.0.0.1:27017 --db dragon_board_test --gzip --archive=<上述路径>`（~1.35GB）。
2. 重写 `clone_mongo_test_db.py`（保持现有双断言：TARGET 不得为生产库名、SOURCE≠TARGET）：
   - `--mode structure`（**新默认**）：不 dump；pymongo 对 TARGET 逐集合 drop（若存在）→ 从 SOURCE `list_collection_names`+`list_indexes` 重建空集合与索引；顶部硬编码 `PROD_COLLECTIONS` 常量（29 个集合名，从 R2 报告 A.1 表抄录），在线时与 SOURCE 实际清单 diff 校验（不一致则警告并以在线为准）。
   - `--mode datasets --datasets a,b --collections c1,c2`：定向子集克隆。mongodump `--collection` 一次一个 → 按集合循环 `--query '{"datasetId":{"$in":[...]}}'`（无 datasetId 字段的集合按映射表：`datasets` 用 `id`；backtest 子表先按 runs 的 datasetId 查出 runId 集合再按 `backtestRunId` 过滤）；`--skip-dump` 在此模式下=当日同名 per-collection archive 存在则跳过 dump。
   - `--mode full`：现行为不变（全量 dump+restore，`--skip-dump` 语义不变）。
   - `--prune-residue [--keep-datasets x,y]`（默认 keep 为空）：删 TARGET 中 datasetId 不在 keep 列表的 dataset 文档、snapshot/theme/optimization 等按 datasetId 的行、backtest runs 及其按 backtestRunId 的子表行；删除前把各类计数打印成摘要（dry-run 统计默认执行，真正删除需 `--execute`）。
3. 执行 `--mode structure` → 复核：29 集合全空、索引已复制（抽查 snapshot_frames/backtest_signals 的索引名清单与生产一致）、`dbstats` dataSize<10MB、storageSize+indexSize<150MB。
4. 抽查验证（顺序执行，全绿才过门）：`pytest tests/theme/test_theme_database.py tests/storage/test_mongodb_runtime_switch.py -q` → `pytest tests/backtest -q` → `pytest tests/snapshot tests/snapshot_collector -q`。
5. 在 R2 报告末尾追加「瘦身执行记录」。

**风险与应急：** 若抽查出现「读存量数据」失败（静态扫描漏检），用 `--mode datasets` 定向重灌该 dataset（分钟级）并记录；不得回退全量克隆。drop 有短暂 IO，避开 16:30 采集槽位。

**验证门：** dbstats 达标 + 抽查全绿 + `git diff scripts/clone_mongo_test_db.py` 仅含模式改造。

---

## Task 3：生产边界加固（阶段 A，全部 TDD）

**依据：** R3 报告缺口 1/2/3/4 + R1 防复发建议。

**Files:**
- Modify: `quant-board/backend/core/settings.py:121,204-219`（默认翻转 + opt-in 开关 + URL 兜底条件化）
- Modify: `quant-board/backend/operations/wechat_info_diff_ingest.py:78-79,92`、`jev_label_driver.py:76`、`jev_label_driver_report.py:68`（直连改 factory）
- Modify: `quant-board/backend/data/repositories/repository_factory.py`（pytest 拒 sqlite 分支）
- Modify: `quant-board/backend/data/models/theme_database.py`（pytest 拒建库）
- Modify: `quant-board/backend/data/backup/supabase_homomorphic.py:261-268`（PYTEST 恒 None）
- Modify: `quant-board/backend/main.py`（startup fail-fast）、`backend/collector_main.py`（lifespan fail-fast）
- Modify: `quant-board/tests/conftest.py`（session 护栏追加 redis 前缀 + uri 断言）
- Test: `quant-board/tests/platform/test_settings_backend_guard.py`（新建）、`tests/storage/test_isolation_guards.py`（新建）

**Steps（每步先写失败测试）：**

1. **A1 settings 默认翻转 + sqlite opt-in**：
   - 测试：`test_settings_backend_guard.py` —— ①环境仅设 `QUANT_BOARD_STORAGE_BACKEND=sqlite` 时 `get_settings()` raise `RuntimeError`（消息含「生产禁止 sqlite」与开关名）；②同环境加 `QUANT_BOARD_ALLOW_SQLITE_BACKEND=1` 时通过；③默认（无任何 env）解析为 `mongodb` 不 raise；④`mongodb_database` 默认仍 `dragon_board_quant`。
   - 实现：`storage_backend` 默认改 `"mongodb"`；新增 `allow_sqlite_backend: bool = False`（env `QUANT_BOARD_ALLOW_SQLITE_BACKEND`）；`get_settings()` 组装完成后校验：`storage_backend=="sqlite" and not allow_sqlite_backend → raise`；:204-219 三个 sqlite URL 兜底改为仅当 `allow_sqlite_backend` 时填充，否则留空串。
   - 注意：测试里直接构造 `Settings(...)` 的既有用例不经 `get_settings()`，不受影响；conftest 已强制 mongodb，也不受影响。
2. **A2 堵 operations 直连旁路**：
   - 测试：`test_isolation_guards.py::test_operations_files_use_factory` —— rg 断言三个文件源码不含 `MongoClient(`；`::test_wechat_ingest_uses_runtime_db` —— monkeypatch `repository_factory.get_runtime_mongodb_database` 返回 MagicMock，调用 `wechat_info_diff_ingest` 的入库函数，断言经 factory 取库（生产语义=同 URI 同库，行为等价）。
   - 实现：三个文件 `MongoClient("mongodb://localhost:27017")["dragon_board_quant"]` → `get_runtime_mongodb_database()`（import 自 `backend.data.repositories.repository_factory`）。
3. **A3 护栏扩展**（每项一测试）：
   - `repository_factory.create_repository`：`PYTEST_CURRENT_TEST` 存在且请求 sqlite 分支 → raise（消息含「pytest 禁止 sqlite 存储链」；sqlite 遗留测试已在 T4 删除，无需放行开关）。
   - `theme_database` 建库函数：pytest 下 raise（同口径）。
   - `SupabaseBackupClient.from_settings`：`PYTEST_CURRENT_TEST` 存在 → 恒返 None。
   - conftest session 护栏追加断言：`settings.redis_key_prefix == "hellobiga:dragon-board:pytest"`、`settings.mongodb_uri` 以 `mongodb://127.0.0.1` 开头。
4. **A4 生产入口 fail-fast**：抽公共函数 `assert_production_storage_backend(settings)`（backend/core/settings.py 或 main.py 内）：`storage_backend!="mongodb" and not allow_sqlite_backend → raise`；`main.startup` 与 `collector_main.lifespan` 首行调用。测试：fake settings 两种取值断言 raise/通过。
5. **验证门（T3 整体）**：
   - `pytest tests/platform/test_settings_backend_guard.py tests/storage/test_isolation_guards.py -q` 全绿；
   - 裸 env 冒烟：`env -i PATH=$PATH ./.venv/Scripts/python.exe -m backend.cli list-datasets` 应报错退出且 `data/warehouse/` 无新 .db 文件（记录前后 mtime/文件清单）；
   - `rg "MongoClient\(" quant-board/backend` 仅剩 `mongodb_migration.py`；
   - 全量 `pytest -q`（基线 2940：通过数不降、18 锚失败维持）。
6. 重启 8000/8001（`--port 8000`/采集器 8001 各自启动命令），curl 健康口确认；记录 16:30 信息差槽位由用户观察。

**回滚：** 每步改动独立成块，可按文件反向编辑；`.env.local` 不改（已是 mongodb）。

---

## Task 4：sqlite 测试层退役 + 冗余测试代码清理（阶段 B1+B2 + 用户任务4）

**前置：** T3 全绿。目标：pytest 全量不再创建/依赖任何 sqlite 文件；双链条件断言收敛为 mongodb 单口径；过期/冗余测试代码删除。

**Files:**
- Modify: `quant-board/tests/conftest.py`（删 :24-26 三个 sqlite URL 注入）
- Delete（用户任务4，git rm 语义=删除后交用户复核）：`tests/storage/test_ingest_outbox.py`（18 用例）、`tests/storage/test_archive_research.py`（6）、`tests/storage/test_duckdb_archive_query.py`（9）、`tests/storage/test_backup_retention.py`（7）——整文件 skipif mongodb 的 sqlite 遗留链测试
- Modify: `tests/theme/test_theme_database.py`（删 2 个 `_sqlite_only` 用例与装饰器）、`tests/theme/test_theme_research.py`（删 1 个）、`tests/snapshot/test_snapshot_read_api.py`、`tests/snapshot/test_snapshot_ingest_outbox_dedupe.py`、`tests/platform/test_operations_schedule.py`、`tests/fixtures/helpers.py`

**Steps:**
1. conftest 删 sqlite URL 注入（该三行删除后，`test_quant_board_snapshots_v2.db` 等不再被触碰）。
2. 删除 4 个 sqlite_legacy 文件（43 skip 的 40 个）——被测对象（sqlite 仓库链/归档/备份 retention）将在 T5 删除，方案已过期，按用户裁决直接清理。
3. 删除 theme 三个 `_sqlite_only` 用例（43 skip 的 3 个）及 `_sqlite_only` 装饰器定义（若仅此三处使用）。
4. 双链移植（固定 mongodb 口径）：
   - `test_snapshot_read_api.py`：`source in {"sqlite","mongodb"}` → 断言 `"mongodb"`；`totalCount` 条件断言删 sqlite 分支（mongo 窗口口径为准）；detail 投影差异 :1001-1005 取 mongodb 分支；attention 503 用例改为 mongodb 语义（不再 monkeypatch 模拟 sqlite，直接断言降级行为）。
   - `test_snapshot_ingest_outbox_dedupe.py`：两个用例的 sqlite 早退分支删除，保留 mongodb 断言。
   - `test_operations_schedule.py`：4 个显式 fake `storage_backend="sqlite"` 的旧 after-market 用例删除（mongodb 对应用例已存在 :297-456）。
   - `tests/fixtures/helpers.py`：`BacktestRepoWriter` 删 sqlite 分支（仅保留 mongo 路径），`strip_dataset_id` 不动。
5. **冗余测试代码审计（用户任务4 的全面部分）**：
   - `rg -n "pytest.mark.skip|skipif|pytest.xfail" tests -g '*.py'` 列全剩余 skip/xfail，逐条定性：条件 skip 有存在理由（如 duckdb 缺失）→ 保留；方案过期 → 删除；并跑 `pytest -q -rs` 人工读 skip 清单，确认 skip 计数从 43 降到仅剩有理由项。
   - `rg -ln "sqlite" tests -g '*.py'`：T4 后残留 sqlite 引用逐条清理（注释/夹具/字符串），T5 删码后再扫一轮归零。
   - 复查上轮重构已知遗留：FakeCache/FakeRedis 失配签名（ttl_seconds）、双链注释是否还有误导性描述。
6. **验证门：** `pytest tests/snapshot tests/platform tests/backtest tests/theme tests/storage -q` 全绿 → 全量 `pytest -q`（通过数≈2879-43+条件修复项，skip 计数显著下降，18 锚失败维持）→ 跑一轮全量后核验 `data/warehouse/test_*.db` mtime 不再更新。

---

## Task 5：sqlite 生产代码删除（阶段 B3 裁剪版，分批+门禁）

**前置：** T4 全绿。**范围裁决：** 按 D1/D2/D6——删 sqlite 仓库链/归档/legacy 迁移/`models/database.py` 引擎层；**保留** models.py ORM 类、mongodb_migration.py（含 sqlite 只读源处理）、`data/warehouse/*.db` 文件本体。（supabase_homomorphic.py 原列保留件，D1 已被用户 2026-09-29 裁决推翻 → 整链删除）

**Files（删除批次）：**
- 批A（引擎层）：`backend/data/models/database.py`（engine/research_engine/SessionLocal/ResearchSessionLocal/init_db 删除；若 `get_db` 被 >15 处路由依赖则保留仅含 `get_db`（yield None，注明 mongo 单链 no-op）的最小 shim，否则连 get_db 一并删并清理路由签名）
- 批B（sqlite 仓库链）：`backend/data/repositories/repository.py`、`snapshot_repository.py`、`backtest_repository.py`、`outbox_repository.py`、`shared.py`、`theme_repository.py`；同批删 `backend/data/models/theme_database.py`
- 批C（sqlite 归档+legacy 迁移）：`backend/data/archive/service.py`、`backend/data/migrations/migration.py`、`legacy_split_migration.py`、`theme_migration.py`
- 批D（sync runner）：`backend/data/backup/backup_sync.py`、`auto_sync.py`、`backup_retention.py`（D1 已更新：sqlite 时代 runner 与 supabase_homomorphic/supabase_backup 一并删除）
- 批E（接线清理）：`backend/main.py` 非 mongo runner 启动块与 410 死分支、`backend/cli.py` legacy 命令与 `reject_legacy_storage_command_in_mongodb`、`backtest_service.py` 等处 `SessionLocal` import 改 factory、各处 `init_db()` 调用点（mongodb 模式本就 no-op）
- 批F（测试残留清理）：`rg -ln "repository import|snapshot_repository|backtest_repository|outbox_repository|theme_repository|SessionLocal|init_db|ResearchSessionLocal" tests` 逐条清理引用已删模块的测试代码（T4 已删大件，此处收尾）

**Steps（每批一道门）：**
1. 每删一批前：`rg -n "<待删符号>" quant-board/backend quant-board/scripts` 列全引用点并先改接线；删除后 `rg` 归零校验。
2. 批A 先行：`backtest_service.py:21-23` 等 `SessionLocal` 引用改 `repository_factory`；models.py 不动（其 `Base` 仍在自身模块内定义）。
3. 每批后：`pytest tests/storage tests/backtest -q` 全绿才进下一批；批E 后跑 `pytest tests/platform -q`。
4. 全部批次后：全量 `pytest -q`；`rg -l "sqlite" quant-board/backend --type py` 期望仅剩 `mongodb_migration.py`（+注释性引用，逐条列出）；裸 env 冒烟同 T3 门。
5. 生产冒烟：重启 8000，`verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour` 通过；curl 健康口。

**中止协议：** 任一批无法在批内达到门禁 → 停在该批，保留已完成批次，报告 BLOCKED 与剩余清单（允许「部分退役」交付，退路=已完成批次的隔离状态仍满足隔离目标）。

---

## Task 6：文档同步与验收口径固化

**Files:**
- Modify: `D:\dragon-board\AGENTS.md` §4.2（存储主链条目改写：MongoDB 单主库 dragon_board_quant + R2 对象备份；回测=生产链入生产库；pytest 只入 dragon_board_test + Redis pytest 前缀；sqlite 链已退役）
- Modify: `quant-board/docs/database-migration-plan.md`（顶部终局说明，正文降级为历史档案）
- Modify: `quant-board/docs/test-suite/README.md`（删 sqlite_legacy 节；补：空结构测试库、clone 三模式、新护栏清单、redis 前缀断言、ALLOW_SQLITE 开关、验收三断言）
- Modify: `quant-board/docs/README.md`、`docs/AI_COLLABORATION.md`（相应口径行）
- Modify: 根 `CLAUDE.md`（如有 storage 相关差异描述，同步）

**验收三断言（写入 README，T7 逐条执行）：**
1. 回测入生产：生产 env 下产生的 backtest run 落 `dragon_board_quant.backtest_runs`（按 dataset_id+config_hash+random_seed 可查）；pytest 会话内同查询只落 `dragon_board_test`。
2. 回归隔离：conftest 三断言（mongodb + dragon_board_test + redis pytest 前缀）；`get_mongodb_database` pytest 护栏拒绝其他库。
3. sqlite 退役：`rg -l "sqlite" backend --type py` 仅剩 mongodb_migration.py（逐条注释性引用已列）；全量 pytest 不创建任何 sqlite 文件；`data/warehouse` 无新增 .db。

---

## Task 7：终验与汇报

**Steps:**
1. 全量 `pytest -q`（预期：通过数≈2900+，skip 含 legacy 与条件 skip，18 锚失败单独列出为存量移交项）。
2. dbstats 复核：`dragon_board_test` <150MB 落盘；`dragon_board_test` 集合=29 全空；`dragon_board_quant` 与审计基线一致（11.3M objects 量级、无新增测试形状文档——重跑 R1 指纹快扫）。
3. Redis 重扫：重跑 T1 清理脚本（清掉终验全量 pytest 新产生的 pytest 前缀残留）→ 两类测试模式=0。
4. 服务健康：8000/8001 重启后健康口 OK；`verify-mongodb-migration` 通过。
5. 汇总 git 文件清单（新增/修改/删除/移动分组）交用户复核；memory 更新；最终汇报（含：污染结论、瘦身前后数字、隔离加固清单、sqlite 退役范围与保留件、待用户授权清单（warehouse .db 删除、models 解绑深度、redis logical db 升级；supabase 链去留已于 2026-09-29 用户裁决：整链删除））。
