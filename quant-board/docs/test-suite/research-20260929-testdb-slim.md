# 测试库 dragon_board_test 瘦身调研（2026-09-29）

> 只读调研。本文所有数字来自对 `mongodb://127.0.0.1:27017` 上 `dragon_board_test` / `dragon_board_quant`
> 两库的只读查询（`$collStats`、`count_documents`、聚合 `$group`，大集合仅服务端聚合 + limit 样例），
> 以及对 `quant-board/tests/**` 的 rg 静态扫描。未对任何库执行写删操作，未运行 pytest。
> 盘点脚本在 `quant-board/.tmp/testdb_inventory_1..5.py`（临时件，不入库）。

## 0. 结论速览

1. 测试库 11,331,295 docs / dataSize 12.46GB / storageSize 2.83GB / 索引 0.74GB，共 29 个集合。
2. 其中 **~99% 是 2026-09-29 08:37 从生产库全量克隆来的 `dragonboard_live` 单一 dataset 数据**（生产库本身只有这 1 个 dataset：2940 帧 + 63.9 万 stock_rows + 1003 万 backtest_signals 等）。
3. **2940 个 pytest 用例没有任何一个函数级读取这批克隆数据**。tests/ 全量静态扫描证明：真实 Mongo 依赖全部被 `FakeDb/FakeCollection/FakeRepo/monkeypatch` 拦截；真实库调用只写"时间戳后缀自播种 dataset"；`dragonboard_live` 字面量出现在 fake 查询或 parser 构造里。`tests/conftest.py` 护栏只要求"mongodb 后端 + 库名=dragon_board_test"，README 亦明示"pytest 只依赖库存在与集合结构，不要求实时同步"。
4. 因此**保留清单 = 空库 + 29 个集合的空集合结构**；删除清单 = 全部克隆数据（~11.0GB 数据 / ~2.5GB 存储 / ~0.7GB 索引）+ 可选的 pytest 跨轮残留（511 个 ds_* dataset，~0.6GB 数据 / ~0.15GB 存储）。
5. 18 个 research 锚代际失败与克隆数据无关：锚测试读 `config/ranktrend-anchors.json` + 模块内冻结常量，不读任何 dataset，瘦身既治不了也伤不了它们。

---

## A. 测试库现状盘点

### A.1 逐集合 count / storageSize（`$collStats`，2026-09-29 实测）

| 集合 | docs | storageSize | dataSize |
| --- | ---: | ---: | ---: |
| backtest_signals | 10,032,960 | 1,160.6MB | 6,687.2MB |
| snapshot_stock_rows | 650,521 | 703.4MB | 2,021.5MB |
| snapshot_analysis | 282,462 | 500.9MB | 1,994.5MB |
| snapshot_records | 9,585 | 207.6MB | 747.2MB |
| snapshot_sector_rows | 225,051 | 47.6MB | 253.5MB |
| backtest_runs | 629 | 42.0MB | 41.3MB |
| hotlist_sentiment | 1,258 | 12.8MB | 35.5MB |
| snapshot_frames | 9,585 | 8.8MB | 26.7MB |
| fund_flow_l2 | 12,196 | 3.3MB | 14.7MB |
| backtest_equity_curve | 55,845 | 2.5MB | 13.5MB |
| theme_daily_factors | 21,514 | 2.2MB | 11.7MB |
| themes | 245 | 1.8MB | 3.5MB |
| trade_journal | 761 | 1.6MB | 5.5MB |
| theme_stock_mappings | 13,307 | 1.4MB | 3.4MB |
| snapshot_collector_runs | 1,789 | 1.3MB | 7.6MB |
| backtest_trades | 3,889 | 1.3MB | 5.4MB |
| optimization_runs | 126 | 0.8MB | 4.2MB |
| theme_metadata | 14 | 0.4MB | 0.6MB |
| datasets | 512 | 0.3MB | 1.1MB |
| migration_audit | 2,569 | 0.3MB | 0.9MB |
| stock_names | 6,042 | 0.3MB | 1.3MB |
| backtest_quality_reports | 430 | 0.1MB | 0.2MB |
| golden_ranktrend_cases | 2 | 0.1MB | 0.2MB |
| archive_manifests | 3 | <0.1MB | <0.1MB |
| theme_factor_frames / theme_quality_reports / theme_signals / theme_stock_exposures / backtest_result_chunks | 0 | 0 | 0 |
| **合计** | **11,331,295** | **2,701.5MB** | **11,881.0MB** |

