# -*- coding: utf-8 -*-
"""regime/risk 核心线位扫描 harness 测试（方案 P3，P3-0 裁决收窄后 12+1 trial）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_regime_risk_thresholds import (
    ANCHOR_BASELINE,
    TRIALS,
    _assert_overrides_applied,
    _save,
    anchor_check,
    assert_regime_line_order,
    build_specs,
    regime_delta_of,
    run_window,
    strong_ban_ratio_of,
    trial_summary,
    validate_trials,
)


# ── ① trial 表完整性：3 轴 × 4 非默认档（默认档由 baseline 承担）──

def test_trial_table_size_and_axes():
    assert len(TRIALS) == 12
    axes = {next(iter(s["overrides"])) for s in TRIALS}
    assert axes == {"regimeStrongScore", "riskSynergyOverheatSevMin", "riskSynergyDivergenceSevMin"}


def test_strong_score_levels_exact():
    """regimeStrongScore 非默认档逐值断言（默认 70 由 baseline 承担）。"""
    pairs = {s["key"]: s["overrides"]["regimeStrongScore"] for s in TRIALS if "regimeStrongScore" in s["overrides"]}
    assert pairs == {"strong_60": 60.0, "strong_65": 65.0, "strong_75": 75.0, "strong_80": 80.0}


def test_overheat_sev_levels_exact():
    pairs = {
        s["key"]: s["overrides"]["riskSynergyOverheatSevMin"]
        for s in TRIALS
        if "riskSynergyOverheatSevMin" in s["overrides"]
    }
    assert pairs == {"overSev_045": 0.45, "overSev_055": 0.55, "overSev_075": 0.75, "overSev_085": 0.85}


def test_divergence_sev_levels_exact():
    pairs = {
        s["key"]: s["overrides"]["riskSynergyDivergenceSevMin"]
        for s in TRIALS
        if "riskSynergyDivergenceSevMin" in s["overrides"]
    }
    assert pairs == {"divSev_04": 0.4, "divSev_05": 0.5, "divSev_07": 0.7, "divSev_08": 0.8}


def test_default_levels_not_duplicated_in_table():
    values = [v for s in TRIALS for v in s["overrides"].values()]
    assert 70.0 not in values  # regimeStrongScore 默认档
    assert 0.65 not in values  # riskSynergyOverheatSevMin 默认档
    assert 0.6 not in values  # riskSynergyDivergenceSevMin 默认档


# ── ② 单变量拆分 ──

def test_single_variable_split():
    for spec in TRIALS:
        assert len(spec["overrides"]) == 1, f"{spec['key']} 违反单变量拆分: {spec['overrides']}"
    validate_trials()  # harness 侧同款预检（单变量 + 线序）


# ── ③ 线序预检断言生效（from_patch 对 regime 三线无校验，乱序静默退化）──

def test_line_order_precheck_rejects_out_of_order_strong():
    """StrongScore=45 < NormalScore=50：乱序 patch 必须被拒（harness 是唯一防线）。"""
    with pytest.raises(AssertionError, match="线序非法"):
        assert_regime_line_order({"regimeStrongScore": 45.0})


def test_line_order_precheck_rejects_tie():
    with pytest.raises(AssertionError, match="线序非法"):
        assert_regime_line_order({"regimeStrongScore": 50.0})  # == NormalScore，须严格 >
    with pytest.raises(AssertionError, match="线序非法"):
        assert_regime_line_order({"regimeStrongScore": 70.0, "regimeNormalScore": 70.0})  # 相切


def test_line_order_precheck_accepts_all_table_trials():
    for spec in TRIALS:
        order = assert_regime_line_order(spec["overrides"])
        assert order["strong"] > order["normal"] > order["weak"]


def test_from_patch_silently_accepts_out_of_order_lines():
    """现状锁定：from_patch 对 regime 三线零校验（乱序静默接受）——证明 harness 预检必要性。
    若未来 from_patch 补校验，本测试提示双层防线重叠（预检可保留）。"""
    cfg = RankTrendConfig.from_patch({"regimeStrongScore": 45.0})
    assert cfg.regimeStrongScore == 45.0


# ── ④ 锚常量（代际：post-fund10）──

def test_anchor_baseline_constant():
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}


# ── ⑤ override 生效守卫 ──

def test_assert_overrides_applied_rejects_unknown_field():
    ok = RankTrendConfig.from_patch({"regimeStrongScore": 62.5})
    _assert_overrides_applied(ok, {"regimeStrongScore": 62.5})
    bad = RankTrendConfig.from_patch({"regimeStrongScoreTypo": 62.5})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"regimeStrongScoreTypo": 62.5})


# ── ⑥ regimeView 四桶 / 禁入触发率统计函数（构造假 evaluate_gate 输出）──

def _gate_result(
    strong_sa,
    strong_n,
    normal_sa=0.10,
    weak_sa=0.08,
    retreat_sa=0.05,
    normal_n=100,
    weak_n=50,
    retreat_n=5,
    synergy_sa=None,
):
    view = {}
    counts = {}
    for state, sa, n in (
        ("strong", strong_sa, strong_n),
        ("normal", normal_sa, normal_n),
        ("weak", weak_sa, weak_n),
        ("retreat", retreat_sa, retreat_n),
    ):
        counts[state] = n
        if n > 0 and sa is not None:
            view[state] = {"saEx": sa, "passHard": True, "distribution": {"S": 1, "A": 1, "C": max(n - 2, 0)}}
    return {
        "regimeView": view,
        "regimeStateCounts": counts,
        "synergy": {"saEx": strong_sa if synergy_sa is None else synergy_sa, "passHard": True},
    }


def test_regime_delta_of_four_states():
    base = _gate_result(0.12, 100)
    trial = _gate_result(0.135, 230)
    delta = regime_delta_of(trial, base)
    assert set(delta) == {"strong", "normal", "weak", "retreat"}
    assert delta["strong"] == 0.015
    assert delta["normal"] == 0.0
    # 桶 saEx None / regimeView 缺失 → None（fail-visible，不伪造 0）
    trial_none = {"regimeView": {"strong": {"saEx": None}}}
    assert regime_delta_of(trial_none, base)["strong"] is None
    assert regime_delta_of({}, base) is None


def test_strong_ban_ratio_of():
    """禁入面监控：strong 桶样本量相对 baseline 比（放大/缩小双向可读）。"""
    base = _gate_result(0.12, 100)
    assert strong_ban_ratio_of(_gate_result(0.12, 230), base) == 2.3
    assert strong_ban_ratio_of(_gate_result(0.12, 53), base) == 0.53
    assert strong_ban_ratio_of(_gate_result(0.12, 100), base) == 1.0
    # fail-visible：缺计数 / baseline 0 桶 → None，不伪造 1.0
    assert strong_ban_ratio_of({"regimeStateCounts": {}}, base) is None
    assert strong_ban_ratio_of(_gate_result(0.12, 10), _gate_result(0.12, 0)) is None


def test_trial_summary_card_pass_candidate_with_regime_monitoring():
    report = {}
    # strong_sa 固定（regimeDelta strong 桶差 = 0）、synergy_sa 变动（判定卡口径）——两口径分离验证
    for win, base_syn, trial_syn in (("decision", 0.100, 0.104), ("oos1", 0.090, 0.092), ("oos2", 0.090, 0.091)):
        report[win] = {"trials": {
            "baseline": {"result": _gate_result(0.12, 100, synergy_sa=base_syn)},
            "t_x": {"result": _gate_result(0.12, 230, synergy_sa=trial_syn)},
        }}
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    win = summary["windows"]["decision"]
    assert set(win["regimeDelta"]) == {"strong", "normal", "weak", "retreat"}  # C4 四桶附加读数
    assert win["regimeDelta"]["strong"] == 0.0
    assert win["strongBanRatio"] == 2.3  # 禁入面随线移动（每 trial 必出）


def test_trial_summary_observe_when_flat():
    report = {}
    for win in ("decision", "oos1", "oos2"):
        report[win] = {"trials": {
            "baseline": {"result": _gate_result(0.100, 100)},
            "t_x": {"result": _gate_result(0.100, 100)},
        }}
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["cardResult"] == "OBSERVE"
    assert summary["verdictCard"]["C1_decisionRelGE3pct"] is False


def test_trial_summary_insufficient_data():
    assert trial_summary({}, {"key": "t_x"}) == {"verdict": "insufficient_data", "windows": {}}


def test_anchor_check_rounding():
    assert anchor_check("oos2", 0.09510, ANCHOR_BASELINE) == {
        "checked": True, "expected": 0.0951, "actual": 0.0951, "match": True,
    }
    assert anchor_check("oos2", None, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("oos2", 0.0951, None) == {"checked": False}


# ── ⑦ _save 剥离帧缓存 + windowsConsumed 标记 ──

def test_save_strips_frames_cache_and_marks_windows_consumed(tmp_path):
    report = {
        "__out__": str(tmp_path / "regime.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "regime.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["windowsConsumed"] is True
    assert saved["decision"]["window"]["frameCount"] == 1


# ── ⑧⑨ run_window mock：resume 冻结守卫 / extra-trial 执行 / 锚守卫 ──

def _mock_engine(monkeypatch, gate_payload):
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_regime_risk_thresholds.evaluate_gate",
        lambda config, frames: gate_payload,
    )


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """resume（已含 window 条目）路径仍必须执行 8 月冻结守卫。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_regime_risk_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_extra_trial_enters_specs_via_build_specs():
    specs = build_specs('{"key": "p3b_probe", "desc": "精扫注入", "overrides": {"regimeStrongScore": 62.5}}')
    keys = [s["key"] for s in specs]
    assert keys[0] == "baseline"
    assert len(keys) == 14  # 1 baseline + 12 内置 + 1 注入
    assert keys.count("p3b_probe") == 1
    for spec in specs:  # 注入 trial 同样过线序预检
        assert_regime_line_order(spec["overrides"])


