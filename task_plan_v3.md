# 题材模块优化升级 V3 任务计划

## Goal

完成 Dragon Board 前端题材领域收口：让 V1/V2 已落地的题材因子、个股暴露和 QuantBoard 桥接，进一步统一到前端运行态服务、轮动、联动和预警链路中。

## Current Status

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete

## Phases

### Phase 1: V3 领域合同与运行态

状态：complete

- 扩展 `src/services/theme/types.ts`，新增 `ThemeEvent`、`ThemeRuntimeSnapshot`、刷新选项。
- 新增 `ThemeRuntimeStore`，保存因子、暴露、轮动、事件和联动快照。
- 新增单元测试覆盖运行态快照不可变和订阅通知。

### Phase 2: 轮动、事件和联动 engine

状态：complete

- 新增 `ThemeRotationEngine`，基于 `ThemeFactorSnapshot[]` 计算兼容 `RotationAnalysis`。
- 新增 `ThemeAlertEngine`，输出标准化 `ThemeEvent`。
- 新增 `ThemeCorrelationEngine`，为联动/龙头识别提供类型化纯计算入口。
- 新增 `ThemeRepository`、`JxbkThemeFeed` 作为后续迁移边界。

### Phase 3: Facade 与旧服务兼容

状态：complete

- `ThemeFacade` 新增 `refresh/getRotationSummary/getThemeEvents/getHotThemesCompat/getThemeDetailCompat/getThemeStocksCompat`。
- `rotationService.analyzeAll()` 优先委托 `themeFacade.refresh()`，保留旧逻辑 fallback。
- `alertService.checkAll()` 消费 `ThemeEvent`，自身保留冷却、历史、已读和个股预警职责。
- `ThemeCorrelationAnalyzer.ts` 去掉 `@ts-nocheck`，主路径委托 `ThemeCorrelationEngine`。

### Phase 4: UI 与 DragonReview 迁移

状态：complete

- 保留旧全局对象，同时 `ThemeFacade` 挂载 `window.themeFacade`。
- 当前阶段优先通过旧 facade 兼容 UI，不批量改面板。
- DragonReview `BattlefieldBuilder` 已从 `themeFacade` 获取题材因子、轮动和个股暴露作为战场种子。

### Phase 5: 验证与收尾

状态：complete

- 运行主题/快照/热度局部测试。
- 运行 `pnpm test:ranktrend`。
- 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`。
- 运行 `pnpm test`。

## Decisions

- V3 不修改 QuantBoard schema。
- V3 不删除旧服务文件，只做委托和兼容导出。
- `alertService` 不再直接把 JXBK 板块扫描作为主预警来源；题材预警由 `ThemeAlertEngine` 生成事件。
- `rotationService` 仍保留 localStorage 展示缓存，但不再把它作为轮动事实源。

## Errors Encountered

| Time | Error | Resolution |
| --- | --- | --- |
| 2026-05-05 08:28 | V3 测试因 `ThemeRuntimeStore` 缺失红灯 | 新增 runtime store、rotation engine、alert engine |
| 2026-05-05 08:30 | 轮动阶段误判 distribution | 明确有主线/流入占优时优先 rising |
| 2026-05-05 08:31 | facade 测试没有主线输入 | 测试补充明确 `rotationAnalysis.mainLines` |
| 2026-05-05 08:34 | 新 feed/repository 委托方法名不匹配 | 改为现有 `getJxbkStockMap/getStockTagsWithReason` |
