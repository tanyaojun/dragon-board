# 2026-09-29 pytest 全量套件对生产数据环境污染审计报告

> 只读审计。全程未对 MongoDB / Redis 执行任何 delete/update/insert/drop/flush/config 改动，未运行 pytest，未修改任何 git 跟踪文件。临时脚本位于 `quant-board/.tmp/`（mongo_inventory.py、prod_fingerprint_scan.py、redis_scan.py，均已 gitignore）。

## 0. 一句话结论

**生产 MongoDB 库 `dragon_board_quant` 未检出任何 pytest 污染（0 文档）；Redis 残留约 320 个测试缓存键（全部带 TTL，最晚 2026-10-06 前自净）；旧库 `dragon_board_quant_pytest` 已不存在（无可清理对象）。**

## 1. 审计方法

### 1.1 事实链（代码侧）

| 事实 | 来源 |
| --- | --- |
| 护栏前 conftest（HEAD 版）强制 `QUANT_BOARD_STORAGE_BACKEND=sqlite`、`QUANT_BOARD_MONGODB_DATABASE=dragon_board_quant_pytest`、未设置 Redis 前缀 | `git show HEAD:quant-board/tests/conftest.py` |
| 生产 `.env.local`：`storage_backend=mongodb`、`mongodb_database=dragon_board_quant`、`redis_key_prefix=hellobiga:dragon-board:local` | `quant-board/.env.local` |
| 生产 id 生成格式 `{prefix}_{uuid4.hex[:16]}`（bt_/opt_/ds_/tj_ 同规则） | `backend/core/utils.new_id`、`backtest_service.py:757,909,1087`、`optimization_service.py:162,388` |
| factory 层 pytest 护栏（拒绝 `dragon_board_quant`）在 HEAD 已提交；conftest 环境强制与 `get_mongodb_database` 层护栏为 09-29 未提交改动 | `repository_factory.py`（HEAD）、工作区 `tests/conftest.py`、`mongodb_migration.py:851-870` |
| 测试动态 dataset 名家族 `f"dragonboard_{family}_{ts}"` | `tests/snapshot/test_snapshot_read_api.py:21-1164` 等 |

**污染路径判定**：护栏前 pytest 的 API 链写入走 sqlite 测试文件；直连 Mongo 的链路（`settings.mongodb_database`）落在 `dragon_board_quant_pytest`；Redis 缓存因未覆盖前缀，写入**生产命名空间** `hellobiga:dragon-board:local:*`（已实锤，见 §3）。测试无任何直连 `127.0.0.1:8000` 生产服务的用例（rg 0 命中）。

### 1.2 指纹体系（数据侧）

- 生产形状 id：`^(bt|opt|ds|tj)_[0-9a-f]{16}$`。
- 测试形状 id：tests/ 源码 rg 收集的 54 个 `bt_*`、18 个 `ds_*`、4 个 `opt_*` 字面量（bt_1、ds_test、ds_delete、bt_large 等）＋一切非 hex16 后缀的同前缀 id。
- 时间窗：`createdAt/startedAt/computedAt >= 2026-09-26`（覆盖 09-28/29 pytest 风暴）。
- Redis：SCAN（未用 KEYS）全量遍历 + 名称/值双指纹。

## 2. 生产库 `dragon_board_quant` 盘点（结论：零污染）

连通性：pymongo ping OK。库规模：11,309,715 objects，dataSize 12.50GB，storageSize 2.95GB，29 collections。

### 2.1 逐集合一览（$collStats，按 storageSize 降序，前 15）

