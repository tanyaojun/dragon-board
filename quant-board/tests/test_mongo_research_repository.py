from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun, TradeJournal
from backend.data.mongo_research_repository import MongoResearchRepository
from backend.data.json_codec import loads_json_field
from backend.utils import json_dumps


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def sort(self, keys) -> "FakeCursor":
        sort_keys = list(keys if isinstance(keys, list) else [keys])
        for key, direction in reversed(sort_keys):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=int(direction) < 0)
        return self

    def limit(self, count: int) -> "FakeCursor":
        if count and count > 0:
            self.rows = self.rows[:count]
        return self

    def skip(self, count: int) -> "FakeCursor":
        if count and count > 0:
            self.rows = self.rows[count:]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeDeleteResult:
    def __init__(self, deleted_count: int) -> None:
        self.deleted_count = deleted_count


class FakeUpdateResult:
    def __init__(self, matched_count: int) -> None:
        self.matched_count = matched_count


class FakeCollection:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def count_documents(self, query: dict[str, Any]) -> int:
        return len(list(self.find(query)))

    def delete_many(self, query: dict[str, Any]) -> FakeDeleteResult:
        before = len(self.rows)
        self.rows = [row for row in self.rows if not _matches(row, query)]
        return FakeDeleteResult(before - len(self.rows))

    def insert_many(self, rows: list[dict[str, Any]], ordered: bool = False) -> None:
        assert ordered is False
        self.rows.extend(dict(row) for row in rows)

    def replace_one(self, query: dict[str, Any], document: dict[str, Any], upsert: bool = False) -> None:
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = dict(document)
                return
        if upsert:
            self.rows.append(dict(document))

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> FakeUpdateResult:
        updates = update.get("$set") if isinstance(update.get("$set"), dict) else {}
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = {**row, **updates}
                return FakeUpdateResult(1)
        return FakeUpdateResult(0)

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        return next(iter(self.find(query)), None)

    def find(self, query: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor([dict(row) for row in self.rows if _matches(row, query or {})])


class FakeMongoDatabase(dict):
    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self:
            self[name] = FakeCollection()
        return dict.__getitem__(self, name)


def test_backtest_run_roundtrips_request_and_result_as_structured_fields() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    created_at = datetime(2026, 5, 12, 9, 30)
    finished_at = datetime(2026, 5, 12, 15, 0)

    saved = repo.save_backtest_run(
        BacktestRun(
            id="bt_1",
            dataset_id="ds_1",
            strategy_name="rank_trend_candidate",
            strategy_version="0.1.0",
            snapshot_type="half_hour",
            config_hash="hash_1",
            random_seed=20260430,
            status="completed",
            date_start="2026-05-11",
            date_end="2026-05-12",
            request_json='{"datasetId":"ds_1","nested":{"a":1}}',
            result_json='{"metrics":{"totalReturn":0.12}}',
            created_at=created_at,
            finished_at=finished_at,
        )
    )

    fetched = repo.get_backtest_run("bt_1")
    as_dict = repo.backtest_run_to_dict(fetched)
    raw_doc = db["backtest_runs"].rows[0]

    assert saved.id == "bt_1"
    assert fetched is not None
    assert fetched.request_json == '{"datasetId":"ds_1","nested":{"a":1}}'
    assert fetched.result_json == '{"metrics":{"totalReturn":0.12}}'
    assert as_dict["request"] == {"datasetId": "ds_1", "nested": {"a": 1}}
    assert as_dict["result"] == {"metrics": {"totalReturn": 0.12}}
    assert raw_doc["request"] == {"datasetId": "ds_1", "nested": {"a": 1}}
    assert raw_doc["resultCompressed"].startswith("__qb_gzip_b64__:") is False
    assert "result" not in raw_doc
    assert "request_json" not in raw_doc
    assert "result_json" not in raw_doc


def test_backtest_run_doc_compresses_large_result_without_losing_payload() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    result = {
        "totalReturn": 0.12,
        "signals": [{"code": f"{index:06d}"} for index in range(200)],
        "tradeEvents": [{"code": f"{index:06d}"} for index in range(200)],
        "strategyDecisions": {
            "frameResults": [
                {
                    "snapshotId": f"s{index}",
                    "buyCandidates": [{"code": f"{index:06d}"} for _ in range(30)],
                    "watchCandidates": [{"code": f"{index:06d}"} for _ in range(30)],
                    "excludedCandidates": [{"code": f"{index:06d}"} for _ in range(30)],
                }
                for index in range(40)
            ]
        },
        "tradeSimulation": {
            "trades": [{"code": f"{index:06d}"} for index in range(200)],
            "equityCurve": [{"equity": 1000000 + index} for index in range(200)],
            "config": {"positionSize": 0.2},
        },
    }

    saved = repo.save_backtest_run(
        BacktestRun(
            id="bt_large",
            dataset_id="ds_1",
            strategy_name="rank_trend_candidate",
            snapshot_type="half_hour",
            config_hash="hash_large",
            random_seed=20260430,
            request_json='{"datasetId":"ds_1"}',
            result_json=json_dumps(result),
        )
    )

    raw_doc = db["backtest_runs"].rows[0]
    restored = repo.get_backtest_run("bt_large")
    restored_result = loads_json_field(restored.result_json, {})

    assert saved.id == "bt_large"
    assert "result" not in raw_doc
    assert raw_doc["resultCompressed"].startswith("__qb_gzip_b64__:")
    assert restored_result == result


def test_backtest_run_without_status_is_stored_as_completed() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    run = BacktestRun(
        id="bt_missing_status",
        dataset_id="ds_1",
        strategy_name="rank_trend_candidate",
        snapshot_type="half_hour",
        config_hash="hash_1",
        random_seed=20260430,
        request_json='{"datasetId":"ds_1"}',
        result_json='{"metrics":{"totalReturn":0.12}}',
    )
    run.status = None

    saved = repo.save_backtest_run(run)
    raw_doc = db["backtest_runs"].rows[0]

    assert raw_doc["status"] == "completed"
    assert saved.status == "completed"


def test_backtest_signals_keep_sequence_order_and_support_tier_regime_filters() -> None:
    repo = MongoResearchRepository(FakeMongoDatabase())

    count = repo.save_backtest_signal_rows(
        "bt_1",
        [
            _signal("000003", 3, "watch", "weak"),
            _signal("000001", 1, "buy", "strong"),
            _signal("000002", 2, "buy", "weak"),
        ],
    )

    assert count == 3
    assert [row["code"] for row in repo.get_backtest_signals("bt_1")] == ["000003", "000001", "000002"]
    assert [row["sequence"] for row in repo.get_backtest_signals("bt_1")] == [1, 2, 3]
    assert [row["code"] for row in repo.get_backtest_signals("bt_1", tier="buy")] == ["000001", "000002"]
    assert [row["code"] for row in repo.get_backtest_signals("bt_1", regime="weak")] == ["000003", "000002"]
    assert repo.count_backtest_signals("bt_1", tier="buy", regime="weak") == 1


def test_optimization_run_roundtrips_structured_request_and_result() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    created_at = datetime(2026, 5, 12, 10, 0)

    repo.save_optimization_run(
        OptimizationRun(
            id="opt_1",
            dataset_id="ds_1",
            strategy_name="rank_trend_candidate",
            method="grid",
            config_hash="hash_opt",
            random_seed=7,
            status="completed",
            request_json='{"space":{"threshold":[1,2]}}',
            result_json='{"best":{"score":0.88}}',
            created_at=created_at,
        )
    )

    fetched = repo.get_optimization_run("opt_1")
    raw_doc = db["optimization_runs"].rows[0]

    assert fetched is not None
    assert fetched.request_json == '{"space":{"threshold":[1,2]}}'
    assert fetched.result_json == '{"best":{"score":0.88}}'
    assert raw_doc["request"] == {"space": {"threshold": [1, 2]}}
    assert raw_doc["result"] == {"best": {"score": 0.88}}
    assert "request_json" not in raw_doc
    assert "result_json" not in raw_doc


def test_golden_case_roundtrips_structured_input_and_expected() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)

    repo.save_golden_case(
        GoldenRankTrendCase(
            id="case_1",
            name="case one",
            dataset_id="ds_1",
            input_json='{"datasetId":"ds_1","frames":[{"id":"s1"}]}',
            expected_json='[{"code":"000001","signal":"buy"}]',
            created_at=datetime(2026, 5, 12, 11, 0),
        )
    )

    fetched = repo.get_golden_case("case_1")
    raw_doc = db["golden_ranktrend_cases"].rows[0]

    assert fetched is not None
    assert fetched.input_json == '{"datasetId":"ds_1","frames":[{"id":"s1"}]}'
    assert fetched.expected_json == '[{"code":"000001","signal":"buy"}]'
    assert raw_doc["input"] == {"datasetId": "ds_1", "frames": [{"id": "s1"}]}
    assert raw_doc["expected"] == [{"code": "000001", "signal": "buy"}]
    assert "input_json" not in raw_doc
    assert "expected_json" not in raw_doc


