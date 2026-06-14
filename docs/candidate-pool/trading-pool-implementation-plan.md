# Trading Pool V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first version of the trading pool as a front-end projection layer on top of the existing candidate pool, with buy-point resonance and auto-exit rules, without changing journal persistence or real trade logs.

**Architecture:** V1 keeps candidate pool persistence unchanged and computes trading-pool rows from existing candidate entries plus current RankTrend signals. The refresh path is `行情刷新/手动刷新 -> CandidateJournalService.reanalyzeCandidate() -> analyzeTradingPoolCandidate() -> CandidatePoolPanel 交易池视图`; V2 persistence is explicitly out of scope for this plan.

Implementation note: `CandidateJournalService.reanalyzeCandidate()` is currently synchronous and returns `CandidateWorkbenchReview`. If a future refactor makes it asynchronous, replace the computed projection with an explicit refresh `ref` pipeline rather than mapping unresolved promises inside `computed()`.

**Tech Stack:** Vue 3 + TypeScript + Vite, Vitest, existing `CandidateJournalService`, `CandidateAnalysisService`, `FusionExecutionOverlay`, RankTrend technical signals, `CandidatePoolPanel.vue`.

---

## Guardrails

- Do not modify refresh manager or introduce a new trading-pool timer in V1.
- Do not write trading-pool state into `favorite_data`.
- Do not touch historical trade-log filtering for `trade_type=entry/exit`.
- Do not break candidate-list filtering for `trade_type=thesis`.
- Do not add backend tables, QuantBoard API changes, or `trade_type=trading_pool` implementation in V1.
- Do not rename or merge the real historical trade log into the trading pool.
- Do not replace the existing candidate auto-entry matrix.
- Keep V1 previous trading-pool rows in session-level storage only; do not persist them as journal records.

## File Map

- Modify: `src/services/candidate/types.ts`
  - Add V1 trading-pool status and result types.
- Create: `src/services/candidate/TradingPoolAnalysisService.ts`
  - Extract real RankTrend signal paths and evaluate entry/exit rules.
- Create: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`
  - Cover entry resonance, auto-exit, conflict priority, stale data, and recovery.
- Modify: `src/components/panels/CandidatePoolPanel.vue`
  - Add trading-pool tab/view backed by front-end projection.
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`
  - Lock tab wording, data source boundary, and no historical-log conflation.
- Modify: `docs/candidate-pool/candidate-pool-trading-pool-design.md`
  - Keep design aligned if implementation reveals wording gaps.

## V2 Out Of Scope

Second-version persistence remains design-only in this plan. A separate V2 plan is required before touching:

- `quant-board/backend/**`
- `quant-board/docs/api-cli.md`
- `quant-board/docs/architecture.md`
- `quant-board/docs/database-migration-plan.md`
- any durable `trade_type=trading_pool` implementation

### Task 1: Lock V1 State Machine And Types

**Files:**
- Modify: `src/services/candidate/types.ts`
- Test: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: Add trading-pool status types**

```ts
export type TradingPoolStatus =
  | '观察买点'
  | '准备介入'
  | '已介入'
  | '持仓观察'
  | '观察中'
  | '已退出'
  | '已完成'

export type TradingPoolDecision = 'enter' | 'watch' | 'downgrade' | 'exit' | 'stale'

export interface TradingPoolSignalSnapshot {
  directionSignal: string | null
  jumpConfidence: number | null
  macdCross: string | null
  accelerationSignal: string | null
  zeroCrossSignal: string | null
  momentumSyncBroken: boolean
  lifecycleAction: string | null
  dataQuality: 'fresh' | 'stale' | 'missing'
}

export interface TradingPoolAnalysisRow {
  code: string
  name?: string
  status: TradingPoolStatus
  decision: TradingPoolDecision
  reasons: string[]
  signalSnapshot: TradingPoolSignalSnapshot
}

export interface TradingPoolAnalysisResult {
  rows: TradingPoolAnalysisRow[]
  staleCount: number
  exitedCount: number
}
```

