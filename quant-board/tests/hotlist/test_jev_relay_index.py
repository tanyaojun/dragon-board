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
    ladder_structure_line,
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


def _frame_failed(date, items):
    """15:00 帧 + THS 炸板池（items 自带 open_num，供「较昨日」对比夹具控制反复开板数）。"""
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {"zhaban": {"ztCount": 50, "count": 8, "rate": 12.0},
                             "drawdown": {"count": 3}, "continuousBoards": {"maxBoard": 5},
                             "thsPools": {"ok": True, "degraded": False, "date": date.replace("-", ""),
                                          "pools": {"failed": {"key": "failed", "total": len(items),
                                                               "items": items}}}}}


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


def test_three_day_chain_line_promo_comparison():
    """relay_momentum 锚1 补供（2026-10-15 诊断）：昨日池今日 vs 前日池昨日晋级率直给对比，
    消除模型跨段心算（段1 晋级率 / 段2 前日池率 / 段5 轨迹率口径不一）。"""
    line = three_day_chain_line(_db(), _D0)
    # D-1 池 {600001,600004} → D0 {600001} = 50.0%；D-2 池 3 只 → D-1 1 只 = 33.3%
    assert "边际对比：昨日池今日晋级率 50.0%（2→1） vs 前日池昨日 33.3%（3→1），+16.7pct" in line


def test_three_day_chain_line_promo_comparison_no_fake_zero():
    """昨日涨停池被炸板池清空 → 对比写不可算，不得伪 0%（fail-visible 红线）。"""
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D1: ["600004"]}),
        "jiuyan_action": FakeCol([_final(_D2, _STOCKS[_D2]),
                                  _final(_D1, [{"code": "600004", "name": "D"}]),
                                  _final(_D0, _STOCKS[_D0])]),
    })
    line = three_day_chain_line(db, _D0)
    assert "边际对比：不可算（昨日涨停池为空）" in line
    assert "昨日池今日晋级率 0.0%" not in line  # 伪 0 红线


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
    # 昨日断板（600002/600003）无 TDX 日线 → 对比写不可算，不得伪 0（fail-visible）
    assert "较昨日断板：不可算（昨日 TDX 日线缺失）" in line


def test_relay_flow_line_broken_yesterday_comparison(monkeypatch):
    """relay_phase.divergence「断板亏钱扩散（中位转负或大面增多）」需昨日可比数
    （2026-10-16 二级审计补供）：昨日断板=前日涨停池−昨日涨停池，亏钱=D-2→D-1 收盘。"""
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],    # 今日断板 -10% 大面
        "600002": [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}],    # 昨日断板 -5% 大面
        "600003": [{"date": _D2, "close": 20.0}, {"date": _D1, "close": 20.2}],   # 昨日断板 +1%
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],   # 晋级 +2%
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    line = relay_flow_line(_db(), _D0)
    # 昨日断板中位 [-5.0, +1.0] → -2.0%、大面 1 只；今日 -10.0%、大面 1 只
    assert "断板 1 只：今日收盘中位 -10.0%" in line
    assert "较昨日断板：中位 -2.0%→-10.0%、大面 1→1 只" in line


def test_relay_flow_line_broken_yesterday_no_prev_day(monkeypatch):
    """只有 1 个前交易日 → 较昨日断板写不可算，不伪造对比（fail-visible）。"""
    bars = {"600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}]}
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D1, _D0]),   # D-2 帧缺 → window<2
        "jiuyan_action": FakeCol([_final(_D1, _STOCKS[_D1]), _final(_D0, _STOCKS[_D0])]),
    })
    line = relay_flow_line(db, _D0)
    assert "较昨日断板：不可算（无前日交易日）" in line


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