def test_theme_trend_research_tables_store_json_as_structured_fields() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)

    assert repo.save_factor_frames([_factor("snap_2", 2), _factor("snap_1", 1)]) == 2
    assert repo.save_stock_exposures([_exposure("000002", 0.4), _exposure("000001", 0.8)]) == 2
    assert repo.save_signals([_theme_signal("watch", 50), _theme_signal("mainline", 90)]) == 2
    assert repo.save_quality_report(_quality_report()) is True

    factors = repo.get_factor_frames("ds_1", "half_hour")
    exposures = repo.get_stock_exposures("ds_1", snapshot_id="snap_1")
    signals = repo.get_signals("ds_1", "half_hour", signal="mainline")
    reports = repo.get_quality_reports("ds_1", "half_hour")

    assert [row["snapshotId"] for row in factors] == ["snap_1", "snap_2"]
    assert factors[0]["qualityFlags"] == ["low_sample"]
    assert [row["code"] for row in exposures] == ["000001", "000002"]
    assert exposures[0]["reasons"] == ["role:leader", "theme:mainline"]
    assert signals[0]["signal"] == "mainline"
    assert reports[0]["issues"] == ["low_coverage"]
    assert reports[0]["warnings"] == ["low_sample"]
    assert reports[0]["stats"] == {"totalFrames": 2}

    for collection_name in (
        "theme_factor_frames",
        "theme_stock_exposures",
        "theme_signals",
        "theme_quality_reports",
    ):
        assert not any(key.endswith("_json") for key in db[collection_name].rows[0])