`dbstats`：objects≈11.33M，dataSize 12.46GB，storageSize 2.83GB，indexSize 737.7MB，磁盘 271.8/349.6GB 已用。
注：任务提到的 `sync_outbox` 在测试库不存在——mongodb 模式不登记 sqlite sync_outbox（见 `test_snapshot_ingest_outbox_dedupe.py` 注释），属预期。

### A.2 按 datasetId 的体积排行（估算 = 组内条数 × 集合均值文档大小）

| dataset | 构成 | 估算 dataSize | 性质 |
| --- | --- | ---: | --- |
| `dragonboard_live`（生产唯一 dataset） | 2,940 frames + 2,940 records + 639,539 stock_rows + 223,008 sector_rows + 282,171 analysis + 185~186 backtest_runs（1003 万 signals、3651 trades、50,759 curves、76 quality reports）+ hotlist_sentiment 1,258 + theme_daily_factors 21,514 + fund_flow_l2 12,196 + trade_journal 761 + snapshot_collector_runs 1,789 + themes 245 + mappings 13,307 + stock_names 6,042 等 | **≈ 11.25GB** | 克隆产物 |
| pytest 残留（511 个 `ds_*` / `dragonboard_live_*_时间戳` dataset） | 6,645 frames(18.5MB) + 6,645 records(518MB) + 10,982 stock_rows(34MB) + 2,043 sector_rows(2.3MB) + 291 analysis(2.1MB) + 443 runs(29MB) + 2,120 signals(1.4MB) + 238 trades(0.3MB) + 5,086 curves(1.2MB) + 354 quality reports(0.2MB) + 94 optimization_runs(3.1MB) + 1 golden case + ~89 migration_audit | **≈ 0.61GB** | pytest 跨轮脏数据 |

时间覆盖：`dragonboard_live` half_hour 1,051 帧（2026-04-15 ~ 09-28），完整覆盖研究窗口 decision(04-15~07-31)/FINAL(08-01~08-14, 100 帧)/oos1(08-15~08-31)/oos2、oos2u(09-01~09-28)；quarter_hour 1,418 帧（03-27 起）、hourly 313、daily 108、five_minutes 50。

---

## B. 测试真实依赖分析

### B.1 扫描口径

- `requires_mongodb` 标记：仅 1 处（`tests/snapshot/test_snapshot_read_api.py`，实际是"sqlite 模拟下拒绝"的 503 合同，不读数据）。
- 直接调用 `get_runtime_mongodb_database()`（非 monkeypatch 字符串）的测试文件共 8 个，逐一核验：
  - `tests/backtest/test_backtest_core.py`：真实库，但 `load_frames(dataset["id"])` 读的是**本用例经 `/api/datasets/import` 自导入的 35 帧 dataset**；
  - `tests/snapshot/test_snapshot_ingest_outbox_dedupe.py`：自播种 `dragonboard_live_outbox_dedupe_<时间戳>`；
  - `tests/theme/test_theme_database.py`：`@_sqlite_only` 跳过 mongodb 模式；autouse fixture 反向清理与克隆主题重名的 AI/POWER（共容而非依赖）；
  - `tests/theme/test_theme_research.py`：`ds_test/ds_v12/ds_compress` 自播种 + autouse 清理；
  - `tests/storage/test_mongodb_snapshot_archive.py`：`FakeMongoDb` 覆盖工厂；
  - `tests/storage/test_mongodb_runtime_switch.py`：护栏合同（连生产库名必须 raise），不需要数据；
  - `tests/fixtures/helpers.py::BacktestRepoWriter`：只写自己 runId 的回测子表；
  - `tests/platform/test_operations_schedule.py`：monkeypatch 工厂。
- `dragonboard_live` 字面量出现于 61 个测试文件、~470 处：全部是 FakeCollection 种子行、monkeypatch 返回值或 `build_parser` 参数构造（`tests/platform/test_cli.py` 只 parse 不执行）。`GET /api/datasets` 的断言全是 `any(item["id"] == 自己导入的 id ...)`，不要求列表非空。
- research harness（`tests/research/*_harness`）：`load_frames`/`evaluate_*.load_frames` 一律 monkeypatch 成已知答案帧；`baseline_anchor()` 只读 `config/ranktrend-anchors.json`；无 DB 读取。

