# -*- coding: utf-8 -*-
"""板块节点 v1 判据测试（预登记 docs/hotlist-jev/sector-nodes-v1-preregistration.md §三）。

纯函数层测试（analysis/hotlist/sector_nodes.assemble_rows），零 DB 零模型调用；
逐档规则 + fail-visible（参照日池缺失/龙头不可考/晋级链不可算不伪 0、不伪判）。
"""
from __future__ import annotations

from backend.analysis.hotlist.sector_nodes import (
    NODE_LABELS_CN,
    SECTOR_NODE_VERSION,
    assemble_rows,
)

D0, D1, D2 = "2026-10-23", "2026-10-22", "2026-10-21"


def _row(board: str = "AI算力", n: int = 3, streak: int | None = 2,
         first: int | None = None, **over) -> dict:
    """day_leader_rows 真实行形状（平铺 code/name/streak/time，非嵌套 leader）。"""
    shape = {"first": (n - 1) if first is None else first,
             "two": 1 if (streak or 0) >= 2 else 0,
             "threePlus": 1 if (streak or 0) >= 3 else 0, "unknown": 0}
    row = {"board": board, "boardN": n,
           "code": "600001" if n > 0 else None, "name": "龙头股" if n > 0 else None,
           "streak": streak if n > 0 else None, "time": "09:31:00" if n > 0 else None,
           "ladderShape": shape, "secondStreak": 1,
           "zhabanN": 0, "prevZhabanN": None, "prevTotal": None, "prevStill": None}
    row.update(over)
    return row


def _hist(entries: list[tuple[str, int]], board: str = "AI算力") -> dict:
    return {board: list(entries)}


def _assemble(**kw) -> dict:
    args = dict(date=D0, today_rows=[_row(n=3)], prev_rows=[_row(n=3)], prev_date=D1,
                prev2_rows=[_row(n=2)], prev2_date=D2,
                count_hist=_hist([(D2, 2), (D1, 3)]),
                prom={"ok": True, "byBoard": {"AI算力": 1}, "ge2ByBoard": {"AI算力": 0}},
                leader_status={"AI算力": "sealed"},
                prev_nodes={"AI算力": "normal"})
    args.update(kw)
    return assemble_rows(**args)


def _node_of(out: dict, board: str = "AI算力") -> dict:
    rows = [r for r in out["rows"] if r["board"] == board]
    assert rows, f"板块 {board} 不在行集：{[r['board'] for r in out['rows']]}"
    return rows[0]


# ── 逐档规则（预登记 §三 优先级序） ─────────────────────────────────────────

def test_wzs_leader_branch():
    """弱转强·龙头分支：昨日转弱 → 家数回升+晋级+龙头续板。"""
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    prev_nodes={"AI算力": "weakening"})
    r = _node_of(out)
    assert r["node"] == "wzs"
    assert any("弱转强" in b or "转弱" in b for b in r["basis"])
    assert any("家数 5→6" in b for b in r["basis"])


def test_wzs_first_board_branch():
    """弱转强·首板分支：龙头断板但首板 ≥ 昨日×2（板块内换血式修复）。"""
    out = _assemble(today_rows=[_row(n=6, streak=1, first=4)],
                    prev_rows=[_row(n=5, first=2)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    leader_status={"AI算力": "broken"},
                    prev_nodes={"AI算力": "collapse"})
    r = _node_of(out)
    assert r["node"] == "wzs"
    assert any("首板 4 家" in b for b in r["basis"])


def test_no_wzs_when_prev_not_weak():
    """防伪：昨日非弱势（主升）不贴弱转强标——延续强归主升/发酵。"""
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    prev_nodes={"AI算力": "mainline"})
    assert _node_of(out)["node"] != "wzs"


def test_collapse():
    out = _assemble(today_rows=[_row(n=2, streak=None)], prev_rows=[_row(n=6)],
                    count_hist=_hist([(D2, 5), (D1, 6)]),
                    leader_status={"AI算力": "broken"},
                    prom={"ok": True, "byBoard": {"AI算力": 0}, "ge2ByBoard": {}},
                    prev_nodes={"AI算力": "weakening"})
    r = _node_of(out)
    assert r["node"] == "collapse"
    assert any("腰斩" in b for b in r["basis"]) and any("晋级 0" in b for b in r["basis"])


