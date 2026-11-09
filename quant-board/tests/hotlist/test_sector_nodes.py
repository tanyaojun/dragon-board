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
    assert SECTOR_NODE_VERSION == "v5"   # v5=板块龙一统一空间龙一（2026-11-09 用户裁决）；v4=池外晋级并入 promN
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


def test_member_union_n10_short_window():
    """N10 窗 > 可得 3 日 → 如实缩短 windowDays=3 并 daysShort；并集去重正确。"""
    u = member_union("AI算力", _pool_list(), 10)
    assert u["windowDays"] == 3 and u["daysShort"] is True
    assert u["codes"] == {"600001", "600002", "600003", "600004", "600005", "600006", "600007"}
    ro = member_union("机器人", _pool_list(), 10)
    assert ro["codes"] == {"700001"} and ro["daysShort"] is True


def test_aggregate_day_missing_no_fake_zero():
    """缺棒/无昨收成员剔除统计 + missingN 披露；不伪装。"""
    u = member_union("AI算力", _pool_list(), 10)
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


def test_assemble_agg_rows_coverage_n10():
    """行覆盖 = N10 并集（含今日无封板板块）；只出 aggN10 单窗；空池板块缺席。"""
    rows = assemble_agg_rows(target_date=D0, window_pool=_pool_list(),
                             bars_by_code=_bars_by_code())
    boards = {r["board"] for r in rows}
    assert boards == {"AI算力", "机器人"}
    ai = next(r for r in rows if r["board"] == "AI算力")
    assert ai["aggN10"]["windowDays"] == 3 and ai["aggN10"]["memberN"] == 7
    assert "aggN5" not in ai and set(ai) == {"board", "aggN10"}
    # 机器人今日无封板照样有聚合读数（弱转强前兆观察位）
    ro = next(r for r in rows if r["board"] == "机器人")
    assert ro["aggN10"]["pctMean"] == 9.52


def test_aggregate_day_empty_window_pool():
    """窗口池全缺 → assemble 空行集（operations 层不再挂载，不伪 0）。"""
    assert assemble_agg_rows(target_date=D0, window_pool=[],
                             bars_by_code={}) == []


def test_agg_version_frozen():
    """版本戳冻结（影子列口径变更须新戳+用户批准；a=V2d 量能锚影子列）。"""
    assert AGG_VERSION == "2026-11-01b"
    from backend.analysis.hotlist.sector_agg import AGG_WINDOWS
    assert AGG_WINDOWS == (10,)


# ── v2 判据（sector-nodes-v2-criteria-preregistration：条款 1/2/3，用户逐条批准） ──

from backend.analysis.hotlist.sector_nodes import SECTOR_NODE_VERSION as _V2


def _agg(pct: float | None = 3.5, red: float | None = 0.8, **over) -> dict:
    a = {"pctMean": pct, "redRatio": red, "quotedN": 10, "missingN": 0,
         "memberN": 12, "windowDays": 10}
    a.update(over)
    return a


def _hand_kw(**over):
    """昨日转弱（n1=5）今日 n0=2 家数未回升 + 晋级 1：分支 3 的 rest 条件底座。"""
    kw = dict(today_rows=[_row(n=2)], prev_rows=[_row(n=5)],
              count_hist=_hist([(D2, 3), (D1, 5)]),
              prom={"ok": True, "byBoard": {"AI算力": 1}, "ge2ByBoard": {"AI算力": 0}},
              leader_status={"AI算力": "broken"},
              prev_nodes={"AI算力": "weakening"})
    kw.update(over)
    return kw


def test_v2_hand_branch_hit():
    """条款 1 分支 3：昨日转弱+今日仍封+晋级+聚合强红 → wzs（家数未回升的资金先手）。"""
    out = _assemble(**_hand_kw(agg_by_board={"AI算力": _agg()}))
    r = _node_of(out)
    assert r["node"] == "wzs"
    assert any("资金先手" in b for b in r["basis"])
    assert any("+3.50%" in b for b in r["basis"])


