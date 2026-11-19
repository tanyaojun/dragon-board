# 2026-11-19 `snapshot_sector_rows` 集合退役 + ThemeTrend 策略链删除

## 裁决

用户 2026-11-19 确认执行方案 A（瘦身内嵌）：

1. MongoDB `dragon_board_quant.snapshot_sector_rows`（313,033 行，独立集合）drop；
2. sector rows 持久化链删除，改为**内嵌进 `snapshot_frames.sectorRows`**（帧文档成为
   sector 行的单一事实源）；
3. ThemeTrend 整条策略链废弃删除（引擎/回测/优化/研究/CLI/API/QB 前端页签）；
4. 根前端 SectorDetail 题材历史趋势页签随数据源退役一并废弃；
5. RankTrend 主链题材维度（hotThemes 投影、题材动量 v2、`/api/theme-momentum/*`、
   `/api/theme-rotation/*`、`/api/snapshots/sector-rows` 读口）**保留**，数据源改吃帧内嵌。

## 归档（drop 前，§1.2.4 硬规则）

- `data/backups/snapshot_sector_rows_20261119/`
  - `mongodump/dragon_board_quant/snapshot_sector_rows.bson`（373MB，可 mongorestore）
  - `snapshot_sector_rows.json.gz`（29MB，mongoexport JSON 参考）
- `data/backups/theme_daily_factors_20261119/mongodump/`（29,469 行）

## drop 的集合

- `snapshot_sector_rows`（313,033 行，含 7 个二级索引）
- `theme_factor_frames` / `theme_signals` / `theme_stock_exposures` / `theme_quality_reports`（均 0 行）
- `theme_daily_factors`（29,469 行，归档后 drop；ThemeDailyFactorsScheduler 与
  daily_factors_service 属 ThemeTrend 持续性因子链，随之删除）

## 帧内嵌 schema（2026-11-19 冻结，`SECTOR_ROW_EMBED_FIELDS`）

- 帧级上下文字段（datasetId/snapshotId/tradingDate/slotTime/timestamp/type/captureMode/source）
  不逐行重复存储，读取时由 `MongoRepository` 从帧回注；
- `metadata` 只保留口径与来源标记：`factorVersion` / `mappingVersion` / `quoteSource` / `fundSource`
  （资金流溯源红线要求来源可追溯）；
- ThemeTrend 因子链专用冗余字段（完整 metadata 诊断、rowId、id 等）不再落库。

## 代码删除清单（要点）

- `backend/analysis/theme/trend.py`、`services/theme_research_service.py`、
  `services/theme/daily_factors_service.py`、`services/theme/daily_factors_scheduler.py`、
  `data/repositories/theme_daily_factor_repository.py`
- `core/backtest/strategy.py` THEME_STRATEGY_DEFINITIONS、`execution.py` theme 入场分支、
  `backtest_service.py` run_theme_trend / run_theme_confluence / _theme_execution_signals /
  _confluence_execution_signals / _theme_sg_inputs / SG helpers
- `optimization_service.run_theme_trend/run_theme_confluence`、`objective.score_theme_trend`、
  `search_space` theme 组、`main.py` 六条 theme 路由与 helpers、`cli.py` 四个 theme 命令
- `operations/diagnose_theme_*` 等 7 个题材研究诊断脚本
- 读口重写：`MongoRepository.list_snapshot_sector_rows` / `_sector_rows_by_snapshot` /
  `save_snapshot_ingest`（内嵌写）、`snapshot_query_service`、`heat_service`、
  collector service_factory 审计、migrations/repair/bar_repair/backup/archive 清单
- 根前端：SectorDetail 历史趋势页签 + `themeHistorySeries.ts` 及其测试
- QB 前端：ThemeTrend 页签/表单/handlers/api/types、题材策略选项

## 验证

- 后端 pytest 全量：5354 passed / 7 skipped
- 根前端 `pnpm test`：1169 passed；`vue-tsc` 无错误
- QB 前端 `vue-tsc` + `npm run build`：通过

## 同日追加：`backtest_signals` 历史明细清理（方案 A，用户裁决）

- 2026-11-19 追加裁决：`backtest_signals` 全量历史明细清理（9,539,568 行，66 个 run，
  最后写入 2026-10-10，磁盘 ~1.73GB）。结论性数据（metrics/trades/equity）在
  `backtest_runs.resultCompressed`，明细可按同参数重跑再生成；golden/journal/optimization
  均无结构依赖。
- 归档：`data/backups/backtest_signals_20261119/dragon_board_quant/backtest_signals.bson.gz`
  （mongodump --gzip，516MB）。
- 操作：`delete_many({})` + `compact`，集合与 6 个索引骨架保留，未来回测照常落库；
  旧 run 的 signals 读口返回结构化空（total=0）。
- 效果：库总体磁盘 4.85GB → **3.62GB**。

## 同日追加二：`snapshot_analysis` 历史清理（1+2 组合，用户裁决）

- 2026-11-19 追加裁决：snapshot_analysis（866,917 行 / 存储 1.6GB / 逻辑 6.3GB）中清理：
  ① 2026-04~08 的 half_hour + daily（218,775 行）；② quarter_hour 全部（143,664 行）。
  共删 362,439 行；保留 five_minutes 全部 + 2026-09~11 的 half_hour/daily（504,478 行）。
- 可恢复性：analysis 是 frames + stock_rows 的纯派生数据，`snapshot-analysis-backfill`
  CLI 可按帧重算；消费面（首屏六列注入 / hotlist displayStatus join / jev 当槽证据链 /
  按需读口）全部只打当前或指定日期读口，无历史窗口依赖。
- 归档：`data/backups/snapshot_analysis_20261119/old_apr_aug/`（162MB）与
  `.../quarter_hour/`（114MB），mongodump --gzip 可 mongorestore。
- 效果：snapshot_analysis 存储 1.6GB → **1.04GB**；库总体磁盘 3.62GB → **3.07GB**。
- 长期待办（另行立项）：存储 schema 瘦身（12 个 analysis 子对象 → 消费面白名单），
  否则仍按 ~7.6KB/行 增长。

## 运维注意

`:8001` snapshot_collector 进程若未重启，仍以旧代码运行；下次交易时段写入会重建
`snapshot_sector_rows`。**必须重启 collector 使其加载帧内嵌写路径**；若发现集合被旧进程
重建，重启后再次单集合 drop 即可（数据会经由帧内嵌链正常落库，不丢失）。
