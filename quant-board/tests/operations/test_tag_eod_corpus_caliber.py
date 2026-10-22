# -*- coding: utf-8 -*-
"""存量 EOD 语料代际打标测试（2026-10-22 日级语料修复）。

存量文档不伪造 evidenceRaw，只加 corpusCaliberVersion + evidenceRawUnavailable；
新代文档（已带 evidenceRaw 或 corpusCaliberVersion）不得被覆盖。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.tag_eod_corpus_caliber import apply_tags, plan_tags


class FakeCollection:
    def __init__(self, rows):
        self.rows = [dict(row) for row in rows]

    def find(self, query=None, projection=None):
        query = query or {}

        def match(row):
            for key, expected in query.items():
                if row.get(key) != expected:
                    return False
            return True

        return iter([row for row in self.rows if match(row)])

    def update_one(self, query, update):
        for row in self.rows:
            if row.get("_id") == query.get("_id"):
                row.update(update.get("$set") or {})
                return type("Result", (), {"modified_count": 1})()
        return type("Result", (), {"modified_count": 0})()


class FakeDb:
    def __init__(self, rows):
        self.col = FakeCollection(rows)

    def __getitem__(self, name):
        assert name == "hotlist_jev_sentiment"
        return self.col


def _doc(_id, *, version=None, evidence=None, corpus=None):
    doc = {"_id": _id, "kind": "eod", "datasetId": "dragonboard_live",
           "tradingDate": "2026-09-30", "evidenceRaw": evidence}
    if version:
        doc["questionSetVersion"] = version
    if corpus:
        doc["corpusCaliberVersion"] = corpus
    return doc


def test_plan_tags_classifies_legacy_and_v25_without_touching_new_docs():
    db = FakeDb([
        _doc("legacy", version=None, evidence=None),
        _doc("v25", version="v2.5", evidence=None),
        _doc("new-with-evidence", version="v2.5", evidence={"frames": []}),
        _doc("new-tagged", version="v2.5", evidence=None, corpus="eod-2026-10-22"),
    ])
    plan = plan_tags(db)
    assert plan["total"] == 4 and plan["toTag"] == 2
    tags = {row["_id"]: row["set"]["corpusCaliberVersion"] for row in plan["updates"]}
    assert tags == {"legacy": "legacy_unversioned", "v25": "v2.5_pre_eod_fix"}
    assert all(row["set"]["evidenceRawUnavailable"] is True for row in plan["updates"])


def test_apply_tags_is_idempotent_and_additive():
    db = FakeDb([
        _doc("legacy", version=None, evidence=None),
        _doc("v25", version="v2.5", evidence=None),
    ])
    plan = plan_tags(db)
    assert apply_tags(db, plan["updates"]) == 2
    by_id = {row["_id"]: row for row in db.col.rows}
    assert by_id["legacy"]["corpusCaliberVersion"] == "legacy_unversioned"
    assert by_id["v25"]["corpusCaliberVersion"] == "v2.5_pre_eod_fix"
    assert by_id["legacy"]["evidenceRawUnavailable"] is True
    # 幂等：已打标文档不再入选
    assert plan_tags(db)["toTag"] == 0