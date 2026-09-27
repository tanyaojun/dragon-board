from __future__ import annotations

import json
from pathlib import Path

from backend.analysis.theme.trend import (
    ThemeTrendConfig,
    ThemeTrendPythonEngine,
    build_theme_quality_report,
)


def _frame(snapshot_id: str, timestamp: int, stocks: list[dict], sectors: list[dict]) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": timestamp,
        "tradingDate": "2026-05-05",
        "stocks": stocks,
        "sectors": sectors,
    }


def test_theme_trend_python_matches_ts_runtime_golden_case() -> None:
    # v15：persistenceScore 重建后 bump（previousFactors 对齐生产 metadata 供给形态，
    # AI 连续热门桶 2+1=3 → 60；exposure themeContribution 连锁）；v14 及以前不可变。
    # 热度口径 theme-market-v2（KPL 人气总和）；POWER 无 KPL → heatScore=None（诚实缺失）。
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "theme_trend_ts_golden_v15.json").read_text(encoding="utf-8")
    )

    result = ThemeTrendPythonEngine().replay(fixture["input"]["frames"], config=ThemeTrendConfig())

    factor_fields = [
        "themeId",
        "themeName",
        "heatScore",
        "heatLevel",
        "momentumScore",
        "breadthScore",
        "fundScore",
        "leadershipScore",
        "correlationScore",
        "crowdingRisk",
        "persistenceScore",
        "rotationState",
        "rank",
        "qualityFlags",
    ]
    actual_factors = [{field: item.get(field) for field in factor_fields} for item in result["factors"]]
    assert actual_factors == fixture["expected"]["factors"]

    exposure_fields = [
        "code",
        "themeId",
        "themeName",
        "role",
        "roleScore",
        "exposureWeight",
        "themeContribution",
        "riskPenalty",
        "reasons",
    ]
    actual_exposures = [{field: item.get(field) for field in exposure_fields} for item in result["exposures"]]
    assert actual_exposures == fixture["expected"]["exposures"]


def test_theme_trend_ts_runtime_golden_case_supports_typed_replay_and_quality_gate() -> None:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "theme_trend_ts_golden_v15.json").read_text(encoding="utf-8")
    )

    typed = ThemeTrendPythonEngine().replay_typed(fixture["input"]["frames"], config=ThemeTrendConfig())

    assert typed.factors[0].themeId == "AI"
    assert "missing_theme_data" not in typed.qualityReport.warnings
    assert typed.qualityReport.themeCount == 2


