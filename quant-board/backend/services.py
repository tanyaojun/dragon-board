from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import BacktestEngine, normalize_strategy_name
from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.quality_gate import evaluate_snapshot_quality
from backend.data.json_codec import dumps_json_field, loads_json_field
from backend.data.database import SessionLocal
from backend.data.repository import Repository
from backend.optimization.jobs import submit_optimization_job
from backend.optimization.runner import OptimizationRunner
from backend.utils import json_loads, new_id, read_json_file, stable_hash


DEFAULT_BACKTEST_STRATEGY_CONFIG = {
    "momentumPeriods": [3, 5, 8, 13, 21],
    "macdFast": 21,
    "macdSlow": 34,
    "macdSignal": 13,
}

BACKTEST_COMPARE_METRICS = {
    "totalReturn",
    "realizedReturn",
    "maxDrawdown",
    "sharpe",
    "winRate",
    "totalTrades",
    "tradeCount",
    "profitFactor",
    "openPositionCount",
}

FATAL_QUALITY_STATS = (
    "invalidCaptureMode",
    "duplicateSnapshotId",
    "nonMonotonicTimestamp",
    "missingCoreFieldCount",
)


def camel_get(payload: dict[str, Any], snake: str, camel: str | None = None, default: Any = None) -> Any:
    if snake in payload:
        return payload[snake]
    camel_key = camel or snake.split("_")[0] + "".join(part.title() for part in snake.split("_")[1:])
    return payload.get(camel_key, default)


def _stock_rows_for_quality(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"snapshotId": frame["snapshotId"]} for frame in frames for _ in frame.get("stocks", [])]


