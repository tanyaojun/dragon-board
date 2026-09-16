# MongoDB 备份链 mongodump 化与冗余清理设计

日期：2026-09-16
状态：设计已确认，待实施计划
关联文档：[mongodb-migration-plan.md](../../mongodb-migration-plan.md)、[api-cli.md](../../api-cli.md)、[architecture.md](../../architecture.md)

## 1. 背景与现状

### 1.1 空间构成（2026-09-16 实测）

`dragon_board_quant` 磁盘占用 8.45 GB（+ 索引 648 MB），活数据 dataSize 6.4 GB：

| 集合                   | 文档数 | storage | freeStorage（可回收） |
| ---------------------- | -----: | ------: | --------------------: |
| backtest_result_chunks |    281 | 5947 MB |           **4905 MB** |
| backtest_signals       | 855014 |  968 MB |            **868 MB** |
| snapshot_stock_rows    | 626660 |  723 MB |                  2 MB |
| snapshot_analysis      | 248009 |  473 MB |                 33 MB |
| 其余 30 个集合         |      — | ~342 MB |                  零头 |

backtest_result_chunks 的死空间来自历史研究清理后 WiredTiger 未归还磁盘；compact 一次即可回收。

### 1.2 备份链现状

存在两套并行实现：

- **A 链（生产在跑）**：计划任务 `QuantBoard-LightBackup`（每日 15:30）/ `QuantBoard-FullBackup`（周五 16:00）→ `scripts/scheduled_backup.py` → `backend/data/backup/mongodb_backup.py` pymongo 逐文档导出 gzip JSONL（`mongodb_backup.v1` manifest + sha256 + R2 push + 30 天 prune）。
- **B 链（工作区 untracked，不属本任务修改范围）**：`backend/operations/mongodb_full_backup.py`，pymongo 手写 bson.gz（mongorestore 兼容格式），2026-09-11 改库前标准备份方式，未接 CLI 与调度。

A 链问题：

1. JSONL 自定义格式**没有恢复工具**——只有备份与校验，真出事时无法直接导入。
2. Python 逐文档序列化慢（light 每日约 4 分钟，随数据增长线性变差）。
3. 计划任务可靠性差：2026-09-11（周五）FullBackup 因任务条件不满足被拒（0x800710E0），当天 light/full 全部缺失，错过即整天无备份。
4. 任务为 GUI 手工注册，仓库内无注册脚本，不可重建。
5. `api-cli.md` 记载的集合数（13/25）与代码（4/15）不一致。

### 1.3 冗余集合审计结论（35 个集合逐一体检）

**死集合（全仓库含 git 历史零代码引用，可 drop）**：

| 集合                  | 文档数 | 判定依据                                                                                                                     |
| --------------------- | -----: | ---------------------------------------------------------------------------------------------------------------------------- |
| big_order_revisions   |    276 | 写入代码随 WIP 提交 75f80457 被 reset 丢弃；现行 big-order 链路走 Redis + gzip 文件归档（`backend/data/big-order/`），不落库 |
| big_order_current     |     21 | 同上                                                                                                                         |
| big_order_attempts    |    421 | 同上                                                                                                                         |
| live_refresh_attempts |   1920 | 全仓库无引用，某版采集器实验残留                                                                                             |
| live_refresh_rounds   |    197 | 同上                                                                                                                         |
| live_refresh_state    |     11 | 同上                                                                                                                         |
| theme_market_rows     |   2895 | 同上                                                                                                                         |

**数据级冗余（集合活跃，内含可清文档）**：

| 项                                  | 体检结果                                                                                      | 判定                                                                                                                                      |
| ----------------------------------- | --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| 数据集 `ds_ffa379a00efe47d0`        | 2026-06-01~12 共 10 天 half_hour，100 records / 22584 stock rows，sourceType=sqlite_snapshots | 6 月中旬 SQLite 导入测试残留；工作区与全部长测文档零引用（长测全用 `dragonboard_live`）；可用现有 `cleanup-mongodb-datasets --apply` 清除 |
| 数据集 `dragonboard_backend_shadow` | 四个快照集合 0 行，仅 datasets 一条空壳元数据                                                 | 文档原意"保留作审计参考"，但数据行早已清空；删空壳元数据                                                                                  |
| `snapshot_records` type=five_minute | 50 条，全部 2026-07-29 单日                                                                   | 粒度已废止，单日实验残留                                                                                                                  |

