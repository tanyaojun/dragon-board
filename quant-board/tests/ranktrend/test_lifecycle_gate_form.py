# -*- coding: utf-8 -*-
"""生命周期环境门干预形态参数化测试（阶段 24 方案 A，TDD 先行）。

审计修订稿 §3.1 soft 合成语义逐条断言 + §5 判定卡 C5 结构守恒约束的单元级性质：
- 默认（hard/hard/hard）= 现行为，golden 不漂移；
- veto 轴与降档轴正交（双轴开关，实施偏差声明见提案 §3.1 实施记录）；
- off 模式 ≡ 23.8 wrapper 把 lc_tier 置 "C" 的删除面（锚 3 等价性的单元基础）；
- 边界映射预登记（§3.1.3）：penalty=0.5 时 v=2.0→B、v=3.0→A；strength=1.5 时
  v_raw=2.0→C、v_raw=3.5→A。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.ranking.volume_price import _lc_gate_veto_path, _synergy_tier, assemble_observation


def _w1(**extra):
    """四维票权重全 1.0 的评估配置（票值算术直读：A=1.0/S=1.2/B=0.8/C=0.5/E=1.0）。

    票强表冻结 pre-vsB070 口径（B=0.8；eabf4b44 于 2026-09-30 落默认 B→0.7，
    与 evaluate_synergy_tier_thresholds.BASE_VOTE_STRENGTHS 同一冻结回退对照口径）：
    本文件只测环境门干预形态语义，§3.1.3 边界映射（v=2.0→A、v=3.0→S）按 B=0.8
    算术预登记；引擎默认票强由 tests/ranktrend/test_hardcoded_parameterization.py 单独覆盖。
    """
    patch = {
        "tierSynergyResonanceVote": 1.0,
        "tierSynergyRankVote": 1.0,
        "tierSynergyVolumePriceVote": 1.0,
        "tierSynergyCrossSectionVote": 1.0,
        "tierSynergyVoteStrengths": [1.2, 1.0, 0.8, 0.5, 1.0, 1.0],  # 冻结 pre-vsB070（回退对照口径）
    }
    patch.update(extra)
    return RankTrendConfig.from_patch(patch)


def _args(v: float, lc_tier: str, **kw):
    """构造指定票值 v 的维度输入（权重全 1.0 口径）+ lifecycle 档位。"""
    table = {
        0.5: (("C", "buy"), ("C", "hold"), ("C", "hold"), None),
        1.5: (("A", "buy"), ("C", "hold"), ("C", "buy"), None),  # 1.0 + 0.5
        2.0: (("A", "buy"), ("C", "hold"), ("A", "up"), None),  # 1.0 + 1.0
        2.5: (("A", "buy"), ("C", "hold"), ("A", "up"), "B"),  # 1.0 + 1.0 + 0.5
        3.0: (("S", "buy"), ("A", "buy"), ("B", "up"), None),  # 1.2 + 1.0 + 0.8
        3.5: (("A", "buy"), ("A", "buy"), ("A", "up"), "B"),  # 1.0×3 + 0.5
    }
    res, rank, vp, cs = table[v]
    return (res[0], res[1], rank[0], rank[1], vp[0], vp[1], lc_tier), cs, kw


def _tier_at(v: float, lc_tier: str, config: RankTrendConfig, **kw) -> tuple[str, list[str]]:
    args, cs, kw2 = _args(v, lc_tier, **kw)
    merged = {**kw2}
    return _synergy_tier(*args, config, cs_tier=cs, **merged)


# ---------------------------------------------------------------------------
# 1. 默认 hard = 现行为（golden 不漂移）
# ---------------------------------------------------------------------------


def test_default_hard_veto_short_circuit():
    tier, reasons = _tier_at(3.5, "E", RankTrendConfig())
    assert tier == "E"
    assert "周期一票否决" in reasons[0]


def test_default_hard_vp_e_forced_d():
    config = RankTrendConfig()
    tier, reasons = _synergy_tier("S", "buy", "S", "buy", "E", "up", "A", config)
    assert tier == "D"
    assert reasons == ["量价出货硬风险"]


def test_default_hard_downgrade_s_to_a_and_a_to_b():
    config = _w1()  # 全 1.0 权重，票值算术直读
    tier, reasons = _tier_at(3.0, "B", config)
    assert tier == "A"
    assert any("环境降档" in r for r in reasons)
    tier, reasons = _tier_at(2.0, "D", config)
    assert tier == "B"
    assert any("环境降档" in r for r in reasons)


def test_default_hard_downgrade_not_touch_b_frame():
    tier, _ = _tier_at(1.5, "B", RankTrendConfig())
    assert tier == "B"  # 首评 B 非降档作用域


# ---------------------------------------------------------------------------
# 2. off 模式 ≡ 删除面（锚 3 等价性的单元基础）
# ---------------------------------------------------------------------------


def test_veto_off_removes_short_circuit():
    config = _w1(lifecycleVetoGateMode="off")
    tier, reasons = _tier_at(2.0, "E", config)
    assert tier == "A"  # v=2.0 正常落 A，无否决
    assert not any("一票否决" in r for r in reasons)


def test_downgrade_off_removes_downgrade():
    config = _w1(lifecycleDowngradeGateMode="off")
    tier, reasons = _tier_at(3.0, "B", config)
    assert tier == "S"  # v=3.0 正常落 S
    assert not any("环境降档" in r for r in reasons)


def test_vp_gate_off_removes_forced_d_and_mutes_vote():
    config = _w1(volumePriceGateMode="off")
    # vp E 静默（不计票）+ 不强制 D：v = res S 1.2 + rank A 1.0 = 2.2 → A
    tier, reasons = _synergy_tier("S", "buy", "A", "buy", "E", "up", "A", config)
    assert tier == "A"
    assert not any("量价出货" in r for r in reasons)


# ---------------------------------------------------------------------------
# 3. soft veto 负票（剂量轴，§3.1.3 边界映射）
# ---------------------------------------------------------------------------


def test_soft_veto_negative_vote_boundaries():
    config = _w1(lifecycleVetoGateMode="soft", lifecycleVetoVoteStrength=1.5)
    tier, reasons = _tier_at(2.0, "E", config)
    assert tier == "C"  # 2.0 − 1.5 = 0.5 → C
    assert any("周期否决负票" in r for r in reasons)
    tier, _ = _tier_at(3.5, "E", config)
    assert tier == "A"  # 3.5 − 1.5 = 2.0 → A（近全票一致可部分对冲）


def test_soft_veto_reaches_d_line():
    config = _w1(lifecycleVetoGateMode="soft", lifecycleVetoVoteStrength=2.25)
    tier, _ = _tier_at(0.5, "E", config)
    assert tier == "D"  # 0.5 − 2.25 = −1.75 ≤ reverse(−1.0) → D


# ---------------------------------------------------------------------------
# 4. veto 路径分流（d1/d2）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path_mode,path,expect_hard",
    [
        ("all_soft", "reversal", False),
        ("all_soft", "highrisk", False),
        ("all_soft", None, False),
        ("reversal_hard", "reversal", True),
        ("reversal_hard", "highrisk", False),
        ("highrisk_hard", "reversal", False),
        ("highrisk_hard", "highrisk", True),
        ("reversal_hard", None, True),  # 路径未知保守保留硬否决（fail-safe）
    ],
)
def test_soft_veto_path_split(path_mode, path, expect_hard):
    config = _w1(lifecycleVetoGateMode="soft", lifecycleVetoPathMode=path_mode)
    tier, _ = _tier_at(3.5, "E", config, lc_veto_path=path)
    assert (tier == "E") is expect_hard


# ---------------------------------------------------------------------------
# 5. soft 降档惩罚（c2a/c2b，§3.1.3 边界映射）
# ---------------------------------------------------------------------------


def test_soft_downgrade_penalty_boundaries():
    config = _w1(lifecycleDowngradeGateMode="soft", lifecycleDowngradePenalty=0.5)
    tier, reasons = _tier_at(3.0, "D", config)
    assert tier == "A"  # 首评 S → 2.5 → A
    assert any("环境惩罚" in r for r in reasons)
    tier, _ = _tier_at(2.0, "B", config)
    assert tier == "B"  # 首评 A → 1.5 → B
    tier, _ = _tier_at(1.5, "B", config)
    assert tier == "B"  # 首评 B 不在作用域，无惩罚


def test_soft_downgrade_zero_penalty_is_noop():
    config = _w1(lifecycleDowngradeGateMode="soft", lifecycleDowngradePenalty=0.0)
    tier, _ = _tier_at(3.0, "B", config)
    assert tier == "S"  # 3.0 − 0 = 3.0 → S（等价降档关闭的连续形式）


def test_vp_gate_soft_forced_negative_vote():
    config = _w1(volumePriceGateMode="soft")
    # vp E 强制负票（E 强度 1.0 × vp 权重 1.0）：v = 1.0(res A) − 1.0 = 0 → C
    tier, reasons = _synergy_tier("A", "buy", "C", "hold", "E", "up", "A", config)
    assert tier == "C"
    assert any("量价出货负票" in r for r in reasons)
    # v = 2.2(res S 1.2 + rank A 1.0) − 1.0 = 1.2 → B
    tier, _ = _synergy_tier("S", "buy", "A", "buy", "E", "up", "A", config)
    assert tier == "B"


# ---------------------------------------------------------------------------
# 6. config 校验（fail-fast）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "patch",
    [
        {"lifecycleVetoGateMode": "bogus"},
        {"lifecycleVetoPathMode": "bogus"},
        {"lifecycleDowngradeGateMode": "bogus"},
        {"volumePriceGateMode": "bogus"},
        {"lifecycleVetoVoteStrength": -0.1},
        {"lifecycleDowngradePenalty": -1.0},
    ],
)
def test_from_patch_rejects_invalid_gate_config(patch):
    with pytest.raises(ValueError):
        RankTrendConfig.from_patch(patch)


def test_direct_construction_invalid_mode_fails_at_consumption():
    config = RankTrendConfig(lifecycleVetoGateMode="bogus")
    with pytest.raises(ValueError):
        _tier_at(2.0, "E", config)


# ---------------------------------------------------------------------------
# 7. veto 路径派生（assemble_observation 接线）
# ---------------------------------------------------------------------------


def test_lc_gate_veto_path_derivation():
    reversal = {"veto": True, "stage": "reversal", "reasons": ["生命周期进入反转路径，辅助决策一票否决。"]}
    highrisk = {"veto": True, "stage": "ignition", "reasons": ["生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。"]}
    assert _lc_gate_veto_path(reversal) == "reversal"
    assert _lc_gate_veto_path(highrisk) == "highrisk"
    # 兜底：reasons 缺失按 stage 判
    assert _lc_gate_veto_path({"veto": True, "stage": "reversal", "reasons": []}) == "reversal"
    assert _lc_gate_veto_path({"veto": True, "stage": "ignition", "reasons": []}) == "highrisk"
    assert _lc_gate_veto_path({"veto": False, "stage": "cooling", "reasons": []}) == "highrisk"


def test_assemble_observation_wires_veto_path():
    """reversal reasons + reversal_hard → 硬 E；highrisk reasons + reversal_hard → 负票非 E。"""

    def _analysis(reasons: list[str], stage: str):
        return {
            "resonance": {},
            "observation": {
                "lifecycle": {
                    "stage": stage,
                    "score": 10,
                    "veto": True,
                    "reasons": reasons,
                    "signalTier": "E",
                    "tierReasons": ["生命周期一票否决"],
                },
                "rankTrend": {"signalTier": "A", "direction": "buy"},
                "crossSection": {"signalTier": "B"},
            },
        }

    stock = {"code": "000001", "change": 2.0, "volumeRatio": 1.2, "zlje": None, "zljzb": 1.0}
    config = _w1(lifecycleVetoGateMode="soft", lifecycleVetoPathMode="reversal_hard")

    obs = assemble_observation(_analysis(["生命周期进入反转路径，辅助决策一票否决。"], "reversal"), stock, config)
    assert obs["synergy"]["signalTier"] == "E"  # reversal 保留硬否决

    obs = assemble_observation(
        _analysis(["生命周期虽处于点火/扩散，但风险背离与过热证据明确反对，辅助决策一票否决。"], "ignition"),
        stock,
        config,
    )
    assert obs["synergy"]["signalTier"] != "E"  # highrisk 转负票


# ---------------------------------------------------------------------------
# 8. C5 结构守恒（单元级性质）：门不作用的帧，soft/off 与 hard 逐位一致
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("lc_tier", ["A", "C"])
@pytest.mark.parametrize(
    "patch",
    [
        {"lifecycleVetoGateMode": "off", "lifecycleDowngradeGateMode": "off"},
        {"lifecycleVetoGateMode": "soft", "lifecycleVetoVoteStrength": 0.375},
        {"lifecycleDowngradeGateMode": "soft", "lifecycleDowngradePenalty": 0.25},
        {"volumePriceGateMode": "off"},
        {"volumePriceGateMode": "soft"},
    ],
)
def test_gate_inactive_frames_conserved(lc_tier, patch):
    """lc ∉ {B,D,E} 且 vp ≠ E 的帧：任何 gate 形态下 synergy 档位与 hard 一致。"""
    baseline = _w1()
    trial = _w1(**patch)
    for v in (0.5, 1.5, 2.0, 2.5, 3.0, 3.5):
        args, cs, _ = _args(v, lc_tier)
        assert _synergy_tier(*args, baseline, cs_tier=cs) == _synergy_tier(*args, trial, cs_tier=cs)
