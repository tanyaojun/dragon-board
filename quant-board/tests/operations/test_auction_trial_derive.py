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

    def find_one(self, q, projection=None, sort=None):
        import copy
        if self.name == "kpl_morning_bidding_raw":
            # 2026-11-19 裁决 1+2：_id<date 倒序查询=前日回退源
            if isinstance(q.get("_id"), dict) and "$lt" in q["_id"]:
                return copy.deepcopy(self.owner.mbl_prev) if self.owner.mbl_prev else None
            return copy.deepcopy(self.owner.mbl) if self.owner.mbl else None
        if self.name == "kpl_auction_price":
            return copy.deepcopy(self.owner.auct) if self.owner.auct else None
        if self.name == "kpl_daban_pool":
            return {"bid_items": copy.deepcopy(self.owner.bid_items or [])}
        return copy.deepcopy(self.owner.doc) if self.owner.doc else None


class FakeSeriesDb:
    """三集合假库：kpl_bidding_series + kpl_morning_bidding_raw（bk_name join）
    + kpl_auction_price（09:15/09:25 价格存档，2026-11-18）。"""

    def __init__(self, doc=None, mbl_rows=None, auct=None, mbl_prev=None,
                 bid_items=None):
        self.doc = doc
        self.mbl = {"rows": mbl_rows} if mbl_rows is not None else None
        self.auct = auct
        self.mbl_prev = {"rows": mbl_prev} if mbl_prev is not None else None
        self.bid_items = bid_items

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
    # 末帧语义：jj_percent 取末帧（pct 链不接投影）；jj_amount/jj_turnover 接投影层
    # （2026-11-19：本 fixture 无公布锚（仅窗内 tick）→ in_pool_pre_match 态，
    # 额=series 窗内虚拟观测（可计算部分保全），换手缺市值→None+no_float_cap）
    assert r["jj_percent"] == 4.78
    assert r["jj_amount"] == 1.3979616e7
    assert r["jjAmountSrc"] == "series_virtual"
    assert r["jj_turnover"] is None and r["jjTurnoverSrc"] is None


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


def test_bk_name_src_same_day_disclosure():
    """2026-11-19 裁决 1+2：同日 MBL 命中 → bkNameSrc=mbl_same + plateSrcN 计数。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    assert rows["605255"]["bkNameSrc"] == "mbl_same"
    assert state["plateSrcN"] == {"mbl_same": 1}


def test_bk_name_fallback_prev_mbl():
    """同日 raw 缺席（09:26 读口）→ 前日 MBL 档回退，桥接不再静默死亡。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), mbl_prev={"605255": {"plate": "机器人"}}), "2026-11-17")
    assert rows["605255"]["bk_name"] == "机器人"
    assert rows["605255"]["bkNameSrc"] == "mbl_prev"
    assert state["plateSrcN"] == {"mbl_prev": 1}
    assert state["plateMissing"] is True   # 同日源缺席仍披露


