# RankTrend Early Big Move Long-Test Baselines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace retired lifecycle H1/H2/Q1 long-test baselines with three `early_big_move_v1` baselines driven by the new early big-move structure.

**Architecture:** Keep the change inside QuantBoard. Register a new `ranktrend_early_big_move` research strategy, route `run-longtest-baselines --baseline-set early_big_move_v1` to three new half-hour baselines, and preserve old H1/H2/Q1 only as retired history. Clear only the local JSONL checkpoint record file after the new CLI contract is in place.

**Tech Stack:** Python, pytest, QuantBoard CLI, existing `BacktestService` and `TradeSimulator`.

---

## Files

- Modify: `quant-board/backend/core/backtest/strategy.py`
  - Register `ranktrend_early_big_move`.
- Modify: `quant-board/backend/core/backtest/execution.py`
  - Add early-big-move candidate detection and score sorting.
- Modify: `quant-board/backend/cli.py`
  - Add `--baseline-set`, build `early_big_move_v1` baseline payloads, and keep old lifecycle set available only when explicitly selected.
- Modify: `quant-board/tests/test_quant_board.py`
  - Add CLI dry-run tests for the new baseline set.
- Modify: `quant-board/tests/test_trade_simulator_round_trips.py`
  - Add strategy entry tests showing `final=hold` can still enter when early-big-move rules pass.
- Modify: `quant-board/docs/optimization-long-task/task_plan.md`
  - Mark old H1/H2/Q1 as retired and point to the new baseline set.
- Modify: `quant-board/docs/optimization-long-task/findings.md`
  - Record the retirement decision and new baseline contract.
- Modify: `quant-board/docs/optimization-long-task/progress.md`
  - Log the new phase and cleanup.
- Clear: `quant-board/data/reports/long_test_runs.jsonl`
  - Remove old local H1/H2/Q1 JSONL run records after implementation.

## Task 1: CLI Baseline Set Contract

- [ ] Add a failing test in `quant-board/tests/test_quant_board.py` that runs:

```python
main([
    "run-longtest-baselines",
    "--checkpoint-id",
    "checkpoint_early_big_move_dry",
    "--baseline-set",
    "early_big_move_v1",
    "--dry-run",
])
```

Expected labels:

```python
[
    "E1_half_hour_signal_forward40",
    "E2_half_hour_ranked_current_bar",
    "E3_half_hour_ranked_strict_fill",
]
```

Expected strategy in every payload:

```python
"ranktrend_early_big_move"
```

- [ ] Run the targeted test and confirm it fails because `--baseline-set` is not accepted.
- [ ] Implement `--baseline-set` in `quant-board/backend/cli.py`.
- [ ] Add `EARLY_BIG_MOVE_BASELINES` and make it the default baseline set.
- [ ] Keep `legacy_lifecycle_v1` available for explicit historical reruns.
- [ ] Run the targeted test and confirm it passes.

## Task 2: Strategy Registration

- [ ] Add a failing test in `quant-board/tests/test_quant_board.py` that `normalize_strategy_name("ranktrend_early_big_move")` returns the same string.
- [ ] Run the targeted test and confirm it fails as unsupported.
- [ ] Add `ranktrend_early_big_move` to research strategy definitions and registry in `quant-board/backend/core/backtest/strategy.py`.
- [ ] Run the targeted test and confirm it passes.

## Task 3: Early Big Move Entry Rules

- [ ] Add a failing test in `quant-board/tests/test_trade_simulator_round_trips.py` using a synthetic signal with:

```python
{
    "code": "002552",
    "candidateTier": "N_NEUTRAL",
    "stage": "ignition",
    "change": 6.2,
    "rankTrend": {
        "jump": {"event": "jump", "direction": "buy", "confidence": 94.2},
        "technical": {
            "signals": {
                "short": {"value": 18.7},
                "mid": {"value": 12.8},
                "long": {"value": 14.3},
                "acceleration": {"value": 27.2},
                "direction": {"signal": "hold"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "hold"},
        },
        "decision": {"final": {"signal": "hold"}},
    },
}
```

Expected: `_entry_candidates(..., "ranktrend_early_big_move")` includes the signal.

- [ ] Run the targeted test and confirm it fails because no early-big-move entry logic exists.
- [ ] Implement `_is_early_big_move_entry_signal()` in `execution.py`.
- [ ] Implement `_early_big_move_score()` in `execution.py` and sort early candidates by score.
- [ ] Ensure `finalSignal`, `direction`, and `zeroCross/MACD` are not hard filters.
- [ ] Run the targeted test and confirm it passes.

## Task 4: Long-Test Summary Compatibility

- [ ] Add a failing dry-run assertion that `E1` has `tradeSimulation.enabled == False` or equivalent no-trade payload.
- [ ] Add a failing dry-run assertion that `E3` has strict execution flags:

```python
{
    "useOrderBookPrice": True,
    "enforceLimitStatus": True,
    "enforceVolumeLimit": True,
    "enforceOrderBookQueue": True,
}
```

- [ ] Implement the payload overrides in `build_longtest_baseline_payloads()`.
- [ ] Run targeted CLI tests and confirm they pass.

## Task 5: Documentation And Cleanup

- [ ] Update `quant-board/docs/optimization-long-task/task_plan.md` with Phase 21: old lifecycle baselines retired and new early-big-move baselines active.
- [ ] Update `quant-board/docs/optimization-long-task/findings.md` with the new baseline table.
- [ ] Update `quant-board/docs/optimization-long-task/progress.md` with this session.
- [ ] Clear `quant-board/data/reports/long_test_runs.jsonl` so old local H1/H2/Q1 JSONL records are removed.
- [ ] Run `git diff --stat` and inspect only touched files.

## Task 6: Verification

- [ ] Run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m pytest tests/test_quant_board.py tests/test_trade_simulator_round_trips.py -q
```

- [ ] Run dry-run:

```powershell
cd quant-board
.\.venv\Scripts\python.exe -m backend.cli run-longtest-baselines --baseline-set early_big_move_v1 --checkpoint-id checkpoint_early_big_move_v1_dry --dry-run
```

- [ ] Confirm output contains the three new labels and no `H1/H2/Q1` labels.
