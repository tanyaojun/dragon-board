# -*- coding: utf-8 -*-
"""2026-11-13 用户裁决 B 方案：龙一候选池每股每日单板块归属（根因修）。

缺陷回顾：space_mode 候选池=当日封板池∪近3日同名板块封板池，无单归属约束 →
迁移股（韭研逐日换板块）在旧/新板块候选池同时排第一 → 一股两板块龙头，
节点判据消费错误龙头、投喂链同股同日重复烧 jev（_id={date}:{code} 后写覆盖）。

B 口径（用户确认三默认）：
1. 单归属复用首板块约定（_pool_of/_promotion_by_board 同源）：当日在池取当日
   首个出现板块；当日缺席取最近在池日首板块；
2. 断板反包本意保留：断板龙一仍留归属板块在列（dayStatus=broken 下游消费），
   判据表 classify_board_day 零改动（纠正的是输入）；
3. 历史不自动重放：新落档 meta.leaderAttribution 版本旗标披露代际。

仅 space_mode 启用；历史 streak 口径不漂移（预登记哲学）。全 fake/monkeypatch，
零真实 jev/TDX/网络调用。
"""
import backend.operations.theme_leader_baseline as baseline
import backend.operations.jev_label_jiuyan as jlj

T, P1, P2 = "2026-11-12", "2026-11-11", "2026-11-10"


def _st(code, name, num, time="09:30:00"):
    return {"code": f"sh{code}", "name": name, "num": num, "time": time}


class _Coll:
    def __init__(self, docs):
        self.docs = docs

    def find_one(self, q, proj=None, sort=None):
        return self.docs.get(q.get("_id"))


class _DB:
    def __init__(self, docs):
        self._cols = {"jiuyan_action": _Coll(docs)}

    def __getitem__(self, key):
        return self._cols[key]


def _wire(monkeypatch, docs, sealed_map, streak_map):
    monkeypatch.setattr(
        baseline, "sealed_and_info",
        lambda db, date, dataset_id=None: (
            sealed_map.get(date, set()), {},
            {"jiuyanFinalFound": True, "thsFound": True}))
    monkeypatch.setattr(
        jlj, "jiuyan_streak_map",
        lambda db, date, dataset_id=None: streak_map.get(date, {}))


def _run(db, date=T, pool_dates=(), space_mode=True, gains=None, changes=None):
    gains = gains or {}
    return baseline.day_leader_rows(
        db, date, None, space_mode=space_mode, pool_dates=list(pool_dates),
        gain_fetcher=lambda codes, d: {c: gains.get(c) for c in codes},
        day_change_fetcher=lambda codes, d: {c: (changes or {}).get(c, 0.0) for c in codes})


def _leaders(rows):
    return {r["board"]: r["code"] for r in rows or []}


def test_migrated_stock_leads_only_new_board(monkeypatch):
    """天普股份式迁移：昨日旧板、今日新板 → 只当选新板龙一；旧板另选当日成员。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "旧板", "stocks": [_st("600002", "旧板成员", "1天1板", "09:40:00")]},
            {"name": "新板", "stocks": [_st("600001", "迁移股", "3天3板", "09:35:00")]}]},
        f"{P1}:final": {"fields": [
            {"name": "旧板", "stocks": [_st("600001", "迁移股", "2天2板"),
                                       _st("600002", "旧板成员", "1天1板")]}]},
    }
    _wire(monkeypatch, docs,
          {T: {"600001", "600002"}, P1: {"600001", "600002"}},
          {T: {"600001": 3, "600002": 1}, P1: {"600001": 2, "600002": 1}})
    rows, meta = _run(_DB(docs), pool_dates=[P1],
                      gains={"600001": 30.0, "600002": 5.0})
    ld = _leaders(rows)
    assert ld.get("新板") == "600001"
    assert ld.get("旧板") == "600002", "旧板龙一不得再是已迁移股（根因）"
    assert len({r["code"] for r in rows}) == len(rows), "同日每股至多一个龙头行（投喂不重复）"
    la = meta.get("leaderAttribution") or {}
    assert la.get("version") == "single-board-20261113"
    mb = {m["code"]: m for m in la.get("multiBoard") or []}
    assert mb["600001"]["chosen"] == "新板"
    assert set(mb["600001"]["boards"]) == {"旧板", "新板"}


def test_broken_leader_stays_on_latest_board_only(monkeypatch):
    """闽发铝业式断板迁移：前日旧板、昨日新板、今日缺席 → 断板龙一仅留新板（反包本意保留）。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "旧板", "stocks": [_st("600002", "旧板成员", "1天1板")]},
            {"name": "新板", "stocks": [_st("600003", "新板成员", "1天1板")]}]},
        f"{P1}:final": {"fields": [
            {"name": "新板", "stocks": [_st("600004", "断板龙", "4天4板")]}]},
        f"{P2}:final": {"fields": [
            {"name": "旧板", "stocks": [_st("600004", "断板龙", "3天3板")]}]},
    }
    _wire(monkeypatch, docs,
          {T: {"600002", "600003"}, P1: {"600004"}, P2: {"600004"}},
          {T: {"600002": 1, "600003": 1}, P1: {"600004": 4}, P2: {"600004": 3}})
    rows, meta = _run(_DB(docs), pool_dates=[P2, P1],
                      gains={"600004": 80.0, "600002": 5.0, "600003": 6.0})
    ld = _leaders(rows)
    assert ld.get("新板") == "600004", "断板龙一留最近在池板块（断板反包本意保留）"
    assert ld.get("旧板") == "600002", "更旧板块不得再挂已迁走断板股"
    broken = next(r for r in rows if r["board"] == "新板")
    assert broken.get("streak") is None and broken.get("poolDay") == P1
    assert len({r["code"] for r in rows}) == len(rows)
    mb = {m["code"]: m for m in (meta.get("leaderAttribution") or {}).get("multiBoard") or []}
    assert mb["600004"]["chosen"] == "新板"


