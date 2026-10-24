# -*- coding: utf-8 -*-
"""情绪 v2 生产计算服务测试：锚日历化（窗口/伪 0/缺数日）+ EOD/槽级计算落库。

2026-10-02 V1 退役：锚读数源=hotlist_jev_sentiment 槽文档（自供锚）。"""
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
    # 2026-10-22 口径修复后现代 15:00 帧形态：连板层五池（10-10 起 EOD 帧入采，真连板口径）
    return [{"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
             "slotTime": "15:00", "_id": f"f:{d}", "snapshotId": f"half_hour:{d}:15:00",
             "timestamp": f"{d}T15:00:00+08:00",
             "indices": {"sh": {"change": -5.0}},
             "limitSummary": {"continuousBoards": {"yiban": 30, "erban": 10, "sanban": 2,
                                                    "sibanPlus": 1, "maxBoard": 4},
                              "zhaban": {"count": 8, "rate": 12.0, "fengbanRate": 88.0, "ztCount": 43},
                              "thsPools": {"pools": {
                                  "one": {"ok": True, "items": [{}] * 30},
                                  "two": {"ok": True, "items": [{}] * 10},
                                  "three": {"ok": True, "items": [{}] * 2},
                                  "four": {"ok": True, "items": [{}]},
                                  "high": {"ok": True, "items": []}}}}}
            for d in dates]


def anchor_slot_doc(date, zt, zhaban=12.0):
    # 修复前存量文档形态：evidenceRaw.limit 只有区间 maxBoard（无 maxTrueBoard——锚取数链回退帧连板层）
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
    # 损坏 limit 块整块不可信：ztCount 伪 0 时同源 zhabanRate 联动置 None；
    # 2026-10-22 起最高连板锚改真连板口径（maxTrueBoard），取数链独立于文档 limit 块
    # （15:00 帧连板层派生）——文档损坏不再连带抹掉真连板样本
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
    assert c["ztCount"] is None and c["zhabanRate"] is None
    assert c["maxTrueBoard"] == 4  # 帧连板层独立供给，不受文档损坏连带
    h = stats["2026-09-21"]
    assert h["ztCount"] == 48 and h["maxTrueBoard"] == 4 and h["zhabanRate"] == 0.0


def test_calendar_window_limited_to_20():
    days = [f"2026-08-{d:02d}" for d in range(1, 32) if d <= 21]
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days + ["2026-08-25", "2026-09-30"]),
        "hotlist_jev_sentiment": [anchor_slot_doc(d, 40 + i) for i, d in enumerate(days)],
    })
    stats = build_history_stats_calendar(db, "dragonboard_live", "2026-09-30", window=10)
    assert len(stats) == 10 and stats[-1]["date"] == "2026-08-25"


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
            "day_pattern": {"type": "choice", "choice": "rally_fade",
                            "probabilities": {"rally_fade": 0.5}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "jev-1.13.0", "answers": answers,
                                      "usage": {"input_tokens": 900, "output_tokens": 90}}}}, 100

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live", trading_date="2026-09-30")
    assert result["written"] is True and result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    assert doc["tradingDate"] == "2026-09-30" and doc["origin"] == "collector"
    assert ((doc["answers"] or {})["day_stage"]["choice"]) == "ferment"
    assert doc["narrativeRaw"].startswith("2026-09-30 交易日全天热榜情绪证据轨迹")
    # 版本分段不变量（2026-10-02 用户裁决）：所有落库点必须盖 questionSetVersion 戳
    assert doc["questionSetVersion"] == v2_module.QUESTION_SET_VERSION
    # 2026-10-22 日级语料修复：EOD 落结构化证据 + 覆盖度 + 语料代际戳
    assert doc["corpusCaliberVersion"] == v2_module.EOD_CORPUS_CALIBER_VERSION
    assert doc["evidenceRaw"] and doc["evidenceRaw"]["frames"]
    # A3（2026-10-24）：叙事截断 fail-visible——未超限为 False（字段恒在，additive）
    assert doc["narrativeTruncated"] is False
    assert doc["frameCoverage"]["hasCloseFrame"] is True
    assert doc["evidenceRaw"]["frameCoverage"]["expectedCount"] == 10


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
    assert doc["questionSetVersion"] == v2_module.QUESTION_SET_VERSION  # 降级路径同样盖版本戳
    # 降级路径同样保留语料证据（fail-visible：缺 token 不等于丢语料）
    assert doc["evidenceRaw"] and doc["evidenceRaw"]["frames"]
    assert doc["corpusCaliberVersion"] == v2_module.EOD_CORPUS_CALIBER_VERSION


