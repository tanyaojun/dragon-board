# -*- coding: utf-8 -*-
"""jev 打标 v2 pilot4 判定门测试：六桶方差/守恒(±8)/T3 抽验制/freshness/稳定性分层/判定映射 §10。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan_report import (
    PHASE3_REF_LIANBAN,
    bucket_next_day,
    confidence_split,
    conservation_check,
    depth_distribution_metrics,
    direction_consistent_with_phase3,
    driver_group_metrics,
    stability_vs_pilot2,
    t3_scaling_scan,
    verdict,
)

CORE, SCAL, EARLY, EQ, CON, INS = ("core_main_business", "new_business_scaling", "new_business_early",
                                   "equity_or_affiliate", "concept_assembly", "insufficient_evidence")


def _rows(labels_pct):
    return [{"label": lab, "nextPct": pct, "nextLianban": pct >= 9.8} for lab, pct in labels_pct]


def test_depth_distribution_six_buckets_expanded():
    depths = [CORE] * 100 + [SCAL] * 64 + [EARLY] * 70 + [EQ] * 20 + [CON] * 8 + [INS] * 4
    m = depth_distribution_metrics(depths)
    assert m["expanded"] is True and m["bucketsWithN5"] == 5


def test_depth_distribution_small_bucket_fails():
    depths = [CORE] * 100 + [SCAL] * 4 + [EARLY] * 70 + [EQ] * 20 + [CON] * 8 + [INS] * 4
    assert depth_distribution_metrics(depths)["expanded"] is False


def test_conservation_check_pilot3_baseline():
    # 基准=pilot3 两新桶 143（scaling 64 + early 79），±8
    assert conservation_check([SCAL] * 64 + [EARLY] * 79)["conserved"] is True
    assert conservation_check([SCAL] * 30 + [EARLY] * 79)["conserved"] is False  # 109，护栏把样本推出新桶


def test_t3_scan_is_candidate_pool_only():
    labels = [
        {"tradingDate": "d", "code": "1", "name": "甲", "catalystDepth": SCAL, "narrative": "公告已小批量供货"},
        {"tradingDate": "d", "code": "3", "name": "丙", "catalystDepth": SCAL, "narrative": "网传闻加单（未证实）"},
    ]
    t3 = t3_scaling_scan(labels)
    assert t3["scanHits"] == 1 and t3["manualReviewList"][0]["name"] == "丙"
    # 抽验制：扫描命中不再决定判定（由 t3_manual 人工参数决定）


def test_stability_vs_pilot3():
    v4 = [{"tradingDate": "d", "code": "1", "catalystDepth": SCAL},
          {"tradingDate": "d", "code": "2", "catalystDepth": CORE}]
    p3 = [{"tradingDate": "d", "code": "1", "catalystDepth": EARLY},
          {"tradingDate": "d", "code": "2", "catalystDepth": CORE}]
    s = stability_vs_pilot2(v4, p3, "catalystDepth")
    assert s == {"overlap": 2, "sameShare": 0.5}


def test_verdict_mapping_pre_registered_pilot4():
    depth_ok = {"expanded": True, "insufficient": False}
    depth_fail = {"expanded": False, "insufficient": False}
    cons_ok = {"conserved": True}
    cons_bad = {"conserved": False}
    group_ok = {"groupOk": True, "insufficient": False}
    group_bad = {"groupOk": False, "insufficient": False}
    stab_hi = {"driver_type": {"sameShare": 0.93}, "depth_overall": {"sameShare": 0.80}}
    stab_depth_lo = {"driver_type": {"sameShare": 0.93}, "depth_overall": {"sameShare": 0.60}}
    stab_driver_lo = {"driver_type": {"sameShare": 0.85}, "depth_overall": {"sameShare": 0.85}}
    # 门A''/守恒/freshness 任一不过 = REJECT
    assert verdict(depth_fail, cons_ok, True, stab_hi, group_ok, True) == "REJECT"
    assert verdict(depth_ok, cons_bad, True, stab_hi, group_ok, True) == "REJECT"
    assert verdict(depth_ok, cons_ok, True, stab_hi, group_ok, False) == "REJECT"  # freshness 未修好
    # T3 抽验：None=待抽验；False=违规 REJECT
    assert verdict(depth_ok, cons_ok, None, stab_hi, group_ok, True) == "PENDING_T3_REVIEW"
    assert verdict(depth_ok, cons_ok, False, stab_hi, group_ok, True) == "REJECT"
    # 全过 + 门B
    assert verdict(depth_ok, cons_ok, True, stab_hi, group_ok, True) == "PASS_CANDIDATE"
    assert verdict(depth_ok, cons_ok, True, stab_hi, group_bad, True) == "INSUFFICIENT"
    # 稳定性分层：driver>90% 与 depth≥75% 分开判
    assert verdict(depth_ok, cons_ok, True, stab_depth_lo, group_ok, True) == "INSUFFICIENT"
    assert verdict(depth_ok, cons_ok, True, stab_driver_lo, group_ok, True) == "INSUFFICIENT"


def test_driver_group_metrics_and_direction():
    rows = _rows([("ma_restructure", 3.0 + i * 0.1) for i in range(5)]
                 + [("ma_restructure", 10.0 + i * 0.1) for i in range(5)]
                 + [("capital_flow", -1.0 - i * 0.1) for i in range(10)])
    m = driver_group_metrics(rows)
    assert m["groupOk"] is True and m["spread"] == 50.0
    assert direction_consistent_with_phase3(dict(PHASE3_REF_LIANBAN))["consistent"] is True
    assert direction_consistent_with_phase3({"policy": 1.0, "order_earnings": 2.0})["computable"] is False


def test_bucket_next_day_and_confidence():
    rows = [{"catalystDepth": SCAL, "nextPct": 3.0, "nextLianban": True},
            {"catalystDepth": SCAL, "nextPct": 1.0, "nextLianban": False},
            {"catalystDepth": EARLY, "nextPct": -1.0, "nextLianban": False}]
    b = bucket_next_day(rows)
    assert b[SCAL]["nextPctMean"] == 2.0 and b[EARLY]["nextPctMean"] == -1.0
    labels = [{"catalystDepth": SCAL, "catalystDepthProbabilities": {SCAL: 0.8}},
              {"catalystDepth": EARLY, "catalystDepthProbabilities": {EARLY: 0.3}}]
    assert confidence_split(labels) == {"n": 2, "mean": 0.55, "lowConfShare": 0.5}
