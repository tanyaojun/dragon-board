# -*- coding: utf-8 -*-
"""日级 EOD 重放脚本：备份导出只读、dry-run 代际可见（review P3-6）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.jev_eod_replay import (
    _close_frame_present,
    _existing_eod_brief,
    export_eod_docs,
)


class _Cursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def find(self, query: dict[str, Any]) -> "_Cursor":
        def matches(row: dict[str, Any]) -> bool:
            for key, expected in query.items():
                value = row.get(key)
                if isinstance(expected, dict) and "$in" in expected:
                    if value not in expected["$in"]:
                        return False
                elif value != expected:
                    return False
            return True

        return _Cursor([row for row in self.rows if matches(row)])

    def find_one(self, query: dict[str, Any], sort=None) -> dict[str, Any] | None:
        rows = list(self.find(query).rows)
        return rows[0] if rows else None

    def __iter__(self):
        return iter(self.rows)


class FakeDb(dict):
    def __init__(self, collections: dict[str, list[dict[str, Any]]] | None = None) -> None:
        super().__init__()
        for name, rows in (collections or {}).items():
            self[name] = _Cursor(rows)

    def __missing__(self, name: str) -> _Cursor:
        self[name] = _Cursor([])
        return self[name]


def test_export_eod_docs_only_selected_dates_and_keeps_db_untouched(tmp_path):
    rows = [
        {"_id": "d:half_hour:2026-10-20:EOD", "kind": "eod", "datasetId": "d",
         "tradingDate": "2026-10-20", "status": "ok"},
        {"_id": "d:half_hour:2026-10-21:EOD", "kind": "eod", "datasetId": "d",
         "tradingDate": "2026-10-21", "status": "ok"},
        {"_id": "d:half_hour:2026-10-22:EOD", "kind": "eod", "datasetId": "d",
         "tradingDate": "2026-10-22", "status": "ok"},
        {"_id": "d:half_hour:2026-10-20:15:00", "kind": "slot", "datasetId": "d",
         "tradingDate": "2026-10-20", "status": "ok"},
    ]
    db = FakeDb({"hotlist_jev_sentiment": rows})

    path = export_eod_docs(db, ["2026-10-20", "2026-10-21"], dataset_id="d", out_dir=tmp_path)

    exported = json.loads(path.read_text(encoding="utf-8"))
    assert [doc["tradingDate"] for doc in exported] == ["2026-10-20", "2026-10-21"]
    assert all(doc["kind"] == "eod" for doc in exported)
    assert len(db["hotlist_jev_sentiment"].rows) == 4  # 导出只读，不改业务集合


def test_existing_eod_brief_discloses_generation_and_coverage():
    db = FakeDb({"hotlist_jev_sentiment": [{
        "_id": "d:half_hour:2026-10-21:EOD", "status": "ok",
        "questionSetVersion": "v2.6", "corpusCaliberVersion": "eod-2026-10-22",
        "frameCoverage": {"hasCloseFrame": True},
        "scores": {"day_temperature": 50.3}}]})

    brief = _existing_eod_brief(db, "2026-10-21", "d")

    assert brief == {"status": "ok", "questionSetVersion": "v2.6",
                     "corpusCaliberVersion": "eod-2026-10-22",
                     "hasCloseFrame": True, "dayTemperature": 50.3}


def test_close_frame_present_checks_half_hour_1500():
    db = FakeDb({"snapshot_frames": [{
        "datasetId": "d", "type": "half_hour", "tradingDate": "2026-10-21",
        "slotTime": "15:00"}]})
    assert _close_frame_present(db, "2026-10-21", "d") is True
    assert _close_frame_present(db, "2026-10-20", "d") is False