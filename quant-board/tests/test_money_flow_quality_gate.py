import pytest

from backend.data.quality_gate import evaluate_snapshot_quality
from backend.services import (
    _cross_market_zero_price_stock_rows,
    _drop_all_zero_price_frames,
    _ensure_runtime_filtered_frames_usable,
    _positive_price_stock_rows,
    _prepare_frames_for_backtest,
    _stock_rows_for_quality,
)


def test_formal_money_flow_gate_blocks_estimated_l1_rows() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:00",
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:30",
        },
    ]
    stock_rows = [
        {
            "snapshotId": "s1",
            "rowId": "s1-000001",
            "code": "000001",
            "price": 10,
            "change": 1,
            "volume": 100,
            "turnover": 1000,
            "turnoverRate": 1,
            "avgRankNum": 1,
            "finalConfidence": 70,
            "capitalFlowSource": "estimated_l1",
            "capitalFlowConfidence": "low",
            "moneyFlowEstimated": True,
        },
        {
            "snapshotId": "s2",
            "rowId": "s2-000001",
            "code": "000001",
            "price": 11,
            "change": 2,
            "volume": 110,
            "turnover": 1200,
            "turnoverRate": 1.2,
            "avgRankNum": 1,
            "finalConfidence": 72,
            "capitalFlowSource": "broker_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
    ]

    result = evaluate_snapshot_quality(
        frames,
        stock_rows,
        require_formal_money_flow=True,
    )

    assert result.passed is False
    assert result.severity == "fail"
    assert result.stats["estimatedL1MoneyFlowCount"] == 1
    assert result.stats["formalMoneyFlowCoverageRatio"] == 0.5
    assert any("estimated_l1 money flow blocked" in issue for issue in result.issues)


def test_backtest_quality_rows_preserve_money_flow_sources() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:00",
            "stocks": [
                {
                    "snapshotId": "s1",
                    "rowId": "s1-000001",
                    "code": "000001",
                    "price": 0,
                    "capitalFlowSource": "official_l2",
                    "capitalFlowConfidence": "medium",
                    "moneyFlowSource": "eastmoney",
                    "moneyFlowEstimated": False,
                },
                {
                    "snapshotId": "s1",
                    "rowId": "s1-000002",
                    "code": "000002",
                    "price": 0,
                    "capitalFlowSource": "estimated_l1",
                    "capitalFlowConfidence": "low",
                    "moneyFlowSource": "tdx_estimate",
                    "moneyFlowEstimated": True,
                },
            ],
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:30",
            "stocks": [{"snapshotId": "s2", "rowId": "s2-000003", "code": "000003", "price": 0}],
        },
    ]

    rows = _stock_rows_for_quality(frames)
    result = evaluate_snapshot_quality(frames, rows, snapshot_type="half_hour")

    assert result.stats["formalMoneyFlowCount"] == 1
    assert result.stats["estimatedL1MoneyFlowCount"] == 1
    assert result.stats["missingMoneyFlowSourceCount"] == 1
    assert result.stats["moneyFlowSourceCounts"] == {
        "official_l2": 1,
        "estimated_l1": 1,
        "missing": 1,
    }
    assert result.stats["nonPositivePriceCount"] == 0


def test_prepare_frames_for_backtest_reports_money_flow_sources_without_price_block() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:00",
            "stocks": [
                {
                    "code": "000001",
                    "price": 0,
                    "capitalFlowSource": "official_l2",
                    "capitalFlowConfidence": "medium",
                    "moneyFlowEstimated": False,
                }
            ],
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
            "tradingDate": "2026-05-08",
            "slotTime": "10:30",
            "stocks": [
                {
                    "code": "000002",
                    "price": 0,
                    "capitalFlowSource": "estimated_l1",
                    "capitalFlowConfidence": "low",
                    "moneyFlowEstimated": True,
                }
            ],
        },
    ]

    run_frames, gate = _prepare_frames_for_backtest(frames, "half_hour")

    assert run_frames == frames
    assert gate["passed"] is True
    assert gate["stats"]["formalMoneyFlowCount"] == 1
    assert gate["stats"]["estimatedL1MoneyFlowCount"] == 1
    assert gate["stats"]["nonPositivePriceCount"] == 0


def test_positive_price_research_filter_drops_only_explicit_non_positive_rows() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "stocks": [
                {"code": "000001", "price": 10},
                {"code": "000002", "price": 0},
                {"code": "000003", "price": None},
            ],
        },
        {
            "snapshotId": "s2",
            "stocks": [{"code": "000004", "price": -1}],
        },
    ]

    filtered, stats = _positive_price_stock_rows(frames)

    assert [stock["code"] for stock in filtered[0]["stocks"]] == ["000001"]
    assert filtered[1]["stocks"] == []
    assert stats["droppedNonPositivePriceRows"] == 3
    assert stats["impactedSnapshots"] == 2
    assert stats["emptySnapshotsAfterFilter"] == 1
    assert stats["emptySnapshotIdsAfterFilter"] == ["s2"]


def test_runtime_price_filters_block_when_usable_snapshots_drop_below_minimum() -> None:
    frames = [
        {"snapshotId": "s1", "stocks": []},
        {"snapshotId": "s2", "stocks": [{"code": "000001"}]},
    ]
    quality_gate = {
        "passed": True,
        "severity": "pass",
        "issues": [],
        "stats": {"minSnapshotCount": 2},
        "runtimeFilter": {
            "priceFilter": {
                "reason": "positive_price_stock_rows_only",
                "emptySnapshotsAfterFilter": 1,
            }
        },
    }

    with pytest.raises(ValueError) as error:
        _ensure_runtime_filtered_frames_usable(frames, quality_gate)

    failed_gate = error.value.args[0]["qualityGate"]
    assert failed_gate["passed"] is False
    assert failed_gate["severity"] == "fail"
    assert failed_gate["runtimeFilter"] == quality_gate["runtimeFilter"]
    assert failed_gate["issues"] == [
        "runtime filters left usable snapshots below minimum 2: 1",
    ]


