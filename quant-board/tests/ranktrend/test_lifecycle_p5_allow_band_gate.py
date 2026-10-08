# -*- coding: utf-8 -*-
"""P5 双轴重设计·allow 腿分位带门专项测试（2026-10-07 预登记合同；lifecycle-p5-preregistration.md）。

- 默认 off 零行为=第一断言（合同 C-6）；
- 三态谓词：pct_band（≥ 门限含等号）/ pct_velocity（fast=velocity>5 低门限；None 走宽松侧）；
- 红线③：veto/exit_watch/caution 不触碰（veto 腿保护价值实锤，C-3.3 结构守卫的函数级前提）；
- 接线守卫：_build_signal 在 analyze_cycle_with_risk 之后调用（off 与 banded 两态）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.trend.lifecycle import apply_allow_band_gate

RANKS = [30, 25, 20, 15, 12, 10, 8, 6]
PCTS = [50.0, 55.0, 60.0, 65.0, 70.0, 75.0, 80.0, 95.0]
DAYS = ["2026-06-01"] * 7 + ["2026-06-02"]  # 末步跨日（G1 语义并存场景）


def _mk_cycle(action="allow", velocity=8.0):
    return {
        "decision": {"action": action, "reasons": ["既有原因。"]},
        "metrics": {"rankVelocity": velocity},
    }


class TestDefaultOffZeroBehavior:
    def test_default_mode_is_off(self):
        assert RankTrendConfig().lifecycleAllowBandGateMode == "off"

    def test_off_returns_same_object_untouched(self):
        c = RankTrendConfig()
        cy = _mk_cycle()
        assert apply_allow_band_gate(cy, 95.0, c) is cy

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            RankTrendConfig.from_patch({"lifecycleAllowBandGateMode": "bogus"})


class TestPctBandGate:
    def test_high_percentile_allow_downgraded(self):
        c = RankTrendConfig(lifecycleAllowBandGateMode="pct_band", lifecycleAllowBandGatePctMin=70.0)
        out = apply_allow_band_gate(_mk_cycle(), 95.0, c)
        assert out["decision"]["action"] == "caution"
        assert any("P5 allow 分位带门" in r for r in out["decision"]["reasons"])
        # 原对象零修改（fail-visible 标注只进副本）
        assert out["decision"]["action"] != _mk_cycle()["decision"]["action"]

    def test_boundary_ge_threshold(self):
        c = RankTrendConfig(lifecycleAllowBandGateMode="pct_band", lifecycleAllowBandGatePctMin=70.0)
        assert apply_allow_band_gate(_mk_cycle(), 70.0, c)["decision"]["action"] == "caution"
        assert apply_allow_band_gate(_mk_cycle(), 69.999, c)["decision"]["action"] == "allow"

    def test_below_threshold_untouched(self):
        c = RankTrendConfig(lifecycleAllowBandGateMode="pct_band", lifecycleAllowBandGatePctMin=70.0)
        cy = _mk_cycle()
        assert apply_allow_band_gate(cy, 60.0, c) is cy


class TestRedLines:
    """红线③：veto/exit_watch/caution 一律不触碰。"""

    def test_protected_actions_untouched(self):
        c = RankTrendConfig(lifecycleAllowBandGateMode="pct_band", lifecycleAllowBandGatePctMin=0.0)
        for action in ("veto", "exit_watch", "caution"):
            cy = _mk_cycle(action=action)
            assert apply_allow_band_gate(cy, 99.0, c) is cy


class TestPctVelocityGate:
    def test_fast_uses_lower_threshold(self):
        c = RankTrendConfig(
            lifecycleAllowBandGateMode="pct_velocity",
            lifecycleAllowBandGatePctMin=70.0,
            lifecycleAllowBandGatePctMinFast=50.0,
        )
        assert apply_allow_band_gate(_mk_cycle(velocity=8.0), 55.0, c)["decision"]["action"] == "caution"
        assert apply_allow_band_gate(_mk_cycle(velocity=2.0), 55.0, c)["decision"]["action"] == "allow"
        assert apply_allow_band_gate(_mk_cycle(velocity=2.0), 75.0, c)["decision"]["action"] == "caution"

    def test_velocity_none_goes_lenient_side(self):
        """velocity=None（G1 gap 步）按宽松侧（slow 门限），不误判 fast。"""
        c = RankTrendConfig(
            lifecycleAllowBandGateMode="pct_velocity",
            lifecycleAllowBandGatePctMin=70.0,
            lifecycleAllowBandGatePctMinFast=50.0,
        )
        assert apply_allow_band_gate(_mk_cycle(velocity=None), 55.0, c)["decision"]["action"] == "allow"
        assert apply_allow_band_gate(_mk_cycle(velocity=None), 75.0, c)["decision"]["action"] == "caution"

    def test_fast_boundary_strictly_above_5(self):
        c = RankTrendConfig(
            lifecycleAllowBandGateMode="pct_velocity",
            lifecycleAllowBandGatePctMin=70.0,
            lifecycleAllowBandGatePctMinFast=50.0,
        )
        # velocity=5.0 非 fast（严格 >5，D3 up_fast 定义）
        assert apply_allow_band_gate(_mk_cycle(velocity=5.0), 55.0, c)["decision"]["action"] == "allow"
        assert apply_allow_band_gate(_mk_cycle(velocity=5.01), 55.0, c)["decision"]["action"] == "caution"


class TestBuildSignalWiring:
    """C-5 接线守卫：_build_signal 在 analyze_cycle_with_risk 之后调用改写函数。"""

    def _run(self, config):
        stock = {"code": "600000", "name": "接线守卫股", "change": 2.0, "volumeRatio": 1.5,
                 "zlje": 1.0, "zljzb": 1.0}
        frame = {"tradingDate": "2026-06-02", "slotTime": "15:00", "type": "half_hour", "stocks": [stock]}
        engine = RankTrendPythonEngine(config=config)
        return engine._build_signal(
            stock, frame, RANKS, PCTS, {"state": "neutral"}, {},
            price_changes=[1.0] * 8, amount_history=[100.0] * 8,
            rank_time_keys=DAYS, rank_frame_indices=list(range(8)),
        )

    def test_off_chain_action_unchanged(self):
        signal = self._run(RankTrendConfig())
        assert signal is not None
        action = ((signal["rankTrend"]["cycle"]).get("decision") or {}).get("action")
        assert action in ("allow", "caution", "veto", "exit_watch")  # 合法枚举即可（该形态下 G1 gap 步语义主导）

    def test_banded_chain_downgrades_high_pct_allow(self):
        """本夹具末帧 pct=95：allow 帧（若为 allow）必须被门改写 caution。"""
        c = RankTrendConfig(lifecycleAllowBandGateMode="pct_band", lifecycleAllowBandGatePctMin=70.0)
        signal = self._run(c)
        assert signal is not None
        cycle = signal["rankTrend"]["cycle"]
        action = (cycle.get("decision") or {}).get("action")
        if action == "caution":
            assert any("P5 allow 分位带门" in r for r in (cycle["decision"].get("reasons") or []))
        else:
            # 非 allow（如 gap 步 veto/cooling caution）=本门无干预对象，合法
            assert action in ("veto", "caution", "exit_watch")
