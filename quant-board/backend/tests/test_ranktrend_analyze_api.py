from fastapi.testclient import TestClient

from backend.main import app


client = TestClient(app)


class FakeRepo:
    def __init__(self, frames):
        self.frames = frames

    def load_frame_bundles(self, *args, **kwargs):
        return self.frames

    def dataset_to_dict(self, dataset):
        return {}


def test_analyze_rejects_unsupported_snapshot_type(monkeypatch):
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "bad_type",
        "codes": [],
    })
    assert response.status_code == 400
    assert "unsupported snapshot_type" in response.text


def test_analyze_returns_py_golden_frames(monkeypatch):
    frames = [{
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [{
            "code": "002279",
            "name": "久其软件",
            "rank": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
        }],
        "hotlist": [],
        "stocks": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.data.repository_factory.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    response = client.post("/api/ranktrend/analyze", json={
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-08-02 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "py_golden"
    assert len(body["frames"]) == 1
    assert body["frames"][0]["frameKey"] == "2026-08-02 14:00"
    assert body["frames"][0]["regime"]["state"] in ("strong", "normal", "weak", "retreat")
    assert body["frames"][0]["stocks"][0]["code"] == "002279"
    assert "strategy" in body["frames"][0]["stocks"][0]["analysis"]
    assert "executionStrategy" in body["frames"][0]["stocks"][0]["analysis"]


def test_frames_include_regime(monkeypatch):
    frames = [{
        "snapshotId": "s1",
        "tradingDate": "2026-08-02",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [{
            "code": "002279",
            "rank": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
        }],
        "stocks": [],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    monkeypatch.setattr(
        "backend.main.create_repository",
        lambda db, enable_backup=True: FakeRepo(frames),
    )
    monkeypatch.setattr(
        "backend.main._resolve_snapshot_dataset",
        lambda repo, dataset_id: ("dragonboard_live", None),
    )
    captured: dict = {}

    def fake_cached(kind, **kwargs):
        captured["loader"] = kwargs["loader"]
        return {"ok": True, "frames": [], "count": 0, "source": "test"}

    monkeypatch.setattr("backend.main._cached_snapshot_response", fake_cached)
    client.get("/api/snapshots/frames")
    body = captured["loader"]()
    assert body["ok"] is True
    assert "regime" in body["frames"][0]
    assert body["frames"][0]["regime"]["state"] in ("strong", "normal", "weak", "retreat")
