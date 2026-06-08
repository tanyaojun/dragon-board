# RankTrend Fusion Candidate Pool Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 废弃主表 `【信号】` 语义链路，让 `ranktrend_early_big_move_v3_lifecycle_fusion` 命中后自动写入候选池，主表只显示 `【候选池】` 状态并作为候选池入口。

**Architecture:** 先把候选池创建合同补成可表达 `triggered + source + signalsSnapshot` 的自动入池入口，再新增一个只负责 fusion 自动入池的 notifier 并接到现有实时刷新链路上。随后引入一层候选池状态投影，把主表列从 `【信号】` 切成 `【候选池】` 状态展示，最后删除 `liveV3SignalMapper` 及其调用与测试。

**Tech Stack:** Vue 3, TypeScript, Vitest, EventManager, QuantBoard journal API

---

## File Map

- Create: `src/services/rankTrend/fusionStrategy.ts`
  - 纯规则 helper，判断单只股票当前是否命中 `ranktrend_early_big_move_v3_lifecycle_fusion` 自动入池条件
- Create: `src/services/rankTrend/FusionCandidateNotifier.ts`
  - 命中主线策略时自动写入候选池，避免重复创建 open candidate
- Create: `src/services/rankTrend/__tests__/fusionStrategy.test.ts`
  - 锁定 fusion 自动入池门槛
- Create: `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`
  - 锁定自动入池 `status=triggered`、来源字段和去重
- Create: `src/services/candidate/CandidatePoolStatusProjector.ts`
  - 一次性读取 open candidates，把候选池状态投影回主表股票行
- Create: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
  - 锁定主表状态投影文案与开池状态映射
- Modify: `src/services/candidate/CandidateJournalService.ts`
  - 让 `addCandidateFromStock()` 支持自动入池来源、状态覆写和 `signalsSnapshot` 补丁
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
  - 去掉 `liveV3SignalMapper`，接入 fusion notifier 与 candidate pool status projector
- Modify: `src/components/common/DataTable.vue`
  - 把原 `【信号】` 列改为 `【候选池】`，显示候选池状态 badge，并复用已有 `candidate-pool:open` 入口
- Modify: `src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`
  - 更新实时刷新链路断言：不再产生 `liveV3SignalDecision`，改为刷新候选池状态与自动入池调用
- Modify: `src/components/common/__tests__/DataTable.test.ts`
  - 更新列文案与事件断言
- Delete: `src/services/rankTrend/liveV3SignalMapper.ts`
- Delete: `src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`
- Modify: `quant-board/docs/superpowers/specs/2026-06-07-ranktrend-v3-live-signal-mapping-design.md`
  - 标记旧方案已被 2026-06-08 候选池方案取代，避免后续误读

---

### Task 1: CandidateJournal 自动入池合同 RED/GREEN

**Files:**
- Modify: `src/services/candidate/CandidateJournalService.ts`
- Modify: `src/services/candidate/__tests__/CandidateJournalService.test.ts`

- [ ] **Step 1: 写失败测试，锁定自动入池必须落成 `triggered` + 来源补丁**

```ts
it('uses status override and snapshot patch when auto-creating a fusion candidate', async () => {
  const api = {
    get: vi.fn().mockResolvedValue({ entries: [] }),
    post: vi.fn().mockResolvedValue({ id: 'fusion-1', stockCode: '600001', status: 'triggered', tradeType: 'thesis' }),
    put: vi.fn(),
    delete: vi.fn(),
  }

  const analyze = vi.fn().mockReturnValue({
    score: 82,
    grade: 'A',
    suggestedStatus: 'candidate',
    entryReason: '原始候选解释',
    tradeHypothesis: '原始假设',
    entryPrerequisites: '原始前提',
    invalidationRules: '原始失效条件',
    riskWarnings: [],
    strengths: [],
    weaknesses: [],
    evidence: [],
    penalties: [],
    structuredThesis: { triggerConditions: [], entryPrerequisites: [], invalidationConditions: [] },
    structuredRisks: [],
    tags: ['ranktrend'],
    scoreBreakdown: { rankTrend: 30, theme: 10, dragon: 10, sentiment: 20, moneyFlow: 12 },
    signalsSnapshot: { rankTrend: { strategy: { candidateTier: 'A_MAIN' } } },
  })

  const service = new CandidateJournalService({ api: api as any, analyze })

  await service.addCandidateFromStock(
    { code: '600001', name: '测试股', price: 12.3 },
    {
      source: 'ranktrend-v3-lifecycle-fusion',
      statusOverride: 'triggered',
      signalsSnapshotPatch: {
        triggerMeta: {
          source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
          triggerType: 'auto',
        },
      },
    },
  )

  expect(api.post).toHaveBeenCalledWith(
    '/api/journal/entries',
    expect.objectContaining({
      status: 'triggered',
      signals_snapshot: expect.objectContaining({
        triggerMeta: expect.objectContaining({
          source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
          triggerType: 'auto',
        }),
      }),
      review_notes: expect.stringContaining('ranktrend-v3-lifecycle-fusion'),
    }),
    expect.anything(),
  )
})
```

