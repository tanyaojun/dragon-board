from __future__ import annotations

from backend.analysis.ranktrend.trend.risk import market_regime


def _frame(status: str | None) -> dict:
    # stocks 非空：market_regime 内部按 stocks 计算宽度/中位数，空表会触发与被测逻辑无关的退化分支
    frame: dict = {"stocks": [{"code": "000001", "rank": 1, "change": 5.0}], "hotlistSentiment": None}
    if status:
        frame["hotlistSentimentStatus"] = status
    return frame


def test_stale_appends_reason_without_score_change():
    base = market_regime(_frame(None))
    stale = market_regime(_frame("stale"))
    assert base["score"] == stale["score"]
    assert base["state"] == stale["state"]
    assert any("stale" in str(reason) for reason in stale["reasons"])
    assert not any("stale" in str(reason) for reason in base["reasons"])


def test_ok_and_missing_do_not_add_reason():
    for status in ("ok", "missing", None):
        reasons = market_regime(_frame(status))["reasons"]
        assert not any("stale" in str(reason) for reason in reasons)
