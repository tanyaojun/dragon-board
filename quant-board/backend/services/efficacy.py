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



def compute_signal_efficacy(
    signals: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    """Layer 1: compute signal tier stability, direction accuracy, and tier discrimination."""
    if not signals:
        return {
            "tierRatio": None,
            "directionAccuracy": None,
            "tierDiscrimination": None,
            "diagnostics": "no_signals",
        }

    total = len(signals)
    tier_counts: dict[str, int] = {}

    for signal in signals:
        tier = str(signal.get("candidateTier") or "?")
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    a_plus_b = tier_counts.get("A_MAIN", 0) + tier_counts.get("B_IGNITION", 0)
    tier_ratio = round(a_plus_b / total, 4) if total else 0.0

    # Build frame index for next-bar price lookup
    frame_index: dict[str, int] = {}
    for idx, frame in enumerate(frames):
        sid = str(frame.get("snapshotId") or "")
        frame_index[sid] = idx

    a_correct = 0
    a_total = 0
    n_correct = 0
    n_total = 0

    for signal in signals:
        tier = str(signal.get("candidateTier") or "?")
        sid = str(signal.get("snapshotId") or "")
        frame_pos = frame_index.get(sid)
        if frame_pos is None or frame_pos + 1 >= len(frames):
            continue
        next_frame = frames[frame_pos + 1]
        next_stocks = next_frame.get("stocks") or []
        next_stock = next((s for s in next_stocks if str(s.get("code") or "") == str(signal.get("code") or "")), None)
        if next_stock is None:
            continue
        try:
            current_price = float(signal.get("price") or 0)
            next_price = float(next_stock.get("price") or 0)
        except (TypeError, ValueError):
            continue
        price_up = next_price > current_price

        if tier == "A_MAIN":
            a_total += 1
            if price_up:
                a_correct += 1
        elif tier == "N_NEUTRAL":
            n_total += 1
            if price_up:
                n_correct += 1

    direction_accuracy = round(a_correct / a_total, 4) if a_total > 0 else None
    n_accuracy = round(n_correct / n_total, 4) if n_total > 0 else None
    tier_discrimination = round((direction_accuracy or 0) - (n_accuracy or 0), 4) if direction_accuracy is not None and n_accuracy is not None else None

    # Binomial test p-value for direction accuracy vs random (H0: p = 0.5)
    p_val: float | None = None
    if a_total >= 5 and direction_accuracy is not None:
        se = math.sqrt(0.5 * 0.5 / a_total)
        z = (direction_accuracy - 0.5) / se if a_total > 0 else 0
        p_val = round(0.5 * (1 + math.erf(z / math.sqrt(2))), 4)
        p_val = 1 - p_val  # one-sided: P(Z > z) under H0

    layer1_green = (
        direction_accuracy is not None and direction_accuracy > 0.55
        and (p_val is not None and p_val < 0.10)
        and tier_discrimination is not None and tier_discrimination > 0.05
        and 0.02 <= tier_ratio <= 0.15
    )

    return {
        "tierRatio": tier_ratio,
        "aPlusBTierCount": a_plus_b,
        "tierCounts": tier_counts,
        "totalSignals": total,
        "directionAccuracy": direction_accuracy,
        "aMainSamples": a_total,
        "nNeutralSamples": n_total,
        "tierDiscrimination": tier_discrimination,
        "binomialPValue": p_val,
        "thresholds": {
            "directionAccuracyMin": 0.55,
            "binomialPMax": 0.10,
            "tierDiscriminationMin": 0.05,
            "tierRatioMin": 0.02,
            "tierRatioMax": 0.15,
        },
        "layer1Status": "green" if layer1_green else "red",
    }


def compute_execution_entry_layer1_efficacy(
    trade_events: list[dict[str, Any]],
    frames: list[dict[str, Any]],
) -> dict[str, Any]:
    """Layer 1 execution path: only evaluate actually filled entry events."""
    entry_events = [
        event
        for event in trade_events
        if isinstance(event, dict) and str(event.get("action") or "").lower() == "buy"
    ]
    signals = [
        {
            "snapshotId": event.get("signalSnapshotId") or event.get("snapshotId"),
            "code": event.get("code"),
            "price": event.get("price"),
            "candidateTier": event.get("candidateTier"),
        }
        for event in entry_events
    ]
    result = compute_signal_efficacy(signals=signals, frames=frames)
    result["sampleScope"] = "execution_entry"
    result["entryEventCount"] = len(entry_events)
    return result


def compute_execution_quality(
    h1_summary: dict[str, Any],
    h2_summary: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Layer 2: compute execution bias between current_bar (H1) and next_bar (H2).

    history, if provided, must be a list of dicts each containing
    {"h1Summary": {"totalReturn": ...}, "h2Summary": {"totalReturn": ...}}.
    Only the last 4 entries are used to compute directionRatio.
    """
    h1_return = float(h1_summary.get("totalReturn") or 0)
    h2_return = float(h2_summary.get("totalReturn") or 0)
    bias = round(h1_return - h2_return, 4)
    abs_h1 = abs(h1_return)
    threshold = min(abs_h1, 0.15) if abs_h1 > 0 else 0.15

    h1_trades = int(h1_summary.get("tradeCount") or 0)
    h2_trades = int(h2_summary.get("tradeCount") or 0)
    trade_diff = h2_trades - h1_trades

    h1_dd = float(h1_summary.get("maxDrawdown") or 0)
    h2_dd = float(h2_summary.get("maxDrawdown") or 0)
    dd_diff = round(abs(h1_dd - h2_dd), 4)

    direction_ratio = 1.0
    if history:
        recent = history[-4:]
        h1_better = sum(
            1 for h in recent
            if float((h.get("h1Summary") or {}).get("totalReturn") or 0)
            >= float((h.get("h2Summary") or {}).get("totalReturn") or 0)
        )
        direction_ratio = round(h1_better / len(recent), 2) if recent else 1.0

    bias_ok = abs(bias) <= threshold
    direction_ok = direction_ratio >= 0.75
    trade_diff_ok = trade_diff <= h1_trades * 0.3 if h1_trades > 0 else True
    dd_diff_ok = dd_diff <= 0.05

    all_green = bias_ok and direction_ok and trade_diff_ok and dd_diff_ok
    if all_green:
        status = "green"
    elif h1_return > h2_return and not bias_ok:
        status = "yellow"  # optimistic bias: H1 > H2 but deviation exceeds threshold
    elif h1_return < h2_return:
        status = "red"  # next_bar outperforms current_bar: chasing/front-running
    else:
        status = "red"

    return {
        "bias": bias,
        "biasThreshold": threshold,
        "biasOk": bias_ok,
        "directionRatio": direction_ratio,
        "directionOk": direction_ok,
        "tradeCountDiff": trade_diff,
        "tradeCountDiffOk": trade_diff_ok,
        "drawdownDiff": dd_diff,
        "drawdownDiffOk": dd_diff_ok,
        "layer2Status": status,
    }


def compute_alignment(
    repo: Any,
    run_ids: list[str],
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Layer 3: cross-reference trade_journal execution records with backtest signals."""
    if not hasattr(repo, "list_journal_entries"):
        return {"alignmentStatus": "unavailable", "reason": "journal requires MongoDB storage backend"}

    journal_entries = repo.list_journal_entries(
        status="reviewed",
        date_from=start_date,
        date_to=end_date,
        limit=200,
    )
    executed = [
        e for e in journal_entries
        if e.get("entryPrice") is not None and float(e.get("entryPrice") or 0) > 0
    ]
    if not executed:
        return {
            "journalExecutedCount": 0,
            "signalCodeCount": 0,
            "intersectionCount": 0,
            "signalOnlyCount": 0,
            "journalOnlyCount": 0,
            "intersectionCodes": [],
            "signalOnlyCodes": [],
            "journalOnlyCodes": [],
            "intersectionPnl": 0,
            "intersectionPnlPct": 0,
            "sufficientSample": False,
            "alignmentStatus": "insufficient_data",
        }

    signal_codes: set[str] = set()
    for run_id in run_ids:
        if not run_id:
            continue
        bt_run = repo.get_backtest_run(run_id)
        if not bt_run:
            continue
        result_json = loads_json_field(getattr(bt_run, "result_json", "{}"), {})
        signals = result_json.get("signals") or []
        for s in signals:
            code = str(s.get("code") or "")
            if code:
                signal_codes.add(code)

    if run_ids and not signal_codes:
        return {"alignmentStatus": "unavailable", "reason": "no backtest runs found for given run_ids"}

    journal_codes = {str(e.get("stockCode") or e.get("stock_code", "")) for e in executed}

    intersection = signal_codes & journal_codes
    signal_only = signal_codes - journal_codes
    journal_only = journal_codes - signal_codes

    intersection_entries = [e for e in executed if str(e.get("stockCode") or e.get("stock_code", "")) in intersection]
    intersection_pnl = sum(float(e.get("pnl") or 0) for e in intersection_entries)
    intersection_pnl_pct = round(sum(float(e.get("pnlPct") or 0) for e in intersection_entries), 4)

    sufficient_sample = len(executed) >= 10

    return {
        "journalExecutedCount": len(executed),
        "signalCodeCount": len(signal_codes),
        "intersectionCount": len(intersection),
        "signalOnlyCount": len(signal_only),
        "journalOnlyCount": len(journal_only),
        "intersectionCodes": sorted(intersection),
        "signalOnlyCodes": sorted(signal_only)[:30],
        "journalOnlyCodes": sorted(journal_only)[:30],
        "intersectionPnl": intersection_pnl,
        "intersectionPnlPct": intersection_pnl_pct,
        "sufficientSample": sufficient_sample,
        "alignmentStatus": "sufficient" if sufficient_sample else "insufficient_data",
    }
