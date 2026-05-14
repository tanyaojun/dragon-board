from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import journal_routes
from backend.main import app


class FakeJournalRepo:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def save_journal_entry(self, entry):
        row = entry.to_dict()
        self.rows[row["id"]] = row
        return entry

    def get_journal_entry(self, entry_id: str):
        return self.rows.get(entry_id)

    def list_journal_entries(self, status=None, limit=50, offset=0, **_kwargs):
        rows = list(self.rows.values())
        if status:
            rows = [row for row in rows if row.get("status") == status]
        return rows[offset : offset + limit]

    def count_journal_entries(self, status=None, **_kwargs):
        return len(self.list_journal_entries(status=status, limit=10_000, offset=0))

    def update_journal_entry(self, entry_id: str, updates: dict):
        self.rows[entry_id].update(updates)
        return self.rows[entry_id]


def test_create_candidate_thesis_entry_round_trips_core_fields(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)

    response = client.post(
        "/api/journal/entries",
        json={
            "stock_code": "000001",
            "stock_name": "平安银行",
            "status": "candidate",
            "market_phase": "repair",
            "theme_role": "mainline",
            "stock_role": "core",
            "entry_reason": "RankTrend 持续上行，题材扩散，情绪修复",
            "trade_hypothesis": "未来 3-5 天沿主线继续走强",
            "entry_prerequisites": "次日不弱于题材，排名不明显回落",
            "invalidation_rules": "题材退潮或 RankTrend 断档",
            "expected_holding_days": 3,
            "human_decision": "watch",
            "signals_snapshot": {"rankTrend": {"candidateTier": "B_IGNITION"}},
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "candidate"
    assert data["marketPhase"] == "repair"
    assert data["themeRole"] == "mainline"
    assert data["stockRole"] == "core"
    assert data["tradeHypothesis"] == "未来 3-5 天沿主线继续走强"
    assert data["price"] == 0
    assert data["volume"] == 0


def test_update_candidate_thesis_review_separates_model_and_execution_result(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)
    created = client.post(
        "/api/journal/entries",
        json={"stock_code": "000002", "stock_name": "万科A", "status": "triggered"},
    ).json()

    response = client.put(
        f"/api/journal/entries/{created['id']}",
        json={
            "status": "reviewed",
            "review_outcome": "success",
            "model_result": "correct",
            "execution_result": "missed",
            "skip_reason": "盘中未确认仓位",
            "review_notes": "模型判断正确，但没有执行",
            "review_tags": ["信号正确未执行"],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "reviewed"
    assert data["reviewOutcome"] == "success"
    assert data["modelResult"] == "correct"
    assert data["executionResult"] == "missed"
    assert data["skipReason"] == "盘中未确认仓位"
    assert data["reviewNotes"] == "模型判断正确，但没有执行"
    assert data["reviewTags"] == ["信号正确未执行"]


def test_list_candidate_entries_can_filter_by_status(monkeypatch) -> None:
    repo = FakeJournalRepo()
    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: repo)
    client = TestClient(app)
    client.post("/api/journal/entries", json={"stock_code": "000003", "stock_name": "测试候选", "status": "candidate"})
    client.post("/api/journal/entries", json={"stock_code": "000004", "stock_name": "测试复盘", "status": "reviewed"})

    response = client.get("/api/journal/entries?status=candidate")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["entries"][0]["status"] == "candidate"


def test_journal_routes_report_structured_error_when_storage_is_not_mongodb(monkeypatch) -> None:
    class NonJournalRepo:
        pass

    monkeypatch.setattr(journal_routes, "create_repository", lambda *_args, **_kwargs: NonJournalRepo())
    client = TestClient(app)

    response = client.get("/api/journal/entries")

    assert response.status_code == 503
    assert response.json()["detail"] == "journal requires MongoDB storage backend"
