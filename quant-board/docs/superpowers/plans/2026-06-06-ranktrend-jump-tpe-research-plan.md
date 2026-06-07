# RankTrend Jump TPE Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a lightweight, reproducible RankTrend Jump research runner that can TPE-search continuous `jumpDeltaPct`, validate with walk-forward splits, and report execution realism diagnostics without enabling auto trading.

**Architecture:** Keep the feature inside QuantBoard. Reuse the existing Python RankTrend engine and `TradeSimulator` for T+1, 40 bars, equity curve, limit status, order book pricing, and liquidity checks. Add only small adapters for Jump entry/exit signals, continuous range search specs, and Chinese research summaries.

**Tech Stack:** Python, pytest, Optuna TPESampler through the existing optimization package, QuantBoard backend modules.

---

## Scope

In scope:

- Continuous TPE search for `jumpDeltaPct` using range specs such as `{"type": "float", "low": 8, "high": 22}`.
- Jump-specific research objective that values realized return, win rate, drawdown control, trade count suitability, and execution quality.
- Walk-forward validation over chronological frame splits.
- `delta=15` treated as one candidate/reference, not a default written back to TS/Python config.
- Fill fallback modes:
  - `strict_fill`: require order book price and liquidity constraints.
  - `fallback_penalized`: allow snapshot price fallback with extra slippage and explicit warning.
  - `blocked_fill`: block order book fallback by requiring buy-side/sell-side quote fields.
- Chinese summary suitable for实盘验证复盘.

Out of scope:

- Auto order placement.
- Changing Dragon Board root frontend.
- Writing optimized parameters back to defaults.
- Large UI/report redesign.

## Files

- Create: `quant-board/backend/analysis/ranktrend_jump_research.py`
  - Owns Jump signal projection, execution mode presets, objective scoring, TPE runner, walk-forward aggregation, and Chinese summary.
- Modify: `quant-board/backend/optimization/search_space.py`
  - Add compact support for continuous float/int range specs while preserving existing list/choice behavior.
- Modify: `quant-board/backend/core/backtest/strategy.py`
  - Register lightweight `ranktrend_jump` strategy key for simulator compatibility.
- Modify: `quant-board/backend/core/backtest/execution.py`
  - Add Jump entry/exit candidate behavior behind `strategy_key == "ranktrend_jump"` only.
- Modify: `quant-board/backend/services.py`
  - Add a service method to run Jump research from a dataset.
- Modify: `quant-board/backend/main.py`
  - Add a small API endpoint for research reruns.
- Modify: `quant-board/backend/cli.py`
  - Add a CLI command for local reruns.
- Test: `quant-board/tests/test_ranktrend_jump_research.py`
  - Cover continuous search specs, fill fallback diagnostics, objective scoring, and TPE/walk-forward output shape.
- Modify docs: `quant-board/docs/superpowers/specs/2026-06-06-ranktrend-jump-detection-evolution.md`
  - Record the new rerun口径 and risk interpretation.

## Tasks

### Task 1: Continuous Search Specs

- [ ] Add failing tests for float/int range specs.
- [ ] Run targeted pytest and verify failure.
- [ ] Implement normalized range specs without breaking list search.
- [ ] Run targeted pytest and verify pass.

### Task 2: Jump Signal Strategy

- [ ] Add tests for `ranktrend_jump` entry/exit behavior using synthetic signals.
- [ ] Verify tests fail because strategy is not registered.
- [ ] Register `ranktrend_jump` and map existing Jump entry/exit rules into simulator candidate/exit paths.
- [ ] Run targeted simulator tests.

### Task 3: Research Runner

- [ ] Add tests for fill modes, objective score, and summary fields.
- [ ] Verify tests fail because module/API is absent.
- [ ] Implement `run_ranktrend_jump_research()` using existing RankTrend replay and `TradeSimulator`.
- [ ] Run targeted research tests.

### Task 4: API/CLI

- [ ] Add tests that parser accepts `research-ranktrend-jump` and endpoint returns reproducible metadata.
- [ ] Implement small service/API/CLI wrappers.
- [ ] Run targeted API/CLI tests.

### Task 5: Verification And Docs

- [ ] Run `.\.venv\Scripts\python.exe -m pytest tests/test_ranktrend_jump_research.py -q`.
- [ ] Run relevant existing QuantBoard tests touched by optimization/backtest.
- [ ] Update the evolution spec with exact execution口径, warnings, and next validation risk.
- [ ] Inspect `git diff` to ensure no unrelated files were changed.

## Success Criteria

- `jumpDeltaPct` can be searched continuously by TPE and retains fixed `random_seed`/`config_hash` metadata.
- Results include train/test or walk-forward diagnostics, not only in-sample best trial.
- Execution uses current-bar signal execution, A股 T+1 exit restriction, max holding 40 bars, realistic equity curve, limit status, order book/liquidity checks, and explicit fallback diagnostics.
- Chinese summary states whether results are suitable only for observation, paper/live validation, or too dependent on fallbacks.
