# -*- coding: utf-8 -*-
"""vp 成交额量比三参数扫描 harness 测试（参数缺口补扫方案 P4，TDD 锁定）。

覆盖：trial 表完整性 / 单变量拆分 / 锚代际 / override 生效守卫 / _save 剥离帧缓存 /
resume 冻结守卫 / extra-trial 注入 / P4-0 诊断口径 / volumePrice focus 维 / 判定卡。
全 mock / 小数据，不触 MongoDB。
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_vp_amount_ratio import (
    AMOUNT_RATIO_AXIS_LEVELS,
    AMOUNT_RATIO_TRIALS,
    ANCHOR_BASELINE,
    TRIGGER_RATE_FLAG,
    _assert_overrides_applied,
    _save,
    amount_ratio_diagnostic,
    anchor_check,
    build_specs,
    run_window,
    trial_summary,
    trigger_rate_of,
)

_DIAG_CONFIG = SimpleNamespace(amountRatioPeriod=5.0, amountRatioHigh=1.5, amountRatioLow=0.5)


# ── trial 表完整性（方案 P4-a：3 轴 × 各 4 非默认档，默认档由 baseline 承担）──


def test_config_defaults_match_scan_center():
    """消费点默认核对：档位表以 config 默认值为中心（5/1.5/0.5）。"""
    config = RankTrendConfig()
    assert float(config.amountRatioPeriod) == 5.0
    assert float(config.amountRatioHigh) == 1.5
    assert float(config.amountRatioLow) == 0.5


def test_trial_table_completeness():
    """3 轴 × 各 4 非默认档共 12 trial，键名与档位值逐个断言。"""
    assert AMOUNT_RATIO_AXIS_LEVELS == {
        "amountRatioPeriod": [2.0, 3.0, 8.0, 13.0],
        "amountRatioHigh": [1.1, 1.3, 2.0, 2.5],
        "amountRatioLow": [0.2, 0.35, 0.65, 0.8],
    }
    assert len(AMOUNT_RATIO_TRIALS) == 12
    expected = {
        "arPeriod_2": {"amountRatioPeriod": 2.0},
        "arPeriod_3": {"amountRatioPeriod": 3.0},
        "arPeriod_8": {"amountRatioPeriod": 8.0},
        "arPeriod_13": {"amountRatioPeriod": 13.0},
        "arHigh_11": {"amountRatioHigh": 1.1},
        "arHigh_13": {"amountRatioHigh": 1.3},
        "arHigh_20": {"amountRatioHigh": 2.0},
        "arHigh_25": {"amountRatioHigh": 2.5},
        "arLow_02": {"amountRatioLow": 0.2},
        "arLow_035": {"amountRatioLow": 0.35},
        "arLow_065": {"amountRatioLow": 0.65},
        "arLow_08": {"amountRatioLow": 0.8},
    }
    assert [spec["key"] for spec in AMOUNT_RATIO_TRIALS] == list(expected)
    for spec in AMOUNT_RATIO_TRIALS:
        assert spec["overrides"] == expected[spec["key"]]


def test_single_variable_trials_change_only_own_axis():
    """单变量拆分：每个 trial 只动自己轴的一个字段，且不等于默认值（默认由 baseline 承担）。"""
    defaults = {"amountRatioPeriod": 5.0, "amountRatioHigh": 1.5, "amountRatioLow": 0.5}
    seen: set[str] = set()
    for spec in AMOUNT_RATIO_TRIALS:
        overrides = spec["overrides"]
        assert len(overrides) == 1, f"{spec['key']} 打包了多字段：{overrides}"
        axis, value = next(iter(overrides.items()))
        assert axis in AMOUNT_RATIO_AXIS_LEVELS, f"{spec['key']} 字段 {axis} 不在三轴内"
        assert value in AMOUNT_RATIO_AXIS_LEVELS[axis], f"{spec['key']} 档位 {value} 不在表内"
        assert value != defaults[axis], f"{spec['key']} 与默认档重复（默认档应由 baseline 承担）"
        assert spec["key"] not in seen
        seen.add(spec["key"])


# ── 锚代际与判定口径 ──


def test_baseline_anchor_constant():
    """锚代际：post-fund10 基线锚（2026-09-15 代际，主代理实测 oos2=0.0951 逐位复现）。"""
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}


def test_anchor_check_round4_match():
    assert anchor_check("oos2", 0.0951, ANCHOR_BASELINE) == {
        "checked": True, "expected": 0.0951, "actual": 0.0951, "match": True,
    }
    assert anchor_check("oos2", 0.095, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("oos2", None, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("oos2", 0.1, None) == {"checked": False}


def test_trigger_rate_flag_line():
    assert TRIGGER_RATE_FLAG == 0.035  # S+A 触发率旗标（同范式，阶段 22.6 观察线）


def test_trigger_rate_of():
    result = {"synergy": {"distribution": {"S": 3, "A": 4, "C": 93}}}
    assert trigger_rate_of(result) == 0.07


# ── override 生效守卫（from_patch 对未知字段静默忽略，防假绿）──


def test_assert_overrides_applied_rejects_unknown_field():
    ok = RankTrendConfig.from_patch({"amountRatioHigh": 2.0})
    _assert_overrides_applied(ok, {"amountRatioHigh": 2.0})
    bad = RankTrendConfig.from_patch({"amountRatioHighTypo": 2.0})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"amountRatioHighTypo": 2.0})


# ── _save 剥离帧缓存 + windowsConsumed 标记 ──


def test_save_strips_frames_cache(tmp_path):
    """__frames__ 全量帧缓存与 __out__ 不得落盘；OOS-2 消费标记 windowsConsumed=True。"""
    report = {
        "__out__": str(tmp_path / "vp.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "vp.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["windowsConsumed"] is True
    assert saved["decision"]["window"]["frameCount"] == 1


# ── mock 依赖（不触 MongoDB / 真引擎）──


def _patch_run_window_mocks(monkeypatch, signals=None, gate_result=None):
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04", "snapshotId": "s1", "stocks": []}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: signals if signals is not None else []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_vp_amount_ratio.evaluate_gate",
        lambda config, frames: gate_result or {"synergy": {"saEx": None, "passHard": False}},
    )


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """resume（已含 window 条目）路径仍必须执行 8 月冻结守卫。"""
    _patch_run_window_mocks(monkeypatch)
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """--extra-trial 注入的 trial 必须真实进执行循环（第二轮精扫补跑）。"""
    _patch_run_window_mocks(monkeypatch, gate_result={"synergy": {"saEx": 0.112, "passHard": True}})
    specs = build_specs(json.dumps({"key": "extra_probe", "desc": "extra", "overrides": {"amountRatioPeriod": 6.0}}))
    assert specs[-1]["key"] == "extra_probe" and specs[-1]["anchor"] is None
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "extra_probe" in trials
    assert trials["extra_probe"]["overrides"] == {"amountRatioPeriod": 6.0}


def test_build_specs_baseline_carries_anchor():
    specs = build_specs()
    assert len(specs) == 13
    assert specs[0]["key"] == "baseline"
    assert specs[0]["overrides"] == {}
    assert specs[0]["anchor"] == ANCHOR_BASELINE
    assert all(spec.get("anchor") is None for spec in specs[1:])


def test_anchor_mismatch_raises_and_saves(monkeypatch, tmp_path):
    """baseline 锚不复现（配置漂移）→ 立即 raise，且报告先落盘留痕。"""
    _patch_run_window_mocks(
        monkeypatch,
        gate_result={"synergy": {"saEx": 0.5, "passHard": True}},
    )
    report = {"__out__": str(tmp_path / "r.json")}
    with pytest.raises(AssertionError, match="配置漂移"):
        run_window("decision", report, specs=[{"key": "baseline", "desc": "b", "overrides": {}, "anchor": ANCHOR_BASELINE}])
    saved = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    check = saved["decision"]["anchorChecks"]["decision"]
    assert check["match"] is False and check["expected"] == 0.112 and check["actual"] == 0.5


def test_anchor_match_passes_and_records(monkeypatch, tmp_path):
    """baseline 锚逐位复现 → 通过并写 anchorChecks 留痕；trial 表整表执行。"""
    _patch_run_window_mocks(
        monkeypatch,
        gate_result={"synergy": {"saEx": 0.112, "passHard": True}},
    )
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report)
    trials = report["decision"]["trials"]
    assert len(trials) == 13
    check = report["decision"]["anchorChecks"]["decision"]
    assert check["match"] is True


def test_run_window_writes_volume_price_and_diagnostic(monkeypatch, tmp_path):
    """focus 维 volumePrice 独立统计出 saEx；P4-0 诊断随 baseline 留痕（fail-visible）。"""
    _patch_run_window_mocks(
        monkeypatch,
        signals=[{"code": "000001", "snapshotId": "s1", "rankTrend": {"observation": {"amountRatio": 1.6}}}],
    )
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=[{"key": "baseline", "desc": "b", "overrides": {}, "anchor": None}])
    result = report["decision"]["trials"]["baseline"]["result"]
    # 帧边界不足（无未来帧）→ vp saEx=None 如实输出，不伪造 0
    assert result["volumePrice"]["saEx"] is None
    diag = report["decision"]["amountRatioDiagnostic"]
    assert diag["total"] == 1
    assert diag["computable"] == 1
    assert diag["computableRate"] == 1.0
    assert diag["lowLeverage"] is False


# ── P4-0 诊断口径 ──


def test_amount_ratio_diagnostic_counts():
    """可算率 = 非 None/非 NaN 占比；增强生效分母为可算样本（High/Low 阈值命中）。"""
    signals = [
        {"rankTrend": {"observation": {"amountRatio": 1.6}}},   # 放量加分生效
        {"rankTrend": {"observation": {"amountRatio": 0.4}}},   # 缩量减分生效
        {"rankTrend": {"observation": {"amountRatio": None}}},  # 历史缺失
        {"rankTrend": {"observation": {"amountRatio": float("nan")}}},
    ]
    diag = amount_ratio_diagnostic(signals, _DIAG_CONFIG)
    assert diag["total"] == 4
    assert diag["computable"] == 2
    assert diag["computableRate"] == 0.5
    assert diag["effective"] == 2
    assert diag["effectiveRate"] == 1.0
    assert diag["lowLeverage"] is False
    assert "低杠杆" not in (diag["note"] or "")


def test_amount_ratio_diagnostic_low_leverage_flag():
    signals = [{"rankTrend": {"observation": {"amountRatio": 1.0}}}] + [
        {"rankTrend": {"observation": {"amountRatio": None}}} for _ in range(3)
    ]
    diag = amount_ratio_diagnostic(signals, _DIAG_CONFIG)
    assert diag["computableRate"] == 0.25
    assert diag["lowLeverage"] is True
    assert "低杠杆" in diag["note"]


def test_amount_ratio_diagnostic_empty_signals_fail_visible():
    """空 signals → 可算率 None（不伪造 0），lowLeverage 不判定。"""
    diag = amount_ratio_diagnostic([], _DIAG_CONFIG)
    assert diag["total"] == 0
    assert diag["computableRate"] is None
    assert diag["effectiveRate"] is None
    assert diag["lowLeverage"] is None


def test_amount_ratio_diagnostic_thresholds_from_config():
    diag = amount_ratio_diagnostic([], SimpleNamespace(amountRatioPeriod=8.0, amountRatioHigh=2.0, amountRatioLow=0.65))
    assert diag["thresholds"] == {"amountRatioPeriod": 8.0, "amountRatioHigh": 2.0, "amountRatioLow": 0.65}


# ── trial_summary：判定卡 + 触发率漂移 + volumePrice 附加读数 + regimeDelta 四桶 ──


def _report_with(card_cases: dict[str, tuple[float, float]]) -> dict:
    """三窗 report 骨架：{win: (baseline_saEx, trial_saEx)}。"""
    report: dict = {}
    for win, (base_sa, trial_sa) in card_cases.items():
        report[win] = {"trials": {
            "baseline": {"result": {"synergy": {"saEx": base_sa, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": trial_sa, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }}
    return report


def test_trial_summary_card_pass_candidate():
    report = _report_with({"decision": (0.10, 0.104), "oos1": (0.05, 0.052), "oos2": (0.05, 0.049)})
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"


def test_trial_summary_card_observe_when_c1_miss():
    report = _report_with({"decision": (0.10, 0.102), "oos1": (0.05, 0.051), "oos2": (0.05, 0.05)})
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"]["C1_decisionRelGE3pct"] is False
    assert summary["cardResult"] == "OBSERVE"


def test_trial_summary_includes_vp_dimension_and_regime_delta():
    report = _report_with({"decision": (0.10, 0.104), "oos1": (0.05, 0.05), "oos2": (0.05, 0.05)})
    for win in report:
        for key in ("baseline", "t_x"):
            sa = 0.2 if key == "baseline" else 0.21
            report[win]["trials"][key]["result"]["volumePrice"] = {"saEx": sa, "passHard": True}
    report["decision"]["trials"]["baseline"]["result"]["regimeView"] = {
        "strong": {"saEx": 0.3}, "normal": {"saEx": 0.1},
    }
    report["decision"]["trials"]["t_x"]["result"]["regimeView"] = {
        "strong": {"saEx": 0.29}, "normal": {"saEx": 0.1},
    }
    summary = trial_summary(report, {"key": "t_x"})
    # 两维 saEx 都出
    assert summary["windows"]["decision"]["saEx"] == 0.104
    assert summary["windows"]["decision"]["vpSaEx"] == 0.21
    assert summary["windows"]["decision"]["vpSaExRel"] == 0.05
    # regimeDelta 四桶附加读数（缺桶如实 None）
    assert summary["windows"]["decision"]["regimeDelta"] == {"strong": -0.01, "normal": 0.0}
