# -*- coding: utf-8 -*-
"""jev 打标 v2 重铸试点（pilot2）判定门测试：depth 方差门 + 判定映射预登记 + 稳定性对照。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan_report import (
    PHASE3_REF_LIANBAN,
    bucket_next_day,
    depth_distribution_metrics,
    direction_consistent_with_phase3,
    driver_group_metrics,
    stability_vs_pilot1,
    verdict,
)

CORE, NEW, EQ, CON, INS = ("core_main_business", "new_growing_business",
                           "equity_or_affiliate", "concept_assembly", "insufficient_evidence")


def _rows(labels_pct):
    return [{"label": lab, "nextPct": pct, "nextLianban": pct >= 9.8} for lab, pct in labels_pct]


def test_depth_distribution_expanded():
    # 手判预估形态：50%/36%/7%/7% + 逃生口少量 → 展开
    depths = ([CORE] * 50 + [NEW] * 36 + [EQ] * 7 + [CON] * 7)
    m = depth_distribution_metrics(depths)
    assert m["expanded"] is True
    assert m["maxBucketShare"] == 0.5 and m["substantiveBucketsWithN5"] == 4


def test_depth_distribution_collapsed_like_old_noul():
    # 旧 noul 塌缩形态：单实质桶 >70% → 不展开
    m = depth_distribution_metrics([CORE] * 80 + [NEW] * 15 + [EQ] * 3 + [CON] * 2)
    assert m["expanded"] is False and m["maxBucketShare"] == 0.8


def test_depth_distribution_escape_hatch_abuse_fails():
    # 逃生口 >15% = 滥用 → 不展开（fail-visible 不得成为逃避判读的出口）
    depths = [CORE] * 40 + [NEW] * 20 + [EQ] * 8 + [CON] * 8 + [INS] * 24
    assert depth_distribution_metrics(depths)["expanded"] is False


def test_depth_distribution_insufficient_sample():
    assert depth_distribution_metrics([CORE] * 10 + [NEW] * 5)["insufficient"] is True


def test_driver_group_metrics():
    # A 组含连板（pct≥9.8 占一半）→ 连板率极差 50pct；两组均值分离 → p 显著
    rows = _rows([("ma_restructure", 3.0 + i * 0.1) for i in range(5)]
                 + [("ma_restructure", 10.0 + i * 0.1) for i in range(5)]
                 + [("capital_flow", -1.0 - i * 0.1) for i in range(10)])
    m = driver_group_metrics(rows)
    assert m["groupOk"] is True and m["spread"] == 50.0
    m2 = driver_group_metrics(_rows([("policy", 1.0)] * 10))
    assert m2["insufficient"] is True


def test_direction_consistent_with_phase3():
    assert direction_consistent_with_phase3(dict(PHASE3_REF_LIANBAN))["consistent"] is True
    reversed_ = {k: -v for k, v in PHASE3_REF_LIANBAN.items()}
    assert direction_consistent_with_phase3(reversed_)["consistent"] is False


def test_verdict_mapping_pre_registered():
    depth_ok = {"expanded": True, "insufficient": False}
    depth_fail = {"expanded": False, "insufficient": False}
    group_ok = {"groupOk": True, "insufficient": False}
    group_bad = {"groupOk": False, "insufficient": False}
    dir_ok = {"consistent": True}
    dir_bad = {"consistent": False}
    # 门A 不过 = REJECT（重铸失败），即使门B 过
    assert verdict(depth_fail, group_ok, dir_ok) == "REJECT"
    assert verdict({"insufficient": True}, group_ok, dir_ok) == "REJECT"
    # 双门全过 = PASS_CANDIDATE
    assert verdict(depth_ok, group_ok, dir_ok) == "PASS_CANDIDATE"
    # 门A 过门B 不过 → INSUFFICIENT（方向一致与否都非 REJECT）
    assert verdict(depth_ok, group_bad, dir_ok) == "INSUFFICIENT"
    assert verdict(depth_ok, group_bad, dir_bad) == "INSUFFICIENT"


def test_stability_vs_pilot1():
    v2 = [{"tradingDate": "2026-09-07", "code": "600825", "label": "ma_restructure", "freshness": "continuing"},
          {"tradingDate": "2026-09-07", "code": "000504", "label": "product_event", "freshness": "continuing"}]
    p1 = [{"tradingDate": "2026-09-07", "code": "600825", "label": "ma_restructure", "freshness": "fresh_catalyst"},
          {"tradingDate": "2026-09-07", "code": "000504", "label": "concept_stretch", "freshness": "continuing"},
          {"tradingDate": "2026-09-08", "code": "999999", "label": "policy", "freshness": "continuing"}]
    s = stability_vs_pilot1(v2, p1, "label")
    assert s == {"overlap": 2, "sameShare": 0.5}
    s2 = stability_vs_pilot1(v2, p1, "freshness")
    assert s2 == {"overlap": 2, "sameShare": 0.5}


def test_bucket_next_day():
    rows = [{"catalystDepth": CORE, "nextPct": 2.0, "nextLianban": True},
            {"catalystDepth": CORE, "nextPct": 0.0, "nextLianban": False},
            {"catalystDepth": CON, "nextPct": -1.0, "nextLianban": False},
            {"catalystDepth": None, "nextPct": 5.0, "nextLianban": False}]
    b = bucket_next_day(rows)
    assert b[CORE] == {"n": 2, "nextPctMean": 1.0, "lianban": 50.0}
    assert b[CON]["nextPctMean"] == -1.0
    assert None not in b  # 未打深的标签不进桶
