import pytest

from backend.analysis.theme.daily_series import (
    build_daily_series,
    virtual_index,
    ThemeDailySeries,
)


def _sector(ts, date, slot, key="BKAI", change=0.02, zt=3, breadth=60.0,
            inflow=1.0, amount_ratio=0.05):
    return {
        "timestamp": ts, "tradingDate": date, "slotTime": slot,
        "entityKey": key, "themeId": key, "themeName": "人工智能",
        "entityType": "hot_theme", "change": change, "ztCount": zt,
        "breadthScore": breadth, "mainNetInflow": inflow,
        "volumeRatio": 1.5, "metadata": {"amountRatio": amount_ratio},
    }


def test_build_daily_series_groups_by_date_and_takes_close_slot_change():
    rows = [
        _sector(1000, "2026-08-03", "15:00", change=0.01, zt=2),
        _sector(2000, "2026-08-04", "10:30", change=0.03, zt=3),
        _sector(3000, "2026-08-04", "15:00", change=0.05, zt=5),  # 收盘槽
    ]
    series = build_daily_series(rows, [])
    assert set(series.keys()) == {"BKAI"}
    daily = series["BKAI"]
    assert [d["date"] for d in daily] == ["2026-08-03", "2026-08-04"]
    # 收盘槽 change 是日收益
    assert [d["change"] for d in daily] == [0.01, 0.05]
    # 收盘槽 ztCount 是日涨停数
    assert [d["ztCount"] for d in daily] == [2, 5]


def test_virtual_index_compounds_daily_changes():
    series = ThemeDailySeries(
        theme_id="BKAI", theme_name="人工智能",
        dates=["2026-08-03", "2026-08-04", "2026-08-05"],
        changes=[0.01, 0.05, -0.02],
        zt_counts=[2, 5, 3], breadths=[50.0, 60.0, 55.0],
        inflows=[1.0, 2.0, -0.5], amount_ratios=[0.04, 0.05, 0.06],
        quality_flags=[],
    )
    idx = virtual_index(series.changes)
    assert idx[0] == pytest.approx(1.01)
    assert idx[1] == pytest.approx(1.01 * 1.05)
    assert idx[2] == pytest.approx(1.01 * 1.05 * 0.98)


def test_build_daily_series_missing_close_slot_uses_last_slot_and_flags():
    rows = [_sector(1000, "2026-08-04", "10:30", change=0.03, zt=3)]
    series = build_daily_series(rows, [])
    daily = series["BKAI"]
    assert daily[-1]["change"] == 0.03  # 无收盘槽回退最后一槽
    assert "close_slot_missing" in daily[-1]["qualityFlags"]


def test_build_daily_series_amount_ratio_fallback():
    # 无 metadata.amountRatio 时资金量能维度降级标记
    row = _sector(1000, "2026-08-04", "15:00")
    row.pop("metadata")
    series = build_daily_series([row], [])
    assert "amount_ratio_missing" in series["BKAI"][-1]["qualityFlags"]
