# RankTrend Live Candidate Explainability Config Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert RankTrend V5 live auto-candidate logic from hardcoded opaque gates into a configurable, explainable, user-visible watchlist workflow without adding new DataTable columns.

**Design Spec:** [RankTrend Live Candidate Explainability Config Design](../specs/2026-06-10-ranktrend-live-candidate-explainability-config-design.md)

**Architecture:** Add a typed live strategy config contract, make `evaluateV5FusionEntry()` return structured gate checks, and project those checks into the existing Fusion candidate projection. DataTable keeps the existing “候选池” column and improves its badge state only; CandidatePoolPanel becomes the primary workbench for strategy mode, parameter snapshot, and gate matrix.

**Tech Stack:** Vue 3 `<script setup>`, TypeScript, Vite/Vitest, existing Dragon Board services under `src/services/rankTrend/**`, runtime config under `src/config/**`, shared projection types under `src/types/**`.

---

## Execution Notes

- Commit steps are optional checkpoints for subagent-driven execution. Only run `git commit` when the user explicitly authorizes committing or branch workflow execution.
- Source-contract tests in existing component test files are guardrails for structure and copy. They must be paired with Playwright/browser validation before claiming UI behavior is complete.

## Cross-Review Fixes Applied

- Product/UX review Critical: Task 8 now requires a unified `selectedLiveDetail` model so transient live projections render in the main CandidatePoolPanel detail area instead of being blocked by `selectedRow`.
- Product/UX review Important: CandidatePoolPanel rule matrix now includes “硬阻断”, parameter snapshot includes acceleration, `accDelta`, allowed tiers, and B-tier confirmation, and strategy mode labels use Chinese user-facing names.
- Product/UX review Important: pending strategy mode is visually separated from the current `entryDecision.configSnapshot`; changing the selector does not mutate the currently displayed diagnosis.
- Product/UX review Important: `triggerCandidate` is constrained to a real live recall structure instead of any positive short/mid momentum, reducing candidate-column noise.
- Engineering review Important: strict execution blocks degraded sample quality, and missing RankTrend is consistently `blocked_candidate`.
- Engineering review Important: `CandidatePoolOpenPayload` is shared across DataTable, App.vue, and CandidatePoolPanel, preventing payload field drift.
- Engineering review Important: `candidatePoolFirstReason` is deliberately not added; the visible reason remains `candidatePoolProjection.entryDecision.summary`.
- Engineering review Important: Task 8 adds Playwright coverage for the non-persisted live projection click path.

## Confirmed Product Constraints

- DataTable already has a “候选池” column. Do not add any new table column for gate reasons, block reason, strategy mode, or confidence.
- The existing DataTable candidate-pool badge may be enhanced in-place with a clearer label, color, compact marker, and click behavior.
- CandidatePoolPanel may be expanded with strategy mode, parameter snapshot, and structured gate matrix.
- Tooltip-only fixes are explicitly out of scope. Tooltips may remain as secondary support, but the main explanation must be visible in CandidatePoolPanel.
- Stocks that are not auto-added but have live `entryDecision` projection must still be explainable from the existing DataTable “候选池” cell.
- `change >= 6` must stop being a default hard block. It should become a configurable gate whose default mode is warning/ranking penalty, not blocking.
- Limit-up detection must use quote fields first and board fallback second.
- The implementation must preserve QuantBoard/Dragon Board boundary: live watch UI and TS live contract stay in root `src/**`; research/backtest remains in `quant-board/**`.

## File Structure

Create:

- `src/types/rankTrendLiveStrategy.ts`
  - Pure TypeScript types for live strategy mode, gate result status, gate severity, live config, and gate diagnostics.
- `src/types/candidatePoolOpenPayload.ts`
  - Pure event payload type shared by DataTable, App.vue, and CandidatePoolPanel for candidate-pool open requests.
- `src/config/rankTrendLiveStrategyConfig.ts`
  - Runtime defaults, normalization, mode presets, and localStorage keys for live strategy config.
- `src/services/rankTrend/liveLimitState.ts`
  - Quote-first limit-up/limit-down detection shared by V5 live gate and tests.
- `src/services/rankTrend/liveGateCheckBuilder.ts`
  - Small helpers for building structured gate checks and selecting first blocking check.
- `src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts`
- `src/services/rankTrend/__tests__/liveLimitState.test.ts`
- `src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts`

Modify:

- `src/services/rankTrend/v5FusionExecutionContract.ts`
  - Accept optional live config and return `checks`, `decisionState`, `firstBlockingCheck`, `configSnapshot`.
- `src/services/rankTrend/FusionStrategyProjector.ts`
  - Include entry diagnostics in `FusionStrategyProjection`.
- `src/services/rankTrend/FusionCandidateNotifier.ts`
  - Use structured decision state; auto-add only when `decisionState === 'auto_add'`.
- `src/services/candidate/CandidatePoolStatusProjector.ts`
  - Project current decision label and first visible reason into existing candidate pool fields.
- `src/types/fusionStrategyProjection.ts`
  - Extend projection type with `entryDecision`.
- `src/components/common/DataTable.vue`
  - Keep existing “候选池” column; change badge label/style based on projection decision.
- `src/App.vue`
  - Forward transient live projection payload from the global `candidate-pool:open` event to CandidatePoolPanel.
- `src/components/panels/CandidatePoolPanel.vue`
  - Add strategy mode selector, config snapshot, gate matrix, and transient live projection details to the existing panel.
- `e2e/vue.spec.ts`
  - Add Playwright coverage for non-persisted live projection details opened from the existing “候选池” column.
- RankTrend tests near changed modules.

Check but avoid changing unless necessary:

- `quant-board/backend/analysis/ranktrend_live_gate_shadow_audit.py`
- `quant-board/backend/core/backtest/execution.py`
- `quant-board/docs/api-cli.md`

---

## Task 1: Add Live Strategy Types And Defaults

**Files:**
- Create: `src/types/rankTrendLiveStrategy.ts`
- Create: `src/config/rankTrendLiveStrategyConfig.ts`
- Test: `src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts`

- [ ] **Step 1: Write failing config tests**

Create `src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import {
  DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
  RANK_TREND_LIVE_STRATEGY_PRESETS,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'

describe('rankTrendLiveStrategyConfig', () => {
  it('defaults to balanced mode without hard blocking change >= 6', () => {
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.mode).toBe('balanced')
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.changeGate.mode).toBe('warn')
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.changeGate.maxEntryChangePct).toBe(6)
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.requireCandidateTier).toBe(false)
    expect(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.allowDegradedSample).toBe(true)
  })

  it('keeps strict execution available as an explicit preset', () => {
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.changeGate.mode).toBe('block')
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.requireCandidateTier).toBe(true)
    expect(RANK_TREND_LIVE_STRATEGY_PRESETS.strict_execution.minJumpConfidence).toBe(90)
  })

  it('normalizes invalid patch values to safe defaults', () => {
    const normalized = normalizeRankTrendLiveStrategyConfig({
      mode: 'balanced',
      minJumpConfidence: 999,
      accelerationMin: -1,
      accDeltaMin: Number.NaN,
      allowDegradedSample: 'yes' as never,
      requireCandidateTier: 'no' as never,
      allowedCandidateTiers: ['A_MAIN', 'BAD_TIER'] as never,
      changeGate: { mode: 'block', maxEntryChangePct: 88 },
    })

    expect(normalized.minJumpConfidence).toBe(100)
    expect(normalized.accelerationMin).toBe(0)
    expect(normalized.accDeltaMin).toBe(DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG.accDeltaMin)
    expect(normalized.allowDegradedSample).toBe(true)
    expect(normalized.requireCandidateTier).toBe(false)
    expect(normalized.allowedCandidateTiers).toEqual(['A_MAIN'])
    expect(normalized.changeGate.maxEntryChangePct).toBe(30)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts
```

Expected: FAIL because `rankTrendLiveStrategyConfig` does not exist.

- [ ] **Step 3: Add pure types**

Create `src/types/rankTrendLiveStrategy.ts`:

