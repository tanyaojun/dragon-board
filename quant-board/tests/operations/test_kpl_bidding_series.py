# -*- coding: utf-8 -*-
"""竞价过程事实序列（kpl_bidding_series）测试——纯假库，零网络零真实 collector。

锁定口径（2026-11-16 事实采集裁决；2026-11-18 用户裁决拆窗门控+节流）：
1. 单写者=collector 推送即全量落库（§4.0 数据链禁硬门禁），无窗门控无节流；
   竞价语义窗 [09:15,09:27) 过滤由消费层 derive 承担（计数留痕）；
2. $slice 存储预算（SERIES_MAX_TICKS，非数据门控）；
3. tick=压缩行（具名竞价字段短键），不冒充 WzsLinker 试盘字段语义；
4. 读口派生 first/max/last 观测值（缺字段如实缺失，不补 0）。
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.kpl_daban_archiver import (
    SERIES_MAX_TICKS,
    TZ_SHANGHAI,
    archive_bidding_series,
)
from backend.api.hotlist_jev_auction_routes import (
    _derive_stock_series_facts,
    get_auction_bidding_series,
)


class FakeSeriesDb:
    """支持 $push $each/$slice + $set upsert 的最小假库（仅 bidding_series 路径）。"""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def __getitem__(self, name):
        return self

    def find_one(self, q):
        import copy
        doc = self.docs.get(q["_id"])
        return copy.deepcopy(doc) if doc else None  # pymongo 快照语义（非活引用）

    def update_one(self, q, upd, upsert=False):
        d = self.docs.setdefault(q["_id"], {"_id": q["_id"], "ticks": []})
        push = upd.get("$push") or {}
        spec = push.get("ticks") or {}
        each = spec.get("$each") or []
        sl = spec.get("$slice")
        if sl is not None:
            d["ticks"] = (d["ticks"] + list(each))[int(sl):]
        else:
            d["ticks"] = d["ticks"] + list(each)
        d.update(upd.get("$set") or {})


def _snap(ts: float, date: str = "2026-11-17", n_stocks: int = 2):
    return {"ok": True, "date": date, "ts": ts, "pid_type": 8,
            "items": [{"stock_id": f"60{i:04d}", "name": f"股{i}",
                       "bidding_pct": 5.0 + i, "bidding_amount": 1e6 * (i + 1),
                       "bidding_net": 5e5, "bidding_turnover": 0.5,
                       "zt_buy_amount": 2e6 * (i + 1), "price": "10.0", "pct": 10.0,
                       "real_float": 1e9, "quotas": ["x"] * 28}
                      for i in range(n_stocks)]}


def _in_window(dt: datetime) -> datetime:
    return dt.replace(tzinfo=TZ_SHANGHAI)


def test_out_of_window_now_appended():
    """2026-11-18 拆窗门控：窗外 tick 同样入档（全量保存，消费层过滤）。
    旧 out_of_window 拒绝判据作废。"""
    db = FakeSeriesDb()
    r = archive_bidding_series(db, _snap(1000.0),
                               now=_in_window(datetime(2026, 11, 17, 10, 0)))
    assert r["ok"] is True and r["tick_n"] == 1
    assert "2026-11-17" in db.docs


def test_in_window_append_and_compact():
    db = FakeSeriesDb()
    r = archive_bidding_series(db, _snap(1000.0),
                               now=_in_window(datetime(2026, 11, 17, 9, 20)))
    assert r["ok"] is True and r["tick_n"] == 1 and r["item_n"] == 2
    doc = db.docs["2026-11-17"]
    assert doc["date"] == "2026-11-17" and doc["last_n"] == 2
    tick = doc["ticks"][-1]
    it = tick["it"][0]
    assert set(it.keys()) == {"s", "bidding_pct", "bidding_amount", "bidding_net",
                              "bidding_turnover", "zt_buy_amount", "price", "pct",
                              "real_float"}, "tick 必须是压缩行（短键、无 quotas）"
    assert "quotas" not in it


def test_no_throttle_consecutive_ticks_all_appended():
    """2026-11-18 拆节流：相邻 tick（<5s）全部入档——tick 密度=服务器推送
    密度，不再人为稀释（11-18 与 WZS 对拍失真教训：稀疏采样致 first/last/peak
    全错）。旧 skipped_throttled 判据作废。"""
    db = FakeSeriesDb()
    t0 = _in_window(datetime(2026, 11, 17, 9, 20))
    archive_bidding_series(db, _snap(1000.0), now=t0)
    r2 = archive_bidding_series(db, _snap(1002.0), now=t0)
    assert r2["ok"] is True and r2.get("skipped") is None
    assert len(db.docs["2026-11-17"]["ticks"]) == 2, "相邻 tick 全落"
    r3 = archive_bidding_series(db, _snap(1006.0), now=t0)
    assert r3["ok"] is True and r3["tick_n"] == 3


def test_slice_cap_drops_oldest():
    db = FakeSeriesDb()
    db.docs["2026-11-17"] = {"_id": "2026-11-17", "ticks": [
        {"ts": float(i), "n": 1, "it": [{"s": "000001"}]} for i in range(SERIES_MAX_TICKS)]}
    r = archive_bidding_series(db, _snap(99999.0),
                               now=_in_window(datetime(2026, 11, 17, 9, 20)))
    assert r["ok"] is True
    ticks = db.docs["2026-11-17"]["ticks"]
    assert len(ticks) == SERIES_MAX_TICKS, "$slice 上限内追加"
    assert ticks[0]["ts"] == 1.0, "最老 tick 被丢弃（保窗口尾部）"


def test_empty_snapshot_and_no_date_rejected():
    db = FakeSeriesDb()
    t = _in_window(datetime(2026, 11, 17, 9, 20))
    r1 = archive_bidding_series(db, _snap(1000.0, n_stocks=0), now=t)
    assert r1["ok"] is False and r1["reason"] == "empty_snapshot"
    snap = _snap(1000.0)
    snap.pop("date")
    r2 = archive_bidding_series(db, snap, now=t)
    assert r2["ok"] is False and r2["reason"] == "no_date"
    assert db.docs == {}


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
    db = FakeSeriesDb()
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