**体检后确认不是冗余、保持不动**：

- `theme_factor_frames` / `theme_stock_exposures` / `theme_signals` / `theme_quality_reports`（4 个空集合）：迁移时特意创建的正式结构 + 索引，repository 活跃引用。
- `trade_journal`（751 条全为 thesis/trading_pool）、`backtest_runs`（151 条全 completed）、`hotlist_sentiment`、`fund_flow_l2`（29 个交易日 9531 条，2.8 MB，运行态设计如此）、`snapshot_collector_runs`（1635 条，1.3 MB）、`migration_audit`、`golden_ranktrend_cases`、`archive_manifests`、`stock_names`、题材集合、快照四表。
- `dragonboard_backend_shadow` 之外的正式数据一律不动；遵守"备份与归档不承担主库瘦身职责"的既有合同。
- **索引不删**：`$indexStats` 显示的零访问索引不可靠（计数自 mongod 启动起算，研究查询近期未跑），且全部是 mongodb-migration-plan.md 明文定义的合同索引；compact 时索引空间顺带重整。

## 2. 目标

1. 备份产物从自定义 JSONL.gz 换成 mongodump 原生 bson.gz，mongorestore 直接可恢复，补齐"备份→校验→恢复→再校验"闭环。
2. 备份调度并入 after-market-once 盘后链，删除两个独立备份计划任务。
3. 删除 7 个死集合与 3 项数据级冗余；compact 回收约 5.8 GB 死空间。
4. 同步更新存储文档，使备份/恢复/清理口径与代码一致。

## 3. 非目标

- 不动 MongoDB 主库正式明细（snapshot\_\* / backtest 明细 / 题材 / stock_names）。
- 不修改、不删除 B 链 `backend/operations/mongodb_full_backup.py`（工作区 untracked，属协作者/用户的 2026-09-11 工作）。
- 不 drop `dragon_board_quant_pytest` 测试库（用户决策：保留）。
- 不改 R2 上传/拉回框架（文件级操作，与备份格式无关）。
- 不调整 `fund_flow_l2` / `snapshot_collector_runs` 的保留策略（体量小，列为观察项）。
- 不删除任何索引，不改集合定义与查询合同。

## 4. 备份引擎改造（mongodump）

### 4.1 工具安装

- `backend/core/settings.py` 新增 `mongodb_tools_bin` 配置项，默认 `D:\APP_SOFT\MongoDB\tools\bin`，可用环境变量覆盖；代码以绝对路径调用 `mongodump.exe` / `mongorestore.exe`，不强依赖 PATH。
- 备份入口在 tools 缺失时结构化报错（错误信息含安装路径提示），不静默回退 JSONL。

### 4.2 MongoBackupService 换引擎

`backend/data/backup/mongodb_backup.py`：

- `_create_backup` 内 pymongo 逐文档导出改为 subprocess 调用：
  - full：`mongodump --uri <uri> --db dragon_board_quant --gzip --out <staging_dir>`（一次全库）。
  - light：对 `LIGHT_BACKUP_COLLECTIONS`（4 个 snapshot 集合）逐集合 `mongodump --uri <uri> --db ... --collection <name> --gzip --out <staging_dir>`。