```ts
import type { CandidateTier } from '@/services/rankTrend/types'

export type RankTrendLiveStrategyMode = 'recall_first' | 'balanced' | 'strict_execution'

export type RankTrendLiveGateMode = 'off' | 'warn' | 'block'

export type RankTrendLiveGateStatus = 'pass' | 'warn' | 'fail' | 'disabled'

export type RankTrendLiveDecisionState =
  | 'auto_add'
  | 'watch_candidate'
  | 'blocked_candidate'
  | 'not_candidate'

export interface RankTrendLiveChangeGateConfig {
  mode: RankTrendLiveGateMode
  maxEntryChangePct: number | null
}

export interface RankTrendLiveStrategyConfig {
  version: string
  mode: RankTrendLiveStrategyMode
  minJumpConfidence: number
  allowDegradedSample: boolean
  requireCandidateTier: boolean
  allowedCandidateTiers: CandidateTier[]
  requireTierBMidAndZeroCross: boolean
  tierBMidMin: number
  accelerationMin: number
  accDeltaMin: number
  changeGate: RankTrendLiveChangeGateConfig
  limitUpPolicy: 'quote_first'
}

export interface RankTrendLiveGateCheck {
  key: string
  label: string
  status: RankTrendLiveGateStatus
  hardBlock: boolean
  actual: string | number | boolean | null
  expected: string
  message: string
}

export interface RankTrendLiveEntryDecision {
  decisionState: RankTrendLiveDecisionState
  accepted: boolean
  label: string
  summary: string
  firstBlockingCheck?: RankTrendLiveGateCheck
  checks: RankTrendLiveGateCheck[]
  configSnapshot: RankTrendLiveStrategyConfig
}
```

- [ ] **Step 4: Add runtime defaults and normalization**

Create `src/config/rankTrendLiveStrategyConfig.ts`:

```ts
import type {
  RankTrendLiveStrategyConfig,
  RankTrendLiveStrategyMode,
} from '@/types/rankTrendLiveStrategy'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY =
  'dragon-board.rankTrend.liveStrategyConfig.v1'

export const RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION = 'live-v5.1.0'

export const RANK_TREND_LIVE_STRATEGY_PRESETS: Record<
  RankTrendLiveStrategyMode,
  RankTrendLiveStrategyConfig
> = {
  recall_first: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'recall_first',
    minJumpConfidence: 80,
    allowDegradedSample: true,
    requireCandidateTier: false,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'],
    requireTierBMidAndZeroCross: false,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'warn', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
  balanced: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'balanced',
    minJumpConfidence: 85,
    allowDegradedSample: true,
    requireCandidateTier: false,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'],
    requireTierBMidAndZeroCross: false,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'warn', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
  strict_execution: {
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode: 'strict_execution',
    minJumpConfidence: 90,
    allowDegradedSample: false,
    requireCandidateTier: true,
    allowedCandidateTiers: ['A_MAIN', 'B_IGNITION'],
    requireTierBMidAndZeroCross: true,
    tierBMidMin: 20,
    accelerationMin: 10,
    accDeltaMin: 8,
    changeGate: { mode: 'block', maxEntryChangePct: 6 },
    limitUpPolicy: 'quote_first',
  },
}

export const DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG =
  RANK_TREND_LIVE_STRATEGY_PRESETS.balanced

function normalizeNumber(value: unknown, fallback: number, min: number, max: number): number {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return fallback
  return Math.min(max, Math.max(min, numeric))
}

function normalizeMode(value: unknown): RankTrendLiveStrategyMode {
  return value === 'recall_first' || value === 'strict_execution' ? value : 'balanced'
}

function normalizeBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === 'boolean' ? value : fallback
}

function normalizeCandidateTiers(
  value: unknown,
  fallback: RankTrendLiveStrategyConfig['allowedCandidateTiers'],
): RankTrendLiveStrategyConfig['allowedCandidateTiers'] {
  if (!Array.isArray(value)) return [...fallback]
  const allowed = new Set(['A_MAIN', 'B_IGNITION', 'N_NEUTRAL'])
  const tiers = value.filter((tier): tier is RankTrendLiveStrategyConfig['allowedCandidateTiers'][number] =>
    typeof tier === 'string' && allowed.has(tier),
  )
  return tiers.length ? tiers : [...fallback]
}

export function normalizeRankTrendLiveStrategyConfig(
  patch: Partial<RankTrendLiveStrategyConfig> = {},
): RankTrendLiveStrategyConfig {
  const mode = normalizeMode(patch.mode)
  const base = RANK_TREND_LIVE_STRATEGY_PRESETS[mode]
  const changeGate = patch.changeGate || {}

  return {
    ...base,
    ...patch,
    version: RANK_TREND_LIVE_STRATEGY_CONFIG_VERSION,
    mode,
    minJumpConfidence: normalizeNumber(patch.minJumpConfidence, base.minJumpConfidence, 0, 100),
    tierBMidMin: normalizeNumber(patch.tierBMidMin, base.tierBMidMin, 0, 100),
    accelerationMin: normalizeNumber(patch.accelerationMin, base.accelerationMin, 0, 100),
    accDeltaMin: normalizeNumber(patch.accDeltaMin, base.accDeltaMin, 0, 100),
    allowDegradedSample: normalizeBoolean(patch.allowDegradedSample, base.allowDegradedSample),
    requireCandidateTier: normalizeBoolean(patch.requireCandidateTier, base.requireCandidateTier),
    requireTierBMidAndZeroCross: normalizeBoolean(
      patch.requireTierBMidAndZeroCross,
      base.requireTierBMidAndZeroCross,
    ),
    allowedCandidateTiers: normalizeCandidateTiers(
      patch.allowedCandidateTiers,
      base.allowedCandidateTiers,
    ),
    changeGate: {
      mode:
        changeGate.mode === 'off' || changeGate.mode === 'block' || changeGate.mode === 'warn'
          ? changeGate.mode
          : base.changeGate.mode,
      maxEntryChangePct:
        changeGate.maxEntryChangePct === null
          ? null
          : normalizeNumber(
              changeGate.maxEntryChangePct,
              base.changeGate.maxEntryChangePct ?? 6,
              0,
              30,
            ),
    },
    limitUpPolicy: 'quote_first',
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/types/rankTrendLiveStrategy.ts src/config/rankTrendLiveStrategyConfig.ts src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts
git commit -m "feat: add ranktrend live strategy config"
```

---

## Task 2: Add Quote-First Limit State Detection

**Files:**
- Create: `src/services/rankTrend/liveLimitState.ts`
- Test: `src/services/rankTrend/__tests__/liveLimitState.test.ts`

- [ ] **Step 1: Write failing limit-state tests**

Create `src/services/rankTrend/__tests__/liveLimitState.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { resolveLiveLimitState } from '../liveLimitState'

describe('resolveLiveLimitState', () => {
  it('uses real limitUpPrice before board fallback', () => {
    const state = resolveLiveLimitState({
      code: '000970',
      price: 14.52,
      change: 10,
      limitUpPrice: 14.52,
    })

    expect(state.atLimitUp).toBe(true)
    expect(state.source).toBe('quote_limit_price')
  })

  it('falls back to main-board threshold for normal 000 stock when quote limit price is missing', () => {
    const state = resolveLiveLimitState({ code: '000970', change: 9.81 })

    expect(state.atLimitUp).toBe(true)
    expect(state.limitPct).toBe(9.8)
    expect(state.source).toBe('board_fallback')
  })

  it('falls back to north exchange threshold for 8/4/9 prefixes', () => {
    expect(resolveLiveLimitState({ code: '830000', change: 29.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '430000', change: 29.9 }).atLimitUp).toBe(true)
    expect(resolveLiveLimitState({ code: '920000', change: 29.9 }).atLimitUp).toBe(true)
  })

  it('does not treat 6 percent move as limit up', () => {
    const state = resolveLiveLimitState({ code: '000970', change: 6.1 })

    expect(state.atLimitUp).toBe(false)
    expect(state.source).toBe('board_fallback')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/liveLimitState.test.ts
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement limit detection**

Create `src/services/rankTrend/liveLimitState.ts`:

```ts
function asNumber(value: unknown): number | null {
  const num = Number(value)
  return Number.isFinite(num) ? num : null
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    const num = asNumber(value)
    if (num !== null && num > 0) return num
  }
  return null
}

function fallbackLimitPct(code: unknown): number {
  const value = String(code || '').trim()
  if (value.startsWith('300') || value.startsWith('301') || value.startsWith('688') || value.startsWith('689')) {
    return 19.8
  }
  if (value.startsWith('8') || value.startsWith('4') || value.startsWith('9')) {
    return 29.8
  }
  return 9.8
}

export interface LiveLimitState {
  atLimitUp: boolean
  atLimitDown: boolean
  source: 'quote_limit_price' | 'board_fallback' | 'missing_quote'
  limitPct: number | null
  limitUpPrice: number | null
  limitDownPrice: number | null
}

