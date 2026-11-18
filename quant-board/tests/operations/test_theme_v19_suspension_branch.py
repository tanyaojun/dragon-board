# -*- coding: utf-8 -*-
"""v19 停牌分支回归（2026-11-18 用户裁决 A，天普停牌案题面层）。

题面：六题停牌分支键控「今日停牌」叙事措辞（续板/人气锚=复牌日；硬度/空间/身位=
停牌前口径；板块延续题停牌≠断板），options 零改动（冻结断言）。
结算：续板结局锚=复牌日（个股轴，outcomeMeta.anchorKind=resume），复牌日不可考/
未到 → pending 自愈；T+2 溢价按逐档锚推导；长停牌 pending 日并入结算目标日。
全 mock，零 jev 真调（AGENTS §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.analysis.hotlist import theme_leader_ammo as A
from backend.operations import schedule as S
import scripts.theme_leader_pilot_eval as pe

D = "2026-11-17"
AXIS = ["2026-11-13", "2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20"]


# ── 题面：停牌分支在场 + options 冻结 ──

def test_v19_suspension_branch_present_in_six_questions():
    q = A.QUESTIONS_THEME_LEADER
    markers = {
        "leader_nextday_continue": "⑤叙事标注待判龙头**今日停牌**时：本题=**复牌日**",
        "leader_headroom": "⑥叙事标注今日停牌时：空间判断以**停牌前高度**",
        "leader_catalyst_hardness": "⑤叙事标注今日停牌时：本题判**最近一次涨停",
        "leader_seat_durability": "⑤叙事标注今日停牌时：身位按停牌前梯队/热度事实",
        "leader_rebound_popularity": "⑥叙事标注今日停牌时：本题=**复牌日**反包的人气",
    }
    for key, mk in markers.items():
        assert mk in q[key]["instructions"], key
    assert "个股停牌非板块断板事实：" in q["theme_continuation"]["instructions"]
    cont = q["leader_nextday_continue"]["instructions"]
    assert "本题=**复牌日**" in cont and "不得作判答锚" in cont
    assert "confidence ≤0.6" in cont, "复牌日不可考降置信门"
    head = q["leader_headroom"]["instructions"]
    assert "停牌前高度" in head and "不得仅因停牌判 peak" in head
    pop = q["leader_rebound_popularity"]["instructions"]
    assert "不得" in pop and "停牌日（无交易）的封板事实" in pop
    # 红线：投喂文本禁版本号/开发标签（§1.2-8，用户 2026-11-18 裁决）
    import re
    for key, qq in q.items():
        for txt in [qq["instructions"], *qq["criteria"].values()]:
            assert not re.search(r"（v\d", txt), f"{key} 投喂文本含版本号"
            assert not re.search(r"\d{4}-\d{2}-\d{2}[a-z]", txt), f"{key} 投喂文本含 AMMO 版本号"
            assert "停牌分支" not in txt and "语料源" not in txt, f"{key} 投喂文本含开发语义"


def test_v19_options_frozen_identical_to_v18_design():
    """options 零改动（换代只动 instructions 判据锚，档位集合冻结）。"""
    frozen = {
        "theme_speculation_depth": ("igniting", "fermenting", "climax", "ebbing", "insufficient"),
        "theme_continuation": ("strong_extend", "weak_extend", "ending", "insufficient"),
        "leader_nextday_continue": ("high_ge65", "mid_45_65", "low_25_45", "verylow_lt25", "insufficient"),
        "leader_headroom": ("space_2plus", "space_1", "peak", "insufficient"),
        "leader_catalyst_hardness": ("hard_fact", "sector_story", "soft_meme", "insufficient"),
        "leader_seat_durability": ("core_seat", "contested_seat", "relay_seat", "insufficient"),
        "leader_rebound_popularity": ("dragon_confirm", "one_day_pop", "insufficient"),
    }
    for key, opts in frozen.items():
        assert tuple(A.QUESTIONS_THEME_LEADER[key]["criteria"]) == opts, key


# ── 结算锚：复牌日个股轴 ──

def _axis_fn(db, s, e):
    return [d for d in AXIS if s <= d <= e]


class _Col:
    def __init__(self, docs):
        self.docs = docs
        self.updates: dict = {}

    def find(self, query, *a, **k):
        if query.get("docKind") == "sector":
            return []
        return list(self.docs)

    def update_one(self, q, upd, *a, **k):
        self.updates[q["_id"]] = upd["$set"]


class _Db:
    def __init__(self, col):
        self.col = col

    def __getitem__(self, k):
        return self.col


def _doc(_id, code, structure):
    return {"_id": _id, "code": code, "name": code, "status": "ok",
            "board": "半导体", "structure": structure, "baselineMeta": {}}


def _stub_eval(monkeypatch, col, sealed_by_day):
    monkeypatch.setattr(pe, "trading_dates", _axis_fn)
    monkeypatch.setattr(pe, "sealed_and_info",
                        lambda db, d, ds=None: (sealed_by_day.get(d, set()), {},
                                                {"thsPoolFound": True}))
    monkeypatch.setattr(pe, "build_rows", lambda db, s, e: {"rows": []})
    monkeypatch.setattr(pe, "_next_day_board_n", lambda db, b, d: None)


def test_resume_anchor_date_first_trading_day_on_or_after_resume(monkeypatch):
    monkeypatch.setattr(pe, "trading_dates", _axis_fn)
    assert pe._resume_anchor_date(None, D, "2026-11-19") == "2026-11-19"
    assert pe._resume_anchor_date(None, D, "2026-11-18") == "2026-11-18"
    assert pe._resume_anchor_date(None, D, None) is None
    monkeypatch.setattr(pe, "trading_dates", lambda db, s, e: [d for d in AXIS[:4] if s <= d <= e])
    assert pe._resume_anchor_date(None, D, "2026-11-19") is None, "复牌日不在轴→pending"


def test_evaluate_suspension_settles_on_resume_anchor(monkeypatch):
    col = _Col([_doc("d1", "605255", {"dayStatus": "suspended", "resumeDate": "2026-11-19"}),
                _doc("d2", "600261", {"dayStatus": "sealed"})])
    _stub_eval(monkeypatch, col, {"2026-11-18": set(), "2026-11-19": {"605255"}})
    pe.evaluate(_Db(col), D, write_outcome=True)
    u1, u2 = col.updates["d1"], col.updates["d2"]
    assert u1["outcomeSealedNextDay"] is True, "复牌日封板→续板 True（市场轴 11-18 无交易不得误判未封）"
    assert u1["outcomeMeta"]["nextDate"] == "2026-11-19"
    assert u1["outcomeMeta"]["anchorKind"] == "resume"
    assert u1["outcomeMeta"]["resumeDate"] == "2026-11-19"
    assert u2["outcomeSealedNextDay"] is False, "非停牌档市场轴口径不变"
    assert u2["outcomeMeta"]["nextDate"] == "2026-11-18"
    assert u2["outcomeMeta"]["anchorKind"] == "market_next"


def test_resume_anchor_malformed_date_pending_not_crash(monkeypatch):
    """review M3：上游日期串非 ISO 形态→不可考 pending，不得击穿整日结算。"""
    monkeypatch.setattr(pe, "trading_dates", _axis_fn)
    assert pe._resume_anchor_date(None, D, "20261119") is None
    assert pe._resume_anchor_date(None, D, "2026/11/19") is None
    col = _Col([_doc("d1", "605255", {"dayStatus": "suspended", "resumeDate": "20261119"})])
    _stub_eval(monkeypatch, col, {"2026-11-18": {"605255"}})
    out = pe.evaluate(_Db(col), D, write_outcome=True)
    assert col.updates["d1"]["outcomeSealedNextDay"] is None, "畸形复牌日→pending 不猜市场轴"
    assert any("605255" in s for s in out["skipped"])


def test_evaluate_suspension_no_resume_date_pending(monkeypatch):
    col = _Col([_doc("d1", "605255", {"dayStatus": "suspended", "resumeDate": None})])
    _stub_eval(monkeypatch, col, {"2026-11-18": {"605255"}})
    out = pe.evaluate(_Db(col), D, write_outcome=True)
    u1 = col.updates["d1"]
    assert u1["outcomeSealedNextDay"] is None, "复牌日不可考→pending，不猜市场轴"
    assert u1["outcomeMeta"]["anchorKind"] == "resume"
    assert u1["outcomeMeta"]["nextDate"] is None
    assert any("复牌日不可考" in s for s in out["skipped"])


def test_evaluate_suspension_resume_not_on_axis_pending(monkeypatch):
    col = _Col([_doc("d1", "605255", {"dayStatus": "suspended", "resumeDate": "2026-11-19"})])
    _stub_eval(monkeypatch, col, {"2026-11-18": {"605255"}})
    monkeypatch.setattr(pe, "trading_dates", lambda db, s, e: [d for d in AXIS[:4] if s <= d <= e])
    out = pe.evaluate(_Db(col), D, write_outcome=True)
    assert col.updates["d1"]["outcomeSealedNextDay"] is None
    assert any("复牌锚日" in s for s in out["skipped"])


def test_settle_day2_uses_per_doc_resume_anchor(monkeypatch):
    monkeypatch.setattr(pe, "trading_dates", _axis_fn)
    col = _Col([
        {**_doc("d1", "605255", {"dayStatus": "suspended", "resumeDate": "2026-11-19"}),
         "outcomeSealedNextDay": True, "outcomeMeta": {"nextDate": "2026-11-19"}},
        {**_doc("d2", "600261", {"dayStatus": "sealed"}),
         "outcomeSealedNextDay": True, "outcomeMeta": {"nextDate": "2026-11-18"}},
    ])
    bars = {"2026-11-18": {"open": 10.0, "close": 10.0},
            "2026-11-19": {"open": 11.0, "close": 11.0},
            "2026-11-20": {"open": 11.5, "close": 12.0}}
    out = pe.settle_day2(_Db(col), D, fetcher=lambda code: bars)
    assert out["settled"] == 2 and not out["errors"]
    assert col.updates["d1"]["outcomeDay2"]["date"] == "2026-11-20", "复牌锚 T+2=11-20"
    assert col.updates["d1"]["outcomeDay2"]["openPct"] == pytest.approx(4.55), "溢价基=复牌日收盘"
    assert col.updates["d2"]["outcomeDay2"]["date"] == "2026-11-19", "市场轴 T+2 口径不变"
    assert col.updates["d2"]["outcomeDay2"]["openPct"] == pytest.approx(10.0)


def test_settle_day2_resume_axis_t2_not_reached_pending(monkeypatch):
    monkeypatch.setattr(pe, "trading_dates", lambda db, s, e: [d for d in AXIS[:5] if s <= d <= e])
    col = _Col([{**_doc("d1", "605255", {"dayStatus": "suspended"}),
                 "outcomeSealedNextDay": True, "outcomeMeta": {"nextDate": "2026-11-19"}}])
    out = pe.settle_day2(_Db(col), D, fetcher=lambda code: {})
    assert out["settled"] == 0 and out["pending"] == 1, "复牌轴 T+2 未到→pending 自愈"
    assert "d1" not in col.updates


# ── 长停牌自愈：结算目标日并入 ──

def test_theme_settle_days_unions_suspension_pending():
    class _C:
        def distinct(self, field, query):
            assert query["structure.dayStatus"] == "suspended"
            assert query["outcomeSealedNextDay"] is None
            return ["2026-10-20", "2026-11-17", None]
    days = S._theme_settle_days(None, _C(), "2026-11-18", 5,
                                lambda db, s, e: ["2026-11-16", "2026-11-17"])
    assert days == ["2026-10-20", "2026-11-16", "2026-11-17"], "长停牌 pending 日不丢自愈"


def test_theme_settle_days_cap_bounds_subprocess_batch():
    class _C:
        def distinct(self, field, query):
            return [f"2026-01-{i:02d}" for i in range(1, 29)] + \
                   [f"2026-02-{i:02d}" for i in range(1, 29)] + \
                   [f"2026-03-{i:02d}" for i in range(1, 29)]
    days = S._theme_settle_days(None, _C(), "2026-11-18", 5, lambda db, s, e: [])
    assert len(days) == 60, "上限 60 约束 subprocess 批量"
