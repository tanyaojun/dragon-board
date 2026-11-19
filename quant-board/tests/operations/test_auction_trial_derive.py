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
from tests.series_fake import FakeSeriesCol, seed_series_legacy


class _Coll:
    """集合作用域视图（pymongo 语义：find_one 归属集合，非 filter 区分）。"""

    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def find(self, q=None, projection=None):
        if self.name == "kpl_bidding_series":
            return self.owner.series.find(q, projection)
        return []

    def find_one(self, q, projection=None, sort=None):
        import copy
        if self.name == "kpl_bidding_series":
            return self.owner.series.find_one(q, projection)
        if self.name == "kpl_morning_bidding_raw":
            # 2026-11-19 裁决 1+2：_id<date 倒序查询=前日回退源
            if isinstance(q.get("_id"), dict) and "$lt" in q["_id"]:
                return copy.deepcopy(self.owner.mbl_prev) if self.owner.mbl_prev else None
            return copy.deepcopy(self.owner.mbl) if self.owner.mbl else None
        if self.name == "kpl_auction_matched":
            return copy.deepcopy(self.owner.matched) if self.owner.matched else None
        if self.name == "kpl_daban_pool":
            return {"bid_items": copy.deepcopy(self.owner.bid_items or [])}
        return None


class FakeSeriesDb:
    """三集合假库：kpl_bidding_series（2026-11-19 逐 tick 文档化，旧嵌入
    fixture 经 seed_series_legacy 适配为新形态）+ kpl_morning_bidding_raw
    （bk_name join）+ kpl_auction_matched（Type=7 终值）。"""

    def __init__(self, doc=None, mbl_rows=None, mbl_prev=None,
                 bid_items=None, matched=None):
        self.series = FakeSeriesCol()
        if doc:
            seed_series_legacy(self.series, doc)
        self.mbl = {"rows": mbl_rows} if mbl_rows is not None else None
        self.matched = {"rows": matched} if matched is not None else None
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
    # 终值语义（2026-11-19 裁决②）：jj_percent=Type=7→TDX 应急；本 fixture 无
    # matched/open_pct → 如实 None（不回退末帧）；jj_amount/jj_turnover 接投影层
    # （无公布锚→series 窗内虚拟观测；换手缺市值→None+no_float_cap）
    assert r["jj_percent"] is None and r["jjSource"] is None
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
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb({"_id": "2026-11-17", "ticks": []}),
                                                  "2026-11-17")
    assert state["reason"] == "no_ztbuy_visible"


def test_derive_nan_not_zero():
    """NaN/Inf 消毒 → None（不伪装 0，与 auction_strength.fnum 同口径）。"""
    doc = _doc()
    doc["ticks"][0]["it"][0]["bidding_pct"] = float("nan")
    rows, _ = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    # NaN 污染首帧 bidding_pct → pct0915=None（不伪装 0）；终值无源 jj_percent=None
    assert rows["605255"]["pct0915"] is None
    assert rows["605255"]["jj_percent"] is None


def test_derive_jj_terminal_matched_priority():
    """裁决②：Type=7 终值（kpl_auction_matched）为 jj_percent/额/换手第一权威，
    掉池股亦有；MBL/bid/末帧不再入 jj 链（3006 退役、单主链对齐 App）。"""
    matched = {"605255": {"pct": 0.0, "price": 4.40, "amount": 1.925e7,
                          "turnover": 0.58, "end_time": "09:25:00"}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows(), matched=matched), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 0.0 and r["jjSource"] == "dingpan_postmatch"
    assert r["jj_amount"] == 1.925e7 and r["jjAmountSrc"] == "dingpan_postmatch"
    assert r["jj_turnover"] == 0.58 and r["jjTurnoverSrc"] == "dingpan_postmatch"
    assert r["jjFrozen"] is True and r["end_time"] == "09:25:00"
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
    assert r["jj_amount"] == 3e7 and r["jjAmountSrc"] == "bid_frozen"
    # jj_percent 不再回退 bid（终值链=Type=7→TDX）；无源→None
    assert r["jj_percent"] is None and r["jjSource"] is None


