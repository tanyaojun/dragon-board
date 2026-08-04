"""ranktrend projection 必须返回 hotThemes 与股票 themes，供题材动量计算。"""

from backend.data.mongo_repository import MongoRepository


class FakeCollection:
    def __init__(self, rows):
        self._rows = list(rows)
        self.last_query = None
        self.last_projection = None

    def find(self, query, projection=None):
        self.last_query = query
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


def _frames():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "type": "half_hour",
        "tradingDate": "2026-08-04",
        "slotTime": "10:00",
        "timestamp": 1,
    }]


def _sector_rows():
    return [{
        "snapshotId": "s1",
        "datasetId": "dragonboard_live",
        "entityType": "hot_theme",
        "entityKey": "T1",
        "entityName": "T1概念板块",
        "heatScore": 80.0,
        "rank": 1,
        "rotationState": "mainline",
        "crowdingRisk": 30.0,
        "metadata": {"rankEligible": True},
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
        "snapshot_sector_rows": _sector_rows(),
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
        "snapshot_sector_rows": _sector_rows(),
    }))
    bundles = repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend")
    assert bundles[0]["hotThemes"] == []
    stock = bundles[0]["stocks"][0]
    assert "themes" not in stock
    assert "themeRole" not in stock
    assert set(stock) == {"code", "name", "rank", "avgRankNum", "change", "volumeRatio", "zlje", "zljzb"}


def test_ranktrend_plus_themes_filters_sector_rows_by_hot_theme_server_side():
    """M1: ranktrend+themes 只按 hot_theme 服务端过滤 sector rows，不加载行业板块行。"""
    db = FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
        "snapshot_sector_rows": _sector_rows(),
    })
    repo = MongoRepository(db)
    repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="ranktrend+themes")
    sector_query = db._collections["snapshot_sector_rows"].last_query
    assert sector_query is not None
    assert sector_query.get("entityType") == "hot_theme"
    assert db._collections["snapshot_sector_rows"].last_projection is not None


def test_full_projection_does_not_filter_sector_rows_server_side():
    """full 投影仍需同时取 sector 与 hot_theme，不应加 entityType 过滤。"""
    db = FakeDb({
        "snapshot_frames": _frames(),
        "snapshot_stock_rows": _stock_rows(),
        "snapshot_sector_rows": _sector_rows(),
    })
    repo = MongoRepository(db)
    repo.load_frame_bundles("dragonboard_live", snapshot_type="half_hour", projection="full")
    sector_query = db._collections["snapshot_sector_rows"].last_query
    assert sector_query is not None
    assert "entityType" not in sector_query
    assert db._collections["snapshot_sector_rows"].last_projection is None
