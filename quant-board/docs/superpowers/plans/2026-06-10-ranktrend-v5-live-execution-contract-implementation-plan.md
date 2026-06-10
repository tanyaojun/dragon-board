# RankTrend V5 Live Execution Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 QuantBoard V5 回测策略 `ranktrend_early_big_move_v3_lifecycle_fusion` 完整接入 Dragon Board 实盘盯盘与自动入池，并用 TS/Python 对齐测试证明 live candidate gate 与 Python V5 执行合同一致。

**Architecture:** 保留 TS golden 分析分层用于展示和 golden 对齐，新增独立 V5 execution contract 用于实盘自动入池和候选池投影。V5 execution contract 必须对齐 Python `candidateTierMode=execution` + `compose_strategy(... hotlistSentiment ...)` + `TradeSimulator._is_early_big_move_v3_lifecycle_fusion_entry_signal()`，不得继续用前端手写近似 gate 作为交易事实。`rankTrend.decision.final.confidence` 继续只做页面展示，不进入本轮交易门槛。

**Tech Stack:** Vue 3, TypeScript, Vitest, QuantBoard Python, pytest, RankTrend TS/Python golden modules

---

## 0. Locked Decisions

> Correction note (2026-06-10): live 盯盘体验优先级已提升为 V5 live contract 的一等目标。`change < 6` 不再作为默认 live 自动入池硬阻断；默认 `balanced` 模式把涨幅位置作为观察降级/排序因素。只有显式选择 `strict_execution` 模式时，才恢复与历史回测执行合同一致的 `change < 6` 硬门槛。
>
> DataTable 不新增“阻断原因/策略模式/入池原因”等额外列。所有 live gate 解释压缩在既有“候选池”列和 CandidatePoolPanel 详情中，避免分散盯盘注意力。

1. V5 主线口径保持已验证基线：
   - `strategyName=ranktrend_early_big_move_v3_lifecycle_fusion`
   - `snapshotType=half_hour`
   - `executionMode=current_bar`
   - `maxHoldingBars=30`
   - `volumeParticipationRate=0.1`
   - `stopLossPct=0.05`
   - `takeProfitPct=9.99`
   - `minJumpConfidence=90`

2. V5 只能有一套执行合同，不允许为了 `77.5` 和 `90` 保留两套冗余策略代码。
   - `minJumpConfidence` 必须只是同一个 V5 contract 的配置值。
   - 本计划先以已复现的 V5 长测证据口径 `90` 作为默认值。
   - 如果后续确认 `77.5` 成为正式口径，应更新同一个配置入口并重新长测验证，而不是新增 V5.1 分叉实现。
   - 当前工作区里的 `77.5` 未提交改动不能和 `+31.00% / 65.79%` 的 V5 证据混用；实施时应通过测试把默认口径讲清楚。

3. DataTable 现有“置信度”列继续表示：
   - `rankTrend.decision.final.confidence`
   - 不改名、不参与 V5 策略门槛。

4. V5 实盘需要新增或展示“Jump 置信度”：
   - 字段来源为 `rankTrend.jump.confidence`
   - 只用于 V5 策略和解释，不替代综合置信度。

5. TS golden 分层和 V5 execution 分层必须分离：
   - `strategy` / `composeCandidateTier(...regime)` 继续用于 golden / 展示。
   - `executionStrategy` / `composeExecutionCandidateTier(...hotlistSentiment)` 用于 V5 live candidate gate。

6. 生命周期 B 是辅助决策系统：
   - V5 入场必须接受 `cycle.decision.action === "veto"` 的一票否决。
   - 生命周期 B 不能独立制造买入信号。
   - 生命周期 B 反对且持仓未盈利时可触发 V5 exit watch / early exit 语义。

---

## 1. File Map

### Dragon Board TS

- Create: `src/services/rankTrend/executionCandidateTierComposer.ts`
  - TS 侧 V5 执行分层，镜像 Python `compose_strategy(...)`。
- Create: `src/services/rankTrend/v5FusionExecutionContract.ts`
  - V5 live 入场、阻断原因、退出语义和默认配置。
- Create: `src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts`
  - 锁定 hotlistSentiment 对 A_MAIN/B_IGNITION/D_EXIT_RISK 的影响。
- Create: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`
  - 锁定 V5 entry/exit 与 Python 执行合同一致。
- Modify: `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
  - 在保留 `strategy` 的同时输出 `executionStrategy`。
- Modify: `src/services/rankTrend/types.ts`
  - 增加 `executionStrategy`、hotlist sentiment 输入或 V5 execution 类型。
- Modify: `src/services/RankTrendAnalyzer.ts`
  - 向 pipeline 传入 live hotlist sentiment；缺失时按 Python `hotlist_missing` 中性处理。
- Modify: `src/services/rankTrend/fusionStrategy.ts`
  - 改为调用 V5 execution contract 的兼容 wrapper。
- Modify: `src/services/rankTrend/FusionCandidateNotifier.ts`
  - 自动入池改用 V5 contract，入池快照写入 V5 证据字段。
- Modify: `src/services/rankTrend/FusionStrategyProjector.ts`
  - 投影使用 V5 contract 的策略状态和阻断原因。
- Modify: `src/services/rankTrend/jumpSignalService.ts`
  - 不再作为 V5 持仓/退出事实源；若保留旧 jump 信号，标注为独立展示层。
- Modify: `src/components/common/DataTable.vue`
  - 保留综合置信度，新增/暴露 Jump 置信度展示或 tooltip 字段。
- Modify: `src/components/common/__tests__/DataTable.test.ts`
  - 验证综合置信度不变、Jump 置信度单独展示。
- Modify: `src/types/rankTrendDefaults.ts`
  - 不放 V5 交易默认阈值；若需要常量，应放在 V5 execution contract 模块内。

### QuantBoard Python

- Modify: `quant-board/backend/core/backtest/config.py`
  - 确保默认 `minJumpConfidence=90.0`。
- Modify: `quant-board/backend/services.py`
  - 确保普通回测 payload 默认 `minJumpConfidence=90.0`，V5 baseline 显式由 CLI baseline set 控制。
- Modify: `quant-board/tests/test_trade_simulator_round_trips.py`
  - 锁定 79.8 默认不通过，显式降低才通过。
- Modify: `quant-board/tests/test_quant_board.py`
  - 锁定后端默认配置仍是 90.0。
- Create: `quant-board/tests/test_ranktrend_v5_live_contract_fixtures.py`
  - 输出/验证 Python V5 fixture，用作 TS 对齐样本来源。