def test_replay_outputs_mainline_theme_factor_for_single_frame() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [
                {
                    "code": "000001",
                    "name": "龙头科技",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                    "themeHeat": 92,
                    "rank": 1,
                },
                {
                    "code": "000002",
                    "name": "核心科技",
                    "mainTheme": "人工智能",
                    "themeRole": "core",
                    "themeContribution": 12,
                    "themeHeat": 76,
                    "rank": 5,
                },
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "rank": 1,
                    "heatScore": 90,
                    "momentumScore": 84,
                    "breadthScore": 78,
                    "fundScore": 82,
                    "leadershipScore": 88,
                    "correlationScore": 74,
                    "crowdingRisk": 32,
                    "persistenceScore": 80,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    result = ThemeTrendPythonEngine().replay(frames, config=ThemeTrendConfig())

    assert result["strategyVersion"] == "theme-trend-v12"
    assert result["factorVersion"] == "theme-factor-v12"
    assert result["signalVersion"] == "theme-signal-v12"
    assert result["qualityReport"]["blocked"] is False

    factor = result["factors"][0]
    assert factor["themeId"] == "ai"
    assert factor["themeName"] == "人工智能"
    assert factor["rotationState"] == "mainline"
    # D5：状态机废弃，无落库 lifecycle 时 neutral 兜底
    assert factor["lifecycle"] == "neutral"
    assert factor["rank"] == 1
    assert factor["qualityFlags"] == []
    assert factor["heatScore"] >= 85
    assert factor["momentumScore"] >= 80
    assert factor["breadthScore"] >= 70
    assert factor["fundScore"] >= 80
    assert factor["leadershipScore"] >= 80
    assert factor["correlationScore"] >= 70
    assert factor["crowdingRisk"] < 50
    assert factor["persistenceScore"] >= 75
    assert result["signals"][0]["themeId"] == "ai"
    assert result["signals"][0]["signal"] == "mainline"


def test_crowded_theme_sets_crowded_lifecycle_and_risk_signal() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [{"code": "000001", "mainTheme": "机器人", "themeRole": "leader", "themeContribution": 20}],
            [
                {
                    "entityKey": "robot",
                    "entityName": "机器人",
                    "rank": 1,
                    "heatScore": 94,
                    "momentumScore": 86,
                    "breadthScore": 82,
                    "fundScore": 80,
                    "leadershipScore": 90,
                    "correlationScore": 78,
                    "crowdingRisk": 86,
                    "persistenceScore": 86,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    result = ThemeTrendPythonEngine().replay(frames)

    assert result["factors"][0]["lifecycle"] == "neutral"  # D5：不再从拥挤度推导 crowded
    assert "crowding_risk_high" in result["factors"][0]["qualityFlags"]
    assert result["signals"][0]["signal"] == "risk"
    assert result["signals"][0]["risk"] == "crowded"


def test_quality_report_warns_when_frames_are_out_of_order() -> None:
    frames = [
        _frame("snap_2", 200, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}]),
        _frame("snap_1", 100, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}]),
    ]

    report = build_theme_quality_report(frames)

    assert report["blocked"] is False
    assert "time_order_invalid" in report["warnings"]


def test_empty_frames_are_blocked_and_replay_returns_empty_outputs() -> None:
    result = ThemeTrendPythonEngine().replay([])

    assert result["qualityReport"]["blocked"] is True
    assert "empty_frames" in result["qualityReport"]["errors"]
    assert result["factors"] == []
    assert result["exposures"] == []
    assert result["signals"] == []


def test_replay_builds_leader_and_core_stock_exposures() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [
                {
                    "code": "000001",
                    "name": "龙头科技",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                    "themeHeat": 90,
                },
                {
                    "code": "000002",
                    "name": "核心科技",
                    "themes": [{"name": "人工智能", "role": "core", "themeContribution": 12}],
                    "themeHeat": 72,
                },
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 80,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        )
    ]

    exposures = ThemeTrendPythonEngine().replay(frames)["exposures"]

    leader = next(item for item in exposures if item["code"] == "000001")
    core = next(item for item in exposures if item["code"] == "000002")
    assert leader["themeId"] == "ai"
    assert leader["themeName"] == "人工智能"
    assert leader["role"] == "leader"
    assert leader["roleScore"] > core["roleScore"]
    assert leader["exposureWeight"] > core["exposureWeight"]
    assert leader["themeContribution"] == 18
    assert leader["riskPenalty"] == 0
    assert "role:leader" in leader["reasons"]
    assert core["role"] == "core"
    assert "role:core" in core["reasons"]


def test_ts_factors_prefer_persisted_rotation_state() -> None:
    from backend.analysis.theme.trend import _theme_context_frames

    frame = {
        "timestamp": 1785807000000,
        "themeContext": {
            "themes": [{"id": "BKAI", "themeId": "BKAI", "themeName": "人工智能"}],
            "themeStocks": {"BKAI": ["600001"]},
            "stockThemes": {"600001": ["BKAI"]},
            "rotationAnalysis": {"mainLines": []},
        },
        "stocks": [{"code": "600001", "change": 5.0, "themeIds": ["BKAI"]}],
        "sectors": [{
            "themeId": "BKAI", "entityKey": "BKAI", "themeName": "人工智能",
            "rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0,
        }],
    }
    factors, _ = _theme_context_frames(frame)
    assert factors
    factor = next(f for f in factors if f.get("themeId") == "BKAI")
    assert factor["rotationState"] == "mainline"
    assert factor["lifecycle"] == "expanding"
    assert "rotationState_local_fallback" not in (factor.get("themeQualityFlags") or [])


