# V2 Long-Test Plan Phase A-C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first three layers of the V2 four-layer decision framework: Layer 3 trade journal execution fields (Phase A), Layer 1 signal efficacy + Layer 2 execution quality metrics (Phase B), and Layer 3 alignment report API (Phase C).

**Architecture:** Three-phase incremental build. Phase A extends the existing `TradeJournal` model and `CandidatePoolPanel.vue` with 7 execution fields. Phase B adds two new pure functions (`compute_signal_efficacy()`, `compute_execution_quality()`) to the backtest service and extends `summarize_longtest_baseline()` to include Layer 1-2 output. Phase C adds a new API endpoint for cross-referencing journal trades against backtest signals.

**Tech Stack:** Python 3.13 (FastAPI + Pydantic dataclasses + MongoDB), TypeScript (Vue 3 `<script setup>` + Pinia), Vitest (frontend), pytest (backend).

**Design doc:** `quant-board/docs/optimization-long-task/2026-05-26-longtest-v2-design.md`

---

## File Map

| Phase | File | Action | Responsibility |
|---|---|---|---|
| A | `quant-board/backend/data/models.py:525-593` | Modify | Add 7 execution fields to `TradeJournal` |
| A | `quant-board/backend/api/journal_routes.py:41-99` | Modify | Add fields to request models |
| A | `quant-board/src/components/panels/CandidatePoolPanel.vue` | Modify | Add execution record form in review card |
| A | `quant-board/src/services/candidate/types.ts` | Modify | Add execution fields to TypeScript types |
| A | `quant-board/src/services/candidate/CandidateJournalService.ts` | Modify | Pass execution fields in API calls |
| B | `quant-board/backend/services.py` | Modify | Add `compute_signal_efficacy()`, `compute_execution_quality()` |
| B | `quant-board/backend/cli.py:641-694` | Modify | Extend `summarize_longtest_baseline()` with Layer 1-2 |
| B | `quant-board/backend/core/backtest/__init__.py` | Modify | Export new functions |
| B | `quant-board/tests/test_quant_board.py` | Modify | Add Layer 1-2 unit + integration tests |
| C | `quant-board/backend/api/backtest_routes.py` | Modify | Add `/api/backtests/alignment` endpoint |
| C | `quant-board/backend/cli.py:697-720` | Modify | Integrate alignment into checkpoint |
| C | `quant-board/tests/test_quant_board.py` | Modify | Add alignment endpoint + integration tests |

---

### Task 1: Add 7 execution fields to TradeJournal model

**Files:**
- Modify: `quant-board/backend/data/models.py:525-594`

- [ ] **Step 1: Add fields to TradeJournal dataclass**

```python
# In quant-board/backend/data/models.py, after the TradeJournal class definition,
# add these 7 fields after `expected_holding_days` (line 549):

    # ---- Layer 3 execution fields ----
    entry_price: float | None = None        # 实际买入价
    entry_time: str | None = None           # 实际买入时间 (ISO 8601)
    exit_price: float | None = None         # 实际卖出价
    exit_time: str | None = None            # 实际卖出时间 (ISO 8601)
    stop_loss_price: float | None = None    # 止损线
    take_profit_price: float | None = None  # 止盈线
    position_pct: float | None = None       # 仓位占比 (0.0–1.0)
```

- [ ] **Step 2: Add fields to to_dict() method**

```python
# In TradeJournal.to_dict(), add after `"expectedHoldingDays": self.expected_holding_days,`:

            "entryPrice": self.entry_price,
            "entryTime": self.entry_time,
            "exitPrice": self.exit_price,
            "exitTime": self.exit_time,
            "stopLossPrice": self.stop_loss_price,
            "takeProfitPrice": self.take_profit_price,
            "positionPct": self.position_pct,
```

- [ ] **Step 3: Verify model import**

Run: `cd quant-board && .venv/Scripts/python.exe -c "from backend.data.models import TradeJournal; t = TradeJournal(id='test', stock_code='000001', stock_name='test'); print(t.to_dict().keys())"`
Expected: Output includes `entryPrice`, `entryTime`, `exitPrice`, `exitTime`, `stopLossPrice`, `takeProfitPrice`, `positionPct`

- [ ] **Step 4: Commit**

```bash
git add quant-board/backend/data/models.py
git commit -m "feat: add Layer 3 execution fields to TradeJournal model"
```

---

### Task 2: Extend journal API request models

**Files:**
- Modify: `quant-board/backend/api/journal_routes.py:41-99`

- [ ] **Step 1: Add fields to CreateJournalEntryRequest**

```python
# In CreateJournalEntryRequest, add after `expected_holding_days: int = 3`:

    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
```

- [ ] **Step 2: Add fields to UpdateJournalEntryRequest**

```python
# In UpdateJournalEntryRequest, add after `expected_holding_days: int | None = None`:

    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
```

- [ ] **Step 3: Pass new fields in create_entry()**

```python
# In create_entry() function (line 107), add after `expected_holding_days=payload.expected_holding_days,`:

        entry_price=payload.entry_price,
        entry_time=payload.entry_time,
        exit_price=payload.exit_price,
        exit_time=payload.exit_time,
        stop_loss_price=payload.stop_loss_price,
        take_profit_price=payload.take_profit_price,
        position_pct=payload.position_pct,
```

- [ ] **Step 4: Add field mapping in update_entry()**