### Docs

- Modify: `quant-board/docs/superpowers/plans/2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md`
  - 标记该计划只解决候选池 projection 语义，不再被误用为 V5 execution contract 接入计划。
- Modify: `quant-board/docs/optimization-long-task/task_plan.md`
  - 回填 V5 live 接入执行状态。
- Modify: `quant-board/docs/optimization-long-task/findings.md`
  - 记录“综合置信度不等于 JumpConfidence”的结论。
- Modify: `quant-board/docs/optimization-long-task/progress.md`
  - 记录实施和验证命令。

---

## 2. Task 1: Guard The Single V5 Jump Confidence Default

**Files:**
- Modify: `quant-board/backend/core/backtest/config.py`
- Modify: `quant-board/backend/services.py`
- Modify: `quant-board/tests/test_trade_simulator_round_trips.py`
- Modify: `quant-board/tests/test_quant_board.py`

- [ ] **Step 1: Write failing Python tests for V5 default `minJumpConfidence=90`**

Add or restore this test in `quant-board/tests/test_trade_simulator_round_trips.py`:

```python
def test_early_big_move_v3_lifecycle_fusion_rejects_79_8_jump_confidence_by_default() -> None:
    candidate = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="buy", change=5.0)
    candidate["rankTrend"]["jump"]["confidence"] = 79.8
    candidate["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "decision": {"action": "allow", "reasons": []},
    }

    candidates = _run_candidates(
        [candidate],
        "ranktrend_early_big_move_v3_lifecycle_fusion",
    )

    assert candidates == []
```

Add or restore this assertion in `quant-board/tests/test_quant_board.py`:

```python
assert run["tradeSimulation"]["config"]["minJumpConfidence"] == 90.0
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_simulator_round_trips.py -k "79_8_jump_confidence" -q
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "import_backtest_optimize_and_golden" -q
```

Expected:

```text
FAIL
```

The failure should show that current dirty defaults accept `79.8` or report `77.5`.

- [ ] **Step 3: Keep one V5 default config entry and set it to the accepted baseline value**

In `quant-board/backend/core/backtest/config.py`, keep a single default entry:

```python
DEFAULT_TRADE_CONFIG: dict[str, Any] = {
    "initialCapital": 1000000,
    "maxPositions": 5,
    "positionSize": 0.2,
    "minJumpConfidence": 90.0,
    ...
}
```

In `quant-board/backend/services.py`, both trade config builders must read the same default:

```python
"minJumpConfidence": camel_get(payload, "min_jump_confidence", "minJumpConfidence", 90.0),
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_simulator_round_trips.py -k "79_8_jump_confidence" -q
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py -k "import_backtest_optimize_and_golden" -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```powershell
git add quant-board/backend/core/backtest/config.py quant-board/backend/services.py quant-board/tests/test_trade_simulator_round_trips.py quant-board/tests/test_quant_board.py
git commit -m "fix: preserve v5 jump confidence baseline"
```

---

## 3. Task 2: Add TS Execution Candidate Tier Composer

**Files:**
- Create: `src/services/rankTrend/executionCandidateTierComposer.ts`
- Create: `src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts`
- Modify: `src/services/rankTrend/types.ts`

- [ ] **Step 1: Write failing tests for hotlist execution tier semantics**

Create `src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { composeExecutionCandidateTier } from '../executionCandidateTierComposer'
import type { RankTrendAnalysisResult } from '../types'

function technical(overrides: Partial<RankTrendAnalysisResult['technical']['momentumProfile']> = {}) {
  return {
    momentumProfile: {
      short: 20,
      mid: 20,
      long: 5,
      acceleration: 12,
      ...overrides,
    },
    signals: {
      direction: { signal: 'buy', confidence: 80, score: 0.7 },
      acceleration: { signal: 'buy', confidence: 80, score: 0.7 },
      zeroCross: { signal: 'buy', confidence: 80, score: 0.7 },
    },
    macd: { dif: 1, dea: 0.5, histogram: 0.5, cross: 'golden', rawScore: 0.8 },
  } as RankTrendAnalysisResult['technical']
}

function cycle(stage: RankTrendAnalysisResult['cycle']['stage'], action = 'allow') {
  return {
    rawStage: stage,
    stage,
    transition: stage,
    confidence: 80,
    metrics: {
      rankVelocity: 10,
      rankAcceleration: 10,
      drawdownFromPeak: 0,
      hotZoneStreak: 1,
      rankPathCommitment: 0.8,
    },
    entryAdvice: { allowed: true, bias: 'preferred', reasons: [] },
    decision: { action, confidence: 80, reasons: [], discovery: { action: 'none', reasons: [] }, evidence: {} },
  } as RankTrendAnalysisResult['cycle']
}

function risk(pressure = 0.2) {
  return {
    pressure,
    divergence: { signal: 'hold', severity: 0.2, reasons: [] },
    overheat: { signal: 'hold', severity: 0.2, reasons: [] },
    synergy: 0.1,
    reasons: [],
  } as RankTrendAnalysisResult['risk']
}

describe('composeExecutionCandidateTier', () => {
  it('allows A_MAIN only when expansion is supported by hotlist climax or fermentation and risk is not high', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 22, short: 18 }),
      cycle: cycle('expansion'),
      risk: risk(0.2),
      hotlist: { stage: '发酵', riskLevel: '中', confidence: 80 },
    })

    expect(result.candidateTier).toBe('A_MAIN')
    expect(result.reasons.join(' ')).toContain('热榜情绪支持A_MAIN')
  })

  it('does not allow A_MAIN when hotlist risk is high', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 22, short: 18 }),
      cycle: cycle('expansion'),
      risk: risk(0.2),
      hotlist: { stage: '发酵', riskLevel: '高', confidence: 80 },
    })

    expect(result.candidateTier).not.toBe('A_MAIN')
  })

  it('does not let lifecycle veto produce A_MAIN or B_IGNITION', () => {
    const result = composeExecutionCandidateTier({
      technical: technical({ mid: 22, short: 18 }),
      cycle: cycle('expansion', 'veto'),
      risk: risk(0.2),
      hotlist: { stage: '高潮', riskLevel: '中', confidence: 80 },
    })

    expect(result.candidateTier).not.toBe('A_MAIN')
    expect(result.candidateTier).not.toBe('B_IGNITION')
    expect(result.reasons.join(' ')).toContain('生命周期辅助决策一票否决')
  })
})
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts
```

Expected:

```text
FAIL
```

Failure should mention `executionCandidateTierComposer` missing.

- [ ] **Step 3: Implement minimal `composeExecutionCandidateTier`**

Create `src/services/rankTrend/executionCandidateTierComposer.ts`:

```ts
import type {
  CandidateTier,
  RankTrendAnalysisResult,
  RankTrendMomentumProfile,
  RankTrendStrategyResult,
  StrategyAction,
} from './types'

