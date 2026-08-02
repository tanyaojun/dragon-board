from backend.analysis.ranktrend import analyze_rank_resonance


def _jump(direction="hold", events=None):
    return {"direction": direction, "event": "jump" if events else "none", "events": events or []}


def test_established_buy_resonance():
    percentiles = [20, 22, 25, 28, 32, 37, 43, 50, 58, 67]
    result = analyze_rank_resonance({
        "percentiles": percentiles,
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 5.0,
        "marketSampleCount": 200,
        "jump": _jump("buy", [{"index": 7, "direction": "surge", "magnitude": 20}]),
    })
    assert result["status"] == "ok"
    assert result["direction"] == "buy"
    assert result["historyState"] == "established"
    assert result["marketMedianShortChange"] == 5.0


def test_insufficient_when_market_sample_low():
    result = analyze_rank_resonance({
        "percentiles": [20, 22, 25, 28, 32, 37, 43, 50, 58, 67],
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 5.0,
        "marketSampleCount": 5,
        "jump": _jump(),
    })
    assert result["status"] == "insufficient"
    assert result["score"] == 0


def test_new_entry_path():
    result = analyze_rank_resonance({
        "percentiles": [95.2],
        "sampleQuality": {"status": "ok", "timelineValid": True},
        "marketMedianShortChange": 1.0,
        "marketSampleCount": 200,
        "jump": _jump("buy", [{"index": 0, "direction": "surge", "magnitude": 10}]),
        "entry": {"isNew": True, "currentAttentionPercentile": 95.2},
    })
    assert result["status"] == "ok"
    assert result["historyState"] == "new_entry"
    assert result["direction"] == "buy"
