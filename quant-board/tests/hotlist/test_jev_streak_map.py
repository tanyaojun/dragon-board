# -*- coding: utf-8 -*-
"""真连板单一事实源测试（jiuyan_streak_map，2026-10-16 口径修正）。

背景：10-15 语料审计发现「区间板数 M（N天M板的 M）」被当连板数用——澳弘电子
19天11板（10-14 已炸板）真连板=1 却写成最高 11 板。本文件锁 streak_map 口径：
N==M 直取 M 不回溯；N>M 走封板链回溯；不可验 → None 不按 M 伪算；今日未封板 → None。

2026-10-16 盘后复核新增：**停牌日不是断板日**。600825 新华传媒 14天11板，其中
10-13/14/15 是上交所停牌（TDX 日线该三日无棒），韭研/THS 池回溯里「昨日不在池」
与「昨日炸板」完全同形，旧口径据此把真连板 11 误判成 1，连带最高板/梯队/首板占比
/ladder_health 全错。本文件锁停牌分辨口径（TDX 日线为唯一权威）。
全 monkeypatch/fake，禁触真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from backend.operations import jev_label_jiuyan as runner
from backend.operations.jev_label_jiuyan import jiuyan_streak_map


@pytest.fixture(autouse=True)
def _clear_streak_cache():
    """_STREAK_CACHE 是模块级盘后批量缓存，跨测试必须清（否则同日不同夹具互相污染）。"""
    runner._STREAK_CACHE.clear()
    yield
    runner._STREAK_CACHE.clear()


class FakeCol:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.find_calls = 0

    def find(self, query=None, projection=None):
        self.find_calls += 1
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
        self.find_calls += 1
        found = self.find(query)
        return found[0] if found else None


class FakeDb:
    def __init__(self, cols):
        self.cols = cols

    def __getitem__(self, k):
        return self.cols.setdefault(k, FakeCol())


def _final(date, stocks):
    return {"_id": f"{date}:final",
            "fields": [{"name": "板块A", "stocks": list(stocks)}]}


def _frame(date, failed_codes=None, with_pool=True):
    """15:00 帧；failed_codes=None 且 with_pool=False → 无 thsPools（THS 池缺失日）。"""
    ls = {"zhaban": {"ztCount": 50, "count": len(failed_codes or []), "rate": 12.0},
          "drawdown": {"count": 3}, "continuousBoards": {"maxBoard": 5}}
    if with_pool:
        ls["thsPools"] = {
            "ok": True, "degraded": False, "date": date.replace("-", ""),
            "pools": {"failed": {"key": "failed", "total": len(failed_codes or []),
                                 "items": [{"code": c, "name": f"股{c}", "open_num": 1}
                                           for c in (failed_codes or [])]}}}
    return {"datasetId": "dragonboard_live", "type": "half_hour", "tradingDate": date,
            "slotTime": "15:00", "snapshotId": f"h:{date}", "timestamp": 2, "limitSummary": ls}


# ── 口径用例（对齐 10-15 实证）─────────────────────────────────────────────

def test_pure_streak_no_walk_direct_m():
    """N==M → 韭研自证纯连板，直取 M（不需要任何历史帧/昨日池）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-10-15", with_pool=True)]),
        "jiuyan_action": FakeCol([_final("2026-10-15", [
            {"code": "002343", "name": "慈文传媒", "num": "5天5板"},   # N==M → 5
            {"code": "002696", "name": "百洋股份", "num": "5天5板"},   # N==M → 5
            {"code": "000530", "name": "冰山冷热", "num": "3天3板"},   # N==M → 3
            {"code": "603237", "name": "五芳斋"}]),                   # num=None → 首板 1
        ]),
    })
    assert jiuyan_streak_map(db, "2026-10-15") == {
        "002343": 5, "002696": 5, "000530": 3, "603237": 1}


