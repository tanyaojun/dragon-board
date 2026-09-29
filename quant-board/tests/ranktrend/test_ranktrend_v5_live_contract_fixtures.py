from __future__ import annotations

import json
from pathlib import Path

from backend.core.backtest.execution import TradeSimulator


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ranktrend_v5_live_execution_contract.json"


def _load_fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_ranktrend_v5_fixture_default_min_jump_confidence_matches_python_contract() -> None:
    fixture = _load_fixture()

    assert fixture["defaultMinJumpConfidence"] == 90


def test_ranktrend_v5_fixture_uses_same_execution_tier_for_python_and_ts_live_gate() -> None:
    fixture = _load_fixture()

    for case in fixture["cases"]:
        signal = case["signal"]
        execution_tier = signal["rankTrend"]["executionStrategy"]["candidateTier"]

        assert signal["candidateTier"] == execution_tier, case["name"]


def test_ranktrend_v5_fixture_keeps_display_tier_separate_when_lifecycle_vetoes() -> None:
    fixture = _load_fixture()
    veto_case = next(
        case for case in fixture["cases"]
        if case["name"] == "lifecycle_veto_rejected_even_when_ranktrend_is_strong"
    )
    signal = veto_case["signal"]

    assert signal["rankTrend"]["strategy"]["candidateTier"] == "A_MAIN"
    assert signal["rankTrend"]["executionStrategy"]["candidateTier"] == "N_NEUTRAL"
    assert signal["candidateTier"] == "N_NEUTRAL"


def test_ranktrend_v5_python_entry_contract_matches_shared_live_fixture() -> None:
    fixture = _load_fixture()
    min_jump_confidence = float(fixture["defaultMinJumpConfidence"])

    for case in fixture["cases"]:
        accepted = TradeSimulator._is_early_big_move_v3_lifecycle_fusion_entry_signal(
            case["signal"],
            min_jump_confidence,
        )

        assert accepted is bool(case["expectedEntry"]), case["name"]
