# 题材模块重构发现记录

## 代码现状

- `ThemeDataService.ts` 同时承担静态映射、标签原因、缓存、API 更新和 DataLayer 同步。
- `sectorAnalyzer.ts` 同时承担 JXBK 拉取、热度计算、题材同步到个股、标签原因同步、板块预警和查询 facade。
- `rotationService.ts` 依赖 JXBK 和 `localStorage` 推导轮动/主线，主要服务展示和 DragonReview 战场种子。
- `ThemeCorrelationAnalyzer.ts` 有联动和龙头识别能力，但是 `@ts-nocheck`，且没有并入统一题材因子。
- `alertService.ts` 自己扫描 JXBK 状态生成板块/个股预警，与题材分析职责重叠。

## 子任务结论：快照与 QuantBoard

- 前端题材快照字段当前通过 `SnapshotSectorRow.metadata` 有扩展空间。
- 个股题材当前保存 `themes/mainTheme/themeHeat/themeLevel`。
- QuantBoard SQLite 当前把 `themes` 存为 `themes_json`，主字段存为 `main_theme/theme_heat/theme_level`。
- 最小兼容方案：题材因子先放 `sectorRows.metadata.themeFactor`，个股暴露先扩展 `themes[]` 元素；暂不新增数据库列。

## 子任务结论：热度与 DragonReview

- 最小接入应投影到现有 `HotTheme` 和 `stock.themes`，不要第一阶段直接改 DragonReview 判断引擎。
- `dataLoader` 会多处从 `dataLayer.getStockThemes()` 回写 `mainTheme/themeHeat`，新投影必须先写入 DataLayer，否则会被旧逻辑覆盖。
- 当前 `StockHotnessCalculator` 没有使用 `themeHeat`，题材贡献纳入热度需要显式加权和测试。

## 设计约束

- 保持 UI 字段兼容。
- 新类型优先作为策略解释和中观因子，不直接替代 RankTrend 或最终交易信号。
- 不批量删除文件。
- 保护现有工作区状态。

## V4 残留调用清单

- `SectorPanel`：展示读取和刷新触发仍直接依赖 `dataLayer.getJxbkBlocksSorted/state.theme.jxbk.lastUpdate` 与 `sectorAnalyzer.forceRefreshJxbk/triggerHeatCalculation`。
- `SectorDetail`：详情展示和成分股加载仍直接读取 `state.theme.jxbk.blocks/stockMap`，刷新触发仍依赖 `sectorAnalyzer`。
- `SectorStocksTree`：树形成分股展示仍直接读取 `state.theme.jxbk.stockMap`，加载仍依赖 `sectorAnalyzer.loadSectorStocks`。
- `SectorRotation`：轮动展示和手动刷新仍以 `rotationService.forceAnalyze()` 为主路径。
- `ExportPanel/exportService`：热门题材导出仍通过 `sectorAnalyzer.getHotThemes()`。
- `ThemeCorrelationPanel/ThemeRiskDashboard`：联动和风险展示仍直接拼 `jxbkBlocks/stockMap`。
- `sectorAnalyzer.ts`：仍包含旧 JXBK 拉取、旧热度计算、旧 hot theme 生成、旧 stock theme fallback；V4 应标记为 deprecated fallback 并逐步委托 `themeFacade/JxbkThemeFeed`。
- `rotationService.ts`：旧手动轮动计算仍作为 fallback 保留；权威来源应固定为 `ThemeRotationEngine`。
- `alertService.ts`：`ThemeEvent` 和 legacy `checkBlocks()` 并行，需避免同一题材同帧重复预警。
- `dataLoader.ts`：仍通过 `sectorAnalyzer.triggerHeatCalculation/syncThemesToStocks` 触发题材同步，属于兼容触发路径。
- `dragon/*`：`BattlefieldBuilder` 已迁移到 `themeFacade`，`ContextBuilder` 仍通过 `sectorAnalyzer.getThemeDetail` 做兼容详情读取。

## V5 剩余旧服务入口

- `dataLoader`：已改为调用 `themeFacade.refreshRuntime({ source: 'dataLoader', syncStocks: true })`，不再直接触发 `sectorAnalyzer.triggerHeatCalculation/syncThemesToStocks`。
- `AlgorithmManager/ConsistencyManager`：已通过 `ThemeSyncAdapter` 注册题材同步修复服务，不再从 `window.sectorAnalyzer` 取同步能力。
- `RefreshCoordinator`：已新增 `themeRuntime` 节点，DragonBreath、DragonReview、Algorithm 依赖改为 `themeRuntime`；`sectorAnalyzer` 作为兼容节点继续保留。
- `alertService.checkBlocks()`：已保留方法名，但 legacy block alert 生成改为 `ThemeLegacyAlertAdapter` 输出标准 `ThemeEvent`，`alertService` 只做冷却、去重、保存和状态写入。
- `ThemeCorrelationAnalyzer`：已改为 `themeFacade.getThemeStockMapCompat()`。
- 剩余兼容边界：
  - `sectorAnalyzer.ts` 文件仍保留旧公开 API 和 fallback 逻辑，供控制台、旧面板和旧调试脚本兼容。
  - `alertService.checkStocks()` 仍读取 JXBK 成分股数据，但通过 `themeFacade.getThemeStockMapCompat()`，不再直接访问 DataLayer 私有 state。

## V6 审计遗留处理记录

- `ThemeFacade` 两条刷新路径：改为由 `refreshRuntimeState()` 包装 `ThemeRuntimeCoordinator.refreshRuntime()`，`refresh()/refreshThemeFacadeState()` 只保留兼容包装语义。
- `alertService` 并行题材事件链：`checkThemeEvents()` 消费 runtime result，legacy block event 由 coordinator 生成；`checkBlocks()` 仅维护板块快照，避免同帧二次生成板块事件。
- `ThemeSyncAdapter` 重复方法：`syncThemesToStocks()` 委托 `syncData()`，保留调用方命名兼容。
- `sectorAnalyzer` 旧同步路径：`syncThemesToStocks()/forceRefresh/forceRefreshJxbk/syncData` 主路径委托 `themeFacade.refreshRuntime()`。
- 仍保留的 legacy 边界：`sectorAnalyzer` 中旧 JXBK 拉取、成分股懒加载和旧热度 fallback 尚未删除，等待用户 review 后再决定是否进入 V7 清理。
