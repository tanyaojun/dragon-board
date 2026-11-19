from fastapi.testclient import TestClient

from backend.main import app


class FakeFrameDb:
    def __init__(self, frames, sectors):
        # 2026-11-19 起 sector rows 内嵌在帧文档 sectorRows（独立集合已 drop）
        self._frames = [
            {**frame, "sectorRows": sectors}
            for frame in frames
        ]

    def __getitem__(self, name):
        if name == "snapshot_frames":
            return _FakeFrameCollection(self._frames)
        raise KeyError(name)


class _FakeFrameCollection:
    def __init__(self, frames):
        self._frames = frames

    def find_one(self, query, projection=None, sort=None):
        # rotationSummary 门控：仅当查询要求 algorithmVersion 且存在帧时返回；
        # sector rows 回放查询（datasetId+snapshotId）按匹配返回。
        if "rotationSummary.algorithmVersion" in query:
            return self._frames[0] if self._frames else None
        matches = [
            frame for frame in self._frames
            if all(frame.get(key) == value for key, value in (query or {}).items())
        ]
        return matches[0] if matches else None


def _patch_db(monkeypatch, frames, sectors):
    import backend.api.theme_rotation_routes as routes
    # 帧文档须带 datasetId（sector_rows_by_snapshot 按 datasetId+snapshotId 查帧）
    frames = [{**frame, "datasetId": "dragonboard_live"} for frame in frames]
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
            "entityType": "hot_theme", "themeId": "BKAI", "themeName": "人工智能", "rank": 1,
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


class FakeCache:
    def __init__(self):
        self.store: dict[str, dict] = {}
        self.deps: tuple[str, list] | None = None

    def get_response(self, key):
        return self.store.get(key)

    def set_response(self, key, response, ttl_seconds=None):
        self.store[key] = response

    def register_dependencies(self, key, index_keys):
        self.deps = (key, index_keys)


def test_theme_rotation_summary_reads_through_redis_cache(monkeypatch):
    calls = {"count": 0}

    class CountingFrameDb(FakeFrameDb):
        def __getitem__(self, name):
            if name == "snapshot_frames":
                return _CountingFrameCollection(self._frames, calls)
            return super().__getitem__(name)

    class _CountingFrameCollection(_FakeFrameCollection):
        def __init__(self, frames, counter):
            super().__init__(frames)
            self._counter = counter

        def find_one(self, query, sort=None):
            self._counter["count"] += 1
            return super().find_one(query, sort)

    import backend.api.theme_rotation_routes as routes
    from backend.data.cache import snapshot_cache

    frames = [{
        "snapshotId": "half_hour:2026-08-04:15:00",
        "tradingDate": "2026-08-04",
        "slotTime": "15:00",
        "timestamp": 1000,
        "rotationSummary": {
            "marketPhase": "rising",
            "mainLines": [],
            "algorithmVersion": "theme_rotation_v2",
        },
        "sectorRows": [{
            "entityType": "hot_theme", "themeId": "BKAI", "themeName": "人工智能", "rank": 1,
            "rotationState": "mainline", "lifecycle": "expanding", "rotationScore": 78.0,
        }],
    }]
    monkeypatch.setattr(
        routes,
        "get_runtime_mongodb_database",
        lambda: CountingFrameDb(frames, []),
    )
    fake_cache = FakeCache()
    monkeypatch.setattr(routes.snapshot_cache, "get_snapshot_redis_cache", lambda: fake_cache)

    client = TestClient(app)
    params = {"dataset_id": "dragonboard_live", "snapshot_type": "half_hour",
              "trading_date": "2026-08-04"}
    first = client.get("/api/theme-rotation/summary", params=params)
    second = client.get("/api/theme-rotation/summary", params=params)
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()
    # 第二次命中 Redis read-through：仍为 2 次 find_one（latest frame + sector rows），
    # 不再随请求次数增长（2026-11-19 起 sector rows 改从帧内嵌读取，也走 find_one）
    assert calls["count"] == 2
    assert fake_cache.deps is not None
    assert any("index" in key for key in fake_cache.deps[1])