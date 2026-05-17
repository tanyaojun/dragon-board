# 候选池工作台进度记录

## Session: 2026-05-17

### Phase 1: 需求与现状固化

- **Status:** complete
- **Started:** 2026-05-17 10:10:25 +08:00
- Actions taken:
  - 读取 `planning-with-files` skill。
  - 执行 session catchup 检查，无输出。
  - 确认用户选择：方案 B（自选股 + 候选池分层）。
  - 确认用户选择：方案 A（规则解释型 AI 分析）。
  - 梳理自选股、右键菜单、TradeJournalPanel、journal API、Mongo repository、RankTrend、ThemeTrend、DragonReview、DragonBreath 相关代码。
- Files created/modified:
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/findings.md`
  - `docs/candidate-pool/progress.md`
  - `docs/candidate-pool/candidate-pool-workbench-design.md`

### Phase 2: 方案设计

- **Status:** complete
- Actions taken:
  - 设计候选池工作台版方案。
  - 明确自选股与候选池的边界。
  - 明确规则解释型分析引擎的输入、输出和评分维度。
  - 明确右键入口、候选池面板、状态流转、存储/API、测试验收和分阶段实施建议。
- Files created/modified:
  - `docs/candidate-pool/candidate-pool-workbench-design.md`

### Phase 3: 第一批 MVP 实施计划

- **Status:** complete
- Actions taken:
  - 写入第一批实现计划，明确服务层、右键入口、候选池面板和验证命令。
  - 确认本批不接外部 LLM，不写入自选股存储，不扩大刷新机制改动。
- Files created/modified:
  - `docs/candidate-pool/implementation-plan.md`

### Phase 4: 第一批 MVP 实施

- **Status:** complete
- Actions taken:
  - 新增 `CandidateAnalysisService`，生成规则评分、等级、入池理由、交易假设、买入前提、失效条件、风险提示和 `signalsSnapshot.candidateAnalysis`。
  - 新增 `CandidateJournalService`，负责候选列表、右键股票入池、重复未复盘候选检测、状态更新和自选股同步添加。
  - 行情列表右键菜单新增“加入候选池”，组件层只调用候选服务，不直接拼 journal API。
  - 新增 `CandidatePoolPanel`，支持候选列表、状态过滤、规则分析详情和状态推进。
  - App 下拉菜单新增“候选池”，保留原自选股和交易日记入口。
  - 补齐 QuantBoard journal 创建接口 `review_tags` 字段，避免创建候选时丢失分级/题材标签。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateAnalysisService.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateAnalysisService.test.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/common/DataTable.vue`
  - `src/components/common/__tests__/DataTable.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `src/App.vue`
  - `quant-board/backend/api/journal_routes.py`
  - `quant-board/docs/api-cli.md`
  - `quant-board/tests/test_trade_journal.py`

### Phase 5: Review 修复

- **Status:** complete
- Actions taken:
  - `CandidateJournalService.addCandidateFromStock` 增加股票代码校验，避免空代码候选误查全量 journal 或写入无效记录。
  - `CandidatePoolPanel.updateStatus` 增加失败提示和更新中禁用状态，后端不可用或状态更新失败时不再静默失败。
  - 复核 `RefreshManager` 当前实现，确认已不再通过全局 scheduler `stopAll()` 误停共享刷新任务。
- Files created/modified:
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

### Phase 6: 候选池工作台可用化

- **Status:** complete
- Actions taken:
  - `CandidateJournalService` 新增 `getOpenCandidateForStock`，供行情右键菜单识别已入池股票。
  - `CandidateJournalService` 新增 `reanalyzeCandidate`，用最新行情上下文重算候选分析，并对比入池快照生成分数变化、状态标签和原因。
  - 候选池面板新增统计概览：今日新增、观察/候选、触发跟踪、待复盘、平均评分、当前风险。
  - 候选池详情新增“入池快照 / 当前重分析 / 状态变化”对比视图，并展示当前评分拆解、条件变化原因和当前风险。
  - 行情列表右键菜单新增已入池识别：未入池显示“加入候选池”，已入池显示“查看候选详情”。
  - 右键新增候选成功后自动打开候选池并定位新记录；候选池已打开时会重新加载并选中新候选。
  - `App.vue` 增加 `candidate-pool:open` 事件桥接，统一由候选池面板处理定位。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/common/DataTable.vue`
  - `src/components/common/__tests__/DataTable.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `src/App.vue`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

### Phase 7: 交易假设编辑与复盘闭环

- **Status:** complete
- Actions taken:
  - `CandidateJournalService` 新增 `updateCandidateThesis`，封装入池理由、交易假设、买入前提、失效条件、人工决策和未执行原因的轻量保存。
  - `CandidateJournalService` 新增 `writeBackCurrentAnalysis`，允许用户把当前重分析结果写回 `signalsSnapshot.candidateAnalysis` 与 `reviewTags`。
  - `CandidateJournalService` 新增 `saveCandidateReview`，保存复盘结果、模型结果、执行结果和复盘结论，并将候选标记为已复盘。
  - 候选池详情新增“假设编辑”和“复盘闭环”工作区，替代旧面板式手工字段堆叠。
  - 候选池筛选新增“待复盘”，统计新增触发率、失效率、复盘胜率。
  - 修复外部右键打开指定候选时被旧状态筛选挡住的问题，打开目标候选会切到“全部状态”并重载定位。
  - 修复复盘结果仍为 `pending` 时被误标记为 `reviewed` 的问题，只有明确复盘结果才推进为已复盘。
- Files created/modified:
  - `src/services/candidate/types.ts`
  - `src/services/candidate/CandidateJournalService.ts`
  - `src/services/candidate/__tests__/CandidateJournalService.test.ts`
  - `src/components/panels/CandidatePoolPanel.vue`
  - `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - `docs/candidate-pool/task_plan.md`
  - `docs/candidate-pool/progress.md`

