# -*- coding: utf-8 -*-
"""2026-11-18 跨源口径核查修复回归（天普停牌案 + 阳光照明末封案，用户裁决 1/2/3）。

① 停牌三态单源链：_bar_verdict 零成交额伪棒 → day_status_of → 节点台账三态 →
   theme 叙事分支/relay 回退（停牌不算断板 v4 裁决，不伪装断板反包候选）；
② 末封=末次封板事件棒（末段连续封住 run 起始棒），非末根收盘封住棒；
③ 首触/末封「棒」字自明口径（TDX 5 分钟棒末时刻标记，当日首棒 09:35 实证）。
全 mock/纯函数，零 jev 真调（AGENTS §1.2-7）；新叙事行过 hygiene 黑名单（§1.2-8）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_label_jiuyan as runner
from backend.operations import theme_leader_label as L
from backend.analysis.hotlist import theme_leader_ammo as A
from backend.analysis.hotlist.jev_driver_ammo import board_shape_line_from_bars
from backend.analysis.hotlist.sector_nodes import SECTOR_NODE_VERSION
from tests.hotlist.test_narrative_hygiene import _assert_clean
from tests.hotlist.test_leader_wzs import _call as wzs_call

D0 = "2026-11-17"


# ── ① 停牌伪棒单源（_bar_verdict / day_status_of）──

def _pseudo_bars():
    """天普 605255 实数据形状：11-13 四板真棒 + 11-17 线上补尾伪棒（平收/额≈0 垃圾值）。"""
    return [{"date": "2026-11-13", "close": 73.82, "high": 73.82, "amount": 1.79e8},
            {"date": D0, "close": 73.82, "high": 73.82, "amount": 5.877e-39}]


def test_pseudo_bar_zero_amount_is_suspended_not_broken():
    bars = _pseudo_bars()
    adj = {D0: 73.82}
    assert runner._bar_verdict("605255", D0, bars, adj) == "suspended"
    assert runner.day_status_of("605255", D0, sealed=set(), touch=set(),
                                bars=bars, adj=adj) == "suspended"
    # 池权威优先：伪棒不推翻 sealed 集合
    assert runner.day_status_of("605255", D0, sealed={"605255"}, touch=set(),
                                bars=bars, adj=adj) == "sealed"


def test_pseudo_bar_in_touch_list_is_unknown_data_hole():
    """触板名单在册=当日确实交易过→TDX 数据洞 unknown，不猜停牌（宁缺毋猜）。"""
    assert runner.day_status_of("605255", D0, sealed=set(), touch={"605255"},
                                bars=_pseudo_bars(), adj={D0: 73.82}) == "unknown"


def test_amount_none_keeps_legacy_and_real_bar_still_broken():
    bars_none = [{"date": "2026-11-13", "close": 10.0, "amount": None},
                 {"date": D0, "close": 10.5, "amount": None}]
    assert runner._bar_verdict("600000", D0, bars_none, {}) == "broken"
    bars_real = [{"date": "2026-11-13", "close": 10.0, "amount": 1e8},
                 {"date": D0, "close": 10.5, "amount": 2e8}]
    assert runner._bar_verdict("600000", D0, bars_real, {}) == "broken"


# ── ②③ 板型末封事件棒 + 棒字口径──

def _bars5(seq):
    return [{"date": D0, "hm": hm, "open": c, "high": h, "close": c}
            for hm, c, h in seq]


def test_board_shape_last_seal_is_event_bar_not_last_sealed_bar():
    """阳光案：waves0 封板至收盘 → 末封棒=首封棒（旧口径恒 15:00 与炸板 0 次矛盾）。"""
    seq = [("09:35", 10.2, 10.3), ("10:35", 10.6, 10.7), ("10:40", 11.0, 11.0),
           ("10:45", 11.0, 11.0), ("15:00", 11.0, 11.0)]
    line = board_shape_line_from_bars(D0, "600261", None, 10.0, _bars5(seq))
    assert "首触棒 10:40" in line and "末封棒 10:40" in line
    assert "炸板 0 次" in line and "封板至收盘" in line
    assert "末封棒 15:00" not in line


def test_board_shape_last_seal_is_last_reseal_event_bar():
    """waves≥1 封板至收盘：末封棒=末次回封棒（旧口径同样吞掉回封时点恒 15:00）。"""
    seq = [("09:35", 11.0, 11.0), ("09:40", 10.8, 11.0), ("09:45", 11.0, 11.0),
           ("10:00", 10.9, 11.0), ("10:05", 11.0, 11.0), ("15:00", 11.0, 11.0)]
    line = board_shape_line_from_bars(D0, "600261", None, 10.0, _bars5(seq))
    assert "炸板 2 次" in line and "末封棒 10:05" in line
    assert "末封棒 15:00" not in line and "烂板" in line


def test_board_shape_last_seal_broken_close_run_start():
    """收盘未封：末封棒=末段封住 run 起始棒（非末根封住棒）。"""
    seq = [("09:35", 11.0, 11.0), ("09:40", 10.8, 11.0), ("09:45", 11.0, 11.0),
           ("14:55", 11.0, 11.0), ("15:00", 10.9, 11.0)]
    line = board_shape_line_from_bars(D0, "600261", None, 10.0, _bars5(seq))
    assert "末封棒 09:45" in line and "收盘未封" in line


# ── ① 题材叙事三态分支（停牌/数据洞不进入断板反包候选措辞）──

def _susp_row(**over):
    row = {"code": "605255", "name": "天普股份", "dayStatus": "suspended",
           "leaderSealedToday": None, "gain10": 53.95, "resumeDate": "2026-11-19",
           "streak": None, "segment": "main", "poolDay": "2026-11-13"}
    row.update(over)
    return row


def test_suspension_narrative_three_state_not_rewrap_candidate():
    row = _susp_row()
    brief = A._leader_brief(row, "main")
    assert "今日停牌（预计复牌 2026-11-19）" in brief
    assert "10 日涨幅 +54.0%（截至 2026-11-13）" in brief
    assert "断板反包候选" not in brief and "今日未封板" not in brief
    sl = A.structure_line(board="半导体", board_n=4, leader=row,
                          followers_ge_ladder=None, prev_board_n=None,
                          prev_peers=None, prev_total=None, prev_still=None,
                          history=None, leader_sealed_today=None, gain10=53.95)
    assert "今日停牌（预计复牌 2026-11-19）" in sl and "断板反包候选" not in sl
    facts = A.structure_facts_line(row, {"stateCn": "发酵期"})
    assert "今日已封板=停牌（无交易）" in facts
    sq = A.seal_quality_line([{"label": "主板龙一 天普股份", "item": None,
                               "unsealed": False, "dayStatus": "suspended"}])
    assert "今日停牌（无交易）" in sq


def test_suspension_without_resume_date_not_fabricated():
    brief = A._leader_brief(_susp_row(resumeDate=None), "main")
    assert "今日停牌（复牌日不可考）" in brief
    assert "预计复牌" not in brief


def test_unknown_day_status_narrative_data_hole():
    row = _susp_row(dayStatus="unknown", resumeDate=None)
    brief = A._leader_brief(row, "main")
    assert "今日续断不可考" in brief
    assert "截至 2026-11-13" in brief and "断板反包候选" not in brief
    assert "今日已封板=不可考" in A.structure_facts_line(row, {})
    sq = A.seal_quality_line([{"label": "主板龙一 天普股份", "item": None,
                               "unsealed": False, "dayStatus": "unknown"}])
    assert "今日续断不可考（无当日封单）" in sq


def test_new_suspension_lines_pass_hygiene_blacklist():
    """§1.2-8 程序性门禁：新增叙事行全块过 FORBIDDEN 黑名单。"""
    for ds in ("suspended", "unknown"):
        row = _susp_row(dayStatus=ds, resumeDate="2026-11-19" if ds == "suspended" else None)
        _assert_clean(A._leader_brief(row, "main"), f"brief-{ds}")
        _assert_clean(A.structure_facts_line(row, {"stateCn": "发酵期"}), f"facts-{ds}")
        _assert_clean(A.seal_quality_line([{"label": "主板龙一 天普股份", "item": None,
                                            "unsealed": False, "dayStatus": ds}]), f"sealq-{ds}")
        _assert_clean(A.structure_line(board="半导体", board_n=4, leader=row,
                                       followers_ge_ladder=None, prev_board_n=None,
                                       prev_peers=None, prev_total=None, prev_still=None,
                                       history=None, leader_sealed_today=None,
                                       gain10=53.95), f"structure-{ds}")


# ── ① 节点单源合并（leaders_for）+ wzs 三态保留──

class _NodeCol:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, q, *a, **k):
        return self.doc


class _NodeDb:
    def __init__(self, doc):
        self.col = _NodeCol(doc)

    def __getitem__(self, k):
        return self.col


def _node_doc(lead):
    return {"status": "ok", "version": SECTOR_NODE_VERSION,
            "rows": [{"board": "半导体", "leader": lead}]}


def _pool_row():
    return {"board": "半导体", "code": "605255", "name": "天普股份",
            "leaderSealedToday": False, "streak": None, "gain10": 53.95,
            "poolDay": None, "days": None, "boards": None}


def _stub_rows(monkeypatch, row):
    monkeypatch.setattr(L, "day_leader_rows",
                        lambda db, date, dataset_id=None, prev_date=None, *,
                        space_mode=False, pool_dates=None: ([row], {}))
    monkeypatch.setattr(L, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: ["2026-11-12", "2026-11-13", "2026-11-16"])


def test_leaders_for_consumes_node_day_status_single_source(monkeypatch):
    lead = {"code": "605255", "name": "天普股份", "streak": None, "time": None,
            "dayStatus": "suspended", "leaderSealedToday": None,
            "poolDay": "2026-11-13", "days": 4, "boards": 4}
    _stub_rows(monkeypatch, _pool_row())
    out, _meta = L.leaders_for(_NodeDb(_node_doc(lead)), D0)
    assert out[0]["dayStatus"] == "suspended"
    assert out[0]["leaderSealedToday"] is None, "停牌三态 None 覆盖池二分 False"
    assert out[0]["poolDay"] == "2026-11-13" and out[0]["boards"] == 4


def test_leaders_for_old_node_doc_keeps_legacy_bool(monkeypatch):
    """旧代节点档无 dayStatus → 不覆盖（历史口径不变，fail-visible 由 relay 回退 unknown）。"""
    lead = {"code": "605255", "name": "天普股份", "streak": None, "time": None}
    _stub_rows(monkeypatch, _pool_row())
    out, _meta = L.leaders_for(_NodeDb(_node_doc(lead)), D0)
    assert out[0]["leaderSealedToday"] is False and "dayStatus" not in out[0]


def test_wzs_leader_row_preserves_none_three_state():
    row = {"date": "2026-10-30", "board": "机器人", "segment": "main",
           "code": "600111", "name": "上海沪工", "streak": None, "time": None,
           "boardN": 3, "othersN": 2, "ladderFollowers": None,
           "prevPeers": 2, "prevBoardN": 2, "prevTotal": 3, "prevStill": 2,
           "zhabanN": 0, "prevZhabanN": 1, "ladderShape": {},
           "secondStreak": 1, "peerCodes": ["600555"], "boardCodes": ["600111"],
           "gain10": 44.4, "leaderSealedToday": None, "poolDay": "2026-10-29",
           "dayStatus": "suspended"}
    pool, _events, _meta = wzs_call(leader_rows=[row])
    hit = next(r for r in pool if r["code"] == "600111")
    assert hit["leaderSealedToday"] is None, "None 不 coerce 成 False 伪装断板"
    assert hit["streak"] is None
    # review M1：停牌/数据洞龙一行不开反包窗（与成员分支同口径，停牌不算断板）
    assert hit["windowK"] is None and hit["windowChanges"] == [], \
        "停牌龙一行不得按断板开反包窗/算窗内序列"
    broken_row = {**row, "leaderSealedToday": False, "dayStatus": "broken"}
    pool_b, _eb, _mb = wzs_call(leader_rows=[broken_row])
    hit_b = next(r for r in pool_b if r["code"] == "600111")
    assert hit_b["windowK"] is not None, "确判断板（is False）反包窗口径不变"


def test_resume_date_picks_latest_suspension_not_list_order():
    """review M2：recent 上游原序无排序保证——按 abnormal_date 最大（≤date）选取，
    多次停牌股不取陈旧复牌日；未来异动日/非停牌记录不参与。"""
    recent = [
        {"abnormal_date": "2026-11-16", "suspended_flag": True, "resume_date": "2026-11-19"},
        {"abnormal_date": "2026-09-01", "suspended_flag": True, "resume_date": "2026-09-05"},
    ]
    assert L._resume_date_from_regulatory(recent, D0) == "2026-11-19"
    assert L._resume_date_from_regulatory(list(reversed(recent)), D0) == "2026-11-19", \
        "不依赖列表顺序"
    assert L._resume_date_from_regulatory(
        [{"abnormal_date": "2026-11-20", "suspended_flag": True, "resume_date": "2026-11-25"}],
        D0) is None, "异动日在后的记录不参与"
    assert L._resume_date_from_regulatory(
        [{"abnormal_date": "2026-11-16", "suspended_flag": False, "resume_date": "2026-11-19"}],
        D0) is None, "非停牌记录不参与"
    assert L._resume_date_from_regulatory([], D0) is None
    assert L._resume_date_from_regulatory(None, D0) is None


def test_seal_quality_suspension_vs_pool_conflict_disclosed():
    """停牌股池档在场＝跨源矛盾显式披露（fail-visible，不静默吞也不渲染无意义封单）。"""
    sq = A.seal_quality_line([{"label": "主板龙一 天普股份",
                               "item": {"pool_state": "sealed", "zt_buy_amount": 123},
                               "unsealed": False, "dayStatus": "suspended"}])
    assert "今日停牌（无交易；池档仍标 sealed）" in sq
    assert "123" not in sq, "停牌日池档封单无判读意义，不渲染质量明细"
    _assert_clean(sq, "sealq-conflict")
    sq2 = A.seal_quality_line([{"label": "主板龙一 天普股份",
                                "item": {"pool_state": "broken"},
                                "unsealed": False, "dayStatus": "unknown"}])
    assert "今日续断不可考（无当日封单；池档仍标 broken）" in sq2
    _assert_clean(sq2, "sealq-conflict-unknown")
