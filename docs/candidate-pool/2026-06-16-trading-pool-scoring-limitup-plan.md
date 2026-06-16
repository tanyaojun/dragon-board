# 交易池混合评分 + 涨停分轨——实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `strongConsensus` 从 8 条件 AND 改为离散+连续混合评分，将涨停过滤从硬排除改为观察轨道标记，消除 Jump 单点否决和涨停夹杀导致的系统性空集。

**Architecture:** `TradingPoolAnalysisService` 新增 `computeResonanceScore()` 评分函数，`decideTradingPoolStatus` 改为评分驱动；`checkEntryConditions` 第 4 条改为标记而非排除；配置层新增 `scoring` 阈值节。

**Tech Stack:** Vue 3 + TypeScript + Vite, Vitest

**实施状态:** 核心服务已完成（2026-06-16）。最终落地与原计划有两点收敛：评分函数就近保留在 `TradingPoolAnalysisService.ts`，未新增独立 `TradingPoolScoringService.ts`；`analyzeTradingPoolCandidate` 只读 `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.scoring/weights`，不接受 per-call `thresholds` / `scoring` 覆盖。

---

## Guardrails

- 不改候选池 V5/Fusion 合同和 `checkEntryConditions` 其余 5 条
- 不改 QuantBoard 回测主链
- 不动旧的 `TradingPoolThresholds` 单体字段（标记 deprecated，暂不删除；不参与决策）
- 不支持 per-call `thresholds` / `scoring` 覆盖，交易池判定只读默认策略配置
- 不引入新依赖

## File Map

- **Modify:** `src/types/rankTrendLiveStrategy.ts` — 新增 `ScoringThresholds`，`TradingPoolThresholds` 新增 `scoring`
- **Modify:** `src/config/rankTrendLiveStrategyConfig.ts` — 预设新增 `scoring` 节
- **Modify:** `src/services/candidate/types.ts` — 移除 `TradingPoolConsensusBreakdown`，新增 `TradingPoolScoringBreakdown`，`TradingPoolStatus` 新增 `'涨停观察'`，`TradingPoolRiskFlag` 新增 `'limit_up'`
- **Modify:** `src/services/candidate/TradingPoolAnalysisService.ts` — 新增评分函数，重写 `decideTradingPoolStatus`，更新 `readRiskFlags`
- **Modify:** `src/services/rankTrend/jumpSignalService.ts` — `checkEntryConditions` 条件 4 改为标记
- **Modify:** `src/components/panels/CandidatePoolPanel.vue` — 评分矩阵替换共识矩阵，新增涨停观察状态渲染
- **No New File:** 评分函数最终就近保留在 `src/services/candidate/TradingPoolAnalysisService.ts`
- **Modify:** `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts` — 更新已有测试匹配新评分体系
- **Modify:** `src/components/panels/__tests__/CandidatePoolPanel.test.ts` — 锁定 涨停观察/评分矩阵

---

## Task 1: 扩展类型和配置

**Files:**
- Modify: `src/types/rankTrendLiveStrategy.ts`
- Modify: `src/config/rankTrendLiveStrategyConfig.ts`

- [ ] **Step 1: 新增 ScoringThresholds 类型**

```ts
// src/types/rankTrendLiveStrategy.ts

export interface ScoringThresholds {
  exitMax: number          // 总分低于此值 → 已退出
  observeMin: number       // 总分 ≥ 此值 → 观察中
  buyPointMin: number      // 总分 ≥ 此值 → 观察买点
  readyMin: number         // 总分 ≥ 此值 + macdGolden + jumpHigh → 准备介入
  readyJumpMin: number     // 准备介入额外要求的 Jump 置信度
}

export interface ContinuousWeights {
  jumpConfidence: number
  finalConfidence: number
  directionConfidence: number
  accelerationConfidence: number
  zeroCrossConfidence: number
}
```

- [ ] **Step 2: TradingPoolThresholds 新增 scoring 字段，旧字段标记 deprecated**

```ts
export interface TradingPoolThresholds {
  /** @deprecated 迁移到 scoring 体系中，下个版本移除 */
  recallJumpMin: number
  /** @deprecated */
  readyJumpMin: number
  /** @deprecated */
  observeFinalMin: number
  /** @deprecated */
  readyFinalMin: number
  /** @deprecated */
  buyVotesMin: number
  /** @deprecated */
  downgradeJumpMin: number
  /** @deprecated */
  downgradeFinalMin: number
  /** @deprecated */
  exitFinalSell: number
  /** @deprecated 方向E的功能已由评分体系中 Jump hold=0 vs buy=+2 替代 */
  jumpHoldMinConfidence: number

  scoring: ScoringThresholds
  weights: ContinuousWeights
}
```