def test_bk_name_fallback_bid_plate():
    """同日+前日 MBL 均缺席 → pid8 bid lane plate（pos11）回退。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), bid_items=[{"stock_id": "605255", "plate": "机器人",
                                        "bidding_pct": 4.78}]), "2026-11-17")
    assert rows["605255"]["bk_name"] == "机器人"
    assert rows["605255"]["bkNameSrc"] == "bid_plate"
    assert state["plateSrcN"] == {"bid_plate": 1}


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
    """存档缺位时回退链：MBL 冻结值优先（jjSource=mbl_frozen）；
    存档在则 open0925_archive 权威（见 test_derive_jj_authority_open0925_archive）。"""
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
    """MBL 榜外掉池股 → bid 通道公布后终态兑底（投影 bid_frozen，jjSource=bid_frozen）。
    公布锚 = mbl 完整公布帧（603030 沪市非零）；605255 不在公布帧但 bid last_seen
    严格晚于额锚 → 留池持久证据分支。"""
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))
    t_pub = _dt.datetime(2026, 11, 17, 9, 26, 20, tzinfo=tz).timestamp()
    t_ls = _dt.datetime(2026, 11, 17, 9, 27, 0, tzinfo=tz).timestamp()
    pub_raw = ["603030", "", "", "", "", "", 11109148, 1.07, 26669214, 0,
               26669214, "", 2499813743, "", 0, 0, ""]

    class DbWithBid(FakeSeriesDb):
        def __getitem__(self, name):
            if name == "kpl_daban_pool":
                class C:
                    def find_one(self, q, projection=None):
                        return {"bid_ts": t_ls, "bid_items": [
                            {"stock_id": "605255", "bidding_pct": 6.6,
                             "bidding_amount": 3e7, "bidding_turnover": 0.3,
                             "last_seen_ts": t_ls}]}
                return C()
            if name == "kpl_mbl_series":
                class C:
                    def find_one(self, q, projection=None):
                        return {"frames": [{"ts": "2026-11-17T09:26:20+08:00",
                                            "rows": [pub_raw]}]}
                return C()
            return super().__getitem__(name)
    rows, state = M.derive_trial_rows_from_series(
        DbWithBid(_doc(), _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 6.6 and r["jj_amount"] == 3e7
    assert r["jjAmountSrc"] == "bid_frozen"
    assert r["jjSource"] == "bid_frozen" and r["jjFrozen"] is True


def test_derive_jj_frozen_partial_fallback():
    """冻结值逐字段不连坐：pct 在（mbl_frozen）/amount 缺 → 投影窗内虚拟观测
    兜底（series_virtual，无公布锚 fixture 形态），pct 链不受影响。"""
    mbl = _mbl_rows()
    mbl["605255"]["bidding_pct"] = 5.5
    rows, _ = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), mbl), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 5.5
    assert r["jj_amount"] == 1.3979616e7
    assert r["jjAmountSrc"] == "series_virtual"
    assert r["jjSource"] == "mbl_frozen"


def test_derive_jj_amount_turnover_projection_600410():
    """投影层锚（2026-11-19 实档回放切片）：掉池股 600410 额=col10 掉池前
    虚拟观测 124381050@09:23:23、换手=派生 0.6132（额/流通市值×100）、
    净额缺位 None（jj_percent 链独立不接投影）。"""
    import datetime as _dt
    tz = _dt.timezone(_dt.timedelta(hours=8))
    t0 = _dt.datetime(2026, 11, 19, 9, 15, 35, tzinfo=tz).timestamp()
    t1 = _dt.datetime(2026, 11, 19, 9, 23, 23, tzinfo=tz).timestamp()
    doc = {"_id": "2026-11-19", "ticks": [
        _tick(t0, [{"s": "600410", "bidding_pct": 9.99, "bidding_amount": 0.0,
                    "bidding_net": 0.0, "bidding_turnover": 0.0,
                    "zt_buy_amount": 1.2e8, "real_float": 20285151636.0}]),
        _tick(t1, [{"s": "600410", "bidding_pct": 9.99, "bidding_amount": 0.0,
                    "bidding_net": 0.0, "bidding_turnover": 0.0,
                    "zt_buy_amount": 1.248e8, "real_float": 20285151636.0}]),
        _tick(t1 + 88, [])]}   # 09:24:51 空帧：600410 掉池证据（末帧不在场）
    raw10 = ["600410", "华胜天成", "", "", "", "", 0, 0, 0, 0, 124381050,
             "", 20285151636, "", 0, 0, ""]
    mbl_ser = {"_id": "2026-11-19", "frames": [
        {"ts": "2026-11-19T09:15:35+08:00", "rows": [raw10]},
        {"ts": "2026-11-19T09:23:23+08:00", "rows": [raw10]},
        {"ts": "2026-11-19T09:24:51+08:00", "rows": []}]}
    pool = {"_id": "2026-11-19", "bid_ts": t1 + 88, "bid_items": [
        {"stock_id": "600410", "name": "华胜天成", "bidding_pct": 9.98811,
         "bidding_net": 0.0, "bidding_turnover": 0.0, "bidding_amount": 0.0,
         "zt_buy_amount": 124802850.0, "real_float": 20285151636.0,
         "last_seen_ts": t1}]}

    class Db(FakeSeriesDb):
        def __getitem__(self, name):
            if name == "kpl_mbl_series":
                class C:
                    def find_one(self, q, projection=None):
                        return mbl_ser
                return C()
            if name == "kpl_daban_pool":
                class C:
                    def find_one(self, q, projection=None):
                        return pool
                return C()
            return super().__getitem__(name)

    rows, state = M.derive_trial_rows_from_series(Db(doc), "2026-11-19")
    r = rows["600410"]
    assert r["jj_amount"] == 124381050.0
    assert r["jjAmountSrc"] == "mbl_col10_preexit"
    assert r["jj_turnover"] == 0.6132 and r["jjTurnoverSrc"] == "derived_cap"
    assert state["trioCensus"]["net_missing_n"] == 1
    assert state["trioState"]["tsPub"] is None   # 无公布锚（掉池股-only 切片）


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
    assert "derive_trial_rows_from_series" in src, "官方序列主链必须在判据链"
    assert "COLLECTION_TRIAL_RAW" not in src and "auction_trial_fetch" not in src, \
        "§7.17 raw 整集合退役：判据链零代码引用（注释提及不受限）"
    assert "fetch_auction_trial" not in src and "TRIAL_HOST" not in src, \
        "WzsLinker 已退役出链（endpoint/采集函数不在判据链）"
    assert "kpl_bidding_series_derived" in open(
        "backend/operations/auction_trial_derive.py", encoding="utf-8").read()


def test_derive_equivalence_ratio_math():
    """比值等价性：WzsLinker 昨涨停行 ratio=jp/pre(=limit) ≡ 派生行 ratio=jp/limit。"""
    from backend.analysis.hotlist import auction_strength as AS
    # WzsLinker 形态（11-13 真值 605255）
    wzs = {"code": "605255", "jj_percent": 4.78, "pre_percent": 10.0,
           "first_amount": 7560000.0, "last_amount": 8980000.0,
           "max_amount": 9610000.0, "jj_amount": 13979616.0}
    wzs.update(AS.row_basis("605255", wzs))
    # 派生形态（pre_percent=None）
    drv = {"code": "605255", "jj_percent": 4.78, "pre_percent": None,
           "first_amount": 7560000.0, "last_amount": 8980000.0,
           "max_amount": 9610000.0, "jj_amount": 13979616.0}
    drv.update(AS.row_basis("605255", drv))
    assert wzs["preseal"] is True and drv["preseal"] is False
    # 分母同为 limit（preseal 行 pre_percent=limit；非 preseal 行取 limit）
    assert AS.jj_ratio(4.78, wzs["pre_percent"], wzs["limit"], True) ==            AS.jj_ratio(4.78, drv["pre_percent"], drv["limit"], False)
    # posture 一致（11-13 真值 605255：末额 8.98M > 首开 7.56M → maintain）
    assert AS.posture(wzs) == AS.posture(drv) == "maintain"


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


# test_historical_equivalence_1113 随 §7.17 raw 退役删除（2026-11-18）：
# 11-13 真值等价性结论已存档 docs §7.9（映射 74/74、入选集合一致）；raw 归档 backups。


# ── 09:15/09:25 价格存档权威（2026-11-18 用户裁决：掉池股真 09:25 = 撮合开盘涨幅）──

def test_derive_jj_authority_open0925_archive():
    """存档在 → jj_percent=09:25 开盘涨幅（掉池股亦有），09:15/09:25 价格涨幅全披露。
    锚：002652 11-18 真值 09:15=10.00%/09:25=0.00%，旧链给 9.77（早退值）错。"""
    auct = {"_id": "2026-11-17",
            "s0915": {"605255": {"price": 4.84, "pct": 10.0, "ts": 1.0}},
            "s0925": {"605255": {"price": 4.40, "pct": 0.0, "ts": 2.0}}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows(), auct=auct), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 0.0 and r["jjSource"] == "open0925_archive"
    assert r["p0915"] == 4.84 and r["pct0915"] == 10.0
    assert r["p0925"] == 4.40 and r["pct0925"] == 0.0
    assert state["open0925N"] == 1 and state["open0925MissingN"] == 0


def test_derive_pct0915_series_first_fallback_and_archive_priority():
    """竞价涨幅（0915）：存档缺 → 回退序列首帧观测值（p0915 缺席不伪）；
    存档在 → 权威覆盖（open0915_archive）。与 0925 开盘涨幅两时点分列。"""
    rows, st = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["pct0915"] == 4.0 and r["jj915Src"] == "series_first"
    assert r["p0915"] is None, "无存档价 → p0915 缺席（不伪）"
    assert st["seriesFirst0915N"] == 1 and st["open0915N"] == 0
    auct = {"s0915": {"605255": {"price": 4.84, "pct": 10.0}}}
    rows2, st2 = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows(), auct=auct), "2026-11-17")
    r2 = rows2["605255"]
    assert r2["pct0915"] == 10.0 and r2["jj915Src"] == "open0915_archive"
    assert r2["p0915"] == 4.84
    assert st2["open0915N"] == 1 and st2["seriesFirst0915N"] == 0


def test_derive_open0925_missing_fallback_disclosure():
    """存档缺且无 TDX 开盘棒 → 开盘涨幅列如实缺席（不回退 MBL/bid/末帧：
    成员制早退值≠开盘，11-16 缺陷定案）；jj_percent 仍走旧链披露。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    assert state["open0925N"] == 0 and state["open0925MissingN"] == 1
    assert state["open0925TdxN"] == 0
    assert rows["605255"]["jjSource"] != "open0925_archive"
    assert rows["605255"]["pct0925"] is None and rows["605255"]["p0925"] is None
    assert rows["605255"]["open0925Src"] is None


