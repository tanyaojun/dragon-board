# -*- coding: utf-8 -*-
"""涨停池证据回填测试：跳过健康/映射/伪 0 防线/fail-visible。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.backfill_limit_evidence import (
    apply_backfill,
    apply_frame_backfill,
    build_backfill_limit,
    plan_backfill,
    plan_frame_backfill,
)


class FakeCollection(dict):
    def __init__(self, rows=None):
        super().__init__()
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def matches(row):
            for key, expected in query.items():
                if key == "tradingDate" and isinstance(expected, dict):
                    val = row.get(key)
                    if "$gte" in expected and not (val and val >= expected["$gte"]):
                        return False
                    if "$lte" in expected and not (val and val <= expected["$lte"]):
                        return False
                    continue
                if row.get(key) != expected:
                    return False
            return True

        return iter([row for row in self.rows if matches(row)])

    def find_one(self, query=None, sort=None):
        for row in self.find(query):
            return row
        return None

    def update_one(self, query, update):
        for row in self.rows:
            if row.get("_id") == query.get("_id"):
                _apply_update(row, update)
                return


def _apply_update(row, update: dict):
    for path, value in (update.get("$set") or {}).items():
        parts = path.split(".")
        cur = row
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    for path, value in (update.get("$addToSet") or {}).items():
        parts = path.split(".")
        cur = row
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        items = cur.setdefault(parts[-1], [])
        if not isinstance(items, list):
            return
        if value not in items:
            items.append(value)


class FakeMongoDb(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


def v1_doc(date, zt):
    return {"_id": f"dragonboard_live:half_hour:{date}:15:00", "kind": "slot",
            "datasetId": "dragonboard_live", "snapshotType": "half_hour",
            "tradingDate": date, "slotTime": "15:00",
            "evidenceRaw": {"limit": {"ztCount": zt, "maxBoard": None,
                                      "boards": {}, "zhabanCount": None,
                                      "zhabanRate": None, "fengbanRate": None},
                            "totalAmount": {"amount": 1.5e12}}}


def frame(date):
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "_id": f"f:{date}"}


SUMMARY = {"continuousBoards": {"yiban": 20, "erban": 8, "sanban": 3, "sibanPlus": 1, "maxBoard": 4},
           "zhaban": {"count": 10, "rate": 22.2, "fengbanRate": 77.8, "ztCount": 45}}


def _db():
    db = FakeMongoDb()
    db["snapshot_frames"] = FakeCollection([frame("2026-09-01"), frame("2026-09-02")])
    db["hotlist_jev_sentiment_v2"] = FakeCollection(
        [v1_doc("2026-09-01", None), v1_doc("2026-09-02", 54)])
    return db


def test_build_backfill_limit_maps_production_shape():
    lim = build_backfill_limit(SUMMARY)
    assert lim["ztCount"] == 45 and lim["maxBoard"] == 4
    assert lim["boards"] == {"yiban": 20, "erban": 8, "sanban": 3, "sibanPlus": 1}
    assert lim["zhabanCount"] == 10 and lim["zhabanRate"] == 22.2 and lim["fengbanRate"] == 77.8
    assert lim["source"] == "ths_hist_backfill" and lim["backfilledAt"]


def test_build_backfill_limit_pseudo_zero_refuses():
    # 伪 0 防线：ztCount=0/缺失/空 summary 一律拒绝（fail-visible，不伪造）
    pseudo = {"continuousBoards": {"maxBoard": 0}, "zhaban": {"ztCount": 0}}
    assert build_backfill_limit(pseudo) is None
    assert build_backfill_limit({"continuousBoards": {}, "zhaban": {}}) is None
    assert build_backfill_limit(None) is None
    assert build_backfill_limit({}) is None


def test_plan_skips_healthy_and_backfills_gap():
    db = _db()

    def fetch_many(date8_list):
        return {d: (SUMMARY if d == "20260901" else None) for d in date8_list}

    actions, healthy, unresolved = plan_backfill(db, "2026-09-01", "2026-09-02", fetch_many)
    assert [a["date"] for a in actions] == ["2026-09-01"]  # 健康日 9/2 不碰
    assert healthy == ["2026-09-02"] and unresolved == []
    assert actions[0]["limit"]["ztCount"] == 45


def test_plan_unresolved_fail_visible():
    db = _db()
    actions, healthy, unresolved = plan_backfill(
        db, "2026-09-01", "2026-09-02", lambda date8_list: {d: None for d in date8_list})
    assert actions == [] and healthy == ["2026-09-02"]
    assert unresolved == ["2026-09-01:THS历史无有效涨停数据"]


def test_plan_upstream_exception_recorded():
    db = _db()

    def fetch_many(date8_list):
        return {d: RuntimeError("boom") for d in date8_list}

    _, _, unresolved = plan_backfill(db, "2026-09-01", "2026-09-01", fetch_many)
    assert unresolved == ["2026-09-01:THS历史拉取失败:boom"]


def test_apply_preserves_other_evidence_fields():
    db = _db()

    def fetch_many(date8_list):
        return {d: SUMMARY for d in date8_list}

    actions, _, _ = plan_backfill(db, "2026-09-01", "2026-09-01", fetch_many)
    apply_backfill(db, actions)
    doc = db["hotlist_jev_sentiment_v2"].find_one({"_id": actions[0]["docId"]})
    assert doc["evidenceRaw"]["limit"]["ztCount"] == 45
    assert doc["evidenceRaw"]["totalAmount"] == {"amount": 1.5e12}  # $set 不伤同文档其他字段


# ── 15:00 帧回填 ──────────────────────────────────────────────────────────────


def _frame(date, zt):
    return {"_id": f"f:{date}", "datasetId": "dragonboard_live", "type": "half_hour",
            "tradingDate": date, "slotTime": "15:00",
            "limitSummary": {} if zt is None else {"zhaban": {"ztCount": zt}},
            "qualityFlags": ["quote_provider_partial"]}


def _frame_db():
    db = FakeMongoDb()
    db["snapshot_frames"] = FakeCollection([
        _frame("2026-09-01", None), _frame("2026-09-02", 54), _frame("2026-09-03", 0)])
    return db


def test_frame_plan_backfills_gap_and_pseudo_zero():
    db = _frame_db()
    actions, healthy, unresolved = plan_frame_backfill(
        db, "2026-09-01", "2026-09-03", lambda ds: {d: SUMMARY for d in ds})
    assert sorted(a["date"] for a in actions) == ["2026-09-01", "2026-09-03"]  # 缺失+伪 0 都回填
    assert healthy == ["2026-09-02"] and unresolved == []
    s = actions[0]["summary"]
    assert s["source"] == "ths_hist_backfill" and s["backfilledAt"]
    assert s["zhaban"]["ztCount"] == 45


def test_frame_apply_sets_summary_and_flag():
    db = _frame_db()
    actions, _, _ = plan_frame_backfill(
        db, "2026-09-01", "2026-09-03", lambda ds: {d: SUMMARY for d in ds})
    apply_frame_backfill(db, actions)
    doc = db["snapshot_frames"].find_one({"_id": "f:2026-09-01"})
    assert doc["limitSummary"]["zhaban"]["ztCount"] == 45
    assert doc["limitSummary"]["source"] == "ths_hist_backfill"
    assert doc["qualityFlags"] == ["quote_provider_partial", "limit_summary_backfilled"]
    # 幂等：重复 apply 不产生重复标记
    apply_frame_backfill(db, actions)
    doc2 = db["snapshot_frames"].find_one({"_id": "f:2026-09-01"})
    assert doc2["qualityFlags"] == ["quote_provider_partial", "limit_summary_backfilled"]


# ── 富集模式（drawdown/sealQuality 块回填）────────────────────────────────────

from backend.operations.backfill_limit_evidence import (  # noqa: E402
    apply_enrich,
    build_enrich_blocks,
    plan_enrich,
)

FULL_SUMMARY = {**SUMMARY,
                "drawdown": {"count": 3, "avgDrawdownPct": 8.5, "deepestDrawdownPct": 12.6},
                "sealQuality": {"byzCount": 25, "hardCount": 10, "rottenCount": 8,
                                "rottenShare": 0.186, "avgSucRate": 0.62}}


def test_build_enrich_blocks_shape_and_provenance():
    blocks = build_enrich_blocks(FULL_SUMMARY)
    assert blocks["drawdown"]["count"] == 3 and blocks["drawdown"]["source"] == "ths_hist_backfill"
    assert blocks["drawdown"]["backfilledAt"]
    assert blocks["sealQuality"]["rottenShare"] == 0.186 and blocks["sealQuality"]["source"] == "ths_hist_backfill"
    assert build_enrich_blocks(None) is None
    assert build_enrich_blocks(SUMMARY) is None  # 无新块的旧式 summary 拒绝


def _enrich_db():
    db = FakeMongoDb()
    db["snapshot_frames"] = FakeCollection([
        _frame("2026-09-01", None),           # 已被旧回填写过的帧（无新块）
        _frame("2026-09-02", 54),             # 健康帧（同样缺新块）
        _frame("2026-09-03", 40)])
    db["snapshot_frames"].rows[2]["limitSummary"]["drawdown"] = {"count": 1}  # 已富集→跳过
    db["hotlist_jev_sentiment_v2"] = FakeCollection([v1_doc("2026-09-01", 45), v1_doc("2026-09-02", 54)])
    return db


def test_plan_enrich_skips_existing_blocks_and_targets_both_collections():
    db = _enrich_db()
    frame_actions, doc_actions, skipped, unresolved = plan_enrich(
        db, "2026-09-01", "2026-09-03", lambda ds: {d: FULL_SUMMARY for d in ds})
    assert sorted(a["date"] for a in frame_actions) == ["2026-09-01", "2026-09-02"]  # 9/3 已有块跳过
    assert sorted(a["date"] for a in doc_actions) == ["2026-09-01", "2026-09-02"]
    assert skipped == 1 and unresolved == []


def test_apply_enrich_preserves_existing_limit_summary_content():
    db = _enrich_db()
    frame_actions, doc_actions, _, _ = plan_enrich(
        db, "2026-09-01", "2026-09-03", lambda ds: {d: FULL_SUMMARY for d in ds})
    apply_enrich(db, frame_actions, doc_actions)
    f = db["snapshot_frames"].find_one({"_id": "f:2026-09-02"})
    assert f["limitSummary"]["drawdown"]["count"] == 3
    assert f["limitSummary"]["zhaban"]["ztCount"] == 54  # 既有块保留
    assert f["limitSummary"]["sealQuality"]["source"] == "ths_hist_backfill"
    d = db["hotlist_jev_sentiment_v2"].find_one({"_id": "dragonboard_live:half_hour:2026-09-01:15:00"})
    assert d["evidenceRaw"]["limit"]["drawdown"]["avgDrawdownPct"] == 8.5
    assert d["evidenceRaw"]["totalAmount"]["amount"] == 1.5e12  # 其他字段不伤
