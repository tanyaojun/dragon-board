# -*- coding: utf-8 -*-
"""原料口径测试（2026-10-05 批次B + 同日二次修正）——全 fake/monkeypatch，禁触真实 jev 调用。

- I6 涨停判定线精确化 ×1.10/0.20/0.30（旧 ×1.098 近板误判）；
  同日二次修正：阈值单源 core/limit_rules，2026-09 新规无 ST 特判（主板 ST 亦 ±10%，
  批次B 的 ST ±5% 特判已撤销），判定线 -9.8/-19.8/-29.8；
- I8 快照取数带 datasetId 隔离，帧查询带 type 并取最新帧；
- I9 trading_dates_before 改查 snapshot_frames；
- 新落库文档盖 ammoVersion 戳（旧文档缺戳=旧代原料，fail-visible）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import (
    AMMO_VERSION,
    DEFAULT_DATASET_ID,
    _limit_pct_of,
    advdec_ratio,
    dieban_count,
    limitup_sequence_line,
    market_metrics,
    stock_board_shape_line,
    ths_positions,
    trading_dates_before,
)


class FakeCol:
    """记录查询参数的假集合（验证 datasetId/type/sort 下推）。"""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.queries: list[tuple[dict, dict | None, dict | None]] = []

    def find(self, query=None, projection=None):
        self.queries.append((query, projection, None))

        def matches(row):
            for key, expected in (query or {}).items():
                if key == "code" and isinstance(expected, dict) and "$in" in expected:
                    if row.get("code") not in expected["$in"]:
                        return False
                    continue
                if isinstance(expected, dict) and "$lt" in expected:
                    val = row.get(key)
                    if not (val and str(val) < expected["$lt"]):
                        return False
                    continue
                if isinstance(expected, dict) and "$exists" in expected:
                    if (row.get(key) is None) != (not expected["$exists"]):
                        return False
                    continue
                if isinstance(expected, dict) and "$ne" in expected:
                    if row.get(key) == expected["$ne"]:
                        return False
                    continue
                if row.get(key) != expected:
                    return False
            return True

        return [dict(r) for r in self.rows if matches(r)]

    def find_one(self, query=None, projection=None, sort=None):
        self.queries.append((query or {}, projection, sort))
        candidates = [r for r in self.rows if all(r.get(k) == v for k, v in (query or {}).items()
                                                  if not isinstance(v, dict))]
        if sort:
            for key, direction in reversed(sort):
                candidates.sort(key=lambda r: r.get(key) or "", reverse=direction < 0)
        return candidates[0] if candidates else None


class FakeDb:
    def __init__(self, cols: dict[str, FakeCol] | None = None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


# ---- I6 涨停判定线精确化 ----

def test_limit_pct_exact_values():
    """2026-10-05 二次修正：阈值单源 core/limit_rules，2026-09 新规无 ST 特判（主板 ST 亦 ±10%）。"""
    assert _limit_pct_of("600000", None) == 0.10
    assert _limit_pct_of("300750", None) == 0.20
    assert _limit_pct_of("688981", None) == 0.20
    assert _limit_pct_of("832000", None) == 0.30
    # 无 ST 特判（新规）：ST 标记不影响板块阈值（旧 ±5% 副本口径退役）
    assert _limit_pct_of("600000", "ST 某某") == 0.10
    assert _limit_pct_of("300750", "ST 某某") == 0.20


def test_limitup_sequence_rejects_near_limit_close(monkeypatch):
    """prev=10.00，收盘 10.98：真实涨停价 11.00，不应再被误判涨停（旧 ×1.098 判定线 10.98）。"""
    bars = [{"date": "2026-09-29", "high": 10.0, "close": 10.0, "vol": 1000.0},
            {"date": "2026-09-30", "high": 10.99, "close": 10.98, "vol": 1000.0}]
    monkeypatch.setattr(runner, "_daily_bars", lambda code: bars)
    monkeypatch.setattr(runner, "_adj_prev_series", lambda date, code, bars_: {})  # P1-1：测试离线，原口径
    line = limitup_sequence_line("2026-09-30", "600000", None, n=2)
    assert "近 2 日 ○●" not in line  # 10.98 非涨停
    assert "当前连板 0" in line

    bars[-1]["close"] = 11.00
    bars[-1]["high"] = 11.00
    line = limitup_sequence_line("2026-09-30", "600000", None, n=2)
    assert "当前连板 1" in line  # 11.00 = 涨停价


def test_board_shape_rejects_near_limit_touch(monkeypatch):
    """板型：最高 10.98 未触真实涨停价 11.00 → 未触板（旧实现会算首触/炸板）。"""
    intraday = [{"date": "2026-09-30", "hm": "10:00", "open": 10.5, "high": 10.98, "close": 10.9}]
    monkeypatch.setattr(runner, "_daily_bars",
                        lambda code: [{"date": "2026-09-29", "high": 10.0, "close": 10.0, "vol": 1.0},
                                      {"date": "2026-09-30", "high": 10.98, "close": 10.9, "vol": 1.0}])
    monkeypatch.setattr(runner, "_intraday_bars", lambda code: intraday)
    line = stock_board_shape_line("2026-09-30", "600000", None, prev_close=10.0)
    assert "未触板" in line


# ---- I7 跌停 ST + I8 datasetId 隔离 ----

def _row(code, pct, dataset=DEFAULT_DATASET_ID, name=None, slot="15:00"):
    return {"datasetId": dataset, "type": "half_hour", "tradingDate": "2026-09-30",
            "slotTime": slot, "code": code, "name": name, "pctChange": pct}


def test_dieban_by_board_thresholds():
    """2026-10-05 二次修正：新规无 ST 特判，判定线单源 core/limit_rules（-9.8/-19.8/-29.8）。"""
    rows = [_row("600001", -9.9, name="甲"),      # 主板 -9.9 ≤ -9.8 计
            _row("600002", -5.0, name="ST 乙"),    # 新规主板 ST 亦 ±10%：-5.0 不计
            _row("600003", -5.0, name="丙"),       # 主板非ST -5.0 不计
            _row("300001", -19.9, name="丁"),      # 创业 20cm 计
            _row("300002", -5.0, name="ST 戊"),    # 创业不计
            _row("920001", -29.9, name="己"),      # 北交 920 计
            ]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") == 3


def test_dieban_dataset_isolated():
    rows = [_row("600001", -10.0, dataset="other_dataset", name="甲")]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") is None  # 其它 dataset 不串数
    assert dieban_count(db, "2026-09-30", dataset_id="other_dataset") == 1


def test_dieban_missing_name_no_st_false_positive():
    rows = [_row("600001", -5.0)]  # 无 name：按主板阈值，不误判
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert dieban_count(db, "2026-09-30") == 0


def test_advdec_dataset_isolated():
    rows = [_row("600001", 5.0, dataset="other")]
    db = FakeDb({"snapshot_stock_rows": FakeCol(rows)})
    assert advdec_ratio(db, "2026-09-30") is None
    assert advdec_ratio(db, "2026-09-30", dataset_id="other") == (1, 0, 0, 1.0)


# ---- I8 帧查询下推 datasetId/type/sort ----

def test_market_metrics_query_scoped_and_latest():
    col = FakeCol([
        {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "old", "timestamp": 1,
         "limitSummary": {"zhaban": {"ztCount": 30}}},
        {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "new", "timestamp": 2,
         "limitSummary": {"zhaban": {"ztCount": 55}}},
        {"datasetId": "other", "type": "half_hour", "tradingDate": "2026-09-30",
         "slotTime": "15:00", "snapshotId": "x", "timestamp": 9,
         "limitSummary": {"zhaban": {"ztCount": 999}}},
    ])
    db = FakeDb({"snapshot_frames": col})
    m = market_metrics(db, "2026-09-30")
    assert m["ztCount"] == 55  # 取同 dataset 最新帧
    query, projection, sort = col.queries[-1]
    assert query["datasetId"] == DEFAULT_DATASET_ID and query["type"] == "half_hour"
    assert sort == [("timestamp", -1), ("snapshotId", -1)]


def test_ths_positions_query_scoped():
    col = FakeCol([{"datasetId": DEFAULT_DATASET_ID, "type": "half_hour",
                    "tradingDate": "2026-09-30", "slotTime": "15:00",
                    "limitSummary": {"thsPools": {"pools": {
                        "one": {"items": [{"stock_code": "sh600000", "continue_day": 1,
                                           "limit_up_time": "09:31", "industry_block": "地产",
                                           "main_net_amount": 1e7}]}}}}}])
    db = FakeDb({"snapshot_frames": col})
    out = ths_positions(db, "2026-09-30")
    assert "600000" in out
    query, _, sort = col.queries[-1]
    assert query["datasetId"] == DEFAULT_DATASET_ID and query["type"] == "half_hour"
    assert sort == [("timestamp", -1), ("snapshotId", -1)]


# ---- I9 交易日历改查 snapshot_frames ----

def test_trading_dates_before_uses_frames_not_rows():
    db = FakeDb({
        "snapshot_frames": FakeCol([
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-28"},
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-29"},
            {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": "2026-09-30"},
            {"datasetId": "other", "type": "half_hour", "tradingDate": "2026-09-27"},
        ]),
        "snapshot_stock_rows": FakeCol([{"tradingDate": "2026-09-26"}]),  # 若误查 rows 会有 09-26
    })
    dates = trading_dates_before(db, "2026-09-30")
    assert dates == ["2026-09-28", "2026-09-29"]  # 只来自 frames 且隔离 dataset
    assert "snapshot_stock_rows" not in db.cols or db.cols["snapshot_stock_rows"].queries == []


# ---- ammoVersion 代际戳 ----

def test_ammo_version_stamp_constant():
    # P1-1（预登记 jev-ammo-p1-preregistration.md §一）：除权修正因子入叙事，代际顺延
    assert AMMO_VERSION == "2026-10-11a"
    assert DEFAULT_DATASET_ID == "dragonboard_live"


# ---- 2026-10-10 梯队双源（jiuyan 主源 / THS 回退，Phase 0）----

def _frame(date: str, *, ths_pools: dict | None = None, zt: int = 55) -> dict:
    ls: dict = {"zhaban": {"ztCount": zt, "count": 8, "rate": 12.0}, "drawdown": {"count": 3},
                "continuousBoards": {"maxBoard": 6}}
    if ths_pools is not None:
        ls["thsPools"] = {"pools": ths_pools}
    return {"datasetId": DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"half_hour:{date}:15:00", "timestamp": 2,
            "limitSummary": ls}


def _jiuyan_final(date: str, boards: list, *, codes: list | None = None) -> dict:
    """boards: 每股真实板数（None=韭研首板不标 num）；codes 可指定（默认 60000{i}）。"""
    stocks = []
    for i, b in enumerate(boards):
        code = (codes[i] if codes else f"60000{i}")
        num = None if b is None else f"{b}天{b}板"
        stocks.append({"code": code, "num": num})
    return {"_id": f"{date}:final", "fields": [{"name": "板块A", "stocks": stocks}]}


def test_market_metrics_ladder_jiuyan_primary():
    """jiuyan 主源：num「N天M板」按 M 入桶；首板 null 入 one；昨日池内漏标计入 UnmarkedPrev。"""
    ths = {k: {"total": 1} for k in ("one", "two", "three", "four", "high")}
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame("2026-09-30", ths_pools=ths),
            _frame("2026-09-29"),  # 昨日帧（供 trading_dates_before 定位前一日）
        ]),
        "jiuyan_action": FakeCol([
            # 妖股跨口径：16天8板 → 按 8 板入 high（不得用天跨 16 入桶）
            _jiuyan_final("2026-09-30", [1, 1, 2, 3, 5, 9, None, None]),
        ]),
    })
    db.cols["jiuyan_action"].rows[0]["fields"][0]["stocks"].append(
        {"code": "600010", "num": "16天8板", "day": 16})  # day 字段是天跨，不得污染桶
    # 昨日池含 600006（今日 null 且在昨日池 → 真连板漏标，不计桶）
    db.cols["jiuyan_action"].rows.append({
        "_id": "2026-09-29:final",
        "fields": [{"name": "板块A", "stocks": [
            {"code": "600006", "num": "2天2板"}, {"code": "600099", "num": "4天4板"}]}]})
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "jiuyan"
    # one=2只1板 + 600007首板；two/three 按值；high=5板/9板/8板妖股
    assert m["ladder"] == {"one": 3, "two": 1, "three": 1, "four": 0, "high": 3}
    assert m["ladderPoolTotal"] == 9
    assert m["ladderDayUnmarked"] == 2 and m["ladderDayUnmarkedPrev"] == 1
    assert m["thsLadder"] == {"one": 1, "two": 1, "three": 1, "four": 1, "high": 1}


def test_market_metrics_ladder_ths_fallback_when_jiuyan_missing():
    """jiuyan final 缺失 → THS 回退并标注来源。"""
    ths = {"one": {"total": 25}, "two": {"total": 3}, "three": {"total": 3},
           "four": {"total": 0}, "high": {"total": 1}}
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-09-30", ths_pools=ths)]),
        "jiuyan_action": FakeCol([]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "ths"
    assert m["ladder"] == {"one": 25, "two": 3, "three": 3, "four": 0, "high": 1}
    assert m["thsLadder"] == m["ladder"]


def test_market_metrics_ladder_both_missing_fail_visible():
    """双源皆缺 → ladder 全 None + source=missing，绝不伪造零梯队。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-09-30", ths_pools={})]),
        "jiuyan_action": FakeCol([]),
    })
    m = market_metrics(db, "2026-09-30")
    assert m["ladderSource"] == "missing"
    assert all(v is None for v in m["ladder"].values())
    assert m["thsLadder"] is None
