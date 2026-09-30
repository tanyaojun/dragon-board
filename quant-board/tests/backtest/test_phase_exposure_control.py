# -*- coding: utf-8 -*-
"""M3 相位暴露控制研究开关测试（ranktrend-phase-acceptance-design.md §5 M3 ①载体）。

默认关（trade_config 无 phaseExposureControl 键）→ factor=1.0，行为与历史逐位一致（golden 不漂移）。
as-of 纪律：入场日 d 的相位 = eodScores 中**严格早于 d 的最近交易日**的 EOD 分（前日定相，无未来函数）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.core.backtest.execution import TradeSimulator

EOD = {"2026-09-25": 30.0, "2026-09-26": 70.0, "2026-09-27": 45.0}


def _cfg(mode: str | None, factor: float = 0.5, threshold: float = 50.0, eod: dict | None = None) -> dict:
    cfg: dict = {}
    if mode is not None:
        cfg["phaseExposureControl"] = {
            "mode": mode, "factor": factor, "threshold": threshold, "eodScores": EOD if eod is None else eod,
        }
    return cfg


def test_absent_key_defaults_off():
    assert TradeSimulator._phase_exposure_factor({}, "2026-09-28") == 1.0


def test_mode_off_explicit():
    assert TradeSimulator._phase_exposure_factor(_cfg("off"), "2026-09-28") == 1.0


def test_reduce_defense_hits_low_prev_score():
    # 09-28 的前一日=09-27（45 分 <50 防守）→ 降仓
    assert TradeSimulator._phase_exposure_factor(_cfg("reduce_defense"), "2026-09-28") == 0.5


def test_reduce_defense_ignores_high_prev_score():
    # 09-27 的前一日=09-26（70 分 offense）→ 不降
    assert TradeSimulator._phase_exposure_factor(_cfg("reduce_defense"), "2026-09-27") == 1.0


def test_reduce_offense_hits_high_prev_score():
    assert TradeSimulator._phase_exposure_factor(_cfg("reduce_offense"), "2026-09-27") == 0.5


def test_no_prev_date_passes_through():
    # 首日无前一日 → 放行（不因缺信号错杀）
    assert TradeSimulator._phase_exposure_factor(_cfg("reduce_defense"), "2026-09-01") == 1.0


def test_custom_threshold_and_factor():
    cfg = _cfg("reduce_offense", factor=0.0, threshold=60.0)
    # 09-26 前一日 09-25=30 分，但阈值 60 → 30<60 防守 → offense 模式不降
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-26") == 1.0
    # 09-27 前一日 09-26=70 ≥60 → offense → factor 0（跳过入场语义由调用方执行）
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-27") == 0.0


def test_missing_score_day_passes_through():
    eod = {"2026-09-25": None}  # 分数缺失（fail-visible 口径：无法定相 → 放行）
    assert TradeSimulator._phase_exposure_factor(_cfg("reduce_defense", eod=eod), "2026-09-26") == 1.0


def test_reduce_band_hits_weak_zone_prev_score():
    """C6 载体：reduce_band 模式——前日分落在 [bandLow, bandHigh) → factor。"""
    cfg = {
        "phaseExposureControl": {
            "mode": "reduce_band", "factor": 0.5, "bandLow": 40.0, "bandHigh": 60.0, "eodScores": EOD,
        }
    }
    # 09-28 前日 09-27=45 ∈ [40,60) → 降仓
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-28") == 0.5
    # 09-26 前日 09-25=30 <40 → 放行
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-26") == 1.0
    # 09-27 前日 09-26=70 ≥60 → 放行
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-27") == 1.0


def test_reduce_band_lower_inclusive_upper_exclusive():
    cfg = {
        "phaseExposureControl": {
            "mode": "reduce_band", "factor": 0.3, "bandLow": 40.0, "bandHigh": 60.0,
            "eodScores": {"2026-09-25": 40.0, "2026-09-26": 60.0},
        }
    }
    # 前日=40.0（含下沿）→ 降仓；前日=60.0（不含上沿）→ 放行
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-26") == 0.3
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-27") == 1.0


def test_ladder_mode_three_tier_user_confirmed():
    """C7 阶梯（用户 2026-10-01 确认 ③）：10-40 满仓 / 40-60 不开仓 / 60+ 三成。

    ladder=[[上界, 因子]...] 升序，取首个 score<上界 的因子；超出全部上界用末条（catch-all）。
    """
    cfg = {
        "phaseExposureControl": {
            "mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
            "eodScores": {"2026-09-25": 30.0, "2026-09-26": 45.0, "2026-09-27": 70.0, "2026-09-28": 85.0},
        }
    }
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-26") == 1.0   # 前日 30 <40 满仓
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-27") == 0.0   # 前日 45 ∈[40,60) 不开仓
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-28") == 0.3   # 前日 70 ≥60 三成
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-29") == 0.3   # 前日 85 ≥80 catch-all 三成


def test_ladder_missing_score_passes_through():
    cfg = {
        "phaseExposureControl": {
            "mode": "ladder", "ladder": [[40, 1.0], [60, 0.0], [999, 0.3]],
            "eodScores": {"2026-09-25": None},
        }
    }
    assert TradeSimulator._phase_exposure_factor(cfg, "2026-09-26") == 1.0
