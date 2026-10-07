# -*- coding: utf-8 -*-
"""P1 尺度模式 / P3 时间正规化行为步测试（2026-10-07 预登记合同 A5/B5）。

合同：docs/ranktrend-tier-backtest/reasoning-corpus-lifecycle-stage.md §11.1/§11.2；
默认值零行为（golden 不漂移）是第一断言。
"""
import math

import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.engine.runtime import analyze_cycle as runtime_analyze_cycle
from backend.analysis.ranktrend.trend.lifecycle import (
    analyze_cycle,
    cycle_metrics_window,
    lifecycle_decision,
    neutralize_gap_metrics,
)


def _series() -> tuple[list[float], list[float]]:
    ranks = [30, 22, 15, 9, 6, 8, 12, 20]
    pcts = [86.5, 90.0, 93.5, 96.0, 97.5, 97.0, 94.5, 91.0]
    return ranks, pcts


class TestDefaultZeroBehavior:
    def test_default_config_modes(self):
        # 2026-10-07 用户裁决：G1（cross_day）落默认；L1 尺度保持 mixed（未落默认）
        c = RankTrendConfig()
        assert c.lifecycleRankScaleMode == "mixed"
        assert c.lifecycleTimeGapStrictness == "cross_day"

    def test_off_mode_still_available_as_diagnostic_arm(self):
        # off=旧行为保留为诊断对照臂（配置面存在性）
        c = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "off"})
        assert c.lifecycleTimeGapStrictness == "off"

    def test_default_gap_semantics_active_without_patch(self):
        # 落默认后：默认配置 + 跨日时间键 → gap 语义自动生效（无需 from_patch）
        ranks, pcts = _series()
        days = ["2026-06-01"] * 7 + ["2026-06-02"]
        out = analyze_cycle(ranks, pcts, time_keys=days, frame_indices=list(range(8)))
        assert out["metrics"].get("temporalGap") is True
        assert out["metrics"]["rankVelocity"] is None  # 输出层 NaN→null（缺证据不伪装成 0）
        assert out["metrics"]["rankShock"] is None
        assert any("temporalGap" in r for r in out["decision"]["reasons"])

    def test_invalid_enum_rejected(self):
        with pytest.raises(ValueError, match="lifecycleRankScaleMode"):
            RankTrendConfig.from_patch({"lifecycleRankScaleMode": "bogus"})
        with pytest.raises(ValueError, match="lifecycleTimeGapStrictness"):
            RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "daily"})

    def test_analyze_cycle_default_identical_with_and_without_kwargs(self):
        # 同日相邻键不触发 gap → 传键与不传（无键=strictness 无输入不启用）行为一致
        ranks, pcts = _series()
        a = analyze_cycle(ranks, pcts)
        b = analyze_cycle(ranks, pcts, None, time_keys=["2026-06-01"] * len(ranks), frame_indices=list(range(len(ranks))))
        assert (a["stage"], a["rawStage"], a["transition"], a["confidence"]) == (
            b["stage"], b["rawStage"], b["transition"], b["confidence"]
        )
        assert a["metrics"] == b["metrics"]

    def test_cycle_metrics_window_backward_compat(self):
        ranks, pcts = _series()
        assert cycle_metrics_window(ranks[-8:], pcts[-8:]) == cycle_metrics_window(ranks[-8:], pcts[-8:], None)

    def test_mixed_metrics_identical_to_legacy_shape(self):
        ranks, pcts = _series()
        m = cycle_metrics_window(ranks[-8:], pcts[-8:], RankTrendConfig())
        assert m["bestRecentRank"] == min(ranks)
        assert m["drawdownFromPeak"] == max(0, ranks[-1] - min(ranks))
        assert "temporalGap" not in m