- 产物为 mongodump 原生 `<db>/<collection>.bson.gz` + `<db>/<collection>.metadata.json`。
- manifest 结构保留（backupId / docCounts / collections.file / fileHash / bytes / strategy / objectKey...），`schemaVersion` 升为 `mongodb_backup.v2`；文档数来源改为 metadata.json 的 count（与 mongodump 实际导出一致）。
- **v1 兼容**：verify 按 manifest 的 schemaVersion 分派——v2 校验 bson.gz 文件 hash 与字节数；v1 走原 JSONL 行数校验路径，保证 2026-05~09 的历史备份仍可校验。
- push / pull / prune / list 为文件级操作，不改。
- 恢复闭环新增 CLI `restore-mongodb-backup`：
  ```powershell
  .\.venv\Scripts\python.exe -m backend.cli restore-mongodb-backup --backup-id <id> [--target-db dragon_board_quant_restore_staging] [--drop]
  ```
  薄封装 `mongorestore --gzip --nsFrom "dragon_board_quant.*" --nsTo "<target>.*"`，只允许恢复到非正式库名（拒绝 target 为 `dragon_board_quant` 本身，防误覆盖）；对齐 mongodb-migration-plan.md 恢复流程第 5-6 步，第 6 步校验复用 `verify-mongodb-migration`。
- 命令构造（mongodump/mongorestore 参数拼装）抽成纯函数供 pytest 直接覆盖；subprocess 执行层保持薄。

### 4.3 备份策略（不变）

- light = 4 个 snapshot 集合，每个交易日；full = 全库，周五；R2 push 仅 full；本地保留 30 天。
- mongodump 引擎下 light 预计从 ~4 分钟降到 1-2 分钟。

## 5. 调度层改造（并入 after-market-once）

`backend/operations/schedule.py` MongoDB 分支在 `hotlistSentiment` 步骤后追加：

```text
hotlistSentiment -> backup(light|full 按交易日历, 周五 full) -> verify -> prune 本地 -> (周五) push R2
```

- 备份失败不回滚、不影响 hotlistSentiment 已完成事实；结构化记录失败步骤与原因（日志 + 返回值），并使 after-market-once 以非零码退出，计划任务历史可见。
- Windows 任务变更：
  - 删除 `QuantBoard-LightBackup`、`QuantBoard-FullBackup` 两个计划任务。
  - 重建 `QuantBoard After Market`：去掉 `--archive-limit 5 --backup-limit 20` 死参数（MongoDB 模式下无效果），补可靠性设置（`StartWhenAvailable`、不限定交流电源/空闲条件，错过窗口后尽快补跑）。
  - 提供 `scripts/register_after_market_task.ps1` 注册脚本入库，任务从此可重建（替换 GUI 手工注册）。
- 触发时间不变（交易日 15:30）。

## 6. 清理清单（盘后执行，逐项先备份再删除）

| 顺序 | 动作                                                                                                                                                                                                                                | 方式                                                       | 回收          |
| ---- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------- |
| 1    | 全量 mongodump 兜底备份（改造后的 full）                                                                                                                                                                                            | 新备份链                                                   | —             |
| 2    | drop 7 个死集合：big_order_revisions / big_order_current / big_order_attempts / live_refresh_attempts / live_refresh_rounds / live_refresh_state / theme_market_rows                                                                | 新增一次性清理 CLI（见 6.1），每个 drop 前单集合 mongodump | ~12 MB        |
| 3    | 数据级冗余：`cleanup-mongodb-datasets --dry-run` 过目后 `--apply` 清 `ds_ffa379a00efe47d0`；删 `dragonboard_backend_shadow` 空壳 datasets 元数据；删 five_minute 残留（records 50 条 + frames/rows 关联数据，dry-run 输出实际计数） | 同上 CLI 子步骤（先 dry-run 输出清单）                     | ~40 MB 活数据 |
| 4    | 删 18 个旧研究 run（2026-06~08）的 backtest_result_chunks 文档                                                                                                                                                                      | 同上 CLI 子步骤；runId 清单与删除计数写 `migration_audit`  | ~1 GB 活数据  |
| 5    | compact `backtest_result_chunks` + `backtest_signals`                                                                                                                                                                               | 手动盘后执行（命令见实施计划），前后 collStats 对比留档    | **~5.8 GB**   |

预计磁盘 8.45 GB → 约 2.5 GB。

### 6.1 一次性清理 CLI

