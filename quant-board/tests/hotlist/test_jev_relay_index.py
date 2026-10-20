# -*- coding: utf-8 -*-
"""连板情绪指数轨道测试（2026-10-10 Phase 1）——全 monkeypatch，禁触真实 jev 调用（AGENTS §1.2-7）。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

import backend.operations.jev_relay_index as relay
from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY
from backend.operations.jev_relay_index import (
    _pool_of,
    _tdx_sample_ok,
    anchor_gaps,
    anchor_gaps_derived,
    high_position_trajectory_lines,
    ladder_structure_line,
    relay_flow_line,
    run_relay_index_day,
    theme_ladder_lines,
    three_day_chain_line,
    zhaban_face_line,
)
from backend.operations.jev_label_jiuyan import day_status_of


@pytest.fixture(autouse=True)
def _hermetic_tdx(monkeypatch):
    """默认屏蔽 TDX 取数（日线/除权）——用例内可用 monkeypatch 覆盖 `relay._daily_bars`。

    v4 起 relay_flow/three_day_chain/high_position_trajectory 会逐股调 _daily_bars +
    _adj_prev_series（停牌分辨），必须与真连板回溯测试同规全 mock（AGENTS §1.2.7）。
    """
    monkeypatch.setattr(relay, "_adj_prev_series", lambda *a, **k: {})
    monkeypatch.setattr(relay, "_daily_bars", lambda code: [])


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
                        if op == "$gte" and not (r.get(k) is not None and r.get(k) >= ov):
                            return False
                        if op == "$lte" and not (r.get(k) is not None and r.get(k) <= ov):
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

    def count_documents(self, query=None):
        # v7：题材证据块 corpus_state 消费（jiuyan_timeline/jiuyan_ai_industry 计数）
        return len(self.find(query or {}))

    def replace_one(self, q, doc, upsert=False):
        self.updates.append((q, doc))


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


def _frames(dates, failed_by_date=None, ths_missing=()):
    """15:00 帧夹具；failed_by_date={date: [codes]} 注入 THS 炸板池（二分口径用）。

    2026-10-16：默认带 ok 炸板池（空池=当日无炸板，合法状态），与生产 EOD 帧同形——
    streak 口径二分与真连板回溯都依赖该池存在；ths_missing={dates} 的帧不带 thsPools
    （THS 炸板池缺失日降级路径专用）。
    """
    failed_by_date = failed_by_date or {}
    rows = []
    for d in dates:
        failed = failed_by_date.get(d, [])
        ls = {"zhaban": {"ztCount": 50, "count": len(failed), "rate": 12.0},
              "drawdown": {"count": 3}, "continuousBoards": {"maxBoard": 5}}
        if d not in ths_missing:
            ls["thsPools"] = {"ok": True, "degraded": False, "date": d.replace("-", ""),
                              "pools": {"failed": {"key": "failed", "total": len(failed),
                                                   "items": [{"code": c, "name": f"股{c}", "open_num": 1}
                                                             for c in failed]}}}
        rows.append({"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": d,
                     "slotTime": "15:00", "snapshotId": f"h:{d}", "timestamp": 2,
                     "limitSummary": ls})
    return FakeCol(rows)


def _final(date, stocks):
    return {"_id": f"{date}:final",
            "fields": [{"name": s.get("board") or "板块A", "stocks": [s]} for s in stocks]}


def _final_multi(date, boards):
    """多股同板块夹具（v6 板块接力链）：{板块名: [stock, ...]}。"""
    return {"_id": f"{date}:final",
            "fields": [{"name": name, "stocks": list(stocks)}
                       for name, stocks in boards.items()]}


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


def test_narrative_context_anchor_includes_today():
    """近20日锚必须含今日：今日创新高时锚显示旧峰值会与事实行自相矛盾。

    2026-10-16 实证：600825 停牌复牌真连板 11 板（前峰值 10 板在 10-12），
    旧口径 trading_dates_before(20) 严格早于当日 → 锚写「最高板峰值 10 板」，
    而同篇事实行写「最高 11 板（100 分位）」。现在 hist = 前 19 日 + 当日。
    """
    dates = [f"2026-09-{d:02d}" for d in range(11, 21)] + ["2026-09-30"]
    today = dates[-1]
    finals = [_final(d, [{"code": "600001", "name": "A",
                          "num": "11天11板" if d == today else "10天10板"}]) for d in dates]
    db = FakeDb({"snapshot_frames": _frames(dates),
                 "jiuyan_action": FakeCol(finals)})
    lines = relay.anchor_lines(db, today)
    anchor = next(l for l in lines if l.startswith("近20日锚"))
    # 今日 11 板必须是锚内峰值（旧口径会报前一日 10 板）
    assert f"最高板峰值 11 板（{today[5:]}）" in anchor
    # 涨停家数锚同样含今日（本例五日皆 50 家，峰谷同日，仅锁不抛错）
    assert "涨停峰值 50 家" in anchor


def test_three_day_chain_line():
    """三日链：D-2 3只 → D-1 1只（33.3%）→ D0 1只；高位股轨迹点名（区间 N天M板 + 真连板）。"""
    line = three_day_chain_line(_db(), _D0)
    assert "3 只" in line and "33.3%" in line
    assert "B 3天3板" in line and "次日即断" in line   # D-2 最高板 B 今日不在池
    # A：D-2 2天2板 → 昨日封、今日封 → 连板中（今日 4天4板·真连板 4 板，2026-10-16 口径）
    assert "A 2天2板→连板中（今日4天4板·连板4板）" in line


def test_three_day_chain_line_fate_reversal_not_streak():
    """2026-10-16 修（审计问题 #4）：昨日炸板、今日回封 ≠ 连板中。

    澳弘电子式路径：D-2 高位 → D-1 触板但炸板（在昨日炸板池）→ D0 回封。
    旧逻辑只看今日封板就写「连板中」；新逻辑要求昨日也封板，否则写「昨日断板今日回封」。
    """
    stocks = {
        _D2: [{"code": "600001", "name": "A", "num": "17天10板"}],
        _D1: [{"code": "600001", "name": "A"}],                 # 触板但炸板（进 D-1 炸板池）
        _D0: [{"code": "600001", "name": "A", "num": "19天11板"}],  # 今日回封
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D1: ["600001"]}),
        "jiuyan_action": FakeCol([_final(d, stocks[d]) for d in (_D2, _D1, _D0)]),
    })
    line = three_day_chain_line(db, _D0)
    assert "A 17天10板→昨日断板今日回封（连板1板）" in line
    assert "连板中" not in line            # 昨日炸板 → 不得判连板中（伪连板红线）


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
    D-1 池（600001 晋级在池，600004 断板）；600004 断板 -10% 大面。

    v5（F4 样本门槛）：覆盖 1/1 < 5 只 → 只写「样本不足」，**不**输出 n=1 的伪精度中位
    （07-16 实证：断板 66 只仅 1 只可验却输出中位 +3.46% 并被当钱效依据）。
    """
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],   # 断板 -10% 大面
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],  # 晋级 +2%
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    line = relay_flow_line(_db(), _D0)
    assert "晋级率 50.0%" in line          # 昨日 2 只（600001/600004）→ 今日 1 只在池
    assert "断板 1 只：样本不足（TDX 覆盖 1/1，门槛 ≥5 只且 ≥20%），不可作钱效依据" in line
    assert "大面(≤-5%) 1 只" not in line and "-10.0%" not in line
    assert "隔日溢价样本 2 只：样本不足" in line
    # 昨日断板（600002/600003）无 TDX 日线 → 对比写不可算，不得伪 0（fail-visible）
    assert "较昨日断板：不可算（昨日 TDX 日线缺失）" in line


def test_relay_flow_line_broken_yesterday_comparison(monkeypatch):
    """relay_phase.divergence「断板亏钱扩散（中位转负或大面增多）」需昨日可比数
    （2026-10-16 二级审计补供）：昨日断板=前日涨停池−昨日涨停池，亏钱=D-2→D-1 收盘。

    v5（F4 门槛）：两侧覆盖都须 ≥5 只才输出中位——夹具补足今日/昨日断板各 5 只。
    """
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],    # 今日断板 -10%
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],   # 晋级 +2%
        "600002": [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}],    # 昨日断板 -5%
        "600003": [{"date": _D2, "close": 20.0}, {"date": _D1, "close": 20.2}],   # 昨日断板 +1%
    }
    today_fillers = [{"code": f"6010{i}", "name": f"TF{i}", "num": "2天2板"} for i in range(1, 5)]
    yest_fillers = [{"code": f"6011{i}", "name": f"YF{i}", "num": "2天2板"} for i in range(1, 4)]
    for s in today_fillers:
        bars[s["code"]] = [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}]
    for s in yest_fillers:
        bars[s["code"]] = [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}]
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D1: [], _D0: []}),
        "jiuyan_action": FakeCol([_final(_D2, _STOCKS[_D2] + yest_fillers),
                                  _final(_D1, _STOCKS[_D1] + today_fillers),
                                  _final(_D0, _STOCKS[_D0])]),
    })
    line = relay_flow_line(db, _D0)
    # 今日断板 = 600004 + 4 填充（均 -10%）→ 中位 -10.0%、大面 5
    assert "断板 5 只：今日收盘中位 -10.0%，大面(≤-5%) 5 只" in line
    # 昨日断板 = 600002 + 600003 + 3 填充 → 中位 -5.0%、大面 4
    assert "较昨日断板：中位 -5.0%→-10.0%、大面 4→5 只" in line


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
        "snapshot_frames": _frames([_D1, _D0], failed_by_date={_D0: ["600001"]},
                                   ths_missing={_D1}),  # D1 帧无 thsPools
        "jiuyan_action": FakeCol([_final(_D1, _STOCKS[_D1]), _final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "较昨日：不可算（昨日 THS 炸板池缺失/降级）" in line
    assert "较昨日：炸板 0→" not in line  # 伪 0 红线
    # 历史不足 5 日 → 反复开板分位同写不可算，不伪 P0
    assert "（历史反复开板数据不足 5 日，无分位参照）" in line


def _frame_full(date, failed=None, rushing=None, seal_quality=None):
    """带炸板池+冲刺池+封板质量的 15:00 帧（P3 炸板面补证夹具）。"""
    failed = failed or []
    rushing = rushing or []
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {"zhaban": {"ztCount": 36, "count": len(failed), "rate": 16.3},
                             "drawdown": {"count": 5}, "continuousBoards": {"maxBoard": 5},
                             "sealQuality": (seal_quality if seal_quality is not None else
                                             {"byzCount": 13, "hardCount": 8, "rottenCount": 15,
                                              "rottenShare": 0.417, "avgSucRate": 0.752}),
                             "thsPools": {"ok": True, "degraded": False,
                                          "pools": {
                                              "failed": {"key": "failed", "ok": True,
                                                         "total": len(failed),
                                                         "items": [{"code": c, "name": f"股{c}",
                                                                    "open_num": 1,
                                                                    "change_rate": 5.0} for c in failed]},
                                              "rushing": {"key": "rushing", "ok": True,
                                                          "total": len(rushing),
                                                          "items": [{"code": c, "name": f"冲{c}",
                                                                     "change_rate": r} for c, r in rushing]}}}}}


def test_zhaban_face_rushing_and_rotten_segments():
    """2026-10-16 补供（审计问题 #6）：冲刺池 6 家、烂板 15 家进语料。

    旧语料「炸板面」只覆盖曾封后开板（failed 池），冲刺池与帧 sealQuality 采集了从不消费。
    """
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_full(_D0,
                                                failed=["600001"],
                                                rushing=[("688265", 15.7), ("000973", 7.4),
                                                         ("600199", 6.9), ("600869", 6.7),
                                                         ("002058", 6.2), ("600241", 6.0)])]),
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "冲刺未封 6 家（南模生物(15.7%)" not in line  # 夹具名是「冲688265」非真实名
    assert "冲刺未封 6 家（冲688265(+15.7%)、冲000973(+7.4%)、冲600199(+6.9%)）" in line
    assert "涨停池烂板（开板≥2次回封）15 家（占 42%）" in line


