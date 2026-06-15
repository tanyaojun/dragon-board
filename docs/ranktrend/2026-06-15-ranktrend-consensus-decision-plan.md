# RankTrend Consensus Decision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development for each code task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 RankTrend 最终方向改成“共识门槛决定方向、加权强度决定置信度和排序”。

**Architecture:** 只调整 `resultComposer` 的 final/base 方向合成规则，不改底层技术信号计算。四个投票来源仍是方向一致性、动量加速度、零线交叉和 MACD；同向票数先决定方向是否成立，加权分数继续决定强弱、置信度和风险扣分。

**Tech Stack:** TypeScript、Vitest、RankTrend golden 兼容输出。

---

## File Structure

- Modify: `src/services/rankTrend/resultComposer.ts`
  - 增加共识票数统计和方向门槛。
  - 保留现有 `combinedScore`、`positiveWeight`、`negativeWeight`、风险扣分和 reversal 翻转保护。
- Modify: `src/services/rankTrend/__tests__/resultComposer.test.ts`
  - 新增用户给出的 6 个验收样例。
  - 更新旧测试中“多组件买入/卖出”的断言，让它明确满足共识票数。
- Inspect: `src/components/common/DataTable.vue`
  - 本计划不改 UI，但实现后必须确认 tooltip 没有把高置信度误导成单项买卖建议。
- Inspect: `docs/attention-manual.md`
  - 本计划不改长文档，但实现后必须确认没有和新共识门槛冲突的描述。

---

## Decision Contract

实现后的核心规则：

```ts
const buyVotes = components.filter((component) => component.signal === 'buy').length
const sellVotes = components.filter((component) => component.signal === 'sell').length

const hasBuyConsensus =
  buyVotes >= 2 &&
  sellVotes <= 1 &&
  combinedScore >= config.buyScoreThreshold

const hasSellConsensus =
  sellVotes >= 2 &&
  buyVotes <= 1 &&
  combinedScore <= config.sellScoreThreshold
```

`baseSignal` 只由 `hasBuyConsensus` / `hasSellConsensus` 决定。`finalSignal` 继续从 `baseSignal` 出发，再经过现有风险翻转逻辑。

本计划采用“票数 + 分数”口径，不增加 `positiveWeight >= negativeWeight` 或 `negativeWeight >= positiveWeight` 条件。原因是这两个条件难以向盯盘用户解释，且会制造“票数和总分都满足但权重比较不满足”的边缘观望结果。

---

## Task 0: Baseline and bypass checks

**Files:**
- Inspect: `src/services/rankTrend/resultComposer.ts`
- Inspect: `src/services/dataLoader/RankTrendSignalService.ts`
- Inspect: `src/services/rankTrend/compat.ts`
- Inspect: `src/components/common/DataTable.vue`
- Inspect: `src/components/panels/RankTrendPanel.vue`

- [ ] **Step 1: Run current RankTrend suite before edits**

```powershell
pnpm test:ranktrend
```

Expected: record current pass/fail state before changing tests. If it fails before this work, capture the failing test names and do not attribute them to the consensus change.

- [ ] **Step 2: Confirm finalSignal source path**

Check these facts before editing implementation:

- `RankTrendAnalyzer` writes `result.finalSignal` from `decision.final.signal`.
- `applyRankTrendAnalysis(...)` writes only `target.rankTrend = rankTrend`.
- `applyJumpSignal(...)` writes only `rankTrend.jump` and `_jumpEntry/_jumpExit` fields.
- DataTable tooltip reads `rankTrend.decision.final.signal` before falling back to legacy `stock.finalSignal`.

Use:

```powershell
rg -n "finalSignal|decision\\.final|applyJumpSignal|applyRankTrendAnalysis" src/services src/components/common/DataTable.vue src/components/panels/RankTrendPanel.vue
```

Expected: no Jump path directly overwrites `stock.finalSignal`; any legacy `stock.finalSignal` fallback is lower priority than `rankTrend.decision.final.signal`.

---

## Task 1: Add consensus decision tests

**Files:**
- Modify: `src/services/rankTrend/__tests__/resultComposer.test.ts`

- [ ] **Step 1: Add a helper that can build explicit four-signal cases**

`createTechnical(...)` 已支持显式传入四个信号和分数。新增测试必须传满四个信号和分数，不依赖默认值：

```ts
createTechnical({
  directionSignal: 'hold',
  directionScore: 0.05,
  accelerationSignal: 'buy',
  accelerationScore: 0.9,
  zeroCrossSignal: 'hold',
  zeroCrossScore: 0,
  macdCross: 'none',
  macdRawScore: 0,
})
```

不需要修改 helper。

