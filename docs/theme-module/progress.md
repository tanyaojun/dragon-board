# 题材模块重构进度

## 2026-05-05 06:57

- 写入 `src/services/theme/__tests__/ThemeFactorEngine.test.ts`。
- 运行 `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts`。
- 结果：失败，原因是 `../ThemeFactorEngine` 尚不存在，符合 TDD 红灯预期。

## 2026-05-05 06:58-07:00

- 新增 `src/services/theme/types.ts`。
- 新增 `src/services/theme/ThemeFactorEngine.ts`。
- 新增 `src/services/theme/ThemeStockProjector.ts`。
- 新增 `src/services/theme/ThemeFacade.ts`。
- 启动两个并行只读子任务：
  - 快照/QuantBoard 字段接入梳理。
  - 个股热度/DragonReview 接入梳理。
- 两个子任务均已返回结论，记录到 `findings.md`。

## 2026-05-05 07:00

- 用户显式调用 `planning-with-files`。
- 初始化 `task_plan.md`、`findings.md`、`progress.md`。

## 2026-05-05 07:01

- 运行 `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts`。
- 结果：通过，3 个测试通过。
- Phase 1 核心合同、因子引擎、个股投影初步可用。

## 2026-05-05 07:02

- 修改 `src/services/sectorAnalyzer.ts`，在 `updateThemeHeat()` 接入 `themeFacade.refreshThemeFactors()`，并把新因子投影成旧 `HotTheme` 兼容结构。
- 修改 `syncThemesToStocks()`，优先从 `ThemeStockExposure` 投影 `stock.themes/mainTheme/themeHeat/themeLevel`，无 exposure 时保留旧静态/JXBK 合并逻辑。
- 运行 `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts`：通过。
- 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 07:03

- 新增 `src/services/snapshot/__tests__/themeFactorProjection.test.ts`，先验证当前会丢 exposure/themeFactor 字段，测试红灯。
- 修改 `src/services/snapshot/types.ts` 和 `src/services/snapshot/builders.ts`：
  - `SnapshotStockRow.themes[]` 保留 `role/exposureWeight/themeContribution/riskPenalty`。
  - `SnapshotSectorRow.metadata.themeFactor` 保存题材因子扩展字段。
- 运行 `pnpm exec vitest run src/services/snapshot/__tests__/themeFactorProjection.test.ts src/services/theme/__tests__/ThemeFactorEngine.test.ts`：通过，5 个测试通过。
- 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 07:05

- 在 `StockHotnessCalculator` 增加 `themeSupport` 小权重组件。
- 新增测试验证强题材不会单独制造高热度。
- 修复 `normalize()` 单有效样本时无效排名 `999` 被反向归一化成 100 的边界。
- 运行 `pnpm exec vitest run src/services/hotness/__tests__/StockHotnessCalculator.test.ts`：通过，6 个测试通过。
- 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 07:06

- 运行 `pnpm test -- src/services/theme src/services/hotness src/services/snapshot`：通过，12 个测试文件、54 个测试通过。
- 运行 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
- 运行 `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
- 检查 `git status --short`：`src/services/trendChartService.ts` 删除、`.claude/`、`CLAUDE.md`、`docs/snapshot-audit-skill.md` 是本任务前已有/外部状态；本轮未修改 `src/services/alertService.ts`。

## 2026-05-05 07:20-07:22

- 处理自查和其他 agent code review 反馈。
- 修复：
  - JXBK 定时刷新后先 `updateThemeHeat()` 再同步股票题材，避免 facade exposure 使用旧缓存。
  - `syncThemesToStocks()` 在有 exposure 时继续合并旧静态题材和 realtime-only JXBK blocks，避免早退导致题材丢失。
  - `relatedThemeIds` 不再错误写入 `coreStocks` 股票代码。
  - 全 NaN/Inf 成分股不再产出虚假热度。
  - noise 且贡献极低的 exposure 会被丢弃。
  - `toFiniteNumber/clamp/round` 提取到 `src/services/theme/utils.ts`。
  - `themeSupportScore()` 去掉 `any`。
  - `buildSectorRow()` metadata 构建改为一次性合并，避免重复 JSON clone。
- 新增/扩展测试：
  - `ThemeFactorEngine`：relatedThemeIds、全非法数值、noise exposure。
  - `themeFactorProjection`：空 metadata、部分 factor key。
- 验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts src/services/snapshot/__tests__/themeFactorProjection.test.ts src/services/hotness/__tests__/StockHotnessCalculator.test.ts`：通过，15 个测试通过。
  - `pnpm test -- src/services/theme src/services/hotness src/services/snapshot`：通过，12 个测试文件、58 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。

## 2026-05-05 题材模块 V3 最终提交

- V3 已复核并提交：
  - `0c10354 feat: 收口题材前端领域服务`
- 提交前验证：
  - `pnpm test`：通过，26 个测试文件、183 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `git diff --cached --check`：通过。
- 提交后工作区干净。

## 2026-05-05 题材模块 V4 启动

- 用户要求实施《题材模块优化升级方案 V4》。
- 已新增 `task_plan_v4.md`。
- V4 目标：前端调用迁移、旧逻辑退场、可观测性与一致性验收。
- 当前原则：不改 QuantBoard schema，不删除旧服务文件，UI 字段保持兼容。

## 2026-05-05 题材模块 V4 实施

