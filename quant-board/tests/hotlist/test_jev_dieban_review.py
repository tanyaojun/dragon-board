# -*- coding: utf-8 -*-
"""跌停复盘读口测试（services/jev/jev_dieban_review + GET /api/hotlist-jev/dieban-review）。

口径（预登记见 docs/hotlist-jev/jev-dieban-review-design.md）：
- 个股明细 = 采集池当日快照行 + THS 大幅回撤池逐股；跌停判定走 core.limit_rules 权威线；
- 全市场跌停家数 = 参考集合（东财池/快照/本地日线），**逐股明细未落库** → 降级时必须
  显式披露，不拿采集池名单冒充全市场（AGENTS §4.0）；
- 连跌 = 逐日回溯同槽跌停集合；近3日跌幅基准缺失 → None（不猜）；
- 「0 家跌停」是真读数（noData=False），只有三源全无原始记录才 noData=True。

全 monkeypatch（假库 + 假参考集合），零 Mongo/零 Redis/零网络/零 jev 调用（§1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.limit_rules import limit_down_price
from backend.operations import market_dieban_pool as mdp
from backend.services.jev import jev_dieban_review as svc


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])

    @staticmethod
    def _match(row: dict, query: dict) -> bool:
        for key, want in (query or {}).items():
            got = row.get(key)
            if isinstance(want, dict):
                if "$lt" in want and not (got is not None and got < want["$lt"]):
                    return False
                if "$in" in want and got not in want["$in"]:
                    return False
                if "$exists" in want and (got is None) == want["$exists"]:
                    return False
                if "$ne" in want and got == want["$ne"]:
                    return False
            elif got != want:
                return False
        return True

    def find(self, query=None, projection=None, sort=None):
        rows = [r for r in self.rows if self._match(r, query or {})]
        for field, direction in reversed(sort or []):
            rows.sort(key=lambda r: (r.get(field) is None, r.get(field)), reverse=direction < 0)
        return rows

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query, projection, sort)
        return rows[0] if rows else None


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


D0, D1, D2, D3 = "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"


def _frame(date, slot="15:00", drawdown=None, items=None, pool_ok=True):
    limit_summary = {}
    if drawdown is not None:
        limit_summary["drawdown"] = drawdown
    if items is not None:
        limit_summary["thsPools"] = {"ok": pool_ok, "pools": {
            "drawdown": {"ok": pool_ok, "total": len(items), "items": items}}}
    return {"datasetId": svc.DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": slot, "timestamp": date + " 15:00:00", "snapshotId": date + slot,
            "limitSummary": limit_summary}


def _row(code, pct, name="X", price=10.0, pre_close=11.0, high=None, low=None,
         sector="测试板块", main_net=None, snapshot_id="s1", slot="15:00", date=D3):
    return {"datasetId": svc.DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": slot, "snapshotId": snapshot_id, "code": code, "name": name,
            "pctChange": pct, "price": price, "preClose": pre_close,
            "high": high if high is not None else price, "low": low,
            "open": price, "limitDownPrice": limit_down_price(code, pre_close),
            "turnoverRate": 5.0, "volumeRatio": 1.5, "amount": 1e9, "zlje": main_net,
            "sectorLabel": sector, "themes": [sector], "leadStatus": ""}


@pytest.fixture(autouse=True)
def _clear_full_market_cache():
    """进程内家数缓存跨用例会串读数 → 每用例前后各清一次。"""
    svc.reset_full_market_cache()
    yield
    svc.reset_full_market_cache()


def _db(frames, rows, ref=None):
    return FakeDb({"snapshot_frames": FakeCol(frames), "snapshot_stock_rows": FakeCol(rows),
                   "market_daily_limit_down": FakeCol(ref or [])})


def _patch_market(monkeypatch, count=0, source=mdp.SOURCE_EM, hist=None):
    monkeypatch.setattr(svc, "limit_down_count", lambda db, date, dataset_id=None: (count, source))
    monkeypatch.setattr(svc, "reference_counts", lambda db, dates, source=None: hist or {})


# ── 跌停 / 一字跌停判定 ────────────────────────────────────────────────────
def test_flags_limit_down_and_one_word(monkeypatch):
    """跌停判定走 core.limit_rules（主板 -9.8 线）；一字跌停=全天最高价=跌停价。"""
    price = round(11.0 * 0.9, 2)                     # 9.90 = 主板跌停价
    rows = [
        _row("600001", -10.0, name="一字", price=price, pre_close=11.0, high=price, low=price),
        _row("600002", -9.85, name="尾盘跌停", price=price, pre_close=11.0, high=11.2, low=price),
        _row("600003", -9.5, name="未跌停", price=9.96, pre_close=11.0, high=11.2),
        _row("300004", -19.9, name="创业板", price=8.0, pre_close=10.0, high=8.2),
    ]
    db = _db([_frame(D3)], rows)
    _patch_market(monkeypatch, count=3)
    out = svc.collect_dieban_review(db, D3)

    assert out["ok"] is True and out["noData"] is False
    assert out["pool"]["dieban"] == 3                      # -10.0 / -9.85 / -19.9（创业板 19.8 线）
    assert out["pool"]["oneWord"] == 1
    by_code = {s["code"]: s for s in out["stocks"]}
    assert by_code["600001"]["oneWordLimitDown"] is True
    assert by_code["600002"]["oneWordLimitDown"] is False  # 盘中有更高价 → 非一字
    assert by_code["600003"]["limitDown"] is False          # 未达板块阈值线
    assert by_code["300004"]["limitDown"] is True           # 创业板 -19.9 达线
    assert out["pool"]["deepDrop"] == 4                    # 全部 ≤ -7%
    assert out["pool"]["deepDropOnly"] == 1                # 未跌停的大跌股


# ── 连跌回溯 / 近3日基准 ───────────────────────────────────────────────────
def test_streak_and_ret3d_from_prior_slots(monkeypatch):
    """连跌按逐日 15:00 跌停集合回溯；近3日跌幅基准取 3 个交易日前 15:00 价。"""
    price = 9.0
    frames = [_frame(d) for d in (D0, D1, D2)] + [_frame(D3)]
    rows = [
        # 前 3 日：600001 连续跌停；600002 只有 D2 跌停
        _row("600001", -10.0, price=12.1, pre_close=13.4, date=D0, slot="15:00"),
        _row("600002", -10.0, price=9.0, pre_close=10.0, date=D0, slot="15:00"),
        _row("600001", -10.0, price=10.9, pre_close=12.1, date=D1, slot="15:00"),
        _row("600001", -10.0, price=9.8, pre_close=10.9, date=D2, slot="15:00"),
        _row("600002", -10.0, price=8.1, pre_close=9.0, date=D2, slot="15:00"),
        _row("600001", -10.0, price=price, pre_close=9.8, date=D3, slot="15:00"),
        _row("600002", -10.0, price=7.3, pre_close=8.1, date=D3, slot="15:00"),
    ]
    db = _db(frames, rows)
    _patch_market(monkeypatch, count=2)
    out = svc.collect_dieban_review(db, D3)
    by_code = {s["code"]: s for s in out["stocks"]}

    assert by_code["600001"]["streak"] == 4      # D0/D1/D2/D3 连续跌停
    assert by_code["600002"]["streak"] == 2      # 只 D2/D3
    assert out["pool"]["streak2"] == 2
    assert out["pool"]["maxStreak"] == 4
    assert out["pool"]["maxStreakCode"] == "600001"
    # 近3日：D3/D0 - 1（D0 是 3 个交易日前，prior 窗口恰 3 日）
    assert by_code["600001"]["ret3d"] == round(9.0 / 12.1 * 100 - 100, 2)


def test_ret3d_null_when_history_insufficient(monkeypatch):
    """历史不足 → ret3d None 且 degraded 结构化披露（不拿 0 或单日涨跌幅冒充）。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    assert out["stocks"][0]["ret3d"] is None
    assert {"scope": "ret3d", "reason": "insufficient_history"} in out["degraded"]


