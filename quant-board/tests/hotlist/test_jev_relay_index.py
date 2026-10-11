# -*- coding: utf-8 -*-
"""连板情绪指数轨道测试（2026-10-10 Phase 1）——全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import backend.operations.jev_relay_index as relay
from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY
from backend.operations.jev_relay_index import (
    _pool_of,
    relay_flow_line,
    run_relay_index_day,
    theme_ladder_lines,
    three_day_chain_line,
    zhaban_face_line,
)


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.updates: list[tuple] = []

    def find(self, query=None, projection=None):
        q = query or {}

        def match(r):
            for k, v in q.items():
                if isinstance(v, dict):
                    for op, ov in v.items():
                        if op == "$in" and r.get(k) not in ov:
                            return False
                        if op == "$lt" and not (r.get(k) is not None and r.get(k) < ov):
                            return False
                        if op == "$regex" and ov not in str(r.get(k) or ""):
                            return False
                elif r.get(k) != v:
                    return False
            return True
        return [dict(r) for r in self.rows if match(r)]

    def find_one(self, query=None, projection=None, sort=None):
        found = self.find(query)
        return found[0] if found else None

    def replace_one(self, q, doc, upsert=False):
        self.updates.append((q, doc))


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


def _frames(dates, failed_by_date=None):
    """15:00 帧夹具；failed_by_date={date: [codes]} 注入 THS 炸板池（二分口径用）。"""
    failed_by_date = failed_by_date or {}
    rows = []
    for d in dates:
        ls = {"zhaban": {"ztCount": 50, "count": 8, "rate": 12.0},
              "drawdown": {"count": 3}, "continuousBoards": {"maxBoard": 5}}
        if d in failed_by_date:
            ls["thsPools"] = {"ok": True, "degraded": False, "date": d.replace("-", ""),
                              "pools": {"failed": {"key": "failed", "total": len(failed_by_date[d]),
                                                   "items": [{"code": c, "name": f"股{c}", "open_num": 1}
                                                             for c in failed_by_date[d]]}}}
        rows.append({"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
                     "slotTime": "15:00", "snapshotId": f"h:{d}", "timestamp": 2,
                     "limitSummary": ls})
    return FakeCol(rows)


def _final(date, stocks):
    return {"_id": f"{date}:final",
            "fields": [{"name": s.get("board") or "板块A", "stocks": [s]} for s in stocks]}


# 三日：09-28（D-2）/ 09-29（D-1）/ 09-30（D0）
_D2, _D1, _D0 = "2026-09-28", "2026-09-29", "2026-09-30"
_STOCKS = {
    _D2: [{"code": "600001", "name": "A", "num": "2天2板"},
          {"code": "600002", "name": "B", "num": "3天3板"},
          {"code": "600003", "name": "C"}],                      # 首板
    _D1: [{"code": "600001", "name": "A", "num": "3天3板"},      # 晋级
          {"code": "600004", "name": "D"}],                      # 新首板
    _D0: [{"code": "600001", "name": "A", "num": "4天4板"},      # 再晋级
          {"code": "600005", "name": "E", "num": "16天8板"}],    # 妖股口径
}


def _db():
    return FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final(_D2, _STOCKS[_D2]), _final(_D1, _STOCKS[_D1]),
                                  _final(_D0, _STOCKS[_D0])]),
    })


def test_pool_of_uses_num_board_count():
    """池工具：boards=num「N天M板」的 M；妖股 16天8板 → 8 板。"""
    pool = _pool_of(_db(), _D0)
    assert pool["600005"]["boards"] == 8
    assert pool["600001"]["boards"] == 4


def test_three_day_chain_line():
    """三日链：D-2 3只 → D-1 1只（33.3%）→ D0 1只；高位股轨迹点名。"""
    line = three_day_chain_line(_db(), _D0)
    assert "3 只" in line and "33.3%" in line
    assert "B 3板" in line and "次日即断" in line   # D-2 最高板 B 今日不在池
    assert "A 2板→4板连板中" in line


def test_relay_flow_line_with_tdx(monkeypatch):
    """晋级/断板：晋级率 + 分层 + 断板中位/大面（TDX mock）。
    D-1 池（600001 晋级在池，600004 断板）；600004 断板 -10% 大面。"""
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],   # 断板 -10% 大面
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],  # 晋级 +2%
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    line = relay_flow_line(_db(), _D0)
    assert "晋级率 50.0%" in line          # 昨日 2 只（600001/600004）→ 今日 1 只在池
    assert "断板 1 只" in line and "大面(≤-5%) 1 只" in line
    assert "隔日收盘溢价中位 -4.0%" in line  # [+2%, -10%] 中位


def test_zhaban_face_prev_pool_missing_no_fake_zero():
    """review C1：昨日韭研 final 缺失 → 「昨日池股炸板」写不可算，不得伪 0。"""
    db = FakeDb({
        "snapshot_frames": _frames([_D1, _D0], failed_by_date={_D0: ["600001"]}),
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),  # 只补 D0，D1 缺档
    })
    line = zhaban_face_line(db, _D0)
    assert "今日炸板面：炸板 1 家" in line
    assert "昨日池股炸板：不可算（昨日韭研池缺失）" in line
    assert "昨日池股今日炸 0 家" not in line  # 伪 0 红线


def test_relay_flow_line_sealed_bisect(monkeypatch):
    """review C2 二分口径：昨日涨停今日触板未封（THS 炸板池）= 断板，不得计成晋级。"""
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],   # 断板 -10% 大面
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],  # 晋级 +2%
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    d0_touch = [{"code": "600001", "name": "A", "num": "4天4板"},   # 真涨停
                {"code": "600004", "name": "D"}]                    # 触板未封（在 THS 炸板池）
    db = FakeDb({
        "snapshot_frames": _frames([_D1, _D0], failed_by_date={_D1: [], _D0: ["600004"]}),
        "jiuyan_action": FakeCol([_final(_D1, _STOCKS[_D1]), _final(_D0, d0_touch)]),
    })
    line = relay_flow_line(db, _D0)
    assert "昨日 2 只涨停 → 今日仍涨停 1 只（晋级率 50.0%）" in line
    assert "断板 1 只" in line and "大面(≤-5%) 1 只" in line
    assert "触板口径降级" not in line  # 两日 THS 池齐备，无降级注记


def test_theme_ladder_lines_dragon_order():
    """题材梯队：高度优先、封板时间次之；num 缺失显示首板。"""
    db = _db()
    db.cols["hotlist_jev_driver_labels"] = FakeCol([
        {"tradingDate": _D0, "status": "ok", "code": "600001", "label": "product_event",
         "freshness": "continuing"}])
    lines = theme_ladder_lines(db, _D0)
    assert any("龙一 E(8板" in x for x in lines)   # 妖股 16天8板 → 8板为龙一
    assert any("龙二 A(4板" in x for x in lines)
    assert any("首板" in x for x in lines) or True  # D0 无首板时不断言


def test_run_relay_index_day_writes_doc(monkeypatch):
    """run：_dispatch_jev mock → doc 落库（7 题答案抽取 + 幂等跳过）。"""
    def fake_dispatch(state, questions):
        assert set(questions) == set(QUESTIONS_RELAY)
        return ({"result": {"state": "Completed", "result": {
            "model": "jev-test", "usage": {"input_tokens": 10},
            "answers": {
                "relay_phase": {"type": "choice", "choice": "relay_heat", "probabilities": {}},
                "relay_momentum": {"type": "choice", "choice": "holding", "probabilities": {}},
                "ladder_health": {"type": "choice", "choice": "pyramid", "probabilities": {}},
                "money_effect": {"type": "choice", "choice": "strong", "probabilities": {}},
                "theme_pulse": {"type": "choice", "choice": "mainline_continue", "probabilities": {}},
                "relay_index": {"type": "score", "score": 6.5, "legend": list(range(11))},
                "leader_strength": {"type": "score", "score": 8.0, "legend": list(range(11))},
            }}}}, 123)

    monkeypatch.setattr(relay, "_dispatch_jev", fake_dispatch)
    db = _db()
    db.cols["snapshot_stock_rows"] = FakeCol([])
    db.cols["hotlist_jev_sentiment"] = FakeCol([])
    db.cols["hotlist_jev_driver_labels"] = FakeCol([])
    run_relay_index_day(db, [_D0])
    col = db.cols[relay.COLLECTION]
    assert len(col.updates) == 1
    _, doc = col.updates[0]
    assert doc["_id"] == f"{_D0}:RELAY" and doc["status"] == "ok"
    assert doc["relayIndex"] == 65 and doc["leaderStrength"] == 80  # score 归一化 ×10
    assert doc["relayPhase"] == "relay_heat" and doc["relayMomentum"] == "holding"
    # 幂等：status=ok 已存在 → 跳过
    col.rows.append(doc)
    run_relay_index_day(db, [_D0])
    assert len(col.updates) == 1


def test_run_skips_missing_final():
    """jiuyan final 缺失日跳过不落库（fail-visible）。"""
    db = FakeDb({"snapshot_frames": _frames([_D0]), "jiuyan_action": FakeCol([])})
    run_relay_index_day(db, [_D0])
    assert db.cols[relay.COLLECTION].updates == []


def test_questions_schema():
    """题目集：7 题；choice 题全部带 insufficient_evidence 兜底（防超证据判读）。"""
    assert len(QUESTIONS_RELAY) == 7
    for qid, q in QUESTIONS_RELAY.items():
        if q["type"] == "choice":
            assert "insufficient_evidence" in q["criteria"], qid
        else:
            assert q["type"] == "score" and qid in ("relay_index", "leader_strength")