export interface HotlistSentimentLike {
  stage?: string | null
  riskLevel?: string | null
  confidence?: number | null
}

function formatMomentum(value: number): string {
  return value > 0 ? `+${value.toFixed(1)}` : value.toFixed(1)
}

function resolveAction(tier: CandidateTier): StrategyAction {
  switch (tier) {
    case 'A_MAIN':
      return 'focus'
    case 'B_IGNITION':
      return 'watch'
    case 'C_CROWDED':
      return 'avoid'
    case 'D_EXIT_RISK':
      return 'exit_watch'
    default:
      return 'hold'
  }
}

export function composeExecutionCandidateTier(input: {
  technical: RankTrendAnalysisResult['technical']
  cycle: RankTrendAnalysisResult['cycle']
  risk: RankTrendAnalysisResult['risk']
  hotlist?: HotlistSentimentLike | null
}): RankTrendStrategyResult & {
  hotlist: { state: 'present' | 'missing'; stage: string | null; riskLevel: string | null; confidence?: number | null }
} {
  const { technical, cycle, risk } = input
  const momentum: RankTrendMomentumProfile = technical.momentumProfile
  const stage = cycle.stage
  const hotlistMissing = !input.hotlist
  const hotlistStage = hotlistMissing ? '' : String(input.hotlist?.stage || '')
  const hotlistRisk = hotlistMissing ? '' : String(input.hotlist?.riskLevel || '')
  const hotlist = {
    state: hotlistMissing ? 'missing' as const : 'present' as const,
    stage: hotlistStage || null,
    riskLevel: hotlistRisk || null,
    confidence: hotlistMissing ? null : input.hotlist?.confidence,
  }
  const reasons: string[] = []
  const lifecycleAction = String(cycle.decision?.action || '')
  const trendBuy =
    technical.signals.direction.signal === 'buy' ||
    technical.signals.acceleration.signal === 'buy' ||
    technical.macd.cross === 'golden'
  let candidateTier: CandidateTier = 'N_NEUTRAL'

  if (hotlistStage === '退潮' || hotlistStage === '冰点') {
    if (momentum.short <= -2 || momentum.acceleration <= -2 || risk.pressure >= 0.55) {
      candidateTier = 'D_EXIT_RISK'
      reasons.push(`热榜${hotlistStage}期，动量衰减触发退出风险`)
    } else {
      reasons.push(`热榜${hotlistStage}期，暂停入场`)
    }
    reasons.push(`热榜情绪: ${hotlistStage}(风险${hotlistRisk || '未知'})`)
    return {
      hotlist,
      regime: { state: 'normal', score: 50, reasons: ['execution tier uses hotlist sentiment'] },
      momentum,
      candidateTier,
      action: resolveAction(candidateTier),
      reasons,
    }
  }

  const allowAMain = hotlistMissing || ((hotlistStage === '高潮' || hotlistStage === '发酵') && hotlistRisk !== '高')
  const allowBIgnition = hotlistMissing || hotlistStage === '高潮' || hotlistStage === '发酵' || hotlistStage === '启动'

  if (lifecycleAction === 'veto') {
    reasons.push('生命周期辅助决策一票否决，阻止进入 A/B 候选池')
  } else if (
    (stage === 'reversal' || stage === 'cooling') &&
    (momentum.short <= -2 || momentum.acceleration <= -2 || risk.pressure >= 0.55)
  ) {
    candidateTier = 'D_EXIT_RISK'
    reasons.push('生命周期进入反转/冷却，短周期动量或风险压力转弱')
  } else if (
    stage === 'crowded' ||
    (momentum.long >= 4 && (momentum.acceleration <= 0 || risk.pressure >= 0.45))
  ) {
    candidateTier = 'C_CROWDED'
    reasons.push('长周期热度高位停留，追高性价比下降')
  } else if (
    stage === 'expansion' &&
    momentum.mid >= 4 &&
    momentum.short >= -1 &&
    trendBuy &&
    allowAMain &&
    risk.divergence.severity < 0.7
  ) {
    candidateTier = 'A_MAIN'
    reasons.push('扩散阶段中周期动量确认，热榜情绪支持A_MAIN入场')
  } else if (
    stage === 'ignition' &&
    momentum.short >= 3 &&
    momentum.acceleration >= 0.5 &&
    allowBIgnition &&
    risk.pressure < 0.65
  ) {
    candidateTier = 'B_IGNITION'
    reasons.push('点火阶段短周期冲击增强，热榜情绪支持B_IGNITION')
  } else if (hotlistStage === '启动' && stage === 'expansion' && trendBuy) {
    reasons.push('热榜启动期，A_MAIN暂缓，等待扩散确认')
  } else if (hotlistRisk === '高' && trendBuy) {
    reasons.push('热榜情绪高风险，买入信号降级为观察')
  } else {
    reasons.push('动量、阶段与风险未形成明确候选池信号')
  }

  if (hotlistMissing) {
    reasons.push('热榜情绪缺失，按中性处理')
  } else if (hotlistStage) {
    reasons.push(`热榜情绪: ${hotlistStage}(风险${hotlistRisk || '未知'})`)
  }
  if (risk.divergence.severity >= 0.6) reasons.push('注意力与资金存在背离')
  if (risk.overheat.severity >= 0.65) reasons.push('过热压力较高')
  reasons.push(
    `动量结构 短${formatMomentum(momentum.short)} 中${formatMomentum(momentum.mid)} 长${formatMomentum(momentum.long)} 加速度${formatMomentum(momentum.acceleration)}`,
  )

  return {
    hotlist,
    regime: { state: 'normal', score: 50, reasons: ['execution tier uses hotlist sentiment'] },
    momentum,
    candidateTier,
    action: resolveAction(candidateTier),
    reasons,
  }
}
```

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit**

```powershell
git add src/services/rankTrend/executionCandidateTierComposer.ts src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts src/services/rankTrend/types.ts
git commit -m "feat: add ranktrend v5 execution tier composer"
```

---

## 4. Task 3: Add V5 Fusion Execution Contract

**Files:**
- Create: `src/services/rankTrend/v5FusionExecutionContract.ts`
- Create: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`
- Modify: `src/services/rankTrend/fusionStrategy.ts`
- Modify: `src/services/rankTrend/__tests__/fusionStrategy.test.ts`

