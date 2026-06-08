from backend.analysis import ranktrend
from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.services import GoldenService


def _make_frames(include_hotlist_sentiment: bool = False) -> list[dict]:
    frames = [
        {
            "snapshotId": f"s{i}",
            "type": "half_hour",
            "timestamp": i,
            "tradingDate": "2026-06-05",
            "slotTime": "10:00",
            "marketContext": {
                "payload": {
                    "sentiment": {"phaseName": "发酵期"},
                    "marketData": {"ztCount": 42, "dtCount": 1, "upCount": 3200, "downCount": 900},
                }
            },
            "stocks": [
                {
                    "code": "000001",
                    "name": "样本",
                    "rank": max(1, 30 - i * 3),
                    "change": 1.5,
                    "volumeRatio": 1.8,
                    "zlje": 1200,
                    "zljzb": 1.2,
                }
            ],
        }
        for i in range(8)
    ]
    if include_hotlist_sentiment:
        for frame in frames:
            frame["hotlistSentiment"] = {"stage": "冰点", "riskLevel": "高", "confidence": 95}
    return frames


def test_golden_replay_uses_pure_analysis_candidate_tier_without_hotlist(monkeypatch) -> None:
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    frames = _make_frames()

    monkeypatch.setattr(
        ranktrend,
        "compose_strategy",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("golden replay should not call compose_strategy")),
    )

    signals = engine.replay(frames, meta={"sampleQuality": "ok"})

    assert signals
    strategy = signals[-1]["rankTrend"]["strategy"]
    assert strategy["regime"]["state"] == "strong"
    assert "hotlist" not in strategy
    assert all("热榜情绪" not in reason for reason in strategy["reasons"])
    assert all("hotlistSentiment" not in frame for frame in frames)
    assert all("hotlistSentimentStatus" not in frame for frame in frames)
    assert all("hotlistSentimentReason" not in frame for frame in frames)
    assert signals[-1]["candidateTier"] == strategy["candidateTier"]


def test_golden_replay_ignores_preexisting_hotlist_sentiment_payload() -> None:
    engine = RankTrendPythonEngine(RankTrendConfig.from_patch({"minSampleCount": 3}))
    baseline_frames = _make_frames()
    frames = _make_frames(include_hotlist_sentiment=True)
    baseline_signals = engine.replay(
        baseline_frames,
        meta={"datasetId": "dragonboard_live", "snapshotType": "half_hour", "sampleQuality": "ok"},
    )

    signals = engine.replay(
        frames,
        meta={"datasetId": "dragonboard_live", "snapshotType": "half_hour", "sampleQuality": "ok"},
    )

    assert baseline_signals
    assert signals
    baseline_strategy = baseline_signals[-1]["rankTrend"]["strategy"]
    strategy = signals[-1]["rankTrend"]["strategy"]
    assert strategy["regime"]["state"] == "strong"
    assert "hotlist" not in strategy
    assert all("热榜情绪" not in reason for reason in strategy["reasons"])
    assert signals[-1]["candidateTier"] == baseline_signals[-1]["candidateTier"]
    assert signals[-1]["action"] == baseline_signals[-1]["action"]
    assert strategy["candidateTier"] == baseline_strategy["candidateTier"]
    assert strategy["action"] == baseline_strategy["action"]
    assert all(frame.get("hotlistSentiment", {}).get("stage") == "冰点" for frame in frames)
    assert all("hotlistSentimentStatus" not in frame for frame in frames)
    assert all("hotlistSentimentReason" not in frame for frame in frames)


