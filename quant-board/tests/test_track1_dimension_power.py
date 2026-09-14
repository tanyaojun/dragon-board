# -*- coding: utf-8 -*-
"""Track 1 维度话语权复核 harness 测试（方案 A，审计 M1/M2/M3/M4 落实断言）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.operations.track1_dimension_power import (
    ANCHOR_BASELINE,
    ANCHOR_W1_OLD,
    ARMS,
    TRADE_COUNT_FLOOR,
    _assert_overrides_applied,
    anchor_check,
    anchor_enforce,
    arm_reading,
)


def _sim(trades: int, wr: float | None, pf: float | None, entries: list[str]):
    return {
        "tradeCount": trades,
        "winRate": wr,
        "profitFactor": pf,
        "totalReturn": -0.05,
        "maxDrawdown": -0.2,
        "tradeEvents": [{"action": "buy", "snapshotId": k.split(":")[0], "code": k.split(":")[1]} for k in entries],
    }


def test_arm_keys_unique_and_complete():
    keys = [a["key"] for a in ARMS]
    assert keys == ["baseline", "w1_old", "no_res", "no_rank", "no_vp", "no_cs"]


def test_w1_old_patch_is_exact_a1_scope():
    """M4：w1_old patch 必须恰为阶段 24.3 a1 口径（res/rank/cs=1.0，vp 不在 patch 内）。"""
    w1 = next(a for a in ARMS if a["key"] == "w1_old")
    assert w1["overrides"] == {"tierSynergyResonanceVote": 1.0, "tierSynergyRankVote": 1.0, "tierSynergyCrossSectionVote": 1.0}
    assert "tierSynergyVolumePriceVote" not in w1["overrides"]


def test_all_arm_patches_construct_valid_configs():
    for arm in ARMS:
        assert RankTrendConfig.from_patch(arm["overrides"]) is not None


def test_anchor_constants_generation():
    """锚代际（2026-09-15 fund10 落默认后）：baseline=post-fund10 基线锚；
    w1_old=24.3 a1 实测（pre-fund10 代际，重跑漂移时按代际漂移处理不阻断）。"""
    assert ANCHOR_BASELINE == {"decision": 0.112, "oos1": 0.088, "oos2": 0.0951}
    assert ANCHOR_W1_OLD == {"decision": 0.0939, "oos1": 0.0854, "oos2": 0.0737}  # 24.3 a1（pre-fund10）
    assert next(a for a in ARMS if a["key"] == "baseline")["anchor"] is ANCHOR_BASELINE
    assert next(a for a in ARMS if a["key"] == "w1_old")["anchor"] is ANCHOR_W1_OLD
    assert all(a["anchor"] is None for a in ARMS if a["key"].startswith("no_"))


def test_anchor_check_round4():
    assert anchor_check("decision", 0.112, ANCHOR_BASELINE)["match"] is True
    assert anchor_check("decision", 0.1121, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("decision", None, ANCHOR_BASELINE)["match"] is False
    assert anchor_check("decision", 0.1, None)["checked"] is False


def test_assert_overrides_applied_rejects_unknown_field():
    """review C1：from_patch 对未知字段静默忽略——harness 必须逐键断言 override 生效。"""
    ok = RankTrendConfig.from_patch({"tierSynergyResonanceVote": 0.5})
    _assert_overrides_applied(ok, {"tierSynergyResonanceVote": 0.5})
    bad = RankTrendConfig.from_patch({"tierSynergyResonanceVoteTypo": 0.5})
    with pytest.raises(AssertionError, match="override 未生效"):
        _assert_overrides_applied(bad, {"tierSynergyResonanceVoteTypo": 0.5})


def test_anchor_enforce_baseline_mismatch_raises():
    """审计 M4：baseline 锚失配 = patch/帧/配置代际与锚不符，先修再继续（raise）。"""
    with pytest.raises(ValueError, match="baseline"):
        anchor_enforce("decision", "baseline", {"checked": True, "expected": 0.112, "actual": 0.1, "match": False})


def test_anchor_enforce_nonbaseline_marks_stale(capsys):
    """非 baseline 锚失配按代际漂移处理：警告 + 返回 stale，不阻断。"""
    assert anchor_enforce("decision", "w1_old", {"checked": True, "expected": 0.0939, "actual": 0.09, "match": False}) is True
    assert "锚失配" in capsys.readouterr().err
    assert anchor_enforce("decision", "w1_old", {"checked": True, "expected": 0.0939, "actual": 0.0939, "match": True}) is False
    assert anchor_enforce("decision", "no_res", {"checked": False}) is False


def test_arm_reading_grade_floor_m2():
    """审计 M2：tradeCount < 30 的窗读数降级 observation。"""
    syn = {"distribution": {"S": 10, "A": 10, "C": 80}}
    below = arm_reading(_sim(22, 0.3, 0.5, ["a:1", "b:2"]), syn, None)
    assert below["tradeCountGrade"] == "observation"
    above = arm_reading(_sim(144, 0.48, 0.96, [f"a:{i}" for i in range(150)]), syn, None)
    assert above["tradeCountGrade"] == "decision"


def test_arm_reading_trigger_and_entry_drift_m2():
    syn = {"distribution": {"S": 5, "A": 15, "C": 80}}
    reading = arm_reading(_sim(100, 0.5, 1.0, ["s1:1", "s2:2", "s3:3"]), syn, base_keys={"s1:1", "s9:9"})
    assert reading["triggerRateSA"] == 0.2
    assert reading["entryNewVsBaseline"] == 2  # s2/s3 新增
    assert reading["entryDroppedVsBaseline"] == 1  # s9 移除
    assert reading["entryCount"] == 3


def test_trade_floor_constant_is_30():
    assert TRADE_COUNT_FLOOR == 30


def test_no_vp_keeps_structural_short_circuit_scope():
    """§2.2 自首差异的边界断言：no_vp patch 只含票权字段，不含 gate 形态字段。"""
    no_vp = next(a for a in ARMS if a["key"] == "no_vp")
    assert no_vp["overrides"] == {"tierSynergyVolumePriceVote": 0.0}
    assert "volumePriceGateMode" not in no_vp["overrides"]


@pytest.mark.parametrize("wr,pf,expected", [(0.5, 1.0, 0.5), (None, 1.0, None), (0.5, None, None)])
def test_arm_reading_wrxpf_passthrough(wr, pf, expected):
    reading = arm_reading(_sim(50, wr, pf, []), {"distribution": {"S": 0, "A": 0, "C": 100}}, None)
    assert reading["winRateXpf"] == expected
