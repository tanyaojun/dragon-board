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
