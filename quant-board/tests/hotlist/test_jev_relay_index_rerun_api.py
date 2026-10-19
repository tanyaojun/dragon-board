# -*- coding: utf-8 -*-
"""relay-index 单日复跑写口测试（2026-10-19 工作台「重跑」按钮后端）。

全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）：`run_relay_index_day` 被替换为
直接写假库的 stub，本测试只验路由适配 / token 前置 / 返回形状；真实判定链由
`test_jev_relay_index.py` 覆盖。

fail-visible 约定：重跑失败照常返回 degraded 文档的 errorCode/errorDetail（不伪造成功）；
韭研 final 缺失导致未写文档时返回 not_written（不伪装成功）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest
from fastapi.testclient import TestClient

from backend.main import app

_DATE = "2026-10-19"
_ROUTE = "/api/hotlist-jev/relay-index/rerun"


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find_one(self, query=None, projection=None, sort=None):
        for r in self.rows:
            if all(r.get(k) == v for k, v in (query or {}).items()):
                return dict(r)
        return None

    def replace_one(self, query, doc, upsert=False):
        for i, r in enumerate(self.rows):
            if all(r.get(k) == v for k, v in (query or {}).items()):
                self.rows[i] = dict(doc)
                return
        self.rows.append(dict(doc))


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


@pytest.fixture()
def client(monkeypatch):
    db = FakeDb({"hotlist_jev_relay_index": FakeCol()})
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db,
    )
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")  # 路由前置只检查存在，不真调
    return TestClient(app), db


def test_rerun_calls_production_entry_and_returns_day(monkeypatch, client):
    c, db = client
    seen: dict = {}

    def fake_run(db_, dates, *, force=False, dataset_id="dragonboard_live", **kw):
        seen.update(dates=list(dates), force=force, dataset_id=dataset_id)
        db_.cols["hotlist_jev_relay_index"].replace_one(
            {"_id": f"{dates[0]}:RELAY"},
            {"_id": f"{dates[0]}:RELAY", "tradingDate": dates[0], "status": "ok",
             "questionSetVersion": "v6", "relayIndex": 40.7, "relayPhase": "bottoming",
             "relayStructure": {"mainline": {"name": "半导体"}},
             "usage": {"input_tokens": 7193, "output_tokens": 337}})

    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day", fake_run)
    r = c.post(_ROUTE, json={"date": _DATE})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["relayIndex"] == 40.7 and body["relayPhase"] == "bottoming"
    # 返回与 GET day 同形：完整文档（含 relayStructure，供前端子视图复用）
    assert body["day"]["relayStructure"]["mainline"]["name"] == "半导体"
    # 复用生产入口、默认 force（当日已 ok 也可重判）
    assert seen == {"dates": [_DATE], "force": True, "dataset_id": "dragonboard_live"}


def test_rerun_force_false_respected(monkeypatch, client):
    c, db = client
    seen: dict = {}
    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day",
                        lambda db_, dates, *, force=False, dataset_id="dragonboard_live", **k:
                        seen.update(force=force) or
                        db_.cols["hotlist_jev_relay_index"].replace_one(
                            {"_id": f"{dates[0]}:RELAY"},
                            {"_id": f"{dates[0]}:RELAY", "tradingDate": dates[0],
                             "status": "ok", "relayIndex": 1.0}))
    body = c.post(_ROUTE, json={"date": _DATE, "force": False}).json()
    assert seen["force"] is False and body["ok"] is True


def test_rerun_degraded_passthrough_not_faked(monkeypatch, client):
    """重跑再次网络失败：返回 degraded 原样错误，绝不伪造 ok（§4.0）。"""
    c, db = client

    def fake_run(db_, dates, *, force=False, dataset_id="dragonboard_live", **kw):
        db_.cols["hotlist_jev_relay_index"].replace_one(
            {"_id": f"{dates[0]}:RELAY"},
            {"_id": f"{dates[0]}:RELAY", "tradingDate": dates[0], "status": "degraded",
             "errorCode": "http_error", "errorDetail": "network: URLError: SSL EOF",
             "relayIndex": None, "usage": {}})

    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day", fake_run)
    body = c.post(_ROUTE, json={"date": _DATE}).json()
    assert body["ok"] is False and body["status"] == "degraded"
    assert body["errorCode"] == "http_error" and "SSL EOF" in body["errorDetail"]


def test_rerun_not_written_when_pool_missing(monkeypatch, client):
    """韭研 final 缺失 → 入口只跳过不写文档：返回 not_written，不伪装成功。"""
    c, db = client
    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day",
                        lambda *a, **k: None)
    body = c.post(_ROUTE, json={"date": _DATE}).json()
    assert body["ok"] is False and body["errorCode"] == "not_written"


def test_rerun_requires_token_and_bad_date(monkeypatch, client):
    c, db = client
    called: list = []
    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day",
                        lambda *a, **k: called.append(1))
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    body = c.post(_ROUTE, json={"date": _DATE}).json()
    assert body["errorCode"] == "missing_token" and not called
    # token 在场但 date 空 → bad_date（同样不调用模型）
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    body = c.post(_ROUTE, json={"date": "  "}).json()
    assert body["errorCode"] == "bad_date" and not called


def test_rerun_route_is_post_only_and_not_shadowed(monkeypatch, client):
    """写口只挂 POST；GET /relay-index 读口不受影响（防路由覆盖）。"""
    c, db = client
    assert c.get(_ROUTE).status_code == 405

# ── 2026-10-19 评审 F6：旧档不得冒充「本次重跑结果」─────────────────────────────
def test_rerun_skipped_by_entry_is_not_rerun_not_stale_ok(monkeypatch, client):
    """该日已有 ok 旧档 + 入口因韭研 final 缺失跳过 → not_rerun（不得报 ok，也不得报旧 errorCode）。"""
    c, db = client
    col = db.cols["hotlist_jev_relay_index"]
    col.replace_one({"_id": f"{_DATE}:RELAY"},
                    {"_id": f"{_DATE}:RELAY", "tradingDate": _DATE, "status": "ok",
                     "relayIndex": 33.3, "computedAt": "2026-10-18T16:20:00"})
    # 入口跳过：什么都没写（真实现里 not _pool_of(db, date) 分支）
    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day",
                        lambda db_, dates, **k: None)

    body = c.post(_ROUTE, json={"date": _DATE}).json()

    assert body["ok"] is False and body["errorCode"] == "not_rerun"
    assert "未重判" in body["error"] and "韭研 final" in body["error"]
    assert body["status"] == "ok", "旧档原样回带（仅供诊断），但 ok=false 已标明本次没重算"
    assert body["day"]["relayIndex"] == 33.3


def test_rerun_refreshed_computed_at_reports_ok(monkeypatch, client):
    """computedAt 刷新 ⇒ 本次真重判：正常报 ok 与本次读数。"""
    c, db = client
    db.cols["hotlist_jev_relay_index"].replace_one(
        {"_id": f"{_DATE}:RELAY"},
        {"_id": f"{_DATE}:RELAY", "tradingDate": _DATE, "status": "degraded",
         "computedAt": "2026-10-19T16:00:00"})

    def fake_run(db_, dates, **kw):
        db_.cols["hotlist_jev_relay_index"].replace_one(
            {"_id": f"{dates[0]}:RELAY"},
            {"_id": f"{dates[0]}:RELAY", "tradingDate": dates[0], "status": "ok",
             "relayIndex": 40.7, "computedAt": "2026-10-19T19:30:00"})

    monkeypatch.setattr("backend.operations.jev_relay_index.run_relay_index_day", fake_run)
    body = c.post(_ROUTE, json={"date": _DATE}).json()

    assert body["ok"] is True and body["relayIndex"] == 40.7


def test_page_proxy_post_timeout_covers_retry_budget():
    """F7：:8008 POST 透传超时必须≥jev 退避预算（否则页面报失败而 :8000 仍在跑并可能写库成功）。"""
    from backend.services.jev.jev_client import JEV_RETRY_DELAYS
    from backend import serve_relay_page

    worst_case = (len(JEV_RETRY_DELAYS) + 1) * 60 + sum(JEV_RETRY_DELAYS)   # 5 次尝试×60s 读超时 + 退避
    assert serve_relay_page._POST_PROXY_TIMEOUT_SECONDS >= worst_case