# ── 回撤池合并 / 降级 ──────────────────────────────────────────────────────
def test_drawdown_pool_merges_and_counts(monkeypatch):
    """THS 回撤池逐股与采集池行按 code 合并（同一股带两个来源）；池外股单独入列。"""
    items = [
        {"stock_code": "600001", "stock_name": "甲", "change": "-8.1", "price": "9.0",
         "max_drawdown": "-12.5", "industry_block": "算力", "main_net_amount": "-1e8"},
        {"stock_code": "000002", "stock_name": "乙", "change": "3.2", "price": "20",
         "max_drawdown": "-18.0", "industry_block": "医药", "effective_turnover_ratio": "12.3"},
    ]
    db = _db([_frame(D3, drawdown={"count": 2, "avgDrawdownPct": 15.25, "deepestDrawdownPct": 18.0},
                     items=items)],
             [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    by_code = {s["code"]: s for s in out["stocks"]}

    assert by_code["600001"]["maxDrawdownPct"] == 12.5                 # 负号 → 正幅值
    assert by_code["600001"]["sources"] == ["pool", "ths_drawdown"]    # 双源标注
    assert by_code["000002"]["sources"] == ["ths_drawdown"]            # 池外股也入列（回撤口径）
    assert by_code["000002"]["maxDrawdownPct"] == 18.0
    assert out["drawdown"]["count"] == 2
    assert out["drawdown"]["itemCount"] == 2
    assert out["drawdown"]["degraded"] is None
    assert out["negative"]["count"] == 2


def test_drawdown_pool_missing_is_degraded_not_zero(monkeypatch):
    """回撤池未采集/上游失败 → degraded 披露 + itemCount None（绝不伪 0）。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    assert out["drawdown"]["itemCount"] is None
    assert out["drawdown"]["degraded"] == "drawdown_pool_missing"
    assert {"scope": "ths_drawdown_pool", "reason": "drawdown_pool_missing"} in out["degraded"]


# ── 全市场口径 / 分位 ─────────────────────────────────────────────────────
def test_full_market_scope_and_percentile(monkeypatch):
    """全市场源在同源历史内算分位；降级到采集池时显式披露 fullMarketScope=False。"""
    hist = {d: n for d, n in zip((D0, D1, D2), (3, 5, 9))}
    db = _db([_frame(D0), _frame(D1), _frame(D2), _frame(D3)],
             [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    _patch_market(monkeypatch, count=30, source=mdp.SOURCE_EM, hist=hist)
    out = svc.collect_dieban_review(db, D3)
    assert out["fullMarket"]["count"] == 30
    assert out["fullMarket"]["source"] == mdp.SOURCE_EM
    assert out["fullMarket"]["fullMarketScope"] is True
    assert out["fullMarket"]["history"] == [3, 5, 9]
    assert out["fullMarket"]["percentile"] is None      # <10 同源样本 → 分位不可算（不伪值）

    _patch_market(monkeypatch, count=4, source=mdp.SOURCE_POOL)
    svc.reset_full_market_cache()          # 绕开 120s 进程内缓存，模拟换源后的下一次读数
    out = svc.collect_dieban_review(db, D3)
    assert out["fullMarket"]["fullMarketScope"] is False
    assert {"scope": "full_market_limit_down",
            "reason": f"degraded_to_pool_scope:{mdp.SOURCE_POOL}"} in out["degraded"]


def test_full_market_count_cached_for_polling(monkeypatch):
    """页面 60s 轮询不得每分钟重算/重试家数：同一 (dataset,date) 缓存窗内只调一次。"""
    calls = []

    def _count(db, date, dataset_id=None):
        calls.append((date, dataset_id))
        return 7, mdp.SOURCE_EM

    monkeypatch.setattr(svc, "limit_down_count", _count)
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    svc.collect_dieban_review(db, D3)
    svc.collect_dieban_review(db, D3)
    assert len(calls) == 1, "缓存窗内复用读数（防 60s 轮询变每分钟外呼）"
    svc.reset_full_market_cache()
    svc.collect_dieban_review(db, D3)
    assert len(calls) == 2, "清缓存后重新读（可观测性/测试夹具语义）"


# ── noData 语义（0 家 ≠ 无数据）─────────────────────────────────────────────
def test_zero_limit_down_is_real_reading(monkeypatch):
    """采集池有行但无跌停 = 真读数：noData=False、名单为空、不报缺口。"""
    db = _db([_frame(D3, drawdown={"count": 0}, items=[])],
             [_row("600001", 2.5, price=11.5)])
    _patch_market(monkeypatch, count=0)
    out = svc.collect_dieban_review(db, D3)
    assert out["noData"] is False and out["reason"] is None
    assert out["pool"]["dieban"] == 0
    assert out["drawdown"]["count"] == 0
    assert out["stocks"] and out["stocks"][0]["limitDown"] is False


def test_no_data_only_when_all_sources_missing(monkeypatch):
    """无帧 + 无行 + 全市场不可算 → noData=True + 结构化原因（不伪空成功）。"""
    db = _db([], [])
    _patch_market(monkeypatch, count=None, source="missing")
    out = svc.collect_dieban_review(db, D3)
    assert out["noData"] is True and "fail-visible" in out["reason"]
    assert {"scope": "snapshot_frame", "reason": "no_half_hour_frame"} in out["degraded"]


# ── 盘中降级 ──────────────────────────────────────────────────────────────
def test_intraday_slot_fallback_keeps_streak_on_close_slots(monkeypatch):
    """15:00 帧未到 → 回落当日最新 half_hour 槽，intraday=True；连跌基准仍取收盘槽。"""
    frames = [_frame(D2), _frame(D3, slot="14:30")]
    rows = [
        _row("600001", -10.0, price=10.0, pre_close=11.0, date=D2, slot="15:00"),
        _row("600001", -10.0, price=9.0, pre_close=10.0, date=D3, slot="14:30"),
    ]
    db = _db(frames, rows)
    _patch_market(monkeypatch, count=2)
    out = svc.collect_dieban_review(db, D3)
    assert out["slotTime"] == "14:30" and out["intraday"] is True
    assert out["stocks"][0]["streak"] == 2      # 前一日收盘槽仍算连跌


# ── 路由 ──────────────────────────────────────────────────────────────────
def test_route_missing_date_and_db_error(monkeypatch):
    """缺 date → 422；读库异常 → 502 + 结构化 reason（fail-visible，不抛 500）。"""
    from fastapi.testclient import TestClient

    from backend.api import hotlist_jev_dieban_routes as routes
    from backend.main import app

    client = TestClient(app)
    # 完全不传 date → FastAPI 查询参数校验 422（早于 handler）
    assert client.get("/api/hotlist-jev/dieban-review").status_code == 422
    # 传空 date → handler 自己的结构化 422（fail-visible，不带 detail 数组）
    empty = client.get("/api/hotlist-jev/dieban-review?date=")
    assert empty.status_code == 422
    assert empty.json() == {"ok": False, "reason": "missing date"}

    def _boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(routes.repository_factory, "get_runtime_mongodb_database", _boom)
    resp = client.get("/api/hotlist-jev/dieban-review?date=2026-09-05")
    assert resp.status_code == 502
    assert "mongo down" in resp.json()["reason"]


# ── 全市场逐股明细（2026-10-20 立项：EM/快照/TDX 逐股合并进读口）─────────────

def _rows_doc(date, rows, source=mdp.SOURCE_EM, count=None, **extra):
    doc = {"_id": date, "source": source, "count": count if count is not None else len(rows),
           "total": None, "truncated": False, "badRows": 0, "rows": rows}
    doc.update(extra)
    return doc


def test_full_market_rows_merged_into_stocks(monkeypatch):
    """全市场逐股行并入名单：池外股（如 EM 独有）单列入列并标 full_market 来源。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [
            {"code": "000949", "name": "新乡化纤", "pctChange": -9.95, "price": 5.79,
             "industry": "化学纤维", "emStreakDays": 1, "openNum": 16,
             "lastSealTime": "14:54:06"},
            # 与采集池行同 code → 来源并集，名称/行业只在缺失时补
            {"code": "600001", "name": "甲股份", "pctChange": -10.0, "price": 9.0},
        ])])
    _patch_market(monkeypatch, count=2)
    out = svc.collect_dieban_review(db, D3)
    by_code = {s["code"]: s for s in out["stocks"]}

    assert out["fullMarket"]["rowsCount"] == 2
    assert out["fullMarket"]["rowsSource"] == mdp.SOURCE_EM
    assert out["fullMarket"]["rowsMissing"] is None
    em_only = by_code["000949"]
    assert em_only["limitDown"] is True and em_only["sources"] == ["full_market"]
    assert em_only["board"] == "化学纤维" and em_only["emStreakDays"] == 1
    assert em_only["lastSealTime"] == "14:54:06"
    merged = by_code["600001"]
    assert merged["sources"] == ["pool", "full_market"]
    assert merged["name"] == "X"            # 采集池已有名称，不覆盖
    assert {"scope": "full_market_rows", "reason": "no_rows_doc"} not in out["degraded"]


