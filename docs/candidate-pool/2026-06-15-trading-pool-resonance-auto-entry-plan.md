# Trading Pool Resonance Auto Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完善交易池自动入池和面板，使强共振但未通过候选池 Jump 硬阈值的股票能进入交易池观察，并在 UI 中清晰区分候选池严格结果、交易池召回结果、综合置信度和 Jump 置信度。

**Architecture:** 保留 V5/Fusion 候选池严格合同不变，在 `TradingPoolAnalysisService` 增加共振评分、风险标签和来源识别；CandidatePoolPanel 读取候选池 thesis、持久化 trading_pool 记录和 live projection 生成交易池工作台；DataTable tooltip 只做展示语义收敛，不承载业务规则。

**Tech Stack:** Vue 3 + TypeScript + Vite, Vitest, Playwright CLI, existing RankTrend services, `CandidateJournalService`, `TradingPoolAnalysisService`, `CandidatePoolPanel.vue`, `DataTable.vue`.

---

## Guardrails

- 不放宽 `v5FusionExecutionContract.ts` 的候选池严格入池硬门槛。
- 不把交易池 `已介入` 自动写成真实历史 `entry`。
- 不把交易池状态写入 `favorite_data`。
- 不引入新依赖。
- 不做 QuantBoard 回测或优化主链改动。
- 不覆盖 `docs/candidate-pool/task_plan.md`、`progress.md` 和已有未提交改动。
- 所有规则必须能在 `TradingPoolAnalysisService.test.ts` 中用具体样例复现。
- 加载 Phase 18 V2 `tradeType=trading_pool` 旧记录时，缺失字段以当前规则重算补齐；不可重算时保留旧状态标记 `stale`，不因字段缺失而降级或出池。

## File Map

- Modify: `src/services/candidate/types.ts`
  - 扩展交易池状态、来源、信号快照、风险标签、统计类型。
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`
  - 增加 final decision、BuyVotes、RiskFlags、强共振召回、准备介入、降级、出池规则。
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - 增加楚江新材型、泰晶科技型、高 Jump 弱共振型、风险双杀型和 stale 样例。
- Modify: `src/services/rankTrend/v5FusionExecutionContract.ts`
  - 仅在需要时增加可解释的 `resonance_observe` 辅助结果，不改变 `jump_confidence` hardBlock。
- Modify: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`
  - 锁定候选池 hardBlock 不被交易池规则放宽。
- Modify: `src/components/panels/CandidatePoolPanel.vue`
  - 补完交易池面板列表、详情、统计、筛选和操作。
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - 锁定交易池自动入池行、字段展示、历史交易日志隔离。
- Modify: `src/components/common/DataTable.vue`
  - 置信度列和 tooltip 文案拆分 Jump、综合判断、候选池结果、交易池动作。
- Modify: `docs/candidate-pool/candidate-pool-trading-pool-design.md`
  - 若实现过程中需要同步正式设计，只追加规则摘要，不改写无关章节。

## Task 1: 锁定交易池强共振规则测试

**Files:**
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [x] **Step 1: 添加楚江新材型测试**

```ts
it('recalls a jump-blocked strong consensus candidate into trading watch', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '002171',
        name: '楚江新材',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 87 } },
          jump: { direction: 'buy', confidence: 82.9 },
          technical: {
            macd: { cross: 'none' },
            signals: {
              direction: { signal: 'buy', confidence: 90 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
        candidateEntryDecision: {
          accepted: false,
          checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
        },
      },
    ],
  })

  expect(result.rows[0]).toMatchObject({
    code: '002171',
    status: '观察买点',
    decision: 'enter',
  })
  expect(result.rows[0].signalSnapshot.buyVotes).toBe(3)
  expect(result.rows[0].signalSnapshot.source).toBe('jump_blocked_resonance')
  expect(result.rows[0].reasons).toContain('jump_blocked_resonance')
})
```

- [x] **Step 2: 添加泰晶科技型测试**

