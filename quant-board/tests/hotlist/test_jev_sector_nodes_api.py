# -*- coding: utf-8 -*-
"""sector-nodes 读口测试（2026-10-27 盘中回退裁决：指定日无档 → 回退 < 指定日最新存档）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）。回退语义：
- date=当日无档（16:20 盘后链未落库）→ 返回最近可得存档 + dateFallback 标记
- date=有档日 → 原样返回，无 dateFallback
- date 早于所有档 → doc=None（既有「无存档」路径，不伪造）
- 不传 date → 最新档（现状不变）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

import pytest

from backend.main import app

_D1, _D2, _D3 = "2026-10-24", "2026-10-25", "2026-10-26"


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
        q = query or {}

        def match(r):
            for k, v in q.items():
                if isinstance(v, dict):
                    for op, ov in v.items():
                        if op == "$in" and r.get(k) not in ov:
                            return False
                        if op == "$ne" and r.get(k) == ov:
                            return False
                        if op == "$lt" and not (r.get(k) is not None and str(r.get(k)) < ov):
                            return False
                elif r.get(k) != v:
                    return False
            return True

        return Cursor([dict(r) for r in self.rows if match(r)])

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query)
        if sort:
            for key, direction in reversed(sort):
                found = found.sort(key, direction)
        return found[0] if found else None


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


def _doc(date):
    return {"_id": f"{date}:SECTOR_NODES", "tradingDate": date, "version": "sector-nodes-v2",
            "status": "ok", "degraded": [],
            "rows": [{"board": "机器人", "node": "weakening", "count": 5, "promN": 1,
                      "brokenN": 2, "zhabanN": 1}]}


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({"hotlist_jev_sector_nodes": FakeCol([_doc(_D1), _doc(_D2), _doc(_D3)])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_intraday_falls_back_to_latest_available(client):
    """盘中查当日（无档）→ 回退最近可得存档 + dateFallback 标记（2026-10-27 用户裁决）。"""
    r = client.get("/api/hotlist-jev/sector-nodes", params={"date": "2026-10-27"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["date"] == _D3                          # date 字段=实际生效日
    assert body["doc"]["tradingDate"] == _D3            # 实际给的是最近可得档
    assert body["dateFallback"] == {"requested": "2026-10-27", "served": _D3}


def test_existing_date_returns_doc_without_fallback(client):
    """指定日有档 → 原样返回，不带 dateFallback。"""
    r = client.get("/api/hotlist-jev/sector-nodes", params={"date": _D2})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["doc"]["tradingDate"] == _D2
    assert "dateFallback" not in body


def test_date_before_all_docs_keeps_empty_doc(client):
    """早于所有档 → doc=None 走既有「无存档」路径，不伪造、不误回退。"""
    r = client.get("/api/hotlist-jev/sector-nodes", params={"date": "2026-09-01"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["doc"] is None
    assert "dateFallback" not in body


def test_no_date_returns_latest_doc(client):
    """不传 date → 最新档（现状不变，无 dateFallback）。"""
    r = client.get("/api/hotlist-jev/sector-nodes")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["doc"]["tradingDate"] == _D3
    assert "dateFallback" not in body


def test_fallback_doc_rows_kept_for_main_table(client):
    """回退档是选中日全量文档：rows 原样保留（主表数据源），并带节点分布换算。"""
    r = client.get("/api/hotlist-jev/sector-nodes", params={"date": "2026-10-27"})
    body = r.json()
    doc = body["doc"]
    assert doc["rows"][0]["board"] == "机器人"
    assert doc["nodeDist"] == {"weakening": 1}