def test_ice_zero_and_one():
    out = _assemble(today_rows=[], prev_rows=[_row(n=3)])
    r = _node_of(out)
    assert r["count"] == 0 and r["node"] == "ice"
    assert any("今日该板块无封板" in n for n in r["notes"])
    out2 = _assemble(today_rows=[_row(n=1, streak=None)], prev_rows=[_row(n=1)],
                     count_hist=_hist([(D2, 1), (D1, 1)]),
                     leader_status={"AI算力": "broken"},
                     prom={"ok": True, "byBoard": {"AI算力": 0}, "ge2ByBoard": {}})
    # n1=1 不构成腰斩（2×1>1）→ 退潮不命中，落冰点第二分支（≤1 家且龙头断板、晋级 0）
    assert _node_of(out2)["node"] == "ice"


def test_weakening_by_count_drop():
    out = _assemble(today_rows=[_row(n=4)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 5), (D1, 5)]))
    r = _node_of(out)
    assert r["node"] == "weakening"
    assert any("家数 5→4 回落" in b for b in r["basis"])


def _hist20(board: str = "AI算力") -> dict:
    vals = [4, 4, 4, 5, 5, 5, 4, 4, 5, 4, 5, 5, 4, 5, 4, 4, 5, 5, 4, 5]
    return {board: [(f"2026-09-{i + 1:02d}", v) for i, v in enumerate(vals)]}


def test_mainline_percentile():
    # n1/n2 按 count_hist 内的日期取值：历史序列须覆盖 D1（昨日 8 家）
    hist = _hist20()
    hist["AI算力"] = hist["AI算力"] + [(D2, 5), (D1, 8)]
    out = _assemble(today_rows=[_row(n=9)], prev_rows=[_row(n=8)],
                    count_hist=hist,
                    prom={"ok": True, "byBoard": {"AI算力": 3}, "ge2ByBoard": {"AI算力": 2}})
    r = _node_of(out)
    assert r["node"] == "mainline"
    assert r["countPct"] is not None and r["countPct"] >= 0.8
    assert any("二板以上晋级 2" in b for b in r["basis"])


def test_mainline_abs_fallback_when_pct_na():
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}})
    r = _node_of(out)
    assert r["node"] == "mainline"
    assert any("分位样本不足" in n for n in r["notes"])


def test_fermenting():
    out = _assemble(today_rows=[_row(n=7)], prev_rows=[_row(n=4)], prev2_rows=[_row(n=2)],
                    count_hist=_hist([(D2, 2), (D1, 4)]))
    assert _node_of(out)["node"] == "fermenting"


def test_brewing():
    """冒头：前日 ≤1 家、今日 ≥3 家；1→2→3 的缓爬归发酵（递增优先）。"""
    out = _assemble(today_rows=[_row(n=4)], prev_rows=[_row(n=1)], prev2_rows=[_row(n=1)],
                    count_hist=_hist([(D2, 1), (D1, 1)]))
    assert _node_of(out)["node"] == "brewing"
    out2 = _assemble(today_rows=[_row(n=3)], prev_rows=[_row(n=2)], prev2_rows=[_row(n=1)],
                     count_hist=_hist([(D2, 1), (D1, 2)]))
    assert _node_of(out2)["node"] == "fermenting"


def test_normal():
    out = _assemble(today_rows=[_row(n=3)], prev_rows=[_row(n=3)],
                    count_hist=_hist([(D2, 3), (D1, 3)]))
    r = _node_of(out)
    assert r["node"] == "normal"


# ── fail-visible（不伪 0 / 不伪判） ─────────────────────────────────────────

def test_prom_unavailable_blocks_prom_branches():
    """晋级链不可算：弱转强/退潮/主升不命中（不把缺料当 0 晋级）。"""
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": False, "reason": "韭研 final 缺失", "byBoard": {}, "ge2ByBoard": {}},
                    prev_nodes={"AI算力": "weakening"})
    r = _node_of(out)
    assert r["node"] != "wzs" and r["promN"] is None
    assert any("晋级链不可算" in n for n in r["notes"])