```ts
it('promotes a golden-cross strong consensus candidate to ready state', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '603738',
        name: '泰晶科技',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 91 } },
          jump: { direction: 'buy', confidence: 87.9 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy', confidence: 88.83 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          cycle: { decision: { action: 'allow' } },
        },
        candidateEntryDecision: {
          accepted: false,
          checks: [{ key: 'jump_confidence', status: 'fail', hardBlock: true }],
        },
      },
    ],
  })

  expect(result.rows[0].status).toBe('准备介入')
  expect(result.rows[0].signalSnapshot.buyVotes).toBe(4)
  expect(result.rows[0].reasons).toEqual(
    expect.arrayContaining(['strong_consensus', 'macd_golden_cross', 'jump_blocked_resonance']),
  )
})
```

- [x] **Step 3: 添加高 Jump 弱共振测试**

```ts
it('does not enter trading pool on high jump alone without consensus', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '000001',
        rankTrend: {
          decision: { final: { signal: 'hold', confidence: 72 } },
          jump: { direction: 'buy', confidence: 95 },
          technical: {
            macd: { cross: 'none' },
            signals: {
              direction: { signal: 'hold', confidence: 50 },
              acceleration: { signal: 'hold', confidence: 50 },
              zeroCross: { signal: 'hold', confidence: 50 },
            },
          },
        },
      },
    ],
  })

  expect(result.rows[0].status).toBe('观察中')
  expect(result.rows[0].decision).toBe('watch')
  expect(result.rows[0].reasons).toContain('consensus_not_enough')
})
```

- [x] **Step 4: 添加风险双杀测试**

```ts
it('keeps double-risk strong consensus in watch instead of ready state', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '300000',
        rankTrend: {
          decision: { final: { signal: 'buy', confidence: 90 } },
          jump: { direction: 'buy', confidence: 88 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy', confidence: 90 },
              acceleration: { signal: 'buy', confidence: 90 },
              zeroCross: { signal: 'buy', confidence: 90 },
            },
          },
          risk: {
            overheatReversal: { signal: 'sell' },
            capitalDivergence: { signal: 'sell' },
          },
        },
      },
    ],
  })

  expect(result.rows[0].status).toBe('观察中')
  expect(result.rows[0].decision).toBe('downgrade')
  expect(result.rows[0].signalSnapshot.riskFlags).toEqual(
    expect.arrayContaining(['overheat_sell', 'capital_divergence_sell']),
  )
})
```

- [x] **Step 5: 运行 RED 验证**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: 新增断言失败，失败原因是当前交易池快照缺少 `finalConfidence`、`buyVotes`、`source`、`riskFlags` 或状态分层。

## Task 2: 扩展交易池类型和信号快照

**Files:**
- Modify: `src/services/candidate/types.ts`
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`

- [x] **Step 1: 增加类型**

```ts
export type TradingPoolSource =
  | 'candidate_auto_add'
  | 'candidate_watch'
  | 'jump_blocked_resonance'
  | 'manual'
  | 'persisted'
  | 'unknown'

export type TradingPoolRiskFlag =
  | 'lifecycle_veto'
  | 'macd_death_cross'
  | 'overheat_sell'
  | 'capital_divergence_sell'
  | 'momentum_sync_broken'
  | 'jump_confidence_low'
  | 'final_confidence_low'
  | 'candidate_hard_blocked'
  | 'data_stale'