def test_compute_day_evidence_raw_coverage_and_historical_asof(monkeypatch):
    """日级 EOD 落结构化证据 + 帧覆盖；历史日早盘不得现查 EOD 真连板（as-of 安全）。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"])
                           + [slot_frame("2026-09-30", "09:30"), frame_rows(["2026-09-30"])[0]],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": f"half_hour:2026-09-30:{s}",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}
                                for s in ("09:30", "15:00")],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)

    def fake_call(account, token, state, questions):
        answers = {
            "day_stage": {"type": "choice", "choice": "ferment", "probabilities": {"ferment": 0.7}},
            "day_crowding": {"type": "choice", "choice": "no_crowding", "probabilities": {}},
            "day_temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
            "day_pattern": {"type": "choice", "choice": "rally_fade", "probabilities": {}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "m", "answers": answers, "usage": {}}}}, 1

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                        trading_date="2026-09-30")
    assert result["status"] == "ok"
    # 09:30 历史帧 + 15:00 帧自带连板层 → 零现查（早盘 EOD 回填被禁止）
    assert calls == []
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    ev = doc["evidenceRaw"]
    cov = ev["frameCoverage"]
    assert cov["expectedCount"] == 10 and cov["frameCount"] == 2
    assert cov["hasCloseFrame"] is True
    assert len(cov["missingSlots"]) == 8
    assert len(ev["frames"]) == 2 and ev["close"]["slotTime"] == "15:00"
    assert ev["summary"]["peakTrueBoard"] == 4
    # 早盘历史槽不回填收盘态 → 仅收盘帧有真连板，必须标 close_only 而不是「全日峰值」
    assert ev["summary"]["trueBoardCoverage"] == "close_only"
    assert "收盘真连板 4 板（仅收盘帧有真连板）" in doc["narrativeRaw"]
    assert doc["frameCoverage"] == cov
    assert doc["corpusCaliberVersion"] == v2_module.EOD_CORPUS_CALIBER_VERSION
    # v2.6 裁决：不补收盘帧全量块；累计段仍给收盘真连板
    assert "【收盘帧证据】" not in doc["narrativeRaw"]
    assert "收盘真连板 4 板（仅收盘帧有真连板）" in doc["narrativeRaw"]
    assert "帧 2/10" in doc["narrativeRaw"]
    assert "缺失槽位" in doc["narrativeRaw"]


def test_compute_day_historical_early_backfilled_pools_not_used_as_asof(monkeypatch):
    """历史早盘帧池若为事后回填（ths_hist_backfill），不得冒充该槽 as-of 真连板。

    回填帧的连板层是收盘态（THS 历史=EOD 语义）；日级聚合只允许 15:00 槽采信帧池，
    早盘槽必须降级披露，否则 review P2-1：帧池捷径绕过日级 as-of 守卫。
    """
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    early = slot_frame("2026-09-30", "09:30")
    early["limitSummary"] = {
        **early["limitSummary"], "source": "ths_hist_backfill",
        "backfilledAt": "2026-10-01T00:00:00+08:00",
        "thsPools": {"pools": {
            "one": {"ok": True, "items": [{}] * 30},
            "two": {"ok": True, "items": [{}] * 10},
            "three": {"ok": True, "items": [{}] * 2},
            "four": {"ok": True, "items": [{}]},
            "high": {"ok": True, "items": [{}] * 2}}}}
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [early, frame_rows(["2026-09-30"])[0]],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": f"half_hour:2026-09-30:{s}",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}
                                for s in ("09:30", "15:00")],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })

    result = compute_and_upsert_for_day(
        db, dataset_id="dragonboard_live", trading_date="2026-09-30", dry_run=True)

    assert calls == [], "历史日早盘不得为回填帧池另发现查"
    early_ev = result["evidenceRaw"]["frames"][0]
    assert early_ev["slotTime"] == "09:30"
    assert "maxTrueBoard" not in early_ev["limit"], "回填帧池不得当作 09:30 的 as-of 真连板"
    assert any("事后回填" in item for item in early_ev["quality"]["degradedSources"])
    assert result["evidenceRaw"]["summary"]["trueBoardCoverage"] == "close_only"
    assert "收盘真连板 4 板（仅收盘帧有真连板）" in result["narrative"]


def test_evidence_skip_reason_distinguishes_missing_snapshot_id():
    """帧在但其 snapshotId 缺失/损坏：原因是 snapshot_missing，不是 rows_empty（排障不误导）。"""
    frame = slot_frame("2026-09-30", "09:30")
    frame["snapshotId"] = ""
    db = FakeMongoDb({"snapshot_frames": [frame]})
    assert v2_module._evidence_skip_reason(
        db, "dragonboard_live", "half_hour", "2026-09-30", "09:30") == "snapshot_missing"


def test_eod_reusable_requires_current_generation_and_close():
    """daily 幂等复用条件：同代 + ok + 收盘帧完整；旧代/降级/缺收盘一律重算。"""
    ok = {"status": "ok",
          "questionSetVersion": v2_module.QUESTION_SET_VERSION,
          "corpusCaliberVersion": v2_module.EOD_CORPUS_CALIBER_VERSION,
          "frameCoverage": {"hasCloseFrame": True}}
    assert v2_module._eod_reusable(ok) is True
    assert v2_module._eod_reusable(None) is False
    assert v2_module._eod_reusable({**ok, "status": "degraded"}) is False
    assert v2_module._eod_reusable({**ok, "questionSetVersion": "v2.5"}) is False
    assert v2_module._eod_reusable(
        {**ok, "corpusCaliberVersion": "v2.5_pre_eod_fix"}) is False
    assert v2_module._eod_reusable({**ok, "frameCoverage": {"hasCloseFrame": False}}) is False


def test_compute_day_reuse_complete_skips_jev_call(monkeypatch):
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    existing = {"_id": "dragonboard_live:half_hour:2026-09-30:EOD", "kind": "eod",
                "status": "ok",
                "questionSetVersion": v2_module.QUESTION_SET_VERSION,
                "corpusCaliberVersion": v2_module.EOD_CORPUS_CALIBER_VERSION,
                "frameCoverage": {"hasCloseFrame": True},
                "scores": {"day_temperature": 60.0}, "answers": {}, "narrativeRaw": "x"}
    db = FakeMongoDb({"hotlist_jev_sentiment": [existing]})

    def boom(*args, **kwargs):
        raise AssertionError("收盘帧完整且同代的 EOD 不得重复调用 jev")

    monkeypatch.setattr(v2_module, "call_jev", boom)
    result = compute_and_upsert_for_day(
        db, dataset_id="dragonboard_live", trading_date="2026-09-30",
        reuse_if_complete=True)
    assert result["written"] is False and result["reused"] is True
    assert result["dayTemperature"] == 60.0


def test_compute_day_no_frames_no_data_keeps_coverage():
    """日级无任何帧：no_data 仍落覆盖度/代际戳（不静默丢文档结构）。"""
    db = FakeMongoDb({})
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                        trading_date="2026-09-30")
    assert result["status"] == "no_data"
    # 采集链 warning 需要可用原因，不得渲染成 "None"（review P3-2）
    assert result["reason"] == "no_half_hour_frames"
    assert result["errorDetail"] == "no half_hour frames"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["status"] == "no_data"
    assert doc["evidenceRaw"]["frameCoverage"]["expectedCount"] == 10
    assert doc["evidenceRaw"]["frameCoverage"]["frameCount"] == 0
    assert doc["frameCoverage"]["hasCloseFrame"] is False
    assert doc["corpusCaliberVersion"] == v2_module.EOD_CORPUS_CALIBER_VERSION


def test_compute_day_frames_without_rows_no_data_reason():
    """帧在但所有槽无行：no_data 必须带结构化原因，且逐槽标记 rows_empty。"""
    db = FakeMongoDb({"snapshot_frames": [slot_frame("2026-09-30", "09:30")]})
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                        trading_date="2026-09-30")
    assert result["status"] == "no_data"
    assert result["reason"] == "frames_present_but_no_rows"
    assert result["errorDetail"] == "frames present but no rows"
    cov = result["frameCoverage"]
    assert cov["emptyEvidenceSlots"] == [{"slot": "09:30", "reason": "rows_empty"}]
    skipped = db["hotlist_jev_sentiment"].rows[0]["evidenceRaw"]["frames"]
    assert skipped == []  # 无 evidence 帧，不伪造


def test_compute_day_missing_close_disclosed(monkeypatch):
    """日级无 15:00 收盘帧：仍写库不阻断，但覆盖度/叙事必须显式降级。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"])
                           + [slot_frame("2026-09-30", "09:30"),
                              slot_frame("2026-09-30", "14:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": f"half_hour:2026-09-30:{s}",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}
                                for s in ("09:30", "14:00")],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)

    def fake_call(account, token, state, questions):
        answers = {
            "day_stage": {"type": "choice", "choice": "ferment", "probabilities": {}},
            "day_crowding": {"type": "choice", "choice": "no_crowding", "probabilities": {}},
            "day_temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
            "day_pattern": {"type": "choice", "choice": "rally_fade", "probabilities": {}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "m", "answers": answers, "usage": {}}}}, 1

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                        trading_date="2026-09-30")
    assert result["status"] == "ok"  # 数据质量降级不阻断主链路
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    cov = doc["frameCoverage"]
    assert cov["hasCloseFrame"] is False and cov["lastSlot"] == "14:00"
    assert "无 15:00 收盘帧" in doc["narrativeRaw"]
    assert "非全天口径" in doc["narrativeRaw"]