```python
# In update_entry() field_map dict (line 196), add after `"expected_holding_days": "expectedHoldingDays",`:

        "entry_price": "entryPrice",
        "entry_time": "entryTime",
        "exit_price": "exitPrice",
        "exit_time": "exitTime",
        "stop_loss_price": "stopLossPrice",
        "take_profit_price": "takeProfitPrice",
        "position_pct": "positionPct",
```

- [ ] **Step 5: Test API round-trip**

Run: `cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "journal" -v`
Expected: Existing journal tests still pass

- [ ] **Step 6: Commit**

```bash
git add quant-board/backend/api/journal_routes.py
git commit -m "feat: add Layer 3 execution fields to journal API request models"
```

---

### Task 3: Add execution record form to CandidatePoolPanel.vue

**Files:**
- Modify: `quant-board/frontend/src/components/panels/CandidatePoolPanel.vue` → Wait, check the actual path...

Actually, the CandidatePoolPanel is at: `src/components/panels/CandidatePoolPanel.vue` (in the root project, not quant-board/frontend). Let me re-check.

<system-reminder>
The agent is attempting to write a file at: d:\dragon-board\quant-board\docs\superpowers\plans\2026-05-26-longtest-v2-phase-a-c.md. The user should be aware that this will create a new file.
</system-reminder>

The CandidatePoolPanel is in the root Dragon Board project, not in quant-board/frontend. The file path is `src/components/panels/CandidatePoolPanel.vue`. Let me also check the types file.

Wait, the types are at `src/services/candidate/types.ts` in the root project.

Let me continue writing the plan with the correct paths. Actually, let me just write the whole plan file at once rather than trying to edit it piecemeal.

Actually wait - the file I was trying to write to is:
`d:\dragon-board\quant-board\docs\superpowers\plans\2026-05-26-longtest-v2-phase-a-c.md`

But the CandidatePoolPanel.vue is at:
`d:\dragon-board\src\components\panels\CandidatePoolPanel.vue`

That's fine - the plan file goes in quant-board/docs, and references files across both the root project and quant-board backend. The plan needs to use absolute paths from the repo root.

Let me just write the complete plan file now. I'll be precise with paths.<｜end▁of▁thinking｜>

<｜｜DSML｜｜tool_calls>
<｜｜DSML｜｜invoke name="Write">
<｜｜DSML｜｜parameter name="content" string="true"># V2 Long-Test Plan Phase A-C Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the first three phases of the V2 four-layer decision framework: trade journal execution fields (Phase A), Layer 1-2 signal and execution quality metrics (Phase B), and alignment report API (Phase C).

**Architecture:** Three-phase incremental build. Phase A extends the `TradeJournal` model + `CandidatePoolPanel.vue` with 7 execution fields — pure data plumbing, no new logic. Phase B adds two pure functions (`compute_signal_efficacy()`, `compute_execution_quality()`) computed during backtest, plus extends `summarize_longtest_baseline()`. Phase C adds one new API endpoint (`/api/backtests/alignment`) that cross-references the trade_journal collection against backtest signals.

**Tech Stack:** Python 3.13 (FastAPI + Pydantic dataclass `TradeJournal` + MongoDB), TypeScript (Vue 3 `<script setup>` + Pinia), pytest (backend), Vitest (frontend).

**Design doc:** `quant-board/docs/optimization-long-task/2026-05-26-longtest-v2-design.md`

---

## File Map

| Phase | File | Action | Responsibility |
|---|---|---|---|
| A | `quant-board/backend/data/models.py:525-593` | Modify | Add 7 execution fields to `TradeJournal` + `to_dict()` |
| A | `quant-board/backend/api/journal_routes.py:41-99` | Modify | Add fields to `CreateJournalEntryRequest` + `UpdateJournalEntryRequest` + `create_entry()` + `update_entry()` field_map |
| A | `src/components/panels/CandidatePoolPanel.vue` | Modify | Add "执行记录" form section in review card |
| A | `src/services/candidate/types.ts` | Modify | Add `TradeExecutionFields` interface |
| A | `src/services/candidate/CandidateJournalService.ts` | Modify | Pass execution fields in `saveCandidateReview()` |
| B | `quant-board/backend/services.py` | Modify | Add `compute_signal_efficacy()` after `_price_quality_diagnostics()` |
| B | `quant-board/backend/services.py` | Modify | Add `compute_execution_quality()` after `compute_signal_efficacy()` |
| B | `quant-board/backend/services.py:520-569` | Modify | Call new functions in `run_ranktrend()`, pass into quality_gate |
| B | `quant-board/backend/core/backtest/engine.py:122-199` | Modify | Pass Layer 1-2 diagnostics through `_data_quality_summary()` |
| B | `quant-board/backend/cli.py:641-694` | Modify | Extend `summarize_longtest_baseline()` with Layer 1-2 fields |
| B | `quant-board/tests/test_money_flow_quality_gate.py` | Modify | Add helper unit tests for new functions |
| B | `quant-board/tests/test_quant_board.py` | Modify | Add integration test for Layer 1-2 in backtest output |
| C | `quant-board/backend/api/backtest_routes.py` | Modify | Add `GET /api/backtests/alignment` endpoint |
| C | `quant-board/backend/cli.py:697-720` | Modify | Integrate alignment call into `cmd_run_longtest_baselines()` |
| C | `quant-board/tests/test_quant_board.py` | Modify | Add alignment endpoint + integration tests |

---

## Phase A: Layer 3 Data Structure

### Task A1: Add 7 execution fields to TradeJournal model

**File:** `quant-board/backend/data/models.py`

