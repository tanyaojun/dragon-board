# -*- coding: utf-8 -*-
"""15:00 帧 indices 七指数历史回填测试（2026-10-21，情绪指数重放前补采）。

全 fake/monkeypatch，禁网禁真实 jev（AGENTS §1.2-7）。锁定项：
1. 原生 changePct 幂等跳过（永不覆盖帧采值）；
2. 原 entry 只有 change 点位 → 保留点位、补 changePct+src；
3. entry/indexExtra 缺失 → 创建带 src 的回填 entry；
4. 本地日线缺当日棒 → 线上兜底；双源全缺 → fail-visible 不补 0；
5. relay 大盘行对回填值显示「（日线回填）」，原生帧值无标注。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import backfill_frame_indices as bf
from backend.operations.jev_relay_index import market_index_line

DATE = "2026-10-19"
SRC = "tdx_daily_backfill"


class _Cursor(list):
    def sort(self, *a, **k):
        return self


class _FrameCol:
    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.bulk: list = []

    def find(self, q=None, projection=None):
        return _Cursor(self.docs)

    def find_one(self, q, projection=None, sort=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in (q or {}).items()):
                return dict(d)
        return None

    def bulk_write(self, ops, ordered=False):
        self.bulk.extend(ops)


class _Db:
    def __init__(self, cols=None):
        self.cols = cols or {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, _FrameCol())


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr("backend.operations.market_dieban_tdx.resolve_root",
                        lambda *a, **k: ("D:/FAKE_TDX", DATE))
    monkeypatch.setattr(bf, "_daily_rows_online", lambda client, code: [])
    yield


def _series():
    return {(m, c): [("2026-10-18", 100.0), (DATE, 101.0)]
            for _, m, c in bf.INDEX_SLOTS}


def _frame(idx):
    return {"_id": f"x:{DATE}", "type": "half_hour", "slotTime": "15:00",
            "tradingDate": DATE, "indices": idx}


# ── backfill_frame 计划逻辑 ────────────────────────────────────────────────
def test_native_pct_skipped():
    ups, miss = bf.backfill_frame(_frame({"sh": {"changePct": 0.5}}), _series(), None)
    assert "sh" not in ups and not miss


def test_change_only_preserves_change_and_adds_pct():
    ups, miss = bf.backfill_frame(_frame({"sh": {"change": 1.0}}), _series(), None)
    assert ups["sh"] == {"change": 1.0, "changePct": 1.0, "src": SRC}
    assert not miss


def test_absent_entry_created():
    ups, miss = bf.backfill_frame(_frame({}), _series(), None)
    assert ups["sh"] == {"changePct": 1.0, "src": SRC}
    assert ups["indexExtra.szcz"]["src"] == SRC
    assert set(ups) == {p for p, _, _ in bf.INDEX_SLOTS} and not miss


def test_uncomputable_fail_visible_no_zero_fill():
    sparse = {(m, c): [] for _, m, c in bf.INDEX_SLOTS}
    ups, miss = bf.backfill_frame(_frame({}), sparse, None)
    assert ups == {} and len(miss) == len(bf.INDEX_SLOTS)
    assert all("fail-visible" in m for m in miss)


def test_online_fallback_when_local_lacks_date(monkeypatch):
    def fake_online(client, code):
        return [("2026-10-17", 100.0), ("2026-10-18", 3000.0), (DATE, 3030.0)]
    monkeypatch.setattr(bf, "_daily_rows_online", fake_online)
    sparse = {(m, c): ([("2026-10-18", 3000.0)] if (m, c) == ("sh", "000300") else [])
              for _, m, c in bf.INDEX_SLOTS}
    ups, miss = bf.backfill_frame(_frame({"hs300": {}}), sparse, None)
    assert ups["hs300"]["changePct"] == pytest.approx(1.0)
    assert not any(m.startswith("hs300") for m in miss)


def test_local_rows_read_lday(monkeypatch):
    recs = [(20261018, 0, 0, 0, 10000.0, 0, 0, 0), (20261019, 0, 0, 0, 10100.0, 0, 0, 0)]
    monkeypatch.setattr("backend.operations.market_dieban_tdx.read_lday",
                        lambda path, take=400: recs)
    rows = bf._daily_rows_local("D:/FAKE_TDX", "sh", "000001")
    assert rows == [("2026-10-18", 100.0), (DATE, 101.0)]


# ── main 写库路径（fake db，幂等 + --apply 门）─────────────────────────────
def test_main_apply_writes_and_idempotent(monkeypatch, capsys):
    db = _Db({"snapshot_frames": _FrameCol([_frame({"sh": {"change": 1.0}, "hs300": {"changePct": 9.9}})])})
    monkeypatch.setattr("backend.data.repositories.repository_factory.get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr("backend.operations.jev_label_jiuyan._tdx_daily_client", lambda: None)
    monkeypatch.setattr(bf, "INDEX_SLOTS", [("sh", "sh", "000001"), ("hs300", "sh", "000300")])
    monkeypatch.setattr(bf, "_daily_rows_local", lambda root, mkt, code: _series()[(mkt, code)])
    sys.argv = ["x", "--apply"]
    bf.main()
    ops = db["snapshot_frames"].bulk
    assert len(ops) == 1 and ops[0]._doc["$set"]["indices.sh"]["src"] == SRC
    # 幂等：原生 pct 的 hs300 不动；再跑一次无新写
    db["snapshot_frames"].bulk.clear()
    db["snapshot_frames"].docs = [{"_id": f"x:{DATE}", "type": "half_hour", "slotTime": "15:00",
                                   "tradingDate": DATE,
                                   "indices": {"sh": {"change": 1.0, "changePct": 1.0, "src": SRC},
                                               "hs300": {"changePct": 9.9}}}]
    bf.main()
    assert db["snapshot_frames"].bulk == []


# ── relay 大盘行口径标注 ───────────────────────────────────────────────────
def _relay_frame(idx):
    f = _frame(idx)
    f["datasetId"] = "dragonboard_live"
    return f


def test_relay_line_labels_backfill_not_native():
    idx = {"sh": {"changePct": 0.5}, "hs300": {"changePct": -0.3, "src": SRC},
           "indexExtra": {"szcz": {"changePct": 0.2, "src": SRC}}}
    db = _Db({"snapshot_frames": _FrameCol([_relay_frame(idx)])})
    line = market_index_line(db, DATE)
    assert "上证 +0.50%" in line and "沪深300 -0.30%" in line, "2026-10-30g+：来源注删"
    assert "深证成指 +0.20%" in line, "2026-10-30g+：来源注删"
    assert "该日未采集" not in line  # indexExtra 已存在（含回填）→ 注消失


def test_relay_line_native_only_no_label():
    idx = {"sh": {"changePct": 0.5}, "hs300": {"change": -12.0},
           "indexExtra": {}}
    db = _Db({"snapshot_frames": _FrameCol([_relay_frame(idx)])})
    line = market_index_line(db, DATE)
    assert "上证 +0.50%" in line
    assert "沪深300 -12.00点" in line, "2026-10-30g+：口径注删"
    assert "（日线回填）" not in line and "该日未采集" in line