- [ ] **Step 2: 跑测试，确认当前实现失败**

Run: `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts -t "uses status override and snapshot patch when auto-creating a fusion candidate"`

Expected: FAIL，提示 `statusOverride` / `signalsSnapshotPatch` 未生效，或 `review_notes` 不包含自动来源。

- [ ] **Step 3: 最小实现 `addCandidateFromStock()` 的自动入池选项**

```ts
interface AddCandidateOptions {
  addToFavorites?: boolean
  source?: string
  statusOverride?: CandidateStatus
  signalsSnapshotPatch?: Record<string, any>
}

private buildCreatePayload(
  stock: CandidateStockLike,
  analysis: CandidateAnalysisResult,
  options: AddCandidateOptions = {},
) {
  const baseSnapshot = analysis.signalsSnapshot || {}
  const mergedSnapshot = {
    ...baseSnapshot,
    ...(options.signalsSnapshotPatch || {}),
  }
  const reviewNotes = options.source ? `[自动入池] ${options.source}` : ''

  return {
    stock_code: normalizeCode(stock.code),
    stock_name: stock.name || normalizeCode(stock.code),
    direction: 'buy',
    trade_type: 'thesis',
    price: Number(stock.price || 0),
    volume: 0,
    signals_snapshot: mergedSnapshot,
    notes: '',
    status: options.statusOverride || analysis.suggestedStatus,
    market_phase: String(mergedSnapshot?.sentiment?.phaseName || ''),
    theme_role: String(mergedSnapshot?.theme?.exposures?.[0]?.role || ''),
    stock_role: String(mergedSnapshot?.dragon?.primaryRole || ''),
    entry_reason: analysis.entryReason,
    trade_hypothesis: analysis.tradeHypothesis,
    entry_prerequisites: analysis.entryPrerequisites,
    invalidation_rules: analysis.invalidationRules,
    expected_holding_days: 3,
    human_decision: 'watch',
    skip_reason: '',
    review_outcome: 'pending',
    model_result: 'unknown',
    execution_result: 'unknown',
    review_notes: reviewNotes,
    review_tags: analysis.tags,
  }
}

const payload = this.buildCreatePayload(context.stock, analysis, options)
```

- [ ] **Step 4: 重新运行 CandidateJournal 测试**

Run: `pnpm exec vitest run src/services/candidate/__tests__/CandidateJournalService.test.ts`

Expected: PASS，包含新增的自动入池测试与原有去重测试全部通过。

- [ ] **Step 5: Commit**

```powershell
git add src/services/candidate/CandidateJournalService.ts src/services/candidate/__tests__/CandidateJournalService.test.ts
git commit -m "feat: support fusion auto candidate creation"
```

---

### Task 2: Fusion 自动入池 notifier RED/GREEN

