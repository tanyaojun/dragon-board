from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from backend.analysis.ranktrend import RankTrendConfig, RankTrendPythonEngine
from backend.analysis.ranktrend_live_gate_shadow_audit import (
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
from backend.analysis.ranktrend_jump_research import build_jump_research_request, summarize_jump_research
from backend.analysis.theme_trend import ThemeTrendConfig, ThemeTrendPythonEngine
from backend.core.backtest import BacktestEngine, TradeSimulator, normalize_strategy_name
from backend.data.models import BacktestRun, GoldenRankTrendCase, OptimizationRun
from backend.data.quality_gate import evaluate_snapshot_quality
from backend.data.json_codec import dumps_json_field, loads_json_field
from backend.data.database import SessionLocal
from backend.data.repository import Repository
from backend.data.repository_factory import create_repository, storage_source_label
from backend.optimization.jobs import submit_optimization_job
from backend.optimization.runner import OptimizationRunner
from backend.optimization.search_space import candidate_count, select_candidates
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


MONEY_FLOW_QUALITY_FIELDS = (
    "capitalFlowSource",
    "capital_flow_source",
    "capitalFlowConfidence",
    "capital_flow_confidence",
    "moneyFlowSource",
    "money_flow_source",
    "moneyFlowEstimated",
    "money_flow_estimated",
)

CROSS_MARKET_ZERO_PRICE_PREFIXES = ("001", "003", "006", "007", "009")


def _stock_rows_for_quality(frames: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for frame in frames:
        snapshot_id = frame.get("snapshotId")
        for stock in frame.get("stocks", []):
            row: dict[str, Any] = {"snapshotId": snapshot_id}
            if isinstance(stock, dict):
                row["snapshotId"] = stock.get("snapshotId") or snapshot_id
                for key in ("rowId", "row_id", "code", *MONEY_FLOW_QUALITY_FIELDS):
                    if key in stock:
                        row[key] = stock.get(key)
            rows.append(row)
    return rows


def _price_is_positive(value: Any) -> bool:
    try:
        return float(value or 0) > 0
    except (TypeError, ValueError):
        return False


def _stock_code(value: Any) -> str:
    code = str(value or "").strip()
    return code.zfill(6) if code.isdigit() else code


def _raw_stock_code(value: Any) -> str:
    return str(value or "").strip()


def _has_zero_quote_shape(stock: dict[str, Any]) -> bool:
    return all(not _price_is_positive(stock.get(key)) for key in ("price", "change", "volume", "turnover"))


def _is_cross_market_zero_price_stock(stock: dict[str, Any], a_share_codes: set[str] | None = None) -> bool:
    if not _has_zero_quote_shape(stock):
        return False
    raw_code = _raw_stock_code(stock.get("code"))
    if raw_code == "000000":
        return True
    if not raw_code.isdigit():
        return False
    if a_share_codes is None:
        return raw_code.startswith(("007", "009"))
    if len(raw_code) != 6:
        return raw_code.startswith(CROSS_MARKET_ZERO_PRICE_PREFIXES)
    return raw_code not in a_share_codes and raw_code.startswith(CROSS_MARKET_ZERO_PRICE_PREFIXES)


def _load_a_share_codes(repo: Any) -> set[str] | None:
    database = getattr(repo, "db", None)
    if database is None:
        return None
    try:
        rows = database["stock_names"].find(
            {"active": True, "market": {"$in": ["SH", "SZ", "BJ"]}},
            {"code": 1},
        )
        return {_stock_code(row.get("code")) for row in rows if row.get("code")}
    except Exception:
        return None


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


def _positive_price_stock_rows(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_rows = 0
    impacted_snapshots: set[str] = set()
    empty_snapshots: list[str] = []
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        kept: list[dict[str, Any]] = []
        for stock in stocks:
            if not isinstance(stock, dict):
                kept.append(stock)
                continue
            if _price_is_positive(stock.get("price")):
                kept.append(stock)
            else:
                dropped_rows += 1
                impacted_snapshots.add(str(frame.get("snapshotId") or ""))
        next_frame = {**frame, "stocks": kept}
        if stocks and not kept:
            empty_snapshots.append(str(frame.get("snapshotId") or ""))
        output.append(next_frame)
    return output, {
        "reason": "positive_price_stock_rows_only",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len([frame for frame in output if frame.get("stocks")]),
        "droppedNonPositivePriceRows": dropped_rows,
        "impactedSnapshots": len(impacted_snapshots),
        "emptySnapshotsAfterFilter": len(empty_snapshots),
        "emptySnapshotIdsAfterFilter": empty_snapshots[:50],
    }


def _cross_market_zero_price_stock_rows(
    frames: list[dict[str, Any]],
    a_share_codes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_rows = 0
    impacted_snapshots: set[str] = set()
    empty_snapshots: list[str] = []
    examples: list[dict[str, Any]] = []
    skipped_all_zero_frames: list[str] = []
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        if stocks and all(isinstance(stock, dict) and not _price_is_positive(stock.get("price")) for stock in stocks):
            skipped_all_zero_frames.append(str(frame.get("snapshotId") or ""))
            output.append(frame)
            continue
        kept: list[dict[str, Any]] = []
        for stock in stocks:
            if not isinstance(stock, dict) or not _is_cross_market_zero_price_stock(stock, a_share_codes):
                kept.append(stock)
                continue
            dropped_rows += 1
            snapshot_id = str(frame.get("snapshotId") or "")
            impacted_snapshots.add(snapshot_id)
            if len(examples) < 20:
                examples.append({
                    "snapshotId": snapshot_id,
                    "code": _raw_stock_code(stock.get("code")),
                    "name": str(stock.get("name") or ""),
                })
        next_frame = {**frame, "stocks": kept}
        if stocks and not kept:
            empty_snapshots.append(str(frame.get("snapshotId") or ""))
        output.append(next_frame)
    return output, {
        "reason": "cross_market_zero_price_rows_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len([frame for frame in output if frame.get("stocks")]),
        "droppedCrossMarketZeroPriceRows": dropped_rows,
        "impactedSnapshots": len(impacted_snapshots),
        "emptySnapshotsAfterFilter": len(empty_snapshots),
        "emptySnapshotIdsAfterFilter": empty_snapshots[:50],
        "skippedAllZeroPriceFrames": len(skipped_all_zero_frames),
        "skippedAllZeroPriceFrameIds": skipped_all_zero_frames[:50],
        "aShareUniverseAvailable": a_share_codes is not None,
        "aShareUniverseCodeCount": len(a_share_codes or set()),
        "examples": examples,
    }


def _drop_all_zero_price_frames(frames: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    dropped_ids: list[str] = []
    dropped_rows = 0
    for frame in frames:
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        is_all_zero = bool(stocks) and all(
            isinstance(stock, dict) and not _price_is_positive(stock.get("price"))
            for stock in stocks
        )
        if is_all_zero:
            dropped_ids.append(str(frame.get("snapshotId") or ""))
            dropped_rows += len(stocks)
            continue
        output.append(frame)
    return output, {
        "reason": "all_zero_price_frames_excluded",
        "sourceTargetFrames": len(frames),
        "usableTargetFrames": len(output),
        "droppedAllZeroPriceFrames": len(dropped_ids),
        "droppedAllZeroPriceRows": dropped_rows,
        "droppedSnapshotIds": dropped_ids[:50],
    }


def _price_quality_diagnostics(
    frames: list[dict[str, Any]],
    a_share_codes: set[str] | None = None,
) -> dict[str, Any]:
    cross_market_rows = 0
    cross_market_snapshots: set[str] = set()
    cross_market_examples: list[dict[str, Any]] = []
    all_zero_frame_ids: list[str] = []
    all_zero_rows = 0
    partial_a_share_rows = 0
    partial_a_share_snapshots: set[str] = set()
    partial_a_share_examples: list[dict[str, Any]] = []

    for frame in frames:
        snapshot_id = str(frame.get("snapshotId") or "")
        stocks = frame.get("stocks") if isinstance(frame.get("stocks"), list) else []
        is_all_zero = bool(stocks) and all(
            isinstance(stock, dict) and not _price_is_positive(stock.get("price"))
            for stock in stocks
        )
        if is_all_zero:
            all_zero_frame_ids.append(snapshot_id)
            all_zero_rows += len(stocks)
            continue

        for stock in stocks:
            if not isinstance(stock, dict) or _price_is_positive(stock.get("price")):
                continue
            if _is_cross_market_zero_price_stock(stock, a_share_codes):
                cross_market_rows += 1
                cross_market_snapshots.add(snapshot_id)
                if len(cross_market_examples) < 20:
                    cross_market_examples.append({
                        "snapshotId": snapshot_id,
                        "code": _raw_stock_code(stock.get("code")),
                        "name": str(stock.get("name") or ""),
                    })
                continue
            partial_a_share_rows += 1
            partial_a_share_snapshots.add(snapshot_id)
            if len(partial_a_share_examples) < 20:
                partial_a_share_examples.append({
                    "snapshotId": snapshot_id,
                    "code": _raw_stock_code(stock.get("code")),
                    "name": str(stock.get("name") or ""),
                    "price": stock.get("price"),
                })

    return {
        "role": "report_only",
        "autoApplyDefaults": False,
        "computedBeforeResearchFilters": True,
        "crossMarketZeroPriceRows": {
            "rowCount": cross_market_rows,
            "snapshotCount": len(cross_market_snapshots),
            "examples": cross_market_examples,
            "aShareUniverseAvailable": a_share_codes is not None,
            "aShareUniverseCodeCount": len(a_share_codes or set()),
            "skippedAllZeroPriceFrames": len(all_zero_frame_ids),
        },
        "allZeroPriceFrames": {
            "frameCount": len(all_zero_frame_ids),
            "rowCount": all_zero_rows,
            "snapshotIds": all_zero_frame_ids[:50],
        },
        "partialAshareZeroPriceRows": {
            "rowCount": partial_a_share_rows,
            "snapshotCount": len(partial_a_share_snapshots),
            "examples": partial_a_share_examples,
        },
    }


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


def _ensure_runtime_filtered_frames_usable(frames: list[dict[str, Any]], quality_gate: dict[str, Any]) -> None:
    stats = quality_gate.get("stats") if isinstance(quality_gate.get("stats"), dict) else {}
    min_snapshot_count = int(stats.get("minSnapshotCount") or 2)
    usable_frames = [frame for frame in frames if frame.get("stocks")]
    if len(usable_frames) >= min_snapshot_count:
        return
    failed_gate = {
        **quality_gate,
        "passed": False,
        "severity": "fail",
        "issues": [
            *(quality_gate.get("issues") or []),
            f"runtime filters left usable snapshots below minimum {min_snapshot_count}: {len(usable_frames)}",
        ],
    }
    raise ValueError({"qualityGate": failed_gate})


def read_checkpoint_history(
    jsonl_path: str | Path,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Read recent checkpoint records from long_test_runs.jsonl."""
    path = Path(jsonl_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json_loads(line.strip())
                if record and record.get("checkpointId"):
                    records.append(record)
            except Exception:
                continue
    return records[-limit:] if len(records) > limit else records


def select_longtest_baseline_slots(
    baselines: list[dict[str, Any]],
) -> dict[str, dict[str, Any] | None]:
    """Map legacy/new long-test baselines into trend-page slots."""

    def pick(predicate: Any) -> dict[str, Any] | None:
        for baseline in baselines:
            if predicate(baseline):
                return baseline
        return None

    def label_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("label") or "")

    def lower_label_of(baseline: dict[str, Any]) -> str:
        return label_of(baseline).lower()

    def snapshot_type_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("snapshotType") or "").lower()

    def execution_mode_of(baseline: dict[str, Any]) -> str:
        return str(baseline.get("executionMode") or "").lower()

    def has_trade_metrics(baseline: dict[str, Any]) -> bool:
        return baseline.get("totalReturn") is not None or baseline.get("tradeCount") is not None

    h1 = pick(lambda baseline: label_of(baseline) == "H1_half_hour_current_bar")
    if h1 is None:
        h1 = pick(
            lambda baseline: ("_E2_" in label_of(baseline) or label_of(baseline).startswith("E2_"))
            and "strict_fill" not in lower_label_of(baseline)
        )
    if h1 is None:
        h1 = pick(
            lambda baseline: execution_mode_of(baseline) == "current_bar"
            and snapshot_type_of(baseline) == "half_hour"
            and "signal_forward" not in lower_label_of(baseline)
            and has_trade_metrics(baseline)
        )

    h2 = pick(lambda baseline: label_of(baseline) == "H2_half_hour_next_bar")
    if h2 is None:
        h2 = pick(lambda baseline: "_E3_" in label_of(baseline) or label_of(baseline).startswith("E3_"))
    if h2 is None:
        h2 = pick(lambda baseline: "strict_fill" in lower_label_of(baseline))
    if h2 is None:
        h2 = pick(
            lambda baseline: execution_mode_of(baseline) == "next_bar"
            and snapshot_type_of(baseline) == "half_hour"
            and has_trade_metrics(baseline)
        )

    q1 = pick(lambda baseline: label_of(baseline) == "Q1_quarter_hour_next_bar")
    if q1 is None:
        q1 = pick(lambda baseline: snapshot_type_of(baseline) == "quarter_hour")

    l1 = pick(
        lambda baseline: "signal_forward" in lower_label_of(baseline)
        and isinstance(baseline.get("layer1SignalEfficacy"), dict)
    )
    if l1 is None:
        l1 = pick(
            lambda baseline: ("_E1_" in label_of(baseline) or label_of(baseline).startswith("E1_"))
            and isinstance(baseline.get("layer1SignalEfficacy"), dict)
        )
    if l1 is None:
        l1 = pick(lambda baseline: isinstance(baseline.get("layer1SignalEfficacy"), dict))
    if l1 is None:
        l1 = h1

    return {
        "h1": h1,
        "h2": h2,
        "q1": q1,
        "l1": l1,
    }


def compute_checkpoint_layer2(baselines: list[dict[str, Any]]) -> dict[str, Any] | None:
    slots = select_longtest_baseline_slots(baselines)
    h1 = slots.get("h1")
    h2 = slots.get("h2")
    for baseline in (h1, h2):
        if isinstance(baseline, dict):
            layer2 = baseline.get("layer2ExecutionQuality")
            if isinstance(layer2, dict) and layer2.get("layer2Status"):
                return layer2
    if not isinstance(h1, dict) or not isinstance(h2, dict):
        return None
    if h1.get("totalReturn") is None or h2.get("totalReturn") is None:
        return None
    return compute_execution_quality(h1_summary=h1, h2_summary=h2)


def summarize_longtest_slot_label(baseline: dict[str, Any] | None) -> str | None:
    if not isinstance(baseline, dict):
        return None
    label = str(baseline.get("label") or "")
    if not label:
        return None
    if label.startswith("H1_"):
        return "H1"
    if label.startswith("H2_"):
        return "H2"
    if label.startswith("Q1_"):
        return "Q1"
    if "_E1_" in label or label.startswith("E1_"):
        return "E1"
    if "_E2_" in label or label.startswith("E2_"):
        return "E2"
    if "_E3_" in label or label.startswith("E3_"):
        return "E3"
    return label


def check_layer1_meltdown(
    history: list[dict[str, Any]],
    label_filter: str = "H1_half_hour_current_bar",
) -> dict[str, Any]:
    """Check if Layer 1 has been red for 3+ consecutive checkpoints (meltdown)."""
    if len(history) < 3:
        return {"meltdown": False, "consecutiveRedPeriods": 0, "diagnostics": "insufficient_history"}

    statuses: list[str] = []
    for record in history:
        baselines = record.get("baselines") or []
        baseline = next((b for b in baselines if b.get("label") == label_filter), None)
        if baseline is None:
            baseline = select_longtest_baseline_slots(baselines).get("l1")
        if not baseline:
            continue
        l1 = baseline.get("layer1SignalEfficacy") or {}
        statuses.append(str(l1.get("layer1Status") or "unknown"))

    consecutive_red = 0
    for status in reversed(statuses):
        if status == "red":
            consecutive_red += 1
        else:
            break

    return {
        "meltdown": consecutive_red >= 3,
        "consecutiveRedPeriods": consecutive_red,
        "statuses": statuses[-6:],
        "recommendation": (
            "触发策略结构性复审：连续 3 期方向精度不达标，建议检查市场状态归属、信号有效性和执行方式"
            if consecutive_red >= 3
            else None
        ),
    }


def check_layer3_trend(
    history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Check Layer 3 alignment trend across recent checkpoints."""
    if len(history) < 2:
        return {"greenLight": False, "diagnostics": "insufficient_history"}

    statuses: list[str] = []
    for record in history[-2:]:
        l3 = record.get("layer3Alignment") or {}
        statuses.append(str(l3.get("alignmentStatus") or "unknown"))

    consecutive_sufficient = all(s == "sufficient" for s in statuses)

    return {
        "greenLight": consecutive_sufficient,
        "recentStatuses": statuses,
        "recommendation": (
            "连续 2 期对齐充足，Layer 3 绿灯"
            if consecutive_sufficient
            else None
        ),
    }


class BacktestService:
    def __init__(self, session: Session | None):
        self.repo = create_repository(session)

    def _augment_low_hotlist_examples(
        self,
        dataset_id: str,
        examples: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for raw in examples:
            item = dict(raw)
            if item.get("snapshotId") and not item.get("captureMode"):
                frame = self.repo.get_snapshot_frame(str(item["snapshotId"]), dataset_id=dataset_id)
                if isinstance(frame, dict) and frame.get("captureMode"):
                    item["captureMode"] = frame.get("captureMode")
            output.append(item)
        return output

    @staticmethod
    def _normalize_quality_warnings(
        warnings: list[str],
        *,
        synthesized_empty_hotlist_count: int,
        raw_empty_hotlist_count: int,
        real_low_hotlist_count: int,
    ) -> list[str]:
        normalized: list[str] = []
        for warning in warnings:
            if (
                synthesized_empty_hotlist_count
                and raw_empty_hotlist_count == 0
                and (
                    warning.startswith("Empty hotlist snapshot:")
                    or ("个空热榜快照" in warning and "重新导入或剔除" in warning)
                )
            ):
                continue
            if (
                synthesized_empty_hotlist_count
                and real_low_hotlist_count == 0
                and "个低热榜快照" in warning
            ):
                continue
            normalized.append(warning)

        if synthesized_empty_hotlist_count:
            normalized.append(
                f"存在 {synthesized_empty_hotlist_count} 个 synthesized 补帧未生成热榜行，相关快照已在回测前剔除，并非原始热榜抓取为 0 行。"
            )

        return list(dict.fromkeys(normalized))

    def _normalize_data_quality(
        self,
        dataset_id: str,
        data_quality: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(data_quality)
        raw_layer2 = normalized.get("layer2ExecutionQuality")
        if not (isinstance(raw_layer2, dict) and raw_layer2.get("layer2Status")):
            normalized.pop("layer2ExecutionQuality", None)

        examples = normalized.get("lowHotlistExamples")
        if isinstance(examples, list):
            normalized_examples = self._augment_low_hotlist_examples(
                dataset_id,
                [item for item in examples if isinstance(item, dict)],
            )
            normalized["lowHotlistExamples"] = normalized_examples
            synthesized_count = sum(
                1
                for item in normalized_examples
                if item.get("stockRowCount") == 0 and item.get("captureMode") == "synthesized"
            )
            normalized.setdefault("synthesizedEmptyHotlistCount", synthesized_count)
            normalized.setdefault(
                "rawEmptyHotlistCount",
                max(0, int(normalized.get("emptyHotlistCount") or 0) - synthesized_count),
            )

        synthesized_empty_hotlist_count = int(normalized.get("synthesizedEmptyHotlistCount") or 0)
        raw_empty_hotlist_count = int(normalized.get("rawEmptyHotlistCount") or 0)
        real_low_hotlist_count = max(
            0,
            int(normalized.get("lowHotlistCount") or 0) - synthesized_empty_hotlist_count,
        )
        warnings = normalized.get("warnings")
        if isinstance(warnings, list):
            normalized["warnings"] = self._normalize_quality_warnings(
                [str(item) for item in warnings],
                synthesized_empty_hotlist_count=synthesized_empty_hotlist_count,
                raw_empty_hotlist_count=raw_empty_hotlist_count,
                real_low_hotlist_count=real_low_hotlist_count,
            )
        if (
            synthesized_empty_hotlist_count
            and raw_empty_hotlist_count == 0
            and str(normalized.get("recommendation") or "").startswith("可以用于候选观察")
        ):
            normalized["recommendation"] = (
                "可以用于候选观察，但需注意样本内存在 synthesized 补帧缺口；相关空热榜补帧已在回测前剔除。"
            )
        return normalized

    @staticmethod
    def _summary_response(run_id: str, result: dict[str, Any], metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        signals = result.get("signals") or []
        signal_count = int(result.get("signalCount") or len(signals))
        compact = BacktestService._compact_backtest_result(result, signal_count=signal_count)
        compact["signalCount"] = signal_count
        compact["isCompact"] = True
        compact["notes"] = [
            *(result.get("notes") or []),
            f"接口默认返回轻量摘要和前 120 条 signals 预览，完整压缩结果已落库：{run_id}",
        ]
        meta = metadata or {}
        return {"id": run_id, "runId": run_id, "run_id": run_id, **meta, "result": compact, **compact}

    @staticmethod
    def _compact_backtest_result(result: dict[str, Any], *, signal_count: int) -> dict[str, Any]:
        compact = {
            key: value
            for key, value in result.items()
            if key
            not in {
                "signals",
                "strategyDecisions",
                "tradeSimulation",
                "roundTripTrades",
                "trades",
                "tradeEvents",
                "equityCurve",
                "openPositions",
            }
        }

        signals = result.get("signals") if isinstance(result.get("signals"), list) else []
        compact["signals"] = [
            BacktestService._compact_signal_preview(signal)
            for signal in signals[:120]
            if isinstance(signal, dict)
        ]
        compact["signalPreviewCount"] = len(compact["signals"])
        compact["signalCount"] = signal_count

        for key in ("roundTripTrades", "trades", "tradeEvents", "equityCurve", "openPositions"):
            values = result.get(key)
            if isinstance(values, list):
                compact[key] = values[:120]

        simulation = result.get("tradeSimulation")
        if isinstance(simulation, dict):
            compact["tradeSimulation"] = BacktestService._compact_trade_simulation(simulation)

        decisions = result.get("strategyDecisions")
        if isinstance(decisions, dict):
            frame_results = decisions.get("frameResults") if isinstance(decisions.get("frameResults"), list) else []
            compact["strategyDecisions"] = {
                key: value
                for key, value in decisions.items()
                if key != "frameResults"
            }
            compact["strategyDecisions"]["frameResultCount"] = len(frame_results)
            compact["strategyDecisions"]["frameResults"] = [
                BacktestService._compact_strategy_frame(frame)
                for frame in frame_results[:20]
                if isinstance(frame, dict)
            ]

        return compact

    @staticmethod
    def _compact_signal_preview(signal: dict[str, Any]) -> dict[str, Any]:
        rank_trend = signal.get("rankTrend") if isinstance(signal.get("rankTrend"), dict) else {}
        decision = rank_trend.get("decision") if isinstance(rank_trend.get("decision"), dict) else {}
        final = decision.get("final") if isinstance(decision.get("final"), dict) else {}
        technical = rank_trend.get("technical") if isinstance(rank_trend.get("technical"), dict) else {}
        momentum = technical.get("momentumProfile") if isinstance(technical.get("momentumProfile"), dict) else {}
        return {
            "snapshotId": signal.get("snapshotId"),
            "tradingDate": signal.get("tradingDate"),
            "slotTime": signal.get("slotTime"),
            "code": signal.get("code"),
            "name": signal.get("name"),
            "rank": signal.get("rank"),
            "price": signal.get("price"),
            "candidateTier": signal.get("candidateTier"),
            "action": signal.get("action"),
            "signal": signal.get("signal") or final.get("signal"),
            "finalSignal": final.get("signal"),
            "confidence": signal.get("confidence"),
            "stage": signal.get("stage"),
            "regime": signal.get("regime"),
            "score": signal.get("score"),
            "technicalSignals": technical.get("signals"),
            "momentumProfile": momentum,
            "risk": rank_trend.get("risk"),
            "momentum": momentum.get("momentum"),
            "acceleration": momentum.get("acceleration"),
            "riskFlags": signal.get("riskFlags") or [],
            "reasons": signal.get("reasons") or [],
            "mainTheme": signal.get("mainTheme"),
            "themeRole": signal.get("themeRole"),
        }

    @staticmethod
    def _compact_trade_simulation(simulation: dict[str, Any]) -> dict[str, Any]:
        compact = {
            key: value
            for key, value in simulation.items()
            if key not in {"roundTripTrades", "trades", "tradeEvents", "equityHistory", "equityCurve", "openPositions"}
        }
        for key in ("roundTripTrades", "trades", "tradeEvents", "equityHistory", "equityCurve", "openPositions"):
            values = simulation.get(key)
            if isinstance(values, list):
                compact[key] = values[:120]
                compact[f"{key}Count"] = len(values)
        return compact

    @staticmethod
    def _compact_strategy_frame(frame: dict[str, Any]) -> dict[str, Any]:
        return {
            "snapshotId": frame.get("snapshotId"),
            "tradingDate": frame.get("tradingDate"),
            "slotTime": frame.get("slotTime"),
            "buyCandidateCount": len(frame.get("buyCandidates") or []),
            "watchCandidateCount": len(frame.get("watchCandidates") or []),
            "excludedCandidateCount": len(frame.get("excludedCandidates") or []),
            "buyCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("buyCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
            "watchCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("watchCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
            "excludedCandidates": [
                BacktestService._compact_decision_preview(item)
                for item in (frame.get("excludedCandidates") or [])[:20]
                if isinstance(item, dict)
            ],
        }

    @staticmethod
    def _compact_decision_preview(item: dict[str, Any]) -> dict[str, Any]:
        return {
            "code": item.get("code"),
            "name": item.get("name"),
            "rank": item.get("rank"),
            "signal": item.get("signal"),
            "candidateTier": item.get("candidateTier"),
            "confidence": item.get("confidence"),
            "stage": item.get("stage"),
            "regime": item.get("regime"),
            "reason": item.get("reason") or item.get("explanation"),
        }

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
        a_share_codes = _load_a_share_codes(self.repo)
        report_only_diagnostics = (
            quality_gate.get("reportOnlyDiagnostics")
            if isinstance(quality_gate.get("reportOnlyDiagnostics"), dict)
            else {}
        )
        report_only_diagnostics = dict(report_only_diagnostics)
        report_only_diagnostics["priceQuality"] = _price_quality_diagnostics(run_frames, a_share_codes)
        quality_gate["reportOnlyDiagnostics"] = report_only_diagnostics
        exclude_non_positive_price_rows = bool(camel_get(payload, "exclude_non_positive_price_rows", "excludeNonPositivePriceRows", False))
        exclude_cross_market_zero_price_rows = bool(camel_get(payload, "exclude_cross_market_zero_price_rows", "excludeCrossMarketZeroPriceRows", False))
        exclude_all_zero_price_frames = bool(camel_get(payload, "exclude_all_zero_price_frames", "excludeAllZeroPriceFrames", False))
        price_filter: dict[str, Any] | None = None
        cross_market_price_filter: dict[str, Any] | None = None
        all_zero_frame_filter: dict[str, Any] | None = None
        runtime_filter = quality_gate.get("runtimeFilter") if isinstance(quality_gate.get("runtimeFilter"), dict) else {}
        runtime_filter = dict(runtime_filter)
        if exclude_all_zero_price_frames:
            run_frames, all_zero_frame_filter = _drop_all_zero_price_frames(run_frames)
            runtime_filter["allZeroPriceFrameFilter"] = all_zero_frame_filter
        if exclude_cross_market_zero_price_rows:
            run_frames, cross_market_price_filter = _cross_market_zero_price_stock_rows(
                run_frames,
                a_share_codes,
            )
            runtime_filter["crossMarketPriceFilter"] = cross_market_price_filter
        if exclude_non_positive_price_rows:
            run_frames, price_filter = _positive_price_stock_rows(run_frames)
            runtime_filter["priceFilter"] = price_filter
        if runtime_filter:
            quality_gate["runtimeFilter"] = runtime_filter
        if exclude_all_zero_price_frames or exclude_cross_market_zero_price_rows or exclude_non_positive_price_rows:
            _ensure_runtime_filtered_frames_usable(run_frames, quality_gate)

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
            "snapshot_type": snapshot_type,
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "quality_gate": quality_gate,
            "research_filters": {
                "excludeNonPositivePriceRows": exclude_non_positive_price_rows,
                "excludeCrossMarketZeroPriceRows": exclude_cross_market_zero_price_rows,
                "excludeAllZeroPriceFrames": exclude_all_zero_price_frames,
                "priceFilter": price_filter,
                "crossMarketPriceFilter": cross_market_price_filter,
                "allZeroPriceFrameFilter": all_zero_frame_filter,
            },
        }
        result = BacktestEngine().run(run_frames, options)

        # Layer 1: signal efficacy (computed from backtest signals)
        layer_1_efficacy = compute_signal_efficacy(
            signals=result.get("signals") or [],
            frames=run_frames,
        )
        quality_gate["layer1SignalEfficacy"] = layer_1_efficacy
        if isinstance(result.get("dataQuality"), dict):
            result["dataQuality"]["layer1SignalEfficacy"] = layer_1_efficacy
            result["dataQuality"] = self._normalize_data_quality(dataset_id, result["dataQuality"])
            result["warnings"] = list(result["dataQuality"].get("warnings") or [])

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "random_seed": int(camel_get(payload, "random_seed", "randomSeed", 20260430)),
            "strategy_name": strategy_name,
            "strategy_config": strategy_config,
            "trade_config": trade_config,
            "research_filters": options["research_filters"],
        }
        trading_dates = sorted({str(f.get("tradingDate") or "") for f in run_frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=request_meta["random_seed"],
            status="completed",
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

    def run_theme_trend(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "theme_rotation"))
        from backend.core.backtest.strategy import THEME_STRATEGY_NAMES
        if strategy_name not in THEME_STRATEGY_NAMES:
            raise ValueError(f"unsupported theme strategy: {strategy_name}")
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))

        frames = self.repo.load_frame_bundles(
            dataset_id, snapshot_type=snapshot_type,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")


        engine_config = {
            "crowdedRiskThreshold": int(camel_get(payload, "crowdingBlockThreshold", "crowdingBlockThreshold", 75)),
            "minFrames": 2,
        }
        config = ThemeTrendConfig.from_patch(engine_config)
        theme_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config)

        quality_report = theme_result.get("qualityReport", {})
        factors = theme_result.get("factors", [])
        signals = theme_result.get("signals", [])
        exposures = theme_result.get("exposures", [])
        execution_signals = self._theme_execution_signals(frames, factors, exposures, strategy_name)
        trade_config = self._theme_trade_config(payload, strategy_name)
        trade_simulation = (
            TradeSimulator().run(frames, execution_signals, trade_config)
            if bool(camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True))
            else {"enabled": False, "trades": [], "equityCurve": []}
        )

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "strategy_name": strategy_name,
            "random_seed": random_seed,
            "engine_config": engine_config,
            "trade_config": trade_config,
        }

        result: dict[str, Any] = {
            "strategyName": strategy_name,
            "analysisMode": "theme_trend",
            "themeTrend": {
                "factorVersion": "theme-factor-v12",
                "signalVersion": "theme-signal-v12",
                "factorCount": len(factors),
                "exposureCount": len(exposures),
                "signalCount": len(signals),
                "factors": factors[:120],
                "signals": signals[:120],
                "exposures": exposures[:120],
                "executionSignalCount": len(execution_signals),
                "tradeSimulation": {
                    "enabled": bool(trade_simulation.get("enabled", False)),
                    "tradeCount": int(trade_simulation.get("tradeCount") or 0),
                    "equityCount": len(trade_simulation.get("equityCurve") or []),
                },
            },
            "signals": signals,
            "signalCount": len(signals),
            "executionSignals": execution_signals[:120],
            "tradeSimulation": trade_simulation,
            "totalReturn": trade_simulation.get("totalReturn"),
            "realizedReturn": trade_simulation.get("realizedReturn"),
            "maxDrawdown": trade_simulation.get("maxDrawdown"),
            "winRate": trade_simulation.get("winRate"),
            "tradeCount": trade_simulation.get("tradeCount"),
            "trades": trade_simulation.get("trades") or [],
            "equityCurve": trade_simulation.get("equityCurve") or [],
            "dataQuality": {
                "passed": not quality_report.get("blocked", False),
                "researchGrade": "degraded" if quality_report.get("warnings") else "research_ready",
                "frameCount": quality_report.get("frameCount", 0),
                "warnings": quality_report.get("warnings", []),
            },
        }

        trading_dates = sorted({str(f.get("tradingDate") or "") for f in frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=random_seed,
            status="completed",
            config_hash=stable_hash(request_meta),
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)

        if signals:
            signal_rows = [
                {
                    "snapshotId": s.get("snapshotId", ""),
                    "tradingDate": s.get("tradingDate", ""),
                    "code": "",
                    "name": s.get("themeName", ""),
                    "candidateTier": s.get("lifecycle", ""),
                    "signal": s.get("signal", "watch"),
                    "confidence": s.get("score", 0.0),
                    "rank": 0,
                    "reasons": [f"theme_lifecycle:{s.get('lifecycle', '')}"],
                    "riskFlags": [s.get("risk", "")] if s.get("risk") != "none" else [],
                    "mainTheme": s.get("themeName", ""),
                    "themeHeat": 0.0,
                    "themeContribution": 0.0,
                    "themeRole": "",
                    "themeSupportScore": s.get("score", 0.0),
                    "themeRiskFlags": [],
                    "themeReasons": [f"lifecycle:{s.get('lifecycle', '')}"],
                }
                for s in signals
            ]
            self.repo.save_backtest_signal_rows(run_id, signal_rows)

        self.repo.save_backtest_trades(run_id, trade_simulation.get("trades") or [])
        self.repo.save_backtest_equity_curve(run_id, trade_simulation.get("equityCurve") or [])
        self.repo.save_backtest_quality_report(
            run_id, result.get("dataQuality", {}), quality_report,
        )

        return self._summary_response(
            run_id, result,
            {
                "datasetId": dataset_id,
                "dataset_id": dataset_id,
                "strategyName": strategy_name,
                "snapshotType": snapshot_type,
                "randomSeed": random_seed,
                "configHash": run.config_hash,
            },
        )

    def run_theme_confluence(self, payload: dict[str, Any]) -> dict[str, Any]:
        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"))
        from backend.core.backtest.strategy import THEME_STRATEGY_NAMES
        if strategy_name not in THEME_STRATEGY_NAMES:
            raise ValueError(f"unsupported confluence strategy: {strategy_name}")
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))

        frames = self.repo.load_frame_bundles(
            dataset_id, snapshot_type=snapshot_type,
        )
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")


        config = ThemeTrendConfig.from_patch(
            {
                "crowdedRiskThreshold": int(camel_get(payload, "maxThemeCrowding", "maxThemeCrowding", 85)),
                "minFrames": 2,
            }
        )
        theme_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config)

        rank_trend_control: dict[str, Any] = {}
        rank_frames: list[dict[str, Any]] = []
        rank_signals: list[dict[str, Any]] = []
        try:
            rank_frames = self.repo.load_frames(
                dataset_id, snapshot_type=snapshot_type, include_payload=True,
            )
            if rank_frames:
                rank_config = RankTrendConfig()
                rank_signals = RankTrendPythonEngine(rank_config).replay(rank_frames)
                rank_trend_control = {
                    "signalCount": len(rank_signals),
                    "description": "RankTrend-only 控制组基线",
                }
        except Exception as exc:
            rank_trend_control = {
                "error": "RankTrend control baseline unavailable",
                "reason": str(exc)[:200],
            }

        run_id = new_id("bt")
        request_meta = {
            **payload,
            "dataset_id": dataset_id,
            "snapshot_type": snapshot_type,
            "strategy_name": strategy_name,
            "random_seed": random_seed,
        }

        quality_report = theme_result.get("qualityReport", {})
        signals = theme_result.get("signals", [])
        factors = theme_result.get("factors", [])
        exposures = theme_result.get("exposures", [])
        execution_frames = rank_frames or frames
        execution_signals = self._confluence_execution_signals(rank_signals, factors, exposures)
        trade_config = self._theme_trade_config(payload, strategy_name)
        trade_simulation = (
            TradeSimulator().run(execution_frames, execution_signals, trade_config)
            if bool(camel_get(payload, "enable_trade_simulation", "enableTradeSimulation", True))
            else {"enabled": False, "trades": [], "equityCurve": []}
        )
        result: dict[str, Any] = {
            "strategyName": strategy_name,
            "analysisMode": "theme_confluence",
            "themeTrend": {
                "factorVersion": "theme-factor-v12",
                "signalVersion": "theme-signal-v12",
                "signals": signals[:120],
                "signalCount": len(signals),
                "executionSignalCount": len(execution_signals),
                "rankTrendControl": rank_trend_control,
                "tradeSimulation": {
                    "enabled": bool(trade_simulation.get("enabled", False)),
                    "tradeCount": int(trade_simulation.get("tradeCount") or 0),
                    "equityCount": len(trade_simulation.get("equityCurve") or []),
                },
            },
            "signals": signals,
            "signalCount": len(signals),
            "executionSignals": execution_signals[:120],
            "tradeSimulation": trade_simulation,
            "totalReturn": trade_simulation.get("totalReturn"),
            "realizedReturn": trade_simulation.get("realizedReturn"),
            "maxDrawdown": trade_simulation.get("maxDrawdown"),
            "winRate": trade_simulation.get("winRate"),
            "tradeCount": trade_simulation.get("tradeCount"),
            "trades": trade_simulation.get("trades") or [],
            "equityCurve": trade_simulation.get("equityCurve") or [],
            "dataQuality": {
                "passed": not quality_report.get("blocked", False),
                "researchGrade": "degraded" if quality_report.get("warnings") else "research_ready",
                "warnings": quality_report.get("warnings", []),
            },
            "isCompact": True,
            "notes": [f"共振策略：RankTrend 候选为主，ThemeTrend 辅助排序/拥挤降级。完整结果已落库：{run_id}"],
        }

        trading_dates = sorted({str(f.get("tradingDate") or "") for f in frames if f.get("tradingDate")})
        run = BacktestRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            snapshot_type=snapshot_type,
            random_seed=random_seed,
            status="completed",
            config_hash=stable_hash(request_meta),
            date_start=trading_dates[0] if trading_dates else None,
            date_end=trading_dates[-1] if trading_dates else None,
            request_json=dumps_json_field(request_meta),
            result_json=dumps_json_field(result),
        )
        self.repo.save_backtest_run(run)
        if signals:
            signal_rows = [
                {
                    "snapshotId": s.get("snapshotId", ""),
                    "tradingDate": s.get("tradingDate", ""),
                    "code": "",
                    "name": s.get("themeName", ""),
                    "candidateTier": s.get("lifecycle", ""),
                    "signal": s.get("signal", "watch"),
                    "confidence": s.get("score", 0.0),
                    "rank": 0,
                    "reasons": [f"confluence:{s.get('lifecycle', '')}"],
                    "riskFlags": [s.get("risk", "")] if s.get("risk") != "none" else [],
                    "mainTheme": s.get("themeName", ""),
                    "themeHeat": 0.0,
                    "themeContribution": 0.0,
                    "themeRole": "",
                    "themeSupportScore": s.get("score", 0.0),
                    "themeRiskFlags": [],
                    "themeReasons": [f"confluence_lifecycle:{s.get('lifecycle', '')}"],
                }
                for s in signals
            ]
            self.repo.save_backtest_signal_rows(run_id, signal_rows)
        self.repo.save_backtest_trades(run_id, trade_simulation.get("trades") or [])
        self.repo.save_backtest_equity_curve(run_id, trade_simulation.get("equityCurve") or [])
        self.repo.save_backtest_quality_report(
            run_id, result.get("dataQuality", {}), quality_report,
        )

        return self._summary_response(
            run_id, result,
            {
                "datasetId": dataset_id,
                "dataset_id": dataset_id,
                "strategyName": strategy_name,
                "snapshotType": snapshot_type,
                "randomSeed": random_seed,
                "configHash": run.config_hash,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        result = loads_json_field(run.result_json, {})
        data_quality = result.get("dataQuality")
        if isinstance(data_quality, dict):
            result["dataQuality"] = self._normalize_data_quality(run.dataset_id, data_quality)
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
        source = storage_source_label()
        total = self.repo.count_backtest_trades(run_id)
        if source == "sqlite" and not items and total == 0:
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
        source = storage_source_label()
        if source == "sqlite" and not items:
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
        source = storage_source_label()
        if source == "sqlite" and not items and total == 0:
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
        run = self.repo.get_backtest_run(run_id)
        if not run:
            return None
        quality = self.repo.get_backtest_quality_report(run_id)
        if quality is None:
            return {"runId": run_id, "qualityReport": None}
        result = loads_json_field(run.result_json, {})
        data_quality = result.get("dataQuality") if isinstance(result.get("dataQuality"), dict) else {}
        normalized_quality = dict(quality)
        if data_quality:
            normalized_data_quality = self._normalize_data_quality(run.dataset_id, data_quality)
            warnings = normalized_data_quality.get("warnings")
            if isinstance(warnings, list):
                normalized_quality["warnings"] = warnings
        dataset = self.repo.get_dataset(run.dataset_id)
        if dataset is not None:
            if not int(normalized_quality.get("stockCount") or 0):
                normalized_quality["stockCount"] = int(dataset.stock_row_count or 0)
            if not int(normalized_quality.get("sectorCount") or 0):
                normalized_quality["sectorCount"] = int(dataset.sector_row_count or 0)
        return {"runId": run_id, "qualityReport": normalized_quality}

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

    @staticmethod
    def _theme_trade_config(payload: dict[str, Any], strategy_name: str) -> dict[str, Any]:
        patch = camel_get(payload, "trade_config", "tradeConfig", {}) or {}
        config = {
            "initialCapital": camel_get(payload, "initial_cash", "initialCash", 1000000),
            "maxPositions": camel_get(payload, "max_positions", "maxPositions", 5),
            "positionSize": camel_get(payload, "position_size", "positionSize", 0.2),
            "takeProfit": camel_get(payload, "take_profit_pct", "takeProfitPct", 0.12),
            "stopLoss": -abs(float(camel_get(payload, "stop_loss_pct", "stopLossPct", 0.06))),
            "maxHoldingBars": camel_get(payload, "max_holding_bars", "maxHoldingBars", 40),
            "targetHoldingDays": camel_get(payload, "target_holding_days", "targetHoldingDays", 5),
            "maxThemeExposure": camel_get(payload, "max_theme_exposure", "maxThemeExposure", 0.45),
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
        config.update(patch)
        config["entryStrategy"] = strategy_name
        return config

    @staticmethod
    def _theme_execution_signals(
        frames: list[dict[str, Any]],
        factors: list[dict[str, Any]],
        exposures: list[dict[str, Any]],
        strategy_name: str,
    ) -> list[dict[str, Any]]:
        factor_by_snapshot_theme = {
            (str(factor.get("snapshotId") or ""), str(factor.get("themeName") or "")): factor
            for factor in factors
        }
        exposure_by_snapshot_code = {
            (str(exposure.get("snapshotId") or ""), str(exposure.get("code") or "")): exposure
            for exposure in exposures
            if exposure.get("code")
        }
        output: list[dict[str, Any]] = []
        for frame in frames:
            snapshot_id = str(frame.get("snapshotId") or "")
            for stock in frame.get("stocks") or frame.get("rows") or frame.get("hotlist") or []:
                if not isinstance(stock, dict):
                    continue
                code = str(stock.get("code") or "")
                if not code:
                    continue
                exposure = exposure_by_snapshot_code.get((snapshot_id, code))
                theme_name = str((exposure or {}).get("themeName") or stock.get("mainTheme") or "")
                factor = factor_by_snapshot_theme.get((snapshot_id, theme_name), {})
                lifecycle = str(factor.get("lifecycle") or "neutral")
                crowding = float(factor.get("crowdingRisk") or 0)
                contribution = float((exposure or {}).get("themeContribution") or stock.get("themeContribution") or 0)
                exposure_weight = float((exposure or {}).get("exposureWeight") or stock.get("themeExposureWeight") or 0)
                tier = "N_NEUTRAL"
                if lifecycle in {"mainline", "expansion"} and crowding < 75 and (exposure_weight >= 55 or contribution >= 8):
                    tier = "A_MAIN"
                elif lifecycle == "ignition" and crowding < 75:
                    tier = "B_IGNITION"
                elif lifecycle in {"crowded", "divergence"} or crowding >= 75:
                    tier = "C_CROWDED"
                elif lifecycle in {"cooling", "reversal"}:
                    tier = "D_EXIT_RISK"
                role = str((exposure or {}).get("role") or stock.get("themeRole") or "")
                confidence = min(100.0, max(0.0, exposure_weight or float(factor.get("heatScore") or 0)))
                theme_risk_flags = [f"crowding:{crowding}"] if crowding >= 75 else []
                theme_reasons = [f"lifecycle:{lifecycle}", f"strategy:{strategy_name}"]
                confluence_score = round(
                    min(100.0, max(0.0, float(factor.get("heatScore") or 0) * 0.45 + exposure_weight * 0.35 + contribution * 0.8)),
                    2,
                )
                if strategy_name == "leader_theme_confirmation":
                    if role == "leader" and tier in {"A_MAIN", "B_IGNITION"} and crowding < 75:
                        theme_reasons.append("leader_confirmation")
                        confidence = min(100.0, confidence + 6.0)
                    else:
                        tier = "D_EXIT_RISK" if lifecycle in {"cooling", "reversal"} or crowding >= 75 else "N_NEUTRAL"
                        theme_risk_flags.append("leader_required")
                        theme_reasons.append("leader_downgraded_to_watch")
                elif strategy_name == "hotlist_theme_confluence":
                    if confluence_score >= 75 and tier in {"A_MAIN", "B_IGNITION"} and crowding < 75:
                        theme_reasons.append("hotlist_confluence")
                        confidence = min(100.0, max(confidence, confluence_score))
                    elif confluence_score < 45 or role == "noise":
                        tier = "N_NEUTRAL"
                        theme_risk_flags.append("theme_noise_or_weak_confluence")
                        theme_reasons.append("hotlist_filtered")
                else:
                    theme_reasons.append("theme_rotation")
                output.append({
                    **stock,
                    "snapshotId": snapshot_id,
                    "timestamp": frame.get("timestamp"),
                    "tradingDate": frame.get("tradingDate"),
                    "slotTime": frame.get("slotTime"),
                    "code": code,
                    "name": stock.get("name") or code,
                    "rank": int(stock.get("rank") or 999),
                    "candidateTier": tier,
                    "regime": "strong" if tier in {"A_MAIN", "B_IGNITION"} else "weak",
                    "confidence": confidence,
                    "stage": lifecycle,
                    "rankTrend": {"strategy": {"momentum": {"acceleration": 1 if tier != "D_EXIT_RISK" else -1}}},
                    "mainTheme": theme_name,
                    "themeHeat": float(factor.get("heatScore") or stock.get("themeHeat") or 0),
                    "themeContribution": contribution,
                    "themeRole": role,
                    "themeSupportScore": exposure_weight,
                    "themeConfluenceScore": confluence_score,
                    "themeRiskFlags": theme_risk_flags,
                    "themeReasons": theme_reasons,
                })
        return output

    @staticmethod
    def _confluence_execution_signals(
        rank_signals: list[dict[str, Any]],
        factors: list[dict[str, Any]],
        exposures: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        factor_by_snapshot_theme = {
            (str(factor.get("snapshotId") or ""), str(factor.get("themeName") or "")): factor
            for factor in factors
        }
        exposure_by_snapshot_code = {
            (str(exposure.get("snapshotId") or ""), str(exposure.get("code") or "")): exposure
            for exposure in exposures
            if exposure.get("code")
        }
        output: list[dict[str, Any]] = []
        for signal in rank_signals:
            snapshot_id = str(signal.get("snapshotId") or "")
            code = str(signal.get("code") or "")
            exposure = exposure_by_snapshot_code.get((snapshot_id, code))
            theme_name = str((exposure or {}).get("themeName") or signal.get("mainTheme") or "")
            factor = factor_by_snapshot_theme.get((snapshot_id, theme_name), {})
            lifecycle = str(factor.get("lifecycle") or "neutral")
            crowding = float(factor.get("crowdingRisk") or 0)
            item = dict(signal)
            item["mainTheme"] = theme_name
            item["themeHeat"] = float(factor.get("heatScore") or signal.get("themeHeat") or 0)
            item["themeContribution"] = float((exposure or {}).get("themeContribution") or signal.get("themeContribution") or 0)
            item["themeRole"] = (exposure or {}).get("role") or signal.get("themeRole") or ""
            item["themeSupportScore"] = float((exposure or {}).get("exposureWeight") or signal.get("themeSupportScore") or 0)
            item["themeReasons"] = [*([str(v) for v in signal.get("themeReasons") or []]), f"theme_lifecycle:{lifecycle}"]
            item["themeRiskFlags"] = [*([str(v) for v in signal.get("themeRiskFlags") or []])]
            if lifecycle in {"cooling", "reversal"} or crowding >= 75:
                item["candidateTier"] = "D_EXIT_RISK"
                item["regime"] = "retreat"
                item["themeRiskFlags"].append("theme_blocked")
            elif lifecycle in {"mainline", "expansion", "ignition"} and item.get("candidateTier") in {"A_MAIN", "B_IGNITION"}:
                item["confidence"] = min(100.0, float(item.get("confidence") or 0) + 5.0)
            output.append(item)
        return output

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
        self.repo = create_repository(session)

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

    def run_theme_trend(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        """执行题材趋势策略参数优化（grid/random 搜索）。

        wait 参数保留用于与 run_ranktrend 接口对齐；当前 MVP 始终同步执行。
        后续可扩展异步路径。
        """
        from backend.optimization.search_space import (
            theme_confluence_search_space,
            theme_parameter_groups,
            theme_search_space,
            normalize_search_space,
            select_candidates,
        )
        from backend.optimization.objective import score_theme_trend

        dataset_id = str(camel_get(payload, "dataset_id", "datasetId", ""))
        snapshot_type = str(camel_get(payload, "snapshot_type", "snapshotType", "half_hour"))
        strategy_name = str(camel_get(payload, "strategy_name", "strategyName", "theme_rotation"))
        search_profile = str(camel_get(payload, "search_profile", "searchProfile", "theme_trend"))
        method = str(camel_get(payload, "method", default="random"))
        objective = str(camel_get(payload, "objective", default="stability"))
        random_seed = int(camel_get(payload, "random_seed", "randomSeed", 20260430))
        max_trials = max(1, int(camel_get(payload, "trials", default=12)))

        frames = self.repo.load_frame_bundles(dataset_id, snapshot_type=snapshot_type)
        if not frames:
            raise ValueError(f"dataset has no frames for {snapshot_type}: {dataset_id}")

        param_grid_input = camel_get(payload, "parameter_grid", "parameterGrid", {}) or {}
        search_space = normalize_search_space(
            param_grid_input
            if param_grid_input
            else (theme_confluence_search_space() if search_profile == "theme_confluence" else theme_search_space())
        )

        run_id = new_id("opt")
        config_hash = stable_hash({k: v for k, v in payload.items() if k != "parameterGrid"})

        trial_results: list[dict[str, Any]] = []
        total_candidates = candidate_count(search_space)
        trial_params_list = select_candidates(search_space, max_trials, method, random_seed)

        trial_errors: list[dict[str, Any]] = []
        for trial_idx, trial_params in enumerate(trial_params_list):
            try:
                config = ThemeTrendConfig.from_patch({
                    k: v for k, v in trial_params.items()
                })
                engine_result = ThemeTrendPythonEngine().replay_sequence(frames, config=config)
                score = score_theme_trend(engine_result, objective)
                trial_results.append({
                    "trialId": trial_idx,
                    "params": {k: v for k, v in trial_params.items()},
                    "score": score,
                    "themeCount": len(engine_result.get("factors", [])),
                    "mainlineCount": sum(1 for f in engine_result.get("factors", []) if f.get("lifecycle") == "mainline"),
                    "engineFactors": engine_result.get("factors", [])[:50],
                })
            except Exception as exc:
                trial_errors.append({
                    "trialId": trial_idx,
                    "params": {k: v for k, v in trial_params.items()},
                    "error": str(exc)[:200],
                })

        trial_results.sort(key=lambda t: t["score"], reverse=True)
        best = trial_results[0] if trial_results else {}

        result_payload = {
            "runId": run_id,
            "method": method,
            "objective": objective,
            "searchProfile": search_profile,
            "supportedParameterGroups": theme_parameter_groups(search_profile),
            "candidateCount": total_candidates,
            "trials": len(trial_results),
            "trialErrors": trial_errors,
            "best": best,
            "trialList": trial_results[:50],
        }

        opt_run = OptimizationRun(
            id=run_id,
            dataset_id=dataset_id,
            strategy_name=strategy_name,
            method=method,
            random_seed=random_seed,
            status="completed" if trial_results else "failed",
            config_hash=config_hash,
            request_json=dumps_json_field(payload),
            result_json=dumps_json_field(result_payload),
        )
        self.repo.save_optimization_run(opt_run)

        return {
            "id": run_id,
            "runId": run_id,
            "status": opt_run.status,
            "method": method,
            "strategyName": strategy_name,
            "analysisMode": "theme_trend",
            "searchProfile": search_profile,
            "supportedParameterGroups": theme_parameter_groups(search_profile),
            "candidateCount": total_candidates,
            "randomSeed": random_seed,
            "best": best,
            "trialCount": len(trial_results),
        }

    def run_theme_confluence(self, payload: dict[str, Any], wait: bool = False) -> dict[str, Any]:
        request = {
            **payload,
            "strategy_name": camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"),
            "strategyName": camel_get(payload, "strategy_name", "strategyName", "hotlist_theme_confluence"),
            "search_profile": "theme_confluence",
            "searchProfile": "theme_confluence",
        }
        result = self.run_theme_trend(request, wait=wait)
        result["analysisMode"] = "theme_confluence"
        result["strategyName"] = str(request["strategyName"])
        result["searchProfile"] = "theme_confluence"
        return result

    def run_ranktrend_jump_research(self, payload: dict[str, Any]) -> dict[str, Any]:
        research_payload = build_jump_research_request(payload)
        dataset_id, snapshot_type, strategy_name, run_frames, request, payload_for_request_json = self._build_request(research_payload)
        if ((request.get("quality_gate") or {}).get("researchGrade")) == "blocked":
            raise ValueError({"qualityGate": request.get("quality_gate"), "reason": "data quality blocked jump research"})
        run_id = str(request["optimization_run_id"])
        config_hash = stable_hash({key: value for key, value in request.items() if key != "optimization_run_id"})
        result = OptimizationRunner().run(run_frames, request)
        summary = summarize_jump_research(
            result,
            fill_fallback_mode=str((research_payload.get("backtest") or {}).get("trade_config", {}).get("fillFallbackMode") or "fallback_penalized"),
        )
        backtest_artifacts = result.pop("backtestArtifacts", []) or []
        for artifact in backtest_artifacts:
            artifact_request = {
                **(artifact.get("request") or {}),
                "artifact_type": "ranktrend_jump_research_trial",
                "artifactType": "ranktrend_jump_research_trial",
            }
            self.repo.save_backtest_run(
                BacktestRun(
                    id=str(artifact.get("runId")),
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    snapshot_type=snapshot_type,
                    random_seed=request["random_seed"],
                    status="completed",
                    config_hash=str(artifact.get("configHash") or stable_hash(artifact_request)),
                    request_json=dumps_json_field(artifact_request),
                    result_json=dumps_json_field(artifact.get("result") or {}),
                )
            )
        result["researchSummary"] = summary
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
        return {
            "id": run_id,
            "runId": run_id,
            "run_id": run_id,
            "status": "completed",
            "analysisMode": "ranktrend_jump_research",
            "strategyName": strategy_name,
            "method": request["method"],
            "randomSeed": request["random_seed"],
            "configHash": config_hash,
            "summary": summary,
            "result": result,
            **result,
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
            artifact_request = {
                **(artifact.get("request") or {}),
                "artifact_type": "optimization_trial",
                "artifactType": "optimization_trial",
            }
            artifact_result = artifact.get("result") or {}
            self.repo.save_backtest_run(
                BacktestRun(
                    id=str(artifact.get("runId")),
                    dataset_id=dataset_id,
                    strategy_name=strategy_name,
                    snapshot_type=snapshot_type,
                    random_seed=request["random_seed"],
                    status="completed",
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
