# -*- coding: utf-8 -*-
"""harness_common 公共库测试（2026-09-21 审计收敛，见
docs/ranktrend-tier-backtest/harness-audit-20260921.md）。

覆盖五类风险对应能力：已知答案校验、信号访问器、指标装配、override 断言、
报告落盘（schemaVersion 校验 / 剥帧缓存）与窗口纪律守卫。
"""
from __future__ import annotations

import json

import pytest

from backend.analysis.ranktrend.research.tier_monotonicity import tier_forward_returns
from backend.optimization.data_windows import assert_not_frozen
from backend.operations.harness_common import (
    assert_overrides_applied,
    cache_frames,
    dimension_tier_of,
    known_answer_issues,
    load_resume,
    new_report,
    sample_quality_of,
    sample_status_of,
    sa_excess,
    save_report,
    status_buckets,
    tier_summary,
)


# ── 已知答案校验（mini replay 结构/数据断言）────────────────────────────────
def test_known_answer_mini_replay_passes():
    assert known_answer_issues() == []


def test_known_answer_confirms_top_level_structure():
    # 2026-09-20 事故型防线前置事实：顶层无 observation（误读点），
    # 权威挂载点是 rankTrend.observation
    from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
    from backend.operations.harness_common import _known_answer_frames

    frames = _known_answer_frames()
    engine = RankTrendPythonEngine(RankTrendConfig())
    signals = engine.replay(frames, meta={"sampleQuality": "ok"})
    assert signals
    assert "observation" not in signals[-1]
    assert isinstance(signals[-1]["rankTrend"]["observation"], dict)


# ── 信号访问器 ──────────────────────────────────────────────────────────────
def _signal_with_status(status: str) -> dict:
    return {"rankTrend": {"meta": {"sampleQuality": {"status": status}}}}


def test_sample_status_reads_ranktrend_meta_path():
    assert sample_status_of(_signal_with_status("degraded")) == "degraded"
    assert sample_status_of(_signal_with_status("ok")) == "ok"
    assert sample_status_of(_signal_with_status("insufficient")) == "insufficient"


def test_sample_status_missing_field_falls_back_insufficient():
    assert sample_status_of({}) == "insufficient"
    assert sample_quality_of({}) == {}


def test_dimension_tier_of_uses_dimension_paths():
    # lifecycle 权威路径 = rankTrend.observation.lifecycle.signalTier
    signal = {"rankTrend": {"observation": {"lifecycle": {"signalTier": "A"}}}}
    assert dimension_tier_of(signal, "lifecycle") == "A"
    assert dimension_tier_of({"rankTrend": {"resonance": {"signalTier": "S"}}}, "resonance") == "S"
    # 非法值/缺字段回退 unknown，不伪装
    assert dimension_tier_of({"rankTrend": {"observation": {}}}, "lifecycle") == "unknown"
    assert dimension_tier_of({}, "synergy") == "unknown"


# ── 指标装配 ────────────────────────────────────────────────────────────────
def test_status_buckets_counts_and_shares():
    signals = [
        _signal_with_status("ok"),
        _signal_with_status("ok"),
        _signal_with_status("degraded"),
        _signal_with_status("insufficient"),
    ]
    buckets = status_buckets(signals)
    assert buckets["ok"] == 2
    assert buckets["degraded"] == 1
    assert buckets["insufficient"] == 1
    assert buckets["total"] == 4
    assert buckets["share"]["ok"] == 0.5


def test_status_buckets_empty_returns_empty_share():
    buckets = status_buckets([])
    assert buckets["total"] == 0
    assert buckets["share"] == {}


def test_tier_summary_and_sa_excess_consume_tiers_key():
    # 键名合同：tier_forward_returns 返回 tiers（非 byTier）；缺失/None 不伪造 0
    stats = tier_forward_returns([], [], horizon=1, dimension="synergy")
    summary = tier_summary(stats)
    assert summary["saEx"] is None
    assert summary["unknownRate"] == 0
    assert set(summary["distribution"]) == {"S", "A", "B", "C", "D", "E", "unknown"}
    assert sa_excess({"tiers": {"S": {"count": 0}, "A": {"count": 0}}}) is None
    assert (
        sa_excess(
            {
                "tiers": {
                    "S": {"count": 1, "excessDirectionAccuracy": 0.10},
                    "A": {"count": 3, "excessDirectionAccuracy": 0.02},
                }
            }
        )
        == pytest.approx((1 * 0.10 + 3 * 0.02) / 4)
    )


