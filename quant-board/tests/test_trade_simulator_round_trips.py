from backend.core.backtest import TradeSimulator


def _jump_signal(snapshot_id: str, date: str, price: float, volume: int) -> dict:
    return {
        "snapshotId": snapshot_id,
        "timestamp": snapshot_id,
        "tradingDate": date,
        "slotTime": "10:00",
        "code": "600001",
        "name": "测试股",
        "rank": 8,
        "price": price,
        "change": 2,
        "volume": volume,
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


def test_trade_count_and_win_rate_are_grouped_by_entry_when_exit_is_partial() -> None:
    frames = [
        {"snapshotId": "s1", "timestamp": "s1", "tradingDate": "2026-05-06", "slotTime": "10:00"},
        {"snapshotId": "s2", "timestamp": "s2", "tradingDate": "2026-05-07", "slotTime": "10:00"},
        {"snapshotId": "s3", "timestamp": "s3", "tradingDate": "2026-05-08", "slotTime": "10:00"},
    ]
    signals = [
        _jump_signal("s1", "2026-05-06", 10.0, 2_000),
        _jump_signal("s2", "2026-05-07", 9.0, 500),
        _jump_signal("s3", "2026-05-08", 12.0, 2_000),
    ]

    result = TradeSimulator().run(
        frames,
        signals,
        {
            "entryStrategy": "ranktrend_jump",
            "initialCapital": 100000,
            "positionSize": 0.1,
            "maxPositions": 1,
            "maxHoldingBars": 1,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": True,
            "volumeParticipationRate": 1,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.5,
            "takeProfit": 0.5,
        },
    )

    assert result["exitSliceCount"] == 2
    assert result["exitSliceWinRate"] == 0.5
    assert result["tradeCount"] == 1
    assert result["winRate"] == 1.0
    assert result["roundTripTrades"][0]["exitSliceCount"] == 2
    assert result["roundTripTrades"][0]["profit"] == 500


def test_early_big_move_entry_allows_final_hold_when_jump_and_momentum_are_strong() -> None:
    signal = {
        "snapshotId": "half_hour:2026-05-21:09:30",
        "timestamp": "2026-05-21T09:30:00",
        "tradingDate": "2026-05-21",
        "slotTime": "09:30",
        "code": "002552",
        "name": "宝鼎科技",
        "rank": 18,
        "price": 10.0,
        "change": 6.2,
        "volume": 2_000,
        "candidateTier": "N_NEUTRAL",
        "stage": "ignition",
        "regime": "strong",
        "confidence": 80,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "confidence": 94.2},
            "technical": {
                "signals": {
                    "short": {"value": 18.7},
                    "mid": {"value": 12.8},
                    "long": {"value": 14.3},
                    "acceleration": {"value": 27.2},
                    "direction": {"signal": "hold"},
                    "zeroCross": {"signal": "hold"},
                },
                "macd": {"cross": "hold"},
            },
            "decision": {"final": {"signal": "hold"}},
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [signal],
        [{"snapshotId": "half_hour:2026-05-21:09:30"}],
        0,
        {},
        {},
        "ranktrend_early_big_move",
    )

    assert [item["code"] for item in candidates] == ["002552"]


def test_early_big_move_entry_reads_python_momentum_profile() -> None:
    signal = {
        "snapshotId": "half_hour:2026-04-30:09:30",
        "timestamp": "2026-04-30T09:30:00",
        "tradingDate": "2026-04-30",
        "slotTime": "09:30",
        "code": "600150",
        "name": "中国船舶",
        "rank": 6,
        "price": 35.0,
        "change": 3.52,
        "volume": 20_000,
        "candidateTier": "A_MAIN",
        "stage": "expansion",
        "regime": "strong",
        "confidence": 85,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "sustained": True, "confidence": 95},
            "technical": {
                "momentumProfile": {
                    "short": 78.92,
                    "mid": 39.46,
                    "long": 42.26,
                    "acceleration": 102.64,
                },
                "signals": {
                    "direction": {"signal": "hold"},
                    "acceleration": {"signal": "hold", "score": -0.01},
                    "zeroCross": {"signal": "hold"},
                },
                "macd": {"cross": "hold"},
            },
            "decision": {"final": {"signal": "hold"}},
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [signal],
        [{"snapshotId": "half_hour:2026-04-30:09:30"}],
        0,
        {},
        {},
        "ranktrend_early_big_move",
    )

    assert [item["code"] for item in candidates] == ["600150"]


