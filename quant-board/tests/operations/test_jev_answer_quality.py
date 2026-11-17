# -*- coding: utf-8 -*-
"""判答质量观测（C1 零调用替代审计）测试——纯假 collection，零网络零模型零真调。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_answer_quality as Q


class FakeCol:
    def __init__(self, docs):
        self.docs = docs

    def find(self, query=None):
        assert not query, "报告全扫描 on-demand，不下推查询"
        return list(self.docs)


class FakeDb:
    def __init__(self, **cols):
        self.cols = cols

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol([]))


def _doc(_id, hash_, version, ammo, answers, status="ok", kind="leader"):
    return {"_id": _id, "status": status, "docKind": kind,
            "questionSetHash": hash_, "questionSetVersion": version,
            "ammoVersion": ammo, "answers": answers}


def test_flags_below_threshold_and_segments_by_generation():
    """max_prob<0.6 入桶（西陇 0.57/广百 0.50 实证校准）；按 hash 代际分段；
    同 hash 跨 AMMO 代 ammoVersions 聚合；边界 0.6 不入桶。"""
    theme = [
        _doc("2026-11-17:002584", "h18", "v18", "2026-11-18a", {
            "leader_catalyst_hardness": {"choice": "hard_fact", "confidence": 0.57,
                                         "probabilities": {"hard_fact": 0.57, "sector_story": 0.26, "soft_meme": 0.17}},
            "leader_nextday_continue": {"choice": "low_25_45", "confidence": 0.95,
                                        "probabilities": {"low_25_45": 0.95, "mid_45_65": 0.05}}}),
        _doc("2026-11-18:002584", "h18", "v18", "2026-11-18b", {
            "leader_headroom": {"choice": "space_1", "confidence": 0.6,
                                "probabilities": {"space_1": 0.6, "peak": 0.4}}}),
        _doc("2026-11-17:board:X", "h18", "v18", "2026-11-18a",
             {"theme_continuation": {"choice": "weak_extend", "probabilities": {"weak_extend": 0.59}}},
             kind="sector"),
        _doc("2026-11-16:000001", "h17", "v17", "2026-11-17b",
             {"leader_nextday_continue": {"choice": "mid_45_65", "probabilities": {"mid_45_65": 0.8}}}),
        _doc("2026-11-17:000002", "h18", "v18", "2026-11-18a",
             {"leader_nextday_continue": {"choice": "mid_45_65", "probabilities": {"mid_45_65": 0.9}}},
             status="degraded"),   # degraded 不进质量统计
    ]
    auction = [
        _doc("2026-11-17:002187", "ha5", "vA5", "2026-11-18a", {
            "auction_leader_seal_today": {"choice": "mid_45_65", "confidence": 0.5,
                                          "probabilities": {"mid_45_65": 0.5, "low_25_45": 0.39, "high_ge65": 0.11}}}),
    ]
    db = FakeDb(**{Q.COLLECTIONS[0]: FakeCol(theme), Q.COLLECTIONS[1]: FakeCol(auction)})
    rep = Q.low_confidence_report(db)
    assert rep["totalAnswers"] == 6 and rep["flagged"] == 3   # 0.57/0.59/0.50；0.6 边界不入桶
    g18 = rep["generations"]["h18"]
    assert g18["ammoVersions"] == ["2026-11-18a", "2026-11-18b"]
    assert g18["totalAnswers"] == 4 and g18["flagged"] == 2
    assert g18["flagRate"] == 0.5
    row = next(r for r in g18["rows"] if r["question"] == "leader_catalyst_hardness")
    assert row["maxProb"] == 0.57 and row["margin"] == 0.31 and row["choice"] == "hard_fact"
    assert rep["generations"]["h17"]["flagged"] == 0
    assert rep["generations"]["ha5"]["rows"][0]["margin"] == 0.11
    assert all(r["id"] != "2026-11-17:000002" for g in rep["generations"].values() for r in g["rows"])


def test_date_filter_and_confidence_fallback():
    """日期闭区间过滤（_id 前缀）；缺 probabilities 回退 confidence（margin=None 不编造）；
    非 dict 判答/缺概率且缺 confidence → 跳过不崩。"""
    docs = [
        _doc("2026-11-10:000001", "h", "v", "a", {"q": {"choice": "x", "confidence": 0.4}}),
        _doc("2026-11-12:000001", "h", "v", "a", {"q": {"choice": "x", "confidence": 0.4}}),
        _doc("2026-11-14:000001", "h", "v", "a", {"q": {"choice": "x", "confidence": 0.4}}),
        _doc("2026-11-12:000002", "h", "v", "a", {"q": "not-a-dict", "q2": {"choice": "y"}}),
    ]
    db = FakeDb(**{Q.COLLECTIONS[0]: FakeCol(docs)})
    rep = Q.low_confidence_report(db, date_start="2026-11-12", date_end="2026-11-12")
    assert rep["totalAnswers"] == 1 and rep["flagged"] == 1
    row = rep["generations"]["h"]["rows"][0]
    assert row["maxProb"] == 0.4 and row["margin"] is None
    rep_all = Q.low_confidence_report(db)
    assert rep_all["totalAnswers"] == 3   # 三日各 1；not-a-dict/缺值跳过


def test_empty_db_and_custom_threshold():
    db = FakeDb()
    rep = Q.low_confidence_report(db)
    assert rep["totalAnswers"] == 0 and rep["flagged"] == 0 and rep["flagRate"] is None
    assert rep["generations"] == {}
    docs = [_doc("2026-11-12:000001", "h", "v", "a",
                 {"q": {"choice": "x", "probabilities": {"x": 0.7, "y": 0.3}}})]
    db2 = FakeDb(**{Q.COLLECTIONS[0]: FakeCol(docs)})
    assert Q.low_confidence_report(db2, threshold=0.8)["flagged"] == 1
    assert Q.low_confidence_report(db2, threshold=0.7)["flagged"] == 0   # 严格小于


def test_non_numeric_and_bool_probabilities_skipped_not_fabricated():
    """review 覆盖 nit：bool/非数概率值跳过不崩；全非法→回退 confidence；
    两者均缺→该题跳过（不编造 0，fail-visible）。"""
    docs = [_doc("2026-11-12:000001", "h", "v", "a", {
        "q1": {"choice": "x", "probabilities": {"x": True, "y": "0.9"}, "confidence": 0.4},
        "q2": {"choice": "y", "probabilities": {"x": None, "y": float("nan")}},
        "q3": {"choice": "z", "probabilities": {"x": 0.2, "y": True, "z": "bad"}},
    })]
    db = FakeDb(**{Q.COLLECTIONS[0]: FakeCol(docs)})
    rep = Q.low_confidence_report(db)
    assert rep["totalAnswers"] == 2   # q1 回退 confidence 0.4；q3 取合法值 0.2；q2 全非法跳过
    assert rep["flagged"] == 2
    rows = {r["question"]: r for r in rep["generations"]["h"]["rows"]}
    assert rows["q1"]["maxProb"] == 0.4 and rows["q1"]["margin"] is None
    assert rows["q3"]["maxProb"] == 0.2 and rows["q3"]["margin"] is None
