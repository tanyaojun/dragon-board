# -*- coding: utf-8 -*-
"""jev_confidence_landscape 统计层测试（2026-10-11）：纯函数零 IO，零 jev 调用。

覆盖：分位数/直方图标准差、六集合提取器分流（sentiment slot/eod、driver 个股/Q5、
relay choice/score 字段型）、版本段隔离、degraded 排除、逃生/骑墙/结构缺失计数。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_SPEC = importlib.util.spec_from_file_location(
    "jev_confidence_landscape",
    Path(__file__).resolve().parents[2] / "scripts" / "jev_confidence_landscape.py")
land = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(land)


# ── 纯函数 ──

def test_pct_basic_and_empty():
    assert land.pct([], 50) is None
    assert land.pct([1.0, 2.0, 3.0, 4.0], 50) == 2.5
    assert land.pct([0.1, 0.9], 90) == 0.82  # 0.1+0.8*0.9


def test_hist_std_ten_anchor_and_degenerate():
    # 全概率集中在第 9 档 → std=0；均匀 10 档 → std=sqrt(8.25)≈2.872
    prob = {str(i): 0.0 for i in range(10)}
    prob["9"] = 1.0
    assert land.hist_std(prob) == 0.0
    even = {str(i): 0.1 for i in range(10)}
    assert abs(land.hist_std(even) - 2.87) < 0.01
    # SCORE_ANCHORS_10 文字锚（"0","11",...）同适用：按数值排序定档序
    text_anchor = {"0": 0.0, "11": 0.0, "22": 1.0}
    assert land.hist_std(text_anchor) == 0.0
    assert land.hist_std({}) is None
    assert land.hist_std({"a": 1.0}) is None  # 单档无离散


# ── 提取器分流 ──

def _slot_doc(answers=None, version="v2.5"):
    return {"kind": "slot", "status": "ok", "questionSetVersion": version,
            "answers": answers if answers is not None else {}}


def test_extract_sentiment_splits_by_kind():
    slot_q = {"frame_stage": {"type": "choice", "confidence": 0.51},
              "temperature": {"type": "score", "confidence": 0.58,
                              "probabilities": {"0": 0.5, "9": 0.5}}}
    out = land._extract_sentiment(_slot_doc(slot_q))
    assert set(out) == {"frame_stage", "temperature"}
    eod = land._extract_sentiment({"kind": "eod", "answers": {
        "day_stage": {"type": "choice"}, "day_pattern": {"type": "choice"}}})
    assert set(eod) == {"day_stage", "day_pattern"}


def test_extract_driver_individual_vs_phase_band():
    stock_doc = {"origin": "driver_label_jiuyan_v3_pilot",
                 "label": "policy", "driverProbabilities": {"policy": 0.9},
                 "catalystDepth": "core_main_business", "catalystDepthProbabilities": {"core_main_business": 0.8},
                 "freshness": "fresh_catalyst",  # runner 未落 probabilities
                 "buySideLogic": "independent_catalyst", "buySideProbabilities": {"independent_catalyst": 0.7}}
    out = land._extract_driver(stock_doc)
    assert set(out) == {"driver_type", "catalyst_depth", "catalyst_freshness", "buy_side_logic"}
    assert out["catalyst_freshness"]["probabilities"] is None
    assert out["driver_type"]["confidence"] is None  # 字段型链 confidence 结构性缺失
    phase_doc = {"origin": "phase_band_daily", "phaseBand": "strong_ge60",
                 "phaseBandProbabilities": {"strong_ge60": 0.85}}
    assert set(land._extract_driver(phase_doc)) == {"phase_band"}


def test_extract_relay_choice_and_score_fields():
    doc = {"relayPhase": "relay_heat", "relayPhaseProbabilities": {"relay_heat": 0.8},
           "relayMomentum": "holding",          # probabilities 未落库
           "relayIndex": 62.5, "leaderStrength": 55.0}
    out = land._extract_relay(doc)
    assert out["relay_phase"]["probabilities"] == {"relay_heat": 0.8}
    assert out["relay_momentum"]["probabilities"] is None
    assert out["relay_index"]["type"] == "score" and out["relay_index"]["score"] == 62.5


# ── P0-2 后 blob 优先路径（新文档 answers 原样包） ──

def test_blob_or_field_prefers_answers_blob_with_confidence():
    doc = {"answers": {"zhaban_cause": {"type": "choice", "choice": "chase_fail",
                                        "confidence": 0.83,
                                        "probabilities": {"chase_fail": 0.83}}},
           "zhabanCause": "chase_fail", "zhabanCauseProbabilities": {"chase_fail": 0.83}}
    v = land.blob_or_field(doc, "zhaban_cause", "zhabanCause", "zhabanCauseProbabilities")
    assert v["confidence"] == 0.83  # blob 直读带 confidence（字段提取给不了）


def test_blob_missing_key_falls_back_to_fields():
    doc = {"answers": {"other_q": {"choice": "x"}},  # partial_answers：缺本题
           "zhabanCause": "chase_fail", "zhabanCauseProbabilities": {"chase_fail": 0.7}}
    v = land.blob_or_field(doc, "zhaban_cause", "zhabanCause", "zhabanCauseProbabilities")
    assert v["choice"] == "chase_fail" and v["confidence"] is None


def test_field_view_reads_optional_conf_field():
    doc = {"stockPhasePosition": "start", "stockPhaseProbabilities": {"start": 0.7},
           "stockPhaseConfidence": 0.9}
    v = land.field_view(doc, "stockPhasePosition", "stockPhaseProbabilities", "stockPhaseConfidence")
    assert v["confidence"] == 0.9
    assert land.field_view({"stockPhasePosition": "start"}, "stockPhasePosition", None,
                           "stockPhaseConfidence")["confidence"] is None


def test_score_blob_carries_histogram_for_hstd():
    doc = {"answers": {"relay_index": {"type": "score", "score": 6.2, "confidence": 0.71,
                                       "legend": {str(i): 1 for i in range(10)},
                                       "probabilities": {str(i): 0.1 for i in range(10)}}},
           "relayIndex": 68.9}
    out = land._extract_relay(doc)
    v = out["relay_index"]
    assert v["type"] == "score" and v["confidence"] == 0.71
    # review P1：blob 锚点期望按 legend 归一到 0-100（6.2/9*100=68.9）与顶层字段同标尺
    assert v["score"] == 68.9
    assert land.hist_std(v["probabilities"]) is not None  # 直方图可测 hstd
    # legend 缺失 → 归一分如实 None（不伪造）
    v2 = land.score_blob_or_field(
        {"answers": {"relay_index": {"type": "score", "score": 6.2}}}, "relay_index", "relayIndex")
    assert v2["score"] is None


def test_scan_projection_includes_stock_phase_confidence():
    """review P1：投影漏 stockPhaseConfidence 会令 $set 路径置信度统计恒缺失（fake db 锁定）。"""
    captured = {}

    class _CapCol:
        def __init__(self):
            self.docs = []

        def find(self, query, projection=None):
            captured["projection"] = projection
            return iter(self.docs)

    class _CapDb:
        def __init__(self, cols):
            self.cols = cols

        def __getitem__(self, name):
            return self.cols.get(name, _CapCol())

    db = _CapDb({spec["collection"]: _CapCol() for spec in land.COLLECTION_SPECS})
    land.scan_collection(db, land.COLLECTION_SPECS[1])
    proj = captured["projection"] or {}
    assert proj.get("stockPhaseConfidence") == 1
    assert proj.get("stockPhaseProbabilities") == 1


def test_extract_driver_blob_covers_all_questions():
    doc = {"answers": {
        "driver_type": {"type": "choice", "choice": "policy", "confidence": 0.66},
        "catalyst_depth": {"type": "choice", "choice": "core_main_business", "confidence": 0.8},
        "catalyst_freshness": {"type": "choice", "choice": "fresh_catalyst", "confidence": 0.9,
                               "probabilities": {"fresh_catalyst": 0.9}},
        "buy_side_logic": {"type": "choice", "choice": "independent_catalyst", "confidence": 0.7},
        "stock_phase_position": {"type": "choice", "choice": "start", "confidence": 0.93}}}
    out = land._extract_driver(doc)
    assert set(out) == {"driver_type", "catalyst_depth", "catalyst_freshness",
                        "buy_side_logic", "stock_phase_position"}
    assert all(v["confidence"] is not None for v in out.values())


# ── accumulate：版本隔离 / degraded 排除 / 计数口径 ──

def test_accumulate_version_segments_and_degraded():
    docs = [
        _slot_doc({"frame_stage": {"type": "choice", "choice": "ferment", "confidence": 0.8,
                                   "probabilities": {"ferment": 0.8, "ice": 0.2}}}, "v2.4"),
        _slot_doc({"frame_stage": {"type": "choice", "choice": "ice", "confidence": 0.5,
                                   "probabilities": {"ferment": 0.45, "ice": 0.55}}}, "v2.5"),
        {"kind": "slot", "status": "degraded", "questionSetVersion": "v2.5", "answers": {}},
        _slot_doc({"frame_stage": {"type": "choice", "choice": "insufficient_evidence",
                                   "confidence": 0.4,
                                   "probabilities": {"insufficient_evidence": 0.45, "ice": 0.55}}},
                  version=None),
    ]
    res = land.accumulate(docs, land._extract_sentiment)
    assert res["counters"]["ok"] == 3 and res["counters"]["not_ok"] == 1
    assert ("v2.4", "frame_stage") in res["buckets"] and ("v2.5", "frame_stage") in res["buckets"]
    # 缺版本戳文档归 (no-stamp) 段，不混入任何现行代
    assert ("(no-stamp)", "frame_stage") in res["buckets"]
    b = res["buckets"]["(no-stamp)", "frame_stage"]
    s = land.summarize_bucket(b)
    assert s["n"] == 1 and s["escape_pct"] == 100.0
    assert s["top_lt060_pct"] == 100.0 and s["conf_lt060_pct"] == 100.0


def test_accumulate_no_conf_no_prob_counted_fail_visible():
    docs = [{"origin": "phase_band_daily", "status": "ok",
             "phaseBand": "weak_40_60", "phaseBandProbabilities": {"weak_40_60": 0.55}}]
    b = land.accumulate(docs, land._extract_driver)["buckets"]["(no-stamp)", "phase_band"]
    s = land.summarize_bucket(b)
    assert s["no_conf_n"] == 1 and s["no_prob_n"] == 0
    assert s["top_lt060_pct"] == 100.0  # top 0.55 < 0.6 骑墙


def test_render_markdown_contains_all_collections():
    stats = {spec["collection"]: {"buckets": {}, "counters": {"ok": 1, "not_ok": 0, "not_ok_detail": {}}}
             for spec in land.COLLECTION_SPECS}
    md = land.render_markdown(stats)
    for spec in land.COLLECTION_SPECS:
        assert spec["collection"] in md
    assert "hstdP50" in md and "conf<60%" in md