export interface TradingPoolSignalSnapshot {
  finalSignal: string | null
  finalConfidence: number | null
  jumpDirection: string | null
  jumpConfidence: number | null
  directionSignal: string | null
  directionConfidence: number | null
  accelerationSignal: string | null
  accelerationConfidence: number | null
  zeroCrossSignal: string | null
  zeroCrossConfidence: number | null
  macdCross: string | null
  buyVotes: number
  riskFlags: TradingPoolRiskFlag[]
  source: TradingPoolSource
  momentumSyncBroken: boolean
  lifecycleAction: string | null
  dataQuality: 'fresh' | 'stale' | 'missing'
}
```

- [x] **Step 2: 增加百分制归一化工具**

```ts
function normalizeConfidence(value: unknown): number | null {
  const numeric = toOptionalNumber(value)
  if (numeric == null) return null
  return numeric <= 1 ? Math.round(numeric * 1000) / 10 : numeric
}
```

- [x] **Step 3: 扩展信号读取**

```ts
function readTradingSignals(stock: TradingPoolCandidateLike): TradingPoolSignalSnapshot {
  const rankTrend = hasOwnValue(stock, 'rankTrend') ? stock.rankTrend : null
  const direction = rankTrend?.technical?.signals?.direction
  const acceleration = rankTrend?.technical?.signals?.acceleration
  const zeroCross = rankTrend?.technical?.signals?.zeroCross
  const macdCross = rankTrend?.technical?.macd?.cross ?? stock.macdCross ?? null
  const riskFlags = readRiskFlags(rankTrend, stock, macdCross)

  const snapshot: TradingPoolSignalSnapshot = {
    finalSignal: rankTrend?.decision?.final?.signal ?? stock.finalSignal ?? null,
    finalConfidence: normalizeConfidence(rankTrend?.decision?.final?.confidence ?? stock.finalConfidence),
    jumpDirection: rankTrend?.jump?.direction ?? stock.jumpDirection ?? null,
    jumpConfidence: normalizeConfidence(rankTrend?.jump?.confidence ?? stock.jumpConfidence),
    directionSignal: direction?.signal ?? stock.directionSignal ?? null,
    directionConfidence: normalizeConfidence(direction?.confidence ?? stock.directionConfidence),
    accelerationSignal: acceleration?.signal ?? stock.accelerationSignal ?? null,
    accelerationConfidence: normalizeConfidence(acceleration?.confidence ?? stock.accelerationConfidence),
    zeroCrossSignal: zeroCross?.signal ?? stock.crossSignal ?? null,
    zeroCrossConfidence: normalizeConfidence(zeroCross?.confidence ?? stock.crossConfidence),
    macdCross,
    buyVotes: 0,
    riskFlags,
    source: resolveTradingPoolSource(stock),
    momentumSyncBroken: Boolean(rankTrend?.technical?.momentumProfile?.syncBroken),
    lifecycleAction: rankTrend?.cycle?.decision?.action ?? stock.lifecycleAction ?? null,
    dataQuality: hasOwnValue(stock, 'rankTrend') ? (rankTrend != null ? 'fresh' : 'stale') : 'missing',
  }

  snapshot.buyVotes = countBuyVotes(snapshot)
  return snapshot
}
```

- [x] **Step 4: 运行类型相关测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: 类型编译通过，规则断言仍可能失败。

## Task 3: 实现交易池自动入池状态机

**Files:**
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`

- [x] **Step 1: 增加买入票数和风险判断函数**

```ts
function countBuyVotes(signals: Pick<
  TradingPoolSignalSnapshot,
  'directionSignal' | 'accelerationSignal' | 'zeroCrossSignal' | 'macdCross'
>): number {
  return [
    signals.directionSignal === 'buy',
    signals.accelerationSignal === 'buy',
    signals.zeroCrossSignal === 'buy',
    signals.macdCross === 'golden',
  ].filter(Boolean).length
}

function hasDoubleRisk(signals: TradingPoolSignalSnapshot): boolean {
  return (
    signals.riskFlags.includes('overheat_sell') &&
    signals.riskFlags.includes('capital_divergence_sell')
  )
}

function isJumpBlockedOnly(stock: TradingPoolCandidateLike): boolean {
  const checks = stock.candidateEntryDecision?.checks || stock.entryDecision?.checks || []
  const hardBlocks = checks.filter((check: any) => check?.hardBlock && check?.status === 'fail')
  return hardBlocks.length > 0 && hardBlocks.every((check: any) => check.key === 'jump_confidence')
}

function readRiskFlags(
  rankTrend: any,
  macdCross: string | null,
  signals: TradingPoolSignalSnapshot,
): TradingPoolRiskFlag[] {
  const flags: TradingPoolRiskFlag[] = []

  if (rankTrend?.cycle?.decision?.action === 'veto' || signals.lifecycleAction === 'veto') {
    flags.push('lifecycle_veto')
  }
  if (macdCross === 'death') {
    flags.push('macd_death_cross')
  }
  if (rankTrend?.risk?.overheatReversal?.signal === 'sell') {
    flags.push('overheat_sell')
  }
  if (rankTrend?.risk?.capitalDivergence?.signal === 'sell') {
    flags.push('capital_divergence_sell')
  }
  if (signals.momentumSyncBroken) {
    flags.push('momentum_sync_broken')
  }
  if ((signals.jumpConfidence ?? 100) < TRADING_POOL_DOWNGRADE_JUMP_MIN) {
    flags.push('jump_confidence_low')
  }
  if ((signals.finalConfidence ?? 100) < TRADING_POOL_DOWNGRADE_FINAL_MIN) {
    flags.push('final_confidence_low')
  }
  if (signals.dataQuality !== 'fresh') {
    flags.push('data_stale')
  }

  return flags
}

function resolveTradingPoolSource(stock: TradingPoolCandidateLike): TradingPoolSource {
  // 候选池严格通过
  if (stock.candidateEntryDecision?.accepted) {
    return 'candidate_auto_add'
  }
  // Jump 阻断但强共振召回
  if (isJumpBlockedOnly(stock)) {
    return 'jump_blocked_resonance'
  }
  // 候选池观察中
  if (stock.candidateEntryDecision && !stock.candidateEntryDecision.accepted) {
    return 'candidate_watch'
  }
  // 手工加入（由调用方在 manual 入口设置）
  return 'unknown'
}
```

