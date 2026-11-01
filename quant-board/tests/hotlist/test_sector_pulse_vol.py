# -*- coding: utf-8 -*-
"""V4-E 日内量能锚测试（预登记 sector-nodes-v4e-intraday-vol-preregistration.md）。

覆盖：帧捕获窗边界 / quotes amount 提取（NaN/缺列 fail-visible）/ 成员级量比
配对中位手算（缺帧/缺成员/零成交剔除不铸 0）/ volTag 三向 / 盘中帧与 15:00 帧
共存 / 非交易日不落帧 / lc5 回填帧（src=lc5_backfill）作为量比基线与 volTag 基准。
全 mock（QUOTES 注入 + FakeDB），禁真实 jev 调用（AGENTS §1.2-7）。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from backend.operations import sector_pulse as sp
from backend.operations.sector_pulse import (
    _board_vol_ratio,
    _fetch_quotes,
    _frame_key_of,
    _member_amounts,
    _vol_tag_of,
    compute_pulse,
)

from tests.hotlist.test_sector_pulse import FakeCollection, FakeDB  # noqa: F401
import backend.snapshot_collector.trading_calendar as trading_calendar
from backend.operations.sector_pulse import get_pulse_cached  # noqa: F401

TODAY = "2026-10-26"   # 周一
PREV = "2026-10-23"    # 周五


@pytest.fixture
def env(monkeypatch):
    """同 test_sector_pulse.env 口径：冻结窗+交易日序列+昨日节点（弱转强候选）。"""
    dates_before = {
        TODAY: [f"2026-10-{d:02d}" for d in range(9, 24)],
        PREV: [f"2026-10-{d:02d}" for d in range(6, 23)],
    }
    monkeypatch.setattr(sp, "trading_dates_before",
                        lambda db, date, n, dataset_id=None: dates_before[date][-n:])

    def _rows(board_codes):
        return [{"board": b, "boardCodes": cs} for b, cs in board_codes.items()]

    pools = {
        PREV: (_rows({"机器人": ["600001", "600002", "600003", "600004"],
                      "AI算力": ["300001"]}), {"jiuyanFinalFound": True}),
    }
    monkeypatch.setattr(sp, "day_leader_rows",
                        lambda db, d, ds=None: pools.get(d, (None, {})))
    nodes = FakeCollection()
    nodes.docs[f"{PREV}:SECTOR_NODES"] = {"rows": [
        {"board": "机器人", "node": "weakening"},
        {"board": "AI算力", "node": "collapse"}]}
    db = FakeDB()
    db.nodes = nodes
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (True, "weekday"))
    return db


def _fetch(prices=None, amounts=None):
    """构造 quotes_fetcher：prices/amounts 缺项 → 成员缺报价/缺 amount。"""
    prices = prices or {}
    amounts = amounts or {}

    def f(codes):
        out = {}
        for c in codes:
            p = prices.get(c)
            if p is None:
                continue
            out[c] = (p[0], p[1], amounts.get(c, p[2] if len(p) > 2 else None))
        return out
    return f


# ---- 帧捕获窗 ----

def test_frame_key_of_windows():
    """帧末+5 分钟捕获窗；午休/尾盘空档无窗；15:00 帧沿用 ≥15:05。"""
    F = lambda h, m, s=0: datetime(2026, 10, 26, h, m, s)
    assert _frame_key_of(F(10, 0, 30)) == "10:00"
    assert _frame_key_of(F(10, 5, 59)) == "10:00"
    assert _frame_key_of(F(10, 6)) is None           # 10:00 帧窗已关，10:30 帧未开
    assert _frame_key_of(F(10, 35)) == "10:30"
    assert _frame_key_of(F(11, 35)) == "11:30"
    assert _frame_key_of(F(11, 50)) is None          # 午休空档
    assert _frame_key_of(F(13, 31)) == "13:30"
    assert _frame_key_of(F(14, 36)) is None          # 14:30 帧窗已关
    assert _frame_key_of(F(15, 4)) is None           # 15:05 前不落
    assert _frame_key_of(F(15, 6)) == "15:00"
    assert _frame_key_of(F(15, 40)) == "15:00"
    assert _frame_key_of(F(9, 15)) is None           # 盘前


# ---- quotes amount 提取（fail-visible） ----

def test_fetch_quotes_amount_extraction(monkeypatch):
    """amount 列：正常提取 / NaN → None / 缺列 → None，不铸 0。"""
    class Client:
        def quotes(self, symbol):
            if symbol == ["600001"]:
                return pd.DataFrame([{"code": "600001", "price": 11.0,
                                      "last_close": 10.0, "amount": 1.5e8}])
            if symbol == ["600002"]:
                return pd.DataFrame([{"code": "600002", "price": 9.8,
                                      "last_close": 10.0, "amount": float("nan")}])
            return pd.DataFrame([{"code": "600003", "price": 5.0,
                                  "last_close": 5.0}])   # 无 amount 列

    monkeypatch.setattr(sp, "_tdx_daily_client", lambda: Client())
    monkeypatch.setattr(sp, "_QUOTES_BATCH", 1)
    q = _fetch_quotes({"600001", "600002", "600003"})
    assert q["600001"][2] == 1.5e8
    assert q["600002"][2] is None      # NaN → None（不铸 0）
    assert q["600003"][2] is None      # 缺列 → None


def test_member_amounts_skip_unquotable():
    """amount 不可考成员不入明细表（由 amountMissingN 对账），不铸 0。"""
    qm = {"600001": (11.0, 10.0, 1.2e8), "600002": (9.8, 10.0, None),
          "600003": (5.0, 5.0, 0.0)}
    assert _member_amounts(qm, {"600001", "600002", "600003"}) == \
        {"600001": 1.2e8, "600003": 0.0}
    assert _member_amounts(None, {"600001"}) == {}


# ---- 量比配对中位手算 ----

def test_board_vol_ratio_pairing_manual():
    """V4-D 配对口径：两侧均>0 才进样本；缺/零成交/缺帧剔除不铸 0。"""
    prev_boards = {"机器人": {"amounts": {"600001": 1.0e8, "600002": 5.0e7,
                                         "600003": 0.0}}}   # 600004 昨日缺、600003 零成交
    today = {"600001": 1.2e8, "600002": 6.5e7, "600003": 3.0e6, "600004": 8.0e6}
    med, n = _board_vol_ratio(prev_boards, "机器人", today)
    assert n == 2                                   # 只剩 600001/600002 配对
    assert med == round((1.2 + 1.3) / 2, 3)         # (1.2e8/1.0e8 + 6.5e7/5.0e7)/2
    # 单成员：中位=自身
    med1, n1 = _board_vol_ratio(prev_boards, "机器人", {"600001": 1.2e8})
    assert n1 == 1 and med1 == 1.2
    # 板块昨日无帧 → (None, 0)
    assert _board_vol_ratio(None, "机器人", today) == (None, 0)
    assert _board_vol_ratio(prev_boards, "AI算力", today) == (None, 0)


# ---- 盘中帧落库 + volTag ----

def test_intraday_frame_saved_and_vol_tag(env):
    """10:33 请求 → 落 10:30 帧（量比=昨日 10:30 帧配对中位）+ 候选 volTag。"""
    env.pulse.docs[f"{PREV}:PULSE"] = {"frames": {"10:30": {
        "src": "lc5_backfill", "volBasis": "prev_frame",
        "boards": {"机器人": {"amounts": {"600001": 1.0e8, "600002": 5.0e7,
                                         "600003": 0.0}},
                   "AI算力": {"amounts": {"300001": 2.0e7}}}}}}
    # 机器人翻红（+10/-2/0/+10 → 均值 4.5%、红盘 0.5）量比中位 1.25 → vol_confirm
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "600003": (5.0, 5.0), "600004": (2.2, 2.0), "300001": (20.0, 21.0)}
    amounts = {"600001": 1.2e8, "600002": 6.5e7, "600003": 3.0e6,
               "600004": 8.0e6, "300001": 2.5e7}
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                            quotes_fetcher=_fetch(prices, amounts))
    assert payload["meta"]["framesSaved"] is True
    assert payload["meta"]["frameSavedKey"] == "10:30"
    doc = env.pulse.docs[f"{TODAY}:PULSE"]
    fr = doc["frames"]["10:30"]
    assert fr["src"] == "live" and fr["volBasis"] == "prev_frame"
    rb = fr["boards"]["机器人"]
    assert rb["volRatioQuotedN"] == 2 and rb["volRatioMedian"] == 1.25
    assert rb["amounts"]["600001"] == 1.2e8
    assert rb["amountMissingN"] == 0 and rb["amountQuotedN"] == 4
    cands = {c["board"]: c for c in payload["candidates"]}
    assert cands["机器人"]["volTag"] == "vol_confirm"
    assert cands["机器人"]["volTagFrame"] == "10:30"
    assert cands["机器人"]["volRatioMedian"] == 1.25
    # 全部行透出量比数值（观察位：直显放量/缩量，非仅候选 chip）
    allrows = {e["board"]: e for e in payload["all"]}
    assert allrows["机器人"]["volRatioMedian"] == 1.25
    assert allrows["机器人"]["volFrame"] == "10:30"
    assert allrows["AI算力"]["volRatioMedian"] is not None   # 昨日同帧有 300001
    # AI算力：不红（单成员 -4.76%）→ volTag None（量比可考但帧内不红不注记）
    assert cands["AI算力"]["volTag"] is None


def test_vol_tag_thin_and_missing(env):
    """缩量翻红 → vol_thin；昨日缺同帧 → 量比不可考 → volTag None（不注记）。"""
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "600003": (5.0, 5.0), "600004": (2.2, 2.0), "300001": (20.0, 21.0)}
    amounts = {"600001": 0.8e8, "600002": 3.0e7, "600003": 1.0e6,
               "600004": 4.0e6, "300001": 2.5e7}
    # 昨日只有 10:30 帧：今日 10:33 请求配对中位 0.8 → vol_thin
    env.pulse.docs[f"{PREV}:PULSE"] = {"frames": {"10:30": {
        "boards": {"机器人": {"amounts": {"600001": 1.0e8, "600002": 5.0e7}}}}}}
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                            quotes_fetcher=_fetch(prices, amounts))
    cands = {c["board"]: c for c in payload["candidates"]}
    assert cands["机器人"]["volTag"] == "vol_thin"
    assert cands["AI算力"]["volTag"] is None     # 昨日无该板块帧 → 量比不可考
    # 昨日无任何 frames → volBasis missing：今日 10:33 帧量比不可考 → volTag None
    del env.pulse.docs[f"{PREV}:PULSE"]
    env.pulse.docs[f"{TODAY}:PULSE"] = {"frames": {}}   # 清今日帧重建
    p2 = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 36, 0),
                       quotes_fetcher=_fetch(prices, amounts))   # 10:30 帧窗已关
    assert all(c["volTag"] is None for c in p2["candidates"])
    assert p2["meta"]["framesSaved"] is False


def test_vol_tag_none_when_frame_not_red(env):
    """当日最近帧不红（回落）→ volTag None，即使量比高（量能锚只在红盘帧语义）。"""
    env.pulse.docs[f"{TODAY}:PULSE"] = {"frames": {"10:00": {
        "boards": {"机器人": {"pctMean": -1.0, "redRatio": 0.2,
                              "volRatioMedian": 1.8}}}}}
    tag = _vol_tag_of(env.pulse.docs[f"{TODAY}:PULSE"]["frames"]["10:00"]["boards"]["机器人"])
    assert tag is None


def test_vol_tag_missing_ratio(env):
    """帧内红盘但量比不可考 → None（不注记，fail-visible）。"""
    assert _vol_tag_of({"pctMean": 2.0, "redRatio": 0.8, "volRatioMedian": None}) is None
    assert _vol_tag_of(None) is None


# ---- 帧共存与幂等 ----

def test_intraday_and_1500_frames_coexist(env):
    """盘中帧先落，15:00 帧后落 → update_one 保留盘中帧；顶层=15:00 读数。"""
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "600003": (5.0, 5.0), "600004": (2.2, 2.0), "300001": (20.0, 21.0)}
    amounts = {"600001": 1.2e8, "600002": 3.4e7, "600003": 0.0,
               "600004": 8.0e6, "300001": 2.5e7}
    compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                  quotes_fetcher=_fetch(prices, amounts))
    compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 15, 6, 0),
                  quotes_fetcher=_fetch(prices, amounts))
    doc = env.pulse.docs[f"{TODAY}:PULSE"]
    assert set(doc["frames"]) == {"10:30", "15:00"}
    assert doc["evidenceStage"] == "closed"          # 顶层=15:00 读数
    assert doc["frames"]["10:30"]["src"] == "live"
    assert doc["meta"]["framesSaved"] is True and doc["meta"]["frameSavedKey"] == "15:00"


def test_backfill_frame_consumed_as_baseline_and_voltag(env):
    """lc5 回填帧（src=lc5_backfill）可作为 volTag 基准；捕获窗内 live 帧覆盖
    回填帧（live 优先，幂等同键），量比基线缺失时 volTag 如实 None。"""
    env.pulse.docs[f"{TODAY}:PULSE"] = {"frames": {"10:00": {
        "src": "lc5_backfill", "volBasis": "prev_frame",
        "boards": {"机器人": {"pctMean": 3.0, "redRatio": 0.75,
                              "amounts": {"600001": 1.1e8},
                              "volRatioMedian": 1.1, "volRatioQuotedN": 1}}}}}
    fetcher = _fetch({"600001": (11.0, 10.0), "600002": (9.8, 10.0),
                      "600003": (5.0, 5.0), "600004": (2.2, 2.0),
                      "300001": (20.0, 21.0)},
                     {"600001": 1.2e8})
    # 窗外请求（10:06）→ 不落帧，volTag 来自回填帧 10:00
    p_out = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 6, 0),
                          quotes_fetcher=fetcher)
    assert p_out["meta"]["framesSaved"] is False
    cands = {c["board"]: c for c in p_out["candidates"]}
    assert cands["机器人"]["volTag"] == "vol_confirm"
    assert cands["机器人"]["volTagFrame"] == "10:00"
    assert cands["机器人"]["volRatioMedian"] == 1.1
    # 捕获窗内请求（10:02）→ live 帧覆盖回填帧；无昨日帧 → 量比不可考 → volTag None
    p_in = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 2, 0),
                         quotes_fetcher=fetcher)
    assert p_in["meta"]["frameSavedKey"] == "10:00"
    doc = env.pulse.docs[f"{TODAY}:PULSE"]
    assert doc["frames"]["10:00"]["src"] == "live"
    cands = {c["board"]: c for c in p_in["candidates"]}
    assert cands["机器人"]["volTag"] is None     # live 帧量比基线缺失，不注记


def test_non_trading_day_intraday_no_frame(env, monkeypatch):
    """非交易日盘中钟表落在捕获窗 → 仍不落帧（交易日判定优先）。"""
    monkeypatch.setattr(trading_calendar, "is_trading_day_cached",
                        lambda d: (False, "weekday"))
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 25, 10, 33, 0),
                            quotes_fetcher=_fetch(
                                {"600001": (11.0, 10.0)}, {"600001": 1.0e8}))
    assert payload["meta"]["framesSaved"] is False
    assert "非交易日" in payload["meta"]["frameSkip"]
    assert env.pulse.updates == []


# ---- V4-F 核心票翻红率 + 量级分位 ----

def test_strong_subset_red_ratio(env, monkeypatch):
    """核心票=昨日连板≥2 子集（streak_map 单一事实源）；子集红盘率独立于全体。"""
    monkeypatch.setattr(sp, "jiuyan_streak_map",
                        lambda db, d, dataset_id=None, **k: {
                            "600001": 3, "600002": 2, "600003": 1, "600004": None})
    monkeypatch.setattr(sp, "_amount_sum_history", lambda db, d, days=60: {})
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0),
              "600003": (5.0, 5.0), "600004": (2.2, 2.0), "300001": (20.0, 21.0)}
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                            quotes_fetcher=_fetch(prices, {"600001": 1e8}))
    e = {x["board"]: x for x in payload["all"]}["机器人"]
    # 600001(+10%)/600002(-2%) 连板≥2 且有报价 → 子集红盘率 1/2
    assert e["strongN"] == 2 and e["strongQuotedN"] == 2
    assert e["strongRedN"] == 1 and e["strongRedRatio"] == 0.5
    # streak=1 / None 的成员不进子集
    assert e["pulse"]["memberN"] == 4


def test_strong_subset_empty_when_no_streak_map(env, monkeypatch):
    """streak_map 不可考（异常/空）→ 子集空、全 None，不铸 0。"""
    monkeypatch.setattr(sp, "jiuyan_streak_map",
                        lambda db, d, dataset_id=None, **k: {"600001": 1})
    monkeypatch.setattr(sp, "_amount_sum_history", lambda db, d, days=60: {})
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                            quotes_fetcher=_fetch({"600001": (11.0, 10.0)},
                                                  {"600001": 1e8}))
    e = {x["board"]: x for x in payload["all"]}["机器人"]
    assert e["strongN"] == 0 and e["strongRedRatio"] is None


def test_amount_pct_percentile(env, monkeypatch):
    """量级分位：hist<min_n=20 → None；手算 below/len；amountSum None → None。"""
    monkeypatch.setattr(sp, "jiuyan_streak_map", lambda db, d, dataset_id=None, **k: {})
    hist = [float(i) for i in range(25)]      # 25 样本
    monkeypatch.setattr(sp, "_amount_sum_history",
                        lambda db, d, days=60: {"机器人": hist, "AI算力": [1.0, 2.0]})
    prices = {"600001": (11.0, 10.0), "600002": (9.8, 10.0), "600003": (5.0, 5.0),
              "600004": (2.2, 2.0), "300001": (20.0, 21.0)}
    amounts = {"600001": 24.0, "600002": 3e7, "600003": 0.0, "600004": 8e6,
               "300001": 2.5e7}
    payload = compute_pulse(env, TODAY, now=datetime(2026, 10, 26, 10, 33, 0),
                            quotes_fetcher=_fetch(prices, amounts))
    e = {x["board"]: x for x in payload["all"]}
    # 机器人 amountSum=24+3e7+0+8e6 ≈ 3.8e7 > hist 全部（0..24 元）→ P100
    assert e["机器人"]["amountPct"] == 1.0 and e["机器人"]["amountPctN"] == 25
    # AI算力 hist=2 样本 <20 → None 如实
    assert e["AI算力"]["amountPct"] is None and e["AI算力"]["amountPctN"] == 2