### B.2 "读存量数据"用例 → dataset → 集合 映射

**结论：空集。** 静态扫描未发现任何用例在未播种的情况下读取克隆来的生产数据。
与克隆库相关的仅有两类"接触"：
1. `tests/theme/test_theme_database.py::_clean_test_themes_mongo_rows`：删除克隆库中与测试固定主题同名的 AI/POWER（幂等导入计数断言的前置清理，mongodb 模式下该断言用例本身被 `@_sqlite_only` 跳过）；
2. 大量用例向测试库**写入**时间戳后缀 dataset（`dragonboard_live_test_*`、`dragonboard_live_outbox_dedupe_*`、`ds_*` 等）——这是 0.61GB 残留的来源，写入路径不依赖库中已有数据（Mongo 集合自动创建）。

### B.3 18 个 research 锚代际失败的澄清

失败用例（如 `test_cs_strengths_harness::test_baseline_anchor_constant`、`test_jump_confirm_parameters_harness::test_baseline_anchor_constant`、`test_vp_signal_parameters_harness::test_anchor_constant`、`test_track1_dimension_power::test_anchor_constants_generation` 等）断言的是：
`baseline_anchor()` 从 `config/ranktrend-anchors.json` 读到的 currentGeneration（`gen-2026-10-b202610`，decision 0.1323/oos1 0.0862/oos2 0.0998/oos2u 0.0812）与各 harness 模块内仍冻结的 fund10 代际常量（`ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}`）一致。
**它们不读任何 dataset/集合**，README"待用户随 10/3 复跑裁决"的口径不变；与本次瘦身正交。

### B.4 snapshot 大集合按 datasetId 逐个判定

| dataset | frames | records | stock_rows | sector_rows | analysis | 判定 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `dragonboard_live` | 2,940 | 2,940 | 639,539 | 223,008 | 282,171 | **完全无人引用**（无用例函数级读取）→ 可删 |
| 511 个 `ds_*`（随机 hex，各 35 帧） | 6,4xx | 6,4xx | ~10,000 | ~1,900 | ~120 | **仅测试自己写入的临时数据**（自播种+时间戳后缀，跨轮不依赖）→ 可删 |
| `dragonboard_live_*_<时间戳>` 等 | 少量 | 少量 | ~1,000 | ~140 | ~170 | 同上 → 可删 |

backtest 子表按 run→dataset 折算：`dragonboard_live` 名下 185 runs / 10,030,840 signals / 3,651 trades / 50,759 curves / 76 quality reports **全部可删**；443 个 pytest run 及其子数据亦可删（对应测试每轮自建自读）。

### B.5 反向结论：无任何测试读取的集合/数据

全部克隆内容（`dragonboard_live` 全量）+ 全部 pytest 残留都没有测试函数级读取。
集合结构本身（集合存在、字段形状）也不是断言对象：真实库写入均走 Mongo 自动建集合。
即：**测试库可以瘦身为"空库 + 29 个空集合"**（保守起见保留空集合结构，防未来新增集成用例隐式依赖 `list_collection_names` 形状）。

---

## 保留清单 vs 删除清单

### 保留（体积≈0）

| 条目 | 体积 | 依据 |
| --- | --- | --- |
| `dragon_board_test` 库本体 + 29 个空集合结构（含 `theme_factor_frames` 等 5 个现成空集合） | ~0 | conftest 护栏要求库名存在；README"只依赖库存在与集合结构"；避免任何隐式 listCollections 依赖 |

### 删除清单（判定依据均为 B 节"无测试函数级读取"）

