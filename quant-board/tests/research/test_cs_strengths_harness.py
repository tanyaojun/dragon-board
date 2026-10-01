# -*- coding: utf-8 -*-
"""cs 档位强度表扫描 harness 测试（方案 B，审计 B1-B4 落实断言）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_cs_strengths import (
    ANCHOR_BASELINE,
    BASE_STRENGTHS,
    CS_TRIALS,
    TRIGGER_RATE_FLAG,
    _assert_overrides_applied,
    _save,
    anchor_check,
    equivalence_check,
    run_window,
    trial_summary,
    trigger_rate_of,
)


def test_all_patches_are_explicit_full_lists():
    """§3.1：list patch 整体替换——每个 trial 必须显式写全 [A,B,C,D] 四值。"""
    for spec in CS_TRIALS:
        strengths = spec["overrides"].get("tierSynergyCsStrengths")
        if strengths is not None:
            assert len(strengths) == 4
    for spec in CS_TRIALS:
        assert RankTrendConfig.from_patch(spec["overrides"]) is not None


def test_single_axis_trials_change_only_own_tier():
    """单轴 trial 只动本档：其余三档保持默认 [1.0, 0.5, -0.5, -1.0]（对照对臂跳过）。"""
    for spec in CS_TRIALS:
        strengths = spec["overrides"].get("tierSynergyCsStrengths")
        if strengths is None:
            continue  # cs_vote_0375 是票权对照臂
        if spec["key"] not in {"csA_025", "csA_05", "csA_15", "csB_025", "csB_075", "csC_0", "csC_025", "csC_075", "csD_05", "csD_15"}:
            continue  # uni_half 是 B2 整表对照臂
        axis = spec["key"].split("_")[0]
        index = {"csA": 0, "csB": 1, "csC": 2, "csD": 3}[axis]
        for i, value in enumerate(BASE_STRENGTHS):
            if i != index:
                assert strengths[i] == value, f"{spec['key']} 非本档 {i} 被改动"


def test_csA_includes_b3_down_probe():
    levels = [s["overrides"]["tierSynergyCsStrengths"][0] for s in CS_TRIALS if s["key"].startswith("csA_")]
    assert 0.25 in levels and 0.5 in levels and 1.5 in levels  # 默认 1.0 由 baseline 承担


def test_b2_equivalence_pair_arithmetic():
    """B2 对照对：uni_half 强度 = 默认 ×0.5；cs_vote_0375 = 0.75 × 0.5。"""
    uni = next(s for s in CS_TRIALS if s["key"] == "uni_half")
    assert uni["overrides"]["tierSynergyCsStrengths"] == [0.5, 0.25, -0.25, -0.5]
    vote = next(s for s in CS_TRIALS if s["key"] == "cs_vote_0375")
    assert vote["overrides"] == {"tierSynergyCrossSectionVote": 0.375}


def test_no_uniform_scaling_only_trials_beyond_pair():
    """B2 边界：除对照对外不允许整表等比 trial（信息增量 ≡ 已扫的票权轴）。"""
    for spec in CS_TRIALS:
        if spec["key"] == "uni_half":
            continue
        strengths = spec["overrides"].get("tierSynergyCsStrengths")
        if strengths is None:
            continue
        ratios = [s / b for s, b in zip(strengths, BASE_STRENGTHS)]
        assert len(set(ratios)) > 1, f"{spec['key']} 是整表均匀缩放（与票权轴线性等价，无信息增量）"


def test_baseline_anchor_constant():
    """锚单一事实源（2026-09-25）：ANCHOR_BASELINE 运行时读锚注册表 currentGeneration，
    不再硬编码代际值——注册表更新（如 10/3 全月重跑 oos2 锚）后自动跟随。"""
    from backend.operations.harness_common import baseline_anchor

    gen, anchors = baseline_anchor()
    assert gen == "gen-2026-09-30-midlong-x30"  # 第七代三参组合（vsB070+floor3+x30）
    assert ANCHOR_BASELINE == anchors
    assert ANCHOR_BASELINE["decision"] == 0.1472  # 当前代际漂移哨兵；注册表推进时同步更新


def test_assert_overrides_applied_rejects_unknown_field():
    """review C1：from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"tierSynergyCsStrengths": [0.5, 0.5, -0.5, -1.0]})
    _assert_overrides_applied(ok, {"tierSynergyCsStrengths": [0.5, 0.5, -0.5, -1.0]})
    bad = RankTrendConfig.from_patch({"tierSynergyCsStrengthsTypo": [0.5, 0.5, -0.5, -1.0]})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"tierSynergyCsStrengthsTypo": [0.5, 0.5, -0.5, -1.0]})