def _early_big_move_v2_signal(
    *,
    tier: str = "A_MAIN",
    change: float = 5.5,
    final_signal: str = "hold",
    macd_cross: str = "hold",
    zero_cross: str = "hold",
    acceleration: float = 32.0,
) -> dict:
    return {
        "snapshotId": "half_hour:2026-05-21:09:30",
        "timestamp": "2026-05-21T09:30:00",
        "tradingDate": "2026-05-21",
        "slotTime": "09:30",
        "code": "002552",
        "name": "宝鼎科技",
        "rank": 18,
        "price": 10.0,
        "change": change,
        "volume": 20_000,
        "candidateTier": tier,
        "stage": "ignition",
        "regime": "strong",
        "confidence": 88,
        "rankTrend": {
            "jump": {"event": "jump", "direction": "buy", "confidence": 94.2},
            "technical": {
                "momentumProfile": {
                    "short": 18.7,
                    "mid": 12.8,
                    "long": 14.3,
                    "acceleration": acceleration,
                },
                "signals": {
                    "direction": {"signal": "hold"},
                    "acceleration": {"signal": "hold", "score": -0.01},
                    "zeroCross": {"signal": zero_cross},
                },
                "macd": {"cross": macd_cross},
            },
            "decision": {"final": {"signal": final_signal}},
        },
    }


