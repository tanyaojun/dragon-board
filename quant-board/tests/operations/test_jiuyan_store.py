# -*- coding: utf-8 -*-
"""韭研存储层测试（内存假 db，无 Mongo）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations.jiuyan_store import (
    action_doc_id,
    get_action_doc,
    get_cached_token,
    list_action_dates,
    save_action_doc,
    save_token,
)


class FakeCollection:
    def __init__(self):
        self.docs = {}

    def replace_one(self, flt, doc, upsert=False):
        key = flt["_id"]
        if key in self.docs or upsert:
            self.docs[key] = doc

    def find_one(self, flt):
        return self.docs.get(flt["_id"])

    def find(self, flt=None, projection=None):
        return list(self.docs.values())


class FakeDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        return self.collections.setdefault(name, FakeCollection())


def test_action_doc_id_kind_guard():
    assert action_doc_id("2026-09-30", "final") == "2026-09-30:final"
    assert action_doc_id("2026-09-30", "midday") == "2026-09-30:midday"
    with pytest.raises(ValueError):
        action_doc_id("2026-09-30", "weekly")


def test_save_and_get_idempotent_upsert():
    db = FakeDB()
    parsed = {"fields": [{"name": "医药医疗", "count": 1, "stocks": []}], "totalStocks": 1, "degradedSources": []}
    save_action_doc(db, date="2026-09-30", kind="final", parsed=parsed, counts={"all": 64}, token_source="cache")
    save_action_doc(db, date="2026-09-30", kind="final", parsed=parsed, counts={"all": 64})  # 重采覆盖
    doc = get_action_doc(db, "2026-09-30", "final")
    assert doc["tradingDate"] == "2026-09-30" and doc["updateKind"] == "final"
    assert doc["counts"] == {"all": 64} and doc["totalStocks"] == 1
    assert doc["quality"]["tokenSource"] == "cache"  # 第二次未传 → 默认 cache
    assert get_action_doc(db, "2026-09-30", "midday") is None  # 不同 kind 互不影响


def test_list_action_dates_sorted():
    db = FakeDB()
    for date, kind in (("2026-09-30", "final"), ("2026-09-01", "final"), ("2026-09-30", "midday")):
        save_action_doc(db, date=date, kind=kind, parsed={"fields": [], "totalStocks": 0, "degradedSources": []})
    dates = list_action_dates(db)
    assert [d["date"] for d in dates] == ["2026-09-01", "2026-09-30"]
    assert dates[1]["kinds"] == ["final", "midday"]


def test_token_meta_roundtrip():
    db = FakeDB()
    assert get_cached_token(db) is None
    save_token(db, token="T" * 80, timestamp="2026-10-02T00:51:52Z", source="manual")
    tok = get_cached_token(db)
    assert tok["token"] == "T" * 80 and tok["source"] == "manual" and tok["mintedAt"]
    save_token(db, token="NEW", timestamp="TS2", source="minted")
    assert get_cached_token(db)["token"] == "NEW"
