from backend.data.hotlist_sentiment_repo import HotListSentimentRepository


class FakeMongoCollection:
    def __init__(self) -> None:
        self._docs: dict[tuple[str, str, str], dict] = {}
        self.queries: list[dict] = []

    def find_one(self, query: dict) -> dict | None:
        self.queries.append(query)
        key = (
            str(query.get("datasetId") or ""),
            str(query.get("snapshotType") or ""),
            str(query.get("tradingDate") or ""),
        )
        return self._docs.get(key)

    def insert_one(self, doc: dict) -> None:
        key = (
            str(doc["datasetId"]),
            str(doc["snapshotType"]),
            str(doc["tradingDate"]),
        )
        self._docs[key] = doc


class FakeMongoDb:
    def __init__(self) -> None:
        self._collections: dict[str, FakeMongoCollection] = {}

    def __getitem__(self, name: str) -> FakeMongoCollection:
        if name not in self._collections:
            self._collections[name] = FakeMongoCollection()
        return self._collections[name]


def test_repo_returns_none_when_sentiment_date_not_found() -> None:
    db = FakeMongoDb()
    repo = HotListSentimentRepository(db)

    result = repo.get_by_date("dragonboard_live", "half_hour", "2026-04-01")

    assert result is None


def test_repo_returns_document_for_dataset_snapshot_and_date() -> None:
    db = FakeMongoDb()
    db["hotlist_sentiment"].insert_one(
        {
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "tradingDate": "2026-06-05",
            "stage": "高潮",
            "riskLevel": "低",
        }
    )
    repo = HotListSentimentRepository(db)

    result = repo.get_by_date("dragonboard_live", "half_hour", "2026-06-05")

    assert result is not None
    assert result["stage"] == "高潮"
    assert result["riskLevel"] == "低"


def test_repo_cache_is_scoped_by_dataset_snapshot_and_date() -> None:
    db = FakeMongoDb()
    db["hotlist_sentiment"].insert_one(
        {
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "tradingDate": "2026-06-05",
            "stage": "高潮",
        }
    )
    repo = HotListSentimentRepository(db)

    repo.get_by_date("dragonboard_live", "half_hour", "2026-06-05")
    repo.get_by_date("dragonboard_live", "half_hour", "2026-06-05")
    repo.get_by_date("dragonboard_live", "quarter_hour", "2026-06-05")

    assert len(db["hotlist_sentiment"].queries) == 2


def test_ranktrend_replay_injects_hotlist_sentiment_by_trading_date(monkeypatch) -> None:
    from backend.analysis import ranktrend
    from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine

    db = FakeMongoDb()
    db["hotlist_sentiment"].insert_one(
        {
            "datasetId": "dragonboard_live",
            "snapshotType": "half_hour",
            "tradingDate": "2026-06-05",
            "stage": "冰点",
            "riskLevel": "高",
        }
    )
    monkeypatch.setattr(ranktrend.repository_factory, "get_runtime_mongodb_database", lambda: db)

    frames = [
        {
            "snapshotId": f"s{i}",
            "type": "half_hour",
            "timestamp": i,
            "tradingDate": "2026-06-05",
            "slotTime": "10:00",
            "stocks": [
                {
                    "code": "000001",
                    "name": "样本",
                    "rank": max(1, 30 - i),
                    "change": 1,
                    "volumeRatio": 1.2,
                    "zlje": 1000,
                    "zljzb": 1,
                }
            ],
        }
        for i in range(8)
    ]
    config = RankTrendConfig.from_patch({"minSampleCount": 3})

    signals = RankTrendPythonEngine(config).replay(
        frames,
        meta={"datasetId": "dragonboard_live", "snapshotType": "half_hour", "sampleQuality": "ok"},
    )

    assert signals
    assert signals[-1]["rankTrend"]["strategy"]["hotlist"]["stage"] == "冰点"
    assert signals[-1]["candidateTier"] not in ("A_MAIN", "B_IGNITION")
    assert len(db["hotlist_sentiment"].queries) == 1