- 位置：`backend/operations/mongodb_dead_data_cleanup.py`，CLI 名 `cleanup-mongodb-dead-data`，默认 dry-run，显式 `--apply` 才执行。
- 行为：每个子步骤（drop / dataset 清理 / chunks 删除）独立开关（如 `--drop-dead-collections --cleanup-datasets --purge-result-chunks`），删除前输出将删对象清单与计数；apply 时每集合先单集合 mongodump 到 `data/backups/mongodb/pre-cleanup-<ts>/`，结果（对象、删前 count、备份路径）写 `migration_audit`（opType=`mongodb_dead_data_cleanup`）。
- 不新增常驻集合；`migration_audit` 是既有 append-only 审计集合。

### 6.2 读取容错

`backtest_runs` 中 18 个 `resultChunked=true` 的 run，chunks 删除后读取路径必须返回结构化缺失标记（如 `resultPurged=true` / 明确错误信息），不得抛未处理异常或返回伪空结果；对齐 fail-visible 原则（派生结论可停产，缺失必须可见）。

## 7. 测试与验证

- pytest（`tests/test_mongodb_backup.py` 改造 + 新增）：
  - v2 manifest 结构、bson.gz 文件 hash 校验、v1 旧备份兼容校验。
  - mongodump / mongorestore 命令构造纯函数（light 多集合、full、restore nsFrom/nsTo、拒绝正式库名）。
  - prune、restore-staging 隔离等既有合同回归。
  - resultChunked run 的 chunks 缺失读取容错。
- 验证命令（不跑全量 pytest，本机已知挂起问题）：
  ```powershell
  cd quant-board
  .\.venv\Scripts\python.exe -m pytest tests/test_mongodb_backup.py -q
  .\.venv\Scripts\python.exe -m pytest tests/test_mongodb_migration.py -q
  ```
- 端到端验收（人工，盘后）：
  1. `backup-mongodb --full` → 确认 bson.gz 产物与 manifest v2。
  2. `verify-mongodb-backup` 通过。
  3. `restore-mongodb-backup --backup-id <id> --drop` → `verify-mongodb-migration` 对 staging 库抽查通过。
  4. 清理各步骤 dry-run → apply → `inspect-mongodb` 复核计数。
  5. compact 前后 collStats 对比。
  6. 次日 15:30 后人工检查 after-market-once 日志与本地备份产物（复盘教训：上线首日必须查实际产物，不能只看任务状态）。

## 8. 文档同步

- `mongodb-migration-plan.md`：备份命令合同（v2 格式、restore CLI）、盘后调度链、清理审计记录。
- `api-cli.md`：计划任务表（删除两任务、重建 after-market 任务）、新增 `restore-mongodb-backup` / `cleanup-mongodb-dead-data`、修正集合数口径（4/15）。
- `architecture.md`：备份链一句带过处对齐 mongodump。

## 9. 风险与回退

| 风险                             | 缓解                                                                         |
| -------------------------------- | ---------------------------------------------------------------------------- |
| 删除不可逆                       | 前置全量 bson.gz 兜底 + 每集合删前单集合 dump + migration_audit 记录，双保险 |
| compact 阻塞                     | 严格盘后执行；compact 失败不损坏数据可重试                                   |
| after-market-once 首日出错       | 备份步骤独立开关与结构化报错；首日人工验证产物                               |
| mongodump 不在预期路径           | settings 配置 + 结构化报错提示                                               |
| 旧 v1 备份不可用                 | verify 按 schemaVersion 分派兼容                                             |
| ds_ffa379a00efe47d0 误删有效数据 | dry-run 清单先行 + 长测文档已证零引用；删除动作可从全量兜底备份恢复          |

## 10. 验收标准

- 备份产物为 mongorestore 可直接消费的 bson.gz；从本地备份经 restore CLI 恢复到 staging 库并通过 `verify-mongodb-migration` 抽查。
- 计划任务只剩 `QuantBoard After Market`（注册脚本入库），盘后链含备份步骤且日志可见。
- 7 个死集合、3 项数据级冗余、18 个 run 的 chunks 已删除，`migration_audit` 有完整记录；pytest 库未动。
- compact 后 `dbStats.storageSize` ≤ 3 GB（预期 ~2.5 GB）。
- 文档三处（migration plan / api-cli / architecture）与实际一致。
