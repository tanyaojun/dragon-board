# 量比计算优化发现记录

## 已确认事实

- `QuoteService.ts` 不计算量比，只提供当前行情字段，例如 `volume`、`turnover`、`turnoverRate`。
- 量比当前由 `VolumeRatioCalculator.ts` 计算，`calculateRawVolumeRatio` 会把结果限制在 `0.01` 到 `99.99`。
- `VolumeHistoryService.ts` 优先读取正式分时快照，分时历史不足时由计算器退回日级历史。
- `DataLayer.ts` 不包含量比公式，但 `applyRealtimeQuoteBatch` 会更新 `stock.volume`，不会同步处理 `stock.volumeRatio`。
- `DataLoaderFacade.runQuoteRefresh` 在非交易时段直接返回；截图发生在收盘后，实时 TDX 链路仍可能更新成交量。
- `DataTable.vue` 直接格式化 `stock.volumeRatio`，没有 stale 或 suspicious 状态判断。
- 启动缓存 bundle 会保存并恢复 `stocks`，历史缓存中的 `volumeRatio` / `volumeRatioMeta` 不能继续视为实时可信字段。

## 异常原因判断

截图中的 `99.99` 是应用内上限，不是行情源真实值。按当前 TDX 成交量和最近历史快照复算，截图股票的量比多数应在 `0.6` 到 `1.1` 附近。因此主要问题是字段生命周期不同步：

```text
旧 volumeRatio 保留
实时 TDX 更新 volume
非交易时段 quote refresh 跳过
volumeRatio 未重算
UI 显示新 volume + 旧 volumeRatio
```

## 风险面

- RankTrend、候选池、题材热度、预警等模块直接消费 `stock.volumeRatio`。
- 只在 UI 层隐藏异常不能解决策略污染。
- 将量比计算放进 `DataLayer` 会违反项目边界，并扩大 `DataLayer` 职责。
- 合并器如果直接计算裸量比，会绕过结构化诊断状态，导致后续服务难以判断量比是否可信。

## 推荐方向

新增统一量比更新服务，保持：

```text
VolumeRatioCalculator: 纯计算
VolumeHistoryService: 历史读取
VolumeRatioUpdateService: 业务编排和写回
DataLayer: 存储最终字段
```

下游消费统一通过 `getTrustedVolumeRatio` 读取个股量比；外部板块源字段，例如 JXBK 板块量比，仍按源数据处理，不混入本次个股量比可信状态。