def _prepare_frames_for_backtest(frames: list[dict[str, Any]], snapshot_type: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    gate = evaluate_snapshot_quality(frames, _stock_rows_for_quality(frames), snapshot_type=snapshot_type)
    gate_dict = gate.to_dict()
    if gate.passed:
        return frames, gate_dict

    stats = gate.stats or {}
    has_empty_hotlist = int(stats.get("emptyHotlistCount") or 0) > 0
    has_other_fatal = any(int(stats.get(key) or 0) > 0 for key in FATAL_QUALITY_STATS)
    non_empty_frames = [frame for frame in frames if frame.get("stocks")]
    min_snapshot_count = int(stats.get("minSnapshotCount") or 2)

    if not has_empty_hotlist or has_other_fatal or len(non_empty_frames) < min_snapshot_count:
        raise ValueError({"qualityGate": gate_dict})

    dropped_frames = [frame for frame in frames if not frame.get("stocks")]
    gate_dict["runtimeFilter"] = {
        "reason": "empty_hotlist_snapshots_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len(non_empty_frames),
        "droppedEmptyHotlistSnapshots": len(dropped_frames),
        "droppedSnapshotIds": [str(frame.get("snapshotId") or "") for frame in dropped_frames[:50]],
    }
    return non_empty_frames, gate_dict


class BacktestService:
    def __init__(self, session: Session | None):
        self.repo = Repository(session)

    @staticmethod
    def _summary_response(run_id: str, result: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        signals = result.get("signals") or []
        signal_count = int(result.get("signalCount") or len(signals))
        compact = dict(result)
        compact["signals"] = signals[:120]
        compact["signalCount"] = signal_count
        compact["isCompact"] = True
        compact["notes"] = [
            *(result.get("notes") or []),
            f"接口默认返回前 120 条 signals 预览，完整结果已落库：{run_id}",
        ]
        meta = metadata or {}
        return {"id": run_id, "runId": run_id, "run_id": run_id, **meta, "result": compact, **compact}

    def run_ranktrend(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        payload_strategy_name = camel_get(payload, "strategy_name", "strategyName", None)
        trade_config_patch = camel_get(payload, "trade_config", "tradeConfig", {}) or {}
        strategy_name = normalize_strategy_name(
            payload_strategy_name
            if payload_strategy_name is not None
            else trade_config_patch.get("entryStrategy") or trade_config_patch.get("controlStrategy") or trade_config_patch.get("strategyName")
        )
        frames = self.repo.load_frames(
            dataset_id,
            snapshot_type=snapshot_type,
            start_date=camel_get(payload, "start_date", "startDate"),
            end_date=camel_get(payload, "end_date", "endDate"),
            include_payload=True,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")
        run_frames, quality_gate = _prepare_frames_for_backtest(frames, snapshot_type)

        trade_config = {
            "initialCapital": camel_get(payload, "initial_cash", "initialCash", 1000000),
            "maxPositions": camel_get(payload, "max_positions", "maxPositions", 5),
            "positionSize": camel_get(payload, "position_size", "positionSize", 0.2),
            "takeProfit": camel_get(payload, "take_profit_pct", "takeProfitPct", 0.12),
            "stopLoss": -abs(float(camel_get(payload, "stop_loss_pct", "stopLossPct", 0.06))),
            "maxHoldingBars": camel_get(payload, "max_holding_bars", "maxHoldingBars", 40),
            "targetHoldingDays": camel_get(payload, "target_holding_days", "targetHoldingDays", 5),
            "enforceT1": camel_get(payload, "enforce_t1", "enforceT1", True),
            "executionMode": camel_get(payload, "execution_mode", "executionMode", "current_bar"),
            "feeRate": camel_get(payload, "fee_rate", "feeRate", 0.0003),
            "stampTaxRate": camel_get(payload, "stamp_tax_rate", "stampTaxRate", 0.0005),
            "slippageRate": camel_get(payload, "slippage_rate", "slippageRate", 0.001),
            "useOrderBookPrice": camel_get(payload, "use_order_book_price", "useOrderBookPrice", True),
            "enforceLimitStatus": camel_get(payload, "enforce_limit_status", "enforceLimitStatus", True),
            "enforceVolumeLimit": camel_get(payload, "enforce_volume_limit", "enforceVolumeLimit", True),
            "enforceOrderBookQueue": camel_get(payload, "enforce_order_book_queue", "enforceOrderBookQueue", True),
            "allowPartialFills": camel_get(payload, "allow_partial_fills", "allowPartialFills", True),
            "volumeParticipationRate": camel_get(payload, "volume_participation_rate", "volumeParticipationRate", 0.05),
            "orderBookParticipationRate": camel_get(payload, "order_book_participation_rate", "orderBookParticipationRate", 0.3),
            "useIntrabarStops": camel_get(payload, "use_intrabar_stops", "useIntrabarStops", True),
            "intrabarAmbiguity": camel_get(payload, "intrabar_ambiguity", "intrabarAmbiguity", "stop_first"),
            "entryStrategy": strategy_name,
        }
        trade_config.update(trade_config_patch)
        trade_config["entryStrategy"] = strategy_name
        strategy_config = {
            **DEFAULT_BACKTEST_STRATEGY_CONFIG,
            **(camel_get(payload, "strategy_config", "strategyConfig", {}) or {}),
        }
        for src, dst in [("macdFast", "macdFast"), ("macdSlow", "macdSlow"), ("macdSignal", "macdSignal"), ("momentumPeriods", "momentumPeriods")]:
            if src in payload:
                strategy_config[dst] = payload[src]
        options = {
            "enable_trade_simulation": camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True),
            "horizons": camel_get(payload, "horizons", default=[1, 3, 5, 10]),
            "trade_config": trade_config,
            "strategy_config": strategy_config,
            "strategy_name": strategy_name,
            "quality_gate": quality_gate,
        }
        result = BacktestEngine().run(run_frames, options)
        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "strategy_name": strategy_name,
            "strategy_config": strategy_config,
            "trade_config": trade_config,
        }
        trading_dates = sorted({str(f.get("tradingDate") or "") for f in run_frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=request_meta["random_seed"],
            config_hash=stable_hash(request_meta),
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)

        # 归一化结果双写
        simulation = result.get("tradeSimulation") or {}
        self.repo.save_backtest_trades(run_id, simulation.get("trades") or [])
        self.repo.save_backtest_equity_curve(run_id, simulation.get("equityCurve") or [])
        self.repo.save_backtest_signals(run_id, result.get("strategyDecisions") or {})
        self.repo.save_backtest_quality_report(run_id, result.get("dataQuality") or {}, quality_gate)

        return self._summary_response(
            run_id,
            result,
            {
                "datasetId": dataset_id,
                "dataset_id": dataset_id,
                "strategyName": strategy_name,
                "snapshotType": snapshot_type,
                "randomSeed": request_meta["random_seed"],
                "configHash": run.config_hash,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        compact = self._summary_response(run.id, result)
        return {
            **compact,
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "dataset_id": run.dataset_id,
            "strategyName": run.strategy_name,
            "snapshotType": run.snapshot_type,
            "randomSeed": run.random_seed,
            "configHash": run.config_hash,
            "createdAt": run.created_at.isoformat(),
        }

    def get_trades(self, run_id: str, limit: int = 100, offset: int = 0) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        self._validate_pagination(limit, offset)
        items = self.repo.get_backtest_trades(run_id, limit=limit, offset=offset)
        source = "sqlite"
        total = self.repo.count_backtest_trades(run_id)
        if not items and total == 0:
            from backend.data.archive.service import ArchiveService

            archive = ArchiveService(SessionLocal())
            archived = archive.query_archived_research_table(run_id, "trades", limit=limit, offset=offset)
            if archived:
                items = archived
                total = archive.count_archived_research_table(run_id, "trades")
                source = "parquet_archive"
        return {
            "runId": run_id,
            "items": items,
            "limit": limit,
            "offset": offset,
            "total": total,
            "source": source,
        }

    def get_equity(self, run_id: str) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        items = self.repo.get_backtest_equity_curve(run_id)
        source = "sqlite"
        if not items:
            from backend.data.archive.service import ArchiveService

            archived = ArchiveService(SessionLocal()).query_archived_research_table(run_id, "equity_curve")
            if archived:
                items = archived
                source = "parquet_archive"
        return {"runId": run_id, "items": items, "source": source}

    def get_signals(
        self,
        run_id: str,
        limit: int = 200,
        offset: int = 0,
        tier: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        self._validate_pagination(limit, offset)
        items = self.repo.get_backtest_signals(run_id, limit=limit, offset=offset, tier=tier, regime=regime)
        total = self.repo.count_backtest_signals(run_id, tier=tier, regime=regime)
        source = "sqlite"
        if not items and total == 0:
            from backend.data.archive.service import ArchiveService

            filters = {"candidateTier": tier, "regime": regime}
            archive = ArchiveService(SessionLocal())
            archived = archive.query_archived_research_table(
                run_id,
                "signals",
                limit=limit,
                offset=offset,
                filters=filters,
            )
            if archived:
                items = archived
                total = archive.count_archived_research_table(run_id, "signals", filters=filters)
                source = "parquet_archive"
        return {
            "runId": run_id,
            "items": items,
            "filters": {"tier": tier, "regime": regime},
            "limit": limit,
            "offset": offset,
            "total": total,
            "source": source,
        }

    def get_quality(self, run_id: str) -> dict[str, Any] | None:
        if not self.repo.get_backtest_run(run_id):
            return None
        quality = self.repo.get_backtest_quality_report(run_id)
        if quality is None:
            return {"runId": run_id, "qualityReport": None}
        return {"runId": run_id, "qualityReport": quality}

    def delete_run(self, run_id: str) -> dict[str, Any] | None:
        return self.repo.delete_backtest_run(run_id, checkpoint=True)

    def research_storage_summary(self) -> dict[str, Any]:
        return self.repo.research_storage_summary()

    def vacuum_research_sqlite(self) -> dict[str, Any]:
        return self.repo.vacuum_research_sqlite()

    def cleanup_research(self, payload: dict[str, Any], *, apply: bool = False) -> dict[str, Any]:
        older_than_days = int(payload.get("olderThanDays") or payload.get("older_than_days") or 30)
        keep_latest = int(payload.get("keepLatestPerGroup") or payload.get("keep_latest_per_group") or 10)
        if older_than_days < 0:
            raise ValueError({"code": "invalid_cleanup_request", "field": "olderThanDays"})
        if keep_latest < 0:
            raise ValueError({"code": "invalid_cleanup_request", "field": "keepLatestPerGroup"})
        if apply and not bool(payload.get("confirm")):
            raise ValueError({"code": "cleanup_confirmation_required", "message": "confirm=true is required"})
        return self.repo.cleanup_research_backtests(
            older_than_days=older_than_days,
            keep_latest_per_group=keep_latest,
            dataset_id=str(payload.get("datasetId") or payload.get("dataset_id") or "") or None,
            snapshot_type=str(payload.get("snapshotType") or payload.get("snapshot_type") or "") or None,
            include_failed=bool(payload.get("includeFailed") or payload.get("include_failed")),
            apply=apply,
            checkpoint=apply,
        )

    def compare_runs(self, run_ids: list[str], metrics: list[str] | None = None) -> dict[str, Any]:
        metric_names = metrics or ["totalReturn", "sharpe", "maxDrawdown", "winRate"]
        invalid = [metric for metric in metric_names if metric not in BACKTEST_COMPARE_METRICS]
        if invalid:
            raise ValueError(
                {
                    "code": "invalid_backtest_metric",
                    "metric": invalid[0],
                    "allowedMetrics": sorted(BACKTEST_COMPARE_METRICS),
                }
            )
        runs = []
        for run_id in run_ids:
            run = self.repo.get_backtest_run(run_id)
            if not run:
                raise LookupError(run_id)
            result = loads_json_field(run.result_json, {})
            metric_values = {metric: self._metric_value(result, metric) for metric in metric_names}
            missing = [metric for metric, value in metric_values.items() if value is None]
            item = {
                "runId": run.id,
                "datasetId": run.dataset_id,
                "snapshotType": run.snapshot_type,
                "strategyName": run.strategy_name,
                "strategyVersion": run.strategy_version,
                "configHash": run.config_hash,
                "randomSeed": run.random_seed,
                "metrics": metric_values,
            }
            if missing:
                item["missingMetrics"] = missing
            runs.append(item)
        return {"runs": runs, "metrics": metric_names}

    def export_report(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        return {
            "runId": run.id,
            "datasetId": run.dataset_id,
            "snapshotType": run.snapshot_type,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "request": loads_json_field(run.request_json, {}),
            "metrics": {metric: self._metric_value(result, metric) for metric in sorted(BACKTEST_COMPARE_METRICS)},
            "trades": self.repo.get_backtest_trades(run_id),
            "equityCurve": self.repo.get_backtest_equity_curve(run_id),
            "signals": self.repo.get_backtest_signals(run_id),
            "qualityReport": self.repo.get_backtest_quality_report(run_id),
            "result": result,
        }

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if limit < 1 or limit > 1000:
            raise ValueError({"code": "invalid_pagination", "field": "limit", "value": limit, "message": "limit must be between 1 and 1000"})
        if offset < 0:
            raise ValueError({"code": "invalid_pagination", "field": "offset", "value": offset, "message": "offset must be greater than or equal to 0"})

    @staticmethod
    def _metric_value(result: dict[str, Any], metric: str) -> Any:
        if metric == "totalTrades":
            return result.get("tradeCount")
        return result.get(metric)


class OptimizationService:
    def __init__(self, session: Session | None):
        self.repo = Repository(session)

    def run_ranktrend(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = self._build_request(payload)
        if ((request.get("quality_gate") or {}).get("researchGrade")) == "blocked":
            raise ValueError({"qualityGate": request.get("quality_gate"), "reason": "data quality blocked optimization"})
        run_id = str(request["optimization_run_id"])
        config_hash = stable_hash({key: value for key, value in request.items() if key != "optimization_run_id"})
        initial = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            status="running",
            config_hash=config_hash,
            request_json=dumps_json_field(payload_for_request_json),
            result_json=dumps_json_field({"status": "running", "runId": run_id}),
        )
        self.repo.save_optimization_run(initial)
        if wait:
            return self._run_sync(
                run_id,
                dataset_id,
                snapshot_type,
                strategy_name,
                run_frames,
                request,
                payload_for_request_json,
                config_hash,
            )
        submit_optimization_job(
            run_id=run_id,
            frames=run_frames,
            request=request,
            dataset_id=dataset_id,
            snapshot_type=snapshot_type,
            strategy_name=strategy_name,
            random_seed=request["random_seed"],
            config_hash=config_hash,
            payload_for_request_json=payload_for_request_json,
        )
        return {
            "id": run_id,
            "runId": run_id,
            "run_id": run_id,
            "status": "running",
            "method": request["method"],
            "strategyName": strategy_name,
            "randomSeed": request["random_seed"],
        }

    def _build_request(self, payload: dict[str, Any]) -> tuple[str, str, str, list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        base_backtest = camel_get(payload, "backtest", default={}) or {}
        base_trade_config = base_backtest.get("trade_config") or base_backtest.get("tradeConfig") or {}
        base_strategy_config = {
            **DEFAULT_BACKTEST_STRATEGY_CONFIG,
            **(base_backtest.get("strategy_config") or base_backtest.get("strategyConfig") or {}),
        }
        payload_strategy_name = camel_get(payload, "strategy_name", "strategyName", None)
        strategy_name = normalize_strategy_name(
            payload_strategy_name
            if payload_strategy_name is not None
            else base_backtest.get("strategy_name")
            or base_backtest.get("strategyName")
            or base_trade_config.get("entryStrategy")
            or base_trade_config.get("controlStrategy")
            or base_trade_config.get("strategyName")
        )
        frames = self.repo.load_frames(dataset_id, snapshot_type=snapshot_type, include_payload=True)
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")
        run_frames, quality_gate = _prepare_frames_for_backtest(frames, snapshot_type)
        search_space = camel_get(payload, "search_space", "searchSpace")
        if not search_space:
            search_space = camel_get(payload, "parameter_grid", "parameterGrid", {})
        request = {
            "method": str(payload.get("method", "grid")).strip().lower(),
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "max_trials": int(camel_get(payload, "max_trials", "trials", 12)),
            "objective": payload.get("objective", "return"),
            "search_space": search_space,
            "strategy_name": strategy_name,
            "strategy_version": camel_get(payload, "strategy_version", "strategyVersion", "0.1.0"),
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "quality_gate": quality_gate,
            "validation_mode": camel_get(payload, "validation_mode", "validationMode", "none"),
            "validation_ratio": float(camel_get(payload, "validation_ratio", "validationRatio", 0.3)),
            "validation_warmup_bars": int(camel_get(payload, "validation_warmup_bars", "validationWarmupBars", 40)),
            "train_range": camel_get(payload, "train_range", "trainRange", None),
            "validation_range": camel_get(payload, "validation_range", "validationRange", None),
            "walk_forward": camel_get(payload, "walk_forward", "walkForward", None),
            "backtest": {**base_backtest, "strategy_name": strategy_name, "strategy_config": base_strategy_config},
        }
        run_id = new_id("opt")
        request["optimization_run_id"] = run_id
        payload_for_request_json = {**payload, **request}
        return dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json

    def _run_sync(
        self,
        run_id: str,
        dataset_id: str,
        snapshot_type: str,
        strategy_name: str,
        run_frames: list[dict[str, Any]],
        request: dict[str, Any],
        payload_for_request_json: dict[str, Any],
        config_hash: str,
    ) -> dict[str, Any]:
        result = OptimizationRunner().run(run_frames, request)
        backtest_artifacts = result.pop("backtestArtifacts", []) or []
        for artifact in backtest_artifacts:
            artifact_request = artifact.get("request") or {}
            artifact_result = artifact.get("result") or {}
            self.repo.save_backtest_run(
                BacktestRun(
                    id=str(artifact.get("runId")),
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    snapshot_type=snapshot_type,
                    random_seed=request["random_seed"],
                    config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                    request_json=dumps_json_field(artifact_request),
                    result_json=dumps_json_field(artifact_result),
                )
            )
        run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            status="completed",
            config_hash=config_hash,
            request_json=dumps_json_field(payload_for_request_json),
            result_json=dumps_json_field(result),
        )
        self.repo.save_optimization_run(run)
        return {"id": run_id, "runId": run_id, "run_id": run_id, "status": "completed", "result": result, **result}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_optimization_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        status = run.status or result.get("status") or "completed"
        if status != "completed":
            return {
                "id": run.id,
                "runId": run.id,
                "datasetId": run.dataset_id,
                "strategyName": run.strategy_name,
                "method": run.method,
                "randomSeed": run.random_seed,
                "configHash": run.config_hash,
                "status": status,
                "createdAt": run.created_at.isoformat(),
                "result": result,
                **(result if isinstance(result, dict) else {}),
            }
        return {
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "strategyName": run.strategy_name,
            "method": run.method,
            "randomSeed": run.random_seed,
            "configHash": run.config_hash,
            "status": status,
            "createdAt": run.created_at.isoformat(),
            "result": result,
            **result,
        }


class GoldenService:
    def __init__(self, session: Session | None):
        self.repo = Repository(session)

    def create_baseline(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(payload.get("dataset_id") or payload.get("datasetId") or "")
        case_id = str(payload.get("case_id") or payload.get("caseId") or "rank_trend_default")
        snapshot_type = str(payload.get("snapshot_type") or payload.get("snapshotType") or "half_hour")
        sample_limit = int(payload.get("sample_limit") or payload.get("sampleLimit") or 500)
        frames = self.repo.load_frames(dataset_id, snapshot_type=snapshot_type, include_payload=False)
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")
        signals = RankTrendPythonEngine(RankTrendConfig()).replay(frames, meta={"sampleQuality": "ok", "warnings": []})
        expected = self._normalize_signals(signals[:sample_limit])
        case = GoldenRankTrendCase(
            id=case_id,
            name=str(payload.get("name") or case_id),
            dataset_id=dataset_id,
            input_json=dumps_json_field({"datasetId": dataset_id, "snapshotType": snapshot_type, "sampleLimit": sample_limit, "source": "python_current_output"}),
            expected_json=dumps_json_field(expected),
        )
        self.repo.save_golden_case(case)
        return {"id": case_id, "caseId": case_id, "datasetId": dataset_id, "snapshotType": snapshot_type, "sampleLimit": sample_limit, "checked": len(expected), "source": "python_current_output", "message": "baseline saved from current Python output"}

    def import_case(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = payload.get("payload")
        if not data and payload.get("path"):
            data = read_json_file(payload["path"])
        if not isinstance(data, dict):
            raise ValueError("golden payload or path is required")
        case_id = str(payload.get("case_id") or payload.get("caseId") or data.get("caseId") or data.get("id") or new_id("golden"))
        dataset_id = payload.get("dataset_id") or payload.get("datasetId") or data.get("datasetId") or data.get("dataset_id")
        snapshot_type = payload.get("snapshot_type") or payload.get("snapshotType") or data.get("snapshotType") or data.get("snapshot_type") or "half_hour"
        expected_raw = data.get("expected") or data.get("signals") or data.get("actual") or data.get("outputs") or data
        expected = self._normalize_expected_payload(expected_raw)
        input_meta = data.get("input") or data.get("frames") or {}
        if not isinstance(input_meta, dict):
            input_meta = {"input": input_meta}
        input_meta = {
            **input_meta,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "source": payload.get("source") or data.get("source") or "ts_golden_import",
            "rankTrendConfig": data.get("rankTrendConfig") or data.get("rank_trend_config") or payload.get("rankTrendConfig") or {},
        }
        case = GoldenRankTrendCase(
            id=case_id,
            name=str(payload.get("name") or case_id),
            dataset_id=dataset_id,
            input_json=dumps_json_field(input_meta),
            expected_json=dumps_json_field(expected),
        )
        self.repo.save_golden_case(case)
        return {
            "id": case_id,
            "caseId": case_id,
            "name": case.name,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "source": input_meta["source"],
            "checked": len(expected) if isinstance(expected, list) else 0,
            "message": "golden case imported",
        }

    def validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        case_id = payload.get("case_id") or payload.get("caseId")
        dataset_id = payload.get("dataset_id") or payload.get("datasetId")
        tolerance = float(payload.get("tolerance") or 1e-6)
        strict = bool(payload.get("strict", True))
        requested_sample_limit = payload.get("sample_limit") or payload.get("sampleLimit")
        sample_limit = int(requested_sample_limit) if requested_sample_limit is not None else None
        if sample_limit is not None and sample_limit <= 0:
            return {"passed": False, "caseId": case_id, "checked": 0, "issues": ["sampleLimit must be positive"]}
        if case_id:
            case = self.repo.get_golden_case(case_id)
            if not case:
                return {"passed": False, "caseId": case_id, "issues": [f"golden case not found: {case_id}"]}
            expected = loads_json_field(case.expected_json, {})
            input_meta = loads_json_field(case.input_json, {})
            target_dataset_id = dataset_id or case.dataset_id or input_meta.get("datasetId")
            snapshot_type = str(payload.get("snapshot_type") or payload.get("snapshotType") or input_meta.get("snapshotType") or "half_hour")
            source = input_meta.get("source") or ("python_current_output" if input_meta.get("sampleLimit") else "unknown")
            rank_trend_config = input_meta.get("rankTrendConfig") or input_meta.get("rank_trend_config") or {}
            embedded_frames = input_meta.get("frames")
            if isinstance(embedded_frames, list) and embedded_frames:
                frames = embedded_frames
            else:
                frames = self.repo.load_frames(str(target_dataset_id), snapshot_type=snapshot_type, include_payload=False)
            if not frames:
                return {"passed": False, "caseId": case_id, "checked": 0, "issues": [f"dataset has no frames for {snapshot_type}: {target_dataset_id}"]}
            expected_list = self._normalize_expected_payload(expected)
            expected_count = len(expected_list)
            if sample_limit is not None:
                if expected_count < sample_limit:
                    return {
                        "passed": False,
                        "caseId": case_id,
                        "datasetId": target_dataset_id,
                        "snapshotType": snapshot_type,
                        "source": source,
                        "isFormalTsGolden": source == "ts_golden_import",
                        "rankTrendConfig": rank_trend_config,
                        "strict": strict,
                        "checked": expected_count,
                        "expectedCount": expected_count,
                        "requestedSampleLimit": sample_limit,
                        "issues": [
                            f"golden case has only {expected_count} expected rows, but sampleLimit={sample_limit}; re-export/import a larger TS Golden"
                        ],
                        "issueCount": 1,
                        "expectedPreview": expected_list[:5],
                        "actualPreview": [],
                    }
                expected_list = expected_list[:sample_limit]
            actual_list = self._normalize_signals(RankTrendPythonEngine(RankTrendConfig.from_patch(rank_trend_config)).replay(frames, meta={"sampleQuality": "ok", "warnings": []})[:len(expected_list)])
            issues = self._compare(expected_list, actual_list, tolerance, strict=strict)
            return {
                "passed": not issues,
                "caseId": case_id,
                "datasetId": target_dataset_id,
                "snapshotType": snapshot_type,
                "source": source,
                "isFormalTsGolden": source == "ts_golden_import",
                "rankTrendConfig": rank_trend_config,
                "strict": strict,
                "checked": len(expected_list),
                "expectedCount": expected_count,
                "requestedSampleLimit": sample_limit,
                "issues": issues[:100],
                "issueCount": len(issues),
                "expectedPreview": expected_list[:5],
                "actualPreview": actual_list[:5],
            }
        if payload.get("path"):
            data = read_json_file(payload["path"])
            return {"passed": bool(data), "caseId": None, "checked": 1, "issues": [] if data else ["empty golden file"]}
        return {"passed": False, "caseId": None, "checked": 0, "issues": ["caseId or path is required"]}

    @staticmethod
    def _normalize_signals(signals: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "snapshotId": signal.get("snapshotId"),
                "code": signal.get("code"),
                "candidateTier": signal.get("candidateTier"),
                "action": signal.get("action"),
                "stage": signal.get("stage"),
                "regime": signal.get("regime"),
                "rank": signal.get("rank"),
                "confidence": signal.get("confidence"),
                "finalSignal": ((signal.get("rankTrend") or {}).get("decision") or {}).get("final", {}).get("signal"),
                "technicalSignals": ((signal.get("rankTrend") or {}).get("technical") or {}).get("signals"),
                "momentumProfile": ((signal.get("rankTrend") or {}).get("technical") or {}).get("momentumProfile"),
                "risk": (signal.get("rankTrend") or {}).get("risk"),
            }
            for signal in signals
        ]

    @classmethod
    def _normalize_expected_payload(cls, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            if isinstance(value.get("signals"), list):
                value = value["signals"]
            elif isinstance(value.get("expected"), list):
                value = value["expected"]
            elif isinstance(value.get("actualPreview"), list):
                value = value["actualPreview"]
            else:
                value = [value]
        if not isinstance(value, list):
            return []
        rows = [item for item in value if isinstance(item, dict)]
        if not rows:
            return []
        if all("rankTrend" in item for item in rows):
            return cls._normalize_signals(rows)
        normalized = []
        for item in rows:
            rank_trend = item.get("rankTrend") or {}
            technical = rank_trend.get("technical") or {}
            decision = rank_trend.get("decision") or {}
            normalized.append(
                {
                    "snapshotId": item.get("snapshotId"),
                    "code": item.get("code"),
                    "candidateTier": item.get("candidateTier"),
                    "action": item.get("action"),
                    "stage": item.get("stage"),
                    "regime": item.get("regime"),
                    "rank": item.get("rank"),
                    "confidence": item.get("confidence"),
                    "finalSignal": item.get("finalSignal") or ((decision.get("final") or {}).get("signal")),
                    "technicalSignals": item.get("technicalSignals") or technical.get("signals"),
                    "momentumProfile": item.get("momentumProfile") or technical.get("momentumProfile"),
                    "risk": item.get("risk") or rank_trend.get("risk"),
                }
            )
        return normalized

    @classmethod
    def _compare(cls, expected: Any, actual: Any, tolerance: float, path: str = "$", strict: bool = True) -> list[str]:
        if isinstance(expected, dict) and isinstance(actual, dict):
            issues: list[str] = []
            keys = (set(expected) | set(actual)) if strict else (set(expected) & set(actual))
            for key in sorted(keys):
                if key not in expected:
                    issues.append(f"{path}.{key}: unexpected field")
                elif key not in actual:
                    issues.append(f"{path}.{key}: missing field")
                else:
                    issues.extend(cls._compare(expected[key], actual[key], tolerance, f"{path}.{key}", strict=strict))
            return issues
        if isinstance(expected, list) and isinstance(actual, list):
            issues = []
            if strict and len(expected) != len(actual):
                issues.append(f"{path}: length mismatch expected {len(expected)} actual {len(actual)}")
            for index, (left, right) in enumerate(zip(expected, actual)):
                issues.extend(cls._compare(left, right, tolerance, f"{path}[{index}]", strict=strict))
            return issues
        if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
            return [] if abs(float(expected) - float(actual)) <= tolerance else [f"{path}: expected {expected} actual {actual}"]
        return [] if expected == actual else [f"{path}: expected {expected!r} actual {actual!r}"]
