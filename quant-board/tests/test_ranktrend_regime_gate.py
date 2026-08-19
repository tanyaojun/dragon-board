# -*- coding: utf-8 -*-
"""regime 门控分层禁测试（2026-08-19 审计 F1）。

banStrongA/banStrongB：strong 市场 A_MAIN/B_IGNITION 分层禁——
默认 True=True（等价旧全禁）；banStrongB=False = strong 下 A 禁 B 观察；
banStrongA=False = strong 下 A 放行。regimeGateStrongBan=False 回退旧规则。
直接单测 compose_analysis_candidate_tier（同 golden 模式）。
"""
from backend.analysis import ranktrend
from backend.analysis.ranktrend.engine import RankTrendConfig


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


def _strategy(config: RankTrendConfig, regime_state: str = "strong", stage: str = "expansion") -> dict:
    return ranktrend.compose_analysis_candidate_tier(
        technical={
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "hold"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "none"},
            "momentumProfile": {"short": 5, "mid": 5, "long": 2, "acceleration": 1},
        },
        cycle={"stage": stage, "decision": {"action": "allow", "reasons": ["allow"]}},
        risk={"pressure": 0.2, "divergence": {"severity": 0.1}, "overheat": {"severity": 0.1}},
        regime={"state": regime_state, "score": 80.0, "reasons": ["strong regime"]},
        config=config,
    )


# ---------- 默认（True=True）= strong 全禁 A/B ----------

def test_default_strong_bans_a_and_b() -> None:
    assert _strategy(cfg())["candidateTier"] == "N_NEUTRAL"


# ---------- banStrongB=False：strong 下 A 禁、B 放行 ----------

def test_ban_strong_b_false_allows_b_ignition() -> None:
    # B_IGNITION 需要 ignition 阶段；A 禁（banStrongA=True 默认）时 B 观察放行
    s = _strategy(cfg(banStrongB=False), stage="ignition")
    assert s["candidateTier"] == "B_IGNITION"


# ---------- banStrongA=False：strong 下 A 放行（B 仍禁） ----------

def test_ban_strong_a_false_allows_a_main() -> None:
    s = _strategy(cfg(banStrongA=False))
    assert s["candidateTier"] == "A_MAIN"


# ---------- 回退模式（regimeGateStrongBan=False）：strong 全放 ----------

def test_legacy_false_allows_a_main_in_strong() -> None:
    s = _strategy(cfg(regimeGateStrongBan=False))
    assert s["candidateTier"] == "A_MAIN"


# ---------- weak 市场 A 放行（环境门数据修正：弱市选强） ----------

def test_weak_allows_a_main() -> None:
    s = _strategy(cfg(), regime_state="weak")
    assert s["candidateTier"] == "A_MAIN"


# ---------- retreat 风控保留禁 ----------

def test_retreat_bans_a_and_b() -> None:
    s = _strategy(cfg(), regime_state="retreat")
    assert s["candidateTier"] == "N_NEUTRAL"
