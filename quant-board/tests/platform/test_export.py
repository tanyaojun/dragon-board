"""Backtest report export tests (jsonl-bundle / json.gz / legacy) and the
cmd_export_report dispatcher.

Extracted from tests/test_quant_board.py.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services import BacktestService

from tests.fixtures.helpers import (
    ExportReportNoAggregateGzipRepo,
    ExportReportNoAggregateRepo,
    ExportReportRepo,
    _make_export_run,
)


def test_export_report_bundle_writes_small_bundle(tmp_path: Path) -> None:
    service = BacktestService(None)
    service.repo = ExportReportRepo(
        runs={"bt_1": _make_export_run("bt_1")},
        signals={"bt_1": [{"sequence": 1, "code": "000001"}, {"sequence": 2, "code": "000002"}]},
        trades={"bt_1": [{"sequence": 1, "code": "000001"}]},
        equity_curves={"bt_1": [{"sequence": 1, "timestamp": "t1"}]},
        quality_reports={"bt_1": {"severity": "pass"}},
    )

    summary = service.export_report_bundle("bt_1", tmp_path / "bt_1")

    assert summary["ok"] is True
    assert summary["format"] == "jsonl-bundle"
    assert (tmp_path / "bt_1" / "manifest.json").exists()
    assert (tmp_path / "bt_1" / "signals.jsonl").exists()
    assert (tmp_path / "bt_1" / "trades.jsonl").exists()
    assert (tmp_path / "bt_1" / "equity_curve.jsonl").exists()
    assert (tmp_path / "bt_1" / "quality_report.json").exists()

    manifest = json.loads((tmp_path / "bt_1" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["runId"] == "bt_1"
    assert manifest["files"]["signals"]["rows"] == 2
    assert manifest["files"]["qualityReport"]["path"] == "quality_report.json"


def test_export_report_bundle_streams_large_signal_rows_without_full_aggregate(tmp_path: Path) -> None:
    service = BacktestService(None)
    service.repo = ExportReportNoAggregateRepo(
        runs={"bt_large": _make_export_run("bt_large", {"totalReturn": 0.2, "tradeCount": 100_000})},
        signals={"bt_large": ({"sequence": index + 1, "code": f"{index:06d}"} for index in range(100_000))},
        trades={"bt_large": []},
        equity_curves={"bt_large": []},
        quality_reports={"bt_large": {"severity": "pass"}},
    )

    summary = service.export_report_bundle("bt_large", tmp_path / "bt_large")
    manifest = json.loads((tmp_path / "bt_large" / "manifest.json").read_text(encoding="utf-8"))

    assert summary["format"] == "jsonl-bundle"
    assert manifest["files"]["signals"]["rows"] == 100_000
    with (tmp_path / "bt_large" / "signals.jsonl").open("r", encoding="utf-8") as handle:
        assert sum(1 for _ in handle) == 100_000


def test_export_report_bundle_does_not_publish_manifest_when_write_fails(tmp_path: Path) -> None:
    def broken_rows():
        yield {"sequence": 1}
        raise RuntimeError("simulated export failure")

    service = BacktestService(None)
    service.repo = ExportReportRepo(
        runs={"bt_broken": _make_export_run("bt_broken")},
        signals={"bt_broken": broken_rows()},
        trades={"bt_broken": []},
        equity_curves={"bt_broken": []},
        quality_reports={"bt_broken": {}},
    )

    with pytest.raises(RuntimeError, match="simulated export failure"):
        service.export_report_bundle("bt_broken", tmp_path / "bt_broken")

    assert not (tmp_path / "bt_broken" / "manifest.json").exists()


def test_export_report_gzip_writes_single_file_payload(tmp_path: Path) -> None:
    service = BacktestService(None)
    service.repo = ExportReportNoAggregateGzipRepo(
        runs={"bt_1": _make_export_run("bt_1")},
        signals={"bt_1": [{"sequence": 1, "code": "000001"}, {"sequence": 2, "code": "000002"}]},
        trades={"bt_1": [{"sequence": 1, "code": "000001"}]},
        equity_curves={"bt_1": [{"sequence": 1, "timestamp": "t1"}]},
        quality_reports={"bt_1": {"severity": "pass"}},
    )

    summary = service.export_report_gzip("bt_1", tmp_path / "bt_1.json.gz")

    assert summary["ok"] is True
    assert summary["format"] == "json.gz"
    with gzip.open(tmp_path / "bt_1.json.gz", "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    assert payload["runId"] == "bt_1"
    assert "qualityReport" in payload
    assert [row["sequence"] for row in payload["signals"]] == [1, 2]


def test_export_report_gzip_creates_parent_directory(tmp_path: Path) -> None:
    service = BacktestService(None)
    service.repo = ExportReportRepo(
        runs={"bt_nested": _make_export_run("bt_nested")},
        signals={"bt_nested": []},
        trades={"bt_nested": []},
        equity_curves={"bt_nested": []},
        quality_reports={"bt_nested": {"severity": "pass"}},
    )

    output = tmp_path / "nested" / "reports" / "bt_nested.json.gz"
    summary = service.export_report_gzip("bt_nested", output)

    assert summary["ok"] is True
    assert output.exists()


def test_cmd_export_report_dispatches_by_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[str, str, str]] = []
    printed: list[dict[str, Any]] = []

    class FakeService:
        def __init__(self, session) -> None:
            self.session = session

        def export_report_bundle(self, run_id: str, output: Path) -> dict[str, Any]:
            calls.append(("bundle", run_id, str(output)))
            return {"ok": True, "format": "jsonl-bundle", "runId": run_id}

        def export_report_gzip(self, run_id: str, output: Path) -> dict[str, Any]:
            calls.append(("gzip", run_id, str(output)))
            return {"ok": True, "format": "json.gz", "runId": run_id}

        def export_report(self, run_id: str) -> dict[str, Any] | None:
            calls.append(("legacy", run_id, ""))
            return {"runId": run_id, "qualityReport": {}, "signals": [], "trades": [], "equityCurve": []}

    monkeypatch.setattr("backend.cli.BacktestService", FakeService)
    monkeypatch.setattr("backend.cli.print_json", lambda payload: printed.append(payload))

    from backend.cli import cmd_export_report

    cmd_export_report(SimpleNamespace(run_id="bt_bundle", output=str(tmp_path / "bundle"), format="jsonl-bundle"))
    cmd_export_report(SimpleNamespace(run_id="bt_gzip", output=str(tmp_path / "report.json.gz"), format="json.gz"))
    cmd_export_report(SimpleNamespace(run_id="bt_legacy", output=str(tmp_path / "report.json"), format="legacy-json"))

    assert calls == [
        ("bundle", "bt_bundle", str(tmp_path / "bundle")),
        ("gzip", "bt_gzip", str(tmp_path / "report.json.gz")),
        ("legacy", "bt_legacy", ""),
    ]
    assert printed[0]["format"] == "jsonl-bundle"
    assert printed[1]["format"] == "json.gz"
    assert printed[2]["format"] == "legacy-json"