| 条目 | docs | dataSize | storageSize（压缩后） | 依据 |
| --- | ---: | ---: | ---: | --- |
| `dragonboard_live` 全部克隆数据（覆盖 24 个非空集合中除 `datasets` 残留外的全部文档：snapshot 四表+analysis、backtest 五表、optimization_runs、hotlist_sentiment、theme_* 、stock_names、fund_flow_l2、trade_journal、snapshot_collector_runs、archive_manifests、migration_audit、golden_ranktrend_cases 1 条克隆 case、datasets 1 条 doc） | ≈11.30M | ≈11.25GB | ≈2.55GB | 无用例读取；研究复算走生产库 |
| pytest 跨轮残留：511 个 `ds_*`/时间戳 dataset 及其 frames/records/stock_rows/sector_rows/analysis + 443 个 run 及子表 + 94 optimization_runs + 1 golden case + ~89 migration_audit | ≈29,000 | ≈0.61GB | ≈0.15GB | 自播种+时间戳后缀，跨轮零依赖 |
| 合计 | ≈11.33M | ≈11.86GB | ≈2.70GB | 另释放索引 ≈0.74GB |

### 预期瘦身效果

- dataSize 12.46GB → **< 10MB**（若只删克隆、留残留：→ ~0.6GB）。
- storageSize 2.83GB + 索引 0.74GB → compact/drop 重建后 **< 100MB**（ WiredTiger 不会因 delete_many 自动还盘；`--drop` 重建集合才即时回收）。
- 与之配套：`data/backups/mongodb/dragon_board_quant_to_dragon_board_test_20260929.archive.gz`（1.34GB）在确认不再需要按日重放后可归档清理（属用户决策，不计入本次）。

### 执行步骤提案（先归档后删；执行人=用户，本调研不执行任何写操作）

1. **归档回滚件**（只读 dump，~1.35GB，数分钟内）：
   `D:\APP_SOFT\MongoDB\tools\bin\mongodump.exe --uri mongodb://127.0.0.1:27017 --db dragon_board_test --gzip --archive=D:\dragon-board\quant-board\data\backups\mongodb\dragon_board_test_pre_slim_20260929.archive.gz`
2. **瘦身重建**：运行改造后的 `clone_mongo_test_db.py --mode structure`（见 C 节；drop 每个集合并按生产库 `list_indexes` 重建空集合，原子完成，避免 conftest 护栏空窗）。
3. **抽查验证**：`.\.venv\Scripts\python.exe -m pytest tests/theme/test_theme_database.py tests/storage/test_mongodb_runtime_switch.py -q` → 再抽 `tests/backtest -m integration`、`tests/snapshot_collector -m integration` → 最后排一轮全量。
4. **磁盘回收确认**：`dbstats` 复核 storageSize/indexSize 已回落。

### 风险

1. **未来新增"读存量"集成用例**会被空库打破——C 节的 `--mode datasets` 可按需半量重灌（分钟级），建议新用例一律自播种。
2. 若团队有"在测试库手工复算研究读数"的隐藏习惯，克隆删除后会失去该便利（生产库不受影响；可用 `--mode datasets --datasets dragonboard_live --collections snapshot_frames,snapshot_stock_rows` 定向重灌）。
3. `hotlist_sentiment` 存在测试 upsert 覆盖克隆行（同 `_id`=`dataset:type:date` 键空间）——删除克隆行同时清除了这类污染，属收益非风险。
4. drop/compact 有短暂 IO 压力，避开生产快照采集时段（8001 采集器写生产库，与本库无关，但同实例）。
5. 回滚：用第 1 步 archive `mongorestore --nsFrom=dragon_board_test.* --nsTo=dragon_board_test.* --drop` 一键还原。

---

## C. 克隆策略演进提案（`scripts/clone_mongo_test_db.py`）

现状：全量 `mongodump --archive --gzip`（1.34GB）+ `mongorestore --nsFrom/--nsTo --drop`；`--skip-dump` 复用当日 archive 重放。问题：全量克隆是测试不需要的 11.86GB，且每次重放把测试库拉回满体积。

提案（保持"生产库绝不成为恢复目标"的双断言与 pytest 护栏不变）：

