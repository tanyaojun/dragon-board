import pytest
from fastapi.testclient import TestClient

from backend.data import snapshot_cache
from backend.main import app
from backend.settings import get_settings


client = TestClient(app)


@pytest.fixture(autouse=True)
def _disable_real_analyze_cache(monkeypatch):
    """默认禁用真实 Redis，保证既有用例走计算路径；缓存专项用例再注入内存 fake。"""
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=None,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )


class FakeRepo:
    def __init__(self, frames):
        self.frames = frames

    def load_frame_bundles(self, *args, **kwargs):
        frames = list(self.frames)
        if kwargs.get("sort") == "desc":
            frames.sort(key=lambda frame: int(frame.get("timestamp") or 0), reverse=True)
            limit = kwargs.get("limit")
            if limit and limit > 0:
                frames = frames[:limit]
        return frames

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
            "avgRankNum": 1,
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


def test_analyze_returns_resonance_and_market_median(monkeypatch):
    frames = [{
        "tradingDate": f"2026-08-0{day}",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": day,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    } for day in range(1, 5)]
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
        "frameKeys": ["2026-08-04 14:00"],
    })
    assert response.status_code == 200
    frame = response.json()["frames"][0]
    assert "marketMedianPercentile" in frame
    assert "marketMedianShortChange" in frame
    assert frame["stocks"][0]["analysis"]["resonance"]["status"] in ("ok", "insufficient")


def test_analyze_finds_recent_frames_when_dataset_exceeds_200_window(monkeypatch):
    # 数据集超过 200 帧时，观察面板请求的是最近历史帧；后端必须加载最近 200 帧，
    # 而不是按 asc 加载最早 200 帧导致请求帧全部落空并返回 503。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
                {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
                {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 221)
    ]
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
        "frameKeys": ["2026-07-220 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    frame_keys = [frame["frameKey"] for frame in body["frames"]]
    assert frame_keys[-1] == "2026-07-220 14:00"
    # 请求帧 + 前导轨道窗口（技术/共振需要足够历史序列）
    assert 1 < len(frame_keys) <= 30
    assert body["frames"][0]["stocks"][0]["code"] == "002279"


def test_analyze_returns_empty_frames_when_requested_keys_missing_but_repo_has_frames(monkeypatch):
    # 请求的帧缺失但库里仍有帧时，不整段 503：返回可计算部分，由前端逐帧降级标记。
    frames = [
        {
            "tradingDate": "2026-07-01",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": 1,
            "rows": [{"code": "002279", "rank": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1}],
            "sentiment": {},
            "marketStats": {},
        }
    ]
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
        "frameKeys": ["2026-07-99 14:00"],
    })
    assert response.status_code == 200
    assert response.json()["frames"] == []


def test_analyze_live_path_keeps_enough_history_for_resonance(monkeypatch):
    # 实时链路（无 frameKeys + currentFrame）必须保留足够回看窗口，否则个股百分位序列
    # 不足 9 点，共振强度会固定返回 insufficient/全零因子。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % 30 + 1,
                    "avgRankNum": (index + day) % 30 + 1,
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(30)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 31)
    ]
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
        "codes": ["C00"],
        "currentFrame": {
            "tradingDate": "2026-07-31",
            "slotTime": "current:1",
            "stocks": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + 31) % 30 + 1,
                    "avgRankNum": (index + 31) % 30 + 1,
                }
                for index in range(30)
            ],
        },
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    assert last["frameKey"] == "2026-07-31 current:1"
    assert isinstance(last["marketMedianShortChange"], float)
    assert isinstance(last["marketMedianPercentile"], float)
    resonance = last["stocks"][0]["analysis"]["resonance"]
    assert resonance["status"] == "ok"
    assert resonance["historyState"] == "established"
    assert "marketSampleCount" in resonance
    assert "marketMedianPercentile" in resonance
    # resonance 已下沉：Python golden 把共振方向/分数直接写进 decision.final
    analysis = last["stocks"][0]["analysis"]
    assert analysis["decision"]["final"] == {
        "signal": resonance["direction"],
        "confidence": resonance["score"],
    }


