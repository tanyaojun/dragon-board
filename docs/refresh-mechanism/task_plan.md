# Unified Refresh Mechanism Implementation Plan

## Goal

将 Dragon Board 分散的业务刷新、轮询和状态展示收敛为可观测、可控制、可验证的统一刷新机制。

## Current Phase

Phase 4 first batch complete for resource locks and write arbitration. Phase 1 remains pending.

## Success Criteria

- 主刷新按钮、设置面板手动刷新、定时全量刷新统一进入同一个刷新入口。
- 写入全局业务状态的刷新任务都有统一状态：`enabled`、`running`、`lastRunAt`、`lastSuccessAt`、`lastError`、`intervalMs`、`source`。
- 全量热榜、行情 HTTP fallback、题材 runtime、龙息、真龙复盘、RankTrend 信号之间有资源级单飞锁或冷却策略。
- 关闭自动刷新、非交易时间和页面隐藏时，各任务行为可解释、可配置、可观测。
- WebSocket 实时流、快照槽位任务、面板 UI tick 与主业务刷新分层，不互相阻塞。
- 相关 Vitest、RankTrend 测试、Vue 类型检查和构建通过。

## Phases

### Phase 0: RefreshManager/Coordinator 止血修复

- [x] 修复 `RefreshManager.manualRefresh()` 设置 `isRefreshing = true` 后没有 `finally` 复位的问题。
- [x] 拆分 `RefreshManager.stop()` 的语义：停止业务刷新 timer 时不要清掉交易时间生命周期 checker。
- [x] 移除 `SettingsPanel.manualRefresh()` 成功后再次 emit `AppEvents.REFRESH.MANUAL_REQUESTED` 的重复入口。
- [x] 将 `App.vue` 主刷新按钮从直接调用 `dataLoader.refreshAll()` 改为统一刷新入口。
- [x] 增加最小单测覆盖：手动刷新成功/失败后状态恢复；重复手动刷新不会并发执行。
- **验证:** `pnpm test`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
- **Status:** complete

### Phase 1: 统一全量刷新入口

- [ ] 在 `RefreshManager` 暴露一个唯一请求入口，例如 `requestRefresh({ kind, source, force })`。
- [ ] 让 `RefreshManager.manualRefresh()`、定时全量刷新、`App.vue` 主刷新、`DataFreshness.vue` 手动刷新都调用该入口。
- [ ] 将 `RefreshCoordinator` 定位为执行器：接收已规范化请求，返回结构化结果。
- [ ] 明确返回结果类型：`success`、`skipped`、`busy`、`errors`、`duration`、`executedTasks`。
- [ ] 保留局部面板刷新，但不得把局部刷新伪装为“全局刷新中”。
- **验证:** 新增/更新 `src/services/__tests__/RefreshCoordinator.test.ts` 和 `RefreshManager` 测试。
- **Status:** pending

### Phase 2: 建立刷新任务注册表

- [x] 新增轻量任务类型定义，例如 `src/services/refresh/types.ts`。
- [x] 新增 `RefreshTaskRegistry`，统一登记任务元信息和运行状态。
- [x] 新增 `RefreshScheduler` 或等价内部模块，负责通用定时、页面可见性策略、交易时间策略和任务状态更新。
- [x] 先登记任务，不立即迁移所有 timer：
  - `dataLoader.full`
  - `dataLoader.quote`
  - `dataLoader.ranktrendSignal`
  - `theme.runtime`
  - `dragon.breath`
  - `dragon.review`
  - `alert.check`
  - `snapshot.sweep`
  - `snapshot.backupSync`
  - `websocket.staleCheck`
- [x] 在设置面板或诊断接口展示任务列表，避免“自动刷新已关闭但后台仍刷新”的误导。
- **验证:** registry 单测覆盖注册、启停、状态更新、错误记录。
- **Status:** complete
- **Scope note:** 本阶段只完成登记、状态模型和 `RefreshManager.getStatus().tasks` 诊断出口；没有迁移既有业务 timer，也没有改变运行时刷新频率。

### Phase 3: 迁移业务型定时器

- [x] 迁移 `DataLoaderFacade` 行情 HTTP fallback 30 秒轮询到统一 scheduler。
- [x] 迁移 `DataLoaderFacade` 14:45 RankTrend 信号检查到统一 scheduler。
- [x] 迁移 `rotationService` 5 秒题材轮动到统一 scheduler，或先降频后迁移。
- [x] 迁移 `DragonBreathAnalyzer` 5 分钟自动刷新到统一 scheduler，保留 `DATA.MERGED` 防抖派生分析。
- [x] 迁移 `alertService` 10 秒预警检查到统一 scheduler。
- [ ] 保留 WebSocket 连接/重连/心跳为独立实时流，但登记状态和隐藏页降频策略。
- [ ] 保留快照槽位扫描/备份同步为独立存储维护任务，但登记状态和质量依赖。
- **验证:** fake timer 测试各任务 interval、暂停、恢复、错误记录。
- **Status:** partial
- **Scope note:** 本阶段第一批只迁移会主动写入全局业务状态的业务 timer：行情 HTTP fallback、RankTrend 信号检查、题材轮动、龙息自动刷新和预警检查。WebSocket stale monitor 与快照槽位/备份任务仍保持独立运行流，只保留登记状态，隐藏页降频策略留到 Phase 5。

### Phase 4: 并发控制与写入仲裁

- [x] 引入资源级单飞锁或冷却键：
  - `hotlist-platform`
  - `quote-http`
  - `theme-runtime`
  - `dragon-breath`
  - `dragon-review`
  - `ranktrend-signal`
  - `snapshot-write`