| 集合 | count | storageSize | 污染判定 |
| --- | ---: | ---: | --- |
| backtest_signals | 10,030,842 | 1243MB | 70 个 backtestRunId 全部 hex16 生产形状，测试形状文档 **0** |
| snapshot_stock_rows | 646,234 | 768MB | datasetId 分布：dragonboard_live 100% |
| snapshot_analysis | 290,132 | 546MB | 全部 dragonboard_live（analyze 落库生产链） |
| snapshot_records | 2,931 | 229MB | 全部 dragonboard_live |
| backtest_runs | 186 | 59MB | 0 测试形状；185 条 dragonboard_live + 1 条孤儿（见 2.3） |
| snapshot_sector_rows | 222,028 | 51MB | 全部 dragonboard_live |
| hotlist_sentiment | 1,295 | 21MB | 全部 dragonboard_live |
| snapshot_frames | 2,933 | 11MB | 全部 dragonboard_live |
| theme_daily_factors | 21,514 | 3.9MB | 时间窗内新写入 0（盘后链生产数据） |
| themes / theme_stock_mappings | 245 / 13,304 | 3.7MB | 抽查无测试 theme id，真实 A 股代码 |
| fund_flow_l2 | 12,482 | 3.7MB | 生产 L2 资金缓存（sessionDate/code 结构） |
| backtest_trades / equity_curve | 3,652 / 50,730 | 2.5MB | 0 测试形状 |
| trade_journal | 767 | 1.9MB | 全部 `tj_`+hex16 生产形状 |
| snapshot_collector_runs | 1,813 | 1.5MB | 全部 dragonboard_live；最新 runId `sc-cf3d18dbe8a9`（09-29 11:25 本地，采集器当前活跃） |
| optimization_runs | 32 | 0.76MB | 0 测试形状，全部 dragonboard_live，时间范围 2026-05-12 ~ 08-15 |

### 2.2 指纹扫描结果

- `backtest_runs` 186 条全量拉取关键字段：测试形状 **0**；strategy 分布 rank_trend_candidate(109)/fusion(64)/…，createdAt 范围 2026-06-07 ~ 2026-09-26。
- `backtest_signals/trades/equity/quality_reports` 按 backtestRunId 聚合：distinct 70/70/70/77 个 run，测试形状文档均为 **0**。最大 run 各含 211,886 条 signals（真实全市场回测）。
- 时间窗（>=2026-09-26）命中：backtest_runs 7 条（全部 09-26 周六，用户手工回测，prod 形状 id）、trade_journal 6 条（09-29 09:35~10:57 本地，真实个股：博纳影业/中新赛克/深华发A 等，含实时行情快照，为用户当日手工日志）、migration_audit 116 条 + snapshot_collector_runs 115 条（生产采集器 09-28 起 snapshot_ingest 审计）。**无一来自 pytest。**
- `datasets` 集合 count=0（生产侧曾有 `mongodb_dataset_cleanup` 审计 3 次，dataset 登记被清理过——属历史生产操作，非 pytest 污染，但属值得注意的异常状态）。

### 2.3 唯一陌生 dataset 引用

`bt_139289ff0d61477c`（theme_state_hybrid，datasetId=`ds_c0dbe472f26340ff`，回测区间 2026-04-01~03，status=completed，createdAt 2026-09-26 12:04 本地）。id 为生产 hex16 形状、无任何子行（signals/trades/quality 均为 0）、dataset 本体已不在（datasets 集合为空）。判定：**用户手工回测后 dataset 被清理的孤儿元数据（1 文档，约 40KB）**，非 pytest 污染；默认保留，如需清理见 §5。

## 3. Redis 盘点（db0，SCAN 单遍普查 2026-09-29 ~11:35，库内 1,789 键）

`hellobiga:dragon-board:*` 共 1,782 键（注意：生产读写进程活跃，两次扫描间总数从 1,220 涨到 1,789，文中数字为单遍时点值）：

