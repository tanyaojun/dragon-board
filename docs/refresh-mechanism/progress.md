# Unified Refresh Mechanism Progress

## 2026-05-17

- 完成 `RefreshManager.ts` 和 `RefreshCoordinator.ts` 只读审计。
- 完成全局定时器、轮询、WebSocket、快照、题材、龙息、预警、面板 UI tick 的只读盘点。
- 完成业务刷新与 `DataLayer` 多源写入路径梳理。
- 确认当前 `RefreshManager/RefreshCoordinator` 不是统一刷新中心，只覆盖部分全量刷新链。
- 形成 0-6 阶段统一刷新机制优化方案。
- 按用户要求使用 `planning-with-files` 工作流，将计划和发现沉淀到：
  - `docs/refresh-mechanism/task_plan.md`
  - `docs/refresh-mechanism/findings.md`
  - `docs/refresh-mechanism/progress.md`
- 开始执行 Phase 0 止血修复。
- 新增 `src/services/__tests__/RefreshManager.test.ts`，先验证当前实现红灯，再实施修复。
- 修复 `RefreshManager.manualRefresh()` 成功、失败和并发后的 `isRefreshing` 复位。
- 调整 `RefreshManager.stop()`，停止业务刷新 timer 时保留交易时间 checker，避免非交易暂停后无法自动恢复。
- 为 rotation timer 增加非浏览器环境防护。
- 将 `App.vue` 主刷新按钮改为走 `RefreshManager.manualRefresh('full')`。
- 移除 `SettingsPanel.vue` 手动刷新成功后额外 emit `AppEvents.REFRESH.MANUAL_REQUESTED` 的重复入口。
- 记录已知例外：`DataFreshness.vue` 仍直接 emit `MANUAL_REQUESTED`，按计划留到 Phase 1 统一入口阶段处理。
- 跳过 Phase 1 实施，按用户要求继续 Phase 2；本轮只做任务注册表和调度骨架，不迁移业务 timer。
- 新增 `src/services/refresh/types.ts`，定义刷新任务 id、分类、来源、任务定义和运行状态。
- 新增 `src/services/refresh/RefreshTaskRegistry.ts`，登记 Phase 2 任务清单，并支持启停、运行中、成功、失败和运行统计状态。
- 新增 `src/services/refresh/RefreshScheduler.ts`，提供通用 interval 调度、交易时间策略、页面可见性策略和任务状态更新能力；当前未接管既有业务 timer。
- 将 `RefreshManager.getStatus()` 扩展为返回 `tasks` 诊断列表，用于后续设置面板或调试入口展示。
- 新增 registry/scheduler 单测，覆盖任务清单、状态更新、错误记录、禁用任务跳过、隐藏页/交易时间 gating。

## Verification

- `pnpm exec vitest run src/services/__tests__/RefreshManager.test.ts`：通过，5 tests passed。
- `pnpm exec vitest run src/services/__tests__/RefreshManager.test.ts src/services/__tests__/RefreshCoordinator.test.ts`：通过，6 tests passed。
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
- `pnpm exec vitest run src/services/refresh/__tests__/RefreshTaskRegistry.test.ts src/services/refresh/__tests__/RefreshScheduler.test.ts src/services/__tests__/RefreshManager.test.ts`：通过，13 tests passed。
- `pnpm exec vitest run src/services/__tests__/RefreshCoordinator.test.ts src/services/__tests__/RefreshManager.test.ts src/services/refresh/__tests__/RefreshTaskRegistry.test.ts src/services/refresh/__tests__/RefreshScheduler.test.ts`：通过，14 tests passed。
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
- `pnpm test`：未全绿；331 passed、1 failed。失败为既有/独立快照测试 `src/services/snapshot/__tests__/runtime.test.ts` 的 `ignores IndexedDB existence and rewrites through sqlite for formal snapshots`，单独运行同样失败，未纳入本次 Phase 0 修复范围。
- `pnpm exec vitest run src/services/dataLoader/__tests__/DataLoaderFacade.test.ts src/services/refresh/__tests__/RefreshTaskRegistry.test.ts src/services/refresh/__tests__/RefreshScheduler.test.ts src/services/__tests__/RefreshManager.test.ts src/services/__tests__/RefreshCoordinator.test.ts src/services/__tests__/DragonBreathAnalyzer.refreshScheduler.test.ts src/services/__tests__/alertService.test.ts src/services/__tests__/themeLegacyAdapters.test.ts`：通过，49 tests passed。