def test_extra_trial_defaults_anchor_to_none():
    specs = build_specs('[{"key": "a", "overrides": {}}]')
    assert specs[-1]["anchor"] is None
    assert specs[0]["anchor"] == ANCHOR_BASELINE
    assert specs[0]["overrides"] == {}


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """--extra-trial 注入的 trial 必须真实执行（不只进 summary）。"""
    _mock_engine(monkeypatch, {"synergy": {"saEx": None, "passHard": False}})
    specs = [
        {"key": "baseline", "desc": "b", "overrides": {}, "anchor": None},
        {"key": "extra_probe", "desc": "extra", "overrides": {"riskSynergyOverheatSevMin": 0.5}, "anchor": None},
    ]
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "extra_probe" in trials
    assert trials["extra_probe"]["overrides"] == {"riskSynergyOverheatSevMin": 0.5}


def test_run_window_full_table_with_anchor_match(monkeypatch, tmp_path):
    """13+1 trial 全执行 + baseline 锚 match 路径 + anchor 读数随 trial 留痕。"""
    gate_payload = _gate_result(0.112, 100)
    gate_payload["synergy"] = {"saEx": 0.112, "passHard": True}  # decision 窗锚值
    _mock_engine(monkeypatch, gate_payload)
    specs = build_specs('{"key": "p3b_probe", "desc": "x", "overrides": {"regimeStrongScore": 62.5}}')
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert len(trials) == 14
    assert trials["baseline"]["anchor"]["match"] is True
    assert trials["strong_60"]["overrides"] == {"regimeStrongScore": 60.0}
    assert trials["p3b_probe"]["overrides"] == {"regimeStrongScore": 62.5}


def test_run_window_baseline_anchor_mismatch_stops(monkeypatch, tmp_path):
    """锚不复现即停（配置漂移）——漂移现场先落盘留痕再 raise。"""
    gate_payload = _gate_result(0.999, 100)
    gate_payload["synergy"] = {"saEx": 0.999, "passHard": True}
    _mock_engine(monkeypatch, gate_payload)
    report = {"__out__": str(tmp_path / "r.json")}
    with pytest.raises(AssertionError, match="配置漂移"):
        run_window("decision", report)
    saved = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    assert saved["decision"]["trials"]["baseline"]["anchor"]["match"] is False
