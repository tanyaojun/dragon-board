from backend.analysis.ranktrend.engine import market_regime


def _frame(stocks, sentiment=None):
    return {
        "stocks": stocks,
        "marketContext": {
            "sentiment": sentiment or {"phaseName": "启动"},
        },
    }


def test_strong_pool_regime():
    frame = _frame(
        [
            {"change": 5.0, "volumeRatio": 1.6, "zlje": 100, "zljzb": 0.2},
            {"change": 10.0, "volumeRatio": 1.8, "zlje": 80, "zljzb": 0.1},
            {"change": -1.0, "volumeRatio": 0.9, "zlje": -20, "zljzb": -0.1},
            {"change": 3.0, "volumeRatio": 1.3, "zlje": 50, "zljzb": 0.05},
            {"change": 9.9, "volumeRatio": 2.0, "zlje": 120, "zljzb": 0.3},
        ],
        {"phaseName": "高潮期"},
    )
    result = market_regime(frame)
    assert result["state"] == "strong"
    assert any("池内上涨" in r for r in result["reasons"])
    assert any("池内涨停" in r for r in result["reasons"])


def test_weak_pool_regime_not_saved_by_full_market():
    # 全A 涨停数很高，但热榜池内部转弱：不能因为全A 给强环境
    frame = {
        "stocks": [
            {"change": -2.0, "volumeRatio": 0.8, "zlje": -10, "zljzb": -0.05},
            {"change": -3.0, "volumeRatio": 0.7, "zlje": -15, "zljzb": -0.08},
            {"change": -1.0, "volumeRatio": 0.9, "zlje": 0, "zljzb": 0.0},
            {"change": -4.0, "volumeRatio": 0.6, "zlje": -30, "zljzb": -0.2},
            {"change": 1.0, "volumeRatio": 1.0, "zlje": 5, "zljzb": 0.01},
        ],
        "marketContext": {
            "sentiment": {"phaseName": "退潮期"},
            "marketStats": {"ztCount": 120, "dtCount": 1, "upCount": 3000, "downCount": 1800, "totalAmo": 1.5e12},
        },
    }
    result = market_regime(frame)
    assert result["state"] in ("weak", "retreat")
    assert "涨停120" not in result["reasons"]


def test_pool_share_factors_are_used():
    frame = _frame(
        [
            {"change": 2.0, "volumeRatio": 1.5, "zlje": 100, "zljzb": 0.2},
            {"change": -1.0, "volumeRatio": 0.8, "zlje": -10, "zljzb": -0.1},
        ]
    )
    result = market_regime(frame)
    assert any("热榜资金正向" in r for r in result["reasons"])
    assert any("量能活跃" in r for r in result["reasons"])


def test_no_stocks_returns_neutral_with_reason():
    result = market_regime({"stocks": [], "marketContext": {}})
    assert result["state"] == "normal"
    assert result["score"] == 50
    assert result["reasons"]
