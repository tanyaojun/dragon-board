# -*- coding: utf-8 -*-
"""jev 打标判定门测试：六桶方差/T3 抽验制/freshness/门B（全量语义，守恒与稳定性为已退役的 pilot 专属门）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan_report import (
    PHASE3_REF_LIANBAN,
    bucket_next_day,
    confidence_split,
    depth_distribution_metrics,
    direction_consistent_with_phase3,
    driver_group_metrics,
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


def test_t3_scan_is_candidate_pool_only():
    labels = [
        {"tradingDate": "d", "code": "1", "name": "甲", "catalystDepth": SCAL, "narrative": "公告已小批量供货"},
        {"tradingDate": "d", "code": "3", "name": "丙", "catalystDepth": SCAL, "narrative": "网传闻加单（未证实）"},
    ]
    t3 = t3_scaling_scan(labels)
    assert t3["scanHits"] == 1 and t3["manualReviewList"][0]["name"] == "丙"
    # 抽验制：扫描命中不再决定判定（由 t3_manual 人工参数决定）


def test_verdict_mapping_full_mode():
    # 全量语义：门A' 展开/freshness/T3/门B
    depth_ok = {"expanded": True, "insufficient": False}
    depth_fail = {"expanded": False, "insufficient": False}
    group_ok = {"groupOk": True, "insufficient": False}
    group_bad = {"groupOk": False, "insufficient": False}
    assert verdict(depth_fail, True, group_ok, True) == "REJECT"
    assert verdict(depth_ok, True, group_ok, False) == "REJECT"  # freshness 未修好
    assert verdict(depth_ok, None, group_ok, True) == "PENDING_T3_REVIEW"
    assert verdict(depth_ok, False, group_ok, True) == "REJECT"
    assert verdict(depth_ok, True, group_ok, True) == "PASS_CANDIDATE"
    assert verdict(depth_ok, True, group_bad, True) == "INSUFFICIENT"


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
