# 同花顺涨停池集成源码发现

## 现有 `LimitUpUpdate` 数据源

`LimitUpUpdate` 当前主要来自 `src/services/dataLoader/LimitUpFeed.ts`：

- `loadLimitUpData()` 调用 `apiService.getLimitUp()`。
- `apiService.getLimitUp()` 请求 `/api/limitup/10jqka`。
- `/api/limitup/10jqka` 在 `proxy-server/routes/market.js` 中代理同花顺 `dataapi/limit_up/limit_up_pool`。
- `mapLimitUpItems()` 把上游 `data.info` 映射为 `LimitUpUpdate`。

当前字段映射：

| 上游字段 | Dragon Board 字段 |
| --- | --- |
| `code` | `code` |
| `reason_type` | `reason` |
| `is_new` | `isNew` |
| `first_limit_up_time` | `firstZtTime` |
| `last_limit_up_time` | `lastZtTime` |
| `continue_day` | `boardHeight` |
| `high_days` | `highDays` |

## `/api/limitup/10jqka` 实测结果

测试环境：

- 本地代理：`http://127.0.0.1:3000`
- 测试时间：2026-05-18 盘前

默认请求：

- `GET /api/limitup/10jqka`
- 返回 `data.info: []`
- 返回 `data.msg: 尚未开盘 / 可切换日期查看历史数据`
- 返回 `data.limit_up_count.yesterday.num: 54`

因此，在盘前默认日期下，这个接口确实只提供汇总和交易状态，不会落到具体股票。

显式历史日期请求：

- `GET /api/limitup/10jqka?date=20260515`
- 返回 `data.info` 共 54 条具体股票明细。
- `data.page.total` 为 54。

样例行字段：

```json
{
  "code": "600386",
  "name": "北巴传媒",
  "change_rate": 10.101,
  "reason_type": "广告传媒+汽车服务+北京国资",
  "first_limit_up_time": "1778810904",
  "last_limit_up_time": "1778828133",
  "high_days": "首板",
  "order_amount": 2492276.3,
  "order_volume": 571623,
  "turnover_rate": 6.366,
  "latest": 4.36
}
```

结论：

- `/api/limitup/10jqka` 不是只有涨停总数，它能返回具体股票明细。
- 但今天盘前默认日期会返回空 `info`，只有昨日涨跌停汇总。
- 当前 `LimitUpFeed` 只处理 `data.info`，所以盘前不会写入任何个股涨停字段。
- 上游时间字段当前是秒级时间戳字符串，不是 `HH:mm:ss`，后续映射需要格式化。
- 实测 20260515 的 `high_days` 全部为字符串，例如 `首板`、`5天3板`、`6天6板`；`continue_day` 全部为 `null`。现有 `LimitUpItem.high_days: number` 类型与真实响应不一致，连板高度应从 `high_days` 文本或 `high_days_value` 解析。
- `high_days_value` 是编码值，不是普通连板数。实测 `196613` 对应 `5天3板`，解析方式为 `板数 = floor(high_days_value / 65536)`，`天数 = high_days_value % 65536`。
- 示例 `first_limit_up_time: "1778810904"` 对应北京时间 `2026-05-15 10:08:24`。

## 旁路写入源

除 `LimitUpFeed` 外，还有两个模块会通过 `dataLayer.updateLimitUpData()` 写入涨停相关扩展：

- `src/services/ThemeDataService.ts`：同步题材标签和题材原因，只写 `reason/tags`。
- `src/services/sectorAnalyzer.ts`：初始化题材标签和原因，只写 `reason/tags`。

这两个来源更像“题材解释/原因补充”，不是同花顺涨停池本体。

## 运行态写入链路

`dataLayer.updateLimitUpData()` 会：

- 把 `reason` 写入 `stockReasons`。
- 把 `isNew` 写入 `stockIsNew`。
- 把 `tags` 写入 `stockTags`。
- 把其余字段合并进 `limitUpData: Map<string, LimitUpExtData>`。

`ExtraDataProjector` 会把 DataLayer 中的涨停扩展投影回合并股票：

- `firstZtTime`
- `lastZtTime`
- `boardHeight`
- `highDays`
- `fengdan`
- `maxFengdan`
- `leadStatus`
- `leadTimes`
- `lianbanStr`
- `reason`
- `tags`
- `isNew`

因此，当前 `LimitUpUpdate` 字段在运行态热榜股票中是可见的。

## 是否进入快照

结论：部分进入，`reason` 当前未进入正式快照字段。

已进入快照 raw payload / stock rows 的字段：

- `firstZtTime`
- `lastZtTime`
- `boardHeight`
- `highDays`
- `fengdan`
- `maxFengdan`
- `leadStatus`
- `leadTimes`
- `lianbanStr`
- `isNew`

未进入或被剔除的字段：