def test_analyze_fuses_insufficient_resonance_into_hold_final(monkeypatch):
    frames = [{
        "tradingDate": f"2026-08-0{day}",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": day,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 5.0, "volumeRatio": 1.5, "zlje": 10, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 3.0, "volumeRatio": 1.2, "zlje": 5, "zljzb": 0.05},
            {"code": "000001", "rank": 3, "avgRankNum": 3, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.01},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    } for day in range(1, 5)]
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
        "frameKeys": ["2026-08-04 14:00"],
    })
    assert response.status_code == 200
    analysis = response.json()["frames"][0]["stocks"][0]["analysis"]
    assert analysis["resonance"]["status"] == "insufficient"
    assert analysis["decision"]["final"] == {"signal": "hold", "confidence": 0}


def test_analyze_historical_frames_keep_enough_history_for_tracks(monkeypatch):
    # 观察面板请求最近历史帧时，后端必须为最早请求帧保留足够的前导帧，
    # 否则技术/共振/生命周期算法只能用 1-4 个 bar 分析，历史 bar 全为样本不足。
    frames = [
        {
            "tradingDate": f"2026-07-{day:03d}",
            "slotTime": "14:00",
            "type": "half_hour",
            "timestamp": day,
            "rows": [
                {
                    "code": f"C{index:02d}",
                    "rank": (index + day) % 30 + 1,
                    "avgRankNum": (index + day) % 30 + 1,
                    "change": 1.0,
                    "volumeRatio": 1.2,
                    "zlje": 10,
                    "zljzb": 0.1,
                }
                for index in range(30)
            ],
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        }
        for day in range(1, 41)
    ]
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
        "codes": ["C00"],
        "frameKeys": ["2026-07-038 14:00", "2026-07-039 14:00", "2026-07-040 14:00"],
    })
    assert response.status_code == 200
    body = response.json()
    by_key = {frame["frameKey"]: frame for frame in body["frames"]}
    earliest = by_key["2026-07-038 14:00"]
    sample_quality = earliest["stocks"][0]["analysis"]["meta"]["sampleQuality"]
    assert sample_quality["sampleCount"] >= 22
    assert earliest["stocks"][0]["analysis"]["resonance"]["status"] == "ok"


def test_analyze_market_median_uses_avg_rank_num_cross_section(monkeypatch):
    # 对齐旧 TS buildFrameCrossSections 合同：横截面只统计 avgRankNum > 0 的股票，
    # 按 avgRankNum 升序重排后取百分位中位数；sampleCount = 帧横截面股票数。
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "C01", "rank": 1, "avgRankNum": 20, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C02", "rank": 2, "avgRankNum": 30, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C03", "rank": 3, "avgRankNum": 40, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C04", "rank": 4, "avgRankNum": 50, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "C05", "rank": 5, "avgRankNum": 0, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
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
        "codes": ["C01"],
        "frameKeys": ["2026-07-01 14:00"],
    })
    assert response.status_code == 200
    frame = response.json()["frames"][0]
    assert frame["marketMedianPercentile"] == 62.5
    assert frame["marketSampleCount"] == 4


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.sets: dict[str, set[str]] = {}

    def get(self, key):
        return self.data.get(key)

    def setex(self, key, ttl, value):
        self.data[key] = value
        self.ttls[key] = ttl

    def incr(self, key):
        self.data[key] = str(int(self.data.get(key, 0)) + 1)
        return int(self.data[key])

    def sadd(self, key, member):
        self.sets.setdefault(key, set()).add(member)
        return 1

    def expire(self, key, ttl):
        return 1

    def smembers(self, key):
        return list(self.sets.get(key, set()))

    def delete(self, *keys):
        removed = 0
        for key in keys:
            if key in self.data:
                del self.data[key]
                removed += 1
            if key in self.sets:
                del self.sets[key]
                removed += 1
        return removed

    def pipeline(self, transaction=False):
        return _FakePipeline(self)


class _FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands: list[tuple] = []

    def sadd(self, key, member):
        self.commands.append(("sadd", key, member))
        return self

    def expire(self, key, ttl):
        self.commands.append(("expire", key, ttl))
        return self

    def execute(self):
        for command in self.commands:
            if command[0] == "sadd":
                self.redis.sadd(command[1], command[2])
            elif command[0] == "expire":
                self.redis.expire(command[1], command[2])
        self.commands = []
        return []