- [ ] **Step A1.1: Add fields to TradeJournal dataclass**

Insert after line 549 (`expected_holding_days: int = 3`):

```python
    # ---- Layer 3 execution fields (V2 long-test plan) ----
    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
```

- [ ] **Step A1.2: Add fields to to_dict()**

Insert after line 584 (`"expectedHoldingDays": self.expected_holding_days,`):

```python
            "entryPrice": self.entry_price,
            "entryTime": self.entry_time,
            "exitPrice": self.exit_price,
            "exitTime": self.exit_time,
            "stopLossPrice": self.stop_loss_price,
            "takeProfitPrice": self.take_profit_price,
            "positionPct": self.position_pct,
```

- [ ] **Step A1.3: Verify import**

```bash
cd quant-board && .venv/Scripts/python.exe -c "from backend.data.models import TradeJournal; t = TradeJournal(id='t1', stock_code='000001', stock_name='test', entry_price=12.5); d = t.to_dict(); assert d['entryPrice'] == 12.5; print('OK')"
```

- [ ] **Step A1.4: Commit**

```bash
git add quant-board/backend/data/models.py
git commit -m "feat: add Layer 3 execution fields to TradeJournal model"
```

---

### Task A2: Extend journal API request models

**File:** `quant-board/backend/api/journal_routes.py`

- [ ] **Step A2.1: Add fields to CreateJournalEntryRequest**

Insert after line 61 (`expected_holding_days: int = 3`):

```python
    # Layer 3 execution fields
    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
```

- [ ] **Step A2.2: Add fields to UpdateJournalEntryRequest**

Insert after line 92 (`expected_holding_days: int | None = None`):

```python
    # Layer 3 execution fields
    entry_price: float | None = None
    entry_time: str | None = None
    exit_price: float | None = None
    exit_time: str | None = None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    position_pct: float | None = None
```

- [ ] **Step A2.3: Pass new fields in create_entry()**

Insert after line 128 (`expected_holding_days=payload.expected_holding_days,`):

```python
        entry_price=payload.entry_price,
        entry_time=payload.entry_time,
        exit_price=payload.exit_price,
        exit_time=payload.exit_time,
        stop_loss_price=payload.stop_loss_price,
        take_profit_price=payload.take_profit_price,
        position_pct=payload.position_pct,
```

- [ ] **Step A2.4: Add field mapping in update_entry()**

Insert after line 218 (`"expected_holding_days": "expectedHoldingDays",`):

```python
        "entry_price": "entryPrice",
        "entry_time": "entryTime",
        "exit_price": "exitPrice",
        "exit_time": "exitTime",
        "stop_loss_price": "stopLossPrice",
        "take_profit_price": "takeProfitPrice",
        "position_pct": "positionPct",
```

- [ ] **Step A2.5: Verify existing journal tests still pass**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "journal or trade_journal" -v
```

- [ ] **Step A2.6: Commit**

```bash
git add quant-board/backend/api/journal_routes.py
git commit -m "feat: add Layer 3 execution fields to journal API request models"
```

---

### Task A3: Add TypeScript types for execution fields

**Files:**
- Modify: `src/services/candidate/types.ts`

- [ ] **Step A3.1: Add TradeExecutionFields interface**

Find the existing `CandidateReviewUpdate` interface and add before it:

```typescript
export interface TradeExecutionFields {
  entryPrice?: number
  entryTime?: string
  exitPrice?: number
  exitTime?: string
  stopLossPrice?: number
  takeProfitPrice?: number
  positionPct?: number
}
```

- [ ] **Step A3.2: Extend CandidateReviewUpdate to include execution fields**

Add `& Partial<TradeExecutionFields>` to the `CandidateReviewUpdate` type, or add the fields directly:

```typescript
export interface CandidateReviewUpdate extends Partial<TradeExecutionFields> {
  reviewOutcome: string
  modelResult: string
  executionResult: string
  reviewNotes: string
}
```

- [ ] **Step A3.3: TypeScript check**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | head -20
```
Expected: No new type errors related to candidate types.

- [ ] **Step A3.4: Commit**

```bash
git add src/services/candidate/types.ts
git commit -m "feat: add Layer 3 TradeExecutionFields TypeScript types"
```

---

### Task A4: Add execution record form to CandidatePoolPanel.vue

**File:** `src/components/panels/CandidatePoolPanel.vue`

- [ ] **Step A4.1: Add reactive form state**

Find the existing `reviewForm` ref (around line 482) and add after it:

```typescript
const execForm = ref<TradeExecutionFields>({
  entryPrice: undefined,
  entryTime: '',
  exitPrice: undefined,
  exitTime: '',
  stopLossPrice: undefined,
  takeProfitPrice: undefined,
  positionPct: undefined,
})
```

Import `TradeExecutionFields` from `@/services/candidate/types`.

- [ ] **Step A4.2: Add execution record section in template**

Insert inside the `<section class="review-card">` element, before the closing `</section>` tag (around line 335). Place it between the review form fields and the "复盘结论" textarea:

