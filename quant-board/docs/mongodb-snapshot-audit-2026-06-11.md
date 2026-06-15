# MongoDB 定时行情快照审计报告（2026-06-11）

## 结论

`dragonboard_live` 在 2026-06-11 修复前存在空 formal snapshot、`snapshot_record` 缺失、frame 计数漂移、15:00 formal close slot 缺失，以及研究集合索引缺失五类问题。已完成备份、修复和复核，当前 `half_hour` 与 `quarter_hour` 两个主研究口径的 `verify-mongodb-migration` 均返回 `ok=true`。

## 审计时间与环境

- 审计日期：2026-06-11
- 运行库：`mongodb://127.0.0.1:27017/dragon_board_quant`
- 数据集：`dragonboard_live`
- 备份 ID：`20260611T093132Z`
- 修复审计行：`migration_audit.opType=mongodb_snapshot_repair`
- 第 1 次修复审计时间：`2026-06-11 09:05:55.366000`
- 第 2 次修复审计时间：`2026-06-11 09:36:04.559000`

## 修复前基线

修复前执行：

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli list-datasets
.\.venv\Scripts\python.exe -m backend.cli inspect-mongodb
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live
```

修复前已确认问题：

1. 空 `half_hour` formal snapshot 4 个：
   - `half_hour:2026-05-07:13:00`
   - `half_hour:2026-05-08:14:00`
   - `half_hour:2026-05-14:13:00`
   - `half_hour:2026-05-18:11:30`
2. `snapshot_record` 缺失 255 个：
   - `half_hour`: 42
   - `quarter_hour`: 213
3. 已确认 frame 计数漂移：
   - `half_hour:2026-04-16:10:00`：`stockRowCount 237 -> 288`
   - `half_hour:2026-05-18:11:30`：`stockRowCount 275 -> 239`，`sectorRowCount 75 -> 25`
   - `quarter_hour:2026-06-08:13:15`：`stockRowCount 229 -> 243`
4. 缺失 formal close slot：
   - 首轮已确认：`half_hour:2026-04-15:15:00`
   - 继续审计发现近期 15:00 close slot 常态性缺失：
     - `2026-05-28`：`hourly:15:00`、`daily:15:00`
     - `2026-06-01`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
     - `2026-06-03`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
     - `2026-06-05`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
     - `2026-06-10`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
5. 研究集合缺失索引 2 个：
   - `backtest_trades(backtestRunId, sequence)`
   - `backtest_equity_curve(backtestRunId, sequence)`

## 修复执行

先完成全库备份并校验：

```powershell
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
```

备份结果：

- `backupId = 20260611T093132Z`
- 本地目录：`quant-board/data/backups/mongodb/full/backup_id=20260611T093132Z`
- `verify=true`

随后执行正式修复与定向 close slot 补齐：

```powershell
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live --apply
.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live --snapshot-id hourly:2026-05-28:15:00 --snapshot-id daily:2026-05-28:15:00 --snapshot-id quarter_hour:2026-06-01:15:00 --snapshot-id half_hour:2026-06-01:15:00 --snapshot-id hourly:2026-06-01:15:00 --snapshot-id daily:2026-06-01:15:00 --snapshot-id quarter_hour:2026-06-03:15:00 --snapshot-id half_hour:2026-06-03:15:00 --snapshot-id hourly:2026-06-03:15:00 --snapshot-id daily:2026-06-03:15:00 --snapshot-id quarter_hour:2026-06-05:15:00 --snapshot-id half_hour:2026-06-05:15:00 --snapshot-id hourly:2026-06-05:15:00 --snapshot-id daily:2026-06-05:15:00 --snapshot-id quarter_hour:2026-06-10:15:00 --snapshot-id half_hour:2026-06-10:15:00 --snapshot-id hourly:2026-06-10:15:00 --snapshot-id daily:2026-06-10:15:00 --apply
```

本次修复实际落库摘要：

| 动作 | 数量 |
| --- | ---: |
| 首轮 `snapshotRepairs` | 5 |
| `countFixes` | 3 |
| `missingRecords` | 255 |
| `indexRepairs` | 2 |
| 次轮 `snapshotRepairs` | 18 |

## 修复后结果

修复后执行：

```powershell
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type quarter_hour
```

修复后主库统计：

| 指标 | 修复后 | 变化 |
| --- | ---: | ---: |
| `snapshot_records` | 1515 | +274 |
| `snapshot_frames` | 1515 | +19 |
| `snapshot_stock_rows` | 330622 | +5390 |
| `snapshot_sector_rows` | 14947 | +53 |
| `migration_audit` | 761 | +2 |

修复后验收结论：

- `half_hour`：`ok=true`
- `quarter_hour`：`ok=true`
- `emptyFrames=[]`
- `missingRecords=[]`
- `countMismatches=[]`
- `missingSlots=[]`
- MongoDB 缺失索引归零
- 目标 18 个 15:00 close slot 全部存在，frame/record/stock rows 复核通过
- `2026-06-11 half_hour:15:00` 为实时正式快照，未发现缺失：
  - `captureMode = real_time`
  - `source = browser_runtime`
  - `stockRowCount = actualStockRows = 214`

## 影响说明

- `snapshot_records +274` 的来源：
  - 补 `snapshot_record` 255 个
  - 新建 `half_hour:2026-04-15:15:00` record 1 个
  - 新建 18 个 15:00 close slot record
- `snapshot_frames +19` 的来源：
  - 新建缺失 formal slot `half_hour:2026-04-15:15:00`
  - 新建 18 个 15:00 close slot frame
- `snapshot_stock_rows +5390` 的来源：
  - 4 个空 `half_hour` donor 回填共 `904`
  - 新建 `half_hour:2026-04-15:15:00` 从 `daily` 补齐 `240`
  - 新建 18 个 15:00 close slot 共 `4246`
- `snapshot_sector_rows +53` 的来源：
  - `half_hour:2026-05-18:11:30` 回填 `25`
  - 新建 `half_hour:2026-04-15:15:00` 从 `daily` 补齐 `28`

## 根因判断

从代码与现有数据形态看，问题分成两层：

1. 历史存量问题：
   - formal frame 已写入，但对应股票行缺失，形成空快照。
   - frame 与 rows 已存在，但 `snapshot_record` 未同步写入。
   - 历史回填或结构变更后，`stockRowCount/sectorRowCount` 未随事实行同步刷新。
   - runtime MongoDB 未补齐两个导出热路径索引。
2. 近期 15:00 close slot 常态性缺失的根因：
   - 前端调度 `snapshot.sweep` 预期在收盘后补跑 close slot。
   - 但任务定义设置了 `tradingTimeOnly=true`，导致 15:00 后 sweep 被直接停掉。
   - 结果是 backfill window 逻辑存在，但收盘后根本没有机会执行，所以 `2026-05-28` 到 `2026-06-10` 多日的 `15:00` slot 持续缺失。

## 剩余风险

- `half_hour:2026-04-15:15:00` 以及本次定向补出的部分 `15:00` slot 属于合成 frame，已显式标记：
  - `captureMode = synthesized`
  - `source = cross_type_backfill` 或 `same_type_backfill`
  - `qualityFlags += backfilled_from_cross_type_snapshot` 或 `backfilled_from_nearest_snapshot`
- `snapshot_record` 补造恢复的是正式读口契约，不代表完全重建历史原始 ingest payload。
- 当前修复是 fix-forward，后续如果 ingest 主链再出现同类异常，仍需把问题追到正式写入环节，而不是长期依赖离线修补。

## 对应文档

- 设计说明：[docs/superpowers/specs/2026-06-11-mongodb-snapshot-repair-design.md](./superpowers/specs/2026-06-11-mongodb-snapshot-repair-design.md)
- 修正记录：[docs/mongodb-snapshot-repair-log-2026-06-11.md](./mongodb-snapshot-repair-log-2026-06-11.md)
