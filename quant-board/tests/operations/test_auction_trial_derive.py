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
        if self.name == "kpl_auction_price":
            return copy.deepcopy(self.owner.auct) if self.owner.auct else None
        return copy.deepcopy(self.owner.doc) if self.owner.doc else None


class FakeSeriesDb:
    """三集合假库：kpl_bidding_series + kpl_morning_bidding_raw（bk_name join）
    + kpl_auction_price（09:15/09:25 价格存档，2026-11-18）。"""

    def __init__(self, doc=None, mbl_rows=None, auct=None):
        self.doc = doc
        self.mbl = {"rows": mbl_rows} if mbl_rows is not None else None
        self.auct = auct

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
    rows, _ = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    r = rows["605255"]
    assert r["pct0915"] == 4.0 and r["jj915Src"] == "series_first"
    assert r["p0915"] is None, "无存档价 → p0915 缺席（不伪）"
    auct = {"s0915": {"605255": {"price": 4.84, "pct": 10.0}}}
    rows2, _ = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows(), auct=auct), "2026-11-17")
    r2 = rows2["605255"]
    assert r2["pct0915"] == 10.0 and r2["jj915Src"] == "open0915_archive"
    assert r2["p0915"] == 4.84


def test_derive_open0925_missing_fallback_disclosure():
    """存档缺 → 回退旧链（MBL→bid→序列末帧），open0925N/MissingN 结构化披露。"""
    rows, state = M.derive_trial_rows_from_series(
        FakeSeriesDb(_doc(), _mbl_rows()), "2026-11-17")
    assert state["open0925N"] == 0 and state["open0925MissingN"] == 1
    assert rows["605255"]["jjSource"] != "open0925_archive"


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
