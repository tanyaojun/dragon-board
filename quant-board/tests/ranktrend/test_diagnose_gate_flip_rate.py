from __future__ import annotations

from backend.operations.diagnose_gate_flip_rate import collect_flip_report


def _signal(code: str, sid: str, slot: str, action: str, regime: str, bd: bool = False) -> dict:
    """replay 产物真实形状：顶层 code/snapshotId/slotTime + decision.action（无 veto 布尔键）。"""
    reasons = ["周期 D 环境降档"] if bd else []
    return {
        "code": code, "snapshotId": sid, "tradingDate": "2026-06-05", "slotTime": slot,
        "rankTrend": {
            "cycle": {"decision": {"action": action, "reasons": []}},
            "observation": {"synergy": {"tierReasons": reasons}},
            "strategy": {"regime": {"state": regime, "reasons": []}},
        },
    }


def test_collect_flip_report_groups_by_code_and_dedupes_regime():
    # 2 帧 × 2 股 = 4 条信号（replay 真实形状：每帧每股一条）
    signals = [
        _signal("000001", "s1", "10:00", "confirm", "normal"),
        _signal("000002", "s1", "10:00", "confirm", "normal"),
        _signal("000001", "s2", "14:30", "veto", "weak"),
        _signal("000002", "s2", "14:30", "confirm", "weak"),
    ]
    report = collect_flip_report(signals)
    assert report["signal_count"] == 4
    assert report["frame_count"] == 2                    # regime 按 snapshotId 去重
    assert report["code_count"] == 2
    assert report["flip_counts"]["veto"] == 1            # 仅 000001 第二帧 veto
    assert report["flip_counts"]["regime_state"] == 1    # 市场级 normal→weak 只计一次
    assert set(report["stage_flip_rates"].keys()) == {"morning", "late"}


def test_collect_flip_report_empty_inputs_fail_visible():
    report = collect_flip_report([])
    assert report["frame_count"] == 0 and report["code_count"] == 0 and report["signal_count"] == 0
    assert report["flip_rates"] == {"veto": 0.0, "bd_downgrade": 0.0, "regime_state": 0.0}
