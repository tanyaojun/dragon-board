# -*- coding: utf-8 -*-
"""cs 档位定义阈值扫描 harness 测试（参数补扫方案 P1-a，9 轴 × 4 非默认档）。

断言面（任务硬要求）：
① trial 表完整性（9 轴 × 4 档逐值，含 StrongAbsMin 轴）；
② 单变量拆分（每 trial 只动自己轴）；
③ ANCHOR_BASELINE 常量（post-fund10 锚）；
④ _assert_overrides_applied 拒未知字段；
⑤ cs 档位分布统计函数（构造假 replay 输出验证 A/B/C/D/unknown 计数）；
⑥ _save 剥离 __frames__/__out__；
⑦ resume 仍执行冻结守卫；
⑧ --extra-trial 注入 trial 进执行循环。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.trend.cross_section import CROSS_SECTION_DEFAULTS
from backend.operations.evaluate_cs_tier_thresholds import (
    ANCHOR_BASELINE,
    AXIS_LEVELS,
    C5_FLIP_RISE_FLAG,
    CS_TRIALS,
    MONITOR_REFERENCES,
    TRIGGER_RATE_FLAG,
    _assert_overrides_applied,
    _save,
    anchor_check,
    cs_tier_distribution_of,
    run_window,
    trial_summary,
)

EXPECTED_AXIS_LEVELS: dict[str, list[float]] = {
    "crossSectionStrongMin": [80.0, 82.5, 87.5, 90.0],
    "crossSectionStrongDeltaUp": [3.0, 4.0, 6.0, 8.0],
    "crossSectionMidMin": [40.0, 45.0, 55.0, 60.0],
    "crossSectionMidDeltaUp": [10.0, 12.0, 20.0, 25.0],
    "crossSectionMidMax": [40.0, 45.0, 55.0, 60.0],
    "crossSectionMidDeltaDown": [-10.0, -12.0, -20.0, -25.0],
    "crossSectionWeakMax": [10.0, 12.5, 17.5, 20.0],
    "crossSectionWeakDeltaDown": [-3.0, -4.0, -6.0, -8.0],
    "crossSectionStrongAbsMin": [60.0, 65.0, 75.0, 80.0],
}


def test_trial_table_complete_9_axes_x4_levels():
    """① 9 轴 × 4 非默认档逐值断言（默认档由 baseline 承担，不得混入 trial 表）。"""
    assert AXIS_LEVELS == EXPECTED_AXIS_LEVELS  # 档位锁值（含 StrongAbsMin 新参数化轴）
    assert len(CS_TRIALS) == 36
    assert {s["axis"] for s in CS_TRIALS} == set(EXPECTED_AXIS_LEVELS)
    for spec in CS_TRIALS:
        assert RankTrendConfig.from_patch(spec["overrides"]) is not None
    for axis, levels in EXPECTED_AXIS_LEVELS.items():
        specs = [s for s in CS_TRIALS if s["axis"] == axis]
        assert len(specs) == 4, f"{axis} 非默认档位数 != 4"
        assert sorted(s["value"] for s in specs) == sorted(levels), f"{axis} 档位值不符"
        keys = [s["key"] for s in specs]
        assert len(set(keys)) == 4, f"{axis} trial 键重复"
        default = CROSS_SECTION_DEFAULTS[axis]
        assert default not in levels, f"{axis} 默认档 {default} 混入 trial 表（应由 baseline 承担）"


def test_all_axes_are_real_config_fields():
    """9 轴全部是 RankTrendConfig 真实字段（防字段名/拼错漂移）。"""
    for axis in EXPECTED_AXIS_LEVELS:
        assert hasattr(RankTrendConfig(), axis), f"{axis} 不是 config 字段"
        assert float(getattr(RankTrendConfig(), axis)) == float(CROSS_SECTION_DEFAULTS[axis])


def test_single_variable_split():
    """② 单变量拆分：每 trial overrides 恰一个键且等于自己的 axis，值等于自己的 value。"""
    keys = [s["key"] for s in CS_TRIALS]
    assert len(set(keys)) == 36
    for spec in CS_TRIALS:
        assert list(spec["overrides"].keys()) == [spec["axis"]], f"{spec['key']} 打包了多个参数"
        assert spec["overrides"][spec["axis"]] == spec["value"]
        assert spec["value"] != float(CROSS_SECTION_DEFAULTS[spec["axis"]])


def test_baseline_anchor_constant():
    """③ 锚代际：post-fund10 基线锚（2026-09-15 fund10 落默认后实测，oos2 已复核）。"""
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}


def test_assert_overrides_applied_rejects_unknown_field():
    """④ from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"crossSectionStrongMin": 82.5})
    _assert_overrides_applied(ok, {"crossSectionStrongMin": 82.5})
    bad = RankTrendConfig.from_patch({"crossSectionStrongMinTypo": 82.5})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"crossSectionStrongMinTypo": 82.5})