def test_v2_hand_branch_guards():
    """分支 3 防伪：n0=0 / 翻红<50% / 聚合≤0 各自不命中。"""
    out = _assemble(**_hand_kw(today_rows=[_row(n=0)],
                               agg_by_board={"AI算力": _agg()}))
    assert _node_of(out)["node"] != "wzs"
    out = _assemble(**_hand_kw(agg_by_board={"AI算力": _agg(red=0.4)}))
    assert _node_of(out)["node"] != "wzs"
    out = _assemble(**_hand_kw(agg_by_board={"AI算力": _agg(pct=-1.2)}))
    assert _node_of(out)["node"] != "wzs"
    # 红线：昨日非弱势（normal）不贴先手标（转折强才是真强）
    out = _assemble(**_hand_kw(prev_nodes={"AI算力": "normal"},
                               agg_by_board={"AI算力": _agg()}))
    assert _node_of(out)["node"] != "wzs"


def test_v2_hand_branch_agg_unavailable():
    """条款 3：聚合不可考 → 分支不命中并注记（不伪 0），档位按 v1 规则落转弱。"""
    out = _assemble(**_hand_kw(agg_by_board={"AI算力": _agg(pct=None, red=None)}))
    r = _node_of(out)
    assert r["node"] == "weakening"
    assert any("聚合不可考" in n for n in r["notes"])
    # agg 整体缺席（旧档/未算）同款
    out = _assemble(**_hand_kw(agg_by_board=None))
    assert _node_of(out)["node"] == "weakening"


def test_v2_defense_note_on_collapse_and_ice():
    """条款 2：退潮/冰点命中且聚合仍强 → 注记不改档；聚合弱 → 无注记。"""
    kw = dict(prom={"ok": True, "byBoard": {"AI算力": 0}, "ge2ByBoard": {"AI算力": 0}},
              leader_status={"AI算力": "broken"},
              prev_nodes={"AI算力": "normal"})
    # 腰斩路径 → collapse + 注记
    out = _assemble(today_rows=[_row(n=0)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 4), (D1, 5)]),
                    agg_by_board={"AI算力": _agg(pct=6.4, red=1.0)}, **kw)
    r = _node_of(out)
    assert r["node"] == "collapse"
    assert any("聚合仍强" in n and "防守信号待复核" in n for n in r["notes"])
    # 非腰斩（昨日仅 1 家）→ ice 直落 + 注记
    out = _assemble(today_rows=[_row(n=0)], prev_rows=[_row(n=1)],
                    count_hist=_hist([(D2, 1), (D1, 1)]),
                    agg_by_board={"AI算力": _agg(pct=6.4, red=1.0)}, **kw)
    r = _node_of(out)
    assert r["node"] == "ice"
    assert any("聚合仍强" in n for n in r["notes"])
    out2 = _assemble(today_rows=[_row(n=0)], prev_rows=[_row(n=5)],
                     count_hist=_hist([(D2, 4), (D1, 5)]),
                     prom={"ok": True, "byBoard": {"AI算力": 0}, "ge2ByBoard": {"AI算力": 0}},
                     leader_status={"AI算力": "broken"},
                     prev_nodes={"AI算力": "normal"},
                     agg_by_board={"AI算力": _agg(pct=-2.0, red=0.2)})
    assert not any("聚合仍强" in n for n in _node_of(out2)["notes"])


def test_v2_version_frozen():
    """v2 判据延续（V2d 仅收紧首板分支，资金先手/防守注记不变）。"""
    assert _V2 == "v5"


# ── V2d（sector-nodes-v2d-preregistration） ────────────────────────────────

def test_v2d_first_board_trivial_true_blocked():
    """条款 3：昨日首板=0 时 ×2 恒真的平凡真被消除——龙头断板不再贴 wzs。"""
    out = _assemble(today_rows=[_row(n=6, streak=1, first=4)],
                    prev_rows=[_row(n=5, first=0)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    leader_status={"AI算力": "broken"},
                    prev_nodes={"AI算力": "collapse"})
    assert _node_of(out)["node"] != "wzs"


def test_v2d_first_board_floor_three():
    """条款 3：prev_first=1 时 ×2=2 不再命中（下限 3）；今日首板=3 命中。"""
    kw = dict(today_rows=[_row(n=6, streak=1, first=2)],
              prev_rows=[_row(n=5, first=1)],
              count_hist=_hist([(D2, 3), (D1, 5)]),
              leader_status={"AI算力": "broken"},
              prev_nodes={"AI算力": "collapse"})
    assert _node_of(_assemble(**kw))["node"] != "wzs"
    kw2 = dict(kw, today_rows=[_row(n=7, streak=1, first=3)])
    r = _node_of(_assemble(**kw2))
    assert r["node"] == "wzs"
    assert any("V2d 收紧" in b for b in r["basis"])


def test_v2d_leader_branch_unaffected_by_tightening():
    """条款 3：龙头续板分支与收紧无关，照常命中。"""
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5, first=0)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    leader_status={"AI算力": "sealed"},
                    prev_nodes={"AI算力": "weakening"})
    assert _node_of(out)["node"] == "wzs"