**Files:**
- Create: `src/services/rankTrend/fusionStrategy.ts`
- Create: `src/services/rankTrend/FusionCandidateNotifier.ts`
- Create: `src/services/rankTrend/__tests__/fusionStrategy.test.ts`
- Create: `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

- [ ] **Step 1: 写失败测试，先锁定 fusion 单票门槛**

```ts
describe('isFusionEntryCandidate', () => {
  it('returns true for A_MAIN + base gate + lifecycle not veto', () => {
    const result = isFusionEntryCandidate({
      code: '600001',
      change: 3.2,
      accDelta: 9,
      rankTrend: {
        jump: { direction: 'buy', confidence: 92 },
        technical: {
          signals: { zeroCross: { signal: 'hold' } },
          momentumProfile: { short: 12, mid: 18, long: 11, acceleration: 12 },
        },
        cycle: { decision: { action: 'allow' } },
        strategy: { candidateTier: 'A_MAIN' },
      },
    })

    expect(result).toBe(true)
  })

  it('returns false when lifecycle action is veto', () => {
    expect(
      isFusionEntryCandidate({
        code: '600001',
        change: 3.2,
        accDelta: 9,
        rankTrend: {
          jump: { direction: 'buy', confidence: 92 },
          technical: {
            signals: { zeroCross: { signal: 'buy' } },
            momentumProfile: { short: 12, mid: 22, long: 11, acceleration: 12 },
          },
          cycle: { decision: { action: 'veto' } },
          strategy: { candidateTier: 'B_IGNITION' },
        },
      }),
    ).toBe(false)
  })
})
```

- [ ] **Step 2: 再写失败测试，锁定 notifier 自动入池必须走 `triggered`**

```ts
it('creates triggered candidate entries for fusion hits and skips duplicates', async () => {
  const addCandidateFromStock = vi.fn().mockResolvedValue({ created: true, entry: { id: 'entry-1' } })
  const getOpenCandidateForStock = vi.fn()
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce({ id: 'existing-1', status: 'triggered' })

  const notifier = new FusionCandidateNotifier({
    candidateJournal: {
      addCandidateFromStock,
      getOpenCandidateForStock,
    } as any,
  })

  await notifier.processStocks([
    createFusionHitStock('600001'),
    createFusionHitStock('600002'),
  ])

  expect(addCandidateFromStock).toHaveBeenCalledTimes(1)
  expect(addCandidateFromStock).toHaveBeenCalledWith(
    expect.objectContaining({ code: '600001' }),
    expect.objectContaining({
      source: 'ranktrend-v3-lifecycle-fusion',
      statusOverride: 'triggered',
    }),
  )
})
```

- [ ] **Step 3: 跑两组测试，确认当前实现失败**

Run: `pnpm exec vitest run src/services/rankTrend/__tests__/fusionStrategy.test.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

Expected: FAIL，提示 helper / notifier 文件不存在。

- [ ] **Step 4: 最小实现规则 helper 与 notifier**

```ts
export function isFusionEntryCandidate(stock: any): boolean {
  const rankTrend = stock?.rankTrend
  const tier = String(rankTrend?.strategy?.candidateTier || '')
  const lifecycleAction = String(rankTrend?.cycle?.decision?.action || '')
  const jumpDirection = String(rankTrend?.jump?.direction || '')
  const jumpConfidence = Number(rankTrend?.jump?.confidence || 0)
  const momentum = rankTrend?.technical?.momentumProfile || rankTrend?.strategy?.momentum || {}
  const short = Number(momentum.short || 0)
  const mid = Number(momentum.mid || 0)
  const long = Number(momentum.long || 0)
  const acceleration = Number(momentum.acceleration || 0)
  const accDelta = Number(stock?.accDelta || 0)
  const change = Number(stock?.change || 0)
  const zeroCross = String(rankTrend?.technical?.signals?.zeroCross?.signal || 'none')

  const baseGate =
    jumpDirection === 'buy' &&
    jumpConfidence >= 90 &&
    short > 0 &&
    mid > 0 &&
    long > 0 &&
    (acceleration >= 10 || accDelta >= 8) &&
    change < 6 &&
    !isLimitUpBlocked(stock)

  if (!baseGate || lifecycleAction === 'veto') return false
  if (tier === 'A_MAIN') return true
  return tier === 'B_IGNITION' && mid >= 20 && zeroCross === 'buy'
}

export class FusionCandidateNotifier {
  async processStocks(stocks: any[]): Promise<void> {
    for (const stock of stocks) {
      if (!isFusionEntryCandidate(stock)) continue
      const code = String(stock?.code || '')
      if (!code) continue
      const existing = await this.candidateJournal.getOpenCandidateForStock(code)
      if (existing) continue
      await this.candidateJournal.addCandidateFromStock(stock, {
        addToFavorites: true,
        source: 'ranktrend-v3-lifecycle-fusion',
        statusOverride: 'triggered',
        signalsSnapshotPatch: {
          triggerMeta: {
            source: 'ranktrend_early_big_move_v3_lifecycle_fusion',
            triggerType: 'auto',
            triggeredAt: new Date().toISOString(),
          },
        },
      })
    }
  }
}
```

- [ ] **Step 5: 运行 notifier 相关测试**

