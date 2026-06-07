from __future__ import annotations

from backend.core.backtest import TradeSimulator, normalize_strategy_name
from backend.optimization.search_space import normalize_search_space, suggest_params


class FakeTrial:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float, float]] = []

    def suggest_float(self, name: str, low: float, high: float, **_: object) -> float:
        self.calls.append(("float", name, low, high))
        return 15.5

    def suggest_int(self, name: str, low: int, high: int, **_: object) -> int:
        self.calls.append(("int", name, low, high))
        return low


def test_continuous_float_search_space_uses_optuna_float_suggestion() -> None:
    from backend.optimization.search_space import search_space_mode

    space = normalize_search_space(
        {
            "jumpDeltaPct": {"type": "float", "low": 8.0, "high": 22.0},
            "maxPositions": [3],
        }
    )

    params = suggest_params(FakeTrial(), space)

    assert params["jumpDeltaPct"] == 15.5
    assert params["maxPositions"] == 3
    assert search_space_mode(space) == "continuous"


def test_ranktrend_jump_strategy_is_registered_for_research_runs() -> None:
    assert normalize_strategy_name("ranktrend_jump") == "ranktrend_jump"


def test_blocked_fill_mode_rejects_missing_orderbook_quote() -> None:
    fill = TradeSimulator._match_order(
        {
            "code": "600001",
            "price": 10.0,
            "change": 1.2,
            "volume": 1000000,
        },
        "buy",
        100,
        10.0,
        {
            "useOrderBookPrice": True,
            "fillFallbackMode": "blocked_fill",
            "enforceLimitStatus": True,
            "enforceOrderBookQueue": True,
            "enforceVolumeLimit": True,
            "volumeParticipationRate": 0.05,
            "orderBookParticipationRate": 0.3,
        },
    )

    assert fill["filled"] is False
    assert fill["reason"] == "missing_order_book_quote"


def test_strict_fill_mode_rejects_missing_orderbook_quote() -> None:
    fill = TradeSimulator._match_order(
        {
            "code": "600001",
            "price": 10.0,
            "change": 1.2,
            "volume": 1000000,
        },
        "buy",
        100,
        10.0,
        {
            "useOrderBookPrice": True,
            "fillFallbackMode": "strict_fill",
            "enforceLimitStatus": True,
            "enforceOrderBookQueue": True,
            "enforceVolumeLimit": True,
            "volumeParticipationRate": 0.05,
            "orderBookParticipationRate": 0.3,
        },
    )

    assert fill["filled"] is False
    assert fill["reason"] == "missing_order_book_quote"



def test_fallback_penalized_mode_marks_snapshot_fallback() -> None:
    fill = TradeSimulator._match_order(
        {
            "code": "600001",
            "price": 10.0,
            "change": 1.2,
            "volume": 1000000,
        },
        "buy",
        100,
        10.0,
        {
            "useOrderBookPrice": True,
            "fillFallbackMode": "fallback_penalized",
            "fallbackSlippageRate": 0.002,
            "slippageRate": 0.001,
            "enforceLimitStatus": True,
            "enforceOrderBookQueue": True,
            "enforceVolumeLimit": True,
            "volumeParticipationRate": 0.05,
            "orderBookParticipationRate": 0.3,
        },
    )

    assert fill["filled"] is True
    assert fill["snapshotPriceFallback"] is True
    assert fill["priceSource"] == "snapshot_price"
    assert fill["price"] == 10.03


def test_ranktrend_jump_can_exit_without_current_ranktrend_signal_when_price_row_exists() -> None:
    frames = [
        {
            "snapshotId": "s1",
            "timestamp": "2026-05-06T10:00:00",
            "tradingDate": "2026-05-06",
            "slotTime": "10:00",
            "stocks": [{"code": "600001", "price": 10.0, "change": 2.0}],
        },
        {
            "snapshotId": "s2",
            "timestamp": "2026-05-07T10:00:00",
            "tradingDate": "2026-05-07",
            "slotTime": "10:00",
            "stocks": [{"code": "600001", "price": 11.0, "change": 1.0}],
        },
    ]
    signals = [
        {
            "snapshotId": "s1",
            "timestamp": "2026-05-06T10:00:00",
            "tradingDate": "2026-05-06",
            "slotTime": "10:00",
            "code": "600001",
            "name": "测试股",
            "rank": 8,
            "price": 10.0,
            "change": 2.0,
            "candidateTier": "A_MAIN",
            "stage": "ignite",
            "regime": "strong",
            "confidence": 90,
            "rankTrend": {
                "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
                "technical": {
                    "macd": {"cross": "golden"},
                    "signals": {
                        "direction": {"signal": "buy"},
                        "acceleration": {"signal": "buy"},
                    },
                },
                "meta": {"rawChange": 120},
            },
        }
    ]

    result = TradeSimulator().run(
        frames,
        signals,
        {
            "entryStrategy": "ranktrend_jump",
            "executionMode": "current_bar",
            "initialCapital": 100000,
            "positionSize": 0.2,
            "maxPositions": 3,
            "maxHoldingBars": 1,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": False,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.05,
            "takeProfit": 0.12,
        },
    )

    assert result["tradeCount"] == 1
    assert result["trades"][0]["reason"] == "到达最大持有快照"