- [ ] **Step 2: Write a status contract test**

```ts
import { describe, expect, it } from 'vitest'
import type { TradingPoolStatus } from '../types'

describe('TradingPool status contract', () => {
  it('keeps the V1 status vocabulary explicit', () => {
    const statuses: TradingPoolStatus[] = [
      '观察买点',
      '准备介入',
      '已介入',
      '持仓观察',
      '观察中',
      '已退出',
      '已完成',
    ]

    expect(statuses).toContain('观察买点')
    expect(statuses).toContain('观察中')
    expect(statuses).toContain('已退出')
  })
})
```

- [ ] **Step 3: Run the contract test**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts
```

Expected: PASS once the type file compiles.

### Task 2: Implement Signal Extraction From Real RankTrend Paths

**Files:**
- Create: `src/services/candidate/TradingPoolAnalysisService.ts`
- Test: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: Write tests using real signal paths**

```ts
import { describe, expect, it } from 'vitest'
import { analyzeTradingPoolCandidate } from '../TradingPoolAnalysisService'

describe('TradingPoolAnalysisService entry rules', () => {
  it('uses RankTrend nested signal paths, not flattened mock fields', () => {
    const candidates = [
      {
        code: '601208',
        name: '东材科技',
        rankTrend: {
          jump: { confidence: 0.88 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy' },
              acceleration: { signal: 'buy' },
              zeroCross: { signal: 'buy' },
            },
          },
        },
      },
      {
        code: '300433',
        name: '蓝思科技',
        rankTrend: {
          jump: { confidence: 0.95 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy' },
              acceleration: { signal: 'hold' },
              zeroCross: { signal: 'hold' },
            },
          },
        },
      },
    ]

    const result = analyzeTradingPoolCandidate({ candidates })

    expect(result.rows.map((row) => [row.code, row.status])).toEqual([
      ['601208', '观察买点'],
      ['300433', '观察中'],
    ])
  })
})
```

- [ ] **Step 2: Implement nested-path extraction with fallbacks**

```ts
function readTradingSignals(stock: any) {
  return {
    directionSignal: stock.rankTrend?.technical?.signals?.direction?.signal ?? stock.directionSignal ?? null,
    jumpConfidence: stock.rankTrend?.jump?.confidence ?? stock.jumpConfidence ?? null,
    macdCross: stock.rankTrend?.technical?.macd?.cross ?? stock.macdCross ?? null,
    accelerationSignal:
      stock.rankTrend?.technical?.signals?.acceleration?.signal ?? stock.accelerationSignal ?? null,
    zeroCrossSignal: stock.rankTrend?.technical?.signals?.zeroCross?.signal ?? stock.crossSignal ?? null,
    momentumSyncBroken: Boolean(stock.rankTrend?.technical?.momentumProfile?.syncBroken),
    lifecycleAction: stock.rankTrend?.cycle?.decision?.action ?? stock.lifecycleAction ?? null,
  }
}
```

- [ ] **Step 3: Run the focused test**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts
```

Expected: PASS for nested RankTrend signal paths.

### Task 3: Add Auto-Exit And Stale-Data Rule Tests

**Files:**
- Modify: `src/services/candidate/TradingPoolAnalysisService.ts`
- Modify: `src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts`

- [ ] **Step 1: Add auto-exit tests**

