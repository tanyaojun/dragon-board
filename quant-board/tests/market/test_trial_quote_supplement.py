# -*- coding: utf-8 -*-
"""试盘行情补全测试（昨涨幅落库采集 + 现价 Redis 读补；零网络零 jev）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.market import trial_quote_supplement as S

DATE = "2026-11-18"


@pytest.fixture(autouse=True)
def _enable_channel(monkeypatch):
    """conftest 全局禁真外呼（KPL_PREV_PCT_ENABLED=0）；单测 monkeypatch 取数，逐测试启用。"""
    monkeypatch.setenv("KPL_PREV_PCT_ENABLED", "1")


class FakeCol:
    def __init__(self):
        self.docs = {}

    def find_one(self, q=None, projection=None):
        d = self.docs.get((q or {}).get("_id"))
        return dict(d) if d else None

    def update_one(self, q, update, upsert=False):
        key = q.get("_id")
        d = self.docs.setdefault(key, {"_id": key})
        d.update(update.get("$set") or {})


class FakeDb:
    def __init__(self):
        self.cols = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


def _seed_universe(db, codes=("600102", "600100")):
    db[S.COLLECTION_SERIES].docs[DATE] = {"_id": DATE, "ticks": [
        {"ts": 1, "it": [{"s": c, "zt_buy_amount": 1e6} for c in codes]}]}


def _bars(c):
    return {"2026-11-16": {"close": 10.0}, "2026-11-17": {"close": 11.0},
            DATE: {"close": 12.0}}   # 当日未收盘棒必须被过滤


def test_collect_computes_prev_pct_and_filters_today(monkeypatch):
    db = FakeDb()
    _seed_universe(db)
    from backend.operations import tdx_daily_bars as T
    monkeypatch.setattr(T, "fetch_daily_bars", lambda c, **k: _bars(c))
    r = S.collect_prev_day_pct(db, DATE)
    assert r["state"] == "ok" and r["ok_n"] == 2
    ser = db[S.COLLECTION_SERIES].docs[DATE]
    rows = ser["prev_pct"]
    assert rows["600102"]["pct"] == 10.0          # (11/10-1)*100，非当日棒
    assert rows["600102"]["prevDate"] == "2026-11-17"
    assert ser["prev_pct_state"]["attempts_n"] == 2
    assert ser.get("ticks")   # 字段级加字段，ticks 不被触碰


def test_collect_limit_respected(monkeypatch):
    db = FakeDb()
    _seed_universe(db)
    from backend.operations import tdx_daily_bars as T
    monkeypatch.setattr(T, "fetch_daily_bars", lambda c, **k: _bars(c))
    r = S.collect_prev_day_pct(db, DATE, limit=1)
    assert r["batch_n"] == 1 and r["pending_n"] == 1


def test_collect_daily_cap_no_fetch(monkeypatch):
    db = FakeDb()
    _seed_universe(db)
    db[S.COLLECTION_SERIES].docs[DATE].update(
        {"prev_pct_state": {"attempts_n": 10**6}})
    from backend.operations import tdx_daily_bars as T

    def boom(*a, **k):
        raise AssertionError("cap 后不得外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    r = S.collect_prev_day_pct(db, DATE)
    assert r["state"] == "daily_cap"


def test_collect_one_close_not_zero(monkeypatch):
    db = FakeDb()
    _seed_universe(db, codes=("600102",))
    from backend.operations import tdx_daily_bars as T
    monkeypatch.setattr(T, "fetch_daily_bars",
                        lambda c, **k: {"2026-11-17": {"close": 11.0}})
    r = S.collect_prev_day_pct(db, DATE)
    assert r["state"] == "all_failed" and r["backoff_rounds"] == 1
    doc = db[S.COLLECTION_SERIES].docs[DATE]
    assert doc["prev_pct"] == {}
    assert doc["prev_pct_state"]["failed"]["600102"] == "no_two_closes"


def test_collect_backoff_skip_decrements(monkeypatch):
    db = FakeDb()
    _seed_universe(db)
    db[S.COLLECTION_SERIES].docs[DATE] = {
        "_id": DATE, "prev_pct_state": {"backoff_rounds": 2}}
    from backend.operations import tdx_daily_bars as T

    def boom(*a, **k):
        raise AssertionError("退避轮不得外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    r = S.collect_prev_day_pct(db, DATE)
    assert r["state"] == "backoff" and r["remaining"] == 1
    assert db[S.COLLECTION_SERIES].docs[DATE]["prev_pct_state"]["backoff_rounds"] == 1


def test_collect_no_universe_zero_fetch(monkeypatch):
    db = FakeDb()
    from backend.operations import tdx_daily_bars as T

    def boom(*a, **k):
        raise AssertionError("无宇宙不得外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    assert S.collect_prev_day_pct(db, DATE)["state"] == "skipped_no_universe"


class FakeRedis:
    def __init__(self, rows=None, ts=None, fail=False):
        self.rows, self.ts, self.fail = rows or {}, ts, fail

    def hmget(self, key, codes):
        if self.fail:
            raise RuntimeError("redis down")
        return [json.dumps(self.rows[c]) if c in self.rows else None for c in codes]

    def get(self, key):
        return str(self.ts) if self.ts else None


def test_read_realtime_prices(monkeypatch):
    from backend.market_proxy import redis_client as RC
    fake = FakeRedis({"600102": {"f2": 12.5, "f3": 3.2}}, ts=1794965169000)
    monkeypatch.setattr(RC, "get_hotlist_redis_client", lambda: fake)
    out, ts = S.read_realtime_prices(["600102", "600999"])
    assert out == {"600102": {"price": 12.5, "pct": 3.2}}
    assert ts == 1794965169000


def test_read_realtime_prices_redis_down(monkeypatch):
    from backend.market_proxy import redis_client as RC
    monkeypatch.setattr(RC, "get_hotlist_redis_client", lambda: FakeRedis(fail=True))
    assert S.read_realtime_prices(["600102"]) == ({}, None)
    monkeypatch.setattr(RC, "get_hotlist_redis_client", lambda: None)
    assert S.read_realtime_prices(["600102"]) == ({}, None)


# ── 开盘涨幅顺带取数（2026-11-19 修复：零新增外呼，TDX 当日棒 open）──

def _bars_with_open(c):
    b = _bars(c)
    b[DATE] = {"close": 12.0, "open": 11.5}
    return b


def test_collect_open_pct_piggyback_zero_extra_fetch(monkeypatch):
    """同一次 fetch_daily_bars 顺带落 open_pct；双字段完成后零外呼 complete。"""
    db = FakeDb()
    _seed_universe(db)
    from backend.operations import tdx_daily_bars as T
    calls = []

    def spy(c, **k):
        calls.append(c)
        return _bars_with_open(c)
    monkeypatch.setattr(T, "fetch_daily_bars", spy)
    r = S.collect_prev_day_pct(db, DATE)
    assert r["state"] == "ok" and r["ok_n"] == 2 and r["open_ok_n"] == 2
    assert len(calls) == 2, "每股一次取数双字段，零新增外呼"
    ser = db[S.COLLECTION_SERIES].docs[DATE]
    op = ser["open_pct"]["600102"]
    assert op["price"] == 11.5 and op["src"] == "tdx_bar"
    assert op["pct"] == round((11.5 / 11.0 - 1) * 100, 4)
    assert ser["open_pct_state"]["n"] == 2
    assert ser.get("ticks"), "字段级加字段，ticks 不被触碰"

    def boom(*a, **k):
        raise AssertionError("双字段完成后不得外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    assert S.collect_prev_day_pct(db, DATE)["state"] == "complete"


def test_collect_open_band_suspect_skip_and_no_retry(monkeypatch):
    """除权 band 越界（镜像 backfill B1）→ 宁缺勿错只披露，且不重试烧预算。"""
    db = FakeDb()
    _seed_universe(db, codes=("600102",))
    from backend.operations import tdx_daily_bars as T
    bars = {"2026-11-16": {"close": 10.0}, "2026-11-17": {"close": 11.0},
            DATE: {"close": 12.0, "open": 20.0}}   # 涨停价 12.1，20 越界
    monkeypatch.setattr(T, "fetch_daily_bars", lambda c, **k: bars)
    r = S.collect_prev_day_pct(db, DATE)
    ser = db[S.COLLECTION_SERIES].docs[DATE]
    assert ser["open_pct"] == {} and r["open_ok_n"] == 0
    assert ser["open_pct_state"]["bandSuspect"] == ["600102"]

    def boom(*a, **k):
        raise AssertionError("band 嫌疑股不得重试外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    assert S.collect_prev_day_pct(db, DATE)["state"] == "complete"


def test_collect_open_no_today_bar_disclosed_and_no_retry(monkeypatch):
    """review 2026-11-19 minor：取数成功但当日棒缺（停牌等）→ openNoBar 披露
    并退出 pending 面，不逐轮烧日预算（fail-visible）。"""
    db = FakeDb()
    _seed_universe(db, codes=("600102",))
    from backend.operations import tdx_daily_bars as T
    bars = {"2026-11-16": {"close": 10.0}, "2026-11-17": {"close": 11.0}}
    monkeypatch.setattr(T, "fetch_daily_bars", lambda c, **k: dict(bars))
    r = S.collect_prev_day_pct(db, DATE)
    ser = db[S.COLLECTION_SERIES].docs[DATE]
    assert r["ok_n"] == 1, "prev_pct 不受当日棒缺影响"
    assert ser["open_pct"] == {} and r["open_ok_n"] == 0
    assert ser["open_pct_state"]["openNoBar"] == ["600102"]
    assert ser["open_pct_state"]["pending_n"] == 0

    def boom(*a, **k):
        raise AssertionError("当日棒缺股不得重试外呼")
    monkeypatch.setattr(T, "fetch_daily_bars", boom)
    assert S.collect_prev_day_pct(db, DATE)["state"] == "complete"


def test_collect_open_pre0925_not_pending(monkeypatch):
    """当日 09:25 撮合前 open 不列 pending（不烧日预算）；09:25 后同棒顺带取。"""
    import datetime as dt
    cst = dt.timezone(dt.timedelta(hours=8))
    today = dt.datetime.now(cst).strftime("%Y-%m-%d")
    now_pre = dt.datetime.now(cst).replace(hour=9, minute=0, second=0,
                                           microsecond=0).timestamp()
    now_post = dt.datetime.now(cst).replace(hour=9, minute=26, second=0,
                                            microsecond=0).timestamp()
    db = FakeDb()
    db[S.COLLECTION_SERIES].docs[today] = {"_id": today, "ticks": [
        {"ts": 1, "it": [{"s": "600102", "zt_buy_amount": 1e6}]}]}
    from backend.operations import tdx_daily_bars as T
    bars = {"2026-11-16": {"close": 10.0}, "2026-11-17": {"close": 11.0},
            today: {"close": 12.0, "open": 11.5}}
    monkeypatch.setattr(T, "fetch_daily_bars", lambda c, **k: bars)
    r = S.collect_prev_day_pct(db, today, now=now_pre)
    assert r["open_pending_n"] == 0 and r["open_ok_n"] == 0
    assert r["ok_n"] == 1, "prev_pct 不受 09:25 门控影响"
    ser = db[S.COLLECTION_SERIES].docs[today]
    assert ser.get("open_pct") or {} == {}
    r2 = S.collect_prev_day_pct(db, today, now=now_post)
    assert r2["open_ok_n"] == 1
    assert ser["open_pct"]["600102"]["pct"] == round((11.5 / 11.0 - 1) * 100, 4)