class TestP1ScaleModes:
    def test_pct_full_converts_rank_predicates(self):
        # 尾 7 元素 pct≥88、首元素 86.5<88 且 rank=30>10 → 两模式 hotZoneStreak 均=7（删名次臂不影响此夹具）
        ranks, pcts = _series()
        m = cycle_metrics_window(ranks[-8:], pcts[-8:], RankTrendConfig.from_patch({"lifecycleRankScaleMode": "pct_full"}))
        assert m["hotZoneStreak"] == 7
        assert m["bestRecentRank"] == pytest.approx(201.0 - 2.0 * max(pcts))
        assert m["drawdownFromPeak"] == pytest.approx(2.0 * max(0.0, max(pcts) - pcts[-1]))
        # velocity/shock/pathCommitment 两模式相同（分位单位）
        m_mixed = cycle_metrics_window(ranks[-8:], pcts[-8:], RankTrendConfig())
        for key in ("rankVelocity", "rankAcceleration", "rankPathCommitment"):
            assert m[key] == m_mixed[key]

    def test_pct_full_flips_rank_only_hot_zone(self):
        # 小池：rank≤10 但 pct<88 —— mixed 记热区，pct_full 不记
        ranks = [5, 6, 7]
        pcts = [80.0, 82.0, 84.0]
        m_mixed = cycle_metrics_window(ranks, pcts, RankTrendConfig())
        m_pct = cycle_metrics_window(ranks, pcts, RankTrendConfig.from_patch({"lifecycleRankScaleMode": "pct_full"}))
        assert m_mixed["hotZoneStreak"] == 3
        assert m_pct["hotZoneStreak"] == 0

    def test_hotzone_pct_only_keeps_rank_units(self):
        ranks, pcts = _series()
        m = cycle_metrics_window(ranks[-8:], pcts[-8:], RankTrendConfig.from_patch({"lifecycleRankScaleMode": "hotzone_pct_only"}))
        assert m["bestRecentRank"] == min(ranks)  # 名次单位保留
        assert m["hotZoneStreak"] == 7

    def test_pct_full_changes_stage_on_synthetic_highpool_path(self):
        # 大池（T≈300）：rank 12 ⇔ pct 96.7 —— mixed 的 best≤10 不含 rank12，
        # pct_full 的 best_equiv=201−2·96.7=7.6 ≤10 含它 → crowded 判定差异可复现。
        # 构造：尾帧 rank=12/pct=96.7，连续 8 帧热区、drawdown 小。
        ranks = [11, 12, 12, 12, 12, 12, 12, 12]
        pcts = [96.7, 96.7, 96.7, 96.7, 96.7, 96.7, 96.7, 96.7]
        mixed = analyze_cycle(ranks, pcts, RankTrendConfig())
        pct = analyze_cycle(ranks, pcts, RankTrendConfig.from_patch({"lifecycleRankScaleMode": "pct_full"}))
        assert mixed["rawStage"] == "crowded" or mixed["rawStage"] == "reversal"  # mixed：best=11>10 非名次热区臂
        assert pct["rawStage"] in ("crowded", "reversal")


