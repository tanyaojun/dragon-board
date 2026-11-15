# -*- coding: utf-8 -*-
"""竞价试盘强度第三源（auction_strength）测试（TDD 先红后绿；零 jev 零网络零生产写）。

覆盖（预登记 auction-leader-trial-strength-source-preregistration-20261115）：
- 纯函数：board_amt 求和（缺值按 0）、board_tier 五档边界、jj_ratio 分母、fnum；
- bre.row_basis 单源（limit/ST 探测/preseal）与 posture/tier_jj 边界；
- trial_strength_roster：root 映射全链（direct>bridge>hist）→ 严格筛
  （中热 2-5亿 × mid50_95 × 撤减）→ 每板 jj_ratio 降序前三；
- 软上限截断记账；fail-visible（trial 缺→整源缺席不阻断、未映射排除、无合格→0）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import auction_strength as AS
from backend.services.jev import jiuyan_board, jiuyan_industry_root

DATE = "2026-11-13"


class FakeCol:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def replace_one(self, flt, doc, upsert=False):
        self.docs[flt["_id"]] = dict(doc)

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs.values():
            ok = True
            for k, v in (query or {}).items():
                val = d.get(k)
                if isinstance(v, dict):
                    if "$gt" in v and not (val is not None and val > v["$gt"]):
                        ok = False
                    if "$gte" in v and not (val is not None and val >= v["$gte"]):
                        ok = False
                    if "$lte" in v and not (val is not None and val <= v["$lte"]):
                        ok = False
                    if "$in" in v and val not in v["$in"]:
                        ok = False
                elif val != v:
                    ok = False
            if ok:
                out.append(dict(d))
        return out

    def find_one(self, query=None, projection=None, **kw):
        for d in self.find(query):
            return d
        return None


class FakeDb:
    def __init__(self):
        self.cols: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


@pytest.fixture(autouse=True)
def _reset_board_caches():
    """进程内索引/桥缓存随进程存活：换假库前后一律清（jiuyan_board 同规）。"""
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()
    yield
    jiuyan_board.reset_jiuyan_board_cache()
    jiuyan_industry_root.reset_jiuyan_industry_root_cache()


def _seed_tree(db, board, codes):
    db["jiuyan_industry_stocks"].docs[f"node:{board}"] = {
        "_id": f"node:{board}", "name": board, "stockN": len(codes),
        "batchDate": "2026-10-25", "stocks": [{"code": c} for c in codes]}


def _row(jj_percent=7.0, jj_amount=3e7, first=1e7, last=5e6, **kw):
    r = {"jj_percent": jj_percent, "jj_amount": jj_amount,
         "first_amount": first, "last_amount": last,
         "start_time": "09:15:00", "end_time": "09:20:11"}
    if jj_percent is None:
        r.pop("jj_percent")
    if first is None:
        r.pop("first_amount")
    if last is None:
        r.pop("last_amount")
    r.update(kw)
    return r


# ── 纯函数：board_amt / board_tier / jj_ratio / fnum ──────────────────────

def test_board_amt_sum_missing_as_zero():
    rows = [{"board": "机器人", "jj_amount": 1e7},
            {"board": "机器人", "jj_amount": None},        # 缺值按 0（求和聚合取舍）
            {"board": "机器人", "jj_amount": "20000000"},  # 数字串可解析
            {"board": "机器人"},                            # 字段缺位按 0
            {"board": None, "jj_amount": 9e9},              # 未分板块不入和
            {"board": "大消费", "jj_amount": 5e7}]
    amt = AS.board_amt(rows)
    assert amt["机器人"] == pytest.approx(3e7)
    assert amt["大消费"] == pytest.approx(5e7)
    assert None not in amt


def test_board_tier_boundaries():
    assert AS.board_tier(None) == "未分板块"
    assert AS.board_tier(0) == "冷 <5000万"
    assert AS.board_tier(5e7 - 1) == "冷 <5000万"
    assert AS.board_tier(5e7) == "温 5000万-2亿"
    assert AS.board_tier(2e8) == "中热 2-5亿"
    assert AS.board_tier(5e8 - 1) == "中热 2-5亿"
    assert AS.board_tier(5e8) == "热 5-10亿"
    assert AS.board_tier(1e9) == "过热 ≥10亿"


def test_jj_ratio_denominators():
    assert AS.jj_ratio(9.54, 10.0, 10.0, True) == pytest.approx(95.4)
    assert AS.jj_ratio(5.0, None, 10.0, False) == pytest.approx(50.0)
    assert AS.jj_ratio(None, 10.0, 10.0, True) is None
    assert AS.jj_ratio(5.0, None, 0, False) is None


def test_fnum():
    assert AS.fnum("12.5") == 12.5
    assert AS.fnum(None) is None
    assert AS.fnum("abc") is None


# ── bre 单源：row_basis / tier_jj / posture ───────────────────────────────

def test_row_basis_st_probe_and_preseal():
    b = AS.bre.row_basis("600100", {"pre_percent": 10.0})
    assert b["limit"] == 10.0 and b["preseal"] is True
    b = AS.bre.row_basis("600100", {"pre_percent": 5.0})   # ST 探测（昨涨停 5% 板）
    assert b["limit"] == 5.0 and b["preseal"] is True
    b = AS.bre.row_basis("300100", {})
    assert b["limit"] == 20.0 and b["preseal"] is False
    b = AS.bre.row_basis("600100", {"pre_percent": 3.0})
    assert b["limit"] == 10.0 and b["preseal"] is False


def test_tier_jj_and_posture_boundaries():
    base = {"limit": 10.0, "preseal": False}
    assert AS.bre.tier_jj({**base, "jj_percent": 9.5}) == "top95"
    assert AS.bre.tier_jj({**base, "jj_percent": 5.0}) == "mid50_95"
    assert AS.bre.tier_jj({**base, "jj_percent": 4.99}) == "low_lt50"
    assert AS.bre.tier_jj({**base}) == "no_ratio"
    assert AS.bre.posture({"first_amount": 1e7, "last_amount": 5e6}) == "decrease"
    assert AS.bre.posture({"first_amount": 5e6, "last_amount": 1e7}) == "maintain"
    assert AS.bre.posture({"first_amount": 5e6, "last_amount": 5e6}) == "maintain"
    assert AS.bre.posture({"first_amount": 5e6}) == "no_data"
    assert AS.bre.posture({}) == "no_data"


# ── roster：严格筛 + 前三（direct 映射）──────────────────────────────────

def _mid_hot_fixture(db):
    """机器人板 9 只试盘股 Σ=2.7e8（中热）：4 只合格（前三入选）+ 5 只各触一条剔除。"""
    codes = [f"6001{i:02d}" for i in range(9)]
    _seed_tree(db, "机器人", codes)
    _seed_tree(db, "热板", ["600200"])
    _seed_tree(db, "冷板", ["600300"])
    rows = {
        "600100": _row(jj_percent=7.0),    # ratio 70 合格
        "600101": _row(jj_percent=9.0),    # ratio 90 合格
        "600102": _row(jj_percent=6.0),    # ratio 60 合格但板内第 4 → 前三截断
        "600103": _row(jj_percent=8.0),    # ratio 80 合格
        "600104": _row(jj_percent=7.5, first=5e6, last=9e6),  # maintain 剔
        "600105": _row(jj_percent=3.0),    # low_lt50 剔
        "600106": _row(jj_percent=9.9),    # top95 剔
        "600107": _row(jj_percent=None),   # no_ratio 剔
        "600108": _row(first=None),        # no_data 剔
        "600200": _row(jj_amount=6e8),     # 热板（个股合格也剔）
        "600300": _row(jj_amount=1e7),     # 冷板
        "600900": _row(),                  # 未映射（无树节点/无 bk_name/无 hist）
    }
    return rows


def test_roster_strict_filter_top3():
    db = FakeDb()
    rows = _mid_hot_fixture(db)
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert state["state"] == "ok"
    assert state["mappedN"] == 11 and state["unmappedN"] == 1
    assert state["selectedN"] == 3
    assert state["hotBoards"] == [{"board": "机器人", "amt": pytest.approx(2.7e8), "n": 9}]
    assert [(r["code"], r["trialStrength"]["rank"]) for r in out] == [
        ("600101", 1), ("600103", 2), ("600100", 3)]   # jj_ratio 降序
    for r in out:
        ts = r["trialStrength"]
        assert r["board"] == "机器人"
        assert ts["btier"] == "中热 2-5亿" and ts["jjtier"] == "mid50_95"
        assert ts["posture"] == "decrease" and ts["boardTrialN"] == 9
        assert ts["boardAmt"] == pytest.approx(2.7e8)
    assert out[0]["trialStrength"]["jjRatio"] == pytest.approx(90.0)


def test_roster_max_per_board_configurable():
    db = FakeDb()
    rows = _mid_hot_fixture(db)
    out, state = AS.trial_strength_roster(db, DATE, rows, max_per_board=1)
    assert [r["code"] for r in out] == ["600101"]
    assert state["selectedN"] == 1


def test_roster_soft_cap_truncation_bookkeeping():
    db = FakeDb()
    rows = {}
    # 3 板 × 3 合格 = 9 候选；全局 jj_ratio 前 6 保留（94/90/85/80/75/70）
    for bi, board in enumerate(["板A", "板B", "板C"]):
        codes = [f"6{bi}{i:02d}00" for i in range(3)]
        _seed_tree(db, board, codes)
        ratios = [[90, 80, 70], [85, 75, 65], [94, 60, 55]][bi]
        for c, jp in zip(codes, ratios):
            rows[c] = _row(jj_percent=jp / 10.0, jj_amount=8e7)
    out, state = AS.trial_strength_roster(db, DATE, rows, max_total=6)
    assert state["selectedN"] == 6 and state["cap"] == 6 and state["truncatedN"] == 3
    kept = {r["code"] for r in out}
    assert kept == {"620000", "600000", "610000", "600100", "610100", "600200"}
    ratios = sorted((r["trialStrength"]["jjRatio"] for r in out), reverse=True)
    assert ratios == pytest.approx([94, 90, 85, 80, 75, 70])


def test_roster_empty_trial_absent():
    db = FakeDb()
    out, state = AS.trial_strength_roster(db, DATE, {})
    assert out == [] and state["state"] == "absent"
    assert state["reason"] == "no_trial_rows"
    assert state["selectedN"] == 0 and state["mappedN"] == 0
    out2, state2 = AS.trial_strength_roster(db, DATE, None)
    assert out2 == [] and state2["state"] == "absent"


def test_roster_no_qualified_not_error():
    db = FakeDb()
    _seed_tree(db, "冷板", ["600300"])
    out, state = AS.trial_strength_roster(db, DATE, {"600300": _row(jj_amount=1e7)})
    assert out == [] and state["state"] == "ok"
    assert state["selectedN"] == 0 and state["reason"] == "no_qualified"
    assert state["hotBoards"] == [] and state["mappedN"] == 1


# ── roster：root 映射全链（bridge / hist）────────────────────────────────

def test_roster_bridge_mapping():
    db = FakeDb()
    # 产业树节点存在（供 inds）但试盘股未收录 → bk_name 治理桥 → root 对照归一
    _seed_tree(db, "机器人产业", ["600001"])
    db["theme_industry_mapping"].docs["机器人概念"] = {
        "_id": "机器人概念", "industryNames": ["机器人产业"]}
    db["jiuyan_industry_root_mapping"].docs["机器人产业"] = {
        "_id": "机器人产业", "rootName": "机器人"}
    rows = {"601000": _row(jj_percent=7.0, jj_amount=1.2e8, bk_name="机器人概念"),
            "601001": _row(jj_percent=8.0, jj_amount=1.2e8, bk_name="机器人概念")}
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert state["mappedN"] == 2 and state["unmappedN"] == 0
    assert [(r["code"], r["board"], r["trialStrength"]["rank"]) for r in out] == [
        ("601001", "机器人", 1), ("601000", "机器人", 2)]


def test_roster_hist_fallback_mapping():
    db = FakeDb()
    db["jiuyan_action"].docs["2026-11-12:final"] = {
        "_id": "2026-11-12:final", "tradingDate": "2026-11-12",
        "fields": [{"name": "机器人", "stocks": [{"code": "602000"}]}]}
    rows = {"602000": _row(jj_percent=7.0, jj_amount=2.5e8)}
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert state["mappedN"] == 1 and state["unmappedN"] == 0
    assert out[0]["board"] == "机器人" and out[0]["trialStrength"]["rank"] == 1


def test_roster_names_joined_from_stock_names():
    db = FakeDb()
    _seed_tree(db, "机器人", ["600100"])
    db["stock_names"].docs["600100"] = {"code": "600100", "name": "甲"}
    out, _ = AS.trial_strength_roster(db, DATE, {"600100": _row(jj_amount=2.5e8)})
    assert out[0]["name"] == "甲"


def test_assign_root_boards_hist_no_cross_date_overwrite():
    """跨日覆盖 bug 回归（2026-11-15 验收发现）：同 code 多日行，某日桥命中、
    另一日桥 miss 进 hist 兑底——hist 不得覆盖已有桥归属的行（单日/全窗同口径）。"""
    db = FakeDb()
    db["jiuyan_action"].docs["2026-11-12:final"] = {
        "_id": "2026-11-12:final", "tradingDate": "2026-11-12",
        "fields": [{"name": "历史板", "stocks": [{"code": "603039"}]}]}
    db["theme_industry_mapping"].docs["测试桥"] = {
        "_id": "测试桥", "industryNames": ["桥板"]}
    rows = [
        {"code": "603039", "bk_name": "测试桥(5)"},   # 桥命中 → 桥板
        {"code": "603039", "bk_name": "军工"},          # 桥 miss → hist 历史板
        {"code": "603039"},                              # 无 bk → hist 历史板
    ]
    AS.assign_root_boards(rows, db)
    assert [r["board"] for r in rows] == ["桥板", "历史板", "历史板"]


def test_roster_st_name_fix_caliber():
    """ST 名称修正与评估同口径：非昨涨停 ST 股（pre_percent 探测不覆盖）limit 补正 5，
    jj_percent=6 → ratio 120 → top95 剔除（不修则 60 误入 mid50_95）。"""
    db = FakeDb()
    _seed_tree(db, "机器人", ["600100", "600101"])
    db["stock_names"].docs["600100"] = {"code": "600100", "name": "ST某某"}
    db["stock_names"].docs["600101"] = {"code": "600101", "name": "乙"}
    rows = {"600100": _row(jj_percent=6.0, jj_amount=1.2e8, pre_percent=2.0),
            "600101": _row(jj_percent=7.0, jj_amount=1.2e8)}
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert [r["code"] for r in out] == ["600101"]   # ST 股 top95 被剔
    assert state["selectedN"] == 1


# ── 评审修复 2026-11-15（review-correctness P2-2/3/5）：NaN 消毒 / 桥降级留痕 / 负 cap ──

def test_fnum_non_finite_to_none():
    """NaN/Inf 非有限值 → None（防板额污染与 posture 误纳入）。"""
    assert AS.fnum(float("nan")) is None
    assert AS.fnum(float("inf")) is None
    assert AS.fnum("-inf") is None
    assert AS.fnum("nan") is None


def test_posture_nan_no_data():
    """NaN/非数字 first/last → no_data（不得判 decrease 误纳入）。"""
    nan = float("nan")
    assert AS.bre.posture({"first_amount": nan, "last_amount": 5e6}) == "no_data"
    assert AS.bre.posture({"first_amount": 1e7, "last_amount": nan}) == "no_data"
    assert AS.bre.posture({"first_amount": "abc", "last_amount": 5e6}) == "no_data"
    assert AS.bre.posture({"first_amount": 1e7, "last_amount": 5e6}) == "decrease"
    assert AS.bre.posture({"first_amount": 1e7, "last_amount": 1e7}) == "maintain"


def test_board_amt_nan_not_poison():
    """NaN jj_amount 按 0 计（不得污染整板 Σ 致误档过热静默排除）。"""
    rows = [{"board": "机器人", "jj_amount": float("nan")},
            {"board": "机器人", "jj_amount": 2.4e8}]
    assert AS.board_amt(rows)["机器人"] == pytest.approx(2.4e8)


def test_roster_nan_row_excluded_not_misincluded():
    """NaN first 的合格板股不得入严格档；其余股正常入选（板 Σ 不被污染）。"""
    db = FakeDb()
    _seed_tree(db, "机器人", ["600100", "600101", "600102"])
    rows = {"600100": _row(jj_percent=7.0, jj_amount=8e7),
            "600101": _row(jj_percent=8.0, jj_amount=8e7),
            "600102": _row(jj_percent=9.0, jj_amount=8e7, first=float("nan"))}
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert [r["code"] for r in out] == ["600101", "600100"]
    assert state["selectedN"] == 2
    assert state["hotBoards"][0]["amt"] == pytest.approx(2.4e8)


def test_roster_bridge_degraded_fail_visible(monkeypatch):
    """桥原料源失败（stock_names 读失败 → ST 补正空转）→ state.bridgeDegraded 留痕，
    选龙不阻断（§4.0 部分失败暴露）。"""
    db = FakeDb()
    _seed_tree(db, "机器人", ["600100", "600101", "600102"])
    real = jiuyan_board._bridge_maps

    def degraded(db_):
        out = real(db_)
        return {**out, "names": {},
                "sourceErrors": {"stock_names": "stock_names:RuntimeError"}}

    monkeypatch.setattr(jiuyan_board, "_bridge_maps", degraded)
    rows = {"600100": _row(jj_percent=7.0, jj_amount=8e7),
            "600101": _row(jj_percent=8.0, jj_amount=8e7),
            "600102": _row(jj_percent=9.0, jj_amount=8e7)}
    out, state = AS.trial_strength_roster(db, DATE, rows)
    assert state["bridgeDegraded"] == {"stock_names": "stock_names:RuntimeError"}
    assert state["selectedN"] == 3          # 非 ST 股不受名称缺位影响


def test_roster_negative_max_total_clamped():
    """负 max_total → 钳 0（截断记账不得虚增/负切片）。"""
    db = FakeDb()
    _seed_tree(db, "机器人", ["600100", "600101", "600102"])
    rows = {"600100": _row(jj_percent=7.0, jj_amount=8e7),
            "600101": _row(jj_percent=8.0, jj_amount=8e7),
            "600102": _row(jj_percent=9.0, jj_amount=8e7)}
    out, state = AS.trial_strength_roster(db, DATE, rows, max_total=-2)
    assert out == []
    assert state["cap"] == 0 and state["truncatedN"] == 3
    assert state["selectedN"] == 0 and state["reason"] == "no_qualified"