def test_save_strips_frames_cache(tmp_path):
    """review I1：__frames__ 全量帧缓存不得落盘（此前单文件膨胀至 ~1GB）。"""
    report = {
        "__out__": str(tmp_path / "cs.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "cs.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["decision"]["window"]["frameCount"] == 1


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """review I2：resume（已含 window 条目）路径仍必须执行 8 月冻结守卫。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    # 冻结守卫应先于任何臂执行抛错；以下 mock 仅保证红灯期不触真引擎/真实报告目录
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_cs_strengths.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """review C2：--extra-trial 注入的 trial 必须真实执行（此前只进 summary 不进执行循环）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.analysis.ranktrend.engine.RankTrendPythonEngine",
        lambda config=None: SimpleNamespace(replay=lambda frames, meta=None: []),
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_cs_strengths.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    specs = [
        {"key": "baseline", "desc": "b", "overrides": {}, "anchor": None},
        {"key": "extra_probe", "desc": "extra", "overrides": {"volumePriceBase": 51.0}, "anchor": None},
    ]
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "extra_probe" in trials
    assert trials["extra_probe"]["overrides"] == {"volumePriceBase": 51.0}


def test_trigger_rate_flag_line():
    assert TRIGGER_RATE_FLAG == 0.035  # 阶段 22.6 观察线


def test_trigger_rate_of_and_flag():
    result = {"synergy": {"distribution": {"S": 3, "A": 4, "C": 93}}}
    assert trigger_rate_of(result) == 0.07
    # >3.5% 旗标在 trial_summary.windows 内断言
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.1044, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.1044, "passHard": True, "distribution": {"S": 4, "A": 4, "C": 92}}}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.0918, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.0918, "passHard": True, "distribution": {"S": 4, "A": 4, "C": 92}}}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.0933, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.0933, "passHard": True, "distribution": {"S": 4, "A": 4, "C": 92}}}},
        }},
    }
    summary = trial_summary(report, {"key": "t_x"})
    assert all(w["triggerFlag"] is True for w in summary["windows"].values())


def test_trial_summary_card_and_b4_note():
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.10, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.104, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.052, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.05, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
            "t_x": {"result": {"synergy": {"saEx": 0.049, "passHard": True, "distribution": {"S": 2, "A": 2, "C": 96}}}},
        }},
    }
    summary = trial_summary(report, {"key": "t_x"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    assert "钝感 ≠ 无信息" in summary["effectSizeNote"]  # 审计 B4


def test_equivalence_check_requires_all_windows():
    report = {
        win: {"trials": {
            "uni_half": {"result": {"synergy": {"saEx": 0.08}, "signalTiers": ["A", "C"]}},
            "cs_vote_0375": {"result": {"synergy": {"saEx": 0.08}, "signalTiers": ["A", "C"]}},
        }}
        for win in ("decision", "oos1", "oos2")
    }
    assert equivalence_check(report)["allMatch"] is True
    report["oos2"]["trials"]["cs_vote_0375"]["result"]["signalTiers"] = ["B", "C"]
    check = equivalence_check(report)
    assert check["allMatch"] is False
    assert check["windows"]["oos2"]["tiersEqual"] is False


def test_equivalence_incomplete_windows_flagged():
    report = {"decision": {"trials": {"uni_half": {"result": {}}}}}
    check = equivalence_check(report)
    assert check["allMatch"] is False
