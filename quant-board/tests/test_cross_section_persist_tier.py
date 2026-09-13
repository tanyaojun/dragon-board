# -*- coding: utf-8 -*-
"""crossSection A 档"持续高位"替代路径（2026-09-13 方案2，四维算法研究流程）。

数学边界：delta = pct[-1] − pct[-2] ≤ 100 − pct[-1]，percentile > 95 的强势股
（榜首 pct=100）永远无法满足 A 档 delta>=5 上升确认——它们没有"继续上升"的空间，
强势体现在"持续停留高位"。方案2 给 A 档加第二条路径：

    pct >= crossSectionPersistMin(90) 且 近 N 帧均值 >= crossSectionPersistMeanMin(85)
    且窗口满 N 帧合法值（证据不足不伪造，fail-visible）

默认关闭（crossSectionPersistFrames=0）→ golden 不漂移；判定顺序
A-delta > A-persist > 原分支 → 开启后行为变更 = 纯增量（部分 B 升 A），
原 A/B/C/D 输出与文案全部不变。

结构性事实：persist 窗口取最后 N 帧（N>=2）必含 [-2] 项，故 persist 非 None 时
percentiles[-2] 必合法 → delta 必非 None。首帧/单点序列/新股天然不触发持续路径。
"""
from __future__ import annotations

import math

import pytest

from backend.analysis.ranktrend.engine.config import RankTrendConfig
from backend.analysis.ranktrend.trend.cross_section import (
    CROSS_SECTION_DEFAULTS,
    compute_cross_section,
)


def _cs(percentiles: list[float], config: RankTrendConfig | None = None) -> dict:
    return compute_cross_section(percentiles, 50.0, config or RankTrendConfig())


def _enabled(**overrides) -> RankTrendConfig:
    return RankTrendConfig(crossSectionPersistFrames=3, **overrides)


# ---------------------------------------------------------------------------
# 默认关闭：golden 不漂移锚点
# ---------------------------------------------------------------------------


def test_default_config_persist_path_disabled() -> None:
    """默认 crossSectionPersistFrames=0：榜首稳定 pct=100 序列仍走原分支 → B（横截面高位）。

    修复 delta 复活后榜首股 delta 仍受数学边界压制（delta ≤ 100−pct = 0），
    默认行为必须与方案1 之后完全一致。"""
    cs = _cs([100.0, 100.0, 100.0])
    assert cs["percentile"] == pytest.approx(100.0)
    assert cs["percentileDelta"] == pytest.approx(0.0)
    assert cs["signalTier"] == "B"
    assert cs["tierReasons"] == ["横截面高位"]


def test_default_config_fields_exist() -> None:
    """新参数默认值：Frames=0（关闭）、Min=90、MeanMin=85；CROSS_SECTION_DEFAULTS 对齐。"""
    c = RankTrendConfig()
    assert c.crossSectionPersistFrames == 0
    assert c.crossSectionPersistMin == pytest.approx(90.0)
    assert c.crossSectionPersistMeanMin == pytest.approx(85.0)
    assert CROSS_SECTION_DEFAULTS["crossSectionPersistFrames"] == 0.0
    assert CROSS_SECTION_DEFAULTS["crossSectionPersistMin"] == 90.0
    assert CROSS_SECTION_DEFAULTS["crossSectionPersistMeanMin"] == 85.0


# ---------------------------------------------------------------------------
# 开启后：持续高位 → A 档
# ---------------------------------------------------------------------------


def test_persist_sustained_high_gives_tier_a() -> None:
    """[92, 96, 100]：delta=4 < 5（delta 路径够不到）但 pct=100 ≥ 90、近 3 帧均值
    96 ≥ 85 → A（持续高位）。"""
    cs = _cs([92.0, 96.0, 100.0], _enabled())
    assert cs["percentile"] == pytest.approx(100.0)
    assert cs["signalTier"] == "A"
    assert any("持续高位" in reason for reason in cs["tierReasons"])


def test_persist_stable_top_gives_tier_a() -> None:
    """榜首股 [100,100,100]：delta=0（数学上永远如此）但持续高位 → A。"""
    cs = _cs([100.0, 100.0, 100.0], _enabled())
    assert cs["signalTier"] == "A"
    assert cs["percentileDelta"] == pytest.approx(0.0)


def test_persist_tolerates_small_pullback() -> None:
    """[100, 98, 99]：delta=+1 不够上升确认，但 pct=99 持续极高位 → A（路径本义）。"""
    cs = _cs([100.0, 98.0, 99.0], _enabled())
    assert cs["signalTier"] == "A"
    assert any("持续高位" in reason for reason in cs["tierReasons"])


# ---------------------------------------------------------------------------
# 门槛与窗口约束：证据不足不触发（fail-visible）
# ---------------------------------------------------------------------------


def test_persist_partial_window_no_trigger() -> None:
    """序列 [95, 98]（2 帧 < N=3）：窗口不满 → 不触发，delta=3 不够上升确认 → B。"""
    cs = _cs([95.0, 98.0], _enabled())
    assert cs["signalTier"] == "B"
    assert not any("持续高位" in reason for reason in cs["tierReasons"])


def test_persist_mean_below_threshold_no_trigger() -> None:
    """[40, 100, 100]：均值 80 < 85（长期低位刚翻上来不算持续高位）且 delta=0
    不够上升确认 → B。"""
    cs = _cs([40.0, 100.0, 100.0], _enabled())
    assert cs["signalTier"] == "B"


