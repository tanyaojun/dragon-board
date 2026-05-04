# 快照存储说明

## 当前结构
正式快照事实库当前由 QuantBoard SQLite 承接，Dragon Board 前端通过
[backendRead.ts](/D:/dragon-board/src/services/snapshot/backendRead.ts) 读取后端 API。
浏览器 IndexedDB 中同名结构只保留为历史迁移、显式缓存、本地维护和 `five_minute`
历史兼容数据，不再作为正式分析事实源；`five_minute` 运行路径当前不再对外保留。

SQLite 快照模块采用一套“原始事实表 + 正式读模型表”的结构：

- `snapshots`
  - 原始快照事实表。
  - 保留 `type / tradingDate / slotTime / timestamp / displayKey / captureMode / source / qualityFlags / payload`。
  - `payload` 已做瘦身，不再持久化旧版镜像字段和冗余大数组。
- `snapshot_frames`
  - 一条正式快照对应一条 frame。
  - 保存帧级摘要：`marketStats / sentiment / moneyFlow / indices / limitSummary / rotationSummary`。
- `snapshot_stock_rows`
  - 一条快照中的一只股票一行。
  - 用于量比、排名趋势、复盘等正式查询。
- `snapshot_sector_rows`
  - 一条快照中的一个板块/题材/主线实体一行。
- `snapshot_projection_meta`
  - 保存投影回填状态和维护水位。
- `archive_manifests`
  - QuantBoard 后端维护的 Parquet 归档索引。
  - 当历史 `snapshot_stock_rows / snapshot_sector_rows` 被归档后，后端可通过 DuckDB 从 Parquet 读取冷数据。

当前长期增长控制口径：

- SQLite 保留近期热数据和 frame/record 元数据。
- 历史股票/板块明细可归档到 `quant-board/data/archive/snapshots/**` 的 Parquet 文件。
- R2/S3 对象存储用于备份 Parquet 和 manifest，不作为 Dragon Board 前端直连数据源。
- Dragon Board 前端仍只调用 QuantBoard API；Parquet、DuckDB、R2 都属于后端实现细节。

## 正式读取口径
正式读取统一遵循 [readPolicy.ts](/D:/dragon-board/src/services/snapshot/readPolicy.ts)：

- `allowedCaptureModes = ['real_time', 'delayed']`
- `excludeRestored = true`

`restored/manual` 只允许在恢复、诊断、人工核查路径读取，不进入正式分析主链。

## 快照类型统一入口
`rankTrend` 主链涉及的正式快照类型，已经统一收口到：

- [rankTrendDefaults.ts](/D:/dragon-board/src/type/rankTrendDefaults.ts)

统一入口负责：

- `RankTrendSnapshotType`
- `RankTrendIntradaySnapshotType`
- `DEFAULT_RANK_TREND_SNAPSHOT_TYPE`
- `RANK_TREND_SNAPSHOT_TYPES`
- `RANK_TREND_INTRADAY_SNAPSHOT_TYPES`
- `buildRankTrendSnapshotPriority()`
- `getRankTrendSnapshotLabel()`
- `getRankTrendSnapshotShortLabel()`
- `getRankTrendSnapshotHistoryLimit()`

正式约束：

- `rankTrend / snapshot / dragon / UI / replay` 凡是共用同一套正式快照类型口径的模块，统一从这个入口引类型和元数据。
- 不允许在业务文件里私自声明 `quarter_hour | half_hour | hourly | daily` 联合类型。
- 不允许在业务文件里私自维护正式快照类型数组、默认类型、中文标签、历史窗口上限。
- `snapshot` 基础层历史上允许扩展 `five_minute` 这类非正式 `rankTrend` 类型；当前不再保留对外读写入口。

一句话：

**正式快照类型只能引用统一入口，不允许私自定义同口径类型。**

## 当前正式读取接口
正式业务读取优先使用以下 facade 接口，内部统一调用 QuantBoard SQLite API：

- [snapshotFacade.listSnapshotFrameBundles](/D:/dragon-board/src/services/snapshot/facade.ts)
- [snapshotFacade.listSnapshotFrames](/D:/dragon-board/src/services/snapshot/facade.ts)
- [snapshotFacade.listSnapshotStockRows](/D:/dragon-board/src/services/snapshot/facade.ts)
- [snapshotFacade.listSnapshotSectorRows](/D:/dragon-board/src/services/snapshot/facade.ts)
- [snapshotFacade.getStockVolumeHistory](/D:/dragon-board/src/services/snapshot/facade.ts)

