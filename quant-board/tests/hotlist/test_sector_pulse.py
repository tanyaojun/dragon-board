# -*- coding: utf-8 -*-
"""V2c 盘中红盘提示测试（预登记 sector-nodes-v2c-intraday-preregistration.md §七）。

全 mock：TDX 报价经 quotes_fetcher 注入（_fetch_quotes 单测 patch _tdx_daily_client）、
窗口池经 day_leader_rows monkeypatch（直查路径，不走 _POOL_CACHE）、
trading_dates_before patch 到 sector_pulse 模块命名空间、交易日判定 patch 源头模块。
禁真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

import backend.snapshot_collector.trading_calendar as trading_calendar
from backend.operations import sector_pulse as sp
from backend.operations.sector_pulse import (
    _evidence_stage,
    _pulse_stats,
    compute_pulse,
    get_pulse_cached,
)

TODAY = "2026-10-26"   # 周一
PREV = "2026-10-23"    # 周五 = 今日上一交易日


class FakeCollection:
    def __init__(self):
        self.docs: dict[str, dict] = {}
        self.replacements: list[str] = []

    def find_one(self, q, *a, **k):
        return self.docs.get(q["_id"])

    def replace_one(self, q, doc, upsert=False):
        self.replacements.append(q["_id"])
        self.docs[q["_id"]] = doc


class FakeDB:
    def __init__(self):
        self.pulse = FakeCollection()
        self.nodes = FakeCollection()

    def __getitem__(self, name):
        if name == "hotlist_jev_sector_pulse":
            return self.pulse
        return self.nodes


@pytest.fixture
def env(monkeypatch):
    """窗口池（昨日封窗冻结口径）+ 交易日序列 + 昨日节点文档。

    dates_before 模拟 trading_dates_before 的升序返回（旧→新）：
    TODAY 前序列结尾必须是 PREV；PREV 前序列结尾是 10-22。
    池：10-23 / 10-20 / 10-17 池 ok，10-22/10-21 与 10-16 起更早日全缺
    → 机器人封窗如实缩短为 3 日（daysShort 语义与落库一致）。
    """
    dates_before = {
        TODAY: [f"2026-10-{d:02d}" for d in range(9, 24)],    # 10-09..10-23 旧→新
        PREV: [f"2026-10-{d:02d}" for d in range(6, 23)],     # 10-06..10-22
    }
    monkeypatch.setattr(sp, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: dates_before[date][-n:])

    def _rows(board_codes):
        return [{"board": b, "boardCodes": cs} for b, cs in board_codes.items()]

    pools = {
        PREV: (_rows({"机器人": ["600001", "600002"], "AI算力": ["300001"]}),
               {"jiuyanFinalFound": True}),
        "2026-10-20": (_rows({"机器人": ["600001", "600003"]}),
                       {"jiuyanFinalFound": True}),
        "2026-10-17": (_rows({"机器人": ["600004"]}),
                       {"jiuyanFinalFound": True}),
    }
    monkeypatch.setattr(sp, "day_leader_rows",
                        lambda db, d, ds=None: pools.get(d, (None, {})))
    nodes = FakeCollection()
    nodes.docs[f"{PREV}:SECTOR_NODES"] = {"rows": [
        {"board": "机器人", "node": "weakening"},
        {"board": "AI算力", "node": "collapse"},
        {"board": "半导体", "node": "wzs"}]}
    db = FakeDB()
    db.nodes = nodes
    # 默认交易日（compute_pulse 证据段判定走 bridge/cache 探测，测试统一 mock 掉）
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))
    return db


QUOTES = {"600001": (11.0, 10.0),    # +10%
          "600002": (9.8, 10.0),     # -2%
          "600003": (5.0, 5.0),      # 0%
          "600004": (2.2, 2.0),      # +10%
          "300001": (20.0, 21.0)}    # -4.76%


def _fetch_ok(codes):
    return {c: QUOTES[c] for c in codes if c in QUOTES}


def test_frozen_union_uses_prev_target_not_today(env):
    """成员=昨日封窗 N10：target 是 PREV 而非 TODAY——今日不在窗内（预登记 §二=A）。"""
    members, root = sp._frozen_union(env, TODAY)
    assert root is None
    # 机器人 = PREV∪10-20∪10-17 并集；窗内 10-22/10-21 与 10-16 起池缺失 → 如实缩短
    assert members["机器人"] == {"600001", "600002", "600003", "600004"}
    assert members["AI算力"] == {"300001"}


def test_frozen_union_direct_query_not_pool_cache(env, monkeypatch):
    """窗口池直查 day_leader_rows（审计 2026-10-24 P3：8000 长驻进程禁用
    _POOL_CACHE 无版本键——final 重采后成员集必须跟随更新）。"""
    assert not hasattr(sp, "_window_pool_of")   # 模块不得再引用 _POOL_CACHE 消费口
    calls: list[str] = []

    def spy(db, d, ds=None):
        calls.append(d)
        return (None, {})

    monkeypatch.setattr(sp, "day_leader_rows", spy)
    members, root = sp._frozen_union(env, TODAY)
    assert members == {} and root is None       # 全部池缺失如实为空，不报错
    assert calls                                # 确认走直查路径


def test_fetch_quotes_batch_error_variants(monkeypatch):
    """_fetch_quotes 三态：客户端不可用/全批次异常 → None（不可考）；
    客户端活着但零行情 → 空表（缺报价口径，不与不可考混同）。"""
    class BoomClient:
        def quotes(self, symbol):
            raise RuntimeError("conn reset")

    monkeypatch.setattr(sp, "_tdx_daily_client", lambda: None)
    assert sp._fetch_quotes({"600001"}) is None
    monkeypatch.setattr(sp, "_tdx_daily_client", lambda: BoomClient())
    assert sp._fetch_quotes({"600001", "600002"}) is None

    class EmptyClient:
        def quotes(self, symbol):
            return pd.DataFrame(columns=["code", "price", "last_close"])

    monkeypatch.setattr(sp, "_tdx_daily_client", lambda: EmptyClient())
    assert sp._fetch_quotes({"600001"}) == {}


def test_fetch_quotes_partial_batch_error_keeps_data(monkeypatch):
    """部分批次异常：剩余批次数据保留（缺报价逐板块披露），不整段判死。"""
    monkeypatch.setattr(sp, "_QUOTES_BATCH", 1)

    class FlakyClient:
        def quotes(self, symbol):
            if symbol == ["600001"]:
                raise RuntimeError("batch1 down")
            return pd.DataFrame([{"code": "600002", "price": 9.8, "last_close": 10.0}])

    monkeypatch.setattr(sp, "_tdx_daily_client", lambda: FlakyClient())
    assert sp._fetch_quotes({"600001", "600002"}) == {"600002": (9.8, 10.0)}


def test_pulse_stats_manual_check():
    """红盘率/聚合涨幅手算对拍 + 全缺不伪 0 + quotes_map=None 不可考。"""
    codes = {"600001", "600002", "600003", "600999"}   # 600999 缺报价
    s = _pulse_stats(QUOTES, codes)
    assert s["memberN"] == 4 and s["quotedN"] == 3 and s["missingN"] == 1
    assert s["pctMean"] == round((10.0 - 2.0 + 0.0) / 3, 2)
    assert s["redRatio"] == round(1 / 3, 3)
    empty = _pulse_stats(QUOTES, {"600998"})
    assert empty["pctMean"] is None and empty["redRatio"] is None
    assert empty["missingN"] == 1
    assert _pulse_stats(None, {"600001"})["pctMean"] is None


def test_compute_pulse_candidates_and_hint(env):
    """候选层=昨日节点∈{转弱,退潮}；chip=聚合涨幅>0 且红盘率≥0.5（零新阈值）。"""
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 11, 0, 0),
                            quotes_fetcher=_fetch_ok)
    assert payload["evidenceStage"] == "early"
    cands = {c["board"]: c for c in payload["candidates"]}
    # 候选=昨日 weakening（机器人）/collapse（AI算力）；wzs 的半导体不进候选
    assert set(cands) == {"机器人", "AI算力"}
    # 机器人：+10/-2/0/+10 → 均值 +4.5%、红盘 2/4=0.5 → chip 亮
    assert cands["机器人"]["hint"] is True
    assert cands["机器人"]["yesterdayNode"] == "weakening"
    # AI算力：单成员 -4.76% → 不亮
    assert cands["AI算力"]["hint"] is False
    # 全量层=封窗成员板块；昨日有节点但窗内无成员的板块（半导体）自然缺席
    assert {e["board"] for e in payload["all"]} == {"机器人", "AI算力"}
    assert payload["hintAny"] is True


def test_compute_pulse_tdx_down_fail_visible(env):
    """报价不可考 → pulse=None + 根因透出，不伪 0（预登记 §三）。"""
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 11, 0, 0),
                            quotes_fetcher=lambda codes: None)
    assert payload["ok"] is True
    assert all(e["pulse"] is None for e in payload["all"])
    assert "TDX 盘中报价不可考" in payload["meta"]["reason"]
    assert "不落 15:00 帧" in payload["meta"]["frameSkip"]


def test_compute_pulse_no_prev_trading_day(env, monkeypatch):
    """无昨日交易日 → 成员不可考根因（封窗无从谈起）。"""
    monkeypatch.setattr(sp, "trading_dates_before", lambda *a, **k: [])
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 11, 0, 0),
                            quotes_fetcher=_fetch_ok)
    assert "无昨日交易日" in payload["meta"]["reason"]
    assert payload["candidates"] == []


def test_frame_saved_after_1505_trading_day(env, monkeypatch):
    """≥15:05 且交易日 → 幂等落帧（_id={date}:PULSE）。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 6, 0),
                            quotes_fetcher=_fetch_ok)
    assert payload["meta"]["framesSaved"] is True
    assert env.pulse.replacements == [f"{TODAY}:PULSE"]
    frame = env.pulse.docs[f"{TODAY}:PULSE"]
    assert frame["date"] == TODAY and frame["evidenceStage"] == "closed"
    assert frame["_id"] == f"{TODAY}:PULSE"
    # 幂等：收盘后再算仍是同键覆盖（replace_one 计数=2、单档）
    compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 30, 0),
                  quotes_fetcher=_fetch_ok)
    assert env.pulse.replacements.count(f"{TODAY}:PULSE") == 2
    assert len([k for k in env.pulse.docs if k.endswith(":PULSE")]) == 1


