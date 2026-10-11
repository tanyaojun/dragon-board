# -*- coding: utf-8 -*-
"""C2 锚供给逃生率告警测试（jev-questionset-ammo-confidence-review.md P0-5）。

规格（jev-temp-crowding-confidence-deepening.md 提案C2，2026-10-02 重评版）：
单日槽位逃生率（crowding=insufficient_evidence 的 ok 槽占比）>25% 连续 2 日 → 排查锚供给；
告警只上报不阻断；基线只以现行代（questionSetVersion 戳）文档计。
全 monkeypatch/纯 fake，禁触真实 jev 调用（AGENTS.md §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev import jev_sentiment_compute as v2_module
from backend.services.jev.jev_sentiment_compute import (
    compute_and_upsert_for_day,
    evaluate_anchor_escape_alert,
)

V = v2_module.QUESTION_SET_VERSION


class _FakeCol:
    def __init__(self, rows):
        self.rows = list(rows)

    def find(self, query, projection=None):
        def match(row):
            for key, expected in query.items():
                if key == "tradingDate" and isinstance(expected, dict):
                    val = row.get(key)
                    if "$lt" in expected and not (val and val < expected["$lt"]):
                        return False
                    continue
                if row.get(key) != expected:
                    return False
            return True
        return iter([row for row in self.rows if match(row)])


class _FakeDb:
    def __init__(self, rows):
        self._col = _FakeCol(rows)

    def __getitem__(self, name):
        return self._col


def _slot(date, escape: bool, stamped=True):
    doc = {"_id": f"d:{date}:{escape}", "kind": "slot", "status": "ok",
           "datasetId": "dragonboard_live", "tradingDate": date,
           "evidenceRaw": {"limit": {"ztCount": 50}}}
    if stamped:
        doc["questionSetVersion"] = V
        doc["answers"] = {"crowding": {"type": "choice",
                                       "choice": "insufficient_evidence" if escape else "no_crowding"}}
    return doc


# ── 纯函数判定 ──

def test_alert_fires_when_two_consecutive_days_over_threshold():
    db = _FakeDb([_slot("2026-10-09", True), _slot("2026-10-09", True),
                  _slot("2026-10-10", True), _slot("2026-10-10", False)])
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["alert"] is True
    assert res["todayRate"] == 0.5 and res["prevRate"] == 1.0 and res["prevDate"] == "2026-10-09"


def test_no_alert_when_prev_day_under_threshold():
    db = _FakeDb([_slot("2026-10-09", False), _slot("2026-10-09", False),
                  _slot("2026-10-10", True), _slot("2026-10-10", True)])
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["alert"] is False and res["prevRate"] == 0.0


def test_no_alert_when_today_has_no_ok_stamped_slots():
    db = _FakeDb([_slot("2026-10-10", True, stamped=False)])  # 无戳=旧代不入基线
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["todayRate"] is None and res["alert"] is False


def test_no_alert_when_no_previous_day():
    db = _FakeDb([_slot("2026-10-10", True)])
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["prevDate"] is None and res["prevRate"] is None and res["alert"] is False


def test_threshold_is_strictly_greater():
    db = _FakeDb([_slot("2026-10-09", True), _slot("2026-10-09", True),
                  # 今日 1/4=0.25 恰在阈值上，>25% 不含等号
                  _slot("2026-10-10", True), _slot("2026-10-10", False),
                  _slot("2026-10-10", False), _slot("2026-10-10", False)])
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["todayRate"] == 0.25 and res["alert"] is False


def test_baseline_counts_only_current_generation_docs():
    # 2 份现行代（全逃生）+ 2 份无戳旧代 → 分母只算现行代，rate=1.0 非 0.5
    db = _FakeDb([_slot("2026-10-09", True), _slot("2026-10-09", True),
                  _slot("2026-10-10", True), _slot("2026-10-10", True),
                  _slot("2026-10-10", True, stamped=False),
                  _slot("2026-10-10", False, stamped=False)])
    res = evaluate_anchor_escape_alert(db, dataset_id="dragonboard_live",
                                       trading_date="2026-10-10")
    assert res["todayRate"] == 1.0 and res["alert"] is True


# ── 集成：EOD 计算落库嵌入告警字段（只上报：主链路照常 ok） ──

def test_compute_day_embeds_anchor_escape_alert(monkeypatch):
    days = ["2026-09-28", "2026-09-29", "2026-09-30"]
    rows = [{"_id": f"dragonboard_live:half_hour:{d}:15:00", "kind": "slot",
             "datasetId": "dragonboard_live", "snapshotType": "half_hour",
             "tradingDate": d, "slotTime": "15:00", "status": "ok",
             "evidenceRaw": {"limit": {"ztCount": 50, "maxBoard": 5, "zhabanRate": 12.0},
                             "totalAmount": {"amount": 1.5e12}}}
            for d in ["2026-09-28"]]
    # 前一日 2 槽全逃生 + 当日 2 槽 1 逃生（带现行代戳）→ 告警应触发
    for d, escapes in [("2026-09-29", (True, True)), ("2026-09-30", (True, False))]:
        for i, esc in enumerate(escapes):
            rows.append({**_slot(d, esc), "_id": f"s:{d}:{i}", "slotTime": "15:00",
                         "evidenceRaw": {"limit": {"ztCount": 50, "maxBoard": 5, "zhabanRate": 12.0},
                                         "totalAmount": {"amount": 1.5e12}}})

    from tests.hotlist.test_jev_sentiment_compute import FakeMongoDb, frame_rows
    db = FakeMongoDb({
        "snapshot_frames": frame_rows(days),
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live", "snapshotId": f"half_hour:{d}:15:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6} for d in days],
        "hotlist_jev_sentiment": rows,
    })
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))
    # 自持（review M11）：不依赖并行线 conftest 的 env 清洗——TYPESAFE_KEY 存在会走直连通道绕过 mock
    monkeypatch.delenv("JEV_TYPESAFE_KEY", raising=False)
    monkeypatch.delenv("JEV_TYPESAFE_PROXY", raising=False)

    def fake_call(account, token, state, questions):
        answers = {
            "day_stage": {"type": "choice", "choice": "ferment", "probabilities": {"ferment": 0.7}},
            "day_crowding": {"type": "choice", "choice": "no_crowding", "probabilities": {"no_crowding": 0.6}},
            "day_temperature": {"type": "score", "score": 5, "legend": {"0": 1, "11": 1}},
            "day_pattern": {"type": "choice", "choice": "rally_fade", "probabilities": {"rally_fade": 0.5}},
        }
        return {"result": {"state": "Completed",
                           "result": {"model": "jev-1.13.0", "answers": answers,
                                      "usage": {"input_tokens": 900, "output_tokens": 90}}}}, 100

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    result = compute_and_upsert_for_day(db, dataset_id="dragonboard_live",
                                        trading_date="2026-09-30")
    assert result["written"] is True and result["status"] == "ok"  # 告警不阻断主链路
    doc = next(r for r in db["hotlist_jev_sentiment"].rows if r.get("kind") == "eod")
    assert doc["anchorEscapeRate"] == 0.5
    assert doc["anchorEscapeAlert"]["alert"] is True
    assert doc["anchorEscapeAlert"]["prevRate"] == 1.0