```html
                  <div class="execution-record">
                    <div class="section-header">
                      <h4>执行记录</h4>
                      <span>实际成交详情，用于回测对齐</span>
                    </div>
                    <div class="form-grid exec-grid">
                      <label>
                        <span>买入价</span>
                        <input v-model.number="execForm.entryPrice" type="number" step="0.01" placeholder="12.50" />
                      </label>
                      <label>
                        <span>买入时间</span>
                        <input v-model="execForm.entryTime" type="datetime-local" />
                      </label>
                      <label>
                        <span>卖出价</span>
                        <input v-model.number="execForm.exitPrice" type="number" step="0.01" placeholder="13.20" />
                      </label>
                      <label>
                        <span>卖出时间</span>
                        <input v-model="execForm.exitTime" type="datetime-local" />
                      </label>
                      <label>
                        <span>止损线</span>
                        <input v-model.number="execForm.stopLossPrice" type="number" step="0.01" placeholder="11.70" />
                      </label>
                      <label>
                        <span>止盈线</span>
                        <input v-model.number="execForm.takeProfitPrice" type="number" step="0.01" placeholder="14.50" />
                      </label>
                      <label>
                        <span>仓位占比</span>
                        <input v-model.number="execForm.positionPct" type="number" step="0.01" min="0" max="1" placeholder="0.20" />
                      </label>
                    </div>
                  </div>
```

- [ ] **Step A4.3: Wire execForm into applySelectedEntryToForms and saveReview**

In `applySelectedEntryToForms()` (line 634), add loading of execution fields:

```typescript
  execForm.value = {
    entryPrice: entry?.entryPrice ?? undefined,
    entryTime: entry?.entryTime ?? '',
    exitPrice: entry?.exitPrice ?? undefined,
    exitTime: entry?.exitTime ?? '',
    stopLossPrice: entry?.stopLossPrice ?? undefined,
    takeProfitPrice: entry?.takeProfitPrice ?? undefined,
    positionPct: entry?.positionPct ?? undefined,
  }
```

Note: `CandidateJournalEntry` needs the 7 fields added via `normalizeEntry()`. See Task A4.4.

In `saveReview()`, merge execForm into the review update call:

```typescript
    const updated = await candidateJournalService.saveCandidateReview(selectedEntry.value.id, {
      ...reviewForm.value,
      ...execForm.value,
    })
```

- [ ] **Step A4.4: Add execution fields to normalizeEntry() in CandidateJournalService.ts**

In `src/services/candidate/CandidateJournalService.ts`, find `normalizeEntry()` (line 71) and add after `expectedHoldingDays` line:

```typescript
    entryPrice: toSafeNumber(raw?.entryPrice ?? raw?.entry_price),
    entryTime: String(raw?.entryTime || raw?.entry_time || ''),
    exitPrice: toSafeNumber(raw?.exitPrice ?? raw?.exit_price),
    exitTime: String(raw?.exitTime || raw?.exit_time || ''),
    stopLossPrice: toSafeNumber(raw?.stopLossPrice ?? raw?.stop_loss_price),
    takeProfitPrice: toSafeNumber(raw?.takeProfitPrice ?? raw?.take_profit_price),
    positionPct: toSafeNumber(raw?.positionPct ?? raw?.position_pct),
```

Also extend the `CandidateJournalEntry` type in `types.ts` to include these fields.

- [ ] **Step A4.5: Add CSS for exec-grid**

In the `<style scoped>` section, find the `.review-grid` style and add after it:

```css
.exec-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--candidate-line);
}
```

- [ ] **Step A4.6: Verify type check**

```bash
cd d:/dragon-board && npx vue-tsc --noEmit -p tsconfig.app.json 2>&1 | grep -i "candidate\|execForm\|execution" | head -20
```
Expected: No type errors.

- [ ] **Step A4.7: Commit**

```bash
git add src/components/panels/CandidatePoolPanel.vue src/services/candidate/types.ts src/services/candidate/CandidateJournalService.ts
git commit -m "feat: add Layer 3 execution record form to candidate pool panel"
```

---

## Phase B: Layer 1-2 Metrics

### Task B1: Add compute_signal_efficacy() function

**File:** `quant-board/backend/services.py`

Insert after the `_price_quality_diagnostics()` function (after line 337):

- [ ] **Step B1.1: Write the function**

