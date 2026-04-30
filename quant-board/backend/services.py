from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.core.backtest import BacktestEngine, Optimizer, normalize_strategy_name
from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.quality_gate import evaluate_snapshot_quality
from backend.data.repository import Repository
from backend.utils import json_dumps, json_loads, new_id, read_json_file, stable_hash


DEFAULT_BACKTEST_STRATEGY_CONFIG = {
    "momentumPeriods": [3, 5, 8, 13, 21],
    "macdFast": 21,
    "macdSlow": 34,
    "macdSignal": 13,
}


def camel_get(payload: dict[str, Any], snake: str, camel: str | None = None, default: Any = None) -> Any:
    if snake in payload:
        return payload[snake]
    camel_key = camel or snake.split("_")[0] + "".join(part.title() for part in snake.split("_")[1:])
    return payload.get(camel_key, default)


class BacktestService:
    def __init__(self, session: Session):
        self.repo = Repository(session)

    @staticmethod
    def _summary_response(run_id: str, result: dict[str, Any]) -> dict[str, Any]:
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
        return {"id": run_id, "runId": run_id, "run_id": run_id, "result": compact, **compact}

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
        stock_rows = [stock for frame in frames for stock in frame.get("stocks", [])]
        gate = evaluate_snapshot_quality(frames, [{"snapshotId": frame["snapshotId"]} for frame in frames for _ in frame.get("stocks", [])], snapshot_type=snapshot_type)
        if not gate.passed:
            raise ValueError({"qualityGate": gate.to_dict()})

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
            "quality_gate": gate.to_dict(),
        }
        result = BacktestEngine().run(frames, options)
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
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=request_meta["random_seed"],
            config_hash=stable_hash(request_meta),
            request_json=json_dumps(request_meta),
            result_json=json_dumps(result),
        )
        self.repo.save_backtest_run(run)
        return self._summary_response(run_id, result)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = json_loads(run.result_json, {})
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


class OptimizationService:
    def __init__(self, session: Session):
        self.repo = Repository(session)

    def run_ranktrend(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        gate = evaluate_snapshot_quality(frames, [{"snapshotId": frame["snapshotId"]} for frame in frames for _ in frame.get("stocks", [])], snapshot_type=snapshot_type)
        if not gate.passed:
            raise ValueError({"qualityGate": gate.to_dict()})
        search_space = camel_get(payload, "search_space", "searchSpace")
        if not search_space:
            search_space = camel_get(payload, "parameter_grid", "parameterGrid", {})
        request = {
            "method": payload.get("method", "grid"),
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "max_trials": int(camel_get(payload, "max_trials", "trials", 12)),
            "objective": payload.get("objective", "return"),
            "search_space": search_space,
            "strategy_name": strategy_name,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "quality_gate": gate.to_dict(),
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
        result = Optimizer().run(frames, request)
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
                    request_json=json_dumps(artifact_request),
                    result_json=json_dumps(artifact_result),
                )
            )
        run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=request["method"],
            random_seed=request["random_seed"],
            config_hash=stable_hash(request),
            request_json=json_dumps({**payload, **request}),
            result_json=json_dumps(result),
        )
        self.repo.save_optimization_run(run)
        return {"id": run_id, "runId": run_id, "run_id": run_id, "result": result, **result}

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_optimization_run(run_id)
        if not run:
            return None
        result = json_loads(run.result_json, {})
        return {
            "id": run.id,
            "runId": run.id,
            "datasetId": run.dataset_id,
            "strategyName": run.strategy_name,
            "method": run.method,
            "randomSeed": run.random_seed,
            "configHash": run.config_hash,
            "createdAt": run.created_at.isoformat(),
            "result": result,
            **result,
        }


class GoldenService:
    def __init__(self, session: Session):
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
            input_json=json_dumps({"datasetId": dataset_id, "snapshotType": snapshot_type, "sampleLimit": sample_limit, "source": "python_current_output"}),
            expected_json=json_dumps(expected),
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
            input_json=json_dumps(input_meta),
            expected_json=json_dumps(expected),
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
        if case_id:
            case = self.repo.get_golden_case(case_id)
            if not case:
                return {"passed": False, "caseId": case_id, "issues": [f"golden case not found: {case_id}"]}
            expected = json_loads(case.expected_json, {})
            input_meta = json_loads(case.input_json, {})
            target_dataset_id = dataset_id or case.dataset_id or input_meta.get("datasetId")
            snapshot_type = str(payload.get("snapshot_type") or payload.get("snapshotType") or input_meta.get("snapshotType") or "half_hour")
            source = input_meta.get("source") or ("python_current_output" if input_meta.get("sampleLimit") else "unknown")
            rank_trend_config = input_meta.get("rankTrendConfig") or input_meta.get("rank_trend_config") or {}
            frames = self.repo.load_frames(str(target_dataset_id), snapshot_type=snapshot_type, include_payload=False)
            if not frames:
                return {"passed": False, "caseId": case_id, "checked": 0, "issues": [f"dataset has no frames for {snapshot_type}: {target_dataset_id}"]}
            expected_list = self._normalize_expected_payload(expected)
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
