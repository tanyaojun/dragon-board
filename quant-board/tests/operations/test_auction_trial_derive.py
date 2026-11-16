# -*- coding: utf-8 -*-
"""试盘字段自建派生测试（kpl_bidding_series → 试盘语义行）。

锚点：11-13 真值 605255 last_amount=8980000 == MBL col4（委买额同语义）；
roster 消费字段 = jj_percent/first_amount/last_amount/max_amount（posture）/
jj_amount（board_amt），pre_percent=None → 分母=代码口径 limit（与 WzsLinker
昨涨停行 pre_percent=limit 数学等价）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import auction_trial_derive as M


class FakeSeriesDb:
    def __init__(self, doc=None):
        self.doc = doc

    def __getitem__(self, name):
        return self

    def find_one(self, q):
        import copy
        return copy.deepcopy(self.doc) if self.doc else None


def _tick(ts, items):
    return {"ts": ts, "it": items}


def _doc():
    return {"_id": "2026-11-17", "ticks": [
        _tick(1000.0, [{"s": "605255", "bidding_pct": 4.0, "bidding_amount": 1.0e6,
                        "bidding_turnover": 0.1, "zt_buy_amount": 7.0e6},
                       {"s": "600000", "bidding_pct": 2.0, "bidding_amount": 5.0e5,
                        "bidding_turnover": 0.05, "zt_buy_amount": None}]),
        _tick(1010.0, [{"s": "605255", "bidding_pct": 4.5, "bidding_amount": 1.2e6,
                        "bidding_turnover": 0.12, "zt_buy_amount": 9.0e6}]),
        _tick(1020.0, [{"s": "605255", "bidding_pct": 4.78, "bidding_amount": 1.3979616e7,
                        "bidding_turnover": 0.15, "zt_buy_amount": 8.98e6}]),
    ]}


def test_derive_fields_from_series():
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(_doc()), "2026-11-17")
    assert state["state"] == "ok" and state["n_rows"] == 1 and state["tickN"] == 3
    r = rows["605255"]
    # 委买额时序统计：首帧/峰值/末帧
    assert r["first_amount"] == 7.0e6 and r["max_amount"] == 9.0e6
    assert r["last_amount"] == 8.98e6
    # 末帧语义：jj_percent/jj_amount/jj_turnover 取末帧
    assert r["jj_percent"] == 4.78 and r["jj_amount"] == 1.3979616e7
    assert r["jj_turnover"] == 0.15


def test_derive_excludes_no_ztbuy():
    """委买额不可见（None/0/非有限）→ 不在试盘宇宙，如实缺席。"""
    doc = _doc()
    doc["ticks"][0]["it"][0]["zt_buy_amount"] = None
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    assert state["state"] == "ok"
    assert set(rows.keys()) == {"605255"}  # 600000 委买额 None 被排除


def test_derive_absent_states():
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(None), "2026-11-17")
    assert rows == {} and state["state"] == "absent"
    assert state["reason"] == "no_series_archive"
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb({"_id": "d", "ticks": []}),
                                                  "2026-11-17")
    assert state["reason"] == "no_ztbuy_visible"


def test_derive_nan_not_zero():
    """NaN/Inf 消毒 → None（不伪装 0，与 auction_strength.fnum 同口径）。"""
    doc = _doc()
    doc["ticks"][0]["it"][0]["bidding_pct"] = float("nan")
    rows, _ = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    # NaN 只污染首帧 bidding_pct；jj_percent 取末帧 → 正常值
    assert rows["605255"]["jj_percent"] == 4.78


def test_label_wiring_derived_before_fetch():
    """打标链接线守卫：派生在 WzsLinker fetch 之前；fetch 以「派生缺席」为门控。"""
    from backend.operations import auction_leader_label as L
    src = open(L.__file__, encoding="utf-8").read()
    i_derive = src.find("derived_rows, derived_state = derive_trial_rows_from_series")
    i_fetch = src.find("tr = fetch_auction_trial(date)")
    assert 0 < i_derive < i_fetch, "派生必须在 WzsLinker fetch 之前"
    assert "if not trial_rows and not dry_run and _in_auction_window():" in src,         "WzsLinker fetch 必须以「派生缺席」为前置门控（迁移期回退语义）"
    assert "kpl_bidding_series_derived" in open(
        "backend/operations/auction_trial_derive.py", encoding="utf-8").read()


def test_derive_equivalence_ratio_math():
    """比值等价性：WzsLinker 昨涨停行 ratio=jp/pre(=limit) ≡ 派生行 ratio=jp/limit。"""
    from backend.analysis.hotlist import auction_strength as AS
    # WzsLinker 形态（11-13 真值 605255）
    wzs = {"code": "605255", "jj_percent": 4.78, "pre_percent": 10.0,
           "first_amount": 7560000.0, "last_amount": 8980000.0,
           "max_amount": 9610000.0, "jj_amount": 13979616.0}
    wzs.update(AS.bre.row_basis("605255", wzs))
    # 派生形态（pre_percent=None）
    drv = {"code": "605255", "jj_percent": 4.78, "pre_percent": None,
           "first_amount": 7560000.0, "last_amount": 8980000.0,
           "max_amount": 9610000.0, "jj_amount": 13979616.0}
    drv.update(AS.bre.row_basis("605255", drv))
    assert wzs["preseal"] is True and drv["preseal"] is False
    # 分母同为 limit（preseal 行 pre_percent=limit；非 preseal 行取 limit）
    assert AS.jj_ratio(4.78, wzs["pre_percent"], wzs["limit"], True) ==            AS.jj_ratio(4.78, drv["pre_percent"], drv["limit"], False)
    # posture 一致（11-13 真值 605255：末额 8.98M > 首开 7.56M → maintain）
    assert AS.bre.posture(wzs) == AS.bre.posture(drv) == "maintain"