def test_same_day_multi_board_first_board_wins(monkeypatch):
    """同日多板块收录：首板块约定单归属（与 _pool_of 同源），不新造口径。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "首板", "stocks": [_st("600001", "多板股", "3天3板")]},
            {"name": "次板", "stocks": [_st("600001", "多板股", "3天3板"),
                                       _st("600003", "次板成员", "1天1板")]}]},
    }
    _wire(monkeypatch, docs, {T: {"600001", "600003"}},
          {T: {"600001": 3, "600003": 1}})
    rows, meta = _run(_DB(docs), gains={"600001": 30.0, "600003": 5.0})
    ld = _leaders(rows)
    assert ld.get("首板") == "600001"
    assert ld.get("次板") == "600003"
    mb = {m["code"]: m for m in (meta.get("leaderAttribution") or {}).get("multiBoard") or []}
    assert mb["600001"]["chosen"] == "首板"


def test_non_space_mode_historical_caliber_unchanged(monkeypatch):
    """历史 streak 口径不漂移：非 space_mode 不做单归属、不带版本旗标。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "首板", "stocks": [_st("600001", "多板股", "3天3板")]},
            {"name": "次板", "stocks": [_st("600001", "多板股", "3天3板")]}]},
    }
    _wire(monkeypatch, docs, {T: {"600001"}}, {T: {"600001": 3}})
    rows, meta = _run(_DB(docs), space_mode=False)
    ld = _leaders(rows)
    assert ld.get("首板") == "600001" and ld.get("次板") == "600001"
    assert "leaderAttribution" not in meta


def test_emptied_board_disclosed_not_silent(monkeypatch):
    """m4 审查修复：某板今日唯一封板成员为同日多板股且归属他板 → 该板被归属过滤
    清空（其断板候选不被考虑=既有板块轴设计），须 boardsEmptied 披露（fail-visible）。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "首板", "stocks": [_st("600001", "多板股", "3天3板")]},
            {"name": "空板", "stocks": [_st("600001", "多板股", "3天3板")]}]},
    }
    _wire(monkeypatch, docs, {T: {"600001"}}, {T: {"600001": 3}})
    rows, meta = _run(_DB(docs), gains={"600001": 30.0})
    assert _leaders(rows) == {"首板": "600001"}
    la = meta.get("leaderAttribution") or {}
    assert la.get("boardsEmptied") == ["空板"]


def test_attribution_x_limit_down_exclusion(monkeypatch):
    """覆盖缺口补：归属×跌停剔除交互——断板候选归属新板但今日跌停 → 剔除+披露；
    旧板不因归属单而复活它（归属单），新板另选当日成员。"""
    docs = {
        f"{T}:final": {"fields": [
            {"name": "旧板", "stocks": [_st("600002", "旧板成员", "1天1板")]},
            {"name": "新板", "stocks": [_st("600003", "新板成员", "1天1板")]},
        ]},
        f"{P1}:final": {"fields": [
            {"name": "新板", "stocks": [_st("600004", "断板龙", "4天4板")]},
        ]},
    }
    _wire(monkeypatch, docs,
          {T: {"600002", "600003"}, P1: {"600004"}},
          {T: {"600002": 1, "600003": 1}, P1: {"600004": 4}})
    rows, meta = _run(_DB(docs), pool_dates=[P1],
                      gains={"600004": 80.0, "600002": 5.0, "600003": 6.0},
                      changes={"600004": -10.0})
    assert _leaders(rows) == {"旧板": "600002", "新板": "600003"}
    assert any("断板龙" in s for s in (meta.get("limitDownExcluded") or {}).get("新板", [])), \
        "跌停剔除须披露（fail-visible）"