def test_broken_streak_walks_seal_chain():
    """N>M 走封板链回溯：19天11板（昨日炸板）→ 1；14天10板（昨日封、前日不在池）→ 2。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame("2026-10-09"),
            _frame("2026-10-12"),
            _frame("2026-10-13"),
            _frame("2026-10-14", failed_codes=["605058"]),   # 澳弘 10-14 炸板
            _frame("2026-10-15"),
        ]),
        "jiuyan_action": FakeCol([
            _final("2026-10-09", [{"code": "605058", "name": "澳弘电子", "num": "15天9板"}]),
            _final("2026-10-12", []),                          # 未触板
            _final("2026-10-13", [{"code": "605058", "name": "澳弘电子", "num": "17天10板"}]),
            _final("2026-10-14", [{"code": "605058", "name": "澳弘电子"},   # 炸板日仍在触板池
                                  {"code": "601811", "name": "新华文轩", "num": "13天9板"}]),
            _final("2026-10-15", [{"code": "605058", "name": "澳弘电子", "num": "19天11板"},
                                  {"code": "601811", "name": "新华文轩", "num": "14天10板"}]),
        ]),
    })
    streaks = jiuyan_streak_map(db, "2026-10-15")
    assert streaks["605058"] == 1     # 昨日炸板 → 连板断，今日回封=1 板
    assert streaks["601811"] == 2     # 昨日封板、前日不在池 → 2 连板


def test_streak_capped_at_m():
    """回溯链长于区间板数 M 时封顶 M（连续高度不可能超区间总板数）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame("2026-10-13"),
            _frame("2026-10-14"),
            _frame("2026-10-15"),
        ]),
        "jiuyan_action": FakeCol([
            _final("2026-10-13", [{"code": "600010", "name": "X"}]),
            _final("2026-10-14", [{"code": "600010", "name": "X"}]),
            _final("2026-10-15", [{"code": "600010", "name": "X", "num": "4天2板"}]),
        ]),
    })
    # 三日连封但 num 只认 2 板 → 封顶 2（宁缺毋滥，不上探）
    assert jiuyan_streak_map(db, "2026-10-15")["600010"] == 2


def test_none_when_history_unverifiable():
    """回溯撞上 THS 炸板池缺失日 → None（不可算），不按 M 伪算（fail-visible 红线）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([
            _frame("2026-10-14", with_pool=False),   # 昨日 THS 池缺失 → 链不可验证
            _frame("2026-10-15"),
        ]),
        "jiuyan_action": FakeCol([
            _final("2026-10-14", [{"code": "605058", "name": "澳弘电子"}]),
            _final("2026-10-15", [{"code": "605058", "name": "澳弘电子", "num": "19天11板"}]),
        ]),
    })
    streaks = jiuyan_streak_map(db, "2026-10-15")
    assert streaks["605058"] is None      # 不得回落成 11


def test_none_when_today_pool_missing():
    """今日 THS 炸板池缺失 → 今日封板不可验证，全股 None（不把触板当封板）。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-10-15", with_pool=False)]),
        "jiuyan_action": FakeCol([_final("2026-10-15", [
            {"code": "002343", "name": "慈文传媒", "num": "5天5板"}])]),
    })
    assert jiuyan_streak_map(db, "2026-10-15") == {"002343": None}


def test_zhaban_today_is_none():
    """今日炸板（在 THS failed 池）→ 无「至今日」连续高度。"""
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame("2026-10-15", failed_codes=["603533"])]),
        "jiuyan_action": FakeCol([_final("2026-10-15", [
            {"code": "603533", "name": "掌阅科技", "num": "14天10板"},
            {"code": "002343", "name": "慈文传媒", "num": "5天5板"}])]),
    })
    streaks = jiuyan_streak_map(db, "2026-10-15")
    assert streaks["603533"] is None
    assert streaks["002343"] == 5


def test_empty_when_final_missing():
    """韭研 final 缺失 → {}（调用方按缺料降级，不伪造）。"""
    db = FakeDb({"snapshot_frames": FakeCol([_frame("2026-10-15")]),
                 "jiuyan_action": FakeCol([])})
    assert jiuyan_streak_map(db, "2026-10-15") == {}


