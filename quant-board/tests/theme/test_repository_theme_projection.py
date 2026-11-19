"""ranktrend projection 必须返回 hotThemes 与股票 themes，供题材动量计算。

2026-11-19 起 sector rows 内嵌在帧文档 sectorRows（独立集合已 drop），
本文件夹具同步改为帧内嵌形态；投影行为合同不变。
"""

import pytest

from backend.data.repositories.mongo_repository import MongoRepository


@pytest.fixture(autouse=True)
def _isolate_redis_cache(monkeypatch):
    """隔离真实 Redis：投影测试要断言 Mongo 查询行为，不能命中持久化缓存。"""
    from backend.data.cache import snapshot_cache

    class NoopCache:
        def get_response(self, key):
            return None

        def set_response(self, key, response, ttl_seconds=None):
            return None

        def get_generation(self, key):
            return 0

        def register_dependencies(self, key, index_keys):
            return None

    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: NoopCache())


class FakeCollection:
    def __init__(self, rows):
        self._rows = list(rows)
        self.last_query = None
        self.last_projection = None
        self.last_queries = []
        self.call_count = 0

    def find(self, query, projection=None):
        self.call_count += 1
        self.last_query = query
        self.last_queries.append(dict(query or {}))
        self.last_projection = projection
        return self

    def sort(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def __iter__(self):
        yield from self._rows

    def count_documents(self, query):
        return 0


class FakeDb:
    def __init__(self, collections):
        self._collections = {
            name: FakeCollection(rows) for name, rows in collections.items()
        }

    def __getitem__(self, name):
        return self._collections[name]


def _embedded_sector_rows():
    """帧内嵌 sector rows（瘦身形态，无帧级上下文重复字段）。"""
    return [
        {
            "entityType": "hot_theme",
            "entityKey": "T1",
            "entityName": "T1概念板块",
            "heatScore": 80.0,
            "rank": 1,
            "rotationState": "mainline",
            "crowdingRisk": 30.0,
            "metadata": {"rankEligible": True},
        },
        {
            "entityType": "sector",
            "entityKey": "BANK",
            "entityName": "银行",
            "heatScore": 40.0,
            "rank": 2,
            "rotationState": "neutral",
        },
    ]


def _frames():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "type": "half_hour",
        "tradingDate": "2026-08-04",
        "slotTime": "10:00",
        "timestamp": 1,
        "sectorRows": _embedded_sector_rows(),
    }]


def _stock_rows():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "code": "000001",
        "name": "平安银行",
        "rank": 1,
        "avgRankNum": 1.0,
        "change": 3.0,
        "volumeRatio": 1.2,
        "zlje": 10.0,
        "zljzb": 0.1,
        "themes": ["T1概念板块"],
        "mainTheme": "T1概念板块",
        "themeRole": "follower",
        "themeContribution": 30.0,
        "leadStatus": "",
    }]


def test_ranktrend_plus_themes_projection_includes_hot_themes_and_stock_themes():
    repo = MongoRepository(FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend+themes")
    assert len(bundles) == 1
    assert bundles[0]["hotThemes"] != []
    assert bundles[0]["hotThemes"][0]["entityType"] == "hot_theme"
    assert bundles[0]["stocks"][0]["themes"] == ["T1概念板块"]
    assert bundles[0]["stocks"][0]["themeRole"] == "follower"


def test_plain_ranktrend_projection_stays_lightweight():
    repo = MongoRepository(FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend")
    assert bundles[0]["hotThemes"] == []
    stock = bundles[0]["stocks"][0]
    assert "themes" not in stock
    assert "themeRole" not in stock
    assert set(stock) == {"code", "name", "rank", "avgRankNum", "change", "volumeRatio", "zlje", "zljzb"}


def test_ranktrend_plus_themes_hot_themes_only_hot_theme_rows():
    """M1 合同延续：ranktrend+themes 投影的 hotThemes 只含 hot_theme 行，
    行业板块（sector）行不进 hotThemes（2026-11-19 起过滤在帧内嵌展开时做）。"""
    repo = MongoRepository(FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend+themes")
    entity_types = {row.get("entityType") for row in bundles[0]["hotThemes"]}
    assert entity_types == {"hot_theme"}


def test_full_projection_includes_sector_and_hot_theme_rows():
    """full 投影同时展开 sector 与 hot_theme 行（不再有服务端 entityType 单值过滤）。"""
    repo = MongoRepository(FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="full")
    entity_types = {row.get("entityType") for row in bundles[0]["entities"]}
    assert entity_types == {"hot_theme", "sector"}
    assert {row.get("entityType") for row in bundles[0]["hotThemes"]} == {"hot_theme"}
    assert {row.get("entityType") for row in bundles[0]["sectors"]} == {"sector"}


def test_ranktrend_plus_themes_bundle_reads_use_redis_ttl_cache(monkeypatch):
    """投影合同读取命中 Redis TTL 缓存时，不再重复查询 MongoDB stock/sector rows。"""
    from backend.data.cache import snapshot_cache

    class FakeRedisCache:
        def __init__(self):
            self.store = {}
            self.generation = 1

        def get_response(self, key):
            return self.store.get(key)

        def set_response(self, key, response, ttl_seconds=None):
            self.store[key] = response

        def get_generation(self, key):
            return self.generation

        def register_dependencies(self, key, index_keys):
            pass

    fake_cache = FakeRedisCache()
    monkeypatch.setattr(snapshot_cache, "get_snapshot_redis_cache", lambda: fake_cache)

    db = FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
    })
    repo = MongoRepository(db)
    repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend+themes")
    stock_calls = db._collections["snapshot_stock_rows"].call_count

    def sector_replay_calls() -> int:
        """帧内嵌 sector 行回放查询数：frames 集合上带 snapshotId 过滤的 find 次数。"""
        return sum(1 for q in db._collections["snapshot_frames"].last_queries if "snapshotId" in q)

    replay_after_first = sector_replay_calls()

    repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend+themes")
    assert db._collections["snapshot_stock_rows"].call_count == stock_calls
    # 缓存命中后不重复回放 sector 行（带 snapshotId 的 frames 查询不新增）
    assert sector_replay_calls() == replay_after_first