# ── persistenceScoreWeight 日级原料接线（Phase 4 P4-3 前置，2026-09-27）──────
# 设计裁决（2026-09-27 用户确认走 Path B）：合成项吃 **注入的日级
# heatLevelStreak**（theme_daily_factors.factors 键），不再吃 in-frame
# persistenceScore——后者经实测全研究窗 15:00 收盘帧 99.3% 恒 92.0
# （公式 d=5 饱和 + half_hour 同日题材集只增不减），横截面零方差不可作因子。
# fail-visible 三态：weight>0 时 未注入→persistence_daily_source_not_provided、
# 键未中→persistence_daily_key_missing、值 None→persistence_daily_value_insufficient。
_PERSISTENCE_SECTOR = {
    "entityKey": "robot",
    "entityName": "机器人",
    "rank": 1,
    "heatScore": 94,
    "momentumScore": 86,
    "breadthScore": 82,
    "fundScore": 80,
    "leadershipScore": 90,
    "correlationScore": 78,
    "crowdingRisk": 86,
    "persistenceScore": 86,
    "rotationState": "mainline",
}


def _persistence_frame(snapshot_id: str, timestamp: int, trading_date: str = "2026-09-14") -> dict:
    return _frame(
        snapshot_id,
        timestamp,
        [{"code": "000001", "mainTheme": "机器人", "themeRole": "leader", "themeContribution": 20}],
        [dict(_PERSISTENCE_SECTOR)],
    ) | {"tradingDate": trading_date}


def _daily(date: str, key: str, streak: float | None) -> dict:
    return {date: {key: {"heatLevelStreak": streak}}}


def test_theme_trend_config_persistence_score_weight_defaults_to_zero() -> None:
    assert ThemeTrendConfig().persistenceScoreWeight == 0.0
    assert ThemeTrendConfig.from_patch(None).persistenceScoreWeight == 0.0
    assert ThemeTrendConfig.from_patch({}).persistenceScoreWeight == 0.0
    assert ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.05}).persistenceScoreWeight == 0.05


def test_persistence_score_weight_zero_keeps_signal_scores_unchanged() -> None:
    """默认关 = 与显式 0.0 逐字段一致，且注入在场也不打标（零行为变化）。"""
    frames = [_persistence_frame("snap_1", 100)]
    injected = _daily("2026-09-14", "机器人", 3)
    default_signals = ThemeTrendPythonEngine().replay_sequence(frames)["signals"]
    explicit_zero = ThemeTrendPythonEngine().replay_sequence(
        frames, config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.0}), daily_factors=injected
    )["signals"]

    assert default_signals == explicit_zero
    assert all("qualityFlags" not in sig for sig in explicit_zero)


def test_persistence_score_weight_consumes_injected_daily_streak_additively() -> None:
    """附加项语义：score = 基础六维 + 日级 heatLevelStreak × weight（不重新归一）。"""
    frames = [_persistence_frame("snap_1", 100)]
    engine = ThemeTrendPythonEngine()
    base = engine.replay_sequence(frames)
    weighted = engine.replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5}),
        daily_factors=_daily("2026-09-14", "机器人", 4),
    )

    base_score = base["signals"][0]["score"]
    assert base_score == 74.4  # 94*.25 + 86*.25 + 82*.15 + 80*.15 + 90*.2 - 86*.15
    sig = weighted["signals"][0]
    assert sig["score"] == round(base_score + 4 * 0.5, 2)
    assert "qualityFlags" not in sig  # 注入命中 → 无标记
    assert {k: v for k, v in sig.items() if k != "score"} == {
        k: v for k, v in base["signals"][0].items() if k != "score"
    }