注意：`readRiskFlags` 应替代 Task 2 Step 3 中 `readTradingSignals` 内部直接调用未定义的 `readRiskFlags` 的逻辑。`readTradingSignals` 内的风险读取改为调用本函数：`const riskFlags = readRiskFlags(rankTrend, macdCross, snapshot)` 并在最后 `snapshot.riskFlags = riskFlags`。

- [x] **Step 2: 实现状态优先级**

```ts
const TRADING_POOL_RECALL_JUMP_MIN = 80
const TRADING_POOL_READY_JUMP_MIN = 85
const TRADING_POOL_OBSERVE_FINAL_MIN = 85
const TRADING_POOL_READY_FINAL_MIN = 88
const TRADING_POOL_BUY_VOTES_MIN = 3
const TRADING_POOL_DOWNGRADE_JUMP_MIN = 75
const TRADING_POOL_DOWNGRADE_FINAL_MIN = 75
const TRADING_POOL_EXIT_FINAL_SELL = 80

function decideTradingPoolStatus(
  signals: TradingPoolSignalSnapshot,
  previous?: Partial<TradingPoolAnalysisRow> | null,
): TradingPoolDecisionResult {
  const wasIntervened = previous?.status === '已介入'

  if (signals.dataQuality !== 'fresh') {
    return {
      status: (previous?.status as TradingPoolStatus) || '观察中',
      decision: 'stale',
      reasons: ['signal_stale'],
    }
  }

  // 强制出池（对所有状态生效，含已介入）
  if (signals.lifecycleAction === 'veto') {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'] }
  }

  if (signals.macdCross === 'death' && (signals.directionSignal !== 'buy' || signals.zeroCrossSignal === 'sell')) {
    return { status: '已退出', decision: 'exit', reasons: ['macd_death_cross'] }
  }

  if (signals.finalSignal === 'sell' && (signals.finalConfidence ?? 0) >= TRADING_POOL_EXIT_FINAL_SELL) {
    return { status: '已退出', decision: 'exit', reasons: ['final_sell_signal'] }
  }

  // 已介入状态：降级门槛更高，轻微走弱仅展示风险不降级（7.7）
  if (wasIntervened) {
    if (signals.finalSignal === 'hold' && (signals.finalConfidence ?? 0) < TRADING_POOL_OBSERVE_FINAL_MIN) {
      return { status: '观察中', decision: 'downgrade', reasons: ['intervened_consensus_weakened'] }
    }
    if (signals.buyVotes <= 1 && (signals.jumpConfidence ?? 0) < TRADING_POOL_DOWNGRADE_JUMP_MIN) {
      return { status: '观察中', decision: 'downgrade', reasons: ['intervened_votes_and_jump_low'] }
    }
    return {
      status: '已介入',
      decision: 'stale',
      reasons: signals.riskFlags.length > 0 ? ['intervened_keep_with_risk'] : ['intervened_keep'],
    }
  }

  // 强制出池：BuyVotes <= 1 且 Jump < 75（7.5，AND 关系）
  if (signals.buyVotes <= 1 && (signals.jumpConfidence ?? 0) < TRADING_POOL_DOWNGRADE_JUMP_MIN) {
    return { status: '已退出', decision: 'exit', reasons: ['low_votes_and_jump'] }
  }

  // 降级观察：以下单项满足即降级（7.4）
  if ((signals.finalConfidence ?? 0) < TRADING_POOL_DOWNGRADE_FINAL_MIN) {
    return { status: '观察中', decision: 'downgrade', reasons: ['consensus_not_enough'] }
  }

  if (signals.momentumSyncBroken) {
    return { status: '观察中', decision: 'downgrade', reasons: ['momentum_sync_broken'] }
  }

  const strongConsensus =
    signals.finalSignal === 'buy' &&
    (signals.finalConfidence ?? 0) >= TRADING_POOL_OBSERVE_FINAL_MIN &&
    signals.buyVotes >= TRADING_POOL_BUY_VOTES_MIN &&
    signals.jumpDirection === 'buy' &&
    (signals.jumpConfidence ?? 0) >= TRADING_POOL_RECALL_JUMP_MIN &&
    [signals.directionSignal, signals.accelerationSignal, signals.zeroCrossSignal].filter((item) => item === 'buy').length >= 2

  if (!strongConsensus) {
    return { status: '观察中', decision: 'watch', reasons: ['consensus_not_enough'] }
  }

  // 双风险检查（7.4a）
  if (hasDoubleRisk(signals)) {
    return { status: '观察中', decision: 'downgrade', reasons: ['double_risk'] }
  }

  const ready =
    (signals.finalConfidence ?? 0) >= TRADING_POOL_READY_FINAL_MIN &&
    (signals.jumpConfidence ?? 0) >= TRADING_POOL_READY_JUMP_MIN &&
    (signals.macdCross === 'golden' || (signals.zeroCrossSignal === 'buy' && signals.directionSignal === 'buy'))

  return ready
    ? { status: '准备介入', decision: 'enter', reasons: ['strong_consensus', 'macd_golden_cross'] }
    : { status: '观察买点', decision: 'enter', reasons: ['strong_consensus'] }
}
```

