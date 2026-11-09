# -*- coding: utf-8 -*-
"""backfill_zt_reason_corpus 单测（2026-11-09 涨停原因语料 HTTP 历史档案链回填）。

pytest 纪律：fetcher 全注入 mock，零真实 HTTP（红线 7，与
kpl_zt_reason_history._pytest_guard 双保险）；db 用假库，零真实 Mongo。
"""
from __future__ import annotations

import json
from typing import Any, Dict

import pytest

from backend.operations.backfill_zt_reason_corpus import (
    SOURCE_RT,
    build_reason_snapshot,
    pick_pool_members,
    run_backfill,
)


class _FakeCollection:
    def __init__(self) -> None:
        self.rows: Dict[str, dict] = {}

    def update_one(self, q: dict, update: dict, upsert: bool = False) -> None:
        assert "_id" not in update["$set"], "$set 不得改写 _id"
        row = self.rows.setdefault(q["_id"], {"_id": q["_id"]}) if upsert else self.rows.get(q["_id"])
        assert upsert or row is not None, "非 upsert 更新不应凭空造档"
        row.update(update["$set"])

    def find_one(self, q: dict) -> dict | None:
        row = self.rows.get(q["_id"]) if isinstance(q.get("_id"), str) else None
        return dict(row) if row else None


class _FakeDb:
    def __init__(self) -> None:
        self._coll = _FakeCollection()

    def __getitem__(self, name: str):
        assert name == "kpl_daban_pool"
        return self._coll


def _parse_ok(sid: str, date: str = "2026-11-09") -> dict:
    return {"ok": True, "stock_id": sid, "matched_date": date,
            "items": [{"date": date, "reason": f"{sid} 光伏+储能涨停原因全文",
                       "gns": "概念解析全文", "boom_zs": "媒体催化原文",
                       "sclt": "日内梯队", "zs_codes": ["801464", "802097"]}],
            "dropped": 0}


def _fetcher_ok(sid: str) -> dict:
    return {"StockID": sid, "List": [{"Date": "2026-11-09",
                                      "Reason": f"{sid} 光伏+储能涨停原因全文",
                                      "GNSM": "概念解析全文", "Boom_ZS": "媒体催化原文",
                                      "SCLT": "日内梯队", "ZSCode": ["801464", "802097"]}]}


def _seed_pool(db: _FakeDb, date: str, sids: list[str]) -> None:
    db._coll.rows[date] = {"_id": date, "date": date,
                           "items": [{"stock_id": s} for s in sids]}


def test_pick_pool_members_fail_visible():
    db = _FakeDb()
    assert pick_pool_members(db, "2026-11-09")["reason"] == "no_pool_members"
    _seed_pool(db, "2026-11-09", ["000001", "000002"])
    picked = pick_pool_members(db, "2026-11-09")
    assert picked["ok"] and picked["members"] == ["000001", "000002"]


def test_build_reason_snapshot_maps_same_source_fields():
    results = {"000001": _parse_ok("000001"),
               "000002": {"ok": True, "stock_id": "000002", "matched_date": "2026-11-05",
                          "items": [], "dropped": 0}}   # 无当日条目 → 不进载荷
    snap = build_reason_snapshot("2026-11-09", results, fetch_ts=1000.0)
    assert snap["date"] == "2026-11-09" and list(snap["reasons"]) == ["000001"]
    it = snap["reasons"]["000001"]
    assert it["zt"] == "000001 光伏+储能涨停原因全文"          # Reason 全文 → zt（同源映射）
    assert it["source"] == SOURCE_RT and it["matched_date"] == "2026-11-09"
    assert it["zs_codes"] == ["801464", "802097"] and it["ts"] == 1000.0


def test_run_backfill_dry_run_no_write():
    db = _FakeDb()
    _seed_pool(db, "2026-11-09", ["000001", "000002"])
    calls: list[str] = []

    def fetcher(sid: str) -> dict:
        calls.append(sid)
        return _fetcher_ok(sid)

    report = run_backfill(db, "2026-11-09", fetcher=fetcher, apply=False)
    assert calls == ["000001", "000002"]
    assert report["matched_n"] == 2 and report["fetched_n"] == 2
    assert report["apply"] is False and "archive" not in report
    assert not any("reason_items" in r for r in db._coll.rows.values())   # dry-run 零写库


def test_run_backfill_apply_archives_with_http_source():
    db = _FakeDb()
    _seed_pool(db, "2026-11-09", ["000001"])
    report = run_backfill(db, "2026-11-09", fetcher=lambda sid: _fetcher_ok(sid), apply=True)
    arch = report["archive"]
    assert arch["ok"] is True and arch["merged_n"] == 1
    row = db._coll.rows["2026-11-09"]
    assert row["reason_source"] == SOURCE_RT and row["reason_count"] == 1
    it = row["reason_items"][0]
    assert it["stock_id"] == "000001" and it["source"] == SOURCE_RT
    assert it["zt"] == "000001 光伏+储能涨停原因全文" and it["gns"] == "概念解析全文"


def test_run_backfill_skips_and_failures_isolated():
    db = _FakeDb()
    _seed_pool(db, "2026-11-09", ["000001", "000002", "000003"])

    def fetcher(sid: str) -> dict:
        if sid == "000001":
            return _fetcher_ok(sid)
        if sid == "000002":
            # 上游仅回最近涨停日（上周五），无当日条目
            return {"StockID": sid, "List": [{"Date": "2026-11-06", "Reason": "旧记录"}]}
        raise OSError("conn reset")

    report = run_backfill(db, "2026-11-09", fetcher=fetcher, apply=False)
    assert report["matched_n"] == 1
    assert "000002" in report["skipped"] and "2026-11-06" in report["skipped"]["000002"]
    assert "000003" in report["failures"]


def test_run_backfill_limit_controls_fanout():
    db = _FakeDb()
    _seed_pool(db, "2026-11-09", ["000001", "000002", "000003", "000004"])
    calls: list[str] = []
    report = run_backfill(db, "2026-11-09", fetcher=lambda s: (calls.append(s), _fetcher_ok(s))[1],
                          limit=2, apply=False)
    assert calls == ["000001", "000002"]
    assert report["members_n"] == 2


def test_main_raw_export_written(tmp_path, monkeypatch):
    """--raw-out：上游原文 JSON 落盘（GNSM/Boom_ZS/SCLT 原料全保留）。"""
    import backend.operations.backfill_zt_reason_corpus as m

    db = _FakeDb()
    _seed_pool(db, "2026-11-09", ["000001"])
    monkeypatch.setattr(m, "get_runtime_mongodb_database", lambda: db, raising=False)
    # main 内部延迟 import repository_factory，直接打桩模块属性
    monkeypatch.setattr(
        "backend.data.repositories.repository_factory.get_runtime_mongodb_database",
        lambda: db)
    monkeypatch.setattr(m, "fetch_stock_zt_reason_realtime", lambda sid: _fetcher_ok(sid))
    out = tmp_path / "raw"
    rc = m.main(["--date", "2026-11-09", "--raw-out", str(out)])
    assert rc == 0
    raw_file = out / "raw_responses.json"
    data = json.loads(raw_file.read_text(encoding="utf-8"))
    assert data["000001"]["List"][0]["Reason"] == "000001 光伏+储能涨停原因全文"
