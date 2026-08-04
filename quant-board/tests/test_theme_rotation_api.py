from fastapi.testclient import TestClient

from backend.main import app


class FakeFrameDb:
    def __init__(self, frames, sectors):
        self._frames = frames
        self._sectors = sectors

    def __getitem__(self, name):
        if name == "snapshot_frames":
            return _FakeFrameCollection(self._frames)
        if name == "snapshot_sector_rows":
            return _FakeSectorCollection(self._sectors)
        raise KeyError(name)


class _FakeFrameCollection:
    def __init__(self, frames):
        self._frames = frames

    def find_one(self, query, sort=None):
        # M6：仅当查询要求 algorithmVersion 且存在帧时返回
        if "rotationSummary.algorithmVersion" not in query:
            return None
        return self._frames[0] if self._frames else None


class _FakeSectorCollection:
    def __init__(self, rows):
        self._rows = rows

    def find(self, query):
        return self

    def sort(self, key_or_list):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


def _patch_db(monkeypatch, frames, sectors):
    import backend.api.theme_rotation_routes as routes
    monkeypatch.setattr(routes, "get_runtime_mongodb_database", lambda: FakeFrameDb(frames, sectors))


def test_theme_rotation_summary_missing_returns_404(monkeypatch):
    _patch_db(monkeypatch, [], [])
    client = TestClient(app)
    resp = client.get(
        "/api/theme-rotation/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour",
                "trading_date": "1999-01-01"},
    )
    assert resp.status_code == 404


def test_theme_rotation_summary_envelope_shape(monkeypatch):
    _patch_db(
        monkeypatch,
        frames=[{
            "snapshotId": "half_hour:2026-08-04:15:00",
            "tradingDate": "2026-08-04",
            "slotTime": "15:00",
            "timestamp": 1000,
            "rotationSummary": {
                "marketPhase": "rising",
                "mainLines": [],
                "algorithmVersion": "theme_rotation_v2",
            },
        }],
        sectors=[{
            "themeId": "BKAI", "themeName": "人工智能", "rank": 1,
            "rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0,
        }],
    )
    client = TestClient(app)
    resp = client.get(
        "/api/theme-rotation/summary",
        params={"dataset_id": "dragonboard_live", "snapshot_type": "half_hour",
                "trading_date": "2026-08-04"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["frame"]["rotationSummary"]["marketPhase"] == "rising"
    assert data["statuses"][0]["rotationState"] == "mainline"
