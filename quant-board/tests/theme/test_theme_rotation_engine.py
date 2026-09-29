from backend.analysis.theme.rotation.config import ThemeRotationConfig
from backend.analysis.theme.rotation.engine import ThemeRotationEngine
from backend.analysis.theme.rotation.models import HistorySlot


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
        _sector("BKAI", "人工智能", 1, 85.0, momentum=80, crowding=40, inflow=3.0, zt=8),
        _sector("BKAG", "机器人", 2, 45.0, momentum=45, inflow=-1.0, zt=1),
    ]
    stocks = [
        _stock("600001", 8, "涨停", ["BKAI"]),
        _stock("600002", 2, "", ["BKAG"]),
    ]
    result = engine.compute(current, _history(), stocks, indices={}, computed_at=3000)
    by_key = {s.theme_id: s for s in result.statuses}
    assert by_key["BKAI"].lifecycle is None  # D5：状态机废弃
    assert by_key["BKAI"].rotation_state == "mainline"
    assert by_key["BKAI"].mainline_concentration_rank == 1
    assert by_key["BKAG"].rotation_state == "outflow"  # 动量 45、资金负 → outflow
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


def test_market_inflow_outflow_carry_theme_names():
    # R1：inflow/outflow 输出对象（themeId + themeName），前端列表不再显示裸代码
    engine = ThemeRotationEngine()
    history = [
        HistorySlot(
            timestamp_ms=1000 + i * 1000,
            trading_date="2026-08-04",
            sector_rows=[
                _sector("BKAI", "人工智能", 1, 70.0, inflow=1.0),
                _sector("BKAG", "机器人", 2, 60.0, inflow=0.8),
                _sector("BKAH", "低空经济", 3, 55.0, inflow=0.5),
                _sector("BKAJ", "数据要素", 4, 50.0, inflow=0.3),
                _sector("BKAK", "退潮题材", 5, 45.0, momentum=30, inflow=-0.5),
            ],
        )
        for i in range(2)
    ]
    current = [
        _sector("BKAI", "人工智能", 1, 85.0, momentum=80, crowding=70, inflow=3.0, zt=8),
        _sector("BKAG", "机器人", 2, 75.0, momentum=70, inflow=1.5, zt=6),
        _sector("BKAH", "低空经济", 3, 65.0, momentum=60, inflow=0.5, zt=3),
        _sector("BKAJ", "数据要素", 4, 62.0, momentum=60, inflow=0.2, zt=2),
        _sector("BKAK", "退潮题材", 5, 55.0, momentum=30, inflow=-1.0, zt=1),
    ]
    stocks = [
        _stock("600001", 8, "涨停", ["BKAI"]),
        _stock("600002", 2, "", ["BKAG"]),
        _stock("600003", 2, "", ["BKAH"]),
        _stock("600004", 2, "", ["BKAJ"]),
        _stock("600005", 2, "", ["BKAK"]),
    ]
    result = engine.compute(current, history, stocks, computed_at=3000)
    by_key = {s.theme_id: s for s in result.statuses}
    assert by_key["BKAJ"].rotation_state == "inflow"  # 动量 60 强 → inflow
    assert by_key["BKAK"].rotation_state == "outflow"  # 动量 30 弱 → outflow
    inflow = result.market.inflow_themes
    outflow = result.market.outflow_themes
    for item in [*inflow, *outflow]:
        assert isinstance(item, dict)
        assert item.get("themeId")
        assert item.get("themeName")
    assert any(item["themeId"] == "BKAJ" and item["themeName"] == "数据要素" for item in inflow)
    assert any(item["themeId"] == "BKAK" and item["themeName"] == "退潮题材" for item in outflow)


def test_engine_missing_heat_not_fabricated_into_mainline_z_rank():
    # heatLevel 迁移审计修复：热度缺失（显式 None 的 v2 行）不伪造 0 参与主线 z-score。
    # 旧行为 robust_z(0.0, []) 恒 0.0，并列排序会让任一题材凭 z_rank=1 进主线候选；
    # 新行为缺失题材不进 heat_zs（z_rank 兜底 999），全市场热度缺失时不得凭空评主线。
    engine = ThemeRotationEngine()
    caliber = {"metadata": {"factorVersion": "theme-market-v2"}}
    current = [
        {**_sector("BKAI", "人工智能", 1, 99999.0, momentum=80, crowding=40, inflow=5.0, zt=8),
         "heatLevel": None, **caliber},
        {**_sector("BKAG", "机器人", 2, 88888.0, momentum=70, crowding=40, inflow=4.0, zt=6),
         "heatLevel": None, **caliber},
    ]
    stocks = [
        _stock("600001", 8, "涨停", ["BKAI"]),
        _stock("600002", 2, "", ["BKAG"]),
    ]
    result = engine.compute(current, _history(), stocks, computed_at=3000)
    by_key = {s.theme_id: s for s in result.statuses}
    assert by_key["BKAI"].rotation_state != "mainline"
    assert by_key["BKAG"].rotation_state != "mainline"


def test_engine_stock_theme_label_normalization_matches_chinese_names():
    # R6：真实 stock rows 的 themes 是中文名（可能带“概念/板块”后缀），
    # 与 sector entityName 归一化后应正确归集主题内股票（boardHeight 不再缺失）
    engine = ThemeRotationEngine()
    current = [_sector("BKAI", "人工智能", 1, 60.0, momentum=55)]
    stocks = [_stock("600001", 5, "涨停", ["人工智能概念板块"])]
    result = engine.compute(current, _history(), stocks, computed_at=3000)
    assert "boardHeight" not in result.statuses[0].quality_flags