- 已扩展 `themeFacade` UI 读口：
  - `getJxbkBlocksCompat/getJxbkLastUpdate/getThemeStockMapCompat/getRuntimeSnapshot/refreshJxbkAndFactors`。
  - refresh 增加受 debug 开关控制的结构化输入/输出/质量摘要日志。
  - 同一输入 context 重复 refresh 不再导致轮动 `persistentDays` 非确定性递增。
- 已迁移 UI/导出主路径：
  - `SectorPanel/SectorDetail/SectorStocksTree/SectorRotation/ExportPanel/exportService` 优先调用 `themeFacade`。
  - `ThemeCorrelationPanel/ThemeRiskDashboard` 不再直接拼 `state.theme.jxbk.stockMap`。
- 已收敛旧服务：
  - `sectorAnalyzer.getHotThemes/getThemeDetail` 优先委托 `themeFacade`。
  - 旧 `ThemeHeatCalculator/generateHotThemes/forceRefreshJxbk` 标记为 V4 deprecated fallback。
  - `ThemeDataService` 注释明确长期职责是静态映射 repository。
  - `alertService` 对 `ThemeEvent` 与 legacy block money-flow alert 做同帧去重，保留其他 legacy 板块预警。
- 已验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts src/services/__tests__/alertService.test.ts`：通过，2 个测试文件、8 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `pnpm exec vitest run src/services/theme`：通过，3 个测试文件、17 个测试通过。
  - `pnpm exec vitest run src/services/snapshot src/services/hotness`：通过，10 个测试文件、52 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
  - `pnpm test`：通过，26 个测试文件、185 个测试通过。

## 2026-05-05 题材模块 V4 review 修复

- 使用 `receiving-code-review` 流程核对外部审查报告。
- 已修复：
  - `getJxbkBlocksCompat()` 只在显式 context 处于 5 分钟 TTL 内时使用快照，否则回落到 `JxbkThemeFeed/DataLayer` 的实时缓存。
  - `getThemeStockMapCompat()` 深拷贝股票条目和 `blocks` 数组，避免 UI 调用方污染 feed 数据。
  - `sourceSignature()` 对 themes 和 JXBK blocks 排序，降低上游顺序变化导致的误判。
  - 相同 source signature 重复 refresh 复用上一轮 rotation summary，避免持续天数和主线状态抖动。
  - `theme_mapping_quality_warning` 新增正式 `data_anomaly` 预警类型和展示配置，不再映射到资金异动。
  - `SectorRotation` 的 legacy fallback 增加防御性说明。
- 已验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts src/services/__tests__/alertService.test.ts`：通过，2 个测试文件、11 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 题材模块 V5 启动

- 用户要求实施《题材模块优化升级方案 V5：运行态编排统一与旧服务退场》。
- 已新增 `task_plan_v5.md`。
- 当前目标：
  - 新增统一 `ThemeRuntimeCoordinator.refreshRuntime()`。
  - 服务层旧调用从 `sectorAnalyzer` 迁移到 `themeFacade/themeRuntime`。
  - legacy block alert 迁入 theme 模块适配器。
  - runtime snapshot 增加可回放元数据。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `rg -n "trendChartService" src -S`：无代码引用。

## 2026-05-05 skills 目录规则

- 用户新增根目录 `skills/`，要求后续所有 `SKILL.md` 放入该目录。
- 已更新 `AGENTS.md`：
  - 根目录树新增 `skills/`。
  - 补充项目级 skills 放置规则。
  - 根目录保留规则加入 `SKILLS.md`。
  - 文档维护规则增加 `SKILLS.md` 与 `skills/` 分工。
- 已更新 `SKILLS.md`：
  - 明确 `SKILLS.md` 是总索引。
  - 具体 skill 正文、模板、引用材料和工作流清单统一放 `skills/`。

## 2026-05-05 外部 review 二次核对

- 使用 `receiving-code-review` 流程逐项核对外部 agent 报告。
- 已确认当前工作区中以下问题已在前序修复中解决：
  - `relatedThemeIds` 不再写入 `coreStocks` 股票代码。
  - `toFiniteNumber/clamp/round` 已提取到 `src/services/theme/utils.ts`。
  - `syncThemesToStocks()` 有 exposure 时仍合并静态题材和 realtime-only JXBK blocks。
  - `themeSupportScore()` 已去掉 `any`。
  - 题材因子、snapshot metadata、noise exposure、非法数值已有测试覆盖。
- 本次新增修复：
  - `ThemeFactorEngine.persistenceScore()` 从 0 -> 45 硬跳变改为连续评分，降低主线进出时的排序抖动。
  - `sectorAnalyzer.calculateThemeMetrics()` 的旧计算路径保留为 facade 未产出因子前的兼容 fallback，并加注释说明，避免误删。