- [x] **Step 3: 合并来源和原因到最终结果**

```ts
// 根据候选池检查结果和传入的 signals.source 确定最终来源
const source = resolveTradingPoolSource(candidate)
// 若 signals.source 已经是 persisted 或 manual，优先保留
const finalSource = signals.source === 'persisted' || signals.source === 'manual'
  ? signals.source
  : source

const reasons = finalSource === 'jump_blocked_resonance'
  ? [...decisionResult.reasons, 'jump_blocked_resonance']
  : decisionResult.reasons
```

- [x] **Step 4: 运行服务测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: 服务测试全部通过。

### Task 3 实施复核补充

Code review 后将以下行为明确纳入实际合同，避免后续维护者只按早期伪代码推断状态机：

- 新候选和历史候选一视同仁：`finalConfidence < 75` 时保留在 `观察中`，但 `decision='downgrade'`，原因包含 `consensus_not_enough`。该语义用于统计“信号降级”，不再依赖 `previous` 是否存在。
- `jumpConfidence < 80` 是交易池召回质量门槛，未达到时降为 `观察中 / downgrade / jump_confidence_low`；`jumpConfidence < 75` 仍作为更强的低 Jump 风险标签。
- 候选池存在非 Jump 硬阻断时，交易池不允许通过 `strongConsensus` 进入 `观察买点` 或 `准备介入`，风险标签为 `candidate_hard_blocked`。交易池召回只承接 Jump 阈值阻断，不承接样本质量、生命周期 veto 等其它硬阻断。
- `macdCross='death'` 即使未触发强制出池，也不允许进入 `strongConsensus`。死叉叠加方向走弱或零线卖出时优先 `已退出`。
- 四信号全共振（方向买入、MACD 金叉、动量加速买入、零线买入）在未达到准备介入门槛时进入 `观察买点`，原因除 `strong_consensus` 外追加 `signal_resonance`，用于 tooltip 和交易池面板解释。
- 过热风险兼容新旧字段：`rankTrend.risk.overheatReversal`、`rankTrend.risk.overheat`、`stock.overheatSignal` 是 OR 聚合来源；任一来源给出 `sell` 即标记 `overheat_sell`。

## Task 4: 保护候选池严格合同