def test_repository_factory_returns_research_capable_mongo_repository(monkeypatch) -> None:
    import backend.data.repository_factory as factory

    fake_db = FakeMongoDatabase()
    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: fake_db)

    repo = factory.create_repository(None)

    assert isinstance(repo, MongoResearchRepository)
    assert repo.db is fake_db
    assert hasattr(repo, "save_backtest_run")
    assert hasattr(repo, "save_factor_frames")


def test_mongo_research_repository_saves_candidate_thesis_fields() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    entry = TradeJournal(
        id="tj_candidate",
        stock_code="000001",
        stock_name="平安银行",
        status="candidate",
        market_phase="repair",
        theme_role="mainline",
        stock_role="core",
        entry_reason="RankTrend 持续上行，题材扩散，情绪修复",
        trade_hypothesis="未来 3-5 天沿主线继续走强",
        entry_prerequisites="次日不弱于题材，排名不明显回落",
        invalidation_rules="题材退潮或 RankTrend 断档",
        expected_holding_days=3,
        human_decision="watch",
        signals_snapshot={"rankTrend": {"candidateTier": "B_IGNITION"}},
    )

    saved = repo.save_journal_entry(entry)
    row = repo.get_journal_entry(saved.id)

    assert row["id"] == "tj_candidate"
    assert row["status"] == "candidate"
    assert row["marketPhase"] == "repair"
    assert row["themeRole"] == "mainline"
    assert row["stockRole"] == "core"
    assert row["tradeHypothesis"] == "未来 3-5 天沿主线继续走强"
    assert row["expectedHoldingDays"] == 3
    assert row["signalsSnapshot"]["rankTrend"]["candidateTier"] == "B_IGNITION"


