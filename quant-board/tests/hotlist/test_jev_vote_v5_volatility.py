# -*- coding: utf-8 -*-
"""方向题集 v4-material 内核测试（jevVoteRecheck vote 部分代际覆盖，2026-10-13 用户裁决）。

全 fake 零 IO，禁触真实 jev 调用与网络（AGENTS.md §1.2-7）。
覆盖：判据 v4 锚冻结（预登记 §五逐字）/版本戳/八块组装形状与黑名单零出现/全池人口/
存档 VOTE 兼容合同（_id 幂等+requestJson 世代字段+responseRaw envelope）/熔断/幂等 done-skip。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_vote_confirm as runner
from backend.analysis.hotlist import market_facts as mf
from backend.analysis.hotlist.jev_vote_ammo import (
    QUESTION_SET_VERSION_LIFECYCLE_RECHECK,
    QUESTION_SET_VERSION_VOTE_CONFIRM,
    QUESTIONS_VOTE_CONFIRM,
    VOTE_AMMO_VERSION,
)

DATE = "2026-09-23"


# ── 判据 v4 锚冻结（预登记 §五逐字；改动=改门须用户点头）──

def test_vote_criteria_v4_anchors():
    q = QUESTIONS_VOTE_CONFIRM["direction"]
    assert q["type"] == "choice"
    ins = q["instructions"]
    assert "历史深度 ≥5 个交易日才可作主证据" in ins          # 序列深度锚
    assert "绝不引用未展示的历史" in ins                        # 铁律 3
    assert "一字板（首封=末封=09:25 且封单大）是真实但不可交易信号，永不作为 buy 证据" in ins
    assert "双门 AND" in ins and "仅 strong 带" in ins          # 双门 Gate1+Gate2
    assert "拥挤/反转位禁 buy" in ins
    assert "11:00 时点" in ins                                  # 计分口径判读时点
    assert set(q["criteria"]) == {"buy", "sell", "hold", "insufficient"}
    assert "永不因证据冲突" in q["criteria"]["insufficient"]


def test_version_stamps_v4_generation():
    assert QUESTION_SET_VERSION_VOTE_CONFIRM == "v4-material"
    assert VOTE_AMMO_VERSION == "2026-10-13a"
    assert QUESTION_SET_VERSION_LIFECYCLE_RECHECK == "v1"       # LC 戳独立不受代际影响


# ── 八块组装（mock db + TDX 壳）──

class FakeCursor(list):
    def sort(self, *a, **k):
        return self


class _FramesCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q, projection=None, sort=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None

    def find(self, q, projection=None):
        dates = sorted({d["tradingDate"] for d in self.docs if d.get("tradingDate")})
        return FakeCursor({"tradingDate": d} for d in dates)


class _RowsCol:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q, projection=None, sort=None):
        for d in self.docs:
            if all(d.get(k) == v for k, v in q.items()):
                return d
        return None

    def find(self, q, projection=None):
        return FakeCursor(d for d in self.docs
                          if all(d.get(k) == v for k, v in q.items()))

    def count_documents(self, q):
        return 200

    def distinct(self, field, q=None):
        return []


class _SimpleCol:
    def __init__(self, docs=None):
        self.docs = list(docs or [])

    def find_one(self, q, projection=None, sort=None):
        for d in self.docs:
            if all(str(d.get(k)) == str(v) for k, v in q.items() if k in d):
                return d
        return None

    def find(self, q, projection=None):
        return FakeCursor(d for d in self.docs
                          if all(str(d.get(k)) == str(v) for k, v in q.items() if k in d))

    def replace_one(self, q, doc, upsert=False):
        self.docs = [d for d in self.docs if d.get("_id") != q.get("_id")] + [doc]

    def find(self, q, projection=None):
        return FakeCursor(d for d in self.docs
                          if all(d.get(k) == v for k, v in q.items()))


class V4Db:
    def __init__(self):
        d11, d15 = "half_hour:%s:11:00" % DATE, "half_hour:%s:15:00" % DATE
        self.snapshot_frames = _FramesCol([
            {"_id": d11, "datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": DATE, "slotTime": "11:00", "snapshotId": d11,
             "limitSummary": {"zhaban": {"ztCount": 37, "count": 20, "rate": 35.1},
                              "drawdown": {"count": 11},
                              "continuousBoards": {"maxBoard": 10},
                              "thsPools": {"pools": {"failed": {"total": 20},
                                                     "drawdown": {"total": 11},
                                                     "rushing": {"total": 11}}},
                              "sealQuality": {"byzCount": 17, "hardCount": 12,
                                              "rottenCount": 8, "rottenShare": 0.22,
                                              "avgSucRate": 0.75}},
             "marketStats": {"upCount": 0, "downCount": 0, "flatCount": 0}},
            {"_id": d15, "datasetId": "dragonboard_live", "type": "half_hour",
             "tradingDate": DATE, "slotTime": "15:00", "snapshotId": d15,
             "limitSummary": {"zhaban": {"ztCount": 46, "count": 25, "rate": 35.1},
                              "drawdown": {"count": 18},
                              "continuousBoards": {"maxBoard": 10}},
             "marketStats": {"upCount": 106, "downCount": 145, "flatCount": 30}},
        ])
        self.snapshot_stock_rows = _RowsCol([
            {"datasetId": "dragonboard_live", "snapshotId": d11, "code": "600001",
             "name": "测试一", "rank": 3, "change": 5.2, "volumeRatio": 1.8,
             "zlje": 8e7, "zljzb": 12.0, "turnoverRate": 9.1,
             "sectorLabel": "低空经济", "mainTheme": "低空经济",
             "themes": ["低空经济", "军工"], "firstZtTime": None, "fengdan": None,
             "volumeRatioMeta": {"status": "available"}},
        ])
        self.snapshot_analysis = _SimpleCol()
        self.hotlist_sentiment = _SimpleCol([
            {"datasetId": "dragonboard_live", "snapshotType": "half_hour",
             "tradingDate": DATE, "slotTime": "11:00",
             "emotionScore": {"score": 61.7}, "stage": "发酵"}])
        self.hotlist_jev_vote_confirm_pilot = _SimpleCol()

    def __getitem__(self, name):
        return getattr(self, name)

    def list_collection_names(self):
        return []


def _ctx_override(monkeypatch):
    """固定 ctx：绕开 setup_day 的多日历史依赖，八块组装只走当日帧。"""
    db = V4Db()
    real_setup = runner.setup_day

    def setup_min(db_, d, dataset_id=runner.DEFAULT_DATASET_ID):
        ctx = real_setup(db_, d, dataset_id)
        ctx["series_days"] = []            # 简化：序列仅判读点（FIRST-SEEN 路径）
        ctx["prev10"], ctx["prev3"] = [], []
        return ctx

    monkeypatch.setattr(runner, "setup_day", setup_min)
    monkeypatch.setattr("backend.operations.jev_label_jiuyan._daily_bars", lambda code: [])
    return db


def test_build_state_v4_blocks_and_blacklist(monkeypatch):
    db = _ctx_override(monkeypatch)
    ctx = runner.setup_day(db, DATE)
    codes, stats = runner.build_population(db, DATE, ctx)
    assert codes == ["600001"] and stats["full_pool"] == 1   # 全池：不排除
    head, blocks, meta = runner.build_state_v4(db, "600001", DATE, ctx)
    assert set(blocks) == {"series", "position", "vp", "market", "themes", "quality", "gate"}
    narrative = "\n".join([head, *[ln for b in blocks.values() for ln in b]])
    bad = [w for w in runner.BLACKLIST_FIELDS if w in narrative]
    assert bad == [], f"黑名单泄漏: {bad}"
    assert meta["seenDays"] == 1 and meta["firstSeen"] is True
    assert "FIRST-SEEN" in "\n".join(blocks["series"])
    # 市场块时点口径：11:00 帧（涨停 37）非 15:00（46）；0 值涨跌家数判缺失
    assert "limit-up count: 37" in narrative
    assert "missing/missing/missing" in narrative


def test_frame_facts_zero_breadth_missing():
    db = V4Db()
    m11 = mf.frame_market_facts(db, DATE, "11:00")
    m15 = mf.frame_market_facts(db, DATE, "15:00")
    assert m11["ztCount"] == 37 and m15["ztCount"] == 46     # 时点参数生效
    assert m11["upCount"] is None and m15["upCount"] == 106  # 全 0 判缺失（0 伪装缺失）


def test_fold_attention_series_jump_and_falling():
    pts = [{"d": f"2026-09-{18 + i}", "slot": "15:00", "rank": 1, "pct": p, "chg": 0.0}
           for i, p in enumerate([50, 55, 60, 30, 35])]
    r = mf.fold_attention_series(pts, [f"2026-09-{18 + i}" for i in range(4)],
                                 "2026-09-22", 35.0)
    assert r["directions"] == [1, 1, -1, 1]
    assert r["jumpIdxs"] == [3]          # 60→30 反向跳变标在 30 当日
    assert r["consecutiveFalling"] == 0


# ── 开火层合同（全 mock）──

def _fire_db(monkeypatch, resp=None):
    db = _ctx_override(monkeypatch)
    ctx = runner.setup_day(db, DATE)
    monkeypatch.setattr(runner, "setup_day", lambda db_, d, dataset_id=runner.DEFAULT_DATASET_ID: ctx)
    envelope = resp or {"result": {"state": "Completed", "result": {
        "answers": {"direction": {"type": "choice", "choice": "hold", "confidence": 0.66}},
        "model": "m", "usage": {"input_tokens": 10, "output_tokens": 5}}}}
    calls = []

    def fake_dispatch(state, questions):
        calls.append(state)
        return envelope, 1

    monkeypatch.setattr(runner, "_dispatch_jev", fake_dispatch)
    return db, calls, envelope


def test_run_vote_v4_fire_persist_contract(monkeypatch):
    db, calls, envelope = _fire_db(monkeypatch)
    stats = runner.run_vote_day(db, [DATE], fire=True)
    assert stats["ok"] == 1 and stats["no_frame"] == 0 and len(calls) == 1
    doc = db.hotlist_jev_vote_confirm_pilot.docs[0]
    assert doc["_id"] == f"{DATE}:11:00:600001:VOTE"        # 幂等键：判读时点 11:00
    assert doc["voteDirection"] == "hold" and doc["voteConfidence"] == 0.66
    assert doc["questionSetVersion"] == "v4-material"
    assert doc["questionSetHash"] == runner._questions_hash(QUESTIONS_VOTE_CONFIRM)
    assert doc["narrative"] and doc["responseRaw"] == envelope
    assert doc["answers"]["direction"]["choice"] == "hold"  # answers 原样包
    assert doc["seenDays"] == 1 and doc["firstSeen"] is True
    assert doc["slotTime"] == "11:00"


def test_run_vote_v4_dry_run_zero_call(monkeypatch):
    db, calls, _ = _fire_db(monkeypatch)
    stats = runner.run_vote_day(db, [DATE], fire=False)
    assert calls == [] and stats["ok"] == 0


def test_run_vote_v4_fuse_blocks(monkeypatch):
    db, calls, _ = _fire_db(monkeypatch)
    stats = runner.run_vote_day(db, [DATE], fire=True, token_fuse=0)
    assert calls == []                                      # 熔断：0 预算即停


def test_run_vote_v4_done_skip(monkeypatch):
    db, calls, _ = _fire_db(monkeypatch)
    db.hotlist_jev_vote_confirm_pilot.docs.append(
        {"_id": f"{DATE}:11:00:600001:VOTE", "status": "ok"})
    stats = runner.run_vote_day(db, [DATE], fire=True)
    assert stats["skip"] == 1 and calls == []               # done-skip 幂等零重复计费