def test_zhaban_face_rushing_pool_missing_no_fake_zero():
    """THS 冲刺池缺失/降级 → 该段写不可算，不伪 0 家（fail-visible）。"""
    db = FakeDb({
        "snapshot_frames": _frames([_D0], failed_by_date={_D0: ["600001"]}),  # 无 rushing 池
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "冲刺未封 不可算（THS 冲刺池缺失/降级）" in line
    assert "冲刺未封 0 家" not in line  # 伪 0 红线


def test_zhaban_face_rotten_missing_no_fake_zero():
    """帧无 sealQuality → 烂板段写不可算，不伪 0 家。"""
    frame = _frame_full(_D0, failed=["600001"], seal_quality={})
    db = FakeDb({"snapshot_frames": FakeCol([frame]),
                 "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])])})
    line = zhaban_face_line(db, _D0)
    assert "涨停池烂板 不可算（sealQuality 缺失）" in line
    assert "烂板（开板≥2次回封）0 家" not in line


def test_zhaban_face_reopen_percentile():
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
    assert "昨日 2 只涨停（触板二分口径） → 今日仍涨停 1 只（晋级率 50.0%）" in line
    # v5（F4 门槛）：断板覆盖 1/1 < 5 只 → 写样本不足，不输出 -10.0% 伪精度中位
    assert "断板 1 只：样本不足（TDX 覆盖 1/1，门槛 ≥5 只且 ≥20%），不可作钱效依据" in line
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
    """题材梯队：高度优先、封板时间次之；区间文案「N天M板」+ 真连板（2026-10-16 口径）。"""
    db = _db()
    db.cols["hotlist_jev_driver_labels"] = FakeCol([
        {"tradingDate": _D0, "status": "ok", "code": "600001", "label": "product_event",
         "freshness": "continuing"}])
    lines = theme_ladder_lines(db, _D0)
    # 妖股 16天8板：龙序仍按区间 M 居首，但文案补跨度与真连板（昨日不在池 → 连板1板）
    assert any("龙一 E(16天8板" in x for x in lines)
    assert any("连板1板" in x for x in lines)
    assert any("龙二 A(4天4板" in x for x in lines)
    # D0 五只全部有板数（600005 16天8板 / 600001 4天4板），无首板股——不断言首板，
    # 但也不能留 `or True` 这种永真式占位（2026-10-16 review：那是噪声不是检查）
    assert not any("首板" in x for x in lines)


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
    # F2：主锚缺位标记随叙事落库（前端徽标读口；v5 起）
    assert "anchorGaps" in doc and isinstance(doc["anchorGaps"], list)
    assert anchor_gaps(doc["narrative"]) == doc["anchorGaps"]
    assert doc["anchorGapsDerived"] == anchor_gaps_derived(doc["narrative"])
    assert doc["questionSetVersion"] == "v7"
    # v6：板块/龙头结构随文档落库（前端同源读取，无需二次计算）
    assert isinstance(doc.get("relayStructure"), dict)
    assert doc["relayStructure"]["mainline"] is not None
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


# ── 2026-10-16 code review 修复（口径自相矛盾 / fail-visible 崩溃）────────────


def _frame_ths_sealed(date, codes_by_pool, pool_ok=None):
    """带 THS 连板层五池的 15:00 帧（_ths_sealed_codes/_zt_caliber_note 专用）。

    pool_ok=None = 五池全 ok；否则只有集合内的池 ok（模拟单池被限流返空）。
    """
    pools = {k: {"key": k, "ok": pool_ok is None or k in pool_ok,
                 "items": [{"stock_code": c, "name": f"股{c}"} for c in codes_by_pool.get(k, [])]}
             for k in relay.THS_KEYS}
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {"zhaban": {"ztCount": 36, "count": 3, "rate": 16.3},
                             "drawdown": {"count": 5}, "continuousBoards": {"maxBoard": 5},
                             "thsPools": {"ok": True, "degraded": False, "pools": pools}}}


def test_ths_sealed_codes_requires_every_pool_ok():
    """单池自身上游失败（THS 风控返 200+空 info）→ 整套对账 None，不静默丢一池的股。

    只读顶层 ok 时，「首板池被限流返空」会被当成当日真无首板——30 只封板股一夜变成
    「触板未封」，整个涨停家数对账反向（2026-10-16 review 实测推演）。
    """
    good = FakeDb({"snapshot_frames": FakeCol([_frame_ths_sealed(
        _D0, {"one": ["600001"], "two": ["600002"]})])})
    assert relay._ths_sealed_codes(good, _D0, "dragonboard_live") == {"600001", "600002"}
    bad = FakeDb({"snapshot_frames": FakeCol([_frame_ths_sealed(
        _D0, {"one": [], "two": ["600002"]}, pool_ok={"two", "three", "four", "high"})])})
    assert relay._ths_sealed_codes(bad, _D0, "dragonboard_live") is None


def test_zt_caliber_note_names_both_directions():
    """「两口径一致」只在双向差集皆空时成立；反向差集（THS 有、二分无）也要点名。

    旧实现只查 `bisect - ths`：韭研 final 漏收日会输出「同花顺涨停池 40 只，两口径一致」
    紧跟一个 36 的家数——同一句里自相矛盾。
    """
    pool = {"600001": {"name": "A"}, "600003": {"name": "C"}}
    db = FakeDb({"snapshot_frames": FakeCol([_frame_ths_sealed(_D0, {"one": ["600001"]})])})
    # 二分多出 600003：点名 + 不代断成因（实证那批是 THS 剔除 ST/北交所，非触板未封）
    note = relay._zt_caliber_note(db, _D0, "dragonboard_live", {"600001", "600003"}, pool)
    assert "二分多出 1 只（C，触板未封/新股/THS池剔除需个股核）" in note
    assert "触板未封/新股：" not in note      # 不写死单一成因
    assert "两口径一致" not in note
    # THS 多出 600002：韭研 final 漏收，必须披露而不是宣称一致
    db2 = FakeDb({"snapshot_frames": FakeCol([_frame_ths_sealed(
        _D0, {"one": ["600001"], "two": ["600002"]})])})
    note2 = relay._zt_caliber_note(db2, _D0, "dragonboard_live", {"600001"}, pool)
    assert "THS 多出 1 只（韭研 final 漏收，二分口径漏计）" in note2
    assert "两口径一致" not in note2
    # 双向皆空才叫一致
    db3 = FakeDb({"snapshot_frames": FakeCol([_frame_ths_sealed(_D0, {"one": ["600001"]})])})
    assert "两口径一致" in relay._zt_caliber_note(db3, _D0, "dragonboard_live",
                                                  {"600001"}, pool)


def test_theme_evolution_line_carries_true_streak():
    """题材演化行必须同时给真连板数——否则同篇段1「最高 5 板」与段2b「最高11板」打架。

    旧实现只渲染区间高度 M（龙序仍按 M，保留），模型在同一份语料里读到两个「最高板」，
    正是本次口径修正要除的污染（审计问题 #2/#3 同族）。
    """
    d1 = [{"code": "600001", "name": "A", "num": "3天3板"}]
    d0 = [{"code": "600001", "name": "A", "num": "5天5板"},
          {"code": "600002", "name": "B"}]
    db = FakeDb({"snapshot_frames": _frames([_D1, _D0]),
                 "jiuyan_action": FakeCol([_final(_D1, d1), _final(_D0, d0)])})
    line = relay.theme_evolution_line(db, _D0)
    assert "最高5天5板（连板5板）" in line
    assert "最高5天5板）" not in line.replace("最高5天5板（连板5板）", "")


def test_three_day_chain_yesterday_break_uses_range_text():
    """高位股轨迹的「昨日断板」分支必须写「N天M板」，不能写裸 M。

    裸「昨日10板」读起来是昨日 10 连板，而同篇段1 说最高 5 板（真连板）——同族自相矛盾。
    """
    d2 = [{"code": "605058", "name": "澳弘电子", "num": "16天9板"}]
    d1 = [{"code": "605058", "name": "澳弘电子", "num": "17天10板"},
          {"code": "600001", "name": "A", "num": "3天3板"}]
    d0 = [{"code": "600001", "name": "A", "num": "4天4板"}]     # 605058 今日不在池 → 断板
    db = FakeDb({"snapshot_frames": _frames([_D2, _D1, _D0]),
                 "jiuyan_action": FakeCol([_final(_D2, d2), _final(_D1, d1), _final(_D0, d0)])})
    line = three_day_chain_line(db, _D0)
    assert "澳弘电子 16天9板→昨日17天10板今日断板" in line
    assert "→昨日10板今日断板" not in line


def test_zhaban_face_prev_layer_uses_range_text():
    """炸板面「昨日2板以上」代表股同样写「N天M板」——裸「(10板)」会被读成昨日 10 连板。"""
    d1 = [{"code": "605058", "name": "澳弘电子", "num": "17天10板"}]
    db = FakeDb({"snapshot_frames": FakeCol([_frame_full(_D1, failed=[]),
                                             _frame_full(_D0, failed=["605058"])]),
                 "jiuyan_action": FakeCol([_final(_D1, d1), _final(_D0, _STOCKS[_D0])])})
    line = zhaban_face_line(db, _D0)
    assert "昨日2板以上 1 家：澳弘电子(17天10板)" in line
    assert "澳弘电子(10板)" not in line


def test_zhaban_face_rotten_share_none_does_not_crash():
    """rottenShare=None（上游样本为空）而 rottenCount=0 → 写「占比不可算」，不得 TypeError。

    build_server_limit_summary 在 quality_n==0 时就是这样输出；旧代码 round(None*100)
    会炸掉整个 relay 日，把 fail-visible 变成崩溃。
    """
    sq = {"byzCount": 0, "hardCount": 0, "rottenCount": 0, "rottenShare": None}
    db = FakeDb({"snapshot_frames": FakeCol([_frame_full(_D0, failed=["600001"], seal_quality=sq)]),
                 "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])])})
    line = zhaban_face_line(db, _D0)
    assert "涨停池烂板（开板≥2次回封）0 家（占比不可算：sealQuality 样本为空，fail-visible）" in line


def test_relay_flow_unlayered_streaks_disclosed():
    """板层不可算的股单独披露只数，不静默回退区间 M 分层。

    旧代码 `layer_key = s if isinstance(s, int) else _day_eff(...)`：19天11板真连板=1
    又被算进 5 板层，晋级率判据被重新污染——正是本次修正要除的东西。
    """
    d1 = [{"code": "600001", "name": "A", "num": "3天3板"},
          {"code": "600005", "name": "E", "num": "16天8板"}]
    d0 = [{"code": "600001", "name": "A", "num": "4天4板"}]
    db = FakeDb({"snapshot_frames": _frames([_D1, _D0], ths_missing={_D1}),
                 "jiuyan_action": FakeCol([_final(_D1, d1), _final(_D0, d0)])})
    line = relay_flow_line(db, _D0)
    assert "2只连板高度不可算未分层" in line
    assert "5板→" not in line      # 不得把 16天8板 按区间高度塞进 5 板层


def test_narrative_context_anchor_maxboard_uncomputable():
    """窗口内最高板全不可算 → 写「不可算」，不得 max([]) 崩掉整个 relay 日。

    真连板口径下 maxBoard=None 远比帧字段时代常见（THS 炸板池缺失/韭研 final 缺失），
    旧代码在此会 ValueError。
    """
    dates = [f"2026-09-{d:02d}" for d in range(11, 21)] + [f"2026-09-{d:02d}" for d in range(22, 31)]
    dates = dates[:20]
    db = FakeDb({"snapshot_frames": _frames(dates, ths_missing=set(dates)),
                 "jiuyan_action": FakeCol([_final(dates[-1], _STOCKS[_D0])])})
    lines = relay.anchor_lines(db, dates[-1])
    assert any("最高板峰值 不可算（窗口内无真连板高度，fail-visible）" in x for x in lines)
    assert any("涨停峰值" in x for x in lines)


# ── v4（2026-10-16 预注册 jev-relay-ammo-v4-preregistration.md）───────────────


def _bars(seq):
    return [{"date": d, "high": c, "close": c, "vol": 1.0} for d, c in seq]


def test_day_status_of_decision_table():
    """停牌分辨决策表（v4 单一事实源）：池权威 + 日线补洞 + 触板名单排除数据洞。"""
    up = _bars([(_D2, 10.0), (_D1, 11.0)])     # +10% 封板
    dn = _bars([(_D2, 10.0), (_D1, 9.5)])      # -5% 未封
    gap = _bars([(_D2, 10.0), (_D0, 12.1)])    # D-1 无棒（落在已覆段内）
    # 池含 → sealed（池为既定权威，即便日线矛盾）
    assert day_status_of("600001", _D1, sealed={"600001"}, touch={"600001"}, bars=dn) == "sealed"
    # 池不含 + 无棒 + 不在触板名单 → suspended（停牌跳过）
    assert day_status_of("600001", _D1, sealed={"600002"}, touch={"600002"}, bars=gap) == "suspended"
    # 池不含 + 无棒 + 触板名单在册 → unknown（TDX 数据洞，不是停牌）
    assert day_status_of("600001", _D1, sealed={"600002"}, touch={"600001"}, bars=gap) == "unknown"
    # 池不含 + 有棒未封 → broken
    assert day_status_of("600001", _D1, sealed={"600002"}, touch={"600002"}, bars=dn) == "broken"
    # 池缺失 + 日线补证：收涨停 → sealed；未封 → broken
    assert day_status_of("600001", _D1, sealed=None, touch=None, bars=up) == "sealed"
    assert day_status_of("600001", _D1, sealed=None, touch=None, bars=dn) == "broken"
    # 池缺失 + 无棒（已覆段内）→ suspended
    assert day_status_of("600001", _D1, sealed=None, touch=None, bars=gap) == "suspended"
    # 日线整体不可用：池权威仍可判（未封→broken）；池缺失 → unknown（不让步为停牌）
    assert day_status_of("600001", _D1, sealed={"600002"}, touch={"600002"}, bars=[]) == "broken"
    assert day_status_of("600001", _D1, sealed=None, touch=None, bars=[]) == "unknown"


def test_three_day_chain_suspension_skip_not_break(monkeypatch):
    """v4 停牌跳过续算（600825 式）：D-2 封板 → D-1 停牌 → D0 回封。

    旧口径写「昨日9天9板今日断板」（假断板，污染 relay_momentum/phase）；v4 必须写
    「昨日停牌今日回封」且不得出现假断板文本。
    """
    bars = {
        # 600001 日线跨过 D-1（D-2 与 D0 有棒，D-1 无棒 = 停牌）
        "600001": _bars([(_D2, 10.0), (_D0, 12.1)]),
        "600002": _bars([(_D2, 10.0), (_D1, 11.0), (_D0, 12.1)]),
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([
            _final(_D2, [{"code": "600001", "name": "新华传媒", "num": "9天9板"},
                         {"code": "600002", "name": "B", "num": "2天2板"}]),
            _final(_D1, [{"code": "600002", "name": "B", "num": "3天3板"}]),   # 600001 停牌不在池
            _final(_D0, [{"code": "600001", "name": "新华传媒", "num": "11天11板"},
                         {"code": "600002", "name": "B", "num": "4天4板"}]),
        ]),
    })
    line = three_day_chain_line(db, _D0)
    assert "新华传媒 9天9板→昨日停牌今日回封（连板11板）" in line
    assert "今日断板" not in line          # 假断板红线（停牌不得当断板）
    assert "今日停牌跳过" not in line


def test_relay_flow_line_suspension_skips_denominator(monkeypatch):
    """v4：停牌股既不进晋级也不进断板，分母同剔并披露。"""
    bars = {
        # 600001 在 D0 停牌：停牌日前后都有棒（D-1 与 10-01），缺 D0 → suspended
        "600001": _bars([(_D1, 10.0), ("2026-10-01", 11.0)]),
        "600002": _bars([(_D1, 10.0), (_D0, 9.5)]),   # 断板 -5%
    }
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([
            _final(_D2, _STOCKS[_D2]),
            _final(_D1, [{"code": "600001", "name": "A", "num": "3天3板"},
                         {"code": "600002", "name": "B", "num": "2天2板"}]),
            _final(_D0, [{"code": "600003", "name": "C"}]),   # 600001 停牌、600002 断板（均不在池）
        ]),
    })
    line = relay_flow_line(db, _D0)
    assert "停牌跳过 1 只" in line and "不计入晋级率" in line
    assert "断板 1 只" in line
    # 分母 = 2 − 1（停牌）= 1；晋级 0 → 0.0%（真实 0，非伪 0）
    assert "（晋级率 0.0%）（停牌跳过 1 只，不计入晋级率）" in line


def test_relay_flow_line_layer_cap_splits_high(monkeypatch):
    """v4 分层 cap=6：5 板与 6板+ 分离（旧 min(s,5) 把 6/10/11 板混进「5板」层）。"""
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([
            _final(_D2, _STOCKS[_D2]),
            _final(_D1, [{"code": "600001", "name": "A", "num": "5天5板"},
                         {"code": "600002", "name": "B", "num": "6天6板"}]),
            _final(_D0, [{"code": "600001", "name": "A", "num": "6天6板"}]),   # 600001 晋级；600002 断板
        ]),
    })
    line = relay_flow_line(db, _D0)
    assert "5板→100%(1/1)" in line
    assert "6板+→0%(0/1)" in line
    assert "5板→0%(0/2)" not in line   # 旧合并层红线


