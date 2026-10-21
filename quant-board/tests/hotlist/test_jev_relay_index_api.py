# -*- coding: utf-8 -*-
"""relay-index 读口测试（2026-10-11 毒带观察 chip 原料：series join EOD day_temperature）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）。join 语义：
- EOD ok 文档存在 → dayTemperature=round(温度,1)
- 缺 EOD / 温度字段非数值 → dayTemperature=None 原样透传（fail-visible，不伪造）
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_D1, _D2, _D3 = "2026-09-22", "2026-09-23", "2026-09-24"


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
                elif r.get(k) != v:
                    return False
            return True
        excl = {k for k, v in (projection or {}).items() if v == 0}
        return Cursor([{k: v for k, v in dict(r).items() if k not in excl}
                       for r in self.rows if match(r)])

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


def _relay(date, idx):
    return {"_id": f"{date}:RELAY", "tradingDate": date, "status": "ok",
            "questionSetVersion": "v6", "relayIndex": idx, "relayPhase": "divergence",
            "narrative": "SECRET", "usage": {"input_tokens": 1, "output_tokens": 2},
            "relayStructure": {"mainline": {"name": "半导体"},
                               "totalLeader": {"code": "600001", "name": "甲"}},
            "computedAt": f"{date}T18:00:00"}


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({
        "hotlist_jev_relay_index": FakeCol(
            [_relay(_D1, 46.3), _relay(_D2, 64.4), _relay(_D3, 51.1)]),
        # EOD：D1 有 ok 温度（58.36，不取整原值透传）；D2 degraded（99 不得泄漏）；
        # D3 ok 但 scores 缺 day_temperature 字段 → 同样 None（三路降级全锁）
        "hotlist_jev_sentiment": FakeCol([
            {"_id": f"{_D1}:eod", "tradingDate": _D1, "kind": "eod", "status": "ok",
             "scores": {"day_temperature": 58.36}},
            {"_id": f"{_D2}:eod", "tradingDate": _D2, "kind": "eod", "status": "degraded",
             "scores": {"day_temperature": 99.0}},
            {"_id": f"{_D3}:eod", "tradingDate": _D3, "kind": "eod", "status": "ok",
             "scores": {}},
        ]),
    })
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    return TestClient(app)


def test_relay_index_joins_day_temperature(client):
    r = client.get("/api/hotlist-jev/relay-index")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    series = {s["tradingDate"]: s for s in body["series"]}
    assert series[_D1]["dayTemperature"] == 58.36
    # 缺 ok EOD → None 原样透传（degraded 温度 99 不得泄漏成假温度）
    assert series[_D2]["dayTemperature"] is None
    # ok EOD 但缺 day_temperature 字段 → None（不伪造）
    assert series[_D3]["dayTemperature"] is None
    # day 文档（最新日）同样携带
    assert body["day"]["dayTemperature"] is None
    # 投影边界：narrative 不出读口
    assert "narrative" not in series[_D1]


def test_relay_index_projection_boundary_of_relay_structure(client):
    """v6 投影边界：`relayStructure` 只随单日 `day` 下发，序列行必须剔除（防 400 日载荷膨胀）。

    前端「板块与龙头」子视图读 `day.relayStructure`（或判定明细按日懒拉的完整存档）；
    序列仅服务列表/图表/space 扫描，不得携带结构体。
    """
    r = client.get("/api/hotlist-jev/relay-index")
    assert r.status_code == 200
    body = r.json()
    assert all("relayStructure" not in s for s in body["series"]), \
        "序列行不得携带 relayStructure（投影必须排除）"
    # 单日 day 必须保留（子视图唯一数据源）
    assert body["day"]["relayStructure"]["mainline"]["name"] == "半导体"
    assert body["day"]["relayStructure"]["totalLeader"]["code"] == "600001"


def test_relay_index_without_any_eod(monkeypatch):
    """全库无 EOD 文档：join 静默降级 None，读口不报错（fail-visible）。"""
    db = FakeDb({"hotlist_jev_relay_index": FakeCol([_relay(_D1, 46.3), _relay(_D2, 64.4)])})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/relay-index", params={"days": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["series"]) == 2
    assert all(s["dayTemperature"] is None for s in body["series"])
    assert "dayTemperatureDegraded" not in body


def test_relay_index_join_failure_degrades_field_not_route(monkeypatch):
    """EOD 集合查询异常：温度字段整体降级 None + 结构化标记，relay 序列照常返回（§4.0 部分失败不阻断）。"""
    class BoomCol(FakeCol):
        def find(self, query=None, projection=None):
            if query and "scores.day_temperature" in (projection or {}):
                raise RuntimeError("mongo down")
            return super().find(query, projection)

    db = FakeDb({"hotlist_jev_relay_index": FakeCol([_relay(_D1, 46.3)])})
    db.cols["hotlist_jev_sentiment"] = BoomCol([])
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    client = TestClient(app)
    r = client.get("/api/hotlist-jev/relay-index")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["series"]) == 1
    assert body["series"][0]["dayTemperature"] is None
    assert "dayTemperatureDegraded" in body


# ── 弱转强节点信号（2026-10-21 立项，用户需求：列表直观看节点） ─────────────
def test_relay_index_attaches_wzs_per_row(client, monkeypatch):
    """series/day 每行携带 wzs 分类结果（单源 analysis/hotlist/weak_to_strong）。"""
    import backend.analysis.hotlist.weak_to_strong as W
    fixed = {_D1: {"hit": False, "continuation": False, "prevIdx": None, "idx": 46.3,
                   "confirm": [], "reason": "prev_not_weak", "state": None},
             _D2: {"hit": True, "continuation": False, "prevIdx": 39.0, "idx": 64.4,
                   "confirm": ["dt_down", "zt_up"], "reason": None, "state": "wzs"},
             _D3: {"hit": False, "continuation": True, "prevIdx": 64.4, "idx": 51.1,
                   "confirm": [], "reason": "prev_not_weak", "state": "strong"}}
    monkeypatch.setattr(W, "classify_series", lambda db, *a, **k: fixed)
    body = client.get("/api/hotlist-jev/relay-index").json()
    assert body["ok"] is True and "wzsDegraded" not in body
    series = {s["tradingDate"]: s for s in body["series"]}
    assert series[_D2]["wzs"]["hit"] is True and series[_D2]["wzs"]["state"] == "wzs"
    assert series[_D3]["wzs"]["continuation"] is True and series[_D3]["wzs"]["state"] == "strong"
    assert body["day"]["wzs"]["continuation"] is True


def test_relay_index_wzs_failure_degrades_not_route(client, monkeypatch):
    """分类器抛异常（存储故障）→ wzs=None + degraded 标注，读口不倒；
    原料缺失（如 zt 帧缺）不走降级，分类器按「结构确认缺失」正常归类（fail-visible 语义）。"""
    body = client.get("/api/hotlist-jev/relay-index").json()
    assert body["ok"] is True
    assert all(s.get("wzs") is not None for s in body["series"]), "原料缺失≠降级：仍出分类（无 zt 序列→结构确认缺失路径）"
    assert all(s["wzs"]["reason"] in ("insufficient_history", "prev_not_weak", "no_structural_confirm")
               for s in body["series"])
    assert "wzsDegraded" not in body
    import backend.analysis.hotlist.weak_to_strong as W
    def _boom(db, *a, **k):
        raise RuntimeError("storage broken")
    monkeypatch.setattr(W, "classify_series", _boom)
    body2 = client.get("/api/hotlist-jev/relay-index").json()
    assert body2["ok"] is True and all(s.get("wzs") is None for s in body2["series"])
    assert "wzsDegraded" in body2
