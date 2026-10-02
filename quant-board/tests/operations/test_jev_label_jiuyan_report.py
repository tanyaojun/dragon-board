# -*- coding: utf-8 -*-
"""jev 打标 v2 判定门测试：方向语义必须锁（gate_verdict 反转事故教训）+ 判定映射预登记。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_label_jiuyan_report import (
    PHASE3_REF_LIANBAN,
    build_migration,
    direction_consistent_with_phase3,
    driver_group_metrics,
    noul_distribution_metrics,
    noul_effect_metrics,
    quartile,
    verdict,
)


def _rows(labels_pct):
    return [{"label": lab, "nextPct": pct, "nextLianban": pct >= 9.8} for lab, pct in labels_pct]


def test_quartile_method_matches_temp_crowding():
    assert quartile(list(range(1, 21)), 0.25) == 5   # idx=int(0.25*19)=4
    assert quartile(list(range(1, 21)), 0.75) == 15  # idx=14


def test_noul_distribution_expanded_vs_old_chain_shape():
    # 旧链形态：挤在 0.6-0.85，低组 0 → 不展开
    old_like = [0.60, 0.63, 0.65, 0.68, 0.70, 0.72, 0.74, 0.76, 0.78, 0.80, 0.82, 0.85] * 2
    m = noul_distribution_metrics(old_like)
    assert m["expanded"] is False and m["lowShare"] == 0.0
    # 修复形态：低组 ≥15% 且 p75-p25 ≥0.30 → 展开
    fixed = ([0.05, 0.10, 0.15, 0.20] * 5  # 低组 20/40=50%
             + [round(0.35 + i * 0.015, 3) for i in range(20)])
    m2 = noul_distribution_metrics(fixed)
    assert m2["expanded"] is True
    assert m2["iqr"] >= 0.30 and m2["lowShare"] >= 0.15


def test_noul_distribution_insufficient_sample():
    m = noul_distribution_metrics([0.5, 0.7, 0.9])
    assert m["insufficient"] is True and m["expanded"] is False


def test_noul_effect_direction_semantics_locked():
    # diff = mean(high) − mean(low)：高组次日好 → 正差 effectOk；写反即挂（方向锁定）
    hi = [(0.9, 4.0 + i * 0.1) for i in range(10)]
    lo = [(0.1, -1.0 - i * 0.1) for i in range(10)]
    m = noul_effect_metrics(hi + lo)
    assert m["diff"] is not None and m["diff"] > 0
    assert m["effectOk"] is True
    # 方向反转 → 负差，effectOk 必须 False
    m2 = noul_effect_metrics([(n, -p) for n, p in hi + lo])
    assert m2["diff"] < 0 and m2["effectOk"] is False


def test_noul_effect_insufficient_groups():
    m = noul_effect_metrics([(0.9, 3.0)] * 5 + [(0.1, 0.0)] * 3)
    assert m["insufficient"] is True and m["effectOk"] is False


def test_driver_group_metrics():
    # A 组含连板（pct≥9.8 占一半）→ 连板率极差 50pct；两组均值分离 → p 显著
    rows = _rows([("ma_restructure", 3.0 + i * 0.1) for i in range(5)]
                 + [("ma_restructure", 10.0 + i * 0.1) for i in range(5)]
                 + [("capital_flow", -1.0 - i * 0.1) for i in range(10)])
    m = driver_group_metrics(rows)
    assert m["groupOk"] is True and m["spread"] == 50.0
    # 单组 → 不可检验
    m2 = driver_group_metrics(_rows([("policy", 1.0)] * 10))
    assert m2["insufficient"] is True


def test_direction_consistent_with_phase3():
    same = dict(PHASE3_REF_LIANBAN)
    assert direction_consistent_with_phase3(same)["consistent"] is True
    reversed_ = {k: -v for k, v in PHASE3_REF_LIANBAN.items()}
    assert direction_consistent_with_phase3(reversed_)["consistent"] is False


def test_verdict_mapping_pre_registered():
    dist_ok = {"expanded": True, "insufficient": False}
    dist_fail = {"expanded": False, "insufficient": False}
    effect_ok = {"effectOk": True, "insufficient": False}
    effect_bad = {"effectOk": False, "insufficient": False}
    group_ok = {"groupOk": True, "insufficient": False}
    group_bad = {"groupOk": False, "insufficient": False}
    dir_ok = {"consistent": True}
    dir_bad = {"consistent": False}
    # 分布未展开 = REJECT（修复失败），即使其余全过
    assert verdict(dist_fail, effect_ok, group_ok, dir_ok) == "REJECT"
    assert verdict({"insufficient": True}, effect_ok, group_ok, dir_ok) == "REJECT"
    # 全过 = PASS_CANDIDATE
    assert verdict(dist_ok, effect_ok, group_ok, dir_ok) == "PASS_CANDIDATE"
    # 组不显著但方向与全窗一致 → INSUFFICIENT 扩窗，非 REJECT
    assert verdict(dist_ok, effect_ok, group_bad, dir_ok) == "INSUFFICIENT"
    assert verdict(dist_ok, effect_bad, group_bad, dir_ok) == "INSUFFICIENT"
    assert verdict(dist_ok, effect_bad, group_ok, dir_bad) == "INSUFFICIENT"


def test_build_migration_overlap_and_noul_quantiles():
    v1 = [{"tradingDate": "2026-09-05", "code": "600825", "label": "ma_restructure", "matchNoul": 0.8},
          {"tradingDate": "2026-09-05", "code": "000504", "label": "product_event", "matchNoul": 0.7},
          {"tradingDate": "2026-09-04", "code": "999999", "label": "policy", "matchNoul": 0.6}]
    v2 = [{"tradingDate": "2026-09-05", "code": "600825", "label": "ma_restructure", "matchNoul": 0.9},
          {"tradingDate": "2026-09-05", "code": "000504", "label": "concept_stretch", "matchNoul": 0.2}]
    m = build_migration(v1, v2)
    assert m["overlap"] == 2 and m["sameLabel"] == 1 and m["sameShare"] == 0.5
    assert m["cross"]["ma_restructure"]["ma_restructure"] == 1
    assert m["cross"]["product_event"]["concept_stretch"] == 1
    assert m["noulQuantiles"]["v1"] is None  # 重叠对 <10 不给分位，不伪造