def test_high_position_trajectory_lines_selects_and_renders(monkeypatch):
    """段 2c：真连板≥4 的 top5、逐日 ●、汇总行；<4 不入段。"""
    bars = {"600001": _bars([(_D2, 10.0), (_D1, 11.0), (_D0, 12.1)])}   # 逐日封板
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([
            _final(_D2, [{"code": "600001", "name": "高标", "num": "3天3板"}]),
            _final(_D1, [{"code": "600001", "name": "高标", "num": "4天4板"}]),
            _final(_D0, [{"code": "600001", "name": "高标", "num": "5天5板"},
                         {"code": "600003", "name": "低标", "num": "2天2板"}]),
        ]),
    })
    joined = "\n".join(high_position_trajectory_lines(db, _D0))
    assert "高位股多日轨迹" in joined
    assert "600001" in joined and "当前连板5" in joined and "区间 5天5板" in joined
    assert "600003" not in joined                       # 真连板 2 < 4，不入段
    assert "高位股今日状态：连板中 1 只" in joined
    assert "●●●" in joined


def test_high_position_trajectory_lines_no_high_stock(monkeypatch):
    """无真连板≥4 样本 → 单行如实披露，不伪造路径。"""
    db = FakeDb({"snapshot_frames": _frames([_D2, _D1, _D0]),
                 "jiuyan_action": FakeCol([_final(_D0, [{"code": "600003", "name": "低标"}])])})
    lines = high_position_trajectory_lines(db, _D0)
    assert len(lines) == 1 and "无真连板≥4" in lines[0]


def test_high_position_trajectory_lines_tdx_unavailable(monkeypatch):
    """TDX 日线整体不可用 → 单行 fail-visible，不得伪造路径。"""
    monkeypatch.setattr(relay, "_daily_bars", lambda code: [])
    db = FakeDb({"snapshot_frames": _frames([_D2, _D1, _D0]),
                 "jiuyan_action": FakeCol([_final(_D0, [{"code": "600001", "name": "高标",
                                                          "num": "5天5板"}])])})
    lines = high_position_trajectory_lines(db, _D0)
    assert lines == ["高位股多日轨迹：TDX 日线不可用（fail-visible）"]


# ── v5 IE 读口径修复（预注册 jev-relay-ie-fix-preregistration.md）────────────────


