"""CLI subcommand tests: run-ranktrend, run-longtest-baselines,
export-report, migrate-snapshots, verify-themes.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.cli import (
    build_longtest_baseline_payloads,
    build_parser,
    build_ranktrend_payload,
    cmd_migrate_snapshots,
    cmd_verify_themes,
    summarize_longtest_baseline,
)
from backend.core.backtest.strategy import normalize_strategy_name


def test_cli_run_ranktrend_exposes_ui_backtest_parameters() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-ranktrend",
            "--dataset-id",
            "ds_cli",
            "--snapshot-type",
            "half_hour",
            "--start-date",
            "2026-04-15",
            "--end-date",
            "2026-04-30",
            "--strategy-name",
            "a_main_only",
            "--seed",
            "42",
            "--initial-cash",
            "123456",
            "--max-positions",
            "3",
            "--position-size",
            "0.15",
            "--target-holding-days",
            "4.5",
            "--max-holding-bars",
            "32",
            "--take-profit-pct",
            "0.09",
            "--stop-loss-pct",
            "0.04",
            "--fee-rate",
            "0.0002",
            "--stamp-tax-rate",
            "0.0006",
            "--slippage-rate",
            "0.0008",
            "--macd-fast",
            "12",
            "--macd-slow",
            "26",
            "--macd-signal",
            "9",
            "--momentum-periods",
            "2,4,8,16",
            "--horizons",
            "1,2,5",
            "--execution-mode",
            "next_bar",
            "--volume-participation-rate",
            "0.02",
            "--order-book-participation-rate",
            "0.25",
            "--intrabar-ambiguity",
            "take_first",
            "--use-theme-factor-for-execution",
            "--exclude-non-positive-price-rows",
            "--exclude-cross-market-zero-price-rows",
            "--exclude-all-zero-price-frames",
            "--no-t1",
            "--no-partial-fills",
        ]
    )

    payload = build_ranktrend_payload(args)

    assert payload["dataset_id"] == "ds_cli"
    assert payload["snapshot_type"] == "half_hour"
    assert payload["start_date"] == "2026-04-15"
    assert payload["end_date"] == "2026-04-30"
    assert payload["strategy_name"] == "a_main_only"
    assert payload["random_seed"] == 42
    assert payload["initialCash"] == 123456
    assert payload["maxPositions"] == 3
    assert payload["targetHoldingDays"] == 4.5
    assert payload["maxHoldingBars"] == 32
    assert payload["takeProfitPct"] == 0.09
    assert payload["stopLossPct"] == 0.04
    assert payload["macdFast"] == 12
    assert payload["macdSlow"] == 26
    assert payload["macdSignal"] == 9
    assert payload["momentumPeriods"] == [2, 4, 8, 16]
    assert payload["horizons"] == [1, 2, 5]
    assert payload["enable_trade_simulation"] is True
    assert payload["tradeConfig"] == {
        "positionSize": 0.15,
        "feeRate": 0.0002,
        "stampTaxRate": 0.0006,
        "slippageRate": 0.0008,
        "enforceT1": False,
        "executionMode": "next_bar",
        "useOrderBookPrice": True,
        "enforceLimitStatus": True,
        "enforceVolumeLimit": True,
        "enforceOrderBookQueue": True,
        "allowPartialFills": False,
        "volumeParticipationRate": 0.02,
        "orderBookParticipationRate": 0.25,
        "useIntrabarStops": True,
        "intrabarAmbiguity": "take_first",
        "useThemeFactorForExecution": True,
    }
    assert payload["excludeNonPositivePriceRows"] is True
    assert payload["excludeCrossMarketZeroPriceRows"] is True
    assert payload["excludeAllZeroPriceFrames"] is True


def test_cli_ranktrend_payload_omits_optional_trade_defaults_when_not_explicit() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-ranktrend",
            "--dataset-id",
            "ds_cli",
            "--strategy-name",
            "ranktrend_early_big_move_v3_lifecycle_fusion",
        ]
    )

    payload = build_ranktrend_payload(args)

    assert "maxHoldingBars" not in payload
    assert "takeProfitPct" not in payload
    assert "stopLossPct" not in payload
    assert "volumeParticipationRate" not in payload["tradeConfig"]


def test_cli_longtest_baselines_use_fixed_research_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--baseline-set",
            "legacy_lifecycle_v1",
            "--checkpoint-id",
            "checkpoint_test",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "H1_half_hour_current_bar",
        "H2_half_hour_next_bar",
        "Q1_quarter_hour_next_bar",
    ]
    assert [item["payload"]["snapshot_type"] for item in specs] == [
        "half_hour",
        "half_hour",
        "quarter_hour",
    ]
    assert [item["payload"]["tradeConfig"]["executionMode"] for item in specs] == [
        "current_bar",
        "next_bar",
        "next_bar",
    ]
    assert [item["payload"]["maxHoldingBars"] for item in specs] == [40, 40, 80]
    assert all(item["payload"]["random_seed"] == 20260430 for item in specs)
    assert all(item["payload"]["strategy_name"] == "rank_trend_candidate" for item in specs)
    assert all(item["payload"]["excludeNonPositivePriceRows"] is False for item in specs)
    assert all(item["payload"]["excludeCrossMarketZeroPriceRows"] is False for item in specs)
    assert all(item["payload"]["excludeAllZeroPriceFrames"] is False for item in specs)


def test_cli_longtest_baselines_default_to_v5_lifecycle_fusion_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--checkpoint-id",
            "checkpoint_early_big_move_dry",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "V5_E1_half_hour_fusion_signal_forward30",
        "V5_E2_half_hour_fusion_current_bar",
    ]
    assert all(item["payload"]["strategy_name"] == "ranktrend_early_big_move_v3_lifecycle_fusion" for item in specs)
    assert [item["payload"]["snapshot_type"] for item in specs] == [
        "half_hour",
        "half_hour",
    ]
    assert [item["payload"]["tradeConfig"]["executionMode"] for item in specs] == [
        "current_bar",
        "current_bar",
    ]
    assert specs[0]["payload"]["enable_trade_simulation"] is False
    assert [item["payload"]["maxHoldingBars"] for item in specs] == [30, 30]
    assert specs[1]["payload"]["stopLossPct"] == 0.05
    assert specs[1]["payload"]["takeProfitPct"] == 9.99
    assert specs[1]["payload"]["tradeConfig"]["volumeParticipationRate"] == 0.1
    assert specs[1]["payload"]["tradeConfig"]["useIntrabarStops"] is True


def test_cli_longtest_baselines_can_build_early_big_move_v1_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--baseline-set",
            "early_big_move_v1",
            "--checkpoint-id",
            "checkpoint_early_big_move_dry",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "E1_half_hour_signal_forward40",
        "E2_half_hour_ranked_current_bar",
        "E3_half_hour_ranked_strict_fill",
    ]
    assert all(item["payload"]["strategy_name"] == "ranktrend_early_big_move" for item in specs)
    assert specs[0]["payload"]["enable_trade_simulation"] is False
    assert specs[2]["payload"]["tradeConfig"]["fillFallbackMode"] == "strict_fill"


def test_cli_longtest_baselines_can_explicitly_dry_run_legacy_lifecycle_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--baseline-set",
            "legacy_lifecycle_v1",
            "--checkpoint-id",
            "checkpoint_legacy_lifecycle_dry",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "H1_half_hour_current_bar",
        "H2_half_hour_next_bar",
        "Q1_quarter_hour_next_bar",
    ]
    assert all(item["payload"]["strategy_name"] == "rank_trend_candidate" for item in specs)


def test_ranktrend_early_big_move_strategy_name_is_supported() -> None:
    assert normalize_strategy_name("ranktrend_early_big_move") == "ranktrend_early_big_move"


def test_ranktrend_early_big_move_v2_strategy_name_is_supported() -> None:
    assert normalize_strategy_name("ranktrend_early_big_move_v2") == "ranktrend_early_big_move_v2"


def test_ranktrend_early_big_move_v3_strategy_name_is_supported() -> None:
    assert normalize_strategy_name("ranktrend_early_big_move_v3") == "ranktrend_early_big_move_v3"


def test_ranktrend_early_big_move_v3_no_lifecycle_gate_strategy_name_is_supported() -> None:
    assert (
        normalize_strategy_name("ranktrend_early_big_move_v3_no_lifecycle_gate")
        == "ranktrend_early_big_move_v3_no_lifecycle_gate"
    )


def test_ranktrend_early_big_move_v3_context_probe_strategy_name_is_supported() -> None:
    assert (
        normalize_strategy_name("ranktrend_early_big_move_v3_context_probe")
        == "ranktrend_early_big_move_v3_context_probe"
    )


def test_ranktrend_early_big_move_v3_a_main_risk_filter_strategy_name_is_supported() -> None:
    assert (
        normalize_strategy_name("ranktrend_early_big_move_v3_a_main_risk_filter")
        == "ranktrend_early_big_move_v3_a_main_risk_filter"
    )


def test_ranktrend_early_big_move_v3_b_long_filter_strategy_name_is_supported() -> None:
    assert (
        normalize_strategy_name("ranktrend_early_big_move_v3_b_long_filter")
        == "ranktrend_early_big_move_v3_b_long_filter"
    )


def test_cli_longtest_baselines_can_build_early_big_move_v2_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--baseline-set",
            "early_big_move_v2",
            "--checkpoint-id",
            "checkpoint_early_big_move_v2_dry",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "V2_E1_half_hour_signal_forward40",
        "V2_E2_half_hour_ranked_current_bar",
        "V2_E3_half_hour_ranked_strict_fill",
    ]
    assert all(item["payload"]["strategy_name"] == "ranktrend_early_big_move_v2" for item in specs)
    assert specs[0]["payload"]["enable_trade_simulation"] is False
    assert [item["payload"]["tradeConfig"]["executionMode"] for item in specs] == [
        "current_bar",
        "current_bar",
        "next_bar",
    ]
    strict_trade_config = specs[2]["payload"]["tradeConfig"]
    assert strict_trade_config["fillFallbackMode"] == "strict_fill"
    assert specs[1]["payload"]["stopLossPct"] == 0.05
    assert specs[1]["payload"]["takeProfitPct"] == 9.99
    assert specs[1]["payload"]["tradeConfig"]["useIntrabarStops"] is True


def test_cli_longtest_baselines_can_build_early_big_move_v3_contract() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--baseline-set",
            "early_big_move_v3",
            "--checkpoint-id",
            "checkpoint_early_big_move_v3_dry",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert [item["label"] for item in specs] == [
        "V3_E1_half_hour_signal_forward50",
        "V3_E2_half_hour_ranked_current_bar",
        "V3_E3_half_hour_ranked_strict_fill",
    ]
    assert all(item["payload"]["strategy_name"] == "ranktrend_early_big_move_v3" for item in specs)
    assert [item["payload"]["maxHoldingBars"] for item in specs] == [50, 50, 50]
    assert specs[0]["payload"]["enable_trade_simulation"] is False
    assert specs[2]["payload"]["tradeConfig"]["fillFallbackMode"] == "strict_fill"
    assert specs[1]["payload"]["stopLossPct"] == 0.05
    assert specs[1]["payload"]["takeProfitPct"] == 9.99


def test_cli_longtest_baselines_can_enable_positive_price_research_filter() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--exclude-non-positive-price-rows",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert all(item["payload"]["excludeNonPositivePriceRows"] is True for item in specs)


def test_cli_longtest_baselines_can_enable_split_price_research_filters() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "run-longtest-baselines",
            "--dataset-id",
            "dragonboard_live",
            "--exclude-cross-market-zero-price-rows",
            "--exclude-all-zero-price-frames",
            "--dry-run",
        ]
    )

    specs = build_longtest_baseline_payloads(args)

    assert all(item["payload"]["excludeCrossMarketZeroPriceRows"] is True for item in specs)
    assert all(item["payload"]["excludeAllZeroPriceFrames"] is True for item in specs)
    assert all(item["payload"]["excludeNonPositivePriceRows"] is False for item in specs)


def test_longtest_baseline_summary_extracts_metrics_and_quality() -> None:
    spec = {
        "label": "H2_half_hour_next_bar",
        "purpose": "formal conservative baseline",
        "payload": {
            "dataset_id": "dragonboard_live",
            "snapshot_type": "half_hour",
            "strategy_name": "rank_trend_candidate",
            "random_seed": 20260430,
            "maxHoldingBars": 40,
            "targetHoldingDays": 5,
            "tradeConfig": {"executionMode": "next_bar", "volumeParticipationRate": 0.1},
        },
    }
    run = {
        "runId": "bt_test",
        "datasetId": "dragonboard_live",
        "snapshotType": "half_hour",
        "strategyName": "rank_trend_candidate",
        "configHash": "abc",
        "randomSeed": 20260430,
        "totalReturn": -0.01,
        "realizedReturn": -0.02,
        "maxDrawdown": -0.05,
        "sharpe": -1.2,
        "winRate": 0.4,
        "tradeCount": 10,
        "openPositionCount": 1,
        "dataQuality": {
            "severity": "warn",
            "researchGrade": "degraded",
            "sampleOkShare": 0.5,
            "sampleDegradedShare": 0.3,
            "sampleInsufficientShare": 0.2,
            "qualityGate": {
                "stats": {
                    "missingMoneyFlowSourceCount": 12,
                    "formalMoneyFlowCount": 1,
                    "estimatedL1MoneyFlowCount": 2,
                }
            },
        },
        "tradeSimulation": {
            "matchingDiagnostics": {
                "blockedByLimit": 3,
                "nextBarEntries": 7,
                "nextBarExits": 8,
                "buyFilled": 7,
                "sellFilled": 8,
            }
        },
    }
    run["dataQuality"]["runtimeFilter"] = {
        "priceFilter": {
            "reason": "positive_price_stock_rows_only",
            "droppedNonPositivePriceRows": 5,
        },
        "crossMarketPriceFilter": {
            "reason": "cross_market_zero_price_rows_excluded",
            "droppedCrossMarketZeroPriceRows": 3,
        },
        "allZeroPriceFrameFilter": {
            "reason": "all_zero_price_frames_excluded",
            "droppedAllZeroPriceFrames": 1,
        },
    }
    run["dataQuality"]["reportOnlyDiagnostics"] = {
        "priceQuality": {
            "role": "report_only",
            "crossMarketZeroPriceRows": {"rowCount": 3},
            "allZeroPriceFrames": {"frameCount": 1},
            "partialAshareZeroPriceRows": {"rowCount": 2},
        }
    }
    spec["payload"]["excludeNonPositivePriceRows"] = True
    spec["payload"]["excludeCrossMarketZeroPriceRows"] = True
    spec["payload"]["excludeAllZeroPriceFrames"] = True

    summary = summarize_longtest_baseline(spec, run)

    assert summary["label"] == "H2_half_hour_next_bar"
    assert summary["runId"] == "bt_test"
    assert summary["executionMode"] == "next_bar"
    assert summary["maxHoldingBars"] == 40
    assert summary["volumeParticipationRate"] == 0.1
    assert summary["totalReturn"] == -0.01
    assert summary["researchGrade"] == "degraded"
    assert summary["missingMoneyFlowSourceCount"] == 12
    assert summary["excludeNonPositivePriceRows"] is True
    assert summary["excludeCrossMarketZeroPriceRows"] is True
    assert summary["excludeAllZeroPriceFrames"] is True
    assert summary["priceFilter"]["droppedNonPositivePriceRows"] == 5
    assert summary["crossMarketPriceFilter"]["droppedCrossMarketZeroPriceRows"] == 3
    assert summary["allZeroPriceFrameFilter"]["droppedAllZeroPriceFrames"] == 1
    assert summary["priceQualityDiagnostics"]["crossMarketZeroPriceRows"]["rowCount"] == 3
    assert summary["blockedByLimit"] == 3


def test_cli_exposes_sync_and_migration_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    build_dataset_args = parser.parse_args(["build-dataset", "--source-dataset-id", "dragonboard_live", "--dry-run"])
    assert build_dataset_args.func.__name__ == "cmd_build_dataset"
    assert build_dataset_args.source_dataset_id == "dragonboard_live"
    assert build_dataset_args.dry_run is True
    assert parser.parse_args(["push-backup"]).func.__name__ == "cmd_push_backup"
    push_backup_args = parser.parse_args(["push-backup", "--full-history"])
    assert push_backup_args.func.__name__ == "cmd_push_backup"
    assert push_backup_args.full_history is True
    assert parser.parse_args(["push-outbox", "--limit", "7"]).limit == 7
    assert parser.parse_args(["pull-backup"]).func.__name__ == "cmd_pull_backup"
    assert parser.parse_args(["smoke-backup"]).func.__name__ == "cmd_smoke_backup"
    prune_backup_args = parser.parse_args(["prune-backup", "--dry-run"])
    assert prune_backup_args.func.__name__ == "cmd_prune_backup"
    assert prune_backup_args.dry_run is True
    after_market_args = parser.parse_args(["after-market-once", "--archive-limit", "3", "--backup-limit", "2", "--dry-run"])
    assert after_market_args.func.__name__ == "cmd_after_market_once"
    assert after_market_args.archive_limit == 3
    assert after_market_args.backup_limit == 2
    assert after_market_args.dry_run is True
    backup_day_args = parser.parse_args(["backup-snapshot-day", "--trading-date", "2026-05-06", "--dry-run"])
    assert backup_day_args.func.__name__ == "cmd_backup_snapshot_day"
    assert backup_day_args.dataset_id == "dragonboard_live"
    assert backup_day_args.snapshot_type == "half_hour"
    assert backup_day_args.trading_date == "2026-05-06"
    assert backup_day_args.dry_run is True
    compare_args = parser.parse_args(["compare-backtests", "--run-ids", "bt_1", "bt_2", "--metrics", "totalReturn,winRate"])
    assert compare_args.func.__name__ == "cmd_compare_backtests"
    assert compare_args.run_ids == ["bt_1", "bt_2"]
    assert compare_args.metrics == "totalReturn,winRate"
    export_args = parser.parse_args(["export-report", "--run-id", "bt_1", "--output", str(tmp_path / "bt_1.json")])
    assert export_args.func.__name__ == "cmd_export_report"
    assert export_args.run_id == "bt_1"
    assert export_args.format == "jsonl-bundle"
    legacy_args = parser.parse_args(
        ["export-report", "--run-id", "bt_1", "--output", str(tmp_path / "bt_1.json"), "--format", "legacy-json"]
    )
    assert legacy_args.format == "legacy-json"
    gzip_args = parser.parse_args(
        ["export-report", "--run-id", "bt_1", "--output", str(tmp_path / "bt_1.json.gz"), "--format", "json.gz"]
    )
    assert gzip_args.format == "json.gz"

    bundle_path = tmp_path / "migration.json"
    bundle_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "id": "half_hour:2026-04-25:10:00",
                        "type": "half_hour",
                        "tradingDate": "2026-04-25",
                        "slotTime": "10:00",
                        "timestamp": 1777092000000,
                        "payload": {
                            "type": "half_hour",
                            "tradingDate": "2026-04-25",
                            "slotTime": "10:00",
                            "timestamp": 1777092000000,
                            "hotlist": [{"code": "600001", "rank": 1}],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    captured: list[dict[str, object]] = []
    monkeypatch.setattr("backend.cli.print_json", lambda payload: captured.append(payload))
    args = parser.parse_args(
        [
            "migrate-snapshots",
            "--path",
            str(bundle_path),
            "--dataset-id",
            "cli_migration_dry_run",
            "--dry-run",
        ]
    )
    cmd_migrate_snapshots(args)
    assert captured
    assert captured[0]["ok"] is True
    assert captured[0]["report"]["dry_run"] is True
    assert captured[0]["report"]["scanned"] == 1

    theme_path = tmp_path / "themes.json"
    theme_payload = {
        "version": "cli-theme-test",
        "themes": [{"id": "AI", "name": "人工智能", "stocks": ["000001", "SZ000001"]}],
    }
    theme_path.write_text(json.dumps(theme_payload, ensure_ascii=False), encoding="utf-8")
    verify_theme_args = parser.parse_args(["verify-themes", "--path", str(theme_path)])
    assert verify_theme_args.func.__name__ == "cmd_verify_themes"

    captured.clear()
    cmd_verify_themes(verify_theme_args)
    assert captured
    assert set(captured[0]) >= {
        "ok",
        "expected",
        "actual",
        "mismatches",
        "missingThemes",
        "extraThemes",
        "missingMappings",
        "extraMappings",
        "source",
    }
