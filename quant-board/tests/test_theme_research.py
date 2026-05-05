from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

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
from backend.data.database import ResearchBase
from backend.data.models import (
    ThemeFactorFrameModel,
    ThemeStockExposureModel,
    ThemeSignalModel,
    ThemeQualityReportModel,
)
from backend.data.theme_research_repository import ThemeResearchRepository


def _research_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'research.db'}")
    ResearchBase.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    return engine, Session()


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


# ── 质量报告测试 ─────────────────────────────

def test_empty_frames_are_blocked() -> None:
    report = build_theme_quality_report([])
    assert report["blocked"] is True
    assert "empty_frames" in report["errors"]


def test_replay_empty_frames_returns_failed_grade() -> None:
    result = ThemeTrendPythonEngine().replay_typed([])
    assert result.qualityReport.passed is False
    assert result.qualityReport.severity == "fail"
    assert "empty_frames" in result.qualityReport.issues
    assert result.factors == []
    assert result.exposures == []
    assert result.signals == []


def test_low_sample_produces_warning() -> None:
    frames = [
        _frame("snap_1", 100, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}])
    ]
    report = build_theme_quality_report(frames)
    assert report["blocked"] is False
    assert "low_sample" in report["warnings"]


def test_low_sample_returns_degraded_grade() -> None:
    frames = [
        _frame("snap_1", 100, [{"code": "000001", "mainTheme": "AI"}], [{"entityName": "AI"}])
    ]
    result = ThemeTrendPythonEngine().replay_typed(frames)
    assert result.qualityReport.passed is True
    assert result.qualityReport.researchGrade == "degraded"
    assert "low_sample" in result.qualityReport.warnings


def test_time_disorder_produces_warning() -> None:
    frames = [
        _frame("snap_2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
        _frame("snap_1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
    ]
    report = build_theme_quality_report(frames)
    assert "time_order_invalid" in report["warnings"]


def test_illegal_numeric_values_produce_warning() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [{"code": "000001", "mainTheme": "AI", "themeContribution": float("nan")}],
            [{"entityName": "AI", "heatScore": float("inf")}],
        )
    ]
    report = build_theme_quality_report(frames)
    assert "illegal_numeric_value" in report["warnings"]


def test_missing_stock_data_produces_warning() -> None:
    frames = [
        _frame("snap_1", 100, [], [{"entityName": "AI"}]),
        _frame("snap_2", 200, [], [{"entityName": "AI"}]),
    ]
    report = build_theme_quality_report(frames)
    assert "missing_stock_data" in report["warnings"]


def test_missing_theme_data_produces_warning() -> None:
    frames = [
        _frame("snap_1", 100, [{"code": "000001"}], []),
        _frame("snap_2", 200, [{"code": "000001"}], []),
    ]
    report = build_theme_quality_report(frames)
    assert "missing_theme_data" in report["warnings"]


# ── 引擎输出合同测试 ─────────────────────────

def test_engine_outputs_all_required_fields() -> None:
    frames = [
        _frame(
            "snap_1",
            100,
            [
                {
                    "code": "000001",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 18,
                }
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 82,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        ),
        _frame(
            "snap_2",
            200,
            [
                {
                    "code": "000001",
                    "mainTheme": "人工智能",
                    "themeRole": "leader",
                    "themeContribution": 20,
                }
            ],
            [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 90,
                    "momentumScore": 85,
                    "breadthScore": 78,
                    "fundScore": 80,
                    "leadershipScore": 86,
                    "correlationScore": 74,
                    "crowdingRisk": 22,
                    "persistenceScore": 80,
                    "rotationState": "mainline",
                }
            ],
        ),
    ]

    result = ThemeTrendPythonEngine().replay_typed(frames)
    assert isinstance(result, ThemeTrendResult)
    assert result.strategyVersion == "theme-trend-v12"
    assert result.factorVersion == "theme-factor-v12"
    assert result.signalVersion == "theme-signal-v12"

    assert len(result.factors) > 0
    factor = result.factors[0]
    assert factor.themeId
    assert factor.themeName
    assert isinstance(factor.heatScore, float)
    assert isinstance(factor.momentumScore, float)
    assert isinstance(factor.breadthScore, float)
    assert isinstance(factor.fundScore, float)
    assert isinstance(factor.leadershipScore, float)
    assert isinstance(factor.correlationScore, float)
    assert isinstance(factor.crowdingRisk, float)
    assert isinstance(factor.persistenceScore, float)
    assert factor.rotationState in {
        "ignition", "expansion", "mainline", "crowded",
        "divergence", "cooling", "reversal", "neutral",
    }
    assert factor.lifecycle in {
        "ignition", "expansion", "mainline", "crowded",
        "divergence", "cooling", "reversal", "neutral",
    }

    assert len(result.exposures) > 0
    exposure = result.exposures[0]
    assert exposure.code == "000001"
    assert exposure.themeId
    assert exposure.role
    assert isinstance(exposure.exposureWeight, float)
    assert isinstance(exposure.themeContribution, float)

    assert len(result.signals) > 0
    signal = result.signals[0]
    assert signal.themeId
    assert signal.signal in {"mainline", "expansion", "ignition", "risk", "reduce", "watch"}
    assert signal.lifecycle

    qr = result.qualityReport
    assert isinstance(qr.passed, bool)
    assert qr.severity in {"pass", "warn", "fail"}
    assert qr.researchGrade in {"research_ready", "degraded", "failed"}


