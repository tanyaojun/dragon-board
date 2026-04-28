# 快照存储说明

## 当前结构
快照模块当前采用一套“原始事实表 + 正式读模型表”的结构：

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
- `snapshot` 基础层允许扩展 `five_minute` 这类非正式 `rankTrend` 类型，但扩展类型必须建立在统一入口之上，例如：
  - `type SnapshotType = RankTrendSnapshotType | 'five_minute'`

一句话：

**正式快照类型只能引用统一入口，不允许私自定义同口径类型。**

## 当前正式读取接口
正式业务读取优先使用以下接口：

- [DataLayer.listSnapshotFrameBundles](/D:/dragon-board/src/services/DataLayer.ts)
- [DataLayer.listSnapshotFrames](/D:/dragon-board/src/services/DataLayer.ts)
- [DataLayer.listSnapshotStockRows](/D:/dragon-board/src/services/DataLayer.ts)
- [DataLayer.listSnapshotSectorRows](/D:/dragon-board/src/services/DataLayer.ts)
- [DataLayer.getStockVolumeHistory](/D:/dragon-board/src/services/DataLayer.ts)

`listSnapshots()` 仍保留，但定位是原始事实表读取，只用于：

- 导出
- 诊断
- coverage 检查
- 维护/重建
- 少量非主链工具代码

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
- 查询方式：`code + type('daily') + beforeTradingDate + sort(desc) + limit`
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

## 测试
快照模块核心回归位于：

- [backupSyncState.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/backupSyncState.test.ts)
- [builders.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/builders.test.ts)
- [projectionBundle.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/projectionBundle.test.ts)
- [runtime.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/runtime.test.ts)
- [snapshotQualityGate.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/snapshotQualityGate.test.ts)
- [store.test.ts](/D:/dragon-board/src/services/snapshot/__tests__/store.test.ts)
