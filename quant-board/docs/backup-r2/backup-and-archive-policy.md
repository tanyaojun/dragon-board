# QuantBoard 备份与 R2 归档策略（2026-09-28 定稿）

> 数据链路设计遵守 `skills/fail-visible-data-pipelines/SKILL.md`：质量检查负责暴露，
> 不做静默丢弃；备份/归档失败以非零退出码 + 落盘日志可见。
> 单次清理审计见同目录 `2026-09-28-result-chunks-cleanup-audit.md`。

## 1. 三层定位

| 层 | 载体 | 内容 | 落点 | 保留 |
| --- | --- | --- | --- | --- |
| 快照历史长期层 | parquet（zstd） | 四类型快照四表（records/frames/stockRows/sectorRows），按 dataset/type/tradingDate 逐日 | R2 `quant-board-archive` 桶，`snapshot_backup_<dataset>_<type>_<date>/` | 永久 |
| 全库灾难恢复层 | mongodump（bson.gz） | 全库所有集合（周五） | R2 同桶 `mongodb-backups/full/backup_id=<UTC时间戳>/` | 13 份（周频 ≈ 90 天） |
| 当日快速恢复层 | mongodump（bson.gz） | 快照四集合（交易日 light） | 本地 `data/backups/mongodb/full/` | 7 天 |

分工：日常按日回看/重算走 parquet 归档；整机/整库灾难用周五全量；当天误删快照用本地 light。
R2 无出网费、存储费可忽略（全库 2026-09 实测 gzip 后 ~1.5GB × 13 份 ≈ 20GB ≈ $0.3/月）。

## 2. 调度

单一计划任务 **QuantBoard After Market**（每日 18:00，2026-09-28 起；原 15:30 与
daily 快照采集窗口重叠，18:00 保证备份/归档拿到全天完整数据）：

```
hotlistSentiment → mongodbBackup → snapshotArchiveR2
```

- **mongodbBackup**：交易日 light / 周五 full → verify（sha256 + 文档数重数）→
  本地 prune → 周五（及断档补跑 full）push R2 → 远端 prune（keep 最近 13 份）。
- **snapshotArchiveR2**：按 `archive_auto_snapshot_types`（half_hour,quarter_hour,
  five_minutes,daily）逐类型归档**最近已收盘交易日**（严格早于今日，避开 15:30 槽位
  竞态）；幂等（已 uploaded 跳过），单类型失败不阻断其它类型，只归档不删 Mongo。
- **结果落盘**：`data/backups/mongodb/after_market.log` 每次一行 JSON 摘要
  （含各类型上传文件数/字节数）；失败另存 `after_market-failure-<ts>.json` 完整结果。
  任务计划历史只有退出码，摘要行是日常核查入口。
- 归档时间 18:00 与 daily 采集（15:30 窗口）、five_minutes 采集（盘中 50 槽）均不重叠。

历史一次性动作：`snapshot-archive-backfill` 已把 half_hour/quarter_hour/daily 全部
存量日期回填进 R2（幂等可重跑）；five_minutes 自入采起由日常链覆盖。

## 3. 断档自愈（2026-09-28 新增）

错过周五（停机/休市调整）时，周末补跑因非交易日跳过、当周只剩 light，R2 全量断档
一整周（2026-09-18 实际发生过）。自愈规则：

- 非周五交易日 18:00 检查最近一次成功全量（优先远端 R2——本地保留期短于周间隔，
  本地可能已看不到上一次全量；远端不可用回退本地 manifest 扫描）；
- 距上次 full **≥ 8 天** → 当日强制 full 并立即 push R2，`fullCatchUp` 字段记录原因；
- 配置了 R2 但从未有任何全量 → 同样强制补一次；
- 未配置 R2 → 无法可靠判断，保持 light 并结构化记录
  `full_history_unavailable_without_object_store`。

## 4. 保留参数（.env.local）

