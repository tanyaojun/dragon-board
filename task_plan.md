# 题材模块重构任务计划

## Goal

把题材/板块能力从分散展示逻辑升级为统一领域模块，第一阶段优先落地可测试的题材因子合同、个股题材暴露、兼容 facade、现有 hotThemes/stock.themes 投影、快照字段最小兼容。

## Current Status

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete

## Phases

### Phase 1: 题材合同与纯计算引擎

状态：complete

- 新增 `src/services/theme/types.ts`
- 新增 `ThemeFactorEngine.ts`
- 新增 `ThemeStockProjector.ts`
- 新增 `ThemeFacade.ts`
- 新增核心单元测试，先红灯后实现

### Phase 2: 兼容接入现有题材链路

状态：complete

- 在 `sectorAnalyzer.ts` 的热题材生成与个股题材同步处接入新 facade
- 保持旧 API 不变
- 不直接大改 UI 和 DragonReview 内核

### Phase 3: 个股热度与战场最小接入

状态：complete

- 优先通过 `stock.themes/mainTheme/themeHeat/themeLevel` 影响现有链路
- 再评估是否给 `StockHotnessCalculator` 增加题材贡献权重
- 增加相关测试

### Phase 4: 快照字段最小兼容

状态：complete

- 题材因子写入 `SnapshotSectorRow.metadata`
- 个股暴露先扩展 `themes[]` 或补 stock row 字段
- 第一轮不改 QuantBoard SQLite/Supabase schema

### Phase 5: 验证与文档

状态：complete

- 运行主题模块测试
- 运行快照相关测试
- 视改动运行 `pnpm test:ranktrend`
- 总结未覆盖风险

## Decisions

- 第一阶段不直接重写 `alertService.ts`，避免覆盖用户当前打开且可能有未提交改动的文件。
- 第一阶段不直接改 QuantBoard 数据库 schema，优先使用 `sectorRows.metadata` 做兼容扩展。
- DragonReview 暂不直接消费新类型，先通过现有 `hotThemes` 和 `stock.themes` 合同接入。

## Errors Encountered

| Time | Error | Resolution |
| --- | --- | --- |
| 2026-05-05 06:57 | `ThemeFactorEngine.test.ts` 因模块不存在失败 | 这是 TDD 红灯基线，随后新增实现文件 |