def test_derive_jj_frozen_partial_fallback():
    """冻结值逐字段不连坐：pct 在（mbl_frozen）/amount 缺 → 投影窗内虚拟观测
    兜底（series_virtual，无公布锚 fixture 形态），pct 链不受影响。"""
    mbl = _mbl_rows()
    mbl["605255"]["bidding_pct"] = 5.5
    rows, _ = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), mbl), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] is None and r["jjSource"] is None  # MBL 不再入 jj 链
    assert r["jj_amount"] == 1.3979616e7
    assert r["jjAmountSrc"] == "series_virtual"


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
    doc = {"_id": "2026-11-17", "ticks": [
        _tick(_BASE + 0, [{"s": "605255", "zt_buy_amount": 9e6}]),
        _tick(_BASE + 10, [{"s": "605255", "zt_buy_amount": 8e6}]),
        _tick(_BASE + 20, [{"s": "605255", "zt_buy_amount": 7e6}])]}
    rows, state = M.derive_trial_rows_from_series(FakeSeriesDb(doc), "2026-11-17")
    assert rows["605255"]["first_add"] is None
    assert state["firstAddN"] == 0


def test_derive_first_add_skips_missing_frames():
    """缺值帧不配对（不猜）：7e6→None→9e6 不产生跨帧 delta。"""
    doc = {"_id": "2026-11-17", "ticks": [
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
    assert r["jj_percent"] is None  # 终值无源（末帧不再入 jj 链）


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

def test_derive_jj_authority_dingpan_postmatch():
    """Type=7 终值在 → jj_percent/p0925/pct0925 权威（掉池股亦有）；09:15 仍=pid8
    首帧（3006 退役）。锚：002652 09:25=0.00%（早退值 9.77 错，终值纠正）。"""
    matched = {"605255": {"price": 4.40, "pct": 0.0}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows(), matched=matched), "2026-11-17")
    r = rows["605255"]
    assert r["jj_percent"] == 0.0 and r["jjSource"] == "dingpan_postmatch"
    assert r["p0925"] == 4.40 and r["pct0925"] == 0.0
    assert r["pct0915"] == 4.0 and r["jj915Src"] == "series_first"
    assert state["open0925N"] == 1 and state["open0925MissingN"] == 0


def test_derive_pct0915_series_first():
    """竞价涨幅（0915）权威=pid8 序列首帧（3006 退役）；p0915=首帧 price，
    首帧无 price 则缺席不伪。与 0925 开盘涨幅两时点分列。"""
    rows, st = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["pct0915"] == 4.0 and r["jj915Src"] == "series_first"
    assert r["p0915"] is None, "首帧无 price → p0915 缺席（不伪）"
    assert st["seriesFirst0915N"] == 1 and "open0915N" not in st, "死计数器已随 3006 退役删除"
    doc = _doc()
    doc["ticks"][0]["it"][0]["price"] = 4.84
    rows2, _ = M.derive_trial_rows_from_series(FakeSeriesDb(doc, _mbl_rows()), "2026-11-17")
    assert rows2["605255"]["p0915"] == 4.84


def test_derive_open0925_missing_fallback_disclosure():
    """Type=7 终值缺且无 TDX 开盘棒 → 开盘涨幅列如实缺席（不回退 MBL/bid/末帧：
    成员制早退值≠开盘，11-16 缺陷定案）；jj 链同源缺席（jjSource=None）。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    assert state["open0925N"] == 0 and state["open0925MissingN"] == 1
    assert state["open0925TdxN"] == 0
    assert rows["605255"]["jjSource"] is None
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


def test_derive_open0925_matched_priority_over_tdx():
    """Type=7 终值在 → 第一权威不被 TDX 应急棒压过（逐行 src 披露）。"""
    doc = _doc()
    doc["open_pct"] = {"605255": {"price": 4.40, "pct": 0.0, "src": "tdx_bar"}}
    matched = {"605255": {"price": 4.50, "pct": 2.27}}
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(doc, _mbl_rows(), matched=matched), "2026-11-17")
    r = rows["605255"]
    assert r["pct0925"] == 2.27 and r["p0925"] == 4.50
    assert r["open0925Src"] == "dingpan_postmatch"
    assert state["open0925N"] == 1 and state["open0925TdxN"] == 0