| 参数 | 值 | 说明 |
| --- | --- | --- |
| `QUANT_BOARD_MONGODB_BACKUP_RETENTION_DAYS` | 7（2026-09-28 起，原 30） | 本地 dump 保留天数。五分钟满负荷后 light 单份预计一年涨到 ~3.5-4GB，30 天保留会吃掉 100GB+ 本地盘；历史已由 R2 归档兜底，本地只做当日桥接 |
| `QUANT_BOARD_MONGODB_REMOTE_BACKUP_KEEP` | 13（原 4） | R2 全量保留份数，周频 ≈ 90 天恢复窗口 |
| `QUANT_BOARD_ARCHIVE_RETENTION_TRADING_DAYS` | 90 | 快照归档保留窗口（现状不动） |
| `QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES` | half_hour,quarter_hour,five_minutes,daily | 归档类型；hourly 为废止类型不归档 |

## 5. 数据量测算（2026-09-28 实测基准）

Mongo 全库 ~14.6GB：backtest_result_chunks 11.7GB（93 个扫描 trial，已按 2026-09-28
审计清理）、backtest_signals 1.24GB、快照四集合 ~1.05GB。

quarter_hour 重采 + five_minutes（50 槽/日）满负荷后：

| 类型 | 帧/天 | 日增 raw |
| --- | --- | --- |
| half_hour | 10 | ~14MB |
| quarter_hour | 19 | ~22MB |
| five_minutes | 50 | ~68MB |
| daily | 1 | ~0.4MB |

快照集合合计 ~105MB/天 raw（WT 压缩后 ~45-60MB/天）→ Mongo 一年 +15GB；
parquet 归档 ~10-25MB/天 → 年 4-9GB；light 单份一年后 ~3.5-4GB。

## 6. 未来选项（未排期，按需决策）

1. **周五 full 排除 `backtest_result_chunks`**（`--excludeCollection`）：该集合数据
   可由回测重现，占全库 80% 体积；排除后 full ~0.4GB。每月首个周五保留一次含
   chunks 的完整 full。
2. **push 大文件 multipart**（`upload_file` 替代 `put_object`）：当前整文件读内存，
   全量涨到数 GB 后需要。
3. **light 改当日增量**（mongodump `--query tradingDate`）：还原 = 最近 full + 逐日
   重放，仅当 light 单份 > 2GB 且 7 天保留仍吃紧时启用。
4. **Mongo 快照清理**：继续暂缓。前置条件 = R2 归档回读 API 落地，否则 frames API
   历史窗口会静默变短（数据链路红线）。归档链已就位，清理决策可独立推进。

## 7. 运维 runbook

```powershell
cd quant-board
# 手动全量备份 + 校验（恢复演练也用它产出基线）
.\.venv\Scripts\python.exe -m backend.cli backup-mongodb --full
.\.venv\Scripts\python.exe -m backend.cli verify-mongodb-backup --backup-id <id>
# 恢复（只允许 staging 库名，防误覆盖正式库）
.\.venv\Scripts\python.exe -m backend.cli restore-mongodb-backup --backup-id <id> --drop
# 快照历史回填 R2（幂等）
.\.venv\Scripts\python.exe -m backend.cli snapshot-archive-backfill --snapshot-type half_hour --start-date 2026-04-15 --end-date 2026-09-24
# 盘后链手动触发（与计划任务同一入口；结果自动落盘 after_market.log）
.\.venv\Scripts\python.exe -m backend.cli after-market-once
# 计划任务重注册（幂等；如任务 ACL 拒绝需提权运行）
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register_after_market_task.ps1
```

## 8. 变更记录

| 日期 | 变更 |
| --- | --- |
| 2026-09-16 | 备份并入 After Market 盘后链，独立 LightBackup/FullBackup 任务清理；mongodump v2（bson.gz）；旧研究 run chunks 首轮清理 |
| 2026-09-28 | snapshotArchiveR2 四类型日归档链上线（80ba814e）；任务 15:30→18:00；本地保留 30→7 天；R2 全量 keep 4→13（≈90 天）；断档自愈；盘后链结果落盘；backtest_result_chunks 11.4GB 审计清理（见同目录审计文档） |
