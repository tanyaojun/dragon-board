# Attention-Rank Resonance Implementation Plan

**Goal:** 以八平台均榜的横截面关注度排名作为共振路径，识别新入榜爆发而不因历史缺席折分；候选池观察与 tooltip 使用同一结果，交易池仍独立决策。

**Architecture:** `RankTrendAnalyzer` 对当前盘面与每个历史快照的 `avgRankNum` 作横截面重排，产生不含资金/换手的关注度排名序列。`resonanceAnalyzer` 是无副作用的纯函数，区分成熟路径和新入榜事件；样本状态仅解释证据稳定性，不乘法折减分数。`compRank` 只用于展示诊断。

**Out of scope:** 不自动下单、不做回测/参数搜索、不创建 `executionFinal`，不改变 QuantBoard Python golden 或策略执行。

---

### Task 1: 关注度排名序列与红测

**Files:**
- Modify: `src/services/RankTrendAnalyzer.ts`
- Test: `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`

1. 写并运行失败用例：相同均榜、不同资金/换手的快照产生相同关注度排名；均榜更小的股票排名更靠前；缺少 `avgRankNum` 的历史帧不回退到 `rank/compRank`。
2. 实现历史和当前盘面均以 `avgRankNum` 升序横截面重排；保留 `compRank` 原始字段但不进入 RankTrend 序列。
3. 运行目标 Vitest 用例通过。

### Task 2: 新入榜共振合同与红测

**Files:**
- Modify: `src/services/rankTrend/resonanceAnalyzer.ts`
- Modify: `src/services/rankTrend/types.ts`
- Test: `src/services/rankTrend/__tests__/resonanceAnalyzer.test.ts`

1. 写并运行失败用例：新入榜且当前关注度强时返回买入与非零分数；历史长度不改变同一新入榜事件的分数；缺当前帧或少于 20 只横截面股票仍返回 `insufficient`。
2. 为 `resonance` 增加 `historyState`，删除 `qualityCap` 乘法；成熟路径保持相对动量、加速度、持续性、Jump 新鲜度与反转惩罚的正交组合。
3. 运行目标 Vitest 用例通过。

### Task 3: 同轮写入、展示诊断与隔离交易池

**Files:**
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
- Modify: `src/components/common/DataTable.vue`
- Modify: 邻近 `__tests__/*.test.ts`

1. 写失败集成用例：002298 使用完整关注度当前帧仍为 buy；仅改变 `compRank` 不改变 resonance；候选观察仅由 resonance 的 status/direction/score 决定。
2. 在 `applyJumpSignals()` 完成后，批量计算横截面基准和 resonance，覆盖每只 `decision.final`，同步兼容的 `finalSignal/finalConfidence` 投影；不写第二个 final。
3. tooltip 展示关注度排名来源、新入榜状态、六因子与市场中位数；仅以 `compRank` 显示“关注-资金一致性”诊断，不混入共振分数或交易池预览。
4. 运行目标 Vitest 用例通过；Playwright 检查桌面与移动端表格、tooltip、候选观察标记、控制台错误和横向溢出。

### Task 4: 回归与 live-only 合同验证

**Files:**
- Modify: `docs/ranktrend/2026-07-26-live-resonance-observation-design.md`（仅补验证记录）

1. 运行 `pnpm test:ranktrend`、`pnpm typecheck:ranktrend`、`pnpm test`、`pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false`、`git diff --check`。
2. 确认 `rankTrend.resonance` 不进入 QuantBoard golden replay 的输入/输出合同；记录命令退出码与 002298 本轮观察结果。