def test_cached_per_dataset_date():
    """同日同 dataset 命中缓存：缓存后改库不改变返回值（与 _FACTS_CACHE 同款语义）。"""
    frames = FakeCol([_frame("2026-10-15")])
    db = FakeDb({"snapshot_frames": frames,
                 "jiuyan_action": FakeCol([_final("2026-10-15", [
                     {"code": "002343", "name": "慈文传媒", "num": "5天5板"}])])})
    first = jiuyan_streak_map(db, "2026-10-15")
    calls_after_first = frames.find_calls
    db.cols["jiuyan_action"].rows.append(
        _final("2026-10-15", [{"code": "002343", "name": "慈文传媒", "num": "9天9板"}]))
    second = jiuyan_streak_map(db, "2026-10-15")
    assert second == first and frames.find_calls == calls_after_first


# ── 停牌分辨（2026-10-16 盘后复核新增，600825 停牌复牌实证）─────────────────

# 600825 的真实交易日历：09-21 起连续 11 个封板日，中间 10-13/14/15 上交所停牌
_SUSP_DATES = ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-28",
               "2026-09-29", "2026-09-30", "2026-10-08", "2026-10-09", "2026-10-12",
               "2026-10-16"]
_SUSPENDED = ["2026-10-13", "2026-10-14", "2026-10-15"]
# 回溯窗要覆盖的全部市场交易日（含停牌日与链起点之前一日，共 14 个历史日）
_SUSP_CALENDAR = _SUSP_DATES[:-1] + _SUSPENDED + ["2026-09-18"]


def _suspension_db(monkeypatch, *, code="600825", name="新华传媒", m=11, n=14,
                   sealed=None, suspended=None, bar_dates=None, pool_missing=()):
    """停牌场景 fake：sealed=该股封板的历史日，suspended=停牌日（TDX 无棒），
    pool_missing=THS 炸板池缺失日（封板二分不可用，需日线补证）。

    bar_dates 默认 = 全部日历日减去停牌日（即该股只在非停牌日有棒）。
    """
    sealed = _SUSP_DATES[:-1] if sealed is None else sealed
    suspended = _SUSPENDED if suspended is None else suspended
    calendar = sorted(set(_SUSP_CALENDAR) | set(sealed) | set(suspended) | {"2026-10-16"})
    frames, finals = [], []
    for d in calendar:
        frames.append(_frame(d, with_pool=d not in pool_missing))
        if d == "2026-10-16":
            stocks = [{"code": code, "name": name, "num": f"{n}天{m}板"}]
        elif d in sealed:
            stocks = [{"code": code, "name": name}]
        elif d in suspended:
            # 停牌日韭研 final 仍在（只是不含该股）——空 stocks 会被当成「final 缺失」，
            # 走的是另一条降级路径，测不到停牌分辨
            stocks = [{"code": "000001", "name": "平安银行"}]
        else:
            stocks = [{"code": "000002", "name": "万科A"}]
        finals.append(_final(d, stocks))
    db = FakeDb({"snapshot_frames": FakeCol(frames), "jiuyan_action": FakeCol(finals)})
    # 日线收盘价要真体现出涨停/非涨停：封板日 +10%、其余 -5%（_bar_verdict 靠它判定）
    limit_up = set(sealed) | {"2026-10-16"}
    bar_seq = ([x for x in calendar if x not in suspended]
               if bar_dates is None else list(bar_dates))
    bars, prev = [], 10.0
    for d in bar_seq:
        close = round(prev * (1.1 if d in limit_up else 0.95), 2)
        bars.append({"date": d, "high": close, "close": close, "vol": 1.0})
        prev = close
    monkeypatch.setattr(runner, "_daily_bars", lambda c, _b=list(bars): [dict(x) for x in _b])
    # 除权因子源走百度（真实网络），与停牌分辨无关——打桩掉，保持用例离线
    monkeypatch.setattr(runner, "_adj_prev_series", lambda *a, **k: {})
    return db