- 重新验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts src/services/snapshot/__tests__/themeFactorProjection.test.ts src/services/hotness/__tests__/StockHotnessCalculator.test.ts`：通过，15 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 题材模块 V2 启动

- 用户要求实施《题材模块优化升级方案 V2》。
- 已新增 `task_plan_v2.md`，将 V2 拆成：
  - Dragon Board 快照题材列。
  - QuantBoard 数据库与 repository。
  - Python 题材支持模型。
  - 回测策略接入。
  - 文档与验证。
- 当前决策：默认不改变回测执行；`useThemeFactorForExecution=true` 时才让题材因子参与置信度调整和风险降级。

## 2026-05-05 题材模块 V2 实施

- Dragon Board 快照：
  - `SnapshotStockRow` 新增 `themeContribution/themeRole/themeExposureWeight/themeRiskFlags`。
  - `SnapshotSectorRow` 新增题材因子稳定列和 `themeQualityFlags`。
  - `snapshot/builders.ts` 从 V1 `themes[]` 与 `metadata.themeFactor` 投影新增列。
  - `pnpm exec vitest run src/services/snapshot/__tests__/themeFactorProjection.test.ts`：通过。
- QuantBoard 后端：
  - 新增 `backend.analysis.theme_support`，输出 `ThemeCandidateSupport`。
  - `snapshot_stock_rows/snapshot_sector_rows/backtest_signals` 新增题材列。
  - SQLite 初始化增加 idempotent 迁移，补齐旧库缺失列。
  - repository、Supabase 同构映射、JSON compaction 映射已同步。
  - `RankTrendPythonEngine.replay()` 带出股票题材摘要。
  - `BaseStrategy` 默认追加题材解释和风险，不改执行；`useThemeFactorForExecution=true` 时启用高支持加置信度和拥挤风险降级。
  - `.\.venv\Scripts\python.exe -m pytest tests/test_theme_support.py tests/test_quant_board.py::test_cli_run_ranktrend_exposes_ui_backtest_parameters`：通过。
  - `.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py::test_snapshot_detail_read_apis_use_sqlite`：通过。
- QuantBoard 前端：
  - 回测表单新增 `useThemeFactorForExecution`，默认关闭。
  - `npm run build`：通过。
- 全量验证：
  - `pnpm test`：通过，24 个测试文件、174 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest`：通过，67 个测试通过。
  - `cd quant-board\frontend; npm run build`：通过。

## 2026-05-05 题材模块 V2 review 修复

- 使用 `receiving-code-review` 流程核对外部审查报告。
- 已修复：
  - Supabase 同构映射保留 `themeRole/rotationState` 的显式空字符串，不再被 snake_case fallback 覆盖。
  - QuantBoard `theme_support` 题材名匹配增加规范化和长度比例约束，避免“电力”误匹配“电力设备”。
  - Dragon Board 快照股票题材摘要不再盲取 `themes[0]`，改按 `themeContribution/heatScore/exposureWeight` 选择主題材。
  - `SnapshotSectorRow` 稳定题材列在顶层字段和 legacy `metadata.themeFactor` 同时存在时，以顶层稳定字段为准。
- 已核对：
  - `_apply_column_migrations()` 当前只忽略 SQLite duplicate column，其他 `OperationalError` 会重新抛出，不存在静默吞掉所有迁移失败的问题；新增幂等迁移测试固化行为。
  - `cooling` 分支保留为合同前向兼容，虽然当前 TS factor engine 暂不产出该状态。
- 验证：
  - `pnpm exec vitest run src/services/snapshot/__tests__/themeFactorProjection.test.ts`：通过，6 个测试通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_support.py`：通过，10 个测试通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py::test_supabase_theme_string_fields_preserve_explicit_empty_values`：通过。
  - `pnpm test`：通过，24 个测试文件、176 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest`：通过，71 个测试通过。

## 2026-05-05 题材模块 V2 更新 review 核对

- 更新版外部 review 中两项仍引用旧代码：
  - `_apply_column_migrations()` 当前不是 `except Exception: pass`，只忽略 SQLite duplicate column，其他迁移失败会抛出；已有幂等测试。
  - `_find_sector_factor()` 当前已移除 `name in theme_name` 双向子串匹配，改为 `_is_same_theme_name()` 规范化匹配；已有“电力/电力设备”边界测试。
- 本次继续修复：
  - TS `ThemeFactorEngine.rotationState()` 现在会在 `marketPhase=distribution/falling` 且题材处于 `outflowThemes` 时产出 `cooling`，让 TS 合同与 Python 侧 `cooling` 风险扣分分支对齐。
  - 新增 `ThemeFactorEngine` 测试覆盖 cooling 产出。
- 验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeFactorEngine.test.ts src/services/snapshot/__tests__/themeFactorProjection.test.ts`：通过，12 个测试通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_support.py`：通过，10 个测试通过。
  - `pnpm test`：通过，24 个测试文件、177 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest`：通过，71 个测试通过。

## 2026-05-05 题材模块 V3 启动与实施

