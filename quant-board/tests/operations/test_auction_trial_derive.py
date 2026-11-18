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


class _Coll:
    """集合作用域视图（pymongo 语义：find_one 归属集合，非 filter 区分）。"""

    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def find_one(self, q, projection=None):
        import copy
        if self.name == "kpl_morning_bidding_raw":
            return copy.deepcopy(self.owner.mbl) if self.owner.mbl else None
        return copy.deepcopy(self.owner.doc) if self.owner.doc else None


class FakeSeriesDb:
    """双集合假库：kpl_bidding_series + kpl_morning_bidding_raw（bk_name join）。"""

    def __init__(self, doc=None, mbl_rows=None):
        self.doc = doc
        self.mbl = {"rows": mbl_rows} if mbl_rows is not None else None

    def __getitem__(self, name):
        return _Coll(self, name)


def _tick(ts, items):
    return {"ts": ts, "it": items}


import datetime as _dt
_TZ = _dt.timezone(_dt.timedelta(hours=8))
_BASE = _dt.datetime(2026, 11, 17, 9, 16, tzinfo=_TZ).timestamp()


def _doc():
    return {"_id": "2026-11-17", "ticks": [
        _tick(_BASE + 0, [{"s": "605255", "bidding_pct": 4.0, "bidding_amount": 1.0e6,
                        "bidding_turnover": 0.1, "zt_buy_amount": 7.0e6},
                       {"s": "600000", "bidding_pct": 2.0, "bidding_amount": 5.0e5,
                        "bidding_turnover": 0.05, "zt_buy_amount": None}]),
        _tick(_BASE + 10, [{"s": "605255", "bidding_pct": 4.5, "bidding_amount": 1.2e6,
                        "bidding_turnover": 0.12, "zt_buy_amount": 9.0e6}]),
        _tick(_BASE + 20, [{"s": "605255", "bidding_pct": 4.78, "bidding_amount": 1.3979616e7,
                        "bidding_turnover": 0.15, "zt_buy_amount": 8.98e6}]),
    ]}


def _mbl_rows():
    return {"605255": {"code": "605255", "plate": "机器人"},
            "600000": {"code": "600000", "plate": "银行"}}


def test_derive_fields_from_series():
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    assert state["state"] == "ok" and state["n_rows"] == 1 and state["tickN"] == 3
    assert state["plateJoinedN"] == 1
    r = rows["605255"]
    assert r["bk_name"] == "机器人", "MBL col11 板块 join 注入 bk_name（桥接主链）"
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
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    assert state["state"] == "ok"
    assert set(rows.keys()) == {"605255"}  # 600000 委买额 None 被排除


def test_derive_plate_missing_fail_visible():
    """MBL raw 无档（历史日）→ plateMissing=True 结构化留痕；bk_name=None 不猜。"""
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(_doc()), "2026-11-17")
    assert state["state"] == "ok" and state["plateMissing"] is True
    assert rows["605255"]["bk_name"] is None


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


def test_derive_jj_frozen_mbl_primary():
    """竞价三字段=MBL 09:25 冻结终值优先（2026-11-18 用户反馈涨幅不对定案）；
    首/峰/末仍序列过程统计，不被冻结值替换。"""
    mbl = _mbl_rows()
    mbl["605255"].update({"bidding_pct": 5.5, "bidding_amount": 2e7,
                          "bidding_turnover": 0.2})
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), mbl), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 5.5 and r["jj_amount"] == 2e7
    assert r["jj_turnover"] == 0.2
    assert r["jjSource"] == "mbl_frozen" and r["jjFrozen"] is True
    assert state["frozenJoinedN"] == 1
    assert r["last_amount"] == 8.98e6