- [ ] **Step 2: Write RED test for one strong buy not becoming buy**

添加测试：

```ts
it('单个强买入信号不能越过共识门槛直接给买入', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'hold',
      directionScore: 0.05,
      accelerationSignal: 'buy',
      accelerationScore: 0.9,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeGreaterThan(0.12)
  expect(result.final.signal).toBe('hold')
})
```

- [ ] **Step 3: Write RED test for buy/sell conflict becoming hold**

添加测试：

```ts
it('一买一卖两观望时综合判断为观望', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'buy',
      directionScore: 0.88,
      accelerationSignal: 'sell',
      accelerationScore: -0.46,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeGreaterThan(0.12)
  expect(result.final.signal).toBe('hold')
})
```

- [ ] **Step 4: Write RED test for one strong sell not becoming sell**

添加测试：

```ts
it('单个强卖出信号不能越过共识门槛直接给卖出', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'sell',
      directionScore: -0.85,
      accelerationSignal: 'hold',
      accelerationScore: 0,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('cooling'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeLessThan(-0.12)
  expect(result.final.signal).toBe('hold')
})
```

- [ ] **Step 5: Write GREEN-target tests for full buy/full sell/two-sell consensus**

添加测试：

```ts
it('四个排名趋势信号全部买入时综合判断为买入', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'buy',
      directionScore: 0.72,
      accelerationSignal: 'buy',
      accelerationScore: 0.82,
      zeroCrossSignal: 'buy',
      zeroCrossScore: 0.65,
      macdCross: 'golden',
      macdRawScore: 0.7,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.final.signal).toBe('buy')
})

it('四个排名趋势信号全部卖出时综合判断为卖出', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'sell',
      directionScore: -0.82,
      accelerationSignal: 'sell',
      accelerationScore: -0.8,
      zeroCrossSignal: 'sell',
      zeroCrossScore: -0.72,
      macdCross: 'death',
      macdRawScore: -0.7,
    }),
    cycle: createCycle('cooling'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.final.signal).toBe('sell')
})

it('两项卖出两项观望且加权分数过阈值时综合判断为卖出', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'hold',
      directionScore: -0.08,
      accelerationSignal: 'sell',
      accelerationScore: -0.88,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'death',
      macdRawScore: -0.7,
    }),
    cycle: createCycle('cooling'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeLessThan(-0.12)
  expect(result.final.signal).toBe('sell')
})
```

- [ ] **Step 6: Write boundary test for votes without enough score**

添加测试：

```ts
it('买入票数够但加权分数未过阈值时仍为观望', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'buy',
      directionScore: 0.1,
      accelerationSignal: 'buy',
      accelerationScore: 0.1,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeLessThan(0.12)
  expect(result.final.signal).toBe('hold')
})
```

- [ ] **Step 7: Write 2+1 allowed conflict boundary tests**

添加测试：

```ts
it('两买一卖且加权分数过阈值时允许买入', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'buy',
      directionScore: 0.8,
      accelerationSignal: 'buy',
      accelerationScore: 0.65,
      zeroCrossSignal: 'sell',
      zeroCrossScore: -0.2,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeGreaterThan(0.12)
  expect(result.final.signal).toBe('buy')
})

it('两卖一买且加权分数过阈值时允许卖出', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'sell',
      directionScore: -0.8,
      accelerationSignal: 'sell',
      accelerationScore: -0.65,
      zeroCrossSignal: 'buy',
      zeroCrossScore: 0.2,
      macdCross: 'none',
      macdRawScore: 0,
    }),
    cycle: createCycle('cooling'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeLessThan(-0.12)
  expect(result.final.signal).toBe('sell')
})
```

- [ ] **Step 8: Write MACD unknown-value fallback test**

添加测试：

```ts
it('未知 MACD cross 值按观望票处理', () => {
  const result = composeDecision({
    technical: createTechnical({
      directionSignal: 'hold',
      directionScore: 0,
      accelerationSignal: 'buy',
      accelerationScore: 0.9,
      zeroCrossSignal: 'hold',
      zeroCrossScore: 0,
      macdCross: 'mystery' as any,
      macdRawScore: 0.9,
    }),
    cycle: createCycle('expansion'),
    risk: createRisk(),
    config: cloneDefaultRankTrendRuntimeConfig(),
  })

  expect(result.base.combinedScore).toBeGreaterThan(0.12)
  expect(result.final.signal).toBe('hold')
})
```