- 用户要求实施《题材模块优化升级方案 V3》。
- 已新增 `task_plan_v3.md`。
- TDD 红灯：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts` 初始失败，原因是 `ThemeRuntimeStore` 等 V3 模块尚不存在。
- 已新增/修改：
  - `src/services/theme/types.ts` 增加 `ThemeEvent/ThemeRuntimeSnapshot/ThemeRefreshOptions`。
  - 新增 `ThemeRuntimeStore.ts`、`ThemeRotationEngine.ts`、`ThemeAlertEngine.ts`。
  - 新增 `ThemeRepository.ts`、`JxbkThemeFeed.ts`、`ThemeCorrelationEngine.ts` 作为领域边界。
  - `ThemeFacade.ts` 新增 `refresh/getRotationSummary/getThemeEvents/getHotThemesCompat/getThemeDetailCompat/getThemeStocksCompat`，并挂载 `window.themeFacade`。
  - `rotationService.analyzeAll()` 优先委托 `themeFacade.refresh()`，旧逻辑保留为 fallback。
  - `alertService.checkAll()` 改为消费 `ThemeEvent` + 个股预警，题材预警事件由 `ThemeAlertEngine` 生成。
  - `ThemeCorrelationAnalyzer.ts` 去掉 `@ts-nocheck`，主路径委托 `ThemeCorrelationEngine`。
  - `main.ts` 显式挂载 `window.themeFacade`。
  - `DragonReview` 的 `BattlefieldBuilder` 改为从 `themeFacade` 读取题材因子、轮动摘要和个股暴露作为战场种子。
- 已验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts`：通过，5 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `pnpm test -- src/services/theme src/services/snapshot src/services/hotness`：通过，13 个测试文件、66 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
  - `pnpm test`：通过，25 个测试文件、182 个测试通过。
  - 最终重跑 `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts`：通过，5 个测试通过。
  - 最终重跑 `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - 最终重跑 `pnpm test`：通过，25 个测试文件、182 个测试通过。
- 额外修复：
  - `ThemeDataService` 自动加载限制到浏览器 IndexedDB 环境，避免 Vitest/Node 导入 facade 时触发 IndexedDB 和相对路径 fetch 噪音。

## 2026-05-05 题材模块 V3 review 修复

- 使用 `receiving-code-review` 流程核对外部审查报告。
- 已修复：
  - `alertService.checkAll()` 恢复旧板块预警与新 `ThemeEvent` 并行，避免批量涨停/资金/强度/放量板块预警失活。
  - `ThemeRuntimeStore` 对 `rotationSummary` 做结构化克隆，避免消费者修改快照污染内部状态。
  - `BattlefieldBuilder` 改用 `ThemeExposureProjection.byTheme.get(themeId)`，避免按题材查询时遍历全部股票 exposure。
  - 题材事件到旧 `AlertType` 的映射调整为更贴近语义的现有类型。
  - `ThemeAlertEngine` fatal quality 阻断业务事件处补充注释。
  - `ThemeFacade` 不再自挂载 `window.themeFacade`，统一由 `main.ts` 挂载。
- 已保留：
  - `rotationService` 旧计算逻辑作为 V3 rollout 兼容 fallback，并加 deprecated fallback 注释，暂不删除。
- 新增测试：
  - `src/services/__tests__/alertService.test.ts` 覆盖 `checkAll()` 同时保留 legacy block alerts。
  - 扩展 `ThemeV3Engines.test.ts` 覆盖 `rotationSummary` 快照不可变。
- 验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeV3Engines.test.ts src/services/__tests__/alertService.test.ts`：通过，2 个测试文件、6 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。

## 2026-05-05 题材模块 V5 启动与实施

- 用户要求实施《题材模块优化升级方案 V5：运行态编排统一与旧服务退场》。
- 已新增 `task_plan_v5.md`。
- 已新增：
  - `src/services/theme/ThemeRuntimeCoordinator.ts`：统一编排 factor、exposure、rotation、event、quality summary 和 stock sync。
  - `src/services/theme/ThemeLegacyAlertAdapter.ts`：把 legacy block alert 规则迁入题材模块，输出标准 `ThemeEvent`。
  - `src/services/theme/ThemeSyncAdapter.ts`：供 `RefreshCoordinator/ConsistencyManager` 显式调用题材运行态同步。
- 已修改：
  - `ThemeFacade.refresh/refreshJxbkAndFactors/refreshRuntime` 委托 runtime coordinator。
  - `ThemeRuntimeStore/types` 增加 `inputSignature/factorVersion/eventVersion/qualitySummary/refreshSource/changedFields`。
  - `dataLoader` 不再调用 `sectorAnalyzer.triggerHeatCalculation()/syncThemesToStocks()`。
  - `RefreshCoordinator` 增加 `themeRuntime` 任务，后续龙息、复盘、算法依赖改为 `themeRuntime`。
  - `AlgorithmManager` 一致性修复使用 `ThemeSyncAdapter`，不再从 `window.sectorAnalyzer` 取同步能力。
  - `alertService.checkBlocks()` 保留方法名，但 legacy block alert 生成改为消费 `ThemeLegacyAlertAdapter` 事件，保存/冷却/去重仍由 alert service 管理。
  - `ThemeCorrelationAnalyzer` 读取 JXBK stockMap 改为走 `themeFacade.getThemeStockMapCompat()`。
- 已验证：
  - `pnpm exec vitest run src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts src/services/theme/__tests__/ThemeLegacyAlertAdapter.test.ts src/services/theme/__tests__/ThemeV3Engines.test.ts src/services/__tests__/alertService.test.ts`：通过，4 个测试文件、16 个测试通过。
  - `pnpm exec vitest run src/services/theme src/services/__tests__/alertService.test.ts`：通过，6 个测试文件、25 个测试通过。
  - `pnpm exec vitest run src/services/snapshot src/services/hotness`：通过，10 个测试文件、52 个测试通过。
  - `pnpm test:ranktrend`：通过，9 个测试文件、95 个测试通过。
  - `pnpm test`：通过，28 个测试文件、193 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 题材模块 V6 启动