**Files:**
- Modify: `src/services/rankTrend/v5FusionExecutionContract.ts`
- Modify: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`

- [x] **Step 1: 覆盖三种策略模式的 Jump 阈值不放宽测试**

```ts
it('keeps jump confidence as a hard block for strict_execution (Jump >= 90)', () => {
  const result = evaluateV5FusionEntry(
    {
      jump: { direction: 'buy', confidence: 87.9 },
      decision: { final: { signal: 'buy', confidence: 91 } },
      technical: {
        macd: { cross: 'golden' },
        signals: {
          direction: { signal: 'buy', confidence: 90 },
          acceleration: { signal: 'buy', confidence: 90 },
          zeroCross: { signal: 'buy', confidence: 90 },
        },
      },
    } as any,
    { ...V5_FUSION_DEFAULTS, minJumpConfidence: 90 },
  )

  expect(result.entryDecision.accepted).toBe(false)
  expect(result.entryDecision.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
    status: 'fail',
    hardBlock: true,
  })
})

it('keeps jump confidence as a hard block for balanced (Jump >= 85)', () => {
  const result = evaluateV5FusionEntry(
    {
      jump: { direction: 'buy', confidence: 82.9 },
      decision: { final: { signal: 'buy', confidence: 87 } },
      technical: {
        macd: { cross: 'none' },
        signals: {
          direction: { signal: 'buy', confidence: 90 },
          acceleration: { signal: 'buy', confidence: 90 },
          zeroCross: { signal: 'buy', confidence: 90 },
        },
      },
    } as any,
    { ...V5_FUSION_DEFAULTS, minJumpConfidence: 85 },
  )

  expect(result.entryDecision.accepted).toBe(false)
  expect(result.entryDecision.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
    status: 'fail',
    hardBlock: true,
  })
})

it('keeps jump confidence as a hard block for recall_first (Jump >= 80)', () => {
  const result = evaluateV5FusionEntry(
    {
      jump: { direction: 'buy', confidence: 78 },
      decision: { final: { signal: 'buy', confidence: 86 } },
      technical: {
        macd: { cross: 'golden' },
        signals: {
          direction: { signal: 'buy', confidence: 90 },
          acceleration: { signal: 'buy', confidence: 90 },
          zeroCross: { signal: 'buy', confidence: 90 },
        },
      },
    } as any,
    { ...V5_FUSION_DEFAULTS, minJumpConfidence: 80 },
  )

  expect(result.entryDecision.accepted).toBe(false)
  expect(result.entryDecision.checks.find((check) => check.key === 'jump_confidence')).toMatchObject({
    status: 'fail',
    hardBlock: true,
  })
})
```

- [x] **Step 2: 如需输出强共振观察，仅新增解释字段（先确认类型扩展可行性）**

在开始实现前，检查 `entryDecision` 的类型定义是否允许扩展 `resonanceObserve` 字段。若不允许，由 `TradingPoolAnalysisService` 自行根据 checks 推导来源，不修改 V5 合同类型。

```ts
// 不改变 accepted / hardBlock，只给 UI 或交易池读取解释。
entryDecision.resonanceObserve = {
  eligible: true,
  reason: 'jump_blocked_strong_consensus',
}
```

如果现有类型不允许扩展 `entryDecision`，跳过此步骤，由 `TradingPoolAnalysisService` 自行根据 checks 推导来源。

- [x] **Step 3: 运行 RankTrend 合同测试**

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts --reporter=dot
```

Expected: 候选池 strict Jump hardBlock 仍然存在。

## Task 5: 补完交易池面板

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [x] **Step 1: 添加面板字段契约测试**

```ts
it('renders trading pool resonance fields and source labels', async () => {
  const wrapper = mountCandidatePoolPanelWithTradingRows([
    {
      code: '603738',
      name: '泰晶科技',
      status: '准备介入',
      decision: 'enter',
      reasons: ['strong_consensus', 'jump_blocked_resonance'],
      signalSnapshot: {
        finalSignal: 'buy',
        finalConfidence: 91,
        jumpDirection: 'buy',
        jumpConfidence: 87.9,
        directionSignal: 'buy',
        directionConfidence: 88.83,
        accelerationSignal: 'buy',
        accelerationConfidence: 90,
        zeroCrossSignal: 'buy',
        zeroCrossConfidence: 90,
        macdCross: 'golden',
        buyVotes: 4,
        riskFlags: [],
        source: 'jump_blocked_resonance',
        momentumSyncBroken: false,
        lifecycleAction: 'allow',
        dataQuality: 'fresh',
      },
    },
  ])

  await wrapper.find('[data-testid="candidate-pool-tab-trading"]').trigger('click')

  expect(wrapper.text()).toContain('泰晶科技')
  expect(wrapper.text()).toContain('准备介入')
  expect(wrapper.text()).toContain('综合 91')
  expect(wrapper.text()).toContain('Jump 87.9')
  expect(wrapper.text()).toContain('4/4')
  expect(wrapper.text()).toContain('Jump阻断强共振')
})
```

