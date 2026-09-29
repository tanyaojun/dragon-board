# -*- coding: utf-8 -*-
"""synergy.state 与 signalTier 口径对齐测试（2026-08-18 P0 A1）。

compute_synergy_state 新增 cs_tier 维度：cs A 补足主升确认的共振方向缺失、
cs D 升级风险状态——观察面板 state 与列表 signalTier 投票口径一致。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig
from backend.analysis.ranktrend.volume_price import compute_synergy_state


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


def syn(*, stage="ignition", vp=80, tech="buy", res="hold", zljzb=1.0, cs=None, **patch):
    return compute_synergy_state(stage, vp, tech, res, zljzb, cfg(**patch), cs_tier=cs)


# ---------- 原有语义保持（无 cs 时不改变） ----------

def test_confirm_without_cs_unchanged() -> None:
    r = syn(stage="ignition", vp=80, tech="buy", res="buy")
    assert r["state"] == "启动确认"
    assert "共振 ↑" in r["reasons"]


def test_suspect_without_cs_unchanged() -> None:
    r = syn(stage="ignition", vp=80, tech="buy", res="hold")  # 缺共振方向
    assert r["state"] == "suspect"


# ---------- cs A 补足主升确认 ----------

def test_cs_a_completes_ignition_confirm() -> None:
    r = syn(stage="ignition", vp=80, tech="buy", res="hold", cs="A")
    assert r["state"] == "启动确认"
    assert any("横截面 A" in x for x in r["reasons"])


def test_cs_a_completes_expansion_confirm() -> None:
    r = syn(stage="expansion", vp=85, tech="buy", res="hold", cs="A")
    assert r["state"] == "主升确认"


def test_cs_a_not_enough_without_high_vp() -> None:
    r = syn(stage="ignition", vp=40, tech="buy", res="hold", cs="A")  # 量价分低
    assert r["state"] != "启动确认"


# ---------- cs D 升级风险 ----------

def test_cs_d_upgrades_risk_in_crowded() -> None:
    r = syn(stage="crowded", vp=60, tech="hold", res="hold", cs="D")
    assert r["state"] == "风险升级"
    assert r["hardWarn"] is True
    assert any("横截面 D" in x for x in r["reasons"])


def test_cs_d_keeps_ignition_suspect() -> None:
    # 点火期 cs D（低位+下降）不足以把正向状态打成风险，但也不给确认
    r = syn(stage="ignition", vp=80, tech="buy", res="hold", cs="D")
    assert r["state"] == "suspect"


# ---------- cs 未知不影响 ----------

def test_cs_unknown_no_effect() -> None:
    r = syn(stage="ignition", vp=80, tech="buy", res="hold", cs="unknown")
    assert r["state"] == "suspect"