def test_derive_jj_bid_frozen_for_mbl_absent():
    """MBL 榜外掉池股 → bid 通道 09:25 匹配推送冻结值兑底（jjSource=bid_frozen）。"""
    class DbWithBid(FakeSeriesDb):
        def __getitem__(self, name):
            if name == "kpl_daban_pool":
                class C:
                    def find_one(self, q, projection=None):
                        return {"bid_items": [{"stock_id": "605255",
                                "bidding_pct": 6.6, "bidding_amount": 3e7,
                                "bidding_turnover": 0.3}]}
                return C()
            return super().__getitem__(name)
    rows, state = M.derive_trial_rows_from_series(
        DbWithBid(_doc(), _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 6.6 and r["jj_amount"] == 3e7
    assert r["jjSource"] == "bid_frozen" and r["jjFrozen"] is True


def test_derive_jj_frozen_partial_fallback():
    """冻结值逐字段回退：pct 在/amount 缺 → amount 取末帧，不连坐。"""
    mbl = _mbl_rows()
    mbl["605255"]["bidding_pct"] = 5.5
    rows, _ = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), mbl), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 5.5
    assert r["jj_amount"] == 1.3979616e7
    assert r["jjSource"] == "mbl_frozen"


def test_derive_first_add_tick_delta():
    """首加额=首笔观测追加委买增量（tick 分笔，2026-11-18 用户裁决）；
    起止=观测首末帧时点；现价/涨幅/流通值=末帧观测值；昨涨幅无源=None。"""
    doc = _doc()  # 7e6 → 9e6 → 8.98e6：首正 delta=2e6
    doc["ticks"][-1]["it"][0].update({"price": 12.3, "pct": 4.78, "real_float": 6e9})
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["first_add"] == 2.0e6
    assert r["start_time"] == "09:16:00" and r["end_time"] == "09:16:20"
    assert r["price"] == 12.3 and r["percent"] == 4.78
    assert r["circulated_value"] == 6e9
    assert r["pre_percent"] is None
    assert state["firstAddN"] == 1 and state["floatJoinedN"] == 1


def test_derive_first_add_none_when_monotone_decrease():
    """全撤减无追加 → first_add=None（不补 0）。"""
    doc = {"_id": "d", "ticks": [
        _tick(_BASE + 0, [{"s": "605255", "zt_buy_amount": 9e6}]),
        _tick(_BASE + 10, [{"s": "605255", "zt_buy_amount": 8e6}]),
        _tick(_BASE + 20, [{"s": "605255", "zt_buy_amount": 7e6}])]}
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    assert rows["605255"]["first_add"] is None
    assert state["firstAddN"] == 0


def test_derive_first_add_skips_missing_frames():
    """缺值帧不配对（不猜）：7e6→None→9e6 不产生跨帧 delta。"""
    doc = {"_id": "d", "ticks": [
        _tick(_BASE + 0, [{"s": "605255", "zt_buy_amount": 7e6}]),
        _tick(_BASE + 10, [{"s": "605255", "zt_buy_amount": None}]),
        _tick(_BASE + 20, [{"s": "605255", "zt_buy_amount": 9e6}])]}
    rows, _ = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    assert rows["605255"]["first_add"] is None


def test_label_wiring_series_primary():
    """主链接线守卫（2026-11-17 正名）：主链=官方 socket 序列试盘行（先行），
    raw 日档回读为次；WzsLinker 退役出链（判据链零第三方代理依赖）。"""
    from backend.operations import auction_leader_label as L
    src = open(L.__file__, encoding="utf-8").read()
    i_series = src.find("derived_rows, derived_state = derive_trial_rows_from_series")
    i_archive = src.find('db[COLLECTION_TRIAL_RAW].find_one')
    assert 0 < i_series < i_archive, "官方序列主链必须先于 raw 日档回读"
    assert "fetch_auction_trial" not in src and "TRIAL_HOST" not in src,         "WzsLinker 已退役出链（endpoint/采集函数不在判据链；注释提及不受限）"
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