- [ ] **Step 3: 三个预设新增 scoring + weights 节**

```ts
// recall_first
scoring: { exitMax: 6, observeMin: 6, buyPointMin: 12, readyMin: 16, readyJumpMin: 75 },
weights: { jumpConfidence: 2.0, finalConfidence: 1.5, directionConfidence: 1.0, accelerationConfidence: 1.0, zeroCrossConfidence: 0.5 },

// balanced
scoring: { exitMax: 8, observeMin: 8, buyPointMin: 15, readyMin: 20, readyJumpMin: 80 },
weights: { jumpConfidence: 2.0, finalConfidence: 1.5, directionConfidence: 1.0, accelerationConfidence: 1.0, zeroCrossConfidence: 0.5 },

// strict_execution
scoring: { exitMax: 10, observeMin: 10, buyPointMin: 18, readyMin: 24, readyJumpMin: 85 },
weights: { jumpConfidence: 2.0, finalConfidence: 1.5, directionConfidence: 1.0, accelerationConfidence: 1.0, zeroCrossConfidence: 0.5 },
```

- [ ] **Step 4: 更新 normalizeTradingPool 处理 scoring 和 weights**

- [ ] **Step 5: 类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

---

## Task 2: 实现混合评分函数

> **实施同步:** 原计划曾考虑新增独立 `TradingPoolScoringService.ts`。最终为保持改动最小、贴合现有服务边界，`computeResonanceScore()` 就近实现于 `TradingPoolAnalysisService.ts`，通过 `TradingPoolAnalysisService.test.ts` 覆盖评分驱动状态与 `scoringBreakdown` 输出。

**Files:**
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: 先写 RED 测试**

在 `TradingPoolAnalysisService.test.ts` 中通过公开 `analyzeTradingPoolCandidate()` 锁定评分行为，不导出私有评分函数：

```ts
it('uses score rather than buyVotes as the DataTable-facing contract', () => {
  const result = analyzeTradingPoolCandidate({ candidates: [/* rankTrend mock */] })
  expect(result.rows[0].scoringBreakdown!.totalScore).toBeGreaterThanOrEqual(15)
  expect(result.rows[0].status).toBe('观察买点')
})
```

- [ ] **Step 2: 运行确认 RED**

- [ ] **Step 3: 实现 computeResonanceScore**

`computeResonanceScore()` 就近放在 `TradingPoolAnalysisService.ts`，接收 `TradingPoolSignalSnapshot` 中的 MACD、Jump 方向和五个连续置信度，返回 `TradingPoolScoringBreakdown`：

```ts
function computeResonanceScore(signals, weights): TradingPoolScoringBreakdown {
  const macdCrossScore = signals.macdCross === 'golden' ? 3 : signals.macdCross === 'death' ? -3 : 0
  const jumpDirectionScore = signals.jumpDirection === 'buy' ? 2 : signals.jumpDirection === 'sell' ? -2 : 0
  const continuousScore = /* five confidence dimensions * DEFAULT weights * 5 */
  return { totalScore, discreteScore, continuousScore, discreteDetail, continuousDetail }
}
```

`decideTradingPoolStatus()` 内只计算一次，并将 `scoringBreakdown` 随结果返回给 row 构建复用。

- [ ] **Step 4: 运行确认 GREEN**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

---

## Task 4: 重写 decideTradingPoolStatus 为评分驱动

