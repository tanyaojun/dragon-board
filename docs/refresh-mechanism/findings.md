# Unified Refresh Mechanism Findings

## Requirements

- 用户要求基于 `RefreshCoordinator.ts`、`RefreshManager.ts` 和项目整体刷新机制做全面梳理。
- 当前阶段要求把分阶段优化实施计划落入文档，不改源码。
- 项目协作规则要求过程文档不要放在根目录；本专题文档落在 `docs/refresh-mechanism/`。

## Research Findings

### RefreshManager

- `RefreshManager` 当前负责配置、状态统计、全量刷新 timer、交易时间检查、设置面板 API 和手动刷新代理。
- `incrementalRefreshInterval` 在状态中保留，但注释说明“不再使用”。
- `manualRefresh()` 设置 `isRefreshing = true` 后没有 `finally` 复位，存在状态卡死风险。
- `stop()` 会调用 `clearAllTimers()`，同时清掉 full、trading、maintenance、rotation timer；非交易时间触发 stop 后可能失去下一次交易时间恢复能力。
- `rotation` timer 每 45 秒调用 `window.webSocketService?.runRotation?.()`，职责和刷新管理混在一起。

### RefreshCoordinator

- `RefreshCoordinator` 当前按固定服务表执行全量链：`dataLoader -> themeRuntime -> sectorAnalyzer -> dragonBreathAnalyzer -> dragonReviewService -> algorithmManager`。
- 构造时立即注册事件监听，并通过 `window` 延迟解析服务；`App.vue` 又在 4.5 秒后显式注册部分服务。
- `reset()` 只重置 `isRefreshing/currentContext`，不清 services、pendingRequests、注册 timer 或事件监听。
- 没有 `destroy()`，没有事件解绑，也没有运行中任务取消机制。
- 并发保护只覆盖 coordinator 内部 `isRefreshing` 和 5 秒 source 级冷却，覆盖不到服务自己的 timer。

### 分散定时器和轮询

- `DataLoaderFacade` 构造即启动行情自动刷新和 RankTrend 信号检查。
- `DragonBreathAnalyzer` 初始化后启动 5 分钟自动刷新，同时监听 `DATA.MERGED` 后防抖分析。
- `rotationService` 构造即启动 5 秒题材轮动分析。
- `alertService` singleton 构造即启动 10 秒预警检查。
- `snapshotFacade` 在浏览器 import 后自动启动快照 runtime；runtime 每秒扫描槽位，并定期备份同步。
- `webSocketService` 构造即启动 stale monitor；重连与心跳属于实时流，不适合并入全量刷新链。
- `DataFreshness` 1 秒 UI tick 和 `StockL2DetailPanel` 250ms UI tick 属于显示层刷新，不应纳入业务刷新 scheduler。

### 绕过统一链路的入口

- `App.vue` 主刷新按钮直接调用 `dataLoader.refreshAll({ force: true, source: 'manual' })`。
- `App.vue` 启动路径直接调用 `dataLoader.bootstrapInitialData()`，懒加载直接启动题材、龙息、复盘和算法。
- `SettingsPanel` 手动刷新先调用 `RefreshManager.manualRefresh()`，成功后又 emit `MANUAL_REQUESTED`，形成重复入口。
- `DataFreshness` 手动刷新直接 emit `MANUAL_REQUESTED`。
- 部分面板会直接调用 `dragonReviewService.runFullUpdate()` 或局部服务刷新。

### DataLayer 多源写入

- `dataLoader.publishStocks()` 通过 `dataLayer.setMergedStocks()` 写入主股票列表，并 emit `DATA.MERGED`。
- 实时行情通过 `applyRealtimeQuoteBatch()` patch `merged.stocks`。
- L2 摘要也会写入 `merged.stocks`。
- 题材 runtime 通过 `dataLayer.updateStockThemes()` 写股票题材字段，并更新轮动分析。
- 真龙复盘通过 `dataLayer.updateReviewData()` 把 leader 投影回股票列表。
- `stockStore` 同时监听 DataLayer 订阅和 `DATA.MERGED`，可能重复 reload。

## Technical Decisions