def test_analyze_redis_cache_hit_and_key_variation(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    calls = {"n": 0}

    def counting_repo(db, enable_backup=True):
        calls["n"] += 1
        return FakeRepo(frames)

    monkeypatch.setattr("backend.data.repository_factory.create_repository", counting_repo)
    payload = {
        "snapshotType": "half_hour",
        "codes": ["002279"],
        "frameKeys": ["2026-07-01 14:00"],
    }

    first = client.post("/api/ranktrend/analyze", json=payload)
    assert first.status_code == 200
    calls_after_first = calls["n"]
    assert calls_after_first == 1

    second = client.post("/api/ranktrend/analyze", json=payload)
    assert second.status_code == 200
    assert calls["n"] == calls_after_first  # 命中缓存，不再走 repository
    assert second.json()["cache"]["hit"] is True
    assert second.json()["source"] == "py_golden"

    # 请求内容不同（codes）→ 缓存键不同 → 重新计算
    calls["n"] = 0
    third = client.post("/api/ranktrend/analyze", json={**payload, "codes": ["002279", "603580"]})
    assert calls["n"] == 1
    assert third.json()["cache"]["hit"] is False

    # dataset generation 递增（ingest 后）→ 新 generation 键不命中旧缓存
    generation_key = snapshot_cache.build_snapshot_cache_generation_key(
        prefix=get_settings().redis_key_prefix,
        dataset_id="dragonboard_live",
    )
    fake_redis.incr(generation_key)
    calls["n"] = 0
    fourth = client.post("/api/ranktrend/analyze", json=payload)
    assert calls["n"] == 1
    assert fourth.json()["cache"]["hit"] is False


def test_analyze_cache_key_ignores_current_frame_sequence_and_volatile_fields(monkeypatch):
    # 面板每次打开都会生成自增的 current:N slotTime，且 currentFrame.stocks 带实时行情字段。
    # 两者都不能进入缓存键，否则 Redis TTL 缓存永远 miss、每次都重新计算。
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
            {"code": "603580", "rank": 2, "avgRankNum": 2, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
        "sentiment": {"phaseName": "启动"},
        "marketStats": {},
    }]
    monkeypatch.setattr(
        "backend.data.repository_factory.get_runtime_mongodb_database",
        lambda: object(),
    )
    calls = {"n": 0}

    def counting_repo(db, enable_backup=True):
        calls["n"] += 1
        return FakeRepo(frames)

    monkeypatch.setattr("backend.data.repository_factory.create_repository", counting_repo)

    def payload(slot: str, change: float, trading_date: str = "2026-08-02"):
        return {
            "snapshotType": "half_hour",
            "codes": ["002279"],
            "frameKeys": ["2026-07-01 14:00"],
            "currentFrame": {
                "tradingDate": trading_date,
                "slotTime": slot,
                "stocks": [
                    {
                        "code": "002279",
                        "rank": 1,
                        "avgRankNum": 1,
                        "change": change,
                        "volumeRatio": 1.0,
                        "zlje": 1,
                        "zljzb": 0.1,
                    }
                ],
            },
        }

    first = client.post("/api/ranktrend/analyze", json=payload("current:1", 5.0))
    assert first.status_code == 200
    assert calls["n"] == 1

    # 自增序列号 + 实时行情字段变化 → 必须命中同一缓存键
    calls["n"] = 0
    second = client.post("/api/ranktrend/analyze", json=payload("current:2", 7.0))
    assert calls["n"] == 0
    assert second.json()["cache"]["hit"] is True

    # 跨交易日（tradingDate 不同）→ 输出口径不同 → 必须生成新键
    calls["n"] = 0
    third = client.post(
        "/api/ranktrend/analyze",
        json=payload("current:3", 7.0, trading_date="2026-08-03"),
    )
    assert calls["n"] == 1
    assert third.json()["cache"]["hit"] is False