def _mk_signal(tier) -> dict:
    return {"rankTrend": {"observation": {"crossSection": {"signalTier": tier}}}}


def test_cs_tier_distribution_counts():
    """⑤ 档位分布统计：A/B/C/D 正确计数；缺 observation / 非法档位 / None → unknown。"""
    signals = [
        _mk_signal("A"),
        _mk_signal("A"),
        _mk_signal("B"),
        _mk_signal("C"),
        _mk_signal("D"),
        _mk_signal("unknown"),
        _mk_signal(None),
        _mk_signal("X"),  # 非法档位
        {"rankTrend": {}},  # 缺 observation
        {},  # 缺 rankTrend
    ]
    dist = cs_tier_distribution_of(signals)
    assert dist["counts"] == {"A": 2, "B": 1, "C": 1, "D": 1, "unknown": 5}
    assert dist["total"] == 10
    assert dist["aSampleCount"] == 2
    assert dist["cShare"] == round(1 / 10, 4)
    assert dist["shares"]["A"] == 0.2
    assert dist["shares"]["unknown"] == 0.5


def test_cs_tier_distribution_empty_is_fail_visible():
    """空 replay 输出：total=0、占比 None（fail-visible，不伪造 0 占比）。"""
    dist = cs_tier_distribution_of([])
    assert dist["total"] == 0
    assert dist["aSampleCount"] == 0
    assert dist["cShare"] is None
    assert all(v is None for v in dist["shares"].values())


