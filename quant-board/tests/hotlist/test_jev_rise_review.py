# -*- coding: utf-8 -*-
"""上涨复盘读口测试（services/jev/jev_rise_review + GET /api/hotlist-jev/rise-review）。

口径（services/jev/jev_rise_review 模块 docstring 为单一事实源）：
- 全市场逐股 = `market_daily_rise_stocks`（本地日线：涨幅>5% 且收盘未封涨停，价格精确闸）；
- 采集池行同一条价格精确闸判定「未涨停」；触板未封缺高低价 → None（未知不判否）；
- 连涨 = 逐日回溯全市场上涨集合；「0 只上涨」是真读数（noData=False），
  只有「无采集池行 + 无逐股文档」才 noData=True。

全 monkeypatch（假库 + 假逐股文档），零 Mongo/零 Redis/零网络/零 jev 调用（§1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.limit_rules import limit_up_price
from backend.operations import market_rise_pool as rp
from backend.services.jev import jev_dieban_review as _die
from backend.services.jev import jev_rise_review as svc


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
            elif got != want:
                return False
        return True

    def find(self, query=None, projection=None, sort=None):
        return [r for r in self.rows if self._match(r, query or {})]

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query, projection, sort)
        return rows[0] if rows else None


class FakeDb:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


D0, D1, D2, D3 = "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"
_UNSET = object()   # 哨兵：区分「未传」与「显式 None」（缺 high → touched 不可判的路径要造得出来）


def _frame(date, slot="15:00"):
    return {"datasetId": svc.DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": slot, "timestamp": date + " 15:00:00", "snapshotId": date + slot,
            "limitSummary": {}}


def _row(code, pct, name="X", price=10.0, pre_close=10.0, high=_UNSET, low=None,
         sector="测试板块", main_net=None, snapshot_id="s1", slot="15:00", date=D3):
    return {"datasetId": svc.DEFAULT_DATASET_ID, "type": "half_hour", "tradingDate": date,
            "slotTime": slot, "snapshotId": snapshot_id, "code": code, "name": name,
            "pctChange": pct, "price": price, "preClose": pre_close,
            "high": high if high is not _UNSET else price, "low": low,
            "open": price, "turnoverRate": 5.0, "volumeRatio": 1.5, "amount": 1e9,
            "zlje": main_net, "sectorLabel": sector, "themes": [sector], "leadStatus": ""}


def _rise_doc(date, rows, source=rp.SOURCE_TDX, count=None):
    return {"_id": date, "source": source, "count": count if count is not None else len(rows),
            "rows": rows}


def _full_row(code, pct, price, prev_close, name="甲", touched=None, high=None, low=None):
    lu = limit_up_price(code, prev_close)
    return {"code": code, "name": name, "pctChange": pct, "price": price,
            "prevClose": prev_close, "open": prev_close, "high": high if high is not None else price,
            "low": low if low is not None else price, "limitUpPrice": lu,
            "touchedLimitUp": touched, "amount": 5e8, "volume": 1e6}


@pytest.fixture(autouse=True)
def _clear_caches():
    """rise 缓存 + die 共享槽位缓存（同日期跨用例/跨假库会串读数）。"""
    svc.reset_rise_cache()
    _die.reset_full_market_cache()
    yield
    svc.reset_rise_cache()
    _die.reset_full_market_cache()


def _db(frames, rows, rise_rows=None):
    cols = {"snapshot_frames": FakeCol(frames), "snapshot_stock_rows": FakeCol(rows)}
    if rise_rows is not None:
        cols[rp.COLLECTION_ROWS] = FakeCol(rise_rows)
    return FakeDb(cols)


def _patch_full(monkeypatch, docs_by_date):
    """monkeypatch 全市场逐股读口（含懒加载入口）：date → doc|None。"""
    monkeypatch.setattr(svc.rp, "rows_lazy",
                        lambda db, date: docs_by_date.get(date))


# ── 扫描判定（market_rise_pool._scan_file_rise）────────────────────────────
def _rec(date_iso, open_, high, low, close, amount=1e8, vol=1e6):
    d = int(date_iso.replace("-", ""))
    return (d, round(open_ * 100), round(high * 100), round(low * 100), round(close * 100),
            amount, vol, 0)


def test_scan_file_rise_criterion():
    """涨幅>5% 且收盘未封涨停才入名单；封死涨停剔除；触板未封标 True；5% 整点不入。"""
    recs = [
        _rec(D2, 10.0, 10.2, 9.9, 10.0),                    # 前收基准
        _rec(D3, 10.1, 11.0, 10.1, 10.8),                   # +8% 触板(11.00=涨停价)未封
        _rec(D1, 10.1, 11.0, 10.1, 11.0),                   # +10% 收盘封死 → 剔除
        _rec(D0, 10.1, 10.5, 10.1, 10.5),                   # +5% 整点（不严格大于）→ 不入
    ]
    hits, seen = rp._scan_file_rise(recs, "600001", {D0, D1, D2, D3})
    assert set(hits) == {D3}
    assert seen == {D0, D1, D3}   # 有棒即计（D2 首根为前收基准不计；封死/涨幅不足日同样计）
    row = hits[D3]
    assert row["code"] == "600001" and row["pctChange"] == 8.0
    assert row["price"] == 10.8 and row["prevClose"] == 10.0
    assert row["limitUpPrice"] == 11.0
    assert row["touchedLimitUp"] is True


def test_scan_file_rise_chi_next_board():
    """创业板 20% 线：+25% 收盘封死剔除；未封的 +23% 入名单。"""
    recs = [
        _rec(D2, 10.0, 10.2, 9.9, 10.0),
        _rec(D3, 10.1, 12.0, 10.1, 12.0),                   # 封死（涨停价 12.00）
    ]
    assert rp._scan_file_rise(recs, "300001", {D3}) == ({}, {D3})
    recs2 = [
        _rec(D2, 10.0, 10.2, 9.9, 10.0),
        _rec(D3, 10.1, 12.0, 10.1, 12.3),                  # 未封 +23%，high 触板（容差 0.005 内）
    ]
    hits, seen = rp._scan_file_rise(recs2, "300001", {D3})
    assert seen == {D3}                                    # 有棒即计（判定闸之前）
    assert hits[D3]["touchedLimitUp"] is True and hits[D3]["pctChange"] == 23.0


# ── scan_rows 覆盖闸（2026-10-31 review blocker 配套：seen 必须计「有棒文件数」非「命中行数」）──
def test_scan_rows_coverage_gate(monkeypatch):
    """覆盖闸：①真 0 只日（全员无涨幅）不被误判 partial，空名单照出；
    ②少数文件有棒的读窗边缘日被判 partial 整日丢弃（不冒充名单）。"""
    # 三只股票：600001 在 D2/D3 均有棒，600002/600003 仅 D3 有棒（D2 处读窗边缘）
    # （每文件首根记录只作前收基准，不参与该日扫描，故 D2 有棒需要 D1 基准棒）
    recs_3 = [_rec(D1, 10.0, 10.2, 9.9, 10.0), _rec(D2, 10.0, 10.2, 9.9, 10.0),
              _rec(D3, 10.0, 10.2, 9.9, 10.0)]
    recs_2 = [_rec(D1, 10.0, 10.2, 9.9, 10.0), _rec(D3, 10.0, 10.2, 9.9, 10.0)]
    paths = ["/fake/vipdoc/sh/lday/sh600001.day",
             "/fake/vipdoc/sh/lday/sh600002.day", "/fake/vipdoc/sh/lday/sh600003.day"]
    monkeypatch.setattr(rp.glob, "glob", lambda pattern: paths if "sh" in pattern else [])
    monkeypatch.setattr(rp.tdx, "read_lday",
                        lambda path, take: recs_3 if "600001" in path else recs_2)
    rows_by_date, meta = rp.scan_rows(
        [D2, D3], root="/fake", universe={"600001", "600002", "600003"})
    # D3：三文件全有棒 → 覆盖足，0 只上涨是真读数（空名单），不得判 partial
    assert rows_by_date[D3] == []
    assert D3 not in meta["partial"] and meta["zero_days"] == 1
    # D2：仅 1/3 文件有棒 → 覆盖不足，整日丢弃（不在结果里 = 缺口）
    assert D2 not in rows_by_date and D2 in meta["partial"]


def test_scan_rows_hit_rows_counted(monkeypatch):
    """命中行照常入名单；覆盖计数独立于命中（强势日命中多不影响弱势日覆盖判定）。"""
    recs = [
        _rec(D1, 10.0, 10.2, 9.9, 10.0),
        _rec(D2, 10.0, 10.2, 9.9, 10.0),
        _rec(D3, 10.1, 10.9, 10.1, 10.8),                   # D3 +8% 入名单
    ]
    paths = [f"/fake/vipdoc/sh/lday/sh60000{i}.day" for i in (1, 2)]
    monkeypatch.setattr(rp.glob, "glob", lambda pattern: paths if "sh" in pattern else [])
    monkeypatch.setattr(rp.tdx, "read_lday", lambda path, take: recs)
    rows_by_date, meta = rp.scan_rows([D2, D3], root="/fake",
                                      universe={"600001", "600002"})
    assert [r["code"] for r in rows_by_date[D3]] == ["600001", "600002"]
    assert rows_by_date[D2] == []          # D2 覆盖足但 0 只 → 真读数空名单
    assert meta["partial"] == []


# ── 采集池口径判定 ─────────────────────────────────────────────────────────
def test_pool_rise_and_strong_flags(monkeypatch):
    """池内涨幅>5% 未涨停入名单；>7% 标大涨；封死涨停不入；资金只在池行统计。"""
    rows = [
        _row("600001", 6.5, price=10.65, pre_close=10.0, main_net=5e6),
        _row("600002", 8.0, price=10.8, pre_close=10.0, high=10.9, main_net=8e6),
        _row("600003", 10.0, price=11.0, pre_close=10.0, high=11.0),   # 封死涨停
        _row("600004", 3.0, price=10.3, pre_close=10.0),               # 涨幅不足
    ]
    db = _db([_frame(D3)], rows)
    _patch_full(monkeypatch, {})
    out = svc.collect_rise_review(db, D3)
    by = {s["code"]: s for s in out["stocks"]}
    assert by["600001"]["rise"] is True and by["600001"]["strong"] is False
    assert by["600002"]["rise"] is True and by["600002"]["strong"] is True
    assert by["600003"]["rise"] is False and by["600003"]["sealedLimitUp"] is True
    assert by["600004"]["rise"] is False
    assert out["pool"]["rise"] == 2 and out["pool"]["strong"] == 1
    assert out["pool"]["up"] == 4   # 4 行涨幅全部 > 0.1（含封涨停与涨幅不足股）
    assert out["positive"]["netInflowTotal"] == 13e6   # 池内 rise 行（600001/600002）主力净额合计


def test_pool_missing_preclose_unknown_not_false(monkeypatch):
    """缺前收 → 封板不可判（None），涨幅>5% 照样入名单；触板不可判为 None（未知不判否）。"""
    rows = [_row("600001", 6.0, price=10.6, pre_close=None, high=None)]
    db = _db([_frame(D3)], rows)
    _patch_full(monkeypatch, {})
    out = svc.collect_rise_review(db, D3)
    s = out["stocks"][0]
    assert s["rise"] is True
    assert s["sealedLimitUp"] is None and s["touchedLimitUp"] is None


def test_pool_touched_unknown_when_high_missing(monkeypatch):
    """有涨停价但缺盘中 high → touched None（不可判，不写 False）；回落股触板如实标 True。"""
    rows = [_row("600001", 6.0, price=10.6, pre_close=10.0, high=None),   # high 缺 → None
            _row("600002", 3.0, price=10.3, pre_close=10.0, high=11.0)]   # 未入名单但触板未封
    db = _db([_frame(D3)], rows)
    _patch_full(monkeypatch, {})
    out = svc.collect_rise_review(db, D3)
    by = {s["code"]: s for s in out["stocks"]}
    assert by["600001"]["touchedLimitUp"] is None
    assert by["600002"]["rise"] is False and by["600002"]["touchedLimitUp"] is True


def test_full_market_touched_none_passthrough(monkeypatch):
    """全市场行 touchedLimitUp=None 透传；与池行合并时只在池侧缺值时回填。"""
    db = _db([_frame(D3)], [_row("600001", 6.0, price=10.6, pre_close=10.0)])
    db.cols[rp.COLLECTION_ROWS] = FakeCol([
        _rise_doc(D3, [_full_row("600001", 6.0, 10.6, 10.0, touched=None)])])
    _patch_full(monkeypatch, {D3: db.cols[rp.COLLECTION_ROWS].rows[0]})
    out = svc.collect_rise_review(db, D3)
    s = next(x for x in out["stocks"] if x["code"] == "600001")
    # 池行自身可算（high=10.6 ≉ 涨停价 11.0）→ False；全市场行 None 不覆盖已有判定
    assert s["touchedLimitUp"] is False
    assert s["sources"] == ["pool", "full_market"]


# ── 全市场逐股合并 / 缺文档披露 ─────────────────────────────────────────────
def test_full_market_rows_merged(monkeypatch):
    """全市场逐股并入名单：池外股单列入列标 full_market；与池行同码来源并集。"""
    db = _db([_frame(D3)], [_row("600001", 6.5, price=10.65, pre_close=10.0)])
    db.cols[rp.COLLECTION_ROWS] = FakeCol([
        _rise_doc(D3, [
            _full_row("000949", 6.2, 5.4, 5.08, name="新乡化纤", touched=False),
            _full_row("600001", 6.5, 10.65, 10.0, name="甲股份"),
        ])])
    _patch_full(monkeypatch, {D3: db.cols[rp.COLLECTION_ROWS].rows[0]})
    out = svc.collect_rise_review(db, D3)
    by = {s["code"]: s for s in out["stocks"]}
    assert out["fullRise"]["rowsCount"] == 2
    assert out["fullRise"]["rowsSource"] == rp.SOURCE_TDX
    em_only = by["000949"]
    assert em_only["rise"] is True and em_only["sources"] == ["full_market"]
    assert em_only["touchedLimitUp"] is False
    merged = by["600001"]
    assert merged["sources"] == ["pool", "full_market"]
    assert {"scope": "full_market_rise", "reason": "no_rows_doc"} not in out["degraded"]


def test_rows_doc_missing_disclosed_and_no_data(monkeypatch):
    """无逐股文档 → rowsMissing + degraded；连采集池行也无 → noData（不伪 0）。"""
    rows = [_row("600001", 6.5, price=10.65, pre_close=10.0)]
    db = _db([_frame(D3)], rows)
    _patch_full(monkeypatch, {D3: None})
    out = svc.collect_rise_review(db, D3)
    assert out["fullRise"]["rowsMissing"] == "no_rows_doc"
    assert {"scope": "full_market_rise", "reason": "no_rows_doc"} in out["degraded"]
    assert out["noData"] is False
    # 连采集池行也无 → noData（两次调用间清共享槽位缓存：die 缓存键不含 db 实例，
    # 生产单库无此问题；测试内两个假库共用进程缓存必须显式清）
    db2 = _db([_frame(D3)], [])
    svc.reset_rise_cache()
    _die.reset_full_market_cache()
    out2 = svc.collect_rise_review(db2, D3)
    assert out2["noData"] is True and out2["reason"]


def test_zero_rise_day_is_real_reading(monkeypatch):
    """覆盖足但当日 0 只（空 rows 文档）→ 真读数，noData=False。"""
    db = _db([_frame(D3)], [_row("600001", 3.0, price=10.3, pre_close=10.0)],
             rise_rows=[_rise_doc(D3, [])])
    _patch_full(monkeypatch, {D3: _rise_doc(D3, [])})
    out = svc.collect_rise_review(db, D3)
    assert out["noData"] is False
    assert out["fullRise"]["count"] == 0 and out["fullRise"]["rowsCount"] == 0


# ── 连涨回溯 / 近3日涨幅 ───────────────────────────────────────────────────
def test_streak_uses_full_market_history(monkeypatch):
    """连涨回溯吃 market_daily_rise_stocks 逐日集合：D1/D2 全市场 + D3 池内 → 连涨 3 天。"""
    frames = [_frame(d) for d in (D1, D2)] + [_frame(D3)]
    rows = [_row("600002", 6.0, price=10.6, pre_close=10.0, date=D2, snapshot_id="d2"),
            _row("600002", 6.0, price=10.6, pre_close=10.0, date=D3)]
    db = _db(frames, rows)
    db.cols[rp.COLLECTION_ROWS] = FakeCol([
        _rise_doc(D1, [{"code": "600002", "name": "B", "pctChange": 6.0}]),
        _rise_doc(D2, [{"code": "600002", "name": "B", "pctChange": 6.0}]),
        _rise_doc(D3, [{"code": "600002", "name": "B", "pctChange": 6.0}]),
    ])
    _patch_full(monkeypatch, {D3: db.cols[rp.COLLECTION_ROWS].rows[2], D2: db.cols[rp.COLLECTION_ROWS].rows[1]})
    out = svc.collect_rise_review(db, D3)
    stock = next(s for s in out["stocks"] if s["code"] == "600002")
    assert stock["streak"] == 3
    assert out["stats"]["streakDays"]["riseDocs"] == 2   # D1/D2 有文档（D3 为当日不计）
    # D1 无 15:00 采集池行 → 槽覆盖披露
    assert any(d["scope"] == "streak_lookback" for d in out["degraded"])


def test_ret3d_from_pool_price_history(monkeypatch):
    """近3日累计涨幅：当前价 / 3 个交易日前 15:00 收盘价 − 1（基准=该日收盘价，非昨收）。"""
    frames = [_frame(d) for d in (D0, D1, D2)] + [_frame(D3)]
    rows = [_row("600001", 5.0, price=8.0, pre_close=10.0, date=D0, snapshot_id="d0"),
            _row("600001", 6.0, price=8.48, pre_close=8.0, date=D3)]
    db = _db(frames, rows)
    _patch_full(monkeypatch, {D3: None})
    out = svc.collect_rise_review(db, D3)
    stock = next(s for s in out["stocks"] if s["code"] == "600001")
    assert stock["ret3d"] == 6.0           # 8.48/8.0 - 1（D0 15:00 收盘价 8.0 为基准）
    assert out["stats"]["retWindow"] == 3


# ── 盘中口径 / 家数分位 ─────────────────────────────────────────────────────
def test_intraday_slot_used(monkeypatch):
    """15:00 帧未到 → 回落最新槽，intraday=True。"""
    rows = [_row("600001", 6.0, price=10.6, pre_close=10.0, slot="14:30", snapshot_id="s1430")]
    db = _db([_frame(D3, slot="14:30")], rows)
    _patch_full(monkeypatch, {D3: None})
    out = svc.collect_rise_review(db, D3)
    assert out["intraday"] is True and out["slotTime"] == "14:30"


def test_history_percentile_same_source(monkeypatch):
    """家数分位只吃同源（TDX）文档；缺文档日剔除并披露。"""
    frames = [_frame(d) for d in (D0, D1, D2)] + [_frame(D3)]
    rows = [_row("600001", 6.0, price=10.6, pre_close=10.0)]
    db = _db(frames, rows)
    db.cols[rp.COLLECTION_ROWS] = FakeCol([
        _rise_doc(D1, [{"code": "600001"}], count=30),
        _rise_doc(D2, [{"code": "600001"}], count=50),
    ])
    _patch_full(monkeypatch, {D3: _rise_doc(D3, [_full_row("600001", 6.0, 10.6, 10.0)])})
    out = svc.collect_rise_review(db, D3)
    fr = out["fullRise"]
    assert fr["count"] == 1 and fr["historyDays"] == 2
    assert fr["history"] == [30, 50]
    assert D0 in fr["historyMissing"] and len(fr["historyMissing"]) >= 1
    # 缺文档日进 degraded 结构化披露（正句锁定，不恒真）
    assert {"scope": "rise_history", "reason": "history_doc_missing:1"} in out["degraded"]
    assert isinstance(fr["historyMissing"], list)


# ── 路由 ──────────────────────────────────────────────────────────────────
def test_route_missing_date_and_db_error(monkeypatch):
    """缺 date → 422；读库异常 → 502 + 结构化 reason（fail-visible，不抛 500）。"""
    from fastapi.testclient import TestClient

    from backend.api import hotlist_jev_rise_routes as routes
    from backend.main import app

    client = TestClient(app)
    assert client.get("/api/hotlist-jev/rise-review").status_code == 422
    empty = client.get("/api/hotlist-jev/rise-review?date=")
    assert empty.status_code == 422
    assert empty.json() == {"ok": False, "reason": "missing date"}

    def _boom():
        raise RuntimeError("mongo down")

    monkeypatch.setattr(routes.repository_factory, "get_runtime_mongodb_database", _boom)
    resp = client.get("/api/hotlist-jev/rise-review?date=2026-09-05")
    assert resp.status_code == 502
    assert "mongo down" in resp.json()["reason"]
