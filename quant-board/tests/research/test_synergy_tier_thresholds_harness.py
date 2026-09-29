# -*- coding: utf-8 -*-
"""synergy 总档阈值阶梯扫描 harness 测试（方案 P2，33 trial 结构 + 预检纪律断言）。

覆盖：trial 表完整性（8 轴 × 4 非默认档）/ 单变量拆分 / VoteStrengths patch len==6
（引擎 2026-09-15 list 形状守卫）+ E=1.0 保持 / 锚代际常量 / override 生效性 /
_save 剥离帧缓存 / resume 冻结守卫 / --extra-trial 进执行循环 / baseline 锚 fail-fast。
测试全 mock，不触真实数据窗口（唯一真实构造是 RankTrendConfig.from_patch 纯 dataclass）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.evaluate_synergy_tier_thresholds import (
    ANCHOR_BASELINE,
    BASE_VOTE_STRENGTHS,
    SYNERGY_TIER_TRIALS,
    TRIGGER_RATE_FLAG,
    V_FINAL_READOUT_NOTE,
    _assert_overrides_applied,
    _save,
    anchor_chain_of,
    anchor_check,
    run_window,
    trial_summary,
    trigger_rate_of,
)

LINE_FIELDS = {
    "strong": "tierSynergyVoteStrong",
    "weak": "tierSynergyVoteWeak",
    "reverse": "tierSynergyVoteReverse",
}
EXPECTED_LINE_LEVELS = {
    "tierSynergyVoteStrong": {1.5, 1.75, 2.25, 2.5},
    "tierSynergyVoteWeak": {0.5, 0.75, 1.25, 1.5},
    "tierSynergyVoteReverse": {-1.5, -1.25, -0.75, -0.5},
}
VS_INDEX = {"S": 0, "A": 1, "B": 2, "C": 3, "D": 4}
EXPECTED_VS_LEVELS = {
    "S": {1.0, 1.1, 1.3, 1.4},
    "A": {0.8, 0.9, 1.1, 1.2},
    "B": {0.6, 0.7, 0.9, 1.0},
    "C": {0.0, 0.25, 0.75, 1.0},
    "D": {0.5, 0.75, 1.25, 1.5},
}


# ---------- ① trial 表完整性：8 轴 × 4 非默认档（默认档由 baseline 承担） ----------


def test_trial_table_shape_8_axes_x4_levels():
    assert len(SYNERGY_TIER_TRIALS) == 32
    keys = [s["key"] for s in SYNERGY_TIER_TRIALS]
    assert len(set(keys)) == 32, "trial key 重复"


def test_line_axes_levels_complete():
    for field, levels in EXPECTED_LINE_LEVELS.items():
        got = {s["overrides"][field] for s in SYNERGY_TIER_TRIALS if field in s["overrides"]}
        assert got == levels, f"{field} 档位缺失：期望 {levels} 实际 {got}"


def test_vote_strengths_axes_levels_complete():
    for tier, levels in EXPECTED_VS_LEVELS.items():
        idx = VS_INDEX[tier]
        got = {
            s["overrides"]["tierSynergyVoteStrengths"][idx]
            for s in SYNERGY_TIER_TRIALS
            if s["key"].startswith(f"vs{tier}_")
        }
        assert got == levels, f"VoteStrengths[{tier}] 档位缺失：期望 {levels} 实际 {got}"


def test_base_vote_strengths_matches_engine_default():
    """BASE_VOTE_STRENGTHS 必须与引擎默认逐位一致——漂移则单变量拆分断言全部失效。"""
    assert BASE_VOTE_STRENGTHS == [1.2, 1.0, 0.8, 0.5, 1.0, 1.0]
    assert BASE_VOTE_STRENGTHS == list(RankTrendConfig().tierSynergyVoteStrengths)


# ---------- ② 单变量拆分（skill L31：不是打包） ----------


def test_line_trials_change_only_own_field():
    for spec in SYNERGY_TIER_TRIALS:
        if spec["key"].startswith("vs"):
            continue
        prefix, field = spec["key"].split("_", 1)[0], LINE_FIELDS[spec["key"].split("_", 1)[0]]
        assert list(spec["overrides"].keys()) == [field], f"{spec['key']} 打包了多字段"
        assert spec["overrides"][field] in EXPECTED_LINE_LEVELS[field]


def test_vote_strengths_trials_change_only_own_index():
    for spec in SYNERGY_TIER_TRIALS:
        if not spec["key"].startswith("vs"):
            continue
        assert list(spec["overrides"].keys()) == ["tierSynergyVoteStrengths"], f"{spec['key']} 打包了多字段"
        tier = spec["key"][2]
        idx = VS_INDEX[tier]
        patch = spec["overrides"]["tierSynergyVoteStrengths"]
        for i, value in enumerate(patch):
            if i == idx:
                assert value != BASE_VOTE_STRENGTHS[i], f"{spec['key']} 档位=默认值（默认档由 baseline 承担）"
            else:
                assert value == BASE_VOTE_STRENGTHS[i], f"{spec['key']} 非本档 index {i} 被改动"


# ---------- ③ 全部 VoteStrengths patch len==6 且 E 保持（引擎 list 形状守卫） ----------


def test_all_vs_patches_len6_and_e_preserved():
    for spec in SYNERGY_TIER_TRIALS:
        patch = spec["overrides"].get("tierSynergyVoteStrengths")
        if patch is None:
            continue
        assert len(patch) == 6, f"{spec['key']} patch 长度 {len(patch)} != 6"
        assert patch[5] == 1.0, f"{spec['key']} E（index 5）被改动——E 强度收口免扫（hard 门早退惰性）"


def test_engine_guard_rejects_wrong_length_vote_strengths():
    """harness 正确性依赖引擎守卫：len!=6 必须抛错而非静默回退旧硬编码（volume_price.py:405-406）。"""
    with pytest.raises(ValueError, match="长度必须为 6"):
        RankTrendConfig.from_patch({"tierSynergyVoteStrengths": [1.0, 1.0, 1.0]})


def test_all_patches_construct_real_config_and_apply():
    """32 trial 全部能真实构造 config（from_patch fail-fast 兜底三线约束）且 override 逐键生效。"""
    for spec in SYNERGY_TIER_TRIALS:
        config = RankTrendConfig.from_patch(spec["overrides"])
        assert config is not None
        _assert_overrides_applied(config, spec["overrides"])


# ---------- ④ 锚代际 ----------


def test_baseline_anchor_constant():
    """post-fund10 基线锚（2026-09-15 fund10 落默认后）；
    pre-fund10 代际锚 = 0.1044/0.0918/0.0933（23.9.1 旧口径，方案 B harness 所用）。"""
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}


def test_anchor_check_match_semantics():
    assert anchor_check("oos2", 0.0951, ANCHOR_BASELINE)["match"] is True
    assert anchor_check("oos2", 0.095100001, ANCHOR_BASELINE)["match"] is True  # round4 对齐
    miss = anchor_check("oos2", 0.0933, ANCHOR_BASELINE)
    assert miss["match"] is False and miss["expected"] == 0.0951


# ---------- ⑤ override 生效性守卫（from_patch 对未知字段静默忽略） ----------


def test_assert_overrides_applied_rejects_unknown_field():
    ok = RankTrendConfig.from_patch({"tierSynergyVoteStrong": 2.25})
    _assert_overrides_applied(ok, {"tierSynergyVoteStrong": 2.25})
    bad = RankTrendConfig.from_patch({"tierSynergyVoteStrongTypo": 2.25})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"tierSynergyVoteStrongTypo": 2.25})


# ---------- ⑥ _save 剥离帧缓存 ----------


def test_save_strips_frames_cache(tmp_path):
    report = {
        "__out__": str(tmp_path / "synergy-tier.json"),
        "__frames__": {"decision": [{"tradingDate": "2026-05-04"}]},
        "decision": {"window": {"frameCount": 1}},
    }
    _save(report)
    saved = json.loads((tmp_path / "synergy-tier.json").read_text(encoding="utf-8"))
    assert "__frames__" not in saved
    assert "__out__" not in saved
    assert saved["windowsConsumed"] is True  # 审计 M3：OOS-2 窗口消费标注
    assert saved["decision"]["window"]["frameCount"] == 1


# ---------- ⑦ resume 冻结守卫（mock） ----------


def _mock_frames_and_gate(monkeypatch):
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-05-04"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_synergy_tier_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )


def test_resume_reruns_freeze_guard(monkeypatch, tmp_path):
    """resume（已含 window 条目）路径仍必须执行 8 月冻结守卫（assert_not_frozen 无条件执行）。"""
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-08-05"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_synergy_tier_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": None, "passHard": False}},
    )
    report = {
        "__out__": str(tmp_path / "r.json"),
        "decision": {"window": {"start": "2026-04-15", "end": "2026-07-31", "frameCount": 1}},
    }
    with pytest.raises(ValueError, match="冻结"):
        run_window("decision", report)


# ---------- ⑧ --extra-trial 进执行循环（mock） ----------


def test_run_window_executes_extra_trial(monkeypatch, tmp_path):
    """--extra-trial 注入的 trial 必须真实执行（P2-b 线位 × 档位小网格注入通道）。"""
    _mock_frames_and_gate(monkeypatch)
    specs = [
        {"key": "baseline", "desc": "b", "overrides": {}, "anchor": None},
        {"key": "extra_probe", "desc": "extra", "overrides": {"tierSynergyVoteStrong": 2.25}, "anchor": None},
    ]
    report = {"__out__": str(tmp_path / "r.json")}
    run_window("decision", report, specs=specs)
    trials = report["decision"]["trials"]
    assert "baseline" in trials
    assert "extra_probe" in trials
    assert trials["extra_probe"]["overrides"] == {"tierSynergyVoteStrong": 2.25}


# ---------- baseline 锚 fail-fast（总纲：不复现即停） ----------


def test_run_window_baseline_anchor_mismatch_stops(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "backend.operations.optimize_resonance_parameters.load_frames",
        lambda s, e: [{"tradingDate": "2026-09-02"}],
    )
    monkeypatch.setattr(
        "backend.operations.evaluate_synergy_tier_thresholds.evaluate_gate",
        lambda config, frames: {"synergy": {"saEx": 0.0933, "passHard": True}},
    )
    report = {"__out__": str(tmp_path / "r.json")}
    with pytest.raises(SystemExit, match="baseline 锚不复现"):
        run_window("oos2", report)
    # 已算的 baseline 结果保留在报告中（fail-visible，不丢已产出数据）
    assert report["oos2"]["trials"]["baseline"]["baselineAnchorCheck"]["match"] is False


# ---------- 监控项 ----------


def test_trigger_rate_flag_line():
    assert TRIGGER_RATE_FLAG == 0.035  # 阶段 22.6 观察线


def test_trigger_rate_of_uses_synergy_distribution():
    result = {"synergy": {"distribution": {"S": 3, "A": 4, "B": 1, "C": 92, "D": 0, "E": 0, "unknown": 0}}}
    assert trigger_rate_of(result) == 0.07


def test_trial_summary_monitor_fields_and_card():
    """每 trial 必出：S+A 触发率 + 档位分布迁移 + v_final 读数不可取注明 + 判定卡。"""
    dist = {"S": 2, "A": 2, "B": 10, "C": 80, "D": 4, "E": 1, "unknown": 1}
    report = {
        "decision": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.112, "passHard": True, "distribution": dict(dist)}}},
            "vsS_100": {"result": {"synergy": {"saEx": 0.116, "passHard": True, "distribution": dict(dist)}}},
        }},
        "oos1": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.088, "passHard": True, "distribution": dict(dist)}}},
            "vsS_100": {"result": {"synergy": {"saEx": 0.090, "passHard": True, "distribution": dict(dist)}}},
        }},
        "oos2": {"trials": {
            "baseline": {"result": {"synergy": {"saEx": 0.0951, "passHard": True, "distribution": dict(dist)}}},
            "vsS_100": {"result": {"synergy": {"saEx": 0.094, "passHard": True, "distribution": dict(dist)}}},
        }},
    }
    summary = trial_summary(report, {"key": "vsS_100"})
    assert summary["verdictCard"] == {"C1_decisionRelGE3pct": True, "C2_oosAnyPositive": True, "C3_decisionPassHard": True}
    assert summary["cardResult"] == "PASS_CANDIDATE"
    for win, window in summary["windows"].items():
        assert window["tierDistribution"] == dist  # 档位分布迁移监控（S/A/B/C/D/E/unknown 计数）
        assert window["triggerRateSA"] == 0.04  # S+A 占比
        assert window["triggerFlag"] is True  # >3.5% 旗标
        assert window["voteSumVsStrongLine"] is None  # v_final 读数不可取
    assert "vote_sum" in V_FINAL_READOUT_NOTE and "S/A 占比" in V_FINAL_READOUT_NOTE


def test_trial_summary_insufficient_data():
    summary = trial_summary({}, {"key": "missing"})
    assert summary["verdict"] == "insufficient_data"


def test_anchor_chain_of_covers_only_ran_windows():
    """锚链只对已跑窗口断言：单窗/渐进模式不把未跑窗口误报成"锚不复现"（fail-visible）。"""
    single = {"baseline": {"windows": {"oos2": {"anchor": {"checked": True, "match": True}}}}}
    assert anchor_chain_of(single) == {"ranWindows": ["oos2"], "baseline": True}
    full_fail = {"baseline": {"windows": {
        "decision": {"anchor": {"checked": True, "match": True}},
        "oos1": {"anchor": {"checked": True, "match": True}},
        "oos2": {"anchor": {"checked": True, "match": False}},
    }}}
    chain = anchor_chain_of(full_fail)
    assert chain["ranWindows"] == ["decision", "oos1", "oos2"]
    assert chain["baseline"] is False  # 已跑窗口锚不符仍如实判 False
    assert anchor_chain_of({})["baseline"] is False  # 无锚证据不算通过