def test_suspended_leader_is_not_broken():
    """停牌不算断板（v4 裁决）：腰斩+停牌 → 转弱（家数回落）而非退潮。"""
    out = _assemble(today_rows=[_row(n=2)], prev_rows=[_row(n=6)],
                    count_hist=_hist([(D2, 5), (D1, 6)]),
                    leader_status={"AI算力": "suspended"},
                    prom={"ok": True, "byBoard": {"AI算力": 0}, "ge2ByBoard": {}})
    r = _node_of(out)
    assert r["node"] == "weakening"
    assert r["leaderState"] == "suspended"


def test_prev_pool_missing_n1_none():
    """昨日池缺失 → n1 不可考（None），涉 n1 判据不命中并注记。"""
    out = _assemble(prev_rows=None, today_rows=[_row(n=3)])
    r = _node_of(out)
    assert r["prevCount"] is None
    assert any("昨日 THS 池缺失" in n for n in r["notes"])
    assert r["node"] == "normal"


def test_prev_doc_missing_blocks_wzs():
    """昨日节点文档缺失 → 弱转强不贴标（转折强才是真强，无昨日证据不冒进）。"""
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    prev_nodes=None)
    r = _node_of(out)
    assert r["node"] != "wzs"
    assert any("昨日节点不可考" in n for n in r["notes"])


def test_ths_missing_whole_day_degraded():
    """今日 THS 池缺失 → 整日降级显式落痕；节点=unknown、家数 None，不伪装成冰点。"""
    out = _assemble(today_rows=None, prev_rows=[_row(n=3)])
    assert any("THS 池缺失" in d for d in out["degraded"])
    r = _node_of(out)
    assert r["node"] == "unknown" and r["count"] is None and r["countPct"] is None
    assert any("节点不可判" in n for n in r["notes"])
    assert any("根因：THS 池缺失" in n for n in r["notes"])


def test_final_missing_same_degraded_path():
    """审计 P2-2：韭研 final 缺失但 THS ok（空列表形态由 operations 置 None）
    → 与 THS 缺失同款降级，根因注记区分，绝不判全场冰点。"""
    out = _assemble(today_rows=None, prev_rows=[_row(n=3)],
                    today_unavailable_reason="韭研 final 缺失/为空，板块家数不可考")
    assert any("韭研 final 缺失" in d for d in out["degraded"])
    r = _node_of(out)
    assert r["node"] == "unknown" and r["count"] is None
    assert any("根因：韭研 final 缺失" in n for n in r["notes"])


def test_index_anchor_placeholder():
    """板块指数锚二期：恒 None，前端/读口显式「未接入」，不伪装成 0。"""
    out = _assemble()
    assert all(r["indexAnchor"] is None for r in out["rows"])


def test_labels_and_version():
    assert SECTOR_NODE_VERSION == "v1"
    assert NODE_LABELS_CN["wzs"] == "弱转强" and NODE_LABELS_CN["collapse"] == "退潮"


# ── V2 影子聚合（预登记 sector-nodes-v2-aggregate §二/§三，判据零参与） ──────

from backend.analysis.hotlist.sector_agg import (
    AGG_VERSION,
    aggregate_day,
    assemble_agg_rows,
    member_union,
)


def _pool_list():
    """窗口池：D2 5 家 / D1 3 家 / D0 2 家，AI算力成员部分重叠。"""
    return [
        (D0, {"AI算力": {"600001", "600002"}, "机器人": {"700001"}}),
        (D1, {"AI算力": {"600001", "600003", "600004"}}),
        (D2, {"AI算力": {"600001", "600003", "600005", "600006", "600007"}}),
    ]


