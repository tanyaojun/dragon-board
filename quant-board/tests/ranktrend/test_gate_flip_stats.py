from __future__ import annotations

from backend.analysis.ranktrend.research.gate_flip_stats import (
    count_gate_flips,
    extract_gate_states,
    top_flip_codes,
)


def _signal(veto: bool, bd: bool, regime: str) -> dict:
    reasons = ["周期 D 环境降档"] if bd else []
    action = "veto" if veto else "confirm"
    return {
        "rankTrend": {
            "cycle": {"decision": {"action": action, "reasons": []}},
            "observation": {"synergy": {"tierReasons": reasons}},
            "strategy": {"regime": {"state": regime, "reasons": []}},
        }
    }


def test_extract_gate_states_reads_three_sources():
    states = extract_gate_states(_signal(veto=True, bd=True, regime="strong"))
    assert states == {"veto": True, "bd_downgrade": True, "regime_state": "strong"}


def test_extract_gate_states_missing_fields_fail_visible():
    states = extract_gate_states({})
    assert states["veto"] is False
    assert states["bd_downgrade"] is False
    assert states["regime_state"] == ""           # 空串 = 缺失，由统计侧计入 missing


def test_extract_gate_states_suppression_reason_not_counted_as_downgrade():
    """跨计划协同：WP2 抑制文案不得被精确锚点误判为真实 B/D 降档。"""
    signal = {"rankTrend": {
        "cycle": {"decision": {"action": "confirm", "reasons": []}},
        "observation": {"synergy": {"tierReasons": ["周期 D 环境降档 单帧确认未达（1/2），暂缓"]}},
        "strategy": {"regime": {"state": "normal", "reasons": []}},
    }}
    assert extract_gate_states(signal)["bd_downgrade"] is False


def test_count_flips_counts_adjacent_changes():
    seq = [_signal(False, False, "normal"), _signal(True, False, "normal"),
           _signal(True, True, "weak"), _signal(False, True, "weak")]
    result = count_gate_flips(
        {"000001": [extract_gate_states(sig) for sig in seq]},
        ["normal", "normal", "weak", "weak"],            # 市场级 regime 序列（与帧一一对应）
    )
    assert result["comparable_pairs"] == 3
    assert result["flip_counts"]["veto"] == 2            # F→T、T→F
    assert result["flip_counts"]["bd_downgrade"] == 1    # F→T
    assert result["flip_counts"]["regime_state"] == 1    # normal→weak（市场级，不按 code 重复计数）
    assert result["flip_rates"]["veto"] == 2 / 3


def test_count_flips_missing_field_pair_not_comparable():
    seq = [_signal(False, False, "normal"),
           {"rankTrend": {"cycle": {"decision": {"action": "confirm", "reasons": []}}}}]  # 无 strategy.regime
    result = count_gate_flips({"000001": [extract_gate_states(sig) for sig in seq]}, [])
    assert result["comparable_pairs"] == 0
    assert result["missing_fields"] == 1                 # regime_state 缺失的对


def test_count_flips_regime_market_level_series():
    result = count_gate_flips({}, ["strong", "strong", "normal", "normal", "weak"])
    assert result["flip_counts"]["regime_state"] == 2
    assert result["comparable_pairs"] == 4


def test_top_flip_codes_sorted_desc():
    per_code = {"a": {"veto": 3, "bd_downgrade": 0, "regime_state": 0},
                "b": {"veto": 5, "bd_downgrade": 1, "regime_state": 0},
                "c": {"veto": 1, "bd_downgrade": 2, "regime_state": 0}}
    assert top_flip_codes(per_code, "veto", n=2) == [("b", 5), ("a", 3)]
