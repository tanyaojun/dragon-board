from __future__ import annotations

from backend.analysis.theme_trend import (
    ThemeTrendConfig,
    ThemeTrendPythonEngine,
    ThemeTrendResult,
    ThemeFactorFrame,
    ThemeStockExposureFrame,
    ThemeSignalRow,
    ThemeQualityReport,
    build_theme_quality_report,
)


def _frame(
    snapshot_id: str,
    timestamp: int,
    stocks: list[dict],
    sectors: list[dict],
    trading_date: str = "2026-05-05",
    slot_time: str = "10:00",
) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": timestamp,
        "tradingDate": trading_date,
        "slotTime": slot_time,
        "stocks": stocks,
        "sectors": sectors,
    }


# ── ThemeFactorFrame 合同 ──────────────────────────────

class TestThemeFactorFrame:
    def test_defaults_are_set_correctly(self) -> None:
        frame = ThemeFactorFrame()
        assert frame.themeId == ""
        assert frame.themeName == ""
        assert frame.heatScore == 0.0
        assert frame.lifecycle == "neutral"
        assert frame.snapshotType == "half_hour"

    def test_to_dict_roundtrips(self) -> None:
        frame = ThemeFactorFrame(
            datasetId="ds1",
            snapshotId="snap1",
            snapshotType="half_hour",
            tradingDate="2026-05-05",
            slotTime="10:00",
            strategyVersion="0.1.0",
            configHash="abc",
            randomSeed=20260430,
            themeId="ai",
            themeName="人工智能",
            heatScore=88.57,
            momentumScore=80.12,
            breadthScore=77.0,
            fundScore=78.0,
            leadershipScore=84.5,
            correlationScore=72.33,
            crowdingRisk=24.0,
            persistenceScore=78.0,
            rotationState="mainline",
            rank=1,
            lifecycle="mainline",
        )
        d = frame.to_dict()
        assert d["themeId"] == "ai"
        assert d["heatScore"] == 88.57
        assert d["lifecycle"] == "mainline"
        assert d["datasetId"] == "ds1"
        assert d["snapshotType"] == "half_hour"
        assert d["strategyVersion"] == "0.1.0"

    def test_engine_produces_typed_factors(self) -> None:
        frames = [
            _frame("snap1", 100,
                   [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
                   [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
                     "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
                     "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        factor = result.factors[0]
        assert isinstance(factor, ThemeFactorFrame)
        assert factor.themeId == "ai"
        assert factor.themeName == "AI"


# ── ThemeQualityReport 合同 ────────────────────────────

class TestThemeQualityReport:
    def test_blocked_when_frames_empty(self) -> None:
        result = ThemeTrendPythonEngine().replay_typed([])
        qr = result.qualityReport
        assert qr.passed is False
        assert qr.severity == "fail"
        assert "empty_frames" in qr.issues

    def test_degraded_when_low_sample(self) -> None:
        frames = [_frame("snap1", 100, [{"code": "000001"}], [{"entityName": "AI"}])]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        qr = result.qualityReport
        assert "low_sample" in qr.warnings
        assert qr.researchGrade == "degraded"

    def test_passed_for_valid_frames(self) -> None:
        frames = [
            _frame("snap1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
            _frame("snap2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        assert result.qualityReport.passed is True
        assert result.qualityReport.researchGrade == "research_ready"

    def test_warns_on_time_disorder(self) -> None:
        frames = [
            _frame("snap2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
            _frame("snap1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        assert "time_order_invalid" in result.qualityReport.warnings


# ── 构建流程合同 ──────────────────────────────────────

class TestThemeTrendResult:
    def test_empty_frames_returns_quality_blocked(self) -> None:
        result = ThemeTrendPythonEngine().replay_typed([])
        assert result.qualityReport.passed is False
        assert result.factors == []
        assert result.exposures == []
        assert result.signals == []

    def test_typed_result_includes_strategy_versions(self) -> None:
        frames = [
            _frame("snap1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
            _frame("snap2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        assert result.strategyVersion == "theme-trend-v12"
        assert result.factorVersion == "theme-factor-v12"
        assert result.signalVersion == "theme-signal-v12"

    def test_uses_defaults_when_meta_omitted(self) -> None:
        frames = [
            _frame("snap1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
            _frame("snap2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        assert result.qualityReport.snapshotType == "half_hour"

    def test_includes_non_finite_values_in_quality_issues(self) -> None:
        frames = [
            _frame("snap1", 100, [{"code": "000001"}],
                   [{"entityName": "AI", "heatScore": float("nan"), "momentumScore": 84}]),
            _frame("snap2", 200, [{"code": "000001"}],
                   [{"entityName": "AI", "heatScore": float("inf"), "momentumScore": 84}]),
        ]
        result = ThemeTrendPythonEngine().replay_typed(frames)
        assert "illegal_numeric_value" in result.qualityReport.warnings

    def test_half_hour_is_default_snapshot_type(self) -> None:
        result = ThemeTrendPythonEngine().replay_typed([])
        assert result.qualityReport.snapshotType == "half_hour"

    def test_explicit_quarter_hour_config_patch_works(self) -> None:
        config = ThemeTrendConfig.from_patch({"minFrames": 5})
        assert config.minFrames == 5