**Files:**
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`

- [ ] **Step 1: 用评分逻辑替代 8 条件 AND**

```ts
function decideTradingPoolStatus(
  signals: TradingPoolSignalSnapshot,
  previous: Partial<TradingPoolAnalysisRow> | null | undefined,
  s: ScoringThresholds,
): TradingPoolDecisionResult {
  // 生命周期否决
  if (signals.lifecycleAction === 'veto') {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'] }
  }

  // 涨停观察
  if (signals.limitUp) {
    return { status: '涨停观察', decision: 'watch', reasons: ['limit_up'] }
  }

  // 信号过期
  if (signals.dataQuality !== 'fresh') {
    return {
      status: (previous?.status as TradingPoolStatus) || '观察中',
      decision: 'stale',
      reasons: ['signal_stale'],
    }
  }

  // 计算评分
  const score = computeResonanceScore(
    {
      macdCross: signals.macdCross as 'golden' | 'none' | 'death' | null,
      jumpDirection: signals.jumpDirection as 'buy' | 'hold' | 'sell' | null,
      lifecycleAction: signals.lifecycleAction,
    },
    {
      jumpConfidence: signals.jumpConfidence,
      finalConfidence: signals.finalConfidence,
      directionConfidence: signals.directionConfidence,
      accelerationConfidence: signals.accelerationConfidence,
      zeroCrossConfidence: signals.zeroCrossConfidence,
    },
  )

  if (score.veto) {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'] }
  }

  const total = score.totalScore

  // 已介入状态保持
  if (previous?.status === '已介入') {
    if (total < s.exitMax) {
      return { status: '已退出', decision: 'exit', reasons: ['score_below_exit'] }
    }
    return {
      status: '已介入',
      decision: 'stale',
      reasons: signals.riskFlags.length ? ['intervened_keep_with_risk'] : ['intervened_keep'],
    }
  }

  // 状态判定
  if (total < s.exitMax) {
    return { status: '已退出', decision: 'exit', reasons: ['score_below_exit'] }
  }

  if (total >= s.readyMin && signals.macdCross === 'golden' && (signals.jumpConfidence ?? 0) >= s.readyJumpMin) {
    return {
      status: '准备介入',
      decision: 'enter',
      reasons: ['strong_consensus', 'macd_golden_cross'],
    }
  }

  if (total >= s.buyPointMin) {
    return { status: '观察买点', decision: 'enter', reasons: ['strong_consensus'] }
  }

  if (total >= s.observeMin) {
    return { status: '观察中', decision: 'watch', reasons: ['consensus_moderate'] }
  }

  return { status: '观察中', decision: 'watch', reasons: ['consensus_moderate'] }
}
```

- [ ] **Step 2: 更新 readRiskFlags**

移除 `jump_confidence_low`、`final_confidence_low` 标签（评分中已体现），新增 `limit_up`：

```ts
function readRiskFlags(/* ... */): TradingPoolRiskFlag[] {
  const flags: TradingPoolRiskFlag[] = []
  if (signals.lifecycleAction === 'veto') flags.push('lifecycle_veto')
  if (signals.macdCross === 'death') flags.push('macd_death_cross')
  // 过热、背离、hardBlock、dataStale 保持不变
  if (signals.limitUp) flags.push('limit_up')
  // 移除: jump_confidence_low, final_confidence_low, momentum_sync_broken
  return flags
}
```

- [ ] **Step 3: 更新 analyzeTradingPoolCandidate**

`TradingPoolInput` 不再暴露 `thresholds` / `scoring` 覆盖参数。运行时只读取默认策略配置：

```ts
export function analyzeTradingPoolCandidate(input: TradingPoolInput): TradingPoolAnalysisResult {
  const tradingPoolConfig = DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool
  const scoring = tradingPoolConfig.scoring
  const weights = tradingPoolConfig.weights
  // ... 合并逻辑不变 ...
  const decisionResult = decideTradingPoolStatus(signals, previous, scoring, weights)
  // ...
}
```

- [ ] **Step 4: 类型检查**

---

## Task 3: 涨停过滤改为标记（含类型准备）

> **依赖说明：** 本 Task 在 Task 4 (`decideTradingPoolStatus`) 之前执行，因为 Task 4 的 `signals.limitUp` 字段需在此 Task 中先添加到类型系统和数据流。

**Files:**
- Modify: `src/services/candidate/types.ts` — `TradingPoolSignalSnapshot` 新增 `limitUp`，`TradingPoolStatus` 新增 `'涨停观察'`，`TradingPoolRiskFlag` 新增 `'limit_up'`
- Modify: `src/services/rankTrend/jumpSignalService.ts`

- [ ] **Step 0: 类型准备 — types.ts 新增字段**

```ts
// TradingPoolSignalSnapshot 新增
limitUp: boolean

// TradingPoolStatus 新增
| '涨停观察'

// TradingPoolRiskFlag 新增
| 'limit_up'
```

- [ ] **Step 1: checkEntryConditions 条件 4 改为标记**

```ts
// 旧代码
if (changePct >= limitPct - 0.3) {
  return { passed: false, reasons: ['limit_up_blocked'] }
}

