# -*- coding: utf-8 -*-
"""竞价过程事实序列（kpl_bidding_series）测试——纯假库，零网络零真实 collector。

锁定口径（2026-11-16 事实采集裁决；2026-11-18 拆窗门控+节流；
2026-11-19 逐 tick 文档化，density-storage-fix-plan §2/§6）：
1. 单写者=collector 推送即全量落库（§4.0 数据链禁硬门禁），无窗门控无节流；
   竞价语义窗 [09:15,09:27) 过滤由消费层 derive 承担（计数留痕）；
2. 逐 tick 文档：append=insert_one，无读改写、无 $slice、无 SERIES_MAX_TICKS
   （旧形态 1200×26KB≈31MB 超 16MB BSON 上限致 code 10334 拒写，常量同轮删除）；
3. tick=压缩行（具名竞价字段短键），不冒充 WzsLinker 试盘字段语义；
4. 读口 load_bidding_series 合同同形（{**meta,"ticks":[...]}），派生
   first/max/last 观测值（缺字段如实缺失，不补 0）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bson  # noqa: E402  pymongo 依赖自带

from backend.services.kpl_daban_archiver import (  # noqa: E402
    TZ_SHANGHAI,
    archive_bidding_series,
    load_bidding_series,
)
from backend.api.hotlist_jev_auction_routes import (  # noqa: E402
    _derive_stock_series_facts,
    get_auction_bidding_series,
)
from tests.series_fake import FakeSeriesCol, seed_series  # noqa: E402

BSON_LIMIT = 16 * 1024 * 1024


class FakeDb:
    def __init__(self):
        self.col = FakeSeriesCol()

    def __getitem__(self, name):
        assert name == "kpl_bidding_series"
        return self.col


def _snap(ts: float, date: str = "2026-11-17", n_stocks: int = 2,
          price_pad: int = 0):
    return {"ok": True, "date": date, "ts": ts, "pid_type": 8,
            "items": [{"stock_id": f"60{i:04d}", "name": f"股{i}",
                       "bidding_pct": 5.0 + i, "bidding_amount": 1e6 * (i + 1),
                       "bidding_net": 5e5, "bidding_turnover": 0.5,
                       "zt_buy_amount": 2e6 * (i + 1),
                       "price": "10.0" + "0" * price_pad, "pct": 10.0,
                       "real_float": 1e9, "quotas": ["x"] * 28}
                      for i in range(n_stocks)]}


def _in_window(dt: datetime) -> datetime:
    return dt.replace(tzinfo=TZ_SHANGHAI)


def test_out_of_window_now_appended():
    """2026-11-18 拆窗门控：窗外 tick 同样入档（全量保存，消费层过滤）。"""
    db = FakeDb()
    r = archive_bidding_series(db, _snap(1000.0),
                               now=_in_window(datetime(2026, 11, 17, 10, 0)))
    assert r["ok"] is True and r["tick_n"] == 1
    meta = db.col.find_one({"_id": "2026-11-17"})
    assert meta and "ticks" not in meta, "日 meta 不再含 ticks（逐 tick 文档化）"


def test_in_window_append_and_compact():
    db = FakeDb()
    r = archive_bidding_series(db, _snap(1000.0),
                               now=_in_window(datetime(2026, 11, 17, 9, 20)))
    assert r["ok"] is True and r["tick_n"] == 1 and r["item_n"] == 2
    meta = db.col.find_one({"_id": "2026-11-17"})
    assert meta["date"] == "2026-11-17" and meta["last_n"] == 2
    assert meta["tick_n"] == 1 and meta["last_ts"] == 1000.0
    tick = db.col.find_one({"date": "2026-11-17", "it": {"$exists": True}})
    assert tick["ts"] == 1000.0 and tick["n"] == 2
    it = tick["it"][0]
    assert set(it.keys()) == {"s", "bidding_pct", "bidding_amount", "bidding_net",
                              "bidding_turnover", "zt_buy_amount", "price", "pct",
                              "real_float"}, "tick 必须是压缩行（短键、无 quotas）"
    assert "quotas" not in it


def test_no_throttle_consecutive_ticks_all_appended():
    """2026-11-18 拆节流：相邻 tick（<5s）全部入档——tick 密度=服务器推送密度。"""
    db = FakeDb()
    t0 = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(db, _snap(1000.0), now=t0)
    r2 = archive_bidding_series(db, _snap(1002.0), now=t0)
    assert r2["ok"] is True and r2.get("skipped") is None
    assert db.col.count_documents({"date": "2026-11-17",
                                   "it": {"$exists": True}}) == 2
    r3 = archive_bidding_series(db, _snap(1006.0), now=t0)
    assert r3["ok"] is True and r3["tick_n"] == 3


def test_16mb_regression_700_ticks_26kb_all_ok():
    """16MB 回归（plan §6）：700 tick×~26KB 连续 append 全 ok。

    旧形态对照（必失败，留作注释不实施）：单文档嵌入 700×26KB≈18.2MB >
    16MB BSON 上限 → update_one code 10334 拒写（11-19 午后 bid_series_fail=749
    实证）；$slice 预算 1200×25.8KB≈31MB 同样失效。新形态单 tick « 16MB，
    meta 只放 last_*/tick_n，体积恒定。
    """
    db = FakeDb()
    t0 = _in_window(datetime(2026, 11, 17, 9, 20))
    snap = _snap(1000.0, n_stocks=110, price_pad=180)
    tick_size = len(bson.BSON.encode(
        {"date": "2026-11-17", "ts": 1000.0, "n": 110,
         "it": [{"s": str(it["stock_id"])[-6:], "price": it["price"]}
                for it in snap["items"]]}))
    assert tick_size > 20 * 1024, "夹具 tick 应达 ~26KB 量级"
    for i in range(700):
        r = archive_bidding_series(db, {**snap, "ts": 1000.0 + i}, now=t0)
        assert r["ok"] is True, f"tick#{i} 拒写：{r}"
        assert r["tick_n"] == i + 1
    meta = db.col.find_one({"_id": "2026-11-17"})
    assert meta["tick_n"] == 700
    assert len(bson.BSON.encode(meta)) < 64 * 1024, "meta 体积恒定（不含 ticks）"
    fake_oid = bson.ObjectId("000000000000000000000000")   # 生产 _id=真 ObjectId（12B 等长）
    for d in db.col.find({"date": "2026-11-17", "it": {"$exists": True}}):
        assert len(bson.BSON.encode({**d, "_id": fake_oid})) < BSON_LIMIT


def test_single_oversize_tick_n210_ok():
    """单 tick 超大（n=210）仍 ok（单文档 « 16MB，无上限门控）。"""
    db = FakeDb()
    r = archive_bidding_series(db, _snap(1000.0, n_stocks=210),
                               now=_in_window(datetime(2026, 11, 17, 9, 20)))
    assert r["ok"] is True and r["item_n"] == 210 and r["tick_n"] == 1


def test_insert_failure_stats_not_blocking():
    """insert 失败 → 结构化 reason 留痕不抛（fail-visible，收流不阻断）。"""
    db = FakeDb()

    def boom(doc):
        raise RuntimeError("simulated write failure")
    db.col.insert_one = boom
    r = archive_bidding_series(db, _snap(1000.0),
                               now=_in_window(datetime(2026, 11, 17, 9, 20)))
    assert r["ok"] is False and r["reason"].startswith("write_failed:")
    assert "simulated" in r["error"]


def test_empty_snapshot_and_no_date_rejected():
    db = FakeDb()
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    r1 = archive_bidding_series(db, _snap(1000.0, n_stocks=0), now=t)
    assert r1["ok"] is False and r1["reason"] == "empty_snapshot"
    snap = _snap(1000.0)
    snap.pop("date")
    r2 = archive_bidding_series(db, snap, now=t)
    assert r2["ok"] is False and r2["reason"] == "no_date"
    assert db.col.docs == []


def test_meta_supplement_fields_preserved():
    """supplement/backfill 的 meta `$set` 加字段写口零改动：archive 不覆盖。"""
    db = FakeDb()
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(db, _snap(1000.0), now=t)
    db.col.update_one({"_id": "2026-11-17"},
                      {"$set": {"prev_pct": {"600000": {"pct": 1.2}},
                                "open_pct": {"600000": {"pct": 2.0}}}},
                      upsert=True)
    r = archive_bidding_series(db, _snap(1006.0), now=t)
    assert r["ok"] is True
    meta = db.col.find_one({"_id": "2026-11-17"})
    assert meta["prev_pct"] == {"600000": {"pct": 1.2}}
    assert meta["open_pct"] == {"600000": {"pct": 2.0}}
    assert meta["tick_n"] == 2


def test_loader_contract_same_shape_and_order():
    """load_bidding_series：{**meta,"ticks"} 同形；ts 升序、同 ts 按 _id（插入序）。"""
    db = FakeDb()
    seed_series(db.col, "2026-11-17", [
        {"ts": 30.0, "it": [{"s": "600001"}]},
        {"ts": 10.0, "it": [{"s": "600000"}]},
        {"ts": 20.0, "it": [{"s": "600002"}]},
        {"ts": 20.0, "it": [{"s": "600003"}]},
    ], window=["09:15:00", "09:27:00"])
    doc = load_bidding_series(db, "2026-11-17")
    assert doc["tick_n"] == 4 and doc["window"] == ["09:15:00", "09:27:00"]
    assert [t["ts"] for t in doc["ticks"]] == [10.0, 20.0, 20.0, 30.0]
    assert [t["it"][0]["s"] for t in doc["ticks"]] == \
        ["600000", "600002", "600003", "600001"], "同 ts 页序按 _id（插入序）"
    assert all("_id" not in t and "date" not in t for t in doc["ticks"]), \
        "tick 投影 ts/n/it（JSON 安全，合同同形）"
    assert load_bidding_series(db, "2026-11-18") is None


def test_loader_codes_only_lightweight():
    db = FakeDb()
    seed_series(db.col, "2026-11-17", [
        {"ts": 1.0, "it": [{"s": "600001", "zt_buy_amount": 1e6},
                            {"s": "600000", "zt_buy_amount": 2e6}]},
        {"ts": 2.0, "it": [{"s": "600001", "zt_buy_amount": 3e6}]},
    ])
    doc = load_bidding_series(db, "2026-11-17", codes_only=True)
    assert doc["codes"] == ["600000", "600001"]
    assert "ticks" not in doc
    assert load_bidding_series(db, "2026-11-18", codes_only=True) is None


def test_derive_stock_series_facts_first_max_last():
    ticks = [
        {"ts": 1.0, "it": [{"s": "600715", "bidding_pct": 2.1,
                            "zt_buy_amount": 1000000}]},
        {"ts": 6.5, "it": [{"s": "600715", "bidding_pct": 5.0,
                            "zt_buy_amount": 3000000}]},
        {"ts": 12.0, "it": [{"s": "600715", "bidding_pct": 4.2,
                             "zt_buy_amount": 2500000}]},
        {"ts": 12.0, "it": [{"s": "000831", "bidding_pct": None,
                             "zt_buy_amount": None}]},
    ]
    facts = _derive_stock_series_facts(ticks)
    f = facts["600715"]
    assert f["first"]["ts"] == 1.0 and f["last"]["ts"] == 12.0
    assert f["max"]["ts"] == 6.5 and f["max"]["zt_buy_amount"] == 3000000
    # 缺值股：帧在、字段如实缺失（None 不冒充 0）
    g = facts["000831"]
    assert g["first"]["bidding_pct"] is None and g["max"] is None


def test_read_route_absent_and_present(monkeypatch):
    import backend.data.repositories.repository_factory as rf
    db = FakeDb()
    monkeypatch.setattr(rf, "get_runtime_mongodb_database", lambda: db)
    # 缺席路径
    r = get_auction_bidding_series("2026-11-17")
    assert r["ok"] is True and r["absent"] is True and r["ticks"] == []
    # 在档路径：先落两个 tick 再读
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(db, _snap(1000.0), now=t)
    archive_bidding_series(db, _snap(1006.0), now=t)
    r2 = get_auction_bidding_series("2026-11-17")
    assert r2["absent"] is False and r2["tickN"] == 2
    assert set(r2["stockFacts"].keys()) == {"600000", "600001"}
    assert r2["stockFacts"]["600000"]["first"]["ts"] == 1000.0


def test_loader_legacy_shape_passthrough():
    """review S1：未迁移旧嵌入档原样透传（显式 "ticks" 键不覆盖嵌入数组
    伪装空档——缺位不伪装 §4.0；迁移漏档/回滚重导入后未迁即读的守卫）。"""
    db = FakeDb()
    db.col.insert_one({"_id": "2026-11-18", "date": "2026-11-18",
                       "ticks": [{"ts": 1.0, "n": 1,
                                  "it": [{"s": "600102", "zt_buy_amount": 1e6}]},
                                 {"ts": 2.0, "n": 1,
                                  "it": [{"s": "600103", "zt_buy_amount": 2e6}]}],
                       "prev_pct": {"600102": {"pct": 5.5}}})
    doc = load_bidding_series(db, "2026-11-18")
    assert [t["ts"] for t in doc["ticks"]] == [1.0, 2.0], "嵌入 ticks 原样透传"
    assert doc["prev_pct"]["600102"]["pct"] == 5.5, "附加字段保全"
    codes_doc = load_bidding_series(db, "2026-11-18", codes_only=True)
    assert codes_doc["codes"] == ["600102", "600103"], "codes_only 从嵌入 ticks 派生"
    assert "ticks" not in codes_doc, "codes_only 轻量（不带全量嵌入 ticks）"


def test_meta_update_failure_retry_then_visible():
    """review S5：meta $inc 失败单次重试；再败返回 write_failed:meta_update
    （fail-visible；tick 已入库不丢数据，读侧计数派生自 len(ticks)）。"""
    db = FakeDb()
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    real_upd = db.col.update_one
    calls = {"n": 0}

    def flaky(q, upd, upsert=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("conn reset")
        return real_upd(q, upd, upsert=upsert)
    db.col.update_one = flaky
    r = archive_bidding_series(db, _snap(1000.0), now=t)
    assert r["ok"] is True and calls["n"] == 2, "首败重试成功，不误报"
    assert r["tick_n"] == 1
    # 两连败：结构化留痕，tick 文档仍在（不静默吞数据）
    calls["n"] = 0

    def always_fail(q, upd, upsert=False):
        calls["n"] += 1
        raise OSError("conn reset")
    db.col.update_one = always_fail
    r2 = archive_bidding_series(db, _snap(1006.0), now=t)
    assert r2["ok"] is False and r2["reason"] == "write_failed:meta_update:OSError"
    assert calls["n"] == 2, "单次重试（无循环）"
    assert db.col.count_documents({"it": {"$exists": True}}) == 2


def test_series_index_ensured_on_write():
    """review S3：写路径幂等建 {date:1,ts:1}（全新库/重建测试库不走迁移也有索引）。"""
    db = FakeDb()
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(db, _snap(1000.0), now=t)
    assert [("date", 1), ("ts", 1)] in db.col.indexes
    n_idx = len(db.col.indexes)
    archive_bidding_series(db, _snap(1006.0), now=t)
    assert len(db.col.indexes) == n_idx, "同库幂等（进程级缓存不重复建）"


def test_trial_route_dates_excludes_tick_docs(monkeypatch):
    """review S4：日期索引 _id $type:string 只命中日 meta（tick ObjectId 不混入，
    走 _id 天然索引不 collscan）。"""
    import backend.data.repositories.repository_factory as rf
    from backend.api.hotlist_jev_auction_routes import get_auction_trial

    db = FakeDb()
    others = FakeSeriesCol()

    class MixedDb(FakeDb):
        def __getitem__(self, name):
            if name == "kpl_bidding_series":
                return self.col
            return others
    mdb = MixedDb()
    monkeypatch.setattr(rf, "get_runtime_mongodb_database", lambda: mdb)
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(mdb, _snap(1000.0, date="2026-11-17"), now=t)
    archive_bidding_series(mdb, _snap(1006.0, date="2026-11-17"), now=t)
    archive_bidding_series(mdb, _snap(1000.0, date="2026-11-18"), now=t)
    r = get_auction_trial("2026-11-17")
    assert r["ok"] is True
    assert "2026-11-17" in r["dates"] and "2026-11-18" in r["dates"]
    assert all(d.count("-") == 2 for d in r["dates"]), \
        f"日期索引无 tick ObjectId 混入：{r['dates']}"