def test_cross_market_zero_price_filter_uses_a_share_universe() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "stocks": [
                {"code": "009992", "name": "泡泡玛特", "price": 0, "change": 0, "volume": 0, "turnover": 0},
                {"code": "603986", "name": "兆易创新", "price": 0, "change": 0, "volume": 0, "turnover": 0},
                {"code": "000000", "name": "特斯拉", "price": 0, "change": 0, "volume": 0, "turnover": 0},
                {"code": "000001", "name": "平安银行", "price": 10, "change": 1, "volume": 100, "turnover": 1000},
            ],
        }
    ]

    filtered, stats = _cross_market_zero_price_stock_rows(frames, {"603986", "000001"})

    assert [stock["code"] for stock in filtered[0]["stocks"]] == ["603986", "000001"]
    assert stats["droppedCrossMarketZeroPriceRows"] == 2
    assert stats["impactedSnapshots"] == 1
    assert stats["aShareUniverseAvailable"] is True
    assert stats["aShareUniverseCodeCount"] == 2


def test_cross_market_zero_price_filter_keeps_raw_hk_prefix_before_a_share_normalization() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "stocks": [
                {"code": "00700", "name": "腾讯控股", "price": 0, "change": 0, "volume": 0, "turnover": 0},
                {"code": "000700", "name": "模塑科技", "price": 12, "change": 1, "volume": 100, "turnover": 1000},
            ],
        }
    ]

    filtered, stats = _cross_market_zero_price_stock_rows(frames, {"000700"})

    assert [stock["code"] for stock in filtered[0]["stocks"]] == ["000700"]
    assert stats["droppedCrossMarketZeroPriceRows"] == 1
    assert stats["examples"][0]["code"] == "00700"


def test_cross_market_zero_price_filter_skips_all_zero_frames() -> None:
    frames = [
        {
            "snapshotId": "all_zero",
            "stocks": [
                {"code": "009992", "name": "泡泡玛特", "price": 0, "change": 0, "volume": 0, "turnover": 0},
                {"code": "603986", "name": "兆易创新", "price": 0, "change": 0, "volume": 0, "turnover": 0},
            ],
        }
    ]

    filtered, stats = _cross_market_zero_price_stock_rows(frames, {"603986"})

    assert filtered == frames
    assert stats["droppedCrossMarketZeroPriceRows"] == 0
    assert stats["skippedAllZeroPriceFrames"] == 1
    assert stats["skippedAllZeroPriceFrameIds"] == ["all_zero"]


def test_all_zero_price_frame_filter_drops_only_full_zero_frames() -> None:
    frames = [
        {
            "snapshotId": "all_zero",
            "stocks": [
                {"code": "000001", "price": 0},
                {"code": "000002", "price": None},
            ],
        },
        {
            "snapshotId": "partial_zero",
            "stocks": [
                {"code": "000003", "price": 0},
                {"code": "000004", "price": 12},
            ],
        },
    ]

    filtered, stats = _drop_all_zero_price_frames(frames)

    assert [frame["snapshotId"] for frame in filtered] == ["partial_zero"]
    assert stats["droppedAllZeroPriceFrames"] == 1
    assert stats["droppedAllZeroPriceRows"] == 2
    assert stats["droppedSnapshotIds"] == ["all_zero"]


def test_formal_money_flow_gate_allows_estimated_l1_when_explicitly_enabled() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
        },
    ]
    stock_rows = [
        {
            "snapshotId": "s1",
            "code": "000001",
            "price": 10,
            "volume": 100,
            "capitalFlowSource": "estimated_l1",
            "capitalFlowConfidence": "low",
            "moneyFlowEstimated": True,
        },
        {
            "snapshotId": "s2",
            "code": "600000",
            "price": 12,
            "volume": 120,
            "capitalFlowSource": "broker_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
    ]

    result = evaluate_snapshot_quality(
        frames,
        stock_rows,
        require_formal_money_flow=True,
        allow_estimated_l1_money_flow=True,
    )

    assert result.passed is True
    assert result.stats["estimatedL1MoneyFlowCount"] == 1
    assert result.stats["formalMoneyFlowCoverageRatio"] == 0.5


def test_formal_money_flow_gate_passes_broker_l2_rows() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "type": "half_hour",
            "timestamp": 1,
            "captureMode": "real_time",
        },
        {
            "snapshotId": "s2",
            "type": "half_hour",
            "timestamp": 2,
            "captureMode": "real_time",
        },
    ]
    stock_rows = [
        {
            "snapshotId": "s1",
            "code": "000001",
            "price": 10,
            "volume": 100,
            "capitalFlowSource": "broker_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
        {
            "snapshotId": "s2",
            "code": "600000",
            "price": 12,
            "volume": 120,
            "capitalFlowSource": "official_l2",
            "capitalFlowConfidence": "high",
            "moneyFlowEstimated": False,
        },
    ]

    result = evaluate_snapshot_quality(
        frames,
        stock_rows,
        require_formal_money_flow=True,
    )

    assert result.passed is True
    assert result.stats["formalMoneyFlowCoverageRatio"] == 1