// 新代码
const isLimitUp = changePct >= (limitPct - 0.3)
// 不再 return false
// isLimitUp 通过返回值传递给下游
```

在 `evaluateJumpSignal` 的返回值中新增 `limitUp: boolean`。

- [ ] **Step 2: readTradingSignals 读取 limitUp**

```ts
function readTradingSignals(stock: TradingPoolCandidateLike, t: TradingPoolThresholds): TradingPoolSignalSnapshot {
  const snapshot: TradingPoolSignalSnapshot = {
    // ... 现有字段 ...
    limitUp: stock.rankTrend?.jump?.limitUp ?? false,
  }
}
```

- [ ] **Step 3: 运行 jumpSignalService 测试确认类型正确**

> **延后说明：** 开板重算（spec §3.3：changePct < 9% 时自动触发重算）不在本计划中实现。涨停观察状态下，用户可通过面板手动刷新交易池来触发重算。自动开板检测的定时/事件机制后续单独出计划。

- [ ] **Step 4: 类型检查**

---

## Task 5: 更新现有测试匹配新评分体系

**Files:**
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: 运行现有 33 个测试确认哪些失败**

评分体系下状态判定逻辑完全不同，多数旧测试的预期状态需要更新。

- [ ] **Step 2: 逐一修复旧测试**

按新的评分阈值重新计算每项测试的预期值，更新断言。保持用例结构不变，只改预期值。

- [ ] **Step 3: 新增评分体系回归测试**

```ts
it('华天科技型: Jump=hold + MACD金叉 + 3/4 buyVotes → 观察买点', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [{
      code: '002185', name: '华天科技',
      rankTrend: {
        decision: { final: { signal: 'buy', confidence: 80 } },
        jump: { direction: 'hold', confidence: 50 },
        technical: {
          macd: { cross: 'golden' },
          signals: {
            direction: { signal: 'buy', confidence: 69.6 },
            acceleration: { signal: 'buy', confidence: 64.05 },
            zeroCross: { signal: 'hold', confidence: 50 },
          },
        },
        cycle: { decision: { action: 'allow' } },
      },
    }],
  })
  expect(result.rows[0].status).toBe('观察买点')
})
```

- [ ] **Step 4: 新增涨停观察测试**

```ts
it('routes limit-up stocks to 涨停观察 instead of scoring', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [{
      code: '000001', rankTrend: {
        jump: { direction: 'buy', confidence: 95, limitUp: true },
        decision: { final: { signal: 'buy', confidence: 95 } },
        technical: { macd: { cross: 'golden' }, signals: { /* ... */ } },
        cycle: { decision: { action: 'allow' } },
      },
    }],
  })
  expect(result.rows[0].status).toBe('涨停观察')
  expect(result.rows[0].decision).toBe('watch')
  expect(result.rows[0].signalSnapshot.riskFlags).toContain('limit_up')
})
```

---

## Task 6: 面板适配

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [ ] **Step 1: 评分矩阵替换共识矩阵**

交易池详情区现有 `consensusBreakdown` 8 条件展示 → 替换为 `scoringBreakdown` 评分拆解：

```
离散分: +3 (MACD金叉+3, Jump持有0)
连续分: +18.93 (Jump5.00 + final6.00 + 方向3.48 + 加速度3.20 + 零线1.25)
总分: 21.93 → 观察买点
```

- [ ] **Step 2: 涨停观察状态渲染**

- `tradingStatusFilter` 下拉新增 `涨停观察` 选项
- 状态 badge 新增 `data-status="limit_up"` 样式
- 显示 `limit_up` 风险标签

- [ ] **Step 3: DataTable tooltip 更新**

tooltip 中移除 `共振评级` 行（该信息已在交易池详情区展示），改为展示评分总分。

---

## Task 7: 验收

- [ ] **Step 1: 交易池分析与 Jump 涨停传播测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/services/rankTrend/__tests__/jumpSignalService.test.ts --reporter=dot
```

- [ ] **Step 2: 交易池分析测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

- [ ] **Step 3: 面板测试**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
```

- [ ] **Step 4: 全量回归**

```powershell
pnpm test
pnpm test:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

---

## Task 8: 自审清单

- [x] 权重从 `DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.tradingPool.weights` 读取
- [x] 旧的 `TradingPoolThresholds` 单体字段已标记 deprecated 但未删除（向后兼容），且不参与决策
- [ ] `jumpHoldMinConfidence`（方向 E 新增）在评分体系下不再需要，调度到 deprecated
- [ ] DataTable tooltip 的 `getTradingPoolActionPreview` 同步适配评分体系
- [ ] 候选池 V5/Fusion 未改动
- [ ] `checkEntryConditions` 其余 5 条未改动
- [ ] 无新阈值数值来源未解释