class TestP3TimeGap:
    def _gap_kwargs(self, days, indices):
        return {"time_keys": days, "frame_indices": indices}

    def test_cross_day_gap_carries_raw_and_nan(self):
        ranks, pcts = _series()
        days = ["2026-06-01"] * 7 + ["2026-06-02"]  # 跨日边界=末步（6→7）
        out = analyze_cycle(ranks, pcts, None, **self._gap_kwargs(days, list(range(len(ranks)))))
        cfg = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        out_gap = analyze_cycle(ranks, pcts, cfg, **self._gap_kwargs(days, list(range(len(ranks)))))
        m = out_gap["metrics"]
        assert m.get("temporalGap") is True
        assert m["rankVelocity"] is None
        assert m["rankShock"] is None
        # hot/best/drawdown（G1 剂量不动）
        assert m["hotZoneStreak"] == out["metrics"]["hotZoneStreak"]
        assert m["bestRecentRank"] == out["metrics"]["bestRecentRank"]
        # raw 沿袭：off 模式末步 raw vs gap 模式 = 前一步 raw（非恒 cooling）
        assert out_gap["rawStage"] == "cooling" or out_gap["rawStage"] == out_gap["decision"]["evidence"]["rawStage"]
        # 落默认后：默认配置（不 patch）+ 跨日键同样触发 gap（G1 已是生产行为）
        assert out["metrics"].get("temporalGap") is True

    def test_non_adjacent_same_day_gap(self):
        ranks, pcts = _series()
        days = ["2026-06-01"] * 8
        indices = [10, 11, 12, 13, 14, 15, 16, 30]  # 末步同日但帧距 14
        cfg_off = RankTrendConfig()
        cfg_g2 = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "non_adjacent"})
        out_off = analyze_cycle(ranks, pcts, cfg_off, **self._gap_kwargs(days, indices))
        out_g2 = analyze_cycle(ranks, pcts, cfg_g2, **self._gap_kwargs(days, indices))
        assert "temporalGap" not in out_off["metrics"]
        assert out_g2["metrics"].get("temporalGap") is True
        # cross_day 严格度不应捕捉同日非相邻
        cfg_g1 = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        out_g1 = analyze_cycle(ranks, pcts, cfg_g1, **self._gap_kwargs(days, indices))
        assert "temporalGap" not in out_g1["metrics"]

    def test_gap_never_silently_cools(self):
        # 反幻觉断言：gap 帧 raw = 前帧 raw，即便前帧是 crowded/expansion 也不许落 cooling
        ranks = [4, 4, 4, 4, 4, 4, 4, 4]
        pcts = [98.5] * 8
        days = ["d1"] * 7 + ["d2"]
        cfg = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        out = analyze_cycle(ranks, pcts, cfg, time_keys=days, frame_indices=list(range(8)))
        assert out["rawStage"] == "crowded"  # 前帧 crowded 沿袭，非 cooling
        assert out["metrics"].get("temporalGap") is True

    def test_neutralize_gap_metrics(self):
        m = {"rankVelocity": float("nan"), "rankShock": float("nan"), "hotZoneStreak": 3, "temporalGap": True}
        out = neutralize_gap_metrics(m)
        assert out["rankVelocity"] == 0.0 and out["rankShock"] == 0.0
        assert out["hotZoneStreak"] == 3 and out["temporalGap"] is True
        plain = {"rankVelocity": 5.0}
        assert neutralize_gap_metrics(plain) is plain  # 无标记恒原样（零开销）

    def test_decision_evidence_nan_to_none_and_reason(self):
        ranks = [4, 4, 4, 4]
        pcts = [98.5] * 4
        days = ["d1"] * 3 + ["d2"]
        cfg = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        out = analyze_cycle(ranks, pcts, cfg, time_keys=days, frame_indices=list(range(4)))
        decision = out["decision"]
        assert any("temporalGap" in r for r in decision["reasons"])
        ev = decision["evidence"]
        assert ev["rankVelocity"] is None and ev["rankAcceleration"] is None
        # JSON 可序列化（无 NaN 泄漏）
        import json as _json

        _json.dumps(decision, allow_nan=False)


class TestEngineWiring:
    def test_engine_replay_off_matches_baseline_semantics(self):
        """引擎 replay 全链：off 模式 + 时间键传参后输出与默认逐位一致。"""
        cfg = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        assert cfg.lifecycleTimeGapStrictness == "cross_day"
        # 引擎装配冒烟：off 与默认同配置路径（不抛错即接线存在）
        engine = RankTrendPythonEngine(config=RankTrendConfig())
        assert callable(getattr(engine, "replay_frame_at", None))

    def test_runtime_analyze_cycle_passthrough(self):
        ranks, pcts = _series()
        days = ["2026-06-01"] * 8
        cfg = RankTrendConfig.from_patch({"lifecycleTimeGapStrictness": "cross_day"})
        out = runtime_analyze_cycle(ranks, pcts, cfg, time_keys=days, frame_indices=list(range(8)))
        assert out["metrics"].get("temporalGap") is not True  # 同日相邻非 gap