def test_v2d_prom_out_of_pool_shadow():
    """条款 2：池外晋级影子列进 rows + notes 注记；in-pool promN 不变。"""
    prom = {"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1},
            "outByBoard": {"AI算力": 1}, "outGe2ByBoard": {"AI算力": 0},
            "unattributed": ["800001"]}
    out = _assemble(prom=prom)
    r = _node_of(out)
    assert r["promN"] == 2 and r["promGe2"] == 1
    assert r["promOutOfPoolN"] == 1 and r["promOutOfPoolGe2"] == 0
    assert any("池外晋级 1 家" in n for n in r["notes"])


def test_v2d_prom_out_of_pool_zero_no_note():
    """条款 2：无池外晋级不注记；prom 链不可考 → 影子列 None（同 promN 惯例）。"""
    out = _assemble()
    r = _node_of(out)
    assert r["promOutOfPoolN"] == 0 and not any("池外晋级" in n for n in r["notes"])
    out2 = _assemble(prom={"ok": False, "reason": "昨日 final 缺失", "byBoard": {},
                           "ge2ByBoard": {}, "outByBoard": {}, "outGe2ByBoard": {},
                           "unattributed": []})
    r2 = _node_of(out2)
    assert r2["promOutOfPoolN"] is None and r2["promOutOfPoolGe2"] is None


def test_v2d_agg_amount_sum_handcheck():
    """条款 1：amountSum 手算对拍（quoted 成员的当日 amount 合计）；缺棒成员剔除。"""
    bars = {
        "600001": [{"date": D1, "close": 10.0}, {"date": D0, "close": 10.2, "amount": 1.0e8}],
        "600002": [{"date": D1, "close": 5.0}, {"date": D0, "close": 5.1, "amount": 2.0e8}],
        "600003": [{"date": D0, "close": 8.0}],                    # 无昨收 → missing
        "600004": [{"date": D1, "close": 20.0}, {"date": D0, "close": 20.5}],  # 棒在无 amount → absentN
    }
    out = aggregate_day(target_date=D0, members={"600001", "600002", "600003", "600004"},
                        bars_by_code=bars, window_days=10)
    assert out["quotedN"] == 3 and out["missingN"] == 1
    assert out["amountQuotedN"] == 2
    assert out["amountSum"] == 3.0e8
    assert out["amountAbsentN"] == 1


def test_v2d_agg_amount_all_absent_none():
    """条款 1：amount 全缺 → amountSum=None 不伪 0（fail-visible）。"""
    bars = {"600001": [{"date": D1, "close": 10.0}, {"date": D0, "close": 10.2}]}
    out = aggregate_day(target_date=D0, members={"600001"},
                        bars_by_code=bars, window_days=10)
    assert out["amountSum"] is None and out["amountAbsentN"] == 1 and out["amountQuotedN"] == 0


def test_v2d_agg_amount_all_missing_zero_quoted():
    """条款 1：全成员缺棒 → amountSum=None、amountQuotedN=0（不落伪 0）。"""
    out = aggregate_day(target_date=D0, members={"999999"}, bars_by_code={}, window_days=3)
    assert out["amountSum"] is None and out["amountQuotedN"] == 0 and out["amountAbsentN"] == 0


def test_v4_amount_ratio_handcheck():
    """V4 候选原料：amountRatio = 当日成员合计 / 同成员前日合计（同锚前一根棒）。"""
    bars = {
        "600001": [{"date": D1, "close": 10.0, "amount": 1.0e8, "vol": 1.0},
                   {"date": D0, "close": 10.2, "amount": 3.0e8, "vol": 1.0}],
        "600002": [{"date": D1, "close": 5.0, "amount": 1.0e8, "vol": 1.0},
                   {"date": D0, "close": 5.1, "amount": 1.0e8, "vol": 1.0}],
    }
    out = aggregate_day(target_date=D0, members={"600001", "600002"},
                        bars_by_code=bars, window_days=10)
    assert out["amountSum"] == 4.0e8 and out["amountPrevSum"] == 2.0e8
    assert out["amountRatio"] == 2.0
    assert out["amountRatioQuotedN"] == 2


