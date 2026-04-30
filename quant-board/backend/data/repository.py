from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.data.models import (
    BacktestRun,
    Dataset,
    GoldenRankTrendCase,
    OptimizationRun,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
)
from backend.utils import json_dumps, json_loads


class Repository:
    def __init__(self, session: Session):
        self.session = session

    def list_datasets(self) -> list[Dataset]:
        return list(self.session.scalars(select(Dataset).order_by(Dataset.created_at.desc())))

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        return self.session.get(Dataset, dataset_id)

    def delete_dataset_children(self, dataset_id: str) -> None:
        for model in [SnapshotSectorRowModel, SnapshotStockRowModel, SnapshotFrameModel, SnapshotRecordModel]:
            self.session.execute(delete(model).where(model.dataset_id == dataset_id))

    def save_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> Dataset:
        self.session.merge(dataset)
        self.delete_dataset_children(dataset.id)

        self.session.add_all([self._record_model(dataset.id, item) for item in records])
        self.session.add_all([self._frame_model(dataset.id, item) for item in frames])
        self.session.add_all([self._stock_model(dataset.id, item) for item in stock_rows])
        self.session.add_all([self._sector_model(dataset.id, item) for item in sector_rows])
        self.session.commit()
        saved = self.session.get(Dataset, dataset.id)
        return saved or dataset

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        frame_models = list(self.session.scalars(query.order_by(SnapshotFrameModel.timestamp.asc())))

        snapshot_ids = [frame.snapshot_id for frame in frame_models]
        rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if snapshot_ids:
            row_query = (
                select(SnapshotStockRowModel)
                .where(
                    SnapshotStockRowModel.dataset_id == dataset_id,
                    SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                )
                .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
            )
            for row in self.session.scalars(row_query):
                rows_by_snapshot[row.snapshot_id].append(self.stock_row_to_dict(row, include_payload=include_payload))

        frames: list[dict[str, Any]] = []
        for frame in frame_models:
            item = self.frame_to_dict(frame)
            item["stocks"] = rows_by_snapshot.get(frame.snapshot_id, [])
            frames.append(item)
        return frames

    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        self.session.merge(run)
        self.session.commit()
        return run

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        return self.session.get(BacktestRun, run_id)

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        self.session.merge(run)
        self.session.commit()
        return run

    def get_optimization_run(self, run_id: str) -> OptimizationRun | None:
        return self.session.get(OptimizationRun, run_id)

    def save_golden_case(self, case: GoldenRankTrendCase) -> GoldenRankTrendCase:
        self.session.merge(case)
        self.session.commit()
        return case

    def get_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        return self.session.get(GoldenRankTrendCase, case_id)

    @staticmethod
    def dataset_to_dict(model: Dataset) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "source_type": model.source_type,
            "source_path": model.source_path,
            "db_name": model.db_name,
            "schema_fingerprint": model.schema_fingerprint,
            "snapshot_count": model.snapshot_count,
            "frame_count": model.frame_count,
            "stock_row_count": model.stock_row_count,
            "sector_row_count": model.sector_row_count,
            "start_date": model.start_date,
            "end_date": model.end_date,
            "snapshot_types": json_loads(model.snapshot_types_json, []),
            "metadata": json_loads(model.metadata_json, {}),
            "created_at": model.created_at.isoformat(),
        }

    @staticmethod
    def frame_to_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = json_loads(model.market_context_json, {})
        return {
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "type": model.type,
            "captureMode": model.capture_mode,
            "source": model.source,
            "marketContext": context,
            "stocks": [],
        }

    @staticmethod
    def stock_row_to_dict(model: SnapshotStockRowModel, include_payload: bool = True) -> dict[str, Any]:
        payload = json_loads(model.payload_json, {}) if include_payload else {}
        payload.update(
            {
                "code": model.code,
                "name": model.name,
                "rank": model.rank,
                "price": model.price,
                "change": model.change,
                "volumeRatio": model.volume_ratio,
                "zlje": model.zlje,
                "zljzb": model.zljzb,
                "turnover": model.turnover,
                "turnoverRate": model.turnover_rate,
            }
        )
        return payload

    @staticmethod
    def _record_model(dataset_id: str, item: dict[str, Any]) -> SnapshotRecordModel:
        return SnapshotRecordModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("id") or item.get("snapshotId")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            display_key=str(item.get("displayKey") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            payload_json=json_dumps(item.get("payload") or item),
        )

    @staticmethod
    def _frame_model(dataset_id: str, item: dict[str, Any]) -> SnapshotFrameModel:
        context = {
            "marketStats": item.get("marketStats"),
            "sentiment": item.get("sentiment"),
            "moneyFlow": item.get("moneyFlow"),
            "indices": item.get("indices"),
            "limitSummary": item.get("limitSummary"),
            "rotationSummary": item.get("rotationSummary"),
            "payload": item.get("payload"),
        }
        return SnapshotFrameModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("snapshotId") or item.get("id")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            market_context_json=json_dumps(context),
            stock_row_count=int(item.get("stockRowCount") or 0),
            sector_row_count=int(item.get("sectorRowCount") or 0),
        )

    @staticmethod
    def _stock_model(dataset_id: str, item: dict[str, Any]) -> SnapshotStockRowModel:
        row_id = str(item.get("id") or f"{item.get('snapshotId')}:{item.get('code')}")
        return SnapshotStockRowModel(
            dataset_id=dataset_id,
            row_id=row_id,
            snapshot_id=str(item.get("snapshotId") or ""),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            capture_mode=str(item.get("captureMode") or "real_time"),
            code=str(item.get("code") or ""),
            name=str(item.get("name") or item.get("code") or ""),
            rank=int(float(item.get("rank") or item.get("compRank") or 0)),
            price=_maybe_float(item.get("price")),
            change=_maybe_float(item.get("change")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zlje=_maybe_float(item.get("zlje")),
            zljzb=_maybe_float(item.get("zljzb")),
            turnover=_maybe_float(item.get("turnover")),
            turnover_rate=_maybe_float(item.get("turnoverRate")),
            payload_json=json_dumps(item),
        )

    @staticmethod
    def _sector_model(dataset_id: str, item: dict[str, Any]) -> SnapshotSectorRowModel:
        row_id = str(item.get("id") or f"{item.get('snapshotId')}:{item.get('entityType')}:{item.get('entityKey')}")
        return SnapshotSectorRowModel(
            dataset_id=dataset_id,
            row_id=row_id,
            snapshot_id=str(item.get("snapshotId") or ""),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            entity_type=str(item.get("entityType") or ""),
            entity_key=str(item.get("entityKey") or ""),
            entity_name=str(item.get("entityName") or ""),
            rank=int(float(item.get("rank") or 0)),
            payload_json=json_dumps(item),
        )


def _maybe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