def test_resolve_historical_slot_no_eod_fetch_when_disallowed(monkeypatch):
    """历史日非收盘槽：allow_historical_eod_ladder=False → None，不按日查 EOD 态。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    db = FakeMongoDb({"hotlist_jev_sentiment": []})
    frame = slot_frame("2026-09-30", "10:00")
    off = v2_module._resolve_slot_true_ladder(
        db, "dragonboard_live", "half_hour", "2026-09-30", "10:00", frame,
        allow_live=False, allow_historical_eod_ladder=False)
    assert off is None and calls == []
    on = v2_module._resolve_slot_true_ladder(
        db, "dragonboard_live", "half_hour", "2026-09-30", "10:00", frame,
        allow_live=False, allow_historical_eod_ladder=True)
    assert on and on["source"] == "ths_date_eod" and calls == ["20260930"]


# ── 槽级计算（2026-10-02 V1 退役后生产槽位唯一评判）──


def slot_frame(date, slot):
    # 盘中帧形态：连板层五池不在帧内（仅 ≥15:00 入采）→ 真连板走解析器供给链
    row = frame_rows([date])[0]
    row["slotTime"] = slot
    row["snapshotId"] = f"half_hour:{date}:{slot}"
    row["_id"] = f"f:{date}:{slot}"
    row["limitSummary"] = {k: v for k, v in row["limitSummary"].items() if k != "thsPools"}
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
    assert doc["origin"] == "collector" and doc["tradingDate"] == "2026-09-30"
    assert doc["evidenceRaw"] and doc["narrativeRaw"] and doc["historyAnchorRange"]
    assert ((doc["answers"] or {})["crowding"]["choice"]) == "no_crowding"
    assert doc["questionSetVersion"] == v2_module.QUESTION_SET_VERSION  # 槽位 ok 路径盖版本戳
    assert doc["narrativeTruncated"] is False  # A3：未超限恒 False，字段恒在
    # B1 第二刀（2026-10-24）：槽级语料代际戳落库（additive，旧文档无戳=旧代）
    assert doc["corpusCaliberVersion"] == v2_module.SLOT_CORPUS_CALIBER_VERSION


def test_compute_slot_missing_frame_no_data_fail_visible(monkeypatch):
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({"snapshot_frames": frame_rows(["2026-09-29"])})
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                            trading_date="2026-09-30", slot_time="10:00")
    assert result["status"] == "no_data"
    doc = db["hotlist_jev_sentiment"].rows[0]
    assert doc["status"] == "no_data" and "missing" in (doc.get("errorDetail") or "")
    assert doc["questionSetVersion"] == v2_module.QUESTION_SET_VERSION  # no_data 路径盖版本戳


def test_compute_slot_model_failure_error_code_visible(monkeypatch):
    """槽级模型失败 degraded 返回必须带 errorCode（2026-10-09 实障回归）：
    CF code 2002 模型执行失败，返回漏 errorCode 时采集 warning 与 /evaluate 补评
    响应都显示 `hotlist_jev_degraded: None`，排障被迫查库才知道真实原因。
    文档侧 fail-visible 不变：失败不伪造 answers/scores。"""
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-30"]),
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })

    def failing_call(account, token, state, questions):
        return {"success": False,
                "errors": [{"message": '{"errors":[{"message":"Model execution failed (Error)",'
                                       '"code":2002}],"success":false,"result":{},"messages":[]}'}]}, 120

    monkeypatch.setattr(v2_module, "call_jev", failing_call)
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="15:00")
    assert result["status"] == "degraded"
    assert result["errorCode"] == "http_error", (
        "degraded 返回必须带 errorCode（采集 warning 与补评响应排障依赖）")
    doc = next(r for r in db["hotlist_jev_sentiment"].rows
               if r.get("_id") == "dragonboard_live:half_hour:2026-09-30:15:00")
    assert doc["status"] == "degraded" and doc["errorCode"] == "http_error"
    assert "2002" in str(doc.get("errorDetail"))
    assert doc["answers"] is None and doc["scores"] is None  # 失败不伪造答案


def test_compute_slot_1500_amount_fallback_survives_recompute(monkeypatch):
    """重算冲掉根治（2026-10-06）：历史帧无 indices.totalAmount（09-30 前接线），15:00 槽重算
    经 market_daily_amount 参考集合回填 amount——replace_one 全量重建不再丢锚量能坐标
    （10-05 v2.5 九月重跑冲掉 10-02 回填 20 文档的教训）。"""
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    db = FakeMongoDb({
        "snapshot_frames": [slot_frame("2026-09-15", "15:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-15:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [],
        "market_daily_amount": [{"_id": "2026-09-15", "totalAmount": 1.9e12,
                                 "source": "tdx_index_kline_backfill"}],
    })

    def fake_call(account, token, state, questions):
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
                                         trading_date="2026-09-15", slot_time="15:00")
    assert result["written"] is True and result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows
               if r.get("kind") == "slot" and r.get("slotTime") == "15:00")
    ta = (doc["evidenceRaw"] or {}).get("totalAmount") or {}
    assert ta["amount"] == 1.9e12, "重算后锚量能坐标必须存活（回退 market_daily_amount）"
    assert ta["source"] == "market_daily_amount_reference"
    assert ta["vsSamePct"] is None  # 与 10-02 回填裁决同口径：派生字段历史保持 None


# ── 2026-10-22 语料口径修复：真连板锚取数链 + 槽位真连板供给解析器 ──
# 链路：文档自供 maxTrueBoard → 15:00 帧连板层 → market_true_ladder 参考集合 → None；
# 槽位供给：帧池（EOD）→ 已存槽文档 as-of 复用 → 当日当前槽现查 / 历史日按日查 → None。


def test_calendar_max_true_board_chain_doc_frame_reference():
    """锚真连板四级取数链：文档 > 帧 > 参考集合 > None（同源=THS 连板层，混采禁令）。"""
    doc_day, frame_day, ref_day, none_day = ("2026-09-20", "2026-09-21", "2026-09-22", "2026-09-23")
    # 文档自供 6（修复后生产自供形态），帧连板层只有 4 —— 文档优先
    doc_supplied = anchor_slot_doc(doc_day, 50)
    doc_supplied["evidenceRaw"]["limit"]["maxTrueBoard"] = 6
    # doc_day 帧：无连板层（占日历位，真连板由文档自供——「文档 > 帧」正是此场景）
    doc_frame = frame_rows([doc_day])[0]
    doc_frame["limitSummary"] = {k: v for k, v in doc_frame["limitSummary"].items() if k != "thsPools"}
    # ref_day 帧：limitSummary 无连板层（10-10 前历史帧形态）
    ref_frame = frame_rows([ref_day])[0]
    ref_frame["limitSummary"] = {k: v for k, v in ref_frame["limitSummary"].items() if k != "thsPools"}
    # none_day：全无
    none_frame = frame_rows([none_day])[0]
    none_frame["limitSummary"] = {k: v for k, v in none_frame["limitSummary"].items() if k != "thsPools"}
    db = FakeMongoDb({
        "snapshot_frames": [doc_frame, frame_rows([frame_day])[0], ref_frame, none_frame]
                           + frame_rows(["2026-09-30"]),
        "hotlist_jev_sentiment": [doc_supplied, anchor_slot_doc(frame_day, 48)],
        "market_true_ladder": [{"_id": ref_day, "maxTrueBoard": 5,
                                "boards": {"one": 20, "two": 5, "three": 1, "four": 1, "high": 0},
                                "source": "ths_ladder_backfill"}],
    })
    stats = {s["date"]: s for s in build_history_stats_calendar(db, "dragonboard_live", "2026-09-30")}
    assert stats[doc_day]["maxTrueBoard"] == 6      # ① 文档自供
    assert stats[frame_day]["maxTrueBoard"] == 4    # ② 帧连板层派生
    assert stats[ref_day]["maxTrueBoard"] == 5      # ③ 参考集合回填
    assert stats[none_day]["maxTrueBoard"] is None  # ④ 全无 → None 不伪造


def test_slot_current_today_uses_live_fetch(monkeypatch):
    """当日当前盘中槽：无帧连板层、无存量文档 → THS 现查（as-of），source=ths_live。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-09-30")
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "10:00")  # 当前时钟槽窗口内
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 3, "boards": {"one": 20, "two": 5, "three": 1, "four": 2, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [slot_frame("2026-09-30", "10:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:10:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="10:00", dry_run=True)
    assert result["status"] == "dry"
    assert calls == ["20260930"]  # date8=YYYYMMDD
    lim = (result["evidence"] or {}).get("limit") or {}
    assert lim["maxTrueBoard"] == 3 and lim["trueBoardSource"] == "ths_live"
    assert "最高 3 连板（真连板）" in result["narrative"]


def test_slot_prior_today_reuses_stored_doc_no_fetch(monkeypatch):
    """当日已走帧重算：已存槽文档 as-of 真连板复用——绝不现查（now-state 会污染历史帧）；
    现查只发生在当前槽（无存量文档时）。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-09-30")
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "10:00")  # 当前时钟槽窗口内
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 3, "boards": {"one": 25, "two": 6, "three": 1, "four": 1, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    stored = {"_id": "dragonboard_live:half_hour:2026-09-30:10:00", "kind": "slot",
              "datasetId": "dragonboard_live", "snapshotType": "half_hour",
              "tradingDate": "2026-09-30", "slotTime": "10:00", "status": "ok",
              "evidenceRaw": {"limit": {"ztCount": 40, "maxTrueBoard": 2,
                                        "trueBoards": {"yiban": 20, "erban": 5, "sanban": 1,
                                                        "sibanPlus": 2, "high": 1},
                                        "trueBoardSource": "ths_live"}}}
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [slot_frame("2026-09-30", "10:00"),
                                                        slot_frame("2026-09-30", "10:30")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": f"half_hour:2026-09-30:{s}",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}
                                for s in ("10:00", "10:30")],
        "hotlist_jev_sentiment": [stored, anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="10:30", dry_run=True)
    # 仅当前槽 10:30 现查一次；已走帧 10:00 走存量文档 as-of 复用，不现查
    assert calls == ["20260930"]
    narrative = result["narrative"]
    prior_line = [line for line in narrative.split("\n") if line.startswith("10:00｜")][0]
    # 已走帧压缩行 = 存档 as-of 真连板（2 板），不是当前现查值（3 板）
    assert "最高 2 连板" in prior_line and "最高 3 连板" not in prior_line
    # 当前帧 10:30 = 现查值
    assert "最高 3 连板（真连板）" in narrative


def test_slot_historical_date_fetch_marks_eod_source(monkeypatch):
    """历史日回放：按日期查 THS 连板层（EOD 态），source=ths_date_eod（回放口径披露）。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")
    calls = []

    def fake_fetch(date8):
        calls.append(date8)
        return {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [slot_frame("2026-09-30", "10:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:10:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="10:00", dry_run=True)
    assert calls == ["20260930"]
    lim = (result["evidence"] or {}).get("limit") or {}
    assert lim["trueBoardSource"] == "ths_date_eod"
    assert "真连板取该日收盘连板层（历史回放口径）" in result["narrative"]


def test_slot_eod_frame_pools_skip_fetch(monkeypatch):
    """15:00 帧（连板层在帧内）→ 帧池 as-of 派生，零外部请求。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-09-30")

    def boom(date8):
        raise AssertionError("EOD 帧连板层已在帧内，不得外部现查")

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", boom)
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + frame_rows(["2026-09-30"]),
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="15:00", dry_run=True)
    lim = (result["evidence"] or {}).get("limit") or {}
    assert lim["trueBoardSource"] == "frame_ths_ladder" and lim["maxTrueBoard"] == 4


# ── 2026-10-22 code review 处置回归（as-of 时间窗/失败安全/口径披露）──


def test_slot_is_current_window(monkeypatch):
    """as-of 硬约束（review P1）：只有真当前时钟槽（槽后容差内）允许现查；
    已走槽被回补/重跑超出容差 → 不现查，防 now-state 冒充槽位 as-of。"""
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "14:05")
    assert v2_module._slot_is_current("14:00") is True   # 槽后 5 分钟（后处理链常态）
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "14:11")
    assert v2_module._slot_is_current("14:00") is False  # 超 10 分钟容差 → 已走槽
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "14:05")
    assert v2_module._slot_is_current("09:30") is False  # 早槽重跑一律不现查
    assert v2_module._slot_is_current("bad-slot") is False  # 畸形槽位按不可现查处理


def test_slot_stale_today_slot_rerun_no_live_fetch(monkeypatch):
    """当日早槽被盘后重跑：现查 now-state 不得落成该槽 as-of → 不现查 + 降级披露。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-09-30")
    monkeypatch.setattr(v2_module, "_sh_now_hm", lambda: "15:30")  # 已远超 10:00 槽容差

    def boom(date8):
        raise AssertionError("当日已走槽重跑不得现查（now-state 污染 as-of）")

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", boom)
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"]) + [slot_frame("2026-09-30", "10:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-09-30:10:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="10:00", dry_run=True)
    lim = (result["evidence"] or {}).get("limit") or {}
    assert "maxTrueBoard" not in lim
    assert "真连板未采集" in " ".join((result["evidence"] or {}).get("quality", {}).get("degradedSources") or [])
    assert "真连板该帧未采集" in result["narrative"]


def test_stored_doc_eod_caliber_not_reused_for_day_early_slot(monkeypatch):
    """存档里是 ths_date_eod（单槽回放写下的收盘态）→ 日级早盘槽必须拒绝复用。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-22")
    stored = {"_id": "dragonboard_live:half_hour:2026-10-21:10:00", "kind": "slot",
              "evidenceRaw": {"limit": {"maxTrueBoard": 4, "trueBoardSource": "ths_date_eod",
                                        "trueBoards": {"yiban": 34, "erban": 12, "sanban": 1,
                                                       "sibanPlus": 3, "high": 0}}}}
    db = FakeMongoDb({"hotlist_jev_sentiment": [stored]})
    frame = slot_frame("2026-10-21", "10:00")
    assert v2_module._resolve_slot_true_ladder(
        db, "dragonboard_live", "half_hour", "2026-10-21", "10:00", frame,
        allow_live=False, allow_historical_eod_ladder=False) is None
    used = v2_module._resolve_slot_true_ladder(
        db, "dragonboard_live", "half_hour", "2026-10-21", "10:00", frame,
        allow_live=False, allow_historical_eod_ladder=True)
    assert used and used["source"] == "ths_date_eod"


def test_stored_doc_ladder_malformed_degrades_not_crashes():
    """存储文档畸形（外部写入字符串等）→ None 降级，不炸整个槽计算（review P3-3）。"""
    db = FakeMongoDb({"hotlist_jev_sentiment": [
        {"_id": "dragonboard_live:half_hour:2026-09-30:10:00",
         "evidenceRaw": {"limit": {"maxTrueBoard": 3,
                                   "trueBoards": {"yiban": "abc", "erban": 5}}}},
    ]})
    assert v2_module._stored_doc_ladder(
        db, "dragonboard_live", "half_hour", "2026-09-30", "10:00") is None


def test_slot_prior_eod_caliber_note_surfaces_in_narrative(monkeypatch):
    """历史日 15:00 槽重算：priors 取 EOD 连板层（当前槽取帧池）时，披露仍进质量段。"""
    monkeypatch.setattr(v2_module, "_sh_today", lambda: "2026-10-01")

    def fake_fetch(date8):
        return {"maxBoard": 4, "boards": {"one": 30, "two": 12, "three": 1, "four": 3, "high": 0}}

    monkeypatch.setattr(v2_module, "_fetch_true_ladder", fake_fetch)
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(["2026-09-29"])
                           + [slot_frame("2026-09-30", "10:00"), frame_rows(["2026-09-30"])[0]],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": f"half_hour:2026-09-30:{s}",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}
                                for s in ("10:00", "15:00")],
        "hotlist_jev_sentiment": [anchor_slot_doc("2026-09-29", 50)],
    })
    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live",
                                         trading_date="2026-09-30", slot_time="15:00", dry_run=True)
    lim = (result["evidence"] or {}).get("limit") or {}
    assert lim["trueBoardSource"] == "frame_ths_ladder"  # 当前槽=帧池
    assert "真连板取该日收盘连板层（历史回放口径）" in result["narrative"]  # priors EOD 披露
