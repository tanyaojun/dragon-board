# five_minutes / quarter_hour 重新入采决策（2026-09-28）

## 背景

自 2026-08 起生产只采集 `half_hour` + `daily`（`.env.local` 的
`QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES=half_hour,daily`）。`quarter_hour` 与
`five_minutes` 仍有研究价值，重新入采。

## 决策

1. **四类型全量入采**：`QUANT_BOARD_SNAPSHOT_COLLECTOR_TYPES=five_minutes,quarter_hour,half_hour,daily`。
   `five_minutes` 槽位表：09:30-11:30 + 13:00-15:00 每 5 分钟共 50 槽（`slots.py` 为唯一口径来源）。
2. **题材行频率解耦**（`SECTOR_SNAPSHOT_TYPES = {half_hour, hourly, daily}`）：
   题材热度半小时一档已够研究用；`five_minutes` / `quarter_hour` 帧不携带题材行
   （sector rows 与 snapshot_context 的 `hotThemes/themeHeatFactors/rotationAnalysis`
   一并剥离），帧 `qualityFlags` 落 `sector_rows_skipped_sector_cadence`（口径决策，
   非采集失败）。纯高频槽位唤醒整组跳过 theme heat 计算，题材上游开销维持每天 11 次。
3. **重叠槽位（09:30/10:00/... 同刻多类型）不去重删除**：调度器同刻合并为一次
   provider 采集（`arun_once_multi`），上游零重复；各类型序列独立完整
   （`dataset_id + snapshot_type` 是研究/回测口径，删重叠点破坏序列连续性）。

## 已知粒度边界（5 分钟频率核查结论）

- 全市场行情缓存（腾讯源 akshare 全市场拉取）300s 周期刷新：相邻 five_minutes 帧
  的行情字段最多滞后 ~5 分钟，可能与上一帧相同；L1 五档/depth 走 bridge 实时源不受影响。
- 八平台热榜：60s TTL 按需拉取，5 分钟节拍下每槽均为新鲜数据（≤60s）。
- 涨停池 30s TTL、指数 10s TTL：每槽实时直连。
- 实测单槽耗时（2026-09 最近一周 run 记录）：中位 ~45s，p90 ~170s，max ~205s < 300s 节拍；
  题材 heat 剥离后高频唤醒进一步缩短。
- 落库增量：+69 帧/天（five_minutes 50 + quarter_hour 19）≈ +1.7 万行/天。

## 生效步骤

重启 8001 采集进程（launcher 里重启 collector）即按新类型表调度；建议在 16:00 后或
次日 09:00 前重启。若当日盘中重启，catch-up 只补当日 ≥15:00 的收盘定格槽（不失真）。

## 待决策（未做）

- ~~归档/保留策略~~ **已决策（2026-09-28 第二轮）**：四类型全部归档进 R2。
  mongodb 后端下 SQLite 版 archive auto 从不启动（runner 只在非 mongodb 分支 start，
  API 410），仅改 `QUANT_BOARD_ARCHIVE_AUTO_SNAPSHOT_TYPES` 是静默空转；因此新增
  mongodb 生产路径：盘后链新增 `snapshotArchiveR2` 步骤（`run_mongodb_snapshot_archive_once`，
  每类型归档最近**已收盘**交易日 T-1，manifest 幂等去重），
  `ArchiveService.backup_mongodb_snapshot_day_to_object` 读 Mongo 四表 → parquet → R2。
  **只归档不删 Mongo**（frames API 无归档回读，删热数据会让历史窗口静默变短；
  清理待归档回读链路就绪后单独决策）。历史回填：
  `python -m backend.cli snapshot-archive-backfill --dataset-id dragonboard_live --snapshot-type five_minutes --start-date ... --end-date ...`（逐日幂等，可重跑）。
- ~~根前端类型选择器~~ **已加（2026-09-28 第二轮）**：`RankTrendSnapshotType` 纳入
  `five_minutes`（标签「五分快照」），槽位表同步；默认 coverage 门禁保持四类型
  （`RANK_TREND_DEFAULT_COVERAGE_TYPES`，防止历史日期被整体过滤），浏览器
  本地定时保存不含 five_minutes（仅后端采集）。

## 验证

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_snapshot_collector_slots.py tests/test_snapshot_collector_sector_cadence.py tests/test_snapshot_collector_service.py tests/test_snapshot_collector_scheduler.py -q
```