- 用户要求实施《题材模块优化升级方案 V6：刷新主链单一化与 Legacy 退场》。
- 本轮严格保留未提交状态，完成后交给用户 review。
- 已新增 `task_plan_v6.md`。
- 已开始执行：
  - `ThemeFacade.refreshRuntimeState()` 包装 runtime coordinator，并同步 facade 读口缓存。
  - `alertService.checkThemeEvents()` 改为消费 `themeFacade.refreshRuntime({ source: 'alertService' })`。
  - `checkBlocks()` 退为 legacy 板块快照维护，不再二次生成 legacy block event。
  - `ThemeSyncAdapter.syncThemesToStocks()` 委托 `syncData()`。
  - `sectorAnalyzer` 公开刷新/同步入口进一步委托 `themeFacade.refreshRuntime()`。
- TDD 红绿记录：
  - 新增测试后首次运行 `pnpm exec vitest run src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts src/services/__tests__/alertService.test.ts`：按预期失败，暴露 `themeFacade.refreshRuntime()` 未同步 facade 读口、`alertService` 未走统一 runtime 事件链。
  - 实现后重跑同命令：通过，2 个测试文件、7 个测试通过。

## 2026-05-05 题材模块 V8 启动

- 用户指定使用 `planning-with-files`，按仓库规则不在根目录创建过程文件，改为使用 `docs/theme-module/plans/task_plan_v8.md`、`docs/theme-module/findings.md`、`docs/theme-module/progress.md`。
- 已新增 V8 执行计划，范围限定为 IndexedDB 题材映射迁移到 QuantBoard 独立 SQLite 主库 `themeDATA.db`。
- 已完成初步代码读取：
  - `ThemeDataService` 当前正式读写仍以 IndexedDB 为中心。
  - `ThemeFacade` 依赖 `themeMapping` 的同步兼容读口，需要在切 SQLite 后保留。
  - QuantBoard 后端当前只有 snapshot/research 两套 DB，需要新增 theme DB 初始化、模型、仓库、迁移 API 和只读 API。
- 已读取 `quant-board/backend/settings.py`，当前 Settings 只有 `snapshot_database_url/research_database_url`，V8 需要新增 `theme_database_url`，默认指向 `warehouse/themeDATA.db`。
- 已确认 QuantBoard 测试目录为 `quant-board/tests/*.py`，V8 后端测试应新增到该目录。
- 后端 TDD 记录：
  - 首次运行 `.\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py -q`：按预期失败，缺少 `backend.data.theme_database`。
  - 新增 theme DB/model/repository/service 后重跑：失败于 `CREATE INDEX ix_theme_stock_mappings_stock_code` 重复，需修正模型重复索引定义。
  - 修正后 `tests/test_theme_database.py` 通过，7 个测试通过。
- 前端 TDD 记录：
  - 新增 `src/services/__tests__/ThemeDataService.test.ts` 后运行 `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts`：按预期失败，当前仍先读 IndexedDB，且 `setData()` 仍尝试写 IndexedDB。
  - 修改后 `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts` 通过，2 个测试通过。
  - 新增 `apiService.getSqliteThemeMapping()` 路由测试，首次按预期失败，随后实现并通过。
- 已实现：
  - 后端新增 `backend/data/theme_database.py`、`theme_models.py`、`theme_repository.py`、`theme_service.py`。
  - 后端新增 API：`POST /api/migrations/themes/import-json`、`GET /api/themes/mapping`、`GET /api/themes/stocks/{theme_id}`、`GET /api/themes/stocks/by-code/{code}`、`GET /api/themes/counts`。
  - `GET /api/health` 增加 `database.theme`。
  - 前端 `ThemeDataService` 正式读口切到 QuantBoard SQLite API，`setData()` 不再写 IndexedDB，后台 API 刷新只合并标签/原因。
  - `apiService` 将 `/api/themes/*` 路由到 QuantBoard 上下文。
- 已通过局部验证：
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py -q`：7 个测试通过。
  - `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts src/services/__tests__/apiService.test.ts src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts src/services/__tests__/themeLegacyAdapters.test.ts`：4 个测试文件、15 个测试通过。

## 2026-05-05 V8 code review 修复

- 已处理审查发现：
  - `ThemeRepository.get_stock_themes()` 改为合并同一股票跨题材的标签和原因，避免只保留最后一个题材。
  - `ThemeDataService.buildMapping()` 改为合并多题材股票原因，初次加载与后续 `mergeTagAndReasonData()` 行为一致。
  - 从 `ThemeDataService` 移除 IndexedDB 初始化、读、写、安全映射判断等死代码；正式服务内不再持有浏览器 IndexedDB 私有路径。
  - `GET /api/themes/mapping` 只在 API 顶层返回 `source: sqlite`，移除 mapping 内层重复 `source`。
  - `loadFromSQLiteAPI()` 移除 `{ data: ... }` 解包分支，按后端实际 `{ ok, source, mapping }` 合同解析。
- 已补测试：
  - 后端测试覆盖同一股票归属多题材时的标签/原因合并，以及 mapping 内层不再重复 `source`。
  - 前端测试覆盖多题材原因初次加载合并、畸形 SQLite 响应下 `forceRefresh()` 返回 `false` 且不污染现有映射。
  - `apiService` 测试改为显式断言 `/api/themes/mapping` 请求发送到 `http://localhost:8000`。