def test_build_signal_runs_risk_aware_analysis_order(monkeypatch) -> None:
    engine = RankTrendPythonEngine(RankTrendConfig())
    order: list[str] = []

    monkeypatch.setattr(
        ranktrend,
        "analyze_technical",
        lambda percentiles, config, fallback: order.append("technical")
        or {
            "signals": {
                "direction": {"signal": "buy", "score": 1},
                "acceleration": {"signal": "buy", "score": 1},
                "zeroCross": {"signal": "hold", "score": 0},
            },
            "macd": {"cross": "golden", "rawScore": 1, "histogram": 0.2},
            "momentumProfile": {"short": 6, "mid": 5, "long": 4, "acceleration": 2},
        },
    )
    monkeypatch.setattr(ranktrend, "detect_rank_jumps", lambda *args, **kwargs: {"hasJump": False, "events": []})
    monkeypatch.setattr(
        ranktrend,
        "analyze_cycle",
        lambda ranks, percentiles: order.append("cycle")
        or {
            "rawStage": "expansion",
            "stage": "expansion",
            "transition": "ignition->expansion",
            "confidence": 78,
            "metrics": {
                "rankVelocity": 12,
                "rankAcceleration": 6,
                "drawdownFromPeak": 0,
                "hotZoneStreak": 1,
                "rankPathCommitment": 0.82,
            },
            "decision": {"action": "allow", "reasons": ["initial"]},
        },
    )
    monkeypatch.setattr(
        ranktrend,
        "analyze_risk",
        lambda current_percentile, technical, cycle, zlje, zljzb, volume_ratio: order.append("risk")
        or {
            "pressure": 0.2,
            "divergence": {"severity": 0.1},
            "overheat": {"severity": 0.1},
            "synergy": 0,
        },
    )
    monkeypatch.setattr(
        ranktrend,
        "analyze_cycle_with_risk",
        lambda cycle, risk, momentum: order.append("cycle_with_risk")
        or {
            **cycle,
            "decision": {"action": "allow", "reasons": ["risk aware"]},
        },
    )
    monkeypatch.setattr(
        ranktrend,
        "compose_decision",
        lambda technical, cycle, risk, config: order.append("decision")
        or {
            "base": {"signal": "buy", "confidence": 80, "combinedScore": 0.5, "scoreMargin": 0.3},
            "final": {"signal": "buy", "confidence": 82},
        },
    )
    monkeypatch.setattr(
        ranktrend,
        "compose_analysis_candidate_tier",
        lambda technical, cycle, risk, regime: order.append("strategy")
        or {
            "regime": regime,
            "momentum": technical["momentumProfile"],
            "candidateTier": "A_MAIN",
            "action": "focus",
            "reasons": ["analysis only"],
        },
    )

    signal = engine._build_signal(
        {
            "code": "000001",
            "name": "样本",
            "change": 1.5,
            "volumeRatio": 1.8,
            "zlje": 1200,
            "zljzb": 1.2,
        },
        {"snapshotId": "s7", "timestamp": 7, "tradingDate": "2026-06-05", "slotTime": "10:00", "type": "half_hour"},
        [30, 24, 18, 12],
        [25, 40, 55, 78],
        {"state": "strong", "score": 82, "reasons": ["strong regime"]},
        {"sampleQuality": "ok"},
    )

    assert signal is not None
    assert order.index("technical") < order.index("cycle") < order.index("risk")
    assert order.index("risk") < order.index("cycle_with_risk") < order.index("decision") < order.index("strategy")


def test_compose_decision_does_not_add_implicit_macd_buy_gate() -> None:
    config = RankTrendConfig.from_patch(
        {
            "momentumPeriods": [3, 5, 8, 13, 21],
            "momentumWeights": [0.15, 0.2, 0.25, 0.25, 0.15],
            "buyThresholds": [5, 8, 13, 21, 34],
            "sellThresholds": [-5, -8, -13, -21, -34],
            "macdFast": 13,
            "macdSlow": 21,
            "macdSignal": 8,
            "directionWeight": 0.3,
            "accelerationWeight": 0.25,
            "crossWeight": 0.2,
            "macdWeight": 0.25,
            "buyScoreThreshold": 0.12,
            "sellScoreThreshold": -0.12,
        }
    )

    decision = ranktrend.compose_decision(
        technical={
            "signals": {
                "direction": {"signal": "buy", "score": 0.5719578382696798},
                "acceleration": {"signal": "buy", "score": 0.4179498301302663},
                "zeroCross": {"signal": "hold", "score": 0},
            },
            "macd": {"cross": "none", "rawScore": 0},
        },
        cycle={"stage": "crowded"},
        risk={
            "pressure": 0,
            "divergence": {"severity": 0},
            "overheat": {"severity": 0},
            "synergy": 0,
        },
        config=config,
    )

    assert config.requireMacdGoldenCross is False
    assert decision["base"]["signal"] == "buy"
    assert decision["final"]["signal"] == "buy"