| 分类 | 键数 | 判定 |
| --- | ---: | --- |
| `pytest:` 前缀残留 | **113** | 护栏生效后（09-28/29）pytest 写入，全部为 `pytest:snapshot:generation:*`，单键 ~125B，TTL 165~167h，**约 2026-10-06 前自净** |
| `local:ths-main-monitor:raw:v1:*` | 796 | 生产（同花顺主力监控缓存） |
| `local:snapshot:index:*` | 637 | 生产，名称全部为 dragonboard_live 各类型索引；测试命名 **0** |
| `local:snapshot:generation:*` 测试命名 | **207** | `dragonboard_{projection_,sqlite_read_,sqlite_detail_,sqlite_detail_filter_,rank_series*,ranktrend_projection_,live_test,live_existing,live_summary,live_mixed,live_reason,history*,analysis_attach,cache_}_<17位时间戳>`，来自 tests/snapshot/test_snapshot_read_api.py 等的动态 dataset 名；名称时间戳 20260923~20260927，即**护栏前** pytest 写入生产前缀；TTL 1~6 天，无永久键（no-expiry=0），**约 2026-10-03 前全部自净** |
| `local:snapshot:generation:dragonboard_live_outbox_dedupe_<ts>` | 11 | 当前 backend 代码无此命名写入方（rg 0 命中），来源不明（疑为历史版本 dedupe 功能或手工 CLI 产物）；TTL 1~5.5 天自净；**处置前不确定，不建议盲删** |
| `local:snapshot:generation:` 生产裸名 | 3 | `dragonboard_live`、`dragonboard_backend_shadow`、`shadow`，生产合法 |
| `local:snapshot:` 读口 payload | 3~7 | ranktrend:analyze / frame_bundles / stock_rows / frames / theme_momentum 等，全部 dragonboard_live，TTL 7~250s |
| `local:theme-fund:v3:*`、`local:market:quotes:*` | ~4 | 生产，TTL 3 天（theme_fund_cache_ttl=259200）/ 分钟级 |
| BASE 之外 | 5 | `snapshot-collector:instance-lock:*`、`volume-ratio:*`（生产） |

值内容抽查：对 `local:snapshot:*`、`local:theme-fund:*` 的 string 值头部（≤300B）扫描测试 id 指纹（ds_test/bt_1/bt_delete 等），命中 **0**；测试命名 index 键 **0**。**即：生产命名空间下没有"值里引用测试 dataset"的缓存负载，污染仅为 generation 标记键本身。** 全程未删除任何键，未执行 FLUSHDB/FLUSHALL。

## 4. 旧库 `dragon_board_quant_pytest` 盘点

**已不存在。** `list_database_names()` 仅返回 `admin / config / dragon_board_quant / dragon_board_test / local`。任务简报中的「约 444MB、6 collections」现状不符——该库在简报撰写与本审计之间已被删除（只读审计无法追溯删除者与时间）。可释放体积：**0（无对象）**。若后续从旧 dump 恢复复现，确认后整库 drop 即可（内容为 pytest 中间产物）。

附带盘点 `dragon_board_test`（护栏后的合法测试库）：12.46GB / 28 collections，为 clone 脚本从生产全量克隆 + 测试残留（datasets 512 条测试 dataset、backtest_runs 629 条含 bt_1 等字面量、optimization_runs 126、snapshot_frames/records 9,585）。属设计内状态，可随时用 `scripts/clone_mongo_test_db.py` 重建；仅提示其占约 12GB 重复存储。

## 5. 清理提案（均未执行，需用户确认后另行操作）

### 5.1 Redis（可选加速自净，价值低——总量约 40KB 且全部带 TTL）

精确删除条件（二者之一）：

1. `hellobiga:dragon-board:pytest:*` —— 命名空间本身即测试专属（conftest 强制前缀），113 键全可删。
2. `hellobiga:dragon-board:local:snapshot:generation:*` 且末段名称匹配测试家族正则 `^dragonboard_(projection_|sqlite_|rank_series|ranktrend_projection_|live_test|live_existing|live_summary|live_mixed|live_reason|history|analysis_attach|cache_)` **且**带 `_\d{17}` 时间戳后缀，207 键。

**明确不可删**：`generation:dragonboard_live`、`generation:dragonboard_backend_shadow`、`generation:shadow`、`generation:dragonboard_live_outbox_dedupe_*`（来源不明）、一切 index/ths-main-monitor/payload/theme-fund 键。

可回滚步骤（先归档后删除）：

