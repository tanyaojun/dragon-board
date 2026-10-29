# -*- coding: utf-8 -*-
"""JEV 读口交易日历回退测试（2026-10-27 用户裁决：文字描述 → 回退显示）。

覆盖面 = 五个带 date 精确匹配的读口 + 共享助手 resolve_view_date：
- /relay-index：day 文档回退（接力四卡/今日连板情绪主表盘中看上一交易日）
- /series：全日无槽位/EOD 文档时整体回退（KPI 前四卡/逐槽/EOD 窗口）
- /limitup-labels、/dieban-review：生效日接线（monkeypatch 捕获委托参数）
- 交易日历口径：回退锚=集合内 < 指定日最大 tradingDate（档案日即交易日），
  盘中当日有档（槽位帧）时不回退（实时优先）。

全 monkeypatch/fake，禁触真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.api.jev_view_date import resolve_view_date
from backend.main import app

_D1, _D2, _TODAY = "2026-10-23", "2026-10-26", "2026-10-27"


class Cursor(list):
    def sort(self, *args):
        key = args[0]
        reverse = len(args) > 1 and args[1] < 0
        list.sort(self, key=lambda r: str(r.get(key) or ""), reverse=reverse)
        return self

    def limit(self, n):
        return Cursor(self[:n])


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        return Cursor([dict(r) for r in self.rows if _match(r, query or {})])

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query)
        if sort:
            for key, direction in reversed(sort):
                found = found.sort(key, direction)
        return found[0] if found else None


def _match(row, query):
    for k, v in query.items():
        if isinstance(v, dict):
            for op, ov in v.items():
                if op == "$in" and row.get(k) not in ov:
                    return False
                if op == "$ne" and row.get(k) == ov:
                    return False
                if op == "$lt" and not (row.get(k) is not None and str(row.get(k)) < ov):
                    return False
                if op == "$gte" and not str(row.get(k) or "") >= ov:
                    return False
                if op == "$lte" and not str(row.get(k) or "") <= ov:
                    return False
        elif row.get(k) != v:
            return False
    return True


class FakeDb:
    def __init__(self, cols=None):
        self.cols = dict(cols or {})

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


# ── resolve_view_date 单元 ────────────────────────────────────────────────

def test_resolve_exact_hit_no_fallback():
    col = FakeCol([{"_id": "a", "tradingDate": _D1}])
    assert resolve_view_date(col, _D1) == (_D1, None)


def test_resolve_miss_falls_back_to_latest_earlier():
    col = FakeCol([{"_id": "a", "tradingDate": _D1}, {"_id": "b", "tradingDate": _D2}])
    assert resolve_view_date(col, _TODAY) == (_D2, {"requested": _TODAY, "served": _D2})


def test_resolve_respects_probe_filter():
    col = FakeCol([
        {"_id": "a", "tradingDate": _D1, "kind": "slot"},
        {"_id": "b", "tradingDate": _D2, "kind": "other"},
    ])
    served, fb = resolve_view_date(col, _TODAY, {"kind": "slot"})
    assert served == _D1 and fb == {"requested": _TODAY, "served": _D1}


def test_resolve_empty_collection_no_fallback():
    served, fb = resolve_view_date(FakeCol(), _TODAY)
    assert served == _TODAY and fb is None


def test_resolve_skips_null_trading_date():
    """null tradingDate 档不参与回退（与序列查询 $ne None 同守卫）。"""
    col = FakeCol([{"_id": "a", "tradingDate": None}])
    served, fb = resolve_view_date(col, _TODAY)
    assert served == _TODAY and fb is None


# ── /relay-index：day 文档回退 ────────────────────────────────────────────

def _relay(date):
    return {"_id": f"{date}:RELAY", "tradingDate": date, "status": "ok",
            "relayIndex": 50.0, "relayPhase": "divergence"}


@pytest.fixture()
def relay_client(monkeypatch):
    db = FakeDb({"hotlist_jev_relay_index": FakeCol([_relay(_D1), _relay(_D2)])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_relay_index_day_falls_back_intraday(relay_client):
    r = relay_client.get("/api/hotlist-jev/relay-index", params={"days": 5, "date": _TODAY})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["date"] == _D2                       # date=实际生效日
    assert body["day"]["tradingDate"] == _D2         # 接力四卡主表数据源
    assert body["dateFallback"] == {"requested": _TODAY, "served": _D2}


def test_relay_index_exact_day_no_fallback(relay_client):
    r = relay_client.get("/api/hotlist-jev/relay-index", params={"days": 5, "date": _D2})
    body = r.json()
    assert body["day"]["tradingDate"] == _D2
    assert "dateFallback" not in body


# ── /series：全日无槽位/EOD 文档时整体回退 ─────────────────────────────────

def _slot(date, slot_time):
    return {"_id": f"{date}:{slot_time}", "datasetId": "dragonboard_live",
            "kind": "slot", "tradingDate": date, "slotTime": slot_time,
            "status": "ok", "answers": {}, "scores": {}}


@pytest.fixture()
def series_client(monkeypatch):
    db = FakeDb({"hotlist_jev_sentiment": FakeCol(
        [_slot(_D1, "10:00"), _slot(_D2, "10:00"), _slot(_D2, "15:00")])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_series_falls_back_when_day_empty(series_client):
    """盘前查当日（全日无档）→ 回退最近有档交易日，date=生效日 + dateFallback。"""
    r = series_client.get("/api/hotlist-jev/series", params={"date": _TODAY})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["date"] == _D2
    assert [s["slotTime"] for s in body["slots"]] == ["10:00", "15:00"]
    assert body["dateFallback"] == {"requested": _TODAY, "served": _D2}


def test_series_keeps_today_when_slots_exist(series_client):
    """盘中当日已有槽位文档 → 实时优先，不回退。"""
    r = series_client.get("/api/hotlist-jev/series", params={"date": _D2})
    body = r.json()
    assert body["date"] == _D2 and len(body["slots"]) == 2
    assert "dateFallback" not in body


# ── /limitup-labels、/dieban-review：生效日接线 ────────────

def test_limitup_labels_delegates_to_fallback_date(monkeypatch):
    captured = {}

    def fake_collect(db, date, with_raw=False):
        captured["date"] = date
        return {"ok": True, "date": date, "stocks": [{"code": "000001"}]}

    monkeypatch.setattr(
        "backend.api.hotlist_jev_limitup_routes.collect_limitup_labels", fake_collect)
    db = FakeDb({"hotlist_jev_driver_labels": FakeCol([
        {"_id": "x", "tradingDate": _D2, "origin": "stock_label", "code": "000001"}])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/limitup-labels", params={"date": _TODAY})
    assert r.status_code == 200
    body = r.json()
    assert captured["date"] == _D2       # 后续梯队/板块/连板 join 全部跟随生效日
    assert body["date"] == _D2
    assert body["dateFallback"] == {"requested": _TODAY, "served": _D2}


def test_dieban_review_delegates_to_fallback_date(monkeypatch):
    captured = {}

    def fake_collect(db, date):
        captured["date"] = date
        return {"ok": True, "date": date, "noData": False, "list": []}

    monkeypatch.setattr(
        "backend.api.hotlist_jev_dieban_routes.collect_dieban_review", fake_collect)
    db = FakeDb({"snapshot_frames": FakeCol([
        {"_id": f"{_D2}:15:00", "type": "half_hour",
         "tradingDate": _D2, "slotTime": "15:00"}])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/dieban-review", params={"date": _TODAY})
    assert r.status_code == 200
    body = r.json()
    assert captured["date"] == _D2
    assert body["dateFallback"] == {"requested": _TODAY, "served": _D2}


def test_dieban_review_keeps_today_when_frame_exists(monkeypatch):
    """盘中当日已有帧 → 实时优先，不回退。"""
    captured = {}

    def fake_collect(db, date):
        captured["date"] = date
        return {"ok": True, "date": date, "noData": False, "list": []}

    monkeypatch.setattr(
        "backend.api.hotlist_jev_dieban_routes.collect_dieban_review", fake_collect)
    db = FakeDb({"snapshot_frames": FakeCol([
        {"_id": f"{_TODAY}:10:00", "type": "half_hour",
         "tradingDate": _TODAY, "slotTime": "10:00"}])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    client.get("/api/hotlist-jev/dieban-review", params={"date": _TODAY})
    assert captured["date"] == _TODAY