- [ ] **Step 9: Run focused test and confirm RED**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/resultComposer.test.ts
```

Expected before implementation: the new one-strong-signal tests fail because current code still lets strong single components cross the threshold.

---

## Task 2: Implement consensus gate in resultComposer

**Files:**
- Modify: `src/services/rankTrend/resultComposer.ts`

- [ ] **Step 1: Add consensus booleans near the existing vote counts**

Replace the base signal condition block with explicit consensus flags:

```ts
const explicitBuyCount = components.filter((component) => component.signal === 'buy').length
const explicitSellCount = components.filter((component) => component.signal === 'sell').length
const hasBuyConsensus =
  explicitBuyCount >= 2 &&
  explicitSellCount <= 1 &&
  combinedScore >= config.buyScoreThreshold
const hasSellConsensus =
  explicitSellCount >= 2 &&
  explicitBuyCount <= 1 &&
  combinedScore <= config.sellScoreThreshold

let baseSignal: RankSignalDirection = 'hold'
if (hasBuyConsensus) {
  baseSignal = 'buy'
} else if (hasSellConsensus) {
  baseSignal = 'sell'
}
```

- [ ] **Step 2: Keep confidence calculation unchanged**

Do not change:

- `combinedScore`
- `positiveWeight`
- `negativeWeight`
- `signedThreshold`
- `baseConfidence`
- `finalConfidence`
- reversal 高压高过热翻转保护
- `baseSignal === 'hold'` 时的 `opposingWeight = Math.min(positiveWeight, negativeWeight)` 口径

This keeps weighted strength available for confidence, ordering, and future UI explanation.

`scoreMargin` 只在 `baseSignal` 为 `buy` 或 `sell` 时表达方向阈值余量；共识失败保持 `hold` 时应返回 `0`，避免没有方向的观望结果携带不对称的阈值余量。

- [ ] **Step 3: Run focused test and confirm GREEN**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/resultComposer.test.ts
```

Expected: all `resultComposer` tests pass.

---

## Task 3: Update affected RankTrend expectations

**Files:**
- Inspect: `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`
- Inspect: `src/services/__tests__/RankTrendAnalyzer.test.ts`
- Inspect: `src/services/quantBoardGolden/**`

- [ ] **Step 1: Run RankTrend suite to find dependent snapshots**

```powershell
pnpm test:ranktrend
```

Expected before updates: tests may fail where fixtures assumed a single strong weighted signal can produce `buy` or `sell`. Existing `resultComposer` tests that already have 2+ 同向票 should remain valid.

- [ ] **Step 2: Inspect every failure**

For each failure:

- If fixture intends a real buy/sell, update fixture technical signals so at least 2 of 4 components agree.
- If fixture only has one strong component, update expected `finalSignal` to `hold`.
- Do not loosen assertions by replacing exact signals with broad matchers.

If there are no failures in these files, leave them unchanged.

- [ ] **Step 3: Re-run RankTrend suite**

```powershell
pnpm test:ranktrend
```

Expected: RankTrend tests pass.

---

## Task 4: Typecheck and documentation check

**Files:**
- Inspect: `src/components/common/DataTable.vue`
- Inspect: `src/components/panels/RankTrendPanel.vue`
- Inspect: `docs/attention-manual.md`

- [ ] **Step 1: Run RankTrend typecheck**

```powershell
pnpm typecheck:ranktrend
```

Expected: exits 0.

- [ ] **Step 2: Search for stale wording**

```powershell
rg -n "强单项|加权阈值|综合判断|三票|四票|共识门槛" docs src/components/common/DataTable.vue src/components/panels/RankTrendPanel.vue
```

Expected:

- New spec and plan appear.
- No project doc claims the old behavior is the intended final direction rule.
- Existing docs that only describe how to read `finalSignal` can remain if they do not contradict the new consensus rule.

- [ ] **Step 3: Record UI/manual follow-up if wording is stale**

If stale docs or UI text imply “综合判断只是加权阈值”， record a follow-up before final handoff:

- `docs/attention-manual.md`
- `src/components/common/DataTable.vue`
- `src/components/panels/RankTrendPanel.vue`

Do not bundle UI copy changes into the algorithm fix.

---

## Task 5: Final verification

**Files:**
- No edits expected.

- [ ] **Step 1: Run final RankTrend verification**

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

Expected: both commands exit 0.

- [ ] **Step 2: Inspect diff**

```powershell
git diff -- src/services/rankTrend/resultComposer.ts src/services/rankTrend/__tests__/resultComposer.test.ts docs/ranktrend/2026-06-15-ranktrend-consensus-decision-design.md docs/ranktrend/2026-06-15-ranktrend-consensus-decision-plan.md
```

Expected:

- Diff only contains consensus decision logic, targeted tests, and these docs.
- No unrelated formatting, UI, QuantBoard storage, or snapshot API changes.