```text
1) SCAN {pattern} COUNT 1000 逐键收集（严禁 KEYS）
2) 每键记录 DUMP + TYPE + TTL，写 JSONL：
   {"key":..., "type":..., "ttl":..., "payload":"<DUMP 的 hex>"}
   归档落 quant-board/data/backups/redis/redis_residue_20260929.jsonl（gitignore 区）
3) 人工复核 JSONL 键名清单（应全部命中 §5.1 条件，零生产裸名）
4) 逐键 DEL（或 UNLINK），建议单批 <=200 键、避开盘中采集时段
5) 回滚：对 JSONL 每行 RESTORE key ttl payload（TTL 用 max(剩余,1)），Redis RESTORE 语法幂等重建
```

### 5.2 MongoDB

- 生产库：**无需任何删除**（0 污染文档）。可选项：孤儿 `bt_139289ff0d61477c`（其 dataset 已被清理）如需清理，先 find_one 导出 JSONL 归档再 delete_one，默认建议保留（用户回测历史）。
- 旧库：无对象可清。
- `dragon_board_test`：如需回收 12GB，先 `mongodump --db=dragon_board_test --archive` 归档，再 drop，之后需要时跑 `scripts/clone_mongo_test_db.py` 重建。非本轮污染清理范畴。

### 5.3 防复发补强（建议，1 行改动）

`tests/conftest.py` 的 `_guard_mongodb_test_database` 目前只断言 `storage_backend` 与 `mongodb_database`，建议追加断言 `settings.redis_key_prefix == "hellobiga:dragon-board:pytest"`——本次 Redis 污染的直接根因就是护栏前未覆盖该前缀，当前只有 env 设置没有护栏断言。

## 6. 风险与不确定项

1. **无法证明"从未发生"**：更早（约 09-23 前）pytest 风暴的缓存键若已过 TTL 自然消失，只读审计不可见；但 Mongo 侧全集合指纹扫描为零，永久性污染不存在。
2. `dragonboard_live_outbox_dedupe_*`（11 键）在当前代码无写入方，来源未定位（历史版本或手工操作），已归入不确定项，TTL 内自净。
3. 审计期间生产采集器/读服务活跃，Redis 计数为时点值；生产库 backtest_runs 在两次读之间出现 185→186 属采集器/用户并发写入的计数口径差（count_documents vs $collStats 元数据）。
4. 生产 `datasets` 集合为空但有 185 个 backtest run 引用 `dragonboard_live`——这是历史清理操作（migration_audit 有 mongodb_dataset_cleanup 记录）造成的既有状态，与本轮 pytest 无关，建议另立课题核实是否影响数据链读口。
5. 本审计未运行 pytest、未触碰任何写命令；所有结论基于 `count_documents`、聚合管道、`$collStats`、`find limit(<=5)` 样例与 SCAN 只读遍历。

## 附：审计产物

- `.tmp/mongo_inventory.py` / `.tmp/mongo_inventory.json` —— 三库 $collStats 全量
- `.tmp/prod_fingerprint_scan.py` / `.tmp/prod_fingerprint_scan.json` —— 生产库指纹扫描原始数据
- `.tmp/redis_scan.py` / `.tmp/redis_scan.json` —— Redis 分类与 TTL 原始数据

## 7. 清理执行记录（2026-09-29 T1，主线程执行）

- 脚本：`.tmp/redis_cleanup_20260929.py`（dry-run 归档+断言 → `--execute` 分批 UNLINK≤200）。
- 实删：**113 键**，全部 `hellobiga:dragon-board:pytest:*`（护栏后 pytest 写入）。
- §5.1 条件 2（generation 测试家族 207 键）：执行时 SCAN 已为 **0**——护栏前写入的键已按 TTL 全部自然过期，无需删除。
- 归档回滚件：`data/backups/redis/redis_residue_20260929.jsonl`（113 行，含 DUMP hex/TTL/TYPE；回滚=逐行 RESTORE）。
- 复扫：两类测试模式残留=0；生产键抽查（`generation:dragonboard_live`、`snapshot:index:dataset:dragonboard_live`、`ths-main-monitor:raw:v1:000001`）全部健在。
- 生产 MongoDB：本任务零改动（审计已证明零污染，无删除对象）。终验（T7）将在最后一轮 pytest 后重跑本脚本做收尾卫生。