def test_ranktrend_jump_entry_uses_trend_signals_not_static_rank_gate() -> None:
    signal = {
        "code": "600001",
        "rank": 88,
        "price": 10.0,
        "change": 2.0,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "buy"},
                },
            },
        },
    }

    assert TradeSimulator._is_jump_entry_signal(signal) is True


def test_ranktrend_jump_entry_requires_momentum_and_acceleration_confirmation() -> None:
    signal = {
        "code": "600001",
        "rank": 8,
        "price": 10.0,
        "change": 2.0,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 90},
            "technical": {
                "macd": {"cross": "golden"},
                "signals": {
                    "direction": {"signal": "buy"},
                    "acceleration": {"signal": "hold"},
                },
            },
        },
    }

    assert TradeSimulator._is_jump_entry_signal(signal) is False


def test_jump_research_request_uses_continuous_tpe_and_reproducible_metadata() -> None:
    from backend.analysis.ranktrend_jump_research import build_jump_research_request

    request = build_jump_research_request(
        {
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "randomSeed": 20260430,
            "trials": 7,
            "fillFallbackMode": "blocked_fill",
        }
    )

    assert request["method"] == "tpe"
    assert request["objective"] == "ranktrend_jump"
    assert request["strategy_name"] == "ranktrend_jump"
    assert request["random_seed"] == 20260430
    assert request["search_space"]["jumpDeltaPct"] == {"type": "float", "low": 8.0, "high": 22.0}
    assert request["backtest"]["trade_config"]["maxHoldingBars"] == 40
    assert request["backtest"]["trade_config"]["enforceT1"] is True
    assert request["backtest"]["trade_config"]["fillFallbackMode"] == "blocked_fill"
    assert request["walk_forward"]["enabled"] is True


def test_jump_research_summary_flags_fallback_dependency() -> None:
    from backend.analysis.ranktrend_jump_research import summarize_jump_research

    summary = summarize_jump_research(
        {
            "best": {
                "parameters": {"jumpDeltaPct": 15.2},
                "metrics": {"totalReturn": 0.07, "winRate": 0.62, "tradeCount": 19, "maxDrawdown": -0.03},
            },
            "walkForward": {"enabled": True, "segmentCount": 2, "aggregate": {"positiveReturnSegmentRate": 0.5}},
            "backtestArtifacts": [
                {
                    "result": {
                        "tradeSimulation": {
                            "matchingDiagnostics": {
                                "snapshotFallbackRate": 0.35,
                                "snapshotPriceFallbacks": 7,
                            }
                        }
                    }
                }
            ],
        },
        fill_fallback_mode="fallback_penalized",
    )

    assert summary["language"] == "zh-CN"
    assert summary["bestDeltaPct"] == 15.2
    assert summary["riskLevel"] == "medium"
    assert "盘口缺失回退占比偏高" in summary["warnings"][0]


def test_jump_objective_penalizes_tiny_sample_and_fallback_dependency() -> None:
    from backend.optimization.objective import score

    healthy = {
        "totalReturn": 0.06,
        "winRate": 0.62,
        "maxDrawdown": -0.02,
        "tradeCount": 18,
        "matchingDiagnostics": {"snapshotFallbackRate": 0.05},
    }
    fragile = {
        "totalReturn": 0.12,
        "winRate": 1.0,
        "maxDrawdown": -0.01,
        "tradeCount": 1,
        "matchingDiagnostics": {"snapshotFallbackRate": 0.8},
    }

    assert score(healthy, "ranktrend_jump") > score(fragile, "ranktrend_jump")


def test_cli_exposes_ranktrend_jump_research_command() -> None:
    from backend.cli import build_parser

    parser = build_parser()

    args = parser.parse_args(
        [
            "research-ranktrend-jump",
            "--dataset-id",
            "dragonboard_live",
            "--snapshot-type",
            "half_hour",
            "--trials",
            "9",
            "--fill-fallback-mode",
            "blocked_fill",
        ]
    )

    assert args.dataset_id == "dragonboard_live"
    assert args.snapshot_type == "half_hour"
    assert args.trials == 9
    assert args.fill_fallback_mode == "blocked_fill"