def test_full_market_rows_missing_disclosed(monkeypatch):
    """无逐股文档 → rowsMissing + degraded（页面标注「仅采集池」，不冒充全市场）。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    _patch_market(monkeypatch, count=22)
    out = svc.collect_dieban_review(db, D3)
    assert out["fullMarket"]["count"] == 22
    assert out["fullMarket"]["rowsMissing"] == "no_rows_doc"
    assert out["fullMarket"]["rowsCount"] is None
    assert {"scope": "full_market_rows", "reason": "no_rows_doc"} in out["degraded"]


def test_streak_uses_full_market_union(monkeypatch):
    """连跌回溯吃「全市场逐股 ∪ 采集池」并集：池外股的前日跌停也计入；覆盖天数披露。"""
    price = 9.0
    frames = [_frame(d) for d in (D1, D2)] + [_frame(D3)]
    rows = [
        _row("600002", -10.0, price=10.0, pre_close=11.0, date=D2),   # 采集池：仅 D2 在池
        _row("600002", -10.0, price=price, pre_close=10.0, date=D3),
    ]
    db = _db(frames, rows)
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D1, [{"code": "600002", "name": "B", "pctChange": -10.0, "price": 11.0}]),
        _rows_doc(D2, [{"code": "600002", "name": "B", "pctChange": -10.0, "price": 10.0}]),
        _rows_doc(D3, [{"code": "600002", "name": "B", "pctChange": -10.0, "price": 9.0}]),
    ])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    stock = next(s for s in out["stocks"] if s["code"] == "600002")
    assert stock["streak"] == 3          # D1 全市场逐股 + D2/D3 池内 → 连跌 3 天
    assert out["stats"]["streakDays"]["fullMarket"] == 2   # 有逐股记录的日数
    assert out["stats"]["streakDays"]["pool"] == 1
    assert out["stats"]["streakDays"]["priorDays"] == 2   # 覆盖披露（槽可用日数/回溯日数）
    assert out["stats"]["streakDays"]["slotDays"] == 1     # D1 无 15:00 采集池行 → 覆盖 1/2
    # 槽缺失会静默截断连跌 → 必须进 degraded（不是伪 0）
    assert any(d["scope"] == "streak_lookback" for d in out["degraded"])


def test_cross_source_rows_and_count_disclosed(monkeypatch):
    """家数与逐股跨源（EM 家数 vs TDX 逐股且数值不同）→ crossSource + degraded 结构化披露。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [
            {"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0},
            {"code": "600002", "name": "乙", "pctChange": -10.0, "price": 8.0},
        ], source=mdp.SOURCE_TDX)])
    _patch_market(monkeypatch, count=1, source=mdp.SOURCE_EM)
    out = svc.collect_dieban_review(db, D3)
    fm = out["fullMarket"]
    assert fm["count"] == 1 and fm["rowsCount"] == 2
    assert fm["crossSource"] is True
    assert fm["rowsSource"] == mdp.SOURCE_TDX
    # 跨源且逐股更多 → 家数存疑（比 cross_source 更强：已剔出分位窗）
    assert fm["countDisputed"] is True
    assert any(d["scope"] == "full_market_count_disputed" for d in out["degraded"])
    # 同源同数 → 不误报跨源
    db2 = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db2.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [{"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0}])])
    svc.reset_full_market_cache()
    assert svc.collect_dieban_review(db2, D3)["fullMarket"]["crossSource"] is False


# ── 2026-10-20 review 修复：并集判定 / 未知不判否 / rowsCount 语义 / 家数存疑 ──

def test_merge_pool_row_adopts_full_market_limit_down(monkeypatch):
    """池内股同时在全市场跌停名单 → 采信全市场判定（徽标一致）；池口径统计不被膨胀。"""
    # 低价股 tick 偏差：-9.7 未达板块 -9.8 线 → 池内判定 False，但全市场名单里有它
    rows = [_row("600001", -9.7, price=2.34, pre_close=2.6)]
    db = _db([_frame(D3)], rows)
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [{"code": "600001", "name": "低价股", "pctChange": -9.7, "price": 2.34}])])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    s = next(x for x in out["stocks"] if x["code"] == "600001")
    assert s["limitDown"] is True and s["limitDownPool"] is False    # 并集判定 vs 池口径分域
    assert s["sources"] == ["pool", "full_market"]                   # 来源不重复累加
    assert s["streak"] == 1
    assert out["pool"]["dieban"] == 0        # 池口径不被全市场行膨胀（旧漏洞会变 1）
    assert out["pool"]["deepDrop"] == 1      # 池内 -9.7 ≤ -7
    assert out["pool"]["deepDropOnly"] == 1  # 池口径未跌停 → 非跌停大跌


