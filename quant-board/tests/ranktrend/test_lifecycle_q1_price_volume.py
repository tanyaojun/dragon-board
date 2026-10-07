# -*- coding: utf-8 -*-
"""Q1 价量证据喂入专项测试（2026-10-07 预登记合同 v1.1；lifecycle-q1-preregistration.md）。

判定线冻结于跑数前；本文件只验机制正确性，不预设剂量臂优劣：
- 机制一 direction_gate（合同 C-c1）：注入人群=跨日步∧|Δpct|≥10（GAP_PV_POPULATION_DELTA_MIN）；
  价跌一律 −P、价升须 volumeRatio≥vrGate 放量确认；证据可用步 raw 由 proxy 驱动（不沿袭）、
  accel/shock 维持置缺（红线②）；证据缺步维持 G1 置缺+沿袭；metrics.gapPriceVolumeProxy 标记
  fail-visible；默认 off 零行为=第一断言（C-7）。
- 机制二前置修复（合同 C-a1）：compute_price_rank_divergence gap_step=True 归 unknown
  （消除 D6：跨日步 rankDir 即隔夜跳变不再进背离判定）。
- 接线守卫（合同 C-6）：live 链 _analyze_one_stock 必须传 lifecycle 专供价量序列
  （a44d965f 评审 P1 教训：replay 单链接线=两代际口径分裂）。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.trend.lifecycle import (
    GAP_PV_POPULATION_DELTA_MIN,
    analyze_cycle,
    gap_velocity_proxy,
)
from backend.analysis.ranktrend.trend.price_rank_divergence import compute_price_rank_divergence

DAYS = ["2026-06-01"] * 7 + ["2026-06-02"]  # 末步跨日
# 末步 |Δpct|=|91.0−20.0|=71 ≥ 10：注入人群内
RANKS = [30, 22, 15, 9, 6, 8, 12, 20]
PCTS = [86.5, 90.0, 93.5, 96.0, 97.5, 97.0, 94.5, 20.0]


def _pv(change_last, vr_last):
    changes = [2.0] * 7 + [change_last]
    ratios = [1.5] * 7 + [vr_last]
    return changes, ratios


class TestDefaultOffZeroBehavior:
    """C-7 第一断言：默认 off 零行为，golden 不漂移。"""

    def test_default_mode_is_off(self):
        c = RankTrendConfig()
        assert c.lifecycleGapPriceVolumeMode == "off"

    def test_off_ignores_price_volume_series(self):
        """off 下传不传价量序列输出逐位一致（含 gap 语义与 decision reasons）。"""
        c = RankTrendConfig()
        base = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS, frame_indices=list(range(8)))
        changes, ratios = _pv(-3.0, 0.5)
        with_pv = analyze_cycle(
            RANKS, PCTS, c, time_keys=DAYS, frame_indices=list(range(8)),
            price_changes=changes, volume_ratios=ratios,
        )
        assert base == with_pv

    def test_off_gap_step_keeps_g1_null_evidence(self):
        c = RankTrendConfig()
        out = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS)
        assert out["metrics"]["rankVelocity"] is None
        assert out["metrics"].get("temporalGap") is True
        assert "gapPriceVolumeProxy" not in out["metrics"]
        assert out["metrics"]["rankAcceleration"] is None

    def test_off_raw_inherits_previous_frame(self):
        """off（与 direction_gate 证据缺步）gap 步 raw 沿袭前帧。"""
        c = RankTrendConfig()
        out = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS)
        prev = analyze_cycle(RANKS[:-1], PCTS[:-1], c, time_keys=DAYS[:-1])
        assert out["rawStage"] == prev["rawStage"]

    def test_invalid_mode_rejected(self):
        with pytest.raises(ValueError):
            RankTrendConfig.from_patch({"lifecycleGapPriceVolumeMode": "bogus"})


class TestGapVelocityProxy:
    """C-c1 表格逐行语义 + inline 复刻自证。"""

    def test_inline_replica_bitwise(self):
        """inline 重写表格逻辑 ↔ gap_velocity_proxy 逐位一致（合同 C-7 L0 自证）。"""
        c = RankTrendConfig(lifecycleGapPriceVolumeProxyP=8.0, lifecycleGapPriceVolumeVrGate=1.5)
        p, vr_gate = 8.0, 1.5

        def inline(change, ratio):
            try:
                ch = float(change)
                vr = float(ratio)
            except (TypeError, ValueError):
                return None
            if ch != ch or vr != vr:  # NaN
                return None
            if ch > 0.0 and vr >= vr_gate:
                return p
            if ch < 0.0:
                return -p
            return None

        for change in (3.0, -3.0, 0.0, None, "", float("nan")):
            for ratio in (2.0, 1.5, 1.49, 0.0, None, "", float("nan")):
                assert gap_velocity_proxy(change, ratio, c) == inline(change, ratio)

    def test_price_down_injects_negative_p(self):
        c = RankTrendConfig(lifecycleGapPriceVolumeProxyP=8.0)
        assert gap_velocity_proxy(-3.0, 0.5, c) == -8.0

    def test_price_up_requires_volume_confirm(self):
        c = RankTrendConfig(lifecycleGapPriceVolumeProxyP=8.0, lifecycleGapPriceVolumeVrGate=1.0)
        assert gap_velocity_proxy(3.0, 1.0, c) == 8.0  # ≥ 门（含等号）
        assert gap_velocity_proxy(3.0, 0.99, c) is None

    def test_flat_or_missing_evidence_is_none(self):
        c = RankTrendConfig()
        assert gap_velocity_proxy(0.0, 1.5, c) is None  # 价平
        assert gap_velocity_proxy(-3.0, None, c) is None  # vr 缺（价跌也须 vr 有限）
        assert gap_velocity_proxy(None, 1.5, c) is None
        assert gap_velocity_proxy("", 1.5, c) is None

    def test_population_threshold_frozen(self):
        assert GAP_PV_POPULATION_DELTA_MIN == 10.0


class TestDirectionGate:
    """机制一 analyze_cycle 集成语义（合同 C-c1/C-c2）。"""

    def test_gap_down_step_proxy_drives_velocity(self):
        c = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=8.0)
        changes, ratios = _pv(-3.0, 0.5)
        out = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS, price_changes=changes, volume_ratios=ratios)
        assert out["metrics"]["rankVelocity"] == -8.0
        assert out["metrics"]["gapPriceVolumeProxy"] is True
        assert out["metrics"]["temporalGap"] is True
        # 红线②：accel/shock 单帧构造不出，维持置缺（不伪造多帧证据）
        assert out["metrics"]["rankAcceleration"] is None
        assert out["metrics"]["rankShock"] is None
        # fail-visible：decision reasons 用代理文案（非「证据缺失」）
        assert any("价量方向代理补位" in r for r in out["decision"]["reasons"])

    def test_gap_up_step_with_volume_confirm(self):
        c = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=5.0)
        changes, ratios = _pv(3.0, 1.2)
        out = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS, price_changes=changes, volume_ratios=ratios)
        assert out["metrics"]["rankVelocity"] == 5.0
        assert out["metrics"]["gapPriceVolumeProxy"] is True

    def test_gap_up_without_volume_stays_g1(self):
        """价升低量（vr 低于门）→ 证据缺，维持 G1 置缺+沿袭。"""
        c = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate")
        changes, ratios = _pv(3.0, 0.5)
        out = analyze_cycle(RANKS, PCTS, c, time_keys=DAYS, price_changes=changes, volume_ratios=ratios)
        assert out["metrics"]["rankVelocity"] is None
        assert "gapPriceVolumeProxy" not in out["metrics"]
        assert any("证据不可判定" in r for r in out["decision"]["reasons"])

    def test_population_outside_delta_min_not_injected(self):
        """人群外（|Δpct|<10）不注入——D3 效度只在该人群验证过（R1 冻结）。"""
        c = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate")
        pcts_flat = [86.5, 88.0, 89.5, 91.0, 92.5, 94.0, 95.5, 91.0]  # 末步 Δ=−4.5
        changes, ratios = _pv(-3.0, 0.5)
        out = analyze_cycle(RANKS, pcts_flat, c, time_keys=DAYS, price_changes=changes, volume_ratios=ratios)
        assert out["metrics"]["rankVelocity"] is None
        assert "gapPriceVolumeProxy" not in out["metrics"]

    def test_length_mismatch_degrades_with_flag(self):
        """价量序列不等长 → 降级 G1 语义 + decision reasons 显式标注（fail-visible）。"""
        c = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate")
        changes, ratios = _pv(-3.0, 0.5)
        out = analyze_cycle(
            RANKS, PCTS, c, time_keys=DAYS,
            price_changes=changes[:3], volume_ratios=None,
        )
        assert out["metrics"]["rankVelocity"] is None
        assert any("价量证据序列" in r and "未启用" in r for r in out["decision"]["reasons"])

    def test_proxy_step_raw_driven_not_inherited(self):
        """证据可用步 raw 由 proxy 驱动（不沿袭前帧）：高位拥挤后跨日崩跌，off 沿袭 crowded、
        direction_gate −P（velocity<0 + drawdown 大）走 raw_stage 自己的判定 → reversal。"""
        c_off = RankTrendConfig()
        c_dg = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=8.0)
        ranks = [30, 25, 20, 15, 12, 10, 8, 50]
        pcts = [86.5, 88.0, 90.0, 92.0, 94.0, 95.0, 95.5, 30.0]  # 末步 |Δ|=65.5 人群内
        days = ["2026-06-01"] * 7 + ["2026-06-02"]
        prev = analyze_cycle(ranks[:-1], pcts[:-1], c_off, time_keys=days[:-1])
        out_off = analyze_cycle(ranks, pcts, c_off, time_keys=days)
        changes, ratios = [2.0] * 7 + [-3.0], [1.5] * 7 + [0.5]
        out_dg = analyze_cycle(ranks, pcts, c_dg, time_keys=days, price_changes=changes, volume_ratios=ratios)
        assert prev["rawStage"] == "crowded"
        assert out_off["rawStage"] == "crowded"  # off 沿袭前帧
        assert out_dg["rawStage"] == "reversal"  # proxy 驱动自行判定

    def test_non_gap_steps_untouched(self):
        """direction_gate 只改 gap 步：同日步输出与 off 逐位一致。"""
        c_off = RankTrendConfig()
        c_dg = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=8.0)
        same_days = ["2026-06-01"] * 8
        changes = [2.0] * 8
        ratios = [1.5] * 8
        out_off = analyze_cycle(RANKS, PCTS, c_off, time_keys=same_days, price_changes=changes, volume_ratios=ratios)
        out_dg = analyze_cycle(RANKS, PCTS, c_dg, time_keys=same_days, price_changes=changes, volume_ratios=ratios)
        assert out_off == out_dg


class TestDivergenceGapDefense:
    """C-a1 前置修复：dv 跨日步归 unknown（D6 缺陷消除）。"""

    def test_gap_step_unknown(self):
        c = RankTrendConfig()
        r = compute_price_rank_divergence([2.0, 3.0], [50.0, 40.0], c, gap_step=True)
        assert r["state"] == "unknown"
        assert r["signalTier"] == "unknown"
        assert r["rankDir"] is None
        assert any("temporalGap" in reason for reason in r["tierReasons"])

    def test_default_false_keeps_legacy(self):
        """默认 False=旧行为（off 模式/旧调用方零漂移）。"""
        c = RankTrendConfig()
        r = compute_price_rank_divergence([2.0, 3.0], [50.0, 40.0], c)
        assert r["state"] == "price_lead_warn"
        assert r["rankDir"] == "down"


class TestLiveChainWiring:
    """C-6 接线守卫：live 链必须传 lifecycle 专供价量序列（两代际口径统一）。"""

    def _args(self, config, pv_changes, pv_ratios):
        ranks, pcts = RANKS, PCTS
        stock = {"code": "600000", "name": "接线守卫股", "change": -3.0, "volumeRatio": 0.5}
        frame = {"tradingDate": "2026-06-02", "slotTime": "15:00", "type": "half_hour", "stocks": [stock]}
        return (
            config, stock, frame,
            ranks, pcts,
            {"state": "neutral"}, [], {}, 50.0, 100, 50.0,
            [None] * 8, [None] * 8,
            None, None, None,
            DAYS, list(range(8)),
            pv_changes, pv_ratios,
        )

    def test_live_chain_wires_price_volume_proxy(self):
        from backend.api.ranktrend_routes import _analyze_one_stock

        config = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=8.0)
        changes, ratios = _pv(-3.0, 0.5)
        result = _analyze_one_stock(self._args(config, changes, ratios))
        assert result is not None
        cycle = (result["analysis"] or {}).get("cycle") or {}
        assert cycle["metrics"]["rankVelocity"] == -8.0
        assert cycle["metrics"]["gapPriceVolumeProxy"] is True

    def test_live_chain_off_has_no_proxy(self):
        from backend.api.ranktrend_routes import _analyze_one_stock

        changes, ratios = _pv(-3.0, 0.5)
        result = _analyze_one_stock(self._args(RankTrendConfig(), changes, ratios))
        cycle = (result["analysis"] or {}).get("cycle") or {}
        assert cycle["metrics"]["rankVelocity"] is None
        assert "gapPriceVolumeProxy" not in cycle["metrics"]

    def test_live_chain_missing_pv_degrades_visibly(self):
        """旧调用方不传价量序列（args 18 元）→ direction_gate 降级标注，不炸不伪装。"""
        from backend.api.ranktrend_routes import _analyze_one_stock

        config = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate")
        ranks, pcts = RANKS, PCTS
        stock = {"code": "600000", "name": "接线守卫股"}
        frame = {"tradingDate": "2026-06-02", "slotTime": "15:00", "type": "half_hour", "stocks": [stock]}
        args = (
            config, stock, frame,
            ranks, pcts,
            {"state": "neutral"}, [], {}, 50.0, 100, 50.0,
            [None] * 8, [None] * 8,
            None, None, None,
            DAYS, list(range(8)),
        )
        result = _analyze_one_stock(args)
        assert result is not None
        cycle = (result["analysis"] or {}).get("cycle") or {}
        assert cycle["metrics"]["rankVelocity"] is None
        assert any("价量证据序列" in r for r in cycle["decision"]["reasons"])


class TestReplayChainWiring:
    """C-6：replay 链同步收集价量序列（volume_ratio_histories）。"""

    def _frames(self):
        # 5 股池（attention 口径按 avgRankNum 升重重排）：600000 从 rank1（pct100）
        # 跨日掉到 rank5（pct20），|Δpct|=80 ≥ 10 注入人群内；价跌 −3.0 → −P 注入。
        def pool(target_avg, target_change, target_vr):
            stocks = []
            for i, avg in enumerate((2.0, 4.0, 6.0, 8.0), start=1):
                stocks.append({
                    "code": f"60000{i}", "avgRankNum": avg, "change": 1.0,
                    "volumeRatio": 1.0, "amount": 100.0, "zlje": 1.0, "zljzb": 1.0,
                })
            stocks.append({
                "code": "600000", "avgRankNum": target_avg, "change": target_change,
                "volumeRatio": target_vr, "amount": 50.0, "zlje": 1.0, "zljzb": 1.0,
            })
            return stocks

        return [
            {"tradingDate": "2026-06-01", "slotTime": "15:00", "type": "half_hour",
             "stocks": pool(1.0, 5.0, 2.0)},
            {"tradingDate": "2026-06-02", "slotTime": "15:00", "type": "half_hour",
             "stocks": pool(9.0, -3.0, 0.5)},
        ]

    def _target_cycle(self, signal):
        return (((signal or {}).get("rankTrend") or {}).get("cycle") or {})

    def test_replay_chain_injects_proxy_on_gap_step(self):
        config = RankTrendConfig(lifecycleGapPriceVolumeMode="direction_gate", lifecycleGapPriceVolumeProxyP=8.0)
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(self._frames(), warmup_count=2)
        assert signals, "replay 应产出信号"
        by_code = {
            str(((s.get("rankTrend") or {}).get("meta") or {}).get("code") or ""): s
            for s in signals
        }
        signal = by_code.get("600000") or signals[-1]
        metrics = self._target_cycle(signal).get("metrics") or {}
        assert metrics.get("temporalGap") is True
        assert metrics.get("gapPriceVolumeProxy") is True
        assert metrics.get("rankVelocity") == -8.0

    def test_replay_chain_off_matches_g1(self):
        config = RankTrendConfig()
        engine = RankTrendPythonEngine(config=config)
        signals = engine.replay(self._frames(), warmup_count=2)
        assert signals
        by_code = {
            str(((s.get("rankTrend") or {}).get("meta") or {}).get("code") or ""): s
            for s in signals
        }
        signal = by_code.get("600000") or signals[-1]
        metrics = self._target_cycle(signal).get("metrics") or {}
        assert metrics.get("temporalGap") is True
        assert "gapPriceVolumeProxy" not in metrics
        assert metrics.get("rankVelocity") is None