```ts
describe('TradingPoolAnalysisService exit rules', () => {
  it('exits immediately when lifecycle veto is present', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            cycle: { decision: { action: 'veto' } },
            jump: { confidence: 0.91 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
    expect(result.rows[0].decision).toBe('exit')
    expect(result.rows[0].reasons).toContain('lifecycle_veto')
  })

  it('exits when MACD death cross and direction weak happen together', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '002129',
          rankTrend: {
            jump: { confidence: 0.73 },
            technical: {
              macd: { cross: 'death' },
              signals: {
                direction: { signal: 'hold' },
                acceleration: { signal: 'hold' },
                zeroCross: { signal: 'sell' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('已退出')
    expect(result.rows[0].decision).toBe('exit')
    expect(result.rows[0].reasons).toContain('macd_death_cross')
  })

  it('downgrades instead of exits when jump confidence alone weakens', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { confidence: 0.62 },
            technical: {
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
  })

  it('downgrades when momentum sync is broken even if jump stays high', () => {
    const result = analyzeTradingPoolCandidate({
      candidates: [
        {
          code: '601208',
          rankTrend: {
            jump: { confidence: 0.91 },
            technical: {
              momentumProfile: { syncBroken: true },
              macd: { cross: 'golden' },
              signals: {
                direction: { signal: 'buy' },
                acceleration: { signal: 'buy' },
                zeroCross: { signal: 'buy' },
              },
            },
          },
        },
      ],
    })

    expect(result.rows[0].status).toBe('观察中')
    expect(result.rows[0].decision).toBe('downgrade')
    expect(result.rows[0].reasons).toContain('momentum_sync_broken')
  })
})
```

- [ ] **Step 2: Add priority conflict test**

```ts
it('lets MACD death cross override direction buy when exit signals are severe', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '000001',
        rankTrend: {
          jump: { confidence: 0.91 },
          technical: {
            macd: { cross: 'death' },
            signals: {
              direction: { signal: 'buy' },
              acceleration: { signal: 'sell' },
              zeroCross: { signal: 'sell' },
            },
          },
        },
      },
    ],
  })

  expect(result.rows[0].status).toBe('已退出')
  expect(result.rows[0].decision).toBe('exit')
})
```

- [ ] **Step 3: Add stale-data non-regression test**

```ts
it('marks stale data without forcing an exit', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '601208',
        rankTrend: null,
      },
    ],
    previousRows: [
      {
        code: '601208',
        status: '观察买点',
        decision: 'enter',
        reasons: ['previous_entry'],
        signalSnapshot: {
          directionSignal: 'buy',
          jumpConfidence: 0.88,
          macdCross: 'golden',
          accelerationSignal: 'buy',
          zeroCrossSignal: 'buy',
          dataQuality: 'fresh',
        },
      },
    ],
  })

  expect(result.rows[0].status).toBe('观察买点')
  expect(result.rows[0].decision).toBe('stale')
  expect(result.rows[0].signalSnapshot.dataQuality).toBe('stale')
})
```

- [ ] **Step 4: Add recovery test**

```ts
it('recovers from watch to buy-point observation when signals return', () => {
  const result = analyzeTradingPoolCandidate({
    candidates: [
      {
        code: '601208',
        rankTrend: {
          jump: { confidence: 0.9 },
          technical: {
            macd: { cross: 'golden' },
            signals: {
              direction: { signal: 'buy' },
              acceleration: { signal: 'buy' },
              zeroCross: { signal: 'buy' },
            },
          },
        },
      },
    ],
    previousRows: [{ code: '601208', status: '观察中' }],
  })

  expect(result.rows[0].status).toBe('观察买点')
  expect(result.rows[0].decision).toBe('enter')
})
```

- [ ] **Step 5: Implement minimal rule priority**

