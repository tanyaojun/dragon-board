# quant-board/tests/test_theme_rotation_direction_labels.py
"""rotationState 收敛为 4 个方向标签；lifecycle 状态机废弃（spec D5/D10）。"""
from backend.analysis.theme.rotation.config import ThemeRotationConfig
from backend.analysis.theme.rotation.engine import ThemeRotationEngine
from backend.analysis.theme.rotation.lifecycle import rotation_state_for
from backend.analysis.theme.rotation.models import HistorySlot


def _slot(ts, key, heat, momentum, inflow, rank, crowding=40.0, zt=0):
    return {
        "timestamp": ts, "tradingDate": "2026-08-04", "slotTime": f"s{ts}",
        "entityKey": key, "themeId": key, "themeName": key, "entityType": "hot_theme",
        "heatScore": heat, "momentumScore": momentum, "mainNetInflow": inflow,
        "crowdingRisk": crowding, "rank": rank, "ztCount": zt,
        "volumeRatio": 1.2, "breadthScore": 60.0,
    }


def _history(rows):
    return [
        HistorySlot(timestamp_ms=row["timestamp"], trading_date="2026-08-04", sector_rows=[row])
        for row in rows
    ]


def _stock(code, board_height=1):
    return {"code": code, "boardHeight": board_height, "themes": ["BKAI"]}


def test_rotation_state_values_are_direction_labels_only():
    cfg = ThemeRotationConfig()
    engine = ThemeRotationEngine(cfg)
    history = _history([
        _slot(1000 + i * 100, "BKAI", 60 + i, 55 + i, 1.0, 1)
        for i in range(8)
    ])
    current = [_slot(999999, "BKAI", 80, 78, 2.0, 1, crowding=40.0)]
    result = engine.compute(
        current, history, [], indices=None, computed_at=999999,
        trading_date="2026-08-04",
    )
    status = next(s for s in result.statuses if s.theme_id == "BKAI")
    assert status.rotation_state in {"mainline", "inflow", "outflow", "neutral"}
    # lifecycle 状态机废弃：不再产出 ice/emerging/expanding/climax/cooling
    assert status.lifecycle is None


def test_rotation_state_outflow_when_momentum_down_and_inflow_negative():
    cfg = ThemeRotationConfig()
    engine = ThemeRotationEngine(cfg)
    history = _history([
        _slot(1000 + i * 100, "BKAI", 40, 35, -1.0, 5) for i in range(8)
    ])
    current = [_slot(999999, "BKAI", 38, 32, -2.0, 5, crowding=50.0)]
    result = engine.compute(current, history, [], indices=None, computed_at=999999,
                            trading_date="2026-08-04")
    status = next(s for s in result.statuses if s.theme_id == "BKAI")
    assert status.rotation_state == "outflow"
    assert status.lifecycle is None


def test_lifecycle_field_always_none_in_output():
    cfg = ThemeRotationConfig()
    engine = ThemeRotationEngine(cfg)
    history = _history([
        _slot(1000 + i * 100, "BKAI", 60, 55, 1.0, 1) for i in range(8)
    ])
    current = [_slot(999999, "BKAI", 80, 78, 2.0, 1)]
    result = engine.compute(current, history, [], indices=None, computed_at=999999,
                            trading_date="2026-08-04")
    for s in result.statuses:
        assert s.lifecycle is None


def test_rotation_state_for_direction_labels():
    # mainline：动量强 + 资金流入 + 不拥挤
    assert rotation_state_for(78.0, True, True, 40.0) == "mainline"
    # 拥挤阻断主线
    assert rotation_state_for(78.0, True, True, 75.0) != "mainline"
    # 动量强 → inflow
    assert rotation_state_for(60.0, False, False, 40.0) == "inflow"
    # 动量弱 → outflow
    assert rotation_state_for(40.0, True, False, 40.0) == "outflow"
    # 中性动量 + 资金流入 → inflow
    assert rotation_state_for(50.0, True, False, 40.0) == "inflow"
    # 中性动量 + 资金流出 → neutral
    assert rotation_state_for(50.0, False, False, 40.0) == "neutral"
