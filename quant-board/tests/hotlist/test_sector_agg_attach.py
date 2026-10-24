# -*- coding: utf-8 -*-
"""V2 影子聚合 operations 层挂载测试（_agg_attach / settle_day 集成形状）。

零 DB：day_leader_rows / trading_dates_before / _daily_bars 全 monkeypatch
（预登记 sector-nodes-v2-aggregate §四；判据零参与）。
"""
from __future__ import annotations

import pytest

from backend.operations import sector_nodes as ops

D0, D1, D2, D3, D4 = ("2026-10-23", "2026-10-22", "2026-10-21",
                      "2026-10-20", "2026-10-19")


def _lrow(board: str, codes: list[str]) -> dict:
    return {"date": D0, "board": board, "code": codes[0] if codes else None,
            "boardN": len(codes), "boardCodes": codes}


def _patch(monkeypatch, pools: dict[str, dict | None],
           dates: list[str], bars: dict[str, list[dict]]):
    def fake_dlr(db, date, dataset_id=ops.DEFAULT_DATASET_ID, prev_date=None):
        if date not in pools:
            return None, {}
        if pools[date] is None:
            return None, {}
        rows = [_lrow(b, sorted(c)) for b, c in pools[date].items()]
        return rows, {"jiuyanFinalFound": True}

    monkeypatch.setattr(ops, "day_leader_rows", fake_dlr)
    monkeypatch.setattr(ops, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: dates[:n])
    monkeypatch.setattr(ops, "_daily_bars", lambda code: bars.get(code, []))
    monkeypatch.setattr(ops, "_POOL_CACHE", {})


def test_agg_attach_mount_and_extra(monkeypatch):
    """v1 行内板块挂 aggN10；N10 独有板块进额外行；池缺失日不进窗口。"""
    pools = {
        D0: {"AI算力": {"600001"}, "机器人": {"700001"}},
        D1: {"AI算力": {"600001", "600002"}},
        D2: None,                      # THS 池缺失 → 不进窗口（fail-visible）
        D3: {"AI算力": {"600003"}},
        D4: {"光伏": {"800001"}},      # 仅在 4 日前 → N10 独有板块
    }
    bars = {
        "600001": [{"date": D1, "close": 10.0}, {"date": D0, "close": 10.5}],
        "700001": [{"date": D1, "close": 6.0}, {"date": D0, "close": 6.3}],
        "800001": [{"date": D4, "close": 4.0}, {"date": D0, "close": 4.0}],
    }
    _patch(monkeypatch, pools, [D1, D2, D3, D4], bars)
    v1_rows = [{"board": "AI算力", "node": "wzs"}, {"board": "机器人", "node": "brewing"}]
    mounted, extra = ops._agg_attach(None, D0, "ds", v1_rows)
    assert set(mounted) == {"AI算力", "机器人"}
    assert mounted["AI算力"]["aggN10"]["pctMean"] == 5.0
    assert mounted["AI算力"]["aggN10"]["windowDays"] == 4   # D0,D1,D3,D4（D2 池缺失剔除）
    assert [e["board"] for e in extra] == ["光伏"]
    assert extra[0]["aggN10"]["pctMean"] == 0.0


def test_agg_attach_no_pool(monkeypatch):
    """全窗口池缺失 → 空挂载空额外行（不伪 0）。"""
    _patch(monkeypatch, {D0: None, D1: None}, [D1], {})
    mounted, extra = ops._agg_attach(None, D0, "ds", [{"board": "AI算力"}])
    assert mounted == {} and extra == []


def test_settle_day_doc_carries_agg(monkeypatch):
    """settle_day 文档形状：rows 挂 agg、aggExtraRows/meta.aggVersion 在场。"""
    pools = {D0: {"AI算力": {"600001"}}, D1: {"AI算力": {"600001"}},
             D2: {"AI算力": {"600001"}}}
    bars = {"600001": [{"date": D2, "close": 10.0}, {"date": D1, "close": 10.0},
                       {"date": D0, "close": 10.2}]}
    _patch(monkeypatch, pools, [D1, D2], bars)

    class _Coll:
        def replace_one(self, q, doc, upsert=False):
            _Coll.saved = doc
    db = {ops.COLLECTION: _Coll()}
    # 其余依赖最小桩：晋级链不可算（影子聚合不受影响）、龙头状态停牌外全 sealed
    monkeypatch.setattr(ops, "_promotion_by_board",
                        lambda db, prev_date, date, ds: {"ok": False, "reason": "无昨日"})
    monkeypatch.setattr(ops, "_leader_states", lambda db, d, pr, ds: {})
    monkeypatch.setattr(ops, "board_count_history", lambda db, d, days, dataset_id=None: {})
    monkeypatch.setattr(ops, "_prev_nodes_of", lambda db, d: None)
    monkeypatch.setattr(ops, "assemble_rows", lambda **kw: {
        "rows": [{"board": "AI算力", "node": "normal", "basis": [], "notes": []}],
        "degraded": []})
    out = ops.settle_day(db, D0, "ds")
    doc = _Coll.saved
    assert doc["meta"]["aggVersion"] == "2026-10-24b"
    r = doc["rows"][0]
    assert r["aggN10"]["memberN"] == 1 and r["aggN10"]["pctMean"] == 2.0
    assert doc["aggExtraRows"] == []
    assert out["boards"] == 1