def test_derive_open0925_tdx_bar_fallback():
    """2026-11-19 修复：存档缺 → TDX 盘中开盘棒（open_pct 加字段）兜底权威；
    锚：301391 11-19 open=50.9/9.09% == MBL 09:28 冻结 == TDX 真开盘。"""
    doc = _doc()
    doc["open_pct"] = {"605255": {"price": 4.40, "pct": 0.0, "src": "tdx_bar"}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["pct0925"] == 0.0 and r["p0925"] == 4.40
    assert r["open0925Src"] == "tdx_bar_open"
    assert r["jj_percent"] == 0.0 and r["jjSource"] == "tdx_bar_open"
    assert r["jjFrozen"] is True
    assert state["open0925TdxN"] == 1 and state["open0925MissingN"] == 0
    assert state["open0925N"] == 0


def test_derive_open0925_price_without_pct_not_half_broken():
    """review 2026-11-19 minor：开盘棒只带 price 缺 pct → 不产出 p0925 有值而
    pct0925/open0925Src 双 None 的半缺位行（price 仅在 pct 在场时顺带取）。"""
    doc = _doc()
    doc["open_pct"] = {"605255": {"price": 4.40, "src": "tdx_bar"}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["pct0925"] is None and r["p0925"] is None
    assert r["open0925Src"] is None
    assert state["open0925TdxN"] == 0 and state["open0925MissingN"] == 1


def test_derive_open0925_archive_priority_over_tdx_bar():
    """存档在 → 第一权威不被 TDX 开盘棒压过（逐行 src 披露）。"""
    doc = _doc()
    doc["open_pct"] = {"605255": {"price": 4.40, "pct": 0.0, "src": "tdx_bar"}}
    auct = {"s0925": {"605255": {"price": 4.50, "pct": 2.27, "ts": 2.0}}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows(), auct=auct), "2026-11-17")
    r = rows["605255"]
    assert r["pct0925"] == 2.27 and r["p0925"] == 4.50
    assert r["open0925Src"] == "open0925_archive"
    assert state["open0925N"] == 1 and state["open0925TdxN"] == 0


def test_collector_capture_auction_price_0915_0925(monkeypatch):
    """3006 现有流捕获：09:15 窗首帧/09:25 窗首帧各一次；price×10000→元、
    incRate=float 百分数直用不缩放（App DataStyleHelper.b 直显，2026-11-18
    源码核实，推翻早期 ×100 错锚）；各自只首帧不覆盖。"""
    from backend.services import kpl_collector_service as CS
    inst = object.__new__(CS.KplCollectorService)
    inst._corpus_persist_stats = {"auct15_ok": 0, "auct25_ok": 0,
                                  "auct_fail": 0, "last_error": ""}
    inst._auct_date, inst._auct15, inst._auct25 = "", set(), set()
    store: dict = {}

    class AuctColl:
        def update_one(self, q, u, upsert=False):
            store.setdefault(q["_id"], {}).update(u["$set"])

    class AuctDb:
        def __getitem__(self, name):
            return AuctColl()

    inst._corpus_db_factory = lambda: AuctDb()
    t15 = _dt.datetime(2026, 11, 17, 9, 16, tzinfo=_TZ).timestamp()
    t25 = _dt.datetime(2026, 11, 17, 9, 26, tzinfo=_TZ).timestamp()
    q1 = {"items": [{"stock_id": "002652", "price": 48400, "inc_rate": 10.0},
                    {"stock_id": "300786", "price": 200000, "inc_rate": 20.0}]}
    monkeypatch.setattr(CS.time, "time", lambda: t15)
    inst._capture_auction_price(q1)
    # 09:15 窗第二帧：同股不覆盖（首帧语义）
    monkeypatch.setattr(CS.time, "time", lambda: t15 + 20)
    inst._capture_auction_price({"items": [{"stock_id": "002652",
                                            "price": 44000, "inc_rate": 0}]})
    monkeypatch.setattr(CS.time, "time", lambda: t25)
    inst._capture_auction_price({"items": [{"stock_id": "002652",
                                            "price": 44000, "inc_rate": 0}]})
    d = store["2026-11-17"]
    assert d["s0915.002652"]["price"] == 4.84 and d["s0915.002652"]["pct"] == 10.0
    assert d["s0915.300786"]["price"] == 20.0 and d["s0915.300786"]["pct"] == 20.0
    assert d["s0925.002652"]["price"] == 4.40 and d["s0925.002652"]["pct"] == 0.0
    assert inst._corpus_persist_stats["auct15_ok"] == 2
    assert inst._corpus_persist_stats["auct25_ok"] == 1


def test_collector_capture_late_start_no_fake_0915(monkeypatch):
    """启动晚于 09:25 → s0915 缺席（不拿 09:25 值冒充 09:15，fail-visible）。"""
    from backend.services import kpl_collector_service as CS
    inst = object.__new__(CS.KplCollectorService)
    inst._corpus_persist_stats = {"auct15_ok": 0, "auct25_ok": 0,
                                  "auct_fail": 0, "last_error": ""}
    inst._auct_date, inst._auct15, inst._auct25 = "", set(), set()
    store: dict = {}

    class AuctColl:
        def update_one(self, q, u, upsert=False):
            store.setdefault(q["_id"], {}).update(u["$set"])

    class AuctDb:
        def __getitem__(self, name):
            return AuctColl()

    inst._corpus_db_factory = lambda: AuctDb()
    t26 = _dt.datetime(2026, 11, 17, 9, 26, tzinfo=_TZ).timestamp()
    monkeypatch.setattr(CS.time, "time", lambda: t26)
    inst._capture_auction_price({"items": [{"stock_id": "002652",
                                            "price": 44000, "inc_rate": 0}]})
    d = store["2026-11-17"]
    assert "s0925.002652" in d and not any(k.startswith("s0915.") for k in d)


def test_archive_auction_price_field_set_and_load():
    """字段级 $set 不覆盖他股；load 回读同形。"""
    from backend.services import kpl_daban_archiver as AR
    store: dict = {}

    class AuctColl:
        def update_one(self, q, u, upsert=False):
            store.setdefault(q["_id"], {}).update(u["$set"])

        def find_one(self, q):
            flat = store.get(q["_id"]) or {}
            if not flat:
                return None
            doc: dict = {"_id": q["_id"]}
            for k, v in flat.items():   # 点键还原嵌套（模拟 Mongo $set 语义）
                cur = doc
                parts = k.split(".")
                for p in parts[:-1]:
                    cur = cur.setdefault(p, {})
                cur[parts[-1]] = v
            return doc

    class AuctDb:
        def __getitem__(self, name):
            return AuctColl()

    db = AuctDb()
    r1 = AR.archive_auction_price(db, "2026-11-17",
                                  s0915={"002652": {"price": 4.84, "pct": 10.0}})
    r2 = AR.archive_auction_price(db, "2026-11-17",
                                  s0925={"002652": {"price": 4.40, "pct": 0.0},
                                         "600000": {"price": 9.0, "pct": 1.0}})
    assert r1["ok"] and r1["n15"] == 1 and r2["ok"] and r2["n25"] == 2
    doc = AR.load_auction_price(db, "2026-11-17")
    assert doc["s0915"]["002652"]["price"] == 4.84
    assert doc["s0925"]["600000"]["pct"] == 1.0
    assert AR.archive_auction_price(db, "") == {"ok": False, "reason": "no_date"}
    assert AR.archive_auction_price(db, "2026-11-17") == {"ok": False, "reason": "empty"}


def _mk_capture_inst(CS, db_factory):
    inst = object.__new__(CS.KplCollectorService)
    inst._corpus_persist_stats = {"auct15_ok": 0, "auct25_ok": 0,
                                  "auct_fail": 0, "last_error": ""}
    inst._auct_date, inst._auct15, inst._auct25 = "", set(), set()
    inst._corpus_db_factory = db_factory
    inst._last_error, inst._stats, inst._emit = "", {"errors": 0}, lambda ev: None
    return inst


class _AuctStoreDb:
    """点键 $set 假库（capture 测试共用）。"""

    def __init__(self):
        self.store: dict = {}

    def __getitem__(self, name):
        outer = self

        class Coll:
            def update_one(self, q, u, upsert=False):
                outer.store.setdefault(q["_id"], {}).update(u["$set"])

        return Coll()


def test_collector_capture_pct_only_bad_floats_and_board_filter(monkeypatch):
    """review M1/m2/m5：pct-only rec 可存；NaN/Inf 按缺字段不占名额；板块 id 不入个股档。"""
    from backend.services import kpl_collector_service as CS
    db = _AuctStoreDb()
    inst = _mk_capture_inst(CS, lambda: db)
    t15 = _dt.datetime(2026, 11, 17, 9, 16, tzinfo=_TZ).timestamp()
    monkeypatch.setattr(CS.time, "time", lambda: t15)
    inst._capture_auction_price({"items": [
        {"stock_id": "002652", "price": 0, "inc_rate": 10.0},          # pct-only
        {"stock_id": "300786", "price": 200000, "inc_rate": float("nan")},
        {"stock_id": "600000", "price": 48400, "inc_rate": float("inf")},
        {"stock_id": "600001", "price": float("nan"), "inc_rate": float("nan")},
        {"stock_id": "801044", "price": 100000, "inc_rate": 1.0},      # 板块 → 拒
    ]})
    d = db.store["2026-11-17"]
    assert d["s0915.002652"]["pct"] == 10.0 and "price" not in d["s0915.002652"]
    assert d["s0915.300786"]["price"] == 20.0 and "pct" not in d["s0915.300786"]
    assert "pct" not in d["s0915.600000"]
    assert not any(k.startswith("s0915.600001") for k in d), "全 NaN 帧不占首帧名额"
    assert not any(k.startswith("s0915.801044") for k in d), "板块 id 不入个股双价档"
    # 600001 后续有效帧仍可收（名额未被坏帧锁死）
    inst._capture_auction_price({"items": [
        {"stock_id": "600001", "price": 50000, "inc_rate": 5.0}]})
    assert db.store["2026-11-17"]["s0915.600001"]["pct"] == 5.0


def test_collector_capture_cross_day_reset(monkeypatch):
    """跨日重置去重集：次日同股重新开档（review m5）。"""
    from backend.services import kpl_collector_service as CS
    db = _AuctStoreDb()
    inst = _mk_capture_inst(CS, lambda: db)
    q = {"items": [{"stock_id": "002652", "price": 48400, "inc_rate": 10.0}]}
    monkeypatch.setattr(CS.time, "time",
                        lambda: _dt.datetime(2026, 11, 17, 9, 16, tzinfo=_TZ).timestamp())
    inst._capture_auction_price(q)
    monkeypatch.setattr(CS.time, "time",
                        lambda: _dt.datetime(2026, 11, 18, 9, 16, tzinfo=_TZ).timestamp())
    inst._capture_auction_price(q)
    assert "s0915.002652" in db.store["2026-11-17"]
    assert "s0915.002652" in db.store["2026-11-18"]


def test_collector_capture_persist_fail_retries_next_frame(monkeypatch):
    """review m1：落库失败退回名额（下帧重试），不永久锁死当日存档；_err 披露。"""
    from backend.services import kpl_collector_service as CS
    db = _AuctStoreDb()
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("mongo down")
        return db

    inst = _mk_capture_inst(CS, factory)
    t15 = _dt.datetime(2026, 11, 17, 9, 16, tzinfo=_TZ).timestamp()
    monkeypatch.setattr(CS.time, "time", lambda: t15)
    q = {"items": [{"stock_id": "002652", "price": 48400, "inc_rate": 10.0}]}
    inst._capture_auction_price(q)
    assert inst._corpus_persist_stats["auct_fail"] == 1
    assert "002652" not in inst._auct15, "失败批次退回名额"
    assert inst._last_error, "_err 披露（镜像 _persist_corpus）"
    inst._capture_auction_price(q)   # 下帧重试成功
    assert db.store["2026-11-17"]["s0915.002652"]["pct"] == 10.0
    assert inst._corpus_persist_stats["auct15_ok"] == 1
