# -*- coding: utf-8 -*-
"""分带实测读数读口测试（GET /api/hotlist-jev/relay-band，2026-10-18 relay_page 可视化消费）。

读口语义：**不加工不重算**——把离线诊断（`scripts/jev_relay_band_diagnostic.py --emit-json`）
的产物原样交给前端；文件缺失/损坏/空 → ok=False + reason + hint（fail-visible：
前端显式标「分带表未生成」，不静默空表，也不拿前端序列直算冒充实测）。
全 monkeypatch（env 指向 tmp_path），零网络零真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient

from backend.api.hotlist_jev_routes import RELAY_BAND_TABLE_ENV
from backend.main import app

client = TestClient(app)

_SAMPLE = {
    "ok": True,
    "generatedAt": "2026-10-18T10:58:00",
    "window": {"start": "2026-05-06", "end": "2026-10-16", "judged": 108, "evaluated": 107},
    "relayGeneration": ["v5"],
    "bars": {"okCodes": 2985, "codes": 2985, "localRoot": "D:/APP_SOFT/TDX"},
    "bands": [{"key": [40, 60], "name": "40-60", "n": 38, "promo": 21.2, "hiPromo": 37.9,
               "premA": 0.6, "premB": 0.7, "bigface": 13.7, "negA": 13}],
    "zones": [{"zone": "回避 40-60∧温≥56", "n": 11, "mean": -0.45}],
    "days": [{"d": "2026-05-06", "idx": 47.7, "temp": 55.9, "phase": "divergence",
              "money": "losing", "premA": 3.2, "bigface": 2.0, "cov": 145, "n_pool": 145}],
}


def _write(tmp_path: Path, name: str, payload) -> Path:
    path = tmp_path / name
    path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                    encoding="utf-8")
    return path


def test_relay_band_reads_artifact(tmp_path, monkeypatch):
    """产物存在 → 原样透传 + 附 artifactPath/artifactMtime（不加工不重算）。"""
    path = _write(tmp_path, "relay-band-table.json", _SAMPLE)
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(path))
    body = client.get("/api/hotlist-jev/relay-band").json()
    assert body["ok"] is True
    assert body["window"]["end"] == "2026-10-16"
    assert body["bands"][0]["name"] == "40-60"
    assert body["days"][0]["d"] == "2026-05-06"
    assert body["artifactPath"] == str(path)
    assert body["artifactMtime"] > 0


def test_relay_band_missing_is_fail_visible(tmp_path, monkeypatch):
    """产物缺失 → ok=False + reason + hint（前端标「未生成」，不静默空表）。"""
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(tmp_path / "nope.json"))
    body = client.get("/api/hotlist-jev/relay-band").json()
    assert body["ok"] is False and body["degraded"] is True
    assert body["reason"] == "band_table_missing"
    assert "jev_relay_band_diagnostic" in body["hint"]


def test_relay_band_unreadable_and_empty(tmp_path, monkeypatch):
    """损坏 JSON / 空 days 都按 fail-visible 返回结构化原因。"""
    bad = _write(tmp_path, "bad.json", "{not json")
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(bad))
    assert client.get("/api/hotlist-jev/relay-band").json()["reason"].startswith(
        "band_table_unreadable")

    empty = _write(tmp_path, "empty.json", {"ok": True, "days": []})
    monkeypatch.setenv(RELAY_BAND_TABLE_ENV, str(empty))
    assert client.get("/api/hotlist-jev/relay-band").json()["reason"] == "band_table_empty"


def test_relay_band_default_path_under_repo(tmp_path, monkeypatch):
    """默认路径 = quant-board/data/backups/relay-band-table.json（相对仓根解析）。"""
    monkeypatch.delenv(RELAY_BAND_TABLE_ENV, raising=False)
    body = client.get("/api/hotlist-jev/relay-band").json()
    expected = Path(__file__).resolve().parents[2] / "data" / "backups" / "relay-band-table.json"
    assert Path(body["artifactPath"]) == expected


def test_relay_band_rejects_non_list_days(tmp_path, monkeypatch):
    """days 非列表/空列表的损坏产物 → ok:false + reason（review P2-4），不得放行成 ok:true。"""
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.api import hotlist_jev_routes as routes

    bad = tmp_path / "relay-band-table.json"
    bad.write_text(json.dumps({"days": "x", "window": {}}), encoding="utf-8")
    monkeypatch.setattr(routes, "_relay_band_table_path", lambda: bad)
    r = TestClient(app).get("/api/hotlist-jev/relay-band")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False and body["reason"] == "band_table_empty"
    assert body.get("hint") and body.get("artifactPath")
