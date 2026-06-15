# MongoDB 定时行情快照修正记录（2026-06-11）

## 执行信息

- 数据集：`dragonboard_live`
- 首轮执行命令：`.\.venv\Scripts\python.exe -m backend.cli backfill-empty-mongodb-snapshots --dataset-id dragonboard_live --apply`
- 次轮执行命令：定向补齐 18 个 `15:00` close slot，见审计报告中的完整命令
- 备份 ID：`20260611T093132Z`
- 首轮修复审计时间：`2026-06-11 09:05:55.366000`
- 次轮修复审计时间：`2026-06-11 09:36:04.559000`
- `migration_audit.opType`：`mongodb_snapshot_repair`

## 修复摘要

| 类别 | 数量 |
| --- | ---: |
| 首轮空快照/缺槽位修复 | 5 |
| frame 计数修复 | 3 |
| `snapshot_record` 补造 | 255 |
| 索引修复 | 2 |
| 次轮 15:00 close slot 补造 | 18 |

## 首轮快照修复明细

| 动作 | 目标快照 | donor | 结果 |
| --- | --- | --- | --- |
| 缺槽位补造 | `half_hour:2026-04-15:15:00` | `daily:2026-04-15:15:00` | 新建 frame 1、record 1、stock rows 240、sector rows 28 |
| 空快照补齐 | `half_hour:2026-05-07:13:00` | `quarter_hour:2026-05-07:13:15` | 回填 stock rows 216 |
| 空快照补齐 | `half_hour:2026-05-08:14:00` | `half_hour:2026-05-08:13:30` | 回填 stock rows 224 |
| 空快照补齐 | `half_hour:2026-05-14:13:00` | `half_hour:2026-05-14:13:30` | 回填 stock rows 225 |
| 空快照补齐 | `half_hour:2026-05-18:11:30` | `half_hour:2026-05-18:11:00` | 回填 stock rows 239、sector rows 25 |

补槽位合同：

- `captureMode = synthesized`
- `source = cross_type_backfill`
- `displayKey = half_hour:2026-04-15:15:00`
- `qualityFlags += backfilled_from_cross_type_snapshot`

## 次轮定向 close slot 补造

- `2026-05-28`：`hourly:15:00`、`daily:15:00`
- `2026-06-01`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
- `2026-06-03`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
- `2026-06-05`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`
- `2026-06-10`：`quarter_hour:15:00`、`half_hour:15:00`、`hourly:15:00`、`daily:15:00`

次轮 donor 规则：

- 优先使用显式规则：如 `half_hour:15:00 <- daily:15:00`
- 若显式 donor 不存在或不可用，则回退到同交易日最近的非空 donor
- 优先同粒度 donor；同粒度不可用时允许跨粒度 donor

## frame 计数修复明细

| 快照 | 字段 | 修复前 | 修复后 |
| --- | --- | ---: | ---: |
| `half_hour:2026-04-16:10:00` | `stockRowCount` | 237 | 288 |
| `half_hour:2026-05-18:11:30` | `stockRowCount` | 275 | 239 |
| `half_hour:2026-05-18:11:30` | `sectorRowCount` | 75 | 25 |
| `quarter_hour:2026-06-08:13:15` | `stockRowCount` | 229 | 243 |

按 repair audit 计数，实际发生的 frame 计数修复对象是 3 个：

- `half_hour:2026-04-16:10:00`
- `half_hour:2026-05-18:11:30`
- `quarter_hour:2026-06-08:13:15`

## `snapshot_record` 补造

本次共补造 `255` 个 `snapshot_record`：

- `half_hour`: `42`
- `quarter_hour`: `213`

补造规则：

- 以现有 `snapshot_frame` 为主
- 对齐 `snapshotId/type/tradingDate/slotTime/timestamp`
- 反建 `displayKey/captureMode/capturedAt/dataTimestamp/delayMs/qualityFlags/source`

完整快照 ID 清单已落在：

- `migration_audit` 最新两条 `opType=mongodb_snapshot_repair`
- 字段：`applied.missingRecords`

## 索引修复

新增 runtime MongoDB 索引：

1. `backtest_trades(backtestRunId, sequence)`
2. `backtest_equity_curve(backtestRunId, sequence)`

修后 `verify-mongodb-migration` 不再报告缺失索引。

## 修复后核验

执行结果：

```powershell
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type half_hour
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-migration --dataset-id dragonboard_live --snapshot-type quarter_hour
```

结论：

- `half_hour`：`emptyFrames/missingRecords/countMismatches/missingSlots` 全部归零
- `quarter_hour`：`missingRecords/countMismatches` 归零
- 索引缺口归零
- 18 个目标 `15:00` close slot 全部复核存在
- `2026-06-11 half_hour:15:00` 为实时快照，`stockRowCount=214`，不存在缺失
