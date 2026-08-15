"""样本状态判定口径（阶段 2 数据质量治理）。

背景：sampleQuality.status 原先用 get_technical_min_samples（=max(macdSlow, momentum.max+1, 30)=34 帧）
判定 ok——该门槛混入了 MACD 预热需求。half_hour 快照下 50 帧滑动窗口跨周末/热榜轮动稀释在榜帧数，
34 帧门槛导致 ok 占比仅 ~46%（20 个历史回测全部 researchGrade=degraded）。
修复：ok 判定改为动量可计算门槛 get_momentum_min_samples（momentumPeriods.max+1=22 帧）；
MACD 预热状态仍通过 _macd_diagnostics.hasStableObservationBars 单独暴露（fail-visible，不隐藏）。

合同：
- len(percentiles) >= 22 → ok
- 5 <= len(percentiles) < 22 → degraded
- len(percentiles) < 5 → insufficient
- _sample_diagnostics.requiredTechnicalBars 与判定口径一致（22），MACD 需求另列 macdMinimumBars
"""

from __future__ import annotations

import pytest

from backend.analysis.ranktrend.engine import (
    RankTrendConfig,
    RankTrendPythonEngine,
    get_momentum_min_samples,
    market_regime,
)


def _make_stock() -> dict:
    return {"code": "000001", "change": 1.2, "volumeRatio": 1.5, "zlje": 1000, "zljzb": 2.0}


def _make_frame() -> dict:
    return {
        "snapshotId": "half_hour:2026-08-14:15:00",
        "type": "half_hour",
        "timestamp": 1000,
        "tradingDate": "2026-08-14",
        "slotTime": "15:00",
    }


def _signal_status(percentile_count: int) -> str:
    engine = RankTrendPythonEngine()
    frame = _make_frame()
    percentiles = [50.0] * percentile_count
    ranks = [float(i) for i in range(percentile_count, 0, -1)]
    signal = engine._build_signal(
        _make_stock(),
        frame,
        ranks,
        percentiles,
        market_regime(frame),
        {"sampleQuality": "ok", "warnings": []},
    )
    assert signal is not None
    return str(((signal.get("rankTrend") or {}).get("meta") or {}).get("sampleQuality", {}).get("status") or "")


def test_sample_status_ok_at_momentum_min_samples() -> None:
    """动量最小可计算样本（22 帧，momentumPeriods.max+1）应判 ok；
    修复前 34 帧门槛会把 22~33 帧误判 degraded（阶段 2 根因）。"""
    config = RankTrendConfig()
    assert get_momentum_min_samples(config) == 22
    assert _signal_status(22) == "ok"
    assert _signal_status(34) == "ok"


def test_sample_status_degraded_below_momentum_min_samples() -> None:
    """5~21 帧：可计算但不足以支持动量全周期 → degraded。"""
    assert _signal_status(21) == "degraded"
    assert _signal_status(5) == "degraded"


def test_sample_status_insufficient_below_5() -> None:
    """<5 帧：样本严重不足 → insufficient，不应作为强交易依据。"""
    assert _signal_status(4) == "insufficient"