def test_persist_current_below_min_no_trigger() -> None:
    """[94, 92, 88]：均值 91.3 达标但当前 pct=88 < 90（已从高位回落）→ B。"""
    cs = _cs([94.0, 92.0, 88.0], _enabled())
    assert cs["signalTier"] == "B"


def test_persist_invalid_value_breaks_window() -> None:
    """[92, NaN, 100]：窗口内非法值 → 合法样本 2 < N=3 → 不触发（不伪造持续证据）。"""
    cs = _cs([92.0, math.nan, 100.0], _enabled())
    assert cs["signalTier"] == "B"


def test_persist_single_point_no_trigger() -> None:
    """单点 [100]（首帧/新股）：窗口不满 → 首帧降级 B，不给 A。"""
    cs = _cs([100.0], _enabled())
    assert cs["signalTier"] == "B"
    assert any("首帧" in reason for reason in cs["tierReasons"])


# ---------------------------------------------------------------------------
# 判定优先级：A-delta > A-persist（开启后原 A 输出与文案不变）
# ---------------------------------------------------------------------------


def test_delta_path_takes_priority_over_persist() -> None:
    """[80, 88, 96]：delta=8 命中上升确认 → A 文案保持原"高位 + 热度排名上升"，
    不被持续路径覆盖（开启 persist 后原 A 输出零漂移）。"""
    cs = _cs([80.0, 88.0, 96.0], _enabled())
    assert cs["signalTier"] == "A"
    assert cs["tierReasons"] == ["高位 + 热度排名上升（横截面强势确认）"]


def test_persist_does_not_affect_mid_band() -> None:
    """[40, 45, 60]：均值 48.3 < 85、当前 60 < 90 → 原分支判定不受 persist 影响
    （delta=15 命中 B-mid，文案保持原样）。"""
    cs = _cs([40.0, 45.0, 60.0], _enabled())
    assert cs["signalTier"] == "B"
    assert cs["tierReasons"] == ["中位之上 + 热度显著上升"]


# ---------------------------------------------------------------------------
# 引擎集成：live 去尾序列上的持续路径（榜首股端到端）
# ---------------------------------------------------------------------------


def _stock(code: str, avg_rank_num: float) -> dict:
    return {
        "code": code,
        "name": f"股{code}",
        "avgRankNum": avg_rank_num,
        "rank": 1,
        "change": 2.0,
        "volumeRatio": 1.5,
        "zlje": 1200.0,
        "zljzb": 1.2,
        "amount": 5000.0,
        "price": 10.0,
        "turnover": 80000.0,
    }


def _stocks(avg: float) -> list[dict]:
    return [_stock("600000", avg)] + [_stock(f"60000{i}", float(i)) for i in range(1, 10)]


def _bundle(date: str, avg: float, ts: int) -> dict:
    return {
        "tradingDate": date,
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": ts,
        "rows": _stocks(avg),
        "hotThemes": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }


def _live_analyze_last(config: RankTrendConfig) -> dict:
    """live 链路端到端：三帧榜单 600000 均为榜首（pct=100）+ current 复制尾帧。"""
    from backend.analysis.ranktrend.engine import RankTrendPythonEngine
    from backend.api.ranktrend_routes import _analyze_frames, _load_frames_for_analysis

    bundles = [_bundle("2026-08-12", 0.5, 1), _bundle("2026-08-13", 0.5, 2), _bundle("2026-08-14", 0.5, 3)]
    current = {
        "tradingDate": "2026-08-14",
        "slotTime": "current:1",
        "stocks": _stocks(0.5),
    }

    class FakeRepo:
        def __init__(self, frames: list[dict]):
            self.frames = frames

        def load_frame_bundles(self, *args, **kwargs):
            return list(self.frames)

    frames, series = _load_frames_for_analysis(
        FakeRepo(bundles), "dragonboard_live", "half_hour", [], current_frame=current, codes=None
    )
    output = _analyze_frames(RankTrendPythonEngine(config=config), frames, series, [])
    assert output, "analyze 无输出"
    return output[-1]


def _cs_of(frame: dict, code: str = "600000") -> dict:
    stock = next(s for s in frame["stocks"] if s.get("code") == code)
    return ((stock.get("analysis") or {}).get("observation") or {}).get("crossSection") or {}


def test_engine_live_default_keeps_b_for_stable_top() -> None:
    """默认 config：榜首股 live 去尾序列 [100,100,100] delta=0 → B（方案1 后现行为）。"""
    last = _live_analyze_last(RankTrendConfig())
    cs = _cs_of(last)
    assert cs["signalTier"] == "B"
    assert cs["tierReasons"] == ["横截面高位"]


def test_engine_live_persist_enabled_gives_a_for_stable_top() -> None:
    """开启 N=3：同一 live 序列去尾后窗口满 3 帧且均值 100 → A（持续高位），
    且 technical 挂载与 observation 一致（两处挂载点同源）。"""
    last = _live_analyze_last(RankTrendConfig(crossSectionPersistFrames=3))
    cs = _cs_of(last)
    assert cs["signalTier"] == "A"
    assert any("持续高位" in reason for reason in cs["tierReasons"])

    stock = next(s for s in last["stocks"] if s.get("code") == "600000")
    analysis = stock.get("analysis") or {}
    assert (analysis.get("technical") or {}).get("crossSection") == cs
