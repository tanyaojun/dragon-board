from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.data.json_codec import dumps_json_field, loads_json_field
from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.mongo_repository import MongoRepository
from backend.utils import json_dumps


class MongoResearchRepository(MongoRepository):
    def save_backtest_run(self, run: BacktestRun) -> BacktestRun:
        self.db["backtest_runs"].replace_one({"id": run.id}, self._backtest_run_doc(run), upsert=True)
        return self.get_backtest_run(run.id) or run

    def get_backtest_run(self, run_id: str) -> BacktestRun | None:
        row = self.db["backtest_runs"].find_one({"id": run_id})
        return self._backtest_run_from_doc(row) if row else None

    def save_backtest_signal_rows(self, run_id: str, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        existing = self.db["backtest_signals"].count_documents({"backtestRunId": run_id})
        docs = [
            self._backtest_signal_doc(run_id, item, sequence=existing + index + 1)
            for index, item in enumerate(rows)
        ]
        self.db["backtest_signals"].insert_many(docs, ordered=False)
        return len(docs)

    def get_backtest_signals(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
        tier: str | None = None,
        regime: str | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self.db["backtest_signals"].find(
            self._backtest_signal_query(run_id, tier=tier, regime=regime)
        ).sort([("sequence", 1)])
        if offset:
            cursor = cursor.skip(offset)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._drop_mongo_id(row) for row in cursor]

    def count_backtest_signals(
        self,
        run_id: str,
        tier: str | None = None,
        regime: str | None = None,
    ) -> int:
        return int(self.db["backtest_signals"].count_documents(
            self._backtest_signal_query(run_id, tier=tier, regime=regime)
        ))

    def save_backtest_trades(self, run_id: str, trades: list[dict[str, Any]]) -> int:
        if not trades:
            return 0
        existing = self.db["backtest_trades"].count_documents({"backtestRunId": run_id})
        docs = [
            {"backtestRunId": run_id, "sequence": existing + index + 1, **dict(item)}
            for index, item in enumerate(trades)
        ]
        self.db["backtest_trades"].insert_many(docs, ordered=False)
        return len(docs)

    def get_backtest_trades(
        self,
        run_id: str,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        cursor = self.db["backtest_trades"].find({"backtestRunId": run_id}).sort([("sequence", 1)])
        if offset:
            cursor = cursor.skip(offset)
        if limit is not None:
            cursor = cursor.limit(limit)
        return [self._drop_mongo_id(row) for row in cursor]

    def count_backtest_trades(self, run_id: str) -> int:
        return int(self.db["backtest_trades"].count_documents({"backtestRunId": run_id}))

    def save_backtest_equity_curve(self, run_id: str, curve: list[dict[str, Any]]) -> int:
        if not curve:
            return 0
        existing = self.db["backtest_equity_curve"].count_documents({"backtestRunId": run_id})
        docs = [
            {"backtestRunId": run_id, "sequence": existing + index + 1, **dict(item)}
            for index, item in enumerate(curve)
        ]
        self.db["backtest_equity_curve"].insert_many(docs, ordered=False)
        return len(docs)

    def save_backtest_equity_rows(self, run_id: str, rows: list[dict[str, Any]]) -> int:
        return self.save_backtest_equity_curve(run_id, rows)

    def get_backtest_equity_curve(self, run_id: str) -> list[dict[str, Any]]:
        cursor = self.db["backtest_equity_curve"].find({"backtestRunId": run_id}).sort([("sequence", 1)])
        return [self._drop_mongo_id(row) for row in cursor]

    def save_backtest_signals(self, run_id: str, strategy_decisions: dict[str, Any]) -> int:
        rows: list[dict[str, Any]] = []
        for frame in strategy_decisions.get("frameResults") or []:
            snapshot_id = str(frame.get("snapshotId") or "")
            trading_date = str(frame.get("tradingDate") or "")
            for key in ("buyCandidates", "watchCandidates", "excludedCandidates"):
                for item in frame.get(key) or []:
                    if isinstance(item, dict):
                        rows.append({**item, "snapshotId": snapshot_id, "tradingDate": trading_date})
        return self.save_backtest_signal_rows(run_id, rows)

    def save_backtest_quality_report(
        self,
        run_id: str,
        data_quality: dict[str, Any],
        quality_gate: dict[str, Any] | None = None,
    ) -> bool:
        gate = quality_gate if isinstance(quality_gate, dict) else {}
        stats = gate.get("stats") if isinstance(gate.get("stats"), dict) else {}
        doc = {
            "backtestRunId": run_id,
            "passed": bool(data_quality.get("severity") == "pass"),
            "severity": str(data_quality.get("severity") or "pass"),
            "researchGrade": str(data_quality.get("researchGrade") or "research_ready"),
            "frameCount": int(data_quality.get("snapshotCount") or 0),
            "stockCount": int(gate.get("stockCount") or 0),
            "sectorCount": int(gate.get("sectorCount") or 0),
            "missingFields": stats.get("missingFields") if isinstance(stats.get("missingFields"), dict) else {},
            "nanCounts": stats.get("nanCounts") if isinstance(stats.get("nanCounts"), dict) else {},
            "infCounts": stats.get("infCounts") if isinstance(stats.get("infCounts"), dict) else {},
            "negativePriceCount": int(stats.get("negativePriceCount") or 0),
            "nonPositivePriceCount": int(stats.get("nonPositivePriceCount") or 0),
            "negativeVolumeCount": int(stats.get("negativeVolumeCount") or 0),
            "coverageRatio": _maybe_float(stats.get("coverageRatio")),
            "timeOrderFixed": bool(gate.get("timeOrderFixed") or False),
            "timeOrderFixCount": int(gate.get("timeOrderFixCount") or 0),
            "warnings": data_quality.get("warnings") if isinstance(data_quality.get("warnings"), list) else [],
        }
        self.db["backtest_quality_reports"].replace_one({"backtestRunId": run_id}, doc, upsert=True)
        return True

    def get_backtest_quality_report(self, run_id: str) -> dict[str, Any] | None:
        row = self.db["backtest_quality_reports"].find_one({"backtestRunId": run_id})
        return self._drop_mongo_id(row) if row else None

    def delete_backtest_run(self, run_id: str, *, checkpoint: bool = False) -> dict[str, Any] | None:
        if not self.get_backtest_run(run_id):
            return None
        deleted = {
            name: int(self.db[name].delete_many(query).deleted_count)
            for name, query in {
                "backtest_runs": {"id": run_id},
                "backtest_trades": {"backtestRunId": run_id},
                "backtest_equity_curve": {"backtestRunId": run_id},
                "backtest_signals": {"backtestRunId": run_id},
                "backtest_quality_reports": {"backtestRunId": run_id},
            }.items()
        }
        return {"ok": True, "deleted": deleted, "checkpoint": checkpoint, "source": "mongodb"}

    def research_storage_summary(self) -> dict[str, Any]:
        tables = {
            name: int(self.db[name].count_documents({}))
            for name in (
                "backtest_runs",
                "backtest_trades",
                "backtest_equity_curve",
                "backtest_signals",
                "backtest_quality_reports",
                "optimization_runs",
                "golden_ranktrend_cases",
            )
        }
        rows = list(self.db["backtest_runs"].find({}))
        created = [row.get("createdAt") for row in rows if row.get("createdAt")]
        created.sort()
        return {
            "ok": True,
            "source": "mongodb",
            "tables": tables,
            "backtestCreatedAt": {
                "oldest": _iso_or_none(created[0]) if created else None,
                "newest": _iso_or_none(created[-1]) if created else None,
            },
        }

    def vacuum_research_sqlite(self) -> dict[str, Any]:
        return {"ok": False, "source": "mongodb", "reason": "sqlite vacuum is unavailable for mongodb backend"}

    def cleanup_research_backtests(
        self,
        *,
        older_than_days: int | None = None,
        keep_latest_per_group: int | None = None,
        dataset_id: str | None = None,
        snapshot_type: str | None = None,
        include_failed: bool = False,
        apply: bool = False,
        checkpoint: bool = False,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "source": "mongodb",
            "reason": "mongodb research cleanup is not implemented",
            "olderThanDays": older_than_days,
            "keepLatestPerGroup": keep_latest_per_group,
            "datasetId": dataset_id,
            "snapshotType": snapshot_type,
            "includeFailed": include_failed,
            "apply": apply,
            "checkpoint": checkpoint,
        }

    def save_optimization_run(self, run: OptimizationRun) -> OptimizationRun:
        self.db["optimization_runs"].replace_one({"id": run.id}, self._optimization_run_doc(run), upsert=True)
        return self.get_optimization_run(run.id) or run

    def get_optimization_run(self, run_id: str) -> OptimizationRun | None:
        row = self.db["optimization_runs"].find_one({"id": run_id})
        return self._optimization_run_from_doc(row) if row else None

    def save_golden_case(self, case: GoldenRankTrendCase) -> GoldenRankTrendCase:
        self.db["golden_ranktrend_cases"].replace_one({"id": case.id}, self._golden_case_doc(case), upsert=True)
        return self.get_golden_case(case.id) or case

    def get_golden_case(self, case_id: str) -> GoldenRankTrendCase | None:
        row = self.db["golden_ranktrend_cases"].find_one({"id": case_id})
        return self._golden_case_from_doc(row) if row else None

    def save_factor_frames(self, rows: list[dict[str, Any]]) -> int:
        return self._insert_theme_rows("theme_factor_frames", rows, self._factor_doc)

    def get_factor_frames(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        trading_date: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"datasetId": dataset_id, "snapshotType": snapshot_type}
        if trading_date:
            query["tradingDate"] = trading_date
        cursor = self.db["theme_factor_frames"].find(query).sort([("snapshotId", 1), ("rank", 1)])
        return [self._drop_mongo_id(row) for row in cursor]

    def save_stock_exposures(self, rows: list[dict[str, Any]]) -> int:
        return self._insert_theme_rows("theme_stock_exposures", rows, self._exposure_doc)

    def get_stock_exposures(
        self,
        dataset_id: str,
        snapshot_id: str | None = None,
        code: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"datasetId": dataset_id}
        if snapshot_id:
            query["snapshotId"] = snapshot_id
        if code:
            query["code"] = code
        cursor = self.db["theme_stock_exposures"].find(query).sort([("exposureWeight", -1)])
        return [self._drop_mongo_id(row) for row in cursor]

    def save_signals(self, rows: list[dict[str, Any]]) -> int:
        return self._insert_theme_rows("theme_signals", rows, self._theme_signal_doc)

    def get_signals(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        signal: str | None = None,
    ) -> list[dict[str, Any]]:
        query: dict[str, Any] = {"datasetId": dataset_id, "snapshotType": snapshot_type}
        if signal:
            query["signal"] = signal
        cursor = self.db["theme_signals"].find(query).sort([("score", -1)])
        return [self._drop_mongo_id(row) for row in cursor]

    def save_quality_report(self, report: dict[str, Any]) -> bool:
        self.db["theme_quality_reports"].insert_many([self._quality_report_doc(report)], ordered=False)
        return True

    def get_quality_reports(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
    ) -> list[dict[str, Any]]:
        cursor = self.db["theme_quality_reports"].find(
            {"datasetId": dataset_id, "snapshotType": snapshot_type}
        ).sort([("createdAt", -1)])
        return [self._drop_mongo_id(row) for row in cursor]

    def delete_theme_research(
        self,
        dataset_id: str,
        snapshot_type: str = "half_hour",
        snapshot_id: str | None = None,
    ) -> dict[str, int]:
        base_query: dict[str, Any] = {"datasetId": dataset_id, "snapshotType": snapshot_type}
        deleted: dict[str, int] = {}
        for name in ("theme_factor_frames", "theme_stock_exposures", "theme_signals"):
            query = dict(base_query)
            if snapshot_id:
                query["snapshotId"] = snapshot_id
            deleted[name] = int(self.db[name].delete_many(query).deleted_count)
        deleted["theme_quality_reports"] = int(
            self.db["theme_quality_reports"].delete_many(base_query).deleted_count
        )
        return deleted

    @staticmethod
    def backtest_run_to_dict(model: BacktestRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "strategy_version": model.strategy_version,
            "snapshot_type": model.snapshot_type,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "dateStart": model.date_start,
            "dateEnd": model.date_end,
            "errorReason": model.error_reason,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "finished_at": model.finished_at.isoformat() if model.finished_at else None,
        }

    @staticmethod
    def optimization_run_to_dict(model: OptimizationRun) -> dict[str, Any]:
        return {
            "id": model.id,
            "dataset_id": model.dataset_id,
            "strategy_name": model.strategy_name,
            "method": model.method,
            "config_hash": model.config_hash,
            "random_seed": model.random_seed,
            "status": model.status,
            "request_json": model.request_json,
            "result_json": model.result_json,
            "request": loads_json_field(model.request_json, {}),
            "result": loads_json_field(model.result_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def golden_case_to_dict(model: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": model.id,
            "name": model.name,
            "dataset_id": model.dataset_id,
            "input_json": model.input_json,
            "expected_json": model.expected_json,
            "input": loads_json_field(model.input_json, {}),
            "expected": loads_json_field(model.expected_json, {}),
            "created_at": model.created_at.isoformat() if model.created_at else None,
        }

    @staticmethod
    def _backtest_run_doc(run: BacktestRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "datasetId": run.dataset_id,
            "strategyName": run.strategy_name,
            "strategyVersion": run.strategy_version,
            "snapshotType": run.snapshot_type,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "status": run.status or "completed",
            "dateStart": run.date_start,
            "dateEnd": run.date_end,
            "errorReason": run.error_reason,
            "request": loads_json_field(run.request_json, {}),
            "resultCompressed": dumps_json_field(loads_json_field(run.result_json, {})),
            "createdAt": run.created_at or _utc_now_naive(),
            "finishedAt": run.finished_at,
        }

    @staticmethod
    def _backtest_run_from_doc(row: dict[str, Any]) -> BacktestRun:
        return BacktestRun(
            id=str(row.get("id") or ""),
            dataset_id=str(row.get("datasetId") or ""),
            strategy_name=str(row.get("strategyName") or "rank_trend_candidate"),
            strategy_version=str(row.get("strategyVersion") or "0.1.0"),
            snapshot_type=str(row.get("snapshotType") or "half_hour"),
            config_hash=str(row.get("configHash") or ""),
            random_seed=int(row.get("randomSeed") or 0),
            status=str(row.get("status") or "completed"),
            date_start=row.get("dateStart"),
            date_end=row.get("dateEnd"),
            error_reason=row.get("errorReason"),
            request_json=json_dumps(row.get("request") or {}),
            result_json=dumps_json_field(
                row.get("result")
                if isinstance(row.get("result"), dict)
                else loads_json_field(row.get("resultCompressed"), {})
            ),
            created_at=_datetime_or_now(row.get("createdAt")),
            finished_at=_datetime_or_none(row.get("finishedAt")),
        )

    @staticmethod
    def _backtest_signal_doc(run_id: str, item: dict[str, Any], *, sequence: int) -> dict[str, Any]:
        return {
            "backtestRunId": run_id,
            "sequence": sequence,
            "snapshotId": _blank_to_none(item.get("snapshotId")),
            "tradingDate": _blank_to_none(item.get("tradingDate")),
            "code": str(item.get("code") or ""),
            "name": str(item.get("name") or ""),
            "candidateTier": _blank_to_none(item.get("candidateTier")),
            "signal": _blank_to_none(item.get("signal")),
            "confidence": _maybe_float(item.get("confidence")),
            "rank": _maybe_int(item.get("rank")),
            "stage": _blank_to_none(item.get("stage")),
            "regime": _blank_to_none(item.get("regime")),
            "reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
            "riskFlags": item.get("riskFlags") if isinstance(item.get("riskFlags"), list) else [],
            "mainTheme": _blank_to_none(item.get("mainTheme")),
            "themeHeat": _maybe_float(item.get("themeHeat")),
            "themeContribution": _maybe_float(item.get("themeContribution")),
            "themeRole": _blank_to_none(item.get("themeRole")),
            "themeSupportScore": _maybe_float(item.get("themeSupportScore")),
            "themeRiskFlags": item.get("themeRiskFlags") if isinstance(item.get("themeRiskFlags"), list) else [],
            "themeReasons": item.get("themeReasons") if isinstance(item.get("themeReasons"), list) else [],
        }

    @staticmethod
    def _backtest_signal_query(
        run_id: str,
        tier: str | None = None,
        regime: str | None = None,
    ) -> dict[str, Any]:
        query: dict[str, Any] = {"backtestRunId": run_id}
        if tier:
            query["candidateTier"] = tier
        if regime:
            query["regime"] = regime
        return query

    @staticmethod
    def _optimization_run_doc(run: OptimizationRun) -> dict[str, Any]:
        return {
            "id": run.id,
            "datasetId": run.dataset_id,
            "strategyName": run.strategy_name,
            "method": run.method,
            "configHash": run.config_hash,
            "randomSeed": run.random_seed,
            "status": run.status,
            "request": loads_json_field(run.request_json, {}),
            "result": loads_json_field(run.result_json, {}),
            "createdAt": run.created_at or _utc_now_naive(),
        }

    @staticmethod
    def _optimization_run_from_doc(row: dict[str, Any]) -> OptimizationRun:
        return OptimizationRun(
            id=str(row.get("id") or ""),
            dataset_id=str(row.get("datasetId") or ""),
            strategy_name=str(row.get("strategyName") or "rank_trend_candidate"),
            method=str(row.get("method") or "grid"),
            config_hash=str(row.get("configHash") or ""),
            random_seed=int(row.get("randomSeed") or 0),
            status=str(row.get("status") or "completed"),
            request_json=json_dumps(row.get("request") or {}),
            result_json=json_dumps(row.get("result") or {}),
            created_at=_datetime_or_now(row.get("createdAt")),
        )

    @staticmethod
    def _golden_case_doc(case: GoldenRankTrendCase) -> dict[str, Any]:
        return {
            "id": case.id,
            "name": case.name,
            "datasetId": case.dataset_id,
            "input": loads_json_field(case.input_json, {}),
            "expected": loads_json_field(case.expected_json, {}),
            "createdAt": case.created_at or _utc_now_naive(),
        }

    @staticmethod
    def _golden_case_from_doc(row: dict[str, Any]) -> GoldenRankTrendCase:
        return GoldenRankTrendCase(
            id=str(row.get("id") or ""),
            name=str(row.get("name") or ""),
            dataset_id=row.get("datasetId"),
            input_json=json_dumps(row.get("input") or {}),
            expected_json=json_dumps(row.get("expected") or {}),
            created_at=_datetime_or_now(row.get("createdAt")),
        )

    def _insert_theme_rows(self, collection: str, rows: list[dict[str, Any]], factory) -> int:
        if not rows:
            return 0
        docs = [factory(item) for item in rows]
        self.db[collection].insert_many(docs, ordered=False)
        return len(docs)

    @staticmethod
    def _factor_doc(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "datasetId": str(item.get("datasetId") or ""),
            "snapshotId": str(item.get("snapshotId") or ""),
            "snapshotType": str(item.get("snapshotType") or "half_hour"),
            "tradingDate": str(item.get("tradingDate") or ""),
            "slotTime": str(item.get("slotTime") or ""),
            "strategyVersion": str(item.get("strategyVersion") or "theme-trend-v12"),
            "configHash": str(item.get("configHash") or ""),
            "randomSeed": int(item.get("randomSeed") or 0),
            "themeId": str(item.get("themeId") or ""),
            "themeName": str(item.get("themeName") or ""),
            "heatScore": float(item.get("heatScore") or 0.0),
            "momentumScore": float(item.get("momentumScore") or 0.0),
            "breadthScore": float(item.get("breadthScore") or 0.0),
            "fundScore": float(item.get("fundScore") or 0.0),
            "leadershipScore": float(item.get("leadershipScore") or 0.0),
            "correlationScore": float(item.get("correlationScore") or 0.0),
            "crowdingRisk": float(item.get("crowdingRisk") or 0.0),
            "persistenceScore": float(item.get("persistenceScore") or 0.0),
            "rotationState": str(item.get("rotationState") or "neutral"),
            "rank": int(item.get("rank") or 0),
            "qualityFlags": item.get("qualityFlags") if isinstance(item.get("qualityFlags"), list) else [],
            "lifecycle": str(item.get("lifecycle") or "neutral"),
        }

    @staticmethod
    def _exposure_doc(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "datasetId": str(item.get("datasetId") or ""),
            "snapshotId": str(item.get("snapshotId") or ""),
            "snapshotType": str(item.get("snapshotType") or "half_hour"),
            "tradingDate": str(item.get("tradingDate") or ""),
            "slotTime": str(item.get("slotTime") or ""),
            "strategyVersion": str(item.get("strategyVersion") or "theme-trend-v12"),
            "configHash": str(item.get("configHash") or ""),
            "randomSeed": int(item.get("randomSeed") or 0),
            "code": str(item.get("code") or ""),
            "themeId": str(item.get("themeId") or ""),
            "themeName": str(item.get("themeName") or ""),
            "role": str(item.get("role") or "unknown"),
            "roleScore": float(item.get("roleScore") or 0.0),
            "exposureWeight": float(item.get("exposureWeight") or 0.0),
            "themeContribution": float(item.get("themeContribution") or 0.0),
            "riskPenalty": float(item.get("riskPenalty") or 0.0),
            "reasons": item.get("reasons") if isinstance(item.get("reasons"), list) else [],
        }

    @staticmethod
    def _theme_signal_doc(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "datasetId": str(item.get("datasetId") or ""),
            "snapshotId": str(item.get("snapshotId") or ""),
            "snapshotType": str(item.get("snapshotType") or "half_hour"),
            "tradingDate": str(item.get("tradingDate") or ""),
            "slotTime": str(item.get("slotTime") or ""),
            "strategyVersion": str(item.get("strategyVersion") or "theme-trend-v12"),
            "configHash": str(item.get("configHash") or ""),
            "randomSeed": int(item.get("randomSeed") or 0),
            "themeId": str(item.get("themeId") or ""),
            "themeName": str(item.get("themeName") or ""),
            "signal": str(item.get("signal") or "watch"),
            "risk": str(item.get("risk") or "none"),
            "lifecycle": str(item.get("lifecycle") or "neutral"),
            "score": float(item.get("score") or 0.0),
        }

    @staticmethod
    def _quality_report_doc(report: dict[str, Any]) -> dict[str, Any]:
        return {
            "datasetId": str(report.get("datasetId") or ""),
            "snapshotType": str(report.get("snapshotType") or "half_hour"),
            "strategyVersion": str(report.get("strategyVersion") or "theme-trend-v12"),
            "configHash": str(report.get("configHash") or ""),
            "randomSeed": int(report.get("randomSeed") or 0),
            "passed": bool(report.get("passed", False)),
            "severity": str(report.get("severity") or "pass"),
            "researchGrade": str(report.get("researchGrade") or "research_ready"),
            "issues": report.get("issues") if isinstance(report.get("issues"), list) else [],
            "warnings": report.get("warnings") if isinstance(report.get("warnings"), list) else [],
            "stats": report.get("stats") if isinstance(report.get("stats"), dict) else {},
            "themeCoverage": float(report.get("themeCoverage") or 0.0),
            "frameCount": int(report.get("frameCount") or 0),
            "stockCount": int(report.get("stockCount") or 0),
            "themeCount": int(report.get("themeCount") or 0),
            "createdAt": _utc_now_naive(),
        }

    @staticmethod
    def _drop_mongo_id(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "_id"}


def _blank_to_none(value: Any) -> str | None:
    text = str(value or "")
    return text or None


def _maybe_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _maybe_int(value: Any) -> int | None:
    return int(value) if value is not None else None


def _datetime_or_now(value: Any) -> datetime:
    return value if isinstance(value, datetime) else _utc_now_naive()


def _datetime_or_none(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def _iso_or_none(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value) if value is not None else None


def _utc_now_naive() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


    # ========== Trade Journal ==========

    def save_journal_entry(self, entry):
        """Save or update a trade journal entry (upsert by id)."""
        from backend.data.models import TradeJournal
        doc = entry.to_dict()
        self.db["trade_journal"].replace_one({"id": entry.id}, doc, upsert=True)
        row = self.db["trade_journal"].find_one({"id": entry.id})
        return TradeJournal.from_dict(self._drop_mongo_id(row)) if row else entry

    def get_journal_entry(self, entry_id: str):
        """Get a single journal entry by id."""
        row = self.db["trade_journal"].find_one({"id": entry_id})
        return self._drop_mongo_id(row) if row else None

    def list_journal_entries(
        self,
        stock_code=None,
        trade_type=None,
        direction=None,
        date_from=None,
        date_to=None,
        review_tags=None,
        limit=50,
        offset=0,
    ):
        """List journal entries with optional filters."""
        query = {}
        if stock_code:
            query["stockCode"] = stock_code
        if trade_type:
            query["tradeType"] = trade_type
        if direction:
            query["direction"] = direction
        if date_from or date_to:
            time_filter = {}
            if date_from:
                time_filter["$gte"] = date_from
            if date_to:
                time_filter["$lte"] = date_to
            if time_filter:
                query["tradeTime"] = time_filter
        if review_tags:
            query["reviewTags"] = {"$in": review_tags}

        cursor = (
            self.db["trade_journal"]
            .find(query)
            .sort([("tradeTime", -1)])
            .skip(offset)
            .limit(limit)
        )
        return [self._drop_mongo_id(row) for row in cursor]

    def count_journal_entries(
        self,
        stock_code=None,
        trade_type=None,
        direction=None,
        date_from=None,
        date_to=None,
    ):
        """Count journal entries with optional filters."""
        query = {}
        if stock_code:
            query["stockCode"] = stock_code
        if trade_type:
            query["tradeType"] = trade_type
        if direction:
            query["direction"] = direction
        if date_from or date_to:
            time_filter = {}
            if date_from:
                time_filter["$gte"] = date_from
            if date_to:
                time_filter["$lte"] = date_to
            if time_filter:
                query["tradeTime"] = time_filter
        return self.db["trade_journal"].count_documents(query)

    def delete_journal_entry(self, entry_id: str):
        """Delete a single journal entry by id. Returns True if deleted."""
        result = self.db["trade_journal"].delete_one({"id": entry_id})
        return result.deleted_count > 0

    def delete_linked_exits(self, linked_entry_id: str):
        """Delete all exit entries linked to a given entry. Returns count deleted."""
        result = self.db["trade_journal"].delete_many({"linkedEntryId": linked_entry_id})
        return result.deleted_count

    def update_journal_entry(self, entry_id: str, updates: dict):
        """Update specific fields of a journal entry. Returns updated doc or None."""
        from datetime import UTC, datetime
        updates["updatedAt"] = datetime.now(UTC).isoformat()
        result = self.db["trade_journal"].update_one({"id": entry_id}, {"$set": updates})
        if result.matched_count == 0:
            return None
        return self.get_journal_entry(entry_id)

    def get_journal_stats(self):
        """Get aggregated journal statistics."""
        pipeline = [
            {"$match": {"reviewTags": {"$ne": None, "$not": {"$size": 0}}}},
            {"$unwind": "$reviewTags"},
            {"$group": {"_id": "$reviewTags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
        ]
        tag_counts = {
            doc["_id"]: doc["count"]
            for doc in self.db["trade_journal"].aggregate(pipeline)
        }

        entries_with_pnl = list(
            self.db["trade_journal"].find(
                {"pnl": {"$ne": None}, "tradeType": "exit"}
            )
        )
        total_pnl = sum(e.get("pnl", 0) for e in entries_with_pnl)
        win_count = sum(1 for e in entries_with_pnl if e.get("pnl", 0) > 0)
        total_exits = len(entries_with_pnl)

        return {
            "tagCounts": tag_counts,
            "totalPnl": total_pnl,
            "winRate": win_count / total_exits if total_exits > 0 else 0,
            "totalExits": total_exits,
        }