def _old_schema_frame(date, failed=17, rushing=14, drawdown=9):
    """旧采集 schema 的 15:00 帧（只有 poolCounts 家数，无 pools.*.items）。

    2026-07-30..09-23 共 16 天的真实形态（08-24 实样）。
    """
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {
                "zhaban": {"ztCount": 50, "count": 22, "rate": 12.0},
                "continuousBoards": {"maxBoard": 5},
                "thsPools": {"source": "ths-limitup-pools", "date": date.replace("-", ""),
                             "degraded": False, "errors": [],
                             "poolCounts": {"one": 36, "two": 5, "three": 3, "four": 1, "high": 0,
                                            "failed": failed, "rushing": rushing,
                                            "drawdown": drawdown},
                             "failedCount": failed, "rushingCount": rushing,
                             "drawdownCount": drawdown,
                             "drawdownRiskLabel": "涨停股回撤榜",
                             "maxDrawdown": -15.59, "avgDrawdown": -11.41}}}


def test_zhaban_face_old_schema_count_fallback():
    """F1：旧 schema 日只出同源可算部分（家数/冲刺/回撤），个股级子项标不可算。

    旧实现整段写「不可算」，把同帧已有的 failed/rushing/drawdown 一并丢弃（AGENTS §4.0）。
    """
    db = FakeDb({"snapshot_frames": FakeCol([_old_schema_frame(_D0)])})
    line = zhaban_face_line(db, _D0)
    assert "家数口径·旧采集 schema" in line
    assert "炸板 17 家" in line and "冲刺未封 14 家" in line and "涨停股回撤榜 9 家" in line
    assert "最大回撤 -15.59%" in line and "均值 -11.41%" in line
    assert "个股级子项不可算" in line and "不可算（无昨日交易日）" in line
    assert "分位不可算" in line


def test_zhaban_face_old_schema_prev_new_schema_count_delta():
    """F1/D1：今日旧 schema + 昨日新 schema → 家数级对比（带标注），反复开板 不可算。"""
    db = FakeDb({"snapshot_frames": FakeCol([
        _old_schema_frame(_D0, failed=17),
        _frame_failed(_D1, [{"code": f"60000{i}", "name": f"股{i}", "open_num": 1} for i in range(22)]),
    ])})
    line = zhaban_face_line(db, _D0)
    assert "较昨日：炸板 22→17 家（-5）" in line
    assert "反复开板 不可算（个股级缺）" in line


def test_zhaban_face_old_schema_prev_old_schema_count_delta():
    """F1/D1：两日同为旧 schema → 家数级对比仍可做（同源同义字段）。"""
    db = FakeDb({"snapshot_frames": FakeCol([
        _old_schema_frame(_D0, failed=17),
        _old_schema_frame(_D1, failed=20),
    ])})
    line = zhaban_face_line(db, _D0)
    assert "较昨日：炸板 20→17 家（-3）" in line


def test_zhaban_face_no_frame_still_fail_visible():
    """无 15:00 帧（连家数都没有）→ 仍如实写不可算，不得伪造家数。"""
    db = FakeDb({"snapshot_frames": FakeCol([])})
    assert zhaban_face_line(db, _D0) == "今日炸板面：不可算（THS 炸板池缺失/降级，fail-visible）"


def test_ladder_line_falls_back_to_jiuyan_without_frame():
    """F3：无 15:00 帧（market_metrics 整段 None）时，梯队仍出韭研桶并披露触板口径。

    07-06/07/07/07-09 实证：韭研 final 96/48/88 只本可出桶，旧读口径整段丢弃 → 梯队 IE。
    """
    db = FakeDb({
        # 当日无 15:00 帧；前一日有帧（供 trading_dates_before 与昨日对比）
        "snapshot_frames": _frames([_D1]),
        "jiuyan_action": FakeCol([_final(_D0, [
            {"code": "600001", "name": "A", "num": "2天2板"},
            {"code": "600002", "name": "B", "num": "4天4板"},
            {"code": "600003", "name": "C"},
        ])]),
    })
    line = ladder_structure_line(db, _D0)
    assert "梯队数据缺失" not in line
    assert "首板占比" in line and "二板 1 只" in line and "三板+ 1 只" in line
    assert "THS炸板池缺失，梯队按触板口径" in line


def test_tdx_sample_gate_thresholds():
    """F4 门槛：绝对门槛 + 比例门槛都要过（1/1=100% 必须被绝对门槛拦住）。"""
    assert _tdx_sample_ok(5, 20) is True
    assert _tdx_sample_ok(1, 1) is False        # 07-06 实证：1/1 不得当钱效依据
    assert _tdx_sample_ok(2, 2) is False
    assert _tdx_sample_ok(4, 20) is False       # 绝对不足
    assert _tdx_sample_ok(20, 200) is False     # 10% < 20%
    assert _tdx_sample_ok(0, 0) is False


def test_relay_flow_drops_pseudo_precision_median(monkeypatch):
    """F4：覆盖不足时断板行改「样本不足」，全文不得出现 n=1 的中位句。"""
    db = _db()
    monkeypatch.setattr(relay, "_close_pct", lambda c, a, b: 3.46 if c == "600001" else None)
    line = relay_flow_line(db, _D0)
    assert "样本不足" in line and "不可作钱效依据" in line
    assert "+3.46" not in line
    assert "隔日溢价不可算" in line or "样本不足" in line


@pytest.mark.parametrize("text,expected", [
    ("", []),
    ("今日炸板面：不可算（THS 炸板池缺失/降级，fail-visible）", ["炸板面"]),
    ("今日炸板面（家数口径·旧采集 schema：仅家数可算，个股级子项不可算）：炸板 17 家；较昨日：不可算（无昨日交易日）",
     []),                                  # 家数级降级：主锚在（家数可算）→ 不进主锚清单
    ("断板 66 只：样本不足（TDX 覆盖 1/66，门槛 ≥5 只且 ≥20%），不可作钱效依据", []),
    ("梯队结构量化：梯队数据缺失（fail-visible）", ["梯队"]),
    ("题材梯队表：韭研 final 缺失（fail-visible）", ["题材梯队表"]),
    ("2026-05-06 交易日\n题材梯队表（top5）：· 板块A：龙一 X｜昨日 1 只", []),
    ("盘面事实：2026-07-06 盘面指标缺失（fail-visible）", ["盘面事实"]),
])
def test_anchor_gaps_marks_only_whole_anchor_loss(text, expected):
    """F2 主锚层（2026-10-18 分层）：只标「整根锚不可用」，派生项一律不入主锚清单。"""
    assert anchor_gaps(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("", []),
    ("今日炸板面：不可算（THS 炸板池缺失/降级，fail-visible）", []),      # 整段缺 → 归主锚
    ("今日炸板面（家数口径·旧采集 schema：仅家数可算，个股级子项不可算）：炸板 17 家；较昨日：不可算（无昨日交易日）",
     ["炸板面个股级", "炸板面对比"]),
    ("断板 66 只：样本不足（TDX 覆盖 1/66，门槛 ≥5 只且 ≥20%），不可作钱效依据", ["断板钱效"]),
    ("断板 24 只：今日表现不可算（TDX 日线缺失）", ["断板钱效"]),
    ("三日晋级链：2026-04-29/2026-04-30 韭研 final 缺失（fail-visible）", ["晋级链前池"]),
    ("题材梯队表：韭研 final 缺失（fail-visible）", []),      # 整表缺 → 主锚，不在子项
    ("盘面事实：2026-07-06 盘面指标缺失（fail-visible）", []),
])
def test_anchor_gaps_derived_marks_subitem_loss(text, expected):
    """F2 子项层：主锚在、子统计/对比/样本不可算 → 灰徽标（不占主锚位）。"""
    assert anchor_gaps_derived(text) == expected


def test_bars_offset_env(monkeypatch):
    """F5/F6：回放长窗开关（2026-10-18「开长窗」后默认 250 = 线上回退窗；本地优先时本值不参与）。"""
    from backend.operations.jev_label_jiuyan import _bars_offset
    monkeypatch.delenv("JEV_BARS_OFFSET", raising=False)
    assert _bars_offset() == 250
    monkeypatch.setenv("JEV_BARS_OFFSET", "60")
    assert _bars_offset() == 60
    monkeypatch.setenv("JEV_BARS_OFFSET", "abc")
    assert _bars_offset() == 250
    monkeypatch.setenv("JEV_BARS_OFFSET", "5")
    assert _bars_offset() == 20          # 下限保护


def test_adj_prev_series_bounded_lookback(monkeypatch):
    """除权日程查询有界回看（2026-10-18「开长窗」配套）：

    本地全历史棒把窗口 60→400 后，`_adj_prev_series` 的「每链接日一次百度日程」外呼被放大
    6.7×（实测单日重算卡 >18 分钟）。消费者只用近端键（`_bar_verdict` 取 `adj.get(date)`、
    真连板回溯 ≤ 区间板数、位置/序列 ≤10 天）→ 只算最近 `_ADJ_LOOKBACK` 个链接。
    """
    from backend.operations import jev_label_jiuyan as J
    seen: list[str] = []

    def fake_div(date: str) -> dict:
        seen.append(date)
        return {"600000": (0.5, 0.0)}          # 每个链接日都有除权事件

    monkeypatch.setattr(J, "_div_event_list", fake_div)
    bars = [{"date": f"2026-{1 + (i // 28):02d}-{1 + (i % 28):02d}", "high": 10.0, "close": 10.0}
            for i in range(200)]
    out = J._adj_prev_series(bars[-1]["date"], "600000", bars)
    assert len(seen) <= J._ADJ_LOOKBACK                 # 有界：不再整窗 199 次外呼
    assert set(out) <= {b["date"] for b in bars[-J._ADJ_LOOKBACK:]}   # 只出近端键
    assert J._ADJ_LOOKBACK == 45


def test_relay_flow_line_today_bars_missing_not_fake_coverage(monkeypatch):
    """当日 TDX 日线**整体缺失** → 写「今日 TDX 日线缺失」，不得伪造成「覆盖 0/N」（review P1-1）。

    旧式 `covered if cur_stats else 0` 把 `_broken_stats` 返回 None（= 无任何日线）渲染成
    一个并不存在的读数「TDX 覆盖 0/5」，归因也从「日线缺失」误成「样本不足」。
    §4.0：缺失必须显式可见，不得用 0 伪装。
    """
    # 昨日断板统计可用（≥5 只），今日断板 ≥5 只但当日日线源整体不可用（_daily_bars → []）
    bars = {
        "600002": [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}],   # 昨日断板
        "600003": [{"date": _D2, "close": 20.0}, {"date": _D1, "close": 20.2}],  # 昨日断板
    }
    yest_fillers = [{"code": f"6011{i}", "name": f"YF{i}", "num": "2天2板"} for i in range(1, 4)]
    for s in yest_fillers:                       # 昨日断板凑到 5 只，越过 F4 门槛
        bars[s["code"]] = [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}]

    def _bars(code):
        # 仅有 _D1/_D2 两日；当日 _D0 无任何棒 → 当日日线整体缺失（不是「覆盖 0」）
        return bars.get(code, [])

    monkeypatch.setattr(relay, "_daily_bars", _bars)
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D1: [], _D0: []}),
        "jiuyan_action": FakeCol([_final(_D2, _STOCKS[_D2] + yest_fillers),
                                  _final(_D1, _STOCKS[_D1]),
                                  _final(_D0, _STOCKS[_D0])]),
    })
    line = relay_flow_line(db, _D0)
    assert "今日 TDX 日线缺失" in line, f"未如实归因：{line}"
    assert "覆盖 0/" not in line, f"把「无日线」渲染成「覆盖 0/N」（伪 0）：{line}"