`snapshotFacade.listSnapshots()` 和 `getSnapshotById()` 的正式类型同样走 SQLite API；
不再保留 `five_minute` 这类非正式临时快照的浏览器本地读取入口。

`SnapshotRuntime.listSnapshots()` 仍保留，但定位是本地 IndexedDB 维护读取，只用于：

- 导出
- 诊断
- coverage 检查
- 维护/重建
- 少量非主链工具代码

QuantBoard 后端不可用时，正式读取应显式失败，不允许静默回落浏览器 IndexedDB。

`getSnapshotFromDB()` 和 `getSnapshotDates()` 已从 `DataLayer` 删除，不再作为兼容口保留。

## 当前主要消费路径
- [RankTrendAnalyzer.ts](/D:/dragon-board/src/services/RankTrendAnalyzer.ts)
  - 通过 `listSnapshotFrameBundles()` 读取正式快照样本。
- [FrameNormalizer.ts](/D:/dragon-board/src/services/dragon/FrameNormalizer.ts)
  - 通过 `listSnapshotFrameBundles()` 构建复盘 frame。
- [DragonBreathAnalyzer.ts](/D:/dragon-board/src/services/DragonBreathAnalyzer.ts)
  - 通过 `daily` frame bundle 读取昨日涨停样本。
- [dataLoader.ts](/D:/dragon-board/src/services/dataLoader.ts)
  - 量比历史通过 `getStockVolumeHistory()` 读取日级 `snapshot_stock_rows`。

## 量比口径
当前量比主链口径已经固定为：

- 来源：`daily` 类型的 `snapshot_stock_rows`
- 查询方式：QuantBoard `GET /api/snapshots/stock-rows`，参数为 `dataset_id + code + snapshot_type('daily') + before_trading_date + sort(desc) + limit`
- 返回内容：最近 4 个交易日成交量，最新在前

`dataLoader` 后续会在运行时剔除“当前成交量与最新日级快照重复”的情况，再使用前三个历史交易日做加权平均。

这条链不再允许退回“全量抓取快照后在内存排序/过滤”的旧实现。

## 原始快照瘦身规则
原始 `payload.hotlist` 保留的核心字段包括：

- `code / name / rank / compRank / platforms / avgRank / avgRankNum`
- `price / change / volume / turnover / turnoverRate / totalMV / cirMV`
- `zlje / zljzb / cddje / cddjzb`
- `pe / pb`
- `volumeRatio / speed`
- `leadStatus / leadTimes / lianbanStr / fengdan / maxFengdan`
- `popularity / popularityChange / institutionBuy / bigMoney300`
- `themes / mainTheme / themeHeat / themeLevel`
- `isNew / firstZtTime / lastZtTime / boardHeight / highDays / hotness`

已从原始快照移除的旧字段包括：

- `tags`
- `reason`
- `technicalIndicators`
- `signals`
- `rankChange`
- `fundPenetration`
- `macdCross`
- `leaders`
- `limitUpStocks`
- `hotThemes`
- `rotation.mainLines`

`signals / rankChange` 已转为 `snapshot_stock_rows` 上的轻量列。

## 维护入口
当前保留的快照维护入口：

- [SnapshotRuntime.rebuildSnapshotProjectionStores](/D:/dragon-board/src/services/snapshot/runtime.ts)
- [SnapshotRuntime.alignSnapshotBackups](/D:/dragon-board/src/services/snapshot/runtime.ts)
- [SnapshotRuntime.compactSnapshotRawRecords](/D:/dragon-board/src/services/snapshot/runtime.ts)
- [SnapshotRuntime.runSnapshotStorageMaintenance](/D:/dragon-board/src/services/snapshot/runtime.ts)

交易日 15:30 后的坚果云 JSON day bundle 自动上传已经退出正式链路。后续云端备份由 QuantBoard/Supabase outbox 承接；根前端只保留历史 remote bundle 的手工恢复和迁移兼容能力。

## 测试
快照模块核心回归位于：

- [backupSyncState.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/backupSyncState.test.ts)
- [builders.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/builders.test.ts)
- [projectionBundle.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/projectionBundle.test.ts)
- [runtime.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/runtime.test.ts)
- [snapshotQualityGate.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/snapshotQualityGate.test.ts)
- [store.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/store.test.ts)
