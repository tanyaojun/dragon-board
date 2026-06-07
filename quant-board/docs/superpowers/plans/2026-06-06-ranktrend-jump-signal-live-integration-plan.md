# RankTrend 跳跃检测实盘接入——实施计划

**Spec:** `quant-board/docs/superpowers/specs/2026-06-06-ranktrend-jump-signal-live-integration-design.md`

**目标：** 将 Python 端验证过的内生阈值跳跃检测策略接入前端实盘展示。TypeScript 移植算法 → 集成信号刷新链路 → DataTable 新增信号列。

**涉及目录：** `src/services/rankTrend/`、`src/services/dataLoader/`、`src/components/common/`

---

## Phase 1: 跳跃检测 TypeScript 移植

### Task 1: 移植 `detectRankJumps()` 纯函数

**Files:**
- Create: `src/services/rankTrend/jumpDetector.ts`
- Create: `src/services/rankTrend/__tests__/jumpDetector.test.ts`

- [-] **Step 1: 写测试（RED）** — 12 个用例：样本不足、未达阈值、surge 触发、collapse 触发、sustained 判定、震荡过滤、delta 参数、置信度、空序列、单元素、rankMagnitude、参考点重置（本地草稿完成，待提交）
- [-] **Step 2: 实现（GREEN）** — ~90 行，1:1 对齐 Python 算法（本地草稿完成，待提交）
- [-] **Step 3: 验证** — 12/12 通过（`npx vitest run src/services/rankTrend/__tests__/jumpDetector.test.ts`，2026-06-06 13:55 通过）

---

## Phase 2: 入场/出场条件服务

### Task 2: 创建 `jumpSignalService.ts`

**Files:**
- Create: `src/services/rankTrend/jumpSignalService.ts`

- [-] **Step 1: 实现入场条件** `checkEntryConditions(stock, rankTrend, jump)` — 六条件 AND（本地草稿完成，待提交）
- [-] **Step 2: 实现出场条件** `checkExitConditions(stock, rankTrend, jump, isInFrame)` — 四条件 OR（本地草稿完成，待提交）
- [-] **Step 3: 实现聚合函数** `evaluateJumpSignal(stock, rankTrend, percentiles, isInFrame)` — 组合检测+条件判断（本地草稿完成，待提交）
- [ ] **Step 4: 验证** — `pnpm exec vue-tsc --noEmit` 通过

---

## Phase 3: 集成到信号刷新链路

### Task 3: RankTrendAnalyzer 新增 `getCachedPercentiles()`

**Files:**
- Modify: `src/services/RankTrendAnalyzer.ts`

- [-] **Step 1: 添加公开方法** — 读取 `rankHistoryCache`，返回百分位数组或 null（本地草稿完成，待提交）
- [ ] **Step 2: 类型检查** — 确认编译通过

### Task 4: compat 层新增 jump 信号函数

**Files:**
- Modify: `src/services/rankTrend/compat.ts`

- [-] **Step 1: 添加** `applyJumpSignal()`, `isJumpEntry()`, `isJumpExit()`, `getJumpExitReason()`（本地草稿完成，待提交）
- [ ] **Step 2: 类型检查** — 确认编译通过

### Task 5: RankTrendSignalService 集成跳跃检测

**Files:**
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`

- [-] **Step 1: 添加 `applyJumpSignals()` 私有方法** — 遍历 stocks，获取 percentiles，运行 evaluateJumpSignal，挂载结果（本地草稿完成，待提交）
- [-] **Step 2: 在 `refreshRankTrendSignals()` 末尾调用**（本地草稿完成，待提交）
- [-] **Step 3: 在 `applySignalsToMerged()` 末尾调用**（本地草稿完成，待提交）
- [ ] **Step 4: 类型检查** — 确认编译通过

---

## Phase 4: DataTable 信号列

### Task 6: 新增"信号"列

**Files:**
- Modify: `src/components/common/DataTable.vue`

- [-] **Step 1: 导入 jump 信号函数** — `isJumpEntry`, `isJumpExit`, `getJumpExitReason`（本地草稿完成，待提交）
- [-] **Step 2: 添加列定义** — `{ key: 'jumpSignal', label: '信号', ... }` 插入在 rankChange 和 confidence 之间（本地草稿完成，待提交）
- [-] **Step 3: 添加列宽** — `jumpSignal: '55px'`（本地草稿完成，待提交）
- [-] **Step 4: 添加模板** — 入场 `←` 绿色标记 / 出场 `→` 红色标记 / 无 `-`（本地草稿完成，待提交）
- [-] **Step 5: 添加 CSS** — `.jump-badge`, `.jump-entry`, `.jump-exit` 样式（本地草稿完成，待提交）
- [ ] **Step 6: 类型检查 + 浏览器验证**

---

## 验收

- [x] `npx vitest run src/services/rankTrend/__tests__/jumpDetector.test.ts` — **12/12 通过**（2026-06-06 14:08）
- [x] `npx vitest run src/services/rankTrend/` — **115/115 通过**（零回归，2026-06-06 14:09）
- [x] `pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false` — **改动文件零新增错误**（1 个已有错误在 `DragonBreathPanel.vue`，与本次无关）
- [x] `pnpm build` — **构建成功**（2026-06-06 14:10, 14:20 两次验证）
- [x] 出场七条件补齐：最大持有周期 + 硬止损 + 止盈（`jumpSignalService.ts`，2026-06-06）
- [x] 持仓追踪：`registerJumpEntry` / `unregisterJumpPosition` / `incrementJumpBar`（`jumpSignalService.ts`）
- [x] `RankTrendSignalService` 集成持仓管理（入场注册 / 出场注销）
- [ ] 浏览器中 DataTable "信号"列正确渲染（需真实数据环境）
- [ ] 有入场信号的股票显示金色 `▲`（需真实数据环境验证）