def test_v4_amount_ratio_missing_prev_amount_excluded():
    """前日 amount 缺 → 该成员不进比值样本（ratioQuotedN 缩小），不铸 0；全缺 → None。"""
    bars = {
        "600001": [{"date": D1, "close": 10.0, "amount": 1.0e8},
                   {"date": D0, "close": 10.2, "amount": 3.0e8}],
        "600002": [{"date": D1, "close": 5.0},              # 前日无 amount
                   {"date": D0, "close": 5.1, "amount": 1.0e8}],
    }
    out = aggregate_day(target_date=D0, members={"600001", "600002"},
                        bars_by_code=bars, window_days=10)
    assert out["amountRatioQuotedN"] == 1
    assert out["amountRatio"] == 3.0
    # 全缺
    bars2 = {"600001": [{"date": D1, "close": 10.0}, {"date": D0, "close": 10.2, "amount": 3.0e8}]}
    out2 = aggregate_day(target_date=D0, members={"600001"},
                         bars_by_code=bars2, window_days=10)
    assert out2["amountRatio"] is None and out2["amountRatioQuotedN"] == 0


def test_v4_prom_merged_out_of_pool_counted_in_prom_n():
    """V4 条款 1：promN 并入池外晋级（进判据）；notes 仍披露池外家数。"""
    prom = {"ok": True, "byBoard": {"AI算力": 3}, "ge2ByBoard": {"AI算力": 1},
            "outByBoard": {"AI算力": 1}, "outGe2ByBoard": {"AI算力": 0},
            "unattributed": []}
    out = _assemble(today_rows=[_row(n=6)], prev_rows=[_row(n=5)],
                    count_hist=_hist([(D2, 3), (D1, 5)]),
                    prom=prom, prev_nodes={"AI算力": "weakening"})
    r = _node_of(out)
    assert r["promN"] == 3 and r["promGe2"] == 1            # 合并口径
    assert r["promOutOfPoolN"] == 1                          # 拆分披露
    assert any("池外晋级 1 家" in n for n in r["notes"])


def test_v4_amount_member_ratio_median():
    """V4-D：成员级量比中位——每成员自比当日/前日，消除成员集漂移噪声。"""
    bars = {
        # 成员自比：3.0 与 1.0 → 中位 2.0；成员集合计口径会给 (4e8/2e8)=2.0 同值
        "600001": [{"date": D1, "close": 10.0, "amount": 1.0e8},
                   {"date": D0, "close": 10.2, "amount": 3.0e8}],
        "600002": [{"date": D1, "close": 5.0, "amount": 2.0e8},
                   {"date": D0, "close": 5.1, "amount": 2.0e8}],
        # 区分两口径：自比 0.5 vs 合计受大成员主导
        "600003": [{"date": D1, "close": 8.0, "amount": 10.0e8},
                   {"date": D0, "close": 8.1, "amount": 5.0e8}],
    }
    out = aggregate_day(target_date=D0, members={"600001", "600002", "600003"},
                        bars_by_code=bars, window_days=10)
    assert out["amountMemberRatio"] == 1.0          # median(3.0, 1.0, 0.5)=1.0
    assert out["amountRatio"] == round(10.0e8 / 13.0e8, 3)   # 合计口径（对照）


def test_v4_amount_member_ratio_prev_zero_excluded():
    """前日 amount≤0 → 比值无定义，成员剔除（不铸 0 不算爆量）；全缺 → None。"""
    bars = {
        "600001": [{"date": D1, "close": 10.0, "amount": 0.0},
                   {"date": D0, "close": 10.2, "amount": 3.0e8}],
        "600002": [{"date": D1, "close": 5.0, "amount": 2.0e8},
                   {"date": D0, "close": 5.1, "amount": 4.0e8}],
    }
    out = aggregate_day(target_date=D0, members={"600001", "600002"},
                        bars_by_code=bars, window_days=10)
    assert out["amountMemberRatio"] == 2.0 and out["amountRatioQuotedN"] == 1
    bars2 = {"600001": [{"date": D1, "close": 10.0, "amount": 0.0},
                        {"date": D0, "close": 10.2, "amount": 3.0e8}]}
    out2 = aggregate_day(target_date=D0, members={"600001"},
                         bars_by_code=bars2, window_days=10)
    assert out2["amountMemberRatio"] is None