def test_analyze_cache_ttl_aligns_with_snapshot_read_ttl(monkeypatch):
    # analyze 缓存 TTL 必须与快照读口一致（settings.snapshot_cache_ttl_seconds），
    # 否则面板打开间隔稍长就丢失缓存并全量重算。
    fake_redis = FakeRedis()
    monkeypatch.setattr(
        "backend.api.ranktrend_routes.snapshot_cache.get_snapshot_redis_cache",
        lambda: snapshot_cache.SnapshotRedisCache(
            redis_client=fake_redis,
            ttl_seconds=60,
            empty_ttl_seconds=10,
        ),
    )
    frames = [{
        "tradingDate": "2026-07-01",
        "slotTime": "14:00",
        "type": "half_hour",
        "timestamp": 1,
        "rows": [
            {"code": "002279", "rank": 1, "avgRankNum": 1, "change": 1.0, "volumeRatio": 1.0, "zlje": 1, "zljzb": 0.1},
        ],
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
        "frameKeys": ["2026-07-01 14:00"],
    })
    assert response.status_code == 200

    analyze_keys = [key for key in fake_redis.ttls if "ranktrend:analyze" in key]
    assert analyze_keys
    for key in analyze_keys:
        assert fake_redis.ttls[key] == get_settings().snapshot_cache_ttl_seconds


def _theme_frames_with_context(count=12, theme_count=25):
    frames = []
    for idx in range(count):
        slot = f"{10 + idx // 2:02d}:{30 if idx % 2 else 0:02d}"
        rows = [{
            "code": "002279",
            "name": "久其软件",
            "rank": 1,
            "avgRankNum": 1,
            "change": 5.0,
            "volumeRatio": 1.5,
            "zlje": 10,
            "zljzb": 0.1,
            "themes": ["主线概念"],
        }]
        hot_themes = [
            {
                "entityType": "hot_theme",
                "themeId": "T0",
                "themeName": "主线概念板块",
                "heatScore": 40.0 + idx * 5.0,
                "rank": 1,
                "rotationState": "mainline",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
        ]
        hot_themes += [
            {
                "entityType": "hot_theme",
                "themeId": f"T{i}",
                "themeName": f"普通概念{i}",
                "heatScore": 50.0,
                "rank": i + 1,
                "rotationState": "neutral",
                "crowdingRisk": 30.0,
                "metadata": {"rankEligible": True},
            }
            for i in range(1, theme_count)
        ]
        frames.append({
            "tradingDate": "2026-08-04",
            "slotTime": slot,
            "type": "half_hour",
            "timestamp": idx + 1,
            "rows": rows,
            "stocks": rows,
            "hotThemes": hot_themes,
            "sentiment": {"phaseName": "启动"},
            "marketStats": {},
        })
    return frames


def test_analyze_includes_theme_context_and_resonance_theme(monkeypatch):
    frames = _theme_frames_with_context()
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
        "frameKeys": ["2026-08-04 15:00"],
    })
    assert response.status_code == 200
    body = response.json()
    frame = next(item for item in body["frames"] if item["frameKey"] == "2026-08-04 15:00")
    assert "themeContext" in frame
    assert frame["themeContext"]["themeSampleCount"] >= 20
    assert frame["themeContext"]["marketThemeMedianShortChange"] is not None
    stock = frame["stocks"][0]
    theme = stock["analysis"]["resonance"].get("theme")
    assert theme is not None
    assert theme["status"] in ("ok", "insufficient")
    if theme["status"] == "ok":
        assert theme["themeMomentumScore"] > 50
        assert theme["themeLifecycle"] == "mainline"
        assert stock["analysis"]["decision"]["final"]["signal"] in ("buy", "hold")


def test_analyze_current_frame_theme_falls_back_to_last_historical_hot_themes(monkeypatch):
    frames = _theme_frames_with_context()
    current_frame = {
        "tradingDate": "2026-08-04",
        "slotTime": "current:1",
        "stocks": [{
            "code": "002279",
            "rank": 1,
            "avgRankNum": 1,
            "themes": ["主线概念"],
        }],
    }
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
        "currentFrame": current_frame,
    })
    assert response.status_code == 200
    body = response.json()
    last = body["frames"][-1]
    theme = last["stocks"][0]["analysis"]["resonance"]["theme"]
    assert theme["status"] == "ok"
    assert theme["themeMomentumScore"] > 50
    assert "theme_mapping_missing" not in theme["reasons"]
