# 量比计算优化任务计划

## 目标

修复量比字段与实时成交量不同步导致的异常展示和下游污染问题，同时保持 `DataLayer` 的窄职责：只存储和投影数据，不承载量比业务算法。

## 成功标准

1. 量比计算业务逻辑集中在 `src/services/dataLoader/**`，不进入 `DataLayer.ts`。
2. 启动合并、定时行情刷新、实时 TDX 行情更新后，量比能由统一服务计算或标记为不可用/待重算。
3. `99.99` 这类上限值不再被静默当作可信真实量比；异常结果需要可诊断的状态和原因。
4. 下游保持兼容：现有 `stock.volumeRatio` 仍可读，新增元信息用于判断可信度。
5. 相关 Vitest 测试覆盖量比结构化计算和实时更新后的 stale/重算链路。

## 当前链路

```text
平台热榜 -> DataLoaderFacade.mergeData()
行情数据 -> QuoteService / QuoteHttpFeed / RealtimeQuoteCoordinator
历史成交量 -> VolumeHistoryService -> snapshotFacade -> QuantBoard 后端
量比计算 -> VolumeRatioCalculator
写回 -> StockMergeCoordinator / DataLoaderFacade.updateVolumeRatios
存储 -> DataLayer.setMergedStocks / updateStockExtData
展示和消费 -> DataTable / RankTrend / 题材 / 候选池 / 预警
```

## 关键决策

- 不把量比计算迁入 `DataLayer`。
- 保留 `VolumeRatioCalculator` 作为纯计算模块。
- 新增统一的量比更新服务，负责拉历史、计算、写回和诊断元信息。
- `DataLayer.applyRealtimeQuoteBatch` 更新成交量时，不直接计算量比；量比 stale 或重算由 dataLoader 层处理。
- 先保持 `volumeRatio?: number` 兼容旧消费者，再逐步引入 `volumeRatioMeta`。

## 阶段

### 阶段 1：结构化计算结果

状态：complete

任务：

- 扩展量比类型，新增状态、来源、计算元信息。
- 在 `VolumeRatioCalculator` 新增结构化 API。
- 保留旧 `calculateVolumeRatioValue` 兼容现有调用。

验证：

- `VolumeRatioCalculator.test.ts` 覆盖 fresh、unavailable、capped/suspicious。

### 阶段 2：统一更新服务

状态：complete

任务：

- 新增 `VolumeRatioUpdateService`。
- 从 `DataLoaderFacade.updateVolumeRatios` 抽出历史读取、计算、写回职责。
- `StockMergeCoordinator` 不再直接负责量比计算，避免合并职责过重。

验证：

- `DataLoaderFacade.test.ts` 覆盖量比服务写回。

### 阶段 3：实时行情 stale/重算链路

状态：complete

任务：

- 实时 flush 后让 dataLoader 层接收 changed codes。
- 非交易时段也允许量比重算或标记 stale。
- 避免 `volume` 更新后旧 `volumeRatio` 长期保持可信状态。

验证：

- 测试模拟旧量比 + 实时成交量更新，最终 `volumeRatioMeta.status` 不应继续为 `fresh`。

### 阶段 4：缓存和展示保护

状态：complete

任务：

- 启动缓存 hydrate 后量比标记 stale，或写缓存时剔除量比元信息。
- `DataTable` 对 stale/suspicious/unavailable 做展示区分。

验证：

- 启动缓存测试覆盖旧量比不会被视为 fresh。

本轮完成：

- `DataTable` 已区分 stale/suspicious/unavailable。
- `StartupBundleService.read()` 会将缓存恢复出的旧 `volumeRatioMeta` 降级为 `stale`。
- 旧版本缓存只有裸 `volumeRatio` 时，会补充 `volumeRatioMeta.status = stale`，避免被 UI 和下游误判为可信实时量比。

### 阶段 5：下游可信量比 helper

状态：complete

任务：

- 新增 `getTrustedVolumeRatio`。
- RankTrend 主计算、状态分层、市场环境统计、个股预警、题材因子和题材关联度改用可信 helper。
- `StockMergeCoordinator` 不再直接计算裸量比，合并后的结构化量比统一由 `VolumeRatioUpdateService` 补齐。

验证：

- 关键下游测试补充 suspicious/stale 不参与强信号评分。

## 最小执行范围

本轮已完成阶段 1 到阶段 5 的最小闭环。剩余未改的 `JXBK` 板块量比属于外部板块源字段，不纳入本次个股量比计算链。

## 验证命令

```powershell
pnpm test -- src/services/dataLoader/__tests__/VolumeRatioCalculator.test.ts
pnpm test -- src/services/dataLoader/__tests__/DataLoaderFacade.test.ts
pnpm test -- src/services/dataLoader/__tests__/StartupBundleService.test.ts
pnpm test -- src/services/dataLoader/__tests__/VolumeRatioTrust.test.ts
pnpm test -- src/services/dataLoader/__tests__/StockMergeCoordinator.test.ts
pnpm test -- src/services/__tests__/RankTrendAnalyzer.test.ts
pnpm test -- src/services/rankTrend/__tests__/statusClassifier.test.ts
pnpm test -- src/services/rankTrend/__tests__/marketRegimeAnalyzer.test.ts
pnpm test -- src/services/__tests__/alertService.test.ts
pnpm test -- src/services/theme/__tests__/ThemeFactorEngine.test.ts
pnpm test -- src/services/theme/__tests__/ThemeCorrelationEngine.test.ts
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```
