from backend.analysis.theme.rotation.history import RotationHistoryService


class FakeRepo:
    def __init__(self, sector_rows, stock_rows):
        self._sector = sector_rows
        self._stock = stock_rows

    def list_snapshot_sector_rows(self, dataset_id, snapshot_type, start_date=None, end_date=None,
                                  entity_type=None, sort="asc", limit=None):
        return {"rows": self._sector, "source": "fake"}

    def list_snapshot_stock_rows(self, dataset_id, snapshot_type, trading_date=None, slot_time=None,
                                 start_date=None, end_date=None, sort="asc", limit=None):
        rows = self._stock
        if slot_time:
            rows = [row for row in rows if row.get("slotTime") == slot_time]
        return {"rows": rows, "source": "fake"}


def _sector(ts, key="BKAI", heat=60):
    return {"timestamp": ts, "slotTime": f"slot{ts}", "tradingDate": "2026-08-04", "entityKey": key,
            "entityType": "hot_theme", "themeId": key, "heatScore": heat, "rank": 1}


def _stock(ts, code="600001"):
    return {"timestamp": ts, "slotTime": f"slot{ts}", "tradingDate": "2026-08-04", "code": code, "boardHeight": 3}


def test_load_filters_current_and_orders():
    repo = FakeRepo(
        [_sector(1000), _sector(2000), _sector(3000)],
        [_stock(1000), _stock(2000)],
    )
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 3000, window=8)
    assert [s.timestamp_ms for s in history.slots] == [1000, 2000]
    assert history.slots[0].stock_rows is None
    assert history.slots[1].stock_rows == [_stock(2000)]


def test_load_window_caps_slots():
    repo = FakeRepo([_sector(1000 + i * 100) for i in range(12)], [])
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 999999, window=4)
    assert len(history.slots) == 4


def test_load_no_history():
    repo = FakeRepo([], [])
    svc = RotationHistoryService(repo, previous_trading_day_fn=lambda date: "2026-08-03")
    history = svc.load("dragonboard_live", "half_hour", "2026-08-04", 3000)
    assert history.slots == []