- [ ] **Step 1: Write failing tests for V5 entry contract**

Create `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import {
  V5_FUSION_DEFAULTS,
  evaluateV5FusionEntry,
  evaluateV5FusionExit,
} from '../v5FusionExecutionContract'

function createStock(overrides: Record<string, unknown> = {}) {
  return {
    code: '002552',
    name: '宝鼎科技',
    change: 5,
    rankTrend: {
      jump: { event: 'jump', direction: 'buy', confidence: 92, sustained: true },
      technical: {
        momentumProfile: { short: 12, mid: 22, long: 6, acceleration: 12 },
        signals: {
          direction: { signal: 'buy', confidence: 80, score: 0.7 },
          acceleration: { signal: 'buy', confidence: 80, score: 0.7 },
          zeroCross: { signal: 'buy', confidence: 80, score: 0.7 },
        },
        macd: { dif: 1, dea: 0.5, histogram: 0.5, cross: 'golden', rawScore: 0.8 },
      },
      meta: {
        rawChange: 20,
        sampleQuality: { status: 'ok', snapshotType: 'half_hour' },
      },
      cycle: {
        stage: 'expansion',
        decision: { action: 'allow', reasons: [] },
      },
      strategy: { candidateTier: 'N_NEUTRAL' },
      executionStrategy: { candidateTier: 'A_MAIN', reasons: ['execution tier'] },
    },
    ...overrides,
  }
}

describe('evaluateV5FusionEntry', () => {
  it('uses minJumpConfidence 90 as the V5 live default', () => {
    expect(V5_FUSION_DEFAULTS.minJumpConfidence).toBe(90)
  })

  it('accepts A_MAIN when early big move structure passes and lifecycle does not veto', () => {
    const result = evaluateV5FusionEntry(createStock())

    expect(result.accepted).toBe(true)
    expect(result.candidateTier).toBe('A_MAIN')
  })

  it('rejects 79.8 jump confidence by default', () => {
    const result = evaluateV5FusionEntry(
      createStock({
        rankTrend: {
          ...createStock().rankTrend,
          jump: { event: 'jump', direction: 'buy', confidence: 79.8, sustained: true },
        },
      }),
    )

    expect(result.accepted).toBe(false)
    expect(result.blockedReasons).toContain('jump_confidence')
  })

  it('lets lifecycle veto block entry even when A structure is strong', () => {
    const stock = createStock()
    stock.rankTrend.cycle.decision.action = 'veto'

    const result = evaluateV5FusionEntry(stock)

    expect(result.accepted).toBe(false)
    expect(result.blockedReasons).toContain('lifecycle_veto')
  })

  it('does not use decision.final.confidence as an entry gate', () => {
    const stock = createStock()
    stock.rankTrend.decision = { final: { signal: 'hold', confidence: 50 } }

    const result = evaluateV5FusionEntry(stock)

    expect(result.accepted).toBe(true)
  })
})

describe('evaluateV5FusionExit', () => {
  it('exits when lifecycle B opposes and holding is not profitable', () => {
    const stock = createStock()
    stock.rankTrend.cycle.decision.action = 'exit_watch'

    const result = evaluateV5FusionExit(stock, {
      holdingBars: 3,
      hotlistMissingBars: 0,
      grossReturn: -0.001,
    })

    expect(result.shouldExit).toBe(true)
    expect(result.reason).toBe('生命周期B反对且未盈利')
  })

  it('exits on rawChange < -50 plus MACD death cross', () => {
    const stock = createStock()
    stock.rankTrend.meta.rawChange = -51
    stock.rankTrend.technical.macd.cross = 'death'

    const result = evaluateV5FusionExit(stock, {
      holdingBars: 3,
      hotlistMissingBars: 0,
      grossReturn: 0.03,
    })

    expect(result.shouldExit).toBe(true)
    expect(result.reason).toBe('排名大幅下降+MACD死叉')
  })
})
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected:

```text
FAIL
```

Failure should mention missing `v5FusionExecutionContract`.

- [ ] **Step 3: Implement V5 contract**

Create `src/services/rankTrend/v5FusionExecutionContract.ts`:

```ts
import type { CandidateTier, RankTrendAnalysisResult } from './types'

export const V5_FUSION_DEFAULTS = {
  minJumpConfidence: 90,
  maxHoldingBars: 30,
  stopLossPct: -0.05,
  takeProfitPct: 9.99,
} as const

export interface V5FusionEntryResult {
  accepted: boolean
  candidateTier: CandidateTier | ''
  blockedReasons: string[]
}

export interface V5FusionExitInput {
  holdingBars: number
  hotlistMissingBars: number
  grossReturn: number
}

export interface V5FusionExitResult {
  shouldExit: boolean
  reason: string | null
}

type StockLike = Record<string, any> & {
  rankTrend?: RankTrendAnalysisResult & {
    executionStrategy?: { candidateTier?: CandidateTier; reasons?: string[] }
    jump?: { direction?: string; confidence?: number; event?: string; sustained?: boolean }
  }
}

function asNumber(value: unknown, fallback = 0): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : fallback
}

function dailyLimitPct(code: string): number {
  if (code.startsWith('8')) return 30
  if (code.startsWith('300') || code.startsWith('301') || code.startsWith('688')) return 20
  return 10
}

function isLimitUpBlocked(stock: StockLike): boolean {
  const change = asNumber(stock.change)
  return change >= dailyLimitPct(String(stock.code || '')) - 0.2
}

function getMomentum(rankTrend: StockLike['rankTrend']) {
  return rankTrend?.technical?.momentumProfile ?? rankTrend?.strategy?.momentum
}

function getExecutionCandidateTier(rankTrend: StockLike['rankTrend']): CandidateTier | '' {
  return (
    rankTrend?.executionStrategy?.candidateTier ??
    rankTrend?.strategy?.candidateTier ??
    ''
  ) as CandidateTier | ''
}

