from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import SQLAlchemyError

from backend.data.models.models import (
    Dataset,
    SnapshotFrameModel,
    SnapshotRecordModel,
    SnapshotSectorRowModel,
    SnapshotStockRowModel,
)
from backend.data.ingest.json_codec import loads_json_field
from backend.core.utils import json_dumps, json_loads
from backend.data.repositories.shared import _compute_archive_source, _maybe_float, _maybe_int


class SnapshotRepositoryMixin:
    def list_datasets(self) -> list[Dataset]:
        if self.session is None:
            return []
        try:
            return list(self.session.scalars(select(Dataset).order_by(Dataset.created_at.desc())))
        except SQLAlchemyError as exc:
            raise RuntimeError("primary database read failed") from exc

    def get_dataset(self, dataset_id: str) -> Dataset | None:
        if self.session is None:
            return None
        try:
            return self.session.get(Dataset, dataset_id)
        except SQLAlchemyError as exc:
            raise RuntimeError("primary database read failed") from exc

    def existing_snapshot_ids(self, dataset_id: str, snapshot_ids: list[str]) -> set[str]:
        if self.session is None or not snapshot_ids:
            return set()
        try:
            frame_rows = self.session.scalars(
                select(SnapshotFrameModel.snapshot_id).where(
                    SnapshotFrameModel.dataset_id == dataset_id,
                    SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
                )
            )
            record_rows = self.session.scalars(
                select(SnapshotRecordModel.snapshot_id).where(
                    SnapshotRecordModel.dataset_id == dataset_id,
                    SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
                )
            )
            return {str(item) for item in [*frame_rows, *record_rows] if item}
        except SQLAlchemyError:
            return set()

    def delete_dataset_children(self, dataset_id: str) -> None:
        if self.session is None:
            return
        for model in [SnapshotSectorRowModel, SnapshotStockRowModel, SnapshotFrameModel, SnapshotRecordModel]:
            self.session.execute(delete(model).where(model.dataset_id == dataset_id))

    def delete_snapshot_children(self, dataset_id: str, snapshot_ids: list[str]) -> None:
        if self.session is None or not snapshot_ids:
            return
        self.session.execute(
            delete(SnapshotSectorRowModel).where(
                SnapshotSectorRowModel.dataset_id == dataset_id,
                SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotStockRowModel).where(
                SnapshotStockRowModel.dataset_id == dataset_id,
                SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotFrameModel).where(
                SnapshotFrameModel.dataset_id == dataset_id,
                SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
            )
        )
        self.session.execute(
            delete(SnapshotRecordModel).where(
                SnapshotRecordModel.dataset_id == dataset_id,
                SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
            )
        )

    def save_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> Dataset:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")

        try:
            self.session.merge(dataset)
            self.delete_dataset_children(dataset.id)

            self.session.add_all([self._record_model(dataset.id, item) for item in records])
            self.session.add_all([self._frame_model(dataset.id, item) for item in frames])
            self.session.add_all([self._stock_model(dataset.id, item) for item in stock_rows])
            self.session.add_all([self._sector_model(dataset.id, item) for item in sector_rows])
            self.session.flush()
            self._refresh_dataset_summary(dataset.id)
            saved_for_sync = self.session.get(Dataset, dataset.id) or dataset
            outbox_key = self._queue_backup_outbox(
                "dataset_bundle",
                {"dataset": self.dataset_to_dict(saved_for_sync)},
                dataset_id=dataset.id,
                snapshot_id=None,
            )
            self.session.commit()
            saved = self.session.get(Dataset, dataset.id)
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("primary database write failed")
        mirror_ok = self._mirror_dataset_bundle(saved or dataset, records, frames, stock_rows, sector_rows)
        self._finalize_outbox_mirror(outbox_key, mirror_ok)
        return saved or dataset

    def save_snapshot_ingest(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
        *,
        idempotency_key: str,
        trading_date: str | None = None,
        source: str = "dragon_board_runtime",
    ) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")

        existing = self.get_outbox_by_idempotency_key(idempotency_key)
        if existing:
            return {
                "dataset": self.dataset_to_dict(dataset),
                "status": existing.status,
                "outbox": self.outbox_to_dict(existing),
                "deduped": True,
            }

        snapshot_ids = sorted(
            {
                str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")
                for item in [*records, *frames, *stock_rows, *sector_rows]
                if isinstance(item, dict)
                and (item.get("snapshotId") or item.get("snapshot_id") or item.get("id"))
            }
        )
        existing_snapshot_ids = self.existing_snapshot_ids(dataset.id, snapshot_ids)
        if existing_snapshot_ids and len(existing_snapshot_ids) == len(snapshot_ids):
            outbox = self._latest_snapshot_ingest_outbox(dataset.id, snapshot_ids)
            saved_dataset = self.session.get(Dataset, dataset.id) or dataset
            return {
                "dataset": self.dataset_to_dict(saved_dataset),
                "status": outbox.status if outbox else "deduped",
                "outbox": self.outbox_to_dict(outbox) if outbox else None,
                "deduped": True,
            }
        if existing_snapshot_ids:
            missing_snapshot_ids = set(snapshot_ids) - existing_snapshot_ids
            records = self._filter_snapshot_payloads(records, missing_snapshot_ids)
            frames = self._filter_snapshot_payloads(frames, missing_snapshot_ids)
            stock_rows = self._filter_snapshot_payloads(stock_rows, missing_snapshot_ids)
            sector_rows = self._filter_snapshot_payloads(sector_rows, missing_snapshot_ids)
            snapshot_ids = sorted(missing_snapshot_ids)
        try:
            self.session.merge(dataset)
            self.delete_snapshot_children(dataset.id, snapshot_ids)
            self.session.add_all([self._record_model(dataset.id, item) for item in records])
            self.session.add_all([self._frame_model(dataset.id, item) for item in frames])
            self.session.add_all([self._stock_model(dataset.id, item) for item in stock_rows])
            self.session.add_all([self._sector_model(dataset.id, item) for item in sector_rows])
            self.session.flush()
            self._refresh_dataset_summary(dataset.id)

            outbox = self._add_outbox_row(
                "snapshot_ingest",
                {
                    "dataset": self.dataset_to_dict(dataset),
                    "records": records,
                    "frames": frames,
                    "stockRows": stock_rows,
                    "sectorRows": sector_rows,
                    "tradingDate": trading_date,
                    "source": source,
                },
                idempotency_key=idempotency_key,
                dataset_id=dataset.id,
                snapshot_id=snapshot_ids[0] if snapshot_ids else None,
            )
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            raise RuntimeError("primary database write failed")
        saved_dataset = self.session.get(Dataset, dataset.id) or dataset
        mirror_ok = False
        if self.backup:
            full_bundle = self.dump_dataset_bundle(dataset.id)
            if full_bundle:
                mirror_dataset, mirror_records, mirror_frames, mirror_stock_rows, mirror_sector_rows = full_bundle
                mirror_ok = self._mirror_dataset_bundle(
                    mirror_dataset,
                    mirror_records,
                    mirror_frames,
                    mirror_stock_rows,
                    mirror_sector_rows,
                )
            else:
                mirror_ok = self._mirror_dataset_bundle(saved_dataset, records, frames, stock_rows, sector_rows)
            refreshed_outbox = self._finalize_outbox_mirror(idempotency_key, mirror_ok)
            if refreshed_outbox:
                outbox = refreshed_outbox
        return {
            "dataset": self.dataset_to_dict(saved_dataset),
            "status": outbox.status,
            "outbox": self.outbox_to_dict(outbox),
            "deduped": False,
        }

    @staticmethod
    def _snapshot_id_from_payload(item: dict[str, Any]) -> str:
        return str(item.get("snapshotId") or item.get("snapshot_id") or item.get("id") or "")

    @classmethod
    def _filter_snapshot_payloads(
        cls,
        items: list[dict[str, Any]],
        snapshot_ids: set[str],
    ) -> list[dict[str, Any]]:
        return [item for item in items if isinstance(item, dict) and cls._snapshot_id_from_payload(item) in snapshot_ids]

    def load_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        include_payload: bool = True,
    ) -> list[dict[str, Any]]:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")
        query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        try:
            frame_models = list(self.session.scalars(query.order_by(SnapshotFrameModel.timestamp.asc())))
        except SQLAlchemyError:
            raise RuntimeError("primary database read failed")

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
            try:
                for row in self.session.scalars(row_query):
                    rows_by_snapshot[row.snapshot_id].append(self.stock_row_to_dict(row, include_payload=include_payload))
            except SQLAlchemyError:
                raise RuntimeError("primary database read failed")

        frames: list[dict[str, Any]] = []
        for frame in frame_models:
            item = self.frame_to_dict(frame)
            item["stocks"] = rows_by_snapshot.get(frame.snapshot_id, [])
            frames.append(item)
        return frames

    def load_frame_bundles(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "asc",
        projection: str = "full",
        fields: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self.session is None:
            raise RuntimeError("primary database is unavailable")
        query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotFrameModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            query = query.where(SnapshotFrameModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotFrameModel.capture_mode != "restored")
        order = SnapshotFrameModel.timestamp.desc() if sort == "desc" else SnapshotFrameModel.timestamp.asc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            frame_models = list(self.session.scalars(query.order_by(order)))
        except SQLAlchemyError:
            raise RuntimeError("primary database read failed")

        snapshot_ids = [frame.snapshot_id for frame in frame_models]
        stock_rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        sector_rows_by_snapshot: dict[str, list[dict[str, Any]]] = defaultdict(list)
        if snapshot_ids:
            try:
                stock_query = (
                    select(SnapshotStockRowModel)
                    .where(
                        SnapshotStockRowModel.dataset_id == dataset_id,
                        SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
                )
                for row in self.session.scalars(stock_query):
                    if projection in ("ranktrend", "ranktrend+themes"):
                        item = {
                            "code": row.code,
                            "name": row.name,
                            "rank": row.rank,
                            "avgRankNum": row.avg_rank_num,
                            "change": row.change,
                            "volumeRatio": row.volume_ratio,
                            "zlje": row.zlje,
                            "zljzb": row.zljzb,
                        }
                        if projection == "ranktrend+themes":
                            item.update({
                                "themes": json_loads(row.themes_json, []),
                                "mainTheme": "",
                                "themeRole": row.theme_role or "",
                                "themeContribution": row.theme_contribution,
                                "leadStatus": row.lead_status or "",
                            })
                        stock_rows_by_snapshot[row.snapshot_id].append(item)
                    else:
                        stock_rows_by_snapshot[row.snapshot_id].append(self.local_stock_to_bundle_dict(row))

                if projection != "ranktrend":
                    sector_query = (
                        select(SnapshotSectorRowModel)
                        .where(
                            SnapshotSectorRowModel.dataset_id == dataset_id,
                            SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
                        )
                        .order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
                    )
                    for row in self.session.scalars(sector_query):
                        sector_rows_by_snapshot[row.snapshot_id].append(self.local_sector_to_bundle_dict(row))
            except SQLAlchemyError:
                raise RuntimeError("primary database read failed")

        bundles: list[dict[str, Any]] = []
        for frame in frame_models:
            item = self.local_frame_to_bundle_dict(frame)
            item["rows"] = stock_rows_by_snapshot.get(frame.snapshot_id, [])
            item["hotlist"] = item["rows"]
            item["stocks"] = item["rows"]
            if projection in ("ranktrend", "ranktrend+themes"):
                item["entities"] = []
                item["sectors"] = []
                if projection == "ranktrend+themes":
                    item["hotThemes"] = [
                        self._sector_entity_to_view(row)
                        for row in sector_rows_by_snapshot.get(frame.snapshot_id, [])
                        if row.get("entityType") == "hot_theme"
                    ]
                else:
                    item["hotThemes"] = []
                bundles.append(item)
                continue
            item["entities"] = sector_rows_by_snapshot.get(frame.snapshot_id, [])
            item["sectors"] = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "sector"
            ]
            item["hotThemes"] = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "hot_theme"
            ]
            main_lines = [
                self._sector_entity_to_view(row)
                for row in item["entities"]
                if row.get("entityType") == "rotation_main_line"
            ]
            rotation_summary = item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else None
            if rotation_summary:
                # H4：引擎帧（含 algorithmVersion）不被旧 rotation_main_line 行顶掉
                if rotation_summary.get("algorithmVersion"):
                    item["rotationSummary"] = rotation_summary
                else:
                    item["rotationSummary"] = {**rotation_summary, "mainLines": main_lines}
            elif main_lines:
                item["rotationSummary"] = {"mainLines": main_lines}
            bundles.append(item)
        return bundles

    def load_rank_series(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        codes: list[str] | None = None,
        limit: int | None = 50,
        sort: str = "asc",
        window_bars: int | None = None,
        rank_basis: str = "composite",
    ) -> dict[str, Any]:
        if self.session is None:
            return {"frames": [], "marketFrames": [], "series": {}}

        query = select(SnapshotStockRowModel).where(
            SnapshotStockRowModel.dataset_id == dataset_id,
            SnapshotStockRowModel.type == snapshot_type,
        )
        if start_date:
            query = query.where(SnapshotStockRowModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotStockRowModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotStockRowModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            query = query.where(SnapshotStockRowModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotStockRowModel.capture_mode != "restored")
        if codes:
            query = query.where(SnapshotStockRowModel.code.in_(codes))

        order = SnapshotStockRowModel.timestamp.desc() if sort == "desc" else SnapshotStockRowModel.timestamp.asc()
        try:
            row_models = list(self.session.scalars(query.order_by(order, SnapshotStockRowModel.rank.asc())))
        except SQLAlchemyError:
            return {"frames": [], "series": {}}

        effective_window = window_bars or limit or 50

        total_count_by_code: dict[str, int] = defaultdict(int)
        for row in row_models:
            code_key = str(row.code or "")
            if code_key:
                total_count_by_code[code_key] += 1

        rows_for_window = sorted(
            row_models,
            key=lambda row: (int(row.timestamp or 0), int(row.rank or 0)),
        )

        # Per-code picking: keep the most recent bars per code
        picked_by_code: dict[str, list[SnapshotStockRowModel]] = defaultdict(list)
        for row in reversed(rows_for_window):
            code_key = str(row.code or "")
            if not code_key or len(picked_by_code[code_key]) >= effective_window:
                continue
            picked_by_code[code_key].append(row)
        # Reverse back to chronological order (ascending)
        for code_key in picked_by_code:
            picked_by_code[code_key].reverse()

        all_code_keys = sorted(picked_by_code.keys())
        picked_rows: list[SnapshotStockRowModel] = []
        for code_key in all_code_keys:
            picked_rows.extend(picked_by_code[code_key])

        # Build frames from picked rows
        snapshot_ids = list(dict.fromkeys(str(row.snapshot_id) for row in picked_rows if row.snapshot_id))
        frames_by_id: dict[str, SnapshotFrameModel] = {}
        if snapshot_ids:
            try:
                frame_rows = self.session.scalars(
                    select(SnapshotFrameModel).where(
                        SnapshotFrameModel.dataset_id == dataset_id,
                        SnapshotFrameModel.snapshot_id.in_(snapshot_ids),
                    )
                )
                frames_by_id = {str(frame.snapshot_id): frame for frame in frame_rows}
            except SQLAlchemyError:
                frames_by_id = {}

        frames_by_snapshot: dict[str, dict[str, Any]] = {}
        for row in picked_rows:
            snapshot_id = str(row.snapshot_id)
            if snapshot_id not in frames_by_snapshot:
                frame = frames_by_id.get(snapshot_id)
                frames_by_snapshot[snapshot_id] = {
                    "snapshotId": snapshot_id,
                    "displayKey": frame.display_key if frame else None,
                    "timestamp": row.timestamp,
                    "type": row.type,
                    "tradingDate": row.trading_date,
                    "slotTime": row.slot_time,
                    "captureMode": row.capture_mode,
                    "totalCount": int(frame.stock_row_count or 0) if frame else 0,
                    "bars": [],
                    "ranks": {},
                }
            frame_item = frames_by_snapshot[snapshot_id]
            frame_item["bars"].append(self.local_stock_to_bundle_dict(row))
            if row.code and row.rank:
                frame_item["ranks"][str(row.code)] = int(row.rank)

        frames = list(frames_by_snapshot.values())
        for frame in frames:
            if not frame["totalCount"]:
                frame["totalCount"] = len(frame["ranks"])

        market_frame_query = select(SnapshotFrameModel).where(
            SnapshotFrameModel.dataset_id == dataset_id,
            SnapshotFrameModel.type == snapshot_type,
        )
        if start_date:
            market_frame_query = market_frame_query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            market_frame_query = market_frame_query.where(SnapshotFrameModel.trading_date <= end_date)
        if before_trading_date:
            market_frame_query = market_frame_query.where(SnapshotFrameModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            market_frame_query = market_frame_query.where(SnapshotFrameModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            market_frame_query = market_frame_query.where(SnapshotFrameModel.capture_mode != "restored")
        try:
            market_models = list(
                self.session.scalars(
                    market_frame_query
                    .order_by(SnapshotFrameModel.timestamp.desc(), SnapshotFrameModel.snapshot_id.desc())
                    .limit(limit or effective_window)
                )
            )
        except SQLAlchemyError:
            market_models = []
        market_frames = [
            {
                "snapshotId": str(frame.snapshot_id),
                "displayKey": frame.display_key,
                "timestamp": frame.timestamp,
                "type": frame.type,
                "tradingDate": frame.trading_date,
                "slotTime": frame.slot_time,
                "captureMode": frame.capture_mode,
                "totalCount": int(frame.stock_row_count or 0),
                "ranks": {},
            }
            for frame in reversed(market_models)
        ]

        # Build per-code series
        series: dict[str, dict[str, Any]] = {}
        for code_key, rows in picked_by_code.items():
            bars = [self.local_stock_to_bundle_dict(row) for row in rows]
            for bar in bars:
                sid = bar.get("snapshotId") or ""
                frame = frames_by_id.get(sid)
                bar["totalCount"] = int(frame.stock_row_count or 0) if frame else 0
            last_bar = bars[-1] if bars else {}
            series[code_key] = {
                "code": code_key,
                "bars": bars,
                "totalCount": total_count_by_code.get(code_key, len(bars)),
                "latestSnapshotId": last_bar.get("snapshotId") or "",
                "latestTradingDate": last_bar.get("tradingDate") or "",
                "latestSlotTime": last_bar.get("slotTime") or "",
            }

        return {"frames": frames, "marketFrames": market_frames, "series": series}

    def list_snapshot_records(
        self,
        dataset_id: str,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        query = select(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        if types:
            query = query.where(SnapshotRecordModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotRecordModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotRecordModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotRecordModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotRecordModel.trading_date < before_trading_date)
        if allowed_capture_modes:
            query = query.where(SnapshotRecordModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotRecordModel.capture_mode != "restored")
        order = SnapshotRecordModel.timestamp.asc() if sort == "asc" else SnapshotRecordModel.timestamp.desc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            return [self.record_to_dict(row) for row in self.session.scalars(query.order_by(order))]
        except SQLAlchemyError:
            return []

    def get_snapshot_record(
        self,
        snapshot_id: str,
        dataset_id: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
    ) -> dict[str, Any] | None:
        if self.session is None:
            return None
        query = select(SnapshotRecordModel).where(SnapshotRecordModel.snapshot_id == snapshot_id)
        if dataset_id:
            query = query.where(SnapshotRecordModel.dataset_id == dataset_id)
        if allowed_capture_modes:
            query = query.where(SnapshotRecordModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotRecordModel.capture_mode != "restored")
        query = query.order_by(SnapshotRecordModel.timestamp.desc())
        try:
            row = self.session.scalars(query).first()
            return self.record_to_dict(row) if row else None
        except SQLAlchemyError:
            return None

    def get_snapshot_frame(
        self,
        snapshot_id: str,
        dataset_id: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
    ) -> dict[str, Any] | None:
        if self.session is None:
            return None
        query = select(SnapshotFrameModel).where(SnapshotFrameModel.snapshot_id == snapshot_id)
        if dataset_id:
            query = query.where(SnapshotFrameModel.dataset_id == dataset_id)
        if allowed_capture_modes:
            query = query.where(SnapshotFrameModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotFrameModel.capture_mode != "restored")
        query = query.order_by(SnapshotFrameModel.timestamp.desc())
        try:
            row = self.session.scalars(query).first()
            return self.frame_to_dict(row) if row else None
        except SQLAlchemyError:
            return None

    def list_snapshot_stock_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        code: str | None = None,
        codes: list[str] | None = None,
        slot_time: str | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
        fields: list[str] | None = None,
    ) -> dict[str, Any]:
        if self.session is None:
            return {"rows": [], "source": "sqlite"}
        query = select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        stock_codes = self._merge_values(code, codes)
        if snapshot_id:
            query = query.where(SnapshotStockRowModel.snapshot_id == snapshot_id)
        if types:
            query = query.where(SnapshotStockRowModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotStockRowModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotStockRowModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotStockRowModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotStockRowModel.trading_date < before_trading_date)
        if stock_codes:
            query = query.where(SnapshotStockRowModel.code.in_(stock_codes))
        if slot_time:
            query = query.where(SnapshotStockRowModel.slot_time == slot_time)
        if allowed_capture_modes:
            query = query.where(SnapshotStockRowModel.capture_mode.in_(allowed_capture_modes))
        if exclude_restored:
            query = query.where(SnapshotStockRowModel.capture_mode != "restored")
        order = SnapshotStockRowModel.timestamp.asc() if sort == "asc" else SnapshotStockRowModel.timestamp.desc()
        if limit and limit > 0:
            query = query.limit(limit)
        try:
            rows = [self.local_stock_to_bundle_dict(row) for row in self.session.scalars(query.order_by(order, SnapshotStockRowModel.rank.asc()))]
        except SQLAlchemyError:
            return {"rows": [], "source": "sqlite"}
        archived = self._archived_stock_rows(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=types[0] if len(types) == 1 else snapshot_type,
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            code=code,
            slot_time=slot_time,
            sort=sort,
            limit=limit if not rows else None,
        )
        merged = self._merge_archived_rows(rows, archived, limit=limit, sort=sort)
        if fields:
            field_set = set(fields)
            merged = [
                {key: value for key, value in row.items() if key in field_set}
                for row in merged
            ]
        source = _compute_archive_source(bool(rows), bool(archived))
        return {"rows": merged, "source": source}

    def list_snapshot_sector_rows(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        snapshot_type: str | None = None,
        snapshot_types: list[str] | None = None,
        trading_date: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        before_trading_date: str | None = None,
        entity_type: str | None = None,
        entity_types: list[str] | None = None,
        entity_key: str | None = None,
        entity_keys: list[str] | None = None,
        allowed_capture_modes: list[str] | None = None,
        exclude_restored: bool = False,
        limit: int | None = None,
        sort: str = "desc",
    ) -> dict[str, Any]:
        if self.session is None:
            return {"rows": [], "source": "sqlite"}
        query = select(SnapshotSectorRowModel).where(SnapshotSectorRowModel.dataset_id == dataset_id)
        types = self._merge_types(snapshot_type, snapshot_types)
        row_entity_types = self._merge_values(entity_type, entity_types)
        row_entity_keys = self._merge_values(entity_key, entity_keys)
        if snapshot_id:
            query = query.where(SnapshotSectorRowModel.snapshot_id == snapshot_id)
        if types:
            query = query.where(SnapshotSectorRowModel.type.in_(types))
        if trading_date:
            query = query.where(SnapshotSectorRowModel.trading_date == trading_date)
        if start_date:
            query = query.where(SnapshotSectorRowModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotSectorRowModel.trading_date <= end_date)
        if before_trading_date:
            query = query.where(SnapshotSectorRowModel.trading_date < before_trading_date)
        if row_entity_types:
            query = query.where(SnapshotSectorRowModel.entity_type.in_(row_entity_types))
        if row_entity_keys:
            query = query.where(SnapshotSectorRowModel.entity_key.in_(row_entity_keys))
        order = SnapshotSectorRowModel.timestamp.asc() if sort == "asc" else SnapshotSectorRowModel.timestamp.desc()
        if limit and limit > 0 and not allowed_capture_modes and not exclude_restored:
            query = query.limit(limit)
        try:
            rows = [self.local_sector_to_bundle_dict(row) for row in self.session.scalars(query.order_by(order, SnapshotSectorRowModel.rank.asc()))]
        except SQLAlchemyError:
            return {"rows": [], "source": "sqlite"}
        if allowed_capture_modes:
            allowed = set(allowed_capture_modes)
            rows = [row for row in rows if str(row.get("captureMode") or "real_time") in allowed]
        if exclude_restored:
            rows = [row for row in rows if str(row.get("captureMode") or "real_time") != "restored"]
        if limit and limit > 0:
            rows = rows[:limit]
        archived = self._archived_sector_rows(
            dataset_id=dataset_id,
            snapshot_id=snapshot_id,
            snapshot_type=types[0] if len(types) == 1 else snapshot_type,
            trading_date=trading_date,
            start_date=start_date,
            end_date=end_date,
            before_trading_date=before_trading_date,
            entity_type=entity_type,
            entity_key=entity_key,
            sort=sort,
            limit=limit if not rows else None,
        )
        merged = self._merge_archived_rows(rows, archived, limit=limit, sort=sort)
        source = _compute_archive_source(bool(rows), bool(archived))
        return {"rows": merged, "source": source}

    def snapshot_table_counts(self, dataset_id: str | None = None) -> dict[str, int]:
        if self.session is None:
            return {"snapshots": 0, "snapshot_frames": 0, "snapshot_stock_rows": 0, "snapshot_sector_rows": 0}
        filters = {
            "snapshots": SnapshotRecordModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_frames": SnapshotFrameModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_stock_rows": SnapshotStockRowModel.dataset_id == dataset_id if dataset_id else None,
            "snapshot_sector_rows": SnapshotSectorRowModel.dataset_id == dataset_id if dataset_id else None,
        }
        models = {
            "snapshots": SnapshotRecordModel,
            "snapshot_frames": SnapshotFrameModel,
            "snapshot_stock_rows": SnapshotStockRowModel,
            "snapshot_sector_rows": SnapshotSectorRowModel,
        }
        counts: dict[str, int] = {}
        try:
            for key, model in models.items():
                query = select(func.count()).select_from(model)
                table_filter = filters[key]
                if table_filter is not None:
                    query = query.where(table_filter)
                counts[key] = int(self.session.scalar(query) or 0)
        except SQLAlchemyError:
            return {"snapshots": 0, "snapshot_frames": 0, "snapshot_stock_rows": 0, "snapshot_sector_rows": 0}
        return counts

    def _archived_stock_rows(self, **filters: Any) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        try:
            from backend.data.archive.service import ArchiveService

            return ArchiveService(self.session).query_archived_stock_rows(**filters)
        except Exception:
            return []

    def _archived_sector_rows(self, **filters: Any) -> list[dict[str, Any]]:
        if self.session is None:
            return []
        try:
            from backend.data.archive.service import ArchiveService

            return ArchiveService(self.session).query_archived_sector_rows(**filters)
        except Exception:
            return []

    @staticmethod
    def _merge_archived_rows(
        sqlite_rows: list[dict[str, Any]],
        archived_rows: list[dict[str, Any]],
        *,
        limit: int | None,
        sort: str,
    ) -> list[dict[str, Any]]:
        if not archived_rows:
            return sqlite_rows
        by_id: dict[str, dict[str, Any]] = {}
        for row in [*sqlite_rows, *archived_rows]:
            key = str(row.get("rowId") or row.get("id") or f"{row.get('snapshotId')}:{row.get('code') or row.get('entityKey')}")
            by_id[key] = row
        rows = list(by_id.values())
        rows.sort(key=lambda row: (int(row.get("timestamp") or 0), int(row.get("rank") or 0)), reverse=sort != "asc")
        if limit and limit > 0:
            return rows[:limit]
        return rows

    def dump_dataset_bundle(
        self,
        dataset_id: str,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        if self.session is None:
            return None
        dataset = self.session.get(Dataset, dataset_id)
        if not dataset:
            return None
        record_query = select(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == dataset_id)
        frame_query = select(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == dataset_id)
        stock_query = select(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == dataset_id)
        sector_query = select(SnapshotSectorRowModel).where(SnapshotSectorRowModel.dataset_id == dataset_id)
        if start_date:
            record_query = record_query.where(SnapshotRecordModel.trading_date >= start_date)
            frame_query = frame_query.where(SnapshotFrameModel.trading_date >= start_date)
            stock_query = stock_query.where(SnapshotStockRowModel.trading_date >= start_date)
            sector_query = sector_query.where(SnapshotSectorRowModel.trading_date >= start_date)
        if end_date:
            record_query = record_query.where(SnapshotRecordModel.trading_date <= end_date)
            frame_query = frame_query.where(SnapshotFrameModel.trading_date <= end_date)
            stock_query = stock_query.where(SnapshotStockRowModel.trading_date <= end_date)
            sector_query = sector_query.where(SnapshotSectorRowModel.trading_date <= end_date)
        records = [
            self.record_to_dict(row)
            for row in self.session.scalars(
                record_query.order_by(SnapshotRecordModel.timestamp.asc())
            )
        ]
        frames = [
            self.local_frame_to_bundle_dict(row)
            for row in self.session.scalars(
                frame_query.order_by(SnapshotFrameModel.timestamp.asc())
            )
        ]
        stock_rows = [
            self.local_stock_to_bundle_dict(row)
            for row in self.session.scalars(
                stock_query.order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
            )
        ]
        sector_rows = [
            self.local_sector_to_bundle_dict(row)
            for row in self.session.scalars(
                sector_query.order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
            )
        ]
        return dataset, records, frames, stock_rows, sector_rows

    def dump_snapshot_bundle(
        self,
        dataset_id: str,
        snapshot_id: str,
    ) -> tuple[Dataset, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None:
        if self.session is None or not snapshot_id:
            return None
        dataset = self.session.get(Dataset, dataset_id)
        if not dataset:
            return None
        try:
            records = [
                self.record_to_dict(row)
                for row in self.session.scalars(
                    select(SnapshotRecordModel)
                    .where(
                        SnapshotRecordModel.dataset_id == dataset_id,
                        SnapshotRecordModel.snapshot_id == snapshot_id,
                    )
                    .order_by(SnapshotRecordModel.timestamp.asc())
                )
            ]
            frames = [
                self.local_frame_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotFrameModel)
                    .where(
                        SnapshotFrameModel.dataset_id == dataset_id,
                        SnapshotFrameModel.snapshot_id == snapshot_id,
                    )
                    .order_by(SnapshotFrameModel.timestamp.asc())
                )
            ]
            stock_rows = [
                self.local_stock_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotStockRowModel)
                    .where(
                        SnapshotStockRowModel.dataset_id == dataset_id,
                        SnapshotStockRowModel.snapshot_id == snapshot_id,
                    )
                    .order_by(SnapshotStockRowModel.timestamp.asc(), SnapshotStockRowModel.rank.asc())
                )
            ]
            sector_rows = [
                self.local_sector_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotSectorRowModel)
                    .where(
                        SnapshotSectorRowModel.dataset_id == dataset_id,
                        SnapshotSectorRowModel.snapshot_id == snapshot_id,
                    )
                    .order_by(SnapshotSectorRowModel.timestamp.asc(), SnapshotSectorRowModel.rank.asc())
                )
            ]
        except SQLAlchemyError:
            return None
        if not records and not frames and not stock_rows and not sector_rows:
            return None
        return dataset, records, frames, stock_rows, sector_rows

    def load_dataset_bundle_slice(
        self,
        dataset_id: str,
        *,
        snapshot_types: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        max_snapshots: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        if self.session is None:
            return [], [], [], []

        query = select(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == dataset_id)
        if snapshot_types:
            query = query.where(SnapshotFrameModel.type.in_(snapshot_types))
        if start_date:
            query = query.where(SnapshotFrameModel.trading_date >= start_date)
        if end_date:
            query = query.where(SnapshotFrameModel.trading_date <= end_date)
        query = query.order_by(SnapshotFrameModel.timestamp.asc(), SnapshotFrameModel.snapshot_id.asc())
        if max_snapshots and max_snapshots > 0:
            query = query.limit(max_snapshots)

        try:
            frame_models = list(self.session.scalars(query))
        except SQLAlchemyError:
            return [], [], [], []

        snapshot_ids = [frame.snapshot_id for frame in frame_models if frame.snapshot_id]
        if not snapshot_ids:
            return [], [], [], []

        try:
            records = [
                self.record_to_dict(row)
                for row in self.session.scalars(
                    select(SnapshotRecordModel)
                    .where(
                        SnapshotRecordModel.dataset_id == dataset_id,
                        SnapshotRecordModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(SnapshotRecordModel.timestamp.asc(), SnapshotRecordModel.snapshot_id.asc())
                )
            ]
            frames = [self.local_frame_to_bundle_dict(row) for row in frame_models]
            stock_rows = [
                self.local_stock_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotStockRowModel)
                    .where(
                        SnapshotStockRowModel.dataset_id == dataset_id,
                        SnapshotStockRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(
                        SnapshotStockRowModel.timestamp.asc(),
                        SnapshotStockRowModel.rank.asc(),
                        SnapshotStockRowModel.code.asc(),
                    )
                )
            ]
            sector_rows = [
                self.local_sector_to_bundle_dict(row)
                for row in self.session.scalars(
                    select(SnapshotSectorRowModel)
                    .where(
                        SnapshotSectorRowModel.dataset_id == dataset_id,
                        SnapshotSectorRowModel.snapshot_id.in_(snapshot_ids),
                    )
                    .order_by(
                        SnapshotSectorRowModel.timestamp.asc(),
                        SnapshotSectorRowModel.rank.asc(),
                        SnapshotSectorRowModel.entity_type.asc(),
                        SnapshotSectorRowModel.entity_key.asc(),
                    )
                )
            ]
        except SQLAlchemyError:
            return [], [], [], []

        return records, frames, stock_rows, sector_rows

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
            "snapshot_types": loads_json_field(model.snapshot_types_json, []),
            "metadata": loads_json_field(model.metadata_json, {}),
            "created_at": model.created_at.isoformat(),
        }

    @staticmethod
    def record_to_dict(model: SnapshotRecordModel) -> dict[str, Any]:
        return {
            "id": model.snapshot_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "displayKey": model.display_key,
            "captureMode": model.capture_mode,
            "capturedAt": model.captured_at or model.timestamp,
            "dataTimestamp": model.data_timestamp or model.timestamp,
            "delayMs": model.delay_ms or 0,
            "qualityFlags": json_loads(model.quality_flags_json, []),
            "source": model.source,
            "payload": {},
        }

    @staticmethod
    def frame_to_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = SnapshotRepositoryMixin._frame_context(model)
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
    def local_frame_to_bundle_dict(model: SnapshotFrameModel) -> dict[str, Any]:
        context = SnapshotRepositoryMixin._frame_context(model)
        return {
            "id": model.snapshot_id,
            "snapshotId": model.snapshot_id,
            "timestamp": model.timestamp,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "type": model.type,
            "displayKey": model.display_key or model.snapshot_id,
            "captureMode": model.capture_mode,
            "source": model.source,
            "qualityFlags": json_loads(model.quality_flags_json, []),
            "delayMs": model.delay_ms or 0,
            "marketStats": context.get("marketStats"),
            "sentiment": context.get("sentiment"),
            "moneyFlow": context.get("moneyFlow"),
            "indices": context.get("indices"),
            "limitSummary": context.get("limitSummary"),
            "rotationSummary": context.get("rotationSummary"),
            "stockRowCount": model.stock_row_count,
            "sectorRowCount": model.sector_row_count,
        }

    @staticmethod
    def stock_row_to_dict(model: SnapshotStockRowModel, include_payload: bool = True) -> dict[str, Any]:
        return SnapshotRepositoryMixin.local_stock_to_bundle_dict(model)

    @staticmethod
    def local_stock_to_bundle_dict(model: SnapshotStockRowModel) -> dict[str, Any]:
        item = {
            "id": model.row_id,
            "rowId": model.row_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "captureMode": model.capture_mode,
            "source": model.source,
            "code": model.code,
            "name": model.name,
            "rank": model.rank,
            "compRank": model.comp_rank,
            "platforms": model.platforms,
            "avgRank": model.avg_rank,
            "avgRankNum": model.avg_rank_num,
            "price": model.price,
            "change": model.change,
            "volume": model.volume,
            "turnover": model.turnover,
            "turnoverRate": model.turnover_rate,
            "totalMV": model.total_mv,
            "cirMV": model.cir_mv,
            "volumeRatio": model.volume_ratio,
            "zlje": model.zlje,
            "zljzb": model.zljzb,
            "cddje": model.cddje,
            "cddjzb": model.cddjzb,
            "pe": model.pe,
            "pb": model.pb,
            "depth10": json_loads(model.depth10_json, {}),
            "bid1Price": model.bid1_price,
            "bid1Volume": model.bid1_volume,
            "ask1Price": model.ask1_price,
            "ask1Volume": model.ask1_volume,
            "spread": model.spread,
            "bid10Total": model.bid10_total,
            "ask10Total": model.ask10_total,
            "depthImbalance": model.depth_imbalance,
            "tickBuyVolume": model.tick_buy_volume,
            "tickSellVolume": model.tick_sell_volume,
            "tickBuyCount": model.tick_buy_count,
            "tickSellCount": model.tick_sell_count,
            "lastTradePrice": model.last_trade_price,
            "lastTradeVolume": model.last_trade_volume,
            "speed": model.speed,
            "leadStatus": model.lead_status,
            "leadTimes": model.lead_times,
            "lianbanStr": model.lianban_str,
            "fengdan": model.fengdan,
            "maxFengdan": model.max_fengdan,
            "popularity": model.popularity,
            "popularityChange": model.popularity_change,
            "institutionBuy": model.institution_buy,
            "bigMoney300": model.big_money300,
            "themes": json_loads(model.themes_json, []),
            "themeContribution": model.theme_contribution,
            "themeRole": model.theme_role,
            "themeExposureWeight": model.theme_exposure_weight,
            "themeRiskFlags": json_loads(model.theme_risk_flags_json, []),
            "isNew": bool(model.is_new),
            "reason": model.reason,
            "firstZtTime": model.first_zt_time,
            "lastZtTime": model.last_zt_time,
            "boardHeight": model.board_height,
            "highDays": model.high_days,
            "hotness": model.hotness,
            "mainTheme": model.main_theme,
            "themeHeat": model.theme_heat,
            "themeLevel": model.theme_level,
            "rankChange": model.rank_change,
            "directionSignal": model.direction_signal,
            "directionConfidence": model.direction_confidence,
            "accelerationSignal": model.acceleration_signal,
            "accelerationConfidence": model.acceleration_confidence,
            "crossSignal": model.cross_signal,
            "crossConfidence": model.cross_confidence,
            "finalSignal": model.final_signal,
            "finalConfidence": model.final_confidence,
            "jumpDirection": model.jump_direction,
            "jumpConfidence": model.jump_confidence,
            "macdCross": model.macd_cross,
            "resonanceIntensity": model.resonance_intensity,
        }
        return {key: value for key, value in item.items() if value is not None}

    @staticmethod
    def local_sector_to_bundle_dict(model: SnapshotSectorRowModel) -> dict[str, Any]:
        item = {
            "id": model.row_id,
            "rowId": model.row_id,
            "snapshotId": model.snapshot_id,
            "type": model.type,
            "tradingDate": model.trading_date,
            "slotTime": model.slot_time,
            "timestamp": model.timestamp,
            "captureMode": model.capture_mode,
            "source": model.source,
            "entityType": model.entity_type,
            "entityKey": model.entity_key,
            "entityCode": model.entity_code,
            "entityName": model.entity_name,
            "rank": model.rank,
            "strength": model.strength,
            "heatScore": model.heat_score,
            "heatLevel": model.heat_level,
            "change": model.change,
            "mainNetInflow": model.main_net_inflow,
            "bigMoney300": model.big_money300,
            "institutionBuy": model.institution_buy,
            "volumeRatio": model.volume_ratio,
            "ztCount": model.zt_count,
            "leaderCount": model.leader_count,
            "persistentDays": model.persistent_days,
            "netInflow": model.net_inflow,
            "momentumScore": model.momentum_score,
            "breadthScore": model.breadth_score,
            "fundScore": model.fund_score,
            "leadershipScore": model.leadership_score,
            "correlationScore": model.correlation_score,
            "crowdingRisk": model.crowding_risk,
            "persistenceScore": model.persistence_score,
            "rotationState": model.rotation_state,
            "themeQualityFlags": json_loads(model.theme_quality_flags_json, []),
            "metadata": json_loads(model.metadata_json, {}),
        }
        return {key: value for key, value in item.items() if value is not None}

    @staticmethod
    def _frame_context(model: SnapshotFrameModel) -> dict[str, Any]:
        return {
            "metadata": json_loads(model.metadata_json, {}),
            "marketStats": json_loads(model.market_stats_json, {}),
            "sentiment": json_loads(model.sentiment_json, {}),
            "moneyFlow": json_loads(model.money_flow_json, {}),
            "indices": json_loads(model.indices_json, {}),
            "limitSummary": json_loads(model.limit_summary_json, {}),
            "rotationSummary": json_loads(model.rotation_summary_json, {}),
        }

    @staticmethod
    def _sector_entity_to_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            **row,
            "id": row.get("entityKey") or row.get("rowId") or row.get("id"),
            "code": row.get("entityCode") or row.get("entityKey"),
            "name": row.get("entityName"),
            "themeName": row.get("entityName"),
        }

    @staticmethod
    def _merge_types(value: str | None, values: list[str] | None) -> list[str]:
        return SnapshotRepositoryMixin._merge_values(value, values)

    @staticmethod
    def _merge_values(value: str | None, values: list[str] | None) -> list[str]:
        output: list[str] = []
        if value:
            output.append(str(value))
        output.extend(str(item) for item in values or [] if item)
        return list(dict.fromkeys(output))

    @staticmethod
    def _record_model(dataset_id: str, item: dict[str, Any]) -> SnapshotRecordModel:
        timestamp = int(item.get("timestamp") or 0)
        return SnapshotRecordModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("id") or item.get("snapshotId")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=timestamp,
            display_key=str(item.get("displayKey") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            captured_at=int(item.get("capturedAt") or timestamp),
            data_timestamp=int(item.get("dataTimestamp") or timestamp),
            delay_ms=int(item.get("delayMs") or 0),
            quality_flags_json=json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            source=str(item.get("source") or "browser_runtime"),
        )

    @staticmethod
    def _frame_model(dataset_id: str, item: dict[str, Any]) -> SnapshotFrameModel:
        return SnapshotFrameModel(
            dataset_id=dataset_id,
            snapshot_id=str(item.get("snapshotId") or item.get("id")),
            type=str(item.get("type") or ""),
            trading_date=str(item.get("tradingDate") or ""),
            slot_time=str(item.get("slotTime") or ""),
            timestamp=int(item.get("timestamp") or 0),
            display_key=str(item.get("displayKey") or item.get("snapshotId") or item.get("id") or ""),
            capture_mode=str(item.get("captureMode") or "real_time"),
            quality_flags_json=json_dumps(item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else []),
            delay_ms=int(item.get("delayMs") or 0),
            source=str(item.get("source") or "browser_runtime"),
            metadata_json=json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
            market_stats_json=json_dumps(item.get("marketStats") if isinstance(item.get("marketStats"), dict) else {}),
            sentiment_json=json_dumps(item.get("sentiment") if isinstance(item.get("sentiment"), dict) else {}),
            money_flow_json=json_dumps(item.get("moneyFlow") if isinstance(item.get("moneyFlow"), dict) else {}),
            indices_json=json_dumps(item.get("indices") if isinstance(item.get("indices"), dict) else {}),
            limit_summary_json=json_dumps(item.get("limitSummary") if isinstance(item.get("limitSummary"), dict) else {}),
            rotation_summary_json=json_dumps(item.get("rotationSummary") if isinstance(item.get("rotationSummary"), dict) else {}),
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
            source=str(item.get("source") or "browser_runtime"),
            code=str(item.get("code") or ""),
            name=str(item.get("name") or item.get("code") or ""),
            rank=int(float(item.get("rank") or item.get("compRank") or 0)),
            comp_rank=int(float(item.get("compRank") or item.get("rank") or 0)),
            platforms=int(float(item.get("platforms") or 0)),
            avg_rank=item.get("avgRank"),
            avg_rank_num=_maybe_float(item.get("avgRankNum")),
            price=_maybe_float(item.get("price")),
            change=_maybe_float(item.get("change")),
            volume=_maybe_float(item.get("volume")),
            turnover=_maybe_float(item.get("turnover")),
            turnover_rate=_maybe_float(item.get("turnoverRate")),
            total_mv=_maybe_float(item.get("totalMV")),
            cir_mv=_maybe_float(item.get("cirMV")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zlje=_maybe_float(item.get("zlje")),
            zljzb=_maybe_float(item.get("zljzb")),
            cddje=_maybe_float(item.get("cddje")),
            cddjzb=_maybe_float(item.get("cddjzb")),
            pe=_maybe_float(item.get("pe")),
            pb=_maybe_float(item.get("pb")),
            depth10_json=json_dumps(item.get("depth10") if isinstance(item.get("depth10"), dict) else {}),
            bid1_price=_maybe_float(item.get("bid1Price")),
            bid1_volume=_maybe_float(item.get("bid1Volume")),
            ask1_price=_maybe_float(item.get("ask1Price")),
            ask1_volume=_maybe_float(item.get("ask1Volume")),
            spread=_maybe_float(item.get("spread")),
            bid10_total=_maybe_float(item.get("bid10Total")),
            ask10_total=_maybe_float(item.get("ask10Total")),
            depth_imbalance=_maybe_float(item.get("depthImbalance")),
            tick_buy_volume=_maybe_float(item.get("tickBuyVolume")),
            tick_sell_volume=_maybe_float(item.get("tickSellVolume")),
            tick_buy_count=_maybe_int(item.get("tickBuyCount")),
            tick_sell_count=_maybe_int(item.get("tickSellCount")),
            last_trade_price=_maybe_float(item.get("lastTradePrice")),
            last_trade_volume=_maybe_float(item.get("lastTradeVolume")),
            speed=_maybe_float(item.get("speed")),
            lead_status=item.get("leadStatus"),
            lead_times=_maybe_int(item.get("leadTimes")),
            lianban_str=item.get("lianbanStr"),
            fengdan=_maybe_float(item.get("fengdan")),
            max_fengdan=_maybe_float(item.get("maxFengdan")),
            popularity=_maybe_float(item.get("popularity")),
            popularity_change=_maybe_float(item.get("popularityChange")),
            institution_buy=_maybe_float(item.get("institutionBuy")),
            big_money300=_maybe_float(item.get("bigMoney300")),
            themes_json=json_dumps(item.get("themes") if isinstance(item.get("themes"), list) else []),
            theme_contribution=_maybe_float(item.get("themeContribution")),
            theme_role=item.get("themeRole"),
            theme_exposure_weight=_maybe_float(item.get("themeExposureWeight")),
            theme_risk_flags_json=json_dumps(item.get("themeRiskFlags") if isinstance(item.get("themeRiskFlags"), list) else []),
            is_new=bool(item.get("isNew")) if item.get("isNew") is not None else False,
            reason=item.get("reason"),
            first_zt_time=item.get("firstZtTime"),
            last_zt_time=item.get("lastZtTime"),
            board_height=_maybe_int(item.get("boardHeight")),
            high_days=_maybe_int(item.get("highDays")),
            hotness=_maybe_float(item.get("hotness")),
            main_theme=item.get("mainTheme"),
            theme_heat=_maybe_float(item.get("themeHeat")),
            theme_level=item.get("themeLevel"),
            rank_change=_maybe_float(item.get("rankChange")),
            direction_signal=item.get("directionSignal"),
            direction_confidence=_maybe_float(item.get("directionConfidence")),
            acceleration_signal=item.get("accelerationSignal"),
            acceleration_confidence=_maybe_float(item.get("accelerationConfidence")),
            cross_signal=item.get("crossSignal"),
            cross_confidence=_maybe_float(item.get("crossConfidence")),
            final_signal=item.get("finalSignal"),
            final_confidence=_maybe_float(item.get("finalConfidence")),
            jump_direction=item.get("jumpDirection"),
            jump_confidence=_maybe_float(item.get("jumpConfidence")),
            macd_cross=item.get("macdCross"),
            resonance_intensity=_maybe_float(item.get("resonanceIntensity")),
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
            capture_mode=str(item.get("captureMode") or "real_time"),
            source=str(item.get("source") or "browser_runtime"),
            entity_type=str(item.get("entityType") or ""),
            entity_key=str(item.get("entityKey") or ""),
            entity_code=item.get("entityCode"),
            entity_name=str(item.get("entityName") or ""),
            rank=int(float(item.get("rank") or 0)),
            strength=_maybe_float(item.get("strength")),
            heat_score=_maybe_float(item.get("heatScore")),
            heat_level=item.get("heatLevel"),
            change=_maybe_float(item.get("change")),
            main_net_inflow=_maybe_float(item.get("mainNetInflow")),
            big_money300=_maybe_float(item.get("bigMoney300")),
            institution_buy=_maybe_float(item.get("institutionBuy")),
            volume_ratio=_maybe_float(item.get("volumeRatio")),
            zt_count=_maybe_int(item.get("ztCount")),
            leader_count=_maybe_int(item.get("leaderCount")),
            persistent_days=_maybe_int(item.get("persistentDays")),
            net_inflow=_maybe_float(item.get("netInflow")),
            momentum_score=_maybe_float(item.get("momentumScore")),
            breadth_score=_maybe_float(item.get("breadthScore")),
            fund_score=_maybe_float(item.get("fundScore")),
            leadership_score=_maybe_float(item.get("leadershipScore")),
            correlation_score=_maybe_float(item.get("correlationScore")),
            crowding_risk=_maybe_float(item.get("crowdingRisk")),
            persistence_score=_maybe_float(item.get("persistenceScore")),
            rotation_state=item.get("rotationState"),
            theme_quality_flags_json=json_dumps(item.get("themeQualityFlags") if isinstance(item.get("themeQualityFlags"), list) else []),
            metadata_json=json_dumps(item.get("metadata") if isinstance(item.get("metadata"), dict) else {}),
        )

    def _mirror_dataset_bundle(
        self,
        dataset: Dataset,
        records: list[dict[str, Any]],
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
        sector_rows: list[dict[str, Any]],
    ) -> bool:
        if self.backup:
            return self.backup.mirror_dataset_bundle(dataset, records, frames, stock_rows, sector_rows)
        return False

    def _refresh_dataset_summary(self, dataset_id: str) -> None:
        dataset = self.session.get(Dataset, dataset_id)
        if not dataset:
            return

        snapshot_count = self.session.scalar(
            select(func.count()).select_from(SnapshotRecordModel).where(SnapshotRecordModel.dataset_id == dataset_id)
        ) or 0
        frame_count = self.session.scalar(
            select(func.count()).select_from(SnapshotFrameModel).where(SnapshotFrameModel.dataset_id == dataset_id)
        ) or 0
        stock_row_count = self.session.scalar(
            select(func.count()).select_from(SnapshotStockRowModel).where(SnapshotStockRowModel.dataset_id == dataset_id)
        ) or 0
        sector_row_count = self.session.scalar(
            select(func.count()).select_from(SnapshotSectorRowModel).where(SnapshotSectorRowModel.dataset_id == dataset_id)
        ) or 0
        start_date = self.session.scalar(
            select(func.min(SnapshotFrameModel.trading_date)).where(SnapshotFrameModel.dataset_id == dataset_id)
        )
        end_date = self.session.scalar(
            select(func.max(SnapshotFrameModel.trading_date)).where(SnapshotFrameModel.dataset_id == dataset_id)
        )
        snapshot_types = list(
            self.session.scalars(select(SnapshotFrameModel.type).where(SnapshotFrameModel.dataset_id == dataset_id).distinct())
        )

        dataset.snapshot_count = int(snapshot_count)
        dataset.frame_count = int(frame_count)
        dataset.stock_row_count = int(stock_row_count)
        dataset.sector_row_count = int(sector_row_count)
        dataset.start_date = start_date
        dataset.end_date = end_date
        dataset.snapshot_types_json = json_dumps(sorted(snapshot_types))
        self.session.flush()
