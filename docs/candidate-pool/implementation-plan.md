# 候选池工作台第一批实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans or inline TDD execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付第一批可用候选池闭环：右键行情股票加入候选池，自动生成规则解释型分析，候选池面板可查看和推进状态。

**Architecture:** 前端新增 `src/services/candidate/**` 服务层，`CandidateAnalysisService` 负责确定性规则分析，`CandidateJournalService` 负责 `/api/journal` 候选 CRUD。`DataTable.vue` 只接右键入口，`CandidatePoolPanel.vue` 负责展示和状态流转，正式存储继续使用 QuantBoard journal API。

**Tech Stack:** Vue 3 + TypeScript + Pinia + Vite + Vitest, QuantBoard journal HTTP API

---

## File Structure

- Create `src/services/candidate/types.ts`
  - 候选分析、候选记录、API payload 类型。
- Create `src/services/candidate/CandidateAnalysisService.ts`
  - 规则评分、文案生成、信号快照构建。
- Create `src/services/candidate/CandidateJournalService.ts`
  - journal API 封装、从股票入池、重复记录检测、状态更新。
- Create `src/services/candidate/__tests__/CandidateAnalysisService.test.ts`
  - 锁定评分、风险、文案行为。
- Create `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - 锁定入池 payload、重复检测、状态更新行为。
- Modify `src/components/common/DataTable.vue`
  - 右键菜单新增“加入候选池”，调用 journal service。
- Modify `src/components/common/__tests__/DataTable.test.ts`
  - 源码级测试锁定右键入口和组件职责。
- Create `src/components/panels/CandidatePoolPanel.vue`
  - 简版候选池工作台。
- Modify `src/App.vue`
  - 下拉菜单接入候选池面板。
- Modify `docs/candidate-pool/progress.md`
  - 更新执行进度。

## Task 1: CandidateAnalysisService

**Files:**
- Create: `src/services/candidate/types.ts`
- Create: `src/services/candidate/CandidateAnalysisService.ts`
- Test: `src/services/candidate/__tests__/CandidateAnalysisService.test.ts`

- [x] Step 1: 写失败测试，覆盖 A_MAIN + 主线题材 + 正资金流生成高分候选。
- [x] Step 2: 运行测试确认因模块不存在失败。
- [x] Step 3: 实现最小类型和规则分析。
- [x] Step 4: 运行测试确认通过。
- [x] Step 5: 增加拥挤/退出风险测试。
- [x] Step 6: 实现风险规则并确认通过。

## Task 2: CandidateJournalService

**Files:**
- Create: `src/services/candidate/CandidateJournalService.ts`
- Test: `src/services/candidate/__tests__/CandidateJournalService.test.ts`

- [x] Step 1: 写失败测试，覆盖从股票创建候选 payload。
- [x] Step 2: 运行测试确认失败。
- [x] Step 3: 实现 journal API 封装和入池方法。
- [x] Step 4: 运行测试确认通过。
- [x] Step 5: 增加重复未复盘候选检测测试。
- [x] Step 6: 实现重复检测并确认通过。

## Task 3: DataTable 右键入口

**Files:**
- Modify: `src/components/common/DataTable.vue`
- Modify: `src/components/common/__tests__/DataTable.test.ts`

- [x] Step 1: 写失败测试，要求右键菜单包含“加入候选池”并调用候选服务。
- [x] Step 2: 运行测试确认失败。
- [x] Step 3: 修改 DataTable 右键菜单和处理函数。
- [x] Step 4: 运行测试确认通过。

## Task 4: CandidatePoolPanel

**Files:**
- Create: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/App.vue`

- [x] Step 1: 新增面板源码级测试或类型检查目标。
- [x] Step 2: 实现简版面板：列表、过滤、详情、状态推进。
- [x] Step 3: App 下拉菜单接入“候选池”。
- [x] Step 4: 运行 vue-tsc 确认通过。

## Task 5: Verification

- [x] Run `pnpm exec vitest run src/services/candidate/__tests__/*.test.ts src/components/common/__tests__/DataTable.test.ts`
- [x] Run `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`
- [x] Run `pnpm build`
- [x] 更新 `docs/candidate-pool/progress.md`

## Guardrails

- 不修改刷新机制相关文件：`src/services/RefreshManager.ts`、`src/services/RefreshCoordinator.ts`、`src/services/refresh/**`、`docs/refresh-mechanism/**`。
- 不把候选生命周期写进 `favorite_data`。
- 不接外部 LLM。
- 不把候选评分描述为买入建议。
