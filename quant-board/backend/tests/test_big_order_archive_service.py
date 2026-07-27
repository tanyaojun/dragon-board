from __future__ import annotations

import gzip
import json
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import big_order_history_routes
from backend.big_order_archive_service import BigOrderArchiveError, BigOrderArchiveService


def _write_archive(path, payload: dict) -> None:
    path.parent.mkdir(parents=True)
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False)


def test_loads_exact_longhu_gzip_archive(tmp_path):
    payload = {
        "source": "longhu",
        "sessionDate": "2026-07-24",
        "stockCode": "002297",
        "data": {"List": []},
    }
    _write_archive(
        tmp_path / "longhu" / "2026-07-24" / "002297.money0.json.gz",
        payload,
    )

    result = BigOrderArchiveService(tmp_path).load(
        "longhu", "002297", date(2026, 7, 24)
    )

    assert result == payload


def test_loads_exact_ths_gzip_archive(tmp_path):
    payload = {
        "source": "ths",
        "sessionDate": "2026-07-24",
        "stockCode": "002297",
        "data": {"title": {}, "list": [], "pricechange": []},
    }
    _write_archive(tmp_path / "ths" / "2026-07-24" / "002297.json.gz", payload)

    result = BigOrderArchiveService(tmp_path).load(
        "ths", "002297", date(2026, 7, 24)
    )

    assert result == payload


def test_missing_archive_does_not_fall_back_to_another_date(tmp_path):
    _write_archive(
        tmp_path / "longhu" / "2026-07-23" / "002297.money0.json.gz",
        {
            "source": "longhu",
            "sessionDate": "2026-07-23",
            "stockCode": "002297",
            "data": {"List": []},
        },
    )

    with pytest.raises(BigOrderArchiveError) as error:
        BigOrderArchiveService(tmp_path).load(
            "longhu", "002297", date(2026, 7, 24)
        )

    assert error.value.code == "archive_not_found"


@pytest.mark.parametrize(
    ("source", "stock_code"),
    [("other", "002297"), ("longhu", "../2297"), ("ths", "00229")],
)
def test_rejects_invalid_archive_selector(tmp_path, source, stock_code):
    with pytest.raises(BigOrderArchiveError) as error:
        BigOrderArchiveService(tmp_path).load(
            source, stock_code, date(2026, 7, 24)
        )

    assert error.value.code == "invalid_request"


def test_rejects_archive_metadata_for_another_session(tmp_path):
    _write_archive(
        tmp_path / "ths" / "2026-07-24" / "002297.json.gz",
        {
            "source": "ths",
            "sessionDate": "2026-07-23",
            "stockCode": "002297",
            "data": {"title": {}, "list": [], "pricechange": []},
        },
    )

    with pytest.raises(BigOrderArchiveError) as error:
        BigOrderArchiveService(tmp_path).load("ths", "002297", date(2026, 7, 24))

    assert error.value.code == "archive_invalid"


def test_history_route_returns_structured_archive_not_found(monkeypatch):
    class MissingService:
        def load(self, source, stock_code, session_date):
            raise BigOrderArchiveError("archive_not_found", "missing")

    monkeypatch.setattr(big_order_history_routes, "BigOrderArchiveService", MissingService)
    app = FastAPI()
    app.include_router(big_order_history_routes.router)

    response = TestClient(app).get(
        "/api/big-order/history",
        params={
            "source": "ths",
            "stockCode": "002297",
            "sessionDate": "2026-07-24",
        },
    )

    assert response.status_code == 404
    assert response.json()["errorCode"] == "archive_not_found"