def test_suspension_days_do_not_break_streak(monkeypatch):
    """停牌日不算断板：14天11板 中间停牌 3 日 → 真连板 11（不是 1）。

    旧口径把「昨日不在封板池」一律当断板 break，600825 因此被判 1 板，连带最高板
    4 板（应 11）、梯队 58/3/2（应 57/3/3）、ladder_health pyramid（应 inverted）。
    """
    db = _suspension_db(monkeypatch)
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 11


def test_traded_but_unsealed_day_still_breaks(monkeypatch):
    """有交易但未封板（炸板日）仍是断板——停牌分辨不得把真断板吞掉。

    10-14 炸板（在触板池且在 THS failed 池）且有日线棒 → 链终止，连板=2。
    """
    db = _suspension_db(monkeypatch, m=5, n=8, sealed=["2026-10-15"],
                        suspended=["2026-10-14"],
                        bar_dates=["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"])
    # 10-14 有棒但不在封板集合 → 断板（区别于停牌的无棒）
    db.cols["snapshot_frames"].rows = [
        {**f, "limitSummary": {**f["limitSummary"], "zhaban": {"ztCount": 50, "count": 1},
                               "thsPools": {"ok": True, "degraded": False,
                                            "pools": {"failed": {"key": "failed", "total": 1,
                                                                 "items": [{"code": "600825",
                                                                            "name": "新华传媒",
                                                                            "open_num": 2}]}}}}}
        if f["tradingDate"] == "2026-10-14" else f
        for f in db.cols["snapshot_frames"].rows]
    db.cols["jiuyan_action"].rows = [
        {**d, "fields": [{"name": "板块A",
                          "stocks": [{"code": "600825", "name": "新华传媒"}]}]}
        if d["_id"] == "2026-10-14:final" else d
        for d in db.cols["jiuyan_action"].rows]
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 2


def test_no_daily_bars_falls_back_to_pool_verdict(monkeypatch):
    """TDX 日线不可用（客户端挂/北交所 920xxx 不覆盖）→ 不让步到「当停牌」。

    那正是要修的 bug 本身：查不到 ≠ 停牌。回落池口径——池说未封即断板，链终止（连板=1），
    与修复前行为一致，不静默虚高（AGENTS §4.0：取不到与真的停牌是两件事）。
    """
    db = _suspension_db(monkeypatch, bar_dates=[])
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 1


def test_walk_beyond_bar_window_follows_pool_verdict(monkeypatch):
    """越过 TDX 窗口左沿但池可用 → 以池为准（未封即断板），不虚高也不冒充不可验。"""
    db = _suspension_db(monkeypatch, m=5, n=9,
                        sealed=["2026-10-12", "2026-10-09"],
                        suspended=["2026-10-15", "2026-10-14", "2026-10-13", "2026-10-08"],
                        bar_dates=["2026-10-16", "2026-10-12", "2026-10-09"])
    # 10-16(1) + 10-12(2) + 10-09(3)，10-08 在窗口外且池说未封 → 断板终止
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 3


def test_bar_fills_pool_missing_day(monkeypatch):
    """THS 炸板池缺失日由该股自己的日线补证——否则整链不可验（09-23 实证）。

    600825 链上的 2026-09-23 正是炸板池缺失日：只靠池回溯会在那里返 None，
    最高板退回 4 板。日线显示当日收在涨停价 → 封板，链继续，真连板仍是 11。
    """
    db = _suspension_db(monkeypatch, pool_missing=["2026-09-23"])
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 11


def test_pool_missing_day_beyond_bar_window_is_none(monkeypatch):
    """池缺失日 + 日线也判不出（早于最早可用棒）→ None，不按 M 伪算（fail-visible 红线）。"""
    db = _suspension_db(monkeypatch, m=5, n=9, pool_missing=["2026-10-08"],
                        sealed=["2026-10-12", "2026-10-09"],
                        suspended=["2026-10-15", "2026-10-14", "2026-10-13", "2026-10-08"],
                        bar_dates=["2026-10-16", "2026-10-12", "2026-10-09"])
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] is None