def test_derive_filters_late_ticks():
    """迟到 tick 防御：09:27 后 tick（冻结后/连续竞价 regime）不进派生，计数留痕。

    2026-11-17 对拍实证：09:32:10 开盘后 tick 混入使 selectedN 1→0（last 语义被
    连续竞价 zt_buy 污染）。"""
    import datetime as dt
    TZ = dt.timezone(dt.timedelta(hours=8))
    doc = _doc()
    # _doc 的 tick ts 是小整数（会被判 1970 年）→ 全部过滤；先给合法早盘 ts
    base = dt.datetime(2026, 11, 17, 9, 16, tzinfo=TZ).timestamp()
    doc["ticks"][0]["ts"] = base
    doc["ticks"][1]["ts"] = base + 10
    doc["ticks"][2]["ts"] = base + 20
    late = dict(doc["ticks"][2])
    late["ts"] = dt.datetime(2026, 11, 17, 9, 32, 10, tzinfo=TZ).timestamp()
    late["it"] = [{"s": "605255", "bidding_pct": 99.0, "bidding_amount": 1.0,
                   "bidding_turnover": 0.0, "zt_buy_amount": 1.0}]
    doc["ticks"].append(late)
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    assert state["state"] == "ok" and state["lateTicksFiltered"] == 1
    assert state["tickN"] == 3
    r = rows["605255"]
    assert r["last_amount"] == 8980000.0, "末帧必须是 09:16:20 tick，非 09:32 开盘后污染帧"
    assert r["jj_percent"] == 4.78


def test_derive_filters_early_ticks():
    """早 tick 防御：09:15 前盘前陈旧态（09:00 门禁后会话爆发推昨日终态页）
    不进派生，计数留痕（防污染 first 基线）。"""
    import datetime as dt
    TZ = dt.timezone(dt.timedelta(hours=8))
    doc = _doc()
    early = dict(doc["ticks"][0])
    early["ts"] = dt.datetime(2026, 11, 17, 9, 11, 30, tzinfo=TZ).timestamp()
    early["it"] = [{"s": "605255", "bidding_pct": -5.0, "bidding_amount": 1.0,
                    "bidding_turnover": 0.0, "zt_buy_amount": 999.0e6}]
    doc["ticks"].insert(0, early)
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    assert state["state"] == "ok" and state["earlyTicksFiltered"] == 1
    r = rows["605255"]
    assert r["first_amount"] == 7.0e6, "首帧必须是 09:16:00 竞价帧，非 09:11 盘前陈旧帧"


def test_historical_equivalence_1113():
    """历史验证（11-13 WzsLinker 真值 95 只）：派生形态（pre_percent=None + bk_name
    保留）走完整 roster，与真值形态入选集合/映射/板块归属完全等价。

    真实库只读（dragon_board_quant，零写零外呼零模型）；无 trial raw 档则跳过。"""
    import copy
    from backend.data.repositories import repository_factory
    from backend.analysis.hotlist import auction_strength as AS
    db = repository_factory.get_runtime_mongodb_database()
    trial = (db["auction_trial_raw"].find_one({"_id": "2026-11-13"}) or {}).get("rows") or {}
    if len(trial) < 50:
        import pytest
        pytest.skip("11-13 trial raw 档缺席，历史等价性验证不可跑")
    out_wzs, st_wzs = AS.trial_strength_roster(db, "2026-11-13", copy.deepcopy(trial))
    drv = {}
    for c, r in trial.items():
        drv[c] = {"code": str(c)[-6:], "bk_name": r.get("bk_name"),
                  "jj_percent": r.get("jj_percent"),
                  "first_amount": r.get("first_amount"),
                  "last_amount": r.get("last_amount"),
                  "max_amount": r.get("max_amount"),
                  "jj_amount": r.get("jj_amount"),
                  "jj_turnover": r.get("jj_turnover")}
    out_drv, st_drv = AS.trial_strength_roster(db, "2026-11-13", drv)
    assert st_drv["mappedN"] == st_wzs["mappedN"], "映射数必须一致（bk_name 桥接主链）"
    assert {r["code"] for r in out_drv} == {r["code"] for r in out_wzs}, "入选集合必须一致"
    wr = {r["code"]: r["trialStrength"] for r in out_wzs}
    dr = {r["code"]: r["trialStrength"] for r in out_drv}
    for c in wr:
        # 板块量/档/姿态/排名一致；jjRatio 允许 preseal 分母微差（≤1%）
        assert dr[c]["boardAmt"] == wr[c]["boardAmt"]
        assert dr[c]["posture"] == wr[c]["posture"] and dr[c]["rank"] == wr[c]["rank"]
        assert abs(dr[c]["jjRatio"] - wr[c]["jjRatio"]) <= 1.0