```ts
const HARD_EXIT_REASONS = ['macd_death_cross', 'direction_weak', 'zero_cross_sell']

function decideTradingPoolStatus(signals: TradingPoolSignalSnapshot, previous?: TradingPoolAnalysisRow) {
  if (signals.dataQuality !== 'fresh') {
    return {
      status: previous?.status ?? '观察中',
      decision: 'stale',
      reasons: ['signal_stale'],
    }
  }

  if (signals.lifecycleAction === 'veto') {
    return { status: '已退出', decision: 'exit', reasons: ['lifecycle_veto'] }
  }

  const reasons: string[] = []
  if (signals.macdCross === 'death') reasons.push('macd_death_cross')
  if (signals.directionSignal !== 'buy') reasons.push('direction_weak')
  if (signals.zeroCrossSignal === 'sell') reasons.push('zero_cross_sell')

  const hardExitCount = reasons.filter((reason) => HARD_EXIT_REASONS.includes(reason)).length
  if (signals.macdCross === 'death' && hardExitCount >= 2) {
    return { status: '已退出', decision: 'exit', reasons }
  }

  if ((signals.jumpConfidence ?? 0) < 0.8) {
    return { status: '观察中', decision: 'downgrade', reasons: ['jump_confidence_low'] }
  }

  if (signals.momentumSyncBroken) {
    return { status: '观察中', decision: 'downgrade', reasons: ['momentum_sync_broken'] }
  }

  if (
    signals.directionSignal === 'buy' &&
    signals.macdCross === 'golden' &&
    signals.accelerationSignal === 'buy' &&
    signals.zeroCrossSignal === 'buy'
  ) {
    return { status: '观察买点', decision: 'enter', reasons: ['signal_resonance'] }
  }

  return { status: '观察中', decision: 'watch', reasons: ['resonance_incomplete'] }
}
```

- [ ] **Step 6: Run the full trading-pool service tests**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts
```

Expected: PASS for entry, exit, conflict priority, stale data, and recovery cases.

### Task 4: Wire Trading Pool View To Existing Reanalysis Flow

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [ ] **Step 1: Add session-level previous-row cache**

```ts
const TRADING_POOL_PREVIOUS_ROWS_KEY = 'dragon-board:trading-pool:v1:previous-rows'