def test_persistence_score_weight_matches_daily_rows_by_theme_name_and_id() -> None:
    """双键匹配确定序：themeName 优先（唯一实测有效对齐键），themeId 冗余补位。

    两键同中不同值时必须取 themeName（code review I-1/I-2：set 迭代序随
    PYTHONHASHSEED 摆动不可复现；且旧用例浅合并丢键、双键路径从未真正执行）。
    """
    frames = [_persistence_frame("snap_1", 100)]
    engine = ThemeTrendPythonEngine()
    by_name = engine.replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 1.0}),
        daily_factors=_daily("2026-09-14", "机器人", 3),
    )["signals"][0]
    # 手工构造嵌套 dict：同日双键并存且值不同（robot=5 / 机器人=3）
    both_keys = {"2026-09-14": {"robot": {"heatLevelStreak": 5}, "机器人": {"heatLevelStreak": 3}}}
    by_both = engine.replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 1.0}),
        daily_factors=both_keys,
    )["signals"][0]

    assert by_name["score"] == round(74.4 + 3 * 1.0, 2)
    assert by_both["score"] == round(74.4 + 3 * 1.0, 2)  # themeName 优先，确定序


def test_persistence_score_weight_flags_when_daily_source_not_provided() -> None:
    """weight>0 但调用方未注入 → 显式标记，不静默按 0 分处理。"""
    frames = [_persistence_frame("snap_1", 100)]
    result = ThemeTrendPythonEngine().replay_sequence(
        frames, config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5})
    )

    sig = result["signals"][0]
    assert sig["score"] == 74.4  # 附加项 = 0，但必须可见
    assert sig["qualityFlags"] == ["persistence_daily_source_not_provided"]


def test_persistence_score_weight_flags_when_daily_key_missing() -> None:
    """注入了但该主题/日期无行 → persistence_daily_key_missing。"""
    frames = [_persistence_frame("snap_1", 100)]
    result = ThemeTrendPythonEngine().replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5}),
        daily_factors=_daily("2026-09-15", "机器人", 3),  # 日期错
    )

    sig = result["signals"][0]
    assert sig["score"] == 74.4
    assert sig["qualityFlags"] == ["persistence_daily_key_missing"]


def test_persistence_score_weight_flags_when_daily_value_insufficient() -> None:
    """行在但 heatLevelStreak=None（日频管线判不可观测）→ insufficient，不伪造 0。"""
    frames = [_persistence_frame("snap_1", 100)]
    result = ThemeTrendPythonEngine().replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5}),
        daily_factors=_daily("2026-09-14", "机器人", None),
    )

    sig = result["signals"][0]
    assert sig["score"] == 74.4
    assert sig["qualityFlags"] == ["persistence_daily_value_insufficient"]


def test_persistence_score_weight_rejects_invalid_values() -> None:
    """fail-visible：负值/非有限/非数值权重回落 0.0（关闭），不伪造负向因子。"""
    for bad in (-1.0, -0.01, float("nan"), float("inf"), "abc", None, [0.05]):
        config = ThemeTrendConfig.from_patch({"persistenceScoreWeight": bad})
        assert config.persistenceScoreWeight == 0.0, bad


def test_replay_sequence_daily_streak_is_as_of_by_trading_date() -> None:
    """多帧逐日：每个交易日只消费该日的 streak 值（as-of 语义，不串日）。"""
    frames = [
        _persistence_frame("snap_1", 100, trading_date="2026-09-14"),
        _persistence_frame("snap_2", 200, trading_date="2026-09-15"),
    ]
    daily = {**_daily("2026-09-14", "机器人", 2), **_daily("2026-09-15", "机器人", 6)}
    result = ThemeTrendPythonEngine().replay_sequence(
        frames, config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 1.0}), daily_factors=daily
    )

    scores = [sig["score"] for sig in result["signals"]]
    assert scores == [round(74.4 + 2, 2), round(74.4 + 6, 2)]
    assert all("qualityFlags" not in sig for sig in result["signals"])