# ── 停牌分辨的两条边界（2026-10-16 code review 补，均有实证场景）─────────────


def test_tdx_data_hole_is_not_suspension(monkeypatch):
    """TDX 数据洞 ≠ 停牌：当日**交易过**（名字在韭研触板名单）而 TDX 无棒 → 不可验返 None。

    「无棒即停牌」这条捷径会把断板日算成连板日、虚报高度——与本次要修的 bug 同族反向。
    场景：D-3 当日炸板（在触板池、在 THS failed 池）且 TDX 恰好缺那一根棒。
    若按停牌跳过 → 虚报成 5 板；正确行为是不可验（None），不猜。
    """
    db = _suspension_db(monkeypatch, m=5, n=7,
                        sealed=["2026-10-15", "2026-10-14", "2026-10-13"],
                        suspended=["2026-10-12"],
                        # 10-09 只是把日线覆盖段的左沿拉到 10-12 之前，让「缺 10-12 这根棒」
                        # 落在已覆段内（否则 _bar_verdict 会判 unknown 而非 suspended）
                        bar_dates=["2026-10-09", "2026-10-13", "2026-10-14",
                                   "2026-10-15", "2026-10-16"])
    # 10-12：该股在触板池（炸板）但 TDX 无棒——把它标成「交易过」而非停牌
    db.cols["jiuyan_action"].rows = [
        {**d, "fields": [{"name": "板块A",
                          "stocks": [{"code": "600825", "name": "新华传媒"}]}]}
        if d["_id"] == "2026-10-12:final" else d
        for d in db.cols["jiuyan_action"].rows]
    db.cols["snapshot_frames"].rows = [
        {**f, "limitSummary": {**f["limitSummary"],
                               "thsPools": {"ok": True, "degraded": False,
                                            "pools": {"failed": {"key": "failed", "total": 1,
                                                                 "items": [{"code": "600825",
                                                                            "name": "新华传媒",
                                                                            "open_num": 3}]}}}}}
        if f["tradingDate"] == "2026-10-12" else f
        for f in db.cols["snapshot_frames"].rows]
    # 不得按停牌跳过续算成 5；宁可不可验
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] is None


def test_walk_window_exhaustion_returns_none():
    """回溯窗耗尽仍未追平 M → None，不返回被窗口截断的偏小连板数。

    所需步数 = M + 窗内停牌日数，可能超过 `_STREAK_WALK_MAX_DATES`。旧实现此时
    verifiable 仍为 True，会返回截断值——与同段板序行（无帽实测）给出两个连板数，
    也违背本函数「宁缺毋猜」的契约。
    """
    days = [f"2026-{7 + i // 22:02d}-{1 + i % 22:02d}" for i in range(70)]
    today = days[-1]
    frames = [_frame(d) for d in days]
    finals = [_final(d, [{"code": "600825", "name": "X"}]) for d in days]
    # N>M 才会走回溯（N==M 是韭研自证纯连板、直取 M 不回溯）
    finals[-1] = _final(today, [{"code": "600825", "name": "X", "num": "75天70板"}])
    db = FakeDb({"snapshot_frames": FakeCol(frames), "jiuyan_action": FakeCol(finals)})
    # 70 个封板日 > 60 日回溯窗：窗口内只能数到 61，截断值不可信 → None
    assert jiuyan_streak_map(db, today)["600825"] is None


