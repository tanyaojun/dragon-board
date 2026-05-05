# 题材模块优化升级 V2 任务计划

## Goal

把 V1 已落地的题材因子正式打通到 QuantBoard 数据库、候选解释和回测策略链路。默认只解释不改变交易执行；新增 `useThemeFactorForExecution` 开关，打开后才参与候选过滤、置信度调整和风险降级。

## Current Status

- Phase 1: complete
- Phase 2: complete
- Phase 3: complete
- Phase 4: complete
- Phase 5: complete

## Phases

### Phase 1: Dragon Board 快照题材列

状态：complete

- 扩展 `SnapshotStockRow` 和 `SnapshotSectorRow` 题材字段。
- `snapshot/builders.ts` 从 V1 `themes[]` 与 `metadata.themeFactor` 投影稳定列。
- 增加前端单元测试覆盖空数据和部分字段。

### Phase 2: QuantBoard 数据库与 Repository

状态：complete

- 更新 SQLAlchemy 模型、SQLite 兼容迁移、Supabase 同构 schema。
- 更新 repository 读写、恢复、API 返回路径。
- 增加后端测试验证新增列保存和读回。

### Phase 3: Python 题材支持模型

状态：complete

- 新增 `backend.analysis.theme_support`。
- 从股票行和板块行构建 `ThemeCandidateSupport`。
- 覆盖强主线、拥挤风险、无题材、JSON fallback。

### Phase 4: 回测策略接入

状态：complete

- `RankTrendPythonEngine.replay()` 带出股票题材摘要。
- `BaseStrategy` 默认只追加题材解释和风险。
- `useThemeFactorForExecution=true` 时启用置信度调整和风险降级。

### Phase 5: 文档与验证

状态：complete

- 更新 QuantBoard 相关文档。
- 运行前端、RankTrend、QuantBoard 后端测试和类型检查。

## Decisions

- V2 主轴是 QuantBoard 回测打通，不继续拆 `sectorAnalyzer.ts`、`rotationService.ts`、`alertService.ts`。
- 新增列范围包含 `snapshot_stock_rows`、`snapshot_sector_rows`、`backtest_signals`。
- 默认 `useThemeFactorForExecution=false`，避免污染旧回测对照。
- 旧快照通过 JSON fallback 或空解释兼容。

## Errors Encountered

| Time | Error | Resolution |
| --- | --- | --- |
| 2026-05-05 07:47 | 快照新增列测试红灯 | 扩展 Snapshot row 类型与 builder 投影 |
| 2026-05-05 07:50 | QuantBoard 题材测试因 `theme_support` 缺失失败 | 新增 Python 题材支持模块、模型列、repository 映射与策略接入 |
| 2026-05-05 07:54 | 拥挤风险用例错误期待置信度提升 | 按方案修正为“无高风险才提升”，并补充 clean support 用例 |