export function resolveLiveLimitState(stock: Record<string, unknown> | null | undefined): LiveLimitState {
  const lastPrice = firstNumber(stock?.price, stock?.latestPrice, stock?.lastPrice, stock?.lastTradePrice)
  const limitUpPrice = firstNumber(stock?.limitUpPrice, stock?.ztPrice, stock?.upLimitPrice, stock?.['涨停价'])
  const limitDownPrice = firstNumber(stock?.limitDownPrice, stock?.dtPrice, stock?.downLimitPrice, stock?.['跌停价'])

  if (lastPrice && limitUpPrice) {
    return {
      atLimitUp: lastPrice >= limitUpPrice * 0.999,
      atLimitDown: !!limitDownPrice && lastPrice <= limitDownPrice * 1.001,
      source: 'quote_limit_price',
      limitPct: null,
      limitUpPrice,
      limitDownPrice,
    }
  }

  const change = asNumber(stock?.change ?? stock?.pctChange ?? stock?.changePct)
  if (change === null) {
    return {
      atLimitUp: false,
      atLimitDown: false,
      source: 'missing_quote',
      limitPct: null,
      limitUpPrice,
      limitDownPrice,
    }
  }

  const limitPct = fallbackLimitPct(stock?.code)
  return {
    atLimitUp: change >= limitPct,
    atLimitDown: change <= -limitPct,
    source: 'board_fallback',
    limitPct,
    limitUpPrice,
    limitDownPrice,
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/liveLimitState.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/services/rankTrend/liveLimitState.ts src/services/rankTrend/__tests__/liveLimitState.test.ts
git commit -m "feat: add quote-first live limit state"
```

---

## Task 3: Add Structured Gate Check Builder

**Files:**
- Create: `src/services/rankTrend/liveGateCheckBuilder.ts`
- Test: `src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts`

- [ ] **Step 1: Write failing gate builder tests**

Create `src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { buildGateCheck, resolveFirstBlockingCheck, resolveLiveDecisionState } from '../liveGateCheckBuilder'

describe('liveGateCheckBuilder', () => {
  it('returns the first hard blocking failed check', () => {
    const checks = [
      buildGateCheck({ key: 'change', label: '涨幅位置', passed: false, mode: 'warn', actual: 6.5, expected: '< 6' }),
      buildGateCheck({ key: 'limit_up', label: '涨停可买性', passed: false, mode: 'block', actual: true, expected: '非涨停' }),
    ]

    expect(resolveFirstBlockingCheck(checks)?.key).toBe('limit_up')
  })

  it('maps warn-only checks to watch candidate', () => {
    const checks = [
      buildGateCheck({ key: 'jump', label: 'Jump', passed: true, mode: 'block', actual: 'buy', expected: 'buy' }),
      buildGateCheck({ key: 'change', label: '涨幅位置', passed: false, mode: 'warn', actual: 6.5, expected: '< 6' }),
    ]

    expect(resolveLiveDecisionState(checks, true)).toBe('watch_candidate')
  })

  it('maps no trigger to not_candidate', () => {
    expect(resolveLiveDecisionState([], false)).toBe('not_candidate')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts
```

Expected: FAIL because module does not exist.

- [ ] **Step 3: Implement builder**

Create `src/services/rankTrend/liveGateCheckBuilder.ts`:

```ts
import type {
  RankTrendLiveDecisionState,
  RankTrendLiveGateCheck,
  RankTrendLiveGateMode,
} from '@/types/rankTrendLiveStrategy'

export function buildGateCheck(input: {
  key: string
  label: string
  passed: boolean
  mode: RankTrendLiveGateMode
  actual: RankTrendLiveGateCheck['actual']
  expected: string
  message?: string
}): RankTrendLiveGateCheck {
  if (input.mode === 'off') {
    return {
      key: input.key,
      label: input.label,
      status: 'disabled',
      hardBlock: false,
      actual: input.actual,
      expected: input.expected,
      message: input.message || `${input.label} 已关闭`,
    }
  }

  const hardBlock = input.mode === 'block'
  const status = input.passed ? 'pass' : hardBlock ? 'fail' : 'warn'
  return {
    key: input.key,
    label: input.label,
    status,
    hardBlock,
    actual: input.actual,
    expected: input.expected,
    message:
      input.message ||
      (input.passed ? `${input.label} 通过` : hardBlock ? `${input.label} 阻断` : `${input.label} 降级观察`),
  }
}

export function resolveFirstBlockingCheck(
  checks: RankTrendLiveGateCheck[],
): RankTrendLiveGateCheck | undefined {
  return checks.find((check) => check.status === 'fail' && check.hardBlock)
}

export function resolveLiveDecisionState(
  checks: RankTrendLiveGateCheck[],
  triggerCandidate: boolean,
): RankTrendLiveDecisionState {
  if (!triggerCandidate) return 'not_candidate'
  if (resolveFirstBlockingCheck(checks)) return 'blocked_candidate'
  if (checks.some((check) => check.status === 'warn')) return 'watch_candidate'
  return 'auto_add'
}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/services/rankTrend/liveGateCheckBuilder.ts src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts
git commit -m "feat: add live gate check builder"
```

---

## Task 4: Refactor V5 Fusion Contract To Use Config And Checks

**Files:**
- Modify: `src/services/rankTrend/v5FusionExecutionContract.ts`
- Modify: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`

- [ ] **Step 1: Add failing tests for 000970-style behavior**

Modify `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts` by adding:

```ts
  it('does not hard block change >= 6 in balanced mode when core live recall signal is present', () => {
    const result = evaluateV5FusionEntry(createLiveRecallStock({
      code: '000970',
      name: '中科三环',
      change: 6.5,
      jumpConfidence: 91,
      candidateTier: 'B_IGNITION',
      short: 18,
      mid: 24,
      long: 12,
      acceleration: 14,
      accDelta: 11,
      zeroCrossSignal: 'buy',
    }))

    expect(result.accepted).toBe(false)
    expect(result.decisionState).toBe('watch_candidate')
    expect(result.blockedReasons).not.toContain('涨幅过高，阻断早期入场')
    expect(result.checks.find((check) => check.key === 'change_position')).toMatchObject({
      status: 'warn',
      hardBlock: false,
    })
  })

  it('hard blocks change >= 6 only in strict execution mode', () => {
    const result = evaluateV5FusionEntry(
      createLiveRecallStock({
        code: '000970',
        name: '中科三环',
        change: 6.5,
        jumpConfidence: 91,
        candidateTier: 'B_IGNITION',
        short: 18,
        mid: 24,
        long: 12,
        acceleration: 14,
        accDelta: 11,
        zeroCrossSignal: 'buy',
      }),
      { mode: 'strict_execution' },
    )

    expect(result.accepted).toBe(false)
    expect(result.decisionState).toBe('blocked_candidate')
    expect(result.firstBlockingCheck?.key).toBe('change_position')
  })

  it('uses quote-first limit-up detection', () => {
    const result = evaluateV5FusionEntry(createLiveRecallStock({
      code: '000970',
      name: '中科三环',
      change: 10,
      price: 14.52,
      limitUpPrice: 14.52,
      jumpConfidence: 91,
      candidateTier: 'A_MAIN',
      short: 18,
      mid: 24,
      long: 12,
      acceleration: 14,
      accDelta: 11,
    }))

    expect(result.decisionState).toBe('blocked_candidate')
    expect(result.firstBlockingCheck?.key).toBe('limit_up')
    expect(result.checks.find((check) => check.key === 'limit_up')?.message).toContain('quote_limit_price')
  })

  it('blocks degraded sample quality in strict execution mode', () => {
    const result = evaluateV5FusionEntry(
      createLiveRecallStock({
        code: '000970',
        name: '中科三环',
        change: 3.2,
        sampleQualityStatus: 'degraded',
        jumpConfidence: 91,
        candidateTier: 'A_MAIN',
        short: 18,
        mid: 24,
        long: 12,
        acceleration: 14,
        accDelta: 11,
      }),
      { mode: 'strict_execution' },
    )

    expect(result.decisionState).toBe('blocked_candidate')
    expect(result.firstBlockingCheck?.key).toBe('sample_quality')
  })
```

If the existing test helper only creates sparse stocks, add a dedicated `createLiveRecallStock()` helper in this test file. It must populate RankTrend, Jump, momentum, candidate tier, acceleration, and zero-cross fields so the 000970 scenario proves the user pain point instead of only proving a synthetic `change` branch.

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected: FAIL because `decisionState`, `checks`, optional config, and quote-first limit state are not wired.

- [ ] **Step 3: Update V5 result contract**

Modify `src/services/rankTrend/v5FusionExecutionContract.ts` imports and interfaces:

```ts
import {
  DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'
import type {
  RankTrendLiveDecisionState,
  RankTrendLiveEntryDecision,
  RankTrendLiveGateCheck,
  RankTrendLiveStrategyConfig,
} from '@/types/rankTrendLiveStrategy'
import { buildGateCheck, resolveFirstBlockingCheck, resolveLiveDecisionState } from './liveGateCheckBuilder'
import { resolveLiveLimitState } from './liveLimitState'
```

Replace `V5FusionEntryResult` with an extension that preserves old fields:

```ts
export interface V5FusionEntryResult extends RankTrendLiveEntryDecision {
  accepted: boolean
  candidateTier: CandidateTier
  jumpConfidence: number
  lifecycleAction: string
  blockedReasons: string[]
}
```

Add input patch type:

```ts
export type V5FusionEntryConfigPatch = Partial<RankTrendLiveStrategyConfig>
```

- [ ] **Step 4: Replace hardcoded gate accumulation**

Change function signature:

```ts
export function evaluateV5FusionEntry(
  stock: any,
  configPatch: V5FusionEntryConfigPatch = {},
): V5FusionEntryResult {
  const config = normalizeRankTrendLiveStrategyConfig({
    ...DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
    ...configPatch,
  })
  const checks: RankTrendLiveGateCheck[] = []
```

For missing rankTrend, return:

```ts
    const missingCheck = buildGateCheck({
      key: 'ranktrend_present',
      label: 'RankTrend 数据',
      passed: false,
      mode: 'block',
      actual: false,
      expected: '存在 rankTrend',
      message: '缺失 rankTrend，无法进入 live 候选评估',
    })
    return {
      accepted: false,
      decisionState: 'blocked_candidate',
      label: '被阻断',
      summary: missingCheck.message,
      candidateTier: 'N_NEUTRAL',
      jumpConfidence: 0,
      lifecycleAction: '',
      blockedReasons: [missingCheck.message],
      checks: [missingCheck],
      firstBlockingCheck: missingCheck,
      configSnapshot: config,
    }
```

Build checks for:

```ts
checks.push(buildGateCheck({
  key: 'execution_strategy',
  label: '执行分层',
  passed: !!executionTier,
  mode: config.requireCandidateTier ? 'block' : 'warn',
  actual: executionTier || 'missing',
  expected: config.requireCandidateTier ? '存在 executionStrategy' : '缺失时降级观察',
}))

checks.push(buildGateCheck({
  key: 'sample_quality',
  label: '样本质量',
  passed:
    rankTrend.meta?.sampleQuality?.status === 'ok' ||
    (config.allowDegradedSample && rankTrend.meta?.sampleQuality?.status === 'degraded'),
  mode: 'block',
  actual: rankTrend.meta?.sampleQuality?.status || 'unknown',
  expected: config.allowDegradedSample ? 'ok/degraded' : 'ok',
}))

checks.push(buildGateCheck({
  key: 'lifecycle_action',
  label: '生命周期动作',
  passed: lifecycleAction !== 'veto',
  mode: 'block',
  actual: lifecycleAction || 'unknown',
  expected: '非 veto',
}))

checks.push(buildGateCheck({
  key: 'jump_direction',
  label: 'Jump 方向',
  passed: jumpDirection === 'buy',
  mode: 'block',
  actual: jumpDirection || 'unknown',
  expected: 'buy',
}))

checks.push(buildGateCheck({
  key: 'jump_confidence',
  label: 'Jump 置信度',
  passed: jumpConfidence >= config.minJumpConfidence,
  mode: 'block',
  actual: jumpConfidence,
  expected: `>= ${config.minJumpConfidence}`,
}))

checks.push(buildGateCheck({
  key: 'momentum_positive',
  label: '多周期动量',
  passed: short > 0 && mid > 0 && long > 0,
  mode: 'block',
  actual: `短${short} 中${mid} 长${long}`,
  expected: 'short/mid/long 全部 > 0',
}))

checks.push(buildGateCheck({
  key: 'acceleration',
  label: '加速度',
  passed: acceleration >= config.accelerationMin || accDelta >= config.accDeltaMin,
  mode: 'block',
  actual: `acc=${acceleration}, accDelta=${accDelta}`,
  expected: `acc>=${config.accelerationMin} 或 accDelta>=${config.accDeltaMin}`,
}))

checks.push(buildGateCheck({
  key: 'change_position',
  label: '涨幅位置',
  passed: config.changeGate.maxEntryChangePct === null || change < config.changeGate.maxEntryChangePct,
  mode: config.changeGate.mode,
  actual: change,
  expected:
    config.changeGate.maxEntryChangePct === null
      ? '不限制'
      : `< ${config.changeGate.maxEntryChangePct}`,
}))

const limitState = resolveLiveLimitState(stock)
checks.push(buildGateCheck({
  key: 'limit_up',
  label: '涨停可买性',
  passed: !limitState.atLimitUp,
  mode: 'block',
  actual: limitState.atLimitUp,
  expected: '非涨停',
  message: limitState.atLimitUp
    ? `涨停状态，阻断入场 (${limitState.source})`
    : `未处于涨停 (${limitState.source})`,
}))
```

Candidate tier checks:

```ts
checks.push(buildGateCheck({
  key: 'candidate_tier',
  label: '候选层级',
  passed: config.allowedCandidateTiers.includes(candidateTier),
  mode: config.requireCandidateTier ? 'block' : 'warn',
  actual: candidateTier,
  expected: config.allowedCandidateTiers.join('/'),
}))

if (candidateTier === 'B_IGNITION') {
  const zeroCross = String(rankTrend.technical?.signals?.zeroCross?.signal ?? 'none')
  checks.push(buildGateCheck({
    key: 'tier_b_confirmation',
    label: 'B档确认',
    passed: mid >= config.tierBMidMin && zeroCross === 'buy',
    mode: config.requireTierBMidAndZeroCross ? 'block' : 'warn',
    actual: `mid=${mid}, zeroCross=${zeroCross}`,
    expected: `mid>=${config.tierBMidMin} 且 zeroCross=buy`,
  }))
}
```

Finish return:

```ts
  const triggerCandidate =
    jumpDirection === 'buy' &&
    jumpConfidence >= Math.min(80, config.minJumpConfidence) &&
    (candidateTier === 'A_MAIN' ||
      candidateTier === 'B_IGNITION' ||
      (config.mode === 'recall_first' && candidateTier === 'N_NEUTRAL')) &&
    (short > 0 || mid > 0)
  const decisionState = resolveLiveDecisionState(checks, triggerCandidate)
  const firstBlockingCheck = resolveFirstBlockingCheck(checks)
  const blockedReasons = checks
    .filter((check) => check.status === 'fail')
    .map((check) => check.message)
  const labelByState: Record<RankTrendLiveDecisionState, string> = {
    auto_add: '自动入池',
    watch_candidate: '观察候选',
    blocked_candidate: '被阻断',
    not_candidate: '未触发',
  }

  return {
    accepted: decisionState === 'auto_add',
    decisionState,
    label: labelByState[decisionState],
    summary: firstBlockingCheck?.message || checks.find((check) => check.status === 'warn')?.message || 'V5 live gate 通过',
    candidateTier,
    jumpConfidence,
    lifecycleAction,
    blockedReasons,
    checks,
    firstBlockingCheck,
    configSnapshot: config,
  }
```

Do not widen `triggerCandidate` to any positive momentum. The DataTable “候选池” column should only become noisy when a core live recall structure exists; weak unrelated rows should remain `not_candidate`.

- [ ] **Step 5: Remove old `isLimitUpBlocked` hardcoded logic**

Delete the old function:

```ts
function isLimitUpBlocked(stock: any): boolean {
  const change = asNumber(stock?.change)
  const code = String(stock?.code ?? '')
  const threshold = code.startsWith('300') || code.startsWith('301') || code.startsWith('688') ? 19.8 : 9.8
  return change >= threshold
}
```

Ensure no reference remains:

```powershell
rg -n "isLimitUpBlocked|涨幅过高，阻断早期入场|change >= 6" src/services/rankTrend/v5FusionExecutionContract.ts
```

Expected: no matches.

- [ ] **Step 6: Run V5 tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/services/rankTrend/v5FusionExecutionContract.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
git commit -m "feat: structure ranktrend live entry gates"
```

---

## Task 5: Project Entry Diagnostics Into Fusion Projection

**Files:**
- Modify: `src/types/fusionStrategyProjection.ts`
- Modify: `src/services/rankTrend/FusionStrategyProjector.ts`
- Modify: `src/services/candidate/CandidatePoolStatusProjector.ts`
- Test: `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`
- Test: `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`

- [ ] **Step 1: Add failing projection tests**

In `src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts`, add:

```ts
  it('projects live entry decision diagnostics for candidate pool UI', () => {
    const projection = buildFusionStrategyProjection({
      stock: createStock({
        code: '000970',
        change: 6.5,
      }),
      snapshotType: 'half_hour',
      tradingDate: '2026-06-10',
      snapshotId: 'half_hour:2026-06-10:14:30',
      frameTime: '2026-06-10T14:30:00+08:00',
    })

    expect(projection.entryDecision).toMatchObject({
      decisionState: 'watch_candidate',
      label: '观察候选',
    })
    expect(projection.entryDecision?.checks.some((check) => check.key === 'change_position')).toBe(true)
  })
```

In `src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts`, add:

```ts
  it('keeps candidate pool label sourced from entry decision without adding columns or reason copies', () => {
    const stocks = [{ code: '000970' }]
    const projections = [{
      stockCode: '000970',
      stockName: '中科三环',
      strategyName: 'ranktrend_early_big_move_v3_lifecycle_fusion',
      snapshotType: 'half_hour',
      tradingDate: '2026-06-10',
      snapshotId: 'half_hour:2026-06-10:14:30',
      frameTime: '2026-06-10T14:30:00+08:00',
      projectionSource: 'live',
      strategyState: 'idle',
      candidateTier: 'A_MAIN',
      lifecycleAction: 'allow',
      entryDecision: {
        decisionState: 'watch_candidate',
        label: '观察候选',
        summary: '涨幅位置降级观察',
        checks: [],
      },
    } as const]

    projectCandidatePoolStatus(stocks, projections)

    expect(stocks[0].candidatePoolLabel).toBe('观察候选')
    expect(stocks[0].candidatePoolProjection?.entryDecision?.summary).toBe('涨幅位置降级观察')
    expect('candidatePoolFirstReason' in stocks[0]).toBe(false)
  })
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts
```

Expected: FAIL because projection does not expose `entryDecision`.

- [ ] **Step 3: Extend projection type**

Modify `src/types/fusionStrategyProjection.ts`:

```ts
import type { RankTrendLiveEntryDecision } from '@/types/rankTrendLiveStrategy'
```

Add to `FusionStrategyProjection`:

```ts
  entryDecision?: Pick<
    RankTrendLiveEntryDecision,
    'decisionState' | 'label' | 'summary' | 'checks' | 'firstBlockingCheck' | 'configSnapshot'
  >
```

- [ ] **Step 4: Add entry decision to projector**

Modify `src/services/rankTrend/FusionStrategyProjector.ts` return object:

```ts
    entryDecision: {
      decisionState: entry.decisionState,
      label: entry.label,
      summary: entry.summary,
      checks: entry.checks,
      firstBlockingCheck: entry.firstBlockingCheck,
      configSnapshot: entry.configSnapshot,
    },
```

Place it near `strategyState` and `candidateTier` so UI consumers can find it.

- [ ] **Step 5: Project label only and keep reason in entryDecision**

Modify label assignment:

```ts
    stock.candidatePoolLabel =
      projection?.entryDecision?.label || STRATEGY_STATE_LABELS[strategyState]
```

Do not add `candidatePoolFirstReason` to `src/types/core.ts` or projector-local stock types. The visible reason must remain `stock.candidatePoolProjection.entryDecision.summary` so `entryDecision` stays the single source of truth.

- [ ] **Step 6: Run projection tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/types/fusionStrategyProjection.ts src/services/rankTrend/FusionStrategyProjector.ts src/services/candidate/CandidatePoolStatusProjector.ts src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts
git commit -m "feat: project live entry diagnostics"
```

---

## Task 6: Wire Auto-Add To Decision State

**Files:**
- Modify: `src/services/rankTrend/FusionCandidateNotifier.ts`
- Test: `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`

- [ ] **Step 1: Add failing notifier tests**

Add to `src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts`:

```ts
  it('does not auto-add watch candidates but preserves diagnostics in evaluation', async () => {
    const candidateJournal = createCandidateJournalMock()
    const notifier = new FusionCandidateNotifier({ candidateJournal, now: () => new Date('2026-06-10T14:30:00+08:00') })

    await notifier.process([
      createStock({
        code: '000970',
        change: 6.5,
      }),
    ])

    expect(candidateJournal.addCandidateFromStock).not.toHaveBeenCalled()
  })
```

Keep the existing auto-add test for an all-pass candidate.

- [ ] **Step 2: Run notifier test to verify failure or current mismatch**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
```

Expected: FAIL if watch candidate is still accepted; PASS if Task 4 already made `accepted` false for watch candidates. If PASS, still perform Step 3 to make the intent explicit.

- [ ] **Step 3: Make auto-add condition explicit**

Modify `src/services/rankTrend/FusionCandidateNotifier.ts`:

```ts
      const entry = evaluateV5FusionEntry(stock)
      if (entry.decisionState !== 'auto_add') continue
```

Do not use `entry.accepted` as the only semantic check in this file.

- [ ] **Step 4: Keep snapshot patch structured**

In `signalsSnapshotPatch.triggerMeta`, add:

```ts
            liveDecisionState: entry.decisionState,
            liveDecisionSummary: entry.summary,
            liveGateChecks: entry.checks,
            liveConfigVersion: entry.configSnapshot.version,
            liveStrategyMode: entry.configSnapshot.mode,
```

Keep existing fields for backward compatibility.

- [ ] **Step 5: Run notifier tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src/services/rankTrend/FusionCandidateNotifier.ts src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts
git commit -m "feat: gate fusion auto add by live decision"
```

---

## Task 7: Enhance Existing DataTable “候选池” Column Only

**Files:**
- Modify: `src/components/common/DataTable.vue`
- Test: `src/components/common/__tests__/DataTable.test.ts`

- [ ] **Step 1: Add failing DataTable source-level test**

Modify `src/components/common/__tests__/DataTable.test.ts` by adding a source contract test:

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'

const source = readFileSync(
  fileURLToPath(new URL('../DataTable.vue', import.meta.url)),
  'utf8',
)

describe('DataTable candidate pool column contract', () => {
  test('keeps candidate pool information in the existing jumpSignal column', () => {
    expect(source).toContain("{ key: 'jumpSignal', label: '候选池'")
    expect(source).not.toContain("label: '阻断'")
    expect(source).not.toContain("label: '入池原因'")
    expect(source).not.toContain("label: '策略模式'")
  })

  test('uses projected live decision label and summary in candidate pool badge', () => {
    expect(source).toContain('entryDecision?.decisionState')
    expect(source).toContain('entryDecision?.summary')
    expect(source).not.toContain('candidatePoolFirstReason')
  })
})
```

If `DataTable.test.ts` already imports `describe/expect/test`, merge imports instead of duplicating them.

- [ ] **Step 2: Run test to verify failure**

Run:

```powershell
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

Expected: FAIL because DataTable does not use `entryDecision?.decisionState` or `entryDecision?.summary`.

- [ ] **Step 3: Change state label helpers in DataTable**

Modify `src/components/common/DataTable.vue` helper functions:

```ts
const getCandidatePoolEntryDecision = (stock: any) =>
  getCandidatePoolProjection(stock)?.entryDecision || null

const getCandidatePoolStrategyState = (stock: any) =>
  getCandidatePoolEntryDecision(stock)?.decisionState ||
  getCandidatePoolProjection(stock)?.strategyState ||
  stock?.candidatePoolStatus ||
  'idle'

const formatCandidatePoolStateLabel = (stock: any) =>
  getCandidatePoolEntryDecision(stock)?.label ||
  getCandidatePoolProjection(stock)?.entryDecision?.label ||
  stock?.candidatePoolLabel ||
  '未触发'
```

Keep the column key as `jumpSignal`.

- [ ] **Step 4: Add compact reason line inside the existing cell**

Modify the `jumpSignal` template only:

```vue
<template v-else-if="col.key === 'jumpSignal'">
  <button
    type="button"
    class="jump-signal-cell candidate-pool-cell"
    @click.stop="openCandidatePoolFromCell(stock)"
  >
    <span
      class="jump-badge candidate-pool-badge"
      :class="`candidate-pool-state-${getCandidatePoolStrategyState(stock)}`"
      :title="getCandidatePoolTitle(stock)"
    >{{ formatCandidatePoolStateLabel(stock) }}</span>
    <span v-if="getCandidatePoolReason(stock)" class="candidate-pool-reason">
      {{ getCandidatePoolReason(stock) }}
    </span>
  </button>
</template>
```

Add helper:

```ts
const getCandidatePoolReason = (stock: any) =>
  getCandidatePoolEntryDecision(stock)?.summary || ''
```

This keeps a single column while making the main reason visible when there is room.

- [ ] **Step 5: Add CSS for existing column only**

Add near candidate pool badge CSS:

```css
.candidate-pool-cell {
  width: 100%;
  min-width: 0;
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 0;
  color: inherit;
  background: transparent;
  border: 0;
  cursor: pointer;
}

.candidate-pool-reason {
  max-width: 86px;
  overflow: hidden;
  color: #9aa6b8;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.1;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.candidate-pool-state-auto_add {
  color: #d9ffe8;
  background: rgba(41, 209, 125, 0.16);
  border: 1px solid rgba(41, 209, 125, 0.34);
}

.candidate-pool-state-watch_candidate {
  color: #ffe8ae;
  background: rgba(255, 177, 59, 0.15);
  border: 1px solid rgba(255, 177, 59, 0.34);
}

.candidate-pool-state-blocked_candidate {
  color: #ffb7c1;
  background: rgba(255, 92, 115, 0.15);
  border: 1px solid rgba(255, 92, 115, 0.32);
}

.candidate-pool-state-not_candidate {
  color: #8f99a8;
  background: rgba(143, 153, 168, 0.1);
  border: 1px solid rgba(143, 153, 168, 0.18);
}
```

Keep old strategy-state classes until all projections are updated.

- [ ] **Step 6: Run DataTable test**

Run:

```powershell
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add src/components/common/DataTable.vue src/components/common/__tests__/DataTable.test.ts
git commit -m "feat: enrich candidate pool column diagnostics"
```

---

## Task 8: Support Transient Live Projection Details

**Files:**
- Create: `src/types/candidatePoolOpenPayload.ts`
- Modify: `src/components/common/DataTable.vue`
- Modify: `src/App.vue`
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `e2e/vue.spec.ts`
- Test: `src/components/common/__tests__/DataTable.test.ts`
- Test: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [ ] **Step 1: Add shared open payload type**

Create `src/types/candidatePoolOpenPayload.ts`:

```ts
import type { FusionStrategyProjection } from '@/types/fusionStrategyProjection'

export interface CandidatePoolOpenPayload {
  candidateId?: string
  candidatePoolEntryId?: string | null
  stockCode?: string
  name?: string
  candidatePoolProjection?: FusionStrategyProjection | null
  stockSnapshot?: Record<string, unknown>
}
```

- [ ] **Step 2: Add failing DataTable event contract test**

Extend the DataTable source contract test from Task 7:

```ts
  test('passes live projection details when opening candidate panel from existing column', () => {
    expect(source).toContain('candidatePoolProjection')
    expect(source).toContain('entryDecision')
    expect(source).toContain('candidate-pool:open')
  })
```

Expected failure before implementation: `openCandidatePoolFromCell` only passes an entry id or stock code and does not preserve the live projection payload for stocks without a journal entry.

- [ ] **Step 3: Extend DataTable open payload**

Modify `openCandidatePoolFromCell(stock)` in `src/components/common/DataTable.vue` so the emitted payload always includes the stock snapshot and the current projection:

```ts
const openCandidatePoolFromCell = (stock: any) => {
  EventManager.emit('candidate-pool:open', {
    stockCode: stock?.code,
    name: stock?.name,
    candidateId:
      stock.candidatePoolEntryId ||
      getCandidatePoolProjection(stock)?.executionOverlay?.entryId ||
      undefined,
    candidatePoolEntryId:
      stock.candidatePoolEntryId ||
      getCandidatePoolProjection(stock)?.executionOverlay?.entryId ||
      null,
    candidatePoolProjection: getCandidatePoolProjection(stock),
    stockSnapshot: {
      code: stock?.code,
      name: stock?.name,
      price: stock?.price,
      change: stock?.change,
      volume: stock?.volume,
      amount: stock?.amount,
    },
  })
}
```

Keep the existing `candidate-pool:open` event name and existing `stockCode` / `candidateId` fields. Add the new fields without removing backward-compatible fields.

- [ ] **Step 4: Add failing CandidatePoolPanel transient-detail contract test**

Extend `src/components/panels/__tests__/CandidatePoolPanel.test.ts`:

```ts
  test('supports transient live projection detail without journal-only actions', () => {
    expect(source).toContain('transientLiveProjection')
    expect(source).toContain('isTransientLiveDetail')
    expect(source).toContain('candidatePoolProjection')
  })
```

Expected failure before implementation: CandidatePoolPanel only derives selected detail from persisted candidate rows.

- [ ] **Step 5: Add transient selection state**

Modify `CandidatePoolPanel.vue` script:

```ts
const transientLiveProjection = ref<{
  code: string
  name?: string
  candidatePoolProjection: any
  stockSnapshot?: Record<string, unknown>
} | null>(null)
```

Do not derive `isTransientLiveDetail` here. The unified detail model in Step 6 is the only source for persisted-vs-transient state.

- [ ] **Step 6: Wire DataTable event into transient detail**

Modify `src/App.vue` so `openCandidatePool()` accepts and forwards the transient projection payload to `CandidatePoolPanel.openCandidate()`:

```ts
import type { CandidatePoolOpenPayload } from '@/types/candidatePoolOpenPayload'

const candidatePoolPanelRef = ref<{
  openCandidate: (data?: CandidatePoolOpenPayload) => Promise<void>
} | null>(null)

const openCandidatePool = async (data: CandidatePoolOpenPayload = {}) => {
  panels.value.candidatePool = true
  await nextTick()
  await candidatePoolPanelRef.value?.openCandidate(data)
}
```

Then update `CandidatePoolPanel.openCandidate()` to accept the same payload. When the payload has `candidateId` or `candidatePoolEntryId`, keep the current persisted-entry behavior. When it has no persisted entry id but has `candidatePoolProjection.entryDecision`, set `transientLiveProjection` and open CandidatePoolPanel on that detail.

Implementation note:

```ts
import type { CandidatePoolOpenPayload } from '@/types/candidatePoolOpenPayload'

function openCandidatePoolDetail(payload: CandidatePoolOpenPayload) {
  const persistedEntryId = payload.candidateId || payload.candidatePoolEntryId || ''
  if (persistedEntryId) {
    transientLiveProjection.value = null
    selectPersistedCandidate(persistedEntryId)
    return
  }
  if (payload.candidatePoolProjection?.entryDecision) {
    transientLiveProjection.value = {
      code: payload.stockCode,
      name: payload.name,
      candidatePoolProjection: payload.candidatePoolProjection,
      stockSnapshot: payload.stockSnapshot,
    }
  }
}
```

Use existing method names where possible; do not introduce a second event channel for the same click.

- [ ] **Step 7: Replace detail template dependency on selectedRow**

This is the critical UX path. Refactor the detail area so both persisted candidates and transient live projections render through one detail model. Do not keep the main detail template under `v-if="selectedRow"` only.

Add a small view model:

```ts
const selectedLiveDetail = computed(() => {
  if (selectedRow.value) {
    return {
      kind: 'journal' as const,
      code: selectedRow.value.entry.stockCode,
      name: selectedRow.value.entry.stockName,
      entry: selectedRow.value.entry,
      projection: selectedRow.value.projection,
      stockSnapshot: null,
    }
  }
  if (!transientLiveProjection.value) return null
  return {
    kind: 'live_projection' as const,
    code: transientLiveProjection.value.code,
    name: transientLiveProjection.value.name || transientLiveProjection.value.code,
    entry: null,
    projection: transientLiveProjection.value.candidatePoolProjection,
    stockSnapshot: transientLiveProjection.value.stockSnapshot || null,
  }
})

const isTransientLiveDetail = computed(() => selectedLiveDetail.value?.kind === 'live_projection')
const selectedEntryDecision = computed(
  () => selectedLiveDetail.value?.projection?.entryDecision || null,
)
```

Change the detail template gate:

```vue
<template v-if="selectedLiveDetail">
  <div class="detail-head">
    <div>
      <h3>{{ selectedLiveDetail.name || selectedLiveDetail.code }}</h3>
      <span>
        {{ selectedLiveDetail.code }} ·
        {{ selectedEntryDecision?.label || strategyStateLabel(selectedLiveDetail.projection.strategyState) }}
      </span>
    </div>
  </div>
</template>
```

Then replace strategy facts that currently read `selectedRow.projection` with `selectedLiveDetail.projection`. Keep thesis/review form fields guarded by `selectedLiveDetail.entry`, because transient live projection has no `trade_journal` row.

- [ ] **Step 8: Hide journal-only actions for transient detail**

In `CandidatePoolPanel.vue`, guard actions that require a persisted `trade_journal` entry:

```vue
<button v-if="!isTransientLiveDetail" type="button" @click="removeSelectedCandidate">
  删除候选
</button>

<button v-if="!isTransientLiveDetail" type="button" @click="saveExecutionOverlay">
  保存执行记录
</button>
```

For transient detail, the panel should still show strategy facts, config snapshot, and rule matrix. It should not show disabled journal-only buttons as if the user can operate on an entry that does not exist.

- [ ] **Step 9: Add Playwright coverage for transient projection details**

Modify `e2e/vue.spec.ts` with a focused test in the existing candidate-pool describe block. Use the existing mock route helpers and add a fixture stock such as `000970` whose merged row has `candidatePoolProjection.entryDecision` but no persisted `candidateId`.

The test should assert the actual click path, not source text:

```ts
test('opens non-persisted live projection details from the existing candidate pool column', async ({ page }, testInfo) => {
  await setupCandidateRoutes(page)
  await page.goto('/')

  const row = page.locator('tr', { hasText: '中科三环' }).first()
  await expect(row).toBeVisible()
  await row.locator('.candidate-pool-cell').click()

  await expect(page.getByRole('heading', { name: '候选池' })).toBeVisible()
  await expect(page.locator('.candidate-detail')).toContainText('中科三环')
  await expect(page.locator('.candidate-detail')).toContainText('规则矩阵')
  await expect(page.locator('.candidate-detail')).toContainText('涨幅位置')
  await expect(page.locator('.candidate-detail')).not.toContainText('删除候选')
  await expect(page.locator('.candidate-detail')).not.toContainText('保存执行记录')

  await page.screenshot({ path: testInfo.outputPath('candidate-pool-transient-live-projection.png'), fullPage: true })
})
```

If the current e2e data setup cannot inject `candidatePoolProjection` directly, add the smallest test-only fixture hook already used in `e2e/vue.spec.ts`; do not add production-only debug globals.

- [ ] **Step 10: Run focused UI contract tests**

Run:

```powershell
pnpm exec vitest run src/components/common/__tests__/DataTable.test.ts src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: PASS.

- [ ] **Step 11: Run focused Playwright test**

Run:

```powershell
pnpm exec playwright test e2e/vue.spec.ts --project=chromium --grep "non-persisted live projection"
```

Expected: PASS. Screenshot artifact shows CandidatePoolPanel detail with rule matrix and without journal-only actions.

- [ ] **Step 12: Commit**

```powershell
git add src/types/candidatePoolOpenPayload.ts src/components/common/DataTable.vue src/components/common/__tests__/DataTable.test.ts src/App.vue src/components/panels/CandidatePoolPanel.vue src/components/panels/__tests__/CandidatePoolPanel.test.ts e2e/vue.spec.ts
git commit -m "feat: explain transient live candidate projections"
```

---

## Task 9: Expand CandidatePoolPanel Workbench

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Test: `src/components/panels/__tests__/CandidatePoolPanel.test.ts`

- [ ] **Step 1: Add failing panel source contract tests**

Modify `src/components/panels/__tests__/CandidatePoolPanel.test.ts`:

```ts
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, test } from 'vitest'

const source = readFileSync(
  fileURLToPath(new URL('../CandidatePoolPanel.vue', import.meta.url)),
  'utf8',
)

describe('CandidatePoolPanel live strategy workbench', () => {
  test('shows strategy mode, parameter snapshot, and gate matrix', () => {
    expect(source).toContain('策略模式')
    expect(source).toContain('参数快照')
    expect(source).toContain('规则矩阵')
    expect(source).toContain('selectedEntryDecision')
  })
})
```

Merge imports with existing test file if needed.

- [ ] **Step 2: Run panel test to verify failure**

Run:

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: FAIL because the panel lacks these sections.

- [ ] **Step 3: Add computed decision helpers**

Modify `src/components/panels/CandidatePoolPanel.vue` script:

```ts
const selectedEntryDecision = computed(
  () => selectedLiveDetail.value?.projection?.entryDecision || null,
)
const selectedGateChecks = computed(() => selectedEntryDecision.value?.checks || [])
const selectedConfigSnapshot = computed(() => selectedEntryDecision.value?.configSnapshot || null)

function gateStatusLabel(status: string): string {
  if (status === 'pass') return '通过'
  if (status === 'warn') return '观察'
  if (status === 'fail') return '阻断'
  return '关闭'
}

function strategyModeLabel(mode: string): string {
  if (mode === 'recall_first') return '召回优先'
  if (mode === 'strict_execution') return '严格执行'
  return '均衡盯盘'
}

function formatGateActual(value: unknown): string {
  if (value === null || value === undefined || value === '') return '-'
  return String(value)
}

function formatTierList(value: unknown): string {
  return Array.isArray(value) && value.length ? value.join('/') : '-'
}
```

This task must reuse the `selectedLiveDetail` model created in Task 8. Do not reintroduce `selectedRow.value?.projection.entryDecision`, because that breaks transient live projection details for non-persisted candidates.

- [ ] **Step 4: Add strategy mode and parameter snapshot to strategy card**

Inside the existing `<section class="strategy-card">`, after the `.fact-grid`, add:

```vue
<div v-if="selectedConfigSnapshot" class="config-strip">
  <div>
    <span>策略模式</span>
    <strong>{{ strategyModeLabel(selectedConfigSnapshot.mode) }}</strong>
  </div>
  <div>
    <span>参数快照</span>
    <strong>{{ selectedConfigSnapshot.version }}</strong>
  </div>
  <div>
    <span>Jump阈值</span>
    <strong>{{ selectedConfigSnapshot.minJumpConfidence }}</strong>
  </div>
  <div>
    <span>涨幅规则</span>
    <strong>{{ selectedConfigSnapshot.changeGate.mode }} / {{ selectedConfigSnapshot.changeGate.maxEntryChangePct ?? '不限' }}</strong>
  </div>
  <div>
    <span>加速度阈值</span>
    <strong>{{ selectedConfigSnapshot.accelerationMin }} / {{ selectedConfigSnapshot.accDeltaMin }}</strong>
  </div>
  <div>
    <span>允许层级</span>
    <strong>{{ formatTierList(selectedConfigSnapshot.allowedCandidateTiers) }}</strong>
  </div>
  <div>
    <span>B档确认</span>
    <strong>{{ selectedConfigSnapshot.requireTierBMidAndZeroCross ? '硬确认' : '观察降级' }}</strong>
  </div>
</div>
```

- [ ] **Step 5: Add visible gate matrix**

Still inside the strategy card, after `config-strip`, add:

```vue
<div v-if="selectedGateChecks.length" class="gate-matrix">
  <div class="section-header compact">
    <h4>规则矩阵</h4>
    <span>{{ selectedEntryDecision?.summary || '无阻断' }}</span>
  </div>
  <div class="gate-table">
    <div class="gate-row gate-head">
      <span>规则</span>
      <span>结果</span>
      <span>硬阻断</span>
      <span>当前值</span>
      <span>要求</span>
    </div>
    <div
      v-for="check in selectedGateChecks"
      :key="check.key"
      class="gate-row"
      :data-status="check.status"
    >
      <span>{{ check.label }}</span>
      <strong>{{ gateStatusLabel(check.status) }}</strong>
      <span>{{ check.hardBlock ? '是' : '否' }}</span>
      <span>{{ formatGateActual(check.actual) }}</span>
      <span>{{ check.expected }}</span>
    </div>
  </div>
</div>
```

- [ ] **Step 6: Add panel CSS**

Add near `.fact-notes`:

```css
.config-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
  margin-top: 12px;
}

.config-strip div {
  min-width: 0;
  padding: 8px 10px;
  background: rgba(13, 17, 24, 0.62);
  border: 1px solid var(--candidate-line);
  border-radius: 7px;
}

.config-strip span {
  display: block;
  color: var(--candidate-muted);
  font-size: 11px;
  font-weight: 700;
}

.config-strip strong {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--candidate-text);
  font-family: var(--candidate-font-data);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.gate-matrix {
  margin-top: 12px;
}

.section-header.compact {
  margin-bottom: 8px;
}

.gate-table {
  display: grid;
  gap: 4px;
}

.gate-row {
  display: grid;
  grid-template-columns: 1.15fr 0.55fr 0.55fr 1.15fr 1.15fr;
  gap: 8px;
  align-items: center;
  min-height: 30px;
  padding: 6px 8px;
  color: var(--candidate-muted);
  background: rgba(13, 17, 24, 0.58);
  border: 1px solid rgba(90, 104, 124, 0.26);
  border-radius: 6px;
  font-size: 12px;
}

.gate-head {
  color: #c7d3e6;
  background: rgba(94, 182, 255, 0.08);
  font-weight: 800;
}

.gate-row strong {
  font-size: 12px;
}

.gate-row[data-status='pass'] strong {
  color: #7ee0a3;
}

.gate-row[data-status='warn'] strong {
  color: #ffd36a;
}

.gate-row[data-status='fail'] strong {
  color: #ff8f9f;
}

.gate-row[data-status='disabled'] strong {
  color: #8f99a8;
}
```

- [ ] **Step 7: Run panel tests**

Run:

```powershell
pnpm exec vitest run src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```powershell
git add src/components/panels/CandidatePoolPanel.vue src/components/panels/__tests__/CandidatePoolPanel.test.ts
git commit -m "feat: add candidate pool gate workbench"
```

---

## Task 10: Add Pending Strategy Mode Setting Persistence

**Files:**
- Modify: `src/components/panels/CandidatePoolPanel.vue`
- Modify: `src/config/rankTrendLiveStrategyConfig.ts`
- Modify: `src/services/rankTrend/v5FusionExecutionContract.ts`
- Test: `src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts`

- [ ] **Step 1: Add failing persistence tests**

Append to `rankTrendLiveStrategyConfig.test.ts`:

```ts
  it('builds preset config by mode', () => {
    expect(normalizeRankTrendLiveStrategyConfig({ mode: 'recall_first' }).mode).toBe('recall_first')
    expect(normalizeRankTrendLiveStrategyConfig({ mode: 'strict_execution' }).mode).toBe('strict_execution')
  })
```

- [ ] **Step 2: Run tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts
```

Expected: PASS if Task 1 already covers this. If PASS, continue with UI wiring.

- [ ] **Step 3: Add pending mode selector without changing the current detail snapshot**

In `CandidatePoolPanel.vue` toolbar, after status filter:

```vue
<select v-model="pendingStrategyMode" title="待生效策略模式">
  <option value="balanced">待生效：均衡盯盘</option>
  <option value="recall_first">待生效：召回优先</option>
  <option value="strict_execution">待生效：严格执行</option>
</select>
<span class="mode-note">当前详情以参数快照为准，待生效设置刷新信号后应用</span>
```

Add script:

```ts
import {
  RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'
import type { RankTrendLiveStrategyMode } from '@/types/rankTrendLiveStrategy'
```

Add ref and watcher:

```ts
const pendingStrategyMode = ref<RankTrendLiveStrategyMode>('balanced')

watch(pendingStrategyMode, (mode) => {
  localStorage.setItem(
    RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
    JSON.stringify(normalizeRankTrendLiveStrategyConfig({ mode })),
  )
})

onMounted(() => {
  const raw = localStorage.getItem(RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY)
  if (!raw) return
  try {
    pendingStrategyMode.value = normalizeRankTrendLiveStrategyConfig(JSON.parse(raw)).mode
  } catch {
    pendingStrategyMode.value = 'balanced'
  }
})
```

- [ ] **Step 4: Keep current diagnostic snapshot visually separate from pending settings**

Do not overwrite `selectedConfigSnapshot` when the user changes `pendingStrategyMode`. The rule matrix and parameter snapshot always describe the already computed `entryDecision.configSnapshot`.

```vue
<div v-if="selectedConfigSnapshot" class="snapshot-note">
  当前诊断：{{ strategyModeLabel(selectedConfigSnapshot.mode) }} · {{ selectedConfigSnapshot.version }}
</div>
```

The selector is a pending setting, not a live recomputation control. Do not mutate `DataLayer`, do not add Pinia, and do not force live signal recomputation from the panel in this task.

- [ ] **Step 5: Commit**

```powershell
git add src/components/panels/CandidatePoolPanel.vue src/config/rankTrendLiveStrategyConfig.ts src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts
git commit -m "feat: expose pending candidate pool strategy mode"
```

---

## Task 11: Sync Live Evaluation With Persisted Config

**Files:**
- Create: `src/services/rankTrend/liveStrategyConfigStore.ts`
- Modify: `src/services/rankTrend/v5FusionExecutionContract.ts`
- Test: `src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts`

- [ ] **Step 1: Add a small browser-safe config reader**

Create `src/services/rankTrend/liveStrategyConfigStore.ts`:

```ts
import {
  DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG,
  RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY,
  normalizeRankTrendLiveStrategyConfig,
} from '@/config/rankTrendLiveStrategyConfig'
import type { RankTrendLiveStrategyConfig } from '@/types/rankTrendLiveStrategy'

export function getRankTrendLiveStrategyConfig(): RankTrendLiveStrategyConfig {
  if (typeof localStorage === 'undefined') return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  const raw = localStorage.getItem(RANK_TREND_LIVE_STRATEGY_CONFIG_STORAGE_KEY)
  if (!raw) return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  try {
    return normalizeRankTrendLiveStrategyConfig(JSON.parse(raw))
  } catch {
    return DEFAULT_RANK_TREND_LIVE_STRATEGY_CONFIG
  }
}
```

- [ ] **Step 2: Use reader in V5 evaluation default path**

Modify `v5FusionExecutionContract.ts`:

```ts
import { getRankTrendLiveStrategyConfig } from './liveStrategyConfigStore'
```

Change config creation:

```ts
  const config = normalizeRankTrendLiveStrategyConfig({
    ...getRankTrendLiveStrategyConfig(),
    ...configPatch,
  })
```

- [ ] **Step 3: Keep tests deterministic**

Tests should pass explicit config patches where needed. For tests relying on default balanced mode, clear localStorage at test start:

```ts
beforeEach(() => {
  localStorage.clear()
})
```

- [ ] **Step 4: Run V5 tests**

Run:

```powershell
pnpm exec vitest run src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src/services/rankTrend/liveStrategyConfigStore.ts src/services/rankTrend/v5FusionExecutionContract.ts src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts
git commit -m "feat: read persisted ranktrend live config"
```

---

## Task 12: Update Documentation And Old Plan Notes

**Files:**
- Modify: `quant-board/docs/superpowers/plans/2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md`
- Modify: `quant-board/docs/api-cli.md` if live gate docs mention hard `change_lt_6`

- [ ] **Step 1: Add a correction note to the old V5 plan**

Append near the V5 live execution contract boundary:

```markdown
> Correction note (2026-06-10): live 盯盘体验优先级已提升为 V5 live contract 的一等目标。`change < 6` 不再作为默认 live 自动入池硬阻断；默认 `balanced` 模式把涨幅位置作为观察降级/排序因素。只有显式选择 `strict_execution` 模式时，才恢复与历史回测执行合同一致的 `change < 6` 硬门槛。
```

- [ ] **Step 2: Document DataTable constraint**

Add:

```markdown
DataTable 不新增“阻断原因/策略模式/入池原因”等额外列。所有 live gate 解释压缩在既有“候选池”列和 CandidatePoolPanel 详情中，避免分散盯盘注意力。
```

- [ ] **Step 3: Commit docs**

```powershell
git add quant-board/docs/superpowers/plans/2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md
git commit -m "docs: clarify ranktrend live gate correction"
```

---

## Task 13: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run focused RankTrend and component tests**

Run:

```powershell
pnpm exec vitest run `
  src/services/rankTrend/__tests__/rankTrendLiveStrategyConfig.test.ts `
  src/services/rankTrend/__tests__/liveLimitState.test.ts `
  src/services/rankTrend/__tests__/liveGateCheckBuilder.test.ts `
  src/services/rankTrend/__tests__/v5FusionExecutionContract.test.ts `
  src/services/rankTrend/__tests__/FusionStrategyProjector.test.ts `
  src/services/rankTrend/__tests__/FusionCandidateNotifier.test.ts `
  src/services/candidate/__tests__/CandidatePoolStatusProjector.test.ts `
  src/components/common/__tests__/DataTable.test.ts `
  src/components/panels/__tests__/CandidatePoolPanel.test.ts
```

Expected: PASS.

- [ ] **Step 2: Run RankTrend suite**

Run:

```powershell
pnpm test:ranktrend
```

Expected: PASS.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
pnpm typecheck:ranktrend
pnpm exec vue-tsc --noEmit -p tsconfig.app.json --pretty false
```

Expected: PASS.

- [ ] **Step 4: Browser validation**

Start dev server if not already running:

```powershell
pnpm dev -- --host 127.0.0.1 --port 5173
```

Validate in browser:

- DataTable still has one “候选池” column.
- 000970-like row with `change >= 6` shows `观察候选` or `被阻断` according to selected mode, not silent `未触发`.
- Clicking the existing “候选池” badge opens CandidatePoolPanel for both persisted candidate entries and transient live projections.
- CandidatePoolPanel shows “策略模式”, “参数快照”, and “规则矩阵”.
- For a non-persisted live projection row, CandidatePoolPanel shows the rule matrix and hides journal-only actions such as delete/save execution.
- No visible text overlaps inside the candidate pool badge at desktop width.
- Console has no Vue warnings or runtime errors during refresh and panel open.

Use Playwright/browser validation for this step. Source-contract Vitest tests are only guardrails for file structure and copy; they do not replace real click-path validation.

- [ ] **Step 5: Final diff review**

Run:

```powershell
git status --short
git diff --stat
git diff -- src/services/rankTrend src/services/candidate src/components/common/DataTable.vue src/App.vue src/components/panels/CandidatePoolPanel.vue src/types src/config quant-board/docs/superpowers/plans/2026-06-10-ranktrend-v5-live-execution-contract-implementation-plan.md
```

Expected:

- No unrelated files.
- No new DataTable columns.
- No hardcoded `change >= 6` live block in `v5FusionExecutionContract.ts`.
- No tooltip-only explanation path.

---

## Self-Review

- Spec coverage: This plan covers configurable live strategy defaults, quote-first limit-up detection, structured gate diagnostics, DataTable single-column constraint, CandidatePoolPanel workbench, notifier behavior, and documentation correction.
- Placeholder scan: No `TBD`, `TODO`, or “write tests for the above” placeholders are present.
- Type consistency: `RankTrendLiveEntryDecision`, `entryDecision`, `decisionState`, `checks`, `firstBlockingCheck`, `configSnapshot`, and `CandidatePoolOpenPayload` are consistently named across types, projector, App.vue, DataTable, and CandidatePoolPanel.
- Scope check: This plan deliberately does not refactor all lifecycle/risk/model internals into user config. It fixes the live candidate execution/UX layer first, which is the user-visible failure surface.