| Decision | Rationale |
| --- | --- |
| 计划分 0-6 阶段推进 | 先修明确 bug，再统一入口，再迁移定时器，降低回归风险。 |
| 任务注册表先观测后接管 | 当前 timer 分散且职责不同，直接重构容易破坏交易时间实时能力。 |
| WebSocket 实时流不并入主全量刷新链 | 连接、心跳、重连是实时传输能力，应只纳入状态观测和隐藏页降频。 |
| 快照任务独立串行，不阻塞主刷新 | 快照依赖时间槽位和存储质量，不应和热榜刷新共享失败语义。 |
| UI tick 留在组件层 | 显示层时间刷新和强制重算不写业务全局状态，不应污染刷新中心。 |
| Phase 2 只建立观测层，不接管 timer | `theme.runtime`、snapshot、WebSocket 等来源副作用复杂；先暴露任务清单和状态合同，再在 Phase 3 逐项迁移。 |

## Issues Encountered

| Issue | Resolution |
| --- | --- |
| 刷新机制范围很大，单线程分析容易遗漏 | 使用 3 个只读子 agent 分别分析核心文件、全局 timer、业务耦合，并交叉核对。 |
| planning-with-files 默认建议根目录产物，但项目规则禁止根目录过程文件 | 直接将 `task_plan.md`、`findings.md`、`progress.md` 放入 `docs/refresh-mechanism/`。 |
| Phase 0 全量 `pnpm test` 未全绿 | 失败集中在 `src/services/snapshot/__tests__/runtime.test.ts`，单独运行同一用例也失败，判断为独立快照测试问题，不混入刷新止血修复。 |
| `DataFreshness.vue` 仍直接 emit `AppEvents.REFRESH.MANUAL_REQUESTED` | 保持为 Phase 1 统一入口范围，Phase 0 只处理 `App.vue` 和 `SettingsPanel.vue` 两个计划内入口。 |
| Phase 2 实现前 registry/scheduler 测试导入失败 | 符合 TDD 红灯预期；新增 `src/services/refresh/RefreshTaskRegistry.ts` 和 `src/services/refresh/RefreshScheduler.ts` 后相关测试通过。 |

## Phase 2 Task Mapping

| Task | Existing Source | Phase 2 State |
| --- | --- | --- |
| `dataLoader.full` | `DataLoaderFacade.refreshAll()` / `runUpdate()`，由 `RefreshManager` 全量 timer 或 `RefreshCoordinator` 调用 | 已登记；`intervalMs: null`，等待统一入口阶段规范来源 |
| `dataLoader.quote` | `DataLoaderFacade.startQuoteAutoRefresh()` 30 秒行情 HTTP fallback | 已登记；不接管现有 timer |
| `dataLoader.ranktrendSignal` | `DataLoaderFacade.startSignalAutoRefresh()` 1 秒检查，14:45 执行 | 已登记；不接管现有 timer |
| `theme.runtime` | `ThemeRuntimeCoordinator.refreshRuntime()`，来源包括 dataLoader、rotationService、alertService | 已登记；保留 `source` 字段为后续区分来源 |
| `dragon.breath` | `DragonBreathAnalyzer.startAutoRefresh()` 5 分钟 timer 与 `DATA.MERGED` 防抖派生 | 已登记；不迁移防抖派生 |
| `dragon.review` | `DragonReviewService.runFullUpdate()`，当前无独立后台 timer | 已登记；`intervalMs: null` |
| `alert.check` | `AlertService.startAutoCheck()` 10 秒 timer | 已登记；不接管现有 timer |
| `snapshot.sweep` | `SnapshotRuntime.startTimer()` 1 秒槽位扫描 | 已登记；标记 `runWhenHidden: true` |
| `snapshot.backupSync` | `SnapshotRuntime.startSnapshotAutoSync()` 周期备份同步 | 已登记；标记 `runWhenHidden: true` |
| `websocket.staleCheck` | `WebSocketService.startStaleMonitor()` 500ms stale monitor | 已登记；标记实时流观测任务 |

## Resources

- `src/services/RefreshManager.ts`
- `src/services/RefreshCoordinator.ts`
- `src/App.vue`
- `src/services/dataLoader/DataLoaderFacade.ts`
- `src/services/DataLayer.ts`
- `src/services/DragonBreathAnalyzer.ts`
- `src/services/rotationService.ts`
- `src/services/alertService.ts`
- `src/services/snapshot/runtime.ts`
- `src/services/snapshot/facade.ts`
- `src/services/websocket.ts`
- `src/components/panels/SettingsPanel.vue`
- `src/components/common/DataFreshness.vue`

## Open Decisions

- “关闭自动刷新”是否关闭行情 HTTP fallback、题材轮动、龙息和预警。
- 快照槽位扫描在页面隐藏时是否继续。
- 主刷新按钮是否执行完整全局链。
- `incrementalRefreshInterval` 删除还是重新定义。
- Store 同步主通道选择 DataLayer 订阅还是事件。