- [x] **Step 2: 增加统计计算**

```ts
const tradingPoolStats = computed(() => ({
  total: tradingPoolRows.value.length,
  watch: tradingPoolRows.value.filter((row) => row.status === '观察买点').length,
  ready: tradingPoolRows.value.filter((row) => row.status === '准备介入').length,
  intervened: tradingPoolRows.value.filter((row) => row.status === '已介入').length,
  exited: tradingPoolRows.value.filter((row) => row.status === '已退出').length,
  stale: tradingPoolRows.value.filter((row) => row.decision === 'stale').length,
}))
```

- [x] **Step 3: 增加交易池筛选**

```ts
const tradingDecisionFilter = ref('')
const tradingStatusFilter = ref('')

const visibleTradingPoolRows = computed(() =>
  tradingPoolRows.value.filter((row) => {
    if (keyword.value) {
      const text = `${row.code} ${row.name || ''}`
      if (!text.includes(keyword.value)) return false
    }
    if (tradingDecisionFilter.value && row.decision !== tradingDecisionFilter.value) return false
    if (tradingStatusFilter.value && row.status !== tradingStatusFilter.value) return false
    return true
  }),
)
```

- [x] **Step 4: 更新交易池表头和行字段**

```vue
<div class="trading-pool-row trading-pool-head">
  <span>股票</span>
  <span>来源</span>
  <span>状态</span>
  <span>综合</span>
  <span>Jump</span>
  <span>票数</span>
  <span>MACD</span>
  <span>风险</span>
  <span>原因</span>
  <span>操作</span>
</div>
```

```vue
<span>{{ tradingPoolSourceLabel(row.signalSnapshot.source) }}</span>
<span>综合 {{ formatTradingPoolValue(row.signalSnapshot.finalConfidence, 0) }}</span>
<span>Jump {{ formatTradingPoolValue(row.signalSnapshot.jumpConfidence, 1) }}</span>
<span>{{ row.signalSnapshot.buyVotes }}/4</span>
<span>{{ formatRiskFlags(row.signalSnapshot.riskFlags) }}</span>
```

- [x] **Step 5: 增加详情区**

```vue
<section v-if="selectedTradingPoolRow" class="trading-pool-detail">
  <h4>{{ selectedTradingPoolRow.name || selectedTradingPoolRow.code }}</h4>
  <p>候选池结果：{{ tradingPoolSourceLabel(selectedTradingPoolRow.signalSnapshot.source) }}</p>
  <p>交易池判定：{{ selectedTradingPoolRow.status }} / {{ tradingPoolDecisionLabel(selectedTradingPoolRow.decision) }}</p>
  <p>信号矩阵：综合 {{ selectedTradingPoolRow.signalSnapshot.finalConfidence ?? '-' }}，Jump {{ selectedTradingPoolRow.signalSnapshot.jumpConfidence ?? '-' }}，买入票 {{ selectedTradingPoolRow.signalSnapshot.buyVotes }}/4</p>
  <p>风险：{{ formatRiskFlags(selectedTradingPoolRow.signalSnapshot.riskFlags) }}</p>
</section>
```

- [x] **Step 6: 运行面板测试**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
```

Expected: 面板测试通过，交易池不再只显示空记录状态。

## Task 6: 收敛 DataTable 置信度 tooltip

**Files:**
- Modify: `src/components/common/DataTable.vue`

- [x] **Step 1: 将列文案从跃迁置信度收敛为 Jump置信**

```ts
{ key: 'confidence', label: 'Jump置信', group: 'comprehensive', always: true },
```

- [x] **Step 2: tooltip 增加综合、Jump、候选池、交易池四段**

```ts
const tradingPoolAction = getTradingPoolActionPreview(stock)
const candidatePoolReason = getCandidatePoolReasonPreview(stock)