def test_typed_result_preserves_persistence_daily_flags() -> None:
    """typed 路径不得静默丢标：ThemeSignalRow.qualityFlags 必须透传
    （theme_research_service 等消费方走 typed 结果，丢标 = fail-visible 失效）。"""
    frames = [_persistence_frame("snap_1", 100)]
    result = ThemeTrendPythonEngine().replay_sequence_typed(
        frames, config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5})
    )

    assert result.signals, "需要非空信号"
    assert all(
        sig.qualityFlags == ["persistence_daily_source_not_provided"]
        for sig in result.signals
    )
    # 注入命中 → 空列表（字段恒在，dict 形态稳定）
    injected = ThemeTrendPythonEngine().replay_sequence_typed(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 0.5}),
        daily_factors=_daily("2026-09-14", "机器人", 2),
    )
    assert all(sig.qualityFlags == [] for sig in injected.signals)


# ── 75 硬层参数化（2026-09-27 D2① 裁决：Phase 2 实测量纲差一个数量级、
# 硬编码 75 在本窗零触发；扫描候选 {35,45,55} 需可设置。默认 75.0 = 逐位不变）
def _hard_layer_sector(crowding: float) -> dict:
    sector = dict(_PERSISTENCE_SECTOR)
    sector["crowdingRisk"] = crowding
    return sector


def _hard_layer_frame(crowding: float) -> dict:
    return _frame(
        "snap_1",
        100,
        [{"code": "000001", "mainTheme": "机器人", "themeRole": "leader", "themeContribution": 20}],
        [_hard_layer_sector(crowding)],
    )


def test_crowded_hard_layer_threshold_defaults_to_legacy_75() -> None:
    assert ThemeTrendConfig().crowdedHardLayerThreshold == 75.0
    frames = [_hard_layer_frame(86)]
    default_signals = ThemeTrendPythonEngine().replay(frames)["signals"]
    explicit_default = ThemeTrendPythonEngine().replay(
        frames, config=ThemeTrendConfig.from_patch({"crowdedHardLayerThreshold": 75.0})
    )["signals"]

    assert default_signals == explicit_default  # 显式默认 = 逐位不变
    assert default_signals[0]["signal"] == "risk"  # 86 ≥ 75 → risk（原行为保持）


def test_crowded_hard_layer_threshold_lowers_risk_trigger() -> None:
    """crowding=40：默认 75 不触发硬层；threshold=35 触发（S3 扫描语义）。"""
    frames = [_hard_layer_frame(40)]
    engine = ThemeTrendPythonEngine()
    default_signal = engine.replay(frames)["signals"][0]
    lowered = engine.replay(
        frames, config=ThemeTrendConfig.from_patch({"crowdedHardLayerThreshold": 35.0})
    )["signals"][0]

    assert default_signal["signal"] != "risk"
    assert default_signal["risk"] == "none"
    assert lowered["signal"] == "risk"
    assert lowered["risk"] == "crowded"


def test_daily_factors_injection_key_stripped_from_persisted_factors() -> None:
    """code review M-2：dailyFactors 仅服务 _build_signal，不得随 factors
    泄漏进持久化产物（result_json / themeTrend.factors）。"""
    frames = [_persistence_frame("snap_1", 100)]
    result = ThemeTrendPythonEngine().replay_sequence(
        frames,
        config=ThemeTrendConfig.from_patch({"persistenceScoreWeight": 1.0}),
        daily_factors=_daily("2026-09-14", "机器人", 3),
    )

    assert result["signals"][0]["score"] == round(74.4 + 3 * 1.0, 2)  # 注入仍生效
    assert all("dailyFactors" not in factor for factor in result["factors"])