def test_compose_analysis_candidate_tier_keeps_ts_veto_and_regime_contract() -> None:
    strategy = ranktrend.compose_analysis_candidate_tier(
        technical={
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "buy"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "golden"},
            "momentumProfile": {"short": 8, "mid": 6, "long": 4, "acceleration": 2},
        },
        cycle={
            "stage": "expansion",
            "decision": {"action": "veto", "reasons": ["veto"]},
        },
        risk={
            "pressure": 0.12,
            "divergence": {"severity": 0.08},
            "overheat": {"severity": 0.11},
        },
        regime={"state": "strong", "score": 88, "reasons": ["strong regime"]},
    )

    assert strategy["regime"]["state"] == "strong"
    assert "marketRegime" not in strategy
    assert strategy["candidateTier"] == "N_NEUTRAL"
    assert strategy["action"] == "hold"
    assert "生命周期辅助决策一票否决，阻止进入 A/B 候选池" in strategy["reasons"]
    assert "市场环境强，允许跟踪点火/扩散机会" in strategy["reasons"]


def test_compose_analysis_candidate_tier_matches_ts_weak_market_downgrade() -> None:
    strategy = ranktrend.compose_analysis_candidate_tier(
        technical={
            "signals": {
                "direction": {"signal": "buy"},
                "acceleration": {"signal": "hold"},
                "zeroCross": {"signal": "hold"},
            },
            "macd": {"cross": "none"},
            "momentumProfile": {"short": 5, "mid": 5, "long": 2, "acceleration": 1},
        },
        cycle={
            "stage": "expansion",
            "decision": {"action": "allow", "reasons": ["allow"]},
        },
        risk={
            "pressure": 0.2,
            "divergence": {"severity": 0.1},
            "overheat": {"severity": 0.1},
        },
        regime={"state": "retreat", "score": 22, "reasons": ["retreat regime"]},
    )

    assert strategy["candidateTier"] == "N_NEUTRAL"
    assert strategy["action"] == "hold"
    assert "弱势/退潮环境下买入信号降级为观察" in strategy["reasons"]
    assert "市场退潮，优先控制回撤风险" in strategy["reasons"]


def test_golden_service_normalizes_cycle_and_decision_summary() -> None:
    normalized = GoldenService._normalize_expected_payload(
        [
            {
                "snapshotId": "half_hour:2026-06-06:11:00",
                "code": "000001",
                "candidateTier": "A_MAIN",
                "action": "focus",
                "stage": "expansion",
                "regime": "strong",
                "rank": 44,
                "confidence": 78.2,
                "rankTrend": {
                    "technical": {
                        "signals": {"direction": {"signal": "buy"}},
                        "momentumProfile": {"short": 5.0, "mid": 4.5, "long": 2.0, "acceleration": 1.2},
                    },
                    "cycle": {
                        "transition": "ignition->expansion",
                        "entryAdvice": {"bias": "preferred"},
                        "decision": {"action": "allow", "confidence": 73.0},
                    },
                    "risk": {"pressure": 0.12, "divergence": {"severity": 0.08}, "overheat": {"severity": 0.11}},
                    "decision": {
                        "base": {"signal": "buy", "confidence": 82.5},
                        "final": {"signal": "buy", "confidence": 78.2},
                    },
                },
            }
        ]
    )

    row = normalized[0]
    assert row["cycle"]["transition"] == "ignition->expansion"
    assert row["cycle"]["entryAdvice"]["bias"] == "preferred"
    assert row["cycle"]["decision"]["action"] == "allow"
    assert row["decision"]["final"]["confidence"] == 78.2


def test_golden_service_compare_reports_nested_cycle_path() -> None:
    expected = [{"cycle": {"transition": "ignition->expansion"}}]
    actual = [{"cycle": {"transition": "expansion->crowded"}}]

    issues = GoldenService._compare(expected, actual, tolerance=1e-6, strict=True)

    assert issues == ["$[0].cycle.transition: expected 'ignition->expansion' actual 'expansion->crowded'"]
