from backend.analysis.theme_rotation.config import ThemeRotationConfig
from backend.analysis.theme_rotation.engine import ThemeRotationEngine
from backend.analysis.theme_rotation.models import HistorySlot


def _sector(theme_id, name, rank, heat, momentum=60, crowding=50, inflow=1.0, zt=3, change=2.0, breadth=60):
    return {
        "themeId": theme_id, "themeName": name, "entityKey": theme_id, "rank": rank,
        "heatScore": heat, "momentumScore": momentum, "crowdingRisk": crowding,
        "mainNetInflow": inflow, "positiveInflowStreak": 2, "negativeInflowStreak": 0,
        "ztCount": zt, "change": change, "breadthScore": breadth, "maxBoardHeight": 2,
    }


def _stock(code, board_height, lead_status, themes, change=9.6):
    return {"code": code, "boardHeight": board_height, "leadStatus": lead_status,
            "themes": themes, "change": change}


def _history(timestamps=(1000, 2000), heat=50.0):
    return [
        HistorySlot(
            timestamp_ms=ts,
            trading_date="2026-08-04",
            sector_rows=[
                _sector("BKAI", "人工智能", 2, heat, inflow=1.0),
                _sector("BKAG", "机器人", 3, heat - 10, inflow=0.5),
            ],
        )
        for ts in timestamps
    ]


def test_engine_insufficient_history_no_state():
    engine = ThemeRotationEngine()
    result = engine.compute(
        [_sector("BKAI", "人工智能", 1, 80.0)],
        [],
        [],
        computed_at=3000,
    )
    assert result.statuses[0].rotation_state is None
    assert result.statuses[0].lifecycle is None
    assert any("insufficient_history" in q for q in result.quality_issues)


def test_engine_sufficient_history_mainline():
    engine = ThemeRotationEngine()
    current = [
        _sector("BKAI", "人工智能", 1, 85.0, momentum=80, crowding=70, inflow=3.0, zt=8),
        _sector("BKAG", "机器人", 2, 45.0, momentum=45, inflow=-1.0, zt=1),
    ]
    stocks = [
        _stock("600001", 8, "涨停", ["BKAI"]),
        _stock("600002", 2, "", ["BKAG"]),
    ]
    result = engine.compute(current, _history(), stocks, indices={}, computed_at=3000)
    by_key = {s.theme_id: s for s in result.statuses}
    assert by_key["BKAI"].lifecycle == "climax"
    assert by_key["BKAI"].rotation_state == "mainline"
    assert by_key["BKAI"].mainline_concentration_rank == 1
    assert by_key["BKAG"].rotation_state == "emerging"
    assert result.market.mainline_concentration is not None
    assert result.market.evidence["framesUsed"] == 3


def test_engine_rotation_score_present():
    engine = ThemeRotationEngine()
    result = engine.compute(
        [_sector("BKAI", "人工智能", 1, 80.0)],
        _history(),
        [_stock("600001", 3, "涨停", ["BKAI"])],
        indices={"sh000001": {"change": 1.0}},
        computed_at=3000,
    )
    assert result.statuses[0].rotation_score is not None
    assert result.market.rotation_speed == 8
    assert result.market.market_phase != "unknown"
