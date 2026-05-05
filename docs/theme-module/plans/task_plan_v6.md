# 题材模块优化升级方案 V6：刷新主链单一化与 Legacy 退场

## 目标

- 将 `themeFacade.refresh()/refreshRuntime()`、预警、轮动和 legacy 同步入口统一到 `ThemeRuntimeCoordinator.refreshRuntime()`。
- 保留旧服务文件和全局对象，但公开刷新/同步 API 只作为 runtime coordinator 的 adapter。
- 本轮不修改 QuantBoard、UI 布局和 RankTrend 默认交易逻辑。

## 实施清单

- `ThemeFacade`：`refreshRuntimeState()` 包装 coordinator，并同步 facade 读口缓存；`refreshThemeFacadeState()` 保留为兼容包装。
- `alertService`：`checkThemeEvents()` 消费一次 runtime result；`checkBlocks()` 退为板块快照维护，不再二次生成 legacy block event。
- `ThemeSyncAdapter`：`syncThemesToStocks()` 委托 `syncData()`，`runUpdate()` 保留 force JXBK 差异。
- `sectorAnalyzer/rotationService`：公开刷新和同步入口改为调用 `themeFacade.refreshRuntime()`，旧逻辑只保留为兼容 fallback。
- 测试：补 runtime/facade 同步、alert 单帧不重复事件，并运行 V6 回归命令。

## 验证命令

- `pnpm exec vitest run src/services/theme src/services/__tests__/alertService.test.ts`
- `pnpm exec vitest run src/services/snapshot src/services/hotness`
- `pnpm test:ranktrend`
- `pnpm test`
- `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
- `git diff --check`

## Review Gate

- 完成后保持未提交状态。
- 交付改动摘要、验证结果、风险点和建议提交信息。
- 等用户明确确认后再提交。