def test_frame_not_saved_intraday_or_holiday(env, monkeypatch):
    """盘中不落帧；非交易日不落帧（frameSkip 披露判定来源）。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))
    p1 = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 14, 0, 0),
                       quotes_fetcher=_fetch_ok)
    assert p1["meta"]["framesSaved"] is False and env.pulse.replacements == []
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (False, "weekday"))
    p2 = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 10, 0),
                       quotes_fetcher=_fetch_ok)
    assert p2["meta"]["framesSaved"] is False
    assert "非交易日" in p2["meta"]["frameSkip"]
    assert env.pulse.replacements == []


def test_frame_not_saved_between_1500_and_1505(env, monkeypatch):
    """15:00-15:05 之间不落帧（预登记 §五 ≥15:05 条款，review 修复对齐）。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))
    p = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 2, 0),
                      quotes_fetcher=_fetch_ok)
    assert p["evidenceStage"] == "closed"
    assert p["meta"]["framesSaved"] is False and env.pulse.replacements == []
    assert "15:05" in p["meta"]["frameSkip"]


def test_frame_write_failure_does_not_kill_payload(env, monkeypatch):
    """帧写库异常不抛——展示数据不因次要写库连坐降级（AGENTS §4.0）。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))

    def boom(q, doc, upsert=False):
        raise RuntimeError("mongo down")

    env.pulse.replace_one = boom
    p = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 6, 0),
                      quotes_fetcher=_fetch_ok)
    assert p["ok"] is True and len(p["all"]) == 2   # 展示数据完好
    assert p["meta"]["framesSaved"] is False
    assert "帧写入失败" in p["meta"]["frameSkip"]


def test_evidence_stage_boundaries():
    """时点证据段边界：盘前无意义 / 早盘温和 / 午后强 / 收盘。"""
    assert _evidence_stage(datetime(2026, 10, 26, 9, 15)) == "pre_open"
    assert _evidence_stage(datetime(2026, 10, 26, 9, 30)) == "early"
    assert _evidence_stage(datetime(2026, 10, 26, 13, 29)) == "early"
    assert _evidence_stage(datetime(2026, 10, 26, 13, 30)) == "strong"
    assert _evidence_stage(datetime(2026, 10, 26, 15, 0)) == "closed"


def test_non_trading_day_stage_forced_closed(env, monkeypatch):
    """非交易日当日读数=最近交易日收盘口径：证据段强制 closed + 注记，
    不按钟表误标「早盘/盘前」（2026-10-25 用户验收反馈）；且不落帧。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (False, "weekday"))
    # 周六上午十点访问：钟表处于「早盘」，但读数是周五收盘
    p = compute_pulse(env, TODAY, now=datetime(2026, 10, 25, 10, 0, 0),
                      quotes_fetcher=_fetch_ok)
    assert p["evidenceStage"] == "closed"
    assert "非交易日" in p["meta"]["tradingDayNote"]
    assert p["meta"]["framesSaved"] is False and env.pulse.replacements == []