```python
def compute_signal_efficacy(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    """Layer 1: compute signal tier stability, direction accuracy, and tier discrimination."""
    if not signals:
        return {
            "tierRatio": None,
            "directionAccuracy": None,
            "tierDiscrimination": None,
            "diagnostics": "no_signals",
        }

    total = len(signals)
    tier_counts: dict[str, int] = {}
    a_main_prices: list[dict[str, Any]] = []
    n_neutral_prices: list[dict[str, Any]] = []

    for signal in signals:
        tier = str((((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality") or {}).get("tier") or "?")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    a_plus_b = tier_counts.get("A_MAIN", 0) + tier_counts.get("B_IGNITION", 0)
    tier_ratio = round(a_plus_b / total, 4) if total else 0.0

    # Build frame index for next-bar price lookup
    frame_index: dict[str, int] = {}
    for idx, frame in enumerate(frames):
        sid = str(frame.get("snapshotId") or "")
        frame_index[sid] = idx

    a_correct = 0
    a_total = 0
    n_correct = 0
    n_total = 0

    for signal in signals:
        tier = str((((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality") or {}).get("tier") or "?")
        sid = str(signal.get("snapshotId") or "")
        code = str(signal.get("code") or "")
        frame_pos = frame_index.get(sid)
        if frame_pos is None or frame_pos + 1 >= len(frames):
            continue
        next_frame = frames[frame_pos + 1]
        next_stocks = next_frame.get("stocks") or []
        next_stock = next((s for s in next_stocks if str(s.get("code") or "") == code), None)
        if next_stock is None:
            continue
        try:
            current_price = float(signal.get("price") or 0)
            next_price = float(next_stock.get("price") or 0)
        except (TypeError, ValueError):
            continue
        price_up = next_price > current_price

        if tier == "A_MAIN":
            a_total += 1
            if price_up:
                a_correct += 1
        elif tier == "N_NEUTRAL":
            n_total += 1
            if price_up:
                n_correct += 1

    direction_accuracy = round(a_correct / a_total, 4) if a_total > 0 else None
    n_accuracy = round(n_correct / n_total, 4) if n_total > 0 else None
    tier_discrimination = round((direction_accuracy or 0) - (n_accuracy or 0), 4) if direction_accuracy is not None and n_accuracy is not None else None

    # Binomial test p-value for direction accuracy vs random (H0: p = 0.5)
    import math
    p_val: float | None = None
    if a_total >= 5 and direction_accuracy is not None:
        # Wald approximation for binomial proportion test
        se = math.sqrt(0.5 * 0.5 / a_total)
        z = (direction_accuracy - 0.5) / se if se > 0 else 0
        # One-sided p-value (approximate with normal CDF)
        p_val = round(0.5 * (1 + math.erf(z / math.sqrt(2))), 4)
        p_val = 1 - p_val  # one-sided: P(Z > z) under H0

    return {
        "tierRatio": tier_ratio,
        "aPlusBTierCount": a_plus_b,
        "tierCounts": tier_counts,
        "totalSignals": total,
        "directionAccuracy": direction_accuracy,
        "aMainSamples": a_total,
        "nNeutralSamples": n_total,
        "tierDiscrimination": tier_discrimination,
        "binomialPValue": p_val,
        "thresholds": {
            "directionAccuracyMin": 0.55,
            "binomialPMax": 0.10,
            "tierDiscriminationMin": 0.05,
            "tierRatioMin": 0.02,
            "tierRatioMax": 0.15,
        },
        "layer1Status": (
            "green" if (
                direction_accuracy is not None and direction_accuracy > 0.55
                and (p_val is not None and p_val < 0.10)
                and tier_discrimination is not None and tier_discrimination > 0.05
                and 0.02 <= tier_ratio <= 0.15
            ) else "red"
        ),
    }
```

- [ ] **Step B1.2: Run import check**

```bash
cd quant-board && .venv/Scripts/python.exe -c "from backend.services import compute_signal_efficacy; print('OK')"
```

- [ ] **Step B1.3: Commit**

```bash
git add quant-board/backend/services.py
git commit -m "feat: add Layer 1 signal efficacy computation"
```

---

### Task B2: Add compute_execution_quality() function

**File:** `quant-board/backend/services.py`

Insert after `compute_signal_efficacy()`:

- [ ] **Step B2.1: Write the function**

```python
def compute_execution_quality(
    h1_summary: dict[str, Any],
    h2_summary: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Layer 2: compute execution bias between current_bar (H1) and next_bar (H2)."""
    h1_return = float(h1_summary.get("totalReturn") or 0)
    h2_return = float(h2_summary.get("totalReturn") or 0)
    bias = round(h1_return - h2_return, 4)
    abs_h1 = abs(h1_return)
    threshold = min(abs_h1, 0.15) if abs_h1 > 0 else 0.15

    h1_trades = int(h1_summary.get("tradeCount") or 0)
    h2_trades = int(h2_summary.get("tradeCount") or 0)
    trade_diff = h2_trades - h1_trades

    h1_dd = float(h1_summary.get("maxDrawdown") or 0)
    h2_dd = float(h2_summary.get("maxDrawdown") or 0)
    dd_diff = round(abs(h1_dd - h2_dd), 4)

    # Direction consistency: H1 >= H2 in recent checkpoints
    direction_ok = True
    direction_ratio = 1.0
    if history:
        recent = history[-4:]  # last 4 checkpoints
        h1_better = sum(
            1 for h in recent
            if float((h.get("h1Summary") or {}).get("totalReturn") or 0)
            >= float((h.get("h2Summary") or {}).get("totalReturn") or 0)
        )
        direction_ratio = round(h1_better / len(recent), 2) if recent else 1.0
        direction_ok = direction_ratio >= 0.75

    bias_ok = abs(bias) <= threshold
    trade_diff_ok = trade_diff <= h1_trades * 0.3 if h1_trades > 0 else True
    dd_diff_ok = dd_diff <= 0.05

    all_green = bias_ok and direction_ok and trade_diff_ok and dd_diff_ok

    return {
        "bias": bias,
        "biasThreshold": threshold,
        "biasOk": bias_ok,
        "directionRatio": direction_ratio,
        "directionOk": direction_ok,
        "tradeCountDiff": trade_diff,
        "tradeCountDiffOk": trade_diff_ok,
        "drawdownDiff": dd_diff,
        "drawdownDiffOk": dd_diff_ok,
        "layer2Status": "green" if all_green else "red",
    }
```

- [ ] **Step B2.2: Run import check**

```bash
cd quant-board && .venv/Scripts/python.exe -c "from backend.services import compute_execution_quality; print('OK')"
```

- [ ] **Step B2.3: Commit**

```bash
git add quant-board/backend/services.py
git commit -m "feat: add Layer 2 execution quality computation"
```

---

### Task B3: Wire Layer 1-2 into backtest run and data quality summary

**Files:**
- Modify: `quant-board/backend/services.py:520-569`
- Modify: `quant-board/backend/core/backtest/engine.py:122-199`