export function evaluateV5FusionEntry(
  stock: StockLike,
  options: { minJumpConfidence?: number } = {},
): V5FusionEntryResult {
  const rankTrend = stock.rankTrend
  const blockedReasons: string[] = []
  const minJumpConfidence = options.minJumpConfidence ?? V5_FUSION_DEFAULTS.minJumpConfidence

  if (!rankTrend) {
    return { accepted: false, candidateTier: '', blockedReasons: ['ranktrend_missing'] }
  }

  const sampleStatus = String(rankTrend.meta?.sampleQuality?.status || '')
  if (sampleStatus !== 'ok') blockedReasons.push('sample_quality')

  const jump = rankTrend.jump || {}
  if (jump.direction !== 'buy') blockedReasons.push('jump_direction')
  if (asNumber(jump.confidence) < minJumpConfidence) blockedReasons.push('jump_confidence')

  const momentum = getMomentum(rankTrend)
  if (asNumber(momentum?.short) <= 0) blockedReasons.push('short_positive')
  if (asNumber(momentum?.mid) <= 0) blockedReasons.push('mid_positive')
  if (asNumber(momentum?.long) <= 0) blockedReasons.push('long_positive')
  const acceleration = asNumber(momentum?.acceleration)
  const accDelta = asNumber(stock.accDelta)
  if (acceleration < 10 && accDelta < 8) blockedReasons.push('acceleration')

  if (asNumber(stock.change) >= 6) blockedReasons.push('change_lt_6')
  if (isLimitUpBlocked(stock)) blockedReasons.push('limit_up')

  const lifecycleAction = String(rankTrend.cycle?.decision?.action || '')
  if (lifecycleAction === 'veto') blockedReasons.push('lifecycle_veto')

  const candidateTier = getExecutionCandidateTier(rankTrend)
  if (candidateTier === 'A_MAIN') {
    return {
      accepted: blockedReasons.length === 0,
      candidateTier,
      blockedReasons,
    }
  }

  if (candidateTier === 'B_IGNITION') {
    const mid = asNumber(momentum?.mid)
    const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal || 'none')
    if (mid < 20) blockedReasons.push('b_mid_confirmation')
    if (zeroCross !== 'buy') blockedReasons.push('b_zero_cross')
    return {
      accepted: blockedReasons.length === 0,
      candidateTier,
      blockedReasons,
    }
  }

  blockedReasons.push('candidate_tier')
  return {
    accepted: false,
    candidateTier,
    blockedReasons,
  }
}

export function evaluateV5FusionExit(
  stock: StockLike,
  position: V5FusionExitInput,
): V5FusionExitResult {
  if (position.hotlistMissingBars >= 3) {
    return { shouldExit: true, reason: '退出热榜连续3个bar' }
  }
  if (position.grossReturn <= V5_FUSION_DEFAULTS.stopLossPct) {
    return { shouldExit: true, reason: '止损' }
  }
  const lifecycleAction = String(stock.rankTrend?.cycle?.decision?.action || '')
  if (position.grossReturn <= 0 && (lifecycleAction === 'veto' || lifecycleAction === 'exit_watch')) {
    return { shouldExit: true, reason: '生命周期B反对且未盈利' }
  }
  const rawChange = asNumber(stock.rankTrend?.meta?.rawChange)
  const macdCross = String(stock.rankTrend?.technical?.macd?.cross || '')
  if (rawChange < -50 && macdCross === 'death') {
    return { shouldExit: true, reason: '排名大幅下降+MACD死叉' }
  }
  if (position.holdingBars >= V5_FUSION_DEFAULTS.maxHoldingBars) {
    return { shouldExit: true, reason: '到达最大持有快照' }
  }
  return { shouldExit: false, reason: null }
}
```

- [ ] **Step 4: Make `fusionStrategy.ts` a compatibility wrapper**

Replace its core implementation with:

```ts
import { evaluateV5FusionEntry } from './v5FusionExecutionContract'

export function isFusionEntryCandidate(stock: any): boolean {
  return evaluateV5FusionEntry(stock).accepted
}
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts src/services/rankTrend/__tests__/fusionStrategy.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 6: Commit**

```powershell
git add src/services/rankTrend/v5FusionExecutionContract.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts src/services/rankTrend/fusionStrategy.ts src/services/rankTrend/__tests__/fusionStrategy.test.ts
git commit -m "feat: add ranktrend v5 live execution contract"
```

---

## 5. Task 4: Wire Execution Strategy Into RankTrend Pipeline

**Files:**
- Modify: `src/services/rankTrend/runRankTrendAnalysisPipeline.ts`
- Modify: `src/services/rankTrend/types.ts`
- Modify: `src/services/RankTrendAnalyzer.ts`
- Modify: `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`

- [ ] **Step 1: Write failing test that pipeline returns both analysis and execution strategy**

Add to `src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts`:

```ts
it('returns analysis strategy and V5 execution strategy separately', () => {
  const result = runRankTrendAnalysisPipeline({
    ranks: [100, 80, 60, 40, 30, 20],
    percentiles: [20, 30, 40, 55, 65, 75],
    currentPercentile: 75,
    displayChange: 10,
    stockChange: 5,
    volumeRatio: 1.5,
    zlje: 10000000,
    zljzb: 5,
    regime: { state: 'weak', score: 30, reasons: [] },
    hotlistSentiment: { stage: '发酵', riskLevel: '中', confidence: 80 },
    config: createDefaultConfig(),
  })

  expect(result.strategy).toBeDefined()
  expect(result.executionStrategy).toBeDefined()
  expect(result.executionStrategy.reasons.join(' ')).toContain('热榜情绪')
})
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts
```

Expected:

```text
FAIL
```

Failure should mention `hotlistSentiment` or `executionStrategy` missing.

- [ ] **Step 3: Add `executionStrategy` to types and pipeline**

Update `runRankTrendAnalysisPipeline.ts`:

```ts
import { composeExecutionCandidateTier } from '@/services/rankTrend/executionCandidateTierComposer'
```

Extend input:

```ts
hotlistSentiment?: HotlistSentimentLike | null
```

Return:

```ts
const strategy = composeCandidateTier({ technical, cycle, risk, regime })
const executionStrategy = composeExecutionCandidateTier({
  technical,
  cycle,
  risk,
  hotlist: input.hotlistSentiment ?? null,
})

return {
  technical,
  cycle,
  risk,
  decision,
  strategy,
  executionStrategy,
}
```

Update `RankTrendAnalysisResult` in `types.ts` to include:

```ts
executionStrategy?: RankTrendStrategyResult & {
  hotlist?: {
    state: 'present' | 'missing'
    stage: string | null
    riskLevel: string | null
    confidence?: number | null
  }
}
```

- [ ] **Step 4: Pass hotlist sentiment from `RankTrendAnalyzer`**

In `src/services/RankTrendAnalyzer.ts`, when calling `runRankTrendAnalysisPipeline`, pass:

```ts
hotlistSentiment: dataLayer.getHotListSentiment?.() ?? null,
```