def test_early_big_move_v2_entry_trades_a_or_b_without_final_macd_zerocross_confirmation() -> None:
    signal = _early_big_move_v2_signal(
        tier="A_MAIN",
        final_signal="hold",
        macd_cross="hold",
        zero_cross="hold",
    )

    candidates = TradeSimulator._entry_candidates(
        [signal],
        [{"snapshotId": signal["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v2",
    )

    assert [item["code"] for item in candidates] == ["002552"]


def test_early_big_move_v2_entry_reason_does_not_claim_final_signal_confirmation() -> None:
    signal = _early_big_move_v2_signal(tier="B_IGNITION", final_signal="hold")

    reason = TradeSimulator._entry_reason(
        signal,
        [{"snapshotId": signal["snapshotId"]}],
        0,
        {},
        "ranktrend_early_big_move_v2",
    )

    assert reason == "早期大肉V2入场：B_IGNITION + 高置信jump + 多周期动量同步"
    assert "finalSignal" not in reason


def test_early_big_move_v2_entry_excludes_neutral_and_overheated_candidates() -> None:
    neutral = _early_big_move_v2_signal(tier="N_NEUTRAL", change=5.0)
    overheated = _early_big_move_v2_signal(tier="B_IGNITION", change=6.0)

    candidates = TradeSimulator._entry_candidates(
        [neutral, overheated],
        [{"snapshotId": neutral["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v2",
    )

    assert candidates == []


def test_early_big_move_v3_keeps_a_main_and_requires_b_mid_momentum_with_zero_cross_buy() -> None:
    a_main = _early_big_move_v2_signal(
        tier="A_MAIN",
        zero_cross="hold",
    )
    weak_b = _early_big_move_v2_signal(
        tier="B_IGNITION",
        zero_cross="hold",
    )
    weak_b["code"] = "002553"
    strong_b = _early_big_move_v2_signal(
        tier="B_IGNITION",
        zero_cross="buy",
    )
    strong_b["code"] = "002554"
    strong_b["rankTrend"]["technical"]["momentumProfile"]["mid"] = 20

    candidates = TradeSimulator._entry_candidates(
        [a_main, weak_b, strong_b],
        [{"snapshotId": a_main["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3",
    )

    assert {item["code"] for item in candidates} == {"002552", "002554"}
    assert "002553" not in {item["code"] for item in candidates}


def test_early_big_move_v3_no_lifecycle_gate_allows_strong_structure_without_a_b_tier() -> None:
    neutral = _early_big_move_v2_signal(
        tier="N_NEUTRAL",
        zero_cross="hold",
    )
    neutral["code"] = "002600"
    neutral["rankTrend"]["technical"]["momentumProfile"]["mid"] = 24
    neutral["rankTrend"]["technical"]["momentumProfile"]["long"] = 18
    neutral["rankTrend"]["technical"]["momentumProfile"]["acceleration"] = 38
    neutral["rankTrend"]["decision"]["final"]["signal"] = "hold"

    weak_a_main = _early_big_move_v2_signal(
        tier="A_MAIN",
        zero_cross="buy",
        change=5.2,
    )
    weak_a_main["code"] = "002601"
    weak_a_main["rankTrend"]["jump"]["confidence"] = 88.5

    candidates = TradeSimulator._entry_candidates(
        [neutral, weak_a_main],
        [{"snapshotId": neutral["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_no_lifecycle_gate",
    )

    assert {item["code"] for item in candidates} == {"002600"}
    assert "002601" not in {item["code"] for item in candidates}


def test_early_big_move_v3_no_lifecycle_gate_does_not_change_default_v3_gate() -> None:
    neutral = _early_big_move_v2_signal(
        tier="N_NEUTRAL",
        zero_cross="buy",
    )
    neutral["code"] = "002600"
    neutral["rankTrend"]["technical"]["momentumProfile"]["mid"] = 24

    candidates = TradeSimulator._entry_candidates(
        [neutral],
        [{"snapshotId": neutral["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3",
    )

    assert candidates == []


def test_early_big_move_v3_context_probe_keeps_v3_and_only_adds_preferred_non_ab_probe() -> None:
    a_main = _early_big_move_v2_signal(
        tier='A_MAIN',
        zero_cross='hold',
    )
    a_main['code'] = '002552'

    strong_b = _early_big_move_v2_signal(
        tier='B_IGNITION',
        zero_cross='buy',
    )
    strong_b['code'] = '002554'
    strong_b['rankTrend']['technical']['momentumProfile']['mid'] = 20

    preferred_non_ab = _early_big_move_v2_signal(
        tier='N_NEUTRAL',
        zero_cross='buy',
    )
    preferred_non_ab['code'] = '002600'
    preferred_non_ab['rankTrend']['technical']['momentumProfile']['mid'] = 18
    preferred_non_ab['rankTrend']['technical']['momentumProfile']['long'] = 8
    preferred_non_ab['rankTrend']['cycle'] = {
        'stage': 'ignition',
        'transition': 'cooling->ignition',
        'entryAdvice': {
            'allowed': True,
            'bias': 'preferred',
            'reason': '处于优选阶段路径，可作为情绪周期主观察对象。',
        },
    }

    watch_non_ab = _early_big_move_v2_signal(
        tier='N_NEUTRAL',
        zero_cross='buy',
    )
    watch_non_ab['code'] = '002601'
    watch_non_ab['rankTrend']['cycle'] = {
        'stage': 'expansion',
        'transition': 'cooling->expansion',
        'entryAdvice': {
            'allowed': False,
            'bias': 'watch',
            'reason': '处于可跟踪阶段，但还不是优选出手路径。',
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [a_main, strong_b, preferred_non_ab, watch_non_ab],
        [{'snapshotId': a_main['snapshotId']}],
        0,
        {},
        {},
        'ranktrend_early_big_move_v3_context_probe',
    )

    assert {item['code'] for item in candidates} == {'002552', '002554', '002600'}
    assert '002601' not in {item['code'] for item in candidates}


def test_early_big_move_v3_lifecycle_fusion_blocks_strong_a_signal_when_lifecycle_vetoes() -> None:
    vetoed = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="buy", change=5.0)
    vetoed["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "ignition->expansion",
        "decision": {
            "action": "veto",
            "confidence": 86,
            "reasons": ["生命周期B反对：原始路径转弱"],
            "evidence": {
                "rawStage": "reversal",
                "stage": "expansion",
                "transition": "ignition->expansion",
                "rankVelocity": -2.0,
                "rankAcceleration": -3.0,
                "drawdownFromPeak": 4,
                "hotZoneStreak": 2,
            },
        },
    }

    allowed = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="buy", change=5.0)
    allowed["code"] = "002553"
    allowed["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "ignition->expansion",
        "decision": {
            "action": "allow",
            "confidence": 78,
            "reasons": ["生命周期B支持：点火后扩散承接"],
            "evidence": {
                "rawStage": "expansion",
                "stage": "expansion",
                "transition": "ignition->expansion",
                "rankVelocity": 3.0,
                "rankAcceleration": 1.0,
                "drawdownFromPeak": 0,
                "hotZoneStreak": 1,
            },
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [vetoed, allowed],
        [{"snapshotId": vetoed["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_lifecycle_fusion",
    )

    assert {item["code"] for item in candidates} == {"002553"}
    assert "002552" not in {item["code"] for item in candidates}


def test_early_big_move_v3_lifecycle_fusion_does_not_let_lifecycle_allow_create_buy() -> None:
    weak_a = _early_big_move_v2_signal(tier="N_NEUTRAL", zero_cross="buy", change=5.0)
    weak_a["code"] = "002600"
    weak_a["rankTrend"]["jump"]["confidence"] = 80
    weak_a["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "ignition->expansion",
        "decision": {
            "action": "allow",
            "confidence": 80,
            "reasons": ["生命周期B支持"],
            "evidence": {
                "rawStage": "expansion",
                "stage": "expansion",
                "transition": "ignition->expansion",
                "rankVelocity": 3.0,
                "rankAcceleration": 1.0,
                "drawdownFromPeak": 0,
                "hotZoneStreak": 1,
            },
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [weak_a],
        [{"snapshotId": weak_a["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_lifecycle_fusion",
    )

    assert candidates == []


def test_early_big_move_v3_lifecycle_fusion_keeps_discovery_as_research_only() -> None:
    discovery_only = _early_big_move_v2_signal(tier="N_NEUTRAL", zero_cross="buy", change=5.0)
    discovery_only["code"] = "002601"
    discovery_only["rankTrend"]["cycle"] = {
        "stage": "ignition",
        "transition": "cooling->ignition",
        "decision": {
            "action": "allow",
            "confidence": 82,
            "reasons": ["生命周期B支持"],
            "discovery": {
                "action": "research_watch",
                "reasons": ["生命周期存在漏选研究价值，但不制造买入"],
            },
            "evidence": {
                "rawStage": "ignition",
                "stage": "ignition",
                "transition": "cooling->ignition",
                "rankVelocity": 24.0,
                "rankAcceleration": 18.0,
                "drawdownFromPeak": 0,
                "hotZoneStreak": 0,
            },
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [discovery_only],
        [{"snapshotId": discovery_only["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_lifecycle_fusion",
    )

    assert candidates == []


def test_early_big_move_v3_lifecycle_fusion_ranks_allow_before_caution_without_deleting_caution() -> None:
    caution = _early_big_move_v2_signal(tier="B_IGNITION", zero_cross="buy", change=5.0)
    caution["code"] = "000657"
    caution["rankTrend"]["technical"]["momentumProfile"]["mid"] = 24
    caution["rankTrend"]["cycle"] = {
        "stage": "ignition",
        "transition": "cooling->ignition",
        "decision": {
            "action": "caution",
            "confidence": 80,
            "reasons": ["生命周期B识别到低可见度首段点火，承接尚未扩散，防止抢占后续高质量仓位。"],
        },
    }
    allow = _early_big_move_v2_signal(tier="B_IGNITION", zero_cross="buy", change=5.0)
    allow["code"] = "603459"
    allow["rankTrend"]["technical"]["momentumProfile"]["mid"] = 24
    allow["rankTrend"]["cycle"] = {
        "stage": "ignition",
        "transition": "cooling->ignition",
        "decision": {
            "action": "allow",
            "confidence": 80,
            "reasons": ["生命周期B支持：点火承接已扩散。"],
        },
    }

    candidates = TradeSimulator._entry_candidates(
        [caution, allow],
        [{"snapshotId": caution["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_lifecycle_fusion",
    )

    assert [item["code"] for item in candidates] == ["603459", "000657"]


def test_early_big_move_v3_lifecycle_fusion_exits_losing_position_when_lifecycle_vetoes() -> None:
    entry = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="buy", change=4.0)
    entry["snapshotId"] = "s1"
    entry["timestamp"] = 1
    entry["tradingDate"] = "2026-05-21"
    entry["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "cooling->expansion",
        "decision": {"action": "allow", "reasons": ["生命周期B支持"]},
    }
    exit_signal = _early_big_move_v2_signal(tier="D_EXIT_RISK", zero_cross="hold", change=-1.0)
    exit_signal["snapshotId"] = "s2"
    exit_signal["timestamp"] = 2
    exit_signal["tradingDate"] = "2026-05-22"
    exit_signal["price"] = 9.9
    exit_signal["rankTrend"]["cycle"] = {
        "stage": "reversal",
        "transition": "expansion->reversal",
        "decision": {"action": "veto", "reasons": ["生命周期B反对：承接失败"]},
    }

    result = TradeSimulator().run(
        [
            {"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-05-21", "slotTime": "09:30"},
            {"snapshotId": "s2", "timestamp": 2, "tradingDate": "2026-05-22", "slotTime": "09:30"},
        ],
        [entry, exit_signal],
        {
            "entryStrategy": "ranktrend_early_big_move_v3_lifecycle_fusion",
            "initialCapital": 100000,
            "positionSize": 0.1,
            "maxPositions": 1,
            "maxHoldingBars": 99,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": False,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.5,
            "takeProfit": 9.99,
        },
    )

    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "生命周期B反对且未盈利"


def test_early_big_move_v3_lifecycle_fusion_does_not_exit_profitable_position_on_lifecycle_veto() -> None:
    entry = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="buy", change=4.0)
    entry["snapshotId"] = "s1"
    entry["timestamp"] = 1
    entry["tradingDate"] = "2026-05-21"
    entry["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "cooling->expansion",
        "decision": {"action": "allow", "reasons": ["生命周期B支持"]},
    }
    veto_profit = _early_big_move_v2_signal(tier="D_EXIT_RISK", zero_cross="hold", change=1.0)
    veto_profit["snapshotId"] = "s2"
    veto_profit["timestamp"] = 2
    veto_profit["tradingDate"] = "2026-05-22"
    veto_profit["price"] = 10.5
    veto_profit["rankTrend"]["cycle"] = {
        "stage": "reversal",
        "transition": "expansion->reversal",
        "decision": {"action": "veto", "reasons": ["生命周期B反对：但价格仍盈利"]},
    }
    max_hold_exit = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="hold", change=1.0)
    max_hold_exit["snapshotId"] = "s3"
    max_hold_exit["timestamp"] = 3
    max_hold_exit["tradingDate"] = "2026-05-23"
    max_hold_exit["price"] = 10.8
    max_hold_exit["rankTrend"]["cycle"] = {
        "stage": "expansion",
        "transition": "expansion",
        "decision": {"action": "allow", "reasons": ["生命周期B支持"]},
    }

    result = TradeSimulator().run(
        [
            {"snapshotId": "s1", "timestamp": 1, "tradingDate": "2026-05-21", "slotTime": "09:30"},
            {"snapshotId": "s2", "timestamp": 2, "tradingDate": "2026-05-22", "slotTime": "09:30"},
            {"snapshotId": "s3", "timestamp": 3, "tradingDate": "2026-05-23", "slotTime": "09:30"},
        ],
        [entry, veto_profit, max_hold_exit],
        {
            "entryStrategy": "ranktrend_early_big_move_v3_lifecycle_fusion",
            "initialCapital": 100000,
            "positionSize": 0.1,
            "maxPositions": 1,
            "maxHoldingBars": 2,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": False,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.5,
            "takeProfit": 9.99,
        },
    )

    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["exitSnapshotId"] == "s3"
    assert result["roundTripTrades"][0]["reason"] == "到达最大持有快照"


def test_early_big_move_v3_a_main_risk_filter_only_blocks_false_strength_a_main() -> None:
    normal_a = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="hold")
    weak_a = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="hold")
    weak_a["code"] = "002281"
    weak_a["regime"] = "weak"
    weak_a["rankTrend"]["technical"]["momentumProfile"]["long"] = 6.5
    negative_change_a = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="hold", change=-1.0)
    negative_change_a["code"] = "301666"
    strong_b = _early_big_move_v2_signal(tier="B_IGNITION", zero_cross="buy")
    strong_b["code"] = "002554"
    strong_b["rankTrend"]["technical"]["momentumProfile"]["mid"] = 20

    candidates = TradeSimulator._entry_candidates(
        [normal_a, weak_a, negative_change_a, strong_b],
        [{"snapshotId": normal_a["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_a_main_risk_filter",
    )

    assert {item["code"] for item in candidates} == {"002552", "002554"}
    assert "002281" not in {item["code"] for item in candidates}
    assert "301666" not in {item["code"] for item in candidates}


def test_early_big_move_v3_b_long_filter_blocks_weak_long_b_only() -> None:
    a_main = _early_big_move_v2_signal(tier="A_MAIN", zero_cross="hold")
    weak_b = _early_big_move_v2_signal(tier="B_IGNITION", zero_cross="buy")
    weak_b["code"] = "002181"
    weak_b["rankTrend"]["technical"]["momentumProfile"]["mid"] = 21.45
    weak_b["rankTrend"]["technical"]["momentumProfile"]["long"] = 4.5
    strong_b = _early_big_move_v2_signal(tier="B_IGNITION", zero_cross="buy")
    strong_b["code"] = "301217"
    strong_b["rankTrend"]["technical"]["momentumProfile"]["mid"] = 25.05
    strong_b["rankTrend"]["technical"]["momentumProfile"]["long"] = 18.36

    candidates = TradeSimulator._entry_candidates(
        [a_main, weak_b, strong_b],
        [{"snapshotId": a_main["snapshotId"]}],
        0,
        {},
        {},
        "ranktrend_early_big_move_v3_b_long_filter",
    )

    assert {item["code"] for item in candidates} == {"002552", "301217"}
    assert "002181" not in {item["code"] for item in candidates}


def test_early_big_move_v3_a_main_risk_filter_uses_big_move_exit_rules() -> None:
    entry = _early_big_move_v2_signal(tier="A_MAIN", final_signal="hold", change=5.0)
    exit_noise = _early_big_move_v2_signal(tier="D_EXIT_RISK", final_signal="sell", change=7.0)
    exit_noise.update({
        "snapshotId": "half_hour:2026-05-22:09:30",
        "timestamp": "2026-05-22T09:30:00",
        "tradingDate": "2026-05-22",
        "price": 11.0,
    })
    exit_noise["rankTrend"]["decision"]["final"]["signal"] = "sell"
    max_hold_exit = _early_big_move_v2_signal(tier="D_EXIT_RISK", final_signal="sell", change=8.0)
    max_hold_exit.update({
        "snapshotId": "half_hour:2026-05-25:09:30",
        "timestamp": "2026-05-25T09:30:00",
        "tradingDate": "2026-05-25",
        "price": 12.0,
    })

    result = TradeSimulator().run(
        [
            {"snapshotId": entry["snapshotId"], "timestamp": entry["timestamp"], "tradingDate": entry["tradingDate"], "slotTime": entry["slotTime"]},
            {"snapshotId": exit_noise["snapshotId"], "timestamp": exit_noise["timestamp"], "tradingDate": exit_noise["tradingDate"], "slotTime": exit_noise["slotTime"]},
            {"snapshotId": max_hold_exit["snapshotId"], "timestamp": max_hold_exit["timestamp"], "tradingDate": max_hold_exit["tradingDate"], "slotTime": max_hold_exit["slotTime"]},
        ],
        [entry, exit_noise, max_hold_exit],
        {
            "entryStrategy": "ranktrend_early_big_move_v3_a_main_risk_filter",
            "initialCapital": 100000,
            "positionSize": 0.2,
            "maxPositions": 1,
            "maxHoldingBars": 2,
            "enforceT1": True,
            "useOrderBookPrice": False,
            "enforceLimitStatus": False,
            "enforceOrderBookQueue": False,
            "enforceVolumeLimit": False,
            "feeRate": 0,
            "stampTaxRate": 0,
            "slippageRate": 0,
            "stopLoss": -0.05,
            "takeProfit": 0.05,
        },
    )

    assert result["tradeCount"] == 1
    assert result["roundTripTrades"][0]["reason"] == "到达最大持有快照"
    assert result["roundTripTrades"][0]["exitSnapshotId"] == max_hold_exit["snapshotId"]


def test_early_big_move_v2_exit_ignores_legacy_sell_signals_and_take_profit() -> None:
    signal = _early_big_move_v2_signal(final_signal="sell", macd_cross="golden")
    signal["rank"] = 80
    pos = {"holdingBars": 8, "hotlistMissingBars": 0}

    should_exit, reason = TradeSimulator._ranktrend_early_big_move_v2_exit_decision(
        signal,
        pos,
        gross_return=0.18,
        config={"maxHoldingBars": 40, "stopLoss": -0.05, "takeProfit": 0.05},
    )

    assert should_exit is False
    assert reason is None


def test_early_big_move_v2_exit_requires_large_rank_drop_and_macd_death() -> None:
    signal = _early_big_move_v2_signal(macd_cross="death")
    signal["rankTrend"]["meta"] = {"rawChange": -55}
    pos = {"holdingBars": 8, "hotlistMissingBars": 0}

    should_exit, reason = TradeSimulator._ranktrend_early_big_move_v2_exit_decision(
        signal,
        pos,
        gross_return=0.02,
        config={"maxHoldingBars": 40, "stopLoss": -0.05},
    )

    assert should_exit is True
    assert reason == "排名大幅下降+MACD死叉"


def test_early_big_move_v2_exit_after_three_missing_hotlist_bars() -> None:
    should_exit, reason = TradeSimulator._ranktrend_early_big_move_v2_exit_decision(
        {},
        {"holdingBars": 8, "hotlistMissingBars": 3},
        gross_return=0.02,
        config={"maxHoldingBars": 40, "stopLoss": -0.05},
    )

    assert should_exit is True
    assert reason == "退出热榜连续3个bar"
