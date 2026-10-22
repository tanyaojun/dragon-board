# -*- coding: utf-8 -*-
"""涨停复盘个股驱动打标「单股复跑」端点（2026-10-21 用户需求，日志详情卡【重跑】）。

mock 化，绝不真调 jev（AGENTS §1.2-7）。钉住：
1. 复用 ``jev_label_jiuyan.run`` 且 force + only_codes 单股过滤（不整日重烧 ≈21 万 tokens）；
2. F6：computedAt 未刷新 → 显式 not_rerun，不用旧档冒充成功；
3. 槽位沿用旧档 labelSlot；伪午盘（midday 名单不可投喂）显式拒绝，不按午盘口径冒判；
4. 旧档带 phaseBand（五题合并代际）→ with_stock_phase=True 同 call 重建，相位不丢。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import hotlist_jev_limitup_routes as limitup_module


def _client(monkeypatch, existing_doc, midday_state=None):
    calls = {}

    def fake_run(start, end, dry_run, token, acc, **kw):
        calls["kw"] = kw
        if existing_doc.get("_simulate_skip"):
            return {}
        existing_doc["computedAt"] = "2026-10-21T12:35:00"
        return {}

    class _Col:
        def find_one(self, q, proj=None):
            if q.get("_id") == existing_doc.get("_id"):
                return dict(existing_doc)
            return None

    class _Db:
        def __getitem__(self, name):
            return _Col()

    monkeypatch.setenv("JEV_TYPESAFE_KEY", "test-key")
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: _Db())

    import backend.operations.jev_label_jiuyan as jiuyan_mod
    monkeypatch.setattr(jiuyan_mod, "run", fake_run)
    if midday_state is not None:
        monkeypatch.setattr(jiuyan_mod, "midday_source_state", lambda db_, date_: midday_state)
    return limitup_module, calls


def _app(module):
    app = FastAPI()
    app.include_router(module.router)
    return TestClient(app)


def test_rerun_success_final_slot(monkeypatch):
    doc = {"_id": "2026-10-20:600003", "tradingDate": "2026-10-20", "code": "600003",
           "name": "双连板", "labelSlot": "final", "status": "degraded",
           "label": "capital_flow", "catalystDepth": "core_main_business",
           "freshness": "continuing", "buySideLogic": "sector_follow",
           "questionSetVersion": "v3.3",
           "computedAt": "2026-10-20T16:05:00"}
    module, calls = _client(monkeypatch, doc)
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "600003"}).json()
    assert body["ok"] is True
    assert body["doc"]["computedAt"] == "2026-10-21T12:35:00"
    # 2026-10-22 报障修复：返回档必须含三题结论（否则详情卡横幅看不到新鲜度变化）
    assert body["doc"]["freshness"] == "continuing"
    assert body["doc"]["catalystDepth"] == "core_main_business"
    assert body["doc"]["buySideLogic"] == "sector_follow"
    assert body["doc"]["questionSetVersion"] == "v3.3"
    kw = calls["kw"]
    assert kw.get("force") is True, "重跑必须 force（覆盖幂等）"
    assert kw.get("confirm_budget") is True
    assert kw.get("only_codes") == {"600003"}, "必须单股过滤（不过滤会整日重烧）"
    assert kw.get("slot") == "final"
    assert kw.get("with_stock_phase") is False


def test_rerun_midday_slot_keeps_phase_and_blocks_fake_noon(monkeypatch):
    """midday 档沿用午盘口径；旧档带 phaseBand → with_stock_phase=True（相位不丢）。"""
    doc = {"_id": "2026-10-20:600003", "tradingDate": "2026-10-20", "code": "600003",
           "labelSlot": "midday", "phaseBand": "heat_sustain",
           "computedAt": "2026-10-20T12:35:00"}
    module, calls = _client(
        monkeypatch, doc,
        midday_state={"ok": True, "found": True, "fetchedAt": "2026-10-20 12:31:00",
                      "reason": None, "detail": None})
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "600003"}).json()
    assert body["ok"] is True
    kw = calls["kw"]
    assert kw.get("slot") == "midday"
    assert kw.get("with_stock_phase") is True


def test_rerun_refuses_fake_noon_midday(monkeypatch):
    """伪午盘（收盘后补写的 midday 名单）→ 显式拒绝，不按午盘口径冒判（§4.0）。"""
    doc = {"_id": "2026-10-20:600003", "tradingDate": "2026-10-20", "code": "600003",
           "labelSlot": "midday", "computedAt": "2026-10-20T12:35:00"}
    module, calls = _client(
        monkeypatch, doc,
        midday_state={"ok": False, "found": True, "fetchedAt": "2026-10-20 20:04:00",
                      "reason": "midday_doc_not_noon", "detail": "fetchedAt 不在午盘窗"})
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "600003"}).json()
    assert body["ok"] is False
    assert body["errorCode"] == "midday_not_feedable"
    assert "kw" not in calls, "拒绝路径不得触达 run（不烧 token）"


def test_rerun_reports_not_rerun_when_computed_at_stale(monkeypatch):
    """F6：两次 jev 调用均失败（computedAt 未刷新）→ 显式 not_rerun，不用旧档冒充成功。"""
    doc = {"_id": "2026-10-20:600003", "tradingDate": "2026-10-20", "code": "600003",
           "labelSlot": "final", "computedAt": "2026-10-20T16:05:00",
           "_simulate_skip": True}
    module, _ = _client(monkeypatch, doc)
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "600003"}).json()
    assert body["ok"] is False
    assert body["errorCode"] == "not_rerun"


def test_rerun_requires_token_and_rejects_unknown_code(monkeypatch):
    module, _ = _client(
        monkeypatch, {"_id": "2026-10-20:600003", "code": "600003",
                      "computedAt": "2026-10-20T16:05:00"})
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_CF_TOKEN", raising=False)
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "600003"}).json()
    assert body["ok"] is False and body["errorCode"] == "missing_token"
    monkeypatch.setenv("JEV_TYPESAFE_KEY", "k")
    body = _app(module).post("/api/hotlist-jev/limitup-labels/rerun",
                             json={"date": "2026-10-20", "code": "000000"}).json()
    assert body["ok"] is False and body["errorCode"] == "not_found"