def _frame_legacy_poolcounts(date, counts, *, degraded=True):
    """旧采集 schema 帧：只有 `poolCounts` 家数（无 `pools.*.items`），P1-3 的真实形态。"""
    tp = {"date": date.replace("-", ""), "source": "ths", "poolCounts": dict(counts)}
    if degraded:
        tp["degraded"] = True
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {"zhaban": {"ztCount": 36, "count": 0, "rate": 16.3},
                             "drawdown": {"count": 5}, "continuousBoards": {"maxBoard": 5},
                             "thsPools": tp}}


def test_zhaban_face_legacy_placeholder_zero_not_fake_zero():
    """旧 schema 占位零（degraded:true + 三池全 0）→ 写「不可算」，不得输出「炸板 0 家」（review P1-3）。

    实测库中存在 35 帧此形态（THS 整池拉取失败时旧前端写 `degraded:true` + poolCounts 全 0）。
    旧实现不看 degraded → 把占位零当读数，输出「炸板 0 家；冲刺未封 0 家；涨停股回撤榜 0 家」。
    §4.0：不得用 0 伪装缺失。
    """
    zero = {"one": 0, "two": 0, "three": 0, "four": 0, "high": 0,
            "failed": 0, "rushing": 0, "drawdown": 0}
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_legacy_poolcounts(_D0, zero)]),
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "炸板 0 家" not in line, f"占位零被当成读数（伪 0）：{line}"
    assert "不可算" in line, f"应显式标不可算：{line}"


def test_zhaban_face_legacy_partial_pool_kept():
    """合法降级：个别池失败但任一池有非零家数 → 家数读数保留（不得一刀切丢弃，§4.0）。"""
    counts = {"one": 0, "two": 0, "three": 0, "four": 0, "high": 0,
              "failed": 7, "rushing": 0, "drawdown": 0}
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame_legacy_poolcounts(_D0, counts)]),
        "jiuyan_action": FakeCol([_final(_D0, _STOCKS[_D0])]),
    })
    line = zhaban_face_line(db, _D0)
    assert "炸板 7 家" in line, f"有可用家数应照常展示：{line}"


# ══════════════════════════════════════════════════════════════════════════════
# v6（2026-10-19）板块接力链 + 龙头结构
# 预注册：docs/hotlist-jev/jev-relay-sector-leader-preregistration.md
# ══════════════════════════════════════════════════════════════════════════════

# 三日板块结构：主线甲板块两只存活；乙板块家数更多但无高位股
_SECTOR_BOARDS = {
    _D2: {
        "甲板块": [{"code": "600101", "name": "甲A", "num": "2天2板", "time": "09:40"},
                   {"code": "600102", "name": "甲B", "num": "2天2板", "time": "10:10"}],
        "乙板块": [{"code": "600201", "name": "乙A", "num": "2天2板", "time": "11:00"},
                   {"code": "600202", "name": "乙B", "num": "2天2板", "time": "13:00"},
                   {"code": "600203", "name": "乙C", "num": "2天2板", "time": "14:00"}],
    },
    _D1: {
        "甲板块": [{"code": "600101", "name": "甲A", "num": "3天3板", "time": "09:35"},
                   {"code": "600102", "name": "甲B", "num": "3天3板", "time": "10:00"}],
        "乙板块": [{"code": "600201", "name": "乙A", "num": "3天3板", "time": "11:00"},
                   {"code": "600301", "name": "丙N", "num": "1天1板", "time": "09:31"}],
    },
    _D0: {
        "甲板块": [{"code": "600101", "name": "甲A", "num": "4天4板", "time": "09:30"},
                   {"code": "600102", "name": "甲B", "num": "4天4板", "time": "10:05"}],
        "乙板块": [{"code": "600201", "name": "乙A", "num": "4天4板", "time": "13:30"},
                   {"code": "600202", "name": "乙B", "num": "1天1板", "time": "09:45"},
                   {"code": "600203", "name": "乙C", "num": "1天1板", "time": "14:10"}],
        "丙板块": [{"code": "600301", "name": "丙N", "num": "2天2板", "time": "09:31"}],
    },
}


def _sector_db():
    return FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, _SECTOR_BOARDS[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
        "hotlist_jev_sentiment": FakeCol([]),
    })


def test_relay_structure_mainline_by_three_day_survivors():
    """主线=三日链存活股归属最多；家数更多但无存活的板块不得夺主线（v6 口径）。"""
    struct = relay.relay_structure(_sector_db(), _D0)
    main = struct["mainline"]
    assert main["name"] == "甲板块"
    assert main["basis"] == "three_day_survivors"
    assert main["survivors"] == 2
    assert main["holdings"] == ["甲A", "甲B"]
    counts = {s["name"]: s["d0"]["count"] for s in struct["sectors"]}
    assert counts["乙板块"] > counts["甲板块"]
    assert struct["sectors"][0]["name"] == "甲板块"
    main_line = next(x for x in relay.sector_relay_lines(struct)
                     if x.startswith("主线板块："))
    assert main_line.startswith("主线板块：甲板块") and "总龙头在本板块：是" in main_line