- [x] 防止 `dataLoader.refreshAll()` 与行情轮询重叠。
- [x] 防止 `setMergedStocks()` 后续增强结果覆盖 WebSocket/L2 已 patch 的实时行情字段。
- [ ] 梳理 `DataLayer.subscribe('merged.stocks')` 与 `AppEvents.DATA.MERGED` 的消费关系，减少重复 reload。
- [ ] 统一失败重试合同：哪些错误跳过、哪些返回失败、哪些保留旧数据。
- **验证:** 并发刷新测试；实时行情字段不被全量写回覆盖的回归测试。
- **Status:** partial
- **Scope note:** 第一批落地资源锁基础设施、`hotlist-platform` 串行、`quote-http` 单飞/跳过，以及 DataLayer 实时 quote/L2 字段写入仲裁。`theme-runtime`、`dragon-*`、`ranktrend-signal`、`snapshot-write` 的实际接入和失败重试合同留待后续批次。

### Phase 5: 页面可见性、交易时间和配置策略

- [ ] 增加统一页面可见性策略：`run`、`pause`、`slow`。
- [ ] 页面隐藏时暂停或降频非关键任务：题材轮动、预警、HTTP fallback、热股异动面板刷新。
- [ ] WebSocket 保持独立连接，但 stale 检查可降频。
- [ ] 快照槽位扫描是否隐藏页继续执行需业务确认；建议交易时间内继续，但保存前检查质量。
- [ ] SettingsPanel 拆成全局策略和任务明细两层。
- **验证:** 模拟 `document.hidden` 的任务调度测试。
- **Status:** pending

### Phase 6: 清理旧口径和文档

- [ ] 删除或重新定义未使用的 `incrementalRefreshInterval` UI/配置。
- [ ] 移除 `RefreshCoordinator` 依赖 `window` 延迟解析服务的主路径，改为 App 初始化显式注册。
- [ ] 给 `RefreshCoordinator` 增加 `destroy()` 和事件解绑。
- [ ] 更新刷新机制专题文档、设置面板说明和开发协作说明。
- [ ] 清理历史误导性注释，例如“由 RefreshManager 调度”但实际未接入的模块注释。
- **验证:** `pnpm test`；`pnpm test:ranktrend`；`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`；`pnpm build`
- **Status:** pending

## Key Questions

1. 关闭“自动刷新”时，是否关闭行情 HTTP fallback、题材轮动、龙息、预警？
2. 页面隐藏时，快照槽位扫描是否继续？
3. 主刷新按钮是否执行完整链：热榜 -> 题材 -> 龙息 -> 复盘 -> 算法？
4. `incrementalRefreshInterval` 是删除，还是重新定义为行情/派生任务的策略参数？
5. Store 同步是否统一只订阅 DataLayer 版本，减少事件和订阅双通道？

## Recommended Decisions

| Decision | Rationale |
| --- | --- |
| 关闭自动刷新时关闭业务刷新，但保留 WebSocket 实时流 | 用户期望“自动刷新关闭”能停止热榜/题材/龙息/预警等主动业务更新；WebSocket 是实时连接能力，不应被全量刷新开关误伤。 |
| 快照任务不并入主刷新链 | 快照是时间槽位和存储维护任务，失败不应阻塞主榜刷新；但应登记状态并依赖数据质量。 |
| 主刷新按钮执行完整全局链 | “刷新全部数据”应覆盖热榜、题材、龙息、复盘、算法，否则用户感知和系统状态不一致。 |
| 先登记任务，再逐步迁移 timer | 一次性迁移所有 timer 风险高；先观测真实运行状态，再分批替换。 |
| UI tick 不进入业务刷新 scheduler | `DataFreshness` 和 L2 面板刷新是显示层 tick，只需要 visible gating，不应污染业务刷新状态。 |

## Proposed File Responsibilities

| File | Responsibility |
| --- | --- |
| `src/services/RefreshManager.ts` | 全局刷新配置、用户入口、状态 facade、定时启动入口。 |
| `src/services/RefreshCoordinator.ts` | 执行标准全量刷新流程，返回结构化执行结果。 |
| `src/services/refresh/types.ts` | 任务、请求、结果、可见性策略、资源锁 key 等类型。 |
| `src/services/refresh/RefreshTaskRegistry.ts` | 任务登记、状态查询、错误和运行统计。 |
| `src/services/refresh/RefreshScheduler.ts` | 通用定时、交易时间策略、页面可见性策略和单飞调度。 |
| `src/services/dataLoader/DataLoaderFacade.ts` | 保留数据加载实现，移除构造即启动 timer，暴露任务方法供 scheduler 调用。 |
| `src/components/panels/SettingsPanel.vue` | 展示全局刷新策略和任务明细，不直接制造重复刷新事件。 |

## Risks

- 迁移过快会影响交易时间内实时行情和快照保存。
- 如果直接让所有任务共享一个全局锁，会导致低优先级维护任务阻塞核心行情刷新。
- 如果只统一入口、不处理 DataLayer 写入仲裁，仍会有实时行情字段被全量写回覆盖的问题。
- 如果设置面板只显示全局开关，不显示任务明细，用户仍会误解后台行为。

## Notes

- 本计划只针对根 Vue 前端刷新机制，不涉及 `proxy-server/`、`python-bridge/` 和 QuantBoard 后端。
- WebSocket 真 L2 能力边界不变：当前默认仍是本地桥接实时行情能力，不把五档能力描述为官方客户端级 L2。
- 任何实现阶段都应小步提交，优先测试并发、状态复位、重复入口和隐藏页策略。