def test_v4_amount_notes_mainline_shrink_warning():
    """V4 条款 2：mainline 但成员级量比<0.9 → 价升量缩待复核注记（不改档）。"""
    out = _assemble(today_rows=[_row(n=8, streak=3)],
                    prev_rows=[_row(n=7, streak=2)],
                    count_hist=_hist([(D2, 6), (D1, 7)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    leader_status={"AI算力": "sealed"},
                    prev_nodes={"AI算力": "mainline"},
                    agg_by_board={"AI算力": _agg(pct=9.0, red=0.9, amountMemberRatio=0.82)})
    r = _node_of(out)
    assert r["node"] == "mainline"   # 档位不变
    assert any("价升量缩" in n and "0.82" in n for n in r["notes"])


def test_v4_amount_notes_hand_confirmed():
    """V4 条款 2：资金先手命中且量比≥1.5 → 量能确认注记；<1.5 不注记。"""
    kw = _hand_kw(agg_by_board={"AI算力": _agg(pct=3.5, red=0.8, amountMemberRatio=1.72)})
    r = _node_of(_assemble(**kw))
    assert r["node"] == "wzs" and any("量能同步放大" in n and "1.72" in n for n in r["notes"])
    kw2 = _hand_kw(agg_by_board={"AI算力": _agg(pct=3.5, red=0.8, amountMemberRatio=1.1)})
    assert not any("量能同步放大" in n for n in _node_of(_assemble(**kw2))["notes"])


def test_v4_amount_notes_no_ratio_no_note():
    """memberRatio 不可考 → 不注记（不伪 0）。"""
    out = _assemble(today_rows=[_row(n=8, streak=3)], prev_rows=[_row(n=7, streak=2)],
                    count_hist=_hist([(D2, 6), (D1, 7)]),
                    prom={"ok": True, "byBoard": {"AI算力": 2}, "ge2ByBoard": {"AI算力": 1}},
                    leader_status={"AI算力": "sealed"}, prev_nodes={"AI算力": "mainline"},
                    agg_by_board={"AI算力": _agg(pct=9.0, red=0.9, amountMemberRatio=None)})
    assert not any("价升量缩" in n or "量能同步放大" in n for n in _node_of(out)["notes"])


# ---- V4-E 量能观察序列（volSeries，展示投影非判据）----

def test_vol_series_aligned_with_count_series_and_gaps():
    """volSeries 与 countSeries 同日期轴逐日对齐；缺档日=None 缺口不插值；
    今日值=当日 aggN10.amountMemberRatio。"""
    out = _assemble(
        count_hist=_hist([(D2, 2), (D1, 3)]),
        vol_hist={"AI算力": [(D1, 1.25)]},          # D2 缺档 → 缺口
        agg_by_board={"AI算力": _agg(pct=3.5, red=0.8, amountMemberRatio=1.4)})
    r = _node_of(out)
    assert [p[0] for p in r["countSeries"]] == [D2, D1, D0]
    assert [p[0] for p in r["volSeries"]] == [D2, D1, D0]
    assert r["volSeries"] == [[D2, None], [D1, 1.25], [D0, 1.4]]


def test_vol_series_none_when_today_agg_missing():
    """今日聚合缺 amountMemberRatio → 今日位=None（不铸 0）；无 vol_hist 全缺。"""
    out = _assemble(agg_by_board={"AI算力": _agg(pct=3.5, red=0.8,
                                                 amountMemberRatio=None)})
    r = _node_of(out)
    assert r["volSeries"][-1] == [D0, None]
    assert all(p[1] is None for p in r["volSeries"])


def test_vol_series_absent_board_keeps_none():
    """vol_hist 未收录板块（历史档无该板块）→ 全序列 None，不报错。"""
    out = _assemble(vol_hist={"其他板块": [(D1, 0.9)]},
                    agg_by_board={"AI算力": _agg(pct=3.5, red=0.8,
                                                 amountMemberRatio=1.1)})
    r = _node_of(out)
    assert r["volSeries"][-1] == [D0, 1.1]
    assert r["volSeries"][0] == [D2, None] and r["volSeries"][1] == [D1, None]
