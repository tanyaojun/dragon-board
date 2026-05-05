# 题材模块优化升级 V5 任务计划

## Goal

统一题材运行态编排主链，迁移仍依赖 `sectorAnalyzer/rotationService/alertService.checkBlocks()` 的服务层入口，让 `themeFacade` 成为刷新、同步、轮动、事件和个股投影的权威入口。

## Current Status

- Phase 1: completed
- Phase 2: completed
- Phase 3: completed
- Phase 4: completed
- Phase 5: completed

## Phases

### Phase 1: 计划与红灯测试

状态：completed

- 新增 `task_plan_v5.md`。
- 增加 `ThemeRuntimeCoordinator`、legacy alert adapter、facade runtime metadata 的红灯测试。
- 更新 `progress.md/findings.md` 记录 V5 范围。

### Phase 2: 运行态 coordinator

状态：completed

- 新增 `ThemeRuntimeCoordinator`，提供 `refreshRuntime()`。
- 扩展 runtime snapshot 元数据：inputSignature、qualitySummary、refreshSource、changedFields、factorVersion、eventVersion。
- `themeFacade.refresh/refreshJxbkAndFactors` 委托 coordinator。

### Phase 3: 服务层旧调用迁移

状态：completed

- `sectorAnalyzer` legacy API 内部委托 `themeFacade.refreshRuntime`。
- `dataLoader/AlgorithmManager/ConsistencyManager/RefreshCoordinator` 使用 theme runtime 同步入口。
- `rotationService` 保留旧返回结构，不再持有独立事实源。

### Phase 4: 预警职责收敛

状态：completed

- 将 legacy block alert 生成迁入 theme 模块适配器。
- `alertService` 只负责事件入库、冷却、去重和状态管理。

### Phase 5: 验证与收尾

状态：completed

- 运行 V5 局部测试、全量前端测试、RankTrend 回归和 Vue 类型检查。
- 记录验证结果和剩余 legacy 边界。

## Decisions

- V5 不改 QuantBoard schema。
- V5 不删除旧服务文件。
- 旧全局对象继续挂载。
- 题材因子仍不直接产生买入信号。

## Errors Encountered

| Time | Error | Resolution |
| --- | --- | --- |
| 2026-05-05 | `refreshRuntime()` 同时需要兼容同步 context 调用和异步 JXBK 刷新调用。 | 使用重载：带 `context` 返回同步 `ThemeRuntimeRefreshResult`，无 `context` 的强制 JXBK 刷新返回 Promise。 |

## Verification

- `pnpm exec vitest run src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts src/services/theme/__tests__/ThemeLegacyAlertAdapter.test.ts src/services/theme/__tests__/ThemeV3Engines.test.ts src/services/__tests__/alertService.test.ts`：通过，4 个测试文件、16 个测试通过。
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
- `pnpm exec vitest run src/services/theme src/services/__tests__/alertService.test.ts`：通过，6 个测试文件、25 个测试通过。
- `pnpm exec vitest run src/services/snapshot src/services/hotness`：通过，10 个测试文件、52 个测试通过。
- `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
- `pnpm test`：通过，28 个测试文件、193 个测试通过。