## Test Results

| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| 文档目录检查 | `docs/candidate-pool/` | 业务专题目录存在 | 已创建 | 通过 |
| 候选池前端单元测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 9 tests passed | 9 tests passed | 通过 |
| 前端类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Journal 后端契约测试 | `.\.venv\Scripts\python.exe -m pytest tests/test_trade_journal.py` | 4 passed | 4 passed | 通过 |
| Review 修复回归测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 5 tests passed | 5 tests passed | 通过 |
| Phase 6 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增行为测试失败 | 5 failed / 5 passed，失败点为缺少公开查询、重分析、统计和事件桥接 | 通过 |
| Phase 6 候选池定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 12 tests passed | 12 tests passed | 通过 |
| Phase 6 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 6 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 7 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增行为测试失败 | 4 failed / 6 passed，失败点为缺少 `updateCandidateThesis`、`writeBackCurrentAnalysis`、`saveCandidateReview` 和面板入口 | 通过 |
| Phase 7 定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 10 tests passed | 10 tests passed | 通过 |
| Phase 7 候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 15 tests passed | 15 tests passed | 通过 |
| Phase 7 类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 7 前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |
| Phase 7 Review 修复 RED 验证 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 新增回归测试失败 | 2 failed / 10 passed，失败点为 pending 复盘误提交 `status: reviewed`、外部打开候选未清空筛选 | 通过 |
| Phase 7 Review 修复定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 12 tests passed | 12 tests passed | 通过 |
| Phase 7 Review 修复候选池完整定向测试 | `pnpm exec vitest run src/services/candidate/__tests__/CandidateAnalysisService.test.ts src/services/candidate/__tests__/CandidateJournalService.test.ts src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot` | 17 tests passed | 17 tests passed | 通过 |
| Phase 7 Review 修复类型检查 | `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` | exit 0 | exit 0 | 通过 |
| Phase 7 Review 修复前端构建 | `pnpm build` | exit 0 | exit 0，存在既有 ThemeFacade 动静态混用 warning | 通过 |

## Error Log

| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 无 | 无 | 1 | 无 |
| 2026-05-17 | `CandidateStockLike` 带索引签名导致 `MergedStock` 类型不可赋值 | 运行 `vue-tsc` 定位到 `CandidateJournalService.ts` | 改为交叉类型 `& Record<string, any>` 后类型检查通过 |
| 2026-05-17 | journal 创建接口不接收 `review_tags`，候选标签会丢失 | 阅读 `quant-board/backend/api/journal_routes.py` 和模型契约 | 为 `CreateJournalEntryRequest` 补 `review_tags` 并写后端测试 |
| 2026-05-17 | 空股票代码可能误查全量 journal 或写入无效候选 | 先补失败测试 | 入池前校验 `stockCode`，无效则抛出 `候选股代码无效` |
| 2026-05-17 | 状态推进失败时面板无反馈 | 先补失败测试 | `updateStatus` 加 try/catch、错误提示和 `updatingStatus` 禁用 |
| 2026-05-17 | 候选池已打开时，右键新增候选可能无法定位到新记录 | 定向测试后人工复核事件流 | 入池事件带 `candidateId`，面板找不到目标时重新加载列表并再次定位 |
| 2026-05-17 | Phase 7 面板与服务缺少轻量编辑、写回分析和复盘保存合同 | 先补 RED 测试 | 新增候选服务更新 API，并在候选池详情页接入轻量表单 |
| 2026-05-17 | 外部打开指定候选可能被候选池旧状态筛选挡住 | 先补 RED 测试 | `openCandidate` 在指定目标时切到“全部状态”并重载定位 |
| 2026-05-17 | 保存 pending 复盘会误把候选标为 reviewed | 先补 RED 测试 | `saveCandidateReview` 仅在复盘结果非 pending 时提交 `status: reviewed` |

## 5-Question Reboot Check

| Question | Answer |
|----------|--------|
| Where am I? | 已完成候选池 Phase 7 交易假设编辑与复盘闭环 |
| Where am I going? | 下一步可做桌面 UI 视觉验证和端到端交互打磨 |
| What's the goal? | 将手工候选/交易假设升级为候选池工作台 |
| What have I learned? | 见 `findings.md` |
| What have I done? | 已实现右键入池、规则分析、候选池面板、状态推进、journal 标签入库契约、统计概览、当前重分析、已入池识别、候选详情定位、假设编辑、分析写回、复盘保存和基础复盘统计 |