def test_relay_structure_mainline_degrades_when_no_survivor():
    """存活为零 → 逐级降级到今日晋级/家数，并在文本暴露依据（不伪 0）。"""
    boards = {
        _D2: {"甲板块": [{"code": "600401", "name": "X", "num": "2天2板", "time": "09:40"}]},
        _D1: {"甲板块": [{"code": "600402", "name": "Y", "num": "2天2板", "time": "09:40"}]},
        _D0: {"乙板块": [{"code": "600403", "name": "Z", "num": "2天2板", "time": "09:40"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    assert struct["mainline"]["name"] == "乙板块"
    assert struct["mainline"]["basis"] == "d0_count"
    assert any("今日板块涨停家数" in x and x.startswith("主线板块：")
               for x in relay.sector_relay_lines(struct))


def test_relay_structure_missing_history_is_fail_visible():
    """D-1/D-2 韭研 final 缺失 → 历史列写「缺失」、存活/晋级写「不可算」，禁落「0 只」（§4.0）。

    2026-10-19 review P1 回归：旧断言只查 `"0只"`（无空格），而存活列写作 `0 只`（有空格），
    假绿放过了伪 0；新断言同时禁两种空格形态并锁「不可算 + 原因」。
    """
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(_D0, _SECTOR_BOARDS[_D0])]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    lines = relay.sector_relay_lines(struct)
    row = next(x for x in lines if x.startswith("· 甲板块"))
    assert struct["chain"]["ok"] is False
    assert "韭研 final 缺失" in struct["chain"]["reason"]
    assert "三日存活 不可算" in row and "今日晋级 不可算" in row
    assert "0只" not in row and "0 只" not in row
    # 依据文案不得声称「均为零」（那是把缺料读成事实）
    assert "chain_na" == struct["mainline"]["basis"]
    main_line = next(x for x in lines if x.startswith("主线板块："))
    assert "三日链不可算" in main_line and "均为真零" not in main_line
    assert struct["mainline"]["survivors"] is None
    assert anchor_gaps_derived("\n".join(lines)) == ["板块接力链"]


def test_relay_structure_mainline_degrades_when_chain_ok_and_truly_zero():
    """三日链可算但存活/晋级真零 → 依据文案必须写「真零」而与「不可算」区分。"""
    boards = {
        _D2: {"甲板块": [{"code": "600711", "name": "A", "num": "2天2板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600712", "name": "B", "num": "2天2板", "time": "09:30"}]},
        _D0: {"甲板块": [{"code": "600713", "name": "C", "num": "1天1板", "time": "09:30"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    assert struct["chain"]["ok"] is True
    assert struct["mainline"]["basis"] == "d0_count"
    row = next(x for x in relay.sector_relay_lines(struct) if x.startswith("· 甲板块"))
    assert "三日存活 0 只" in row and "今日晋级 0 只" in row
    assert any("均为真零" in x and x.startswith("主线板块：")
               for x in relay.sector_relay_lines(struct))


def test_relay_structure_leader_same_stock():
    """总龙头=区间高度 M 最高；情绪龙头=真连板最高；同日两者可重合。"""
    struct = relay.relay_structure(_sector_db(), _D0)
    assert struct["totalLeader"]["code"] == "600101"       # 甲A 4天4板 + 最早封板
    assert struct["sentimentLeader"]["code"] == "600101"   # 真连板 4 同为最高
    assert struct["sameStock"] is True
    assert "为同一只" in "\n".join(relay.leader_structure_lines(struct))


def test_relay_structure_leader_diverges():
    """妖股口径：区间高度高但真连板低 → 总龙头与情绪龙头必须分离并显式标注。

    注：本用例与上一个共用同一日期，必须拆成两个 test——_STREAK_CACHE 按
    (dataset, date) 键且在单个 test 内不重置，两个夹具同日期会在同一用例内串读。
    """
    boards = {
        _D2: {"甲板块": [{"code": "600501", "name": "妖", "num": "19天11板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600511", "name": "连", "num": "2天2板", "time": "09:30"}]},
        _D0: {"甲板块": [{"code": "600501", "name": "妖", "num": "19天11板", "time": "09:30"},
                         {"code": "600511", "name": "连", "num": "3天3板", "time": "09:31"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    s2 = relay.relay_structure(db, _D0)
    assert s2["totalLeader"]["code"] == "600501"
    assert s2["sentimentLeader"]["code"] == "600511"
    assert s2["sameStock"] is False
    assert "总龙头与情绪龙头不同" in "\n".join(relay.leader_structure_lines(s2))


def test_leader_genesis_from_jiuyan_span_not_tdx(monkeypatch):
    """诞生轨迹：首板日按韭研「N天M板」的 N 推算；TDX 全空也必须可算。"""
    monkeypatch.setattr(relay, "_daily_bars", lambda code: [])
    boards = {
        _D2: {"甲板块": [{"code": "600901", "name": "甲", "num": "1天1板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600901", "name": "甲", "num": "2天2板", "time": "09:30"}]},
        _D0: {"甲板块": [{"code": "600901", "name": "甲", "num": "3天3板", "time": "09:30"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    gen = struct["genesis"]
    # 韭研 N=3 → 首板日 = 3-1 = 2 个交易日前（日期与天数必须互证，2026-10-19 review P1）
    assert gen["tradingDaysAgo"] == 2 and gen["breaks"] == 0
    assert gen["firstBoardDate"] == _D2
    assert gen["degraded"] is None
    assert "诞生轨迹：首板 09-28（2 个交易日前）" in "\n".join(
        relay.leader_structure_lines(struct))


def test_leader_genesis_first_board_is_today(monkeypatch):
    """首板股（韭研不标 num）→ 首板日=当日、天数 0，渲染「当日」。"""
    monkeypatch.setattr(relay, "_daily_bars", lambda code: [])
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(_D0, {"甲板块": [
            {"code": "600921", "name": "新", "time": "09:30"}]})]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    gen = struct["genesis"]
    assert gen["tradingDaysAgo"] == 0 and gen["firstBoardDate"] == _D0
    assert "首板 09-30（当日）" in "\n".join(relay.leader_structure_lines(struct))


def test_leader_genesis_window_short_is_fail_visible(monkeypatch):
    """推算所需交易日史不足 → 明示不可算，不得伪造首板日。"""
    monkeypatch.setattr(relay, "_daily_bars", lambda code: [])
    db = FakeDb({
        "snapshot_frames": _frames([_D0]),
        "jiuyan_action": FakeCol([_final(_D0, [{"code": "600005", "name": "E",
                                                "num": "16天8板", "time": "09:30"}])]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    assert struct["genesis"]["firstBoardDate"] is None
    assert "超出可取交易日史" in struct["genesis"]["degraded"]
    assert "诞生轨迹：不可算" in "\n".join(relay.leader_structure_lines(struct))


def test_leader_genesis_before_pool_history_blames_raw_material(monkeypatch):
    """§14.6 修复：首板日早于韭研池史起点 → 归因原料边界，不得写成「口径不一致」。

    2026-10-19 全量验收实测 10 天属于此类（首板日在韭研池史 2026-05-06 之前）。
    """
    d4, d3, d2, d1 = "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"
    db = FakeDb({
        "snapshot_frames": _frames([d4, d3, d2, d1, _D0]),
        # 池史只有 d1/_D0（起点=d1）；龙头 N=5 → 首板日=d4，**早于池史起点**
        "jiuyan_action": FakeCol([
            _final(d1, [{"code": "600901", "name": "甲", "num": "5天5板", "time": "09:30"}]),
            _final(_D0, [{"code": "600901", "name": "甲", "num": "5天5板", "time": "09:30"}]),
        ]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    gen = relay.relay_structure(db, _D0)["genesis"]
    assert gen["firstBoardDate"] == d4 and gen["tradingDaysAgo"] == 4
    assert "早于韭研池史起点" in gen["degraded"] and d1 in gen["degraded"]
    assert "口径不一致" not in gen["degraded"]
    assert "不在韭研池" not in gen["degraded"]


def test_leader_genesis_absent_within_pool_history(monkeypatch):
    """池史覆盖首板日、但该股当日不在涨停池 → 归因「推算/停牌」，不得赖池史边界。"""
    d4, d3, d2, d1 = "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"
    db = FakeDb({
        "snapshot_frames": _frames([d4, d3, d2, d1, _D0]),
        "jiuyan_action": FakeCol([
            # 首板日 d4 当天池存在，但只有另一只股（该股不在池）
            _final(d4, [{"code": "600902", "name": "乙", "num": "1天1板", "time": "09:30"}]),
            _final(_D0, [{"code": "600901", "name": "甲", "num": "5天5板", "time": "09:30"}]),
        ]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    gen = relay.relay_structure(db, _D0)["genesis"]
    assert gen["firstBoardDate"] == d4
    assert "不在韭研池" in gen["degraded"] and "停牌" in gen["degraded"]
    assert "早于韭研池史起点" not in gen["degraded"]
    assert "口径不一致" not in gen["degraded"]


def test_leader_genesis_first_board_day_pool_missing(monkeypatch):
    """首板日在池史范围内、但该日韭研 final 缺档 → 明写「韭研池缺失」，不伪造。"""
    d4, d3, d2, d1 = "2026-09-23", "2026-09-24", "2026-09-25", "2026-09-28"
    db = FakeDb({
        "snapshot_frames": _frames([d4, d3, d2, d1, _D0]),
        # 池史起点=d4（< 首板日 d3），但 d3 当天无 final → 不可校验
        "jiuyan_action": FakeCol([
            _final(d4, [{"code": "600902", "name": "乙", "num": "1天1板", "time": "09:30"}]),
            _final(_D0, [{"code": "600901", "name": "甲", "num": "4天4板", "time": "09:30"}]),
        ]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    gen = relay.relay_structure(db, _D0)["genesis"]
    assert gen["firstBoardDate"] == d3
    assert "韭研池缺失" in gen["degraded"]
    assert "早于韭研池史起点" not in gen["degraded"] and "不在韭研池" not in gen["degraded"]


def test_leader_succession_reports_prev_leader_status(monkeypatch):
    """更替：昨日总龙头今日不在池（池权威未封、无日线佐证）→ 断板退位。"""
    boards = {
        _D2: {"甲板块": [{"code": "600601", "name": "旧", "num": "2天2板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600601", "name": "旧", "num": "3天3板", "time": "09:30"}]},
        _D0: {"甲板块": [{"code": "600602", "name": "新", "num": "5天5板", "time": "09:30"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    succ = struct["succession"]
    assert succ["changed"] is True and succ["prevLeader"]["code"] == "600601"
    # 池权威：今日未被封且无停牌佐证（TDX 不可用不让步为停牌）→ broken
    assert succ["prevStatus"] == "broken"
    text = "\n".join(relay.leader_structure_lines(struct))
    assert "今日换龙头" in text and "旧龙头今日断板" in text


def test_relay_structure_pseudo_board_never_becomes_mainline():
    """韭研泛板块（其他/公告/新股）不得当主线：真题材优先且必披露剔除。"""
    boards = {
        _D2: {"其他": [{"code": "600701", "name": "杂A", "num": "2天2板", "time": "09:30"}],
               "半导体": [{"code": "600702", "name": "芯B", "num": "2天2板", "time": "09:31"}]},
        _D1: {"其他": [{"code": "600701", "name": "杂A", "num": "3天3板", "time": "09:30"}],
               "半导体": [{"code": "600702", "name": "芯B", "num": "3天3板", "time": "09:31"}]},
        _D0: {"其他": [{"code": "600701", "name": "杂A", "num": "4天4板", "time": "09:30"},
                        {"code": "600703", "name": "杂C", "num": "1天1板", "time": "09:40"}],
               "半导体": [{"code": "600702", "name": "芯B", "num": "4天4板", "time": "09:31"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    assert struct["mainline"]["name"] == "半导体"
    assert struct["mainline"]["pseudoExcluded"] == "其他"
    text = "\n".join(relay.sector_relay_lines(struct))
    assert "泛板块「其他」" in text and "已排除" in text
    assert "（泛板块）" in text


def test_relay_structure_sentiment_leader_uncomputable_not_fallback_m():
    """全池落 THS 炸板池 → 真连板全不可验 → 情绪龙头=None，且不得回落区间 M 冒充。"""
    boards = {_D0: {"甲板块": [{"code": "600931", "name": "甲", "num": "4天4板", "time": "09:30"}]}}
    db = FakeDb({
        "snapshot_frames": _frames([_D0], failed_by_date={_D0: ["600931"]}),
        "jiuyan_action": FakeCol([_final_multi(_D0, boards[_D0])]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    assert struct["totalLeader"]["code"] == "600931"        # 总龙头仍有（区间高度口径）
    assert struct["sentimentLeader"] is None                # 情绪龙头不可验 → None
    assert struct["sameStock"] is None                      # 布尔语义未知，不得落 False
    text = "\n".join(relay.leader_structure_lines(struct))
    assert "情绪龙头 不可算" in text and "不可判" in text
    assert any("情绪龙头不可算" in x for x in struct["degraded"])


def test_leader_succession_continued_and_sealed_displaced(monkeypatch):
    """更替三态补锁：同一只延续；旧龙头仍封板但被更高板超越。"""
    # 延续：D1 与 D0 的总龙头都是 甲A
    struct = relay.relay_structure(_sector_db(), _D0)
    assert struct["succession"]["changed"] is False
    assert "今日延续" in "\n".join(relay.leader_structure_lines(struct))

    # 旧龙头仍封板但被超越（sealed 支）——与上例同日期，需独立用例（_STREAK_CACHE 串读）
    boards = {
        _D2: {"甲板块": [{"code": "600941", "name": "旧", "num": "3天3板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600941", "name": "旧", "num": "3天3板", "time": "09:30"},
                         {"code": "600942", "name": "新", "num": "2天2板", "time": "09:40"}]},
        _D0: {"甲板块": [{"code": "600942", "name": "新", "num": "5天5板", "time": "09:31"},
                         {"code": "600941", "name": "旧", "num": "3天3板", "time": "09:30"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    s = relay.relay_structure(db, _D0)
    assert s["succession"]["changed"] is True
    assert s["succession"]["prevLeader"]["code"] == "600941"
    assert s["succession"]["prevStatus"] == "sealed"
    assert "位次被超越" in "\n".join(relay.leader_structure_lines(s))


def test_leader_succession_suspended(monkeypatch):
    """旧龙头今日无棒且在已覆段内 → 停牌跳过（不得写成断板）。"""
    monkeypatch.setattr(
        relay, "_daily_bars",
        lambda code: ([{"date": _D2, "high": 10.0, "close": 10.0},
                       {"date": "2026-10-05", "high": 10.0, "close": 10.0}]
                      if code == "600951" else []))
    boards = {
        _D2: {"甲板块": [{"code": "600951", "name": "停", "num": "3天3板", "time": "09:30"}]},
        _D1: {"甲板块": [{"code": "600951", "name": "停", "num": "3天3板", "time": "09:30"}]},
        _D0: {"甲板块": [{"code": "600952", "name": "新", "num": "5天5板", "time": "09:30"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0]),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    s = relay.relay_structure(db, _D0)
    assert s["succession"]["changed"] is True
    assert s["succession"]["prevStatus"] == "suspended"
    assert "旧龙头今日停牌跳过" in "\n".join(relay.leader_structure_lines(s))


def test_theme_ladder_includes_mainline_outside_top5():
    """主线板块不在家数 top5 时被强制纳入且置顶（家数多≠主线）。"""
    boards = {f"板块{i}": [{"code": f"6007{i:02d}", "name": f"S{i}", "num": "1天1板",
                           "time": "09:30"}] for i in range(6)}
    boards["主线甲"] = [{"code": "600801", "name": "M", "num": "2天2板", "time": "09:30"}]
    db = FakeDb({
        "snapshot_frames": _frames([_D0]),
        "jiuyan_action": FakeCol([_final_multi(_D0, boards)]),
        "hotlist_jev_driver_labels": FakeCol([]),
    })
    rows = [x for x in theme_ladder_lines(db, _D0, mainline="主线甲") if x.startswith("· ")]
    assert rows[0].startswith("· 主线甲（主线）")
    assert sum(1 for x in rows if x.startswith("· 主线甲")) == 1
    assert len(rows) == 5


def test_anchor_gaps_derived_marks_sector_and_leader_sections():
    """新段缺位归子项层（灰），不得抬主锚徽标（108 天噪声教训）。"""
    text = "\n".join(["板块接力链（三日）：不可算（韭研 final 缺失，fail-visible）",
                      "龙头结构：不可算（韭研 final 缺失，fail-visible）"])
    assert anchor_gaps(text) == []
    assert anchor_gaps_derived(text) == ["板块接力链", "龙头结构"]


def test_question_set_v6_instructions_lock():
    """v6 判据快照锁定：四题含新段关键词、三题未动、枚举与打分锚零变动（预注册 §3）。

    2026-10-19 review P2：原先只锁版本串——instructions 被误改而版本不变会静默破坏快照。
    """
    from backend.analysis.hotlist.jev_relay_ammo import QUESTIONS_RELAY
    from backend.analysis.hotlist.jev_state import SCORE_ANCHORS_10

    for q, needles in (("relay_index", ("板块接力链", "龙头结构")),
                       ("relay_phase", ("板块接力链", "龙头结构")),
                       ("leader_strength", ("龙头结构",)),
                       ("theme_pulse", ("板块接力链",))):
        txt = QUESTIONS_RELAY[q]["instructions"]
        for needle in needles:
            assert needle in txt, (q, needle)
    for q, needle in (("relay_momentum", "三日晋级链"), ("ladder_health", "梯队分布"),
                      ("money_effect", "晋级与断板")):
        txt = QUESTIONS_RELAY[q]["instructions"]
        assert needle in txt, q
        assert "龙头结构" not in txt and "板块接力链" not in txt, f"{q} 不应引用新段"
    for q in ("relay_index", "leader_strength"):
        assert QUESTIONS_RELAY[q]["criteria"] == list(SCORE_ANCHORS_10)


def test_relay_structure_narrative_and_doc_are_single_source(monkeypatch):
    """叙事段与落库 relayStructure 同一事实源：总龙头/主线两处必须一致。"""
    def fake_dispatch(state, questions):
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
            }}}}, 100)

    monkeypatch.setattr(relay, "_dispatch_jev", fake_dispatch)
    db = _sector_db()
    run_relay_index_day(db, [_D0])
    _, doc = db.cols[relay.COLLECTION].updates[0]
    struct = doc["relayStructure"]
    assert struct["mainline"]["name"] == "甲板块"
    narrative = doc["narrative"]
    assert "板块接力链（三日" in narrative and "龙头结构（" in narrative
    assert f"主线板块：{struct['mainline']['name']}" in narrative
    assert f"总龙头 {struct['totalLeader']['name']}({struct['totalLeader']['code']})" in narrative
    assert f"龙头档案：{struct['totalLeader']['name']}({struct['totalLeader']['code']})" in narrative
    assert doc["questionSetVersion"] == "v7"


# ══════════════════════════════════════════════════════════════════════════════
# v7（2026-10-20）全语料盘点 + 瘦身增益
# 预注册：docs/hotlist-jev/jev-relay-v7-preregistration.md
# ══════════════════════════════════════════════════════════════════════════════


def _frame_indices(date, indices):
    """15:00 帧夹具（v7 D2：带 indices/indexExtra）。"""
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2,
            "limitSummary": {"zhaban": {"ztCount": 50, "count": 0, "rate": 0.0}},
            "indices": indices}


def test_market_index_line_seven_indices():
    """D2：大盘指数行 7 指数全渲染（changePct 口径，zhaban broad_market/relay_index 对照锚）。"""
    idx = {"sh": {"change": -12.3, "changePct": -0.35},
           "hs300": {"change": -8.1, "changePct": -0.21},
           "zz500": {"change": -12.9, "changePct": -0.27},
           "zz1000": {"change": -10.5, "changePct": -0.15},
           "indexExtra": {"szcz": {"change": -40.2, "changePct": -0.38},
                          "cybz": {"change": -88.9, "changePct": -1.56},
                          "kc50": {"change": 6.7, "changePct": 0.07}}}
    db = FakeDb({"snapshot_frames": FakeCol([_frame_indices(_D0, idx)])})
    line = relay.market_index_line(db, _D0)
    assert line.startswith("大盘指数：")
    for frag in ("上证 -0.35%", "深证成指 -0.38%", "沪深300 -0.21%", "中证500 -0.27%",
                 "中证1000 -0.15%", "创业板指 -1.56%", "科创50 +0.07%"):
        assert frag in line, frag
    assert "未采集" not in line and "点位口径" not in line and "不可算" not in line


def test_market_index_line_old_frame_degrades_to_four():
    """D2 fail-visible：历史帧无 indexExtra → 4 指数 + 「该日未采集」注（不补 0）。"""
    idx = {"sh": {"change": -12.3, "changePct": -0.35},
           "hs300": {"change": -8.1, "changePct": -0.21}}
    db = FakeDb({"snapshot_frames": FakeCol([_frame_indices(_D0, idx)])})
    line = relay.market_index_line(db, _D0)
    assert "上证 -0.35%" in line and "沪深300 -0.21%" in line
    assert "深证成指/创业板指/科创50 该日未采集" in line
    assert "-0.38%" not in line and "-1.56%" not in line


def test_market_index_line_point_only_degrades():
    """D2：changePct 缺失 → 点位口径显式标注（不拿点位冒充百分比，10-12 教训）。"""
    idx = {"sh": {"change": -12.3},
           "indexExtra": {"szcz": {"change": -40.2}}}
    db = FakeDb({"snapshot_frames": FakeCol([_frame_indices(_D0, idx)])})
    line = relay.market_index_line(db, _D0)
    assert "上证 -12.30点（点位口径）" in line and "深证成指 -40.20点（点位口径）" in line
    assert "% ｜" not in line


def test_market_index_line_missing_frame_fail_visible():
    db = FakeDb({"snapshot_frames": FakeCol([])})
    line = relay.market_index_line(db, _D0)
    assert line.startswith("大盘指数：不可算")


def test_anchor_lines_drop_sentiment_keep_objective_anchor():
    """D1：删热榜 slot/EOD 叙事两行（全叙事唯一「另一模型结论」混入点，七题判据零引用），
    保留近20日锚（relay_index/phase/ladder 坐标系）。"""
    db = _db()
    db.cols["hotlist_jev_sentiment"] = FakeCol([
        {"tradingDate": _D0, "kind": "slot", "status": "ok", "slotTime": "15:00",
         "answers": {"frame_stage": {"choice": "ferment"},
                     "temperature": {"score": 5.6},
                     "crowding": {"choice": "breadth_climax"}}},
        {"tradingDate": _D1, "kind": "eod", "status": "ok",
         "answers": {"day_stage": {"choice": "climax"}, "day_pattern": {"choice": "wide_swing"}},
         "scores": {"day_temperature": 68.0}},
    ])
    lines = relay.anchor_lines(db, _D0)
    text = "\n".join(lines)
    assert "热榜叙事轨迹" not in text and "EOD 叙事" not in text
    assert "ferment" not in text and "climax" not in text
    assert any(l.startswith("【近20日参照锚") for l in lines)
    assert any(l.startswith("近20日锚") for l in lines)


def test_anchor_lines_percentile_scale():
    """D4：锚段补分位刻度（晋级率/炸板/断板中位/溢价的 P20/P50/P80），
    relay_index「参照带中高位」自此有刻度（对齐温度题锚定法）。"""
    hist = [{"date": f"2026-09-{d:02d}", "promo": 10.0 + d % 5, "zhaban": 15 + d % 7,
             "broken_median": -1.0 - (d % 3), "premium_median": -0.2 + (d % 5) * 0.1}
            for d in range(1, 21)]
    lines = relay.anchor_lines(_db(), _D0, money_hist=hist)
    scale = next(l for l in lines if "分位刻度" in l)
    for axis in ("晋级率", "炸板家数", "断板中位", "隔日溢价"):
        assert axis in scale, axis
    assert "P20" in scale and "P50" in scale and "P80" in scale
    assert "有效 20/20" in scale


def test_anchor_lines_percentile_insufficient_fail_visible():
    """D4 fail-visible：历史样本 <10 → 刻度行写不可算（percentile_fraction 门槛），不补 0。"""
    hist = [{"date": f"2026-09-{d:02d}", "promo": 10.0 + d, "zhaban": 15 + d,
             "broken_median": -1.0, "premium_median": 0.1} for d in range(1, 6)]
    lines = relay.anchor_lines(_db(), _D0, money_hist=hist)
    scale = next(l for l in lines if "分位刻度" in l)
    assert "不可算" in scale and "有效 5/5" in scale
    assert "P20" not in scale


def test_relay_flow_line_money_percentile(monkeypatch):
    """D3：断板中位/大面/隔日溢价各带近 20 日分位（此前钱效只有昨日一个对照点）。"""
    bars = {
        "600004": [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}],    # 今日断板 -10%
        "600001": [{"date": _D1, "close": 20.0}, {"date": _D0, "close": 20.4}],   # 晋级 +2%
        "600002": [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}],
        "600003": [{"date": _D2, "close": 20.0}, {"date": _D1, "close": 20.2}],
    }
    today_fillers = [{"code": f"6010{i}", "name": f"TF{i}", "num": "2天2板"} for i in range(1, 5)]
    yest_fillers = [{"code": f"6011{i}", "name": f"YF{i}", "num": "2天2板"} for i in range(1, 4)]
    for s in today_fillers:
        bars[s["code"]] = [{"date": _D1, "close": 10.0}, {"date": _D0, "close": 9.0}]
    for s in yest_fillers:
        bars[s["code"]] = [{"date": _D2, "close": 10.0}, {"date": _D1, "close": 9.5}]
    monkeypatch.setattr(relay, "_daily_bars", lambda code: bars.get(code, []))
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D1: [], _D0: []}),
        "jiuyan_action": FakeCol([_final(_D2, _STOCKS[_D2] + yest_fillers),
                                  _final(_D1, _STOCKS[_D1] + today_fillers),
                                  _final(_D0, _STOCKS[_D0])]),
    })
    hist = [{"date": f"2026-09-{d:02d}", "promo": 10.0 + d, "zhaban": 15 + d,
             "broken_median": -1.0 - (d % 3) * 0.5, "big": 1 + d % 4,
             "premium_median": -0.2 + (d % 5) * 0.1} for d in range(1, 21)]
    line = relay_flow_line(db, _D0, money_hist=hist)
    assert "钱效近20日分位（20 日）" in line
    assert "断板中位 P" in line and "大面 P" in line and "隔日溢价 P" in line


def test_relay_flow_line_money_percentile_skipped_when_hist_short():
    """D3 fail-visible：历史 <10 日 → 不输出分位（不伪刻度），叙事其余部分不受影响。"""
    hist = [{"date": f"2026-09-{d:02d}", "promo": 10.0, "zhaban": 15,
             "broken_median": -1.0, "premium_median": 0.1} for d in range(1, 4)]
    line = relay_flow_line(_db(), _D0, money_hist=hist)
    assert "钱效近20日分位" not in line


def test_ladder_structure_prev_layers():
    """D6：昨日梯队分层家数入语料——ladder fracture「二板较昨日腰斩」判据自此可验。"""
    line = ladder_structure_line(_db(), _D0)
    assert "昨日梯队：一板 1/二板 0/三板+ 1" in line


def test_relay_trajectory_title_and_swing_aligned():
    """D6：段名对齐判据引用名【近10日连板轨迹】——近10日=今日+近9日（与高位轨迹段
    「近10个交易日」同规）；摆动锚窗口同步 10 日。"""
    dates = [f"2026-09-{d:02d}" for d in range(11, 21)] + ["2026-09-30"]
    finals = [_final(d, _STOCKS[_D0]) for d in dates]
    db = FakeDb({"snapshot_frames": _frames(dates), "jiuyan_action": FakeCol(finals)})
    line = relay.relay_trajectory_line(db, dates[-1])
    assert line.startswith("近10日连板轨迹（含今日")
    assert "近11日连板轨迹" not in line
    assert "近10个交易日涨停峰值" in line


def test_theme_evidence_lines_top3_boards():
    """D5：题材证据块（韭研产业树+投资日历确定性拼装，top3 板块）注入题材段；
    未映射板块如实标注，不做模糊猜测。"""
    boards = {"机器人": [{"code": "600001", "name": "A", "num": "4天4板", "time": "09:25"}],
              "低空经济": [{"code": "600002", "name": "B", "num": "3天3板", "time": "09:44"}],
              "公告": [{"code": "600003", "name": "C"}]}
    db = FakeDb({
        "jiuyan_action": FakeCol([_final_multi(_D0, boards)]),
        "jiuyan_timeline": FakeCol([
            {"_id": "t1", "date": "2026-10-01", "title": "英伟达GTC大会",
             "content": "黄仁勋发表主题演讲，发布物理AI机器人平台",
             "grade": 5, "themes": ["机器人"], "firstSeenDate": "2026-09-29",
             "lastFetchDate": "2026-09-30"},
        ]),
        "jiuyan_ai_industry": FakeCol([
            {"_id": "i1", "code": "n1", "name": "机器人", "level": 2,
             "content": "2026年9月25日，特斯拉已将Optimus人形机器人产量扩大到约10倍",
             "hot": 19.11, "contentChangedDate": "2026-09-30",
             "lastFetchDate": "2026-09-30"},
        ]),
    })
    lines = relay.theme_evidence_lines(db, _D0)
    text = "\n".join(lines)
    assert "题材证据（韭研产业树+投资日历" in lines[0] and "top3" in lines[0]
    assert "取数日 2026-09-30" in lines[0]
    assert "板块级催化原文（韭研产业树「机器人」" in text
    assert "未来 3 日既定事件" in text and "英伟达GTC大会" in text
    # 公告=粗分桶（NOT_A_THEME）→ 未映射如实标注
    assert "未映射" in text and "不代表无催化" in text


def test_theme_evidence_lines_corpus_missing_fail_visible():
    """D5 fail-visible：题材语料未采集（2026-10-20 起才有）→ 显式标注，并计入
    anchorGapsDerived（子项缺位，不抬主锚徽标）。"""
    db = FakeDb({"jiuyan_action": FakeCol(
        [_final_multi(_D0, {"机器人": [{"code": "600001", "name": "A"}]})])})
    lines = relay.theme_evidence_lines(db, _D0)
    assert len(lines) == 1
    assert "语料未采集" in lines[0] and "无催化" in lines[0]
    assert anchor_gaps_derived("\n".join(lines)) == ["题材证据"]


def test_sector_lines_sustain_baseline():
    """D5：板块接力链段尾增同桶隔日连板基线行（结构基线单一事实源
    theme_leader_baseline；主线甲板块龙一甲A=4板/2家/早封 → 组合桶 62.5%）。"""
    struct = relay.relay_structure(_sector_db(), _D0)
    lines = relay.sector_relay_lines(struct)
    line = next(l for l in lines if "同桶隔日连板基线" in l)
    assert "甲A" in line and "62.5%（8 样本）" in line
    assert "总体 34.3%（341 样本" in line
    assert "2026-08-01~10-19" in line


def test_sector_lines_sustain_baseline_streak_unknown():
    """D5 fail-visible：主线龙一真连板不可算 → 桶不可定位，只给总体基线，不猜桶。"""
    struct = relay.relay_structure(_sector_db(), _D0)
    struct["mainline"]["sustain"]["streak"] = None
    lines = relay.sector_relay_lines(struct)
    line = next(l for l in lines if "同桶隔日连板基线" in l)
    assert "桶不可定位（真连板不可算）" in line and "总体 34.3%" in line
    assert "62.5%" not in line


def test_sector_lines_sustain_baseline_caliber_sealed_and_streak():
    """D5 评审修复：同桶基线桶键与 SUSTAIN 表同口径（封板二分 + 真连板序）。

    旧实现拿 struct 的 dragon（区间 M 序）+ d0Count（触板池全量）入桶：
    炸板股被算进「板块家数」、M 序龙一的 streak/time 冒充真连板龙一——桶键错口径
    = 同桶不同桶。修复后：炸板股不入家数、龙一取真连板最高（rank_board_stocks
    单源），THS 池缺失日按触板口径并披露。
    """
    boards = {
        _D2: {"甲板块": [{"code": "600502", "name": "龙Y", "num": "1天1板", "time": "09:40"}]},
        _D1: {"甲板块": [{"code": "600502", "name": "龙Y", "num": "2天2板", "time": "09:40"}]},
        _D0: {"甲板块": [
            # 妖股X：M 序第一（14天10板）但今日炸板（进 failed 池，不封板）
            {"code": "600501", "name": "妖X", "num": "14天10板", "time": "09:35"},
            {"code": "600502", "name": "龙Y", "num": "3天3板", "time": "09:40"}]},
    }
    db = FakeDb({
        "snapshot_frames": _frames([_D2, _D1, _D0], failed_by_date={_D0: ["600501"]}),
        "jiuyan_action": FakeCol([_final_multi(d, boards[d]) for d in (_D2, _D1, _D0)]),
        "snapshot_stock_rows": FakeCol([]),
        "hotlist_jev_driver_labels": FakeCol([]),
        "hotlist_jev_sentiment": FakeCol([]),
    })
    struct = relay.relay_structure(db, _D0)
    sus = struct["mainline"]["sustain"]
    # 桶键=封板口径：妖X 炸板不入家数（boardN=1）；龙一=真连板序（龙Y streak 3）
    assert sus["boardN"] == 1 and sus["streak"] == 3 and sus["name"] == "龙Y"
    lines = relay.sector_relay_lines(struct)
    line = next(l for l in lines if "同桶隔日连板基线" in l)
    assert "龙Y" in line and "妖X" not in line
    # (3, 1-2, early) 无组合桶 → 按高度档回退 46.2%；旧口径 (1, 2家) 会给 19.2%
    assert "46.2%（39 样本）" in line and "19.2%" not in line


def test_money_hist_series_skips_day_with_missing_final():
    """D3/D4 评审修复：历史日韭研 final 缺失 → 该日整体不入钱效序列。

    旧实现 cur 池缺失时 cur_zt=空集 → promo 落 0.0 + 断板=昨日全池（伪造），
    污染 20 日分位刻度与钱效分位（§4.0：不可算 ≠ 0 晋级）。
    """
    d4, d3, d2, d1 = "2026-09-25", "2026-09-26", "2026-09-27", "2026-09-28"
    finals = [
        _final_multi(d4, {"甲": [{"code": "600601", "name": "A", "num": "1天1板"}]}),
        _final_multi(d3, {"甲": [{"code": "600601", "name": "A", "num": "2天2板"}]}),
        # d2 韭研 final 缺失（采集失败日）
        _final_multi(d1, {"甲": [{"code": "600602", "name": "B", "num": "1天1板"}]}),
    ]
    db = FakeDb({"snapshot_frames": _frames([d4, d3, d2, d1]),
                 "jiuyan_action": FakeCol(finals)})
    rows = relay._money_hist_series(db, _D0)
    # 只有 d3 一日两头齐全（d4 无前日、d2 缺 final、d1 前日=d2 缺 final）
    assert [r["date"] for r in rows] == [d3]
    assert rows[0]["promo"] == 100.0      # A 昨日封板今日仍封板
    assert all(r["promo"] != 0.0 for r in rows)  # 无伪造 0 晋级日


def test_questions_v7_criteria_revisions():
    """D7：判据修订四处——ladder 补 balanced 过渡档、momentum 冲突消解序、
    theme_pulse 主线双定义消歧、money_effect 线化 + relay_index 锚定句。"""
    lh = QUESTIONS_RELAY["ladder_health"]["criteria"]
    assert "balanced" in lh and "0.5" in lh["balanced"] and "1.5" in lh["balanced"]
    assert "断板亏钱与炸板面证据定档" in QUESTIONS_RELAY["relay_momentum"]["instructions"]
    assert "三日存活口径" in QUESTIONS_RELAY["theme_pulse"]["instructions"]
    assert "≤-2%" in QUESTIONS_RELAY["money_effect"]["criteria"]["losing"]
    assert "近20日分位" in QUESTIONS_RELAY["money_effect"]["criteria"]["losing"]
    assert "分位刻度" in QUESTIONS_RELAY["relay_index"]["instructions"]
    # 版本与题数：v7 仍七题一 call（第八题暂缓，门=theme-leader pilot 过验收）
    from backend.analysis.hotlist.jev_relay_ammo import QUESTION_SET_VERSION_RELAY
    assert QUESTION_SET_VERSION_RELAY == "v7"
    assert len(QUESTIONS_RELAY) == 7