def test_merge_is_idempotent_when_code_appears_twice(monkeypatch):
    """逐股文档同 code 重复出现：来源不重复累加（列表去重守卫）。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [{"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0},
                       {"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0}])])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    s = next(x for x in out["stocks"] if x["code"] == "600001")
    assert s["sources"] == ["pool", "full_market"]


def test_full_market_only_row_one_word_is_unknown(monkeypatch):
    """全市场逐股行无盘中高低价 → 一字跌停=None（不可判），不得呈现「确认不是一字」。"""
    db = _db([_frame(D3)], [])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [{"code": "000949", "name": "新乡化纤", "pctChange": -9.95, "price": 5.79}])])
    _patch_market(monkeypatch, count=1)
    out = svc.collect_dieban_review(db, D3)
    s = next(x for x in out["stocks"] if x["code"] == "000949")
    assert s["oneWordLimitDown"] is None and s["limitDown"] is True
    assert out["pool"]["oneWord"] == 0        # 池口径不受影响


def test_rows_count_is_actual_rows_not_doc_count(monkeypatch):
    """截断日：rowsCount = 实际行数、rowsDocCount = 自报家数，两者分列不互冒。"""
    db = _db([_frame(D3)], [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D3, [{"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0},
                       {"code": "600002", "name": "乙", "pctChange": -10.0, "price": 8.0}],
                  count=26, truncated=True)])
    _patch_market(monkeypatch, count=26)
    fm = svc.collect_dieban_review(db, D3)["fullMarket"]
    assert fm["rowsCount"] == 2 and fm["rowsDocCount"] == 26 and fm["rowsTruncated"] is True


def test_disputed_count_excluded_from_history(monkeypatch):
    """家数存疑日（EM 0 vs 同日 TDX 逐股 4）不进同源分位窗，并列进 historyExcluded。"""
    frames = [_frame(d) for d in (D1, D2)] + [_frame(D3)]
    db = _db(frames, [_row("600001", -10.0, price=9.0, pre_close=10.0)])
    db.cols["market_daily_limit_down_stocks"] = FakeCol([
        _rows_doc(D1, [{"code": f"60000{i}", "pctChange": -10.0} for i in range(1, 5)],
                  source=mdp.SOURCE_TDX, count=4),
        _rows_doc(D3, [{"code": "600001", "name": "甲", "pctChange": -10.0, "price": 9.0}]),
    ])
    _patch_market(monkeypatch, count=1, source=mdp.SOURCE_EM, hist={D1: 0, D2: 2})
    out = svc.collect_dieban_review(db, D3)
    fm = out["fullMarket"]
    assert fm["history"] == [2]                 # 存疑日 0 被剔除出分位窗
    assert fm["historyExcluded"] == [D1]