# ── override 断言 ───────────────────────────────────────────────────────────
def test_assert_overrides_applied_passes_and_fails():
    from backend.analysis.ranktrend.engine import RankTrendConfig

    config = RankTrendConfig.from_patch({"degradedSampleFloor": 3})
    assert_overrides_applied(config, {"degradedSampleFloor": 3})
    with pytest.raises(RuntimeError, match="override 未生效"):
        assert_overrides_applied(config, {"degradedSampleFloor": 7})


# ── 报告落盘 ────────────────────────────────────────────────────────────────
def test_save_report_strips_frames_and_writes_meta(tmp_path):
    out = tmp_path / "rep.json"
    report = new_report(out, schema_version="test-v1", nature="测试报告")
    cache_frames(report, "oos1", [{"snapshotId": "big"}])
    save_report(report)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert "__frames__" not in payload  # 帧缓存不落盘（防 GB 级报告）
    assert payload["schemaVersion"] == "test-v1"
    assert payload["nature"] == "测试报告"
    assert payload["windowsConsumed"] == ["oos1"]
    assert "generatedAt" in payload


def test_load_resume_rejects_schema_mismatch(tmp_path):
    out = tmp_path / "rep.json"
    report = new_report(out, schema_version="v2")
    report["oos1"] = {"trials": {"baseline": {"score": 1}}}
    save_report(report)

    resumed = load_resume(out, schema_version="v2")
    assert resumed is not None
    assert resumed["oos1"]["trials"]["baseline"]["score"] == 1
    assert resumed["__frames__"] == {}  # resume 不恢复帧缓存，重新加载走守卫

    # 版本不匹配 / 无版本字段的旧格式 → None（防跨 schema 混合读数）
    assert load_resume(out, schema_version="v3") is None
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"oos1": {"trials": {}}}), encoding="utf-8")
    assert load_resume(legacy, schema_version="v2") is None


# ── 窗口纪律守卫（FINAL 冻结）───────────────────────────────────────────────
def test_assert_not_frozen_blocks_final_frames_for_scan():
    final_frame = {"tradingDate": "2026-08-05"}
    with pytest.raises(ValueError, match="冻结窗口"):
        assert_not_frozen([final_frame], "scan")
    assert_not_frozen([final_frame], "report")  # 报告用途豁免
    assert_not_frozen([{"tradingDate": "2026-07-31"}], "scan")  # decision 尾帧安全


def test_baseline_anchor_reads_registry():
    """锚单一事实源（2026-09-25）：baseline_anchor 运行时读注册表 currentGeneration。"""
    from backend.operations.harness_common import baseline_anchor

    gen, anchors = baseline_anchor()
    assert gen == "gen-2026-10-b202610"
    assert anchors["decision"] == 0.1323 and anchors["oos1"] == 0.0862
    assert anchors["oos2"] == 0.0998 and anchors["oos2u"] == 0.0812  # 演练口径，10/3 全月后注册表更新即自动跟随
    assert all(v > 0 for v in anchors.values())


def test_baseline_anchor_missing_generation_raises(tmp_path):
    """currentGeneration 指向不存在的代际时 fail-fast，不许静默用旧锚。"""
    import json as _json
    from unittest import mock as _mock

    import backend.operations.harness_common as hc

    registry = _json.loads(hc._ANCHOR_REGISTRY_PATH.read_text(encoding="utf-8"))
    registry["currentGeneration"] = "gen-not-exist"
    fake = tmp_path / "anchors.json"
    fake.write_text(_json.dumps(registry), encoding="utf-8")
    with _mock.patch.object(hc, "_ANCHOR_REGISTRY_PATH", fake):
        raised = False
        try:
            hc.baseline_anchor()
        except KeyError:
            raised = True
    assert raised, "未知代际应 raise 而非静默返回旧锚"
