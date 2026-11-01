# -*- coding: utf-8 -*-
"""V2d 条款 2：池外晋级归属（_promotion_by_board 分流）测试。

零 DB：_promotion_stats / jiuyan_streak_map 全 monkeypatch（预登记
sector-nodes-v2d-preregistration 条款 2；影子列不进判据）。
"""
from __future__ import annotations

import pytest

from backend.operations import sector_nodes as ops


def _patch(monkeypatch, *, promoted, prev_pool, cur_pool, streaks):
    monkeypatch.setattr(ops, "_promotion_stats",
                        lambda db, prev_date, date, ds: {
                            "ok": True, "promoted": promoted,
                            "prev_pool": prev_pool, "cur_pool": cur_pool})
    monkeypatch.setattr(ops, "jiuyan_streak_map", lambda db, date, ds: streaks)


def test_in_pool_attribution_unchanged(monkeypatch):
    """in-pool 口径逐字不变：昨日 pool 首板块归属 + ge2 连板计数。"""
    _patch(monkeypatch, promoted=["600001", "600002"],
           prev_pool={"600001": {"board": "AI算力"}, "600002": {"board": "AI算力"}},
           cur_pool={"600001": {"board": "AI算力"}},
           streaks={"600001": 2, "600002": 1})
    out = ops._promotion_by_board(None, "2026-10-22", "2026-10-23", "ds")
    assert out["ok"] is True
    assert out["byBoard"] == {"AI算力": 2}
    assert out["ge2ByBoard"] == {"AI算力": 1}
    assert out["outByBoard"] == {} and out["unattributed"] == []


def test_out_of_pool_attributed_and_merged_into_prom(monkeypatch):
    """池外晋级按今日 pool 首板块归属；V4 条款 1 起合并进 byBoard（进判据）。"""
    _patch(monkeypatch, promoted=["600001", "700001"],
           prev_pool={"600001": {"board": "AI算力"}},          # 700001 不在昨日 pool
           cur_pool={"700001": {"board": "机器人"}},
           streaks={"600001": 1, "700001": 2})
    out = ops._promotion_by_board(None, "2026-10-22", "2026-10-23", "ds")
    assert out["byBoard"] == {"AI算力": 1, "机器人": 1}        # 合并口径（判据消费）
    assert out["ge2ByBoard"] == {"机器人": 1}                  # 合并口径（判据消费）
    assert out["outByBoard"] == {"机器人": 1}                  # 拆分披露（in-pool 子集口径）
    assert out["outGe2ByBoard"] == {"机器人": 1}
    assert out["unattributed"] == []


def test_double_out_of_pool_goes_unattributed(monkeypatch):
    """昨日池与今日池都无归属 → unattributed 名单披露（fail-visible，不硬塞板块）。"""
    _patch(monkeypatch, promoted=["800001"],
           prev_pool={}, cur_pool={}, streaks={})
    out = ops._promotion_by_board(None, "2026-10-22", "2026-10-23", "ds")
    assert out["outByBoard"] == {} and out["unattributed"] == ["800001"]


def test_prev_pool_board_empty_falls_unattributed(monkeypatch):
    """昨日 pool 有键但 board 为空（脏数据）→ 不进 in-pool 计数，走未归属披露。"""
    _patch(monkeypatch, promoted=["600001"],
           prev_pool={"600001": {"board": ""}}, cur_pool={}, streaks={})
    out = ops._promotion_by_board(None, "2026-10-22", "2026-10-23", "ds")
    assert out["byBoard"] == {} and out["unattributed"] == ["600001"]


def test_prom_chain_not_ok_shape(monkeypatch):
    """晋级链不可算 → 影子键齐备（outByBoard/outGe2ByBoard/unattributed 空表）。"""
    monkeypatch.setattr(ops, "_promotion_stats",
                        lambda db, prev_date, date, ds: {"ok": False, "reason": "昨日 final 缺失"})
    out = ops._promotion_by_board(None, "2026-10-22", "2026-10-23", "ds")
    assert out["ok"] is False
    assert out["outByBoard"] == {} and out["outGe2ByBoard"] == {} and out["unattributed"] == []


def test_no_prev_date_shape(monkeypatch):
    assert ops._promotion_by_board(None, None, "2026-10-23", "ds")["outByBoard"] == {}


def test_settle_meta_total_includes_unattributed(monkeypatch):
    """review P3-4：promOutOfPoolTotal = 板块归属 + 未归属（unattributed 也是池外晋级）。"""
    from backend.operations import sector_nodes as ops2

    monkeypatch.setattr(ops2, "_promotion_by_board",
                        lambda db, prev_date, date, ds: {
                            "ok": True, "byBoard": {"AI算力": 1}, "ge2ByBoard": {},
                            "outByBoard": {"AI算力": 2}, "outGe2ByBoard": {},
                            "unattributed": ["800001", "800002"]})
    monkeypatch.setattr(ops2, "_leader_states", lambda db, d, pr, ds: {})
    monkeypatch.setattr(ops2, "board_count_history", lambda db, d, days, dataset_id=None: {})
    monkeypatch.setattr(ops2, "_member_ratio_history", lambda db, d, days=21, dataset_id=None: {})
    monkeypatch.setattr(ops2, "_prev_nodes_of", lambda db, d: None)
    monkeypatch.setattr(ops2, "_agg_rows_compute", lambda db, d, ds: [])
    monkeypatch.setattr(ops2, "_static_rows_compute", lambda db, d, boards: {})
    monkeypatch.setattr(ops2, "day_leader_rows", lambda db, date, dataset_id=None, prev_date=None: (None, {}))
    monkeypatch.setattr(ops2, "trading_dates_before", lambda db, date, n, dataset_id=None: [])

    class _Coll:
        def replace_one(self, q, doc, upsert=False):
            _Coll.saved = doc
    db = {ops2.COLLECTION: _Coll()}
    ops2.settle_day(db, "2026-10-23", "ds")
    meta = _Coll.saved["meta"]
    assert meta["promOutOfPoolTotal"] == 4        # 2 归属 + 2 未归属
    assert meta["promOutOfPoolUnattributed"] == ["800001", "800002"]