# ── 默认值测试 ───────────────────────────────

def test_half_hour_is_default_snapshot_type_in_dataclass() -> None:
    factor = ThemeFactorFrame()
    assert factor.snapshotType == "half_hour"

    exposure = ThemeStockExposureFrame()
    assert exposure.snapshotType == "half_hour"

    signal = ThemeSignalRow()
    assert signal.snapshotType == "half_hour"

    report = ThemeQualityReport()
    assert report.snapshotType == "half_hour"


def test_config_patch_respects_explicit_values() -> None:
    config = ThemeTrendConfig.from_patch(
        {"crowdedRiskThreshold": 75, "mainlineHeatThreshold": 80}
    )
    assert config.crowdedRiskThreshold == 75
    assert config.mainlineHeatThreshold == 80
    assert config.minFrames == 1  # default


# ── repository 测试 ───────────────────────────

def test_save_and_read_factor_frames(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    rows = [
        {
            "datasetId": "ds_test",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "themeId": "ai",
            "themeName": "人工智能",
            "heatScore": 88.0,
            "momentumScore": 82.0,
            "breadthScore": 76.0,
            "fundScore": 78.0,
            "leadershipScore": 84.0,
            "correlationScore": 72.0,
            "crowdingRisk": 24.0,
            "persistenceScore": 78.0,
            "rotationState": "mainline",
            "rank": 1,
            "qualityFlags": [],
            "lifecycle": "mainline",
        }
    ]

    count = repo.save_factor_frames(rows)
    assert count == 1

    results = repo.get_factor_frames("ds_test", "half_hour")
    assert len(results) == 1
    assert results[0]["themeId"] == "ai"
    assert results[0]["themeName"] == "人工智能"
    assert results[0]["lifecycle"] == "mainline"
    assert results[0]["snapshotType"] == "half_hour"
    assert results[0]["configHash"] == "abc123"
    assert results[0]["randomSeed"] == 20260430

    repo.close()
    engine.dispose()


def test_save_and_read_stock_exposures(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    rows = [
        {
            "datasetId": "ds_test",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "code": "000001",
            "themeId": "ai",
            "themeName": "人工智能",
            "role": "leader",
            "roleScore": 100.0,
            "exposureWeight": 85.0,
            "themeContribution": 18.0,
            "riskPenalty": 0.0,
            "reasons": ["role:leader", "theme:mainline"],
        }
    ]

    count = repo.save_stock_exposures(rows)
    assert count == 1

    results = repo.get_stock_exposures("ds_test", snapshot_id="snap_1")
    assert len(results) == 1
    assert results[0]["code"] == "000001"
    assert results[0]["role"] == "leader"
    assert results[0]["reasons"] == ["role:leader", "theme:mainline"]

    repo.close()
    engine.dispose()


def test_save_and_read_signals(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    rows = [
        {
            "datasetId": "ds_test",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "themeId": "ai",
            "themeName": "人工智能",
            "signal": "mainline",
            "risk": "none",
            "lifecycle": "mainline",
            "score": 72.5,
        }
    ]

    count = repo.save_signals(rows)
    assert count == 1

    results = repo.get_signals("ds_test", "half_hour", signal="mainline")
    assert len(results) == 1
    assert results[0]["signal"] == "mainline"
    assert results[0]["score"] == 72.5

    repo.close()
    engine.dispose()


def test_save_and_read_quality_report(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    report = {
        "datasetId": "ds_test",
        "snapshotType": "half_hour",
        "strategyVersion": "theme-trend-v12",
        "configHash": "abc123",
        "randomSeed": 20260430,
        "passed": True,
        "severity": "pass",
        "researchGrade": "research_ready",
        "issues": [],
        "warnings": [],
        "stats": {"totalFrames": 10},
        "themeCoverage": 0.85,
        "frameCount": 10,
        "stockCount": 500,
        "themeCount": 20,
    }

    assert repo.save_quality_report(report) is True

    results = repo.get_quality_reports("ds_test", "half_hour")
    assert len(results) == 1
    assert results[0]["passed"] is True
    assert results[0]["researchGrade"] == "research_ready"
    assert results[0]["frameCount"] == 10

    repo.close()
    engine.dispose()


def test_delete_theme_research_removes_all_tables(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    # 写入测试数据
    repo.save_factor_frames(
        [
            {
                "datasetId": "ds_test",
                "snapshotId": "snap_1",
                "snapshotType": "half_hour",
                "tradingDate": "2026-05-05",
                "slotTime": "10:00",
                "strategyVersion": "theme-trend-v12",
                "configHash": "abc123",
                "randomSeed": 20260430,
                "themeId": "ai",
                "themeName": "AI",
                "heatScore": 80.0,
                "momentumScore": 70.0,
                "breadthScore": 60.0,
                "fundScore": 50.0,
                "leadershipScore": 40.0,
                "correlationScore": 30.0,
                "crowdingRisk": 20.0,
                "persistenceScore": 10.0,
                "rotationState": "neutral",
                "rank": 1,
                "qualityFlags": [],
                "lifecycle": "neutral",
            }
        ]
    )
    repo.save_stock_exposures(
        [
            {
                "datasetId": "ds_test",
                "snapshotId": "snap_1",
                "snapshotType": "half_hour",
                "tradingDate": "2026-05-05",
                "slotTime": "10:00",
                "strategyVersion": "theme-trend-v12",
                "configHash": "abc123",
                "randomSeed": 20260430,
                "code": "000001",
                "themeId": "ai",
                "themeName": "AI",
                "role": "leader",
                "roleScore": 100.0,
                "exposureWeight": 80.0,
                "themeContribution": 15.0,
                "riskPenalty": 0.0,
                "reasons": [],
            }
        ]
    )
    repo.save_signals(
        [
            {
                "datasetId": "ds_test",
                "snapshotId": "snap_1",
                "snapshotType": "half_hour",
                "tradingDate": "2026-05-05",
                "slotTime": "10:00",
                "strategyVersion": "theme-trend-v12",
                "configHash": "abc123",
                "randomSeed": 20260430,
                "themeId": "ai",
                "themeName": "AI",
                "signal": "watch",
                "risk": "none",
                "lifecycle": "neutral",
                "score": 50.0,
            }
        ]
    )
    repo.save_quality_report(
        {
            "datasetId": "ds_test",
            "snapshotType": "half_hour",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "passed": True,
            "severity": "pass",
            "researchGrade": "research_ready",
            "issues": [],
            "warnings": [],
            "stats": {},
            "themeCoverage": 0.0,
            "frameCount": 1,
            "stockCount": 1,
            "themeCount": 1,
        }
    )

    assert len(repo.get_factor_frames("ds_test")) == 1
    assert len(repo.get_stock_exposures("ds_test")) == 1
    assert len(repo.get_signals("ds_test")) == 1
    assert len(repo.get_quality_reports("ds_test")) == 1

    deleted = repo.delete_theme_research("ds_test", "half_hour")
    assert deleted["theme_factor_frames"] == 1
    assert deleted["theme_stock_exposures"] == 1
    assert deleted["theme_signals"] == 1
    assert deleted["theme_quality_reports"] == 1

    assert repo.get_factor_frames("ds_test") == []
    assert repo.get_stock_exposures("ds_test") == []
    assert repo.get_signals("ds_test") == []
    assert repo.get_quality_reports("ds_test") == []

    repo.close()
    engine.dispose()


def test_repository_filter_by_code(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    rows = [
        {
            "datasetId": "ds_test",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "code": "000001",
            "themeId": "ai",
            "themeName": "AI",
            "role": "leader",
            "roleScore": 100.0,
            "exposureWeight": 80.0,
            "themeContribution": 15.0,
            "riskPenalty": 0.0,
            "reasons": [],
        },
        {
            "datasetId": "ds_test",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "code": "000002",
            "themeId": "robot",
            "themeName": "机器人",
            "role": "core",
            "roleScore": 78.0,
            "exposureWeight": 60.0,
            "themeContribution": 10.0,
            "riskPenalty": 0.0,
            "reasons": [],
        },
    ]

    repo.save_stock_exposures(rows)

    all_results = repo.get_stock_exposures("ds_test")
    assert len(all_results) == 2

    filtered = repo.get_stock_exposures("ds_test", code="000001")
    assert len(filtered) == 1
    assert filtered[0]["code"] == "000001"

    repo.close()
    engine.dispose()


def test_config_hash_changes_with_parameters() -> None:
    from backend.utils import stable_hash

    hash1 = stable_hash({"crowdingRiskThreshold": 80})
    hash2 = stable_hash({"crowdingRiskThreshold": 75})
    assert hash1 != hash2


def test_quality_report_metadata_fields_preserved(tmp_path: Path) -> None:
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    report = {
        "datasetId": "ds_v12",
        "snapshotType": "half_hour",
        "strategyVersion": "theme-trend-v12",
        "configHash": "def456",
        "randomSeed": 20260430,
        "passed": True,
        "severity": "pass",
        "researchGrade": "research_ready",
        "issues": [],
        "warnings": ["low_sample"],
        "stats": {"totalFrames": 3},
        "themeCoverage": 0.72,
        "frameCount": 3,
        "stockCount": 150,
        "themeCount": 12,
    }

    repo.save_quality_report(report)
    results = repo.get_quality_reports("ds_v12")
    assert len(results) == 1
    assert results[0]["datasetId"] == "ds_v12"
    assert results[0]["snapshotType"] == "half_hour"
    assert results[0]["strategyVersion"] == "theme-trend-v12"
    assert results[0]["configHash"] == "def456"
    assert results[0]["randomSeed"] == 20260430

    repo.close()
    engine.dispose()


def test_large_json_field_roundtrips_through_compression(tmp_path: Path) -> None:
    """验证 qualityFlags JSON 字段在压缩/解压路径下的 round-trip。

    json_codec 默认压缩阈值为 4096 字节，超过该长度会触发 gzip + base64 编码。
    """
    engine, session = _research_session(tmp_path)
    repo = ThemeResearchRepository()
    repo._session = session

    # 构造足够大的 qualityFlags 以触发压缩（>4KB）
    large_flags = [f"flag_{i:04d}_" + "x" * 60 for i in range(100)]
    rows = [
        {
            "datasetId": "ds_compress",
            "snapshotId": "snap_1",
            "snapshotType": "half_hour",
            "tradingDate": "2026-05-05",
            "slotTime": "10:00",
            "strategyVersion": "theme-trend-v12",
            "configHash": "abc123",
            "randomSeed": 20260430,
            "themeId": "ai",
            "themeName": "测试",
            "heatScore": 80.0,
            "momentumScore": 70.0,
            "breadthScore": 60.0,
            "fundScore": 50.0,
            "leadershipScore": 40.0,
            "correlationScore": 30.0,
            "crowdingRisk": 20.0,
            "persistenceScore": 10.0,
            "rotationState": "neutral",
            "rank": 1,
            "qualityFlags": large_flags,
            "lifecycle": "neutral",
        }
    ]

    count = repo.save_factor_frames(rows)
    assert count == 1

    results = repo.get_factor_frames("ds_compress")
    assert len(results) == 1
    assert results[0]["qualityFlags"] == large_flags

    repo.close()
    engine.dispose()


def test_unmatched_theme_stock_produces_warning() -> None:
    """当 stock 的 themeName 无法匹配任何 sector 时，产出警告。"""
    from backend.analysis.theme_trend import ThemeTrendPythonEngine

    frames = [
        {
            "snapshotId": "snap_1",
            "timestamp": 100,
            "tradingDate": "2026-05-05",
            "stocks": [
                {"code": "000001", "mainTheme": "不存在题材", "themeRole": "leader", "themeContribution": 18}
            ],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 82,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        },
        {
            "snapshotId": "snap_2",
            "timestamp": 200,
            "tradingDate": "2026-05-05",
            "stocks": [
                {"code": "000001", "mainTheme": "不存在题材", "themeRole": "leader", "themeContribution": 18}
            ],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 82,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        },
    ]

    result = ThemeTrendPythonEngine().replay(frames)
    assert "unmatched_theme_stock" in result["qualityReport"]["warnings"]
    assert result["exposures"] == []  # 无匹配时不生成 exposure


def test_unmatched_theme_stock_not_added_for_empty_theme_name() -> None:
    """股票没有主题名时不报告 unmatched_theme_stock（属于正常情况）。"""
    from backend.analysis.theme_trend import ThemeTrendPythonEngine

    frames = [
        {
            "snapshotId": "snap_1",
            "timestamp": 100,
            "tradingDate": "2026-05-05",
            "stocks": [
                {"code": "000001", "name": "无主题股票"}
            ],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 82,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        },
        {
            "snapshotId": "snap_2",
            "timestamp": 200,
            "tradingDate": "2026-05-05",
            "stocks": [
                {"code": "000001", "name": "无主题股票"}
            ],
            "sectors": [
                {
                    "entityKey": "ai",
                    "entityName": "人工智能",
                    "heatScore": 88,
                    "momentumScore": 82,
                    "breadthScore": 76,
                    "fundScore": 78,
                    "leadershipScore": 84,
                    "correlationScore": 72,
                    "crowdingRisk": 24,
                    "persistenceScore": 78,
                    "rotationState": "mainline",
                }
            ],
        },
    ]

    result = ThemeTrendPythonEngine().replay(frames)
    assert "unmatched_theme_stock" not in result["qualityReport"]["warnings"]


# ── Phase 2: 多帧序列回放 ─────────────────────────

def test_replay_sequence_tracks_consecutive_frames() -> None:
    """验证 replay_sequence 跨帧追踪主题的 continuousFrames 计数。"""
    frames = [
        _frame("snap_1", 100,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
                 "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
                 "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}]),
        _frame("snap_2", 200,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 92, "momentumScore": 86,
                 "breadthScore": 80, "fundScore": 82, "leadershipScore": 90, "correlationScore": 76,
                 "crowdingRisk": 18, "persistenceScore": 82, "rotationState": "mainline", "rank": 1}]),
        _frame("snap_3", 300,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 94, "momentumScore": 88,
                 "breadthScore": 82, "fundScore": 84, "leadershipScore": 92, "correlationScore": 78,
                 "crowdingRisk": 16, "persistenceScore": 84, "rotationState": "mainline", "rank": 1}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    factors = result["factors"]
    assert len(factors) == 3  # 每帧一个 factor

    assert factors[0]["consecutiveFrames"] == 1
    assert factors[0]["prevLifecycle"] == ""
    assert factors[0]["lifecycleTransition"] == ""
    assert factors[0]["snapshotId"] == "snap_1"

    assert factors[1]["consecutiveFrames"] == 2
    assert factors[1]["prevLifecycle"] == "mainline"
    assert factors[1]["lifecycleTransition"] == ""  # same lifecycle, no transition

    assert factors[2]["consecutiveFrames"] == 3
    assert factors[2]["prevLifecycle"] == "mainline"
    assert factors[2]["snapshotId"] == "snap_3"


def test_replay_sequence_detects_lifecycle_transition() -> None:
    """验证 replay_sequence 检测题材生命周期迁移。"""
    frames = [
        _frame("snap_1", 100,
               [{"code": "000001"}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 60, "momentumScore": 55,
                 "breadthScore": 50, "fundScore": 60, "leadershipScore": 50, "correlationScore": 50,
                 "crowdingRisk": 30, "persistenceScore": 50, "rotationState": "ignition", "rank": 1}]),
        _frame("snap_2", 200,
               [{"code": "000001"}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 82, "momentumScore": 80,
                 "breadthScore": 75, "fundScore": 78, "leadershipScore": 84, "correlationScore": 72,
                 "crowdingRisk": 24, "persistenceScore": 78, "rotationState": "mainline", "rank": 1}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    factors = result["factors"]

    assert factors[0]["lifecycle"] == "ignition"
    assert factors[1]["lifecycle"] == "mainline"
    assert factors[1]["prevLifecycle"] == "ignition"
    assert factors[1]["lifecycleTransition"] == "ignition>mainline"


def test_replay_sequence_persistence_increases_over_frames() -> None:
    """验证 persistenceScore 随连续帧数增长。"""
    frames = [
        _frame(
            "snap_1", 100,
            [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
            [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
              "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
              "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}],
        )
        for snap_idx in range(1, 6)
    ]
    # 每帧时间戳递增
    for idx, frame in enumerate(frames):
        frame["timestamp"] = (idx + 1) * 100
        frame["snapshotId"] = f"snap_{idx + 1}"

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    factors = result["factors"]
    assert len(factors) == 5

    # persistenceScore 应随 consecutiveFrames 单调递增
    scores = [factor["persistenceScore"] for factor in factors]
    for i in range(1, len(scores)):
        assert scores[i] >= scores[i - 1], f"persistenceScore 应在帧间递增: {scores}"


def test_replay_sequence_exposures_have_frame_metadata() -> None:
    """验证 replay_sequence 返回的 exposures 携带来源帧 metadata。"""
    frames = [
        _frame("snap_1", 100,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
                 "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
                 "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    exposures = result["exposures"]
    assert len(exposures) == 1
    assert exposures[0]["snapshotId"] == "snap_1"
    assert exposures[0]["code"] == "000001"


def test_replay_sequence_signals_have_frame_metadata() -> None:
    """验证 replay_sequence 返回的 signals 携带来源帧 metadata。"""
    frames = [
        _frame("snap_1", 100,
               [{"code": "000001"}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
                 "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
                 "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    signals = result["signals"]
    assert len(signals) == 1
    assert signals[0]["snapshotId"] == "snap_1"
    assert signals[0]["signal"] == "mainline"


def test_replay_sequence_quality_report_warns_time_disorder() -> None:
    """验证 replay_sequence 检测时间乱序。"""
    frames = [
        _frame("snap_2", 200, [{"code": "000001"}], [{"entityName": "AI"}]),
        _frame("snap_1", 100, [{"code": "000001"}], [{"entityName": "AI"}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence(frames)
    assert "time_order_invalid" in result["qualityReport"]["warnings"]


def test_replay_sequence_typed_roundtrips() -> None:
    """验证 replay_sequence_typed 返回完整的 ThemeTrendResult。"""
    frames = [
        _frame("snap_1", 100,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 90, "momentumScore": 84,
                 "breadthScore": 78, "fundScore": 80, "leadershipScore": 88, "correlationScore": 74,
                 "crowdingRisk": 20, "persistenceScore": 80, "rotationState": "mainline", "rank": 1}]),
        _frame("snap_2", 200,
               [{"code": "000001", "mainTheme": "AI", "themeRole": "leader", "themeContribution": 15}],
               [{"entityKey": "ai", "entityName": "AI", "heatScore": 92, "momentumScore": 86,
                 "breadthScore": 80, "fundScore": 82, "leadershipScore": 90, "correlationScore": 76,
                 "crowdingRisk": 18, "persistenceScore": 82, "rotationState": "mainline", "rank": 1}]),
    ]

    result = ThemeTrendPythonEngine().replay_sequence_typed(frames)
    from backend.analysis.theme_trend import ThemeTrendResult

    assert isinstance(result, ThemeTrendResult)
    assert result.strategyVersion == "theme-trend-v12"
    assert len(result.factors) == 2
    assert result.factors[1].consecutiveFrames == 2
    assert result.factors[1].prevLifecycle == "mainline"