def _bars_by_code():
    """成员日线棒：600001 三日连续 +2%/-1%；600002 缺今日棒（missingN）；600003 首棒即 D0（无昨收）。"""
    bars = {
        "600001": [{"date": D2, "close": 10.0}, {"date": D1, "close": 10.2},
                   {"date": D0, "close": 10.4}],
        "600002": [{"date": D2, "close": 5.0}, {"date": D1, "close": 5.1}],
        "600003": [{"date": D0, "close": 8.0}],
        "600004": [{"date": D2, "close": 20.0}, {"date": D1, "close": 19.0},
                   {"date": D0, "close": 18.95}],   # D0 -0.26%
        "600005": [{"date": D2, "close": 4.0}, {"date": D1, "close": 4.2},
                   {"date": D0, "close": 4.62}],    # D0 +10%
        "600006": [{"date": D2, "close": 9.0}, {"date": D1, "close": 8.6},
                   {"date": D0, "close": 8.5}],     # D0 -1.16%
        "600007": [{"date": D2, "close": 3.0}, {"date": D1, "close": 3.0},
                   {"date": D0, "close": 3.0}],     # D0 0%
        "700001": [{"date": D2, "close": 6.0}, {"date": D1, "close": 6.3},
                   {"date": D0, "close": 6.9}],     # D0 +9.52%
    }
    return bars


def test_member_union_n5_n10_short_window():
    """N5 窗 > 可得 3 日 → 如实缩短 windowDays=3 并 daysShort；并集去重正确。"""
    u5 = member_union("AI算力", _pool_list(), 5)
    assert u5["windowDays"] == 3 and u5["daysShort"] is True
    assert u5["codes"] == {"600001", "600002", "600003", "600004", "600005", "600006", "600007"}
    u10 = member_union("机器人", _pool_list(), 10)
    assert u10["codes"] == {"700001"} and u10["daysShort"] is True


def test_aggregate_day_missing_no_fake_zero():
    """缺棒/无昨收成员剔除统计 + missingN 披露；不伪装。"""
    u = member_union("AI算力", _pool_list(), 5)
    out = aggregate_day(target_date=D0, members=u["codes"],
                        bars_by_code=_bars_by_code(), window_days=u["windowDays"])
    assert out["memberN"] == 7 and out["quotedN"] == 5 and out["missingN"] == 2
    # quoted: 600001 +1.96%, 600004 -0.26%, 600005 +10.0%, 600006 -1.16%, 600007 0%
    assert out["pctMean"] == round((1.9608 + (-0.2632) + 10.0 + (-1.1628) + 0.0) / 5, 2)
    assert out["redRatio"] == round(2 / 5, 3)


def test_aggregate_day_all_missing_none():
    """全成员缺棒 → 统计值 None（不落伪 0），missingN=memberN。"""
    out = aggregate_day(target_date=D0, members={"999999"},
                        bars_by_code={}, window_days=3)
    assert out["pctMean"] is None and out["pctMedian"] is None and out["redRatio"] is None
    assert out["missingN"] == 1 and out["quotedN"] == 0


def test_assemble_agg_rows_coverage_n10_superset():
    """行覆盖 = N10 并集（含今日无封板板块）；aggN5 ⊆ aggN10 行集；空池板块缺席。"""
    rows = assemble_agg_rows(target_date=D0, window_pool=_pool_list(),
                             bars_by_code=_bars_by_code())
    boards = {r["board"] for r in rows}
    assert boards == {"AI算力", "机器人"}
    ai = next(r for r in rows if r["board"] == "AI算力")
    assert ai["aggN5"]["windowDays"] == 3 and ai["aggN10"]["windowDays"] == 3
    assert ai["aggN5"]["memberN"] == 7 and ai["aggN10"]["memberN"] == 7
    # 机器人今日无封板照样有聚合读数（弱转强前兆观察位）
    ro = next(r for r in rows if r["board"] == "机器人")
    assert ro["aggN5"]["pctMean"] == 9.52


def test_aggregate_day_empty_window_pool():
    """窗口池全缺 → assemble 空行集（operations 层不再挂载，不伪 0）。"""
    assert assemble_agg_rows(target_date=D0, window_pool=[],
                             bars_by_code={}) == []


def test_agg_version_frozen():
    """版本戳冻结（影子列口径变更须新戳+用户批准）。"""
    assert AGG_VERSION == "2026-10-24a"