def test_mongo_research_repository_filters_journal_entries_by_status() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    repo.save_journal_entry(TradeJournal(id="tj_1", stock_code="000001", stock_name="a", status="candidate"))
    repo.save_journal_entry(TradeJournal(id="tj_2", stock_code="000002", stock_name="b", status="reviewed"))

    rows = repo.list_journal_entries(status="candidate")

    assert [row["id"] for row in rows] == ["tj_1"]


def test_mongo_research_repository_updates_review_result_separately_from_execution() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    repo.save_journal_entry(TradeJournal(id="tj_1", stock_code="000001", stock_name="a", status="triggered"))

    row = repo.update_journal_entry(
        "tj_1",
        {
            "status": "reviewed",
            "reviewOutcome": "success",
            "modelResult": "correct",
            "executionResult": "missed",
            "skipReason": "盘中未确认仓位",
            "reviewNotes": "模型判断正确，但没有执行",
        },
    )

    assert row["status"] == "reviewed"
    assert row["modelResult"] == "correct"
    assert row["executionResult"] == "missed"
    assert row["skipReason"] == "盘中未确认仓位"
    assert row["reviewNotes"] == "模型判断正确，但没有执行"


def test_mongo_research_repository_journal_stats_include_status_and_review_breakdowns() -> None:
    db = FakeMongoDatabase()
    repo = MongoResearchRepository(db)
    repo.save_journal_entry(
        TradeJournal(
            id="tj_1",
            stock_code="000001",
            stock_name="a",
            status="candidate",
            review_tags=["主线确认"],
        )
    )
    repo.save_journal_entry(
        TradeJournal(
            id="tj_2",
            stock_code="000002",
            stock_name="b",
            trade_type="exit",
            status="reviewed",
            review_tags=["主线确认", "模型正确"],
            pnl=1200,
            model_result="correct",
            execution_result="missed",
        )
    )

    stats = repo.get_journal_stats()

    assert stats["tagCounts"] == {"主线确认": 2, "模型正确": 1}
    assert stats["statusCounts"] == {"candidate": 1, "reviewed": 1}
    assert stats["modelResultCounts"] == {"unknown": 1, "correct": 1}
    assert stats["executionResultCounts"] == {"unknown": 1, "missed": 1}
    assert stats["totalPnl"] == 1200
    assert stats["winRate"] == 1
    assert stats["totalExits"] == 1


def test_backtest_service_runs_on_mongodb_snapshots_without_historical_research(monkeypatch) -> None:
    import backend.data.repository_factory as factory
    import backend.services as services

    db = FakeMongoDatabase()
    _seed_snapshot_frames(db)

    monkeypatch.setattr(factory, "get_settings", lambda: type("Settings", (), {"storage_backend": "mongodb"})())
    monkeypatch.setattr(factory, "get_runtime_mongodb_database", lambda: db)
    monkeypatch.setattr(services, "storage_source_label", lambda: "mongodb")

    service = services.BacktestService(None)
    response = service.run_ranktrend({"datasetId": "ds_1", "snapshotType": "half_hour", "enableTradeSimulation": True})
    run_id = response["runId"]

    assert db["backtest_runs"].count_documents({}) == 1
    assert service.get_run(run_id)["datasetId"] == "ds_1"
    assert service.get_trades(run_id)["source"] == "mongodb"
    assert service.get_equity(run_id)["source"] == "mongodb"
    assert service.get_signals(run_id)["source"] == "mongodb"
    assert service.get_quality(run_id)["qualityReport"]["frameCount"] == 3


def _signal(code: str, rank: int, tier: str, regime: str) -> dict[str, Any]:
    return {
        "snapshotId": "snap_1",
        "tradingDate": "2026-05-12",
        "code": code,
        "name": code,
        "candidateTier": tier,
        "signal": "buy" if tier == "buy" else "watch",
        "confidence": 0.8,
        "rank": rank,
        "stage": "open",
        "regime": regime,
        "reasons": ["rank"],
        "riskFlags": ["none"],
        "mainTheme": "AI",
        "themeHeat": 90.0,
        "themeContribution": 18.0,
        "themeRole": "leader",
        "themeSupportScore": 88.0,
        "themeRiskFlags": ["crowding:low"],
        "themeReasons": ["theme:AI"],
    }