- 保留不改：
  - `/api/snapshots/*` 路由到 QuantBoard 是快照正式读口已迁移后的既定行为，不回退到 ingest-only。
  - `main.py` CRLF 警告暂不单独扩大改动面；如后续统一行尾，应由仓库级 `.gitattributes` 一次性治理。
- code review 修复局部验证：
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py -q`：7 个测试通过。
  - `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts src/services/__tests__/apiService.test.ts`：2 个测试文件、8 个测试通过。

## 2026-05-05 题材模块 V9 启动

- 用户要求实施《题材模块 V9：迁移校验工具化 + 题材基础读口彻底收口》。
- 已新增 `docs/theme-module/plans/task_plan_v9.md`。
- V9 范围确认：
  - 后端新增 `themeDATA.db` 只读校验 API/CLI。
  - 前端把 `sectorAnalyzer.loadSectorStocks()` 的缓存和加载职责迁入 `JxbkThemeFeed`。
  - 不改题材因子、轮动、预警算法和 UI 布局。
- 后端 TDD 记录：
  - 新增测试后首次运行 `.\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py tests/test_quant_board.py::test_cli_exposes_sync_and_migration_commands -q`：按预期失败，缺少 `cmd_verify_themes`。
  - 实现 `ThemeMigrationService.verify_mapping()`、`POST /api/migrations/themes/verify-json`、`verify-themes --path` 后，同命令通过，9 个测试通过。
- 前端 TDD 记录：
  - 新增 `JxbkThemeFeed.test.ts` 与 legacy adapter 测试后首次运行 `pnpm exec vitest run src/services/theme/__tests__/JxbkThemeFeed.test.ts src/services/__tests__/themeLegacyAdapters.test.ts`：按预期失败，缺少 `loadSectorStocks/clearSectorStockCache`。
  - 实现后同命令通过，2 个测试文件、5 个测试通过。
- 已实现：
  - `JxbkThemeFeed` 承接板块成分股加载、缓存、并发复用、失败空数组、DataLayer 写入和 runtime refresh。
  - `sectorAnalyzer.loadSectorStocks/clearCache/getStats` 改为委托 `JxbkThemeFeed`。
  - QuantBoard 文档补充题材迁移校验 API/CLI 合同。
- 静态复核：
  - `sectorAnalyzer` 已无独立 `sectorStocksCache`。
  - 成分股 API 请求集中到 `JxbkThemeFeed.loadSectorStocks()`。
- 完整验证中发现：
  - `vue-tsc` 首次失败于 `JxbkThemeFeed.ts` filter 回调参数隐式 `any`，已补 `JxbkStockData` 类型标注。

## 2026-05-05 V9 code review 修复

- 已处理审查发现：
  - `sectorAnalyzer.forceRefreshJxbk()` 增加 `state.destroyed` 检查，与 `runUpdate/forceRefresh/syncData` 对齐。
  - `JxbkThemeFeed.normalizeStockRow()` 对 `item[100]` 增加 `Array.isArray` 防护，异常格式不再按字符串字符解析。
  - `refreshBlocks()` 的 ST 过滤改为 `ST/*ST` 前缀判断，避免误杀普通名称中包含 `ST` 的板块。
- 已补测试：
  - `sectorAnalyzer.forceRefreshJxbk()` 在 destroy 后不触发 runtime refresh。
  - `JxbkThemeFeed.loadSectorStocks()` 收到畸形 `item[100]` 时不解析出脏 blocks/价格。
- 局部验证：
  - `pnpm exec vitest run src/services/theme/__tests__/JxbkThemeFeed.test.ts src/services/__tests__/themeLegacyAdapters.test.ts`：2 个测试文件、7 个测试通过。

## 2026-05-05 题材模块 V10 启动

- 用户要求把 IndexedDB 的 `ThemeDataDB` 数据迁移到 SQLite `themeDATA.db`。
- 已新增 `docs/theme-module/plans/task_plan_v10.md`。
- 初步发现：
  - 工作区干净。
  - 仓库内未发现现成的 `ThemeDataDB` 导出 JSON。
  - 浏览器候选 IndexedDB 目录存在：Chrome `http_localhost_5173.indexeddb.leveldb` 与 `http_127.0.0.1_5173.indexeddb.leveldb`。
  - `public/data/theme_base_mapping.json` 和 `dist/data/theme_base_mapping.json` 存在，但它们是静态映射文件，不一定等同于 IndexedDB 当前值。
- 用户确认 V10 源应使用 Chrome `http_localhost_5173.indexeddb.leveldb`。
- 迁移执行记录：
  - `http_localhost_5173.indexeddb.leveldb` 中 `ThemeDataDB/theme_mapping/theme_data` 是 Blink IndexedDB value wrapper；完整 payload 位于同名 `http_localhost_5173.indexeddb.blob`。
  - 已从 blob `2/00/1d` 解码出 `theme_data`，版本与更新时间均为 `2026-05-04T10:51:20.267Z`。
  - 已生成迁移导入文件：`quant-board/data/staging/theme_v10_http_localhost_5173_ThemeDataDB_import.json`。
  - 导入目标：`quant-board/data/warehouse/themeDATA.db`。
  - 首次导入结果：新增 237 个题材、12215 条题材-股票关系，去重股票 4166 只。
  - 再次导入结果：新增 0 个题材、0 条映射，更新 237 个题材，确认导入幂等。
  - `verify-themes --path data\staging\theme_v10_http_localhost_5173_ThemeDataDB_import.json` 返回 `ok=true`，expected/actual 均为 237/12215/4166。
  - 基础读口抽样：`DeepSeek概念(302)` 返回 69 只股票；`300033` 可反查到 `大金融`，标签和原因来自 SQLite。

## 2026-05-05 题材模块 V11 启动

- 用户要求制定下一步《题材分析模块优化重构方案 V11》，目标是严格收口、清理兼容层、完全切断对 IndexedDB 的依赖。
- 已复核题材相关源码：
  - `ThemeDataService` 正式映射已走 `apiService.getSqliteThemeMapping()`，未发现 `ThemeDataDB` IndexedDB 正式读写函数。
  - 当前残留为本地静态 JSON fallback、外部 `/api/themes/batch` 增量刷新、自动定时刷新，以及 `sectorAnalyzer` 对 `themeMapping` 私有 Map 的直接读取。
  - `sectorAnalyzer.loadSectorStocks()` 已委托 `JxbkThemeFeed`，但 `sectorAnalyzer` 仍作为旧公开 adapter 暴露。
  - `themeFacade` 仍暴露多组 `Compat` 读口，多个面板仍在调用。
- 已新增 `docs/theme-module/plans/task_plan_v11.md`，将 V11 分为 SQLite-only、仓库命名收口、`sectorAnalyzer` 私有依赖清理、兼容层收窄、后端合同检查和文档验收六个阶段。

## 2026-05-05 题材模块 V11 实施

- 已按 TDD 补充前端红灯测试：
  - SQLite 失败时不请求 `/data/theme_base_mapping.json` 或 `/api/themes/batch`。
  - `ThemeDataService.getLoadStatus()` 返回 SQLite 状态。
  - `sectorAnalyzer` 通过 `themeRepository` 公开 getter 同步标签和原因。
- 已实现：
  - `ThemeDataService` 移除本地 JSON fallback、批量 API 增量刷新和浏览器定时刷新入口。
  - `ThemeRepository` 增加 `loadThemeBase/getThemes/refreshThemeBase/getThemeBaseStatus` 等正式入口。
  - `ThemeFacade/ThemeRuntimeCoordinator/sectorAnalyzer` 改用 `themeRepository`，并新增 `getJxbkBlocks/getThemeStockMap/getHotThemes/getThemeDetail/getThemeStocks` 正式别名。
  - 面板和服务调用迁到正式 facade 方法；旧 `Compat` wrapper 保留但不再被业务代码调用。
  - 后端测试补强 `GET /api/themes/mapping` 标签/原因合同和 `GET /api/themes/counts` 完整字段合同。
- 局部验证：
  - `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts src/services/__tests__/themeLegacyAdapters.test.ts`：通过，2 个测试文件、10 个测试通过。
  - `cd quant-board; .\.venv\Scripts\python.exe -m pytest tests/test_theme_database.py -q`：通过，8 个测试通过。
  - `pnpm exec vitest run src/services/__tests__/ThemeDataService.test.ts src/services/__tests__/themeLegacyAdapters.test.ts src/services/theme/__tests__/ThemeRuntimeCoordinator.test.ts src/services/__tests__/alertService.test.ts src/services/dragon/__tests__/ContextBuilder.test.ts src/services/theme/__tests__/ThemeV3Engines.test.ts`：通过，6 个测试文件、28 个测试通过。
  - `pnpm test`：通过，33 个测试文件、212 个测试通过。
  - `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`：通过。

## 2026-05-05 题材模块 V12 启动

- 用户要求按《ThemeTrend 量化研究平台化》方案进入实施，并开启多任务协同模式。
- 当前执行原则：
  - Dragon Board 根项目继续只做实时看板和题材 runtime，不新增回测平台。
  - QuantBoard 承接 ThemeTrend Python 引擎、题材研究数据、回测、优化、API/CLI 和报告。
  - `themeDATA.db` 继续只作为题材基础映射库，不承载运行态因子或研究结果。
  - 默认 `snapshot_type=half_hour`；`quarter_hour` 只能显式选择。
- 已启动并行协作分工：
  - Worker A：负责 `quant-board/backend/analysis/theme_trend.py` 与 `quant-board/tests/test_theme_trend_engine.py`，先落地 Python ThemeTrend 引擎和 TDD 用例。
  - Worker B：负责 V12 文档合同，包括 `docs/theme-module/plans/task_plan_v12.md` 以及 QuantBoard API/架构/协作文档的 ThemeTrend 入口说明。
  - 主会话：负责总集成、服务/API/CLI 接入、progress 维护和最终验证。
- 初步实现策略：
  - 先交付可运行的后端核心 MVP：ThemeTrend 引擎、质量门禁、题材策略回测入口和优化入口骨架。
  - 复用现有 `BacktestService`、`Repository`、`BacktestRun`、归一化 signals/trades/equity/quality 表，不为 V12 第一刀另起独立回测存储链。
  - 后续再扩展研究归一化表 `theme_factor_frames/theme_stock_exposures/theme_signals/theme_quality_reports`。

## 2026-05-05 V12 Phase 1 实施

- 全面接手 V12，从 Phase 1（研究合同与数据层）开始实施。
- 已在 `quant-board/backend/analysis/theme_trend.py` 新增 5 个正式数据合同 dataclass：
  - `ThemeFactorFrame`：题材因子帧（11 个因子字段 + 生命周期 + 质量标记 + 完整溯源链）
  - `ThemeStockExposureFrame`：股票题材暴露帧（角色/得分/权重/贡献/风险惩罚 + 溯源链）
  - `ThemeSignalRow`：题材信号行（信号/风险/生命周期/得分 + 溯源链）
  - `ThemeQualityReport`：质量报告（passed/severity/researchGrade/issues/warnings/stats + 溯源链）
  - `ThemeTrendResult`：引擎输出聚合容器
- 已在 `quant-board/backend/data/models.py` 新增 4 张 research SQLite 表模型：
  - `ThemeFactorFrameModel` → `theme_factor_frames`
  - `ThemeStockExposureModel` → `theme_stock_exposures`
  - `ThemeSignalModel` → `theme_signals`
  - `ThemeQualityReportModel` → `theme_quality_reports`
- 每张表均保留完整溯源链：`dataset_id`、`snapshot_id`、`snapshot_type`、`trading_date`、`slot_time`、`strategy_version`、`config_hash`、`random_seed`。
- 已新增 `quant-board/backend/data/theme_research_repository.py`：
  - `ThemeResearchRepository` 提供 4 张表的 CRUD、查询过滤和批量删除。
  - JSON 字段序列化复用现有 `json_codec` 模块。
  - 写入使用 ResearchBase 绑定 `quant_board_research.db`，不进入 Supabase 链路。
- 已新增 `quant-board/backend/services/theme_research_service.py`：
  - `build_theme_research()` 从正式快照事实表回放构建题材研究帧。
  - 逐帧调用 `ThemeTrendPythonEngine`，按帧注入元数据，写入研究表。
  - 合并多帧质量报告生成数据集级 `ThemeQualityReport`。
  - 不修改 `themeDATA.db`，不写入 Supabase。
- 已新增 `quant-board/tests/test_theme_research.py`：19 个测试覆盖：
  - 空帧阻塞、低样本降级、时间乱序、非法数值、缺股票/题材数据
  - 引擎输出完整字段合同验证
  - 默认 `half_hour` 生效
  - repository CRUD 端到端（factor/exposure/signal/quality + 删除 + code 过滤）
  - config_hash 一致性
- 已修正 `quant-board/tests/test_theme_trend_storage.py`（Worker B 旧 TDD 桩）对齐实际 API。
- 已更新 QuantBoard 文档：
  - `architecture.md`：ThemeTrend 研究结果段改为描述已落地的 4 张表
  - `AI_COLLABORATION.md`：记录 Phase 1 完成状态
- 验证结果：
  - `test_theme_trend_engine.py`：5 通过
  - `test_theme_research.py`：19 通过
  - `test_theme_trend_storage.py`：10 通过
  - `test_theme_support.py`：10 通过
  - `test_theme_database.py`：8 通过
  - 全量 pytest：116 通过，4 失败（pre-existing Phase 3 API/CLI TDD 前瞻测试）
- 当前原则延续：
  - Dragon Board 不新增回测平台。
  - `themeDATA.db` 只承载题材基础映射。
  - Phase 1 研究结果只进入 research SQLite local-only 链路。

## 2026-05-05 V12 Phase 1 Code Review 修复

处理了外部 code review 报告的全部 High/Medium 级别发现：

**High:**
1. `_empty_result` 补齐 `strategyVersion/factorVersion/signalVersion` 三个版本字段，与正常路径合同一致。
2. `build_theme_research` 去除双重 `replay()` + `replay_typed()` 调用，每个帧只执行一次 `replay_typed()`，质量报告从 `typed.qualityReport.to_dict()` 获取。
3. 写入路径增加整体 try/except 保护，`save_*` 内部已有各表级 rollback。
4. `build_theme_research` docstring 新增"已知限制"段，记录逐帧回放下生命周期推断的局限性。

**Medium:**
5. `_merge_quality_reports` 的 `themeCount/stockCount` 改用 `set` 去重（跨帧按 `themeId/code` 收集），不再使用整数除法截断。
6. `ThemeTrendPythonEngine.replay()` 中 `_build_exposure` 返回 None 时计数 `unmatched_stocks`，>0 时向质量报告注入 `unmatched_theme_stock` 警告。有 theme 名但匹配不上 sector 才计数；无 theme 名的股票不计入。
7. 新增 `test_large_json_field_roundtrips_through_compression` 测试（100 条 × ~70 字符 = ~7KB，超过 4KB 压缩阈值），验证 JSON 压缩/解压 round-trip。
10. `RESEARCH_JSON_FIELD_MAP` 中 `ThemeSignalModel: ()` 添加注释"信号表无 JSON 列，所有字段均为标量"。

**Low:**
- Low #8 (_frame 复写)、#9 (测试 session 注入)、#11 (文档 vs 测试合同) 记录为已知，暂不修改。Low #8 涉及三份测试文件重构，#9 沿用 `test_theme_database.py` 既存模式，#11 的 Phase 3 前瞻测试属于预期失败的 TDD 红灯。

- 新增测试 `test_unmatched_theme_stock_produces_warning` 和 `test_unmatched_theme_stock_not_added_for_empty_theme_name`，覆盖有主题名不匹配和无主题名两种边界。
- 验证结果：58 题材测试通过，全量 92 通过（排除 test_quant_board.py 中 4 个 Phase 3 TDD 前瞻测试）。