def test_save_strips_frames_cache(tmp_path):
    """⑥ __frames__ 全量帧缓存不得落盘（同 evaluate_cs_strengths review I1 模式）。"""
    report = {
        "__out__": str(tmp_path / "cs-tier.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "cs-tier.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["decision"]["window"]["frameCount"] == 1
    assert saved["windowsConsumed"] is True
    assert saved["monitorReferences"] == MONITOR_REFERENCES


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """⑦ resume（已含 window 条目）路径仍必须执行 8 月冻结守卫。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_cs_tier_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """⑧ --extra-trial 注入的 trial 必须真实执行（P1-b persist 交叉对照未来用此注入）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_cs_tier_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    specs = [
        {"key": "baseline", "desc": "b", "overrides": {}, "anchor": None},
        {"key": "persist_f3", "desc": "P1-b persist 交叉对照", "overrides": {"crossSectionPersistFrames": 3}, "anchor": None},
    ]
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "persist_f3" in trials
    assert trials["persist_f3"]["overrides"] == {"crossSectionPersistFrames": 3}


def test_monitor_references_marked_stale():
    """监控对照值必须标注 fund10 前旧口径 + 首跑重测；WeakAbsMax 无效轴归档注记在案。"""
    assert MONITOR_REFERENCES["aTierSampleCount"]["ref"] == 500
    assert "§11.5" in MONITOR_REFERENCES["aTierSampleCount"]["source"]
    assert MONITOR_REFERENCES["cTierShare"]["ref"] == 0.625
    assert "§23.8" in MONITOR_REFERENCES["cTierShare"]["source"]
    for key in ("aTierSampleCount", "cTierShare"):
        assert "旧口径" in MONITOR_REFERENCES[key]["note"]
        assert "重测" in MONITOR_REFERENCES[key]["note"]
    assert "无效轴" in MONITOR_REFERENCES["weakAbsMaxAxis"]["status"]
    assert "不参数化" in MONITOR_REFERENCES["weakAbsMaxAxis"]["note"]


def test_trigger_rate_flag_line():
    assert TRIGGER_RATE_FLAG == 0.035  # 阶段 22.6 观察线
    assert C5_FLIP_RISE_FLAG == 0.01  # C5 附加卡：veto/bd 翻转升幅对照线


def _mk_report(a_base=100, c_base=0.625, a_trial=100, c_trial=0.625, sa=0.10, trial_sa=None, flips=None, trial_flips=None):
    def result(sa_value, a, c, flip):
        return {
            "synergy": {"saEx": sa_value, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}},
            "csTierDistribution": {"counts": {"A": a, "B": 10, "C": 62, "D": 5, "unknown": 1}, "total": 78 + a, "shares": {}, "aSampleCount": a, "cShare": c},
            "flipRates": flip or {"veto": 0.01, "bd_downgrade": 0.02, "regime_state": 0.0},
        }

    base = result(sa, a_base, c_base, flips)
    trial = result(sa if trial_sa is None else trial_sa, a_trial, c_trial, trial_flips)
    return {
        win: {"trials": {"baseline": {"result": base}, "t_x": {"result": trial}}}
        for win in ("decision", "oos1", "oos2")
    }


def test_trial_summary_card_and_monitor_fields():
    """判定卡 C1/C2/C3 + C5 附加卡 + cs 分布/触发率/flipDelta 每窗必出。"""
    report = _mk_report(sa=0.10, trial_sa=0.104, trial_flips={"veto": 0.012, "bd_downgrade": 0.02, "regime_state": 0.0})
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {
        "C1_decisionRelGE3pct": True,
        "C2_oosAnyPositive": True,
        "C3_decisionPassHard": True,
        "C5_flipRiseLE1pct": True,
    }
    assert summary["cardResult"] == "PASS_CANDIDATE"
    win = summary["windows"]["decision"]
    assert win["csTierDistribution"]["aSampleCount"] == 100
    assert win["triggerRateSA"] == 0.04
    assert win["triggerFlag"] is True
    assert win["flipDelta"]["veto"] == 0.002
    assert summary["distributionDelta"] is not None


def test_trial_summary_c5_flagged_on_flip_rise():
    report = _mk_report(trial_flips={"veto": 0.05, "bd_downgrade": 0.02, "regime_state": 0.0})
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"]["C5_flipRiseLE1pct"] is False
    assert summary["cardResult"] == "OBSERVE"  # C1 rel=0 未达 +3%
    assert summary["verdictCard"]["C5_flipRiseLE1pct"] is False


def test_trial_summary_structural_cost_flag_on_a_collapse():
    """A 档样本塌缩 >30% 必须打结构代价旗标（方案 P1 收口节：分布剧变标注结构代价）。"""
    report = _mk_report(a_base=100, a_trial=60)
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["distributionDelta"]["aSampleCountRel"] == round(-40 / 100, 4)
    assert summary["distributionDelta"]["structuralCostFlag"] is True


def test_trial_summary_insufficient_data():
    summary = trial_summary({}, {"key": "t_x"})
    assert summary["verdict"] == "insufficient_data"


def test_anchor_check_match_semantics():
    checked = anchor_check("oos2", 0.0951, ANCHOR_BASELINE)
    assert checked == {"checked": True, "expected": 0.0951, "actual": 0.0951, "match": True}
    assert anchor_check("oos2", 0.0949, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("oos2", None, None) == {"checked": False}
