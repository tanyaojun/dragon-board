# -*- coding: utf-8 -*-
"""温度分位（answers.temperature.percentile）测试。

口径（2026-10-14 用户裁决「近20日 EOD 日级温度」）：
参照系=近 20 个交易日的 EOD scores.day_temperature，窗口严格早于当日（零未来函数），
有效样本 <10 不产出字段（fail-visible，不补 0 不伪造）。

覆盖点：窗口边界与未来函数 / 样本不足 / responseRaw 保真 / 派生字段不进原始返回。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.jev import jev_sentiment_compute as v2_module
from backend.services.jev.jev_sentiment_compute import temperature_percentile


class _Coll:
    """最小 pymongo 替身：只实现本测试用到的 find/find_one + tradingDate $lt/$gt。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])

    def find(self, query=None, projection=None):
        query = query or {}

        def ok(row):
            for key, exp in query.items():
                if key == "tradingDate" and isinstance(exp, dict):
                    val = row.get(key)
                    if "$lt" in exp and not (val and val < exp["$lt"]):
                        return False
                    if "$gt" in exp and not (val and val > exp["$gt"]):
                        return False
                    continue
                if row.get(key) != exp:
                    return False
            return True

        return iter([r for r in self.rows if ok(r)])

    def find_one(self, query=None, sort=None):
        for row in self.find(query):
            return row
        return None


class _Db(dict):
    def __init__(self, collections=None):
        super().__init__()
        for name, rows in (collections or {}).items():
            self[name] = _Coll(rows)

    def __missing__(self, name):
        self[name] = _Coll()
        return self[name]


def _frame(date):
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "_id": f"f:{date}", "snapshotId": f"half_hour:{date}:15:00"}


def _eod(date, temp):
    return {"_id": f"dragonboard_live:half_hour:{date}:EOD", "kind": "eod", "status": "ok",
            "datasetId": "dragonboard_live", "snapshotType": "half_hour",
            "tradingDate": date, "scores": {"day_temperature": temp}}


# 10 档锚点（与生产 jev score 协议同构）：分母 = len(legend)-1 = 9
TEMP_LEGEND = {str(i): i * (100 / 9) for i in range(10)}


def _window(count, start=1):
    """count 个历史交易日（严格早于 2026-10-14）+ 对应 EOD 温度。"""
    dates = [f"2026-09-{d:02d}" for d in range(start, start + count)]
    return dates, [_eod(d, 40.0 + i) for i, d in enumerate(dates)]


# ── 算法源（analysis 层）──

def test_percentile_fraction_basic_and_bool_guard():
    from backend.analysis.hotlist.jev_driver_ammo import percentile_fraction, percentile_rank

    vals = [float(i) for i in range(10)]  # 0..9
    assert percentile_fraction(vals, 5) == 0.5  # 不含 cur 自身：5 个小于 5
    assert percentile_fraction(vals, 0) == 0.0
    assert percentile_fraction(vals, 9) == 0.9
    # 布尔是 int 子类：混入 True 会同时污染样本数与「小于 cur」计数，必须显式排除。
    # 若未排除，vals=15 且有 5 个 True(=1.0) < 5 → 5/15≈0.333；排除后只有 10 个浮点 → 0.5
    assert percentile_fraction([True] * 5 + vals, 5) == 0.5
    assert percentile_rank(vals, 5) == "50"  # 展示形状委托同一算法


def test_percentile_fraction_thin_sample_returns_none():
    from backend.analysis.hotlist.jev_driver_ammo import percentile_fraction

    assert percentile_fraction([1.0] * 9, 5.0) is None  # <10 不可算
    assert percentile_fraction([], 5.0) is None
    assert percentile_fraction([1.0] * 10, None) is None  # cur 非数
    assert percentile_fraction(["a"] * 10, 5.0) is None  # 参照值非数被滤空


# ── 服务层取数（窗口/未来函数）──

def test_percentile_window_strictly_before_today():
    """未来函数防线：当日及以后的 EOD 不得进参照系（回填历史槽位时同样成立）。"""
    dates, eods = _window(12)
    db = _Db({"snapshot_frames": [_frame(d) for d in dates]
              + [_frame("2026-10-14"), _frame("2026-10-15")],
              "hotlist_jev_sentiment": eods
              + [_eod("2026-10-14", 99.0), _eod("2026-10-15", 99.0)]})
    frac, n = temperature_percentile(db, dataset_id="dragonboard_live",
                                     trading_date="2026-10-14", current=45.0)
    assert n == 12, "窗口只含严格早于当日的历史交易日"
    # 45 大于 12 个参照值中的 5 个（40..44），若混入当日 99 则结果被拉低
    assert frac == 5 / 12


def test_percentile_window_capped_at_20():
    dates, eods = _window(30)
    db = _Db({"snapshot_frames": [_frame(d) for d in dates],
              "hotlist_jev_sentiment": eods})
    _frac, n = temperature_percentile(db, dataset_id="dragonboard_live",
                                      trading_date="2026-10-14", current=50.0)
    assert n == 20, "参照系上限 ANCHOR_WINDOW=20"