If no stable facade exists, add a private resolver in `RankTrendAnalyzer` that reads the same market context object used by `analyzeMarketRegime`, and returns `null` when unavailable. Do not direct-connect to QuantBoard backend from the component layer.

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts src/services/rankTrend/__tests__/executionCandidateTierComposer.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 6: Commit**

```powershell
git add src/services/rankTrend/runRankTrendAnalysisPipeline.ts src/services/rankTrend/types.ts src/services/RankTrendAnalyzer.ts src/services/rankTrend/__tests__/runRankTrendAnalysisPipeline.test.ts
git commit -m "feat: expose ranktrend v5 execution strategy"
```

---

## 6. Task 5: Wire Auto Candidate Creation To V5 Contract

**Files:**
- Modify: `src/services/rankTrend/FusionCandidateNotifier.ts`
- Modify: `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

- [ ] **Step 1: Write failing notifier tests**

Add to `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`:

```ts
it('uses V5 executionStrategy instead of analysis strategy for auto candidate creation', async () => {
  const stock = createFusionStock({
    rankTrend: {
      ...createRankTrend(),
      strategy: { candidateTier: 'N_NEUTRAL' },
      executionStrategy: { candidateTier: 'A_MAIN', reasons: ['hotlist execution tier'] },
    },
  })
  const candidateJournal = createCandidateJournalMock()
  const notifier = new FusionCandidateNotifier({ candidateJournal, now: () => new Date('2026-06-10T10:00:00+08:00') })

  await notifier.process([stock])

  expect(candidateJournal.addCandidateFromStock).toHaveBeenCalledWith(
    stock,
    expect.objectContaining({
      source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
      statusOverride: 'triggered',
      signalsSnapshotPatch: expect.objectContaining({
        triggerMeta: expect.objectContaining({
          baseline: 'early_big_move_v5',
          jumpConfidence: 92,
          executionCandidateTier: 'A_MAIN',
        }),
      }),
    }),
  )
})

it('does not create a candidate when V5 lifecycle veto blocks entry', async () => {
  const stock = createFusionStock({
    rankTrend: {
      ...createRankTrend(),
      executionStrategy: { candidateTier: 'A_MAIN', reasons: [] },
      cycle: {
        ...createRankTrend().cycle,
        decision: { action: 'veto', reasons: ['risk'], confidence: 80, discovery: { action: 'none', reasons: [] }, evidence: {} },
      },
    },
  })
  const candidateJournal = createCandidateJournalMock()
  const notifier = new FusionCandidateNotifier({ candidateJournal })

  await notifier.process([stock])

  expect(candidateJournal.addCandidateFromStock).not.toHaveBeenCalled()
})
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
```

Expected:

```text
FAIL
```

Failure should show missing V5 trigger metadata or old strategy tier behavior.

- [ ] **Step 3: Update notifier to use V5 contract**

In `FusionCandidateNotifier.ts`:

```ts
import { evaluateV5FusionEntry } from './v5FusionExecutionContract'
```

Replace:

```ts
if (!isFusionEntryCandidate(stock)) continue
```

With:

```ts
const entry = evaluateV5FusionEntry(stock)
if (!entry.accepted) continue
```

Patch trigger metadata:

```ts
triggerMeta: {
  source: FUSION_STRATEGY_SOURCE,
  baseline: 'early_big_move_v5',
  triggerType: 'auto',
  triggeredAt: this.now().toISOString(),
  jumpConfidence: Number(stock.rankTrend?.jump?.confidence ?? 0),
  executionCandidateTier: entry.candidateTier,
  lifecycleAction: String(stock.rankTrend?.cycle?.decision?.action || ''),
  blockedReasons: entry.blockedReasons,
}
```

- [ ] **Step 4: Run tests and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit**

```powershell
git add src/services/rankTrend/FusionCandidateNotifier.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
git commit -m "feat: wire fusion auto candidates to v5 contract"
```

---

## 7. Task 6: Align Projection And V5 Exit Semantics

**Files:**
- Modify: `src/services/rankTrend/FusionStrategyProjector.ts`
- Modify: `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`
- Modify: `src/services/rankTrend/jumpSignalService.ts`

- [ ] **Step 1: Write failing projection tests for V5 state and exit reasons**

Add to `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`:

```ts
it('marks V5 triggered_wait_entry from V5 execution contract', () => {
  const projection = buildFusionStrategyProjection({
    stock: createFusionStock({
      rankTrend: {
        ...createRankTrend(),
        strategy: { candidateTier: 'N_NEUTRAL' },
        executionStrategy: { candidateTier: 'A_MAIN', reasons: ['execution tier'] },
      },
    }),
    snapshotType: 'half_hour',
    tradingDate: '2026-06-10',
    snapshotId: 'half_hour:2026-06-10:10:00',
    frameTime: '2026-06-10T10:00:00+08:00',
  })

  expect(projection.strategyState).toBe('triggered_wait_entry')
  expect(projection.candidateTier).toBe('A_MAIN')
})

it('projects lifecycle B opposition as exit_signaled only when strategy lifecycle has an open position', () => {
  const projection = buildFusionStrategyProjection({
    stock: createFusionStock(),
    snapshotType: 'half_hour',
    tradingDate: '2026-06-10',
    snapshotId: 'half_hour:2026-06-10:11:00',
    frameTime: '2026-06-10T11:00:00+08:00',
    strategyLifecycle: {
      triggered: true,
      hasOpenPosition: true,
      exitWatch: true,
      exitReason: '生命周期B反对且未盈利',
    },
  })

  expect(projection.strategyState).toBe('exit_signaled')
  expect(projection.exitReason).toBe('生命周期B反对且未盈利')
})
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts
```

Expected:

```text
FAIL
```

- [ ] **Step 3: Update projector to use V5 entry result**

In `FusionStrategyProjector.ts`, replace `isFusionEntryCandidate(stock)` with:

```ts
const entry = evaluateV5FusionEntry(stock)
const triggered = lifecycle?.triggered ?? entry.accepted
```

Use execution candidate tier:

```ts
candidateTier: normalizeCandidateTier(input.stock, entry.candidateTier),
```

Ensure `executionOverlay` remains overlay only and never defines `active_holding`, `exit_signaled`, or `closed`.

- [ ] **Step 4: Mark old jump signal holding as non-V5**

In `jumpSignalService.ts`, keep existing behavior only for legacy jump display. Add comments and tests if needed:

```ts
// Legacy jump display state. V5 fusion holding/exit semantics live in v5FusionExecutionContract
// and FusionStrategyProjector; do not use this map as V5 strategy state.
```

- [ ] **Step 5: Run tests and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 6: Commit**

```powershell
git add src/services/rankTrend/FusionStrategyProjector.ts src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts src/services/rankTrend/jumpSignalService.ts
git commit -m "feat: align fusion projections with v5 semantics"
```

---

## 8. Task 7: Preserve DataTable Final Confidence And Add Jump Confidence Visibility

**Files:**
- Modify: `src/components/common/DataTable.vue`
- Modify: `src/components/common/__tests__/DataTable.test.ts`

- [ ] **Step 1: Write failing DataTable source contract test**

Add to `src/components/common/__tests__/DataTable.test.ts`:

```ts
test('keeps final confidence as the confidence column and exposes jump confidence separately', () => {
  const source = readFileSync(new URL('../DataTable.vue', import.meta.url), 'utf-8')

  expect(source).toContain('getFinalConfidence(stock)')
  expect(source).toContain('decision?.final?.confidence')
  expect(source).toContain('getJumpConfidence')
  expect(source).toContain('rankTrend?.jump?.confidence')
  expect(source).not.toContain('getFinalConfidence(stock)?.jump')
})
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