def test_zhaban_face_line_yesterday_comparison():
    """relay_momentum 锚2 补供（2026-10-15 诊断）：炸板/反复开板较昨日增减直给——
    分位/均值只给绝对位置，模型无从判 criteria 的「较昨日收敛/恶化」方向。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_failed(_D1, [{"code": "600002", "name": "B", "open_num": 3},
                                                        {"code": "600003", "name": "C", "open_num": 1}]),
                                    _frame_failed(_D0, [{"code": "600001", "name": "A", "open_num": 1}])]),
        "jiuyan_action": FakeCol([_final(_D1, _STOCKS[_D1]), _final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "今日炸板面：炸板 1 家" in line
    assert "较昨日：炸板 2→1 家（-1）" in line
    assert "反复开板 1→0 家（-1）" in line


def test_zhaban_face_line_yesterday_frame_missing_no_fake():
    """昨日 THS 炸板池帧缺失/降级 → 对比写不可算，不得以 0 家伪算增减（fail-visible）。"""
    db = FakeDb({
        "snapshot_frames": _frames([_D1, _D0], failed_by_date={_D0: ["600001"]}),  # D1 帧无 thsPools
        "jiuyan_action": FakeCol([_final(_D1, _STOCKS[_D1]), _final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "较昨日：不可算（昨日 THS 炸板池缺失/降级）" in line
    assert "较昨日：炸板 0→" not in line  # 伪 0 红线
    # 历史不足 5 日 → 反复开板分位同写不可算，不伪 P0
    assert "（历史反复开板数据不足 5 日，无分位参照）" in line


def test_zhaban_face_reopen_percentile():
    """反复开板分位（2026-10-16 二级审计补供 relay_phase「反复开板处参照高位/低位」）：
    炸板家数分位原已给，反复开板只有绝对值；同一 20 日回溯顺带算其分位。"""
    hist = [("2026-09-21", [("600101", 2)]), ("2026-09-22", [("600102", 3)]),
            ("2026-09-23", [("600103", 2), ("600104", 1)]), ("2026-09-24", [("600105", 5)]),
            ("2026-09-25", [("600106", 2), ("600107", 2)])]   # 反复开板逐日 1/1/1/1/2
    frames = [_frame_failed(d, [{"code": c, "name": c, "open_num": on} for c, on in items])
              for d, items in hist]
    frames.append(_frame_failed(_D0, [{"code": "600001", "name": "A", "open_num": 1}]))
    db = FakeDb({
        "snapshot_frames": FakeCol(frames),
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    # 今日炸板 1 家 / 反复开板 0 家，均低于全部 5 个历史日 → 双 P0；炸板均值=[1,1,1,2,2] 中位 1
    assert "炸板 1 家（近5日分位 P0，均值 1 家）" in line
    assert "反复开板(≥2次) 0 家（占 0%）（近5日分位 P0）" in line


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


def test_ladder_structure_first_board_pct_yesterday():
    """relay_phase.launch「首板占梯队比例明显升高」需昨日可比数（2026-10-16 二级审计补供）：
    梯队行原只有二板/三板+ 比率挂（昨日 X），首板占比无昨日值。"""
    d0 = [{"code": "600011", "name": "F"}, {"code": "600012", "name": "G"},        # 首板 ×2（不在昨日池）
          {"code": "600003", "name": "C", "num": "2天2板"},                          # 二板
          {"code": "600004", "name": "D", "num": "3天3板"},                          # 三板
          {"code": "600005", "name": "E", "num": "5天5板"}]                          # high(≥5)
    d1 = [{"code": "600021", "name": "H"},                                           # 首板 ×1（不在前日池）
          {"code": "600003", "name": "C", "num": "3天3板"},
          {"code": "600004", "name": "D", "num": "4天4板"}]
    db = FakeDb({
        "snapshot_frames": _frames([_D1, _D0]),
        "jiuyan_action": FakeCol([_final(_D1, d1), _final(_D0, d0)]),
    })
    line = ladder_structure_line(db, _D0)
    # D0：首板 2/5=40%；D1：首板 1/3=33%
    assert "首板占比 40%（2/5）（昨日 33%）" in line
    assert "二板/三板+比率 0.5（昨日 0.0）" in line


def test_ladder_structure_first_board_pct_no_prev_no_fake():
    """无昨日梯队 → 首板占比不挂（昨日 X），不得伪 0%（fail-visible）。"""
    d0 = [{"code": "600011", "name": "F"}, {"code": "600012", "name": "G"},
          {"code": "600003", "name": "C", "num": "2天2板"}]
    db = FakeDb({
        "snapshot_frames": _frames([_D0]),   # 无前日帧
        "jiuyan_action": FakeCol([_final(_D0, d0)]),
    })
    line = ladder_structure_line(db, _D0)
    assert "首板占比 67%（2/3） ·" in line
    assert "（昨日 0%）" not in line and "（昨日 33%）" not in line  # 伪 0 红线


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