```
--mode structure   （新默认）不 dump。pymongo 对 TARGET_DB 逐个 create_collection(29 集合)，
                   并从 SOURCE_DB listIndexes/listCollections 复制索引定义；幂等，先 drop 再建。
                   --skip-dump 对本模式无意义（无 archive），忽略并提示。
--mode datasets    定向子集克隆：--datasets dragonboard_live --collections snapshot_frames,snapshot_stock_rows,...
                   mongodump 的 --collection 一次只能一个 → 按集合循环：
                   mongodump --db SRC --collection C --query '{"datasetId":{"$in":[...]}}'
                             --gzip --archive=<dir>/SRC_to_TARGET_<C>_<YYYYMMDD>.archive.gz
                   再逐文件 mongorestore --nsFrom/--nsTo --drop。
                   无 datasetId 字段的集合（datasets/backtest_runs 用 id/datasetId，hotlist_sentiment 用 datasetId）
                   查询键按集合映射表配置；backtest 子表按 backtestRunId 关联 runs 过滤。
--mode full        现行为（全量 dump+restore），保留用于归档/回滚件。
--skip-dump        仅 full 模式有意义，语义不变（复用当日 archive 只重放）；
                   datasets 模式的对应语义 = 当日同名 per-collection archive 存在则跳过 dump 只 restore。
--prune-residue    附加子命令：删除 TARGET 库中不在 --keep-datasets（默认仅 dragonboard_live 或空）的
                   dataset 及其 frames/records/stock_rows/sector_rows/analysis 与 run 子数据，
                   作为瘦身后日常卫生（pytest 残留会随轮次重新积累）。
```

要点：
- `--mode structure` 让"瘦身后重建测试库"的体积恒为 ~0，`--mode datasets` 提供可累积的中间档；full 只服务归档。
- 集合清单来源建议硬编码常量 `PROD_COLLECTIONS`（29 个，含 5 个长期空集合），避免依赖生产库在线。
- 保留 `assert TARGET_DB != SOURCE_DB`、`assert TARGET_DB != "dragon_board_quant"` 与既有日志风格；README 的克隆章节同步改写。

---

## 不确定项

1. **动态/间接读取**：静态扫描覆盖 import 与字符串字面量；若存在经环境变量拼接集合名或在 fixture 里按库名遍历的极端写法，理论上有漏检（未见迹象：tests/ 无 `MongoClient` 直连、无 `list_collection_names` 断言）。
2. **用户隐性用途**：是否有流程（CI、手工诊断脚本、AI 协作习惯）在 pytest 之外读测试库克隆数据，需用户确认。
3. **残留清理口径**：`--prune-residue` 是否进 pytest 链（不推荐，pytest 不应删库）或仅手动，属用户决策。
4. compact 后 storageSize 的实际回落幅度依赖 WiredTiger 版本行为，报告值为估算。

## D. 瘦身执行记录（2026-09-29，主线程执行）

- **回滚件**：`data/backups/mongodb/dragon_board_test_pre_slim_20260929.archive.gz`（1.3GB，瘦身穿棱前全量 dump，exit 0）。
- **用户中途纠偏（重要）**：初次执行为全空结构，用户指出 `stock_names`/`theme_stock_mappings` 等基础参照数据必须保留——修正为「空结构 + 基础参照集合播种」。最终保留集合：`stock_names`(6,042)、`themes`(245)、`theme_stock_mappings`(13,307)、`theme_metadata`(14)、`golden_ranktrend_cases`(2)，合计 19,610 docs / 9.4MB。
- **克隆脚本升级**（`scripts/clone_mongo_test_db.py`）：`--mode structure`（新默认，drop 全部→重建空集合+索引→播种 REFERENCE_COLLECTIONS）；`--mode datasets`（定向子集）；`--mode full`（原全量行为）；`--prune-residue`（残留卫生，dry-run 默认）。
- **实测事故与修复**：对 archive 做定向恢复时误用 `--nsFrom/--nsTo`（该参数只改名不过滤），mongorestore 把整卷归档灌回测试库；已用 `--nsInclude` 修正脚本并重跑 structure 清除。**教训：archive 定向恢复必须 `--nsInclude`。**
- **验证**：`dbstats` objects 11,331,295→19,610，dataSize 12.46GB→9.4MB，storage+index 2.83+0.74GB→0.5MB（WiredTiger 磁盘回收需 compact，本机磁盘充足暂不做）；索引定义与生产逐一抽查一致；抽查 theme/storage 40 绿、backtest 124 绿、snapshot+collector 635 绿；**全量 pytest 2880 passed / 43 skipped / 17 failed（全部为 research 锚漂移存量，较瘦身前基线 2879/18 无新增失败）**。