return [
  `综合判断: ${finalSignalLabel} (置信度: ${finalConfidence}%)`,
  `Jump跃迁: ${jumpConfidence}% (候选池阈值: ${candidateJumpThreshold || '-'} / ${candidateJumpPassed ? '已过' : '未过'})`,
  `共振评级: ${tradingPoolAction.resonanceLabel} (BuyVotes: ${tradingPoolAction.buyVotes}/4)`,
  `候选池: ${candidatePoolReason}`,
  `交易池: ${tradingPoolAction.actionLabel}`,
  '',
  existingSignalLines,
].filter(Boolean).join('\n')
```

- [x] **Step 3: 避免 tooltip 里业务规则重复实现**

如果 `getTradingPoolActionPreview(stock)` 需要规则判断，优先调用 `analyzeTradingPoolCandidate({ candidates: [stock] })`，不要在 `DataTable.vue` 复制一套阈值。

- [x] **Step 4: 运行 DataTable 相关类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: 类型检查通过。

## Task 7: 文档同步

**Files:**
- Modify: `docs/candidate-pool/candidate-pool-trading-pool-design.md`
- Optional Modify: `docs/candidate-pool/task_plan.md`
- Optional Modify: `docs/candidate-pool/progress.md`

- [x] **Step 1: 在双池设计文档追加规则摘要和 V2 兼容说明**

```md
### 强共振召回补充

候选池严格入池不放宽 Jump hardBlock；交易池新增 `jump_blocked_resonance` 来源，用于承接 final buy、综合置信 >=85、BuyVotes >=3、Jump >=80 且无 veto/death 的买点观察。

### V2 持久化向前兼容

Phase 18 已存在的 `tradeType=trading_pool` 记录可能在 `signalsSnapshot.tradingPool` 中缺少 `buyVotes`、`riskFlags`、`source`、`momentumSyncBroken` 等字段。加载旧记录时，若实时 RankTrend 可用则以当前规则重新计算缺失字段；不可用时保留旧快照并标记 `dataQuality=stale`，不因字段缺失而降级或出池。
```

- [x] **Step 2: 仅在执行完成后更新 progress**

```md
## 2026-06-15 Phase XX 交易池强共振自动入池

- 已补充强共振自动入池规则。
- 已补完交易池面板字段和 tooltip 语义。
- 验证命令：...
```

不要在实现前把 progress 标成完成。

## Task 8: 验证和浏览器验收

**Files:**
- No source edits beyond previous tasks.

- [x] **Step 1: 运行交易池服务测试**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts --reporter=dot
```

Expected: PASS.

- [x] **Step 2: 运行候选池面板测试**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts --reporter=dot
```

Expected: PASS.

- [x] **Step 3: 运行 RankTrend 验证**

```powershell
pnpm test:ranktrend
pnpm typecheck:ranktrend
```

Expected: PASS，候选池严格合同未被放宽。

- [x] **Step 4: 运行应用类型检查**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: exit code 0.

- [x] **Step 5: 启动 dev server 并 Playwright 验收主表 tooltip**

```powershell
# 终端 1：启动 dev server（若尚未运行）
pnpm dev

# 终端 2：浏览器验收
npx --yes --package @playwright/cli playwright-cli -s=ranktrend open http://localhost:5173 --headed
```

Expected:

- `confidence` 表头显示 `Jump置信`。
- hover `603738` 或同类行时，tooltip 同时展示综合判断、Jump 阈值、共振评级、候选池结果和交易池动作。

- [x] **Step 6: Playwright 验收交易池面板**

```powershell
npx --yes --package @playwright/cli playwright-cli -s=ranktrend eval "await page.getByText('候选池').click(); await page.getByTestId('candidate-pool-tab-trading').click();"
```

Expected:

- 交易池面板不再只有空态。
- 自动入池行展示状态、来源、综合置信度、Jump、BuyVotes、风险和原因。
- `已介入` 操作不生成历史 `entry` 记录。

## Task 9: 自审清单

- [x] 候选池 `jump_confidence` hardBlock 未被交易池规则改写。
- [x] 交易池自动入池规则不依赖单只股票代码。
- [x] Jump 置信度统一百分制，兼容 `0-1` 和 `0-100` 输入。
- [x] tooltip 没有再把 Jump 置信度称为综合置信度。
- [x] 交易池面板能解释为什么入池、为什么降级、为什么退出。
- [x] 文档、测试、UI 文案使用同一套状态词。
- [x] 未修改无关 QuantBoard 后端、数据库或历史交易日志逻辑。