- `reason`：`buildDailySnapshot` 的测试明确断言 `snapshot.hotlist[0]` 不包含 `reason`。
- `tags`：同样被 daily compact 剔除。
- `SnapshotStockRow` 类型当前没有 `reason` 字段。
- `buildSnapshotStockRows()` 当前没有写入 `reason`。
- `compactHotlistItem()` 当前没有保留 `reason`。

影响：

- 运行态 UI 可以显示涨停原因。
- 快照导出函数存在“涨停原因”列，但 raw snapshot 中没有 `stock.reason` 时会导出空值。
- 后续 QuantBoard 或复盘若依赖 snapshot stock rows，将拿不到涨停原因。

## THS HTML 可迁移信息

`d:\TDX外挂\THS连板\THS连板.html` 的可用逻辑是接口和字段，不是 DOM 表格。

可迁移接口：

- `get_limit_up_stocks`：首板、二板、三板、四板、高标。
- `open_limit_pool`：炸板。
- `limit_up`：冲板。
- `get_drawdown_stocks`：涨停股最大回撤。

可迁移字段：

- `stock_code`
- `stock_name`
- `change`
- `volume_money`
- `limit_up_time`
- `limit_up_reason`
- `continue_day`
- `max_drawdown`
- `rise_rate`
- `turnover`
- `turnover_rate`
- `currency_value`

不可直接迁移：

- 直接 DOM 拼接表格。
- `window.location.href = http://www.treeid/code_xxx`。
- 硬编码节假日。
- 2 秒全量刷新策略。
- 页面拖拽和主题逻辑。

## 待确认点

- 同花顺 `volume_money` 在 `get_limit_up_stocks` 中是否始终代表封单额，需用真实响应样本确认。
- `limit_up_time` 与现有 `first_limit_up_time` 语义是否完全一致，建议保留为 `limitUpTime` 并同步写 `firstZtTime`。
- `get_drawdown_stocks` 的“大面”应标注为“涨停股回撤”，不能替代全市场亏钱效应。

## 2026-05-18 盘中 MongoDB 落库审计

审计时间：2026-05-18 14:23-14:30。

环境：

- `QUANT_BOARD_STORAGE_BACKEND=mongodb`
- `QUANT_BOARD_MONGODB_URI=mongodb://127.0.0.1:27017`
- `QUANT_BOARD_MONGODB_DATABASE=dragon_board_quant`
- 数据集：`dragonboard_live`
- 交易日：`2026-05-18`

MongoDB 当前数据：

- `snapshot_frames` 今日 24 条。
- `snapshot_stock_rows` 今日 5136 条。
- 最新快照到 `14:00`，包含 `half_hour/hourly/quarter_hour`。

THS 代理实时响应：

- `GET /api/limitup/ths/pools?date=20260518` 返回 `ok=true`、`degraded=false`、`errors=[]`。
- 分池计数：首板 65、二板 5、三板 1、四板 2、高标 1、炸板 37、冲板 20、涨停股回撤 6。
- 结论：盘中 THS 上游和本地代理当前有真实数据，不是上游无数据。

MongoDB 落库结果：

- 今日没有任何 `limitSummary.thsPools` 对象落库。
- `limitSummary.thsPools` 为 `null` 的快照 24 条，其中最新 `13:45`、`14:00` 已有 `limitSummary.thsPools: null`。
- `limitSummary.thsPools` 字段缺失的快照 20 条，主要是阶段 6 代码落地前生成的早盘快照。
- 今日个股级涨停字段曾成功落库：
  - `13:15`：`firstZtTime` 33 条、`boardHeight > 0` 33 条。
  - `13:30`：`firstZtTime` 39 条、`boardHeight > 0` 38 条。
- 但 `13:45`、`14:00` 个股级 `firstZtTime/boardHeight/highDays` 又变为 0 条，只剩 `reason` 大量存在。

疑似原因：

- `DragonBreathAnalyzer` 产出的 `breathData.marketData` 已包含 `thsLimitUpPools`。
- `snapshotFacade` 构建快照时读取的是 `dataLayer.getBreathMarketData()`。
- `DataLayer.updateBreathData()` 当前重建 `state.analysis.breath.marketData` 时没有拷贝 `data.marketData.thsLimitUpPools`，导致快照构建看到的是 `null`。
- 因此 THS 市场池摘要未进入 MongoDB 的直接疑点在 DataLayer 白名单丢字段，而不是 THS 代理失败。

额外现象：

- `13:45` 和 `14:00` 个股级涨停时间、连板高度断档，说明运行态股票增强字段在这些快照槽位也不稳定。
- 这需要进一步区分是 `LimitUpFeed.loadEnhancedLimitUpPools()` 调用时序、THS 增强只写部分股票、还是快照保存时拿到的股票列表被后续数据源覆盖。