def _factor(snapshot_id: str, rank: int) -> dict[str, Any]:
    return {
        "datasetId": "ds_1",
        "snapshotId": snapshot_id,
        "snapshotType": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "10:00",
        "strategyVersion": "theme-trend-v12",
        "configHash": "hash_theme",
        "randomSeed": 20260430,
        "themeId": "ai",
        "themeName": "AI",
        "heatScore": 88.0,
        "momentumScore": 82.0,
        "breadthScore": 76.0,
        "fundScore": 78.0,
        "leadershipScore": 84.0,
        "correlationScore": 72.0,
        "crowdingRisk": 24.0,
        "persistenceScore": 78.0,
        "rotationState": "mainline",
        "rank": rank,
        "qualityFlags": ["low_sample"],
        "lifecycle": "mainline",
    }


def _exposure(code: str, weight: float) -> dict[str, Any]:
    return {
        "datasetId": "ds_1",
        "snapshotId": "snap_1",
        "snapshotType": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "10:00",
        "strategyVersion": "theme-trend-v12",
        "configHash": "hash_theme",
        "randomSeed": 20260430,
        "code": code,
        "themeId": "ai",
        "themeName": "AI",
        "role": "leader",
        "roleScore": 90.0,
        "exposureWeight": weight,
        "themeContribution": 18.0,
        "riskPenalty": 0.0,
        "reasons": ["role:leader", "theme:mainline"],
    }


def _theme_signal(signal: str, score: float) -> dict[str, Any]:
    return {
        "datasetId": "ds_1",
        "snapshotId": "snap_1",
        "snapshotType": "half_hour",
        "tradingDate": "2026-05-12",
        "slotTime": "10:00",
        "strategyVersion": "theme-trend-v12",
        "configHash": "hash_theme",
        "randomSeed": 20260430,
        "themeId": "ai",
        "themeName": "AI",
        "signal": signal,
        "risk": "none",
        "lifecycle": "mainline",
        "score": score,
    }


def _quality_report() -> dict[str, Any]:
    return {
        "datasetId": "ds_1",
        "snapshotType": "half_hour",
        "strategyVersion": "theme-trend-v12",
        "configHash": "hash_theme",
        "randomSeed": 20260430,
        "passed": False,
        "severity": "warn",
        "researchGrade": "degraded",
        "issues": ["low_coverage"],
        "warnings": ["low_sample"],
        "stats": {"totalFrames": 2},
        "themeCoverage": 0.5,
        "frameCount": 2,
        "stockCount": 100,
        "themeCount": 8,
    }


def _seed_snapshot_frames(db: FakeMongoDatabase) -> None:
    frames = []
    stock_rows = []
    for index, slot_time in enumerate(("09:30", "10:00", "10:30"), start=1):
        snapshot_id = f"s{index}"
        timestamp = 1_778_520_000 + index * 1_800
        frames.append(
            {
                "datasetId": "ds_1",
                "snapshotId": snapshot_id,
                "type": "half_hour",
                "tradingDate": "2026-05-12",
                "slotTime": slot_time,
                "timestamp": timestamp,
                "captureMode": "real_time",
                "stockRowCount": 20,
            }
        )
        for rank in range(1, 21):
            stock_rows.append(
                {
                    "datasetId": "ds_1",
                    "snapshotId": snapshot_id,
                    "timestamp": timestamp,
                    "rank": rank,
                    "code": f"000{rank:03d}",
                    "name": f"stock-{rank}",
                    "price": 10 + rank + index / 10,
                    "changePct": rank / 100,
                    "volume": 10000 + rank,
                    "amount": 100000 + rank,
                    "moneyFlowSource": "formal",
                    "moneyFlowConfidence": 1,
                }
            )
    db["snapshot_frames"].insert_many(frames, ordered=False)
    db["snapshot_stock_rows"].insert_many(stock_rows, ordered=False)


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        value = row.get(key)
        if isinstance(expected, dict):
            if "$in" in expected and value not in expected["$in"]:
                return False
            if "$gte" in expected and value < expected["$gte"]:
                return False
            if "$lte" in expected and value > expected["$lte"]:
                return False
            if "$lt" in expected and value >= expected["$lt"]:
                return False
            if "$ne" in expected and value == expected["$ne"]:
                return False
            continue
        if value != expected:
            return False
    return True