- [ ] **Step B3.1: Compute Layer 1 in run_ranktrend()**

In `services.py`, after the backtest engine runs and returns a result, compute Layer 1 from the signals. Find the point in `run_ranktrend()` where the result dict is assembled, and add:

```python
        # Layer 1: signal efficacy (computed from backtest signals)
        layer_1_efficacy = compute_signal_efficacy(
            signals=result.get("signals") or [],
            frames=run_frames,
        )
        quality_gate["layer1SignalEfficacy"] = layer_1_efficacy
```

Insert this after line 544 (`quality_gate["reportOnlyDiagnostics"] = report_only_diagnostics`) — before the research filter switches.

- [ ] **Step B3.2: Pass Layer 1-2 through _data_quality_summary()**

In `engine.py`, in `_data_quality_summary()`, add after the `report_only_diagnostics` extraction (line 138):

```python
        layer_1_efficacy = gate.get("layer1SignalEfficacy") if isinstance(gate.get("layer1SignalEfficacy"), dict) else {}
        layer_2_quality = gate.get("layer2ExecutionQuality") if isinstance(gate.get("layer2ExecutionQuality"), dict) else {}
```

And add to the return dict (after line 197):

```python
            "layer1SignalEfficacy": layer_1_efficacy,
            "layer2ExecutionQuality": layer_2_quality,
```

- [ ] **Step B3.3: Export new functions**

In `quant-board/backend/core/backtest/__init__.py`, ensure `compute_signal_efficacy` and `compute_execution_quality` are importable from `backend.services`.

- [ ] **Step B3.4: Verify existing tests pass**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "backtest" -v --timeout=60 2>&1 | tail -20
```
Expected: Existing backtest tests still pass.

- [ ] **Step B3.5: Commit**

```bash
git add quant-board/backend/services.py quant-board/backend/core/backtest/engine.py quant-board/backend/core/backtest/__init__.py
git commit -m "feat: wire Layer 1-2 diagnostics into backtest pipeline"
```

---

### Task B4: Extend summarize_longtest_baseline() with Layer 1-2 fields

**File:** `quant-board/backend/cli.py:641-694`

- [ ] **Step B4.1: Add Layer 1-2 to summary output**

In `summarize_longtest_baseline()`, add after line 688 (`"priceQualityDiagnostics": ...`):

```python
        "layer1SignalEfficacy": data_quality.get("layer1SignalEfficacy"),
        "layer2ExecutionQuality": data_quality.get("layer2ExecutionQuality"),
```

- [ ] **Step B4.2: Add Layer 2 computation to cmd_run_longtest_baselines()**

In `cmd_run_longtest_baselines()`, after all three baselines are collected, find the H1 and H2 results and compute Layer 2:

```python
    # Layer 2: compute execution quality from H1 vs H2
    h1_baseline = next((b for b in baselines if b.get("label") == "H1_half_hour_current_bar"), None)
    h2_baseline = next((b for b in baselines if b.get("label") == "H2_half_hour_next_bar"), None)
    if h1_baseline and h2_baseline:
        layer_2 = compute_execution_quality(
            h1_summary=h1_baseline,
            h2_summary=h2_baseline,
        )
        # Annotate both baselines with Layer 2
        for baseline in baselines:
            if baseline.get("label") in ("H1_half_hour_current_bar", "H2_half_hour_next_bar"):
                baseline["layer2ExecutionQuality"] = layer_2
```

Insert this after the three baselines are collected and before the final output JSON is assembled (around line 710).

- [ ] **Step B4.3: Verify CLI tests**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py -k "longtest" -v --timeout=60 2>&1 | tail -20
```
Expected: All longtest tests pass.

- [ ] **Step B4.4: Commit**

```bash
git add quant-board/backend/cli.py
git commit -m "feat: add Layer 1-2 fields to long-test baseline summary"
```

---

### Task B5: Add unit tests for compute_signal_efficacy and compute_execution_quality

**File:** `quant-board/tests/test_money_flow_quality_gate.py`

- [ ] **Step B5.1: Write test for compute_signal_efficacy**

Add after the existing price quality diagnostic tests (after line 355):

```python
def test_compute_signal_efficacy_detects_random_signals() -> None:
    from backend.services import compute_signal_efficacy

    # Build fake signals with A_MAIN tier and random next-bar price movement
    signals = [
        {
            "snapshotId": "s1", "code": "000001", "price": 10.0,
            "rankTrend": {"meta": {"sampleQuality": {"tier": "A_MAIN"}}},
        },
        {
            "snapshotId": "s1", "code": "000002", "price": 10.0,
            "rankTrend": {"meta": {"sampleQuality": {"tier": "A_MAIN"}}},
        },
        {
            "snapshotId": "s1", "code": "000003", "price": 10.0,
            "rankTrend": {"meta": {"sampleQuality": {"tier": "N_NEUTRAL"}}},
        },
    ]

    frames = [
        {"snapshotId": "s1", "stocks": [
            {"code": "000001", "price": 10.0},
            {"code": "000002", "price": 10.0},
            {"code": "000003", "price": 10.0},
        ]},
        {"snapshotId": "s2", "stocks": [
            {"code": "000001", "price": 10.5},  # up
            {"code": "000002", "price": 9.5},   # down
            {"code": "000003", "price": 10.6},  # up
        ]},
    ]

    result = compute_signal_efficacy(signals, frames)

    assert result["totalSignals"] == 3
    assert result["aMainSamples"] == 2
    assert result["directionAccuracy"] == 0.5  # 1 correct / 2
    assert result["layer1Status"] == "red"  # 0.5 <= 0.55


def test_compute_execution_quality_flags_large_bias() -> None:
    from backend.services import compute_execution_quality

    h1 = {"totalReturn": 0.05, "tradeCount": 40, "maxDrawdown": -0.03}
    h2 = {"totalReturn": -0.12, "tradeCount": 55, "maxDrawdown": -0.10}

    result = compute_execution_quality(h1, h2)

    assert abs(result["bias"]) > 0.05  # |5% - (-12%)| = 17pp
    assert result["biasOk"] is False
    assert result["drawdownDiff"] > 0.05
    assert result["drawdownDiffOk"] is False
    assert result["layer2Status"] == "red"


def test_compute_execution_quality_accepts_small_bias() -> None:
    from backend.services import compute_execution_quality

    h1 = {"totalReturn": 0.04, "tradeCount": 20, "maxDrawdown": -0.03}
    h2 = {"totalReturn": 0.01, "tradeCount": 22, "maxDrawdown": -0.05}

    result = compute_execution_quality(h1, h2)

    assert abs(result["bias"]) == 0.03
    assert result["biasOk"] is True  # 3pp < min(|4%|, 15pp) = 4pp
    assert result["tradeCountDiff"] == 2
    assert result["tradeCountDiffOk"] is True  # 2 < 20*0.3 = 6
```