Run: `pnpm exec vitest run src/services/rankTrend/__tests__/fusionStrategy.test.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

Expected: PASS，自动入池只在 fusion 命中且无 open candidate 时触发。

- [ ] **Step 6: Commit**

```powershell
git add src/services/rankTrend/fusionStrategy.ts src/services/rankTrend/FusionCandidateNotifier.ts src/services/rankTrend/__tests__/fusionStrategy.test.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
git commit -m "feat: add fusion auto candidate notifier"
```

---

### Task 3: 主表改成候选池状态投影 RED/GREEN

**Files:**
- Create: `src/services/candidate/CandidatePoolStatusProjector.ts`
- Create: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`
- Modify: `src/services/dataLoader/RankTrendSignalService.ts`
- Modify: `src/components/common/DataTable.vue`
- Modify: `src/components/common/__tests__/DataTable.test.ts`

- [ ] **Step 1: 写失败测试，锁定状态投影文案**

```ts
it('maps open candidate entries back to table-friendly status labels', () => {
  const stocks = [
    { code: '600001', name: '甲' },
    { code: '600002', name: '乙' },
  ]

  const entries = [
    { stockCode: '600001', status: 'triggered', id: 'entry-1' },
  ]

  const result = projectCandidatePoolStatus(stocks as any[], entries as any[])

  expect(result[0]).toMatchObject({
    candidatePoolStatus: 'triggered',
    candidatePoolLabel: '已触发',
    candidatePoolEntryId: 'entry-1',
  })
  expect(result[1]).toMatchObject({
    candidatePoolStatus: 'none',
    candidatePoolLabel: '未入池',
  })
})
```

- [ ] **Step 2: 再写 DataTable 失败测试，锁定列名必须从 `信号` 变成 `候选池`**

```ts
it('renders candidate pool status instead of legacy signal labels', async () => {
  const source = await fs.promises.readFile('src/components/common/DataTable.vue', 'utf8')
  expect(source).toContain("{ key: 'jumpSignal', label: '候选池'")
  expect(source).toContain('candidatePoolLabel')
  expect(source).not.toContain('getLiveV3Signal(')
})
```

- [ ] **Step 3: 跑状态投影与 DataTable 测试，确认失败**

Run: `pnpm exec vitest run src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts src/components/common/__tests__/DataTable.test.ts`

Expected: FAIL，提示投影 helper 不存在，DataTable 仍在使用旧信号标签。

- [ ] **Step 4: 最小实现状态投影，并接入刷新链路**

```ts
const STATUS_LABELS = {
  none: '未入池',
  observe: '观察',
  candidate: '候选',
  triggered: '已触发',
  tracking: '跟踪中',
  reviewed: '已复盘',
} as const

export async function applyCandidatePoolStatus(stocks: any[], candidateJournal = candidateJournalService) {
  const entries = await candidateJournal.listCandidates({ limit: 200 })
  const openByCode = new Map(
    entries
      .filter((entry) => ['observe', 'candidate', 'triggered', 'tracking', 'reviewed'].includes(entry.status))
      .map((entry) => [entry.stockCode, entry]),
  )

  for (const stock of stocks) {
    const code = String(stock?.code || '').replace(/\D/g, '').padStart(6, '0').slice(-6)
    const entry = openByCode.get(code)
    const status = entry?.status || 'none'
    stock.candidatePoolStatus = status
    stock.candidatePoolLabel = STATUS_LABELS[status as keyof typeof STATUS_LABELS] || '未入池'
    stock.candidatePoolEntryId = entry?.id || ''
  }

  return stocks
}
```

```ts
// RankTrendSignalService.refreshRankTrendSignals()
const mergedStocks = this.updateStockSignals(updates)
this.applyJumpSignals(mergedStocks)
await this.fusionCandidateNotifier.processStocks(mergedStocks)
await applyCandidatePoolStatus(mergedStocks)
return mergedStocks
```

```vue
{ key: 'jumpSignal', label: '候选池', group: 'comprehensive', always: true }

<template v-else-if="col.key === 'jumpSignal'">
  <div class="jump-signal-cell">
    <span
      class="jump-badge candidate-pool-badge"
      :class="`candidate-pool-${stock.candidatePoolStatus || 'none'}`"
      :title="getCandidatePoolTitle(stock)"
      @click.stop="openCandidatePoolFromCell(stock)"
    >{{ stock.candidatePoolLabel || '未入池' }}</span>
  </div>
</template>
```

