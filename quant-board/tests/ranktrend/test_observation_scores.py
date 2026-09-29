from backend.analysis.ranktrend.engine import compose_observation_scores
from backend.analysis.ranktrend.engine import RankTrendPythonEngine


def test_lifecycle_opportunity_weights():
    result = compose_observation_scores({
        "technical": {"momentumProfile": {"short": 15, "mid": 15, "acceleration": 8}},
        "cycle": {
            "stage": "expansion",
            "metrics": {"rankPathCommitment": 1.0},
            "decision": {"action": "allow", "reasons": []},
        },
        "risk": {"pressure": 0.0},
        "decision": {"base": {"signal": "buy", "combinedScore": 0.6}},
    })
    assert result["lifecycle"]["stage"] == "expansion"
    assert result["lifecycle"]["score"] == 100
    assert result["lifecycle"]["veto"] is False
    assert result["rankTrend"]["direction"] == "buy"
    assert result["rankTrend"]["score"] == 60


def test_veto_keeps_score_and_marks_reason():
    result = compose_observation_scores({
        "technical": {"momentumProfile": {"short": 0, "mid": 0, "acceleration": 0}},
        "cycle": {
            "stage": "crowded",
            "metrics": {"rankPathCommitment": 0.5},
            "decision": {"action": "veto", "reasons": ["生命周期进入反转路径"]},
        },
        "risk": {"pressure": 0.5},
        "decision": {"base": {"signal": "hold", "combinedScore": 0}},
    })
    assert result["lifecycle"]["veto"] is True
    assert result["lifecycle"]["reasons"] == ["生命周期进入反转路径"]


def test_replay_signal_contract_has_observation_and_both_strategies():
    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "stocks": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
        ],
        "marketContext": {"sentiment": {"phaseName": "启动"}, "marketStats": {}},
    }]
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert len(signals) == 2
    for signal in signals:
        rt = signal["rankTrend"]
        assert {"technical", "cycle", "risk", "decision", "observation", "strategy", "executionStrategy"} <= set(rt)
        assert "candidateTier" in rt["strategy"]
        assert "candidateTier" in rt["executionStrategy"]
        assert "regime" in rt["strategy"]


def test_replay_codes_filter_only_builds_requested_signals():
    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "stocks": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
        ],
        "marketContext": {"sentiment": {"phaseName": "启动"}, "marketStats": {}},
    }]
    engine = RankTrendPythonEngine()
    filtered = engine.replay(frames, warmup_count=1, codes=["002279"])
    assert [signal["code"] for signal in filtered] == ["002279"]
    all_signals = engine.replay(frames, warmup_count=1)
    assert {signal["code"] for signal in all_signals} == {"002279", "603580"}


def test_replay_excludes_stocks_without_valid_avg_rank_num():
    # 趋势核心因子是 avgRankNum 均榜百分位：avgRankNum 无效（<=0/缺失）的股票
    # 不进入趋势百分位序列（旧 TS attention 口径），综合排名只决定池子大小。
    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "stocks": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 0, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
        ],
        "marketContext": {"sentiment": {"phaseName": "启动"}, "marketStats": {}},
    }]
    engine = RankTrendPythonEngine()
    signals = engine.replay(frames, warmup_count=1)
    assert [signal["code"] for signal in signals] == ["002279"]