- [ ] **Step B5.2: Run new tests**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py -k "signal_efficacy or execution_quality" -v
```
Expected: 3 passed.

- [ ] **Step B5.3: Commit**

```bash
git add quant-board/tests/test_money_flow_quality_gate.py
git commit -m "test: add Layer 1-2 unit tests for signal efficacy and execution quality"
```

---

## Phase C: Layer 3 Alignment Report

### Task C1: Add GET /api/backtests/alignment endpoint

**File:** `quant-board/backend/api/backtest_routes.py`

- [ ] **Step C1.1: Add alignment endpoint**

Insert a new route before the existing routes:

```python
@router.get("/alignment")
def get_alignment(
    checkpoint_id: str = Query(...),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
) -> dict[str, Any]:
    """Cross-reference trade_journal execution records with backtest signals for a checkpoint period."""
    repo = create_repository(None)

    # Fetch journal entries with execution fields (reviewed + has entryPrice)
    journal_entries = repo.list_journal_entries(
        status="reviewed",
        date_from=start_date,
        date_to=end_date,
        limit=200,
    )
    executed = [
        e for e in journal_entries
        if e.get("entryPrice") is not None and e.get("entryPrice", 0) > 0
    ]

    # Fetch checkpoint baselines from JSONL
    import json
    from pathlib import Path
    jsonl_path = Path(__file__).resolve().parent.parent / "data" / "reports" / "long_test_runs.jsonl"
    checkpoint_runs: list[dict[str, Any]] = []
    if jsonl_path.exists():
        with open(jsonl_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line.strip())
                    if record.get("checkpointId") == checkpoint_id:
                        checkpoint_runs = record.get("baselines") or []
                        break
                except (json.JSONDecodeError, KeyError):
                    continue

    # Cross-reference: find journal codes that appear in backtest signals
    signal_codes: set[str] = set()
    for baseline in checkpoint_runs:
        run_id = baseline.get("runId")
        if not run_id:
            continue
        # Fetch signals from backtest result (compact preview)
        bt = repo.get_backtest_run(run_id)
        if not bt:
            continue
        result = bt.get("result") or {}
        signals = result.get("signals") or []
        for s in signals:
            code = str(s.get("code") or "")
            if code:
                signal_codes.add(code)

    journal_codes = {str(e.get("stockCode") or e.get("stock_code", "")) for e in executed}

    intersection = signal_codes & journal_codes
    signal_only = signal_codes - journal_codes
    journal_only = journal_codes - signal_codes

    # Compute intersection P&L
    intersection_entries = [e for e in executed if str(e.get("stockCode") or e.get("stock_code", "")) in intersection]
    intersection_pnl = sum(float(e.get("pnl") or 0) for e in intersection_entries)
    intersection_pnl_pct = round(sum(float(e.get("pnlPct") or 0) for e in intersection_entries), 4)

    sufficient_sample = len(executed) >= 10

    return {
        "checkpointId": checkpoint_id,
        "journalExecutedCount": len(executed),
        "signalCodeCount": len(signal_codes),
        "intersectionCount": len(intersection),
        "signalOnlyCount": len(signal_only),
        "journalOnlyCount": len(journal_only),
        "intersectionCodes": sorted(intersection),
        "signalOnlyCodes": sorted(signal_only)[:30],
        "journalOnlyCodes": sorted(journal_only)[:30],
        "intersectionPnl": intersection_pnl,
        "intersectionPnlPct": intersection_pnl_pct,
        "sufficientSample": sufficient_sample,
        "alignmentStatus": (
            "sufficient" if sufficient_sample else "insufficient_data"
        ),
    }