- [ ] **Step 5: 跑主表相关测试**

Run: `pnpm exec vitest run src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts src/components/common/__tests__/DataTable.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`

Expected: PASS，主表不再依赖 `liveV3SignalDecision`，候选池状态能投影到股票行。

- [ ] **Step 6: Commit**

```powershell
git add src/services/candidate/CandidatePoolStatusProjector.ts src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts src/services/dataLoader/RankTrendSignalService.ts src/components/common/DataTable.vue src/components/common/__tests__/DataTable.test.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts
git commit -m "feat: show candidate pool status in main table"
```

---

### Task 4: 删除旧信号链并同步文档 RED/GREEN

**Files:**
- Delete: `src/services/rankTrend/liveV3SignalMapper.ts`
- Delete: `src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts`
- Modify: `quant-board/docs/superpowers/specs/2026-06-07-ranktrend-v3-live-signal-mapping-design.md`

- [ ] **Step 1: 写失败测试，锁定旧信号链已被移除**

```ts
it('removes the legacy live V3 signal mapper import from refresh service', async () => {
  const source = await fs.promises.readFile('src/services/dataLoader/RankTrendSignalService.ts', 'utf8')
  expect(source).not.toContain("liveV3SignalMapper")
  expect(source).not.toContain('applyLiveV3SignalDecisions')
})
```

- [ ] **Step 2: 运行测试确认当前仍失败**

Run: `pnpm exec vitest run src/services/dataLoader/__tests__/RankTrendSignalService.test.ts`

Expected: FAIL，旧 import 仍存在，或快照测试仍断言 `liveV3SignalDecision`。

- [ ] **Step 3: 删除文件并更新旧 spec 为 superseded**

```md
# RankTrend V3 实盘信号映射到行情列表——设计规格

> **状态更新（2026-06-08）：** 本方案已被
> `2026-06-08-ranktrend-fusion-candidate-pool-replacement-design.md`
> 取代。后续实现不再沿用主表 `【信号】` 动作标签方向，而改用
> `【候选池】` 状态入口 + fusion 自动入池。
```

- [ ] **Step 4: 运行 ranktrend 相关测试，确认删除后链路稳定**

Run: `pnpm test:ranktrend`

Expected: PASS，旧 `liveV3SignalMapper` 测试不再参与，新增 fusion / candidate pool 测试通过。

- [ ] **Step 5: 运行类型检查**

Run: `pnpm typecheck:ranktrend`

Expected: PASS，无残留 `liveV3SignalDecision` / `resetLiveV3SignalState` 类型引用。

- [ ] **Step 6: Commit**

```powershell
git add quant-board/docs/superpowers/specs/2026-06-07-ranktrend-v3-live-signal-mapping-design.md src/services/dataLoader/RankTrendSignalService.ts src/services/dataLoader/__tests__/RankTrendSignalService.test.ts src/components/common/DataTable.vue
git rm src/services/rankTrend/liveV3SignalMapper.ts src/services/rankTrend/__tests__/liveV3SignalMapper.test.ts
git commit -m "refactor: replace live signal column with candidate pool workflow"
```

---

## Self-Review

- Spec coverage:
  - 已覆盖主表 `【信号】` → `【候选池】` 替换
  - 已覆盖 fusion 自动入池 `status=triggered`
  - 已覆盖候选池状态投影与点击入口
  - 已覆盖旧 `liveV3SignalMapper` 删除
  - 已覆盖旧 spec 标记为已废弃
- Placeholder scan:
  - 无 `TODO` / `TBD`
  - 每个阶段都带了文件、测试、命令和最小代码骨架
- Type consistency:
  - 统一使用 `statusOverride`、`signalsSnapshotPatch`、`candidatePoolStatus`、`candidatePoolLabel`
  - notifier 名称统一为 `FusionCandidateNotifier`

## Execution Handoff

Plan complete and saved to `quant-board/docs/superpowers/plans/2026-06-08-ranktrend-fusion-candidate-pool-replacement-implementation-plan.md`. Two execution options:

1. Subagent-Driven (recommended) - 我分 task 派新 subagent 执行，中间逐段 review，适合这次删旧链路 + 接新链路的重构
2. Inline Execution - 我在当前会话按计划连续执行，过程中做检查点

Which approach?
