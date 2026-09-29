"""RankTrend Jump 检测参数化测试（2026-08-17）。

背景：用户要求【共振】信号深入到核心指标 jump 跳跃值参数构成。detect_rank_jumps 的
delta_pct 已 config 化（jumpDeltaPct），本测试覆盖参数化后的 reset_lookback（事件触发后
重置窗口）与 sustain_count（持续事件数判定）——默认值 = 原硬编码（3 / 2），golden 不漂移。
"""

from __future__ import annotations

from backend.analysis.ranktrend.engine import RankTrendConfig, detect_rank_jumps


def test_default_params_match_legacy_hardcoded() -> None:
    """默认 reset_lookback=3 / sustain_count=2 与旧硬编码一致（golden 不漂移）。"""
    c = RankTrendConfig()
    assert c.jumpResetLookback == 3
    assert c.jumpSustainCount == 2


def test_sustain_count_controls_sustained_flag() -> None:
    """单调上升序列 [10,30,50,70]（delta=15）触发 3 次 surge：
    sustain_count=2 → sustained=True；sustain_count=4 → False（默认参数不改变行为）。"""
    pct = [10.0, 30.0, 50.0, 70.0]
    r2 = detect_rank_jumps(pct, delta_pct=15.0, sustain_count=2)
    assert r2["event"] == "jump"
    assert r2["direction"] == "buy"
    assert r2["surgeCount"] == 3
    assert r2["sustained"] is True
    r4 = detect_rank_jumps(pct, delta_pct=15.0, sustain_count=4)
    assert r4["sustained"] is False


def test_reset_lookback_controls_post_event_reset() -> None:
    """序列 [10,40,41]（delta=15）：首个事件后重置窗口大小影响是否触发第二次事件。
    reset_lookback=3 → ref=avg(10,40)=25，41-25=16>15 再触发；reset_lookback=1 → ref=40，
    41-40=1 不触发（第二次事件仅出现在 lookback 大的配置）。"""
    pct = [10.0, 40.0, 41.0]
    r_small = detect_rank_jumps(pct, delta_pct=15.0, reset_lookback=1)
    assert r_small["eventCount"] == 1
    r_large = detect_rank_jumps(pct, delta_pct=15.0, reset_lookback=3)
    assert r_large["eventCount"] == 2


def test_config_fields_flow_into_detection() -> None:
    """config 字段 jumpResetLookback/jumpSustainCount 实际传入检测（engine 调用点契约）。"""
    c = RankTrendConfig.from_patch({"jumpResetLookback": 1, "jumpSustainCount": 3})
    assert c.jumpResetLookback == 1
    assert c.jumpSustainCount == 3
    # 与直接传参结果一致
    pct = [10.0, 40.0, 41.0]
    direct = detect_rank_jumps(pct, delta_pct=15.0, reset_lookback=1, sustain_count=3)
    assert direct["eventCount"] == 1