def test_percentile_thin_history_no_field():
    """历史薄（<10 个有效 EOD）→ (None, n)，调用方据此不写字段。"""
    dates, eods = _window(4)
    db = _Db({"snapshot_frames": [_frame(d) for d in dates],
              "hotlist_jev_sentiment": eods})
    frac, n = temperature_percentile(db, dataset_id="dragonboard_live",
                                     trading_date="2026-10-14", current=50.0)
    assert frac is None and n == 4


def test_percentile_skips_non_ok_and_missing_temperature():
    """degraded EOD 与缺 day_temperature 的 EOD 不计入有效样本（不把降级当日当坐标）。"""
    dates, eods = _window(10)
    eods[0]["status"] = "degraded"
    eods[1]["scores"] = {}
    db = _Db({"snapshot_frames": [_frame(d) for d in dates],
              "hotlist_jev_sentiment": eods})
    _frac, n = temperature_percentile(db, dataset_id="dragonboard_live",
                                      trading_date="2026-10-14", current=50.0)
    assert n == 8


def test_percentile_no_frame_calendar_returns_none():
    db = _Db({})
    frac, n = temperature_percentile(db, dataset_id="dragonboard_live",
                                     trading_date="2026-10-14", current=50.0)
    assert frac is None and n == 0


# ── 落库接线（compute_and_upsert_for_slot）──

def _slot_db(monkeypatch, eod_rows, temperature_score=5):
    """槽级计算最小环境：一帧一行 + 给定 EOD 参照；call_jev 全 mock（禁真实调用）。"""
    from tests.hotlist.test_jev_sentiment_compute import FakeMongoDb, slot_frame

    db = FakeMongoDb({
        "snapshot_frames": [slot_frame("2026-10-13", "10:00")],
        "snapshot_stock_rows": [{"datasetId": "dragonboard_live",
                                 "snapshotId": "half_hour:2026-10-13:10:00",
                                 "code": "000001", "name": "甲", "rank": 1, "heat": 90,
                                 "pctChange": 9.9, "change": 9.9, "price": 9.66,
                                 "limitUpPrice": 9.66, "zlje": 3.0e6}],
        "hotlist_jev_sentiment": eod_rows,
    })
    monkeypatch.setattr(v2_module, "_jev_config", lambda: (True, "tok", "acc"))

    def fake_call(account, token, state, questions):
        assert questions == v2_module.JEV_SLOT_QUESTIONS
        return {"result": {"state": "Completed",
                           "result": {"model": "jev-1.13.0",
                                      "answers": {
                                          "frame_stage": {"type": "choice", "choice": "ferment",
                                                          "probabilities": {"ferment": 0.6}},
                                          "sequence_stage": {"type": "choice", "choice": "ferment",
                                                             "probabilities": {"ferment": 0.55}},
                                          "temperature": {"type": "score",
                                                          "score": temperature_score,
                                                          "legend": TEMP_LEGEND,
                                                          "probabilities": {"0": 0.1, "9": 0.9},
                                                          "confidence": 0.7},
                                          "crowding": {"type": "choice", "choice": "no_crowding",
                                                       "probabilities": {"no_crowding": 0.5}},
                                      },
                                      "usage": {"input_tokens": 800, "output_tokens": 80}}}}, 100

    monkeypatch.setattr(v2_module, "call_jev", fake_call)
    return db


def test_slot_doc_carries_temperature_percentile(monkeypatch):
    dates = [f"2026-09-{d:02d}" for d in range(3, 23)]  # 20 个历史交易日
    eods = [_eod(d, 40.0 + i) for i, d in enumerate(dates)]
    # 槽级计算需要 half_hour 帧日历；补历史帧让窗口取满
    from tests.hotlist.test_jev_sentiment_compute import slot_frame
    db = _slot_db(monkeypatch, eods, temperature_score=4.5)
    for d in dates:
        db["snapshot_frames"].rows.append(slot_frame(d, "15:00"))

    result = v2_module.compute_and_upsert_for_slot(
        db, dataset_id="dragonboard_live", trading_date="2026-10-13", slot_time="10:00")
    assert result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows
               if r.get("kind") == "slot" and r.get("slotTime") == "10:00")
    temp = doc["answers"]["temperature"]
    assert doc["scores"]["temperature"] == 50.0  # score 4.5 / (10-1) × 100
    # 50 大于 20 个参照值中的 10 个（40..49）→ P50
    assert temp["percentile"] == 0.5
    # 派生字段不得污染 responseRaw（信封元信息=模型原始返回）
    raw_temp = doc["responseRaw"]["result"]["result"]["answers"]["temperature"]
    assert "percentile" not in raw_temp, "percentile 是库内派生值，不得写进模型原始返回"


def test_slot_doc_omits_percentile_when_history_thin(monkeypatch):
    from tests.hotlist.test_jev_sentiment_compute import slot_frame
    db = _slot_db(monkeypatch, [_eod("2026-09-30", 42.0)], temperature_score=5)
    db["snapshot_frames"].rows.append(slot_frame("2026-09-30", "15:00"))

    result = v2_module.compute_and_upsert_for_slot(
        db, dataset_id="dragonboard_live", trading_date="2026-10-13", slot_time="10:00")
    assert result["status"] == "ok"
    doc = next(r for r in db["hotlist_jev_sentiment"].rows
               if r.get("kind") == "slot" and r.get("slotTime") == "10:00")
    assert "percentile" not in doc["answers"]["temperature"], "样本不足时字段缺席，不补 0"
