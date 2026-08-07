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
from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.quality_gate import evaluate_snapshot_quality
from backend.data.json_codec import dumps_json_field, loads_json_field
from backend.data.database import SessionLocal
from backend.data.repository import Repository
from backend.data.repository_factory import create_repository, storage_source_label
from backend.optimization.jobs import submit_optimization_job
from backend.optimization.runner import OptimizationRunner
from backend.optimization.search_space import candidate_count, select_candidates
from backend.core.utils import json_dumps, json_loads, new_id, read_json_file, stable_hash



class RankTrendLiveGateAuditService:
    def __init__(self, session: Session | None = None):
        self.repo = create_repository(session)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(payload.get("dataset_id") or payload.get("datasetId") or "")
        if not dataset_id:
            raise ValueError("dataset_id is required")
        snapshot_type = str(payload.get("snapshot_type") or payload.get("snapshotType") or "half_hour")
        anchor_samples = payload.get("anchor_samples") or payload.get("anchorSamples") or []
        confidence_thresholds = payload.get("confidence_thresholds") or payload.get("confidenceThresholds") or [
            70,
            75,
            80,
            85,
            90,
            95,
        ]
        research_all_frames = bool(payload.get("research_all_frames") or payload.get("researchAllFrames"))
        focus_codes = {
            str(code).strip()
            for code in (payload.get("focus_codes") or payload.get("focusCodes") or [])
            if str(code).strip()
        }
        start_date, end_date = self._resolve_date_window(
            start_date=payload.get("start_date") or payload.get("startDate"),
            end_date=payload.get("end_date") or payload.get("endDate"),
        )
        max_snapshots = payload.get("max_snapshots") or payload.get("maxSnapshots")
        records, frames, stock_rows, _sector_rows = self.repo.load_dataset_bundle_slice(
            dataset_id,
            snapshot_types=[snapshot_type],
            start_date=start_date,
            end_date=end_date,
            max_snapshots=max_snapshots,
        )
        merged_frames = self._merge_frames(frames, stock_rows)
        if not merged_frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")

        baseline_signal_maps = self._replay_frame_signals_by_snapshot(merged_frames)
        variant_signal_maps_by_snapshot = self._replay_variant_signal_maps_by_snapshot(merged_frames)
        anchor_index = self._build_anchor_index(anchor_samples, default_snapshot_type=snapshot_type)
        all_findings: list[dict[str, Any]] = []
        focus_findings: list[dict[str, Any]] = []
        ranking_candidates: list[dict[str, Any]] = []

        for frame_index, frame in enumerate(merged_frames):
            snapshot_id = str(frame.get("snapshotId") or "")
            baseline_signal_map = baseline_signal_maps.get(snapshot_id) or {}
            variant_signal_maps = {
                variant_key: signal_maps.get(snapshot_id) or {}
                for variant_key, signal_maps in variant_signal_maps_by_snapshot.items()
            }
            frame_codes = set(baseline_signal_map)
            for signal_map in variant_signal_maps.values():
                frame_codes.update(signal_map)
            frame_codes.update(self._requested_frame_codes(frame=frame, focus_codes=focus_codes, anchor_index=anchor_index))
            for code in sorted(frame_codes):
                baseline_signal = baseline_signal_map.get(code)
                display_signal = baseline_signal or self._select_display_signal(
                    code=code,
                    variant_signal_maps=variant_signal_maps,
                )
                variant_results = self._resolve_variant_results(
                    baseline_signal=baseline_signal,
                    code=code,
                    variant_signal_maps=variant_signal_maps,
                )
                signal = display_signal
                anchor = anchor_index.get(
                    (
                        code,
                        str(frame.get("tradingDate") or ""),
                        str(frame.get("slotTime") or ""),
                        str(frame.get("type") or snapshot_type or "half_hour"),
                    )
                )
                hotlist_buy_tags = classify_hotlist_buy_pattern(signal)
                baseline = variant_results.get("baseline") or {}
                finding = {
                    "snapshotId": snapshot_id,
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "code": code,
                    "name": signal.get("name"),
                    "baselineTriggered": baseline.get("triggered"),
                    "baselineJumpTriggered": ((baseline.get("jump") or {}).get("triggered")),
                    "baselineFusionTriggered": ((baseline.get("fusion") or {}).get("triggered")),
                    "firstJumpFailure": summarize_first_failure((baseline.get("jump") or {}).get("checks") or []),
                    "firstFusionFailure": summarize_first_failure((baseline.get("fusion") or {}).get("checks") or []),
                    "variantResults": variant_results,
                    "baselineSignal": baseline_signal,
                    "displaySignal": display_signal if display_signal else None,
                    "hotlistBuyTags": hotlist_buy_tags,
                    "isAnchor": anchor is not None,
                    "anchorLabel": anchor.get("label") if anchor else None,
                    "anchorEvidence": anchor.get("evidence") if anchor else None,
                    "anchorStatus": anchor.get("status") if anchor else None,
                    "isPositiveOutcome": self._is_positive_outcome(signal),
                    "candidateTier": _nested_get(signal, "rankTrend", "strategy", "candidateTier"),
                    "cycleStage": _nested_get(signal, "rankTrend", "cycle", "stage"),
                    "cycleDecisionAction": _nested_get(signal, "rankTrend", "cycle", "decision", "action"),
                    "sampleQualityStatus": _nested_get(signal, "rankTrend", "meta", "sampleQuality", "status"),
                }
                all_findings.append(finding)
                if not focus_codes or code in focus_codes:
                    focus_findings.append(finding)
                ranking_candidates.append(
                    {
                        **rank_shadow_candidate(signal),
                        "snapshotId": snapshot_id,
                        "tradingDate": frame.get("tradingDate"),
                        "slotTime": frame.get("slotTime"),
                        "frameIndex": frame_index,
                    }
                )

        all_findings.sort(key=lambda item: (str(item.get("snapshotId") or ""), str(item.get("code") or "")))
        focus_findings.sort(key=lambda item: (str(item.get("snapshotId") or ""), str(item.get("code") or "")))
        ranking_suggestions = sorted(
            ranking_candidates,
            key=lambda item: (-int(item.get("score") or 0), str(item.get("code") or "")),
        )
        daily_summaries = self._build_daily_summaries(focus_findings)
        acc_delta_present_ratio = self._compute_acc_delta_present_ratio(stock_rows)
        research_findings = all_findings if research_all_frames else focus_findings
        anchor_findings = [
            item
            for item in research_findings
            if item.get("isAnchor") and item.get("anchorStatus") == "confirmed"
        ]
        extended_hotlist_findings = [
            item
            for item in research_findings
            if not item.get("isAnchor") and item.get("hotlistBuyTags")
        ]
        research_summary_findings = anchor_findings + extended_hotlist_findings

        return {
            "meta": {
                "datasetId": dataset_id,
                "snapshotType": snapshot_type,
                "recordCount": len(records),
                "frameCount": len(merged_frames),
                "anchorSampleStatusCounts": self._count_anchor_statuses(anchor_samples),
                **build_audit_meta(acc_delta_present_ratio=acc_delta_present_ratio),
                "outcomeLabelPolicy": (
                    "后续涨停型/短线爆发型当前只从 signal.isPositiveOutcome 或外部 outcomeLabels/"
                    "resultLabels 读取；未提供后验标签时 positiveRecall 统计保持 0，不自动用收益推断。"
                ),
            },
            "focusFindings": focus_findings,
            "dailySummaries": daily_summaries,
            "rankingSuggestions": ranking_suggestions,
            "anchorFindings": anchor_findings,
            "extendedHotlistFindings": extended_hotlist_findings,
            "confidenceThresholdScan": scan_jump_confidence_thresholds(
                research_summary_findings,
                [float(value) for value in confidence_thresholds],
            ),
            "jumpDefinitionReplaySummary": summarize_jump_definition_replays(research_findings),
            "fusionGateMissSummary": summarize_fusion_gate_misses(research_summary_findings),
        }

    @staticmethod
    def _build_anchor_index(
        anchor_samples: list[dict[str, Any]],
        *,
        default_snapshot_type: str,
    ) -> dict[tuple[str, str, str, str], dict[str, Any]]:
        index: dict[tuple[str, str, str, str], dict[str, Any]] = {}
        for item in anchor_samples:
            if not isinstance(item, dict):
                continue
            if str(item.get("status") or "confirmed") == "exclude":
                continue
            key = (
                str(item.get("code") or "").strip(),
                str(item.get("tradingDate") or "").strip(),
                str(item.get("slotTime") or "").strip(),
                str(item.get("snapshotType") or default_snapshot_type or "half_hour").strip(),
            )
            if all(key):
                index[key] = item
        return index

    @staticmethod
    def _count_anchor_statuses(anchor_samples: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in anchor_samples:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "confirmed")
            counts[status] = int(counts.get(status) or 0) + 1
        return counts

    @staticmethod
    def _requested_frame_codes(
        *,
        frame: dict[str, Any],
        focus_codes: set[str],
        anchor_index: dict[tuple[str, str, str, str], dict[str, Any]],
    ) -> set[str]:
        trading_date = str(frame.get("tradingDate") or "")
        slot_time = str(frame.get("slotTime") or "")
        snapshot_type = str(frame.get("type") or "half_hour")
        stock_codes = {
            str(row.get("code") or "").strip()
            for row in (frame.get("stocks") or [])
            if str(row.get("code") or "").strip()
        }
        requested = {code for code in focus_codes if code in stock_codes}
        for code, anchor_date, anchor_slot, anchor_snapshot_type in anchor_index:
            if (
                anchor_date == trading_date
                and anchor_slot == slot_time
                and anchor_snapshot_type == snapshot_type
                and code in stock_codes
            ):
                requested.add(code)
        return requested

    @staticmethod
    def _is_positive_outcome(signal: dict[str, Any]) -> bool:
        if signal.get("isPositiveOutcome") is not None:
            return bool(signal.get("isPositiveOutcome"))
        labels = signal.get("outcomeLabels") or signal.get("resultLabels") or []
        if not isinstance(labels, list):
            return False
        return bool({"limit_up_1_4_bars", "short_burst_gain_ge_6"} & {str(label) for label in labels})

    def _resolve_date_window(
        self,
        *,
        start_date: str | None,
        end_date: str | None,
    ) -> tuple[str | None, str | None]:
        if start_date or end_date:
            return start_date, end_date
        today = self._today()
        return ((today - timedelta(days=6)).isoformat(), today.isoformat())

    def _today(self) -> date:
        return date.today()

    @staticmethod
    def _merge_frames(
        frames: list[dict[str, Any]],
        stock_rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        stock_rows_by_snapshot: dict[str, list[dict[str, Any]]] = {}
        for row in stock_rows:
            snapshot_id = str(row.get("snapshotId") or "")
            stock_rows_by_snapshot.setdefault(snapshot_id, []).append(row)
        merged: list[dict[str, Any]] = []
        for frame in sorted(frames, key=lambda item: (int(item.get("timestamp") or 0), str(item.get("snapshotId") or ""))):
            snapshot_id = str(frame.get("snapshotId") or "")
            merged.append({**frame, "stocks": stock_rows_by_snapshot.get(snapshot_id, [])})
        return merged

    def _replay_frame_signals_by_snapshot(
        self,
        merged_frames: list[dict[str, Any]],
        *,
        jump_delta_pct: float = 15.0,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        output: dict[str, dict[str, dict[str, Any]]] = {}
        for index in range(len(merged_frames)):
            frame_slice = merged_frames[: index + 1]
            snapshot_id = str(merged_frames[index].get("snapshotId") or "")
            output[snapshot_id] = self._replay_frame_signals(frame_slice, jump_delta_pct=jump_delta_pct)
        return output

    def _replay_frame_signals(
        self,
        frames: list[dict[str, Any]],
        *,
        jump_delta_pct: float = 15.0,
    ) -> dict[str, dict[str, Any]]:
        config = RankTrendConfig.from_patch({"jumpDeltaPct": jump_delta_pct})
        signals = RankTrendPythonEngine(config).replay(frames, meta={"sampleQuality": "ok", "warnings": []})
        current_snapshot_id = str(frames[-1].get("snapshotId") or "")
        output: dict[str, dict[str, Any]] = {}
        for signal in signals:
            if str(signal.get("snapshotId") or "") != current_snapshot_id:
                continue
            code = str(signal.get("code") or "")
            if code:
                output[code] = signal
        return output

    def _resolve_variant_results(
        self,
        *,
        baseline_signal: dict[str, Any] | None,
        code: str,
        variant_signal_maps: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        if baseline_signal is None:
            baseline_results = self._build_missing_baseline_results(code=code)
        else:
            baseline_results = evaluate_shadow_variants(baseline_signal, variants=DEFAULT_SHADOW_VARIANTS)
        resolved: dict[str, dict[str, Any]] = {}
        for variant in DEFAULT_SHADOW_VARIANTS:
            current = dict((baseline_results.get(variant.key) or {}))
            if not variant.requires_separate_replay:
                resolved[variant.key] = current
                continue
            signal_map = variant_signal_maps.get(variant.key) or {}
            replay_signal = signal_map.get(code)
            if replay_signal is None:
                resolved[variant.key] = {
                    **current,
                    "triggered": False,
                    "liveGateTriggered": False,
                    "missingSignal": True,
                    "failureReason": "signal_missing_in_replay",
                    "requiresReplayConfirmation": False,
                    "evaluationMode": "replay_missing",
                    "jump": {
                        "triggered": False,
                        "missing": True,
                        "checks": [],
                    },
                    "fusion": {
                        "triggered": False,
                        "missing": True,
                        "checks": [],
                    },
                }
                continue
            replay_result = evaluate_shadow_variants(replay_signal, variants=(variant,)).get(variant.key) or {}
            replay_result["triggered"] = replay_result.get("liveGateTriggered")
            replay_result["requiresReplayConfirmation"] = False
            replay_result["evaluationMode"] = "separate_replay"
            resolved[variant.key] = replay_result
        return resolved

    @staticmethod
    def _build_missing_baseline_results(code: str) -> dict[str, dict[str, Any]]:
        baseline_result = {
            "variant": "baseline",
            "requiresSeparateReplay": False,
            "triggered": False,
            "liveGateTriggered": False,
            "missingSignal": True,
            "failureReason": "signal_missing_in_baseline_replay",
            "requiresReplayConfirmation": False,
            "evaluationMode": "baseline_missing",
            "jump": {
                "triggered": False,
                "missing": True,
                "signal": {"code": code},
                "checks": [
                    {
                        "name": "signal_missing_in_baseline_replay",
                        "passed": False,
                    }
                ],
            },
            "fusion": {
                "triggered": False,
                "missing": True,
                "checks": [
                    {
                        "name": "signal_missing_in_baseline_replay",
                        "passed": False,
                    }
                ],
            },
        }
        return {variant.key: dict(baseline_result, variant=variant.key) for variant in DEFAULT_SHADOW_VARIANTS}

    @staticmethod
    def _select_display_signal(
        *,
        code: str,
        variant_signal_maps: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        for variant in DEFAULT_SHADOW_VARIANTS:
            signal_map = variant_signal_maps.get(variant.key) or {}
            signal = signal_map.get(code)
            if isinstance(signal, dict) and signal:
                return signal
        return {}

    def _replay_variant_signal_maps_by_snapshot(
        self,
        merged_frames: list[dict[str, Any]],
    ) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        replay_maps_by_delta: dict[float, dict[str, dict[str, dict[str, Any]]]] = {}
        for variant in DEFAULT_SHADOW_VARIANTS:
            if not variant.requires_separate_replay:
                continue
            if variant.jump_delta_pct not in replay_maps_by_delta:
                replay_maps_by_delta[variant.jump_delta_pct] = self._replay_frame_signals_by_snapshot(
                    merged_frames,
                    jump_delta_pct=variant.jump_delta_pct,
                )
        maps: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
        for variant in DEFAULT_SHADOW_VARIANTS:
            if not variant.requires_separate_replay:
                continue
            maps[variant.key] = replay_maps_by_delta[variant.jump_delta_pct]
        return maps

    @staticmethod
    def _build_daily_summaries(focus_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_date: dict[str, dict[str, Any]] = {}
        for item in focus_findings:
            trading_date = str(item.get("tradingDate") or "")
            summary = by_date.setdefault(
                trading_date,
                {
                    "tradingDate": trading_date,
                    "focusFrameCount": 0,
                    "baselineTriggeredCount": 0,
                    "variantTriggeredCounts": {},
                },
            )
            summary["focusFrameCount"] += 1
            if item.get("baselineTriggered"):
                summary["baselineTriggeredCount"] += 1
            for variant_key, variant_result in (item.get("variantResults") or {}).items():
                if variant_result.get("triggered"):
                    counts = summary["variantTriggeredCounts"]
                    counts[variant_key] = int(counts.get(variant_key) or 0) + 1
        return [by_date[key] for key in sorted(by_date)]

    @staticmethod
    def _compute_acc_delta_present_ratio(stock_rows: list[dict[str, Any]]) -> float:
        total = 0
        present = 0
        for row in stock_rows:
            total += 1
            if row.get("accDelta") not in (None, ""):
                present += 1
        if total <= 0:
            return 0.0
        return round(present / total, 4)