def test_trading_day_check_failure_degrades_visibly(env, monkeypatch):
    """交易日判定不可用 → 按钟表分段 + 注记（fail-visible，不炸读口）。"""
    def boom(d):
        raise RuntimeError("bridge down and no cache")

    monkeypatch.setattr(trading_calendar, "is_trading_day_cached", boom)
    p = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 11, 0, 0),
                      quotes_fetcher=_fetch_ok)
    assert p["evidenceStage"] == "early"          # 钟表分段兜底
    assert "交易日判定不可用" in p["meta"]["tradingDayNote"]


def test_get_pulse_cached_60s(env, monkeypatch):
    """60s 缓存壳：同日 60s 内命中缓存不重算，过期重算。"""
    seen: list[str] = []
    orig = sp.compute_pulse

    def spy(db, today, ds=None, *, now=None, quotes_fetcher=None):
        seen.append(today)
        return orig(db, today, ds, now=now, quotes_fetcher=_fetch_ok)

    monkeypatch.setattr(sp, "compute_pulse", spy)
    p1 = get_pulse_cached(env, TODAY, now=datetime(2026, 10, 26, 10, 0, 0))
    p2 = get_pulse_cached(env, TODAY, now=datetime(2026, 10, 26, 10, 0, 30))
    assert len(seen) == 1 and p1 is p2      # 30s 命中缓存，同一 payload
    p3 = get_pulse_cached(env, TODAY, now=datetime(2026, 10, 26, 10, 1, 1))
    assert len(seen) == 2 and p3["date"] == TODAY   # 61s 过期重算