Expected:

```text
FAIL
```

Failure should mention `getJumpConfidence` missing.

- [ ] **Step 3: Add Jump confidence helper and tooltip line**

In `DataTable.vue`:

```ts
const getJumpConfidence = (stock: any) =>
  Number(getRankTrendAnalysis(stock)?.jump?.confidence ?? stock?.jumpConfidence ?? 0)
```

In the confidence tooltip:

```ts
const jumpConfidence = getJumpConfidence(stock)
if (jumpConfidence > 0) {
  title += `   🚀 Jump跃迁置信: ${formatTooltipNumber(jumpConfidence, 1)}%\n`
}
```

Do not modify `getFinalConfidence`.

- [ ] **Step 4: Run test and verify GREEN**

Run:

```powershell
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

Expected:

```text
PASS
```

- [ ] **Step 5: Commit**

```powershell
git add src/components/common/DataTable.vue src/components/common/__tests__/DataTable.test.ts
git commit -m "feat: expose jump confidence in datatable"
```

---

## 9. Task 8: Add TS/Python Fixture Alignment

**Files:**
- Create: `quant-board/tests/test_ranktrend_v5_live_contract_fixtures.py`
- Create: `src/services/rankTrend/__tests__/v5FusionPythonFixtureAlignment.test.ts`
- Create: `src/services/rankTrend/__fixtures__/v5FusionExecutionCases.json`

- [ ] **Step 1: Write Python fixture tests**

Create `quant-board/tests/test_ranktrend_v5_live_contract_fixtures.py`:

```python
from backend.core.backtest.execution import TradeSimulator


def _candidate(confidence: float = 92.0, lifecycle_action: str = "allow", tier: str = "A_MAIN") -> dict:
    return {
        "code": "002552",
        "name": "宝鼎科技",
        "change": 5.0,
        "candidateTier": tier,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "confidence": confidence, "sustained": True},
            "technical": {
                "momentumProfile": {"short": 12, "mid": 22, "long": 6, "acceleration": 12},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "buy"},
                    "zeroCross": {"signal": "buy"},
                },
                "macd": {"cross": "golden"},
            },
            "meta": {"sampleQuality": {"status": "ok"}, "rawChange": 20},
            "cycle": {"stage": "expansion", "decision": {"action": lifecycle_action, "reasons": []}},
        },
    }


def test_v5_fixture_entry_cases_match_python_contract() -> None:
    cases = [
        ("a_main_accept", _candidate(), True),
        ("low_jump_reject", _candidate(confidence=79.8), False),
        ("lifecycle_veto_reject", _candidate(lifecycle_action="veto"), False),
    ]

    actual = [
        {
            "name": name,
            "accepted": TradeSimulator._is_early_big_move_v3_lifecycle_fusion_entry_signal(signal, 90.0),
        }
        for name, signal, _expected in cases
    ]

    assert actual == [{"name": name, "accepted": expected} for name, _signal, expected in cases]
```

- [ ] **Step 2: Run Python fixture test**

Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_v5_live_contract_fixtures.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 3: Add shared JSON fixture**

Create `src/services/rankTrend/__fixtures__/v5FusionExecutionCases.json`:

```json
[
  {
    "name": "a_main_accept",
    "expectedAccepted": true,
    "stock": {
      "code": "002552",
      "name": "宝鼎科技",
      "change": 5,
      "rankTrend": {
        "jump": { "event": "jump", "direction": "buy", "confidence": 92, "sustained": true },
        "technical": {
          "momentumProfile": { "short": 12, "mid": 22, "long": 6, "acceleration": 12 },
          "signals": {
            "direction": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "acceleration": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "zeroCross": { "signal": "buy", "confidence": 80, "score": 0.7 }
          },
          "macd": { "dif": 1, "dea": 0.5, "histogram": 0.5, "cross": "golden", "rawScore": 0.8 }
        },
        "meta": { "rawChange": 20, "sampleQuality": { "status": "ok", "snapshotType": "half_hour" } },
        "cycle": { "stage": "expansion", "decision": { "action": "allow", "reasons": [] } },
        "executionStrategy": { "candidateTier": "A_MAIN", "reasons": ["fixture"] }
      }
    }
  },
  {
    "name": "low_jump_reject",
    "expectedAccepted": false,
    "stock": {
      "code": "002552",
      "name": "宝鼎科技",
      "change": 5,
      "rankTrend": {
        "jump": { "event": "jump", "direction": "buy", "confidence": 79.8, "sustained": true },
        "technical": {
          "momentumProfile": { "short": 12, "mid": 22, "long": 6, "acceleration": 12 },
          "signals": {
            "direction": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "acceleration": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "zeroCross": { "signal": "buy", "confidence": 80, "score": 0.7 }
          },
          "macd": { "dif": 1, "dea": 0.5, "histogram": 0.5, "cross": "golden", "rawScore": 0.8 }
        },
        "meta": { "rawChange": 20, "sampleQuality": { "status": "ok", "snapshotType": "half_hour" } },
        "cycle": { "stage": "expansion", "decision": { "action": "allow", "reasons": [] } },
        "executionStrategy": { "candidateTier": "A_MAIN", "reasons": ["fixture"] }
      }
    }
  },
  {
    "name": "lifecycle_veto_reject",
    "expectedAccepted": false,
    "stock": {
      "code": "002552",
      "name": "宝鼎科技",
      "change": 5,
      "rankTrend": {
        "jump": { "event": "jump", "direction": "buy", "confidence": 92, "sustained": true },
        "technical": {
          "momentumProfile": { "short": 12, "mid": 22, "long": 6, "acceleration": 12 },
          "signals": {
            "direction": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "acceleration": { "signal": "buy", "confidence": 80, "score": 0.7 },
            "zeroCross": { "signal": "buy", "confidence": 80, "score": 0.7 }
          },
          "macd": { "dif": 1, "dea": 0.5, "histogram": 0.5, "cross": "golden", "rawScore": 0.8 }
        },
        "meta": { "rawChange": 20, "sampleQuality": { "status": "ok", "snapshotType": "half_hour" } },
        "cycle": { "stage": "expansion", "decision": { "action": "veto", "reasons": ["fixture"] } },
        "executionStrategy": { "candidateTier": "A_MAIN", "reasons": ["fixture"] }
      }
    }
  }
]
```

- [ ] **Step 4: Write TS fixture alignment test**

Create `src/services/rankTrend/__tests__/v5FusionPythonFixtureAlignment.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import cases from '../__fixtures__/v5FusionExecutionCases.json'
import { evaluateV5FusionEntry } from '../v5FusionExecutionContract'