## Phase 3 First Batch

- 新增 `src/services/refresh/RefreshTaskRuntime.ts`，提供共享 `refreshTaskRegistry` 和 `refreshScheduler`，作为业务 timer 逐步接入的统一运行时。
- `RefreshManager` 改为读取共享任务注册表，但不拥有共享 scheduler 生命周期；`reset()` / `destroy()` 只处理自身全量刷新 timer，不停止或重置其它服务任务。
- `RefreshScheduler.startTask()` 支持调用方传入 interval override，用于保持各业务服务原有测试和启动参数语义。
- 本批迁移显式保留旧 timer 运行策略：题材轮动、预警和 RankTrend 检查不提前套交易时间 gating，已迁移任务默认允许 hidden page 继续 tick；隐藏页降频留到 Phase 5。
- 迁移 `DataLoaderFacade` 的行情 HTTP fallback 自动轮询到 `dataLoader.quote`。
- 迁移 `DataLoaderFacade` 的 14:45 RankTrend 信号检查到 `dataLoader.ranktrendSignal`。
- 迁移 `rotationService` 的题材轮动自动分析到 `theme.runtime`。
- 迁移 `DragonBreathAnalyzer` 的 5 分钟自动刷新到 `dragon.breath`，保留 `DATA.MERGED` 触发的 500ms 防抖派生分析。
- 迁移 `alertService` 的 10 秒预警检查到 `alert.check`。
- WebSocket stale monitor、连接/重连/心跳和快照槽位/备份同步本批不接管，只保留 Phase 2 登记；隐藏页降频留到 Phase 5。
- 当前工作区存在候选池和 QuantBoard journal 的独立未提交改动，刷新机制提交需要显式排除这些路径。
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## Phase 4 First Batch

- 新增 `src/services/refresh/RefreshResourceLocks.ts`，提供资源级单飞锁，支持等待串行和 `skipIfLocked` 跳过策略。
- `DataLoaderFacade` 的平台热榜加载接入 `hotlist-platform` 锁，避免多个全量/启动加载同时执行平台合并链。
- `DataLoaderFacade` 的全量行情补全、手工行情详情和 HTTP fallback 接入 `quote-http` 锁；fallback 在全量刷新占用 quote HTTP 时跳过本轮，避免重复请求和写入交错。
- `DataLayer.setMergedStocks()` 在写入全量/增强股票行时重新叠加已有 realtime quote 与 L2 summary 投影，防止 WebSocket/L2 已 patch 的价格、成交、盘口和逐笔聚合字段被旧全量结果覆盖。
- 新增资源锁单测、DataLoader 并发回归测试和 DataLayer 实时字段保护测试。
- 本批未处理 `theme-runtime`、`dragon-breath`、`dragon-review`、`ranktrend-signal`、`snapshot-write` 的实际接入；失败重试合同和 `StockStore` 双通道 reload 去重仍留待后续。

## Next Step

- 继续 Phase 4 后半段：给题材、龙息、复盘、RankTrend 信号和快照写入逐步接入资源锁，并定义失败重试/跳过合同。
- 梳理 `StockStore` 的 `DataLayer.subscribe('merged.stocks')` 与 `AppEvents.DATA.MERGED` 双监听，减少重复 `loadStocks()`。
- 回到 Phase 1：统一全量刷新入口，优先处理 `DataFreshness.vue` 仍绕过 `RefreshManager` 的手动刷新入口。
- 后续不要直接启用 `RefreshScheduler.startAll()`；仍应逐个迁移任务并保留回归测试。
- 另行决定是否单独修复 `snapshot/runtime.test.ts` 的既有失败。