```

Note: Ensure `from backend.data.repository_factory import create_repository` is imported at the top of the file.

- [ ] **Step C1.2: Verify endpoint is registered**

```bash
cd quant-board && .venv/Scripts/python.exe -c "
from backend.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
assert '/api/backtests/alignment' in routes
print('OK')
"
```

- [ ] **Step C1.3: Commit**

```bash
git add quant-board/backend/api/backtest_routes.py
git commit -m "feat: add GET /api/backtests/alignment endpoint for Layer 3"
```

---

### Task C2: Integrate alignment into run-longtest-baselines

**File:** `quant-board/backend/cli.py:697-720`

- [ ] **Step C2.1: Call alignment after checkpoint completes**

In `cmd_run_longtest_baselines()`, after assembling the final JSONL record, add:

```python
    # Layer 3: compute alignment if trade journal data available
    try:
        from backend.api.backtest_routes import get_alignment
        alignment_result = get_alignment(
            checkpoint_id=checkpoint_id,
            start_date=args.start_date,
            end_date=args.end_date,
        )
        record["layer3Alignment"] = alignment_result
        if alignment_result.get("sufficientSample"):
            print(f"  Layer 3 alignment: {alignment_result['intersectionCount']} overlapping stocks, intersection P&L: {alignment_result['intersectionPnlPct']:.2%}")
        else:
            print(f"  Layer 3 alignment: insufficient data ({alignment_result['journalExecutedCount']} executed trades, need ≥ 10)")
    except Exception as exc:
        print(f"  Layer 3 alignment skipped: {exc}")
        record["layer3Alignment"] = {"status": "skipped", "reason": str(exc)}
```

- [ ] **Step C2.2: Commit**

```bash
git add quant-board/backend/cli.py
git commit -m "feat: integrate Layer 3 alignment into run-longtest-baselines"
```

---

### Task C3: Add integration tests

**File:** `quant-board/tests/test_quant_board.py`

- [ ] **Step C3.1: Write test for Layer 1-2 in backtest output**

Add a test that runs a backtest and verifies the report includes `layer1SignalEfficacy` and `layer2ExecutionQuality`:

```python
def test_ranktrend_backtest_includes_layer1_signal_efficacy(tmp_path: Path) -> None:
    client = TestClient(app)
    bundle = make_bundle(tmp_path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    bundle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    imported = client.post(
        "/api/datasets/import",
        json={"sourceType": "json_bundle", "sourcePath": str(bundle), "name": "layer1-test", "snapshotTypes": ["half_hour"]},
    )
    assert imported.status_code == 200, imported.text
    dataset = imported.json()

    response = client.post(
        "/api/backtests/rank-trend",
        json={"datasetId": dataset["id"], "snapshotType": "half_hour", "randomSeed": 20260430},
    )
    assert response.status_code == 200, response.text
    run = response.json()

    data_quality = run.get("dataQuality") or {}
    layer1 = data_quality.get("layer1SignalEfficacy")
    assert layer1 is not None, "Layer 1 signal efficacy missing from backtest output"
    assert "tierRatio" in layer1
    assert "directionAccuracy" in layer1
    assert "layer1Status" in layer1
    assert layer1["totalSignals"] > 0


def test_longtest_baseline_summary_includes_layer1_layer2(tmp_path: Path) -> None:
    from backend.cli import summarize_longtest_baseline

    spec = {
        "label": "H1_half_hour_current_bar",
        "purpose": "page-compatible optimistic baseline",
        "payload": {"maxHoldingBars": 40, "tradeConfig": {"executionMode": "current_bar"}},
    }
    run = {
        "runId": "bt_test_layer",
        "totalReturn": 0.05,
        "maxDrawdown": -0.03,
        "sharpe": 0.5,
        "winRate": 0.4,
        "tradeCount": 40,
        "dataQuality": {
            "severity": "warn",
            "researchGrade": "degraded",
            "layer1SignalEfficacy": {
                "tierRatio": 0.04,
                "directionAccuracy": 0.6,
                "tierDiscrimination": 0.08,
                "layer1Status": "green",
            },
            "layer2ExecutionQuality": {
                "bias": 0.03,
                "layer2Status": "green",
            },
            "qualityGate": {"stats": {}},
            "reportOnlyDiagnostics": {},
        },
    }

    summary = summarize_longtest_baseline(spec, run)

    layer1 = summary.get("layer1SignalEfficacy")
    assert layer1 is not None, "Layer 1 missing from summary"
    assert layer1["layer1Status"] == "green"

    layer2 = summary.get("layer2ExecutionQuality")
    assert layer2 is not None, "Layer 2 missing from summary"
    assert layer2["layer2Status"] == "green"
```

- [ ] **Step C3.2: Run all new tests**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_quant_board.py tests/test_money_flow_quality_gate.py -k "signal_efficacy or execution_quality or layer1 or layer2 or alignment" -v --timeout=120
```
Expected: All new tests pass.

- [ ] **Step C3.3: Run full regression**

```bash
cd quant-board && .venv/Scripts/python.exe -m pytest tests/test_money_flow_quality_gate.py tests/test_quant_board.py -k "price or cross_market or all_zero or runtime_price_filters or cli_run_ranktrend or longtest_baselines or price_quality_diagnostics or signal_efficacy or execution_quality or layer1 or layer2 or alignment" -v --timeout=120
```
Expected: All tests pass (≥ 16 passed).

- [ ] **Step C3.4: Commit**

```bash
git add quant-board/tests/test_quant_board.py
git commit -m "test: add Layer 1-2 and Layer 3 integration tests"
```

---

## Phase D-F Preview (not in this plan)

Phase D (Layer 4 optimization expansion) requires ≥ 60 trading days of data — estimated July 2026.
Phase E (P1 statistics/benchmarks) requires ≥ 50 trading days.
Phase F (P2 attribution/compliance) requires ≥ 70 trading days.

These will be implemented in a follow-up plan when the data threshold is met.