describe('V5 TS/Python fixture alignment', () => {
  it.each(cases)('matches Python V5 entry decision for $name', (item) => {
    expect(evaluateV5FusionEntry(item.stock).accepted).toBe(item.expectedAccepted)
  })
})
```

- [ ] **Step 5: Run TS/Python fixture tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionPythonFixtureAlignment.test.ts
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_v5_live_contract_fixtures.py -q
```

Expected:

```text
PASS
```

- [ ] **Step 6: Commit**

```powershell
git add quant-board/tests/test_ranktrend_v5_live_contract_fixtures.py src/services/rankTrend/__fixtures__/v5FusionExecutionCases.json src/services/rankTrend/__tests__/v5FusionPythonFixtureAlignment.test.ts
git commit -m "test: align ranktrend v5 ts python fixtures"
```

---

## 10. Task 9: Update Docs And Progress

**Files:**
- Modify: `quant-board/docs/optimization-long-task/task_plan.md`
- Modify: `quant-board/docs/optimization-long-task/findings.md`
- Modify: `quant-board/docs/optimization-long-task/progress.md`
- Modify: `quant-board/docs/superpowers/plans/2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md`

- [ ] **Step 1: Document V5 live contract boundary**

Add to `findings.md`:

```md
### V5 live execution contract boundary

- DataTable 的“置信度”列仍是 `rankTrend.decision.final.confidence`，只做综合技术展示。
- V5 策略门槛使用 `rankTrend.jump.confidence`，不是 DataTable 综合置信度。
- V5 只有一套 execution contract；`minJumpConfidence` 是该合同的配置值，不允许复制出 `77.5` / `90` 两套策略实现。
- 当前已复现的 V5 长测证据口径使用 `minJumpConfidence=90`；如果后续改用 `77.5`，必须更新同一个配置入口并重新长测验证。
- Dragon Board live 自动入池必须消费 `executionStrategy`，不能继续用 `strategy` 的 TS golden 分层代替 Python execution tier。
```

- [ ] **Step 2: Mark the 2026-06-08 semantics plan as projection-only**

Add near the top of `2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md`:

```md
> **Scope note (2026-06-10):** 本计划只解决候选池 projection / execution overlay 语义，不等同于 V5 回测执行合同完整接入。V5 live execution contract 以 `2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md` 为准。
```

- [ ] **Step 3: Update progress**

Add to `progress.md`:

```md
### Phase 40 V5 live execution contract integration

- **Status:** in_progress
- Decision:
  - 保留 `decision.final.confidence` 为展示置信度。
  - V5 策略使用 `jump.confidence`。
  - V5 主线默认继续使用已复现证据口径 `minJumpConfidence=90`。
  - 不为 `77.5` 建立冗余策略分支；若后续采纳，只改同一个配置入口并重新验证。
- Implementation source:
  - `quant-board/docs/superpowers/plans/2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md`
```

- [ ] **Step 4: Commit**

```powershell
git add quant-board/docs/optimization-long-task/task_plan.md quant-board/docs/optimization-long-task/findings.md quant-board/docs/optimization-long-task/progress.md quant-board/docs/superpowers/plans/2026-06-08-ranktrend-fusion-candidate-pool-unified-semantics-implementation-plan.md
git commit -m "docs: define ranktrend v5 live execution contract"
```

---

## 11. Final Verification

Run all commands from a clean final implementation state:

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_trade_simulator_round_trips.py tests/test_quant_board.py tests/test_ranktrend_v5_live_contract_fixtures.py -q
```

Manual/browser check after implementation because DataTable changes are visible UI:

```powershell
pnpm dev
```

Open Dragon Board main page and verify:

- Existing “置信度” still shows `decision.final.confidence`.
- Tooltip or new field shows “Jump跃迁置信” from `rankTrend.jump.confidence`.
- Candidate pool trigger state comes from V5 contract, not `trade_journal.status`.

If browser automation is available, use Playwright to check:

- The DataTable renders without console errors.
- The confidence tooltip includes both 综合判断置信度 and Jump跃迁置信.

---

## 12. Self-Review

- Spec coverage:
  - Covers V5 live candidate gate.
  - Covers Python execution contract.
  - Covers lifecycle veto.
  - Covers JumpConfidence.
  - Covers holding / exit semantics.
  - Covers DataTable final confidence remaining display-only.
  - Covers TS tests, Python tests, notifier tests, and UI field check.
- Placeholder scan:
  - No TBD / TODO placeholders.
  - Every task has concrete files, tests, commands, expected results, and commits.
- Type consistency:
  - `strategy` remains analysis/golden tier.
  - `executionStrategy` is V5 execution tier.
  - `decision.final.confidence` remains display confidence.
  - `jump.confidence` is V5 JumpConfidence.

## 13. Execution Handoff

Plan complete and saved to `quant-board/docs/superpowers/plans/2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md`.

Recommended execution order:

1. Task 1 guards the single V5 default and prevents `77.5` / `90` from becoming duplicate strategy branches.
2. Task 2-4 establish V5 TS execution contract.
3. Task 5-7 connect auto入池, projection, and DataTable visibility.
4. Task 8 proves TS/Python fixture alignment.
5. Task 9 updates docs and progress.

Do not batch all tasks into one commit. This goal changes live trading-assist behavior, so each task should be small, test-backed, and reviewable.