function loadPreviousTradingPoolRows(): TradingPoolAnalysisRow[] {
  try {
    const raw = sessionStorage.getItem(TRADING_POOL_PREVIOUS_ROWS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function savePreviousTradingPoolRows(rows: TradingPoolAnalysisRow[]): void {
  sessionStorage.setItem(TRADING_POOL_PREVIOUS_ROWS_KEY, JSON.stringify(rows))
}
```

This is session continuity only. It must not create journal entries or write to `favorite_data`.

- [ ] **Step 2: Document the V1 call chain in panel comments only if needed**

```ts
// V1 trading pool is a live projection:
// reanalyzeCandidate(entry) -> analyzeTradingPoolCandidate() -> rendered rows.
```

- [ ] **Step 3: Add behavior-level panel test**

```ts
it('renders trading pool from candidate projection without historical trade rows', async () => {
  const wrapper = mount(CandidatePoolPanel, {
    global: {
      provide: {
        candidateJournalService: {
          listCandidates: vi.fn().mockResolvedValue([
            { id: 'c1', stockCode: '601208', stockName: '东材科技', tradeType: 'thesis' },
          ]),
          reanalyzeCandidate: vi.fn().mockReturnValue({
            entry: { stockCode: '601208', stockName: '东材科技' },
            currentAnalysis: {
              signalsSnapshot: {
                rankTrend: {
                  jump: { confidence: 0.88 },
                  technical: {
                    macd: { cross: 'golden' },
                    signals: {
                      direction: { signal: 'buy' },
                      acceleration: { signal: 'buy' },
                      zeroCross: { signal: 'buy' },
                    },
                  },
                },
              },
            },
          }),
        },
      },
    },
  })

  await wrapper.find('[data-testid="candidate-pool-tab-trading"]').trigger('click')

  expect(wrapper.text()).toContain('交易池')
  expect(wrapper.text()).toContain('601208')
  expect(wrapper.text()).toContain('观察买点')
  expect(wrapper.text()).not.toContain('trade_type=trading_pool')
  expect(wrapper.text()).not.toContain('entry/exit')
})
```

- [ ] **Step 4: Add trading-pool tab and data source**

```vue
<button
  type="button"
  class="candidate-pool-tab"
  data-testid="candidate-pool-tab-trading"
  :class="{ active: activePoolTab === 'trading' }"
  @click="activePoolTab = 'trading'"
>
  交易池
</button>
```

```ts
const tradingPoolRows = computed(() =>
  analyzeTradingPoolCandidate({
    candidates: candidateEntries.value.map((entry) => candidateJournalService.reanalyzeCandidate(entry)),
    previousRows: previousTradingPoolRows.value,
  }).rows,
)
```

- [ ] **Step 5: Save previous rows after evaluation**

```ts
watch(
  tradingPoolRows,
  (rows) => {
    previousTradingPoolRows.value = rows
    savePreviousTradingPoolRows(rows)
  },
  { deep: true },
)
```

- [ ] **Step 6: Render V1 row fields**

```vue
<tr v-for="row in tradingPoolRows" :key="row.code">
  <td>{{ row.code }}</td>
  <td>{{ row.name || '-' }}</td>
  <td>{{ row.status }}</td>
  <td>{{ row.signalSnapshot.jumpConfidence ?? '-' }}</td>
  <td>{{ row.signalSnapshot.directionSignal ?? '-' }}</td>
  <td>{{ row.signalSnapshot.macdCross ?? '-' }}</td>
  <td>{{ row.reasons.join(' / ') }}</td>
</tr>
```

```vue
<span v-if="row.decision === 'stale'" class="status-badge status-badge--muted">信号过期</span>
<span v-else-if="row.status === '已退出'" class="status-badge status-badge--exit">已退出</span>
<span v-else-if="row.status === '观察中'" class="status-badge status-badge--muted">观察中</span>
<span v-else class="status-badge status-badge--entry">{{ row.status }}</span>
```

The table should visibly distinguish fresh buy-point rows, downgraded watch rows, exited rows, and stale-data rows.

- [ ] **Step 7: Keep manual intervention explicit**

```vue
<button type="button" class="candidate-pool-action" @click="markTradingPoolIntervened(row)">
  已介入
</button>
```

The button only changes V1 UI state. It must not create a real `entry` trade log.

- [ ] **Step 8: Run panel tests**

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: PASS and trading-pool behavior test confirms V1 projection does not use historical trade rows.

### Task 5: V1 Verification

**Files:**
- Modify: only files listed in the File Map.

- [ ] **Step 1: Run focused tests**

```powershell
pnpm exec vitest run src/services/candidate/__tests__/TradingPoolAnalysisService.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: PASS.

- [ ] **Step 2: Run TypeScript app check**

```powershell
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: exit code 0.

- [ ] **Step 3: Run production build**

```powershell
pnpm build
```

Expected: exit code 0.

- [ ] **Step 4: Browser verification for UI implementation**

```powershell
pnpm dev
```

Use Playwright or browser validation to confirm:

- Candidate pool tab still renders existing candidate list.
- Trading pool tab renders only front-end projected rows.
- Exited rows are visibly marked as exited.
- Stale rows are visibly muted or labeled stale.
- `601208`-style full resonance shows `观察买点`.
- `300433`-style incomplete resonance shows `观察中`.
- `002129`-style death-cross exit shows `已退出`.
- Manual `已介入` does not create a historical `entry` record.

### Task 6: V2 Planning Handoff

**Files:**
- Create later: `docs/candidate-pool/trading-pool-persistence-v2-plan.md`

- [ ] **Step 1: Do not implement V2 in this plan**

```md
V2 requires a separate plan before touching backend, API docs, database schema, or trade_type=trading_pool persistence.
```

- [ ] **Step 2: Preserve V2 requirements for the next plan**

```md
V2 must define:
- trade_type=trading_pool as a durable journal record
- candidateEntryId as a top-level field
- signalsSnapshot.tradingPool for trading-pool decisions and snapshots
- explicit separation from trade_type=entry/exit historical trades
- migration and cascade behavior
```
