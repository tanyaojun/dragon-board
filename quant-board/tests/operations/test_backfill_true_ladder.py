# -*- coding: utf-8 -*-
"""真连板锚参考集合（market_true_ladder）回填测试：跳过帧已供给/幂等/fail-visible。

2026-10-22 语料口径修复配套（jev-slot-corpus-caliber-fix-preregistration.md §2.3）：
锚「最高连板」改真连板口径，历史日无帧连板层（10-10 前）由本工具按日查 THS 连板层
回填参考集合——与帧池同源同口径（同源采样铁律）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations.backfill_true_ladder import (  # noqa: E402
    LADDER_POOL_KEYS,
    apply_backfill,
    plan_backfill,
)


def test_ladder_pool_keys_frozen():
    # 连板层五池键位单一事实源（与 providers._LADDER_POOL_KEYS 同集，防拼写漂移）
    assert LADDER_POOL_KEYS == ("one", "two", "three", "four", "high")


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

    def update_one(self, query, update, upsert=False):
        if "$set" not in update:
            return
        for row in self.rows:
            if row.get("_id") == query.get("_id"):
                row.update(update["$set"])
                return
        if upsert:
            self.rows.append({"_id": query["_id"], **update["$set"]})


class FakeMongoDb(dict):
    def __init__(self, collections=None):
        super().__init__()
        for name, rows in (collections or {}).items():
            self[name] = FakeCollection(rows)

    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


def frame_doc(date, with_ladder, zt=43):
    ls = {"continuousBoards": {"yiban": 30, "erban": 10, "sanban": 2, "sibanPlus": 1, "maxBoard": 4},
          "zhaban": {"count": 8, "rate": 12.0, "fengbanRate": 88.0, "ztCount": zt}}
    if with_ladder:
        ls["thsPools"] = {"pools": {
            "one": {"ok": True, "items": [{}] * 30},
            "two": {"ok": True, "items": [{}] * 10},
            "three": {"ok": True, "items": [{}] * 2},
            "four": {"ok": True, "items": [{}]},
            "high": {"ok": True, "items": []}}}
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "_id": f"f:{date}", "limitSummary": ls}


def fake_fetch_map(results):
    def fetch(need):
        return {date8: results.get(date8) for date8 in need}
    return fetch


def test_plan_skips_frame_served_and_existing_reference():
    # 帧已带连板层（锚直读帧）与参考集合已存（幂等）都跳过，只计划真正缺源的日子
    db = FakeMongoDb({
        "snapshot_frames": [frame_doc("2026-09-20", with_ladder=True),
                            frame_doc("2026-09-22", with_ladder=False),
                            frame_doc("2026-09-23", with_ladder=False)],
        "market_true_ladder": [{"_id": "2026-09-23", "maxTrueBoard": 5,
                                "boards": {"one": 20, "two": 5, "three": 1, "four": 1, "high": 0}}],
    })
    actions, frame_served, already, unresolved = plan_backfill(
        db, "2026-09-20", "2026-09-23", fetch=fake_fetch_map({"20260922": None}))
    assert frame_served == 1 and already == 1
    assert unresolved == ["2026-09-22:THS历史无有效连板层"]  # fetch 返 None → 如实登记不伪造
    assert actions == []


def test_plan_and_apply_backfill_upserts_reference():
    db = FakeMongoDb({"snapshot_frames": [frame_doc("2026-09-22", with_ladder=False, zt=50)]})
    lad = {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}
    actions, frame_served, already, unresolved = plan_backfill(
        db, "2026-09-22", "2026-09-22", fetch=fake_fetch_map({"20260922": lad}))
    assert (frame_served, already, unresolved) == (0, 0, [])
    assert len(actions) == 1 and actions[0]["date"] == "2026-09-22"
    assert actions[0]["ladder"]["maxBoard"] == 4
    written = apply_backfill(db, actions)
    assert written == 1
    ref = db["market_true_ladder"].rows[0]
    assert ref["_id"] == "2026-09-22" and ref["maxTrueBoard"] == 4
    assert ref["boards"]["four"] == 3 and ref["source"] == "ths_ladder_backfill"
    # 幂等：重跑计划 → 已存参考跳过
    _, _, already2, _ = plan_backfill(db, "2026-09-22", "2026-09-22", fetch=fake_fetch_map({}))
    assert already2 == 1


def test_plan_all_zero_pools_with_zt_unresolved():
    # 连板层全零但当日 zt>0（池未就绪/口径异常）→ 派生 None → 不可算不落库（宁缺毋猜）
    db = FakeMongoDb({"snapshot_frames": [frame_doc("2026-09-22", with_ladder=False, zt=50)]})
    actions, _, _, unresolved = plan_backfill(
        db, "2026-09-22", "2026-09-22", fetch=fake_fetch_map({"20260922": None}))
    assert actions == [] and unresolved == ["2026-09-22:THS历史无有效连板层"]