def test_pool_sealed_beats_contradicting_bar(monkeypatch):
    """池说封板而日线显示未收在涨停价 → 以池为权威（+1），不被日线翻供。

    决策表第一行「池=封板 → 连板 +1，池为既定权威」：日线只在池覆盖不到的两个歧义
    场景（停牌/池缺失日）兜底。若把顺序改成日线优先，这条链会被日线截短。
    """
    days = ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
    db = FakeDb({
        "snapshot_frames": FakeCol([_frame(d) for d in days]),
        "jiuyan_action": FakeCol([
            _final("2026-10-13", [{"code": "600825", "name": "X"}]),
            _final("2026-10-14", [{"code": "600825", "name": "X"}]),
            _final("2026-10-15", [{"code": "600825", "name": "X"}]),
            _final("2026-10-16", [{"code": "600825", "name": "X", "num": "6天4板"}])]),
    })
    # 日线让 10-14/10-15 都收在 -5%（与池矛盾）：池仍说封板，链应走到 4
    bars = [{"date": d, "high": 9.5, "close": 9.5, "vol": 1.0} for d in days]
    monkeypatch.setattr(runner, "_daily_bars", lambda c: [dict(b) for b in bars])
    monkeypatch.setattr(runner, "_adj_prev_series", lambda *a, **k: {})
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 4


def test_pool_missing_day_with_sub_limit_bar_breaks(monkeypatch):
    """池缺失日 + 日线显示未收在涨停价 → 断板，链终止（不按 M 伪算成连板中）。"""
    days = ["2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16"]
    db = FakeDb({
        # 10-14 炸板池缺失 → 该日封板不可二分，须由日线补证
        "snapshot_frames": FakeCol([_frame(d, with_pool=d != "2026-10-14") for d in days]),
        "jiuyan_action": FakeCol([
            _final("2026-10-13", [{"code": "600825", "name": "X"}]),
            _final("2026-10-14", [{"code": "600825", "name": "X"}]),
            _final("2026-10-15", [{"code": "600825", "name": "X"}]),
            _final("2026-10-16", [{"code": "600825", "name": "X", "num": "6天4板"}])]),
    })
    bars = [{"date": d, "high": 10.0, "close": 10.0, "vol": 1.0} for d in days]
    bars[1] = {"date": "2026-10-14", "high": 9.6, "close": 9.5, "vol": 1.0}  # 未收涨停
    monkeypatch.setattr(runner, "_daily_bars", lambda c: [dict(b) for b in bars])
    monkeypatch.setattr(runner, "_adj_prev_series", lambda *a, **k: {})
    # 10-15(+1) 后 10-14 日线判断板 → 链终止，连板 = 2（今日 + 昨日）
    assert jiuyan_streak_map(db, "2026-10-16")["600825"] == 2


def test_daily_bars_transient_failure_not_cached(monkeypatch):
    """TDX 瞬时失败不落空缓存：否则一次抖动让整轮回溯永久降级、进程内无恢复路径。

    `_DAILY_CLIENT` 已缓存时 `_TDX_DOWN_UNTIL` 负缓存不会介入，空缓存一旦写下就再也
    洗不掉（2026-10-16 review 实测：第二次调用带健康客户端仍返 []）。
    """
    saved = (runner._TDX_DOWN_UNTIL, runner._DAILY_CLIENT)
    runner._DAILY_BARS_CACHE.clear()
    runner._TDX_DOWN_UNTIL = 0.0
    runner._DAILY_CLIENT = None
    calls = []

    class _Df:
        def __len__(self):
            return 1

        def iterrows(self):
            yield 0, {"year": 2026, "month": 10, "day": 16, "high": 11.0, "close": 11.0}

    class _Client:
        def bars(self, **_kw):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("tdx blip")
            return _Df()

    try:
        monkeypatch.setattr(runner, "_tdx_daily_client", lambda: _Client())
        real = runner._REAL_DAILY_BARS      # 离线护栏把模块属性打空了，这里取回真实实现
        key = (runner._bars_offset(), "600825")   # v5：缓存键含 bars offset（JEV_BARS_OFFSET）
        assert real("600825") == []                      # 首次失败：降级但不写缓存
        assert runner._DAILY_BARS_CACHE.get(key) is None
        assert len(real("600825")) == 1                   # 重试即恢复
        assert runner._DAILY_BARS_CACHE.get(key)          # 成功后照常缓存
    finally:
        runner._TDX_DOWN_UNTIL, runner._DAILY_CLIENT = saved
        runner._DAILY_BARS_CACHE.clear()
