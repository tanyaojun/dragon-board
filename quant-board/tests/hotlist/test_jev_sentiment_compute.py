# -*- coding: utf-8 -*-
"""情绪 v2 生产计算服务测试：锚日历化（窗口/伪 0/缺数日）+ gate + EOD/槽级计算落库。

2026-10-02 V1 退役：锚读数源=hotlist_jev_sentiment_v2 槽文档（v2 自供锚）。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev import jev_sentiment_compute as v2_module
from backend.services.jev.jev_sentiment_compute import (
    build_history_stats_calendar,
    compute_and_upsert_for_day,
    compute_and_upsert_for_slot,
    sentiment_gate_enabled,
)


class FakeCollection:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def matches(row):
            for key, expected in query.items():
                if key == "tradingDate" and isinstance(expected, dict):
                    val = row.get(key)
                    if "$lt" in expected and not (val and val < expected["$lt"]):
                        return False
                    if "$gt" in expected and not (val and val > expected["$gt"]):
                        return False
                    continue
                if key == "evidenceRaw.limit.ztCount" and isinstance(expected, dict):
                    zt = ((row.get("evidenceRaw") or {}).get("limit") or {}).get("ztCount")
                    if "$gt" in expected and not (isinstance(zt, (int, float)) and zt > expected["$gt"]):
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

    def replace_one(self, query, doc, upsert=False):
        self.rows = [row for row in self.rows if row.get("_id") != query.get("_id")]
        self.rows.append(doc)


class FakeMongoDb(dict):
    def __init__(self, collections=None):
        super().__init__()
        for name, rows in (collections or {}).items():
            self[name] = FakeCollection(rows)

    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


def frame_rows(dates):
    return [{"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
             "slotTime": "15:00", "_id": f"f:{d}", "snapshotId": f"half_hour:{d}:15:00",
             "timestamp": f"{d}T15:00:00+08:00",
             "indices": {"sh": {"change": -5.0}},
             "limitSummary": {"continuousBoards": {"yiban": 30, "erban": 10, "sanban": 2,
                                                    "sibanPlus": 1, "maxBoard": 4},
                              "zhaban": {"count": 8, "rate": 12.0, "fengbanRate": 88.0, "ztCount": 43}}}
            for d in dates]


def anchor_slot_doc(date, zt, zhaban=12.0):
    return {"_id": f"dragonboard_live:half_hour:{date}:15:00", "kind": "slot",
            "datasetId": "dragonboard_live", "snapshotType": "half_hour",
            "tradingDate": date, "slotTime": "15:00", "status": "ok",
            "evidenceRaw": {"limit": {"ztCount": zt, "maxBoard": 5, "zhabanRate": zhaban},
                            "totalAmount": {"amount": 1.5e12}}}


def test_calendar_window_one_entry_per_trading_day():
    # 窗口按交易日历：6 个历日严格 < D，其中 1 日文档缺失 → 仍占窗口位（None 指标）
    days = ["2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days + ["2026-09-30"]),
        "hotlist_jev_sentiment": [anchor_slot_doc(d, 50) for d in days if d != "2026-09-22"],
    })
    stats = build_history_stats_calendar(db, "dragonboard_live", "2026-09-30")
    assert [s["date"] for s in stats] == days  # 日历窗口：缺失日照占位
    missing = [s for s in stats if s["date"] == "2026-09-22"][0]
    assert missing["ztCount"] is None  # 缺失日如实 None，不伪造
    assert [s["ztCount"] for s in stats if s["ztCount"]] == [50] * (len(days) - 1)


def test_calendar_window_fake_zero_excluded():
    # v2.3 教训：ztCount=0 是伪 0（伪装缺失），不得进锚样本
    days = ["2026-09-20", "2026-09-21", "2026-09-22"]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days + ["2026-09-30"]),
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-20", 0), anchor_slot_doc("2026-09-21", 48)],
    })
    stats = build_history_stats_calendar(db, "dragonboard_live", "2026-09-30")
    by_date = {s["date"]: s["ztCount"] for s in stats}
    assert by_date["2026-09-20"] is None  # 伪 0 → None
    assert by_date["2026-09-21"] == 48


def test_calendar_window_corrupted_limit_block_linked_fields():
    # 损坏 limit 块整块不可信：ztCount 伪 0 时同源 maxBoard/zhabanRate 联动置 None，
    # 不得以真值身份进分位（maxBoard=0 亦按伪 0 处理）
    days = ["2026-09-20", "2026-09-21", "2026-09-22"]
    corrupt = anchor_slot_doc("2026-09-20", 0)
    corrupt["evidenceRaw"]["limit"] = {"ztCount": 0, "maxBoard": 0, "zhabanRate": 0.0}
    healthy = anchor_slot_doc("2026-09-21", 48, zhaban=0.0)  # 健康文档炸板率 0 是合法值
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days + ["2026-09-30"]),
        "hotlist_jev_sentiment": [corrupt, healthy],
    })
    stats = {s["date"]: s for s in build_history_stats_calendar(db, "dragonboard_live", "2026-09-30")}
    c = stats["2026-09-20"]
    assert c["ztCount"] is None and c["maxBoard"] is None and c["zhabanRate"] is None
    h = stats["2026-09-21"]
    assert h["ztCount"] == 48 and h["maxBoard"] == 5 and h["zhabanRate"] == 0.0


def test_calendar_window_limited_to_20():
    days = [f"2026-08-{d:02d}" for d in range(1, 32) if d <= 21]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days + ["2026-08-25", "2026-09-30"]),
        "hotlist_jev_sentiment": [anchor_slot_doc(d, 40 + i) for i, d in enumerate(days)],
    })
    stats = build_history_stats_calendar(db, "dragonboard_live", "2026-09-30", window=10)
    assert len(stats) == 10 and stats[-1]["date"] == "2026-08-25"


def test_sentiment_gate_enabled_default_on_and_reversible(monkeypatch):
    monkeypatch.delenv("JEV_SENTIMENT_V2_ENABLED", raising=False)
    assert sentiment_gate_enabled() is True  # 默认开
    monkeypatch.setenv("JEV_SENTIMENT_V2_ENABLED", "0")
    assert sentiment_gate_enabled() is False  # 可回退


def test_compute_day_happy_path(monkeypatch):
    days = ["2026-09-28", "2026-09-29", "2026-09-30"]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days),
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live", "snapshotId": f"half_hour:{d}:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6} for d in days],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-28", 50)],
    })
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))

    def fake_call(account, token, state, questions):
        answers = {
            "day_stage": {"type": "choice", "choice": "ferment",
                          "probabilities": {"ferment": 0.7}},
            "day_crowding": {"type": "choice", "choice": "no_crowding",
                             "probabilities": {"no_crowding": 0.6}},
            "day_temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "jev-1.13.0", "answers": answers,
                                      "usage": {"input_tokens": 900, "output_tokens": 90}}}}, 100

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live", trading_date="2026-09-30")
    assert result["written"] is True and result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    assert doc["tradingDate"] == "2026-09-30" and doc["origin"] == "collector_v2"
    assert ((doc["answers"] or {})["day_stage"]["choice"]) == "ferment"
    assert doc["narrativeRaw"].startswith("2026-09-30 交易日全天热榜情绪证据轨迹")


def test_compute_day_token_missing_degraded_fail_visible(monkeypatch):
    days = ["2026-09-29", "2026-09-30"]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days),
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live", "snapshotId": f"half_hour:{d}:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6} for d in days],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "", "acc"))
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live", trading_date="2026-09-30")
    assert result["status"] == "degraded" and result["errorCode"] == "missing_token"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    assert doc["status"] == "degraded" and doc["narrativeRaw"]  # 叙事留存，不吞证据


def test_compute_day_disabled_skips(monkeypatch):
    monkeypatch.setenv("JEV_SENTIMENT_V2_ENABLED", "0")
    db = FakeMongoDb({"snapshot_frames": frame_rows(["2026-09-29", "2026-09-30"])})
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                           trading_date="2026-09-30", force=False)
    assert result.get("skipped") is True


def test_compute_day_gate_off_default_force_skips(monkeypatch):
    # 安全默认方向：不传 force（默认 False）+ gate 关 → 必须跳过，防止新调用方漏传静默绕过
    monkeypatch.setenv("JEV_SENTIMENT_V2_ENABLED", "0")
    db = FakeMongoDb({"snapshot_frames": frame_rows(["2026-09-29", "2026-09-30"])})
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                           trading_date="2026-09-30")
    assert result == {"written": False, "skipped": True, "reason": "v2_disabled"}
    assert db["hotlist_jev_sentiment"].rows == []  # 不落库

# ── 槽级计算（2026-10-02 V1 退役后生产槽位唯一评判）──


def slot_frame(date, slot):
    row = frame_rows([date])[0]
    row["slotTime"] = slot
    row["snapshotId"] = f"half_hour:{date}:{slot}"
    row["_id"] = f"f:{date}:{slot}"
    return row


def test_compute_slot_happy_path(monkeypatch):
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [slot_frame("2026-09-30", "10:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:10:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))

    def fake_call(account, token, state, questions):
        assert questions == v2_module.JEV_SLOT_QUESTIONS
        assert "近20日参照" in state, "v2 槽位叙事必须带锚段"
        answers = {
            "frame_stage": {"type": "choice", "choice": "ferment",
                            "probabilities": {"ferment": 0.6}},
            "sequence_stage": {"type": "choice", "choice": "ferment",
                               "probabilities": {"ferment": 0.55}},
            "temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
            "crowding": {"type": "choice", "choice": "no_crowding",
                         "probabilities": {"no_crowding": 0.5}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "jev-1.13.0", "answers": answers,
                                      "usage": {"input_tokens": 800, "output_tokens": 80}}}}, 100

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                            trading_date="2026-09-30", slot_time="10:00")
    assert result["written"] is True and result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows
               if r.get("kind") == "slot" and r.get("slotTime") == "10:00")
    assert doc["origin"] == "collector_v2" and doc["tradingDate"] == "2026-09-30"
    assert doc["evidenceRaw"] and doc["narrativeRaw"] and doc["historyAnchorRange"]
    assert ((doc["answers"] or {})["crowding"]["choice"]) == "no_crowding"


def test_compute_slot_disabled_skips(monkeypatch):
    monkeypatch.setenv("JEV_SENTIMENT_V2_ENABLED", "0")
    db = FakeMongoDb({"snapshot_frames": [slot_frame("2026-09-30", "10:00")]})
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                            trading_date="2026-09-30", slot_time="10:00")
    assert result == {"written": False, "skipped": True, "reason": "v2_disabled"}
    assert db["hotlist_jev_sentiment"].rows == []  # 不落库


def test_compute_slot_missing_frame_no_data_fail_visible(monkeypatch):
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({"snapshot_frames": frame_rows(["2026-09-29"])})
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                            trading_date="2026-09-30", slot_time="10:00")
    assert result["status"] == "no_data"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["status"] == "no_data" and "missing" in (doc.get("errorDetail") or "")
