# -*- coding: utf-8 -*-
"""jev 打标 v2 pilot3 判定门测试：六桶方差/守恒/T3 扫描/稳定性/判定映射预登记。"""
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
    # 预估形态：core 110 / scaling 45 / early 65 / equity 27 / concept 9 + 逃生口 9
    depths = [CORE] * 110 + [SCAL] * 45 + [EARLY] * 65 + [EQ] * 27 + [CON] * 9 + [INS] * 9
    m = depth_distribution_metrics(depths)
    assert m["expanded"] is True and m["bucketsWithN5"] == 5
    assert m["maxBucketShare"] == round(110 / 265, 3)


def test_depth_distribution_small_bucket_fails():
    # scaling 桶 n=4 <5 → 不展开
    depths = [CORE] * 110 + [SCAL] * 4 + [EARLY] * 65 + [EQ] * 27 + [CON] * 9 + [INS] * 9
    assert depth_distribution_metrics(depths)["expanded"] is False


def test_depth_distribution_escape_hatch_abuse_fails():
    depths = [CORE] * 90 + [SCAL] * 30 + [EARLY] * 40 + [EQ] * 15 + [CON] * 8 + [INS] * 40
    assert depth_distribution_metrics(depths)["expanded"] is False  # 逃生口 17%>15%


def test_conservation_check():
    depths = [CORE] * 100 + [SCAL] * 45 + [EARLY] * 70 + [EQ] * 27 + [CON] * 9  # new 合计 115
    assert conservation_check(depths)["conserved"] is True  # |115-117|<=5
    depths2 = [CORE] * 100 + [SCAL] * 10 + [EARLY] * 70 + [EQ] * 27 + [CON] * 9  # 80，溢出
    assert conservation_check(depths2)["conserved"] is False


def test_t3_scaling_scan_clean_and_hits():
    labels = [
        {"tradingDate": "2026-09-07", "code": "1", "name": "甲", "catalystDepth": SCAL,
         "narrative": "公司公告已小批量供货，客户加单。"},
        {"tradingDate": "2026-09-07", "code": "2", "name": "乙", "catalystDepth": EARLY,
         "narrative": "网传订单加单（未证实）"},  # early 含 T3 字样不算
        {"tradingDate": "2026-09-07", "code": "3", "name": "丙", "catalystDepth": SCAL,
         "narrative": "市场传闻供货特斯拉（市场消息）"},  # scaling 含 T3 字样 → 命中
    ]
    t3 = t3_scaling_scan(labels)
    assert t3["scanHits"] == 1 and t3["clean"] is False
    assert t3["manualReviewList"][0]["name"] == "丙" and "传闻" in t3["manualReviewList"][0]["markers"]
    clean = t3_scaling_scan(labels[:2])
    assert clean["clean"] is True and clean["scanHits"] == 0


def test_stability_vs_pilot2_with_filter():
    v3 = [{"tradingDate": "d", "code": "1", "catalystDepth": SCAL},
          {"tradingDate": "d", "code": "2", "catalystDepth": CORE}]
    p2 = [{"tradingDate": "d", "code": "1", "catalystDepth": "new_growing_business"},  # 被过滤
          {"tradingDate": "d", "code": "2", "catalystDepth": CORE}]  # 进入对账
    s = stability_vs_pilot2(v3, p2, "catalystDepth", {"core_main_business", "equity_or_affiliate", "concept_assembly"})
    assert s == {"overlap": 1, "sameShare": 1.0}


def test_verdict_mapping_pre_registered():
    depth_ok = {"expanded": True, "insufficient": False}
    depth_fail = {"expanded": False, "insufficient": False}
    cons_ok = {"conserved": True}
    cons_bad = {"conserved": False}
    t3_ok = {"clean": True, "scanHits": 0}
    t3_hit = {"clean": False, "scanHits": 2}
    group_ok = {"groupOk": True, "insufficient": False}
    group_bad = {"groupOk": False, "insufficient": False}
    stab_hi = {"a": {"sameShare": 0.95}}
    stab_lo = {"a": {"sameShare": 0.8}}
    assert verdict(depth_fail, cons_ok, t3_ok, stab_hi, group_ok) == "REJECT"
    assert verdict(depth_ok, cons_bad, t3_ok, stab_hi, group_ok) == "REJECT"
    # T3 扫描命中 → 待人工抽验，不擅自判级
    assert verdict(depth_ok, cons_ok, t3_hit, stab_hi, group_ok) == "PENDING_T3_REVIEW"
    assert verdict(depth_ok, cons_ok, t3_ok, stab_hi, group_ok) == "PASS_CANDIDATE"
    assert verdict(depth_ok, cons_ok, t3_ok, stab_hi, group_bad) == "INSUFFICIENT"
    assert verdict(depth_ok, cons_ok, t3_ok, stab_lo, group_ok) == "INSUFFICIENT"


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
    c = confidence_split(labels)
    assert c == {"n": 2, "mean": 0.55, "lowConfShare": 0.5}
