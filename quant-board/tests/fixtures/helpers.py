"""Shared test helpers for the quant-board test suite.

Extracted from the former tests/test_quant_board.py so topic-focused test
modules can reuse them without duplication.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

from fastapi.testclient import TestClient

from backend.core.utils import json_dumps
from backend.data.models.models import BacktestRun, Dataset
from backend.data.repositories.mongo_repository import MongoRepository


def wait_for_optimization(client: TestClient, run_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    last: dict | None = None
    while time.time() < deadline:
        response = client.get(f"/api/optimizations/{run_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in {"completed", "failed"}:
            return last
        time.sleep(0.1)
    raise AssertionError(f"optimization did not finish: {last}")


def make_bundle(path: Path) -> Path:
    frames = []
    records = []
    for i in range(35):
        day = i // 7 + 1
        bar = i % 7
        date = f"2026-04-{day:02d}"
        slot = f"{10 + (bar // 2):02d}:{(bar % 2) * 30:02d}"
        snapshot_id = f"half_hour:{date}:{i:02d}"
        hotlist = [
            {
                "code": "600001",
                "name": "样本A",
                "rank": max(1, 50 - i),
                "avgRankNum": max(1, 50 - i),
                "price": 10 + i * 0.1,
                "change": 1,
                "volumeRatio": 1.3,
                "zlje": 1000000,
                "zljzb": 3,
            },
            {
                "code": "600002",
                "name": "样本B",
                "rank": 20 + (i % 5),
                "avgRankNum": 20 + (i % 5),
                "price": 20 - i * 0.03,
                "change": -0.5,
                "volumeRatio": 0.9,
                "zlje": -100000,
                "zljzb": -1,
            },
        ]
        if i in {3, 10}:
            hotlist = hotlist[:1]
        record = {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": date,
            "slotTime": slot,
            "timestamp": 1775000000000 + i * 1800000,
            "captureMode": "real_time",
            "payload": {"type": "half_hour", "tradingDate": date, "slotTime": slot, "timestamp": 1775000000000 + i * 1800000, "hotlist": hotlist},
        }
        records.append(record)
    bundle = path / "bundle.json"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_bundle_with_empty_hotlist(path: Path) -> Path:
    bundle = make_bundle(path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    records = data["records"]
    for index in {8, 15, 22}:
        records[index]["payload"]["hotlist"] = []
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_bundle_with_synthesized_empty_hotlist(path: Path) -> Path:
    bundle = make_bundle(path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    records = data["records"]
    for index in {8, 15, 22}:
        records[index]["payload"]["hotlist"] = []
        records[index]["captureMode"] = "synthesized"
        records[index]["payload"]["captureMode"] = "synthesized"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_bundle_with_one_positive_price_frame(path: Path) -> Path:
    bundle = make_bundle(path)
    data = json.loads(bundle.read_text(encoding="utf-8"))
    records = data["records"]
    for index, record in enumerate(records):
        for stock in record["payload"]["hotlist"]:
            stock["price"] = 0 if index else 10
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def make_theme_trade_bundle(path: Path) -> Path:
    frames = []
    records = []
    for i in range(8):
        date = f"2026-04-{1 + i // 4:02d}"
        slot = f"{10 + (i % 4) // 2:02d}:{((i % 4) % 2) * 30:02d}"
        snapshot_id = f"half_hour:{date}:theme:{i:02d}"
        hotlist = [
            {
                "code": "600001",
                "name": "题材龙头",
                "rank": 1,
                "price": 10 + i * 0.2,
                "lastTradePrice": 10 + i * 0.2,
                "change": 1.2,
                "volume": 10000000,
                "turnover": 100000000,
                "volumeRatio": 2.2,
                "zlje": 3000000,
                "zljzb": 6,
                "mainTheme": "机器人",
                "themeRole": "leader",
                "themeContribution": 20,
                "themeExposureWeight": 88,
            }
        ]
        sectors = [
            {
                "name": "机器人",
                "entityName": "机器人",
                "entityKey": "robot",
                "rank": 1,
                "heatScore": 86,
                "momentumScore": 82,
                "breadthScore": 68,
                "fundScore": 70,
                "leadershipScore": 85,
                "correlationScore": 65,
                "crowdingRisk": 35,
                "persistenceScore": 72,
                "rotationState": "mainline",
            }
        ]
        record = {
            "id": snapshot_id,
            "type": "half_hour",
            "tradingDate": date,
            "slotTime": slot,
            "timestamp": 1775000000000 + i * 1800000,
            "captureMode": "real_time",
            "payload": {
                "type": "half_hour",
                "tradingDate": date,
                "slotTime": slot,
                "timestamp": 1775000000000 + i * 1800000,
                "hotlist": hotlist,
                "sectors": sectors,
            },
        }
        records.append(record)
    bundle = path / "theme_trade_bundle.json"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


def add_theme_follower_to_bundle(bundle: Path) -> None:
    data = json.loads(bundle.read_text(encoding="utf-8"))
    for record in data["records"]:
        record["payload"]["hotlist"].append(
            {
                "code": "600002",
                "name": "题材跟随",
                "rank": 2,
                "price": 9.5,
                "lastTradePrice": 9.5,
                "change": 0.8,
                "volume": 8000000,
                "turnover": 80000000,
                "volumeRatio": 1.5,
                "zlje": 1000000,
                "zljzb": 3,
                "mainTheme": "机器人",
                "themeRole": "follower",
                "themeContribution": 6,
                "themeExposureWeight": 62,
            }
        )
    bundle.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_theme_sg_bundle(path: Path) -> Path:
    """SG 变体合同测试夹具（Phase R3）：3 交易日 × 2 槽（10:30/15:00）。

    题材"机器人" rotationState 序列（15:00 槽）：d1=outflow → d2=inflow（SG2 触发）
    → d3=inflow；mainLines：d1=[]（引擎判定无主线）、d2 键缺失（缺失打标）、
    d3=[机器人]（引擎主线日）。
    """
    rotation_states = {"2026-04-01": "outflow", "2026-04-02": "inflow", "2026-04-03": "inflow"}
    main_lines = {
        "2026-04-01": [],
        # entityName 与 themeName 同值：SQLite H4 会把 mainLines 派生为 rotation_main_line
        # 行（视图 themeName=entityName），缺 entityName 会退化为 rotation_main_line_0
        "2026-04-03": [{"themeId": "robot", "themeName": "机器人", "entityName": "机器人", "rotationScore": 60, "rotationState": "mainline", "rankChange": 0}],
    }
    records = []
    index = 0
    for date in ("2026-04-01", "2026-04-02", "2026-04-03"):
        for slot in ("10:30", "15:00"):
            snapshot_id = f"half_hour:{date}:sg:{index:02d}"
            sectors = [
                {
                    "name": "机器人",
                    "entityName": "机器人",
                    "entityKey": "robot",
                    "rank": 1,
                    "heatScore": 86,
                    "momentumScore": 82,
                    "breadthScore": 68,
                    "fundScore": 70,
                    "leadershipScore": 85,
                    "correlationScore": 65,
                    "crowdingRisk": 35,
                    "persistenceScore": 72,
                    "rotationState": rotation_states[date],
                }
            ]
            hotlist = [
                {
                    "code": "600001",
                    "name": "题材龙头",
                    "rank": 1,
                    "price": 10 + index * 0.5,
                    "lastTradePrice": 10 + index * 0.5,
                    "change": 1.2,
                    "volume": 10000000,
                    "turnover": 100000000,
                    "volumeRatio": 2.2,
                    "zlje": 3000000,
                    "zljzb": 6,
                    "mainTheme": "机器人",
                    "themeRole": "leader",
                    "themeContribution": 20,
                    "themeExposureWeight": 88,
                }
            ]
            payload = {
                "type": "half_hour",
                "tradingDate": date,
                "slotTime": slot,
                "timestamp": 1775000000000 + index * 1800000,
                "hotlist": hotlist,
                "sectors": sectors,
            }
            if slot == "15:00":
                rotation_summary: dict[str, object] = {"marketPhase": "chaos"}
                if date in main_lines:
                    rotation_summary["mainLines"] = main_lines[date]
                payload["rotationSummary"] = rotation_summary
            records.append(
                {
                    "id": snapshot_id,
                    "type": "half_hour",
                    "tradingDate": date,
                    "slotTime": slot,
                    "timestamp": 1775000000000 + index * 1800000,
                    "captureMode": "real_time",
                    "payload": payload,
                }
            )
            index += 1
    bundle = path / "theme_sg_bundle.json"
    bundle.write_text(json.dumps({"records": records}, ensure_ascii=False), encoding="utf-8")
    return bundle


class MemoryBackup:
    last_error = None

    def __init__(self) -> None:
        self.datasets: dict[str, Dataset] = {}
        self.frames: dict[str, list[dict[str, object]]] = {}
        self.fail_writes = False

    def mirror_dataset_bundle(self, dataset, records, frames, stock_rows, sector_rows):
        if self.fail_writes:
            self.last_error = "backup offline"
            return False
        self.datasets[dataset.id] = dataset
        self.frames[dataset.id] = [
            {
                "payload": {"frame": frame, "stocks": [row for row in stock_rows if row.get("snapshotId") == frame.get("snapshotId")]},
                "timestamp": frame.get("timestamp") or 0,
            }
            for frame in frames
        ]
        return True

    def list_rows(self, record_type, source=None, page_size=500):
        if record_type == "qb_dataset":
            return [{"payload": {"dataset": MongoRepository.dataset_to_dict(dataset)}, "display_key": dataset.id} for dataset in self.datasets.values()]
        if record_type == "qb_snapshot_bundle":
            return list(self.frames.get(source, []))
        return []

    def get_row(self, record_type, display_key, source=None):
        if record_type == "qb_dataset" and display_key in self.datasets:
            dataset = self.datasets[display_key]
            return {"payload": {"dataset": MongoRepository.dataset_to_dict(dataset)}, "display_key": dataset.id}
        return None

    def dataset_from_row(self, row):
        payload = row["payload"]["dataset"]
        return Dataset(
            id=payload["id"],
            name=payload["name"],
            source_type=payload["source_type"],
            source_path=payload["source_path"],
            db_name=payload["db_name"],
            schema_fingerprint=payload["schema_fingerprint"],
            snapshot_count=payload["snapshot_count"],
            frame_count=payload["frame_count"],
            stock_row_count=payload["stock_row_count"],
            sector_row_count=payload["sector_row_count"],
            start_date=payload["start_date"],
            end_date=payload["end_date"],
            snapshot_types_json=json_dumps(payload["snapshot_types"]),
            metadata_json=json_dumps(payload["metadata"]),
        )


class ExportReportRepo:
    def __init__(
        self,
        *,
        runs: dict[str, BacktestRun],
        signals: dict[str, Iterable[dict[str, Any]]],
        trades: dict[str, Iterable[dict[str, Any]]],
        equity_curves: dict[str, Iterable[dict[str, Any]]],
        quality_reports: dict[str, dict[str, Any] | None],
    ) -> None:
        self.runs = runs
        self.signals = signals
        self.trades = trades
        self.equity_curves = equity_curves
        self.quality_reports = quality_reports

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        return self.runs.get(run_id)

    def iter_backtest_signals(self, run_id: str, batch_size: int = 1000):
        yield from self.signals.get(run_id, [])

    def iter_backtest_trades(self, run_id: str, batch_size: int = 1000):
        yield from self.trades.get(run_id, [])

    def iter_backtest_equity_curve(self, run_id: str, batch_size: int = 1000):
        yield from self.equity_curves.get(run_id, [])

    def get_backtest_quality_report(self, run_id: str) -> dict[str, Any] | None:
        return self.quality_reports.get(run_id)


class ExportReportNoAggregateRepo(ExportReportRepo):
    def get_backtest_signals(self, run_id: str, limit: int | None = None, offset: int = 0):
        raise AssertionError("bundle export should not call get_backtest_signals")

    def get_backtest_trades(self, run_id: str, limit: int | None = None, offset: int = 0):
        raise AssertionError("bundle export should not call get_backtest_trades")

    def get_backtest_equity_curve(self, run_id: str):
        raise AssertionError("bundle export should not call get_backtest_equity_curve")


class ExportReportNoAggregateGzipRepo(ExportReportNoAggregateRepo):
    def iter_backtest_signals(self, run_id: str, batch_size: int = 1000):
        yield from self.signals.get(run_id, [])

    def iter_backtest_trades(self, run_id: str, batch_size: int = 1000):
        yield from self.trades.get(run_id, [])

    def iter_backtest_equity_curve(self, run_id: str, batch_size: int = 1000):
        yield from self.equity_curves.get(run_id, [])


def _make_export_run(run_id: str, result: dict[str, Any] | None = None) -> BacktestRun:
    return BacktestRun(
        id=run_id,
        dataset_id="ds_export",
        strategy_name="rank_trend_candidate",
        strategy_version="0.1.0",
        snapshot_type="half_hour",
        config_hash=f"cfg_{run_id}",
        random_seed=20260430,
        status="completed",
        request_json=json_dumps({"datasetId": "ds_export", "runId": run_id}),
        result_json=json_dumps(result or {"totalReturn": 0.12, "tradeCount": 2, "winRate": 0.5}),
    )


class BacktestRepoWriter:
    """回测造数器：直写 MongoResearchRepository（测试库 dragon_board_test）。

    sqlite 分支已随 2026-09-29 sqlite 链退役删除。
    """

    def __init__(self) -> None:
        from backend.data.repositories.mongo_research_repository import (
            MongoResearchRepository,
        )
        from backend.data.repositories.repository_factory import (
            get_runtime_mongodb_database,
        )

        self._session = None
        self._repo = MongoResearchRepository(get_runtime_mongodb_database())

    def save_run(self, run: BacktestRun) -> None:
        self._repo.save_backtest_run(run)

    def save_trades(self, run_id: str, trades: list[dict[str, Any]]) -> None:
        self._repo.save_backtest_trades(run_id, trades)

    def save_equity_curve(self, run_id: str, curve: list[dict[str, Any]]) -> None:
        self._repo.save_backtest_equity_curve(run_id, curve)

    def save_signals(self, run_id: str, decisions: dict[str, Any]) -> None:
        self._repo.save_backtest_signals(run_id, decisions)

    def save_quality_report(
        self, run_id: str, data_quality: dict[str, Any], quality_gate: dict[str, Any]
    ) -> None:
        self._repo.save_backtest_quality_report(run_id, data_quality, quality_gate)

    def delete_run(self, run_id: str) -> None:
        self._repo.delete_backtest_run(run_id)

    def close(self) -> None:  # 兼容 with 语法的历史调用
        return None

    def __enter__(self) -> "BacktestRepoWriter":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def strip_dataset_id(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """mongodb 读链会在 executionSignals 行内注入 datasetId（sqlite 链不会），
    跨轮回测比较信号需剥离该字段。"""
    return [{k: v for k, v in row.items() if k != "datasetId"} for row in signals]
