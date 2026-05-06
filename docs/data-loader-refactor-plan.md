# dataLoader Refactor Notes

## Goal

在保持 `src/services/dataLoader.ts` 对外 facade API 和调用方 import 不变的前提下，分阶段拆分行情、实时、热榜、合并、RankTrend 信号等职责。

## Phase Status

| Phase | Scope | Status |
| --- | --- | --- |
| 0 | 行为锁定测试 | done |
| 1 | 类型、常量、工具函数下沉 | done |
| 2 | 纯算法模块抽取 | done |
| 3 | 行情服务抽取 | done |
| 4 | TDX 实时运行态抽取 | done |
| 5 | 平台热榜与涨停 feed 抽取 | done |
| 6 | 合并主编排抽取 | done |
| 7 | RankTrend 信号服务抽取 | done |
| 8 | Facade 收口与文档 | done |

## Current Structure

- `src/services/dataLoader.ts` 是兼容入口，只 re-export `dataLoader` 和必要类型。
- `DataLoaderFacade.ts` 保留公开 API、loading 状态、初始化、刷新/维护、生命周期和模块委托。
- 行情 HTTP/合并行情在 `QuoteHttpFeed.ts`、`QuoteService.ts`。
- TDX 实时运行态在 `RealtimeQuoteCoordinator.ts`。
- 平台热榜和涨停池在 `PlatformHotlistService.ts`、`LimitUpFeed.ts`。
- 合并主链和扩展字段投影在 `StockMergeCoordinator.ts`、`ExtraDataProjector.ts`。
- RankTrend 信号在 `RankTrendSignalService.ts`。
- 量比历史和热度更新在 `VolumeHistoryService.ts`、`StockHotnessService.ts`。

## Verification Log

| Command | Result |
| --- | --- |
| `pnpm exec vitest run src/services/dataLoader/__tests__/QuoteService.test.ts` | pass |
| `pnpm exec vitest run src/services/dataLoader/__tests__` | pass |
| `pnpm exec vitest run src/services/dataLoader/__tests__` after Phase 4 | pass |
| `pnpm exec vitest run src/services/dataLoader/__tests__` after Phase 5 | pass |
| `pnpm exec vitest run src/services/dataLoader/__tests__` after Phase 6 | pass |
| `pnpm exec vitest run src/services/dataLoader/__tests__` after Phase 7 | pass |
| `pnpm test:ranktrend` after Phase 7 | pass |
| `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | pass |
| `pnpm build` | pass，存在既有 ThemeFacade 动态/静态导入分块警告 |
| `pnpm test` | pass，40 files / 243 tests；ThemeDataService 用例输出预期 sqlite 失败日志 |

## Errors Encountered

| Error | Resolution |
| --- | --- |
| planning-with-files catchup 脚本因外部脚本执行风险被拦截 | 改用 `git diff --stat`、计划文档和显式进度记录维护上下文 |
