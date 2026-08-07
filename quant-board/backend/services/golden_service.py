from __future__ import annotations
import gzip
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from sqlalchemy.orm import Session
from backend.analysis.ranktrend.engine import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend.live_gate_shadow_audit import (
    DEFAULT_SHADOW_VARIANTS,
    _nested_get,
    build_audit_meta,
    classify_hotlist_buy_pattern,
    evaluate_shadow_variants,
    rank_shadow_candidate,
    scan_jump_confidence_thresholds,
    summarize_fusion_gate_misses,
    summarize_first_failure,
    summarize_jump_definition_replays,
)
from backend.analysis.ranktrend.jump_research import build_jump_research_request, summarize_jump_research
from backend.analysis.theme.trend import ThemeTrendConfig, ThemeTrendPythonEngine
from backend.core.backtest import (
    DEFAULT_TRADE_CONFIG,
    V5_LIFECYCLE_FUSION_TRADE_DEFAULTS,
    BacktestEngine,
    TradeSimulator,
    normalize_strategy_name,
)
from backend.data.models.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.ingest.quality_gate import evaluate_snapshot_quality
from backend.data.ingest.json_codec import dumps_json_field, loads_json_field
from backend.data.models.database import SessionLocal
from backend.data.repositories.repository import Repository
from backend.data.repositories.repository_factory import create_repository, storage_source_label
from backend.optimization.jobs import submit_optimization_job
from backend.optimization.runner import OptimizationRunner
from backend.optimization.search_space import candidate_count, select_candidates
from backend.core.utils import json_dumps, json_loads, new_id, read_json_file, stable_hash



class GoldenService:
    def __init__(self, session: Session | None):
        self.repo = create_repository(session)

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
        normalized: list[dict[str, Any]] = []
        for signal in signals:
            rank_trend = signal.get("rankTrend") or {}
            technical = rank_trend.get("technical") or {}
            cycle = rank_trend.get("cycle") or {}
            decision = rank_trend.get("decision") or {}
            normalized.append(
                {
                    "snapshotId": signal.get("snapshotId"),
                    "code": signal.get("code"),
                    "candidateTier": signal.get("candidateTier"),
                    "action": signal.get("action"),
                    "stage": signal.get("stage"),
                    "regime": signal.get("regime"),
                    "rank": signal.get("rank"),
                    "confidence": signal.get("confidence"),
                    "finalSignal": (decision.get("final") or {}).get("signal"),
                    "technicalSignals": technical.get("signals"),
                    "momentumProfile": technical.get("momentumProfile"),
                    "risk": rank_trend.get("risk"),
                    "cycle": {
                        "transition": cycle.get("transition"),
                        "entryAdvice": cycle.get("entryAdvice"),
                        "decision": cycle.get("decision"),
                    },
                    "decision": {
                        "base": decision.get("base"),
                        "final": decision.get("final"),
                    },
                }
            )
        return normalized

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
            cycle = rank_trend.get("cycle") or {}
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
                    "cycle": item.get("cycle")
                    or {
                        "transition": cycle.get("transition"),
                        "entryAdvice": cycle.get("entryAdvice"),
                        "decision": cycle.get("decision"),
                    },
                    "decision": item.get("decision")
                    or {
                        "base": decision.get("base"),
                        "final": decision.get("final"),
                    },
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
